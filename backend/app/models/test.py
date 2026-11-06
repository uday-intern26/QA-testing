from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.application import utcnow


class TestDefinition(SQLModel, table=True):
    __test__ = False
    __tablename__ = "tests"

    id: str = Field(primary_key=True)
    name: str
    application_id: str = Field(index=True, foreign_key="applications.id")
    reference_id: str | None = Field(default=None, foreign_key="references.id")
    jewelry_id: str | None = None
    jewelry_type: str = "earring"
    ear_side: str = "left"
    selected_finger: str | None = "ring"
    capture_fps: int = 5
    capture_duration_seconds: float = 6.0
    minimum_confidence: float = 0.80
    pass_threshold: float = 0.10
    fail_threshold: float = 0.15
    minimum_pass_rate: float = 0.95
    maximum_consecutive_failures: int = 2
    zone_y_scale: float = 1.0
    min_selected_frames: int = 5
    max_selected_frames: int = 30
    created_at: datetime = Field(default_factory=utcnow)
