from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
from wordcloud import WordCloud

from utils.settings import ARTIFACTS_DIR


@dataclass(frozen=True)
class VizResult:
    paths: list[str]


def _ensure_artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


def plot_monthly_sales_with_forecast(monthly: pd.DataFrame, forecast: pd.DataFrame) -> str:
    out_dir = _ensure_artifacts_dir()
    df = monthly.copy()
    df["ds"] = pd.to_datetime(df["year_month"] + "-01")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df["ds"], y=df["total_gmv"], mode="lines+markers", name="GMV (monthly)"))
    fig.add_trace(go.Scatter(x=forecast["ds"], y=forecast["yhat"], mode="lines+markers", name="Forecast (weekly)"))
    fig.add_trace(
        go.Scatter(
            x=list(forecast["ds"]) + list(forecast["ds"][::-1]),
            y=list(forecast["yhat_upper"]) + list(forecast["yhat_lower"][::-1]),
            fill="toself",
            fillcolor="rgba(99,110,250,0.2)",
            line=dict(color="rgba(255,255,255,0)"),
            hoverinfo="skip",
            name="80% interval",
        )
    )
    fig.update_layout(title="Monthly GMV + 6-week Forecast", xaxis_title="Date", yaxis_title="GMV")
    path = out_dir / "ts_gmv_forecast.png"
    if path.exists():
        return str(path)
    fig.write_image(str(path), scale=2)
    return str(path)


def plot_state_sales_map(state_sales: pd.DataFrame) -> str:
    out_dir = _ensure_artifacts_dir()
    df = state_sales.copy()
    agg = (
        df.groupby("customer_state", as_index=False)
        .agg(total_gmv=("total_gmv", "sum"), total_orders=("total_orders", "sum"))
        .sort_values("total_gmv", ascending=False)
    )
    fig = px.bar(
        agg.head(27),
        x="customer_state",
        y="total_gmv",
        title="State GMV distribution",
    )
    path = out_dir / "geo_state_gmv_bar.png"
    if path.exists():
        return str(path)
    fig.write_image(str(path), scale=2)
    return str(path)


def plot_geo_bubble_by_state(state_geo: pd.DataFrame) -> str:
    """
    A real geo bubble chart using lat/lng from geolocation aggregated by state.
    Required columns: customer_state, lat, lng, total_gmv, total_orders
    """
    out_dir = _ensure_artifacts_dir()
    df = state_geo.copy()
    fig = px.scatter_geo(
        df,
        lat="lat",
        lon="lng",
        size="total_gmv",
        color="total_orders",
        hover_name="customer_state",
        hover_data={"total_gmv": ":.2f", "total_orders": True, "lat": False, "lng": False},
        title="Brazil Geo Bubble: GMV(size) & Orders(color) by State",
        scope="south america",
    )
    fig.update_geos(fitbounds="locations", visible=True)
    path = out_dir / "geo_bubble_state.png"
    if path.exists():
        return str(path)
    fig.write_image(str(path), scale=2)
    return str(path)


def plot_payment_matrix(payment: pd.DataFrame) -> str:
    out_dir = _ensure_artifacts_dir()
    df = payment.copy()
    # heatmap: payment_type x avg_installments (rounded) with total_transactions
    df["installments_round"] = df["avg_installments"].round().astype(int)
    pivot = (
        df.pivot_table(
            index="payment_type",
            columns="installments_round",
            values="total_transactions",
            aggfunc="sum",
            fill_value=0,
        )
        .sort_index()
    )
    fig = px.imshow(pivot, aspect="auto", title="Payment type × installments matrix (transactions)")
    path = out_dir / "heatmap_payment_installments.png"
    if path.exists():
        return str(path)
    fig.write_image(str(path), scale=2)
    return str(path)


def plot_weight_vs_freight(scatter_df: pd.DataFrame) -> str:
    out_dir = _ensure_artifacts_dir()
    df = scatter_df.copy()
    fig = px.scatter(
        df,
        x="product_weight_g",
        y="freight_value",
        size="order_cnt",
        color="order_status",
        hover_data=["product_category_english"],
        title="Weight vs Freight (bubble size=orders)",
    )
    path = out_dir / "scatter_weight_freight.png"
    if path.exists():
        return str(path)
    fig.write_image(str(path), scale=2)
    return str(path)


def plot_category_top(category_sales: pd.DataFrame) -> str:
    out_dir = _ensure_artifacts_dir()
    agg = (
        category_sales.groupby("product_category_english", as_index=False)
        .agg(total_gmv=("total_gmv", "sum"))
        .sort_values("total_gmv", ascending=False)
        .head(15)
    )
    fig = px.bar(agg, x="total_gmv", y="product_category_english", orientation="h", title="Top categories by GMV")
    path = out_dir / "bar_top_categories.png"
    if path.exists():
        return str(path)
    fig.write_image(str(path), scale=2)
    return str(path)


def plot_delivery_perf(delivery: pd.DataFrame) -> str:
    out_dir = _ensure_artifacts_dir()
    agg = (
        delivery.groupby("customer_state", as_index=False)
        .agg(avg_delivery_days=("avg_delivery_days", "mean"), on_time_rate=("on_time_rate", "mean"))
        .sort_values("avg_delivery_days", ascending=False)
        .head(15)
    )
    fig = px.bar(
        agg,
        x="customer_state",
        y="avg_delivery_days",
        title="Top delayed states (avg delivery days)",
    )
    path = out_dir / "bar_delivery_days.png"
    if path.exists():
        return str(path)
    fig.write_image(str(path), scale=2)
    return str(path)


def plot_negative_wordcloud(neg_terms: list[str]) -> str:
    out_dir = _ensure_artifacts_dir()
    text = " ".join([t.replace(" ", "_") for t in neg_terms]) or "no_data"
    wc = WordCloud(width=1200, height=600, background_color="white").generate(text)
    fig = plt.figure(figsize=(12, 6))
    plt.imshow(wc, interpolation="bilinear")
    plt.axis("off")
    path = out_dir / "wordcloud_negative.png"
    if path.exists():
        return str(path)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def build_default_viz_bundle(tables: dict[str, pd.DataFrame], forecast_df: pd.DataFrame | None) -> VizResult:
    paths: list[str] = []

    if "mv_monthly_sales" in tables and forecast_df is not None:
        paths.append(plot_monthly_sales_with_forecast(tables["mv_monthly_sales"], forecast_df))
    if "mv_state_sales" in tables:
        paths.append(plot_state_sales_map(tables["mv_state_sales"]))
    if "state_geo" in tables:
        paths.append(plot_geo_bubble_by_state(tables["state_geo"]))
    if "mv_payment_dist" in tables:
        paths.append(plot_payment_matrix(tables["mv_payment_dist"]))
    if "mv_category_sales" in tables:
        paths.append(plot_category_top(tables["mv_category_sales"]))
    if "mv_delivery_perf" in tables:
        paths.append(plot_delivery_perf(tables["mv_delivery_perf"]))
    if "scatter_weight_freight" in tables:
        paths.append(plot_weight_vs_freight(tables["scatter_weight_freight"]))
    if "_nlp_negative_terms" in tables:
        neg_terms = tables["_nlp_negative_terms"]["term"].dropna().astype(str).tolist()
        paths.append(plot_negative_wordcloud(neg_terms))

    return VizResult(paths=paths)


def build_viz_bundle_for_charts(
    tables: dict[str, pd.DataFrame],
    forecast_df: pd.DataFrame | None,
    *,
    chart_ids: list[str],
) -> VizResult:
    """
    Build only the requested charts (in order). Unknown/unsupported ids are ignored.
    Empty chart_ids => no charts.
    """
    if not chart_ids:
        return VizResult(paths=[])

    paths: list[str] = []
    for cid in chart_ids:
        try:
            if cid == "ts_gmv_forecast":
                if "mv_monthly_sales" in tables and forecast_df is not None:
                    paths.append(plot_monthly_sales_with_forecast(tables["mv_monthly_sales"], forecast_df))
            elif cid == "bar_state_gmv":
                if "mv_state_sales" in tables:
                    paths.append(plot_state_sales_map(tables["mv_state_sales"]))
            elif cid == "geo_bubble_state":
                if "mv_state_geo" in tables:
                    paths.append(plot_geo_bubble_by_state(tables["mv_state_geo"]))
            elif cid == "heatmap_payment_installments":
                if "mv_payment_dist" in tables:
                    paths.append(plot_payment_matrix(tables["mv_payment_dist"]))
            elif cid == "bar_top_categories":
                if "mv_category_sales" in tables:
                    paths.append(plot_category_top(tables["mv_category_sales"]))
            elif cid == "bar_delivery_days":
                if "mv_delivery_perf" in tables:
                    paths.append(plot_delivery_perf(tables["mv_delivery_perf"]))
            elif cid == "scatter_weight_freight":
                if "scatter_weight_freight" in tables:
                    paths.append(plot_weight_vs_freight(tables["scatter_weight_freight"]))
            elif cid == "wordcloud_negative":
                if "_nlp_negative_terms" in tables:
                    neg_terms = tables["_nlp_negative_terms"]["term"].dropna().astype(str).tolist()
                    paths.append(plot_negative_wordcloud(neg_terms))
        except Exception:
            # best-effort: one chart failing shouldn't kill the run
            continue

    return VizResult(paths=paths)

