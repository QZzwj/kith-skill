"""Pre-release privacy scan for generated skill packages."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

from . import storage, versions
from .privacy import DEIXIS, redact

RULES = (
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号可能未脱敏"),
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "邮箱可能未脱敏"),
    ("id_or_card", re.compile(r"(?<!\d)(?:\d{17}[\dXx]|\d{16,19})(?!\d)"), "身份证或银行卡号可能未脱敏"),
    ("private_deixis", re.compile("|".join(re.escape(x) for x in DEIXIS)), "包含只对本人有意义的私密指代"),
    ("location", re.compile(r"(?:[\u4e00-\u9fff]{2,12})(?:省|市|区|县|镇|街道|路|号|宿舍|学校|公司|医院)"), "包含地点、单位或地址线索"),
)


def scan_text(text: str, filename: str = "") -> list[dict]:
    items = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for category, pattern, suggestion in RULES:
            match = pattern.search(line)
            if not match:
                continue
            fragment = match.group(0)[:120]
            item_id = hashlib.sha256(f"{filename}:{line_no}:{category}:{line}".encode()).hexdigest()[:16]
            items.append({"id": item_id, "file": filename, "line": line_no,
                          "category": category, "severity": "high" if category in ("phone", "email", "id_or_card") else "medium",
                          "text": fragment, "redacted": redact(fragment), "suggestion": suggestion})
    return items


def review(root: Path) -> dict:
    items = []
    for filename, data in versions.current_files(root).items():
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            items.append({'id': hashlib.sha256(filename.encode() + data).hexdigest()[:16],
                          'file': filename, 'line': None, 'category': 'binary', 'severity': 'high',
                          'text': '二进制原始导出', 'redacted': '', 'suggestion': '无法自动扫描，请人工检查原始导出后再分享'})
            continue
        items.extend(scan_text(text, filename))
    risk = "high" if any(item["severity"] == "high" for item in items) else "medium" if items else "low"
    return {"schema_version": 1, "risk": risk, "items": items, "scanned_at": storage.now(),
            "root": root.name, "fingerprint": versions.fingerprint(root)}


def confirmation_path(root: Path) -> Path:
    return storage.local_dir(root) / "privacy.json"


def confirm(root: Path, item_id: str, confirmed: bool = True) -> dict:
    with storage.lock(root):
        report = review(root)
        if item_id not in {item['id'] for item in report['items']}:
            raise ValueError('该条目已变化，请重新扫描')
        state = storage.load(confirmation_path(root), {}) or {}
        values = set(state.get('confirmed', [])) if state.get('fingerprint') == report['fingerprint'] else set()
        if confirmed:
            values.add(item_id)
        else:
            values.discard(item_id)
        state = {'confirmed': sorted(values), 'fingerprint': report['fingerprint']}
        storage.write(confirmation_path(root), state)
        return state


def with_confirmations(root: Path, report: dict) -> dict:
    state = storage.load(confirmation_path(root), {"confirmed": []}) or {"confirmed": []}
    confirmed = set(state.get("confirmed", [])) if state.get('fingerprint') == report.get('fingerprint') else set()
    result = dict(report)
    result["items"] = [{**item, "confirmed": item["id"] in confirmed} for item in report.get("items", [])]
    result["unconfirmed"] = sum(not item["confirmed"] for item in result["items"])
    return result

