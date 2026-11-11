from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PIVOT_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://pivot:pivot_dev@localhost:5433/pivot"
    admin_key: str | None = None  # có giá trị → các thao tác phá dữ liệu demo (reset/kịch bản/làm tuổi dữ liệu) cần header X-Admin-Key
    static_dir: str | None = None  # thư mục giao diện đã build; có giá trị → API phục vụ luôn giao diện (một link duy nhất)
    cors_origins: str = ""  # danh sách origin phân tách bằng dấu phẩy (chỉ cần khi giao diện chạy ở domain khác)
    hold_seconds: int = 120  # DRAFT 5.4: hold có hạn, demo 120 giây
    data_mode: str = "mock"  # mock | live — hiển thị trên UI (DRAFT mục 7)
    worker_inline: bool = True  # worker outbox chạy nền cùng API (tắt khi chạy `python -m app.worker` riêng)
    intake_extractor: str = "rule"  # rule | llm  (llm chỉ dùng được khi có PIVOT_ANTHROPIC_API_KEY)
    anthropic_api_key: str | None = None  # KHÔNG ghi vào mã/log; cấp qua biến môi trường
    anthropic_model: str = "claude-haiku-5-5"
    allow_framing: bool = False  # true → bỏ X-Frame-Options (cần khi nhúng trong khung của Hugging Face Spaces)
    allow_dev_tokens: bool = True  # chỉ cho prototype local; tắt khi có OIDC thật


    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        """Nhà cung cấp (Render/Heroku…) đưa `postgres://` hoặc `postgresql://`; SQLAlchemy cần driver psycopg v3."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v


settings = Settings()
