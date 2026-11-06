import json
from pathlib import Path

import cv2
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlmodel import Session, select

from app.api.dependencies import get_app_settings, get_db
from app.core.config import Settings
from app.cv.visualization import composite_catalog_earring, draw_placed_earring
from app.db.repositories import runs as run_repo
from app.models.application import Application
from app.models.frame import FrameResult
from app.models.result import TestRun
from app.schemas.result import DashboardSummary, FramePlacement
from app.schemas.test import ManualReviewRequest
from app.utils.files import ensure_within_data

router = APIRouter(tags=["results"])


def _latest(session: Session, test_id: str) -> TestRun:
    if run_repo.get_test(session, test_id) is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Test was not found."})
    run = run_repo.latest_run(session, test_id)
    if run is None or not run.report_json:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "No results are available yet."})
    return run


def _frame_view(session: Session, test_id: str, frame: FrameResult, settings: Settings) -> dict:
    payload = json.loads(frame.result_json)
    record = run_repo.get_frame(session, frame.frame_id)
    image_url = f"{settings.api_prefix}/tests/{test_id}/frames/{frame.frame_id}/image"
    annotated_url = None
    if record and record.annotated_path:
        annotated_url = f"{image_url}?variant=annotated"
    placement = payload.get("placement") or {}
    return {
        "frame_id": frame.frame_id,
        "frame_number": payload.get("frame_number"),
        "timestamp_ms": payload.get("timestamp_ms"),
        "side": frame.side,
        "earlobe_detected": payload.get("earlobe_detected", False),
        "earring_detected": payload.get("earring_detected", False),
        "earlobe": (payload.get("ear") or {}).get("anchor") if payload.get("ear") else payload.get("earlobe"),
        "earring": (payload.get("earring") or {}).get("anchor") if payload.get("earring") else payload.get("earring_anchor"),
        "earlobe_confidence": payload.get("earlobe_confidence"),
        "earring_confidence": payload.get("earring_confidence"),
        "dx": placement.get("dx", payload.get("dx")),
        "dy": placement.get("dy", payload.get("dy")),
        "normalized_distance": frame.normalized_distance,
        "status": frame.status,
        "reason": placement.get("reason") or payload.get("reason"),
        "automated_result": frame.automated_result,
        "manual_result": frame.manual_result,
        "reviewer": frame.reviewer,
        "review_reason": frame.review_reason,
        "image_url": image_url,
        "annotated_image_url": annotated_url,
        "zone": payload.get("zone"),
        "earring_source": (payload.get("earring") or {}).get("source"),
    }


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(session: Session = Depends(get_db)) -> DashboardSummary:
    tests = run_repo.list_tests(session)
    runs = run_repo.list_runs(session, limit=200)
    finished = [run for run in runs if run.overall_status in {"PASS", "FAIL", "WARNING"}]
    passed = sum(1 for run in finished if run.overall_status == "PASS")
    failed = sum(1 for run in finished if run.overall_status == "FAIL")
    warnings = sum(1 for run in finished if run.overall_status == "WARNING")
    rates = []
    for run in finished:
        if run.statistics_json:
            stats = json.loads(run.statistics_json)
            if stats.get("pass_rate") is not None:
                rates.append(float(stats["pass_rate"]))
    latest = finished[0] if finished else None
    latest_failure = next((run for run in finished if run.overall_status == "FAIL"), None)

    def brief(run: TestRun | None) -> dict | None:
        if run is None:
            return None
        test = run_repo.get_test(session, run.test_id)
        return {
            "test_run_id": run.id,
            "test_id": run.test_id,
            "test_name": test.name if test else run.test_id,
            "overall_status": run.overall_status,
            "reason": run.reason,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }

    return DashboardSummary(
        total_tests=len(tests),
        passed=passed,
        failed=failed,
        warnings=warnings,
        latest_test=brief(latest),
        latest_failure=brief(latest_failure),
        average_pass_rate=(sum(rates) / len(rates)) if rates else None,
    )


@router.get("/runs")
def list_runs(session: Session = Depends(get_db)) -> list[dict]:
    payload = []
    for run in run_repo.list_runs(session):
        test = run_repo.get_test(session, run.test_id)
        payload.append(
            {
                "test_run_id": run.id,
                "test_id": run.test_id,
                "test_name": test.name if test else run.test_id,
                "status": run.status,
                "overall_status": run.overall_status,
                "progress": run.progress,
                "stage_message": run.stage_message,
                "created_at": run.created_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
        )
    return payload


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(
    run_id: str,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> None:
    run = run_repo.get_run(session, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Run was not found."})
    run_repo.delete_run(session, run, data_dir=settings.data_dir)


@router.delete("/history", status_code=200)
def clear_history(
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    """Delete all test runs, results, and reports. Applications and test configs are kept."""
    deleted = run_repo.delete_all_runs(session, data_dir=settings.data_dir)
    return {"deleted_runs": deleted}


@router.get("/tests/{test_id}/results")
def test_results(
    test_id: str,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    run = _latest(session, test_id)
    report = json.loads(run.report_json or "{}")
    test = run_repo.get_test(session, test_id)
    application = session.get(Application, test.application_id) if test else None
    frames = []
    for result in run_repo.results_for_run(session, run.id):
        frames.append(_frame_view(session, test_id, result, settings))
    frames.sort(key=lambda item: (item["frame_number"], item["side"]))
    report["frames"] = frames
    report["application"] = None
    if application is not None:
        report["application"] = {
            "id": application.id,
            "name": application.name,
            "type": application.type,
            "url": application.url,
        }
    report["thresholds"] = report.get("thresholds") or {}
    return report


@router.get("/tests/{test_id}/frames/{frame_id}")
def frame_detail(
    test_id: str,
    frame_id: str,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> dict:
    run = _latest(session, test_id)
    frame = run_repo.get_frame(session, frame_id)
    if frame is None or frame.test_run_id != run.id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Frame was not found."})
    quality = json.loads(frame.quality_json or "{}")
    results = [_frame_view(session, test_id, item, settings) for item in run_repo.results_for_frame(session, frame_id)]
    return {
        "frame_id": frame.id,
        "frame_number": frame.frame_number,
        "timestamp_ms": frame.timestamp_ms,
        "selected": frame.selected,
        "rejected": frame.rejected,
        "rejection_reasons": json.loads(frame.rejection_reasons or "[]"),
        "quality": quality,
        "image_url": f"{settings.api_prefix}/tests/{test_id}/frames/{frame.id}/image",
        "annotated_image_url": (
            f"{settings.api_prefix}/tests/{test_id}/frames/{frame.id}/image?variant=annotated"
            if frame.annotated_path
            else None
        ),
        "results": results,
    }


@router.get("/tests/{test_id}/frames/{frame_id}/image")
def frame_image(
    test_id: str,
    frame_id: str,
    variant: str = "original",
    session: Session = Depends(get_db),
) -> FileResponse:
    run = _latest(session, test_id)
    frame = run_repo.get_frame(session, frame_id)
    if frame is None or frame.test_run_id != run.id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Frame was not found."})
    raw = frame.annotated_path if variant == "annotated" and frame.annotated_path else frame.path
    path = ensure_within_data(Path(raw))
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Frame image is missing."})
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        return FileResponse(path)
    for item in run_repo.results_for_frame(session, frame_id):
        payload = json.loads(item.result_json or "{}")
        anchor = (payload.get("earring") or {}).get("anchor") or payload.get("earring_anchor")
        if not anchor or anchor.get("x") is None or anchor.get("y") is None:
            continue
        zone = payload.get("zone") or {}
        ear = payload.get("ear") or {}
        ear_width = zone.get("ear_width") or ear.get("ear_width")
        sprite = Path(frame.path).resolve().parent.parent / "selected_earring.png"
        if sprite.is_file():
            image = composite_catalog_earring(image, sprite, float(anchor["x"]), float(anchor["y"]), ear_width)
        else:
            image = draw_placed_earring(image, float(anchor["x"]), float(anchor["y"]), ear_width)
    encoded, buffer = cv2.imencode(".png", image)
    if not encoded:
        return FileResponse(path)
    return Response(content=buffer.tobytes(), media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/tests/{test_id}/frames/{frame_id}/review")
def review_frame(
    test_id: str,
    frame_id: str,
    payload: ManualReviewRequest,
    session: Session = Depends(get_db),
) -> dict:
    run = _latest(session, test_id)
    frame = run_repo.get_frame(session, frame_id)
    if frame is None or frame.test_run_id != run.id:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Frame was not found."})
    statement = select(FrameResult).where(FrameResult.frame_id == frame_id)
    results = list(session.exec(statement).all())
    if payload.side:
        results = [item for item in results if item.side == payload.side]
    if not results:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Frame result was not found."})
    for result in results:
        result.manual_result = payload.manual_result
        result.reviewer = payload.reviewer
        result.review_reason = payload.reason
        session.add(result)
    session.commit()
    return {
        "frame_id": frame_id,
        "automated_result": results[0].automated_result,
        "manual_result": payload.manual_result,
        "reviewer": payload.reviewer,
        "reason": payload.reason,
        "note": "The automated result is unchanged.",
    }


@router.get("/tests/{test_id}/report")
def download_report(test_id: str, session: Session = Depends(get_db)) -> FileResponse:
    run = _latest(session, test_id)
    if not run.report_json:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Report was not found."})
    report = json.loads(run.report_json)
    path = None
    from app.models.result import ReportRow

    row = session.exec(select(ReportRow).where(ReportRow.test_run_id == run.id)).first()
    if row is not None:
        path = ensure_within_data(Path(row.path))
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Report file is missing."})
    del report
    return FileResponse(path, media_type="application/json", filename=f"{run.id}-report.json")


@router.get("/settings")
def settings_view(settings: Settings = Depends(get_app_settings)) -> dict:
    return {
        "default_capture_fps": settings.default_capture_fps,
        "default_min_confidence": settings.default_min_confidence,
        "default_pass_threshold": settings.default_pass_threshold,
        "default_fail_threshold": settings.default_fail_threshold,
        "default_min_pass_rate": settings.default_min_pass_rate,
        "default_max_consecutive_failures": settings.default_max_consecutive_failures,
        "applitools_enabled": settings.applitools_enabled,
        "applitools_configured": bool(settings.applitools_api_key),
        "face_model_present": settings.resolved_face_model_path.is_file(),
        "overlay": {
            "earlobe": settings.overlay_earlobe_color,
            "earring": settings.overlay_earring_color,
            "zone": settings.overlay_zone_color,
            "vector": settings.overlay_vector_color,
        },
    }
