from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text

from utils.db import build_mysql_engine, ensure_database_exists
from utils.refresh_views import VIEW_DEFS, refresh_all_views
from utils.settings import get_settings


BASE_TABLES = [
    "customers",
    "geolocation",
    "order_items",
    "payments",
    "order_reviews",
    "orders",
    "products",
    "sellers",
    "product_category_name_translation",
]

REQUIRED_VIEWS = list(VIEW_DEFS.keys())


@dataclass
class StartupStatus:
    database_ready: bool
    missing_tables: list[str]
    missing_views: list[str]
    views_refreshed: bool
    message: str


def _table_exists(conn, table_name: str) -> bool:
    s = get_settings()
    row = conn.execute(
        text(
            """
            SELECT COUNT(*) AS cnt
            FROM information_schema.tables
            WHERE table_schema = :db AND table_name = :tbl
            """
        ),
        {"db": s.mysql_database, "tbl": table_name},
    ).mappings().first()
    return bool(row and row["cnt"] > 0)


def check_missing_tables() -> list[str]:
    ensure_database_exists()
    engine = build_mysql_engine()
    missing: list[str] = []
    with engine.connect() as conn:
        for tbl in BASE_TABLES:
            if not _table_exists(conn, tbl):
                missing.append(tbl)
    return missing


def check_missing_views() -> list[str]:
    ensure_database_exists()
    engine = build_mysql_engine()
    missing: list[str] = []
    with engine.connect() as conn:
        for view in REQUIRED_VIEWS:
            if not _table_exists(conn, view):
                missing.append(view)
    return missing


def ensure_views_ready(*, auto_refresh: bool = True) -> StartupStatus:
    """
    Verify pre-aggregation materialized tables exist; refresh if missing.

    Called at dashboard startup so agents can safely query views.
    """
    missing_tables = check_missing_tables()
    missing_views = check_missing_views()
    views_refreshed = False

    if missing_tables:
        return StartupStatus(
            database_ready=False,
            missing_tables=missing_tables,
            missing_views=missing_views,
            views_refreshed=False,
            message=(
                f"基础表缺失 {len(missing_tables)} 张，请先运行: python -m utils.db_init"
            ),
        )

    if missing_views and auto_refresh:
        refresh_all_views()
        missing_views = check_missing_views()
        views_refreshed = True

    if missing_views:
        return StartupStatus(
            database_ready=False,
            missing_tables=[],
            missing_views=missing_views,
            views_refreshed=views_refreshed,
            message=f"预聚合视图仍缺失: {', '.join(missing_views)}",
        )

    return StartupStatus(
        database_ready=True,
        missing_tables=[],
        missing_views=[],
        views_refreshed=views_refreshed,
        message="数据库与预聚合视图已就绪",
    )


def main() -> None:
    status = ensure_views_ready(auto_refresh=True)
    print(status.message)
    if status.missing_tables:
        print("missing tables:", ", ".join(status.missing_tables))
    if status.missing_views:
        print("missing views:", ", ".join(status.missing_views))
    if not status.database_ready:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
