#!/bin/sh
# Khởi động bản triển khai: migration → seed nếu DB trống (lần đầu) → chạy API + giao diện (+ worker nền cùng tiến trình).
set -e
cd /app/backend
python -m alembic upgrade head
python -m app.seed --if-empty
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips="*"
