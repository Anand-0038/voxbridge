from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.schemas import ApproveAndDubRequest
from app.services.youtube_service import (
    _build_ytdlp_options,
    _cleanup_download_artifacts,
    _format_youtube_download_error,
    _parse_browser_cookie_spec,
    normalize_youtube_url,
)


def test_youtube_url_validation_accepts_single_video_urls():
    assert normalize_youtube_url("https://youtu.be/abc123") == "https://youtu.be/abc123"
    assert (
        normalize_youtube_url("https://www.youtube.com/watch?v=abc123&list=demo")
        == "https://www.youtube.com/watch?v=abc123&list=demo"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=abc123",
        "https://example.com/watch?v=abc123",
        "https://www.youtube.com/playlist?list=abc123",
        "https://www.youtube.com/shorts/",
    ],
)
def test_youtube_url_validation_rejects_unsafe_or_non_video_urls(url):
    with pytest.raises(ValueError):
        normalize_youtube_url(url)


@pytest.mark.parametrize("consent", [None, "true", 1])
def test_consent_requires_a_real_boolean(consent):
    with pytest.raises(ValidationError):
        ApproveAndDubRequest(
            job_id="local-job",
            target_language="es",
            consent_confirmed=consent,
        )


def test_youtube_cleanup_is_scoped_to_one_job(tmp_path: Path):
    (tmp_path / "local-job.mp4.part").write_bytes(b"partial")
    (tmp_path / "local-job.mp4").write_bytes(b"video")
    (tmp_path / "other-job.mp4.part").write_bytes(b"keep")

    _cleanup_download_artifacts(str(tmp_path), "local-job")

    assert not (tmp_path / "local-job.mp4.part").exists()
    assert not (tmp_path / "local-job.mp4").exists()
    assert (tmp_path / "other-job.mp4.part").exists()


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("chrome", ("chrome",)),
        ("chrome:Default", ("chrome", "Default")),
        ("chrome+gnomekeyring:Default::none", ("chrome", "Default", "gnomekeyring", "none")),
    ],
)
def test_browser_cookie_spec_matches_ytdlp_tuple_format(spec, expected):
    assert _parse_browser_cookie_spec(spec) == expected


def test_ytdlp_options_use_browser_cookies_without_copying_them(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("YOUTUBE_COOKIES_FROM_BROWSER", "chrome")
    monkeypatch.delenv("YOUTUBE_COOKIES_FILE", raising=False)

    options = _build_ytdlp_options(str(tmp_path), "local-job")

    assert options["cookiesfrombrowser"] == ("chrome",)
    assert "cookiefile" not in options


def test_ytdlp_options_reject_two_cookie_sources(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("YOUTUBE_COOKIES_FROM_BROWSER", "chrome")
    monkeypatch.setenv("YOUTUBE_COOKIES_FILE", str(tmp_path / "cookies.txt"))

    with pytest.raises(RuntimeError, match="only one"):
        _build_ytdlp_options(str(tmp_path), "local-job")


def test_youtube_auth_error_explains_local_cookie_configuration(monkeypatch):
    monkeypatch.delenv("YOUTUBE_COOKIES_FROM_BROWSER", raising=False)
    monkeypatch.delenv("YOUTUBE_COOKIES_FILE", raising=False)

    message = _format_youtube_download_error(
        RuntimeError("Sign in to confirm you’re not a bot. Use --cookies-from-browser")
    )

    assert "YOUTUBE_COOKIES_FROM_BROWSER=chrome" in message
