import asyncio

from app.api import routes


def test_processing_timeout_removes_uploaded_video(monkeypatch):
    removed_paths = []

    async def timeout_internal(*_args, **_kwargs):
        raise TimeoutError

    async def no_op(*_args, **_kwargs):
        return None

    monkeypatch.setattr(routes, "_process_uploaded_video_internal", timeout_internal)
    monkeypatch.setattr(routes, "_remove_file_if_exists", removed_paths.append)
    monkeypatch.setattr(routes, "save_job_state", no_op)
    monkeypatch.setattr(routes, "log_step", no_op)
    monkeypatch.setattr(routes, "update_job_status", no_op)

    asyncio.run(routes.process_uploaded_video("local-job", "/tmp/local-job-video.mp4"))

    assert removed_paths == ["/tmp/local-job-video.mp4"]
