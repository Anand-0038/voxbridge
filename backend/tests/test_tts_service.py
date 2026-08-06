import asyncio
from pathlib import Path

import pytest

from app.models.schemas import TranslationSegment
from app.services.tts_service import synthesize_speech_parallel


def _translation() -> list[TranslationSegment]:
    return [
        TranslationSegment(
            original_text="Hello",
            translated_text="Hola",
            start_time=0.0,
            end_time=1.0,
            confidence=1.0,
        )
    ]


def test_fixture_tts_is_explicit_and_produces_audible_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("TTS_PROVIDER", "fixture")
    monkeypatch.setenv("PROCESSED_DIR", str(tmp_path))

    segments = asyncio.run(
        synthesize_speech_parallel(
            _translation(),
            "es",
            consent_verified=True,
            output_prefix="test-job",
        )
    )

    assert len(segments) == 1
    artifact = Path(segments[0]["audio_path"])
    assert artifact.exists()
    assert artifact.stat().st_size > 0
    assert segments[0]["metadata"]["demo_fixture"] is True
    assert segments[0]["metadata"]["service"] == "Demo fixture (FFmpeg)"


def test_tts_requires_consent(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("TTS_PROVIDER", "fixture")

    with pytest.raises(ValueError, match="explicit user consent"):
        asyncio.run(
            synthesize_speech_parallel(
                _translation(),
                "es",
                consent_verified=False,
            )
        )


def test_fixture_provider_is_rejected_in_real_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TTS_PROVIDER", "fixture")

    with pytest.raises(RuntimeError, match="requires DEMO_MODE=true"):
        asyncio.run(
            synthesize_speech_parallel(
                _translation(),
                "es",
                consent_verified=True,
            )
        )
