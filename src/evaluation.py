"""Offline scenario regression cases and checks.

Static checks are deliberately separate from model scoring: quote overlap only
proves grounding, not that a response sounds like the person.
"""
from __future__ import annotations

import re
from pathlib import Path

from . import storage
from . import versions, feedback
from .scenarios import route

GENERIC = ("您好", "不客气", "很高兴能帮助", "请问还有什么", "感谢您的理解", "作为 AI")


def build_cases(scenarios: list[dict], limit: int = 30) -> list[dict]:
    cases = []
    for item in scenarios:
        for index, example in enumerate(item.get("examples", [])[:3], 1):
            incoming = " ".join(example.get("incoming", []))
            cases.append({"id": f"{item['id']}-{index}", "scenario_id": item["id"],
                          "scenario": item["label"], "prompt": incoming,
                          "expected_move": item.get("response_move", ""),
                          "allowed_quotes": example.get("reply", []),
                          "forbidden": item.get("avoid", []), "status": "not_run"})
    return cases[:limit]


def static_check(case: dict, reply: str, scenarios: list[dict] | None = None) -> dict:
    text = str(reply or "").strip()
    reasons = []
    if not text:
        reasons.append("没有回复")
    generic = next((phrase for phrase in GENERIC if phrase in text), "")
    if generic:
        reasons.append(f"泛化客服话术：{generic}")
    if any(item and item in text for item in case.get("forbidden", [])):
        reasons.append("命中禁止项")
    matched = route(case.get("prompt", ""), scenarios or []) if scenarios else None
    if scenarios and matched and matched.get("id") != case.get("scenario_id"):
        reasons.append("输入被路由到另一个情境")
    quote_hit = any(q and q in text for q in case.get("allowed_quotes", []))
    # Quoting is evidence of grounding, not a requirement: a good response can
    # use the action without copying old words.
    return {"id": case.get("id"), "scenario_id": case.get("scenario_id"),
            "prompt": case.get("prompt", ""), "reply": text,
            "passed": not reasons, "reasons": reasons,
            "quote_grounded": quote_hit, "checked": True}


def report(cases: list[dict], replies: dict[str, str] | None = None,
           scenarios: list[dict] | None = None) -> dict:
    replies = replies or {}
    results = []
    for case in cases:
        if case.get("id") not in replies:
            results.append({**case, "checked": False, "passed": None, "reasons": []})
        else:
            results.append({**case, **static_check(case, replies[case["id"]], scenarios)})
    checked = [row for row in results if row.get("checked")]
    return {"schema_version": 1, "total": len(results), "checked": len(checked),
            "passed": sum(bool(row.get("passed")) for row in checked), "results": results}


def load_package(root: Path) -> dict:
    try:
        return storage.load(root / "references" / "evaluation.json", {}) or {}
    except (OSError, ValueError):
        return {}


def cases_for(root: Path, scenarios: list[dict]) -> list[dict]:
    cases = list(load_package(root).get('cases', []))
    seen = {case.get('prompt') for case in cases}
    for row in reversed(feedback.read(root)):
        if row.get('label') not in ('太客气', '答非所问', '场景用错', '事实错误') or row.get('user') in seen:
            continue
        matched = route(row.get('user', ''), scenarios) or {}
        cases.append({'id': 'feedback-' + versions.digest((row.get('time', '') + row['user']).encode())[:16],
                      'scenario_id': row.get('scenario_id') or matched.get('id', ''),
                      'scenario': matched.get('label', '试聊失败用例'), 'prompt': row['user'],
                      'expected_move': feedback._CORRECTIONS.get(row['label'], ''),
                      'allowed_quotes': [], 'forbidden': [], 'origin': 'feedback',
                      'note': row.get('note', ''), 'failed_reply': row.get('reply', '')})
        seen.add(row['user'])
        if len(cases) >= 50:
            break
    return cases


def view(root: Path, scenarios: list[dict]) -> dict:
    cases = cases_for(root, scenarios)
    saved = storage.load(storage.local_dir(root) / 'evaluation-run.json', {}) or {}
    state = versions.state(root)
    fresh = saved.get('fingerprint') == state['fingerprint']
    # New feedback can add cases without changing the skill files.
    replies = saved.get('replies', {}) if fresh else {}
    return {**report(cases, replies, scenarios), **state, 'stale': bool(saved) and not fresh,
            'run_at': saved.get('run_at') if fresh else None}


def save(root: Path, replies: dict[str, str], scenarios: list[dict], fingerprint: str) -> dict:
    with storage.lock(root):
        state = versions.state(root)
        if fingerprint != state['fingerprint']:
            raise ValueError('技能内容已变化，请刷新后重新测评')
        cases = cases_for(root, scenarios)
        known = {case['id'] for case in cases}
        if any(key not in known for key in replies):
            raise ValueError('包含不存在的用例')
        prior = storage.load(storage.local_dir(root) / 'evaluation-run.json', {}) or {}
        merged = prior.get('replies', {}) if prior.get('fingerprint') == fingerprint else {}
        merged.update({key: str(value)[:4000] for key, value in replies.items()})
        storage.write(storage.local_dir(root) / 'evaluation-run.json',
                      {**state, 'replies': merged, 'run_at': storage.now()})
        return view(root, scenarios)

