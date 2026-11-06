from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


ApplicationType = Literal["web", "desktop", "video"]


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    type: ApplicationType = "web"
    url: str | None = None
    executable_path: str | None = None
    video_path: str | None = None
    anchor_file: str | None = None
    username: str | None = None
    username_selector: str | None = None
    password_selector: str | None = None
    submit_selector: str | None = None
    ready_selector: str | None = None


class ApplicationRead(BaseModel):
    id: str
    name: str
    type: str
    url: str | None
    executable_path: str | None
    video_path: str | None
    anchor_file: str | None
    username: str | None
    username_selector: str | None
    password_selector: str | None
    submit_selector: str | None
    ready_selector: str | None
    last_validation_status: str | None
    last_validation_message: str | None
    validation_screenshot: str | None
    created_at: datetime
    updated_at: datetime


class ApplicationUpdate(BaseModel):
    url: str | None = None
    username: str | None = None


class TryOnForm(BaseModel):
    """Blank try-on form. Saved applications are not copied into these fields."""

    name: str = ""
    url: str = ""
    username: str = ""


class ApplicationValidateRequest(BaseModel):
    url: str
    name: str | None = None
    username: str = ""
    password: str = ""
    type: ApplicationType = "web"
    application_id: str | None = None
    username_selector: str | None = None
    password_selector: str | None = None
    submit_selector: str | None = None
    ready_selector: str | None = None


class CheckItem(BaseModel):
    name: str
    ok: bool
    detail: str


class CatalogCategory(BaseModel):
    category: str
    items: list[str] = []


class CatalogRequest(BaseModel):
    url: str
    username: str = ""
    password: str = ""
    application_id: str | None = None


class CatalogResponse(BaseModel):
    url: str
    categories: list[CatalogCategory] = []
    message: str = ""


class ApplicationValidateResponse(BaseModel):
    status: Literal["success", "failed"]
    reachable: bool
    login_successful: bool
    application_loaded: bool
    message: str
    checks: list[CheckItem]
    screenshot_url: str | None = None
    application_id: str | None = None
    jewelry: list[str] = []
    catalog: list[CatalogCategory] = []


class TargetDescriptor(BaseModel):
    """Application target. Desktop path is accepted and rejected at execution time."""

    type: ApplicationType
    url: HttpUrl | None = None
    path: str | None = None
