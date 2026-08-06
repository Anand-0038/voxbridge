import asyncio
from types import SimpleNamespace

from app.services import transcription_service


def test_gemini_upload_runs_through_asyncio_to_thread(monkeypatch, tmp_path):
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"fixture audio")
    uploaded_file = object()
    upload_calls = []
    to_thread_calls = []

    def upload_file(path):
        upload_calls.append(path)
        return uploaded_file

    class FakeModel:
        async def generate_content_async(self, payload):
            assert payload[1] is uploaded_file
            return SimpleNamespace(
                text='[{"text":"Hello","start_time":0,"end_time":1,"confidence":1}]'
            )

    async def fake_to_thread(func, *args, **kwargs):
        to_thread_calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr(transcription_service.GenAIClient, "get_key_count", lambda: 1)
    monkeypatch.setattr(
        transcription_service.GenAIClient, "get_model", lambda _: FakeModel()
    )
    monkeypatch.setattr(transcription_service.genai, "upload_file", upload_file)
    monkeypatch.setattr(transcription_service.asyncio, "to_thread", fake_to_thread)

    segments = asyncio.run(transcription_service.transcribe_audio(str(audio_path)))

    assert len(segments) == 1
    assert upload_calls == [str(audio_path)]
    assert to_thread_calls == [upload_file]
