"""
Utility functions for VoxBridge.
"""

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# Define project base directory (backend root)
BASE_DIR = Path(__file__).resolve().parent.parent.parent


def decode_json_object(value: object) -> dict:
    """Normalize a PostgreSQL JSON/JSONB value to a dictionary.

    asyncpg may return JSONB as a decoded mapping or as a JSON string,
    depending on connection codec configuration. Keeping this conversion at
    the data boundary prevents route handlers from calling mapping methods on
    an undecoded string.
    """
    if value is None or value == "":
        return {}

    decoded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(decoded, dict):
        raise TypeError("Expected a JSON object for persisted job state")
    return decoded


def get_absolute_path(path_str: str) -> str:
    """
    Resolve a path to an absolute path against BASE_DIR.
    If the path is already absolute, returns it as is.
    
    Args:
        path_str: The path to resolve
        
    Returns:
        Absolute path string
    """
    if not path_str:
        return path_str
        
    path = Path(path_str)
    if path.is_absolute():
        return str(path)
        
    return str(BASE_DIR / path)


def get_relative_path(path_str: str) -> str:
    """Return a safe project-relative path for persisted job state.

    Job state and audit records must never contain host-specific absolute
    paths.  Storage is intentionally rooted inside the backend directory, so
    rejecting paths outside that root also prevents an accidental path
    traversal from becoming durable state.
    """
    if not path_str:
        return path_str

    absolute_path = Path(get_absolute_path(path_str)).resolve()
    base_path = BASE_DIR.resolve()
    try:
        return absolute_path.relative_to(base_path).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Path must be inside the backend directory: {path_str}"
        ) from exc


def is_valid_uuid(value: str) -> bool:
    """
    Check if a string is a valid UUID.
    
    Args:
        value: String to validate
        
    Returns:
        True if valid UUID format
    """
    import re
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    return bool(uuid_pattern.match(value))


def validate_path_within_base(file_path: str, allowed_dirs: list[str] = None) -> bool:
    """
    Validate that a file path stays within allowed directories.
    Prevents path traversal attacks (e.g., ../../etc/passwd).
    Also resolves symlinks to prevent symlink-based bypass.
    
    Args:
        file_path: Path to validate
        allowed_dirs: List of allowed base directories (defaults to storage dirs)
        
    Returns:
        True if path is within allowed directories
    """
    if allowed_dirs is None:
        import os
        allowed_dirs = [
            os.getenv("UPLOAD_DIR", "storage/uploads"),
            os.getenv("PROCESSED_DIR", "storage/processed"),
            os.getenv("OUTPUT_DIR", "storage/outputs"),
        ]
    
    # Resolve to absolute path and follow symlinks (security fix)
    abs_path = Path(get_absolute_path(file_path)).resolve()
    
    # Reject if path contains symlinks that escape allowed dirs
    if abs_path.is_symlink():
        # Resolve the symlink target and check that
        try:
            real_path = abs_path.resolve(strict=True)
            abs_path = real_path
        except (OSError, RuntimeError):
            return False  # Broken symlink or loop
    
    # Check if resolved path is within any allowed directory
    for allowed_dir in allowed_dirs:
        allowed_abs = Path(get_absolute_path(allowed_dir)).resolve()
        try:
            abs_path.relative_to(allowed_abs)
            return True
        except ValueError:
            continue
    
    return False


def generate_file_hash(file_path: str) -> str:
    """
    Generate SHA-256 hash of a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Hexadecimal hash string
    """
    sha256_hash = hashlib.sha256()
    
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            sha256_hash.update(chunk)
    
    return sha256_hash.hexdigest()


def generate_text_hash(text: str) -> str:
    """
    Generate SHA-256 hash of text content.
    
    Args:
        text: Text to hash
        
    Returns:
        Hexadecimal hash string
    """
    return hashlib.sha256(text.encode()).hexdigest()


def format_timestamp(dt: Optional[datetime] = None) -> str:
    """
    Format datetime as ISO 8601 string.
    
    Args:
        dt: Datetime to format (default: now)
        
    Returns:
        Formatted timestamp string
    """
    if dt is None:
        dt = datetime.utcnow()
    return dt.isoformat() + "Z"


def get_file_extension(filename: str) -> str:
    """
    Get file extension from filename.
    
    Args:
        filename: Name or path of file
        
    Returns:
        File extension with dot (e.g., '.mp4')
    """
    return os.path.splitext(filename)[1].lower()


def validate_video_format(filename: str) -> bool:
    """
    Check if file has a valid video extension.
    
    Args:
        filename: Name or path of file
        
    Returns:
        True if valid video format
    """
    valid_extensions = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
    return get_file_extension(filename) in valid_extensions


def validate_audio_format(filename: str) -> bool:
    """
    Check if file has a valid audio extension.
    
    Args:
        filename: Name or path of file
        
    Returns:
        True if valid audio format
    """
    valid_extensions = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
    return get_file_extension(filename) in valid_extensions


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string (e.g., '2:34' or '1:02:34')
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename for safe storage.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename
    """
    # Remove path separators and dangerous characters
    dangerous_chars = ['/', '\\', '..', '\0', '\n', '\r']
    result = filename
    
    for char in dangerous_chars:
        result = result.replace(char, '_')
    
    # Limit length
    max_length = 200
    if len(result) > max_length:
        name, ext = os.path.splitext(result)
        result = name[:max_length - len(ext)] + ext
    
    return result


def calculate_confidence_level(score: float) -> str:
    """
    Convert confidence score to descriptive level.
    
    Args:
        score: Confidence score (0.0 to 1.0)
        
    Returns:
        Confidence level string
    """
    if score >= 0.9:
        return "high"
    elif score >= 0.7:
        return "medium"
    elif score >= 0.5:
        return "low"
    else:
        return "very_low"


# File signature (magic bytes) validation
VIDEO_SIGNATURES = {
    b'\x00\x00\x00\x20\x66\x74\x79\x70': 'video/mp4',  # MP4 ftyp at offset 4
    b'\x00\x00\x00\x18\x66\x74\x79\x70': 'video/mp4',  # MP4 variant
    b'\x00\x00\x00\x1c\x66\x74\x79\x70': 'video/mp4',  # MP4 variant
    b'\x00\x00\x00\x14\x66\x74\x79\x70': 'video/quicktime',  # MOV
    b'\x52\x49\x46\x46': 'video/x-msvideo',  # AVI (RIFF)
    b'\x1a\x45\xdf\xa3': 'video/webm',  # WebM/MKV
}


def validate_file_signature(file_path: str, expected_type: str = 'video') -> dict:
    """
    Validate file by checking magic bytes (file signature).
    
    Prevents malicious files from being uploaded with fake extensions.
    
    Args:
        file_path: Path to file to validate
        expected_type: 'video' or 'audio'
        
    Returns:
        Dict with 'valid' bool, 'detected_type' string, and 'message'
    """
    try:
        with open(file_path, 'rb') as f:
            header = f.read(32)
        
        if len(header) < 8:
            return {'valid': False, 'detected_type': None, 'message': 'File too small'}
        
        # Check for MP4 - look for 'ftyp' marker
        if b'ftyp' in header:
            return {'valid': True, 'detected_type': 'video/mp4', 'message': 'Valid MP4'}
        
        # Check other signatures
        for sig, mime_type in VIDEO_SIGNATURES.items():
            if header.startswith(sig):
                return {'valid': True, 'detected_type': mime_type, 'message': f'Valid {expected_type}'}
        
        return {'valid': False, 'detected_type': None, 'message': 'Unknown format'}
        
    except Exception as e:
        return {'valid': False, 'detected_type': None, 'message': str(e)}


def validate_segment_continuity(segments: list[dict]) -> dict:
    """
    Validate that audio segments are continuous without overlaps.
    
    Args:
        segments: List of segment dicts with 'start_time' and 'end_time'
        
    Returns:
        Dict with 'valid' bool, 'gaps' list, and 'overlaps' list
    """
    if not segments:
        return {'valid': True, 'gaps': [], 'overlaps': []}
    
    sorted_segs = sorted(segments, key=lambda x: x.get('start_time', 0))
    gaps, overlaps = [], []
    
    for i in range(1, len(sorted_segs)):
        prev_end = sorted_segs[i-1].get('end_time', 0)
        curr_start = sorted_segs[i].get('start_time', 0)
        gap = curr_start - prev_end
        
        if gap > 0.1:  # 100ms gap threshold
            gaps.append({'after': i - 1, 'gap': round(gap, 2)})
        elif gap < -0.1:  # Overlap
            overlaps.append({'segments': [i - 1, i], 'overlap': round(-gap, 2)})
    
    return {'valid': len(overlaps) == 0, 'gaps': gaps, 'overlaps': overlaps}


def validate_segment_timings(segments: list[dict], max_gap: float = 0.5) -> dict:
    """
    Check for timing issues: overlaps, large gaps, zero-duration segments.
    
    More comprehensive than validate_segment_continuity - catches issues
    that can cause pipeline failures.
    
    Args:
        segments: List of dicts with 'start_time' and 'end_time'
        max_gap: Maximum allowed gap between segments (default 0.5s)
        
    Returns:
        Dict with 'valid', 'errors', 'warnings'
    """
    errors = []
    warnings = []
    
    if not segments:
        return {'valid': True, 'errors': [], 'warnings': ['No segments provided']}
    
    for i, seg in enumerate(segments):
        start = seg.get('start_time', 0)
        end = seg.get('end_time', 0)
        
        # Zero-duration check
        if end <= start:
            errors.append(f"Segment {i}: zero/negative duration ({start:.2f}-{end:.2f})")
        
        # Check continuity
        if i > 0:
            prev_end = segments[i-1].get('end_time', 0)
            gap = start - prev_end
            
            if gap < -0.05:  # Overlap (5ms tolerance)
                errors.append(f"Segment {i}: overlaps with {i-1} by {abs(gap):.2f}s")
            elif gap > max_gap:  # Large gap
                warnings.append(f"Segment {i}: large gap of {gap:.2f}s after {i-1}")
    
    return {
        'valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }
