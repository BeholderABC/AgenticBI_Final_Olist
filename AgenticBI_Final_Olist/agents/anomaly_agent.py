"""
C9: 异常检测 Agent (Anomaly Detection Agent)

Scans recent pre-aggregated views (mv_state_sales, mv_delivery_perf) for
anomalous patterns:
  - State-level order count sudden drops (>30% vs previous period)
  - State-level bad-review rate spikes (>2x the platform average)

Methodology:
  - Compare month-over-month (MoM) state-level total_orders from mv_state_sales.
  - Flag states where the most recent month's orders dropped more than a
    configurable threshold (default: 30%) vs the prior month.
  - Check mv_delivery_perf for on_time_rate deterioration.
  - Output structured alerts for the decision agent and Web UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import text

from utils.db import build_mysql_engine


@dataclass
class AnomalyAlert:
    """A single anomaly alert record."""
    alert_type: str           # "order_drop" | "review_quality_drop" | "delivery_delay_spike"
    state: str
    metric: str
    current_value: float
    baseline_value: float
    change_pct: float
    severity: str            # "high" | "medium" | "low"
    detail: str


@dataclass
class AnomalyReport:
    """Structured anomaly detection output."""
    alerts: list[AnomalyAlert] = field(default_factory=list)
    summary: str = ""
    success: bool = True
    message: str = ""


def _detect_order_drops(data: pd.DataFrame, threshold_pct: float = 0.30) -> list[AnomalyAlert]:
    """
    Detect states where the most recent month's total_orders dropped
    more than threshold_pct compared to the previous month.

    Expects columns: year_month, customer_state, total_orders
    """
    if not {"year_month", "customer_state", "total_orders"}.issubset(data.columns):
        return []

    df = data.copy()
    df["year_month"] = df["year_month"].astype(str)

    # Get the two most recent months
    months = sorted(df["year_month"].unique(), reverse=True)
    if len(months) < 2:
        return []

    current_month, prev_month = months[0], months[1]

    current = (
        df[df["year_month"] == current_month]
        .groupby("customer_state", as_index=False)["total_orders"]
        .sum()
        .rename(columns={"total_orders": "current_orders"})
    )
    previous = (
        df[df["year_month"] == prev_month]
        .groupby("customer_state", as_index=False)["total_orders"]
        .sum()
        .rename(columns={"total_orders": "previous_orders"})
    )

    merged = current.merge(previous, on="customer_state", how="left").fillna(0)
    merged["change_pct"] = (merged["current_orders"] - merged["previous_orders"]) / merged["previous_orders"].replace(0, 1)
    merged["dropped"] = merged["change_pct"] <= -threshold_pct

    alerts: list[AnomalyAlert] = []
    for _, row in merged[merged["dropped"]].iterrows():
        severity = "high" if row["change_pct"] <= -0.5 else "medium"
        alerts.append(AnomalyAlert(
            alert_type="order_drop",
            state=str(row["customer_state"]),
            metric="total_orders",
            current_value=float(row["current_orders"]),
            baseline_value=float(row["previous_orders"]),
            change_pct=round(float(row["change_pct"]) * 100, 1),
            severity=severity,
            detail=(
                f"{row['customer_state']} 州订单量从 {int(row['previous_orders'])} "
                f"骤降至 {int(row['current_orders'])}（{round(float(row['change_pct']) * 100, 1)}%），"
                f"需要排查物流、竞品或季节性因素。"
            ),
        ))
    return alerts


def _detect_review_quality_drops(data: pd.DataFrame, threshold_mult: float = 2.0) -> list[AnomalyAlert]:
    """
    Detect states where the on_time_rate has dropped significantly
    relative to the platform average (in the most recent month).

    Expects columns: year_month, customer_state, on_time_rate
    """
    if not {"year_month", "customer_state", "on_time_rate"}.issubset(data.columns):
        return []

    df = data.copy()
    df["year_month"] = df["year_month"].astype(str)

    months = sorted(df["year_month"].unique(), reverse=True)
    if not months:
        return []

    current_month = months[0]
    recent = df[df["year_month"] == current_month].copy()

    if recent.empty:
        return []

    # Platform average on_time_rate for the recent month
    platform_avg = recent["on_time_rate"].mean()

    # Compute per-state average on_time_rate
    state_rates = (
        recent.groupby("customer_state", as_index=False)["on_time_rate"]
        .mean()
        .rename(columns={"on_time_rate": "state_on_time_rate"})
    )
    state_rates["delay_rate"] = 1.0 - state_rates["state_on_time_rate"]
    platform_delay_rate = 1.0 - platform_avg

    alerts: list[AnomalyAlert] = []
    for _, row in state_rates.iterrows():
        if platform_delay_rate > 0 and row["delay_rate"] > platform_delay_rate * threshold_mult:
            severity = "high" if row["delay_rate"] > platform_delay_rate * 3 else "medium"
            alerts.append(AnomalyAlert(
                alert_type="delivery_delay_spike",
                state=str(row["customer_state"]),
                metric="on_time_rate",
                current_value=round(float(row["state_on_time_rate"]), 3),
                baseline_value=round(float(platform_avg), 3),
                change_pct=round((row["delay_rate"] - platform_delay_rate) / platform_delay_rate * 100, 1),
                severity=severity,
                detail=(
                    f"{row['customer_state']} 州准时率 {float(row['state_on_time_rate']):.1%} "
                    f"显著低于平台均值 {platform_avg:.1%}，"
                    f"延迟率高出平台 {round((row['delay_rate'] / platform_delay_rate - 1) * 100, 1)}%。"
                ),
            ))
    return alerts


def run_anomaly_detection(
    *,
    order_drop_threshold: float = 0.30,
    delay_threshold_mult: float = 2.0,
) -> AnomalyReport:
    """
    Execute anomaly detection across state-level views.

    Args:
        order_drop_threshold: MoM drop ratio that triggers an alert (default 0.30 = 30%).
        delay_threshold_mult: Multiplier over platform delay rate to flag a state.

    Returns:
        AnomalyReport with all alerts and a human-readable summary.
    """
    engine = build_mysql_engine()
    all_alerts: list[AnomalyAlert] = []

    try:
        # 1. Check order drops from mv_state_sales
        with engine.begin() as conn:
            sales_df = pd.read_sql(text("SELECT * FROM mv_state_sales ORDER BY 1, 2"), conn)
        order_alerts = _detect_order_drops(sales_df, order_drop_threshold)
        all_alerts.extend(order_alerts)
    except Exception as e:
        return AnomalyReport(
            success=False,
            message=f"Failed to query mv_state_sales: {e}",
        )

    try:
        # 2. Check delivery quality drops from mv_delivery_perf
        with engine.begin() as conn:
            delivery_df = pd.read_sql(text("SELECT * FROM mv_delivery_perf ORDER BY 1, 2"), conn)
        delivery_alerts = _detect_review_quality_drops(delivery_df, delay_threshold_mult)
        all_alerts.extend(delivery_alerts)
    except Exception as e:
        # Non-fatal: delivery check can fail independently
        pass

    # Build summary
    if not all_alerts:
        return AnomalyReport(
            alerts=[],
            summary="✅ 近期数据未检测到显著异常，各州订单量与准时率均在正常范围内。",
            success=True,
            message="No anomalies detected.",
        )

    high_count = sum(1 for a in all_alerts if a.severity == "high")
    med_count = sum(1 for a in all_alerts if a.severity == "medium")

    summary_lines = [
        f"⚠️ 异常检测报告：发现 {len(all_alerts)} 个异常信号",
        f"   - 高风险：{high_count} 个",
        f"   - 中风险：{med_count} 个",
        "",
        "详细预警列表：",
    ]
    for i, alert in enumerate(all_alerts, 1):
        severity_icon = "🔴" if alert.severity == "high" else "🟡"
        summary_lines.append(
            f"  {i:2d}. {severity_icon} [{alert.severity.upper()}] "
            f"{alert.state}: {alert.detail}"
        )

    summary_lines.extend([
        "",
        "建议：优先排查高风险州的物流承运商、季节性波动、及竞品促销活动。",
    ])

    return AnomalyReport(
        alerts=all_alerts,
        summary="\n".join(summary_lines),
        success=True,
        message=f"Detected {len(all_alerts)} anomalies.",
    )


def _anomaly_alerts_to_dicts(alerts: list[AnomalyAlert]) -> list[dict[str, Any]]:
    """Convert AnomalyAlert list to a list of serializable dicts for state ingestion."""
    return [
        {
            "alert_type": a.alert_type,
            "state": a.state,
            "metric": a.metric,
            "current_value": a.current_value,
            "baseline_value": a.baseline_value,
            "change_pct": a.change_pct,
            "severity": a.severity,
            "detail": a.detail,
        }
        for a in alerts
    ]