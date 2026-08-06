# Frontend - VoxBridge

React frontend for the VoxBridge video dubbing platform.

---

## Setup

### Prerequisites

- Node.js 18+

### Installation

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

### Access

Development server runs at: http://localhost:5173

---

## Project Structure

```
frontend/
├── src/
│   ├── main.jsx          # React entry point
│   ├── App.jsx           # Main app with routing
│   ├── index.css         # Global styles
│   ├── pages/
│   │   ├── UploadPage.jsx    # Video upload interface
│   │   ├── AnalysisPage.jsx  # Safety analysis dashboard
│   │   ├── DubbingPage.jsx   # Approval and dubbing config
│   │   └── ResultsPage.jsx   # Final results and audit
│   └── components/
│       └── SafetyDashboard.jsx  # Reusable safety display
├── index.html
├── vite.config.js
└── package.json
```

---

## Pages

### Upload Page

- Drag-and-drop video upload
- File type validation (MP4, MOV, AVI)
- Progress indicator
- Safety preview with preloaded transcript samples; previews do not create jobs or artifacts

### Analysis Page

- Safety analysis dashboard
- Risk score display
- Flag details with explanations
- Transcript with highlighted issues

### Dubbing Page

- Target language selection
- Consent confirmation
- Safety override acknowledgment
- Progress tracking

### Results Page

- Download buttons (video, audio, audit)
- Complete audit trail
- Processing step summary
- Metrics overview

---

## Design System

### Colors

- Primary: Blue (#2563eb)
- Success: Green (#059669)
- Warning: Amber (#d97706)
- Danger: Red (#dc2626)
- Neutral: Gray scale

### Typography

- Font: Inter (Google Fonts)
- Sizes: xs to 3xl scale

### Components

- Cards with shadows
- Progress bars
- Risk badges (low/medium/high)
- Step indicators
- Alert boxes

---

## Demo and real provider modes

The frontend sample buttons are preview-only:

1. **Safe Content Demo**: Educational content that passes all checks
2. **Flagged Content Demo**: Content with toxicity and bias flags

They do not simulate dubbing or claim downloadable results. To verify the
complete local workflow, start the backend with:

```bash
DEMO_MODE=true TTS_PROVIDER=fixture uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Then upload a real video from the Upload page. This exercises the backend's
real job, PostgreSQL, FFmpeg, consent, audit, and download paths while using
clearly labeled local fixture transcript/translation/tone providers.
