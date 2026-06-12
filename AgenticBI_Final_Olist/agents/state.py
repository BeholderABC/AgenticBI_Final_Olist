from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgenticState:
    user_question: str
    # Conversation turns from the UI/CLI. Each item is {"role": "user"|"assistant", "content": "..."}.
    conversation_history: list[dict[str, str]] = field(default_factory=list)
    # quick_mode=True: prioritize responsiveness (<60s) and generate a minimal chart set.
    # quick_mode=False: generate full dashboard charts (>=6 types) when explicitly requested.
    quick_mode: bool = True
    # Which charts to generate for this question. Empty => skip drawing.
    requested_charts: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    plan_detail: dict[str, Any] = field(default_factory=dict)
    route: dict[str, bool] = field(default_factory=dict)
    tables: dict[str, Any] = field(default_factory=dict)  # name -> df (serialized later)
    figures: list[str] = field(default_factory=list)  # file paths
    forecast: dict[str, Any] = field(default_factory=dict)
    nlp: dict[str, Any] = field(default_factory=dict)
    # C8-C9 additions: what-if simulation and anomaly detection results
    whatif: dict[str, Any] = field(default_factory=dict)
    anomaly: dict[str, Any] = field(default_factory=dict)
    final_answer: str = ""

