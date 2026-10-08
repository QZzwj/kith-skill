"""Coverage matrix for observed conversation situations."""
from __future__ import annotations

import re
from .conversations import _SITUATIONS, reply_exchanges
from .message_index import build as index_messages


def build(routes: list[dict], msgs=None, target="", counterpart="") -> dict:
    by_label = {item.get("label"): item for item in routes}
    matrix = []
    exchanges = reply_exchanges(msgs, target, counterpart) if msgs and target and counterpart else []
    inputs = [row for row in index_messages(msgs or [])['messages'] if row['speaker'] == counterpart]
    for label, _left, _right, action in _SITUATIONS:
        route = by_label.get(label)
        sessions = int(route.get("sessions", 0)) if route else 0
        examples = route.get("examples", []) if route else []
        observed = [e for e in exchanges if re.search(_left, " ".join(e.incoming))]
        observed_inputs = [row for row in inputs if re.search(_left, row['text'])]
        if not route or not examples:
            status = "missing_response" if observed_inputs or route else "evidence_insufficient"
        elif sessions < 2:
            status = "evidence_insufficient"
        else:
            status = "covered"
        matrix.append({
            "id": route.get("id", label) if route else label,
            "label": label,
            "status": status,
            "sessions": sessions,
            "examples": len(examples),
            "observed_inputs": len(observed_inputs),
            "message_indices": sorted({row['index'] for row in observed_inputs} |
                                      {i for e in observed for i in e.incoming_messages + e.reply_messages}),
            "response_move": route.get("response_move", action) if route else "",
            "signals": route.get("signals", []) if route else [],
        })
    return {
        "schema_version": 1,
        "matrix": matrix,
        "summary": {
            "covered": sum(row["status"] == "covered" for row in matrix),
            "evidence_insufficient": sum(row["status"] == "evidence_insufficient" for row in matrix),
            "missing_response": sum(row["status"] == "missing_response" for row in matrix),
            "total": len(matrix),
        },
    }


def render_markdown(data: dict) -> str:
    labels = {"covered": "已覆盖", "evidence_insufficient": "证据不足", "missing_response": "缺失接法"}
    lines = ["## 情境覆盖矩阵", "", "已覆盖表示至少两段会话有可用接法；单次观察保留为证据不足，不自动升级成固定规则。", ""]
    for row in data.get("matrix", []):
        lines.append(f"- {row['label']}：{labels.get(row['status'], row['status'])}；"
                     f"会话 {row['sessions']} 段；示例 {row['examples']} 个；"
                     f"接法 {row['response_move'] or '待补标'}")
    return "\n".join(lines) + "\n"
