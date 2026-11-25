import asyncio

from app.adapters.earring_anchor_adapter import EarringAnchorPageAdapter


class _FakeBrowser:
    def __init__(self, bridge, report):
        self.bridge = bridge
        self.report = report
        self.calls = []

    async def evaluate(self, script, arg=None):
        self.calls.append(arg)
        # First call is the bridge script (no arg); later calls are the scene probe.
        if arg is None:
            return self.bridge
        return self.report


def test_empty_bridge_falls_through_to_scene_probe():
    browser = _FakeBrowser(
        bridge={"loading": False},
        report={
            "renderer_found": True,
            "scene_found": True,
            "camera_found": True,
            "glb_loaded": True,
            "mesh_visible": True,
            "transform_computed": True,
            "anchor_projected": True,
            "notes": [],
            "candidates": [
                {
                    "name": "LeftEarring",
                    "visible": True,
                    "side": "left",
                    "screen": {"x": 0.32, "y": 0.55, "in_front": True},
                    "rotation_deg": 2.0,
                    "scale": 1.0,
                }
            ],
        },
    )
    adapter = EarringAnchorPageAdapter(browser)
    state = asyncio.run(adapter.read_state("earring", ("left", "right")))
    assert state["anchor_source"] == "scene_probe"
    assert state["left"]["x"] == 0.32
    assert state["bridge_present_but_empty"] is True


def test_populated_bridge_skips_scene_probe():
    browser = _FakeBrowser(
        bridge={"left": {"x": 0.3, "y": 0.5, "visible": True, "confidence": 0.97}},
        report={"notes": ["should_not_run"], "candidates": []},
    )
    adapter = EarringAnchorPageAdapter(browser)
    state = asyncio.run(adapter.read_state("earring", ("left", "right")))
    assert state["anchor_source"] == "debug_bridge"
    assert state["left"]["x"] == 0.3
    assert len(browser.calls) == 1
