from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

# DB trên mạng (Neon) có thể ngắt kết nối nhàn rỗi → pre_ping + recycle. Pool 10 + 10 (mặc định 5 + 10 cạn khi nhiều cửa sổ polling
# trên Render: request chờ 30 giây giữ hết thread → cả /healthz cũng treo → Render khởi động lại, 502 theo chu kỳ). Chờ tối đa
# 10 giây thay vì 30 để request quá tải trả lỗi sớm, nhả thread cho request khác.
engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=300,
                       pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow, pool_timeout=settings.db_pool_timeout)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
