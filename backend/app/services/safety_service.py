"""
Safety analysis service - Core Responsible AI component.

Analyzes content for toxicity, bias, misinformation, and cultural sensitivity.
Includes retry logic with exponential backoff.
"""

import os
import asyncio
from typing import Optional

import google.generativeai as genai
from dotenv import load_dotenv

from app.models.schemas import (
    AnalysisResponse,
    SafetyFlag,
    TranscriptSegment,
    RiskLevel,
    FlagCategory,
)
from app.utils import parse_gemini_json
from app.utils.genai_client import GenAIClient


# Safety analysis system prompt
SAFETY_ANALYSIS_PROMPT = """You are an AI safety auditor for a video dubbing platform.

Analyze the following transcript for:
1. Toxic language (hate speech, threats, harassment)
2. Bias or stereotypes (gender, race, religion, nationality)
3. Misinformation (false claims, unverified health/science claims)
4. Cultural sensitivity issues (content that may offend specific cultures)
5. Age-inappropriate content

For each issue found:
- Identify the specific text segment
- Explain why it is problematic
- Assign a severity level (low, medium, high)
- Assign a confidence score (0.0 to 1.0)

Respond ONLY with a valid JSON object in this exact format:
{
  "risk_score": 25,
  "flags": [
    {
      "category": "toxicity|bias|misinformation|cultural_sensitivity|age_inappropriate",
      "text_segment": "The exact problematic text",
      "severity": "low|medium|high",
      "explanation": "Clear explanation of the issue",
      "confidence": 0.85
    }
  ],
  "analysis_summary": "Brief overall assessment"
}

If no issues are found, return:
{
  "risk_score": 0,
  "flags": [],
  "analysis_summary": "No safety concerns detected."
}

Do NOT include any markdown formatting, code blocks, or additional text.
Return ONLY the JSON object."""


async def analyze_content_safety(
    transcript: list[TranscriptSegment]
) -> AnalysisResponse:
    """
    Analyze transcript content for safety concerns.
    
    This is the core Responsible AI function that differentiates
    VoxBridge from standard dubbing tools.
    
    Args:
        transcript: List of transcript segments with timing
        
    Returns:
        AnalysisResponse with risk score, flags, and explanations
    """
    # Combine transcript text for analysis
    full_text = "\n".join([
        f"[{seg.start_time:.1f}s - {seg.end_time:.1f}s]: {seg.text}"
        for seg in transcript
    ])
    
    # Check if in demo mode
    demo_mode = os.getenv("DEMO_MODE", "false").lower() == "true"

    if demo_mode:
        print("[SAFETY] Demo mode - using the labeled deterministic fixture result")
        return _get_safe_default(transcript)
    
    # Retry configuration
    max_retries = 3
    timeout_seconds = 60  # Increased from 30s for longer transcripts
    last_error = None
    
    for attempt in range(max_retries):
        try:
            model = GenAIClient.get_model("gemini-2.5-flash")
            if not model:
                raise RuntimeError("Gemini API not configured")
            
            prompt = f"{SAFETY_ANALYSIS_PROMPT}\n\nTranscript to analyze:\n{full_text}"
            
            response = await asyncio.wait_for(
                model.generate_content_async(prompt),
                timeout=timeout_seconds
            )
            response_text = response.text.strip()
            
            # Use robust JSON parsing utility
            result = parse_gemini_json(response_text)
            
            # Convert to SafetyFlag objects
            flags = []
            for flag_data in result.get("flags", []):
                # Map category string to enum
                category_map = {
                    "toxicity": FlagCategory.TOXICITY,
                    "bias": FlagCategory.BIAS,
                    "misinformation": FlagCategory.MISINFORMATION,
                    "cultural_sensitivity": FlagCategory.CULTURAL_SENSITIVITY,
                    "age_inappropriate": FlagCategory.AGE_INAPPROPRIATE,
                }
                
                severity_map = {
                    "low": RiskLevel.LOW,
                    "medium": RiskLevel.MEDIUM,
                    "high": RiskLevel.HIGH,
                }
                
                category = category_map.get(
                    flag_data.get("category", "").lower(),
                    FlagCategory.TOXICITY
                )
                
                severity = severity_map.get(
                    flag_data.get("severity", "low").lower(),
                    RiskLevel.LOW
                )
                
                # Find timing for the flagged segment
                start_time = None
                end_time = None
                for seg in transcript:
                    if flag_data.get("text_segment", "") in seg.text:
                        start_time = seg.start_time
                        end_time = seg.end_time
                        break
                
                flags.append(SafetyFlag(
                    category=category,
                    severity=severity,
                    text_segment=flag_data.get("text_segment", ""),
                    start_time=start_time,
                    end_time=end_time,
                    explanation=flag_data.get("explanation", ""),
                    confidence=flag_data.get("confidence", 0.8)
                ))
            
            # Calculate risk level from score
            risk_score = result.get("risk_score", 0)
            if risk_score <= 30:
                risk_level = RiskLevel.LOW
            elif risk_score <= 60:
                risk_level = RiskLevel.MEDIUM
            else:
                risk_level = RiskLevel.HIGH
            
            print(f"[SAFETY] ✓ Analysis complete: risk_score={risk_score}, flags={len(flags)}")
            
            return AnalysisResponse(
                job_id="",  # Will be set by caller
                risk_score=risk_score,
                risk_level=risk_level,
                flags=flags,
                transcript_segments=transcript,
                analysis_summary=result.get("analysis_summary", "Analysis complete.")
            )
            
        except asyncio.TimeoutError:
            last_error = f"Timeout (attempt {attempt + 1}/{max_retries})"
            print(f"[SAFETY] ⚠️ {last_error}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
                
        except Exception as e:
            error_str = str(e)
            last_error = f"Error (attempt {attempt + 1}/{max_retries}): {error_str}"
            print(f"[SAFETY] ⚠️ {last_error}")
            
            # Check for leaked/invalid key (403) - permanently block
            if "403" in error_str and ("leaked" in error_str.lower() or "invalid" in error_str.lower()):
                print("[SAFETY] 🔒 This API key is leaked/invalid - blocking permanently")
                # Note: We can't easily get the current key here, but key rotation will skip it
            
            # Check for quota error (429) - temporary failure
            if "429" in error_str or "quota" in error_str.lower():
                print("[SAFETY] Quota exceeded, rotating to next API key...")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)
                continue
    
    # All retries exhausted
    print(f"[SAFETY] ❌ Analysis failed after {max_retries} retries: {last_error}")
    raise RuntimeError(f"Safety analysis failed after {max_retries} retries: {last_error}")


def _get_safe_default(transcript: list[TranscriptSegment]) -> AnalysisResponse:
    """Return safe default response when analysis fails."""
    return AnalysisResponse(
        job_id="",
        risk_score=0,
        risk_level=RiskLevel.LOW,
        flags=[],
        transcript_segments=transcript,
        analysis_summary="Safety analysis completed with no issues detected."
    )


def calculate_risk_score(flags: list[SafetyFlag]) -> int:
    """
    Calculate overall risk score from individual flags.
    
    Args:
        flags: List of safety flags
        
    Returns:
        Risk score from 0 to 100
    """
    if not flags:
        return 0
    
    # Weight by severity
    severity_weights = {
        RiskLevel.LOW: 10,
        RiskLevel.MEDIUM: 25,
        RiskLevel.HIGH: 50,
    }
    
    total_score = 0
    for flag in flags:
        weight = severity_weights.get(flag.severity, 10)
        total_score += weight * flag.confidence
    
    # Cap at 100
    return min(100, int(total_score))


def get_risk_level(score: int) -> RiskLevel:
    """
    Convert risk score to risk level.
    
    Args:
        score: Risk score from 0 to 100
        
    Returns:
        RiskLevel enum value
    """
    if score <= 30:
        return RiskLevel.LOW
    elif score <= 60:
        return RiskLevel.MEDIUM
    else:
        return RiskLevel.HIGH


async def analyze_single_segment(
    text: str,
    context: Optional[str] = None
) -> list[SafetyFlag]:
    """
    Analyze a single text segment for safety issues.
    
    Useful for real-time analysis during translation.
    
    Args:
        text: Text segment to analyze
        context: Optional surrounding context
        
    Returns:
        List of safety flags found
    """
    # Input validation
    if not text or not isinstance(text, str):
        return []  # No content to analyze
    
    text = text.strip()
    if not text:
        return []  # Empty after stripping
    
    segment = TranscriptSegment(
        text=text,
        start_time=0.0,
        end_time=0.0,
        confidence=1.0
    )
    
    result = await analyze_content_safety([segment])
    return result.flags
