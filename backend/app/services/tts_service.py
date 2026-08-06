"""
Text-to-Speech service with ethical safeguards.

Uses ElevenLabs API for voice synthesis with consent validation.
"""

import os
import re
import uuid
from typing import Optional

from app.models.schemas import TranslationSegment
from app.utils.helpers import get_absolute_path


# Voice ID mapping for supported languages
VOICE_MAPPING = {
    "en": "21m00Tcm4TlvDq8ikWAM",  # Rachel
    "es": "AZnzlk1XvdvUeBnXmlld",  # Spanish voice
    "fr": "EXAVITQu4vr4xnSDxMaL",  # French voice
    "de": "VR6AewLTigWG4xSOukaG",  # German voice
    "it": "ThT5KcBeYPX3keUQqHPh",  # Italian voice
    "pt": "pNInz6obpgDQGcFmaJgB",  # Portuguese voice
    "hi": "21m00Tcm4TlvDq8ikWAM",  # Hindi - uses multilingual Rachel voice
    "ja": "21m00Tcm4TlvDq8ikWAM",  # Japanese - uses multilingual voice
    "ko": "21m00Tcm4TlvDq8ikWAM",  # Korean - uses multilingual voice
    "zh": "21m00Tcm4TlvDq8ikWAM",  # Chinese - uses multilingual voice
    "ar": "21m00Tcm4TlvDq8ikWAM",  # Arabic - uses multilingual voice
    "ru": "21m00Tcm4TlvDq8ikWAM",  # Russian - uses multilingual voice
}


def _safe_output_prefix(output_prefix: str | None) -> str:
    """Create a filesystem-safe prefix so concurrent jobs cannot overwrite files."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", output_prefix or uuid.uuid4().hex)


def _summarize_provider_error(error: Exception) -> str:
    """Return a user-safe provider diagnosis without exposing response headers."""
    message = str(error).lower()
    if "paid_plan_required" in message or "payment_required" in message or "402" in message:
        return "ElevenLabs requires a paid plan for the configured voice."
    if "401" in message or "403" in message or "unauthorized" in message:
        return "ElevenLabs rejected the configured credentials."
    if "429" in message or "rate limit" in message:
        return "ElevenLabs rate limit reached; try again later."
    return "ElevenLabs request failed; check the server logs for details."


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
    
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    provider = os.getenv("TTS_PROVIDER", "fixture" if demo_mode else "elevenlabs").strip().lower()
    if provider in {"fixture", "demo"}:
        if not demo_mode:
            raise RuntimeError("The fixture TTS provider requires DEMO_MODE=true")
        print("[TTS] Demo mode - generating clearly labeled local fixture audio")
        return _get_demo_audio_segments(translations, target_language, output_prefix)
    if provider != "elevenlabs":
        raise RuntimeError(f"Unsupported TTS_PROVIDER: {provider}")

    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key or "your_" in api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY is not configured. Set DEMO_MODE=true for the explicit fixture provider."
        )
    
    # API key is configured - use real ElevenLabs TTS
    try:
        from elevenlabs import ElevenLabs
        
        client = ElevenLabs(api_key=api_key)
        
        processed_dir = os.getenv("PROCESSED_DIR", "storage/processed")
        processed_dir = get_absolute_path(processed_dir)
        os.makedirs(processed_dir, exist_ok=True)
        safe_prefix = _safe_output_prefix(output_prefix)
        
        audio_segments = []
        voice_id = VOICE_MAPPING.get(target_language, VOICE_MAPPING["en"])
        
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
            
            audio_segments.append({
                "index": i,
                "audio_path": audio_path,
                "text": segment.translated_text,
                "start_time": getattr(segment, 'start_time', i * 5.0),  # Include timing for sorting
                "end_time": getattr(segment, 'end_time', (i + 1) * 5.0),
                "language": target_language,
                "voice_id": voice_id,
                "metadata": {
                    "ai_generated": True,
                    "consent_verified": consent_verified,
                    "service": "ElevenLabs",
                    "model": "eleven_multilingual_v2"
                }
            })
        
        return audio_segments
        
    except ImportError as e:
        # ElevenLabs library not installed - this is a setup error, raise it
        raise RuntimeError(f"ElevenLabs library not installed. Run: pip install elevenlabs. Error: {e}")
    except Exception as e:
        # API key was configured but TTS failed - raise the error instead of silently falling back
        import traceback
        print(f"❌ TTS error with configured API key: {e}")
        traceback.print_exc()
        raise RuntimeError(f"ElevenLabs TTS failed: {_summarize_provider_error(e)}") from e


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
    
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"
    provider = os.getenv("TTS_PROVIDER", "fixture" if demo_mode else "elevenlabs").strip().lower()
    if provider in {"fixture", "demo"}:
        if not demo_mode:
            raise RuntimeError("The fixture TTS provider requires DEMO_MODE=true")
        print("[TTS] Demo mode - generating clearly labeled local fixture audio")
        return _get_demo_audio_segments(translations, target_language, output_prefix)
    if provider != "elevenlabs":
        raise RuntimeError(f"Unsupported TTS_PROVIDER: {provider}")

    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key or "your_" in api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY is not configured. Set DEMO_MODE=true for the explicit fixture provider."
        )
    
    # API key is configured - use real ElevenLabs TTS
    try:
        from elevenlabs import ElevenLabs
        
        client = ElevenLabs(api_key=api_key)
        
        processed_dir = os.getenv("PROCESSED_DIR", "storage/processed")
        processed_dir = get_absolute_path(processed_dir)
        os.makedirs(processed_dir, exist_ok=True)
        safe_prefix = _safe_output_prefix(output_prefix)
        
        voice_id = VOICE_MAPPING.get(target_language, VOICE_MAPPING["en"])
        semaphore = asyncio.Semaphore(max_concurrent)
        failure_summaries = []
        
        async def generate_segment(i: int, segment: TranslationSegment) -> Optional[dict]:
            async with semaphore:  # Limit concurrent API calls
                if not segment.translated_text:
                    return None
                
                # Run sync ElevenLabs call in thread pool
                loop = asyncio.get_event_loop()
                try:
                    audio = await loop.run_in_executor(
                        None,
                        lambda: list(client.text_to_speech.convert(
                            text=segment.translated_text,
                            voice_id=voice_id,
                            model_id="eleven_multilingual_v2"
                        ))
                    )
                    
                    audio_path = os.path.join(processed_dir, f"{safe_prefix}_segment_{i}.mp3")
                    with open(audio_path, "wb") as f:
                        for chunk in audio:
                            f.write(chunk)
                    
                    print(f"[TTS] Generated segment {i} with ElevenLabs ({len(segment.translated_text)} chars)")
                    
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
                            "service": "ElevenLabs",
                            "model": "eleven_multilingual_v2"
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
        raise RuntimeError(f"ElevenLabs library not installed. Run: pip install elevenlabs. Error: {e}")
    except Exception as e:
        import traceback
        print(f"❌ Parallel TTS error: {e}")
        traceback.print_exc()
        if isinstance(e, RuntimeError) and str(e).startswith("All TTS segments failed"):
            raise
        raise RuntimeError(f"ElevenLabs TTS failed: {_summarize_provider_error(e)}") from e


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
