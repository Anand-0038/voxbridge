# VoxBridge

Responsible AI–Powered Multilingual Video Dubbing Platform

---

## What This Is

VoxBridge is a video dubbing system that prioritizes **safety, transparency, and accountability**.

Instead of blindly translating and dubbing content, it analyzes videos for harmful content *before* they can be amplified across languages.

---

## Why This Matters

AI dubbing tools today:
- Spread misinformation faster
- Amplify harmful content across cultures
- Provide no audit trail
- Ignore voice ethics

VoxBridge fixes this by introducing a **Responsible AI safety layer**.

---

## Core Capabilities

- Pre-dubbing content moderation
- Bias, toxicity, and misinformation detection
- Translation transparency with confidence scores
- Ethical voice synthesis with consent enforcement
- End-to-end audit logging

---

## Architecture Summary

```
React Frontend
       |
       v
FastAPI Gateway
       |
       v
Service Layer
  - Media Processing
  - Safety Analysis (Core)
  - Translation
  - Voice Synthesis
  - Audit Logging
       |
       v
Final Dubbed Video + Compliance Logs
```

---

## Technology Stack

| Layer | Tech |
|------|-----|
| Frontend | React + Vite |
| Backend | FastAPI (Python 3.11) |
| AI | Gemini API |
| TTS | ElevenLabs |
| Media | ffmpeg, MoviePy |
| Database | PostgreSQL |
| Package Mgmt | uv |

---

## Responsible AI Focus

This is **not** a dubbing tool with safety added later.  
Safety is the **first-class feature**.

Every AI decision:
- Is explainable
- Is logged
- Can be audited
- Can be overridden only with acknowledgment

---

## Quick Start

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Access Points

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs

---

## Demo Scenarios

The frontend's safe and flagged samples are safety previews only; they do not
create fake jobs or downloadable artifacts. For a complete local artifact
demo, run the backend with the explicit fixture provider and upload a real
video:

```bash
cd backend
DEMO_MODE=true TTS_PROVIDER=fixture uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

This still exercises PostgreSQL, FFmpeg extraction/mixing/merge, consent, and
audit/download endpoints. The transcript, translation, and tone audio are
labeled fixtures rather than external-provider output.

Real mode uses Gemini and ElevenLabs. Provider failures are surfaced as job
errors; no fabricated voice fallback is used.

Judges are encouraged to review audit logs.

---

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/upload-video` | POST | Upload video file (MP4, MOV, AVI, MKV, WEBM) |
| `/api/analyze-content` | POST | Run safety checks, returns risk report |
| `/api/approve-and-dub` | POST | Proceed with dubbing after approval |
| `/api/audit-report/{job_id}` | GET | Retrieve audit logs and compliance data |
| `/api/job-status/{job_id}` | GET | Check current job status |
| `/api/download/{type}/{job_id}` | GET | Download video, audio, or audit file |

---

## Documentation

- `ARCHITECTURE.md` — system design details

---

## License

MIT License
