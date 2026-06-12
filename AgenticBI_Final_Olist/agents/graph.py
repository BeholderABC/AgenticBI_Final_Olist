from __future__ import annotations

import pandas as pd
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agents.state import AgenticState
from agents.coordinator import plan_question
from agents.sql_agent import run_sql_agent
from agents.viz_agent import build_viz_bundle_for_charts, build_default_viz_bundle
from agents.viz_planner_agent import plan_charts
from agents.nlp_agent import run_nlp_agent
from agents.decision_agent import run_decision_agent
from agents.anomaly_agent import run_anomaly_detection, _anomaly_alerts_to_dicts
from models.forecast import forecast_6_weeks
from models.whatif import run_whatif_delist_bad_sellers, format_whatif_report
from utils.db import build_mysql_engine
from sqlalchemy import text
from typing import Any


def _serialize_tables(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """Convert DataFrames to msgpack-safe dicts (all numpy types → native Python)."""
    import numpy as np

    safe: dict[str, Any] = {}
    for k, df in tables.items():
        d = {}
        for col in df.columns:
            vals = df[col].tolist()
            # Recursively convert any numpy scalars to Python types
            clean_vals = []
            for v in vals:
                if isinstance(v, (np.integer,)):
                    clean_vals.append(int(v))
                elif isinstance(v, (np.floating,)):
                    if np.isnan(v):
                        clean_vals.append(None)
                    else:
                        clean_vals.append(float(v))
                elif isinstance(v, (np.bool_,)):
                    clean_vals.append(bool(v))
                elif isinstance(v, (np.ndarray,)):
                    clean_vals.append(v.tolist())
                elif v is None or isinstance(v, (str, int, float, bool, list, dict)):
                    clean_vals.append(v)
                elif isinstance(v, (bytes,)):
                    clean_vals.append(v.decode("utf-8", errors="replace"))
                else:
                    clean_vals.append(str(v))
            d[col] = clean_vals
        safe[k] = d
    return safe


def _coordinator_node(state: AgenticState) -> AgenticState:
    planned = plan_question(state.user_question, state.conversation_history)
    state.plan_detail = planned
    state.route = planned.get("route", {}) if isinstance(planned.get("route"), dict) else {}
    subtasks = planned.get("subtasks", [])
    if isinstance(subtasks, list):
        state.plan = [
            f"{item.get('agent', 'agent')}: {item.get('task', '')}"
            for item in subtasks
            if isinstance(item, dict)
        ]
    if not state.plan:
        state.plan = ["sql: Query pre-aggregated views first.", "decision: Synthesize the final answer."]
    return state


def _effective_question(state: AgenticState) -> str:
    rewritten = state.plan_detail.get("context_rewrite") if isinstance(state.plan_detail, dict) else None
    return rewritten if isinstance(rewritten, str) and rewritten.strip() else state.user_question


def _analysis_node(state: AgenticState) -> AgenticState:
    tables: dict[str, pd.DataFrame] = {}

    # Pull lightweight pre-agg views for dashboard completeness.
    # IMPORTANT: keep this fast (<60s). Avoid huge tables or heavy runtime JOINs here.
    engine = build_mysql_engine()
    effective_question = _effective_question(state)
    q = effective_question.lower()

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
        if any(k in q for k in ["卖家", "seller", "差评率", "评分最低"]):
            view_queries["mv_seller_perf"] = "SELECT * FROM mv_seller_perf ORDER BY avg_review_score ASC, total_orders DESC LIMIT 2000"
        if any(k in q for k in ["地图", "地理", "geo", "经纬度"]):
            view_queries["mv_state_geo"] = "SELECT * FROM mv_state_geo ORDER BY 4 DESC"
    else:
        view_queries = {
            # NOTE: use ORDER BY ordinal to avoid identifier quirks in some MySQL setups
            "mv_monthly_sales": "SELECT * FROM mv_monthly_sales ORDER BY 1",
            "mv_state_sales": "SELECT * FROM mv_state_sales ORDER BY 1, 2",
            "mv_category_sales": "SELECT * FROM mv_category_sales ORDER BY 1, 3 DESC",
            "mv_delivery_perf": "SELECT * FROM mv_delivery_perf ORDER BY 1, 2",
            "mv_seller_perf": "SELECT * FROM mv_seller_perf ORDER BY avg_review_score ASC, total_orders DESC LIMIT 2000",
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
                  pr.product_length_cm,
                  pr.product_height_cm,
                  pr.product_width_cm,
                  AVG(oi.freight_value) AS freight_value,
                  COUNT(DISTINCT oi.order_id) AS order_cnt
                FROM order_items oi
                JOIN orders o ON o.order_id = oi.order_id
                JOIN products pr ON pr.product_id = oi.product_id
                LEFT JOIN product_category_name_translation t
                  ON t.product_category_name = pr.product_category_name
                WHERE pr.product_weight_g IS NOT NULL
                GROUP BY 1, 2, 3, 4, 5, 6
                HAVING order_cnt >= 5
                ORDER BY order_cnt DESC
                LIMIT 2000
                """
                tables["scatter_weight_freight"] = pd.read_sql(text(scatter_sql), conn)
            except Exception:
                pass

        if (not state.quick_mode) or any(k in q for k in ["卖家", "seller", "差评率最高", "差评卖家", "评分最低"]):
            try:
                seller_sql = """
                SELECT
                  seller_id,
                  seller_state,
                  SUM(total_orders) AS total_orders,
                  SUM(total_gmv) AS total_gmv,
                  AVG(avg_review_score) AS avg_review_score,
                  AVG(CASE WHEN avg_review_score <= 2 THEN 1 ELSE 0 END) AS low_score_month_ratio
                FROM mv_seller_perf
                GROUP BY seller_id, seller_state
                HAVING total_orders >= 5
                ORDER BY avg_review_score ASC, total_orders DESC
                LIMIT 20
                """
                tables["diagnostic_bad_review_sellers"] = pd.read_sql(text(seller_sql), conn)
            except Exception:
                pass

        if (not state.quick_mode) or any(k in q for k in ["配送", "交付", "延迟", "准时", "全国均值", "州级"]):
            try:
                delivery_sql = """
                SELECT
                  d.customer_state,
                  AVG(d.avg_delivery_days) AS avg_delivery_days,
                  AVG(d.on_time_rate) AS on_time_rate,
                  SUM(d.delayed_orders) AS delayed_orders,
                  n.national_avg_delivery_days,
                  n.national_on_time_rate,
                  AVG(d.avg_delivery_days) - n.national_avg_delivery_days AS delivery_days_vs_national
                FROM mv_delivery_perf d
                CROSS JOIN (
                  SELECT
                    AVG(avg_delivery_days) AS national_avg_delivery_days,
                    AVG(on_time_rate) AS national_on_time_rate
                  FROM mv_delivery_perf
                ) n
                GROUP BY d.customer_state, n.national_avg_delivery_days, n.national_on_time_rate
                ORDER BY delivery_days_vs_national DESC, on_time_rate ASC
                LIMIT 20
                """
                tables["diagnostic_delivery_vs_national"] = pd.read_sql(text(delivery_sql), conn)
            except Exception:
                pass

        if (not state.quick_mode) or any(k in q for k in ["品类", "类目", "差评", "原因", "review", "rating"]):
            try:
                category_review_sql = """
                SELECT
                  COALESCE(t.product_category_name_english, p.product_category_name, 'unknown') AS product_category_english,
                  COUNT(DISTINCT o.order_id) AS reviewed_orders,
                  AVG(r.review_score) AS avg_review_score,
                  AVG(CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END) AS bad_review_rate,
                  SUM(CASE WHEN r.review_score <= 2 THEN 1 ELSE 0 END) AS bad_review_orders
                FROM order_reviews r
                JOIN orders o ON o.order_id = r.order_id
                JOIN order_items oi ON oi.order_id = o.order_id
                JOIN products p ON p.product_id = oi.product_id
                LEFT JOIN product_category_name_translation t
                  ON t.product_category_name = p.product_category_name
                WHERE r.review_score IS NOT NULL
                GROUP BY 1
                HAVING reviewed_orders >= 30
                ORDER BY bad_review_rate DESC, bad_review_orders DESC
                LIMIT 10
                """
                tables["diagnostic_bad_review_categories"] = pd.read_sql(text(category_review_sql), conn)
            except Exception:
                pass

    # Also answer the user's question via dynamic SQL (view-first prompt)
    try:
        res = run_sql_agent(effective_question, history=state.conversation_history)
        tables["question_result"] = res.df
        tables["_question_meta"] = pd.DataFrame([{"sql": res.sql, **res.meta}])
    except Exception as e:
        tables["_question_error"] = pd.DataFrame([{"error": str(e)}])

    # Serialize DataFrames to dicts, converting all numpy types to native Python
    # (LangGraph uses msgpack which chokes on numpy.float64/int64/etc.)
    state.tables = _serialize_tables(tables)
    return state


def _forecast_node(state: AgenticState) -> AgenticState:
    if "mv_monthly_sales" not in state.tables:
        return state

    monthly = pd.DataFrame(state.tables["mv_monthly_sales"])
    if not {"year_month", "total_gmv"}.issubset(set(monthly.columns)):
        return state

    fc = forecast_6_weeks(monthly, fast_mode=state.quick_mode)
    # Convert forecast values to native Python types for msgpack compatibility
    forecast_native: dict[str, list] = {}
    raw_forecast = fc.df.to_dict(orient="list")
    for col, vals in raw_forecast.items():
        clean = []
        for v in vals:
            if isinstance(v, (float,)) and pd.isna(v):
                clean.append(None)
            elif isinstance(v, (float, int,)):
                clean.append(v)
            else:
                clean.append(str(v) if v is not None else None)
        forecast_native[col] = clean
    state.forecast = {"forecast": forecast_native}
    return state


def _nlp_node(state: AgenticState) -> AgenticState:
    # Skip NLP unless the question explicitly touches reviews/negative reasons.
    q = _effective_question(state).lower()
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

    # pass negative & positive terms to viz layer as tiny tables (C7/C2)
    try:
        neg_terms = state.nlp.get("top_negative_terms", []) if isinstance(state.nlp, dict) else []
        pos_terms = state.nlp.get("top_positive_terms", []) if isinstance(state.nlp, dict) else []
        if neg_terms:
            state.tables["_nlp_negative_terms"] = {"term": list(neg_terms)}
        if pos_terms:
            state.tables["_nlp_positive_terms"] = {"term": list(pos_terms)}
    except Exception:
        pass
    return state


def _viz_node(state: AgenticState) -> AgenticState:
    tables = {k: pd.DataFrame(v) for k, v in state.tables.items() if not k.startswith("_")}
    forecast_df = None
    if state.forecast.get("forecast"):
        forecast_df = pd.DataFrame(state.forecast["forecast"])

    if state.quick_mode:
        # Quick mode: select 1-4 focused charts matching the question
        available = list(state.tables.keys())
        plan = plan_charts(_effective_question(state), available, quick_mode=True)
        state.requested_charts = plan.get("charts", []) if isinstance(plan, dict) else []
        if state.requested_charts:
            state.requested_charts = state.requested_charts[:4]
        viz = build_viz_bundle_for_charts(
            {**tables, **{k: pd.DataFrame(v) for k, v in state.tables.items() if k.startswith("_")}},
            forecast_df,
            chart_ids=state.requested_charts,
        )
        state.figures = viz.paths
    else:
        # Non-quick mode (重新生成图表 button): generate all available charts
        viz = build_default_viz_bundle(
            {**tables, **{k: pd.DataFrame(v) for k, v in state.tables.items() if k.startswith("_")}},
            forecast_df,
        )
        state.figures = viz.paths
        state.requested_charts = []
    return state


# ===========================================================================
# C8: What-if Simulation Node
# ===========================================================================

def _whatif_node(state: AgenticState) -> AgenticState:
    """Run What-if simulation: estimate platform score uplift from delisting worst sellers."""
    q = _effective_question(state).lower()
    if not any(k in q for k in ["what", "if", "如果", "假如", "下架", "移除", "模拟", "预估"]):
        return state
    try:
        result = run_whatif_delist_bad_sellers(top_n=20)
        report = format_whatif_report(result)
        state.whatif = {
            "success": result.success,
            "report": report,
            "current_score": result.current_platform_avg_score,
            "new_score": result.new_platform_avg_score,
            "score_uplift": result.score_uplift,
            "score_uplift_pct": result.score_uplift_pct,
            "removed_seller_count": result.removed_seller_count,
            "removed_order_count": result.removed_order_count,
        }
    except Exception as e:
        state.whatif = {"success": False, "report": f"What-if simulation failed: {e}"}
    return state


# ===========================================================================
# C9: Anomaly Detection Node
# ===========================================================================

def _anomaly_node(state: AgenticState) -> AgenticState:
    """Run anomaly detection: scan for state-level order drops and delivery spikes."""
    q = _effective_question(state).lower()
    if state.quick_mode and not any(k in q for k in ["异常", "预警", "骤降", "突升", "anomaly", "突变", "检测"]):
        state.anomaly = {}
        return state
    try:
        report = run_anomaly_detection()
        alerts_dict = _anomaly_alerts_to_dicts(report.alerts)
        state.anomaly = {
            "success": report.success,
            "summary": report.summary,
            "alerts": alerts_dict,
            "alert_count": len(report.alerts),
        }
    except Exception as e:
        state.anomaly = {"success": False, "summary": f"Anomaly detection failed: {e}", "alerts": []}
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

    if "diagnostic_bad_review_sellers" in state.tables:
        sellers = pd.DataFrame(state.tables["diagnostic_bad_review_sellers"])
        if len(sellers):
            analysis_bits.append(f"bad_review_sellers={sellers.head(10).to_dict(orient='records')}")

    if "diagnostic_delivery_vs_national" in state.tables:
        delivery = pd.DataFrame(state.tables["diagnostic_delivery_vs_national"])
        if len(delivery):
            analysis_bits.append(f"delivery_vs_national={delivery.head(10).to_dict(orient='records')}")

    if "diagnostic_bad_review_categories" in state.tables:
        cats = pd.DataFrame(state.tables["diagnostic_bad_review_categories"])
        if len(cats):
            analysis_bits.append(f"bad_review_categories={cats.head(10).to_dict(orient='records')}")

    analysis_summary = "\n".join(analysis_bits) if analysis_bits else "No analysis tables available."
    if state.plan:
        analysis_summary = f"agent_plan={state.plan}\nroute={state.route}\n{analysis_summary}"

    forecast_summary = None
    if state.forecast.get("forecast"):
        fdf = pd.DataFrame(state.forecast["forecast"])
        forecast_summary = fdf.head(6).to_dict(orient="records").__repr__()

    nlp_summary = None
    if state.nlp:
        nlp_summary = str(state.nlp)

    try:
        answer = run_decision_agent(
            user_question=_effective_question(state),
            analysis_summary=analysis_summary,
            forecast_summary=forecast_summary,
            nlp_summary=nlp_summary,
        )
    except Exception as e:
        answer = f"Decision agent failed: {e}\n\nanalysis_summary:\n{analysis_summary}\n\nnlp:\n{nlp_summary}"

    if not str(answer).strip():
        answer = _fallback_answer_from_tables(state, analysis_summary)

    state.final_answer = answer
    return state


def _filter_year(df: pd.DataFrame, question: str) -> pd.DataFrame:
    if "2017" in question and "year_month" in df.columns:
        return df[df["year_month"].astype(str).str.startswith("2017-")]
    return df


def _fmt_pct(value: float | int | None) -> str:
    if value is None or pd.isna(value):
        return "暂无可用数据"
    return f"{float(value) * 100:.1f}%"


def _fallback_answer_from_tables(state: AgenticState, analysis_summary: str) -> str:
    question = _effective_question(state)
    q = question.lower()

    if "准时" in q or "on_time" in q or "交付" in q or "配送" in q:
        delivery = pd.DataFrame(state.tables.get("mv_delivery_perf", {}))
        state_sales = pd.DataFrame(state.tables.get("mv_state_sales", {}))
        if not delivery.empty:
            delivery = _filter_year(delivery, question)
            target_state = None
            if not state_sales.empty:
                state_sales = _filter_year(state_sales, question)
                if {"customer_state", "total_gmv"}.issubset(state_sales.columns):
                    top_state = (
                        state_sales.groupby("customer_state", as_index=False)["total_gmv"]
                        .sum()
                        .sort_values("total_gmv", ascending=False)
                        .head(1)
                    )
                    if len(top_state):
                        target_state = str(top_state.iloc[0]["customer_state"])

            if target_state and "customer_state" in delivery.columns:
                scoped = delivery[delivery["customer_state"].astype(str) == target_state]
            else:
                scoped = delivery

            if len(scoped) and "on_time_rate" in scoped.columns:
                on_time_rate = scoped["on_time_rate"].mean()
                avg_days = scoped["avg_delivery_days"].mean() if "avg_delivery_days" in scoped.columns else None
                prefix = f"承接上一问，{target_state} 州" if target_state else "按当前查询结果"
                extra = ""
                if avg_days is not None and not pd.isna(avg_days):
                    extra = f"，平均配送时长约 {float(avg_days):.1f} 天"
                return f"{prefix}的交付准时率约为 {_fmt_pct(on_time_rate)}{extra}。"

    if "卖家" in q or "seller" in q:
        sellers = pd.DataFrame(
            state.tables.get("diagnostic_bad_review_sellers")
            or state.tables.get("mv_seller_perf")
            or {}
        )
        if not sellers.empty and {"seller_id", "avg_review_score"}.issubset(sellers.columns):
            cols = [c for c in ["seller_id", "seller_state", "total_orders", "avg_review_score"] if c in sellers.columns]
            rows = sellers.sort_values("avg_review_score", ascending=True).head(5)[cols].to_dict(orient="records")
            return f"差评风险最高的卖家主要是这些记录：{rows}。建议优先复核其物流履约、商品描述和售后处理。"

    if "question_result" in state.tables:
        qr = pd.DataFrame(state.tables["question_result"])
        if not qr.empty:
            return f"已完成查询，核心结果如下：{qr.head(5).to_dict(orient='records')}"

    return f"已完成分析，但 LLM 未返回文本。可用分析摘要如下：\n{analysis_summary}"


def _route_after_analysis(state: AgenticState) -> str:
    if state.route.get("forecast"):
        return "forecast"
    if state.route.get("nlp"):
        return "nlp"
    if state.route.get("viz"):
        return "viz"
    return "decision"


def _route_after_forecast(state: AgenticState) -> str:
    if state.route.get("nlp"):
        return "nlp"
    if state.route.get("viz"):
        return "viz"
    return "decision"


def _route_after_nlp(state: AgenticState) -> str:
    if state.route.get("viz"):
        return "viz"
    return "decision"


def _route_after_viz(state: AgenticState) -> str:
    """After viz, route to anomaly/whatif if requested, else to decision."""
    if state.route.get("anomaly"):
        return "anomaly"
    if state.route.get("whatif"):
        return "whatif"
    return "decision"


def _route_after_specialties(state: AgenticState) -> str:
    """After anomaly or whatif, check if the other special agent is also needed."""
    # Track which specialty nodes have run via state.route
    if state.route.get("whatif") and state.route.get("anomaly"):
        return "decision"  # both run, go to decision
    return "decision"


def build_graph():
    g = StateGraph(AgenticState)
    g.add_node("coordinator", _coordinator_node)
    g.add_node("analysis", _analysis_node)
    g.add_node("forecast", _forecast_node)
    g.add_node("nlp", _nlp_node)
    g.add_node("viz", _viz_node)
    # C8/C9: bonus specialty agents (routed conditionally via coordinator)
    g.add_node("anomaly", _anomaly_node)
    g.add_node("whatif", _whatif_node)
    g.add_node("decision", _decision_node)

    g.set_entry_point("coordinator")
    g.add_edge("coordinator", "analysis")
    g.add_conditional_edges(
        "analysis",
        _route_after_analysis,
        {"forecast": "forecast", "nlp": "nlp", "viz": "viz", "decision": "decision"},
    )
    g.add_conditional_edges(
        "forecast",
        _route_after_forecast,
        {"nlp": "nlp", "viz": "viz", "decision": "decision"},
    )
    g.add_conditional_edges("nlp", _route_after_nlp, {"viz": "viz", "decision": "decision"})
    # After viz, route to anomaly/whatif if the question warrants it
    g.add_conditional_edges(
        "viz",
        _route_after_viz,
        {"anomaly": "anomaly", "whatif": "whatif", "decision": "decision"},
    )
    g.add_conditional_edges("anomaly", _route_after_specialties, {"decision": "decision"})
    g.add_conditional_edges("whatif", _route_after_specialties, {"decision": "decision"})
    g.add_edge("decision", END)

    return g.compile(checkpointer=MemorySaver())

