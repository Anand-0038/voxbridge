"""
API route handlers for VoxBridge.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.models.schemas import (
    AnalysisResponse,
    AnalyzeContentRequest,
    ApproveAndDubRequest,
    AuditReportResponse,
    DubbingStatusResponse,
    RiskLevel,
    TranscriptSegment,
    TranslationSegment,
    UploadResponse,
    YouTubeImportRequest,
)
from app.services.audit_service import (
    create_job,
    get_audit_report,
    get_job,
    log_step,
    log_user_decision,
    save_job_state,
    update_job_status,
)
from app.services.media_service import (
    create_dubbed_audio_track,
    encode_audio_format,
    extract_audio,
    get_video_duration,
    merge_audio_video,
    validate_merged_output,
)
from app.services.safety_service import analyze_content_safety
from app.services.transcription_service import transcribe_audio
from app.services.translation_service import translate_transcript
from app.services.tts_service import synthesize_speech_parallel
from app.services.youtube_service import download_youtube_video
from app.services.transcription_service import detect_language
from app.utils.helpers import (
    get_absolute_path,
    get_file_extension,
    get_relative_path,
    is_valid_uuid,
    sanitize_filename,
    validate_path_within_base,
    validate_segment_timings,
)

router = APIRouter()

# NOTE: jobs_cache removed - all state now stored in PostgreSQL via save_job_state()
# This ensures state persists across server restarts.
_active_tasks: set[asyncio.Task] = set()


def _remove_file_if_exists(file_path: str) -> None:
    """Best-effort cleanup for a specific upload artifact."""
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        print(f"[STORAGE] Could not remove {file_path}: {exc}")


def _track_background_task(coroutine) -> asyncio.Task:
    """Keep a strong reference to fallback tasks until they finish."""
    task = asyncio.create_task(coroutine)
    _active_tasks.add(task)
    task.add_done_callback(_active_tasks.discard)
    return task


@router.post("/upload-video", response_model=UploadResponse)
async def upload_video(
    file: UploadFile = File(...), background_tasks: BackgroundTasks = None
):
    """
    Upload a video file for processing.

    Creates a new job and starts audio extraction.
    Supports files up to 500MB using chunked streaming.
    """
    # Validate file type - support by MIME and extension fallback
    allowed_types = {
        "video/mp4",
        "video/quicktime",
        "video/x-msvideo",
        "video/avi",
        "video/m4v",
        "video/x-m4v",
        "video/x-matroska",
        "video/matroska",
        "video/webm",
        "video/mkv",
        "video/x-ms-asf",
    }
    allowed_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    ext = get_file_extension(file.filename or "").lower()
    is_valid_content_type = bool(content_type) and content_type in allowed_types
    is_valid_extension = ext in allowed_extensions

    if not (is_valid_content_type or is_valid_extension):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed: MP4, MOV, AVI, MKV, WEBM, M4V",
        )

    # Generate job ID
    job_id = str(uuid.uuid4())
    filename = file.filename or f"{job_id}.mp4"
    filename = sanitize_filename(filename)
    ext = get_file_extension(filename)
    if not ext:
        fallback_ext_map = {
            "video/mp4": ".mp4",
            "video/quicktime": ".mov",
            "video/x-msvideo": ".avi",
            "video/m4v": ".m4v",
            "video/x-m4v": ".m4v",
            "video/matroska": ".mkv",
            "video/mkv": ".mkv",
            "video/webm": ".webm",
            "video/x-matroska": ".mkv",
            "video/avi": ".avi",
        }
        filename = f"{filename}{fallback_ext_map.get(content_type, '.mp4')}"

    # Create upload directory
    upload_dir = os.getenv("UPLOAD_DIR", "storage/uploads")
    await asyncio.to_thread(os.makedirs, upload_dir, exist_ok=True)

    # Save uploaded file using chunked streaming (critical for large files)
    file_ext = get_file_extension(filename)
    saved_filename = f"{job_id}{file_ext}"
    file_path = os.path.join(upload_dir, saved_filename)

    # Stream file in chunks to avoid memory overflow
    CHUNK_SIZE = 1024 * 1024  # 1MB chunks
    file_size = 0

    try:
        # UploadFile may be backed by a disk spool; reading its underlying
        # handle directly avoids a second executor hop for every chunk.
        with open(file_path, "wb") as output_file:
            while True:
                chunk = file.file.read(CHUNK_SIZE)
                if not chunk:
                    break
                output_file.write(chunk)
                file_size += len(chunk)
    except Exception as e:
        # Clean up partial file on error
        await asyncio.to_thread(_remove_file_if_exists, file_path)
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    # Validate file signature (magic bytes) - security check
    from app.utils.helpers import validate_file_signature

    sig_result = await asyncio.to_thread(validate_file_signature, file_path, "video")
    if not sig_result["valid"]:
        # Clean up invalid file
        await asyncio.to_thread(_remove_file_if_exists, file_path)
        raise HTTPException(
            status_code=400, detail=f"Invalid video file: {sig_result['message']}"
        )

    # Persist only a project-relative path. The absolute path remains an
    # internal runtime detail used by the media worker.
    relative_file_path = get_relative_path(file_path)

    try:
        await create_job(job_id, filename, relative_file_path)
    except Exception as exc:
        await asyncio.to_thread(_remove_file_if_exists, file_path)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create processing job: {exc}",
        ) from exc

    # Log upload step
    await log_step(
        job_id,
        "video_upload",
        "completed",
        {
            "original_filename": filename,
            "saved_path": relative_file_path,
            "file_size": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
        },
    )

    # Start audio extraction in background
    if background_tasks is not None:
        background_tasks.add_task(process_uploaded_video, job_id, file_path)
    else:
        # Defensive fallback if DI doesn't provide BackgroundTasks
        _track_background_task(process_uploaded_video(job_id, file_path))

    return UploadResponse(
        job_id=job_id,
        status="uploaded",
        message="Video uploaded successfully. Audio extraction started.",
        filename=filename,
    )


@router.post("/import-youtube", response_model=UploadResponse)
async def import_youtube_video(
    request: YouTubeImportRequest, background_tasks: BackgroundTasks
):
    """Acquire one public YouTube video and enter the normal job pipeline."""
    job_id = str(uuid.uuid4())
    file_path: str | None = None
    keep_file = False

    try:
        downloaded = await download_youtube_video(
            request.url,
            os.getenv("UPLOAD_DIR", "storage/uploads"),
            job_id,
        )
        file_path = downloaded["file_path"]

        from app.utils.helpers import validate_file_signature

        signature = await asyncio.to_thread(validate_file_signature, file_path, "video")
        if not signature["valid"]:
            raise HTTPException(
                status_code=400,
                detail=f"Downloaded file is not a valid video: {signature['message']}",
            )

        filename = (
            sanitize_filename(downloaded.get("filename") or os.path.basename(file_path))
            or f"{job_id}.mp4"
        )
        if not get_file_extension(filename):
            filename = f"{filename}{os.path.splitext(file_path)[1] or '.mp4'}"
        relative_file_path = get_relative_path(file_path)

        await create_job(job_id, filename, relative_file_path)
        await save_job_state(
            job_id,
            {
                "source_type": "youtube",
                "source_url": downloaded["source_url"],
                "source_title": downloaded.get("title"),
                "source_duration": downloaded.get("duration"),
            },
        )
        await log_step(
            job_id,
            "youtube_import",
            "completed",
            {
                "source_url": downloaded["source_url"],
                "title": downloaded.get("title"),
                "duration": downloaded.get("duration"),
                "saved_path": relative_file_path,
            },
        )
        background_tasks.add_task(process_uploaded_video, job_id, file_path)
        keep_file = True

        return UploadResponse(
            job_id=job_id,
            status="uploaded",
            message="YouTube video downloaded. Audio extraction started.",
            filename=filename,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        if file_path and not keep_file:
            await asyncio.to_thread(_remove_file_if_exists, file_path)


async def process_uploaded_video(job_id: str, video_path: str):
    """
    Background task with global timeout and guaranteed status update.

    This wrapper ensures:
    1. Status is set to 'processing' immediately
    2. If task takes > 5 minutes, it times out with proper error status
    3. All exceptions result in 'error' status being set
    """
    try:
        # Set status to processing immediately
        await update_job_status(job_id, "processing")

        # Run internal processing with 5-minute timeout
        await asyncio.wait_for(
            _process_uploaded_video_internal(job_id, video_path),
            timeout=300.0,  # 5 minutes max
        )

    except asyncio.TimeoutError:
        error_msg = "Processing timed out after 5 minutes"
        print(f"[PIPELINE] ✗ Job {job_id} TIMEOUT: {error_msg}")
        # Removing one local artifact is tiny and deterministic; keep cleanup
        # inline so timeout handling cannot leave an executor task behind.
        _remove_file_if_exists(video_path)
        await save_job_state(job_id, {"error": error_msg})
        await log_step(job_id, "pipeline_timeout", "failed", {"timeout": 300})
        await update_job_status(job_id, "error")

    except Exception as e:
        import traceback

        error_msg = str(e)
        print(f"[PIPELINE] ✗ Job {job_id} failed: {error_msg}")
        print(traceback.format_exc())
        _remove_file_if_exists(video_path)
        await save_job_state(job_id, {"error": error_msg})
        await log_step(job_id, "processing_error", "failed", {"error": error_msg})
        await update_job_status(job_id, "error")


async def _process_uploaded_video_internal(job_id: str, video_path: str):
    """Internal processing function without timeout wrapper."""

    # Step 1: Extract audio
    await log_step(
        job_id,
        "audio_extraction",
        "started",
        {"video_path": get_relative_path(video_path)},
    )
    processed_dir = os.getenv("PROCESSED_DIR", "storage/processed")
    await asyncio.to_thread(os.makedirs, processed_dir, exist_ok=True)
    audio_output_path = os.path.join(processed_dir, f"{job_id}.wav")
    audio_path = await extract_audio(video_path, audio_output_path)
    await log_step(
        job_id,
        "audio_extraction",
        "completed",
        {"audio_path": get_relative_path(audio_path)},
    )

    # Step 2: Transcribe audio
    await log_step(
        job_id,
        "transcription",
        "started",
        {"audio_path": get_relative_path(audio_path)},
    )
    transcript = await transcribe_audio(audio_path)
    await log_step(
        job_id,
        "transcription",
        "completed",
        {
            "segment_count": len(transcript),
        },
    )

    # Step 3: Save state to PostgreSQL
    await save_job_state(
        job_id,
        {
            "audio_path": get_relative_path(audio_path),
            "transcript": [
                (
                    seg.model_dump()
                    if hasattr(seg, "model_dump")
                    else seg.__dict__
                    if hasattr(seg, "__dict__")
                    else seg
                )
                for seg in transcript
            ],
            "file_path": get_relative_path(video_path),
        },
    )

    await update_job_status(job_id, "ready_for_analysis")
    print(f"[PIPELINE] ✓ Job {job_id} ready for analysis")


@router.post("/analyze-content", response_model=AnalysisResponse)
async def analyze_content(request: AnalyzeContentRequest):
    """
    Run Responsible AI safety checks on the transcript.

    Analyzes content for toxicity, bias, misinformation, and cultural sensitivity.
    """
    job_id = request.job_id

    # Get job data from database
    job_data = await get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    state = job_data.get("state_data", {}) or {}
    status = job_data.get("status", "")

    if status != "ready_for_analysis":
        if status in ["uploaded", "processing"]:
            raise HTTPException(
                status_code=400, detail="Video is still being processed. Please wait."
            )
        raise HTTPException(status_code=400, detail="Job is not ready for analysis")

    # Bug #9 fix: Add validation for transcript structure
    try:
        raw_transcript = state.get("transcript", [])
        if not raw_transcript:
            raise HTTPException(status_code=400, detail="No transcript available")

        # Validate each segment has required fields
        transcript = []
        for i, t in enumerate(raw_transcript):
            if not isinstance(t, dict):
                raise ValueError(f"Segment {i} is not a dict")

            # Strict validation
            if "text" not in t:
                raise ValueError(f"Segment {i} missing 'text' field")

            # Validate timing logic
            start = float(t.get("start_time", 0))
            end = float(t.get("end_time", 0))
            if end < start:
                raise ValueError(
                    f"Segment {i} has invalid timing: end ({end}) < start ({start})"
                )

            transcript.append(TranscriptSegment(**t))
    except (TypeError, ValueError) as e:
        raise HTTPException(
            status_code=400, detail=f"Invalid transcript structure: {str(e)}"
        )

    # Run safety analysis
    await log_step(job_id, "safety_analysis", "started", {})

    try:
        analysis_result = await analyze_content_safety(transcript)
    except Exception as exc:
        error_message = f"Safety analysis failed: {exc}"
        await save_job_state(job_id, {"error": error_message})
        await log_step(job_id, "safety_analysis", "failed", {"error": error_message})
        await update_job_status(job_id, "error")
        raise HTTPException(status_code=502, detail=error_message) from exc

    analysis_result.job_id = job_id

    analysis_payload = (
        analysis_result.model_dump(mode="json")
        if hasattr(analysis_result, "model_dump")
        else {
            "job_id": job_id,
            "risk_score": analysis_result.risk_score,
            "risk_level": str(analysis_result.risk_level),
            "flags": [],
            "transcript_segments": [
                t.model_dump(mode="json") if hasattr(t, "model_dump") else t
                for t in transcript
            ],
            "analysis_summary": "Safety analysis completed.",
        }
    )
    analysis_payload["risk_level"] = analysis_result.risk_level.value
    analysis_payload["flags"] = [
        f.model_dump(mode="json") if hasattr(f, "model_dump") else f
        for f in analysis_result.flags
    ]

    await log_step(
        job_id,
        "safety_analysis",
        "completed",
        {
            "risk_score": analysis_result.risk_score,
            "risk_level": analysis_result.risk_level.value,
            "flag_count": len(analysis_result.flags),
            "flags": analysis_payload["flags"],
            "analysis_summary": analysis_result.analysis_summary,
            "transcript_segment_count": len(transcript),
        },
    )

    # Save analysis to PostgreSQL
    await save_job_state(
        job_id,
        {
            "analysis": analysis_payload,
        },
    )
    await update_job_status(job_id, "analyzed")

    return analysis_result


@router.post("/approve-and-dub", response_model=DubbingStatusResponse)
async def approve_and_dub(
    request: ApproveAndDubRequest, background_tasks: BackgroundTasks
):
    """
    Approve content and start the dubbing process.

    Requires explicit consent confirmation for voice synthesis.
    """
    job_id = request.job_id

    # Get job data from database
    job_data = await get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    if job_data.get("status") != "analyzed":
        raise HTTPException(status_code=400, detail="Content must be analyzed first")

    # Validate consent
    if request.consent_confirmed is not True:
        raise HTTPException(
            status_code=400, detail="Voice synthesis consent must be confirmed"
        )

    # Validate target_language is supported
    from app.utils import get_supported_languages, is_language_supported

    if not is_language_supported(request.target_language):
        supported = [lang["code"] for lang in get_supported_languages()]
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language '{request.target_language}'. Supported: {', '.join(supported)}",
        )

    # Check for high-risk content from state_data
    # Bug #7 fix: Require valid analysis, default to 'high' risk if missing
    state = job_data.get("state_data", {}) or {}
    analysis = state.get("analysis")
    if not analysis or not isinstance(analysis, dict):
        raise HTTPException(
            status_code=400,
            detail="Content analysis is missing. Please run analysis first.",
        )
    risk_level = analysis.get("risk_level")
    if isinstance(risk_level, RiskLevel):
        risk_level = risk_level.value
    elif hasattr(risk_level, "value"):
        risk_level = risk_level.value
    elif isinstance(risk_level, str):
        risk_level = risk_level.lower().replace("risklevel.", "")
    if not risk_level:
        # Default to high risk if analysis exists but risk_level is missing
        risk_level = "high"
    if risk_level == "high" and not request.override_safety:
        raise HTTPException(
            status_code=400,
            detail="High-risk content detected. Set override_safety=true to proceed with acknowledgment.",
        )

    # Log approval decision
    await log_step(
        job_id,
        "user_approval",
        "completed",
        {
            "target_language": request.target_language,
            "consent_confirmed": request.consent_confirmed,
            "override_safety": request.override_safety,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )
    await log_user_decision(
        job_id,
        "consent_confirmed",
        str(request.consent_confirmed).lower(),
        reason="User confirmed AI voice synthesis consent.",
    )
    await log_user_decision(
        job_id,
        "override_safety",
        str(request.override_safety).lower(),
        reason="User acknowledged high-risk review requirement."
        if request.override_safety
        else "Not acknowledged",
    )

    # Start dubbing - status updated in database
    await update_job_status(
        job_id,
        "dubbing",
        target_language=request.target_language,
        consent_confirmed=True,
        consent_timestamp=datetime.utcnow(),
    )

    background_tasks.add_task(run_dubbing_pipeline, job_id, request.target_language)

    return DubbingStatusResponse(
        job_id=job_id,
        status="dubbing",
        progress=0,
        message="Dubbing process started",
        current_step="translation",
    )


async def run_dubbing_pipeline(job_id: str, target_language: str):
    """Background task to run the full dubbing pipeline."""
    error_msg: str | None = None
    try:
        # Get job data from database
        job_data = await get_job(job_id)
        state = job_data.get("state_data", {}) if job_data else {}
        transcript = (
            [
                TranscriptSegment(**t) if isinstance(t, dict) else t
                for t in state.get("transcript", [])
            ]
            if state.get("transcript")
            else []
        )
        video_path = (
            state.get("file_path") or job_data.get("file_path", "") if job_data else ""
        )

        # Ensure video path is absolute
        if video_path:
            video_path = get_absolute_path(video_path)

        # Translation
        await log_step(
            job_id, "translation", "started", {"target_language": target_language}
        )
        translated = await translate_transcript(transcript, target_language)

        # Detect source language for audit traceability.
        source_language = "en"
        if transcript:
            first_text = str(transcript[0].text or "").strip()
            if first_text:
                try:
                    source_language = await detect_language(first_text)
                except Exception:
                    source_language = "en"

        translated_segments = [
            segment
            for segment in translated
            if isinstance(segment, TranslationSegment) and segment.translated_text.strip()
        ]
        translated_confidences = [
            float(seg.confidence or 0.0) for seg in translated_segments
        ]
        translation_avg_confidence = (
            sum(translated_confidences) / len(translated_confidences)
            if translated_confidences
            else 0.0
        )
        translation_examples = [
            {
                "index": index,
                "original_text": segment.original_text,
                "translated_text": segment.translated_text,
            }
            for index, segment in enumerate(translated_segments[:3])
        ]

        await log_step(
            job_id,
            "translation",
            "completed",
            {
                "source_language": source_language,
                "target_language": target_language,
                "segment_count": len(translated),
                "segments_translated": len(translated_segments),
                "average_confidence": translation_avg_confidence,
                "samples": translation_examples,
            },
        )

        # CHECKPOINT: Save after translation (prevents data loss on crash)
        await save_job_state(
            job_id,
            {
                "translated": [
                    (
                        t.model_dump(mode="json")
                        if hasattr(t, "model_dump")
                        else t.__dict__
                        if hasattr(t, "__dict__")
                        else t
                    )
                    for t in translated
                ],
                "pipeline_step": "translation_complete",
            },
        )

        # TIMING VALIDATION: Catch issues early before TTS (added fix)
        timing_check = validate_segment_timings(
            [
                {
                    "start_time": getattr(s, "start_time", 0),
                    "end_time": getattr(s, "end_time", 0),
                }
                for s in translated
            ]
        )
        if not timing_check["valid"]:
            print(f"[TIMING] ❌ Errors: {timing_check['errors']}")
            raise RuntimeError(f"Segment timing errors: {timing_check['errors']}")
        if timing_check["warnings"]:
            print(f"[TIMING] ⚠️ Warnings: {timing_check['warnings']}")

        # Text-to-Speech
        await log_step(job_id, "tts_synthesis", "started", {})
        audio_segments = await synthesize_speech_parallel(
            translated,
            target_language,
            consent_verified=True,
            output_prefix=job_id,
        )
        expected_audio_indices = {
            index
            for index, segment in enumerate(translated)
            if getattr(segment, "translated_text", "")
        }
        generated_audio_indices = {
            segment.get("index")
            for segment in audio_segments
            if segment.get("index") is not None
        }
        missing_tts_indices = sorted(expected_audio_indices - generated_audio_indices)
        await log_step(
            job_id,
            "tts_synthesis",
            "completed",
            {
                "audio_segment_count": len(audio_segments),
                "expected_audio_segment_count": len(expected_audio_indices),
                "missing_segment_indices": missing_tts_indices,
                "silence_padded_segments": missing_tts_indices,
                "partial": bool(missing_tts_indices),
                "provider": (
                    audio_segments[0].get("metadata", {}).get("service")
                    if audio_segments
                    else None
                ),
                "demo_fixture": bool(
                    audio_segments
                    and audio_segments[0].get("metadata", {}).get("demo_fixture", False)
                ),
            },
        )

        # CHECKPOINT: Save after TTS (prevents data loss on crash). Persist
        # relative paths only; the worker continues using its absolute paths.
        persisted_audio_segments = []
        for segment in audio_segments:
            persisted_segment = dict(segment)
            if persisted_segment.get("audio_path"):
                persisted_segment["audio_path"] = get_relative_path(
                    persisted_segment["audio_path"]
                )
            persisted_audio_segments.append(persisted_segment)

        await save_job_state(
            job_id,
            {
                "audio_segments": persisted_audio_segments,
                "pipeline_step": "tts_complete",
            },
        )

        # Generate output files
        output_dir = os.getenv("OUTPUT_DIR", "storage/outputs")
        # Ensure absolute output dir
        output_dir = get_absolute_path(output_dir)
        await asyncio.to_thread(os.makedirs, output_dir, exist_ok=True)

        # Create output paths
        output_video_path = os.path.join(output_dir, f"{job_id}_dubbed.mp4")
        output_audio_path = os.path.join(output_dir, f"{job_id}_audio.mp3")
        timeline_audio_path = os.path.join(output_dir, f"{job_id}_audio_timeline.wav")
        output_audit_path = os.path.join(output_dir, f"{job_id}_audit.json")
        relative_output_video_path = get_relative_path(output_video_path)
        relative_output_audio_path = get_relative_path(output_audio_path)
        relative_output_audit_path = get_relative_path(output_audit_path)

        await log_step(job_id, "output_generation", "started", {})

        # Bug #1 fix: Sort audio segments by start_time before concatenation
        sorted_segments = sorted(audio_segments, key=lambda x: x.get("start_time", 0))

        # Keep the complete translated timeline, including failed TTS
        # segments. The timeline utility treats entries without an audio path
        # as intentional silence, so a missing segment cannot collapse later
        # speech toward the beginning of the video or truncate the tail.
        generated_by_index = {
            segment.get("index"): segment
            for segment in audio_segments
            if segment.get("index") is not None
        }
        timeline_segments = []
        for index, translated_segment in enumerate(translated):
            generated_segment = generated_by_index.get(index, {})
            timeline_segments.append(
                {
                    **generated_segment,
                    "index": index,
                    "audio_path": generated_segment.get("audio_path"),
                    "start_time": getattr(translated_segment, "start_time", 0),
                    "end_time": getattr(translated_segment, "end_time", 0),
                }
            )

        # Collect valid audio segment paths (maintaining sorted order)
        segment_paths = []
        missing_file_indices = []
        for seg in sorted_segments:
            segment_index = seg.get("index")
            p = seg.get("audio_path")
            if p:
                abs_p = get_absolute_path(p)
                if os.path.exists(abs_p):
                    segment_paths.append(abs_p)
                else:
                    missing_file_indices.append(segment_index)
            else:
                missing_file_indices.append(segment_index)

        missing_segments = sorted(
            {
                index
                for index in [*missing_tts_indices, *missing_file_indices]
                if index is not None
            }
        )

        if missing_segments:
            print(
                f"WARNING: {len(missing_segments)} audio segments will be silence-padded for job {job_id}: indices {missing_segments}"
            )
            await log_step(
                job_id,
                "audio_segment_validation",
                "completed",
                {
                    "missing_segment_indices": missing_segments,
                    "silence_padded": True,
                },
            )

        print(
            f"Found {len(segment_paths)} audio segments to concatenate (sorted by start_time)"
        )

        # Build the timeline against the source video duration. The legacy
        # concatenation wrapper only extends to the last spoken segment and
        # truncates videos that contain trailing silence or visuals.
        await create_dubbed_audio_track(
            segments=timeline_segments,
            video_path=video_path,
            output_audio_path=timeline_audio_path,
            temp_dir=os.path.dirname(output_audio_path),
        )
        await encode_audio_format(timeline_audio_path, output_audio_path)
        if os.path.exists(timeline_audio_path):
            await asyncio.to_thread(os.remove, timeline_audio_path)
        print(f"Created synchronized master audio track: {output_audio_path}")

        # Merge audio with video (actual dubbing)
        if video_path and os.path.exists(video_path):
            # Get video duration for validation
            video_duration = await get_video_duration(video_path)

            await merge_audio_video(
                video_path=video_path,
                audio_path=output_audio_path,
                output_path=output_video_path,
                # Replace original audio by default for a clear dubbing result.
                # Use PRESERVE_ORIGINAL_AUDIO=true in env to keep a ducked
                # background mix for scenarios where that is preferred.
                preserve_background=os.getenv("PRESERVE_ORIGINAL_AUDIO", "false").lower()
                == "true",
            )
            print(f"Created dubbed video: {output_video_path}")

            # POST-MERGE VALIDATION: Verify output has correct audio and duration (added fix)
            validation = await validate_merged_output(output_video_path, video_duration)
            print(
                f"[VALIDATION] ✓ {validation['audio_codec']}, {validation['duration']:.1f}s (diff: {validation['duration_diff']:.2f}s)"
            )
        else:
            raise FileNotFoundError(f"Original video file missing: {video_path}")

        # Create audit data - reading from correct state location
        analysis = state.get("analysis", {})

        audit_data = {
            "job_id": job_id,
            "target_language": target_language,
            "created_at": datetime.utcnow().isoformat(),
            "status": "completed",
            "transcript_segments": [
                t.model_dump() if hasattr(t, "model_dump") else t for t in transcript
            ],
            "translated_segments": len(translated),
            "audio_segments": len(audio_segments),
            "expected_audio_segments": len(expected_audio_indices),
            "silence_padded_segments": missing_segments,
            "safety_analysis": (
                {
                    "risk_score": analysis.get("risk_score", 0),
                    "risk_level": analysis.get("risk_level", "low"),
                    "flag_count": len(analysis.get("flags", [])),
                    "flags": analysis.get("flags", []),
                }
                if analysis
                else None
            ),
            "output_files": {
                "video": relative_output_video_path,
                "audio": relative_output_audio_path,
                "audit": relative_output_audit_path,
            },
            "ai_disclosure": (
                "AI voice segments were generated with user consent. Missing segments were silence-padded and are listed in this audit."
                if missing_segments
                else "All audio content was generated using AI voice synthesis with user consent."
            ),
        }

        with open(output_audit_path, "w", encoding="utf-8") as audit_file:
            json.dump(audit_data, audit_file, indent=2)

        await log_step(
            job_id,
            "output_generation",
            "completed",
            {
                "video": relative_output_video_path,
                "audio": relative_output_audio_path,
                "audit": relative_output_audit_path,
                "validation": validation,
                "silence_padded_segments": missing_segments,
            },
        )

        # Update status to completed
        await save_job_state(
            job_id,
            {
                "output_video": relative_output_video_path,
                "output_audio": relative_output_audio_path,
                "output_audit": relative_output_audit_path,
                "pipeline_step": "complete",
                "validation": validation,
            },
        )
        await update_job_status(
            job_id,
            "completed",
        )

    except Exception as e:
        import traceback

        traceback.print_exc()
        error_msg = str(e)
        print(f"Error in dubbing pipeline: {error_msg}")

        await save_job_state(job_id, {"error": error_msg})
        await update_job_status(job_id, "error")
        await log_step(job_id, "pipeline", "failed", {"error": error_msg})


@router.get("/job-status/{job_id}", response_model=DubbingStatusResponse)
async def get_job_status(job_id: str):
    """Get the current status of a job with detailed progress."""
    job_data = await get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    status = job_data.get("status", "unknown")
    state = job_data.get("state_data", {}) or {}

    # More granular progress based on status and state
    progress_map = {
        "uploaded": 10,
        "processing": 20,
        "ready_for_analysis": 30,
        "analyzed": 40,
        "dubbing": 60,
        "completed": 100,
        "error": 0,
    }

    # Bug #11 fix: Calculate progress for all statuses, check pipeline_step
    progress = progress_map.get(status, 0)
    pipeline_step = state.get("pipeline_step", "")

    # More granular progress based on pipeline checkpoint
    if status == "dubbing" or (status == "completed" and pipeline_step):
        if pipeline_step == "complete" or state.get("output_video"):
            progress = 95 if status == "dubbing" else 100
        elif pipeline_step == "tts_complete" or state.get("output_audio"):
            progress = 85
        elif state.get("audio_segments"):
            progress = 75
        elif pipeline_step == "translation_complete" or state.get("translated"):
            progress = 65

    # User-friendly step names
    step_names = {
        "uploaded": "Video uploaded",
        "processing": "Extracting audio...",
        "ready_for_analysis": "Ready for analysis",
        "analyzed": "Analysis complete",
        "dubbing": "Processing dubbing...",
        "completed": "Complete!",
        "error": "Error occurred",
    }

    # Get error message if exists
    error_msg = state.get("error", "")
    message = (
        f"Error: {error_msg}"
        if status == "error" and error_msg
        else f"Job status: {status}"
    )

    return DubbingStatusResponse(
        job_id=job_id,
        status=status,
        progress=progress,
        message=message,
        current_step=step_names.get(status, status),
    )


@router.get("/audit-report/{job_id}", response_model=AuditReportResponse)
async def get_audit_report_endpoint(job_id: str):
    """
    Retrieve the full audit report for a job.

    Includes all logged steps, safety analysis, and user decisions.
    """
    report = await get_audit_report(job_id)
    if not report:
        raise HTTPException(status_code=404, detail="Audit report not found")

    return report


@router.get("/demo/flagged-transcript")
async def get_demo_flagged_transcript():
    """
    Get a demo transcript with flagged content for demonstration.
    """
    return {
        "transcript": [
            {
                "text": "Welcome to our product demonstration video.",
                "start_time": 0.0,
                "end_time": 3.0,
                "confidence": 0.98,
            },
            {
                "text": "This revolutionary product will cure all diseases instantly.",
                "start_time": 3.0,
                "end_time": 7.0,
                "confidence": 0.95,
            },
            {
                "text": "Studies show that certain groups are naturally less capable.",
                "start_time": 7.0,
                "end_time": 11.0,
                "confidence": 0.92,
            },
            {
                "text": "Thank you for watching our presentation.",
                "start_time": 11.0,
                "end_time": 14.0,
                "confidence": 0.97,
            },
        ],
        "expected_flags": [
            {"category": "misinformation", "segment_index": 1},
            {"category": "bias", "segment_index": 2},
        ],
    }


@router.get("/demo/safe-transcript")
async def get_demo_safe_transcript():
    """
    Get a demo transcript with safe content for demonstration.
    """
    return {
        "transcript": [
            {
                "text": "Welcome to our educational video about renewable energy.",
                "start_time": 0.0,
                "end_time": 4.0,
                "confidence": 0.98,
            },
            {
                "text": "Solar panels convert sunlight into electricity.",
                "start_time": 4.0,
                "end_time": 8.0,
                "confidence": 0.97,
            },
            {
                "text": "Wind turbines harness wind power for clean energy generation.",
                "start_time": 8.0,
                "end_time": 12.0,
                "confidence": 0.96,
            },
            {
                "text": "Thank you for learning about sustainable energy with us.",
                "start_time": 12.0,
                "end_time": 16.0,
                "confidence": 0.99,
            },
        ],
        "expected_flags": [],
    }


@router.get("/download/{file_type}/{job_id}")
async def download_output(file_type: str, job_id: str):
    """
    Download a generated output file.

    SECURITY: Paths are reconstructed from trusted job_id, NOT from DB.
    This prevents path traversal attacks via DB manipulation.

    Args:
        file_type: 'video', 'audio', or 'audit'
        job_id: Job identifier
    """
    # Security: Validate job_id is a valid UUID
    if not is_valid_uuid(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job_data = await get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    # SECURITY FIX: Reconstruct paths from trusted job_id, NOT from DB
    # This prevents path traversal attacks if an attacker modifies state_data
    output_dir = get_absolute_path(os.getenv("OUTPUT_DIR", "storage/outputs"))

    file_path = None
    media_type = None
    filename = f"{job_id}"

    if file_type == "video":
        # Construct path from trusted components only
        file_path = os.path.join(output_dir, f"{job_id}_dubbed.mp4")
        media_type = "video/mp4"
        filename += "_dubbed.mp4"
    elif file_type == "audio":
        file_path = os.path.join(output_dir, f"{job_id}_audio.mp3")
        media_type = "audio/mpeg"
        filename += "_audio.mp3"
    elif file_type == "audit":
        file_path = os.path.join(output_dir, f"{job_id}_audit.json")
        media_type = "application/json"
        filename += "_audit.json"
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    # Double-check: Validate reconstructed path is within allowed directories
    if not validate_path_within_base(file_path):
        print(
            f"SECURITY ERROR: Invalid path construction for job {job_id}: {file_path}"
        )
        raise HTTPException(status_code=500, detail="Internal path error")

    # Validation: Check if job was completed successfully
    if job_data.get("status") != "completed":
        state = job_data.get("state_data", {}) or {}
        if "error" in state:
            raise HTTPException(status_code=500, detail=f"Job failed: {state['error']}")
        # It's possible status updates lagged but file exists, but generally we should warn
        print(
            f"WARNING: Downloading file for incomplete job {job_id} (status: {job_data.get('status')})"
        )

    if not os.path.exists(file_path):
        print(f"DEBUG: Looking for file at: {file_path}")
        print(f"DEBUG: Current working directory: {os.getcwd()}")
        raise HTTPException(
            status_code=404, detail=f"{file_type.capitalize()} file not found on server"
        )

    return FileResponse(path=file_path, media_type=media_type, filename=filename)


@router.get("/debug/job/{job_id}")
async def debug_job_state(job_id: str):
    """Debug endpoint to inspect job state (DEV ONLY)"""
    job_data = await get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    state = job_data.get("state_data", {}) or {}

    output_video = state.get("output_video")
    output_audio = state.get("output_audio")

    return {
        "job_id": job_id,
        "status": job_data.get("status"),
        "file_path": job_data.get("file_path"),
        "state_keys": list(state.keys()),
        "output_video_in_state": output_video,
        "output_video_exists": (
            os.path.exists(get_absolute_path(output_video)) if output_video else False
        ),
        "output_audio_in_state": output_audio,
        "output_audio_exists": (
            os.path.exists(get_absolute_path(output_audio)) if output_audio else False
        ),
    }


@router.get("/stream/original/{job_id}")
async def stream_original_video(job_id: str):
    """
    Stream the original uploaded video for preview.

    Args:
        job_id: Job identifier
    """
    # Security: Validate job_id is a valid UUID
    if not is_valid_uuid(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job_data = await get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    # Get the original video path from job data
    file_path = job_data.get("file_path", "")
    if file_path:
        file_path = get_absolute_path(file_path)

    # Validate path is within allowed directories
    if not file_path or not validate_path_within_base(file_path):
        raise HTTPException(status_code=404, detail="Original video not found")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Original video file not found")

    return FileResponse(
        path=file_path, media_type="video/mp4", filename=f"original_{job_id}.mp4"
    )


@router.get("/stream/dubbed/{job_id}")
async def stream_dubbed_video(job_id: str):
    """
    Stream the dubbed video for preview.

    Args:
        job_id: Job identifier
    """
    # Security: Validate job_id is a valid UUID
    if not is_valid_uuid(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")

    job_data = await get_job(job_id)
    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    # Check if dubbing is complete
    if job_data.get("status") != "completed":
        raise HTTPException(
            status_code=400,
            detail="Dubbed video not available yet. Please wait for dubbing to complete.",
        )

    # Construct path from trusted job_id
    output_dir = get_absolute_path(os.getenv("OUTPUT_DIR", "storage/outputs"))
    file_path = os.path.join(output_dir, f"{job_id}_dubbed.mp4")

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Dubbed video file not found")

    return FileResponse(
        path=file_path, media_type="video/mp4", filename=f"dubbed_{job_id}.mp4"
    )
