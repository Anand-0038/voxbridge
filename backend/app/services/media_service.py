"""
Media processing service for video/audio operations.

Uses ffmpeg for video processing and audio merging.
Implements timeline-based audio placement with absolute timestamps.

KEY DESIGN DECISIONS:
1. Use WAV internally (not MP3) to avoid encoder delay/drift
2. Use adelay + amix for timeline placement (not concat protocol)
3. Normalize segment duration BEFORE placement
4. Use sidechain compression for background ducking (not static volume)
5. Force consistent audio format everywhere (44100Hz stereo)
"""

import asyncio
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from app.utils.helpers import get_absolute_path

# ================================================================
# CONSTANTS - Force consistent audio format everywhere
# ================================================================
SAMPLE_RATE = 44100
CHANNELS = 2  # stereo
INTERNAL_FORMAT = "wav"  # WAV internally to avoid encoder delay


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    return shutil.which("ffmpeg") is not None


async def check_audio_stream(videopath: str) -> bool:
    """Check if video has audio stream."""
    cmd = ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
           '-show_entries', 'stream=codec_type',
           '-of', 'default=noprint_wrappers=1:nokey=1', videopath]
    
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, _ = await process.communicate()
    return b'audio' in stdout


async def validate_audio_in_video(videopath: str) -> dict:
    """Validate video has audio and get codec info."""
    import json
    
    cmd = ['ffprobe', '-v', 'error',
           '-show_entries', 'stream=codec_type,codec_name,bit_rate',
           '-of', 'json', videopath]
    
    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE)
    stdout, _ = await process.communicate()
    
    try:
        data = json.loads(stdout)
        audio_streams = [s for s in data.get('streams', []) 
                        if s.get('codec_type') == 'audio']
        
        if audio_streams:
            return {
                'has_audio': True,
                'audio_codec': audio_streams[0].get('codec_name'),
                'bitrate': audio_streams[0].get('bit_rate')
            }
    except json.JSONDecodeError:
        pass
    
    return {'has_audio': False, 'audio_codec': None, 'bitrate': None}


async def validate_merged_output(video_path: str, expected_duration: float, strict: bool = True) -> dict:
    """
    Validate that merged video has correct audio and duration.
    Prevents silent/broken outputs from reaching users.
    
    Args:
        video_path: Path to the merged video
        expected_duration: Expected duration in seconds
        strict: If False, duration mismatch becomes warning instead of error
        
    Returns:
        Dict with validation results
        
    Raises:
        RuntimeError: If validation fails (when strict=True)
    """
    import json
    
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "stream=codec_type,duration,codec_name,sample_rate:format=duration",
        "-of", "json",
        video_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, _ = await process.communicate()
    
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Failed to probe video: {video_path}")
    
    # Check audio stream exists
    audio_streams = [s for s in data.get('streams', []) 
                     if s.get('codec_type') == 'audio']
    
    if not audio_streams:
        raise RuntimeError(f"Merge failed: No audio stream in {video_path}")
    
    # Check duration
    actual_duration = float(data.get('format', {}).get('duration', 0))
    duration_diff = abs(actual_duration - expected_duration)
    
    if strict and duration_diff > 1.0:  # 1 second tolerance
        raise RuntimeError(
            f"Duration mismatch: {actual_duration:.1f}s vs expected {expected_duration:.1f}s"
        )
    elif duration_diff > 1.0:
        print(f"[VALIDATION] WARNING: Duration mismatch: {duration_diff:.2f}s")
    
    return {
        'valid': True,
        'duration': actual_duration,
        'audio_codec': audio_streams[0].get('codec_name'),
        'sample_rate': audio_streams[0].get('sample_rate'),
        'expected_duration': expected_duration,
        'duration_diff': duration_diff
    }


async def get_audio_duration(audio_path: str) -> float:
    """Get the duration of an audio file in seconds."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, _ = await process.communicate()
    
    if process.returncode == 0 and stdout:
        try:
            return float(stdout.decode().strip())
        except ValueError:
            return 0.0
    
    return 0.0


async def get_video_duration(video_path: str) -> float:
    """Get the duration of a video file in seconds."""
    return await get_audio_duration(video_path)  # ffprobe works for both


# ================================================================
# FIX 4 - FORCE CONSISTENT AUDIO FORMAT EVERYWHERE
# ================================================================
async def normalize_audio_format(input_path: str, output_path: str) -> str:
    """
    Normalize audio to consistent format: 44100Hz stereo WAV.
    
    This prevents encoding issues from mixing different formats.
    """
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-c:a", "pcm_s16le",  # WAV format
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    await process.communicate()
    
    if process.returncode == 0 and os.path.exists(output_path):
        return output_path
    
    raise RuntimeError(f"Failed to normalize audio: {input_path}")


async def encode_audio_format(input_path: str, output_path: str) -> str:
    """Encode an internally normalized audio track to the requested format.

    Timeline mixing always produces PCM WAV.  Output artifacts may use a
    compressed format, such as MP3, so the codec must match the destination
    extension instead of relying on FFmpeg's implicit format selection.
    """
    input_path = get_absolute_path(input_path)
    output_path = get_absolute_path(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    extension = Path(output_path).suffix.lower()
    if extension == ".mp3":
        codec_args = ["-c:a", "libmp3lame", "-b:a", "192k"]
    elif extension == ".wav":
        codec_args = ["-c:a", "pcm_s16le"]
    else:
        raise ValueError(f"Unsupported audio output format: {extension or 'none'}")

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        *codec_args,
        output_path,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()

    if process.returncode != 0 or not os.path.exists(output_path):
        print(f"[ENCODE] FFmpeg error: {stderr.decode(errors='replace')}")
        raise RuntimeError(f"Failed to encode audio as {extension}")

    return output_path


# ================================================================
# FIX 2 - NORMALIZE SEGMENT DURATION BEFORE PLACEMENT
# Uses rubberband for high-quality time-stretching
# ================================================================
async def normalize_segment_duration(
    audio_path: str,
    target_duration: float,
    output_path: str,
    tolerance: float = 0.02  # TIGHTENED: 20ms tolerance for professional quality
) -> str:
    """
    Normalize audio to EXACTLY match target duration using rubberband.
    
    Rubberband provides better quality than FFmpeg's atempo filter. The
    external rubberband CLI is preferred, then FFmpeg's native rubberband
    filter, and finally the bounded atempo fallback.
    
    | Case            | Action                     |
    | actual < target | pad silence                |
    | actual ≈ target | OK (format normalize only) |
    | actual > target | rubberband time-stretch    |
    
    Args:
        audio_path: Path to input audio
        target_duration: Desired duration in seconds
        output_path: Path for normalized audio
        tolerance: Duration tolerance in seconds (default 20ms)
        
    Returns:
        Path to normalized audio file
    """
    if target_duration <= 0:
        raise ValueError("Target audio duration must be greater than zero")

    actual_duration = await get_audio_duration(audio_path)
    
    if actual_duration <= 0:
        raise RuntimeError(f"Invalid audio duration: {audio_path}")
    
    # Close enough - just normalize format
    if abs(actual_duration - target_duration) <= tolerance:
        return await normalize_audio_format(audio_path, output_path)
    
    # Audio too short - pad with silence
    if actual_duration < target_duration:
        pad_duration = target_duration - actual_duration
        cmd = [
            "ffmpeg", "-y", "-i", audio_path,
            "-af", f"apad=pad_dur={pad_duration}",
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-c:a", "pcm_s16le",
            "-t", str(target_duration),  # Ensure exact length
            output_path
        ]
        
        print(f"[NORM] {os.path.basename(audio_path)}: {actual_duration:.2f}s → {target_duration:.2f}s (padding)")
        
        # Use a bounded synchronous subprocess for sequential segment
        # conversion.  The local asyncio subprocess transport can hang after
        # several FFmpeg invocations even though the same command succeeds.
        try:
            completed = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print("[NORM] Padding timed out; falling back to format normalization")
            return await normalize_audio_format(audio_path, output_path)

        if completed.returncode != 0:
            print(f"[NORM] Padding failed: {completed.stderr}")
            return await normalize_audio_format(audio_path, output_path)
        
        return output_path
    
    # Audio too long - time-stretch
    ratio = target_duration / actual_duration
    print(f"[NORM] {os.path.basename(audio_path)}: {actual_duration:.2f}s → {target_duration:.2f}s (stretch ratio: {ratio:.3f})")
    
    # Try rubberband first (best quality)
    if shutil.which("rubberband"):
        try:
            temp_rubberband_output = output_path + ".rubberband.wav"
            
            cmd = [
                "rubberband",
                "--time", str(ratio),  # Time stretch ratio
                "--pitch", "1.0",      # Preserve pitch
                "--threads", "4",
                audio_path,
                temp_rubberband_output
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            _, stderr = await process.communicate()
            
            if process.returncode == 0:
                # FIX BUG#1: Rubberband output needs format normalization to 44100Hz stereo
                await normalize_audio_format(temp_rubberband_output, output_path)
                
                # Clean up rubberband temp file
                if os.path.exists(temp_rubberband_output):
                    os.remove(temp_rubberband_output)
                
                # Verify final duration
                final_duration = await get_audio_duration(output_path)
                duration_error = abs(final_duration - target_duration)
                
                if duration_error > tolerance:
                    print(f"[NORM] WARNING: Duration still off by {duration_error:.3f}s")
                else:
                    print(f"[NORM] ✓ Rubberband success: {actual_duration:.2f}s → {final_duration:.2f}s")
                
                return output_path
            else:
                print(f"[NORM] Rubberband failed: {stderr.decode()[:200]}, falling back to atempo")
                
        except Exception as e:
            print(f"[NORM] Rubberband exception: {e}, falling back to atempo")
    else:
        if await asyncio.to_thread(_ffmpeg_has_filter, "rubberband"):
            print("[NORM] Rubberband CLI not found; using FFmpeg's native rubberband filter")
            if await _normalize_with_ffmpeg_rubberband(
                audio_path, target_duration, output_path, ratio
            ):
                return output_path
        print("[NORM] Rubberband unavailable - using atempo fallback")
    
    # Fallback to atempo
    return await _normalize_with_atempo(audio_path, target_duration, output_path)


@lru_cache(maxsize=8)
def _ffmpeg_has_filter(filter_name: str) -> bool:
    """Check once whether the installed FFmpeg exposes a named audio filter."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False

    return any(
        len(fields) > 1 and fields[1] == filter_name
        for fields in (line.split() for line in result.stdout.splitlines())
    )


def has_rubberband_support() -> bool:
    """Return whether either the Rubber Band CLI or FFmpeg filter is usable."""
    return shutil.which("rubberband") is not None or _ffmpeg_has_filter("rubberband")


async def _normalize_with_ffmpeg_rubberband(
    audio_path: str,
    target_duration: float,
    output_path: str,
    ratio: float,
) -> bool:
    """Use FFmpeg's native rubberband filter when the CLI is unavailable."""
    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-af", f"rubberband=tempo={1.0 / ratio:.6f}:pitch=1.0",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-c:a", "pcm_s16le",
        "-t", str(target_duration),
        output_path,
    ]
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode == 0 and os.path.exists(output_path):
        return True

    print(f"[NORM] FFmpeg rubberband failed: {stderr.decode(errors='replace')[:500]}")
    return False


async def _normalize_with_atempo(
    audio_path: str,
    target_duration: float,
    output_path: str
) -> str:
    """
    Fallback time-stretching using ffmpeg atempo filter.
    
    atempo accepts 0.5 to 2.0, chain filters for larger ratios.
    """
    if target_duration <= 0:
        raise ValueError("Target audio duration must be greater than zero")

    actual_duration = await get_audio_duration(audio_path)
    ratio = target_duration / actual_duration
    atempo_filter = _build_atempo_filter(ratio)

    cmd = [
        "ffmpeg", "-y", "-i", audio_path,
        "-af", f"{atempo_filter},apad=whole_dur={target_duration}",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-c:a", "pcm_s16le",
        "-t", str(target_duration),  # Hard limit to exact duration
        output_path
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    _, stderr = await process.communicate()

    if process.returncode != 0:
        print(f"[NORM] atempo Error: {stderr.decode()}")
        # Last resort fallback: just normalize format
        return await normalize_audio_format(audio_path, output_path)

    return output_path


def _build_atempo_filter(ratio: float) -> str:
    """Build a valid FFmpeg atempo chain for an output/input duration ratio.

    FFmpeg accepts each atempo factor only in the range 0.5..2.0. A ratio
    outside that range needs multiple filters; keeping this calculation
    separate makes the boundary easy to test without invoking FFmpeg.
    """
    if ratio <= 0:
        raise ValueError("Audio duration ratio must be greater than zero")

    if ratio < 0.5:
        # Very aggressive speedup needed - chain atempo filters
        tempo_chain = []
        remaining = 1.0 / ratio  # How much to speed up
        while remaining > 2.0:
            tempo_chain.append("atempo=2.0")
            remaining /= 2.0
        if remaining > 1.0:
            tempo_chain.append(f"atempo={remaining:.4f}")
    elif ratio > 2.0:
        # Slow down significantly
        tempo_chain = []
        remaining = ratio
        while remaining > 2.0:
            tempo_chain.append("atempo=0.5")
            remaining /= 2.0
        if remaining > 1.0:
            tempo_chain.append(f"atempo={1.0 / remaining:.4f}")
    else:
        tempo_chain = [f"atempo={1.0 / ratio:.4f}"]

    return ",".join(tempo_chain)


# ================================================================
# FIX 1 - TIMELINE-BASED PLACEMENT WITH ADELAY + AMIX
# ================================================================
async def place_audio_on_timeline(
    segments: List[dict],
    total_duration: float,
    output_path: str,
    temp_dir: str
) -> str:
    """
    Place audio segments at absolute timestamps using adelay + amix.
    
    THIS IS THE CORRECT WAY to do dubbing - professional systems use this.
    
    Instead of concat (which accumulates drift), we:
    1. Normalize each segment to its target duration
    2. Delay each segment to its absolute start timestamp
    3. Mix all delayed tracks together
    
    Args:
        segments: List of dicts with 'audio_path', 'start_time', 'end_time'
        total_duration: Total video duration in seconds
        output_path: Path for final mixed audio
        temp_dir: Directory for temporary files
        
    Returns:
        Path to mixed audio file
    """
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg not found in PATH")
    
    if not segments:
        raise ValueError("No audio segments provided")

    if total_duration <= 0:
        raise ValueError("Total duration must be greater than zero")
    
    output_path = get_absolute_path(output_path)
    temp_dir = get_absolute_path(temp_dir)
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    # Sort segments by start time
    sorted_segments = sorted(segments, key=lambda x: x.get('start_time', 0))
    
    # Prepare normalized segments
    normalized_files = []
    cleanup_files = []
    
    for i, segment in enumerate(sorted_segments):
        audio_path = segment.get('audio_path')
        start_time = segment.get('start_time', 0)
        end_time = segment.get('end_time', start_time + 5)
        target_duration = end_time - start_time
        
        if not audio_path:
            print(f"[TIMELINE] Skipping segment {i}: no audio path")
            continue
            
        abs_audio_path = get_absolute_path(audio_path)
        if not os.path.exists(abs_audio_path):
            print(f"[TIMELINE] Skipping segment {i}: file not found: {abs_audio_path}")
            continue
        
        # Normalize duration
        normalized_path = os.path.join(temp_dir, f"norm_{i}.wav")
        try:
            await normalize_segment_duration(abs_audio_path, target_duration, normalized_path)
            normalized_files.append({
                'path': normalized_path,
                'start_ms': round(start_time * 1000),  # FIX BUG#4: Use round() instead of int() to avoid drift
                'index': i
            })
            cleanup_files.append(normalized_path)
        except Exception as e:
            print(f"[TIMELINE] Error normalizing segment {i}: {e}")
            continue
    
    if not normalized_files:
        print("[TIMELINE] No valid segments after normalization; generating silent baseline")
        silence_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=stereo:sample_rate={SAMPLE_RATE}",
            "-t",
            str(total_duration),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "-c:a",
            "pcm_s16le",
            output_path,
        ]

        process = await asyncio.create_subprocess_exec(
            *silence_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()

        if process.returncode != 0:
            raise RuntimeError(f"Failed to create silent baseline: {stderr.decode(errors='replace')}")

        return output_path
    
    # If only one segment, just delay and output
    if len(normalized_files) == 1:
        seg = normalized_files[0]
        cmd = [
            "ffmpeg", "-y", "-i", seg['path'],
            "-af", f"adelay={seg['start_ms']}|{seg['start_ms']},apad=pad_dur={total_duration}",
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-c:a", "pcm_s16le",
            "-t", str(total_duration),
            output_path
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()

        _cleanup_temp_files(cleanup_files)
        if process.returncode != 0 or not os.path.exists(output_path):
            raise RuntimeError(
                f"Timeline placement failed: {stderr.decode(errors='replace')[-1000:]}"
            )
        return output_path
    
    # Build filter_complex for multiple segments
    # Format: [0:a]adelay=1000|1000[a0];[1:a]adelay=4200|4200[a1];[a0][a1]amix=inputs=2[out]
    
    inputs = []
    filter_parts = []
    mix_inputs = []
    
    for seg in normalized_files:
        idx = seg['index']
        start_ms = seg['start_ms']
        
        inputs.extend(["-i", seg['path']])
        filter_parts.append(f"[{len(mix_inputs)}:a]adelay={start_ms}|{start_ms}[a{idx}]")
        mix_inputs.append(f"[a{idx}]")
    
    # Add amix to combine all delayed tracks
    mix_filter = f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=longest:dropout_transition=0[mixed]"
    filter_parts.append(mix_filter)
    
    # Pad to total duration
    filter_parts.append(f"[mixed]apad=pad_dur={total_duration}[out]")
    
    filter_complex = ";".join(filter_parts)
    
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-c:a", "pcm_s16le",
        "-t", str(total_duration),
        output_path
    ]
    
    print(f"[TIMELINE] Mixing {len(normalized_files)} segments on timeline")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    _, stderr = await process.communicate()
    
    _cleanup_temp_files(cleanup_files)
    
    if process.returncode != 0:
        print(f"[TIMELINE] FFmpeg error: {stderr.decode()}")
        raise RuntimeError("Timeline mixing failed. Check server logs for FFmpeg details.")
    
    print(f"[TIMELINE] ✓ Created timeline-synced audio: {output_path}")
    return output_path


def _cleanup_temp_files(files: List[str]):
    """Clean up temporary files."""
    for f in files:
        try:
            if f and os.path.exists(f):
                os.remove(f)
        except Exception:
            pass


# ================================================================
# FIX 3 - SIDECHAIN COMPRESSION FOR BACKGROUND DUCKING
# ================================================================
async def merge_audio_video(
    video_path: str,
    audio_path: str,
    output_path: str,
    preserve_background: bool = False
) -> str:
    """
    Merge new audio track with original video.
    
    Uses sidechain compression for natural background ducking instead of
    static volume reduction.
    
    Args:
        video_path: Path to input video
        audio_path: Path to new audio track
        output_path: Path for output video
        preserve_background: If True, duck original audio when voice plays
        
    Returns:
        Path to output video with merged audio
    """
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg not found in PATH")
        
    video_path = get_absolute_path(video_path)
    audio_path = get_absolute_path(audio_path)
    output_path = get_absolute_path(output_path)
    
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    
    if output_path == video_path:
        raise ValueError("Output path cannot be same as input video path")
    
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")
    
    if preserve_background:
        has_original_audio = await check_audio_stream(video_path)
        
        if has_original_audio:
            # FIX 3: Improved sidechain compression for professional ducking
            # - threshold=0.003: Duck when voice exceeds -50dB (more sensitive)
            # - ratio=20: Stronger compression (20:1 instead of 8:1)
            # - attack=5: Faster response (5ms for immediate ducking)
            # - release=200: Smooth 200ms release for natural recovery
            # - makeup=2: Boost output by 2dB after compression
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex",
                # Sidechain compression: duck [0:a] when [1:a] is present
                (
                    "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[voice];"
                    "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo[bg];"
                    "[voice]asplit=2[voice_sc][voice_mix];"
                    "[bg][voice_sc]sidechaincompress=threshold=0.003:ratio=20:attack=5:release=200:makeup=2[ducked];"
                    "[ducked][voice_mix]amix=inputs=2:duration=first:dropout_transition=0[out]"
                ),
                "-map", "0:v",
                "-map", "[out]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                output_path
            ]
        else:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "192k",
                "-map", "0:v",
                "-map", "1:a",
                "-shortest",
                output_path
            ]
    else:
        # Replace original audio entirely
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-map", "0:v",
            "-map", "1:a",
            "-shortest",
            output_path
        ]
    
    print(f"[MERGE] Running ffmpeg merge...")
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    # Dynamic timeout based on video duration
    video_duration = await get_video_duration(video_path)
    dynamic_timeout = max(60, min(3600, video_duration * 3 + 60))
    
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=dynamic_timeout)
    except asyncio.TimeoutError:
        process.kill()
        raise RuntimeError(f"FFmpeg merge timed out after {dynamic_timeout:.0f}s")
    
    if process.returncode != 0:
        print(f"[MERGE] FFmpeg error: {stderr.decode()}")
        raise RuntimeError("Audio-video merge failed. Check server logs for FFmpeg details.")
    
    # FIX 7 - VALIDATION HOOK AFTER MERGE
    if not os.path.exists(output_path):
        raise RuntimeError(f"FFmpeg finished but output file missing: {output_path}")
        
    if os.path.getsize(output_path) == 0:
        raise RuntimeError(f"FFmpeg created empty file: {output_path}")
    
    # Verify output has audio
    audio_info = await validate_audio_in_video(output_path)
    if not audio_info['has_audio']:
        raise RuntimeError(f"Output video has no audio stream: {output_path}")
    
    # Verify duration matches (within tolerance)
    output_duration = await get_video_duration(output_path)
    if abs(output_duration - video_duration) > 1.0:
        print(f"[MERGE] WARNING: Duration mismatch! Input: {video_duration:.2f}s, Output: {output_duration:.2f}s")
    
    print(f"[MERGE] ✓ Audio merged: {audio_info['audio_codec']}, {output_duration:.1f}s")
    return output_path


# ================================================================
# MAIN ENTRY POINT FOR DUBBING PIPELINE
# ================================================================
async def create_dubbed_audio_track(
    segments: List[dict],
    video_path: str,
    output_audio_path: str,
    temp_dir: str
) -> str:
    """
    Create dubbed audio track from TTS segments using timeline placement.
    
    This is the main entry point that replaces the old concatenate functions.
    
    Args:
        segments: List of dicts with 'audio_path', 'start_time', 'end_time'
        video_path: Original video path (to get duration)
        output_audio_path: Where to save the final audio track
        temp_dir: Directory for temporary files
        
    Returns:
        Path to the synchronized audio track
    """
    video_duration = await get_video_duration(video_path)
    
    if video_duration <= 0:
        # Fallback: calculate from segments
        video_duration = max(s.get('end_time', 0) for s in segments) + 1.0
    
    return await place_audio_on_timeline(
        segments=segments,
        total_duration=video_duration,
        output_path=output_audio_path,
        temp_dir=temp_dir
    )


# ================================================================
# LEGACY WRAPPERS - For backward compatibility
# ================================================================
async def extract_audio(video_path: str, output_path: Optional[str] = None) -> str:
    """Extract audio track from video file."""
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg not found in PATH")
        
    video_path = get_absolute_path(video_path)
    if output_path:
        output_path = get_absolute_path(output_path)
    
    if not output_path:
        # Use WAV for internal processing (FIX 5)
        output_path = str(Path(video_path).with_suffix('.wav'))
    
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    # Extract to WAV for consistent processing
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-c:a", "pcm_s16le",
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    _, stderr = await process.communicate()
    
    if process.returncode != 0:
        print(f"[EXTRACT] FFmpeg error: {stderr.decode()}")
        raise RuntimeError(f"Audio extraction failed: {stderr.decode()}")
    
    return output_path


async def concatenate_audio_with_timing(
    segments: List[dict],
    output_path: str,
    temp_dir: Optional[str] = None
) -> str:
    """
    DEPRECATED: Use create_dubbed_audio_track() instead.
    
    This wrapper exists for backward compatibility.
    Redirects to timeline-based placement.
    """
    if not temp_dir:
        temp_dir = os.path.dirname(output_path)
    
    # Calculate total duration from segments
    total_duration = max(s.get('end_time', 0) for s in segments) + 1.0
    
    return await place_audio_on_timeline(
        segments=segments,
        total_duration=total_duration,
        output_path=output_path,
        temp_dir=temp_dir
    )


async def concatenate_audio_segments(
    audio_files: list[str],
    output_path: str
) -> str:
    """
    DEPRECATED: Use create_dubbed_audio_track() for proper sync.
    
    Simple concatenation without timing - DO NOT USE FOR DUBBING.
    Preserved only for legacy compatibility.
    """
    if not check_ffmpeg():
        raise RuntimeError("ffmpeg not found in PATH")
    
    if not audio_files:
        raise ValueError("No audio files provided")
    
    output_path = get_absolute_path(output_path)
    audio_files = [get_absolute_path(f) for f in audio_files]
    valid_files = [f for f in audio_files if os.path.exists(f)]
    
    if not valid_files:
        raise ValueError("No valid audio files found")
    
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    
    if len(valid_files) == 1:
        shutil.copy(valid_files[0], output_path)
        return output_path
    
    concat_file = output_path + ".txt"
    with open(concat_file, "w") as f:
        for audio_file in valid_files:
            escaped_path = os.path.abspath(audio_file).replace("'", "'\\''")
            f.write(f"file '{escaped_path}'\n")
    
    # Use WAV output and loudnorm
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_file,
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-ar", str(SAMPLE_RATE),
        "-ac", str(CHANNELS),
        "-c:a", "pcm_s16le",
        output_path
    ]
    
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    _, stderr = await process.communicate()
    
    if os.path.exists(concat_file):
        os.remove(concat_file)
    
    if process.returncode != 0:
        raise RuntimeError(f"Audio concatenation failed: {stderr.decode()}")
    
    return output_path
