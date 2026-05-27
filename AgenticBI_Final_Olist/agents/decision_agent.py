from __future__ import annotations

import json

from models.deepseek_client import DeepSeekClient, ChatMessage


SYSTEM = """You are a decision intelligence agent for an e-commerce platform.
Input will include:
- descriptive/diagnostic tables summary
- forecast results
- NLP insights (negative themes)

Your output must be actionable and prescriptive:
- 3-5 prioritized actions with expected impact and how-to steps
- mention what metrics to monitor
- if asked for what-if, provide assumptions and approximate estimate
Respond in Chinese.
"""


def run_decision_agent(
    user_question: str,
    analysis_summary: str,
    forecast_summary: str | None,
    nlp_summary: str | None,
) -> str:
    client = DeepSeekClient()
    content = client.chat(
        [
            ChatMessage(role="system", content=SYSTEM),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {
                        "question": user_question,
                        "analysis_summary": analysis_summary,
                        "forecast_summary": forecast_summary,
                        "nlp_summary": nlp_summary,
                    },
                    ensure_ascii=False,
                ),
            ),
        ],
        temperature=0.2,
    )
    return content

