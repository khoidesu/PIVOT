import asyncio
import logging
import math
import time
from contextlib import asynccontextmanager

import os

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import auth, benefits, core, demo, docks, eta, events, incidents, intake, matching, sandbox, tracking
from .worker import process_pending

log = logging.getLogger("pivot.main")


def _warm_eta() -> None:
    from .eta import ml, onnx_model
    onnx_model.state()  # nạp + kiểm tra model ONNX sớm (nếu có)
    ml.ensure_trained()


def sim_tick_once() -> None:
    """Đẩy bộ giả lập GPS một bước (chỉ có tác dụng khi có chuyến đã bật mô phỏng)."""
    from datetime import datetime, timezone
    from .db import SessionLocal
    from .sim import gps
    try:
        with SessionLocal() as s:
            if gps.tick(s, datetime.now(timezone.utc)):
                s.commit()
    except Exception:  # noqa: BLE001 — mô phỏng không được làm sập vòng worker
        pass


class Activity:
    """Lần cuối có request API thật (không tính /healthz của Render/UptimeRobot) + tín hiệu đánh thức worker.

    14/11: worker truy vấn DB mỗi giây kể cả khi không ai dùng web → Neon (gói miễn phí) không bao giờ được tạm nghỉ và hết hạn
    mức ("Your account or project has exceeded the quota"). Nay worker chỉ chạy khi có người dùng; rảnh quá
    `worker_idle_after_s` giây thì đóng kết nối DB và ngủ tới request kế tiếp."""

    def __init__(self) -> None:
        self.last = time.monotonic()
        self.kick: asyncio.Event | None = None

    def touch(self) -> None:
        self.last = time.monotonic()
        if self.kick is not None:
            self.kick.set()

    def idle(self, idle_after: float) -> bool:
        return idle_after > 0 and time.monotonic() - self.last > idle_after


activity = Activity()


async def background_loop(interval: float = 1.0) -> None:
    """Vòng worker nền. Một lần lỗi (vd Neon ngắt kết nối) chỉ ghi log rồi chạy tiếp — nếu để lỗi thoát ra ngoài thì task
    asyncio chết lặng lẽ và outbox/mô phỏng dừng hẳn cho tới khi khởi động lại. Không ai dùng web → ngủ (xem `Activity`)."""
    activity.kick = asyncio.Event()
    while True:
        if activity.idle(settings.worker_idle_after_s):
            from .db import engine
            activity.kick.clear()  # xoá TRƯỚC khi đóng kết nối: request tới trong lúc đó vẫn đánh thức được
            log.info("worker idle: closing DB connections and sleeping until the next API request")
            await asyncio.to_thread(engine.dispose)  # không giữ kết nối mở → Neon tự tạm nghỉ được
            if activity.idle(settings.worker_idle_after_s):
                await activity.kick.wait()  # request API kế tiếp đánh thức (không hẹn giờ: hẹn giờ cũng đánh thức Neon)
            log.info("worker resumed")
        try:
            await asyncio.to_thread(process_pending)
            await asyncio.to_thread(sim_tick_once)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("background worker iteration failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chốt chặn: token dev chỉ được bật cùng dữ liệu mô phỏng
    if settings.allow_dev_tokens and settings.data_mode != "mock":
        raise RuntimeError("Refusing to start: dev tokens enabled while PIVOT_DATA_MODE != 'mock'")
    task = None
    asyncio.get_running_loop().run_in_executor(None, _warm_eta)  # huấn luyện ETA mô phỏng nền (không chặn khởi động)
    if settings.worker_inline:  # worker nền đọc outbox mỗi giây (chạy cùng tiến trình cho demo local)
        task = asyncio.create_task(background_loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="LOGECTION", version="0.2.0", lifespan=lifespan,
              description="Prototype điều phối logistics — dữ liệu MÔ PHỎNG (mock).")

_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
] + [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(core.router)
app.include_router(matching.router)
app.include_router(events.router)
app.include_router(sandbox.router)  # trước benefits: /benefits/{id} sẽ nuốt /benefits/sandbox/*
app.include_router(benefits.router)
app.include_router(intake.router)
app.include_router(tracking.router)
app.include_router(incidents.router)
app.include_router(docks.router)
app.include_router(eta.router)
app.include_router(demo.router)


def _json_safe(v):
    """Đưa chi tiết lỗi validate về dạng JSON chắc chắn serialize được: số không hữu hạn → chuỗi ("nan", "inf"),
    kiểu lạ (bytes, exception trong ctx…) → chuỗi. Cấu trúc dict/list giữ nguyên."""
    if isinstance(v, float) and not math.isfinite(v):
        return str(v)
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Giữ đúng định dạng 422 mặc định của FastAPI ({"detail": [...]}) nhưng không bao giờ 500 vì `input` chứa NaN/Infinity (QA-04)."""
    return JSONResponse(status_code=422, content={"detail": _json_safe(jsonable_encoder(exc.errors()))})


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.url.path.startswith("/v1/"):  # có người dùng thật → worker chạy (giữ /healthz ngoài để UptimeRobot không giữ Neon thức)
        activity.touch()
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not settings.allow_embed:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.get("/healthz")
async def healthz():  # async: chạy trên event loop, không mượn thread của API → vẫn trả lời khi DB/threadpool đang quá tải (tránh Render khởi động lại oan)
    return {"status": "ok"}


def mount_static(application: FastAPI, directory: str | None) -> bool:
    """Phục vụ giao diện đã build ở "/" (một link duy nhất). Gắn SAU các router API nên không bao giờ che /v1, /healthz, /docs."""
    if directory and os.path.isdir(directory):
        application.mount("/", StaticFiles(directory=directory, html=True), name="web")
        return True
    return False


mount_static(app, settings.static_dir)
