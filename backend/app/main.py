from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import core

app = FastAPI(title="PIVOT / VSGA", version="0.1.0",
              description="Prototype điều phối logistics — dữ liệu MÔ PHỎNG (mock).")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(core.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
