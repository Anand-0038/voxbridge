import pytest

from app.services.media_service import _build_atempo_filter


def _tempo_values(filter_chain: str) -> list[float]:
    return [float(part.split("=", 1)[1]) for part in filter_chain.split(",")]


@pytest.mark.parametrize("ratio", [0.1, 0.25, 0.5, 2.5, 4.0, 8.0])
def test_atempo_chain_keeps_every_factor_in_ffmpeg_range(ratio):
    values = _tempo_values(_build_atempo_filter(ratio))

    assert values
    assert all(0.5 <= value <= 2.0 for value in values)


def test_atempo_chain_slows_four_times_without_invalid_factor():
    assert _tempo_values(_build_atempo_filter(4.0)) == [0.5, 0.5]


def test_atempo_filter_rejects_non_positive_ratio():
    with pytest.raises(ValueError, match="greater than zero"):
        _build_atempo_filter(0)
