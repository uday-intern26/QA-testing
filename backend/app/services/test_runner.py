"""Executes the three-layer earring placement pipeline as separate stages."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session

from app.adapters.tryon_application import TryOnError, build_tryon_adapter
from app.core.config import Settings
from app.core.logging import log_event
from app.core.security import secret_registry
from app.cv.anchor_geometry import reference_vector_from_points
from app.cv.face_landmarks import FaceLandmarkError, MediaPipeFaceLandmarker
from app.cv.image_processing import bgr_to_rgb
from app.cv.types import FaceLandmarkResult, PlacementMeasurement, ReferenceVector
from app.cv.visualization import OverlayPalette, annotate_frame, save_image
from app.db.database import session_scope
from app.db.repositories import runs as run_repo
from app.models.frame import FrameRecord, FrameResult
from app.models.reference import ReferenceImage
from app.models.result import PlacementResultRow, ReportRow, TestRun
from app.models.test import TestDefinition
from app.services.capture_service import CaptureService
from app.services.comparison_service import ComparisonService
from app.services.earlobe_detector import EarlobeDetector
from app.services.earring_detector import DebugStateEarringDetector, FallbackEarringAnchorDetector
from app.services.frame_selector import FrameSelector, RawFrame, SelectedFrame
from app.cv.earring_lay import aggregate_earring_lay, evaluate_earring_lay, measurement_from_earring_lay
from app.cv.necklace_lay import aggregate_necklace_lay, evaluate_necklace_lay, measurement_from_necklace_lay
from app.cv.bangle_lay import aggregate_bangle_lay, evaluate_bangle_lay, measurement_from_bangle_lay
from app.cv.bracelet_lay import aggregate_bracelet_lay, evaluate_bracelet_lay, measurement_from_bracelet_lay
from app.cv.ring_lay import aggregate_ring_lay, evaluate_ring_lay, measurement_from_ring_lay
from app.services.placement_validator import validator_for
from app.services.report_service import ReportService
from app.services.temporal_validator import combine_statuses, summarize_temporal

WAITING_STEPS = [
    "application",
    "authentication",
    "capture",
    "frame_selection",
    "earlobe_detection",
    "earring_detection",
    "placement_validation",
    "report",
]


class TestRunner:
    __test__ = False

    def __init__(self, settings: Settings, landmark_provider=None) -> None:
        self.settings = settings
        self.landmark_provider = landmark_provider
        self.capture_service = CaptureService()
        self.reports = ReportService()
        self.comparison = ComparisonService(settings)
        self.debug_detector = DebugStateEarringDetector()
        self.fallback_detector = FallbackEarringAnchorDetector()

    async def execute(self, run_id: str, username: str | None, password: str | None) -> None:
        if password:
            secret_registry.add(password)
        try:
            log_event("TEST_START", test_run_id=run_id)
            raw_frames = await self.prepare_and_capture(run_id, username or "", password or "")
            await asyncio.to_thread(self.analyze, run_id, raw_frames)
            log_event("TEST_COMPLETED", test_run_id=run_id)
        except Exception as exc:
            self._fail(run_id, exc)
            log_event("TEST_COMPLETED", test_run_id=run_id, status="failed")
        finally:
            self._save_tested_application(run_id)
            if password:
                secret_registry.discard(password)

    async def prepare_and_capture(self, run_id: str, username: str, password: str) -> list[RawFrame]:
        from app.models.application import Application

        with session_scope() as session:
            run = self._require_run(session, run_id)
            test = self._require_test(session, run.test_id)
            stored = session.get(Application, test.application_id)
            if stored is None:
                raise TryOnError("The configured application no longer exists.", "APPLICATION_MISSING")
            application = Application.model_validate(stored.model_dump())
            from app.services.application_service import ApplicationService

            remembered = ApplicationService.validated_urls.get(application.id)
            if remembered:
                application.url = remembered
            output_dir = self.settings.data_dir / "results" / run.id
            output_dir.mkdir(parents=True, exist_ok=True)
            self._set_step(session, run, "application", "RUNNING", "Preparing application...", 5, status="running")
            app_type = application.type
            app_url = application.url
            duration = test.capture_duration_seconds
            fps = test.capture_fps
            jewelry_id = test.jewelry_id
            jewelry_type = test.jewelry_type or "earring"

        adapter = build_tryon_adapter(
            application,
            username=username,
            password=password,
            output_dir=output_dir,
            fps=fps,
            duration_seconds=duration,
            headless=self.settings.playwright_headless,
            viewport_width=self.settings.viewport_width,
            viewport_height=self.settings.viewport_height,
            timeout_ms=self.settings.navigation_timeout_ms,
        )
        if getattr(adapter, "live_overlay", None) is not None:
            adapter.live_overlay.jewelry_type = jewelry_type
        if hasattr(adapter, "jewelry_type"):
            adapter.jewelry_type = jewelry_type
        try:
            await adapter.connect()
            with session_scope() as session:
                run = self._require_run(session, run_id)
                detail = "Connected." if app_type == "web" else "Video/file source is available."
                self._set_step(session, run, "application", "PASS", detail, 12)
                self._set_step(session, run, "authentication", "RUNNING", "Authenticating...", 18)
            await adapter.authenticate()
            with session_scope() as session:
                run = self._require_run(session, run_id)
                auth_detail = "Authentication successful." if app_type == "web" else "Video/file source does not require login."
                self._set_step(session, run, "authentication", "PASS", auth_detail, 28)
            await adapter.launch()
            note = await adapter.select_jewelry(jewelry_id, jewelry_type=jewelry_type)
            with session_scope() as session:
                run = self._require_run(session, run_id)
                self._set_step(
                    session,
                    run,
                    "capture",
                    "RUNNING",
                    "Showing the selected jewelry on the live video. Pass or fail is decided after this.",
                    40,
                )
            frames, capture_note = await self.capture_service.capture(
                adapter, jewelry_id, jewelry_type=jewelry_type
            )
            del note
            video_path = getattr(adapter, "video_file", None)
            if video_path:
                destination = output_dir / "original_capture.mp4"
                if not self.capture_service.remux_to_mp4(Path(video_path), destination):
                    shutil.copy(video_path, output_dir / Path(video_path).name)
                    destination = output_dir / Path(video_path).name
                with session_scope() as session:
                    run = self._require_run(session, run_id)
                    run.capture_path = str(destination)
                    session.add(run)
                    session.commit()
            with session_scope() as session:
                run = self._require_run(session, run_id)
                overlay_note = (
                    "Selected jewelry was shown on the live video. "
                    if getattr(adapter, "live_overlay", None) and adapter.live_overlay.shown
                    else ""
                )
                self._set_step(
                    session,
                    run,
                    "capture",
                    "PASS",
                    f"{overlay_note}{capture_note} Captured {len(frames)} frames.",
                    55,
                )
            log_event("CAPTURE_COMPLETED", test_run_id=run_id, frames=len(frames), url=app_url)
            return frames
        finally:
            await adapter.close()

    def analyze(self, run_id: str, raw_frames: list[RawFrame]) -> dict:
        with session_scope() as session:
            run = self._require_run(session, run_id)
            test = self._require_test(session, run.test_id)
            reference = session.get(ReferenceImage, test.reference_id) if test.reference_id else None
            reference_path = Path(reference.path) if reference else None
            reference_filename = reference.filename if reference else None
            reference_vector = self._vector_from_reference(reference)
            config = self._config(test)
            jewelry_type = test.jewelry_type or "earring"
            selected_finger = getattr(test, "selected_finger", None) or "ring"
            config["selected_finger"] = selected_finger
            if jewelry_type == "earring":
                sides = ["left", "right"] if test.ear_side == "both" else [test.ear_side]
            elif jewelry_type in {"bracelet", "bangle", "ring"} and test.ear_side in {"left", "right"}:
                sides = [test.ear_side]
            else:
                sides = ["center"]
            test_id = test.id
            test_name = test.name
            jewelry_id = test.jewelry_id
            ear_side = test.ear_side
            output_dir = self.settings.data_dir / "results" / run.id
            output_dir.mkdir(parents=True, exist_ok=True)

        if not raw_frames:
            raise TryOnError(
                "No frames were captured.",
                "INSUFFICIENT_FRAMES",
                "Increase the capture duration or confirm the try-on view is visible.",
            )

        selector = FrameSelector(
            min_blur_variance=self.settings.min_blur_variance,
            blur_norm_variance=self.settings.blur_norm_variance,
            duplicate_hash_distance=self.settings.duplicate_hash_distance,
            head_pose_max_delta_deg=self.settings.head_pose_max_delta_deg,
            head_pose_max_yaw_deg=self.settings.head_pose_max_yaw_deg,
            min_ear_width=self.settings.min_ear_width,
            minimum_confidence=config["minimum_confidence"],
            ear_side=ear_side if jewelry_type == "earring" else "left",
            require_ear_visibility=jewelry_type == "earring",
        )
        faces = self._detect_faces(raw_frames)
        evaluated = selector.evaluate(raw_frames, faces)
        selected = selector.select(evaluated, config["max_selected_frames"])
        selected_ids = {frame.raw.index for frame in selected}
        layer1 = "PASS" if len(selected) >= config["min_selected_frames"] else "FAIL"
        layer1_detail = (
            f"{len(selected)} representative frames selected from {len(raw_frames)} captured."
            if layer1 == "PASS"
            else (
                f"Only {len(selected)} frames passed quality checks; "
                f"{config['min_selected_frames']} are required."
            )
        )
        log_event("FRAME_SELECTION_COMPLETED", test_run_id=run_id, selected=len(selected), captured=len(raw_frames))
        with session_scope() as session:
            run = self._require_run(session, run_id)
            self._set_step(session, run, "frame_selection", layer1, layer1_detail, 68)

        earlobe_detector = EarlobeDetector(self.settings.min_ear_width)
        validator = validator_for(jewelry_type)
        palette = OverlayPalette(
            self.settings.overlay_earlobe_color,
            self.settings.overlay_earring_color,
            self.settings.overlay_zone_color,
            self.settings.overlay_pass_zone_color,
            self.settings.overlay_vector_color,
        )
        reference_bgr = None
        if reference_path and reference_path.is_file():
            from app.cv.image_processing import read_bgr

            reference_bgr = read_bgr(reference_path)

        per_side_statuses: dict[str, list[str]] = {side: [] for side in sides}
        per_side_measurements: dict[str, list[PlacementMeasurement]] = {side: [] for side in sides}
        missing_earlobe = {side: 0 for side in sides}
        missing_earring = {side: 0 for side in sides}
        frame_payloads: list[dict] = []
        necklace_frame_lays: list[dict] = []
        earring_frame_lays: list[dict] = []
        ring_frame_lays: list[dict] = []
        bracelet_frame_lays: list[dict] = []
        bangle_frame_lays: list[dict] = []

        with session_scope() as session:
            run = self._require_run(session, run_id)
            body_label = "earlobe" if jewelry_type == "earring" else f"{jewelry_type} body"
            jewel_label = "earring" if jewelry_type == "earring" else jewelry_type
            self._set_step(session, run, "earlobe_detection", "RUNNING", f"Detecting {body_label} anchors...", 74)
            self._set_step(session, run, "earring_detection", "RUNNING", f"Detecting {jewel_label} attachment anchors...", 80)

        from app.cv.body_geometry import body_anchor_for

        for item in evaluated:
            self._persist_frame_row(run_id, item, selected_ids)
            if item.raw.index not in selected_ids:
                continue
            image = item.image_bgr
            if image is None:
                from app.cv.image_processing import read_bgr

                image = read_bgr(item.raw.path)
            annotated = image
            side_results = []
            for side in sides:
                if jewelry_type == "earring":
                    body, body_error = earlobe_detector.detect(item.face, side)
                else:
                    body, body_error = body_anchor_for(jewelry_type, item.face, side)
                if body is None:
                    missing_earlobe[side] += 1
                detect_side = side if jewelry_type != "necklace" else "center"
                jewelry = self.debug_detector.detect_from_state(item.raw.debug_state, detect_side)
                if jewelry is None or not jewelry.visible or jewelry.x is None:
                    jewelry = self.fallback_detector.detect(
                        image,
                        body,
                        side=detect_side,
                        reference=reference_vector if jewelry_type == "earring" else None,
                        reference_bgr=reference_bgr if jewelry_type == "earring" else None,
                    )
                    if jewelry.x is None:
                        missing_earring[side] += 1
                measurement = validator.validate(body, jewelry, config=config)
                necklace_lay = None
                ring_lay = None
                bracelet_lay = None
                bangle_lay = None
                if jewelry_type == "necklace":
                    left_jewel = self.debug_detector.detect_from_state(item.raw.debug_state, "left")
                    right_jewel = self.debug_detector.detect_from_state(item.raw.debug_state, "right")
                    necklace_lay = evaluate_necklace_lay(
                        item.face,
                        body,
                        jewelry,
                        config=config,
                        left_jewelry=left_jewel,
                        right_jewelry=right_jewel,
                    )
                    measurement = measurement_from_necklace_lay(necklace_lay, measurement)
                    necklace_frame_lays.append(necklace_lay)
                elif jewelry_type == "ring":
                    ring_lay = evaluate_ring_lay(
                        item.face,
                        body,
                        jewelry,
                        config=config,
                        selected_finger=selected_finger,
                        side=side if side in {"left", "right"} else "left",
                        debug_state=item.raw.debug_state if isinstance(item.raw.debug_state, dict) else None,
                    )
                    measurement = measurement_from_ring_lay(ring_lay, measurement)
                    ring_frame_lays.append(ring_lay)
                elif jewelry_type == "bracelet":
                    bracelet_lay = evaluate_bracelet_lay(
                        item.face,
                        body,
                        jewelry,
                        config=config,
                        side=side if side in {"left", "right"} else "left",
                        jewelry_id=jewelry_id,
                        debug_state=item.raw.debug_state if isinstance(item.raw.debug_state, dict) else None,
                    )
                    measurement = measurement_from_bracelet_lay(bracelet_lay, measurement)
                    bracelet_frame_lays.append(bracelet_lay)
                elif jewelry_type == "bangle":
                    bangle_lay = evaluate_bangle_lay(
                        item.face,
                        body,
                        jewelry,
                        config=config,
                        side=side if side in {"left", "right"} else "left",
                        jewelry_id=jewelry_id,
                        debug_state=item.raw.debug_state if isinstance(item.raw.debug_state, dict) else None,
                    )
                    measurement = measurement_from_bangle_lay(bangle_lay, measurement)
                    bangle_frame_lays.append(bangle_lay)
                per_side_statuses[side].append(measurement.status)
                per_side_measurements[side].append(measurement)
                annotated = annotate_frame(
                    annotated,
                    body,
                    jewelry,
                    palette=palette,
                    pass_threshold=config["pass_threshold"],
                    fail_threshold=config["fail_threshold"],
                    zone_y_scale=config["zone_y_scale"],
                    normalized_distance=measurement.normalized_distance,
                )
                side_results.append(
                    (side, body, jewelry, measurement, body_error, necklace_lay, ring_lay, bracelet_lay, bangle_lay)
                )

            earring_lay = None
            if jewelry_type == "earring":
                earring_lay = evaluate_earring_lay(
                    item.face,
                    [
                        (side, body, jewelry)
                        for side, body, jewelry, _m, _e, _n, _r, _br, _bg in side_results
                    ],
                    config=config,
                    required_sides=list(sides),
                )
                earring_frame_lays.append(earring_lay)
                updated_side_results = []
                for side, body, jewelry, measurement, body_error, necklace_lay, ring_lay, bracelet_lay, bangle_lay in side_results:
                    side_meas = measurement_from_earring_lay(earring_lay, side, measurement)
                    per_side_statuses[side][-1] = side_meas.status
                    per_side_measurements[side][-1] = side_meas
                    updated_side_results.append(
                        (side, body, jewelry, side_meas, body_error, necklace_lay, ring_lay, bracelet_lay, bangle_lay)
                    )
                side_results = updated_side_results

            annotated_path = output_dir / "annotated_frames" / f"frame_{item.raw.index:04d}.png"
            save_image(annotated_path, annotated)
            selected_copy = output_dir / "selected_frames" / item.raw.path.name
            selected_copy.parent.mkdir(parents=True, exist_ok=True)
            if not selected_copy.exists():
                shutil.copy(item.raw.path, selected_copy)
            self._update_annotated_path(run_id, item, annotated_path)
            for side, body, jewelry, measurement, body_error, necklace_lay, ring_lay, bracelet_lay, bangle_lay in side_results:
                payload = self._frame_payload(
                    item,
                    side,
                    body,
                    jewelry,
                    measurement,
                    body_error,
                    necklace_lay=necklace_lay,
                    earring_lay=earring_lay,
                    ring_lay=ring_lay,
                    bracelet_lay=bracelet_lay,
                    bangle_lay=bangle_lay,
                )
                frame_payloads.append(payload)
                self._persist_frame_result(run_id, item, payload)

        log_event("EARLOBE_DETECTION_COMPLETED", test_run_id=run_id)
        log_event("EARRING_DETECTION_COMPLETED", test_run_id=run_id)
        log_event("PLACEMENT_VALIDATION_COMPLETED", test_run_id=run_id)

        temporal = {
            side: summarize_temporal(
                per_side_statuses[side],
                minimum_pass_rate=config["minimum_pass_rate"],
                maximum_consecutive_failures=config["maximum_consecutive_failures"],
                detection_failures=0,
            )
            for side in sides
        }
        critical = 0
        for side in sides:
            if not per_side_statuses[side] or missing_earlobe[side] == len(per_side_statuses[side]):
                critical += 1
            elif missing_earring[side] == len(per_side_statuses[side]):
                critical += 1
        for summary in temporal.values():
            summary.critical_detection_failures = critical

        layer2 = self._layer2_status(sides, missing_earlobe, missing_earring, len(selected))
        layer3_status = combine_statuses([temporal[side].status for side in sides]) if selected else "NOT_RUN"
        if layer1 == "FAIL":
            layer2 = "NOT_RUN"
            layer3_status = "NOT_RUN"

        reference_report = self._reference_report(sides, per_side_measurements, reference_vector, validator, config)
        if layer1 == "FAIL":
            reference_report["status"] = "NOT_RUN"

        visual = self.comparison.compare_local(
            reference_path,
            selected[0].raw.path if selected else None,
        )
        visual["applitools"] = self.comparison.compare_applitools(
            selected[0].raw.path if selected else None,
            test_name,
        )

        overall, reason, action = self._decide(
            layer1=layer1,
            layer2=layer2,
            layer3=layer3_status,
            reference_status=reference_report.get("status", "NOT_RUN"),
            temporal=temporal,
            critical=critical,
            sides=sides,
            missing_earlobe=missing_earlobe,
            missing_earring=missing_earring,
            selected_count=len(selected),
            config=config,
            jewelry_type=jewelry_type,
        )
        necklace_lay_summary = None
        if jewelry_type == "necklace":
            necklace_lay_summary = aggregate_necklace_lay(necklace_frame_lays)
            if necklace_lay_summary.get("final_result") == "FAIL":
                overall = "FAIL"
                reason = necklace_lay_summary.get("reason") or reason
                action = (
                    "Reposition the necklace around the neck so the chain follows the neckline "
                    "and the pendant hangs toward the upper chest."
                )
            elif necklace_lay_summary.get("final_result") == "WARNING" and overall == "PASS":
                overall = "WARNING"
                reason = necklace_lay_summary.get("reason") or reason
                action = "Review necklace frames for uneven sides or a slightly misaligned pendant."
            elif necklace_lay_summary.get("final_result") == "PASS" and overall in {"PASS", "WARNING"}:
                reason = necklace_lay_summary.get("reason") or reason
        earring_lay_summary = None
        if jewelry_type == "earring":
            earring_lay_summary = aggregate_earring_lay(earring_frame_lays)
            if earring_lay_summary.get("final_result") == "FAIL":
                overall = "FAIL"
                reason = earring_lay_summary.get("reason") or reason
                action = (
                    "Reposition the earrings so each attachment sits on the intended earlobe "
                    "or piercing point, not floating on the cheek, neck, or face."
                )
            elif earring_lay_summary.get("final_result") == "WARNING" and overall == "PASS":
                overall = "WARNING"
                reason = earring_lay_summary.get("reason") or reason
                action = "Review earring frames for partial occlusion, slight misalignment, or uneven sides."
            elif earring_lay_summary.get("final_result") == "PASS" and overall in {"PASS", "WARNING"}:
                reason = earring_lay_summary.get("reason") or reason
        ring_lay_summary = None
        if jewelry_type == "ring":
            ring_lay_summary = aggregate_ring_lay(ring_frame_lays)
            if ring_lay_summary.get("final_result") == "FAIL":
                overall = "FAIL"
                reason = ring_lay_summary.get("reason") or reason
                action = (
                    "Reposition the ring around the selected finger near the finger base, "
                    "aligned with the finger center — not on the palm, knuckle, or adjacent fingers."
                )
            elif ring_lay_summary.get("final_result") == "WARNING" and overall == "PASS":
                overall = "WARNING"
                reason = ring_lay_summary.get("reason") or reason
                action = "Review ring frames for partial hand visibility, slight tilt, or low ring confidence."
            elif ring_lay_summary.get("final_result") == "PASS" and overall in {"PASS", "WARNING"}:
                reason = ring_lay_summary.get("reason") or reason
        bracelet_lay_summary = None
        if jewelry_type == "bracelet":
            bracelet_lay_summary = aggregate_bracelet_lay(bracelet_frame_lays)
            if bracelet_lay_summary.get("final_result") == "FAIL":
                overall = "FAIL"
                reason = bracelet_lay_summary.get("reason") or reason
                action = (
                    "Reposition the bracelet around the wrist near the wrist joint, "
                    "aligned with the wrist center — not on the palm, fingers, or upper forearm."
                )
            elif bracelet_lay_summary.get("final_result") == "WARNING" and overall == "PASS":
                overall = "WARNING"
                reason = bracelet_lay_summary.get("reason") or reason
                action = "Review bracelet frames for partial wrist visibility, clothing occlusion, or slight tilt."
            elif bracelet_lay_summary.get("final_result") == "PASS" and overall in {"PASS", "WARNING"}:
                reason = bracelet_lay_summary.get("reason") or reason
        bangle_lay_summary = None
        if jewelry_type == "bangle":
            bangle_lay_summary = aggregate_bangle_lay(bangle_frame_lays)
            if bangle_lay_summary.get("final_result") == "FAIL":
                overall = "FAIL"
                reason = bangle_lay_summary.get("reason") or reason
                action = (
                    "Reposition the bangle around the wrist so it keeps a natural circular or oval shape "
                    "at the wrist joint — not on the palm, fingers, or upper forearm."
                )
            elif bangle_lay_summary.get("final_result") == "WARNING" and overall == "PASS":
                overall = "WARNING"
                reason = bangle_lay_summary.get("reason") or reason
                action = "Review bangle frames for tilt, uneven multi-bangle spacing, or partial wrist visibility."
            elif bangle_lay_summary.get("final_result") == "PASS" and overall in {"PASS", "WARNING"}:
                reason = bangle_lay_summary.get("reason") or reason
        statistics = self._statistics(len(raw_frames), len(evaluated), selected, temporal, sides)
        report = {
            "test_run_id": run_id,
            "test_id": test_id,
            "test_name": test_name,
            "overall_status": overall,
            "reason": reason,
            "recommended_action": action,
            "jewelry_type": jewelry_type,
            "layers": {
                "frame_selection": {"status": layer1, "detail": layer1_detail},
                "anchor_detection": {"status": layer2, "detail": self._layer2_detail(sides, missing_earlobe, missing_earring, len(selected))},
                "placement_validation": {
                    "status": layer3_status,
                    "detail": " ".join(temporal[side].reason for side in sides) if selected else "Placement was not run.",
                },
            },
            "statistics": statistics,
            "thresholds": {
                "pass_threshold": config["pass_threshold"],
                "fail_threshold": config["fail_threshold"],
                "minimum_pass_rate": config["minimum_pass_rate"],
                "minimum_confidence": config["minimum_confidence"],
                "maximum_consecutive_failures": config["maximum_consecutive_failures"],
                "zone_y_scale": config["zone_y_scale"],
            },
            "reference_comparison": reference_report,
            "temporal": {side: temporal[side].__dict__ for side in sides},
            "visual_comparison": visual,
            "jewelry_id": jewelry_id,
            "ear_side": ear_side,
            "reference_filename": reference_filename,
            "frames": frame_payloads,
            "rejection_summary": self._rejection_summary(evaluated),
        }
        if necklace_lay_summary is not None:
            report["necklace_lay"] = necklace_lay_summary
        if earring_lay_summary is not None:
            report["earring_lay"] = earring_lay_summary
        if ring_lay_summary is not None:
            report["ring_lay"] = ring_lay_summary
            report["selected_finger"] = selected_finger
        if bracelet_lay_summary is not None:
            report["bracelet_lay"] = bracelet_lay_summary
        if bangle_lay_summary is not None:
            report["bangle_lay"] = bangle_lay_summary
        report_path = self.reports.write(output_dir, report)
        reports_copy = self.settings.data_dir / "reports" / f"{run_id}.json"
        reports_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(report_path, reports_copy)
        log_event("REPORT_GENERATED", test_run_id=run_id, overall_status=overall)
        self._save_tested_application(run_id)

        with session_scope() as session:
            run = self._require_run(session, run_id)
            for side in sides:
                run_repo.add_placement(
                    session,
                    PlacementResultRow(
                        id=f"{run_id}-{side}",
                        test_run_id=run_id,
                        side=side,
                        status=temporal[side].status,
                        summary_json=json.dumps(temporal[side].__dict__),
                    ),
                )
            run_repo.add_report(
                session,
                ReportRow(
                    id=f"RPT-{run_id}",
                    test_run_id=run_id,
                    path=str(report_path),
                    overall_status=overall,
                ),
            )
            run.overall_status = overall
            run.reason = reason
            run.recommended_action = action
            run.statistics_json = json.dumps(statistics)
            run.layers_json = json.dumps(report["layers"])
            run.report_json = json.dumps(report)
            run.status = "completed"
            run.progress = 100
            run.stage = "completed"
            run.stage_message = f"Overall {overall}."
            run.finished_at = datetime.now(timezone.utc)
            self._set_step(session, run, "earlobe_detection", "PASS" if layer2 == "PASS" else layer2, "Earlobe detection finished.", 88)
            self._set_step(session, run, "earring_detection", "PASS" if layer2 == "PASS" else layer2, "Earring anchor detection finished.", 92)
            self._set_step(session, run, "placement_validation", layer3_status, report["layers"]["placement_validation"]["detail"], 96)
            self._set_step(session, run, "report", "PASS", "Report generated.", 100, status="completed")
            run_repo.save_run(session, run)
        return report

    def _detect_faces(self, raw_frames: list[RawFrame]) -> list[FaceLandmarkResult]:
        provider = self.landmark_provider or MediaPipeFaceLandmarker(self.settings.resolved_face_model_path)
        faces: list[FaceLandmarkResult] = []
        try:
            for frame in raw_frames:
                from app.cv.image_processing import read_bgr

                image = read_bgr(frame.path)
                faces.append(provider.detect(bgr_to_rgb(image)))
        except FaceLandmarkError:
            raise
        finally:
            close = getattr(provider, "close", None)
            if close and provider is not self.landmark_provider:
                close()
        return faces

    def _persist_frame_row(self, run_id: str, item: SelectedFrame, selected_ids: set[int]) -> None:
        rejected = bool(item.quality.rejection_reasons) or item.raw.index not in selected_ids
        reasons = list(item.quality.rejection_reasons)
        if item.raw.index not in selected_ids and not reasons:
            reasons.append("not_selected_as_representative")
        with session_scope() as session:
            run_repo.add_frame(
                session,
                FrameRecord(
                    id=self._frame_id(run_id, item.raw.index),
                    test_run_id=run_id,
                    frame_number=item.raw.index,
                    timestamp_ms=item.raw.timestamp_ms,
                    path=str(item.raw.path),
                    selected=item.raw.index in selected_ids,
                    rejected=item.raw.index not in selected_ids,
                    rejection_reasons=json.dumps(reasons),
                    quality_json=item.quality.model_dump_json(),
                ),
            )
            session.commit()

    def _update_annotated_path(self, run_id: str, item: SelectedFrame, path: Path) -> None:
        with session_scope() as session:
            frame = run_repo.get_frame(session, self._frame_id(run_id, item.raw.index))
            if frame is not None:
                frame.annotated_path = str(path)
                session.add(frame)
                session.commit()

    def _persist_frame_result(self, run_id: str, item: SelectedFrame, payload: dict) -> None:
        with session_scope() as session:
            run_repo.add_frame_result(
                session,
                FrameResult(
                    id=f"{self._frame_id(run_id, item.raw.index)}-{payload['side']}",
                    frame_id=self._frame_id(run_id, item.raw.index),
                    test_run_id=run_id,
                    side=payload["side"],
                    status=payload["status"],
                    normalized_distance=payload.get("normalized_distance"),
                    result_json=json.dumps(payload),
                    automated_result=payload["status"],
                ),
            )
            session.commit()

    def _frame_payload(
        self,
        item,
        side,
        earlobe,
        earring,
        measurement: PlacementMeasurement,
        earlobe_error,
        *,
        necklace_lay: dict | None = None,
        earring_lay: dict | None = None,
        ring_lay: dict | None = None,
        bracelet_lay: dict | None = None,
        bangle_lay: dict | None = None,
    ) -> dict:
        payload = {
            "frame_number": item.raw.index,
            "timestamp_ms": item.raw.timestamp_ms,
            "side": side,
            "ear": None
            if earlobe is None
            else {
                "side": side,
                "anchor": {"x": earlobe.x, "y": earlobe.y},
                "confidence": earlobe.confidence,
                "ear_width": earlobe.ear_width,
                "ear_height": earlobe.ear_height,
            },
            "earring": None
            if earring is None or earring.x is None
            else {
                "anchor": {"x": earring.x, "y": earring.y},
                "confidence": earring.confidence,
                "source": earring.source,
                "visible": earring.visible,
            },
            "placement": {
                "dx": measurement.dx,
                "dy": measurement.dy,
                "normalized_distance": measurement.normalized_distance,
                "status": measurement.status,
                "reason": measurement.reason,
            },
            "status": measurement.status,
            "reason": earlobe_error or measurement.reason,
            "earlobe_detected": earlobe is not None,
            "earring_detected": bool(earring and earring.x is not None and earring.visible),
            "earlobe_confidence": earlobe.confidence if earlobe else None,
            "earring_confidence": earring.confidence if earring else None,
            "normalized_distance": measurement.normalized_distance,
            "dx": measurement.dx,
            "dy": measurement.dy,
            "earlobe": None if earlobe is None else {"x": earlobe.x, "y": earlobe.y},
            "earring_anchor": None if earring is None or earring.x is None else {"x": earring.x, "y": earring.y},
            "zone": None
            if earlobe is None
            else {"ear_width": earlobe.ear_width, "ear_height": earlobe.ear_height},
        }
        if necklace_lay is not None:
            payload["necklace_lay"] = necklace_lay
        if earring_lay is not None:
            payload["earring_lay"] = earring_lay
        if ring_lay is not None:
            payload["ring_lay"] = ring_lay
        if bracelet_lay is not None:
            payload["bracelet_lay"] = bracelet_lay
        if bangle_lay is not None:
            payload["bangle_lay"] = bangle_lay
        return payload

    def _reference_report(self, sides, measurements, reference_vector, validator, config) -> dict:
        if reference_vector is None:
            return {"status": "NOT_RUN", "reason": "No reference relative placement vector is available."}
        reports = []
        for side in sides:
            usable = [item for item in measurements[side] if item.dx is not None and item.dy is not None]
            if not usable:
                reports.append({"side": side, "status": "FAIL", "reason": "No measured frames to compare with the reference."})
                continue
            mean_dx = sum(item.dx for item in usable) / len(usable)
            mean_dy = sum(item.dy for item in usable) / len(usable)
            mean_norm = sum(item.normalized_distance or 0 for item in usable) / len(usable)
            average = PlacementMeasurement(
                dx=mean_dx,
                dy=mean_dy,
                normalized_distance=mean_norm,
                status="PASS",
                reason="",
            )
            comparison = validator.compare(reference_vector, average, config)
            reports.append({"side": side, **comparison.model_dump()})
        status = combine_statuses([item["status"] for item in reports])
        return {"status": status, "sides": reports, "reason": reports[0]["reason"] if reports else ""}

    def _decide(self, **kwargs) -> tuple[str, str, str]:
        layer1 = kwargs["layer1"]
        layer2 = kwargs["layer2"]
        layer3 = kwargs["layer3"]
        reference_status = kwargs["reference_status"]
        temporal = kwargs["temporal"]
        critical = kwargs["critical"]
        sides = kwargs["sides"]
        missing_earlobe = kwargs["missing_earlobe"]
        missing_earring = kwargs["missing_earring"]
        selected_count = kwargs["selected_count"]
        config = kwargs["config"]
        jewelry_type = kwargs.get("jewelry_type") or "earring"
        if layer1 == "FAIL":
            return (
                "FAIL",
                f"Insufficient frames. {selected_count} representative frames were selected.",
                "Improve face and ear visibility, reduce blur, or lower the capture motion.",
            )
        chunks = []
        body_name = "earlobe" if jewelry_type == "earring" else ("neck" if jewelry_type == "necklace" else f"{jewelry_type} body")
        jewel_name = "earring" if jewelry_type == "earring" else jewelry_type
        for side in sides:
            if missing_earlobe[side]:
                chunks.append(
                    f"Unable to detect {side} {body_name} in {missing_earlobe[side]} of {selected_count} selected frames."
                )
            if missing_earring[side]:
                chunks.append(
                    f"Unable to detect {side} {jewel_name} attachment anchor in {missing_earring[side]} of {selected_count} selected frames."
                )
        rate_ok = all(temporal[side].pass_rate >= config["minimum_pass_rate"] for side in sides)
        consecutive_ok = all(
            temporal[side].max_consecutive_failures <= config["maximum_consecutive_failures"] for side in sides
        )
        reference_ok = reference_status in {"PASS", "NOT_RUN", "WARNING"}
        if critical:
            chunks.append(f"A required {body_name} had no successful anchor pair.")
        if layer3 == "FAIL":
            chunks.append(" ".join(temporal[side].reason for side in sides))
        if reference_status == "FAIL":
            chunks.append("Reference relative placement does not match the actual try-on.")
        passed = (
            layer2 == "PASS"
            and layer3 == "PASS"
            and rate_ok
            and consecutive_ok
            and critical == 0
            and reference_status in {"PASS", "NOT_RUN"}
        )
        if passed:
            if jewelry_type == "necklace":
                return (
                    "PASS",
                    "Necklace is positioned around the neck and follows the natural neckline.",
                    "None.",
                )
            if jewelry_type == "ring":
                return (
                    "PASS",
                    "Ring is positioned around the selected finger near the natural finger base.",
                    "None.",
                )
            if jewelry_type == "bracelet":
                return (
                    "PASS",
                    "Bracelet is positioned around the wrist near the wrist joint.",
                    "None.",
                )
            if jewelry_type == "bangle":
                return (
                    "PASS",
                    "Bangle is positioned around the wrist and keeps a natural circular or oval shape.",
                    "None.",
                )
            return ("PASS", "Earring attachment points stayed inside the earlobe placement zone.", "None.")
        if layer3 == "WARNING" and layer2 in {"PASS", "WARNING"} and critical == 0 and reference_ok:
            if jewelry_type == "necklace":
                return (
                    "WARNING",
                    "Necklace placement is near the edge of the allowed neckline zone.",
                    "Review warning frames for uneven sides or a slightly misaligned pendant.",
                )
            if jewelry_type == "ring":
                return (
                    "WARNING",
                    "Ring placement is near the edge of the allowed finger zone.",
                    "Review warning frames for slight tilt, partial hand visibility, or low ring confidence.",
                )
            if jewelry_type == "bracelet":
                return (
                    "WARNING",
                    "Bracelet placement is near the edge of the allowed wrist zone.",
                    "Review warning frames for clothing occlusion, slight tilt, or partial wrist visibility.",
                )
            if jewelry_type == "bangle":
                return (
                    "WARNING",
                    "Bangle placement is near the edge of the allowed wrist zone.",
                    "Review warning frames for tilt, uneven multi-bangle spacing, or partial wrist visibility.",
                )
            return (
                "WARNING",
                "Placement is near the edge of the allowed earlobe zone.",
                "Review warning frames and confirm the earring attachment object in the try-on scene.",
            )
        reason = " ".join(chunks) or "Placement validation failed."
        action = "Check camera angle or improve ear visibility."
        if jewelry_type == "necklace":
            action = "Confirm the face and neck are visible and the necklace sits on the neckline."
        if jewelry_type == "ring":
            action = "Confirm the hand and selected finger are visible and the ring sits near the finger base."
        if jewelry_type == "bracelet":
            action = "Confirm the wrist is visible and the bracelet sits around the wrist joint."
        if jewelry_type == "bangle":
            action = "Confirm the wrist is visible and the bangle sits around the wrist with a natural circle/oval."
        if any(missing_earring.values()):
            action = (
                "Expose the AIJewel debug anchor (window.__AIJEWEL_QA__ or GET /debug/tryon-state) "
                "so the attachment point is projected from the jewelry transform."
            )
        return ("FAIL", reason, action)

    def _statistics(self, captured, analyzed, selected, temporal, sides) -> dict:
        passed = sum(temporal[side].passed_frames for side in sides)
        warnings = sum(temporal[side].warning_frames for side in sides)
        failed = sum(temporal[side].failed_frames for side in sides)
        total = sum(temporal[side].total_frames for side in sides)
        rates = [temporal[side].pass_rate for side in sides]
        return {
            "frames_captured": captured,
            "frames_analyzed": analyzed,
            "frames_selected": len(selected),
            "frames_passed": passed,
            "frames_warning": warnings,
            "frames_failed": failed,
            "pass_rate": (passed / total) if total else 0.0,
            "max_consecutive_failures": max(temporal[side].max_consecutive_failures for side in sides) if sides else 0,
            "side_pass_rates": {side: rates[index] for index, side in enumerate(sides)},
        }

    def _layer2_status(self, sides, missing_earlobe, missing_earring, selected_count) -> str:
        if selected_count == 0:
            return "FAIL"
        states = []
        for side in sides:
            if missing_earlobe[side] == selected_count or missing_earring[side] == selected_count:
                states.append("FAIL")
            elif missing_earlobe[side] or missing_earring[side]:
                states.append("WARNING")
            else:
                states.append("PASS")
        return combine_statuses(states)

    def _layer2_detail(self, sides, missing_earlobe, missing_earring, selected_count) -> str:
        parts = []
        for side in sides:
            parts.append(
                f"{side} earlobe misses {missing_earlobe[side]}/{selected_count}, "
                f"earring misses {missing_earring[side]}/{selected_count}."
            )
        return " ".join(parts)

    def _rejection_summary(self, evaluated: list[SelectedFrame]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for frame in evaluated:
            for reason in frame.quality.rejection_reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return counts

    def _vector_from_reference(self, reference: ReferenceImage | None) -> ReferenceVector | None:
        if reference is None or None in {
            reference.earlobe_x,
            reference.earlobe_y,
            reference.earring_x,
            reference.earring_y,
            reference.ear_width,
            reference.ear_height,
        }:
            return None
        return reference_vector_from_points(
            reference.earlobe_x,
            reference.earlobe_y,
            reference.earring_x,
            reference.earring_y,
            reference.ear_width,
            reference.ear_height,
            self.settings.default_zone_y_scale,
        )

    def _config(self, test: TestDefinition) -> dict:
        return {
            "minimum_confidence": test.minimum_confidence,
            "pass_threshold": test.pass_threshold,
            "fail_threshold": test.fail_threshold,
            "minimum_pass_rate": test.minimum_pass_rate,
            "maximum_consecutive_failures": test.maximum_consecutive_failures,
            "zone_y_scale": test.zone_y_scale,
            "min_selected_frames": test.min_selected_frames,
            "max_selected_frames": test.max_selected_frames,
            "selected_finger": getattr(test, "selected_finger", None) or "ring",
        }

    def _set_step(
        self,
        session: Session,
        run: TestRun,
        name: str,
        step_status: str,
        detail: str,
        progress: float,
        status: str | None = None,
    ) -> None:
        steps = json.loads(run.steps_json or "[]")
        found = False
        for step in steps:
            if step["name"] == name:
                step["status"] = step_status
                step["detail"] = detail
                found = True
        if not found:
            steps.append({"name": name, "status": step_status, "detail": detail})
        run.steps_json = json.dumps(steps)
        run.stage = name
        run.stage_message = detail
        run.progress = progress
        if status:
            run.status = status
        elif run.status in {"pending", "running"}:
            run.status = "running"
        run_repo.save_run(session, run)

    def _save_tested_application(self, run_id: str) -> None:
        from app.services.application_service import ApplicationService

        try:
            with session_scope() as session:
                run = session.get(TestRun, run_id)
                if run is None:
                    return
                test = session.get(TestDefinition, run.test_id)
                if test is None:
                    return
                ApplicationService().save_tested_application(session, test.application_id)
        except Exception:
            log_event("APPLICATION_SAVE_FAILED", test_run_id=run_id)

    def _fail(self, run_id: str, exc: Exception) -> None:
        self._save_tested_application(run_id)
        message = str(exc) or exc.__class__.__name__
        action = getattr(exc, "recommended_action", None) or "Review the stage message and run the test again."
        with session_scope() as session:
            run = session.get(TestRun, run_id)
            if run is None:
                return
            run.status = "failed"
            run.overall_status = "FAIL"
            run.error = message
            run.reason = message
            run.recommended_action = action
            run.stage_message = message
            run.finished_at = datetime.now(timezone.utc)
            steps = json.loads(run.steps_json or "[]")
            for step in steps:
                if step["status"] in {"WAITING", "RUNNING"}:
                    step["status"] = "FAIL"
                    step["detail"] = message
                    break
            run.steps_json = json.dumps(steps)
            report = {
                "test_run_id": run_id,
                "overall_status": "FAIL",
                "reason": message,
                "recommended_action": action,
                "layers": {
                    "frame_selection": {"status": "NOT_RUN", "detail": message},
                    "anchor_detection": {"status": "NOT_RUN", "detail": ""},
                    "placement_validation": {"status": "NOT_RUN", "detail": ""},
                },
            }
            run.report_json = json.dumps(report)
            run_repo.save_run(session, run)

    def _require_run(self, session: Session, run_id: str) -> TestRun:
        run = session.get(TestRun, run_id)
        if run is None:
            raise TryOnError(f"Test run {run_id} was not found.", "RUN_NOT_FOUND")
        return run

    def _require_test(self, session: Session, test_id: str) -> TestDefinition:
        test = session.get(TestDefinition, test_id)
        if test is None:
            raise TryOnError(f"Test {test_id} was not found.", "TEST_NOT_FOUND")
        return test

    @staticmethod
    def _frame_id(run_id: str, index: int) -> str:
        return f"{run_id}-F{index:04d}"


def initial_steps() -> list[dict]:
    return [{"name": name, "status": "WAITING", "detail": ""} for name in WAITING_STEPS]
