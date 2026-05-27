from __future__ import annotations

from pathlib import Path
import time
import textwrap

from utils.db import build_mysql_engine
from utils.settings import ROOT_DIR

VIEW_DEFS = {
    "mv_monthly_sales": "mv_monthly_sales",
    "mv_state_sales": "mv_state_sales",
    "mv_category_sales": "mv_category_sales",
    "mv_delivery_perf": "mv_delivery_perf",
    "mv_seller_perf": "mv_seller_perf",
    "mv_payment_dist": "mv_payment_dist",
    # geo helpers (avoid runtime big JOINs)
    "mv_zip_geo": "mv_zip_geo",
    "mv_state_geo": "mv_state_geo",
}

VIEW_SQL_STMTS = {
    # geo helper must be defined before mv_state_geo (referenced during refresh)
    "mv_zip_geo": """
        SELECT
          geolocation_zip_code_prefix,
          AVG(geolocation_lat) AS lat,
          AVG(geolocation_lng) AS lng
        FROM geolocation
        GROUP BY 1
    """,
    "mv_monthly_sales": """
        SELECT
          CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS `year_month`,
          SUM(oi.price) AS total_gmv,
          COUNT(DISTINCT o.order_id) AS total_orders,
          (SUM(oi.price) / NULLIF(COUNT(DISTINCT o.order_id), 0)) AS avg_basket,
          SUM(oi.freight_value) AS total_freight
        FROM `orders` o
        JOIN `order_items` oi ON oi.order_id = o.order_id
        WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
        GROUP BY `year_month`
    """,
    "mv_state_sales": """
        SELECT
          CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS `year_month`,
          c.customer_state,
          SUM(oi.price) AS total_gmv,
          COUNT(DISTINCT o.order_id) AS total_orders,
          COUNT(DISTINCT c.customer_unique_id) AS unique_customers
        FROM `orders` o
        JOIN `customers` c ON c.customer_id = o.customer_id
        JOIN `order_items` oi ON oi.order_id = o.order_id
        WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
        GROUP BY `year_month`, c.customer_state
    """,
    "mv_category_sales": """
        SELECT
          CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS `year_month`,
          COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS product_category_english,
          SUM(oi.price) AS total_gmv,
          COUNT(DISTINCT o.order_id) AS total_orders,
          AVG(oi.price) AS avg_price
        FROM `orders` o
        JOIN `order_items` oi ON oi.order_id = o.order_id
        JOIN `products` p ON p.product_id = oi.product_id
        LEFT JOIN `product_category_name_translation` t
          ON t.product_category_name = p.product_category_name
        WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
        GROUP BY `year_month`, 
                 COALESCE(t.product_category_name_english, p.product_category_name, 'unknown')
    """,
    "mv_delivery_perf": """
        SELECT
          CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS `year_month`,
          c.customer_state,
          AVG(DATEDIFF(o.order_delivered_customer_date, o.order_purchase_timestamp)) AS avg_delivery_days,
          AVG(CASE WHEN o.order_delivered_customer_date <= o.order_estimated_delivery_date THEN 1 ELSE 0 END) AS on_time_rate,
          SUM(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1 ELSE 0 END) AS delayed_orders
        FROM `orders` o
        JOIN `customers` c ON c.customer_id = o.customer_id
        WHERE o.order_status = 'delivered'
          AND o.order_delivered_customer_date IS NOT NULL
          AND o.order_estimated_delivery_date IS NOT NULL
        GROUP BY `year_month`, c.customer_state
    """,
    "mv_seller_perf": """
        SELECT
          CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS `year_month`,
          oi.seller_id,
          s.seller_state,
          SUM(oi.price) AS total_gmv,
          COUNT(DISTINCT o.order_id) AS total_orders,
          AVG(r.review_score) AS avg_review_score
        FROM `orders` o
        JOIN `order_items` oi ON oi.order_id = o.order_id
        JOIN `sellers` s ON s.seller_id = oi.seller_id
        LEFT JOIN `order_reviews` r ON r.order_id = o.order_id
        WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
        GROUP BY `year_month`, oi.seller_id, s.seller_state
    """,
    "mv_payment_dist": """
        SELECT
          CONCAT(YEAR(o.order_purchase_timestamp), '-', LPAD(MONTH(o.order_purchase_timestamp), 2, '0')) AS `year_month`,
          p.payment_type,
          COUNT(*) AS total_transactions,
          AVG(p.payment_installments) AS avg_installments,
          SUM(p.payment_value) AS total_value
        FROM `orders` o
        JOIN `payments` p ON p.order_id = o.order_id
        WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
        GROUP BY `year_month`, p.payment_type
    """,
    "mv_state_geo": """
        SELECT
          k.customer_state,
          s.lat,
          s.lng,
          k.total_gmv,
          k.total_orders
        FROM (
          SELECT
            customer_state,
            SUM(total_gmv) AS total_gmv,
            SUM(total_orders) AS total_orders
          FROM mv_state_sales
          GROUP BY 1
        ) k
        LEFT JOIN (
          SELECT
            c.customer_state,
            AVG(z.lat) AS lat,
            AVG(z.lng) AS lng
          FROM customers c
          JOIN mv_zip_geo z
            ON z.geolocation_zip_code_prefix = c.customer_zip_code_prefix
          GROUP BY 1
        ) s
          ON s.customer_state = k.customer_state
        ORDER BY k.total_gmv DESC
    """,
}

def refresh_all_views(*, per_view_timeout_s: int = 600) -> dict[str, float]:
    """
    Refresh materialized views as physical tables.

    Reliability first:
    - Each view is refreshed in its own fresh connection/transaction.
    - Long-running refresh uses a larger read timeout than interactive queries.
    - Failures are recorded but do not prevent other views from refreshing.
    """
    timings: dict[str, float] = {}

    for view_name in VIEW_DEFS.keys():
        select_stmt = VIEW_SQL_STMTS[view_name]
        select_stmt = textwrap.dedent(select_stmt).strip()

        engine = build_mysql_engine(read_timeout_s=per_view_timeout_s, write_timeout_s=per_view_timeout_s)
        try:
            with engine.begin() as conn:
                try:
                    conn.exec_driver_sql("SET SESSION lock_wait_timeout = 10")
                except Exception:
                    pass
                try:
                    conn.exec_driver_sql("SET SESSION max_execution_time = 600000")
                except Exception:
                    pass

                conn.exec_driver_sql(f"DROP TABLE IF EXISTS `{view_name}`")
                start = time.perf_counter()
                conn.exec_driver_sql(f"CREATE TABLE `{view_name}` AS {select_stmt}")
                elapsed = time.perf_counter() - start
                timings[view_name] = elapsed
        except Exception as e:
            timings[view_name] = -1.0
            print(f"[WARN] refresh failed for {view_name}: {type(e).__name__}: {e}")

    # indexes (best-effort, in fresh connection)
    engine = build_mysql_engine(read_timeout_s=per_view_timeout_s, write_timeout_s=per_view_timeout_s)
    with engine.begin() as conn:
        index_ddls = [
            "CREATE INDEX idx_mv_monthly_sales_ym ON mv_monthly_sales(`year_month`)",
            "CREATE INDEX idx_mv_state_sales_ym_state ON mv_state_sales(`year_month`, customer_state)",
            "CREATE INDEX idx_mv_category_sales_ym_cat ON mv_category_sales(`year_month`, product_category_name_english)",
            "CREATE INDEX idx_mv_delivery_perf_ym_state ON mv_delivery_perf(`year_month`, customer_state)",
            "CREATE INDEX idx_mv_seller_perf_ym_seller ON mv_seller_perf(`year_month`, seller_id)",
            "CREATE INDEX idx_mv_payment_dist_ym_type ON mv_payment_dist(`year_month`, payment_type)",
            "CREATE INDEX idx_mv_state_geo_state ON mv_state_geo(customer_state)",
        ]
        for ddl in index_ddls:
            try:
                conn.exec_driver_sql(ddl)
            except Exception:
                pass

    return timings

def main() -> None:
    timings = refresh_all_views()
    print("Refreshed materialized views:")
    for k, v in timings.items():
        print(f"- {k}: {v:.3f}s")

if __name__ == "__main__":
    main()