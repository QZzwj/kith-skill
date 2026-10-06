"""Time-aware relationship memory derived from the existing memory sections."""
from __future__ import annotations

import hashlib
import re

from .models import Msg
from .cite import claims_of

_KIND = {
    "关系时间线": "fact",
    "一起去过的地方": "fact",
    "inside_jokes": "joke",
    "争吵模式": "fact",
    "甜蜜瞬间": "fact",
    "称呼与专属用语": "mentioned",
}


def _status(kind: str, text: str) -> str:
    # A phrase explicitly classified as an inside joke keeps that meaning even
    # when it contains words such as "一定" or "下次".
    if kind == "joke":
        return "joke"
    if any(word in text for word in ("不确定", "不一定", "可能", "好像", "似乎",
                                     "保证不了", "不能保证", "没法保证")):
        return "uncertain"
    if any(word in text for word in ("答应", "保证", "一定", "承诺")):
        return "promise"
    if any(word in text for word in ("下次", "改天", "以后", "说定", "打算", "计划", "准备", "约好")):
        return "plan"
    # Merely mentioning a place or an event does not establish that it happened.
    for match in re.finditer(r'刚到|已经到|去了|去过|完成了|交了|成功了', text):
        prefix = re.split(r'[，。！？；,!?;\n]', text[:match.start()])[-1][-8:]
        if not re.search(r'不|没|未|别', prefix):
            return 'fact'
    return 'mentioned'


def build(memory: dict, msgs: list[Msg], cites=None) -> list[dict]:
    ledger = []
    for section, values in memory.items():
        if not isinstance(values, list):
            continue
        kind = _KIND.get(section, "mentioned")
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            claims = claims_of(section, text)
            evidence = [(index, msg) for index, msg in enumerate(msgs, 1)
                        if any(claim in msg.text for claim in claims if len(claim) >= 2)]
            dates = [msg.ts for _, msg in evidence if msg.ts]
            sessions = {msg.ts.date().isoformat() for _, msg in evidence if msg.ts}
            status = _status(kind, ' '.join(claims))
            if not evidence and status not in ('plan', 'promise', 'joke'):
                status = 'uncertain'
            identity = hashlib.sha256((section + '\n' + text).encode()).hexdigest()[:16]
            ledger.append({
                "id": identity,
                "text": text,
                "section": section,
                "kind": kind,
                "status": status,
                "time_start": min(dates).date().isoformat() if dates else None,
                "time_end": max(dates).date().isoformat() if dates else None,
                "date_semantics": "observed_in_chat",
                "expires_at": None,
                "validity": "needs_confirmation" if status in ('plan', 'promise', 'uncertain') else "historical_observation",
                "source": cites.mark(section, text).strip() if cites else '',
                "evidence": [{"message": index, "quote": msg.text, "time": msg.ts.isoformat() if msg.ts else None}
                             for index, msg in evidence[:3]],
                "confidence": ('repeated_observation' if len(sessions) > 1 else 'single_observation')
                              if evidence else 'uncertain',
            })
    return ledger


def package_data(ledger: list[dict]) -> dict:
    return {"schema_version": 1, "statuses": ["fact", "plan", "promise", "mentioned", "joke", "uncertain"],
            "memories": ledger}


def status_label(status: str) -> str:
    return {"fact": "事实", "plan": "计划", "promise": "承诺", "mentioned": "提及",
            "joke": "玩笑", "uncertain": "不确定"}.get(status, status)

