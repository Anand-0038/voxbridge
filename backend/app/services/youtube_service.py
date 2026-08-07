"""Validated YouTube acquisition for the local VoxBridge pipeline."""

import asyncio
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlunparse

from app.utils.helpers import get_absolute_path

YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
VIDEO_PATH_PREFIXES = ("/watch", "/shorts/", "/embed/", "/live/")
YOUTUBE_AUTH_ERROR_MARKERS = (
    "sign in to confirm",
    "cookies-from-browser",
    "cookies for the authentication",
)


def _cleanup_download_artifacts(output_dir: str, job_id: str) -> None:
    """Remove only artifacts produced by one failed YouTube job."""
    for path in Path(output_dir).glob(f"{job_id}.*"):
        if path.is_file():
            try:
                path.unlink()
            except OSError as exc:
                print(f"[YOUTUBE] Could not remove partial artifact {path}: {exc}")


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
        raise ValueError(
            "Only https://www.youtube.com or https://youtu.be URLs are supported"
        )

    query = parse_qs(parsed.query)
    if host == "youtu.be":
        if not parsed.path.strip("/"):
            raise ValueError("The YouTube URL does not contain a video ID")
    elif parsed.path == "/watch":
        if not query.get("v", [""])[0]:
            raise ValueError("The YouTube watch URL does not contain a video ID")
    else:
        matching_prefix = next(
            (
                prefix
                for prefix in VIDEO_PATH_PREFIXES[1:]
                if parsed.path.startswith(prefix)
            ),
            None,
        )
        if not matching_prefix or not parsed.path[len(matching_prefix) :].strip("/"):
            raise ValueError(
                "The YouTube URL must point to one video, not a channel or playlist"
            )

    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def _parse_browser_cookie_spec(value: str) -> tuple[str | None, ...]:
    """Convert yt-dlp's browser cookie syntax into its Python tuple form."""
    spec = value.strip()
    if not spec:
        raise ValueError("YOUTUBE_COOKIES_FROM_BROWSER cannot be empty")

    browser_and_profile, separator, container = spec.partition("::")
    if separator and not container:
        raise ValueError(
            "YOUTUBE_COOKIES_FROM_BROWSER must include a container after '::'"
        )

    browser_and_keyring, profile_separator, profile = browser_and_profile.partition(":")
    browser, keyring_separator, keyring = browser_and_keyring.partition("+")
    browser = browser.strip().lower()
    if not browser:
        raise ValueError("YOUTUBE_COOKIES_FROM_BROWSER must name a browser")

    values: list[str | None] = [
        browser,
        profile.strip() if profile_separator and profile.strip() else None,
        keyring.strip() if keyring_separator and keyring.strip() else None,
        container.strip() if separator and container.strip() else None,
    ]
    while values and values[-1] is None:
        values.pop()
    return tuple(values)


def _youtube_auth_is_configured() -> bool:
    """Return whether yt-dlp will receive an authenticated YouTube session."""
    return bool(
        os.getenv("YOUTUBE_COOKIES_FROM_BROWSER", "").strip()
        or os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
    )


def _build_ytdlp_options(output_dir: str, job_id: str) -> dict:
    """Build download options without ever materializing cookies in app state."""
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

    browser_spec = os.getenv("YOUTUBE_COOKIES_FROM_BROWSER", "").strip()
    cookie_file = os.getenv("YOUTUBE_COOKIES_FILE", "").strip()
    if browser_spec and cookie_file:
        raise RuntimeError(
            "Configure only one of YOUTUBE_COOKIES_FROM_BROWSER or YOUTUBE_COOKIES_FILE"
        )

    if browser_spec:
        options["cookiesfrombrowser"] = _parse_browser_cookie_spec(browser_spec)
    elif cookie_file:
        cookie_path = Path(cookie_file).expanduser()
        if not cookie_path.is_absolute():
            cookie_path = Path(get_absolute_path(str(cookie_path)))
        if not cookie_path.is_file():
            raise RuntimeError("YOUTUBE_COOKIES_FILE is configured but the file is unavailable")
        options["cookiefile"] = str(cookie_path)

    user_agent = os.getenv("YOUTUBE_USER_AGENT", "").strip()
    if user_agent:
        options["http_headers"] = {"User-Agent": user_agent}

    remote_components = [
        component.strip()
        for component in os.getenv("YOUTUBE_REMOTE_COMPONENTS", "").split(",")
        if component.strip()
    ]
    if remote_components:
        options["remote_components"] = remote_components

    return options


def _format_youtube_download_error(exc: Exception) -> str:
    """Turn YouTube's bot-check failure into a safe, actionable local error."""
    message = str(exc).strip()
    lowered = message.lower()
    if not any(marker in lowered for marker in YOUTUBE_AUTH_ERROR_MARKERS):
        return f"YouTube download failed: {message}"

    if _youtube_auth_is_configured():
        return (
            "YouTube rejected the configured browser session. Refresh YouTube in "
            "that browser and retry; if it persists, export a fresh YouTube-only "
            "cookies file or set YOUTUBE_USER_AGENT to the matching browser user agent."
        )

    return (
        "YouTube requires an authenticated browser session for this request. "
        "Set YOUTUBE_COOKIES_FROM_BROWSER=chrome (or configure "
        "YOUTUBE_COOKIES_FILE) in backend/.env and restart the backend, or upload "
        "the video file directly. Never paste cookie values into chat or logs."
    )


def _download_youtube_video(url: str, output_dir: str, job_id: str) -> dict:
    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("YouTube import requires the yt-dlp package") from exc

    options = _build_ytdlp_options(output_dir, job_id)

    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=True)
            prepared_path = Path(downloader.prepare_filename(info))
    except Exception as exc:
        _cleanup_download_artifacts(output_dir, job_id)
        raise RuntimeError(_format_youtube_download_error(exc)) from exc

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
        _cleanup_download_artifacts(output_dir, job_id)
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
