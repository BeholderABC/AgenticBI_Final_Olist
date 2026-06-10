from __future__ import annotations

import json
from typing import Any

from models.deepseek_client import ChatMessage, DeepSeekClient


SYSTEM_PROMPT = """You are the coordinator agent for an Agentic BI system.
Break the user's business question into structured subtasks and decide which agents are needed.

Return JSON only:
{
  "intent": "descriptive|diagnostic|forecast|prescriptive|mixed",
  "subtasks": [
    {"agent": "sql|forecast|nlp|viz|decision", "task": "short task", "reason": "short reason"}
  ],
  "route": {
    "analysis": true,
    "forecast": true|false,
    "nlp": true|false,
    "viz": true|false,
    "decision": true
  },
  "context_rewrite": "standalone question using recent conversation context"
}

Routing rules:
- Forecast questions mention future, predict, forecast, trend projection, or 6 weeks.
- NLP questions mention reviews, comments, sentiment, negative reasons, good/bad reviews, rating reasons.
- Diagnostic questions mention why, reason, delay, worse, high bad review sellers/categories, drill down.
- Descriptive questions should usually skip forecast and NLP.
- Decision is always needed to write the final business answer.
"""


FORECAST_TERMS = ("预测", "未来", "6周", "六周", "forecast", "predict", "projection")
NLP_TERMS = ("评论", "差评", "好评", "情感", "review", "rating", "原因", "主题", "词云")
DIAGNOSTIC_TERMS = ("为什么", "原因", "延迟", "差评率", "下钻", "显著高于", "诊断", "worse", "why")
VIZ_TERMS = ("图", "可视化", "趋势", "排名", "分布", "对比", "chart", "plot")
FOLLOW_UP_TERMS = ("那", "它", "这个", "再", "继续", "准时率", "细化", "呢")


def _extract_json_object(text: str) -> dict[str, Any]:
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
        raise ValueError("Coordinator response was not a JSON object.")
    return parsed


def _history_snippet(history: list[dict[str, str]], limit: int = 6) -> str:
    turns = history[-limit:]
    lines = []
    for item in turns:
        role = item.get("role", "unknown")
        content = item.get("content", "")
        if content:
            lines.append(f"{role}: {content[:500]}")
    return "\n".join(lines)


def _rule_based_plan(question: str, history: list[dict[str, str]]) -> dict[str, Any]:
    q = question.lower()
    has_history = bool(history)
    forecast = any(k in q for k in FORECAST_TERMS)
    nlp = any(k in q for k in NLP_TERMS)
    diagnostic = any(k in q for k in DIAGNOSTIC_TERMS)
    viz = (not forecast and not nlp) or any(k in q for k in VIZ_TERMS)

    if forecast and (diagnostic or nlp):
        intent = "mixed"
    elif forecast:
        intent = "forecast"
    elif diagnostic or nlp:
        intent = "diagnostic"
    elif any(k in q for k in ("建议", "策略", "降低", "优化", "方案", "决策")):
        intent = "prescriptive"
    else:
        intent = "descriptive"

    context_rewrite = question
    if has_history and any(k in question for k in FOLLOW_UP_TERMS):
        recent_user = [i.get("content", "") for i in history if i.get("role") == "user"]
        previous = recent_user[-1] if recent_user else ""
        if previous:
            context_rewrite = f"{previous}。追问：{question}"

    subtasks: list[dict[str, str]] = [
        {
            "agent": "sql",
            "task": "Query matching pre-aggregated views first, then fall back to base tables if needed.",
            "reason": "All BI answers need a structured data result.",
        }
    ]
    if forecast:
        subtasks.append(
            {
                "agent": "forecast",
                "task": "Forecast future GMV from mv_monthly_sales.",
                "reason": "The user asks about future sales or trend projection.",
            }
        )
    if nlp or diagnostic:
        subtasks.append(
            {
                "agent": "nlp",
                "task": "Extract review themes and negative feedback signals.",
                "reason": "Diagnostics need review and rating context.",
            }
        )
    if viz:
        subtasks.append(
            {
                "agent": "viz",
                "task": "Generate focused charts from available analysis tables.",
                "reason": "The answer benefits from visual comparison.",
            }
        )
    subtasks.append(
        {
            "agent": "decision",
            "task": "Synthesize data, context, and recommendations into the final answer.",
            "reason": "The user expects business interpretation.",
        }
    )

    return {
        "intent": intent,
        "subtasks": subtasks,
        "route": {
            "analysis": True,
            "forecast": forecast,
            "nlp": nlp or diagnostic,
            "viz": viz,
            "decision": True,
        },
        "context_rewrite": context_rewrite,
        "planner": "rule_fallback",
    }


def plan_question(question: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
    history = history or []
    fallback = _rule_based_plan(question, history)
    try:
        client = DeepSeekClient()
        content = client.chat(
            [
                ChatMessage(role="system", content=SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=(
                        f"Conversation history:\n{_history_snippet(history)}\n\n"
                        f"Current question:\n{question}"
                    ),
                ),
            ],
            temperature=0.1,
        )
        planned = _extract_json_object(content)
    except Exception as e:
        fallback["planner_error"] = f"{type(e).__name__}: {e}"
        return fallback

    route = planned.get("route")
    if not isinstance(route, dict):
        planned["route"] = fallback["route"]
    else:
        planned["route"] = {
            "analysis": bool(route.get("analysis", True)),
            "forecast": bool(route.get("forecast", False)),
            "nlp": bool(route.get("nlp", False)),
            "viz": bool(route.get("viz", fallback["route"]["viz"])),
            "decision": True,
        }
    if not isinstance(planned.get("subtasks"), list):
        planned["subtasks"] = fallback["subtasks"]
    if not planned.get("context_rewrite"):
        planned["context_rewrite"] = fallback["context_rewrite"]
    planned["planner"] = "llm"
    return planned
