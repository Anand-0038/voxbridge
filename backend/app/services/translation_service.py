"""
Translation service with transparency features.

Provides translation with confidence scores and alternative suggestions.
Includes retry logic with exponential backoff and key rotation.
"""

import os
import json
import asyncio
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

from app.models.schemas import TranscriptSegment, TranslationSegment
from app.utils import get_language_name
from app.utils import parse_gemini_json
from app.utils.genai_client import GenAIClient


TRANSLATION_PROMPT = """You are a professional translator with expertise in cultural nuance.

Translate the following text segments to {target_language}.

For each segment:
1. Provide the best translation
2. Rate your confidence (0.0 to 1.0)
3. Flag if there is ambiguity
4. Provide 1-2 alternative translations if confidence is below 0.9

Input segments:
{segments}

Return ONLY a JSON array in this exact format:
[
  {{
    "original_text": "The original text",
    "translated_text": "The translated text",
    "confidence": 0.95,
    "alternatives": ["Alternative 1", "Alternative 2"],
    "has_ambiguity": false,
    "notes": "Optional translator notes"
  }}
]

Do NOT include any markdown formatting or additional text."""


async def translate_transcript(
    transcript: list[TranscriptSegment],
    target_language: str
) -> list[TranslationSegment]:
    """
    Translate transcript segments with transparency data.
    
    Args:
        transcript: List of transcript segments
        target_language: Target language code (e.g., 'es', 'fr', 'de')
        
    Returns:
        List of translation segments with confidence and alternatives
        
    Raises:
        RuntimeError: If translation fails with configured API after all retries
    """
    # Check if in demo mode
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"

    if demo_mode:
        print("[TRANSLATION] Demo mode - using clearly labeled fixture translations")
        return _get_demo_translations(transcript, target_language)
    
    # Check if API is configured first
    if GenAIClient.get_key_count() == 0:
        raise RuntimeError("Gemini API not configured and DEMO_MODE is disabled")
    
    # Prepare segments for translation
    segments_text = json.dumps([
        {"text": seg.text, "index": i}
        for i, seg in enumerate(transcript)
    ], indent=2)
    
    target_name = get_language_name(target_language)
    
    # Retry configuration
    max_retries = 3
    timeout_seconds = 45
    last_error = None
    
    for attempt in range(max_retries):
        try:
            model = GenAIClient.get_model("gemini-2.5-flash")
            if not model:
                raise RuntimeError("Failed to get Gemini model")
            
            prompt = TRANSLATION_PROMPT.format(
                target_language=target_name,
                segments=segments_text
            )
            
            # Add timeout to API call
            response = await asyncio.wait_for(
                model.generate_content_async(prompt),
                timeout=timeout_seconds
            )
            response_text = response.text.strip()
            
            # Use robust JSON parsing utility
            translations = parse_gemini_json(response_text)
            
            result = [
                TranslationSegment(
                    original_text=trans.get("original_text", transcript[i].text if i < len(transcript) else ""),
                    translated_text=trans.get("translated_text", ""),
                    start_time=transcript[i].start_time if i < len(transcript) else 0.0,
                    end_time=transcript[i].end_time if i < len(transcript) else 0.0,
                    confidence=trans.get("confidence", 0.8),
                    alternatives=trans.get("alternatives", []),
                    has_ambiguity=trans.get("has_ambiguity", False)
                )
                for i, trans in enumerate(translations)
            ]
            
            print(f"[TRANSLATION] ✓ Successfully translated {len(result)} segments to {target_name}")
            return result
            
        except asyncio.TimeoutError:
            last_error = f"Timeout (attempt {attempt + 1}/{max_retries})"
            print(f"[TRANSLATION] ⚠️ {last_error}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
                
        except Exception as e:
            error_str = str(e)
            last_error = f"Error (attempt {attempt + 1}/{max_retries}): {error_str}"
            print(f"[TRANSLATION] ⚠️ {last_error}")
            
            # Check for quota error
            if "429" in error_str or "quota" in error_str.lower():
                print("[TRANSLATION] Quota exceeded, rotating to next API key...")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
    
    # All retries exhausted
    raise RuntimeError(f"Translation failed after {max_retries} retries: {last_error}")


def _get_demo_translations(transcript: list[TranscriptSegment], target_language: str) -> list[TranslationSegment]:
    """Return demo translations for testing."""
    return [
        TranslationSegment(
            original_text=seg.text,
            translated_text=f"[DEMO FIXTURE - {target_language}] {seg.text}",
            start_time=seg.start_time,
            end_time=seg.end_time,
            confidence=0.5,
            alternatives=[],
            has_ambiguity=True
        )
        for seg in transcript
    ]


async def translate_single_segment(
    text: str,
    target_language: str
) -> TranslationSegment:
    """
    Translate a single text segment.
    
    Args:
        text: Text to translate
        target_language: Target language code
        
    Returns:
        TranslationSegment with translation data
    """
    segment = TranscriptSegment(
        text=text,
        start_time=0.0,
        end_time=0.0,
        confidence=1.0
    )
    
    results = await translate_transcript([segment], target_language)
    
    if results:
        return results[0]
    
    return TranslationSegment(
        original_text=text,
        translated_text=text,
        confidence=0.0,
        alternatives=[],
        has_ambiguity=True
    )


async def validate_translation(
    original: str,
    translation: str,
    language: str
) -> dict:
    """
    Validate a translation for accuracy and cultural appropriateness.
    
    Args:
        original: Original text
        translation: Translated text
        language: Target language
        
    Returns:
        Validation result with score and issues
    """
    try:
        model = GenAIClient.get_model("gemini-2.5-flash")
        if not model:
            raise ValueError("API not configured")
        
        prompt = f"""Validate this translation:

Original (English): {original}
Translation ({language}): {translation}

Check for:
1. Accuracy of meaning
2. Grammar correctness
3. Cultural appropriateness
4. Register/tone preservation

Return JSON:
{{
  "accuracy_score": 0.95,
  "grammar_score": 0.90,
  "cultural_score": 0.85,
  "overall_score": 0.90,
  "issues": ["List of any issues found"],
  "suggestions": ["Improvement suggestions"]
}}

Return ONLY the JSON object."""
        
        response = await asyncio.wait_for(
            model.generate_content_async(prompt),
            timeout=15
        )
        response_text = response.text.strip()
        
        # Use robust JSON parsing
        return parse_gemini_json(response_text)
        
    except Exception as e:
        print(f"[TRANSLATION] Validation error: {e}")
        return {
            "accuracy_score": 0.8,
            "grammar_score": 0.8,
            "cultural_score": 0.8,
            "overall_score": 0.8,
            "issues": [],
            "suggestions": []
        }
