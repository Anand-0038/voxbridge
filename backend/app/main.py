"""
VoxBridge - FastAPI Application Entry Point

Responsible AI-Powered Multilingual Video Dubbing Platform
"""

import asyncio
import os
import shutil
import time
from collections import OrderedDict
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.routes import router
from app.services.audit_service import init_database
from app.services.media_service import has_rubberband_support
from app.utils.database import close_db_pool, get_pool, init_db_pool
from app.utils.helpers import decode_json_object

# Load environment variables
load_dotenv()

# Configuration from environment
# FORCE ABSOLUTE PATHS to prevent "file not found" errors when running from different dirs
BASE_DIR = Path(__file__).resolve().parent.parent

# Update env vars with absolute paths so other services see them
os.environ["UPLOAD_DIR"] = str(BASE_DIR / os.getenv("UPLOAD_DIR", "storage/uploads"))
os.environ["PROCESSED_DIR"] = str(BASE_DIR / os.getenv("PROCESSED_DIR", "storage/processed"))
os.environ["OUTPUT_DIR"] = str(BASE_DIR / os.getenv("OUTPUT_DIR", "storage/outputs"))

MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500")) * 1024 * 1024
RATE_LIMIT_UPLOADS = int(os.getenv("RATE_LIMIT_UPLOADS", "10"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
RATE_LIMIT_MAX_CLIENTS = max(1, int(os.getenv("RATE_LIMIT_MAX_CLIENTS", "10000")))


class LimitUploadSizeMiddleware(BaseHTTPMiddleware):
    """Middleware to limit upload size and provide better error messages."""
    
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and "upload" in request.url.path:
            content_length = request.headers.get("content-length")
            if content_length:
                content_length = int(content_length)
                if content_length > MAX_UPLOAD_SIZE:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024*1024)}MB",
                            "max_size_mb": MAX_UPLOAD_SIZE // (1024*1024),
                            "your_size_mb": content_length // (1024*1024)
                        }
                    )
        return await call_next(request)


# Bounded in-memory rate limiting. Entries are pruned on every upload request
# and the oldest client is evicted if the configured bound is reached.
upload_requests: OrderedDict[str, list[float]] = OrderedDict()


def _prune_rate_limit_entries(current_time: float) -> None:
    """Remove expired client timestamps and prevent unbounded client growth."""
    for client_ip, timestamps in list(upload_requests.items()):
        active_timestamps = [
            timestamp
            for timestamp in timestamps
            if current_time - timestamp < RATE_LIMIT_WINDOW
        ]
        if active_timestamps:
            upload_requests[client_ip] = active_timestamps
        else:
            upload_requests.pop(client_ip, None)

    while len(upload_requests) > RATE_LIMIT_MAX_CLIENTS:
        upload_requests.popitem(last=False)


async def _rate_limit_cleanup_loop() -> None:
    """Expire abandoned client entries even when no new uploads arrive."""
    interval = max(1.0, min(float(RATE_LIMIT_WINDOW), 60.0))
    while True:
        await asyncio.sleep(interval)
        _prune_rate_limit_entries(time.time())


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple rate limiting to protect demo from abuse."""
    
    async def dispatch(self, request: Request, call_next):
        if request.method == "POST" and "upload" in request.url.path:
            client_ip = request.client.host if request.client else "unknown"
            current_time = time.time()
            
            _prune_rate_limit_entries(current_time)
            client_timestamps = upload_requests.get(client_ip, [])
            
            # Check rate limit
            if len(client_timestamps) >= RATE_LIMIT_UPLOADS:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": f"Rate limit exceeded. Maximum {RATE_LIMIT_UPLOADS} uploads per minute.",
                        "retry_after": int(RATE_LIMIT_WINDOW - (current_time - client_timestamps[0]))
                    }
                )
            
            # Record this request
            upload_requests[client_ip] = [*client_timestamps, current_time]
            _prune_rate_limit_entries(current_time)
        
        return await call_next(request)


def validate_environment():
    """Validate critical environment variables."""
    errors = []
    warnings = []
    
    # Check database URL
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        errors.append("DATABASE_URL not configured")
    elif "your_" in db_url or "example" in db_url:
        errors.append("DATABASE_URL contains placeholder value")
    
    # Check API keys - now supports multiple keys
    from app.utils.genai_client import GenAIClient
    key_count = GenAIClient.get_key_count()
    if key_count == 0:
        demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
        if demo_mode:
            warnings.append("GEMINI_API_KEYS not configured - DEMO_MODE enabled")
        else:
            errors.append("GEMINI_API_KEYS not configured and DEMO_MODE is disabled")
    else:
        print(f"✓ Found {key_count} Gemini API keys for round-robin")
    
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    tts_provider = os.getenv("TTS_PROVIDER", "fixture" if demo_mode else "elevenlabs").strip().lower()
    if tts_provider == "elevenlabs":
        elevenlabs_key = os.getenv("ELEVENLABS_API_KEY", "")
        if not elevenlabs_key or "your_" in elevenlabs_key:
            warnings.append("ELEVENLABS_API_KEY not configured for the selected TTS provider")
    elif tts_provider == "openai":
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if not openai_key or "your_" in openai_key:
            warnings.append("OPENAI_API_KEY not configured for the selected TTS provider")
    elif tts_provider in {"fixture", "demo"} and not demo_mode:
        errors.append("Fixture TTS requires DEMO_MODE=true")
    
    # Check ffmpeg
    if not shutil.which("ffmpeg"):
        warnings.append("ffmpeg not found in PATH - video processing limited")
    
    # Check either the Rubber Band CLI or FFmpeg's native filter.
    if not has_rubberband_support():
        warnings.append("Rubberband CLI/native FFmpeg filter unavailable - audio time-stretching will use atempo")
    
    return errors, warnings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    
    # Startup
    print("🚀 Starting VoxBridge API...")
    
    # Validate environment
    errors, warnings = validate_environment()
    
    if errors:
        for error in errors:
            print(f"❌ ERROR: {error}")
        raise RuntimeError("Critical configuration errors. Fix .env file.")
    
    for warning in warnings:
        print(f"⚠️  WARNING: {warning}")
    
    # Initialize database connection pool
    await init_db_pool()
    
    # Initialize database schema
    await init_database()
    
    # Create storage directories
    # Bug #10 fix: Use os.environ directly - paths are already absolute from startup
    storage_dirs = [
        os.environ["UPLOAD_DIR"],
        os.environ["PROCESSED_DIR"],
        os.environ["OUTPUT_DIR"],
    ]
    for directory in storage_dirs:
        os.makedirs(directory, exist_ok=True)
    
    # Resume incomplete jobs from previous session
    await resume_incomplete_jobs()
    
    rate_limit_cleanup_task = asyncio.create_task(_rate_limit_cleanup_loop())
    print("✅ Application started successfully")

    try:
        yield
    finally:
        rate_limit_cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await rate_limit_cleanup_task
    
    # Shutdown
    print("🛑 Shutting down...")
    await close_db_pool()
    print("✅ Shutdown complete")


async def resume_incomplete_jobs():
    """Resume jobs that were interrupted during previous session."""
    try:
        from app.services.audit_service import update_job_status
        from app.utils.database import get_db_connection
        
        async with get_db_connection() as conn:
            # Find jobs that were in progress when server stopped
            incomplete = await conn.fetch(
                "SELECT job_id, state_data, status FROM jobs WHERE status IN ('dubbing', 'processing')"
            )
            
            if not incomplete:
                return
            
            print(f"⚡ Found {len(incomplete)} incomplete jobs to handle...")
            
            for job in incomplete:
                job_id = job["job_id"]
                state = decode_json_object(job["state_data"])
                status = job["status"]
                pipeline_step = state.get("pipeline_step", "")
                
                # Mark stuck jobs as 'error' so user can retry
                if status == "dubbing":
                    if pipeline_step == "complete":
                        # Almost done, mark as completed
                        await update_job_status(job_id, "completed")
                        print(f"  ✓ Job {job_id[:8]} marked completed")
                    else:
                        # Stuck mid-pipeline, mark for retry
                        await update_job_status(job_id, "error")
                        print(f"  ⚠️ Job {job_id[:8]} marked for retry (was at: {pipeline_step or 'unknown'})")
                elif status == "processing":
                    # Reset to uploaded so user can retry
                    await update_job_status(job_id, "uploaded")
                    print(f"  ↺ Job {job_id[:8]} reset to uploaded")
                    
    except Exception as e:
        print(f"⚠️ Job resumption error (non-fatal): {e}")


# Create FastAPI application
app = FastAPI(
    title="VoxBridge API",
    description="Responsible AI-Powered Multilingual Video Dubbing Platform",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS - strip whitespace from origins
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# Add upload size limit middleware
app.add_middleware(LimitUploadSizeMiddleware)

# Add rate limiting middleware
app.add_middleware(RateLimitMiddleware)

# Include API routes
app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "VoxBridge API",
        "version": "1.0.0",
        "description": "Responsible AI-Powered Multilingual Video Dubbing Platform",
        "documentation": "/docs",
    }


@app.get("/health")
async def health_check():
    """Enhanced health check with dependency validation."""
    from app.utils.genai_client import GenAIClient
    
    health_status = {
        "status": "healthy",
        "database": "unknown",
        "ffmpeg": "unknown",
        "gemini_api": "unknown",
        "tts": "unknown",
        "demo_mode": os.getenv("DEMO_MODE", "false").lower() == "true",
    }
    
    # Check database
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        health_status["database"] = "connected"
    except Exception as e:
        health_status["database"] = f"error: {str(e)}"
        health_status["status"] = "unhealthy"
    
    # Check ffmpeg
    health_status["ffmpeg"] = "available" if shutil.which("ffmpeg") else "missing"
    
    # Check Gemini API keys
    key_count = GenAIClient.get_key_count()
    healthy_keys = GenAIClient.get_healthy_key_count()
    health_status["gemini_api"] = {
        "total_keys": key_count,
        "healthy_keys": healthy_keys,
        "status": "ready" if healthy_keys > 0 else "no_keys"
    }

    # Check the selected TTS provider without exposing credential values.
    tts_provider = os.getenv("TTS_PROVIDER", "fixture" if health_status["demo_mode"] else "elevenlabs").strip().lower()
    if tts_provider == "elevenlabs":
        tts_api_key = os.getenv("ELEVENLABS_API_KEY", "")
        tts_ready = bool(tts_api_key and "your_" not in tts_api_key)
    elif tts_provider == "openai":
        tts_api_key = os.getenv("OPENAI_API_KEY", "")
        tts_ready = bool(tts_api_key and "your_" not in tts_api_key)
    elif tts_provider == "gemini":
        tts_ready = healthy_keys > 0
    else:
        tts_ready = health_status["demo_mode"]

    health_status["tts"] = {
        "provider": tts_provider,
        "api_key_configured": tts_ready,
        "status": "ready" if tts_ready else "not_configured"
    }
    
    return health_status
