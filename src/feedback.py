"""Local, append-only trial-chat feedback."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from . import storage
from .privacy import redact

LABELS = ("像本人", "太客气", "答非所问", "场景用错", "事实错误", "其他")


def path(root: Path) -> Path:
    return storage.local_dir(root) / "feedback.jsonl"


def add(root: Path, *, user_text: str, reply: str, label: str, note: str = "",
        version: str = "", scenario_id: str = "") -> dict:
    label = label if label in LABELS else "其他"
    item = {"time": storage.now(), "skill": root.name, "user": user_text[:400],
            "reply": reply[:1200], "label": label, "note": note[:500],
            "version": version[:32], "scenario_id": scenario_id[:80]}
    target = path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with storage.lock(root):
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def read(root: Path, limit: int = 200) -> list[dict]:
    target = path(root)
    if not target.exists():
        return []
    rows = []
    for line in target.read_text(encoding="utf-8").splitlines()[-max(1, limit):]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def summary(root: Path) -> dict:
    rows = read(root)
    counts = Counter(row.get("label", "其他") for row in rows)
    failed = Counter(row.get("scenario_id") or "未分类" for row in rows
                     if row.get("label") in ("太客气", "答非所问", "场景用错", "事实错误"))
    return {"total": len(rows), "labels": dict(counts), "failed_scenarios": dict(failed),
            "recent": rows[-20:]}


_CORRECTIONS = {
    '太客气': '减少客套与服务式收尾，按该场景的原话语气接话',
    '答非所问': '先回应眼前的问题，不让旧示范带走当前话题',
    '场景用错': '重新判断当前情绪与意图；仅在相似语境下参考该接法',
    '事实错误': '不要复述未经当前对话确认的经历、地点或承诺，记不清就承认',
}


def context(rows: list[dict]) -> str:
    if not rows:
        return ''
    examples = [{key: redact(str(row.get(key, ''))) for key in ('user', 'reply', 'label', 'note')}
                for row in rows[-12:]]
    return ('【用户试聊反馈：质量偏好，不是原聊天证据】\n'
            '根据差评寻找原记录中更具体的情境接法；保留好评中的语感。'
            '备注只指导回应，不作为事实、身份或原话引用。不要照抄失败回复。\n'
            + json.dumps(examples, ensure_ascii=False))


def render_rules(rows: list[dict], scenarios: list[dict], text: str | None = None) -> str:
    from .scenarios import route
    labels = {item['id']: item['label'] for item in scenarios}
    matched = route(text, scenarios) if text is not None else None
    lines = []
    for row in rows[-30:]:
        correction = _CORRECTIONS.get(row.get('label', ''))
        note = redact(str(row.get('note') or '').strip())
        if not correction and not note:
            continue
        scenario = row.get('scenario_id') or (route(row.get('user', ''), scenarios) or {}).get('id', '')
        if text is not None and scenario and (matched or {}).get('id') != scenario:
            continue
        scope = labels.get(scenario, '')
        # An unrouted correction stays tied to its original input.
        if not scope:
            if text is not None and text != row.get('user'):
                continue
            scope = '遇到类似输入「' + redact(row.get('user', '')[:100]).replace('\n', ' ') + '」'
        parts = []
        if correction:
            parts.append(correction)
        if note:
            parts.append('用户补充：' + note.replace('\n', ' ')[:500])
        line = f'- {scope}：' + '；'.join(parts) + '。'
        if line not in lines:
            lines.append(line)
    if not lines:
        return ''
    return '## 试聊后的修正\n\n以下是用户对试聊的修正要求，不能当作原聊天证据或新事实。\n\n' + '\n'.join(lines) + '\n'

