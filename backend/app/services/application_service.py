"""Application records. Passwords are never written to the database."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from app.db.database import allocate_id
from app.models.application import Application
from app.schemas.application import ApplicationCreate, ApplicationUpdate


class ApplicationService:
    # The link used for the current validation. It is written to the application after the test.
    validated_urls: dict[str, str] = {}

    def remember_url(self, application_id: str, url: str) -> None:
        self.validated_urls[application_id] = url.strip()

    def create(self, session: Session, payload: ApplicationCreate) -> Application:
        self._validate_target(payload)
        record = Application(
            id=allocate_id(session, "APP", Application),
            name=payload.name.strip(),
            type=payload.type,
            url=payload.url,
            executable_path=payload.executable_path,
            video_path=payload.video_path,
            anchor_file=payload.anchor_file,
            username=payload.username,
            username_selector=payload.username_selector,
            password_selector=payload.password_selector,
            submit_selector=payload.submit_selector,
            ready_selector=payload.ready_selector,
        )
        session.add(record)
        session.commit()
        session.refresh(record)
        return record

    def list(self, session: Session) -> list[Application]:
        return list(session.exec(select(Application).order_by(Application.created_at.desc())).all())

    def get(self, session: Session, application_id: str) -> Application | None:
        return session.get(Application, application_id)

    def update_target(self, session: Session, application: Application, payload: ApplicationUpdate) -> Application:
        if payload.username is not None:
            application.username = payload.username.strip() or None
        application.updated_at = datetime.now(timezone.utc)
        session.add(application)
        session.commit()
        session.refresh(application)
        return application

    def attach_face_video(
        self,
        session: Session,
        application: Application,
        *,
        filename: str,
        content: bytes,
        captures_dir: Path,
    ) -> Application:
        if application.type != "web":
            raise ValueError("Upload the bare-ear face video on the try-on URL application.")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".mp4", ".webm", ".mov"}:
            raise ValueError("Upload an mp4, webm, or mov of a person wearing no earrings.")
        if not content:
            raise ValueError("The face video file is empty.")
        captures_dir.mkdir(parents=True, exist_ok=True)
        for existing in captures_dir.iterdir():
            if existing.is_file() and existing.suffix.lower() in {".mp4", ".webm", ".mov", ".y4m", ".avi"}:
                existing.unlink()
        destination = captures_dir / "bare-face.mp4"
        destination.write_bytes(content)
        application.video_path = str(destination)
        application.updated_at = datetime.now(timezone.utc)
        session.add(application)
        session.commit()
        session.refresh(application)
        return application

    def save_passed_url(
        self,
        session: Session,
        application: Application,
        url: str,
        username: str | None,
        name: str | None = None,
    ) -> Application:
        """Store the try-on link under the name entered for this test."""
        url = url.strip()
        given_name = (name or application.name).strip()
        existing = session.exec(select(Application).where(Application.url == url)).first()
        if existing is not None:
            target = existing
        elif not application.url:
            target = application
        else:
            target = Application(
                id=allocate_id(session, "APP", Application),
                name=given_name,
                type=application.type,
                url=url,
                video_path=application.video_path,
                username=username.strip() if username else application.username,
                username_selector=application.username_selector,
                password_selector=application.password_selector,
                submit_selector=application.submit_selector,
                ready_selector=application.ready_selector,
            )
        target.url = url
        if given_name:
            target.name = given_name
        if username and username.strip():
            target.username = username.strip()
        target.updated_at = datetime.now(timezone.utc)
        session.add(target)
        session.commit()
        session.refresh(target)
        return target

    def save_tested_application(self, session: Session, application_id: str) -> Application | None:
        """After a placement test, keep the try-on link with the name that was entered."""
        application = self.get(session, application_id)
        if application is None or application.type != "web":
            return None
        url = self.validated_urls.get(application.id) or application.url or ""
        if not url.strip():
            return None
        return self.save_passed_url(session, application, url, application.username, name=application.name)

    def mark_validation(
        self,
        session: Session,
        application: Application,
        *,
        status: str,
        message: str,
        screenshot: str | None,
    ) -> Application:
        application.last_validation_status = status
        application.last_validation_message = message
        application.validation_screenshot = screenshot
        application.updated_at = datetime.now(timezone.utc)
        session.add(application)
        session.commit()
        session.refresh(application)
        return application

    def delete(self, session: Session, application: Application, data_dir: Path | None = None) -> None:
        """Delete an application and cascade its tests and runs."""
        from app.db.repositories import runs as run_repo

        for test in run_repo.tests_for_application(session, application.id):
            run_repo.delete_test(session, test, data_dir=data_dir)
        screenshot = application.validation_screenshot
        session.delete(application)
        session.commit()
        self.validated_urls.pop(application.id, None)
        if screenshot:
            path = Path(screenshot)
            if path.is_file():
                path.unlink(missing_ok=True)

    def _validate_target(self, payload: ApplicationCreate) -> None:
        if payload.type == "web" and not payload.url:
            raise ValueError("A web application requires a URL.")
        if payload.type == "video" and not payload.video_path:
            raise ValueError("A video/file application requires a video path.")
        if payload.type == "desktop" and not payload.executable_path:
            raise ValueError("A desktop application requires an executable path.")
