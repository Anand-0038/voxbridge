import asyncio
import io
import wave
from pathlib import Path

import pytest

from app.models.schemas import TranslationSegment
from app.services.tts_service import (
    _prepare_audio_payload,
    _resolve_tts_provider,
    _synthesize_with_openai,
    synthesize_speech_parallel,
)


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


def test_gemini_pcm_payload_is_wrapped_as_wav():
    payload, extension = _prepare_audio_payload(
        b"\x00\x00" * 240,
        "audio/L16;codec=pcm;rate=24000",
    )

    assert extension == "wav"
    with wave.open(io.BytesIO(payload), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 24000
        assert wav_file.getnframes() == 240


def test_openai_provider_generates_mp3_request(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("TTS_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
    monkeypatch.setenv("OPENAI_TTS_VOICE", "alloy")
    captured = {}

    class Response:
        status_code = 200
        content = b"mp3-audio"
        text = ""
        headers = {"Content-Type": "audio/mpeg"}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["authorization"] = kwargs["headers"]["Authorization"]
        return Response()

    monkeypatch.setattr("requests.post", fake_post)

    assert _resolve_tts_provider() == "openai"
    audio, mime = _synthesize_with_openai("Hola", "Spanish")

    assert audio == b"mp3-audio"
    assert mime == "audio/mpeg"
    assert captured["url"] == "https://api.openai.com/v1/audio/speech"
    assert captured["json"]["model"] == "gpt-4o-mini-tts"
    assert captured["json"]["voice"] == "alloy"
    assert captured["json"]["response_format"] == "mp3"
    assert captured["authorization"] == "Bearer test-key"
