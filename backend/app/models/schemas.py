"""
Pydantic models for request and response validation.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, StrictBool


class RiskLevel(str, Enum):
    """Risk level classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FlagCategory(str, Enum):
    """Safety flag categories."""

    TOXICITY = "toxicity"
    BIAS = "bias"
    MISINFORMATION = "misinformation"
    CULTURAL_SENSITIVITY = "cultural_sensitivity"
    AGE_INAPPROPRIATE = "age_inappropriate"


# Request Models


class AnalyzeContentRequest(BaseModel):
    """Request to analyze content for safety."""

    job_id: str = Field(..., description="Job ID from video upload")


class ApproveAndDubRequest(BaseModel):
    """Request to approve and start dubbing."""

    job_id: str = Field(..., description="Job ID from video upload")
    target_language: str = Field(
        ..., description="Target language code (e.g., 'es', 'fr')"
    )
    consent_confirmed: StrictBool = Field(
        ..., description="User consent for AI voice synthesis"
    )
    override_safety: StrictBool = Field(
        False, description="Override safety flags with acknowledgment"
    )


class YouTubeImportRequest(BaseModel):
    """Request to acquire one public YouTube video for local processing."""

    url: str = Field(..., min_length=12, max_length=2048)


# Response Models


class UploadResponse(BaseModel):
    """Response after video upload."""

    job_id: str
    status: str
    message: str
    filename: str


class SafetyFlag(BaseModel):
    """A single safety flag with details."""

    category: FlagCategory
    severity: RiskLevel
    text_segment: str
    start_time: float | None = None
    end_time: float | None = None
    explanation: str
    confidence: float = Field(..., ge=0, le=1)


class TranscriptSegment(BaseModel):
    """A segment of the transcript with timing."""

    text: str
    start_time: float
    end_time: float
    confidence: float = Field(..., ge=0, le=1)


class AnalysisResponse(BaseModel):
    """Response from content safety analysis."""

    job_id: str
    risk_score: int = Field(..., ge=0, le=100)
    risk_level: RiskLevel
    flags: list[SafetyFlag]
    transcript_segments: list[TranscriptSegment]
    analysis_summary: str


class TranslationSegment(BaseModel):
    """A translated segment with transparency data and timing."""

    original_text: str
    translated_text: str
    start_time: float = 0.0  # Preserved from transcript for audio sync
    end_time: float = 0.0  # Preserved from transcript for audio sync
    confidence: float = Field(..., ge=0, le=1)
    alternatives: list[str] = Field(default_factory=list)
    has_ambiguity: bool = False


class DubbingStatusResponse(BaseModel):
    """Response for dubbing status check."""

    job_id: str
    status: str
    progress: int = Field(..., ge=0, le=100)
    message: str
    current_step: str | None = None


class DubbingCompleteResponse(BaseModel):
    """Response when dubbing is complete."""

    job_id: str
    status: str
    video_url: str
    audio_url: str
    audit_url: str
    message: str


class AuditStep(BaseModel):
    """A single step in the audit log."""

    step_name: str
    timestamp: datetime
    status: str
    details: dict = Field(default_factory=dict)


class AuditReportResponse(BaseModel):
    """Full audit report for a job."""

    job_id: str
    created_at: datetime
    completed_at: datetime | None = None
    steps: list[AuditStep]
    safety_analysis: dict | None = None
    translation_data: dict | None = None
    voice_synthesis: dict | None = None
    transcript_segments: list[TranscriptSegment] = Field(default_factory=list)
    analysis_summary: str | None = None
    outputs: dict | None = None
    user_decisions: list[dict] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str
    job_id: str | None = None
