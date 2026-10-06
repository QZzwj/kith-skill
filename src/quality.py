"""可判定的内容筛选；不把引用命中率冒充人物还原质量。"""

from __future__ import annotations

import re

from . import offline
from .conversations import reply_exchanges, select_exchanges, split_sessions
from .models import Msg, Stats
from .verify import QUOTE_RE


_GENERIC = re.compile(r"^(?:性格|风格|特点|TA)?[：: ]*(?:幽默风趣|嘴硬心软|说话自然|"
                      r"关心对方|善解人意|活泼开朗|温柔体贴|表达简洁|自然随性)[。！! ]*$")
_TIMING_RULE = re.compile(r"秒回|隔.*(?:分钟|小时).*回|回消息(?:快|慢)|夜里更活跃|深夜型")
_ABSOLUTE = re.compile(r"从不|永不|绝不|一律不")
_PAIR = re.compile(r"对方\s*[:：]\s*((?:[「『“\"][^「」『』“”\"]+[」』”\"]\s*)+)"
                   r"(?:→|->|⇒)\s*(?:我|TA)\s*[:：]\s*"
                   r"((?:[「『“\"][^「」『』“”\"]+[」』”\"]\s*)+)")
_PAIR_QUOTES = re.compile(r'[「『“"]([^「」『』“”"]+)[」』”"]')


def _pairs(item: str) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    return [(tuple(q.strip() for q in _PAIR_QUOTES.findall(left)),
             tuple(q.strip() for q in _PAIR_QUOTES.findall(right)))
            for left, right in _PAIR.findall(item)]


def _matches_quotes(item: str, texts: list[str]) -> bool:
    quotes = QUOTE_RE.findall(item)
    return bool(quotes) and all(any(quote in text for text in texts) for quote in quotes)


def prepare_persona(persona: dict, msgs: list[Msg], target: str, stats: Stats,
                    desc: str = "", relation: str = "朋友") -> tuple[dict, list[str]]:
    """筛掉泛标签、未获支持的新策略和执行不了的规则，缺少接法时用真实片段补齐。"""
    local, _ = offline.distill(msgs, target, stats, desc, relation)
    result = {key: list(value) for key, value in persona.items() if isinstance(value, list)}
    notes = []
    removed = 0
    texts = [m.text for m in msgs]
    mine = [m.text for m in msgs if m.speaker == target]
    other = offline._counterpart(stats, target)
    exchanges = reply_exchanges(msgs, target, other) if other else []
    valid_pairs = {(tuple(e.incoming), tuple(e.reply)) for e in exchanges}
    for key in ("人物特点", "情境策略", "接话方式", "说话风格", "情感模式", "温度与分寸", "关系行为", "硬规则"):
        kept = []
        for item in result.get(key, []):
            if not isinstance(item, str) or _GENERIC.fullmatch(item.strip()):
                removed += 1
                continue
            if key == "硬规则" and (_TIMING_RULE.search(item)
                                  or (_ABSOLUTE.search(item) and re.search(r"表情|亲昵|肉麻|关心|直球", item))):
                removed += 1
                continue
            if key in ("人物特点", "情境策略", "接话方式"):
                quotes = _PAIR_QUOTES.findall(item)
                supported = _matches_quotes(item, texts) and any(
                    quote in text for quote in quotes for text in mine)
                # 新策略需完整摘录真实接话对，不能用两条孤立原话自证。
                if key in ("情境策略", "接话方式"):
                    pairs = _pairs(item)
                    supported = bool(pairs) and all(pair in valid_pairs for pair in pairs)
                if not supported:
                    removed += 1
                    continue
            kept.append(item)
        result[key] = kept
    sessions = split_sessions(msgs)
    phrases = []
    for item in result.get("口头禅", []):
        quotes = _PAIR_QUOTES.findall(item)
        if not quotes:
            quotes = [re.split(r"[（(]", item, maxsplit=1)[0].strip()]
        if not quotes or not all(sum(quote in text for text in mine) >= 2 for quote in quotes):
            removed += 1
            continue
        if all(m.ts for m in msgs) and not all(sum(
                any(m.speaker == target and quote in m.text for m in session)
                for session in sessions) >= 2 for quote in quotes):
            removed += 1
            continue
        # 使用本地词性/表达筛选，防止模型把反复出现的课名和地名当口头禅。
        if not all(offline._is_expressive(quote) for quote in quotes):
            removed += 1
            continue
        phrases.append(item)
    result["口头禅"] = phrases
    result["典型例句"] = [item for item in result.get("典型例句", [])
                          if isinstance(item, str) and item.strip('「」『』“”"') in mine]
    if removed:
        notes.append(f"筛除 {removed} 条泛化标签、无原话支撑的策略、话题词或不适合作为指令的规则")
    filled = []
    for key in ("人物特点", "情境策略", "接话方式", "硬规则", "说话风格"):
        if not result.get(key) and local.get(key):
            result[key] = local[key]
            filled.append(key)
    if filled:
        notes.append("从完整会话补入：" + "、".join(filled))
    # 完整记录的计数由本地提供，不使用模型对抽样片段猜测的次数。
    for key in ("说话风格", "情感模式", "温度与分寸", "关系行为"):
        # 统计仍可审阅，但不挤占运行时的主技能；带具体原话的行为描述留在正文。
        instructions = []
        for item in result.get(key, []):
            if not (re.match(r"消息长度：|标点：|作息：|情绪基调：|表达频率：|回复速度：|"
                             r"主动性：|话量：|篇幅对称：|亲密度\s*\d|冷热节奏：", item)
                    and not QUOTE_RE.search(item)):
                instructions.append(item)
        result[key] = instructions
    result["统计画像"] = local["统计画像"]
    # 多批失败时仍可能留下很长的并集；保留有区别的示范，正文不堆重复条目。
    if len(result.get("接话方式", [])) > 8:
        selected = {(tuple(e.incoming), tuple(e.reply)) for e in select_exchanges(exchanges, 8)}
        preferred = [item for item in result["接话方式"] if any(pair in selected for pair in _pairs(item))]
        result["接话方式"] = (preferred + [item for item in result["接话方式"] if item not in preferred])[:8]
    for key, limit in (("人物特点", 4), ("情境策略", 6), ("口头禅", 12), ("典型例句", 8)):
        result[key] = list(dict.fromkeys(result.get(key, [])))[:limit]
    notes.append(f"保留 {len(result.get('人物特点', []))} 条有原话的人物特点、"
                 f"{len(result.get('情境策略', []))} 条情境接法、"
                 f"{len(result.get('接话方式', []))} 段接话示范；引用核验不能判断语义是否成立或是否像本人")
    return result, notes
