from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.schemas import ApproveAndDubRequest
from app.services.youtube_service import (
    _cleanup_download_artifacts,
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
