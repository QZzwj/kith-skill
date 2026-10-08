"""Structured, conversation-grounded situation routing.

The renderer is intentionally human-readable, while this module keeps the same
evidence in a machine-readable form for regression checks and targeted feedback.
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from .conversations import (Exchange, _SITUATIONS, matches_input, reply_exchanges,
                            select_exchanges, situation)
from .models import Msg

_STOP = {
    "然后", "这个", "那个", "真的", "现在", "已经", "不是", "可以", "什么",
    "怎么", "我们", "你们", "哈哈", "一下", "一下子", "事情", "知道", "感觉",
}


def _signals(exchanges: Iterable[Exchange], limit: int = 6) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for exchange in exchanges:
        text = " ".join(exchange.incoming)
        for token in re.findall(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_-]{2,}", text):
            if token not in _STOP:
                counts[token] += 1
    return [word for word, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def scenario_id(label: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    # Chinese labels have no ASCII letters; keep IDs stable and readable.
    if not value:
        value = {
            "对方表达感谢": "thanks-reciprocity",
            "被催或被提醒": "being-reminded",
            "被指出说法或承诺有问题": "correction-or-promise",
            "对方抱怨没被叫上": "left-out-complaint",
            "对方要求正经一点": "asked-to-be-serious",
            "对方给出答应或确认": "confirmation",
            "对方报告进度或结果": "progress-or-result",
            "日常接话": "everyday-chat",
        }.get(label, "scenario")
    return value


def build_scenarios(msgs: list[Msg], target: str, counterpart: str = "", limit: int = 12) -> list[dict]:
    if not counterpart:
        names = defaultdict(int)
        for msg in msgs:
            if msg.speaker != target:
                names[msg.speaker] += 1
        counterpart = max(names, key=names.get, default="")
    exchanges = reply_exchanges(msgs, target, counterpart) if counterpart else []
    groups: dict[str, list[Exchange]] = defaultdict(list)
    actions: dict[str, str] = {}
    for exchange in exchanges:
        label, action = situation(exchange)
        if not action:
            continue
        groups[label].append(exchange)
        actions[label] = action

    ranked = sorted(groups, key=lambda label: (-len({e.session for e in groups[label]}), label))
    result = []
    for label in ranked[:limit]:
        group = groups[label]
        sessions = sorted({e.session for e in group})
        examples = []
        for exchange in select_exchanges(group, 3):
            examples.append({
                "incoming": exchange.incoming,
                "reply": exchange.reply,
                "source": f"session:{exchange.session + 1}",
                "incoming_messages": exchange.incoming_messages,
                "reply_messages": exchange.reply_messages,
                "pairing": exchange.pairing,
            })
        result.append({
            "id": scenario_id(label),
            "label": label,
            "signals": _signals(group),
            "trigger_pattern": next(left for name, left, _, _ in _SITUATIONS if name == label),
            "reply_pattern": next(right for name, _, right, _ in _SITUATIONS if name == label),
            "response_move": actions[label],
            "examples": examples,
            "avoid": ["不要把旧地点、旧承诺或单次玩笑当成当前事实"],
            "confidence": "repeated_observation" if len(sessions) > 1 else "single_observation",
            "sessions": len(sessions),
        })
    return result


def route(text: str, scenarios: list[dict]) -> dict | None:
    # A serious complaint must not be turned into an invitation to play a joke.
    if re.search(r"很难过|真的难受|不想活|崩溃|别开玩笑|认真说|不是开玩笑", text):
        return None
    ranked = []
    for item in scenarios:
        label = item.get('label', '')
        # Existing packages may retain the old broad trigger patterns. A
        # matching word alone must not override the current situation rule.
        if any(name == label for name, _, _, _ in _SITUATIONS) and not matches_input(label, text):
            continue
        score = sum(len(signal) for signal in item.get('signals', []) if signal in text)
        pattern = item.get('trigger_pattern', '')
        if pattern and re.search(pattern, text):
            score += 2
        if score:
            ranked.append((score, item))
    return max(ranked, key=lambda pair: pair[0])[1] if ranked else None


def prompt(text: str, scenarios: list[dict]) -> str:
    matched = route(text, scenarios)
    if not matched:
        return ''
    return ('【当前情境参考】\n' + matched['label'] + '：' + matched['response_move']
            + '\n避免：' + '；'.join(matched.get('avoid', []))
            + '\n只参考回应动作；无需命中原话，也不要照搬旧经历。')


def package_data(scenarios: list[dict]) -> dict:
    return {"schema_version": 1, "scenarios": scenarios}


def render_markdown(scenarios: list[dict]) -> str:
    lines = ["## 情境路由表", "", "先判断用户当前处于哪种情境，再采用对应的回应动作；示例只在相似语境下参考。", ""]
    if not scenarios:
        return "\n".join(lines + ["（记录中没有足够的相邻接话可建立路由。）", ""])
    for item in scenarios:
        confidence = "多段会话重复" if item["confidence"] == "repeated_observation" else "单次观察"
        lines += [f"### {item['label']}",
                  f"- 触发信号：{'、'.join(item['signals']) or '相似语境'}",
                  f"- 回应动作：{item['response_move']}",
                  f"- 证据强度：{confidence}（{item['sessions']} 段会话）"]
        for example in item["examples"]:
            lines.append(f"- 真实接法：对方：{' / '.join(example['incoming'])} → 我：{' / '.join(example['reply'])}")
        for avoid in item["avoid"]:
            lines.append(f"- 避免：{avoid}")
        lines.append("")
    return "\n".join(lines)
