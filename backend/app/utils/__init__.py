"""
Utility module for VoxBridge.
"""

import json
import os
import re
from typing import Union

# Re-export everything from helpers
from app.utils.helpers import (
    generate_file_hash,
    generate_text_hash,
    format_timestamp,
    get_file_extension,
    validate_video_format,
    validate_audio_format,
    format_duration,
    sanitize_filename,
    calculate_confidence_level,
)


def parse_gemini_json(response_text: str) -> Union[dict, list]:
    """
    Safely parse JSON from Gemini responses.
    
    Gemini sometimes wraps JSON in markdown code blocks or returns
    malformed responses. This function handles common edge cases.
    
    Args:
        response_text: Raw response text from Gemini
        
    Returns:
        Parsed JSON as dict/list
        
    Raises:
        ValueError: If JSON parsing fails after all cleanup attempts
    """
    if not response_text or not response_text.strip():
        raise ValueError("Empty response from Gemini")
    
    text = response_text.strip()
    
    # Try parsing as-is first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Remove markdown code blocks if present
    if text.startswith("```"):
        lines = text.split("\n")
        # Skip first line (```json or ```) and last line (```)
        if len(lines) >= 3:
            # Check if last line is just ```
            if lines[-1].strip() == "```":
                text = "\n".join(lines[1:-1])
            else:
                text = "\n".join(lines[1:])
        else:
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
    
    # Try parsing cleaned text
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON object in the text
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    
    # Try to find JSON array in the text
    array_match = re.search(r'\[[\s\S]*\]', text)
    if array_match:
        try:
            return json.loads(array_match.group())
        except json.JSONDecodeError:
            pass
    
    # All attempts failed
    raise ValueError(f"Failed to parse JSON from Gemini response: {text[:200]}...")


# Supported languages configuration
# TODO: For production, load from external API or database
SUPPORTED_LANGUAGES = {
    "en": {"name": "English", "voice_id": "21m00Tcm4TlvDq8ikWAM", "rtl": False},
    "es": {"name": "Spanish", "voice_id": "AZnzlk1XvdvUeBnXmlld", "rtl": False},
    "fr": {"name": "French", "voice_id": "EXAVITQu4vr4xnSDxMaL", "rtl": False},
    "de": {"name": "German", "voice_id": "VR6AewLTigWG4xSOukaG", "rtl": False},
    "it": {"name": "Italian", "voice_id": "ThT5KcBeYPX3keUQqHPh", "rtl": False},
    "pt": {"name": "Portuguese", "voice_id": "pNInz6obpgDQGcFmaJgB", "rtl": False},
    "ja": {"name": "Japanese", "voice_id": "yoZ06aMxZJJ28mfd3POQ", "rtl": False},
    "ko": {"name": "Korean", "voice_id": "yoZ06aMxZJJ28mfd3POQ", "rtl": False},
    "zh": {"name": "Chinese", "voice_id": "yoZ06aMxZJJ28mfd3POQ", "rtl": False},
    "ar": {"name": "Arabic", "voice_id": "yoZ06aMxZJJ28mfd3POQ", "rtl": True},
    "hi": {"name": "Hindi", "voice_id": "yoZ06aMxZJJ28mfd3POQ", "rtl": False},
    "ru": {"name": "Russian", "voice_id": "yoZ06aMxZJJ28mfd3POQ", "rtl": False},
}


def get_language_name(code: str) -> str:
    """Get full language name from ISO code."""
    lang = SUPPORTED_LANGUAGES.get(code)
    if lang:
        return lang["name"]
    return code


def get_language_voice_id(code: str) -> str:
    """Get ElevenLabs voice ID for a language."""
    lang = SUPPORTED_LANGUAGES.get(code)
    if lang:
        return lang["voice_id"]
    return SUPPORTED_LANGUAGES["en"]["voice_id"]


def get_supported_languages() -> list[dict]:
    """Get list of supported languages for frontend."""
    return [
        {"code": code, "name": data["name"], "rtl": data["rtl"]}
        for code, data in SUPPORTED_LANGUAGES.items()
    ]


def is_language_supported(code: str) -> bool:
    """Check if a language code is supported."""
    return code in SUPPORTED_LANGUAGES
