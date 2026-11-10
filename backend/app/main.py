import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import core, events, matching
from .worker import process_pending



@asynccontextmanager
async def lifespan(app: FastAPI):
    # Chốt chặn: token dev chỉ được bật cùng dữ liệu mô phỏng
    if settings.allow_dev_tokens and settings.data_mode != "mock":
        raise RuntimeError("Refusing to start: dev tokens enabled while PIVOT_DATA_MODE != 'mock'")
    task = None
    if settings.worker_inline:  # worker nền đọc outbox mỗi giây (chạy cùng tiến trình cho demo local)
        async def loop():
            while True:
                await asyncio.to_thread(process_pending)
                await asyncio.sleep(1)
        task = asyncio.create_task(loop())
    yield
    if task:
        task.cancel()


app = FastAPI(title="PIVOT / VSGA", version="0.2.0", lifespan=lifespan,
              description="Prototype điều phối logistics — dữ liệu MÔ PHỎNG (mock).")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core.router)
app.include_router(matching.router)
app.include_router(events.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
