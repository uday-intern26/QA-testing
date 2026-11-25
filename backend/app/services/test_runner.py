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
from app.cv.debug_config import debug_profile_for
from app.cv.debug_landmarks import contour_indices, selected_landmark_index, uses_hand_landmarks
from app.cv.debug_overlay import render_debug_frame
from app.cv.landmark_validation import FrameValidation, evaluate_frame, summarize_validation
from app.cv.face_landmarks import FaceLandmarkError, MediaPipeFaceLandmarker
from app.cv.hand_landmarks import HandLandmarkError, MediaPipeHandLandmarker
from app.cv.image_processing import bgr_to_rgb, read_bgr
from app.cv.jewelry_presence import frame_wears_jewelry
from app.cv.jewelry_profiles import profile_for
from app.cv.types import FaceLandmarkResult, HandLandmarkResult, PlacementMeasurement, ReferenceVector
from app.cv.visualization import OverlayPalette, annotate_frame, save_image
from app.db.database import session_scope
from app.db.repositories import runs as run_repo
from app.models.frame import FrameRecord, FrameResult
from app.models.reference import ReferenceImage
from app.models.result import PlacementResultRow, ReportRow, TestRun
from app.models.test import TestDefinition
from app.services.capture_service import CaptureService
from app.services.frame_review import apply_frame_review
from app.services.comparison_service import ComparisonService
from app.services.earlobe_detector import EarlobeDetector
from app.services.earring_detector import DebugStateEarringDetector, FallbackEarringAnchorDetector
from app.services.frame_selector import FrameSelector, RawFrame, SelectedFrame
from app.cv.earring_lay import aggregate_earring_lay, evaluate_earring_lay, measurement_from_earring_lay
from app.cv.necklace_lay import aggregate_necklace_lay, evaluate_necklace_lay, measurement_from_necklace_lay
from app.cv.bangle_lay import aggregate_bangle_lay, evaluate_bangle_lay, measurement_from_bangle_lay
from app.cv.bracelet_lay import aggregate_bracelet_lay, evaluate_bracelet_lay, measurement_from_bracelet_lay
from app.cv.ring_lay import aggregate_ring_lay, evaluate_ring_lay, measurement_from_ring_lay
from app.cv.tryon_placement_rules import (
    EUCLIDEAN_PASS,
    EUCLIDEAN_WARNING,
    aggregate_placement_panel,
    validate_earring_side,
    validate_necklace_frame,
)
from app.services.placement_validator import validator_for
from app.services.report_service import ReportService
from app.services.temporal_validator import combine_statuses, summarize_temporal

def anchor_diagnostics(debug_state: dict | None) -> dict:
    """Per-frame record of how far the jewelry anchor pipeline got.

    The stages mirror the try-on data flow: the page publishes a QA bridge, or the
    scene probe reads the GLB transform, or neither and we say which step stopped.
    """
    if not isinstance(debug_state, dict):
        return {
            "anchor_source": "unavailable",
            "anchor_stage": "NO_DEBUG_STATE",
            "detail": "The try-on page published no QA bridge and no scene was readable.",
        }
    scene = debug_state.get("scene_diagnostics") if isinstance(debug_state.get("scene_diagnostics"), dict) else {}
    raw_source = debug_state.get("anchor_source")
    if not raw_source or str(raw_source).lower() in {"unavailable", "none", "null"}:
        anchor_source = "qa_overlay" if debug_state.get("qa_overlay") else None
    else:
        anchor_source = raw_source
    stage = debug_state.get("anchor_stage")
    has_anchor = any(
        isinstance(debug_state.get(key), dict) and debug_state[key].get("x") is not None
        for key in ("left", "right", "center", "necklace", "ring", "bracelet", "bangle", "jewelry", "attachment")
    )
    if not stage:
        if has_anchor:
            stage = "ANCHOR_AVAILABLE"
            if not anchor_source:
                anchor_source = "debug_bridge"
        else:
            stage = "NO_ANCHOR_IN_DEBUG_STATE"
            if not anchor_source:
                anchor_source = "unavailable"
    return {
        "anchor_source": anchor_source or "unavailable",
        "anchor_stage": stage,
        "qa_status": debug_state.get("qa_status"),
        "glb_loaded": scene.get("glb_loaded"),
        "mesh_visible": scene.get("mesh_visible"),
        "transform_computed": scene.get("transform_computed"),
        "camera_found": scene.get("camera_found"),
        "anchor_projected": scene.get("anchor_projected"),
        "notes": list(scene.get("notes") or []),
    }


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

        from app.services.browser_service import release_live_tryon

        await release_live_tryon()
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
        adapter.min_capture_frames = self.settings.min_capture_frames
        adapter.target_capture_frames = self.settings.target_capture_frames
        adapter.capture_timeout_seconds = self.settings.capture_timeout_seconds
        adapter.jewelry_appear_timeout_seconds = self.settings.jewelry_appear_timeout_seconds
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
            settle_seconds = float(getattr(self.settings, "jewelry_settle_seconds", 15) or 15)
            with session_scope() as session:
                run = self._require_run(session, run_id)
                self._set_step(
                    session,
                    run,
                    "capture",
                    "RUNNING",
                    (
                        f"Waiting until the jewelry is on the girl video, then {settle_seconds:.0f}s settle, "
                        "then capturing frames. Pass or fail is decided after this."
                    ),
                    40,
                )
            frames, capture_note = await self.capture_service.capture(
                adapter,
                jewelry_id,
                jewelry_type=jewelry_type,
                already_selected=True,
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
                self._set_step(
                    session,
                    run,
                    "capture",
                    "PASS",
                    f"{capture_note} Captured {len(frames)} frames from the try-on AR (no QA overlay).",
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
            debug_mode = bool(getattr(test, "debug_mode", False))
            debug_overrides = self._debug_overrides(test)
            output_dir = self.settings.data_dir / "results" / run.id
            output_dir.mkdir(parents=True, exist_ok=True)

        if not raw_frames:
            raise TryOnError(
                "No frames were captured.",
                "INSUFFICIENT_FRAMES",
                "Increase the capture duration or confirm the try-on view is visible.",
            )

        category = profile_for(jewelry_type)
        selector = FrameSelector(
            min_blur_variance=self.settings.min_blur_variance,
            blur_norm_variance=self.settings.blur_norm_variance,
            duplicate_hash_distance=self.settings.duplicate_hash_distance,
            head_pose_max_delta_deg=self.settings.head_pose_max_delta_deg,
            head_pose_max_yaw_deg=self.settings.head_pose_max_yaw_deg,
            min_ear_width=self.settings.min_ear_width,
            minimum_confidence=config["minimum_confidence"],
            ear_side=ear_side if jewelry_type == "earring" else "left",
            jewelry_type=jewelry_type,
        )
        faces = self._detect_faces(raw_frames)
        hands = self._detect_hands(raw_frames) if category.requires_hand else None
        evaluated = selector.evaluate(raw_frames, faces, hands=hands)
        needed = int(config["min_selected_frames"])
        worn = [frame for frame in evaluated if self._frame_wears_jewelry(frame, jewelry_type)]
        body_ok = [frame for frame in evaluated if selector._has_required_body(frame.quality)]
        # Measure every captured frame. Tracing-point distance, not sharpness, picks the best ones.
        selected = list(evaluated)
        selected_ids = {frame.raw.index for frame in evaluated}
        for frame in evaluated:
            frame.quality.selection_status = "measured"
        layer1 = "PASS" if len(body_ok) >= needed or len(worn) >= needed else "FAIL"
        required_parts = ", ".join(category.required_body_parts)
        usable_count = len(body_ok) if body_ok else len(worn)
        rejected_count = max(0, len(raw_frames) - usable_count)
        if layer1 == "PASS":
            layer1_detail = (
                f"{len(raw_frames)} frames captured after the jewelry was laid "
                f"({usable_count} with the required body: {required_parts}). "
                "The closest tracing-point matches are ranked after placement."
            )
        else:
            missing_counts: dict[str, int] = {}
            for frame in evaluated:
                detected = set(frame.quality.detected_body_parts or [])
                for part in category.required_body_parts:
                    if part not in detected:
                        missing_counts[part] = missing_counts.get(part, 0) + 1
            missing_hint = (
                "; most common missing: "
                + ", ".join(f"{part} ({count})" for part, count in sorted(missing_counts.items(), key=lambda item: -item[1])[:3])
                if missing_counts
                else ""
            )
            layer1_detail = (
                f"Only {len(body_ok)} frames showed the required body ({required_parts}); "
                f"{needed} are required"
                f"{missing_hint}."
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
        placement_panel_frames: list[dict] = []
        debug_profile = debug_profile_for(jewelry_type, debug_overrides)
        landmark_validations: dict[str, list[FrameValidation]] = {side: [] for side in sides}
        debug_frame_paths: list[dict] = []

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
                    body, body_error = body_anchor_for(
                        jewelry_type,
                        item.face,
                        side,
                        hand=getattr(item, "hand", None),
                        selected_finger=selected_finger,
                    )
                if body is None:
                    missing_earlobe[side] += 1
                detect_side = side if jewelry_type != "necklace" else "center"
                jewelry = self.debug_detector.detect_from_state(item.raw.debug_state, detect_side)
                if jewelry is None or not jewelry.visible or jewelry.x is None:
                    debug_state = item.raw.debug_state if isinstance(item.raw.debug_state, dict) else {}
                    diagnostics = anchor_diagnostics(debug_state)
                    from app.cv.types import EarringAnchor

                    # Do not invent attachment coordinates from skin highlights. When the
                    # try-on never published an anchor, report that explicitly.
                    stage = diagnostics.get("anchor_stage") or "ATTACHMENT_ANCHOR_MISSING"
                    jewelry = EarringAnchor(
                        side=detect_side,
                        source="missing",
                        visible=False,
                        confidence=0.0,
                        reason=(
                            f"{jewelry_type.capitalize()} attachment was not published "
                            f"({stage}). QA will not invent coordinates from the pixels."
                        ),
                    )
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
                        hand_landmarks=getattr(item, "hand", None),
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
                        hand_landmarks=getattr(item, "hand", None),
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
                        hand_landmarks=getattr(item, "hand", None),
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
                panel_row: dict = {
                    "frame_number": item.raw.index,
                    "timestamp_ms": item.raw.timestamp_ms,
                    "head_angle_deg": None,
                }
                for side, body, jewelry, measurement, body_error, necklace_lay, ring_lay, bracelet_lay, bangle_lay in side_results:
                    side_meas = measurement_from_earring_lay(earring_lay, side, measurement)
                    panel_side = validate_earring_side(
                        side,
                        item.face,
                        body,
                        jewelry,
                        required=side in sides,
                        pass_threshold=float(config.get("pass_threshold", EUCLIDEAN_PASS)),
                        fail_threshold=float(config.get("fail_threshold", EUCLIDEAN_WARNING)),
                    )
                    panel_row[side] = panel_side
                    panel_row["head_angle_deg"] = panel_side.get("head_angle_deg")
                    # Prefer landmark-relative panel status; never upgrade FAIL/WARNING to PASS.
                    if panel_side.get("status") in {"FAIL", "WARNING", "NOT_TESTABLE"}:
                        # Keep the diagnostic "attachment was not published" reason when the
                        # try-on never sent coordinates — the pass-tracking copy is less useful.
                        missing_anchor = (
                            jewelry is None
                            or not jewelry.visible
                            or jewelry.x is None
                            or str(jewelry.source or "").lower() == "missing"
                        )
                        if missing_anchor and jewelry is not None and jewelry.reason:
                            reason = jewelry.reason
                        else:
                            reason = panel_side.get("reason") or side_meas.reason
                        side_meas = side_meas.model_copy(
                            update={
                                "status": panel_side["status"],
                                "reason": reason,
                                "normalized_distance": panel_side.get("placement_error", side_meas.normalized_distance),
                            }
                        )
                    per_side_statuses[side][-1] = side_meas.status
                    per_side_measurements[side][-1] = side_meas
                    updated_side_results.append(
                        (side, body, jewelry, side_meas, body_error, necklace_lay, ring_lay, bracelet_lay, bangle_lay)
                    )
                side_results = updated_side_results
                placement_panel_frames.append(panel_row)
            elif jewelry_type == "necklace" and side_results:
                side, body, jewelry, measurement, body_error, necklace_lay, ring_lay, bracelet_lay, bangle_lay = side_results[0]
                left_jewel = self.debug_detector.detect_from_state(item.raw.debug_state, "left")
                right_jewel = self.debug_detector.detect_from_state(item.raw.debug_state, "right")
                panel_row = validate_necklace_frame(
                    item.face,
                    body,
                    jewelry,
                    left_jewelry=left_jewel,
                    right_jewelry=right_jewel,
                    pass_threshold=float(config.get("pass_threshold", EUCLIDEAN_PASS)),
                    fail_threshold=float(config.get("fail_threshold", EUCLIDEAN_WARNING)),
                )
                panel_row = {
                    **panel_row,
                    "frame_number": item.raw.index,
                    "timestamp_ms": item.raw.timestamp_ms,
                }
                placement_panel_frames.append(panel_row)
                if panel_row.get("status") in {"FAIL", "WARNING", "NOT_TESTABLE"} and necklace_lay is not None:
                    measurement = measurement.model_copy(
                        update={
                            "status": panel_row["status"],
                            "reason": panel_row.get("reason") or measurement.reason,
                            "normalized_distance": panel_row.get("placement_error", measurement.normalized_distance),
                        }
                    )
                    per_side_statuses[side][-1] = measurement.status
                    per_side_measurements[side][-1] = measurement
                    side_results = [
                        (side, body, jewelry, measurement, body_error, necklace_lay, ring_lay, bracelet_lay, bangle_lay)
                    ]

            frame_size = (int(image.shape[1]), int(image.shape[0]))
            diagnostics = anchor_diagnostics(item.raw.debug_state)
            frame_validations: dict[str, FrameValidation] = {}
            for side, body, jewelry, _meas, *_rest in side_results:
                landmark_index = selected_landmark_index(jewelry_type, side, selected_finger)
                validation = evaluate_frame(
                    frame_number=item.raw.index,
                    timestamp_ms=item.raw.timestamp_ms,
                    side=side,
                    profile=debug_profile,
                    face=item.face,
                    hand=getattr(item, "hand", None),
                    expected=body,
                    jewelry=jewelry,
                    frame_size=frame_size,
                    landmark_index=landmark_index,
                    diagnostics=diagnostics,
                )
                landmark_validations.setdefault(side, []).append(validation)
                frame_validations[side] = validation
                if not debug_mode:
                    continue
                debug_canvas = render_debug_frame(
                    image,
                    profile=debug_profile,
                    validation=validation,
                    face=item.face,
                    hand=getattr(item, "hand", None),
                    expected=body,
                    jewelry=jewelry,
                    contour_indices=contour_indices(jewelry_type, side),
                    selected_landmark_index=landmark_index,
                    selected_landmark_source="hand" if uses_hand_landmarks(jewelry_type) else "face",
                )
                debug_path = output_dir / "debug_frames" / f"frame_{item.raw.index:04d}_{side}.png"
                save_image(debug_path, debug_canvas)
                debug_frame_paths.append(
                    {
                        "frame_number": item.raw.index,
                        "side": side,
                        "status": validation.status,
                        "failure_reason": validation.failure_reason,
                        "path": str(debug_path),
                    }
                )

            self._write_frame_landmarks(output_dir, item, jewelry_type, selected_finger, sides)

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
                    validation=frame_validations.get(side),
                )
                frame_payloads.append(payload)
                self._persist_frame_result(run_id, item, payload)

        order = self._rank_placement_frames(frame_payloads, top_n=5)
        top_numbers = set(order[:5])
        self._persist_ranking(run_id, frame_payloads, top_numbers)
        if layer1 == "PASS" and order:
            by_index = {frame.raw.index: frame for frame in evaluated}
            selected = [by_index[number] for number in order[:5] if number in by_index]
            for frame in evaluated:
                frame.quality.selection_status = "selected" if frame.raw.index in top_numbers else "measured"
            analyzed_order = [frame.raw.index for frame in evaluated]
            index_of = {number: index for index, number in enumerate(analyzed_order)}
            keep_indexes = [index_of[number] for number in sorted(top_numbers) if number in index_of]

            def _take(items: list) -> list:
                return [items[index] for index in keep_indexes if index < len(items)]

            for side in sides:
                per_side_statuses[side] = _take(per_side_statuses[side])
                per_side_measurements[side] = _take(per_side_measurements[side])
                landmark_validations[side] = _take(landmark_validations.get(side, []))
            earring_frame_lays = _take(earring_frame_lays)
            necklace_frame_lays = _take(necklace_frame_lays)
            ring_frame_lays = _take(ring_frame_lays)
            bracelet_frame_lays = _take(bracelet_frame_lays)
            bangle_frame_lays = _take(bangle_frame_lays)
            placement_panel_frames = _take(placement_panel_frames)
            missing_earlobe = {side: 0 for side in sides}
            missing_earring = {side: 0 for side in sides}
            for payload in frame_payloads:
                if payload.get("frame_number") not in top_numbers:
                    continue
                side = payload.get("side")
                if side not in missing_earlobe:
                    continue
                if not payload.get("earlobe_detected"):
                    missing_earlobe[side] += 1
                if not payload.get("earring_detected"):
                    missing_earring[side] += 1
            layer1_detail = (
                f"Top {len(selected)} frames ranked by tracing-point distance "
                f"from {len(raw_frames)} captured."
            )
            with session_scope() as session:
                run = self._require_run(session, run_id)
                self._set_step(session, run, "frame_selection", layer1, layer1_detail, 68)

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
        closest_frames = apply_frame_review(
            frame_payloads,
            float(config["pass_threshold"]),
            float(config["fail_threshold"]),
            limit=10,
        )
        statistics = self._statistics(
            len(raw_frames),
            len(evaluated),
            selected,
            temporal,
            sides,
            jewelry_type=jewelry_type,
            output_dir=output_dir,
        )
        statistics["frames_usable"] = usable_count
        statistics["frames_rejected"] = rejected_count
        statistics["near_pass_frames"] = sum(1 for frame in frame_payloads if frame.get("review_label") == "NEAR_PASS")
        measured = [frame.get("normalized_distance") for frame in frame_payloads if isinstance(frame.get("normalized_distance"), (int, float))]
        statistics["best_placement_distance"] = round(min(measured), 4) if measured else None
        grouped_scores: dict[int, list[float]] = {}
        grouped_valid: dict[int, bool] = {}
        grouped_detected: dict[int, bool] = {}
        for payload in frame_payloads:
            number = int(payload.get("frame_number") or 0)
            grouped_scores.setdefault(number, []).append(float(payload.get("matching_score") or 0.0))
            grouped_valid[number] = grouped_valid.get(number, True) and bool(payload.get("tracing_points_valid"))
            detected = bool(payload.get("earlobe_detected") or payload.get("earring_detected"))
            grouped_detected[number] = grouped_detected.get(number, False) or detected
        valid_scores = [sum(scores) / len(scores) for number, scores in grouped_scores.items() if grouped_valid.get(number)]
        statistics["frames_detected"] = sum(1 for number, flag in grouped_detected.items() if flag)
        statistics["frames_with_tracing_points"] = len(valid_scores)
        statistics["average_tracing_accuracy"] = round(100.0 * sum(valid_scores) / len(valid_scores), 1) if valid_scores else 0.0
        statistics["best_frame_number"] = order[0] if order else None
        statistics["top_frame_numbers"] = order[:5]
        landmark_validation = {
            "enabled": True,
            "debug_mode": debug_mode,
            "enforced": debug_mode,
            "profile": debug_profile.as_dict(),
            "sides": {
                side: summarize_validation(landmark_validations.get(side, []), debug_profile)
                for side in sides
            },
            "debug_frames": debug_frame_paths,
            "failed_debug_frames": [
                entry for entry in debug_frame_paths if entry["status"] == "FAIL"
            ],
        }
        side_overalls = [
            landmark_validation["sides"][side]["overall_status"] for side in sides
        ]
        landmark_validation["overall_status"] = combine_statuses(side_overalls) if side_overalls else "NOT_TESTABLE"
        landmark_validation["failure_reason"] = next(
            (
                landmark_validation["sides"][side]["failure_reason"]
                for side in sides
                if landmark_validation["sides"][side]["failure_reason"]
            ),
            None,
        )
        placement_validation_panel = None
        if jewelry_type in {"earring", "necklace"} and placement_panel_frames:
            placement_validation_panel = aggregate_placement_panel(
                jewelry_type=jewelry_type,
                frame_panels=placement_panel_frames,
            )
            panel_overall = placement_validation_panel.get("overall_status")
            if panel_overall == "FAIL":
                overall = "FAIL"
                reason = next(
                    (
                        str(component.get("reason"))
                        for component in (placement_validation_panel.get("components") or {}).values()
                        if isinstance(component, dict) and component.get("status") == "FAIL" and component.get("reason")
                    ),
                    reason,
                )
                action = "Reposition the jewellery so every visible attachment stays within the pass tolerance."
            elif panel_overall == "WARNING" and overall == "PASS":
                overall = "WARNING"
                reason = "Placement is between the pass and fail Euclidean thresholds."
            elif panel_overall == "NOT_TESTABLE" and overall == "PASS":
                overall = "NOT_TESTABLE"
                reason = "Required ear or necklace anchors were not visible / not testable."
            summary = placement_validation_panel.get("summary") or {}
            statistics = {
                **statistics,
                "frames_passed": summary.get("passed_frames", statistics.get("frames_passed")),
                "frames_warning": summary.get("warning_frames", statistics.get("frames_warning")),
                "frames_failed": summary.get("failed_frames", statistics.get("frames_failed")),
                "frames_not_testable": summary.get("not_testable_frames", 0),
                "testable_frames": summary.get("testable_frames", statistics.get("frames_selected")),
                "pass_percentage": summary.get("pass_percentage"),
                "earring_accuracy": summary.get("earring_accuracy"),
                "necklace_accuracy": summary.get("necklace_accuracy"),
                "pass_rate": (summary.get("pass_percentage", 0) / 100.0)
                if summary.get("pass_percentage") is not None
                else statistics.get("pass_rate"),
            }
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
                "euclidean_pass": EUCLIDEAN_PASS,
                "euclidean_fail": EUCLIDEAN_WARNING,
            },
            "reference_comparison": reference_report,
            "temporal": {side: temporal[side].__dict__ for side in sides},
            "visual_comparison": visual,
            "jewelry_id": jewelry_id,
            "ear_side": ear_side,
            "reference_filename": reference_filename,
            "frames": frame_payloads,
            "closest_frames": [
                {
                    "frame_number": frame.get("frame_number"),
                    "status": frame.get("status"),
                    "review_label": frame.get("review_label"),
                    "normalized_distance": frame.get("normalized_distance"),
                    "placement_gap": frame.get("placement_gap"),
                    "pass_threshold": frame.get("pass_threshold"),
                    "fail_threshold": frame.get("fail_threshold"),
                    "reason": frame.get("reason"),
                    "body_confidence": frame.get("body_confidence"),
                    "earring_confidence": frame.get("earring_confidence"),
                    "earlobe": frame.get("earlobe"),
                    "earring_anchor": frame.get("earring_anchor"),
                }
                for frame in closest_frames
            ],
            "rejection_summary": self._rejection_summary(evaluated),
            "rejection_sources": self._rejection_sources(evaluated),
        }
        report["landmark_validation"] = landmark_validation
        # Debug Mode OFF keeps the landmark results report-only so the existing
        # customer-facing verdict is unchanged; ON makes them authoritative.
        if debug_mode and landmark_validation["overall_status"] == "FAIL":
            overall = "FAIL"
            reason = self._landmark_failure_reason(landmark_validation) or reason
            action = (
                "Open the debug frames for the failing frames and correct the attachment "
                "offset, rotation, or scale that the landmark validation reported."
            )
            report["overall_status"] = overall
            report["reason"] = reason
            report["recommended_action"] = action
        if placement_validation_panel is not None:
            report["placement_validation"] = placement_validation_panel
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

    def _detect_hands(self, raw_frames: list[RawFrame]) -> list[HandLandmarkResult]:
        provider = MediaPipeHandLandmarker(self.settings.resolved_hand_model_path)
        hands: list[HandLandmarkResult] = []
        try:
            for frame in raw_frames:
                from app.cv.image_processing import read_bgr

                image = read_bgr(frame.path)
                hands.append(provider.detect(bgr_to_rgb(image)))
        except HandLandmarkError as exc:
            # Soft-fail hand model issues into empty detections so reports stay usable.
            log_event("HAND_LANDMARKER_UNAVAILABLE", error=str(exc))
            return [
                HandLandmarkResult(hand_detected=False, reason="hand_landmarker_unavailable")
                for _ in raw_frames
            ]
        finally:
            close = getattr(provider, "close", None)
            if close:
                close()
        return hands

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
        validation: FrameValidation | None = None,
    ) -> dict:
        quality = getattr(item, "quality", None)
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
            # Missing jewelry is "not measured", never a fake 0.00 detection score.
            "earring_confidence": (
                float(earring.confidence)
                if earring is not None and earring.x is not None and earring.visible
                else None
            ),
            "normalized_distance": measurement.normalized_distance,
            "dx": measurement.dx,
            "dy": measurement.dy,
            "earlobe": None if earlobe is None else {"x": earlobe.x, "y": earlobe.y},
            "earring_anchor": None if earring is None or earring.x is None else {"x": earring.x, "y": earring.y},
            "zone": None
            if earlobe is None
            else {"ear_width": earlobe.ear_width, "ear_height": earlobe.ear_height},
            "jewelry_category": getattr(quality, "jewelry_category", None),
            "detected_body_parts": list(getattr(quality, "detected_body_parts", []) or []),
            "required_body_parts": list(getattr(quality, "required_body_parts", []) or []),
            "body_confidence": getattr(quality, "body_confidence", None),
            "frame_quality_score": getattr(quality, "quality_score", None),
            "selection_status": getattr(quality, "selection_status", None),
            "rejection_reasons": list(getattr(quality, "rejection_reasons", []) or []),
            "rejection_sources": dict(getattr(quality, "rejection_sources", {}) or {}),
            "jewelry_diagnostics": anchor_diagnostics(item.raw.debug_state),
            "failure_reason": (
                validation.failure_reason
                if validation is not None and validation.failure_reason
                else self._placement_failure_reason(measurement, earring, item.raw.debug_state)
            ),
        }
        if validation is not None:
            payload["landmark_validation"] = validation.to_dict()
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
            body_hint = {
                "earring": "face and ear",
                "necklace": "face and neck",
                "ring": "hand and fingers",
                "bracelet": "hand and wrist",
                "bangle": "hand and wrist",
            }.get(jewelry_type, "required body region")
            return (
                "FAIL",
                f"Insufficient frames for {jewelry_type}. {selected_count} representative frames were selected.",
                f"Ensure the {body_hint} are clearly visible, reduce blur, or lower capture motion.",
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

    def _frame_wears_jewelry(self, frame: SelectedFrame, jewelry_type: str) -> bool:
        image = frame.image_bgr
        if image is None:
            try:
                image = read_bgr(frame.raw.path)
            except (OSError, ValueError):
                image = None
        state = frame.raw.debug_state if isinstance(frame.raw.debug_state, dict) else None
        return frame_wears_jewelry(image, jewelry_type, state)

    @staticmethod
    def _matching_score(payload: dict) -> float:
        """Higher is a closer jewelry-to-body match. Image sharpness is not part of the score."""
        if not payload.get("earlobe_detected") or not payload.get("earring_detected"):
            return 0.0
        distance = payload.get("normalized_distance")
        if not isinstance(distance, (int, float)):
            return 0.0
        closeness = 1.0 / (1.0 + float(distance) * 8.0)
        visibility = min(1.0, float(payload.get("earring_confidence") or 0.0))
        body = min(1.0, float(payload.get("earlobe_confidence") or payload.get("body_confidence") or 0.0))
        return closeness * 0.8 + visibility * 0.1 + body * 0.1

    @staticmethod
    def _rank_placement_frames(payloads: list[dict], top_n: int = 5) -> list[int]:
        """Rank frame numbers from closest tracing-point match to worst. Mutates each payload."""
        grouped: dict[int, dict] = {}
        for payload in payloads:
            number = int(payload.get("frame_number") or 0)
            bucket = grouped.setdefault(
                number,
                {"scores": [], "distances": [], "sides": [], "timestamp_ms": payload.get("timestamp_ms") or 0},
            )
            bucket["scores"].append(TestRunner._matching_score(payload))
            bucket["sides"].append(payload)
            distance = payload.get("normalized_distance")
            if (
                payload.get("earlobe_detected")
                and payload.get("earring_detected")
                and isinstance(distance, (int, float))
            ):
                bucket["distances"].append(float(distance))
        ranked = sorted(
            grouped.items(),
            key=lambda item: (
                0 if item[1]["distances"] and len(item[1]["distances"]) == len(item[1]["sides"]) else 1,
                max(item[1]["distances"]) if item[1]["distances"] else 999.0,
                -(sum(item[1]["scores"]) / len(item[1]["scores"])),
                int(item[1]["timestamp_ms"] or 0),
            ),
        )
        order = [number for number, _bucket in ranked]
        top = set(order[:top_n])
        best = order[0] if order else None
        for number, bucket in grouped.items():
            score = sum(bucket["scores"]) / len(bucket["scores"])
            valid = bool(bucket["distances"]) and len(bucket["distances"]) == len(bucket["sides"])
            rank = order.index(number) + 1
            for payload in bucket["sides"]:
                payload["matching_score"] = round(score, 4)
                payload["placement_accuracy"] = round(score * 100.0, 1)
                payload["placement_rank"] = rank
                payload["best_match"] = number == best
                payload["top_match"] = number in top
                payload["tracing_points_valid"] = valid
        return order

    def _persist_ranking(self, run_id: str, payloads: list[dict], top_numbers: set[int]) -> None:
        from app.models.frame import FrameResult

        with session_scope() as session:
            for payload in payloads:
                result_id = f"{self._frame_id(run_id, payload['frame_number'])}-{payload['side']}"
                row = session.get(FrameResult, result_id)
                if row is None:
                    continue
                row.result_json = json.dumps(payload)
                row.normalized_distance = payload.get("normalized_distance")
                session.add(row)
            for frame in run_repo.frames_for_run(session, run_id):
                frame.selected = frame.frame_number in top_numbers
                session.add(frame)
            session.commit()

    @staticmethod
    def _best_frames(frames: list[SelectedFrame], count: int) -> list[SelectedFrame]:
        ranked = sorted(
            frames,
            key=lambda frame: (
                -(float(getattr(frame.quality, "quality_score", 0.0) or 0.0)),
                -(float(getattr(frame.quality, "body_confidence", 0.0) or 0.0)),
                frame.raw.timestamp_ms,
            ),
        )
        chosen: list[SelectedFrame] = []
        seen: set[int] = set()
        for frame in ranked:
            if frame.raw.index in seen:
                continue
            seen.add(frame.raw.index)
            chosen.append(frame)
            if len(chosen) >= count:
                break
        return chosen

    def _even_frames(frames: list[SelectedFrame], count: int) -> list[SelectedFrame]:
        if len(frames) <= count:
            return list(frames)
        last = len(frames) - 1
        chosen: list[SelectedFrame] = []
        seen: set[int] = set()
        for slot in range(count):
            position = round(slot * last / (count - 1)) if count > 1 else 0
            frame = frames[position]
            if frame.raw.index in seen:
                continue
            seen.add(frame.raw.index)
            chosen.append(frame)
        if len(chosen) < count:
            for frame in frames:
                if frame.raw.index not in seen:
                    chosen.append(frame)
                    seen.add(frame.raw.index)
                if len(chosen) >= count:
                    break
        return chosen

    def _capture_plan(self, output_dir: Path | None) -> dict:
        plan = {
            "minimum_required_frames": self.settings.min_capture_frames,
            "target_frames": self.settings.target_capture_frames,
        }
        if output_dir is None:
            return plan
        path = output_dir / "capture_plan.json"
        if not path.is_file():
            plan["minimum_required_frames"] = None
            return plan
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return plan
        if isinstance(payload, dict):
            plan.update({key: payload[key] for key in ("minimum_required_frames", "target_frames", "blank_dropped") if key in payload})
        return plan

    def _jewelry_lay_seconds(self, output_dir: Path) -> float | None:
        path = output_dir / "jewelry_lay.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        seconds = payload.get("seconds") if isinstance(payload, dict) else None
        if isinstance(seconds, (int, float)):
            return round(float(seconds), 1)
        return None

    def _statistics(
        self,
        captured,
        analyzed,
        selected,
        temporal,
        sides,
        *,
        jewelry_type: str = "earring",
        output_dir: Path | None = None,
    ) -> dict:
        passed = sum(temporal[side].passed_frames for side in sides)
        warnings = sum(temporal[side].warning_frames for side in sides)
        failed = sum(temporal[side].failed_frames for side in sides)
        not_testable = sum(getattr(temporal[side], "not_testable_frames", 0) for side in sides)
        testable = passed + warnings + failed
        rates = [temporal[side].pass_rate for side in sides]
        category = profile_for(jewelry_type)
        body_hits = 0
        for frame in selected:
            quality = getattr(frame, "quality", None)
            if quality and set(category.required_body_parts).issubset(set(quality.detected_body_parts or [])):
                body_hits += 1
        return {
            "frames_captured": captured,
            "frames_analyzed": analyzed,
            "frames_selected": len(selected),
            "frames_passed": passed,
            "frames_warning": warnings,
            "frames_failed": failed,
            "frames_not_testable": not_testable,
            "testable_frames": testable,
            "pass_rate": (passed / testable) if testable else 0.0,
            "pass_percentage": round(100.0 * passed / testable, 1) if testable else 0.0,
            "max_consecutive_failures": max(temporal[side].max_consecutive_failures for side in sides) if sides else 0,
            "side_pass_rates": {side: rates[index] for index, side in enumerate(sides)},
            "jewelry_type": category.jewelry_type,
            "required_body_parts": list(category.required_body_parts),
            "body_parts_detected_frames": body_hits,
            "frames_rejected": max(0, analyzed - len(selected)),
            "frames_usable": analyzed,
            "jewelry_lay_seconds": self._jewelry_lay_seconds(output_dir) if output_dir else None,
            **self._capture_plan(output_dir),
        }

    def _config(self, test: TestDefinition) -> dict:
        jewelry_type = (getattr(test, "jewelry_type", None) or "earring").lower()
        pass_threshold = test.pass_threshold
        fail_threshold = test.fail_threshold
        # Earring / necklace default to Euclidean bands from the placement spec.
        if jewelry_type in {"earring", "necklace"}:
            if pass_threshold is None or pass_threshold >= 0.08:
                pass_threshold = EUCLIDEAN_PASS
            if fail_threshold is None or fail_threshold >= 0.12:
                fail_threshold = EUCLIDEAN_WARNING
        return {
            "minimum_confidence": test.minimum_confidence,
            "pass_threshold": pass_threshold,
            "fail_threshold": fail_threshold,
            "minimum_pass_rate": test.minimum_pass_rate,
            "maximum_consecutive_failures": test.maximum_consecutive_failures,
            "zone_y_scale": test.zone_y_scale,
            "min_selected_frames": test.min_selected_frames,
            "max_selected_frames": test.max_selected_frames,
            "selected_finger": getattr(test, "selected_finger", None) or "ring",
        }

    @staticmethod
    def _write_frame_landmarks(output_dir, item, jewelry_type: str, selected_finger: str, sides) -> None:
        """Persist the runtime landmarks so the UI can draw the real mesh, not a stand-in."""
        from app.cv.debug_landmarks import contour_indices, selected_landmark_index, uses_hand_landmarks

        face = getattr(item, "face", None)
        hand = getattr(item, "hand", None)
        payload: dict = {
            "frame_number": item.raw.index,
            "jewelry_type": jewelry_type,
            "uses_hand_landmarks": uses_hand_landmarks(jewelry_type),
            "face": [],
            "hand": [],
            "contours": {},
            "selected_landmarks": {},
        }
        if face is not None and face.face_detected and face.landmarks:
            payload["face"] = [[round(p.x, 5), round(p.y, 5)] for p in face.landmarks]
        if hand is not None and getattr(hand, "hand_detected", False) and hand.landmarks:
            payload["hand"] = [[round(p.x, 5), round(p.y, 5)] for p in hand.landmarks]
        for side in sides:
            contour = contour_indices(jewelry_type, side)
            if contour:
                payload["contours"][side] = list(contour)
            index = selected_landmark_index(jewelry_type, side, selected_finger)
            if index is not None:
                payload["selected_landmarks"][side] = index
        path = output_dir / "landmarks" / f"frame_{item.raw.index:04d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")

    @staticmethod
    def _debug_overrides(test: TestDefinition) -> dict | None:
        raw = getattr(test, "debug_options_json", None)
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _landmark_failure_reason(landmark_validation: dict) -> str | None:
        for side, summary in (landmark_validation.get("sides") or {}).items():
            if summary.get("overall_status") != "FAIL":
                continue
            for name, check in (summary.get("checks") or {}).items():
                if check.get("status") == "FAIL":
                    return f"[{summary.get('failure_reason')}] {side}: {check.get('detail')}"
        return None

    @staticmethod
    def _placement_failure_reason(measurement: PlacementMeasurement, earring, debug_state) -> str | None:
        """Map a frame measurement onto an explicit failure code for the UI."""
        from app.cv.landmark_validation import (
            ATTACHMENT_ANCHOR_MISSING,
            LANDMARK_NOT_DETECTED,
            NORMALIZED_DISTANCE_EXCEEDED,
            reason_for_missing_anchor,
        )

        if measurement.status not in {"FAIL", "NOT_TESTABLE"}:
            return None
        if measurement.earlobe_confidence == 0 and "missing" in (measurement.reason or "").lower():
            return LANDMARK_NOT_DETECTED
        if earring is None or earring.x is None or not earring.visible:
            return reason_for_missing_anchor(anchor_diagnostics(debug_state if isinstance(debug_state, dict) else None))
        if measurement.normalized_distance is not None:
            return NORMALIZED_DISTANCE_EXCEEDED
        return ATTACHMENT_ANCHOR_MISSING

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
                f"{side} body misses {missing_earlobe[side]}/{selected_count}, "
                f"jewelry misses {missing_earring[side]}/{selected_count}."
            )
        return " ".join(parts)

    def _rejection_summary(self, evaluated: list[SelectedFrame]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for frame in evaluated:
            for reason in frame.quality.rejection_reasons:
                counts[reason] = counts.get(reason, 0) + 1
        return counts

    @staticmethod
    def _rejection_sources(evaluated: list[SelectedFrame]) -> dict[str, dict[str, int]]:
        """Rejections grouped by the stage that produced them.

        Frames dropped by duplicate filtering or candidate selection are skipped,
        not failed, so they are never counted as placement failures.
        """
        from app.services.frame_selector import rejection_source

        grouped: dict[str, dict[str, int]] = {}
        for frame in evaluated:
            sources = getattr(frame.quality, "rejection_sources", {}) or {}
            for reason in frame.quality.rejection_reasons:
                stage = sources.get(reason) or rejection_source(reason)
                bucket = grouped.setdefault(stage, {})
                bucket[reason] = bucket.get(reason, 0) + 1
        return grouped

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
