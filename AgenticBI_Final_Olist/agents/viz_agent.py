from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import plotly.express as px
import plotly.graph_objects as go
from wordcloud import WordCloud
import seaborn as sns
import folium
from folium.plugins import HeatMap

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
    # heatmap: payment_type x installment bins with total_transactions
    # Bin installments into coarser groups to avoid sparse all-black heatmap.
    df["install_bin"] = pd.cut(
        df["avg_installments"].round().astype(int),
        bins=[0, 2, 4, 6, 8, 12, 100],
        labels=["1-2", "3-4", "5-6", "7-8", "9-12", "12+"],
        right=True,
    )
    pivot = (
        df.pivot_table(
            index="payment_type",
            columns="install_bin",
            values="total_transactions",
            aggfunc="sum",
            fill_value=0,
        )
        .sort_index()
    )
    # Use a perceptually uniform colormap with explicit min/max to avoid washing out
    max_val = pivot.max().max() if not pivot.empty else 1
    fig = px.imshow(
        pivot,
        aspect="auto",
        title="Payment type × installments heatmap (transactions)",
        color_continuous_scale="Blues",
        zmin=0,
        zmax=float(max_val),
        text_auto=False,
    )
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


# ===========================================================================
# C1: 品类×平均评分热力矩阵图 (Category × Rating Heatmap Matrix)
# ===========================================================================

def plot_category_rating_heatmap(category_review_df: pd.DataFrame) -> str:
    """
    Generate a category × rating heatmap matrix from diagnostic_bad_review_categories
    or any DataFrame with categories and avg review scores.

    Expected columns: product_category_english, avg_review_score, reviewed_orders,
                      bad_review_rate (optional)
    """
    out_dir = _ensure_artifacts_dir()
    df = category_review_df.copy()

    if "product_category_english" not in df.columns:
        return ""

    if "avg_review_score" in df.columns:
        df["rating_bin"] = df["avg_review_score"].round(1)
        pivot = df.pivot_table(
            index="product_category_english",
            columns="rating_bin",
            values="reviewed_orders",
            aggfunc="sum",
            fill_value=0,
        )
    else:
        return ""

    if pivot.empty:
        return ""

    # Keep top 15 categories by total reviewed orders
    pivot["_total"] = pivot.sum(axis=1)
    pivot = pivot.sort_values("_total", ascending=False).head(15)
    pivot = pivot.drop(columns=["_total"])

    fig, ax = plt.subplots(figsize=(14, 10))
    sns.heatmap(
        pivot,
        annot=True,
        fmt=".0f",
        cmap="YlOrRd",
        linewidths=0.5,
        ax=ax,
        cbar_kws={"label": "Reviewed Orders"},
    )
    ax.set_title("Category × Average Rating Heatmap (Reviewed Orders per Rating Bin)", fontsize=14)
    ax.set_xlabel("Average Review Score (rounded)")
    ax.set_ylabel("Product Category")
    fig.tight_layout()

    path = out_dir / "heatmap_category_rating.png"
    if path.exists():
        plt.close(fig)
        return str(path)
    fig.savefig(str(path), dpi=200, bbox_inches="tight")
    plt.close(fig)
    return str(path)


# ===========================================================================
# C2: 好评/差评对比双词云 (Positive vs Negative Dual Word Cloud)
# ===========================================================================

def plot_dual_wordcloud(
    pos_terms: list[str],
    neg_terms: list[str],
) -> str:
    """
    Generate a side-by-side comparison word cloud: positive vs negative reviews.

    Args:
        pos_terms: Top TF-IDF terms from positive reviews (score >= 4)
        neg_terms: Top TF-IDF terms from negative reviews (score <= 2)
    """
    out_dir = _ensure_artifacts_dir()
    pos_text = " ".join([t.replace(" ", "_") for t in pos_terms]) or "no_positive_data"
    neg_text = " ".join([t.replace(" ", "_") for t in neg_terms]) or "no_negative_data"

    fig, axes = plt.subplots(1, 2, figsize=(20, 8))

    # Positive word cloud (green tones)
    wc_pos = WordCloud(
        width=1000,
        height=500,
        background_color="white",
        colormap="Greens",
        max_words=50,
    ).generate(pos_text)
    axes[0].imshow(wc_pos, interpolation="bilinear")
    axes[0].set_title("Good Reviews (Score >= 4) Key Themes", fontsize=14, color="green")
    axes[0].axis("off")

    # Negative word cloud (red tones)
    wc_neg = WordCloud(
        width=1000,
        height=500,
        background_color="white",
        colormap="Reds",
        max_words=50,
    ).generate(neg_text)
    axes[1].imshow(wc_neg, interpolation="bilinear")
    axes[1].set_title("Bad Reviews (Score <= 2) Key Themes", fontsize=14, color="red")
    axes[1].axis("off")

    fig.tight_layout()
    path = out_dir / "wordcloud_pos_vs_neg.png"
    if path.exists():
        plt.close(fig)
        return str(path)
    fig.savefig(str(path), dpi=200, bbox_inches="tight")
    plt.close(fig)
    return str(path)


# ===========================================================================
# C3: 各州客单价柱状图 (State-Level Average Basket Value Bar Chart)
# ===========================================================================

def plot_state_avg_basket(state_sales: pd.DataFrame) -> str:
    """
    Generate a bar chart of average basket value (AOV) per state.
    Computed from mv_state_sales: avg_basket = total_gmv / total_orders.

    Required columns: customer_state, total_gmv, total_orders
    """
    out_dir = _ensure_artifacts_dir()
    df = state_sales.copy()

    if not {"customer_state", "total_gmv", "total_orders"}.issubset(set(df.columns)):
        return ""

    agg = (
        df.groupby("customer_state", as_index=False)
        .agg(total_gmv=("total_gmv", "sum"), total_orders=("total_orders", "sum"))
    )
    agg["avg_basket"] = agg["total_gmv"] / agg["total_orders"].replace(0, 1)
    agg = agg.sort_values("avg_basket", ascending=False).head(20)

    fig = px.bar(
        agg,
        x="customer_state",
        y="avg_basket",
        title="Average Basket Value (AOV) by State (R$)",
        text=agg["avg_basket"].round(1),
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(xaxis_title="State", yaxis_title="Average Basket (R$)")
    path = out_dir / "bar_state_avg_basket.png"
    if path.exists():
        return str(path)
    fig.write_image(str(path), scale=2)
    return str(path)


# ===========================================================================
# C4: Folium 巴西州级地理热力图 (Brazilian State Geographic Heatmap)
# ===========================================================================

# Brazilian state centroid coordinates (lat, lng) for all 27 states
_BRAZIL_STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AC": (-9.0238, -70.8120),
    "AL": (-9.5713, -36.7820),
    "AP": (0.9020, -52.0030),
    "AM": (-3.4168, -65.8561),
    "BA": (-12.5797, -41.7007),
    "CE": (-5.4984, -39.3206),
    "DF": (-15.7801, -47.9292),
    "ES": (-19.1834, -40.3089),
    "GO": (-15.8270, -49.8362),
    "MA": (-4.9609, -45.2744),
    "MT": (-12.6819, -56.9211),
    "MS": (-20.7722, -54.7852),
    "MG": (-18.5122, -44.5550),
    "PA": (-3.7900, -52.4800),
    "PB": (-7.2399, -36.7819),
    "PR": (-25.2521, -52.0215),
    "PE": (-8.0476, -34.8770),
    "PI": (-7.7183, -42.7289),
    "RJ": (-22.9068, -43.1729),
    "RN": (-5.4026, -36.9541),
    "RS": (-30.0346, -51.2177),
    "RO": (-10.8300, -63.3400),
    "RR": (2.7376, -60.7300),
    "SC": (-27.2423, -50.2189),
    "SP": (-23.5505, -46.6333),
    "SE": (-10.5741, -37.3857),
    "TO": (-10.1753, -48.2982),
}


def plot_folium_geo_heatmap(state_sales: pd.DataFrame) -> str:
    """
    Generate an interactive Folium heatmap on a full Brazil map using
    state-level aggregate data weighted by GMV.

    Required columns: customer_state, total_gmv, total_orders

    Output: saves folium_geo_heatmap.html (interactive) and attempts PNG.
            Returns the HTML path as the primary deliverable.
    """
    out_dir = _ensure_artifacts_dir()
    df = state_sales.copy()

    if not {"customer_state", "total_gmv"}.issubset(set(df.columns)):
        return ""

    agg = (
        df.groupby("customer_state", as_index=False)
        .agg(total_gmv=("total_gmv", "sum"), total_orders=("total_orders", "sum"))
    )

    # Build heat data: [lat, lng, weight] for each state
    heat_data: list[list[float]] = []
    for _, row in agg.iterrows():
        state = str(row["customer_state"]).strip().upper()
        centroid = _BRAZIL_STATE_CENTROIDS.get(state)
        if centroid is None:
            continue
        lat, lng = centroid
        # Scale GMV to millions for sensible heatmap radius
        weight = float(row["total_gmv"]) / 1_000_000
        heat_data.append([lat, lng, weight])

    if not heat_data:
        return ""

    # Create the map centered on Brazil
    m = folium.Map(
        location=[-10.0, -52.0],
        zoom_start=4,
        tiles="CartoDB positron",
    )

    HeatMap(
        heat_data,
        radius=35,
        blur=20,
        max_zoom=6,
        gradient={0.2: "blue", 0.4: "cyan", 0.6: "lime", 0.8: "yellow", 1.0: "red"},
    ).add_to(m)

    # Add state labels as CircleMarkers
    for _, row in agg.iterrows():
        state = str(row["customer_state"]).strip().upper()
        centroid = _BRAZIL_STATE_CENTROIDS.get(state)
        if centroid is None:
            continue
        lat, lng = centroid
        folium.CircleMarker(
            location=[lat, lng],
            radius=4,
            color="black",
            fill=True,
            fill_opacity=0.6,
            tooltip=f"{state}: GMV R${row['total_gmv']:,.0f}",
        ).add_to(m)

    # Save interactive HTML (primary output)
    html_path = out_dir / "folium_geo_heatmap.html"
    m.save(str(html_path))

    # Attempt PNG export if selenium headless is available
    png_path = out_dir / "folium_geo_heatmap.png"
    if not png_path.exists():
        try:
            # folium's built-in _to_png requires selenium + webdriver;
            # best-effort, silently ignore on failure.
            img_data = m._to_png(5)
            if img_data:
                png_path.write_bytes(img_data)
        except Exception:
            pass

    if png_path.exists():
        return str(png_path)
    return str(html_path)


# ===========================================================================
# C5: 扩展散点图 — 重量+尺寸 vs 运费
#      Expands weight scatter to also include product dimensions (L×W×H)
# ===========================================================================

def plot_weight_dims_vs_freight(scatter_df: pd.DataFrame) -> str:
    """
    Generate a multi-panel scatter showing product weight, length, height, width
    vs freight value, to reveal dimensional weight pricing effects.

    Expected columns (from extended SQL in graph.py):
    product_weight_g, product_length_cm, product_height_cm, product_width_cm,
    freight_value, order_cnt, order_status, product_category_english
    """
    out_dir = _ensure_artifacts_dir()
    df = scatter_df.copy()

    dim_cols = [
        c for c in ["product_length_cm", "product_height_cm", "product_width_cm"]
        if c in df.columns
    ]
    if not dim_cols:
        # Fallback to simple weight-only scatter if dimensions unavailable
        return plot_weight_vs_freight(df)

    metrics = ["product_weight_g"] + [c for c in dim_cols if c in df.columns]
    metrics = metrics[:4]  # at most 4 subplots

    n = len(metrics)
    cols = min(2, n)
    rows = (n + 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(7 * cols, 6 * rows), squeeze=False)
    axes_flat = axes.flatten()

    for i, col_name in enumerate(metrics):
        ax = axes_flat[i]
        sc = ax.scatter(
            df[col_name],
            df["freight_value"],
            c=df["order_cnt"].fillna(1),
            cmap="viridis",
            alpha=0.6,
            s=20,
            edgecolors="none",
        )
        cbar = fig.colorbar(sc, ax=ax)
        cbar.set_label("Order Count")
        display_name = col_name.replace("product_", "").replace("_", " ").title()
        ax.set_xlabel(display_name)
        ax.set_ylabel("Freight Value (R$)")
        ax.set_title(f"{display_name} vs Freight")

    # Hide unused subplots
    for j in range(i + 1, len(axes_flat)):
        axes_flat[j].set_visible(False)

    fig.suptitle("Product Weight & Dimensions vs Freight Value", fontsize=16, y=1.02)
    fig.tight_layout()

    path = out_dir / "scatter_weight_dims_vs_freight.png"
    if path.exists():
        plt.close(fig)
        return str(path)
    fig.savefig(str(path), dpi=200, bbox_inches="tight")
    plt.close(fig)
    return str(path)


# ===========================================================================
# Default viz bundle & chart dispatcher (updated with C1-C5)
# ===========================================================================

def build_default_viz_bundle(tables: dict[str, pd.DataFrame], forecast_df: pd.DataFrame | None) -> VizResult:
    """
    C6: Default display strategy — generate at least 4 core chart types
    for the first question / full-regeneration mode.
    """
    paths: list[str] = []

    # Core charts always generated when data is available
    if "mv_monthly_sales" in tables and forecast_df is not None:
        paths.append(plot_monthly_sales_with_forecast(tables["mv_monthly_sales"], forecast_df))

    if "mv_state_sales" in tables:
        paths.append(plot_state_sales_map(tables["mv_state_sales"]))
        # C3: also generate AOV bar chart from the same state_sales data
        paths.append(plot_state_avg_basket(tables["mv_state_sales"]))
        # C4: interactive folium heatmap
        paths.append(plot_folium_geo_heatmap(tables["mv_state_sales"]))

    if "mv_payment_dist" in tables:
        paths.append(plot_payment_matrix(tables["mv_payment_dist"]))

    if "mv_category_sales" in tables:
        paths.append(plot_category_top(tables["mv_category_sales"]))

    if "mv_delivery_perf" in tables:
        paths.append(plot_delivery_perf(tables["mv_delivery_perf"]))

    if "scatter_weight_freight" in tables:
        paths.append(plot_weight_vs_freight(tables["scatter_weight_freight"]))
        # C5: also generate the extended weight+dims scatter
        paths.append(plot_weight_dims_vs_freight(tables["scatter_weight_freight"]))

    # C1: category rating heatmap from diagnostic data
    if "diagnostic_bad_review_categories" in tables:
        paths.append(plot_category_rating_heatmap(tables["diagnostic_bad_review_categories"]))

    # C2: dual wordcloud if both pos/neg terms are available
    if "_nlp_negative_terms" in tables and "_nlp_positive_terms" in tables:
        neg_terms = tables["_nlp_negative_terms"]["term"].dropna().astype(str).tolist()
        pos_terms = tables["_nlp_positive_terms"]["term"].dropna().astype(str).tolist()
        paths.append(plot_dual_wordcloud(pos_terms, neg_terms))
    elif "_nlp_negative_terms" in tables:
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

    C6: quick_mode is now governed upstream — this function draws exactly
    what is requested. The caller (graph.py) ensures at least 4 chart types
    for non-quick mode via plan_charts.
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
            elif cid == "bar_state_avg_basket":                       # C3
                if "mv_state_sales" in tables:
                    paths.append(plot_state_avg_basket(tables["mv_state_sales"]))
            elif cid == "geo_bubble_state":
                if "mv_state_geo" in tables:
                    paths.append(plot_geo_bubble_by_state(tables["mv_state_geo"]))
            elif cid == "folium_geo_heatmap":                         # C4
                if "mv_state_sales" in tables:
                    paths.append(plot_folium_geo_heatmap(tables["mv_state_sales"]))
            elif cid == "heatmap_payment_installments":
                if "mv_payment_dist" in tables:
                    paths.append(plot_payment_matrix(tables["mv_payment_dist"]))
            elif cid == "heatmap_category_rating":                    # C1
                if "diagnostic_bad_review_categories" in tables:
                    paths.append(plot_category_rating_heatmap(tables["diagnostic_bad_review_categories"]))
            elif cid == "bar_top_categories":
                if "mv_category_sales" in tables:
                    paths.append(plot_category_top(tables["mv_category_sales"]))
            elif cid == "bar_delivery_days":
                if "mv_delivery_perf" in tables:
                    paths.append(plot_delivery_perf(tables["mv_delivery_perf"]))
            elif cid == "scatter_weight_freight":
                if "scatter_weight_freight" in tables:
                    paths.append(plot_weight_vs_freight(tables["scatter_weight_freight"]))
            elif cid == "scatter_weight_dims_freight":                # C5
                if "scatter_weight_freight" in tables:
                    paths.append(plot_weight_dims_vs_freight(tables["scatter_weight_freight"]))
            elif cid == "wordcloud_negative":
                if "_nlp_negative_terms" in tables:
                    neg_terms = tables["_nlp_negative_terms"]["term"].dropna().astype(str).tolist()
                    paths.append(plot_negative_wordcloud(neg_terms))
            elif cid == "wordcloud_dual":                             # C2
                pos_available = "_nlp_positive_terms" in tables
                neg_available = "_nlp_negative_terms" in tables
                if pos_available and neg_available:
                    pos_terms = tables["_nlp_positive_terms"]["term"].dropna().astype(str).tolist()
                    neg_terms = tables["_nlp_negative_terms"]["term"].dropna().astype(str).tolist()
                    paths.append(plot_dual_wordcloud(pos_terms, neg_terms))
                elif neg_available:
                    neg_terms = tables["_nlp_negative_terms"]["term"].dropna().astype(str).tolist()
                    paths.append(plot_negative_wordcloud(neg_terms))
        except Exception:
            # best-effort: one chart failing shouldn't kill the run
            continue

    return VizResult(paths=paths)