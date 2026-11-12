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
    intake_extractor: str = "rule"  # rule | llm | hybrid  (llm cần PIVOT_ANTHROPIC_API_KEY; hybrid = luật trước + Gemini bổ sung, cần PIVOT_GEMINI_API_KEY)
    gemini_api_key: str | None = None  # KHÔNG ghi vào mã/log; cấp qua biến môi trường hoặc backend/.env (đã .gitignore)
    gemini_model: str = "gemini-3.1-flash-lite"  # nhanh, rẻ, đủ cho trích xuất có schema (gemini-2.5-flash đã ngừng cấp cho khoá mới)
    gemini_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_timeout_s: float = 25.0  # tổng thời gian chờ Gemini (kể cả mô hình dự phòng); quá hạn → quay về kết quả của luật
    gemini_fallback_models: str = "gemini-3.5-flash-lite"  # gọi song song khi mô hình chính chưa trả sau gemini_hedge_after_s (rỗng = tắt)
    gemini_hedge_after_s: float = 5.0
    gemini_vision_hedge_after_s: float = 15.0  # đọc ảnh chậm hơn văn bản: chờ lâu hơn trước khi gọi song song mô hình dự phòng (lỗi thì gọi ngay)
    gemini_vision_model: str | None = None  # mô hình đọc ẢNH / PDF scan (vd một bản Pro, đọc chữ viết tay tốt hơn); trống = dùng gemini_model
    llm_per_user_day: int = 50  # giới hạn lượt gọi mô hình: mỗi người/ngày, mỗi người/phút, toàn hệ thống/ngày (vượt → dùng bộ luật)
    llm_per_user_minute: int = 5
    llm_global_day: int = 500
    llm_per_ip_day: int = 150  # theo IP: chặn đổi tên đăng nhập để lấy thêm lượt (nhóm cùng mạng văn phòng dùng chung mức này)
    llm_per_ip_minute: int = 15
    llm_global_minute: int = 30  # toàn hệ thống mỗi phút: nhiều người thử cùng lúc không vượt giới hạn tốc độ của khoá
    intake_image_enabled: bool = True  # cho phép nhập liệu từ ảnh (cần khoá Gemini). Ảnh gửi NGUYÊN VẸN ra ngoài → tắt ở bản công khai
    llm_image_per_user_day: int = 3  # ảnh tốn lượt hơn văn bản: giới hạn riêng, không có bộ luật để quay về nên hết lượt là báo lỗi rõ
    llm_image_per_user_minute: int = 2
    llm_image_global_day: int = 100
    llm_image_per_ip_day: int = 20
    llm_image_per_ip_minute: int = 6
    llm_image_global_minute: int = 10
    trust_proxy: bool = False  # true khi chạy sau proxy (Render): IP người dùng = phần tử CUỐI của X-Forwarded-For (do proxy thêm, không giả được)
    intake_image_max_bytes: int = 4_000_000
    intake_pdf_enabled: bool = True  # PDF có lớp chữ đọc ngay trong máy chủ (không cần khoá); PDF scan cần đọc ảnh (Gemini) và tính vào lượt ảnh
    intake_pdf_max_bytes: int = 5_000_000
    intake_pdf_max_pages: int = 3
    intake_pdf_min_letters: int = 40  # ít chữ cái hơn ngưỡng này (vd chỉ có chân trang) → coi là PDF scan
    anthropic_api_key: str | None = None  # KHÔNG ghi vào mã/log; cấp qua biến môi trường
    anthropic_model: str = "claude-haiku-5-5"
    allow_embed: bool = False  # true → bỏ X-Frame-Options (cần khi chạy trong khung nhúng của Hugging Face Spaces)
    signals_enabled: bool = True  # ETA tầng 2: gọi OSRM (đường bộ thật) + Open-Meteo (thời tiết); tắt → chỉ dùng ETA luật + tuyến nội suy
    osrm_url: str = "https://router.project-osrm.org"  # máy chủ demo công khai (fair use); tự dựng OSRM riêng cho production
    weather_url: str = "https://api.open-meteo.com/v1/forecast"
    signals_timeout_s: float = 2.5
    mapbox_token: str | None = None  # KHÔNG ghi vào mã/log; cấp qua biến môi trường PIVOT_MAPBOX_TOKEN. Có → kẹt xe thật (Mapbox Directions driving-traffic)
    mapbox_url: str = "https://api.mapbox.com"
    eta_model_dir: str | None = None  # thư mục model ONNX (mặc định backend/model); đặt RỖNG để tắt
    eta_model_force: bool = False  # true: dùng model dù cổng promote KHÔNG đạt — CHỈ để thử/demo, luôn gắn nhãn bật thủ công
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
