"""
C8: What-if 模拟分析模块 (What-if Simulation Module)

Estimates the platform-level review score change if the Top N
lowest-rated sellers' products were delisted.

Methodology:
  1. Identify Top N sellers with the lowest average review scores
     from mv_seller_perf (pre-aggregated seller performance view).
  2. Compute the current platform-wide average review score across
     all sellers.
  3. Remove those N sellers' orders and recalculate the platform
     average rating using a weighted mean formula.
  4. Return the estimated score uplift, affected order count,
     and actionable recommendations.

Assumptions & limitations:
  - This is a simplified model assuming independent seller effects.
    Real-world causal effects (substitution, seasonality) are not modeled.
  - Review scores are treated as cardinal values on [1, 5].
  - The "delist" action is simulated by removing all orders associated
    with those sellers from the scoring denominator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
from sqlalchemy import text

from utils.db import build_mysql_engine


@dataclass(frozen=True)
class WhatIfResult:
    """Structured output from the What-if simulation."""

    # Input parameters
    top_n: int
    current_platform_avg_score: float
    current_total_reviewed_orders: int

    # Affected sellers
    removed_seller_count: int
    removed_order_count: int
    removed_seller_ids: list[str] = field(default_factory=list)
    removed_seller_scores: list[float] = field(default_factory=list)

    # Post-delist estimates
    new_platform_avg_score: float = 0.0
    score_uplift: float = 0.0
    score_uplift_pct: float = 0.0

    # Status
    success: bool = True
    message: str = ""


def _fetch_seller_perf_data(top_n: int) -> Optional[pd.DataFrame]:
    """
    Fetch seller-level review aggregation from mv_seller_perf.
    Returns columns: seller_id, total_orders, total_gmv, avg_review_score
    """
    engine = build_mysql_engine()
    sql = text("""
        SELECT
            seller_id,
            SUM(total_orders) AS total_orders,
            SUM(total_gmv) AS total_gmv,
            AVG(avg_review_score) AS avg_review_score
        FROM mv_seller_perf
        GROUP BY seller_id
        HAVING total_orders >= 5
    """)
    with engine.begin() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return None
    return df


def run_whatif_delist_bad_sellers(
    top_n: int = 20,
    min_orders: int = 5,
) -> WhatIfResult:
    """
    Simulate the effect of delisting the Top N worst-rated sellers.

    Args:
        top_n: Number of worst-rated sellers to hypothetically remove.
        min_orders: Minimum order count for a seller to be considered.

    Returns:
        WhatIfResult with pre/post delist score estimates.
    """
    df = _fetch_seller_perf_data(top_n)
    if df is None or df.empty:
        return WhatIfResult(
            top_n=top_n,
            current_platform_avg_score=0.0,
            current_total_reviewed_orders=0,
            removed_seller_count=0,
            removed_order_count=0,
            success=False,
            message="No seller performance data available (mv_seller_perf may be empty).",
        )

    # Current platform weighted average review score
    df = df[df["total_orders"] >= min_orders].copy()
    if df.empty:
        return WhatIfResult(
            top_n=top_n,
            current_platform_avg_score=0.0,
            current_total_reviewed_orders=0,
            removed_seller_count=0,
            removed_order_count=0,
            success=False,
            message=f"No sellers meet the min_orders={min_orders} threshold.",
        )

    total_orders_all = df["total_orders"].sum()
    total_weighted_score = (df["avg_review_score"] * df["total_orders"]).sum()
    current_avg = total_weighted_score / max(total_orders_all, 1)

    # Identify Top N worst sellers (lowest avg_review_score, then most orders)
    worst = df.nsmallest(top_n, columns=["avg_review_score", "total_orders"])
    n_removed = len(worst)

    removed_orders = worst["total_orders"].sum()
    removed_weighted_score = (worst["avg_review_score"] * worst["total_orders"]).sum()

    remaining_orders = total_orders_all - removed_orders
    remaining_weighted_score = total_weighted_score - removed_weighted_score

    if remaining_orders <= 0:
        return WhatIfResult(
            top_n=top_n,
            current_platform_avg_score=round(current_avg, 3),
            current_total_reviewed_orders=int(total_orders_all),
            removed_seller_count=n_removed,
            removed_order_count=int(removed_orders),
            removed_seller_ids=worst["seller_id"].astype(str).tolist(),
            removed_seller_scores=worst["avg_review_score"].round(3).tolist(),
            new_platform_avg_score=0.0,
            score_uplift=0.0,
            score_uplift_pct=0.0,
            success=True,
            message="After removal, no orders remain — platform score undefined.",
        )

    new_avg = remaining_weighted_score / remaining_orders
    uplift = new_avg - current_avg
    uplift_pct = (uplift / current_avg) * 100 if current_avg > 0 else 0.0

    return WhatIfResult(
        top_n=top_n,
        current_platform_avg_score=round(current_avg, 3),
        current_total_reviewed_orders=int(total_orders_all),
        removed_seller_count=n_removed,
        removed_order_count=int(removed_orders),
        removed_seller_ids=worst["seller_id"].astype(str).tolist(),
        removed_seller_scores=worst["avg_review_score"].round(3).tolist(),
        new_platform_avg_score=round(new_avg, 3),
        score_uplift=round(uplift, 3),
        score_uplift_pct=round(uplift_pct, 2),
        success=True,
        message="What-if simulation completed successfully.",
    )


def format_whatif_report(result: WhatIfResult) -> str:
    """
    Produce a human-readable Chinese-language report from a WhatIfResult.
    Suitable for display in the Web UI or inclusion in the decision agent input.
    """
    if not result.success:
        return f"⚠️ What-if 模拟未完成：{result.message}"

    lines = [
        "=" * 60,
        f"  What-if 模拟分析：下架 Top {result.top_n} 差评卖家对平台评分的影响",
        "=" * 60,
        "",
        f"📊 当前平台状态：",
        f"   - 平台整体平均评分：{result.current_platform_avg_score:.3f} / 5.0",
        f"   - 被评订单总数：{result.current_total_reviewed_orders:,}",
        "",
        f"🗑️  拟下架卖家（Top {result.top_n} 最低评分）：",
        f"   - 涉及卖家数：{result.removed_seller_count}",
        f"   - 涉及订单数：{result.removed_order_count:,}",
        f"   - 涉及订单占比：{result.removed_order_count / max(result.current_total_reviewed_orders, 1) * 100:.1f}%",
    ]

    if result.removed_seller_ids:
        pairs = list(zip(result.removed_seller_ids, result.removed_seller_scores))
        for i, (sid, score) in enumerate(pairs[:10], 1):
            lines.append(f"     {i:2d}. {sid}  (平均评分: {score:.2f})")
        if len(pairs) > 10:
            lines.append(f"     ... 还有 {len(pairs) - 10} 个卖家")

    lines.extend([
        "",
        f"📈 下架后预估：",
        f"   - 新平台平均评分：{result.new_platform_avg_score:.3f} / 5.0",
        f"   - 评分提升：+{result.score_uplift:.3f} 分",
        f"   - 评分提升幅度：+{result.score_uplift_pct:.2f}%",
        "",
        f"💡 解读：",
        f"   移除 Top {result.top_n} 低评分卖家后，平台整体评分预计从 "
        f"{result.current_platform_avg_score:.3f} 提升至 {result.new_platform_avg_score:.3f}，"
        f"提升 {result.score_uplift:.3f} 分（{result.score_uplift_pct:.1f}%）。"
        f"需要注意，下架卖家会影响 {result.removed_order_count:,} 个历史订单的"
        f"关联数据，实际操作应结合卖家改善计划逐步推进。",
        "",
        "=" * 60,
    ])
    return "\n".join(lines)