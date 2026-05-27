from __future__ import annotations

import time

import pandas as pd
from sqlalchemy import text

from utils.db import build_mysql_engine


def timed_query(sql: str) -> tuple[pd.DataFrame, float]:
    engine = build_mysql_engine()
    with engine.begin() as conn:
        start = time.perf_counter()
        df = pd.read_sql(text(sql), conn)
        elapsed = time.perf_counter() - start
    return df, elapsed


def main() -> None:
    """
    Example performance comparison required by the report:
    Compare monthly GMV query using base tables vs pre-aggregated view.
    """
    base_sql = """
    SELECT
      DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS year_month,
      SUM(oi.price) AS total_gmv
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.order_id
    WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
    GROUP BY 1
    ORDER BY 1
    """
    mv_sql = "SELECT year_month, total_gmv FROM mv_monthly_sales ORDER BY year_month"

    _, t1 = timed_query(base_sql)
    _, t2 = timed_query(mv_sql)

    print("Performance comparison (same question: monthly GMV):")
    print(f"- base tables aggregation: {t1:.3f}s")
    print(f"- pre-aggregation view (mv_monthly_sales): {t2:.3f}s")


if __name__ == "__main__":
    main()

