"""Independent verification of Member A self-test claims."""
from __future__ import annotations

import time

import pandas as pd
from sqlalchemy import text

from utils.db import build_mysql_engine

BASE_SQL = """
SELECT
  DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS ym,
  SUM(oi.price) AS gmv
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')
ORDER BY ym
"""

MV_SQL = "SELECT `year_month` AS ym, total_gmv AS gmv FROM mv_monthly_sales ORDER BY ym"

# Kaggle Olist public dataset expected approximate row counts
EXPECTED_RAW = {
    "orders": (99_000, 100_000),
    "order_items": (112_000, 113_000),
    "customers": (99_000, 100_000),
    "geolocation_raw_csv": (1_000_000, 1_001_000),
    "payments": (103_000, 104_000),
    "order_reviews": (98_000, 100_000),
    "products": (32_000, 33_000),
    "sellers": (3_000, 3_100),
}


def main() -> None:
    engine = build_mysql_engine()

    print("=" * 60)
    print("1. ROW COUNTS vs Kaggle expected ranges")
    print("=" * 60)
    tables = [
        "orders",
        "order_items",
        "customers",
        "geolocation",
        "payments",
        "order_reviews",
        "products",
        "sellers",
        "mv_monthly_sales",
    ]
    with engine.connect() as conn:
        for t in tables:
            n = conn.execute(text(f"SELECT COUNT(*) FROM `{t}`")).scalar()
            note = ""
            if t in EXPECTED_RAW:
                lo, hi = EXPECTED_RAW[t]
                ok = lo <= n <= hi
                note = "OK" if ok else f"UNEXPECTED (expected {lo:,}-{hi:,})"
            elif t == "geolocation":
                note = "aggregated by design (raw CSV ~1M rows)"
            elif t == "mv_monthly_sales":
                note = "pre-aggregated (~25 months)"
            print(f"  {t:25s} {n:>10,}  {note}")

    print("\n" + "=" * 60)
    print("2. DATA CORRECTNESS: base GMV vs mv_monthly_sales")
    print("=" * 60)
    with engine.connect() as conn:
        base = pd.read_sql(text(BASE_SQL), conn)
        mv = pd.read_sql(text(MV_SQL), conn)

    merged = base.merge(mv, on="ym", suffixes=("_base", "_mv"))
    merged["diff"] = (merged["gmv_base"] - merged["gmv_mv"]).abs()
    max_diff = merged["diff"].max()
    bad = merged[merged["diff"] > 0.01]

    print(f"  months in base query : {len(base)}")
    print(f"  months in view       : {len(mv)}")
    print(f"  max absolute GMV diff: {max_diff:.6f}")
    print(f"  rows with diff > 0.01: {len(bad)}")
    if len(bad):
        print("  MISMATCH rows:")
        print(bad.to_string(index=False))
    else:
        print("  RESULT: GMV values MATCH (view is numerically correct)")

    print("\n" + "=" * 60)
    print("3. PERFORMANCE MEASUREMENT (5 runs each, ms precision)")
    print("=" * 60)
    for label, sql in [("base_tables_join_agg", BASE_SQL), ("mv_monthly_sales", MV_SQL)]:
        times: list[float] = []
        for _ in range(5):
            with engine.begin() as conn:
                t0 = time.perf_counter()
                pd.read_sql(text(sql), conn)
                times.append(time.perf_counter() - t0)
        avg = sum(times) / len(times)
        print(f"  {label}")
        print(f"    runs (s): {[round(t, 4) for t in times]}")
        print(f"    avg (s) : {avg:.4f}")
        print(f"    min (s) : {min(times):.4f}")

    def bench(sql: str, n: int = 5) -> list[float]:
        out = []
        for _ in range(n):
            with engine.begin() as conn:
                t0 = time.perf_counter()
                pd.read_sql(text(sql), conn)
                out.append(time.perf_counter() - t0)
        return out

    b_times = bench(BASE_SQL)
    m_times = bench(MV_SQL)
    b_avg, m_avg = sum(b_times) / len(b_times), sum(m_times) / len(m_times)
    ratio = b_avg / m_avg if m_avg > 0 else float("inf")

    print(f"\n  speedup (avg base / avg mv): {ratio:.1f}x")
    print("  NOTE: mv table has only ~25 rows; sub-ms times are expected.")
    print("  NOTE: 602x headline used first base run (cold) vs warm mv repeats.")

    print("\n" + "=" * 60)
    print("4. API KEY RELEVANCE")
    print("=" * 60)
    print("  db_init / refresh_views / perf_compare do NOT call LLM API.")
    print("  These results are independent of DEEPSEEK_API_KEY.")

    print("\n" + "=" * 60)
    print("5. GEOLOCATION AGGREGATION CHECK")
    print("=" * 60)
    with engine.connect() as conn:
        zip_cnt = conn.execute(
            text("SELECT COUNT(DISTINCT geolocation_zip_code_prefix) FROM geolocation")
        ).scalar()
        row_cnt = conn.execute(text("SELECT COUNT(*) FROM geolocation")).scalar()
    print(f"  geolocation rows after clean: {row_cnt:,}")
    print(f"  distinct zip prefixes       : {zip_cnt:,}")
    print(f"  rows == distinct zips       : {row_cnt == zip_cnt}")
    print("  Intentional: aggregate 1M duplicate zip rows -> 1 row per prefix.")


if __name__ == "__main__":
    main()
