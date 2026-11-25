from app.services.frame_review import apply_frame_review


def test_near_pass_does_not_rewrite_fail_status():
    frames = [
        {"frame_number": 12, "status": "FAIL", "normalized_distance": 0.14},
        {"frame_number": 31, "status": "PASS", "normalized_distance": 0.04},
        {"frame_number": 18, "status": "WARNING", "normalized_distance": 0.09},
        {"frame_number": 4, "status": "FAIL", "normalized_distance": None},
    ]
    closest = apply_frame_review(frames, 0.08, 0.15)
    by_number = {frame["frame_number"]: frame for frame in frames}
    assert by_number[31]["review_label"] == "PASS"
    assert by_number[31]["status"] == "PASS"
    assert by_number[18]["review_label"] == "NEAR_PASS"
    assert by_number[18]["status"] == "WARNING"
    assert by_number[12]["status"] == "FAIL"
    assert by_number[4]["review_label"] == "FAIL"
    assert [frame["frame_number"] for frame in closest] == [31, 18, 12]
    assert closest[2]["review_label"] == "NEAR_PASS"
    assert closest[2]["status"] == "FAIL"
