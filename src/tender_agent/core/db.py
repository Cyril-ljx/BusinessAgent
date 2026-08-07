"""数据库 Session 工厂。"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ..config.settings import settings


if not settings.DATABASE_URL:
    raise RuntimeError("未配置 DATABASE_URL,请在 .env 中填写数据库连接串")


def _connect_args() -> dict:
    if settings.DATABASE_URL.startswith(("postgresql://", "postgresql+psycopg2://")):
        return {"connect_timeout": int(settings.DB_CONNECT_TIMEOUT_SECONDS)}
    return {}


engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=int(settings.DB_POOL_TIMEOUT_SECONDS),
    connect_args=_connect_args(),
)
SessionLocal = sessionmaker(bind=engine)


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI/LangGraph 共用的数据库 session 生成器。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
