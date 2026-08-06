# Backend - VoxBridge

FastAPI backend for the VoxBridge video dubbing platform.

---

## Setup

### Prerequisites

- Python 3.11+
- ffmpeg installed and in PATH
- Optional: rubberband CLI; FFmpeg's native rubberband filter is used when the CLI is unavailable
- Gemini API key
- ElevenLabs API key

### Installation

```bash
# Create/update the uv-managed environment from pyproject.toml and uv.lock
uv sync

# Activate it when using commands directly (optional with `uv run`)
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Copy environment template and add your API keys
cp .env.example .env
```

### Configuration

Edit `.env` file with your credentials:

```
GEMINI_API_KEY=your_gemini_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key
DEMO_MODE=false
TTS_PROVIDER=elevenlabs
```

For a local artifact-producing demo that does not call external AI providers,
run the backend with `DEMO_MODE=true TTS_PROVIDER=fixture`. The fixture uses
the real upload, PostgreSQL, FFmpeg, consent, audit, and download paths, but
its transcript, translation, and tone audio are explicitly labeled fixtures;
it is not an ElevenLabs voice.

### Running

```bash
# Development
uv run uvicorn app.main:app --reload

# Production
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Real mode requires usable Gemini and ElevenLabs credentials. The application
fails the job rather than substituting fabricated audio when a provider fails.
An ElevenLabs account that cannot use the configured voice will return a
provider payment/plan error; that must be resolved in the ElevenLabs account
before claiming a real voice result.

---

## API Documentation

When running, access interactive docs at: http://localhost:8000/docs

### Endpoints

#### POST /upload-video

Upload a video file for processing.

**Request:** Multipart form data with video file
**Response:**
```json
{
  "job_id": "uuid-string",
  "status": "uploaded",
  "message": "Video uploaded successfully"
}
```

#### POST /analyze-content

Run Responsible AI safety checks on transcript.

**Request:**
```json
{
  "job_id": "uuid-string"
}
```

**Response:**
```json
{
  "job_id": "uuid-string",
  "risk_score": 25,
  "risk_level": "low",
  "flags": [],
  "explanations": [],
  "transcript_segments": [...]
}
```

#### POST /approve-and-dub

Proceed with dubbing after user approval.

**Request:**
```json
{
  "job_id": "uuid-string",
  "target_language": "es",
  "consent_confirmed": true
}
```

**Response:**
```json
{
  "job_id": "uuid-string",
  "status": "processing",
  "message": "Dubbing started"
}
```

#### GET /audit-report/{job_id}

Retrieve audit logs and compliance data.

**Response:**
```json
{
  "job_id": "uuid-string",
  "created_at": "timestamp",
  "steps": [...],
  "safety_analysis": {...},
  "translation_data": {...},
  "voice_synthesis": {...}
}
```

---

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI application entry
│   ├── api/
│   │   └── routes.py        # API endpoint handlers
│   ├── services/
│   │   ├── media_service.py       # Audio/video processing
│   │   ├── transcription_service.py  # Speech-to-text
│   │   ├── safety_service.py      # Responsible AI analysis
│   │   ├── translation_service.py # Language translation
│   │   ├── tts_service.py         # Text-to-speech
│   │   └── audit_service.py       # Audit logging
│   ├── models/
│   │   └── schemas.py       # Pydantic data models
│   └── utils/
│       └── helpers.py       # Utility functions
├── storage/                 # Local file storage
│   ├── uploads/            # Uploaded videos
│   ├── processed/          # Processed media
│   └── outputs/            # Final dubbed videos
├── .env.example            # Environment template
└── requirements.txt        # Python dependencies
```

---

## Services Overview

### Media Service

Handles video and audio processing using ffmpeg:
- Extract audio from video
- Merge new audio with video
- Preserve background music
- Sync audio timing

### Transcription Service

Converts speech to text using Gemini:
- Generate timestamps per segment
- Support multiple source languages
- Output structured transcript

### Safety Service

Core Responsible AI analysis:
- Toxicity detection
- Bias identification
- Misinformation flagging
- Cultural sensitivity checks
- Natural-language explanations

### Translation Service

Language translation with transparency:
- Translate transcript segments
- Generate confidence scores
- Detect ambiguities
- Suggest alternatives

### TTS Service

Text-to-speech with ethical safeguards:
- Require consent confirmation
- Generate audio via ElevenLabs
- Add AI-generated metadata
- Log voice parameters
- Use the explicit FFmpeg fixture only in demo mode

### Audit Service

Comprehensive logging:
- Log all pipeline steps
- Store to PostgreSQL
- Export JSON format
- Generate compliance reports
