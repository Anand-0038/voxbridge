"""Validated YouTube acquisition for the local VoxBridge pipeline."""

import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

from app.utils.helpers import get_absolute_path


YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
VIDEO_PATH_PREFIXES = ("/watch", "/shorts/", "/embed/", "/live/")


def normalize_youtube_url(value: str) -> str:
    """Validate and normalize a single-video YouTube URL.

    The allowlist prevents this downloader from becoming a general-purpose
    server-side request proxy. Playlists are disabled in yt-dlp as a second
    boundary, but a valid video URL may still contain a playlist referral.
    """
    candidate = value.strip()
    parsed = urlparse(candidate)
    host = parsed.hostname.lower().removeprefix("www.") if parsed.hostname else ""

    if parsed.scheme != "https" or host not in YOUTUBE_HOSTS:
        raise ValueError("Only https://www.youtube.com or https://youtu.be URLs are supported")

    query = parse_qs(parsed.query)
    if host == "youtu.be":
        if not parsed.path.strip("/"):
            raise ValueError("The YouTube URL does not contain a video ID")
    elif parsed.path == "/watch":
        if not query.get("v", [""])[0]:
            raise ValueError("The YouTube watch URL does not contain a video ID")
    elif not parsed.path.startswith(VIDEO_PATH_PREFIXES[1:]):
        raise ValueError("The YouTube URL must point to one video, not a channel or playlist")

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def _download_youtube_video(url: str, output_dir: str, job_id: str) -> dict:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("YouTube import requires the yt-dlp package") from exc

    output_template = str(Path(output_dir) / f"{job_id}.%(ext)s")
    options = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "noplaylist": True,
        "restrictfilenames": True,
        "quiet": True,
        "no_warnings": True,
    }

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            prepared_path = Path(downloader.prepare_filename(info))
    except Exception as exc:
        raise RuntimeError(f"YouTube download failed: {exc}") from exc

    candidates = [prepared_path, Path(output_dir) / f"{job_id}.mp4"]
    candidates.extend(
        path
        for path in Path(output_dir).glob(f"{job_id}.*")
        if path.suffix.lower() not in {".part", ".ytdl"}
    )
    downloaded_path = next((path for path in candidates if path.is_file()), None)
    if downloaded_path is None:
        raise RuntimeError("YouTube download completed without a video file")

    max_bytes = int(os.getenv("MAX_UPLOAD_SIZE_MB", "500")) * 1024 * 1024
    if downloaded_path.stat().st_size > max_bytes:
        downloaded_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Downloaded video exceeds the {max_bytes // (1024 * 1024)}MB upload limit"
        )

    return {
        "file_path": str(downloaded_path),
        "filename": info.get("title") or downloaded_path.name,
        "title": info.get("title"),
        "duration": info.get("duration"),
    }


async def download_youtube_video(url: str, output_dir: str, job_id: str) -> dict:
    """Download one validated YouTube video without blocking FastAPI."""
    normalized_url = normalize_youtube_url(url)
    absolute_output_dir = get_absolute_path(output_dir)
    await asyncio.to_thread(os.makedirs, absolute_output_dir, exist_ok=True)
    result = await asyncio.to_thread(
        _download_youtube_video, normalized_url, absolute_output_dir, job_id
    )
    result["source_url"] = normalized_url
    return result
