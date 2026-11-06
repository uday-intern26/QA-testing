import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".tmp-test-data"
ROOT.mkdir(parents=True, exist_ok=True)
DATA = ROOT / "data"
DATA.mkdir(parents=True, exist_ok=True)
DB_PATH = ROOT / "qa.sqlite3"
os.environ["DATA_DIR"] = str(DATA)
os.environ["DATABASE_URL"] = "sqlite:///" + DB_PATH.as_posix()
os.environ["FACE_MODEL_PATH"] = str(ROOT / "missing-face-landmarker.task")
os.environ["APPLITOOLS_ENABLED"] = "false"
os.environ["APPLITOOLS_API_KEY"] = ""

import pytest

from app.core.config import get_settings
from app.db.database import init_db, reset_engine
from app.services.application_service import ApplicationService


@pytest.fixture(autouse=True)
def isolated_database():
    get_settings.cache_clear()
    ApplicationService.validated_urls.clear()
    reset_engine()
    if DB_PATH.exists():
        DB_PATH.unlink()
    get_settings().ensure_dirs()
    init_db()
    yield
    reset_engine()
