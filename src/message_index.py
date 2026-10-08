"""Stable, package-safe message references used by the workbench.

Message numbers are one-based and remain stable for an unchanged transcript.
The index deliberately contains only the redacted text passed to generation.
"""
from __future__ import annotations

import hashlib

from .models import Msg, SESSION_GAP


def message_id(index: int, msg: Msg) -> str:
    value = f"{index}\n{msg.ts.isoformat() if msg.ts else ''}\n{msg.speaker}\n{msg.text}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def content_key(msg: Msg) -> str:
    value = f"{msg.ts.isoformat() if msg.ts else ''}\n{msg.speaker}\n{msg.text}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build(msgs: list[Msg]) -> dict:
    rows = []
    session = 0
    previous = None
    for index, msg in enumerate(msgs, 1):
        if msg.ts and previous and (msg.ts < previous or msg.ts - previous > SESSION_GAP):
            session += 1
        previous = msg.ts or previous
        rows.append({
            "index": index,
            "id": message_id(index, msg),
            "key": content_key(msg),
            "time": msg.ts.isoformat() if msg.ts else None,
            "date": msg.ts.date().isoformat() if msg.ts else None,
            "speaker": msg.speaker,
            "text": msg.text,
            "session": session + 1,
            "source_id": msg.source_id,
            "reply_to": msg.reply_to,
        })
    return {"schema_version": 1, "complete": True, "messages": rows}


def rows(data: dict | None) -> list[dict]:
    return list((data or {}).get("messages", []))


def by_index(data: dict | None, index: int) -> dict | None:
    return next((row for row in rows(data) if row.get("index") == index), None)
