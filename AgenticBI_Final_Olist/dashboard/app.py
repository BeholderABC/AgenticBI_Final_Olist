from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from agents.graph import build_graph
from agents.state import AgenticState
from utils.startup_check import ensure_views_ready


ROOT = Path(__file__).resolve().parents[1]

def _get_field(obj, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


st.set_page_config(page_title="Agentic BI - Olist", layout="wide")
st.title("Agentic BI 驱动的电商运营分析与决策智能系统（Olist）")

if "graph" not in st.session_state:
    st.session_state.graph = build_graph()
if "thread_id" not in st.session_state:
    st.session_state.thread_id = "default"
if "history" not in st.session_state:
    st.session_state.history = []
if "startup_checked" not in st.session_state:
    with st.spinner("正在检查数据库与预聚合视图..."):
        st.session_state.startup_status = ensure_views_ready(auto_refresh=True)
    st.session_state.startup_checked = True

startup = st.session_state.startup_status
if not startup.database_ready:
    st.error(startup.message)
    if startup.missing_tables:
        st.code("python -m utils.db_init", language="bash")
    st.stop()
elif startup.views_refreshed:
    st.toast("已自动刷新缺失的预聚合视图", icon="✅")


left, right = st.columns([0.48, 0.52], gap="large")

with left:
    st.subheader("对话区")
    for item in st.session_state.history:
        role = item["role"]
        if role == "user":
            st.chat_message("user").write(item["content"])
        else:
            st.chat_message("assistant").write(item["content"])

    user_q = st.chat_input("请输入业务问题（支持多轮追问）")
    if user_q:
        st.session_state.history.append({"role": "user", "content": user_q})

        init_state = AgenticState(user_question=user_q, quick_mode=True)
        config = {"configurable": {"thread_id": st.session_state.thread_id}}
        try:
            with st.spinner("正在分析与生成图表（可能需要 10~60 秒）..."):
                out_state = st.session_state.graph.invoke(init_state, config=config)
            st.session_state.last_state = out_state
            final_answer = _get_field(out_state, "final_answer", "")
            if not final_answer:
                final_answer = "已完成运行，但未生成 final_answer（请查看右侧数据表/图表或检查日志）。"
            st.session_state.history.append({"role": "assistant", "content": final_answer})
        except Exception as e:
            st.session_state.last_state = None
            st.session_state.history.append(
                {"role": "assistant", "content": f"运行失败：{type(e).__name__}: {e}"}
            )
        st.rerun()


with right:
    st.subheader("图表与结果")
    if st.session_state.history and st.session_state.history[-1]["role"] == "assistant":
        st.caption("图表来自预聚合视图 + 自动可视化 Agent。")

    # show latest run artifacts if exist
    # (recompute from last assistant output is expensive; instead we keep last state in session)
    if "last_state" not in st.session_state:
        st.session_state.last_state = None

    # A simple button to rerun last question and store state with figures/tables
    if st.button("重新生成图表（使用最近一次提问）", type="primary"):
        last_user_q = None
        for it in reversed(st.session_state.history):
            if it["role"] == "user":
                last_user_q = it["content"]
                break
        if last_user_q:
            init_state = AgenticState(user_question=last_user_q, quick_mode=False)
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            out_state = st.session_state.graph.invoke(init_state, config=config)
            st.session_state.last_state = out_state
        else:
            st.warning("没有找到历史提问。")

    state = st.session_state.last_state
    if state:
        figures = _get_field(state, "figures", []) or []
        tables = _get_field(state, "tables", {}) or {}

        if figures:
            for p in figures:
                if Path(p).exists():
                    st.image(p, use_container_width=True)

        if tables:
            with st.expander("数据表（节选）", expanded=False):
                for k, v in tables.items():
                    if k.startswith("_"):
                        continue
                    df = pd.DataFrame(v)
                    st.markdown(f"**{k}**  (rows={len(df):,})")
                    st.dataframe(df.head(200), use_container_width=True)

