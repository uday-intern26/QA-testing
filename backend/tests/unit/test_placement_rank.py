from app.services.test_runner import TestRunner


def _frame(number: int, distance: float | None, *, detected: bool = True, quality: float = 1.0) -> dict:
    return {
        "frame_number": number,
        "side": "left",
        "timestamp_ms": number * 400,
        "earlobe_detected": detected,
        "earring_detected": detected,
        "normalized_distance": distance,
        "earring_confidence": 0.9,
        "earlobe_confidence": 0.9,
        "frame_quality_score": quality,
    }


def test_closer_tracing_point_outranks_a_sharper_distant_frame():
    frames = [
        _frame(1, 0.25, quality=1.0),
        _frame(2, 0.02, quality=0.1),
        _frame(3, None, detected=False, quality=1.0),
    ]
    order = TestRunner._rank_placement_frames(frames, top_n=5)
    assert order[0] == 2
    assert order[-1] == 3
    best = next(frame for frame in frames if frame["frame_number"] == 2)
    assert best["best_match"] is True
    assert best["top_match"] is True
    assert best["tracing_points_valid"] is True
    assert best["placement_rank"] == 1
    missed = next(frame for frame in frames if frame["frame_number"] == 3)
    assert missed["tracing_points_valid"] is False
    assert missed["matching_score"] == 0.0
