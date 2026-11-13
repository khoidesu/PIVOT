"""14/11: Neon (gói miễn phí) hết hạn mức vì worker nền truy vấn DB mỗi giây, 24/7. Worker phải ngủ khi không ai dùng web,
đóng kết nối DB, và thức lại ngay khi có request API; /healthz (Render, UptimeRobot) không được tính là có người dùng."""
import asyncio
import time

from app import main
from app.config import settings
from tests.conftest import auth


def test_worker_sleeps_when_idle_and_wakes_on_request(monkeypatch):
    calls, disposed = [], []
    monkeypatch.setattr(main, "process_pending", lambda: calls.append(time.monotonic()))
    monkeypatch.setattr(main, "sim_tick_once", lambda: None)
    monkeypatch.setattr("app.db.engine.dispose", lambda: disposed.append(1))
    monkeypatch.setattr(settings, "worker_idle_after_s", 0.3)

    async def scenario():
        main.activity.last = time.monotonic()
        task = asyncio.create_task(main.background_loop(interval=0.02))
        await asyncio.sleep(0.15)
        busy = len(calls)
        assert busy > 3                                  # đang có người dùng → chạy liên tục
        await asyncio.sleep(0.6)                         # quá ngưỡng rảnh → ngủ
        asleep = len(calls)
        await asyncio.sleep(0.4)
        assert len(calls) == asleep, "worker vẫn truy vấn DB khi không ai dùng"
        assert disposed, "phải đóng kết nối DB khi ngủ để Neon tạm nghỉ được"
        main.activity.touch()                            # có request API → thức ngay
        await asyncio.sleep(0.1)
        assert len(calls) > asleep
        task.cancel()

    asyncio.run(scenario())


def test_healthz_does_not_count_as_activity_but_api_does(client):
    main.activity.last = 0.0
    client.get("/healthz")
    assert main.activity.last == 0.0                     # UptimeRobot/Render không giữ worker (và Neon) thức
    client.get("/v1/meta", headers=auth("shipper_a"))
    assert main.activity.last > 0.0
