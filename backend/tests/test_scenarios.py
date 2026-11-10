"""6 kịch bản demo bắt buộc chạy end-to-end qua API thật và lặp lại được (DRAFT Ngày 5)."""
import pytest
from fastapi.testclient import TestClient

from app.demo.scenarios import SCENARIOS, run_scenario
from app.main import app


@pytest.mark.parametrize("sid", [s for s, _ in SCENARIOS])
def test_scenario_passes(sid, seeded):
    res = run_scenario(sid, lambda: TestClient(app))
    failed = [s for s in res["steps"] if not s["ok"]]
    assert res["passed"] and not failed, failed


def test_scenarios_are_repeatable(seeded):
    for _ in range(2):  # chạy lại ngay lập tức (không phụ thuộc trạng thái của lần trước)
        for sid in ("success", "race", "duplicate_restart"):
            assert run_scenario(sid, lambda: TestClient(app))["passed"], sid


def test_reset_does_not_deadlock_with_concurrent_readers_and_worker(seeded):
    """Hồi quy: reset bằng TRUNCATE từng bế tắc với request/worker song song (phát hiện khi chạy tab Demo)."""
    import threading
    from tests.conftest import auth
    from tests.helpers import run_worker
    stop, errors = threading.Event(), []

    def hammer():
        c = TestClient(app, raise_server_exceptions=False)
        while not stop.is_set():
            c.get("/v1/shipments", headers=auth("shipper_a"))
            c.get("/v1/proposals", headers=auth("shipper_a"))
            run_worker(c)

    ts = [threading.Thread(target=hammer) for _ in range(4)]
    [t.start() for t in ts]
    try:
        c = TestClient(app, raise_server_exceptions=False)
        for _ in range(8):
            r = c.post("/v1/demo/reset", headers=auth("dispatch"))
            if r.status_code != 200:
                errors.append(r.status_code)
    finally:
        stop.set()
        [t.join() for t in ts]
    assert errors == []
