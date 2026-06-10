from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text

from models.deepseek_client import DeepSeekClient, ChatMessage
from utils.db import build_mysql_engine


SYSTEM_PROMPT = """You are a senior data analyst agent for an e-commerce BI system.
Your job: translate the user's business question into ONE safe MySQL SELECT query.

CRITICAL RULES:
- Only output JSON, no extra text.
- The query MUST be read-only: SELECT only. No INSERT/UPDATE/DELETE/DDL.
- Prefer pre-aggregated materialized views when possible.
- If a pre-aggregated view can answer the KPI, you MUST use that view.
- Only fall back to base tables for dimensions not covered by any view, such as product size,
  raw review text, exact order details, or category-level bad review reason drill-down.
- Use LIMIT 2000 unless the user explicitly asks for full export.
- Use column names that exist in Olist dataset tables.

AVAILABLE PRE-AGG VIEWS (tables):
- mv_monthly_sales(year_month,total_gmv,total_orders,avg_basket,total_freight)
- mv_state_sales(year_month,customer_state,total_gmv,total_orders,unique_customers)
- mv_category_sales(year_month,product_category_english,total_gmv,total_orders,avg_price)
- mv_delivery_perf(year_month,customer_state,avg_delivery_days,on_time_rate,delayed_orders)
- mv_seller_perf(year_month,seller_id,seller_state,total_gmv,total_orders,avg_review_score)
- mv_payment_dist(year_month,payment_type,total_transactions,avg_installments,total_value)

AVAILABLE BASE TABLES (key columns):
- orders(order_id,customer_id,order_status,order_purchase_timestamp,order_delivered_customer_date,order_estimated_delivery_date)
- order_items(order_id,product_id,seller_id,price,freight_value,product_weight_g)
- customers(customer_id,customer_unique_id,customer_zip_code_prefix,customer_state)
- payments(order_id,payment_type,payment_installments,payment_value)
- order_reviews(order_id,review_score,review_comment_message)
- products(product_id,product_category_name)
- sellers(seller_id,seller_state)
- product_category_name_translation(product_category_name,product_category_name_english)

OUTPUT JSON SCHEMA:
{
  "use_view": true|false,
  "view_name": "mv_monthly_sales" | null,
  "sql": "SELECT ...",
  "kpi_explanation": "short explanation of what it computes"
}
"""


def _extract_json_object(text: str) -> dict:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end + 1])
        else:
            raise
    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek response did not contain a JSON object.")
    return parsed


@dataclass(frozen=True)
class SQLAgentResult:
    sql: str
    df: pd.DataFrame
    meta: dict


def _is_safe_select(sql: str) -> bool:
    s = sql.strip().lower()
    if not s.startswith("select"):
        return False
    banned = ["insert ", "update ", "delete ", "drop ", "alter ", "create ", "truncate "]
    return not any(b in s for b in banned)


VIEW_HINTS: dict[str, tuple[tuple[str, int], ...]] = {
    "mv_monthly_sales": (("gmv", 3), ("销售额", 2), ("按月", 3), ("月度", 3), ("趋势", 1), ("客单价", 2), ("basket", 2)),
    "mv_state_sales": (("州", 1), ("state", 1), ("地区", 1), ("区域", 1), ("排名", 1), ("销售额最高", 4), ("各州", 2)),
    "mv_category_sales": (("品类", 3), ("类目", 3), ("category", 3), ("商品类别", 3)),
    "mv_delivery_perf": (("配送", 4), ("交付", 4), ("准时", 7), ("延迟", 7), ("delivery", 4), ("on time", 7)),
    "mv_seller_perf": (("卖家", 4), ("seller", 4), ("差评率最高", 6), ("评分最低", 5), ("差评卖家", 6)),
    "mv_payment_dist": (("支付", 4), ("payment", 4), ("分期", 5), ("installment", 5)),
}


def _preferred_views(question: str) -> list[str]:
    q = question.lower()
    scored: list[tuple[int, str]] = []
    for view, hints in VIEW_HINTS.items():
        score = sum(weight for hint, weight in hints if hint in q)
        if score:
            scored.append((score, view))
    return [view for _, view in sorted(scored, key=lambda item: item[0], reverse=True)]


def _mentions_view(sql: str, view_name: str) -> bool:
    return view_name.lower() in sql.lower()


def _fallback_query_for_view(question: str, view_name: str) -> str:
    q = question.lower()
    if view_name == "mv_monthly_sales":
        where = "WHERE year_month LIKE '2017-%'" if "2017" in q else ""
        return f"""
        SELECT year_month, total_gmv, total_orders, avg_basket, total_freight
        FROM mv_monthly_sales
        {where}
        ORDER BY year_month
        LIMIT 2000
        """
    if view_name == "mv_state_sales":
        where = "WHERE year_month LIKE '2017-%'" if "2017" in q else ""
        return f"""
        SELECT customer_state, SUM(total_gmv) AS total_gmv, SUM(total_orders) AS total_orders,
               SUM(unique_customers) AS unique_customers
        FROM mv_state_sales
        {where}
        GROUP BY customer_state
        ORDER BY total_gmv DESC
        LIMIT 2000
        """
    if view_name == "mv_delivery_perf":
        return """
        SELECT customer_state,
               AVG(avg_delivery_days) AS avg_delivery_days,
               AVG(on_time_rate) AS on_time_rate,
               SUM(delayed_orders) AS delayed_orders
        FROM mv_delivery_perf
        GROUP BY customer_state
        ORDER BY on_time_rate ASC, avg_delivery_days DESC
        LIMIT 2000
        """
    if view_name == "mv_seller_perf":
        return """
        SELECT seller_id, seller_state,
               SUM(total_orders) AS total_orders,
               SUM(total_gmv) AS total_gmv,
               AVG(avg_review_score) AS avg_review_score
        FROM mv_seller_perf
        GROUP BY seller_id, seller_state
        HAVING total_orders >= 5
        ORDER BY avg_review_score ASC, total_orders DESC
        LIMIT 20
        """
    if view_name == "mv_payment_dist":
        return """
        SELECT payment_type,
               SUM(total_transactions) AS total_transactions,
               AVG(avg_installments) AS avg_installments,
               SUM(total_value) AS total_value
        FROM mv_payment_dist
        GROUP BY payment_type
        ORDER BY total_transactions DESC
        LIMIT 2000
        """
    return """
    SELECT product_category_english,
           SUM(total_gmv) AS total_gmv,
           SUM(total_orders) AS total_orders,
           AVG(avg_price) AS avg_price
    FROM mv_category_sales
    GROUP BY product_category_english
    ORDER BY total_gmv DESC
    LIMIT 2000
    """


def _conversation_context(history: list[dict[str, str]] | None) -> str:
    if not history:
        return ""
    lines: list[str] = []
    for item in history[-6:]:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        if content:
            lines.append(f"{role}: {content[:500]}")
    return "\n".join(lines)


def run_sql_agent(question: str, history: list[dict[str, str]] | None = None) -> SQLAgentResult:
    client = DeepSeekClient()
    context = _conversation_context(history)
    user_content = question if not context else f"Recent conversation:\n{context}\n\nCurrent question:\n{question}"
    content = client.chat(
        [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_content),
        ],
        temperature=0.1,
    )

    meta = _extract_json_object(content)
    sql = meta.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError(f"DeepSeek returned invalid SQL metadata: {meta}")
    if not _is_safe_select(sql):
        raise ValueError(f"Unsafe SQL generated: {sql}")

    preferred = _preferred_views(question)
    requested_view = meta.get("view_name")
    use_view = bool(meta.get("use_view"))
    if use_view and isinstance(requested_view, str) and requested_view:
        if not _mentions_view(sql, requested_view):
            sql = _fallback_query_for_view(question, requested_view)
            meta["view_strategy"] = "forced_fallback_llm_view_mismatch"
    elif preferred and not any(_mentions_view(sql, view) for view in preferred):
        selected = preferred[0]
        sql = _fallback_query_for_view(question, selected)
        meta.update(
            {
                "use_view": True,
                "view_name": selected,
                "view_strategy": "forced_preagg_view_by_runtime_policy",
            }
        )
    else:
        meta["view_strategy"] = "llm_sql_accepted"

    engine = build_mysql_engine()
    with engine.begin() as conn:
        df = pd.read_sql(text(sql), conn)

    return SQLAgentResult(sql=sql, df=df, meta=meta)

