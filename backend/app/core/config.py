"""Runtime configuration. Thresholds come from the environment, not source literals in validators."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    app_name: str = "AIJewel Earring QA"
    api_prefix: str = "/api/v1"
    backend_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:3010,http://127.0.0.1:3010"
    )

    data_dir: Path = Path("data")
    database_url: str = "sqlite:///./data/qa.sqlite3"
    face_model_path: Path = Path("models/face_landmarker.task")

    applitools_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("APPLITOOLS_ENABLED", "applitools_enabled", "applitoools_enabled"),
    )
    applitools_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("APPLITOOLS_API_KEY", "applitools_api_key", "applitoools_api_key"),
    )
    applitools_server_url: str = Field(
        default="",
        validation_alias=AliasChoices("APPLITOOLS_SERVER_URL", "applitools_server_url", "applitoools_server_url"),
    )

    default_capture_fps: int = 5
    default_min_confidence: float = 0.80
    default_pass_threshold: float = 0.10
    default_fail_threshold: float = 0.15
    default_min_pass_rate: float = 0.95
    default_max_consecutive_failures: int = 2
    default_capture_duration_seconds: float = 6.0
    default_min_selected_frames: int = 5
    default_max_selected_frames: int = 30
    default_zone_y_scale: float = 1.0

    min_blur_variance: float = 12.0
    blur_norm_variance: float = 120.0
    duplicate_hash_distance: int = 4
    head_pose_max_delta_deg: float = 18.0
    head_pose_max_yaw_deg: float = 55.0
    min_ear_width: float = 0.012

    playwright_headless: bool = False
    viewport_width: int = 1280
    viewport_height: int = 720
    navigation_timeout_ms: int = 45000

    overlay_earlobe_color: str = "#22c55e"
    overlay_earring_color: str = "#ef4444"
    overlay_zone_color: str = "#eab308"
    overlay_pass_zone_color: str = "#38bdf8"
    overlay_vector_color: str = "#f8fafc"

    log_level: str = "INFO"
    max_upload_bytes: int = 25 * 1024 * 1024

    def ensure_dirs(self) -> None:
        root = self.data_dir
        for name in ("applications", "references", "captures", "frames", "results", "reports"):
            (root / name).mkdir(parents=True, exist_ok=True)

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def resolved_face_model_path(self) -> Path:
        path = Path(self.face_model_path)
        if path.is_file():
            return path.resolve()
        backend_root = Path(__file__).resolve().parents[2]
        candidate = (backend_root / path).resolve()
        if candidate.is_file():
            return candidate
        return path


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
