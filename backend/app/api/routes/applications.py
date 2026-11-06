from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.api.dependencies import get_app_settings, get_db
from app.core.config import Settings
from app.schemas.application import (
    ApplicationCreate,
    ApplicationRead,
    ApplicationUpdate,
    ApplicationValidateRequest,
    ApplicationValidateResponse,
    CatalogRequest,
    CatalogResponse,
    TryOnForm,
)
from app.services.application_service import ApplicationService
from app.services.browser_service import BrowserService
from app.utils.files import ensure_within_data, is_public_id

router = APIRouter(prefix="/applications", tags=["applications"])


@router.get("", response_model=list[ApplicationRead])
def list_applications(session: Session = Depends(get_db)) -> list[ApplicationRead]:
    return [ApplicationRead.model_validate(item, from_attributes=True) for item in ApplicationService().list(session)]


@router.get("/form", response_model=TryOnForm)
def blank_tryon_form() -> TryOnForm:
    """The try-on name and link start empty. A saved application is used only after it is chosen."""
    return TryOnForm()


@router.post("", response_model=ApplicationRead, status_code=201)
def create_application(payload: ApplicationCreate, session: Session = Depends(get_db)) -> ApplicationRead:
    try:
        record = ApplicationService().create(session, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_APPLICATION", "message": str(exc)}) from exc
    return ApplicationRead.model_validate(record, from_attributes=True)


@router.post("/catalog", response_model=CatalogResponse)
async def list_tryon_catalog(
    payload: CatalogRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> CatalogResponse:
    """Return jewelry on a try-on URL, grouped as earrings, necklaces, bangles, rings, and bracelets."""
    application = ApplicationService().get(session, payload.application_id) if payload.application_id else None
    if payload.application_id and application is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    return await BrowserService(settings).list_catalog(
        url=payload.url,
        username=payload.username,
        password=payload.password,
        video_path=application.video_path if application else None,
    )


@router.post("/validate", response_model=ApplicationValidateResponse)
async def validate_application(
    payload: ApplicationValidateRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ApplicationValidateResponse:
    service = ApplicationService()
    application = service.get(session, payload.application_id) if payload.application_id else None
    if payload.application_id and application is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    if application is not None:
        if payload.name and payload.name.strip():
            application.name = payload.name.strip()
            application.updated_at = datetime.now(timezone.utc)
            session.add(application)
            session.commit()
            session.refresh(application)
        service.remember_url(application.id, payload.url)
    screenshot_dir = settings.data_dir / "applications" / "validation"
    result = await BrowserService(settings).validate(
        url=payload.url,
        username=payload.username,
        password=payload.password,
        username_selector=payload.username_selector or (application.username_selector if application else None),
        password_selector=payload.password_selector or (application.password_selector if application else None),
        submit_selector=payload.submit_selector or (application.submit_selector if application else None),
        ready_selector=payload.ready_selector or (application.ready_selector if application else None),
        screenshot_dir=screenshot_dir,
        video_path=application.video_path if application else None,
    )
    screenshot_url = None
    if result.screenshot_url:
        shot = Path(result.screenshot_url)
        screenshot_url = f"{settings.api_prefix}/applications/validation-screenshots/{shot.name}"
        result.screenshot_url = screenshot_url
    if application is not None:
        service.mark_validation(
            session,
            application,
            status=result.status,
            message=result.message,
            screenshot=str(Path(screenshot_dir / Path(screenshot_url).name)) if screenshot_url else None,
        )
        if result.status == "success":
            application = service.save_passed_url(
                session,
                application,
                payload.url,
                payload.username,
                name=payload.name or application.name,
            )
        result.application_id = application.id
    return result


@router.get("/validation-screenshots/{filename}")
def validation_screenshot(filename: str, settings: Settings = Depends(get_app_settings)) -> FileResponse:
    path = ensure_within_data(settings.data_dir / "applications" / "validation" / Path(filename).name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Screenshot was not found."})
    return FileResponse(path)


@router.post("/{application_id}/face-video", response_model=ApplicationRead)
async def upload_face_video(
    application_id: str,
    file: UploadFile = File(...),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> ApplicationRead:
    if not is_public_id(application_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    service = ApplicationService()
    record = service.get(session, application_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    content = await file.read()
    try:
        record = service.attach_face_video(
            session,
            record,
            filename=file.filename or "bare-face.mp4",
            content=content,
            captures_dir=settings.data_dir / "captures",
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_FACE_VIDEO", "message": str(exc)}) from exc
    return ApplicationRead.model_validate(record, from_attributes=True)


@router.patch("/{application_id}", response_model=ApplicationRead)
def update_application(
    application_id: str,
    payload: ApplicationUpdate,
    session: Session = Depends(get_db),
) -> ApplicationRead:
    if not is_public_id(application_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    service = ApplicationService()
    record = service.get(session, application_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    try:
        record = service.update_target(session, record, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "INVALID_APPLICATION", "message": str(exc)}) from exc
    return ApplicationRead.model_validate(record, from_attributes=True)


@router.get("/{application_id}", response_model=ApplicationRead)
def get_application(application_id: str, session: Session = Depends(get_db)) -> ApplicationRead:
    if not is_public_id(application_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    record = ApplicationService().get(session, application_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    return ApplicationRead.model_validate(record, from_attributes=True)


@router.delete("/{application_id}", status_code=204)
def delete_application(
    application_id: str,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_app_settings),
) -> None:
    if not is_public_id(application_id):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    service = ApplicationService()
    record = service.get(session, application_id)
    if record is None:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application was not found."})
    service.delete(session, record, data_dir=settings.data_dir)
