from __future__ import annotations

import json

from agents.graph import build_graph
from agents.state import AgenticState


def main() -> None:
    graph = build_graph()
    print("Agentic BI CLI. Type your question, or 'exit'.")
    thread_id = "cli"
    history: list[dict[str, str]] = []
    while True:
        q = input("\n> ").strip()
        if not q:
            continue
        if q.lower() in {"exit", "quit"}:
            break
        out = graph.invoke(
            AgenticState(user_question=q, conversation_history=list(history)),
            config={"configurable": {"thread_id": thread_id}},
        )
        print("\n---\n")
        print(out.final_answer)
        history.append({"role": "user", "content": q})
        history.append({"role": "assistant", "content": out.final_answer})


if __name__ == "__main__":
    main()

