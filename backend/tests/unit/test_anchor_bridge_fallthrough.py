"""Empty QA bridges must not block the scene-probe fallback."""

from app.adapters.earring_anchor_adapter import state_has_attachment
from app.cv.landmark_validation import (
    ATTACHMENT_ANCHOR_MISSING,
    EARRING_MODEL_NOT_LOADED,
    reason_for_missing_anchor,
)
from app.services.test_runner import TestRunner, anchor_diagnostics
from app.cv.types import EarringAnchor, PlacementMeasurement


def test_empty_bridge_is_not_a_usable_attachment():
    assert state_has_attachment(None) is False
    assert state_has_attachment({}) is False
    assert state_has_attachment({"loading": False, "qa_status": "ready"}) is False
    assert state_has_attachment({"left": {"visible": False}}) is False
    assert state_has_attachment({"left": {"x": 0.3, "y": 0.5, "visible": True}}) is True
    assert state_has_attachment({"jewelry": {"left": {"x": 0.2, "y": 0.4, "visible": True}}}) is True


def test_anchor_diagnostics_names_missing_stage():
    diagnostics = anchor_diagnostics({"qa_status": "ready", "anchor_source": "unavailable"})
    assert diagnostics["anchor_stage"] == "NO_ANCHOR_IN_DEBUG_STATE"
    assert reason_for_missing_anchor(diagnostics) == ATTACHMENT_ANCHOR_MISSING


def test_scene_diagnostics_are_surfaced():
    diagnostics = anchor_diagnostics(
        {
            "anchor_source": "unavailable",
            "anchor_stage": "EARRING_MODEL_NOT_LOADED",
            "scene_diagnostics": {
                "glb_loaded": False,
                "mesh_visible": False,
                "transform_computed": False,
                "camera_found": True,
                "anchor_projected": False,
                "notes": ["no_jewelry_node_matched_keywords"],
            },
        }
    )
    assert diagnostics["glb_loaded"] is False
    assert diagnostics["camera_found"] is True
    assert "no_jewelry_node_matched_keywords" in diagnostics["notes"]
    assert reason_for_missing_anchor(diagnostics) == EARRING_MODEL_NOT_LOADED


def test_missing_jewelry_failure_reason_is_explicit():
    reason = TestRunner._placement_failure_reason(
        PlacementMeasurement(status="FAIL", reason="missing", earlobe_confidence=0.9, earring_confidence=0.0),
        EarringAnchor(side="left", source="missing", visible=False, reason="not published"),
        {"anchor_stage": "NO_ANCHOR_IN_DEBUG_STATE"},
    )
    assert reason == ATTACHMENT_ANCHOR_MISSING
