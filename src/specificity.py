"""Evidence-based specificity scores for persona observations."""
from __future__ import annotations

import re
from collections import Counter

from .cite import claims_of
from .models import Msg
from .message_index import build as index_messages

_GENERIC = re.compile(
    r"幽默|风趣|嘴硬心软|说话自然|关心对方|善解人意|活泼开朗|温柔体贴|表达简洁|自然随性|"
    r"很有个性|性格很好|比较外向|比较内向|喜欢聊天|情商高|人很好"
)
_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_-]{2,}")


def _tokens(text: str) -> list[str]:
    tokens = set()
    for token in _TOKEN.findall(text or ""):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            tokens.update(token[i:i+n] for n in (2, 3, 4) for i in range(len(token)-n+1))
        else:
            tokens.add(token.lower())
    return list(tokens)


def _claims(section: str, item: str) -> list[str]:
    return [claim.strip("「」『』“”\"' ") for claim in claims_of(section, item) if len(claim.strip()) >= 2]


def _evidence(section: str, item: str, msgs: list[Msg]) -> list[dict]:
    claims = _claims(section, item)
    result = []
    for index, msg in enumerate(msgs, 1):
        if any(claim and claim in msg.text for claim in claims):
            result.append({
                "message": index,
                "time": msg.ts.isoformat() if msg.ts else None,
                "speaker": msg.speaker,
                "quote": msg.text,
            })
    # For model-written traits without explicit quotes, a conservative substring
    # match is still useful for navigation, but never claims semantic proof.
    if not result:
        compact = re.sub(r"[「」『』“”\"'（）()，。！？、；：: ]", "", item)
        for index, msg in enumerate(msgs, 1):
            if len(compact) >= 6 and compact in re.sub(r"\W", "", msg.text):
                result.append({"message": index, "time": msg.ts.isoformat() if msg.ts else None,
                               "speaker": msg.speaker, "quote": msg.text})
    return result


def _risk(item: str, quote_count: int, session_count: int, unique_count: int) -> str:
    if not quote_count:
        return "high"
    if _GENERIC.search(item) or session_count <= 1 or unique_count == 0:
        return "medium"
    return "low"


def _score(quote_count: int, session_count: int, unique_count: int, risk: str) -> int:
    score = min(45, quote_count * 12) + min(30, session_count * 15) + min(25, unique_count * 5)
    return max(0, min(100, score - {"high": 35, "medium": 12, "low": 0}[risk]))


def build(persona: dict, msgs: list[Msg], target: str = "") -> dict:
    # Token rarity is calculated against the target's own messages so a common
    # topic word does not inflate a personality score.
    target_texts = [m.text for m in msgs if not target or m.speaker == target]
    frequencies = Counter(token for text in target_texts for token in _tokens(text))
    other_frequencies = Counter(token for m in msgs if target and m.speaker != target for token in _tokens(m.text))
    index_rows = index_messages(msgs)["messages"]
    session_for = {row["index"]: row["session"] for row in index_rows if row["time"]}
    items = []
    for section, values in persona.items():
        if not isinstance(values, list):
            continue
        for ordinal, raw in enumerate(values, 1):
            text = str(raw).strip()
            if not text:
                continue
            evidence = _evidence(section, text, msgs)
            mine = [row for row in evidence if not target or row["speaker"] == target]
            sessions = {session_for[row["message"]] for row in mine if row["message"] in session_for}
            tokens = {token for row in mine for token in _tokens(row["quote"])}
            unique = sorted((token for token in tokens if frequencies.get(token, 0) > other_frequencies.get(token, 0)
                             and token not in {"知道", "现在", "已经", "这个", "那个", "真的", "我们", "你们", "然后", "什么"}),
                            key=lambda word: (-len(word), -frequencies[word], word))
            risk = _risk(text, len(mine), len(sessions), len(unique))
            items.append({
                "id": f"{section}-{ordinal}",
                "section": section,
                "text": text,
                "quote_count": len(mine),
                "session_count": len(sessions),
                "unique_words": unique[:12],
                "generalization_risk": risk,
                "score": _score(len(mine), len(sessions), len(unique), risk),
                "evidence": mine,
            })
    trait_items = [item for item in items if item["section"] == "人物特点"]
    return {
        "schema_version": 1,
        "target": target,
        "items": items,
        "traits": trait_items,
        "summary": {
            "items": len(items),
            "traits": len(trait_items),
            "low_risk": sum(item["generalization_risk"] == "low" for item in items),
            "medium_risk": sum(item["generalization_risk"] == "medium" for item in items),
            "high_risk": sum(item["generalization_risk"] == "high" for item in items),
        },
    }


def render_markdown(data: dict) -> str:
    lines = ["## 具体性评分", "", "评分依据是原话数量、跨会话覆盖和独特词；它衡量证据密度，不等于性格准确率。", ""]
    for item in data.get("traits", data.get("items", [])):
        evidence = "、".join(f"[{row['message']}]" for row in item.get("evidence", [])) or "无"
        lines.append(
            f"- {item['text']}：{item['score']}/100；原话 {item['quote_count']} 条；"
            f"会话 {item['session_count']} 段；独特词 {', '.join(item['unique_words']) or '无'}；"
            f"泛化风险 {item['generalization_risk']}；出处 {evidence}"
        )
    return "\n".join(lines) + "\n"
