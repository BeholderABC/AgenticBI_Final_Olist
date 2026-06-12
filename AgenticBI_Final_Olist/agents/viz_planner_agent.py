from __future__ import annotations

import json

from models.deepseek_client import ChatMessage, DeepSeekClient


CHART_CATALOG = [
    "none",
    # time series
    "ts_gmv_forecast",
    # categorical/bar
    "bar_state_gmv",
    "bar_state_avg_basket",        # C3: 各州客单价柱状图
    "bar_top_categories",
    "bar_delivery_days",
    # matrix/heatmap
    "heatmap_payment_installments",
    "heatmap_category_rating",     # C1: 品类×评分热力矩阵图
    # scatter/bubble
    "scatter_weight_freight",
    "scatter_weight_dims_freight", # C5: 重量+尺寸 vs 运费扩展散点
    # geo
    "geo_bubble_state",
    "folium_geo_heatmap",          # C4: Folium 巴西州级地理热力图
    # text / nlp
    "wordcloud_negative",
    "wordcloud_dual",              # C2: 好评/差评对比双词云
]


SYSTEM = """You are a BI visualization planning agent.
Given a user's business question and what data tables are available, decide which charts to generate.

Rules:
- Output JSON only.
- If charts are not needed, output an empty list.
- Prefer 0-3 charts that best answer the question (do NOT generate all charts).
- If the question is a pure factual lookup, prefer no charts.

Allowed chart ids:
{catalog}

Output schema:
{{
  "charts": ["chart_id", ...],
  "rationale": "one sentence"
}}
""".format(
    catalog=", ".join(CHART_CATALOG)
)


def plan_charts(user_question: str, available_tables: list[str], *, quick_mode: bool) -> dict:
    """
    Returns: {"charts": [...], "rationale": "..."}.
    Best-effort: if LLM fails, fallback to simple heuristics.
    """
    # heuristic fast-path: when quick_mode and question looks like pure SQL lookup
    q = user_question.lower()
    if any(k in q for k in ["多少", "是多少", "what is", "how many", "count", "总计"]) and not any(
        k in q for k in ["趋势", "变化", "forecast", "预测", "分布", "对比", "关系", "相关", "map", "地理", "热力"]
    ):
        return {"charts": [], "rationale": "pure lookup; no chart needed"}

    try:
        client = DeepSeekClient()
        content = client.chat(
            [
                ChatMessage(role="system", content=SYSTEM),
                ChatMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "question": user_question,
                            "available_tables": available_tables,
                            "quick_mode": quick_mode,
                        },
                        ensure_ascii=False,
                    ),
                ),
            ],
            temperature=0.1,
        )
        data = json.loads(content[content.find("{") : content.rfind("}") + 1])
        charts = data.get("charts", [])
        if not isinstance(charts, list):
            charts = []
        charts = [c for c in charts if c in CHART_CATALOG and c != "none"]
        # quick_mode guard: keep it small
        if quick_mode:
            charts = charts[:2]
        return {"charts": charts, "rationale": str(data.get("rationale", ""))[:300]}
    except Exception:
        # fallback: accumulate all matching chart types
        charts: list[str] = []
        if any(k in q for k in ["趋势", "按月", "forecast", "预测", "未来", "6周", "gmv"]):
            charts.append("ts_gmv_forecast")
        if any(k in q for k in ["州", "state", "地区", "区域", "regional", "分布"]):
            charts.append("bar_state_gmv")
            charts.append("bar_state_avg_basket")    # also show AOV
        if any(k in q for k in ["支付", "payment", "分期", "installment"]):
            charts.append("heatmap_payment_installments")
        if any(k in q for k in ["重量", "运费", "freight", "weight", "关系", "相关"]):
            charts.append("scatter_weight_freight")
        if any(k in q for k in ["尺寸", "长宽高", "dimension", "长度", "体积"]):
            charts.append("scatter_weight_dims_freight")
        if any(k in q for k in ["差评", "评论", "原因", "主题", "好评", "情感"]):
            charts.append("wordcloud_dual")
        if any(k in q for k in ["客单价", "平均消费", "aov", "basket"]):
            charts.append("bar_state_avg_basket")
        if any(k in q for k in ["地图", "热力", "地理", "geo", "map", "folium"]):
            charts.append("folium_geo_heatmap")
        if any(k in q for k in ["评分", "rating", "品类"]):
            charts.append("heatmap_category_rating")
        if any(k in q for k in ["配送", "延迟", "准时", "delivery", "交付"]):
            charts.append("bar_delivery_days")
        if any(k in q for k in ["品类", "类目", "category", "商品", "排行"]):
            charts.append("bar_top_categories")
        # C6: at least 4 chart types in non-quick mode
        if not quick_mode and len(charts) < 4:
            defaults = ["ts_gmv_forecast", "bar_state_gmv", "bar_state_avg_basket", "heatmap_payment_installments"]
            for d in defaults:
                if d not in charts:
                    charts.append(d)
            charts = charts[:6]
        if quick_mode:
            charts = charts[:4]   # allow up to 4 even in quick mode
        return {"charts": charts, "rationale": "fallback heuristic"}

