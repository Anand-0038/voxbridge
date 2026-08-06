import pytest

from app.utils.helpers import (
    decode_json_object,
    get_relative_path,
    validate_segment_timings,
)


def test_get_relative_path_keeps_persisted_paths_portable():
    assert (
        get_relative_path("storage/uploads/example.mp4")
        == "storage/uploads/example.mp4"
    )


def test_get_relative_path_rejects_paths_outside_backend():
    with pytest.raises(ValueError, match="inside the backend directory"):
        get_relative_path("/tmp/voxbridge-outside.mp4")


def test_decode_json_object_accepts_asyncpg_string_or_mapping():
    assert decode_json_object('{"pipeline_step":"complete"}') == {
        "pipeline_step": "complete"
    }
    assert decode_json_object({"pipeline_step": "complete"}) == {
        "pipeline_step": "complete"
    }


def test_decode_json_object_rejects_non_object_json():
    with pytest.raises(TypeError, match="JSON object"):
        decode_json_object("[]")


def test_validate_segment_timings_rejects_overlaps_and_reports_gaps():
    result = validate_segment_timings(
        [
            {"start_time": 0.0, "end_time": 2.0},
            {"start_time": 1.8, "end_time": 3.0},
            {"start_time": 4.0, "end_time": 5.0},
        ],
        max_gap=0.5,
    )

    assert result["valid"] is False
    assert any("overlaps" in error for error in result["errors"])
    assert any("large gap" in warning for warning in result["warnings"])
