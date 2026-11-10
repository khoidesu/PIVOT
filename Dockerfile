# Một image: giao diện (React build) + API (FastAPI) chung một link. Build từ thư mục gốc repo.
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# rỗng = gọi API cùng origin (giao diện và API cùng một domain)
ARG VITE_API_URL=
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/static
COPY deploy/entrypoint.sh /app/entrypoint.sh
ENV PIVOT_STATIC_DIR=/app/static PIVOT_DATA_MODE=mock
RUN useradd --create-home app && chmod +x /app/entrypoint.sh && chown -R app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT','8000'))"
CMD ["/app/entrypoint.sh"]
