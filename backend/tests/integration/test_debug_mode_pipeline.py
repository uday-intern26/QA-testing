"""Debug Mode runs end-to-end alongside the existing pipeline."""

import json
import shutil
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.db.database import session_scope
from app.db.repositories import runs as run_repo
from app.models.application import Application
from app.models.test import TestDefinition
from app.services.test_runner import TestRunner, initial_steps
from app.utils.files import write_json

from tests.integration.test_pipeline import FIXTURES, FixedLandmarks, _write_video


def _seed(video: Path, anchors: Path, *, debug_mode: bool, suffix: str) -> str:
    with session_scope() as session:
        application = Application(
            id=f"APP-DBG-{suffix}",
            name="Local video",
            type="video",
            video_path=str(video),
            anchor_file=str(anchors),
        )
        test = TestDefinition(
            id=f"TEST-DBG-{suffix}",
            name="Debug mode earring test",
            application_id=application.id,
            jewelry_id="E123",
            jewelry_type="earring",
            ear_side="left",
            capture_fps=5,
            minimum_confidence=0.8,
            pass_threshold=0.10,
            fail_threshold=0.15,
            minimum_pass_rate=0.95,
            maximum_consecutive_failures=2,
            min_selected_frames=3,
            max_selected_frames=30,
            debug_mode=debug_mode,
            debug_options_json=json.dumps({"position_tolerance_px": 9.0}) if debug_mode else None,
        )
        session.add(application)
        session.add(test)
        session.commit()
        return run_repo.create_run(session, test.id, initial_steps()).id


def _anchors(path: Path) -> Path:
    write_json(
        path,
        {
            "frames": [
                {
                    "frame_index": index,
                    "jewelry_id": "E123",
                    "jewelry_type": "earring",
                    "left": {"x": 0.338, "y": 0.604, "visible": True},
                }
                for index in range(8)
            ]
        },
    )
    return path


async def _run(tmp_path: Path, *, debug_mode: bool, suffix: str) -> dict:
    video = _write_video(FIXTURES / "sample_tryon.mp4")
    anchors = _anchors(tmp_path / f"anchors-{suffix}.json")
    run_id = _seed(video, anchors, debug_mode=debug_mode, suffix=suffix)
    # Run ids restart with the database, so clear any artefacts from a previous test.
    shutil.rmtree(get_settings().data_dir / "results" / run_id, ignore_errors=True)
    await TestRunner(get_settings(), landmark_provider=FixedLandmarks()).execute(run_id, None, "pw")
    with session_scope() as session:
        run = run_repo.get_run(session, run_id)
        assert run is not None and run.status == "completed"
        return json.loads(run.report_json or "{}")


@pytest.mark.asyncio
async def test_debug_mode_on_renders_frames_and_reports_measurements(tmp_path: Path):
    report = await _run(tmp_path, debug_mode=True, suffix="on")
    validation = report["landmark_validation"]

    assert validation["debug_mode"] is True
    assert validation["enforced"] is True
    assert validation["profile"]["jewelry_type"] == "earring"
    # Per-test override reached the engine.
    assert validation["profile"]["tolerances"]["position_tolerance_px"] == 9.0

    left = validation["sides"]["left"]
    assert set(left["checks"]) == {
        "landmark_detection",
        "visibility",
        "position",
        "rotation",
        "scale",
        "temporal_stability",
    }
    assert left["metrics"]["total_frames"] > 1
    assert left["frames"][0]["landmark_index"] == 132
    assert left["frames"][0]["expected_px"] is not None
    assert left["frames"][0]["position_error_px"] is not None

    assert validation["debug_frames"], "Debug Mode should write debug overlay frames"
    for entry in validation["debug_frames"]:
        assert Path(entry["path"]).is_file()


@pytest.mark.asyncio
async def test_debug_mode_off_writes_no_frames_and_does_not_change_the_verdict(tmp_path: Path):
    report = await _run(tmp_path, debug_mode=False, suffix="off")
    validation = report["landmark_validation"]

    assert validation["debug_mode"] is False
    assert validation["enforced"] is False
    assert validation["debug_frames"] == []
    # Measurements are still reported, they just do not drive the verdict.
    assert validation["sides"]["left"]["metrics"]["total_frames"] > 1

    output_dir = get_settings().data_dir / "results" / report["test_run_id"] / "debug_frames"
    assert not output_dir.exists()
