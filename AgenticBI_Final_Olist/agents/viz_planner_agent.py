from __future__ import annotations

import json

from models.deepseek_client import ChatMessage, DeepSeekClient


CHART_CATALOG = [
    "none",
    # time series
    "ts_gmv_forecast",
    # categorical/bar
    "bar_state_gmv",
    "bar_top_categories",
    "bar_delivery_days",
    # matrix/heatmap
    "heatmap_payment_installments",
    # scatter/bubble
    "scatter_weight_freight",
    # geo
    "geo_bubble_state",
    # text / nlp
    "wordcloud_negative",
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
        # fallback: minimal useful defaults
        charts: list[str] = []
        if any(k in q for k in ["趋势", "按月", "forecast", "预测", "未来", "6周"]):
            charts.append("ts_gmv_forecast")
        if any(k in q for k in ["州", "state", "地区", "区域", "regional", "分布"]):
            charts.append("bar_state_gmv")
        if any(k in q for k in ["支付", "payment", "分期", "installment"]):
            charts.append("heatmap_payment_installments")
        if any(k in q for k in ["重量", "尺寸", "运费", "关系", "相关"]):
            charts.append("scatter_weight_freight")
        if any(k in q for k in ["差评", "评论", "原因", "主题"]):
            charts.append("wordcloud_negative")
        if quick_mode:
            charts = charts[:2]
        return {"charts": charts, "rationale": "fallback heuristic"}

