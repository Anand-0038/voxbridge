# VoxBridge - Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              VOXBRIDGE                              │
│                  Responsible AI Video Dubbing Platform                    │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐      ┌─────────────────────────────────────────────────┐
│                 │      │                   BACKEND                        │
│    FRONTEND     │      │                  (FastAPI)                       │
│    (React)      │      │                                                  │
│                 │ HTTP │  ┌───────────────────────────────────────────┐  │
│  ┌───────────┐  │ ───► │  │              API GATEWAY                  │  │
│  │  Upload   │  │      │  │         /api/upload-video                 │  │
│  │   Page    │  │      │  │         /api/analyze-content              │  │
│  └───────────┘  │      │  │         /api/approve-and-dub              │  │
│  ┌───────────┐  │      │  │         /api/audit-report                 │  │
│  │ Analysis  │  │ ◄─── │  └───────────────────────────────────────────┘  │
│  │   Page    │  │ JSON │                      │                          │
│  └───────────┘  │      │                      ▼                          │
│  ┌───────────┐  │      │  ┌───────────────────────────────────────────┐  │
│  │ Dubbing   │  │      │  │             SERVICE LAYER                  │  │
│  │   Page    │  │      │  │                                            │  │
│  └───────────┘  │      │  │  ┌─────────────────┐  ┌────────────────┐  │  │
│  ┌───────────┐  │      │  │  │ Media Service   │  │ Transcription  │  │  │
│  │ Results   │  │      │  │  │ (ffmpeg)        │  │ Service        │  │  │
│  │   Page    │  │      │  │  └─────────────────┘  └────────────────┘  │  │
│  └───────────┘  │      │  │  ┌─────────────────┐  ┌────────────────┐  │  │
│                 │      │  │  │ SAFETY SERVICE  │  │ Translation    │  │  │
│                 │      │  │  │ ★ CORE FEATURE  │  │ Service        │  │  │
│                 │      │  │  └─────────────────┘  └────────────────┘  │  │
│                 │      │  │  ┌─────────────────┐  ┌────────────────┐  │  │
│                 │      │  │  │ TTS Service     │  │ Audit Service  │  │  │
│                 │      │  │  │ (ElevenLabs)    │  │ (Postgres)     │  │  │
│                 │      │  │  └─────────────────┘  └────────────────┘  │  │
│                 │      │  └───────────────────────────────────────────┘  │
└─────────────────┘      └─────────────────────────────────────────────────┘
         │                                    │
         │                                    │
         ▼                                    ▼
┌─────────────────┐              ┌─────────────────────────────────────────┐
│  User Browser   │              │           EXTERNAL SERVICES             │
│  localhost:5173 │              │                                         │
└─────────────────┘              │  ┌─────────────┐    ┌─────────────────┐ │
                                 │  │  Gemini AI  │    │   ElevenLabs    │ │
                                 │  │  - Analysis │    │   - Voice TTS   │ │
                                 │  │  - Translate│    │   - Multilingual│ │
                                 │  └─────────────┘    └─────────────────┘ │
                                 └─────────────────────────────────────────┘
```

---

## Data Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           VIDEO DUBBING PIPELINE                          │
└──────────────────────────────────────────────────────────────────────────┘

     ┌─────────┐                                                    
     │ Video   │                                                    
     │ Upload  │                                                    
     └────┬────┘                                                    
          │                                                         
          ▼                                                         
     ┌─────────┐     ┌─────────┐     ┌─────────────────────────────┐
     │  Audio  │ ──► │Transcribe│ ──► │     RESPONSIBLE AI          │
     │ Extract │     │ (Gemini) │     │     SAFETY CHECKS           │
     │ (ffmpeg)│     │          │     │                             │
     └─────────┘     └──────────┘     │  • Toxicity Detection       │
                                      │  • Bias Analysis            │
                                      │  • Misinformation Flagging  │
                                      │  • Cultural Sensitivity     │
                                      └──────────────┬──────────────┘
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │       SAFETY REPORT          │
                                      │  • Risk Score (0-100)        │
                                      │  • Category Flags            │
                                      │  • Explanations              │
                                      │  • Highlighted Segments      │
                                      └──────────────┬───────────────┘
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │     USER DECISION POINT      │
                                      │                              │
                                      │  ┌────────┐    ┌──────────┐  │
                                      │  │ Reject │    │ Approve  │  │
                                      │  │  ✗     │    │  (w/ack) │  │
                                      │  └────────┘    └────┬─────┘  │
                                      └─────────────────────┼────────┘
                                                            │
                                                            ▼
                                      ┌──────────────────────────────┐
                                      │    TRANSLATION + TTS         │
                                      │                              │
                                      │  • Translate (with scores)   │
                                      │  • Voice Synthesis           │
                                      │  • Consent Verified          │
                                      │  • AI Audio Labeled          │
                                      └──────────────┬───────────────┘
                                                     │
                                                     ▼
                                      ┌──────────────────────────────┐
                                      │      FINAL OUTPUT            │
                                      │                              │
                                      │  • Dubbed Video              │
                                      │  • Audit Report (JSON)       │
                                      │  • Compliance Log            │
                                      └──────────────────────────────┘
```

---

## Service Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                         SERVICE LAYER DETAIL                            │
└────────────────────────────────────────────────────────────────────────┘

┌─────────────────────┐
│   MEDIA SERVICE     │
│   media_service.py  │
├─────────────────────┤        
│ • extract_audio()   │────────► ffmpeg
│ • merge_audio()     │          subprocess
│ • get_duration()    │
│ • concat_segments() │ <--- Timestamp-aware with silence padding
└─────────────────────┘

┌─────────────────────┐
│ TRANSCRIPTION SVC   │
│ transcription_svc.py│
├─────────────────────┤
│ • transcribe_audio()│────────► Gemini API
│ • detect_language() │          Audio upload
│ • get_timestamps()  │
└─────────────────────┘

┌─────────────────────┐
│ ★ SAFETY SERVICE    │        ┌──────────────────────────┐
│   safety_service.py │        │   GEMINI SAFETY PROMPT   │
├─────────────────────┤        │                          │
│ • analyze_content() │───────►│ "You are an AI safety    │
│ • calculate_risk()  │        │  auditor. Analyze for:   │
│ • get_risk_level()  │        │  - Toxicity              │
│                     │◄───────│  - Bias                  │
│ Returns:            │  JSON  │  - Misinformation        │
│ • risk_score        │        │  - Cultural sensitivity" │
│ • flags[]           │        └──────────────────────────┘
│ • explanations[]    │
└─────────────────────┘

┌─────────────────────┐
│ TRANSLATION SERVICE │
│ translation_svc.py  │
├─────────────────────┤
│ • translate()       │────────► Gemini API
│ • get_confidence()  │          Translation
│ • get_alternatives()│          + transparency data
└─────────────────────┘

┌─────────────────────┐
│   TTS SERVICE       │
│   tts_service.py    │
├─────────────────────┤
│ • synthesize()      │────────► ElevenLabs API
│ • verify_consent()  │          Voice synthesis
│ • add_metadata()    │
│                     │
│ CONSENT REQUIRED ★  │
└─────────────────────┘

┌─────────────────────┐
│   AUDIT SERVICE     │
│   audit_service.py  │
├─────────────────────┤
│ • create_job()      │────────► PostgreSQL DB
│ • log_step()        │          (asyncpg)
│ • get_report()      │
│ • export_json()     │
└─────────────────────┘
```

---

## Database Schema

```
┌────────────────────────────────────────────────────────────────────────┐
│                          POSTGRESQL DATABASE                            │
│                             (Neon / Local)                              │
└────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────┐
│          JOBS               │
├─────────────────────────────┤
│ job_id         TEXT PK      │
│ original_file  TEXT         │
│ file_path      TEXT         │
│ status         TEXT         │
│ created_at     TIMESTAMP    │
│ completed_at   TIMESTAMP    │
│ target_lang    TEXT         │
│ risk_score     INTEGER      │
│ risk_level     TEXT         │
│ state_data     JSONB        │ ◄── SINGLE SOURCE OF TRUTH
└─────────────────────────────┘
  NOTE: All file paths in DB are relative.
  Resolve to absolute when reading.
            │
            │ 1:N
            ▼
┌─────────────────────────────┐
│       AUDIT_STEPS           │
├─────────────────────────────┤
│ id             INTEGER PK   │
│ job_id         TEXT FK      │
│ step_name      TEXT         │
│ status         TEXT         │
│ details        JSON         │
│ timestamp      TIMESTAMP    │
└─────────────────────────────┘
            │
            │ 1:N
            ▼
┌─────────────────────────────┐
│     USER_DECISIONS          │
├─────────────────────────────┤
│ id             INTEGER PK   │
│ job_id         TEXT FK      │
│ decision_type  TEXT         │
│ decision_value TEXT         │
│ reason         TEXT         │
│ timestamp      TIMESTAMP    │
└─────────────────────────────┘
```

---

## API Endpoints

```
┌────────────────────────────────────────────────────────────────────────┐
│                           REST API                                      │
└────────────────────────────────────────────────────────────────────────┘

POST /api/upload-video
├── Request:  multipart/form-data (video file)
└── Response: { job_id, status, message }

POST /api/analyze-content
├── Request:  { job_id }
└── Response: { risk_score, risk_level, flags[], transcript[] }

POST /api/approve-and-dub
├── Request:  { job_id, target_language, consent_confirmed, override_safety }
└── Response: { status, progress, message }

GET  /api/job-status/{job_id}
└── Response: { status, progress, current_step }

GET  /api/audit-report/{job_id}
└── Response: { job_id, steps[], safety_analysis, user_decisions[] }

GET  /api/demo/safe-transcript
└── Response: { transcript[] } (for demo mode)

GET  /api/demo/flagged-transcript
└── Response: { transcript[], expected_flags[] } (for demo mode)
```

---

## Technology Stack

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TECHNOLOGY STACK                                 │
└─────────────────────────────────────────────────────────────────────────┘

FRONTEND                    BACKEND                     EXTERNAL
─────────────────────────────────────────────────────────────────────────

┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│   React 18   │           │  FastAPI     │           │  Gemini AI   │
│   + Vite     │           │  Python 3.11 │           │  API         │
└──────────────┘           └──────────────┘           └──────────────┘

┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│ React Router │           │   Pydantic   │           │  ElevenLabs  │
│   v6         │           │   v2         │           │  TTS API     │
└──────────────┘           └──────────────┘           └──────────────┘

┌──────────────┐           ┌──────────────┐           ┌──────────────┐
│  Vanilla CSS │           │  PostgreSQL  │           │   ffmpeg     │
│  (custom)    │           │  Database    │           │  (local)     │
└──────────────┘           └──────────────┘           └──────────────┘

                           ┌──────────────┐
                           │   MoviePy    │
                           │   (video)    │
                           └──────────────┘
```
