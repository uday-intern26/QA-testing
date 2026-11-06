import json
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.dependencies import get_app_settings, get_db
from app.core.config import Settings
from app.db.repositories import runs as run_repo
from app.schemas.test import StepStatus, TestRunAccepted, TestRunRequest, TestStatusRead
from app.services.test_runner import TestRunner, initial_steps

router = APIRouter(prefix="/tests", tags=["execution"])


@router.post("/{test_id}/run", response_model=TestRunAccepted, status_code=202)
async def run_test(
    test_id: str,
    payload: TestRunRequest,
    background: BackgroundTasks,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> TestRunAccepted:
    test = run_repo.get_test(session, test_id)
    if test is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Test was not found."})
    from app.models.application import Application

    application = session.get(Application, test.application_id)
    if application is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    active = run_repo.latest_run(session, test_id)
    if active and active.status in {"pending", "running"}:
        raise HTTPException(
            status_code=409,
            detail={"code": "RUN_IN_PROGRESS", "message": "This test already has a run in progress."},
        )
    run = run_repo.create_run(session, test_id, initial_steps())
    username = payload.username if payload.username is not None else application.username
    runner = TestRunner(settings)
    background.add_task(runner.execute, run.id, username, payload.password)
    return TestRunAccepted(test_id=test_id, test_run_id=run.id, status=run.status)


@router.get("/{test_id}/live-preview")
def live_preview(
    test_id: str,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> FileResponse:
    if run_repo.get_test(session, test_id) is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Test was not found."})
    run = run_repo.latest_run(session, test_id)
    path = Path(settings.data_dir) / "results" / (run.id if run else "") / "live_preview.png"
    if run is None or not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Live jewelry preview is not ready."})
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/{test_id}/status", response_model=TestStatusRead)
def test_status(
    test_id: str,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> TestStatusRead:
    if run_repo.get_test(session, test_id) is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Test was not found."})
    run = run_repo.latest_run(session, test_id)
    if run is None:
        return TestStatusRead(
            test_id=test_id,
            test_run_id=None,
            status="not_run",
            progress=0,
            stage="not_run",
            stage_message="This test has not been run.",
            steps=[],
        )
    steps = [StepStatus.model_validate(item) for item in json.loads(run.steps_json or "[]")]
    preview = Path(settings.data_dir) / "results" / run.id / "live_preview.png"
    return TestStatusRead(
        test_id=test_id,
        test_run_id=run.id,
        status=run.status,
        progress=run.progress,
        stage=run.stage,
        stage_message=run.stage_message,
        overall_status=run.overall_status,
        steps=steps,
        error=run.error,
        reason=run.reason,
        recommended_action=run.recommended_action,
        preview_image_url=(
            f"{settings.api_prefix}/tests/{test_id}/live-preview" if preview.is_file() else None
        ),
    )
