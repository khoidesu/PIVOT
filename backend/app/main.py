import asyncio
from contextlib import asynccontextmanager

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import auth, benefits, core, demo, docks, eta, events, incidents, intake, matching, tracking
from .worker import process_pending



def _warm_eta() -> None:
    from .eta import ml
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chốt chặn: token dev chỉ được bật cùng dữ liệu mô phỏng
    if settings.allow_dev_tokens and settings.data_mode != "mock":
        raise RuntimeError("Refusing to start: dev tokens enabled while PIVOT_DATA_MODE != 'mock'")
    task = None
    asyncio.get_event_loop().run_in_executor(None, _warm_eta)  # huấn luyện ETA mô phỏng nền (không chặn khởi động)
    if settings.worker_inline:  # worker nền đọc outbox mỗi giây (chạy cùng tiến trình cho demo local)
        async def loop():
            while True:
                await asyncio.to_thread(process_pending)
                await asyncio.to_thread(sim_tick_once)
                await asyncio.sleep(1)
        task = asyncio.create_task(loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="LOGECTION", version="0.2.0", lifespan=lifespan,
              description="Prototype điều phối logistics — dữ liệu MÔ PHỎNG (mock).")

_origins = ["http://localhost:5173", "http://127.0.0.1:5173"] + [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(core.router)
app.include_router(matching.router)
app.include_router(events.router)
app.include_router(benefits.router)
app.include_router(intake.router)
app.include_router(tracking.router)
app.include_router(incidents.router)
app.include_router(docks.router)
app.include_router(eta.router)
app.include_router(demo.router)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if not settings.allow_framing:
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def mount_static(application: FastAPI, directory: str | None) -> bool:
    """Phục vụ giao diện đã build ở "/" (một link duy nhất). Gắn SAU các router API nên không bao giờ che /v1, /healthz, /docs."""
    if directory and os.path.isdir(directory):
        application.mount("/", StaticFiles(directory=directory, html=True), name="web")
        return True
    return False


mount_static(app, settings.static_dir)
