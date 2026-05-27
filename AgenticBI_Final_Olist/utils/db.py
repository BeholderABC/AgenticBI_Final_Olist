from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from utils.settings import get_settings


@dataclass(frozen=True)
class MySQLConnInfo:
    host: str
    port: int
    user: str
    password: str
    database: str


def get_mysql_info() -> MySQLConnInfo:
    s = get_settings()
    return MySQLConnInfo(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        database=s.mysql_database,
    )


def build_mysql_engine(
    database: str | None = None,
    *,
    connect_timeout_s: int = 10,
    read_timeout_s: int = 60,
    write_timeout_s: int = 60,
) -> Engine:
    info = get_mysql_info()
    db = database or info.database
    # NOTE: use utf8mb4 for Portuguese chars/review text
    url = (
        f"mysql+pymysql://{info.user}:{info.password}@{info.host}:{info.port}/{db}"
        "?charset=utf8mb4"
    )
    # Avoid "infinite hang" on bad network / wrong host: add timeouts.
    # PyMySQL supports these kwargs; SQLAlchemy passes them through.
    connect_args = {
        "connect_timeout": connect_timeout_s,
        "read_timeout": read_timeout_s,
        "write_timeout": write_timeout_s,
        "charset": "utf8mb4",
    }
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_timeout=10,
        pool_recycle=1800,
        connect_args=connect_args,
        future=True,
    )


def ensure_database_exists() -> None:
    info = get_mysql_info()
    # connect without specifying database to create it if needed
    url = f"mysql+pymysql://{info.user}:{info.password}@{info.host}:{info.port}/?charset=utf8mb4"
    engine = create_engine(url, pool_pre_ping=True, future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{info.database}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        )


@contextmanager
def mysql_conn(engine: Engine):
    with engine.begin() as conn:
        yield conn

