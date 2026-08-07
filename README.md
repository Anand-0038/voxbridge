# VoxBridge

Turn one creator video into a synchronized multilingual cut without rebuilding
the edit by hand.

![VoxBridge upload workflow](docs/screenshots/voxbridge-home.png)

## Creator Outcome

Upload a video or import a public YouTube URL, choose a target language, and
download three usable deliverables:

- A dubbed MP4 with speech aligned to the original timeline
- A separate dubbed audio track for further editing
- A JSON audit report with the processing history

VoxBridge brings transcription, translation, voice generation, timing, and
final media assembly into one workflow. Creators and small editing teams can
review one completed cut instead of coordinating several disconnected tools
and manually rebuilding the audio timeline.

## Verified Working Result

The core flow has been tested with real provider calls and real media output,
not mocked success states.

| Check | Verified result |
|---|---|
| Source | 5:55 creator video |
| Localization | English to Hindi |
| Voice generation | Real Gemini TTS with `DEMO_MODE=false` |
| Timeline integrity | Source and dubbed output both `355.966667s` |
| Final media | AV1 video stream plus AAC dubbed audio stream |
| Downloads | Dubbed MP4, MP3 audio, and JSON audit report |
| Backend verification | 39 tests passed |

![VoxBridge completed dubbing result](docs/screenshots/voxbridge-results.png)

## The Creator Workflow

1. Upload a local video or import one public YouTube video.
2. VoxBridge extracts and transcribes speech with timestamps.
3. The creator reviews the transcript and any content warnings.
4. The creator selects a target language and confirms voice-generation consent.
5. VoxBridge translates each timestamped segment and generates multilingual speech.
6. FFmpeg fits the new speech to the original edit and preserves the full video duration.
7. The creator previews and downloads the video, audio, and processing report.

## What Makes It Useful

- One upload-to-download localization workflow
- Timestamp-aware speech placement instead of naive audio concatenation
- Automatic handling of silence, segment gaps, and speech-duration mismatch
- Output validation that rejects missing audio or truncated video
- Local file upload and public YouTube URL intake
- Gemini, OpenAI, and ElevenLabs TTS provider support
- Downloadable assets that remain editable by the creator or editor

## Trust Layer

Safety is a checkpoint, not the product pitch. Before dubbing, VoxBridge flags
potential toxicity, bias, misinformation risk, and cultural-sensitivity issues.
The creator remains in control: flagged content requires acknowledgment, voice
generation requires consent, and provider failures are shown instead of being
replaced with fabricated output.

## Architecture

```text
Video upload / public URL
          |
          v
FastAPI job pipeline
          |
          +--> timestamped transcription
          +--> content review
          +--> segment translation
          +--> multilingual TTS
          +--> FFmpeg timeline placement and validation
          |
          v
Dubbed MP4 + audio track + audit report
```

## Technology

| Layer | Technology |
|---|---|
| Frontend | React, Vite |
| Backend | FastAPI, Python 3.11 |
| AI | Gemini API |
| TTS | Gemini, OpenAI, or ElevenLabs |
| Media | FFmpeg |
| Persistence | SQLite locally, PostgreSQL-ready adapter |
| Package management | uv, npm |

## Run Locally

### Backend

```bash
cd backend
uv sync
cp .env.example .env
# Add Gemini credentials and keep:
# DEMO_MODE=false
# TTS_PROVIDER=gemini
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`.

## Judge Walkthrough

The complete product can be evaluated in a short recording or local run:

1. Show the upload screen and select a source video.
2. Show timestamped transcription and content review.
3. Select Hindi and confirm voice consent.
4. Start dubbing and show real pipeline progress.
5. Preview the completed result.
6. Download the dubbed MP4 and audit report.
7. Compare source and output duration with FFprobe.

The recommended submission demo is a 2-4 minute screen recording following
these steps. The current recordings are available here:

## Demo Recordings

- [Vimeo demo](https://vimeo.com/1216336577?share=copy&fl=sv&fe=ci)
- [Loom walkthrough](https://www.loom.com/share/2d1a26ee868746a386d2291044a9412b)

## API Reference

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/upload-video` | POST | Upload source media |
| `/api/import-youtube` | POST | Acquire one public YouTube URL |
| `/api/analyze-content` | POST | Transcribe and review content |
| `/api/approve-and-dub` | POST | Translate and generate the dubbed cut |
| `/api/job-status/{job_id}` | GET | Read live pipeline progress |
| `/api/audit-report/{job_id}` | GET | Retrieve processing evidence |
| `/api/download/{type}/{job_id}` | GET | Download video, audio, or report |

## Documentation

- `ARCHITECTURE.md` - detailed system design
- `backend/README.md` - backend configuration and API notes
- `frontend/README.md` - frontend commands and behavior

## License

MIT License
