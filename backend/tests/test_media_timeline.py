import asyncio
import subprocess

from app.services.media_service import get_audio_duration, place_audio_on_timeline


def test_single_segment_timeline_matches_total_duration(tmp_path):
    source = tmp_path / "source.wav"
    output = tmp_path / "timeline.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(source),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    asyncio.run(
        place_audio_on_timeline(
            segments=[
                {
                    "audio_path": str(source),
                    "start_time": 2.0,
                    "end_time": 3.0,
                }
            ],
            total_duration=5.0,
            output_path=str(output),
            temp_dir=str(tmp_path),
        )
    )

    duration = asyncio.run(get_audio_duration(str(output)))
    assert abs(duration - 5.0) < 0.05


def test_multi_segment_timeline_matches_total_duration(tmp_path):
    source = tmp_path / "source.wav"
    output = tmp_path / "timeline.wav"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(source),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    asyncio.run(
        place_audio_on_timeline(
            segments=[
                {"audio_path": str(source), "start_time": 0.0, "end_time": 1.0},
                {"audio_path": str(source), "start_time": 2.0, "end_time": 3.0},
            ],
            total_duration=5.0,
            output_path=str(output),
            temp_dir=str(tmp_path),
        )
    )

    duration = asyncio.run(get_audio_duration(str(output)))
    assert abs(duration - 5.0) < 0.05
