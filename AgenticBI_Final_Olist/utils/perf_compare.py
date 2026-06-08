from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
from sqlalchemy import text

from utils.db import build_mysql_engine
from utils.settings import ARTIFACTS_DIR


PERF_DIR = ARTIFACTS_DIR / "perf"

BASE_SQL = """
SELECT
  DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m') AS `year_month`,
  SUM(oi.price) AS total_gmv
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.order_status IN ('delivered', 'shipped', 'invoiced', 'approved')
GROUP BY DATE_FORMAT(o.order_purchase_timestamp, '%Y-%m')
ORDER BY `year_month`
"""

MV_SQL = "SELECT `year_month`, total_gmv FROM mv_monthly_sales ORDER BY `year_month`"


def timed_query(sql: str, *, runs: int = 3) -> tuple[pd.DataFrame, float, list[float]]:
    engine = build_mysql_engine()
    timings: list[float] = []
    df = pd.DataFrame()
    for _ in range(runs):
        with engine.begin() as conn:
            start = time.perf_counter()
            df = pd.read_sql(text(sql), conn)
            elapsed = time.perf_counter() - start
            timings.append(elapsed)
    return df, sum(timings) / len(timings), timings


def _save_chart(base_time: float, mv_time: float, speedup: float, out_path: Path) -> None:
    labels = ["Base tables\n(JOIN + GROUP BY)", "Pre-aggregation\n(mv_monthly_sales)"]
    values = [base_time, mv_time]
    colors = ["#E15759", "#4E79A7"]

    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.bar(labels, values, color=colors, width=0.55)
    ax.set_ylabel("Query time (seconds)")
    ax.set_title("Monthly GMV Query: Base Tables vs Pre-Aggregation View")
    ymax = max(values) * 1.25 if max(values) > 0 else 1.0
    ax.set_ylim(0, ymax)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + ymax * 0.02,
            f"{val:.3f}s",
            ha="center",
            va="bottom",
            fontsize=11,
            fontweight="bold",
        )

    ax.text(
        0.5,
        0.95,
        f"Speedup: {speedup:.1f}x faster with pre-aggregation",
        transform=ax.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5),
    )
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def run_benchmark(*, runs: int = 3) -> dict:
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    base_df, base_avg, base_runs = timed_query(BASE_SQL, runs=runs)
    mv_df, mv_avg, mv_runs = timed_query(MV_SQL, runs=runs)
    speedup = base_avg / mv_avg if mv_avg > 0 else float("inf")

    result = {
        "question": "月度 GMV 趋势（按月汇总销售额）",
        "base_sql": "orders JOIN order_items GROUP BY year_month",
        "mv_sql": "SELECT FROM mv_monthly_sales",
        "base_avg_sec": base_avg,
        "mv_avg_sec": mv_avg,
        "base_runs_sec": base_runs,
        "mv_runs_sec": mv_runs,
        "speedup_x": speedup,
        "base_rows": len(base_df),
        "mv_rows": len(mv_df),
        "timestamp": ts,
    }

    # CSV detail
    csv_path = PERF_DIR / f"perf_compare_{ts}.csv"
    pd.DataFrame(
        [
            {"query_type": "base_tables", "run": i + 1, "seconds": t}
            for i, t in enumerate(base_runs)
        ]
        + [{"query_type": "mv_monthly_sales", "run": i + 1, "seconds": t} for i, t in enumerate(mv_runs)]
        + [
            {
                "query_type": "summary",
                "run": 0,
                "seconds": base_avg,
                "note": "base_avg",
            },
            {
                "query_type": "summary",
                "run": 0,
                "seconds": mv_avg,
                "note": "mv_avg",
            },
        ]
    ).to_csv(csv_path, index=False, encoding="utf-8-sig")

    # Markdown report
    md_path = PERF_DIR / f"perf_compare_{ts}.md"
    md_content = f"""# 预聚合视图性能对比报告

生成时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 测试问题

{result["question"]}

## SQL 对比

| 方式 | SQL 说明 |
|------|----------|
| 原始表聚合 | `{result["base_sql"]}` |
| 预聚合视图 | `{result["mv_sql"]}` |

## 执行耗时（每项运行 {runs} 次取平均）

| 查询方式 | 平均耗时 (s) | 各次耗时 (s) | 返回行数 |
|----------|-------------|-------------|---------|
| 原始表 JOIN 聚合 | {base_avg:.4f} | {", ".join(f"{t:.4f}" for t in base_runs)} | {len(base_df)} |
| 预聚合视图 mv_monthly_sales | {mv_avg:.4f} | {", ".join(f"{t:.4f}" for t in mv_runs)} | {len(mv_df)} |

**加速比：{speedup:.2f}x**（预聚合视图相对原始表聚合）

## 结论

预聚合视图 `mv_monthly_sales` 将跨表 JOIN 与 GROUP BY 计算前置到离线刷新阶段，
Agent 在回答「月度销售趋势」「GMV 环比」类问题时可直接 `SELECT` 视图，
避免每次提问都对 `orders` + `order_items` 做全量实时聚合，查询耗时显著降低。

## 附件

- 对比柱状图：`perf_compare_chart.png`
- 原始数据：`{csv_path.name}`
"""
    md_path.write_text(md_content, encoding="utf-8")

    # Chart PNG (fixed name for report引用 + timestamped copy)
    chart_path = PERF_DIR / "perf_compare_chart.png"
    chart_ts_path = PERF_DIR / f"perf_compare_chart_{ts}.png"
    _save_chart(base_avg, mv_avg, speedup, chart_path)
    _save_chart(base_avg, mv_avg, speedup, chart_ts_path)

    result["csv_path"] = str(csv_path)
    result["md_path"] = str(md_path)
    result["chart_path"] = str(chart_path)
    return result


def main() -> None:
    print("Running pre-aggregation performance benchmark...")
    result = run_benchmark()
    print("Performance comparison (same question: monthly GMV):")
    print(f"- base tables aggregation: {result['base_avg_sec']:.3f}s (avg of 3 runs)")
    print(f"- pre-aggregation view (mv_monthly_sales): {result['mv_avg_sec']:.3f}s (avg of 3 runs)")
    print(f"- speedup: {result['speedup_x']:.2f}x")
    print(f"- chart saved: {result['chart_path']}")
    print(f"- report saved: {result['md_path']}")
    print(f"- csv saved: {result['csv_path']}")


if __name__ == "__main__":
    main()
