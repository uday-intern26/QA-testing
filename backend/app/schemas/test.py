from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class TestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    application_id: str
    reference_id: str | None = None
    jewelry_id: str | None = None
    jewelry_type: Literal["earring", "necklace", "bracelet", "ring", "bangle"] = "earring"
    ear_side: Literal["left", "right", "both"] = "left"
    selected_finger: Literal["thumb", "index", "middle", "ring", "little"] | None = "ring"
    capture_fps: Literal[1, 2, 5, 10] = 5
    capture_duration_seconds: float = Field(default=6, ge=1, le=60)
    minimum_confidence: float = Field(default=0.80, ge=0, le=1)
    pass_threshold: float = Field(default=0.10, ge=0, le=2)
    fail_threshold: float = Field(default=0.15, ge=0, le=2)
    minimum_pass_rate: float = Field(default=0.95, ge=0, le=1)
    maximum_consecutive_failures: int = Field(default=2, ge=0, le=100)
    zone_y_scale: float = Field(default=1.0, gt=0, le=3)
    min_selected_frames: int = Field(default=5, ge=1, le=200)
    max_selected_frames: int = Field(default=30, ge=1, le=300)


class TestRead(TestCreate):
    id: str
    created_at: datetime


class TestRunRequest(BaseModel):
    username: str | None = None
    password: str | None = None
    capture_duration_seconds: float | None = Field(default=None, ge=1, le=60)


class TestRunAccepted(BaseModel):
    test_id: str
    test_run_id: str
    status: str


class StepStatus(BaseModel):
    name: str
    status: str
    detail: str = ""


class TestStatusRead(BaseModel):
    test_id: str
    test_run_id: str | None
    status: str
    progress: float
    stage: str
    stage_message: str
    overall_status: str | None = None
    steps: list[StepStatus] = []
    error: str | None = None
    reason: str | None = None
    recommended_action: str | None = None
    preview_image_url: str | None = None


class ManualReviewRequest(BaseModel):
    manual_result: Literal["PASS", "WARNING", "FAIL"]
    reviewer: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=3, max_length=500)
    side: Literal["left", "right"] | None = None
