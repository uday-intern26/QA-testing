"""Rank measured frames by how close they are to the existing pass threshold.

The placement status is left unchanged. A near-pass label never becomes PASS.
"""

from __future__ import annotations


def apply_frame_review(
    frames: list[dict],
    pass_threshold: float,
    fail_threshold: float,
    *,
    limit: int = 10,
) -> list[dict]:
    threshold = float(pass_threshold)
    fail_band = float(fail_threshold)
    for frame in frames:
        distance = frame.get("normalized_distance")
        status = str(frame.get("status") or "FAIL")
        gap = float(distance) - threshold if isinstance(distance, (int, float)) else None
        if status == "PASS":
            label = "PASS"
        elif gap is not None and (status == "WARNING" or gap <= max(0.0, fail_band - threshold)):
            label = "NEAR_PASS"
        else:
            label = "FAIL"
        frame["placement_gap"] = None if gap is None else round(gap, 4)
        frame["pass_threshold"] = threshold
        frame["fail_threshold"] = fail_band
        frame["review_label"] = label

    measured = [frame for frame in frames if frame.get("placement_gap") is not None]
    measured.sort(key=lambda frame: (frame["placement_gap"], frame.get("frame_number") or 0))
    closest = measured[: max(1, limit)] if measured else []
    for frame in closest:
        if frame.get("status") != "PASS":
            frame["review_label"] = "NEAR_PASS"
    return closest
