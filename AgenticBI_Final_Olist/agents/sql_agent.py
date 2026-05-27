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


def run_sql_agent(question: str) -> SQLAgentResult:
    client = DeepSeekClient()
    content = client.chat(
        [
            ChatMessage(role="system", content=SYSTEM_PROMPT),
            ChatMessage(role="user", content=question),
        ],
        temperature=0.1,
    )

    meta = _extract_json_object(content)
    sql = meta.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError(f"DeepSeek returned invalid SQL metadata: {meta}")
    if not _is_safe_select(sql):
        raise ValueError(f"Unsafe SQL generated: {sql}")

    engine = build_mysql_engine()
    with engine.begin() as conn:
        df = pd.read_sql(text(sql), conn)

    return SQLAgentResult(sql=sql, df=df, meta=meta)

