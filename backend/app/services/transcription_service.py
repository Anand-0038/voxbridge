"""
Transcription service for speech-to-text conversion.

Uses Gemini API for audio transcription with timestamps.
Includes retry logic with exponential backoff and key rotation.
"""

import asyncio
import os

import google.generativeai as genai

from app.models.schemas import TranscriptSegment
from app.utils.genai_client import GenAIClient


async def transcribe_audio(audio_path: str) -> list[TranscriptSegment]:
    """
    Transcribe audio file to text with timestamps.
    
    Args:
        audio_path: Path to the audio file
        
    Returns:
        List of transcript segments with timing
        
    Raises:
        FileNotFoundError: If audio file doesn't exist
        RuntimeError: If transcription fails after all retries
    """
    # Validate audio file exists
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    # Check if in demo mode
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"

    if demo_mode:
        print("[TRANSCRIPTION] Demo mode - using the labeled fixture transcript")
        return _get_demo_transcript()
    
    # Check if API is configured
    if GenAIClient.get_key_count() == 0:
        raise RuntimeError("Gemini API not configured and DEMO_MODE is disabled")

    # Retry configuration
    max_retries = 3
    timeout_seconds = 60
    last_error = None
    
    for attempt in range(max_retries):
        try:
            model = GenAIClient.get_model("gemini-2.5-flash")
            if not model:
                raise RuntimeError("Failed to get Gemini model")

            # The legacy Gemini SDK upload is synchronous. Run it off the
            # event loop so large files do not block other API requests.
            audio_file = await asyncio.wait_for(
                asyncio.to_thread(genai.upload_file, audio_path),
                timeout=timeout_seconds,
            )
            
            prompt = """Transcribe this audio file. 
            
Return the transcription as a JSON array with the following structure:
[
  {
    "text": "The spoken text",
    "start_time": 0.0,
    "end_time": 3.5,
    "confidence": 0.95
  }
]

Only return the JSON array, no other text.
If the audio is unclear, still provide your best transcription with lower confidence scores.
"""
            
            # Use await with timeout
            response = await asyncio.wait_for(
                model.generate_content_async([prompt, audio_file]),
                timeout=timeout_seconds
            )
            
            # Parse response
            import json
            response_text = response.text.strip()
            
            # Clean up markdown code blocks if present
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                response_text = "\n".join(lines[1:-1])
            
            segments_data = json.loads(response_text)
            
            segments = [
                TranscriptSegment(
                    text=seg["text"],
                    start_time=seg["start_time"],
                    end_time=seg["end_time"],
                    confidence=seg.get("confidence", 0.9)
                )
                for seg in segments_data
            ]
            
            print(f"[TRANSCRIPTION] ✓ Successfully transcribed {len(segments)} segments")
            return segments
            
        except asyncio.TimeoutError:
            last_error = f"Timeout (attempt {attempt + 1}/{max_retries})"
            print(f"[TRANSCRIPTION] ⚠️ {last_error}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
                
        except Exception as e:
            error_str = str(e)
            last_error = f"Error (attempt {attempt + 1}/{max_retries}): {error_str}"
            print(f"[TRANSCRIPTION] ⚠️ {last_error}")
            
            # Check for quota error and mark key as failed
            if "429" in error_str or "quota" in error_str.lower():
                # Key rotation will happen on next get_model() call
                print("[TRANSCRIPTION] Quota exceeded, rotating to next API key...")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
    
    # All retries exhausted
    raise RuntimeError(f"Transcription failed after {max_retries} retries: {last_error}")


def _get_demo_transcript() -> list[TranscriptSegment]:
    """Return demo transcript for testing."""
    return [
        TranscriptSegment(
            text="Welcome to this demonstration of our video dubbing platform.",
            start_time=0.0,
            end_time=4.0,
            confidence=0.97
        ),
        TranscriptSegment(
            text="This system uses responsible AI to ensure content safety.",
            start_time=4.0,
            end_time=8.0,
            confidence=0.95
        ),
        TranscriptSegment(
            text="All content is analyzed before translation and dubbing.",
            start_time=8.0,
            end_time=12.0,
            confidence=0.96
        ),
        TranscriptSegment(
            text="Thank you for watching our demonstration.",
            start_time=12.0,
            end_time=15.0,
            confidence=0.98
        ),
    ]


async def detect_language(text: str) -> str:
    """
    Detect the language of the given text.
    
    Args:
        text: Text to analyze
        
    Returns:
        Language code (e.g., 'en', 'es', 'fr')
    """
    try:
        model = GenAIClient.get_model("gemini-2.5-flash")
        if not model:
            return "en"  # Default to English if API not configured
        
        prompt = f"""Detect the language of this text and return only the ISO 639-1 language code.
        
Text: {text}

Return only the 2-letter language code, nothing else."""
        
        response = await asyncio.wait_for(
            model.generate_content_async(prompt),
            timeout=30
        )
        return response.text.strip().lower()[:2]
        
    except Exception as e:
        print(f"[TRANSCRIPTION] Language detection error: {e}")
        return "en"  # Default to English
