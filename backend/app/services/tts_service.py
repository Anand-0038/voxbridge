"""
Text-to-Speech service with ethical safeguards.

Supports the following provider modes via TTS_PROVIDER:
- fixture: deterministic FFmpeg beep used in demo mode
- elevenlabs: production ElevenLabs provider
- gemini: Google Gemini audio output
- openai: OpenAI speech generation
"""

import base64
import io
import json
import os
import re
import uuid
import wave
from typing import Optional

from app.models.schemas import TranslationSegment
from app.utils import get_language_name, get_language_voice_id
from app.utils.helpers import get_absolute_path
from app.utils.genai_client import GenAIClient


def _resolve_tts_provider() -> str:
    """Resolve and validate TTS provider selection from environment."""
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    provider = os.getenv("TTS_PROVIDER", "fixture" if demo_mode else "elevenlabs").strip().lower()

    if provider in {"fixture", "demo"}:
        if not demo_mode:
            raise RuntimeError("The fixture TTS provider requires DEMO_MODE=true")
        return "fixture"

    if provider not in {"elevenlabs", "gemini", "openai"}:
        raise RuntimeError(f"Unsupported TTS_PROVIDER: {provider}")

    return provider


def _get_tts_provider_config() -> dict:
    """Return provider-level metadata used for status/health reporting."""
    provider = os.getenv(
        "TTS_PROVIDER",
        "fixture" if os.getenv("DEMO_MODE", "false").lower() == "true" else "elevenlabs",
    ).strip().lower()

    if provider in {"fixture", "demo"}:
        return {"provider": "fixture", "service": "Demo fixture", "model": "ffmpeg_sine"}

    if provider == "gemini":
        model = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-audio").strip()
        return {"provider": "gemini", "service": "Gemini TTS", "model": model}

    if provider == "openai":
        model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
        return {"provider": "openai", "service": "OpenAI TTS", "model": model}

    return {"provider": "elevenlabs", "service": "ElevenLabs", "model": "eleven_multilingual_v2"}


def _safe_ext_from_mime(mime: str | None) -> str:
    """Map a mime type into a practical file extension."""
    if not mime:
        return "mp3"

    mime = mime.lower()
    if "wav" in mime:
        return "wav"
    if "ogg" in mime:
        return "ogg"
    if "mp3" in mime or "mpeg" in mime:
        return "mp3"
    if "flac" in mime:
        return "flac"
    return "mp3"


def _prepare_audio_payload(audio: bytes, mime: str | None) -> tuple[bytes, str]:
    """Convert raw PCM provider output into a self-describing WAV file."""
    normalized_mime = (mime or "").lower()
    if "l16" not in normalized_mime and "pcm" not in normalized_mime:
        return audio, _safe_ext_from_mime(mime)

    rate_match = re.search(r"rate=(\d+)", normalized_mime)
    sample_rate = int(rate_match.group(1)) if rate_match else 24000
    wav_buffer = io.BytesIO()
    with wave.open(wav_buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio)
    return wav_buffer.getvalue(), "wav"


def _parse_gemini_audio_payload(response_payload: dict) -> tuple[bytes, str]:
    """Extract inline audio bytes and mime type from Gemini API response payload."""
    candidates = response_payload.get("candidates", [])
    if not candidates or not isinstance(candidates, list):
        raise RuntimeError("Gemini response had no candidates")

    for candidate in candidates:
        parts = (
            candidate
            if isinstance(candidate, dict)
            else {}
        ).get("content", {}).get("parts", [])
        for part in parts:
            inline_data = None
            if isinstance(part, dict):
                inline_data = part.get("inlineData") or part.get("inline_data")

            if not isinstance(inline_data, dict):
                continue

            data_field = inline_data.get("data") or inline_data.get("base64") or inline_data.get("audio")
            if not data_field:
                continue

            mime_type = inline_data.get("mimeType") or inline_data.get("mime_type") or "audio/mpeg"
            return base64.b64decode(data_field), mime_type

    raise RuntimeError("Gemini response did not include inline audio output")


def _synthesize_with_gemini(text: str, language_name: str) -> tuple[bytes, str]:
    """Call Gemini Audio API and return audio bytes and mime type."""
    import requests

    if not text.strip():
        raise RuntimeError("Cannot synthesize empty text")

    if not GenAIClient.configure():
        raise RuntimeError("Gemini API is not configured")

    api_key = GenAIClient.get_next_key()
    if not api_key:
        raise RuntimeError("No usable Gemini API key is available for TTS")

    model = os.getenv("GEMINI_TTS_MODEL", "gemini-2.5-flash-preview-audio").strip()
    if not model:
        raise RuntimeError("GEMINI_TTS_MODEL is empty")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": f"Speak naturally in {language_name}.\n\nText: {text}"
                    }
                ],
            }
        ],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
        },
    }

    preferred_voice = os.getenv("GEMINI_TTS_VOICE", "").strip()
    if preferred_voice:
        payload["generationConfig"]["speechConfig"] = {
            "voiceConfig": {
                "prebuiltVoiceConfig": {
                    "voiceName": preferred_voice,
                }
            }
        }

    response = requests.post(
        url,
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload),
        timeout=float(os.getenv("TTS_REQUEST_TIMEOUT_SECONDS", "60")),
    )
    if response.status_code != 200:
        raise RuntimeError(f"Gemini TTS API error: HTTP {response.status_code}: {response.text[:260]}")

    try:
        payload_json = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Gemini TTS returned invalid JSON: {response.text[:260]}") from exc

    return _parse_gemini_audio_payload(payload_json)


def _synthesize_with_openai(text: str, language_name: str) -> tuple[bytes, str]:
    """Call OpenAI's speech endpoint and return an MP3 payload."""
    import requests

    if not text.strip():
        raise RuntimeError("Cannot synthesize empty text")

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    model = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
    voice = os.getenv("OPENAI_TTS_VOICE", "alloy").strip()
    if not model or not voice:
        raise RuntimeError("OpenAI TTS model and voice must be configured")

    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
    }
    if model.startswith("gpt-4o-mini-tts"):
        payload["instructions"] = f"Speak naturally and clearly in {language_name}."

    response = requests.post(
        "https://api.openai.com/v1/audio/speech",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=float(os.getenv("TTS_REQUEST_TIMEOUT_SECONDS", "60")),
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI TTS API error: HTTP {response.status_code}: {response.text[:260]}")
    if not response.content:
        raise RuntimeError("OpenAI TTS returned an empty audio response")

    return response.content, response.headers.get("Content-Type", "audio/mpeg")


def _safe_output_prefix(output_prefix: str | None) -> str:
    """Create a filesystem-safe prefix so concurrent jobs cannot overwrite files."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", output_prefix or uuid.uuid4().hex)


def _summarize_provider_error(error: Exception) -> str:
    """Return a user-safe provider diagnosis without exposing response headers."""
    message = str(error).lower()
    if "openai" in message and ("401" in message or "invalid_api_key" in message):
        return "OpenAI rejected the configured API key."
    if "openai" in message and ("insufficient_quota" in message or "429" in message):
        return "OpenAI API quota or billing is unavailable for text-to-speech."
    if "openai_api_key" in message:
        return "OPENAI_API_KEY is not configured for the backend process."
    if "paid_plan_required" in message or "payment_required" in message or "402" in message:
        return "ElevenLabs requires a paid plan for the configured voice."
    if "elevenlabs" in message and ("401" in message or "403" in message or "unauthorized" in message):
        return "ElevenLabs rejected the configured credentials."
    if "429" in message or "rate limit" in message:
        return "ElevenLabs rate limit reached; try again later."
    if "gemini" in message or "generativelanguage" in message or "responsemodalities" in message:
        return "Gemini TTS request failed. Verify API key, model and provider settings for audio output."
    if "invalid" in message and "api key" in message:
        return "Gemini API key is invalid or expired."
    return "TTS request failed; check the server logs for details."


async def synthesize_speech(
    translations: list[TranslationSegment],
    target_language: str,
    consent_verified: bool = False,
    output_prefix: str | None = None,
) -> list[dict]:
    """
    Generate speech audio from translated text.

    Requires explicit consent confirmation before synthesis.

    Args:
        translations: List of translation segments
        target_language: Target language code
        consent_verified: Whether user consent has been verified

    Returns:
        List of audio segment metadata (paths and timing)
    """
    # ETHICAL SAFEGUARD: Require consent
    if not consent_verified:
        raise ValueError("Voice synthesis requires explicit user consent")

    provider = _resolve_tts_provider()
    if provider == "fixture":
        print("[TTS] Demo mode - generating clearly labeled local fixture audio")
        return _get_demo_audio_segments(translations, target_language, output_prefix)

    processed_dir = os.getenv("PROCESSED_DIR", "storage/processed")
    processed_dir = get_absolute_path(processed_dir)
    os.makedirs(processed_dir, exist_ok=True)
    safe_prefix = _safe_output_prefix(output_prefix)
    language_name = get_language_name(target_language)
    metadata_cfg = _get_tts_provider_config()
    audio_segments = []

    try:
        if provider == "elevenlabs":
            from elevenlabs import ElevenLabs

            api_key = os.getenv("ELEVENLABS_API_KEY", "")
            if not api_key or "your_" in api_key:
                raise RuntimeError(
                    "ELEVENLABS_API_KEY is not configured. Set DEMO_MODE=true for the explicit fixture provider."
                )

            client = ElevenLabs(api_key=api_key)
            voice_id = get_language_voice_id(target_language)

            for i, segment in enumerate(translations):
                if not segment.translated_text:
                    continue

                # Generate audio using new SDK v2.x API
                audio = client.text_to_speech.convert(
                    text=segment.translated_text,
                    voice_id=voice_id,
                    model_id="eleven_multilingual_v2"
                )

                # Save audio file
                audio_path = os.path.join(processed_dir, f"{safe_prefix}_segment_{i}.mp3")
                with open(audio_path, "wb") as f:
                    for chunk in audio:
                        f.write(chunk)

                print(f"[TTS] Generated segment {i} with ElevenLabs ({len(segment.translated_text)} chars)")

                audio_segments.append(
                    {
                        "index": i,
                        "audio_path": audio_path,
                        "text": segment.translated_text,
                        "start_time": getattr(segment, "start_time", i * 5.0),
                        "end_time": getattr(segment, "end_time", (i + 1) * 5.0),
                        "language": target_language,
                        "voice_id": voice_id,
                        "metadata": {
                            "ai_generated": True,
                            "consent_verified": consent_verified,
                            "service": metadata_cfg["service"],
                            "model": metadata_cfg["model"],
                        },
                    }
                )
        else:
            import asyncio as _asyncio
            synthesize_provider = (
                _synthesize_with_gemini if provider == "gemini" else _synthesize_with_openai
            )
            voice_id = (
                os.getenv("GEMINI_TTS_VOICE", "gemini-default")
                if provider == "gemini"
                else os.getenv("OPENAI_TTS_VOICE", "alloy")
            )
            for i, segment in enumerate(translations):
                if not segment.translated_text:
                    continue

                audio_bytes, audio_mime = await _asyncio.to_thread(
                    synthesize_provider,
                    segment.translated_text,
                    language_name,
                )
                audio_bytes, ext = _prepare_audio_payload(audio_bytes, audio_mime)
                audio_path = os.path.join(processed_dir, f"{safe_prefix}_segment_{i}.{ext}")
                with open(audio_path, "wb") as f:
                    f.write(audio_bytes)

                print(f"[TTS] Generated segment {i} with {metadata_cfg['service']} ({len(segment.translated_text)} chars)")

                audio_segments.append(
                    {
                        "index": i,
                        "audio_path": audio_path,
                        "text": segment.translated_text,
                        "start_time": getattr(segment, "start_time", i * 5.0),
                        "end_time": getattr(segment, "end_time", (i + 1) * 5.0),
                        "language": target_language,
                        "voice_id": voice_id,
                        "metadata": {
                            "ai_generated": True,
                            "consent_verified": consent_verified,
                            "service": metadata_cfg["service"],
                            "model": metadata_cfg["model"],
                        },
                    }
                )

        return audio_segments

    except ImportError as e:
        if provider == "elevenlabs":
            raise RuntimeError(
                f"ElevenLabs library not installed. Run: pip install elevenlabs. Error: {e}"
            )
        raise
    except Exception as e:
        import traceback
        print(f"❌ TTS error with configured API key: {e}")
        traceback.print_exc()
        raise RuntimeError(f"TTS failed: {_summarize_provider_error(e)}") from e


async def synthesize_speech_parallel(
    translations: list[TranslationSegment],
    target_language: str,
    consent_verified: bool = False,
    max_concurrent: int = 5,
    output_prefix: str | None = None,
) -> list[dict]:
    """
    Generate TTS for all segments in parallel with concurrency limit.
    5x faster than sequential processing.

    Args:
        translations: List of translation segments
        target_language: Target language code
        consent_verified: Whether user consent has been verified
        max_concurrent: Max concurrent API calls (default 5)

    Returns:
        List of audio segment metadata (paths and timing)
    """
    import asyncio

    # ETHICAL SAFEGUARD: Require consent
    if not consent_verified:
        raise ValueError("Voice synthesis requires explicit user consent")

    provider = _resolve_tts_provider()
    if provider == "fixture":
        print("[TTS] Demo mode - generating clearly labeled local fixture audio")
        return _get_demo_audio_segments(translations, target_language, output_prefix)

    processed_dir = os.getenv("PROCESSED_DIR", "storage/processed")
    processed_dir = get_absolute_path(processed_dir)
    os.makedirs(processed_dir, exist_ok=True)
    safe_prefix = _safe_output_prefix(output_prefix)
    language_name = get_language_name(target_language)
    metadata_cfg = _get_tts_provider_config()

    try:
        import asyncio as _asyncio

        if provider == "elevenlabs":
            from elevenlabs import ElevenLabs

            api_key = os.getenv("ELEVENLABS_API_KEY", "")
            if not api_key or "your_" in api_key:
                raise RuntimeError(
                    "ELEVENLABS_API_KEY is not configured. Set DEMO_MODE=true for the explicit fixture provider."
                )

            client = ElevenLabs(api_key=api_key)
            voice_id = get_language_voice_id(target_language)
        else:
            client = None
            synthesize_provider = (
                _synthesize_with_gemini if provider == "gemini" else _synthesize_with_openai
            )
            voice_id = (
                os.getenv("GEMINI_TTS_VOICE", "gemini-default")
                if provider == "gemini"
                else os.getenv("OPENAI_TTS_VOICE", "alloy")
            )

        semaphore = asyncio.Semaphore(max_concurrent)
        failure_summaries = []

        async def generate_segment(i: int, segment: TranslationSegment) -> Optional[dict]:
            async with semaphore:  # Limit concurrent API calls
                if not segment.translated_text:
                    return None

                loop = _asyncio.get_event_loop()
                try:
                    if provider == "elevenlabs":
                        audio = await loop.run_in_executor(
                            None,
                            lambda: list(
                                client.text_to_speech.convert(
                                    text=segment.translated_text,
                                    voice_id=voice_id,
                                    model_id="eleven_multilingual_v2"
                                )
                            )
                        )
                        audio_path = os.path.join(processed_dir, f"{safe_prefix}_segment_{i}.mp3")
                        with open(audio_path, "wb") as f:
                            for chunk in audio:
                                f.write(chunk)
                    else:
                        audio_bytes, audio_mime = await loop.run_in_executor(
                            None,
                            lambda: synthesize_provider(
                                segment.translated_text,
                                language_name,
                            )
                        )
                        audio_bytes, ext = _prepare_audio_payload(audio_bytes, audio_mime)
                        audio_path = os.path.join(processed_dir, f"{safe_prefix}_segment_{i}.{ext}")
                        with open(audio_path, "wb") as f:
                            f.write(audio_bytes)

                    print(f"[TTS] Generated segment {i} with {metadata_cfg['service']} ({len(segment.translated_text)} chars)")

                    return {
                        "index": i,
                        "audio_path": audio_path,
                        "text": segment.translated_text,
                        "start_time": getattr(segment, 'start_time', i * 5.0),
                        "end_time": getattr(segment, 'end_time', (i + 1) * 5.0),
                        "language": target_language,
                        "voice_id": voice_id,
                        "metadata": {
                            "ai_generated": True,
                            "consent_verified": consent_verified,
                            "service": metadata_cfg["service"],
                            "model": metadata_cfg["model"],
                        }
                    }
                except Exception as e:
                    print(f"[TTS] Segment {i} failed: {e}")
                    failure_summaries.append(_summarize_provider_error(e))
                    return None

        # Generate all segments in parallel
        tasks = [generate_segment(i, seg) for i, seg in enumerate(translations)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter out failed segments and exceptions
        audio_segments = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"[TTS] Segment {i} exception: {result}")
                failure_summaries.append(_summarize_provider_error(result))
            elif result is not None:
                audio_segments.append(result)

        # FIX BUG#6: Raise error if all segments failed
        if not audio_segments:
            provider_error = failure_summaries[0] if failure_summaries else "No audio was returned."
            raise RuntimeError(
                f"All TTS segments failed. Generated 0/{len(translations)} segments. {provider_error}"
            )

        print(f"[TTS] ✓ Generated {len(audio_segments)}/{len(translations)} segments in parallel")
        return audio_segments

    except ImportError as e:
        if provider == "elevenlabs":
            raise RuntimeError(f"ElevenLabs library not installed. Run: pip install elevenlabs. Error: {e}")
        raise
    except Exception as e:
        import traceback
        print(f"❌ Parallel TTS error: {e}")
        traceback.print_exc()
        if isinstance(e, RuntimeError) and str(e).startswith("All TTS segments failed"):
            raise
        raise RuntimeError(f"TTS failed: {_summarize_provider_error(e)}") from e


def _get_demo_audio_segments(
    translations: list[TranslationSegment],
    target_language: str,
    output_prefix: str | None = None,
) -> list[dict]:
    """
    Generate deterministic local fixture audio for explicit demo mode.

    This is intentionally not used by the real ElevenLabs provider. The
    metadata makes the boundary visible in the audit report.
    """
    import subprocess
    
    processed_dir = os.getenv("PROCESSED_DIR", "storage/processed")
    processed_dir = get_absolute_path(processed_dir)
    os.makedirs(processed_dir, exist_ok=True)
    
    safe_prefix = _safe_output_prefix(output_prefix)
    segments = []
    
    for i, segment in enumerate(translations):
        if not segment.translated_text:
            continue
            
        audio_path = os.path.join(processed_dir, f"demo_{safe_prefix}_segment_{i}.mp3")
        
        # Estimate duration from word count
        word_count = len(segment.translated_text.split())
        duration = max(word_count * 0.4, 1.0)
        
        # Generate 300Hz beep instead of silence
        # This ensures the dubbed video has audible audio for verification
        if not os.path.exists(audio_path):
            try:
                cmd = [
                    'ffmpeg', '-y',
                    '-f', 'lavfi',
                    '-i', f'sine=frequency=300:duration={duration}',
                    '-ar', '44100',
                    '-ac', '2',
                    '-b:a', '128k',
                    audio_path
                ]
                
                print(f"[TTS] Generating demo fixture audio for segment {i}...")
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                
            except Exception as e:
                raise RuntimeError(f"Failed to create demo fixture audio: {e}") from e
                
        segments.append({
            "index": i,
            "audio_path": audio_path,
            "text": segment.translated_text,
            "start_time": getattr(segment, 'start_time', i * 5.0),  # Include timing for sorting
            "end_time": getattr(segment, 'end_time', (i + 1) * 5.0),
            "language": target_language,
            "voice_id": "demo_fixture",
            "metadata": {
                "ai_generated": False,
                "consent_verified": True,
                "service": "Demo fixture (FFmpeg)",
                "model": "sine_wave_fixture",
                "demo_fixture": True,
                "duration": duration
            }
        })
        
    return segments


async def get_available_voices(language: str) -> list[dict]:
    """
    Get available voices for a language.
    
    Args:
        language: Language code
        
    Returns:
        List of available voice options
    """
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    provider = os.getenv("TTS_PROVIDER", "fixture" if demo_mode else "elevenlabs").strip().lower()
    api_key = os.getenv("ELEVENLABS_API_KEY", "")

    if provider in {"fixture", "demo"} and demo_mode:
        return [
            {
                "voice_id": "demo_fixture",
                "name": "Local fixture tone",
                "language": language,
                "description": "Explicit demo-only FFmpeg fixture; not a human voice",
            }
        ]

    if provider == "gemini":
        voice_id = os.getenv("GEMINI_TTS_VOICE", "gemini-default")
        return [
            {
                "voice_id": voice_id,
                "name": voice_id,
                "language": language,
                "description": "Configured Gemini prebuilt voice",
            }
        ]

    if provider == "openai":
        voices = [
            "alloy", "ash", "ballad", "coral", "echo", "fable", "onyx",
            "nova", "sage", "shimmer", "verse", "marin", "cedar",
        ]
        return [
            {
                "voice_id": voice,
                "name": voice.title(),
                "language": language,
                "description": "OpenAI built-in synthetic voice",
            }
            for voice in voices
        ]

    if not api_key or "your_" in api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is required to list real voices")
    
    try:
        from elevenlabs import ElevenLabs
        
        client = ElevenLabs(api_key=api_key)
        voices = client.voices.get_all()
        
        return [
            {
                "voice_id": voice.voice_id,
                "name": voice.name,
                "language": language,
                "description": getattr(voice, "description", "")
            }
            for voice in voices.voices
        ]
        
    except Exception as e:
        print(f"Error fetching voices: {e}")
        return []


def generate_consent_statement(purpose: str) -> str:
    """
    Generate a consent statement for voice synthesis.
    
    Args:
        purpose: Description of how the voice will be used
        
    Returns:
        Consent statement text
    """
    return f"""VOICE SYNTHESIS CONSENT STATEMENT

By proceeding, you acknowledge and agree that:

1. AI-generated voice synthesis will be used for: {purpose}

2. The generated audio will be clearly labeled as AI-generated.

3. You have the right to use this content for the stated purpose.

4. You understand that voice cloning technology carries ethical responsibilities.

5. You will not use this technology for:
   - Impersonation without consent
   - Fraud or deception
   - Harassment or harm
   - Creating misleading content

This consent is logged for accountability purposes.
"""


def get_voice_metadata(voice_id: str, language: str) -> dict:
    """
    Get metadata for audit logging.
    
    Args:
        voice_id: ElevenLabs voice ID
        language: Target language
        
    Returns:
        Metadata dictionary for audit logs
    """
    return {
        "voice_id": voice_id,
        "language": language,
        "service": "ElevenLabs",
        "ai_generated": True,
        "ethical_disclosure": "AI-generated audio clearly labeled",
        "consent_required": True,
    }
