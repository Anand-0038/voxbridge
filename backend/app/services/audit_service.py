"""
Audit logging service for compliance and accountability.
PostgreSQL implementation with asyncpg.
"""

import json
from datetime import datetime
from typing import Optional

from app.models.schemas import AuditReportResponse, AuditStep
from app.utils.database import get_db_connection, is_sqlite_database
from app.utils.helpers import decode_json_object


async def _init_sqlite_schema(conn) -> None:
    """Create the local schema without PostgreSQL-only types or extensions."""
    statements = [
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            original_filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'uploaded',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            completed_at TEXT,
            target_language TEXT,
            risk_score INTEGER,
            risk_level TEXT,
            state_data TEXT NOT NULL DEFAULT '{}',
            consent_confirmed INTEGER NOT NULL DEFAULT 0,
            consent_timestamp TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            step_name TEXT NOT NULL,
            status TEXT NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            decision_type TEXT NOT NULL,
            decision_value TEXT NOT NULL,
            reason TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_transcripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            segment_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            confidence REAL DEFAULT 0.9,
            language TEXT DEFAULT 'en',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE,
            UNIQUE (job_id, segment_index)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_translations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            segment_index INTEGER NOT NULL,
            original_text TEXT NOT NULL,
            translated_text TEXT NOT NULL,
            language TEXT NOT NULL,
            start_time REAL,
            end_time REAL,
            confidence REAL DEFAULT 0.9,
            alternatives TEXT NOT NULL DEFAULT '[]',
            has_ambiguity INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE,
            UNIQUE (job_id, segment_index, language)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS job_safety_flags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            category TEXT NOT NULL,
            severity TEXT NOT NULL,
            text_segment TEXT,
            start_time REAL,
            end_time REAL,
            explanation TEXT,
            confidence REAL DEFAULT 0.8,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_audit_steps_job_id ON audit_steps(job_id)",
        "CREATE INDEX IF NOT EXISTS idx_audit_steps_job_step ON audit_steps(job_id, step_name)",
        "CREATE INDEX IF NOT EXISTS idx_job_transcripts_job ON job_transcripts(job_id)",
        "CREATE INDEX IF NOT EXISTS idx_job_translations_job ON job_translations(job_id)",
        "CREATE INDEX IF NOT EXISTS idx_job_translations_lang ON job_translations(job_id, language)",
        "CREATE INDEX IF NOT EXISTS idx_job_safety_flags_job ON job_safety_flags(job_id)",
        "CREATE INDEX IF NOT EXISTS idx_job_safety_flags_severity ON job_safety_flags(job_id, severity)",
    ]
    for statement in statements:
        await conn.execute(statement)


async def init_database():
    """
    Initialize PostgreSQL database schema.
    Creates tables if they don't exist.
    Supports both legacy tables (jobs.id) and current schema (jobs.job_id).
    """
    async with get_db_connection() as conn:
        if is_sqlite_database():
            await _init_sqlite_schema(conn)
            print("✓ SQLite audit schema initialized")
            return

        existing_jobs = await conn.fetchval(
            "SELECT to_regclass('public.jobs') IS NOT NULL"
        )

        if not existing_jobs:
            # Jobs table with state_data for pipeline artifacts
            await conn.execute("""
                CREATE TABLE jobs (
                    job_id TEXT PRIMARY KEY,
                    original_filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'uploaded',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    target_language TEXT,
                    risk_score INTEGER,
                    risk_level TEXT,
                    state_data JSONB DEFAULT '{}',
                    consent_confirmed BOOLEAN DEFAULT FALSE,
                    consent_timestamp TIMESTAMP
                )
            """)
        else:
            # Legacy compatibility migration: older schema used jobs.id + different names
            existing_columns = {
                row["column_name"] for row in await conn.fetch(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'jobs'
                    """
                )
            }

            if "job_id" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS job_id TEXT")
                if "id" in existing_columns:
                    await conn.execute("UPDATE jobs SET job_id = id WHERE job_id IS NULL")
            if "original_filename" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS original_filename TEXT")
            if "file_path" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS file_path TEXT")
                if "input_s3_key" in existing_columns:
                    await conn.execute(
                        "UPDATE jobs SET file_path = COALESCE(file_path, input_s3_key) WHERE file_path IS NULL"
                    )
            if "state_data" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS state_data JSONB DEFAULT '{}'")
            if "target_language" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS target_language TEXT")
            if "risk_score" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS risk_score INTEGER")
            if "risk_level" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS risk_level TEXT")
            if "created_at" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
            if "updated_at" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP")
            if "completed_at" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP")
            if "status" not in existing_columns:
                await conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'uploaded'")
            await conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS jobs_job_id_key
                ON jobs (job_id)
            """)

        # Ensure required columns have usable values for legacy rows
        if existing_jobs:
            if "id" in existing_columns:  # type: ignore[name-defined]
                await conn.execute("""
                    UPDATE jobs
                    SET original_filename = COALESCE(original_filename, file_path, 'upload')
                    WHERE original_filename IS NULL
                """)
                await conn.execute("""
                    UPDATE jobs
                    SET file_path = COALESCE(file_path, original_filename, job_id, 'upload')
                    WHERE file_path IS NULL
                """)
                await conn.execute("""
                    UPDATE jobs
                    SET state_data = COALESCE(state_data, '{}'::jsonb)
                    WHERE state_data IS NULL
                """)
                await conn.execute("""
                    UPDATE jobs
                    SET job_id = COALESCE(job_id, id::text)
                    WHERE job_id IS NULL
                """)
            else:
                await conn.execute("""
                    UPDATE jobs
                    SET original_filename = COALESCE(original_filename, 'upload')
                    WHERE original_filename IS NULL
                """)
                await conn.execute("""
                    UPDATE jobs
                    SET file_path = COALESCE(file_path, original_filename, 'upload')
                    WHERE file_path IS NULL
                """)
                await conn.execute("""
                    UPDATE jobs
                    SET state_data = COALESCE(state_data, '{}'::jsonb)
                    WHERE state_data IS NULL
                """)
                await conn.execute("""
                    UPDATE jobs
                    SET job_id = COALESCE(job_id, md5(random()::text || clock_timestamp()::text))
                    WHERE job_id IS NULL
                """)
        
        # Audit steps table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_steps (
                id SERIAL PRIMARY KEY,
                job_id TEXT NOT NULL,
                step_name TEXT NOT NULL,
                status TEXT NOT NULL,
                details JSONB DEFAULT '{}',
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
            )
        """)
        
        # Create index for faster job lookups
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_steps_job_id 
            ON audit_steps(job_id)
        """)
        
        # Create composite index for step lookups (Performance fix)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_steps_job_step 
            ON audit_steps(job_id, step_name)
        """)
        
        # User decisions table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_decisions (
                id SERIAL PRIMARY KEY,
                job_id TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                decision_value TEXT NOT NULL,
                reason TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
            )
        """)
        
        # Add consent tracking columns if not exist (Consent Tracking Fix)
        await conn.execute("""
            ALTER TABLE jobs 
            ADD COLUMN IF NOT EXISTS consent_confirmed BOOLEAN DEFAULT FALSE
        """)
        await conn.execute("""
            ALTER TABLE jobs 
            ADD COLUMN IF NOT EXISTS consent_timestamp TIMESTAMP
        """)
        
        # ============================================================
        # NORMALIZED TABLES - Avoid loading large JSONB for job status
        # ============================================================
        
        # Job transcripts table (Database Normalization)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS job_transcripts (
                id SERIAL PRIMARY KEY,
                job_id TEXT NOT NULL,
                segment_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                start_time REAL NOT NULL,
                end_time REAL NOT NULL,
                confidence REAL DEFAULT 0.9,
                language TEXT DEFAULT 'en',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE,
                UNIQUE (job_id, segment_index)
            )
        """)
        
        # Index for text search on transcripts
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_transcripts_job 
            ON job_transcripts(job_id)
        """)
        
        # Full-text search index for transcript text
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_transcripts_text 
            ON job_transcripts USING gin(to_tsvector('english', text))
        """)
        
        # Job translations table (Database Normalization)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS job_translations (
                id SERIAL PRIMARY KEY,
                job_id TEXT NOT NULL,
                segment_index INTEGER NOT NULL,
                original_text TEXT NOT NULL,
                translated_text TEXT NOT NULL,
                language TEXT NOT NULL,
                start_time REAL,
                end_time REAL,
                confidence REAL DEFAULT 0.9,
                alternatives JSONB DEFAULT '[]',
                has_ambiguity BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE,
                UNIQUE (job_id, segment_index, language)
            )
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_translations_job 
            ON job_translations(job_id)
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_translations_lang 
            ON job_translations(job_id, language)
        """)
        
        # Job safety flags table (Database Normalization)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS job_safety_flags (
                id SERIAL PRIMARY KEY,
                job_id TEXT NOT NULL,
                category TEXT NOT NULL,
                severity TEXT NOT NULL,
                text_segment TEXT,
                start_time REAL,
                end_time REAL,
                explanation TEXT,
                confidence REAL DEFAULT 0.8,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (job_id) REFERENCES jobs (job_id) ON DELETE CASCADE
            )
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_safety_flags_job 
            ON job_safety_flags(job_id)
        """)
        
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_safety_flags_severity 
            ON job_safety_flags(job_id, severity)
        """)
        
        print("✓ Database schema initialized")


async def create_job(job_id: str, filename: str, file_path: str) -> dict:
    """
    Create a new job record.
    
    Args:
        job_id: Unique job identifier
        filename: Original uploaded filename
        file_path: Path where file is stored
        
    Returns:
        Job data dictionary
    """
    async with get_db_connection() as conn:
        # The project previously used a different jobs schema with several
        # required columns (id, progress, input_s3_key, and voice_id). Build
        # the insert from the columns that actually exist so existing Neon
        # databases remain usable while new installs use the lean schema.
        available_columns = {
            row["column_name"]
            for row in await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'jobs'
                """
            )
        }

        values = {
            "job_id": job_id,
            "original_filename": filename,
            "file_path": file_path,
            "status": "uploaded",
        }

        # Compatibility values satisfy the old schema without leaking an
        # absolute filesystem path or inventing a processing result.
        legacy_values = {
            "id": job_id,
            "progress": 0,
            "input_s3_key": file_path,
            "source_language": "en",
            "target_language": "",
            "voice_id": "",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }
        for column, value in legacy_values.items():
            if column in available_columns:
                values[column] = value

        columns = list(values)
        placeholders = ", ".join(f"${index}" for index in range(1, len(columns) + 1))
        await conn.execute(
            f"""
            INSERT INTO jobs ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT (job_id) DO NOTHING
            """,
            *(values[column] for column in columns),
        )
    
    return {
        "job_id": job_id,
        "original_filename": filename,
        "file_path": file_path,
        "status": "uploaded",
        "created_at": datetime.utcnow().isoformat(),
    }


async def log_step(
    job_id: str,
    step_name: str,
    status: str,
    details: Optional[dict] = None
):
    """
    Log a pipeline step to the audit trail.
    
    Args:
        job_id: Job identifier
        step_name: Name of the step
        status: Step status ('started', 'completed', 'failed')
        details: Additional details (stored as JSONB)
    """
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO audit_steps (job_id, step_name, status, details)
            VALUES ($1, $2, $3, $4)
            """,
            job_id, step_name, status, json.dumps(details or {}, default=str)
        )


async def log_user_decision(
    job_id: str,
    decision_type: str,
    decision_value: str,
    reason: Optional[str] = None
):
    """
    Log a user decision for accountability.
    
    Args:
        job_id: Job identifier
        decision_type: Type of decision
        decision_value: The decision made
        reason: Optional reason
    """
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO user_decisions (job_id, decision_type, decision_value, reason)
            VALUES ($1, $2, $3, $4)
            """,
            job_id, decision_type, decision_value, reason
        )


async def update_job_status(job_id: str, status: str, **kwargs):
    """
    Update job status and optional fields.
    
    Args:
        job_id: Job identifier
        status: New status
        **kwargs: Additional fields (target_language, risk_score, risk_level)
    """
    async with get_db_connection() as conn:
        if status == "completed":
            await conn.execute(
                "UPDATE jobs SET status = $1, completed_at = $2 WHERE job_id = $3",
                status, datetime.utcnow(), job_id
            )
        else:
            await conn.execute(
                "UPDATE jobs SET status = $1 WHERE job_id = $2",
                status, job_id
            )
        
        # Update additional fields if provided
        for key, value in kwargs.items():
            if key in [
                "target_language",
                "risk_score",
                "risk_level",
                "consent_confirmed",
                "consent_timestamp",
            ]:
                await conn.execute(
                    f"UPDATE jobs SET {key} = $1 WHERE job_id = $2",
                    value, job_id
                )


async def get_job(job_id: str) -> Optional[dict]:
    """
    Get job data by ID.
    
    Args:
        job_id: Job identifier
        
    Returns:
        Job data dictionary or None
    """
    async with get_db_connection() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM jobs WHERE job_id = $1",
            job_id
        )
        
        if row:
            result = dict(row)
            # Normalize JSONB across asyncpg codec configurations.
            result["state_data"] = decode_json_object(result.get("state_data"))
            return result
        return None


async def save_job_state(job_id: str, state_data: dict):
    """
    Save pipeline state data for a job with atomic updates.
    
    RACE CONDITION FIX: Uses SELECT FOR UPDATE to lock the row during
    read-modify-write operations, preventing concurrent overwrites.
    
    Args:
        job_id: Job identifier
        state_data: Dictionary of state to save (will be deep-merged with existing)
    """
    async with get_db_connection() as conn:
        # Use a transaction with row locking to prevent race conditions
        async with conn.transaction():
            # SELECT FOR UPDATE locks the row until transaction completes
            row = await conn.fetchrow(
                "SELECT state_data FROM jobs WHERE job_id = $1 FOR UPDATE",
                job_id
            )
            
            if not row:
                # Job doesn't exist, nothing to update
                return
            
            existing_state = decode_json_object(row["state_data"])
            
            # Deep merge: recursively update nested dicts
            def deep_merge(base: dict, update: dict) -> dict:
                """Recursively merge update into base, preserving nested structure."""
                result = base.copy()
                for key, value in update.items():
                    if (
                        key in result 
                        and isinstance(result[key], dict) 
                        and isinstance(value, dict)
                    ):
                        result[key] = deep_merge(result[key], value)
                    else:
                        result[key] = value
                return result
            
            merged_state = deep_merge(existing_state, state_data)
            
            # Write back the merged state
            await conn.execute(
                "UPDATE jobs SET state_data = $1 WHERE job_id = $2",
                json.dumps(merged_state, default=str),
                job_id
            )


async def get_audit_report(job_id: str) -> Optional[AuditReportResponse]:
    """
    Retrieve full audit report for a job.
    
    Args:
        job_id: Job identifier
        
    Returns:
        AuditReportResponse or None
    """
    async with get_db_connection() as conn:
        # Get job data
        job = await conn.fetchrow(
            "SELECT * FROM jobs WHERE job_id = $1",
            job_id
        )
        
        if not job:
            return None
        
        # Get audit steps
        steps_rows = await conn.fetch(
            """
            SELECT step_name, timestamp, status, details 
            FROM audit_steps 
            WHERE job_id = $1 
            ORDER BY timestamp ASC
            """,
            job_id
        )
        
        steps = [
            AuditStep(
                step_name=row["step_name"],
                timestamp=row["timestamp"],
                status=row["status"],
                details=json.loads(row["details"]) if isinstance(row["details"], str) else (row["details"] or {})
            )
            for row in steps_rows
        ]
        
        # Get user decisions
        decisions_rows = await conn.fetch(
            """
            SELECT decision_type, decision_value, reason, timestamp 
            FROM user_decisions 
            WHERE job_id = $1 
            ORDER BY timestamp ASC
            """,
            job_id
        )
        
        user_decisions = [
            {
                "decision_type": row["decision_type"],
                "decision_value": row["decision_value"],
                "reason": row["reason"],
                "timestamp": str(row["timestamp"]) if row["timestamp"] else None,
            }
            for row in decisions_rows
        ]

        state = decode_json_object(job.get("state_data"))

        transcript_segments = state.get("transcript", [])
        analysis_summary = None
        
        # Extract specific data from steps
        safety_analysis = None
        translation_data = None
        voice_synthesis = None
        
        for step in steps:
            if step.step_name == "safety_analysis" and step.status == "completed":
                safety_analysis = step.details
                if not analysis_summary:
                    analysis_summary = step.details.get("analysis_summary")
            elif step.step_name == "translation" and step.status == "completed":
                translation_data = step.details
            elif step.step_name == "tts_synthesis" and step.status == "completed":
                voice_synthesis = step.details

        # Normalize translation_data payload for UI consumers.
        if translation_data:
            normalized_translation = dict(translation_data)
            if "segments_translated" not in normalized_translation:
                normalized_translation["segments_translated"] = normalized_translation.get(
                    "segment_count", 0
                )
            if "average_confidence" not in normalized_translation:
                normalized_translation["average_confidence"] = 0.0
            if "source_language" not in normalized_translation:
                normalized_translation["source_language"] = "en"
            if "target_language" not in normalized_translation:
                normalized_translation["target_language"] = job.get("target_language") or "unknown"
            if "samples" not in normalized_translation:
                normalized_translation["samples"] = []
            translation_data = normalized_translation
        
        # Extract outputs from state_data (JSONB)
        outputs = {}
        outputs = {
            "video": state.get("output_video"),
            "audio": state.get("output_audio"),
            "audit": state.get("output_audit"),
        }
        
        return AuditReportResponse(
            job_id=job["job_id"],
            created_at=job["created_at"],
            completed_at=job["completed_at"],
            steps=steps,
            safety_analysis=safety_analysis,
            translation_data=translation_data,
            voice_synthesis=voice_synthesis,
            transcript_segments=transcript_segments,
            analysis_summary=analysis_summary,
            outputs=outputs,
            user_decisions=user_decisions,
        )


def export_audit_json(job_id: str) -> str:
    """
    Export audit report as JSON string (sync wrapper for compatibility).
    
    WARNING: This is a sync wrapper. For async contexts, use get_audit_report directly.
    
    Args:
        job_id: Job identifier
        
    Returns:
        JSON string of the audit report
    """
    import asyncio
    
    async def _get_report():
        report = await get_audit_report(job_id)
        if not report:
            return json.dumps({"error": "Job not found"})
        return report.model_dump_json(indent=2)
    
    # Check if we're already in an async context
    try:
        loop = asyncio.get_running_loop()
        # Already in async context - schedule as task (caller should await)
        # This is a fallback; callers should use get_audit_report directly
        import warnings
        warnings.warn("export_audit_json called in async context - use get_audit_report instead")
        return json.dumps({"error": "Use get_audit_report in async context"})
    except RuntimeError:
        # No event loop running - safe to use asyncio.run
        return asyncio.run(_get_report())


# ================================================================
# NORMALIZED TABLE FUNCTIONS - Efficient data access without JSONB
# ================================================================

async def save_transcripts(job_id: str, segments: list) -> int:
    """
    Save transcript segments to normalized table.
    
    Args:
        job_id: Job identifier
        segments: List of TranscriptSegment objects or dicts
        
    Returns:
        Number of segments saved
    """
    async with get_db_connection() as conn:
        count = 0
        for i, seg in enumerate(segments):
            text = seg.text if hasattr(seg, 'text') else seg.get('text', '')
            start = seg.start_time if hasattr(seg, 'start_time') else seg.get('start_time', 0)
            end = seg.end_time if hasattr(seg, 'end_time') else seg.get('end_time', 0)
            conf = seg.confidence if hasattr(seg, 'confidence') else seg.get('confidence', 0.9)
            
            await conn.execute("""
                INSERT INTO job_transcripts (job_id, segment_index, text, start_time, end_time, confidence)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (job_id, segment_index) DO UPDATE SET
                    text = EXCLUDED.text,
                    start_time = EXCLUDED.start_time,
                    end_time = EXCLUDED.end_time,
                    confidence = EXCLUDED.confidence
            """, job_id, i, text, start, end, conf)
            count += 1
        
        return count


async def get_transcripts(job_id: str) -> list[dict]:
    """Retrieve transcripts for a job."""
    async with get_db_connection() as conn:
        rows = await conn.fetch("""
            SELECT segment_index, text, start_time, end_time, confidence
            FROM job_transcripts
            WHERE job_id = $1
            ORDER BY segment_index
        """, job_id)
        
        return [dict(row) for row in rows]


async def save_translations(job_id: str, translations: list, language: str) -> int:
    """Save translations to normalized table."""
    async with get_db_connection() as conn:
        count = 0
        for i, trans in enumerate(translations):
            orig = trans.original_text if hasattr(trans, 'original_text') else trans.get('original_text', '')
            translated = trans.translated_text if hasattr(trans, 'translated_text') else trans.get('translated_text', '')
            start = trans.start_time if hasattr(trans, 'start_time') else trans.get('start_time')
            end = trans.end_time if hasattr(trans, 'end_time') else trans.get('end_time')
            conf = trans.confidence if hasattr(trans, 'confidence') else trans.get('confidence', 0.9)
            alts = trans.alternatives if hasattr(trans, 'alternatives') else trans.get('alternatives', [])
            ambig = trans.has_ambiguity if hasattr(trans, 'has_ambiguity') else trans.get('has_ambiguity', False)
            
            await conn.execute("""
                INSERT INTO job_translations 
                    (job_id, segment_index, original_text, translated_text, language, start_time, end_time, confidence, alternatives, has_ambiguity)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                ON CONFLICT (job_id, segment_index, language) DO UPDATE SET
                    translated_text = EXCLUDED.translated_text,
                    confidence = EXCLUDED.confidence
            """, job_id, i, orig, translated, language, start, end, conf, json.dumps(alts), ambig)
            count += 1
        
        return count


async def get_translations(job_id: str, language: str = None) -> list[dict]:
    """Retrieve translations for a job, optionally filtered by language."""
    async with get_db_connection() as conn:
        if language:
            rows = await conn.fetch("""
                SELECT segment_index, original_text, translated_text, language, start_time, end_time, confidence
                FROM job_translations
                WHERE job_id = $1 AND language = $2
                ORDER BY segment_index
            """, job_id, language)
        else:
            rows = await conn.fetch("""
                SELECT segment_index, original_text, translated_text, language, start_time, end_time, confidence
                FROM job_translations
                WHERE job_id = $1
                ORDER BY segment_index
            """, job_id)
        
        return [dict(row) for row in rows]


async def save_safety_flags(job_id: str, flags: list) -> int:
    """Save safety flags to normalized table."""
    async with get_db_connection() as conn:
        # Clear existing flags for this job
        await conn.execute("DELETE FROM job_safety_flags WHERE job_id = $1", job_id)
        
        count = 0
        for flag in flags:
            cat = flag.category.value if hasattr(flag.category, 'value') else str(flag.category) if hasattr(flag, 'category') else flag.get('category', 'unknown')
            sev = flag.severity.value if hasattr(flag.severity, 'value') else str(flag.severity) if hasattr(flag, 'severity') else flag.get('severity', 'low')
            text_seg = flag.text_segment if hasattr(flag, 'text_segment') else flag.get('text_segment')
            start = flag.start_time if hasattr(flag, 'start_time') else flag.get('start_time')
            end = flag.end_time if hasattr(flag, 'end_time') else flag.get('end_time')
            explanation = flag.explanation if hasattr(flag, 'explanation') else flag.get('explanation')
            conf = flag.confidence if hasattr(flag, 'confidence') else flag.get('confidence', 0.8)
            
            await conn.execute("""
                INSERT INTO job_safety_flags (job_id, category, severity, text_segment, start_time, end_time, explanation, confidence)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, job_id, cat, sev, text_seg, start, end, explanation, conf)
            count += 1
        
        return count


async def get_safety_flags(job_id: str, severity: str = None) -> list[dict]:
    """Retrieve safety flags for a job, optionally filtered by severity."""
    async with get_db_connection() as conn:
        if severity:
            rows = await conn.fetch("""
                SELECT category, severity, text_segment, start_time, end_time, explanation, confidence
                FROM job_safety_flags
                WHERE job_id = $1 AND severity = $2
                ORDER BY created_at
            """, job_id, severity)
        else:
            rows = await conn.fetch("""
                SELECT category, severity, text_segment, start_time, end_time, explanation, confidence
                FROM job_safety_flags
                WHERE job_id = $1
                ORDER BY created_at
            """, job_id)
        
        return [dict(row) for row in rows]


async def search_transcripts(query: str, limit: int = 50) -> list[dict]:
    """
    Full-text search across all job transcripts.
    
    Args:
        query: Search query string
        limit: Maximum results to return
        
    Returns:
        List of matching transcripts with job_id
    """
    async with get_db_connection() as conn:
        rows = await conn.fetch("""
            SELECT job_id, segment_index, text, start_time, end_time,
                   ts_rank(to_tsvector('english', text), plainto_tsquery('english', $1)) as rank
            FROM job_transcripts
            WHERE to_tsvector('english', text) @@ plainto_tsquery('english', $1)
            ORDER BY rank DESC
            LIMIT $2
        """, query, limit)
        
        return [dict(row) for row in rows]
