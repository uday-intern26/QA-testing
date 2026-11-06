from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.api.dependencies import get_app_settings, get_db
from app.core.config import Settings
from app.db.database import allocate_id
from app.db.repositories import runs as run_repo
from app.models.reference import ReferenceImage
from app.models.test import TestDefinition
from app.schemas.test import TestCreate, TestRead
from app.services.application_service import ApplicationService
from app.utils.validators import assert_thresholds

router = APIRouter(prefix="/tests", tags=["tests"])


@router.get("", response_model=list[TestRead])
def list_tests(session: Session = Depends(get_db)) -> list[TestRead]:
    return [TestRead.model_validate(item, from_attributes=True) for item in run_repo.list_tests(session)]


@router.post("", response_model=TestRead, status_code=201)
def create_test(
    payload: TestCreate,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> TestRead:
    try:
        assert_thresholds(payload.pass_threshold, payload.fail_threshold, payload.minimum_pass_rate)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_THRESHOLDS", "message": str(exc)}) from exc
    if payload.max_selected_frames < payload.min_selected_frames:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_THRESHOLDS", "message": "Max selected frames must be at least the minimum."},
        )
    if ApplicationService().get(session, payload.application_id) is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    if payload.reference_id and session.get(ReferenceImage, payload.reference_id) is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Reference was not found."})
    record = TestDefinition(
        id=allocate_id(session, "TEST", TestDefinition),
        **payload.model_dump(),
    )
    if record.capture_fps == 0:
        record.capture_fps = settings.default_capture_fps
    session.add(record)
    session.commit()
    session.refresh(record)
    return TestRead.model_validate(record, from_attributes=True)


@router.get("/{test_id}", response_model=TestRead)
def get_test(test_id: str, session: Session = Depends(get_db)) -> TestRead:
    record = run_repo.get_test(session, test_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Test was not found."})
    return TestRead.model_validate(record, from_attributes=True)


@router.delete("/{test_id}", status_code=204)
def delete_test(
    test_id: str,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> None:
    record = run_repo.get_test(session, test_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Test was not found."})
    run_repo.delete_test(session, record, data_dir=settings.data_dir)
