from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIVOT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pivot:pivot_dev@localhost:5433/pivot"
    hold_seconds: int = 120  # DRAFT 5.4: hold có hạn, demo 120 giây
    data_mode: str = "mock"  # mock | live — hiển thị trên UI (DRAFT mục 7)
    worker_inline: bool = True  # worker outbox chạy nền cùng API (tắt khi chạy `python -m app.worker` riêng)
    allow_dev_tokens: bool = True  # chỉ cho prototype local; tắt khi có OIDC thật


settings = Settings()
