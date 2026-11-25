from app.adapters.scene_probe import failure_stage, pick_candidate, state_from_report
from app.services.frame_selector import rejection_source
from app.services.test_runner import anchor_diagnostics


def _report(**overrides) -> dict:
    report = {
        "renderer_found": True,
        "scene_found": True,
        "camera_found": True,
        "glb_loaded": True,
        "mesh_visible": True,
        "transform_computed": True,
        "anchor_projected": True,
        "candidates": [],
        "notes": [],
    }
    report.update(overrides)
    return report


def _candidate(name: str, x: float, side=None, visible=True, in_front=True) -> dict:
    return {
        "name": name,
        "visible": visible,
        "side": side,
        "world": {"x": 0.0, "y": 0.0, "z": 0.0},
        "screen": {"x": x, "y": 0.5, "in_front": in_front},
        "scale": 1.0,
        "rotation_deg": 3.0,
    }


def test_failure_stage_names_the_first_incomplete_step():
    assert failure_stage(_report()) == "ANCHOR_AVAILABLE"
    assert failure_stage(_report(scene_found=False)) == "SCENE_NOT_REACHABLE"
    assert failure_stage(_report(glb_loaded=False)) == "EARRING_MODEL_NOT_LOADED"
    assert failure_stage(_report(mesh_visible=False)) == "JEWELRY_MESH_HIDDEN"
    assert failure_stage(_report(transform_computed=False)) == "TRANSFORM_NOT_COMPUTED"
    assert failure_stage(_report(camera_found=False)) == "CAMERA_NOT_FOUND"
    assert failure_stage(_report(anchor_projected=False)) == "ATTACHMENT_ANCHOR_MISSING"


def test_named_candidates_are_matched_to_their_side():
    report = _report(candidates=[_candidate("EarringLeft", 0.33, side="left"), _candidate("EarringRight", 0.66, side="right")])
    assert pick_candidate(report, "left")["name"] == "EarringLeft"
    assert pick_candidate(report, "right")["name"] == "EarringRight"


def test_unnamed_candidates_are_ordered_by_screen_position():
    report = _report(candidates=[_candidate("earring_b", 0.70), _candidate("earring_a", 0.30)])
    assert pick_candidate(report, "left")["name"] == "earring_a"
    assert pick_candidate(report, "right")["name"] == "earring_b"


def test_hidden_or_behind_camera_candidates_are_not_used():
    hidden = _report(candidates=[_candidate("earring", 0.3, side="left", visible=False)])
    assert pick_candidate(hidden, "left") is None
    behind = _report(candidates=[_candidate("earring", 0.3, side="left", in_front=False)])
    assert pick_candidate(behind, "left") is None


def test_state_carries_measured_coordinates_not_a_guess():
    report = _report(candidates=[_candidate("EarringLeft", 0.33, side="left")])
    state = state_from_report(report, "earring", ("left", "right"))
    assert state is not None
    assert state["left"]["x"] == 0.33
    assert state["left"]["source"] == "scene_probe"
    assert state["left"]["confidence"] == 0.99
    assert state["left"]["rotation"] == 3.0
    assert state["left"]["scale"] == 1.0


def test_state_is_none_when_nothing_was_projected():
    assert state_from_report(_report(candidates=[]), "earring", ("left",)) is None


def test_anchor_diagnostics_explains_a_missing_bridge():
    diagnostics = anchor_diagnostics(None)
    assert diagnostics["anchor_source"] == "unavailable"
    assert diagnostics["anchor_stage"] == "NO_DEBUG_STATE"


def test_anchor_diagnostics_flags_a_state_with_no_anchor_block():
    diagnostics = anchor_diagnostics({"qa_status": "ready"})
    assert diagnostics["anchor_stage"] == "NO_ANCHOR_IN_DEBUG_STATE"
    assert diagnostics["anchor_source"] == "unavailable"


def test_anchor_diagnostics_recognises_a_real_bridge_payload():
    diagnostics = anchor_diagnostics({"qa_status": "ready", "left": {"x": 0.3, "y": 0.5, "visible": True}})
    assert diagnostics["anchor_stage"] == "ANCHOR_AVAILABLE"
    assert diagnostics["anchor_source"] == "debug_bridge"


def test_anchor_diagnostics_surfaces_each_scene_stage():
    state = {
        "anchor_source": "unavailable",
        "anchor_stage": "EARRING_MODEL_NOT_LOADED",
        "qa_status": "ready",
        "scene_diagnostics": _report(glb_loaded=False, mesh_visible=False, notes=["no_jewelry_node_matched_keywords"]),
    }
    diagnostics = anchor_diagnostics(state)
    assert diagnostics["anchor_stage"] == "EARRING_MODEL_NOT_LOADED"
    assert diagnostics["glb_loaded"] is False
    assert diagnostics["mesh_visible"] is False
    assert diagnostics["camera_found"] is True
    assert diagnostics["notes"] == ["no_jewelry_node_matched_keywords"]


def test_rejection_reasons_are_attributed_to_their_stage():
    assert rejection_source("near_duplicate") == "duplicate_filter"
    assert rejection_source("not_selected_as_representative") == "candidate_selection"
    assert rejection_source("ear_not_visible") == "body_detection"
    assert rejection_source("jewelry_not_loaded") == "jewelry_detection"
    assert rejection_source("head_pose_unstable") == "frame_quality"
    assert rejection_source("excessive_blur") == "frame_quality"
