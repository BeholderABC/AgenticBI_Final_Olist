from __future__ import annotations

import pandas as pd
from langgraph.graph import StateGraph, END

from agents.state import AgenticState
from agents.sql_agent import run_sql_agent
from agents.viz_agent import build_viz_bundle_for_charts
from agents.viz_planner_agent import plan_charts
from agents.nlp_agent import run_nlp_agent
from agents.decision_agent import run_decision_agent
from models.forecast import forecast_6_weeks
from utils.db import build_mysql_engine
from sqlalchemy import text


def _coordinator_node(state: AgenticState) -> AgenticState:
    q = state.user_question.lower()
    plan: list[str] = []

    # basic routing - still LLM will generate SQL per query
    plan.append("Query pre-aggregated views for sales, region, category, delivery, payment.")
    if any(k in q for k in ["预测", "forecast", "未来", "6周", "six weeks", "趋势"]):
        plan.append("Build 6-week forecast from mv_monthly_sales.")
    plan.append("Run NLP insights on review texts.")
    plan.append("Generate visualizations bundle.")
    plan.append("Generate prescriptive recommendations.")

    state.plan = plan
    return state


def _analysis_node(state: AgenticState) -> AgenticState:
    tables: dict[str, pd.DataFrame] = {}

    # Pull lightweight pre-agg views for dashboard completeness.
    # IMPORTANT: keep this fast (<60s). Avoid huge tables or heavy runtime JOINs here.
    engine = build_mysql_engine()
    q = state.user_question.lower()

    # In quick mode, only load the minimal tables required by the question
    # (instead of loading the entire dashboard dataset every time).
    if state.quick_mode:
        view_queries: dict[str, str] = {}
        if any(k in q for k in ["趋势", "按月", "forecast", "预测", "未来", "6周", "gmv"]):
            view_queries["mv_monthly_sales"] = "SELECT * FROM mv_monthly_sales ORDER BY 1"
        if any(k in q for k in ["州", "state", "地区", "区域", "排名", "分布"]):
            view_queries["mv_state_sales"] = "SELECT * FROM mv_state_sales ORDER BY 1, 2"
        if any(k in q for k in ["品类", "类目", "category", "商品"]):
            view_queries["mv_category_sales"] = "SELECT * FROM mv_category_sales ORDER BY 1, 3 DESC"
        if any(k in q for k in ["配送", "交付", "延迟", "准时", "delivery"]):
            view_queries["mv_delivery_perf"] = "SELECT * FROM mv_delivery_perf ORDER BY 1, 2"
        if any(k in q for k in ["支付", "payment", "分期", "installment"]):
            view_queries["mv_payment_dist"] = "SELECT * FROM mv_payment_dist ORDER BY 1, 2"
        if any(k in q for k in ["地图", "地理", "geo", "经纬度"]):
            view_queries["mv_state_geo"] = "SELECT * FROM mv_state_geo ORDER BY 4 DESC"
    else:
        view_queries = {
            # NOTE: use ORDER BY ordinal to avoid identifier quirks in some MySQL setups
            "mv_monthly_sales": "SELECT * FROM mv_monthly_sales ORDER BY 1",
            "mv_state_sales": "SELECT * FROM mv_state_sales ORDER BY 1, 2",
            "mv_category_sales": "SELECT * FROM mv_category_sales ORDER BY 1, 3 DESC",
            "mv_delivery_perf": "SELECT * FROM mv_delivery_perf ORDER BY 1, 2",
            "mv_payment_dist": "SELECT * FROM mv_payment_dist ORDER BY 1, 2",
            # precomputed geo table (materialized) to avoid big joins at runtime
            "mv_state_geo": "SELECT * FROM mv_state_geo ORDER BY 4 DESC",
        }
    with engine.begin() as conn:
        # Hard limit server-side execution time for SELECT (ms). Best-effort only.
        try:
            conn.execute(text("SET SESSION max_execution_time = 60000"))
        except Exception:
            pass
        for name, sql in view_queries.items():
            try:
                tables[name] = pd.read_sql(text(sql), conn)
            except Exception:
                # view might not exist yet; keep going
                continue

        # Scatter/bubble: weight vs freight (only when relevant)
        if (not state.quick_mode) or any(k in q for k in ["重量", "尺寸", "运费", "freight", "weight", "关系", "相关"]):
            try:
                scatter_sql = """
                SELECT
                  o.order_status,
                  COALESCE(t.product_category_name_english, pr.product_category_name, 'unknown') AS product_category_english,
                  pr.product_weight_g,
                  AVG(oi.freight_value) AS freight_value,
                  COUNT(DISTINCT oi.order_id) AS order_cnt
                FROM order_items oi
                JOIN orders o ON o.order_id = oi.order_id
                JOIN products pr ON pr.product_id = oi.product_id
                LEFT JOIN product_category_name_translation t
                  ON t.product_category_name = pr.product_category_name
                WHERE pr.product_weight_g IS NOT NULL
                GROUP BY 1, 2, 3
                HAVING order_cnt >= 5
                ORDER BY order_cnt DESC
                LIMIT 2000
                """
                tables["scatter_weight_freight"] = pd.read_sql(text(scatter_sql), conn)
            except Exception:
                pass

    # Also answer the user's question via dynamic SQL (view-first prompt)
    try:
        res = run_sql_agent(state.user_question)
        tables["question_result"] = res.df
        tables["_question_meta"] = pd.DataFrame([{"sql": res.sql, **res.meta}])
    except Exception as e:
        tables["_question_error"] = pd.DataFrame([{"error": str(e)}])

    state.tables = {k: v.to_dict(orient="list") for k, v in tables.items()}
    return state


def _forecast_node(state: AgenticState) -> AgenticState:
    if "mv_monthly_sales" not in state.tables:
        return state

    monthly = pd.DataFrame(state.tables["mv_monthly_sales"])
    if not {"year_month", "total_gmv"}.issubset(set(monthly.columns)):
        return state

    fc = forecast_6_weeks(monthly, fast_mode=state.quick_mode)
    state.forecast = {"forecast": fc.df.to_dict(orient="list")}
    return state


def _nlp_node(state: AgenticState) -> AgenticState:
    # Skip NLP unless the question explicitly touches reviews/negative reasons.
    q = state.user_question.lower()
    if state.quick_mode and not any(k in q for k in ["评论", "差评", "好评", "review", "rating", "原因", "主题", "情感"]):
        state.nlp = {}
        return state
    try:
        # quick mode: smaller sample + cached result for responsiveness
        if state.quick_mode:
            state.nlp = run_nlp_agent(sample_limit=4000, cache_ttl_s=3600)
        else:
            state.nlp = run_nlp_agent(sample_limit=20000, cache_ttl_s=3600)
    except Exception as e:
        state.nlp = {"summary": f"NLP agent failed: {e}", "top_negative_terms": []}

    # pass negative terms to viz layer as a tiny table
    try:
        terms = state.nlp.get("top_negative_terms", []) if isinstance(state.nlp, dict) else []
        if terms:
            # store as a table-like payload (keeps the same serialization approach)
            state.tables["_nlp_negative_terms"] = {"term": list(terms)}
    except Exception:
        pass
    return state


def _viz_node(state: AgenticState) -> AgenticState:
    tables = {k: pd.DataFrame(v) for k, v in state.tables.items() if not k.startswith("_")}
    forecast_df = None
    if state.forecast.get("forecast"):
        forecast_df = pd.DataFrame(state.forecast["forecast"])

    # Decide which charts are needed for this question (0-3).
    # Empty => skip drawing for fastest response.
    available = list(state.tables.keys())
    plan = plan_charts(state.user_question, available, quick_mode=state.quick_mode)
    state.requested_charts = plan.get("charts", []) if isinstance(plan, dict) else []

    # quick mode safety: avoid the slowest charts even if requested
    if state.quick_mode and state.requested_charts:
        deny = {"geo_bubble_state", "wordcloud_negative"}
        state.requested_charts = [c for c in state.requested_charts if c not in deny][:2]

    viz = build_viz_bundle_for_charts(
        {**tables, **{k: pd.DataFrame(v) for k, v in state.tables.items() if k.startswith("_")}},
        forecast_df,
        chart_ids=state.requested_charts,
    )
    state.figures = viz.paths
    return state


def _decision_node(state: AgenticState) -> AgenticState:
    # Build concise summaries
    analysis_bits = []
    if "question_result" in state.tables:
        qr = pd.DataFrame(state.tables["question_result"])
        analysis_bits.append(f"question_result shape={qr.shape}, columns={list(qr.columns)[:12]}")
        if len(qr):
            analysis_bits.append(f"question_result head={qr.head(5).to_dict(orient='records')}")

    if "mv_state_sales" in state.tables:
        ss = pd.DataFrame(state.tables["mv_state_sales"])
        top = (
            ss.groupby("customer_state", as_index=False)["total_gmv"]
            .sum()
            .sort_values("total_gmv", ascending=False)
            .head(5)
        )
        analysis_bits.append(f"top_states_by_gmv={top.to_dict(orient='records')}")

    if "mv_delivery_perf" in state.tables:
        dp = pd.DataFrame(state.tables["mv_delivery_perf"])
        worst = (
            dp.groupby("customer_state", as_index=False)["on_time_rate"]
            .mean()
            .sort_values("on_time_rate", ascending=True)
            .head(5)
        )
        analysis_bits.append(f"worst_states_on_time={worst.to_dict(orient='records')}")

    if "scatter_weight_freight" in state.tables:
        sw = pd.DataFrame(state.tables["scatter_weight_freight"])
        if len(sw):
            analysis_bits.append(
                f"scatter_weight_freight sample={sw.head(5).to_dict(orient='records')}"
            )

    analysis_summary = "\n".join(analysis_bits) if analysis_bits else "No analysis tables available."

    forecast_summary = None
    if state.forecast.get("forecast"):
        fdf = pd.DataFrame(state.forecast["forecast"])
        forecast_summary = fdf.head(6).to_dict(orient="records").__repr__()

    nlp_summary = None
    if state.nlp:
        nlp_summary = str(state.nlp)

    try:
        answer = run_decision_agent(
            user_question=state.user_question,
            analysis_summary=analysis_summary,
            forecast_summary=forecast_summary,
            nlp_summary=nlp_summary,
        )
    except Exception as e:
        answer = f"Decision agent failed: {e}\n\nanalysis_summary:\n{analysis_summary}\n\nnlp:\n{nlp_summary}"

    state.final_answer = answer
    return state


def build_graph():
    g = StateGraph(AgenticState)
    g.add_node("coordinator", _coordinator_node)
    g.add_node("analysis", _analysis_node)
    g.add_node("forecast", _forecast_node)
    g.add_node("nlp", _nlp_node)
    g.add_node("viz", _viz_node)
    g.add_node("decision", _decision_node)

    g.set_entry_point("coordinator")
    g.add_edge("coordinator", "analysis")
    g.add_edge("analysis", "forecast")
    g.add_edge("forecast", "nlp")
    g.add_edge("nlp", "viz")
    g.add_edge("viz", "decision")
    g.add_edge("decision", END)

    return g.compile()

