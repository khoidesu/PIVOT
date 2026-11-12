import os

import psycopg
import pytest

# DB test riêng: không phá dữ liệu demo. Phải đặt env TRƯỚC khi import app.
TEST_DB = "pivot_test"
os.environ["PIVOT_DATABASE_URL"] = f"postgresql+psycopg://pivot:pivot_dev@localhost:5433/{TEST_DB}"
os.environ["PIVOT_INTAKE_EXTRACTOR"] = "rule"  # test KHÔNG được gọi mô hình thật dù backend/.env có khoá
os.environ["PIVOT_ETA_MODEL_DIR"] = ""  # test ETA mô phỏng cũ không bị model ONNX trong backend/model chen vào; test ONNX tự trỏ thư mục
os.environ["PIVOT_GEMINI_API_KEY"] = ""
os.environ["PIVOT_ANTHROPIC_API_KEY"] = ""
for _k, _v in {"LLM_IMAGE_PER_USER_DAY": "3", "LLM_IMAGE_PER_USER_MINUTE": "2", "LLM_IMAGE_GLOBAL_DAY": "100",  # giới hạn lượt cố định:
               "LLM_PER_USER_DAY": "50", "LLM_PER_USER_MINUTE": "5", "LLM_GLOBAL_DAY": "500",
               "LLM_PER_IP_DAY": "150", "LLM_PER_IP_MINUTE": "15", "LLM_GLOBAL_MINUTE": "30",
               "LLM_IMAGE_PER_IP_DAY": "20", "LLM_IMAGE_PER_IP_MINUTE": "6", "LLM_IMAGE_GLOBAL_MINUTE": "10", "TRUST_PROXY": "false"}.items():  # backend/.env (demo) không làm lệch test
    os.environ[f"PIVOT_{_k}"] = _v
os.environ.pop("PIVOT_GEMINI_VISION_MODEL", None)
os.environ["PIVOT_SIGNALS_ENABLED"] = "false"  # test không gọi OSRM/Open-Meteo thật (xác định, chạy offline); test tín hiệu bật lại bằng monkeypatch


def _ensure_test_db() -> None:
    with psycopg.connect("postgresql://pivot:pivot_dev@localhost:5433/postgres", autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB}"')


@pytest.fixture(scope="session", autouse=True)
def _db():
    _ensure_test_db()
    from app.db import engine
    from app.models import Base
    assert engine.url.database.endswith("_test"), "refusing to drop_all on a non-test database"
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture()
def seeded(_db):
    from app.db import SessionLocal
    from app.seed import reset, seed
    with SessionLocal() as session:
        reset(session)
        seed(session)
        session.commit()


@pytest.fixture()
def client(seeded):
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def auth(user_key: str) -> dict:
    return {"Authorization": f"Bearer dev:{user_key}"}
