"""关系类型：同一份聊天记录，恋人和同事需要的东西并不一样。

问题出在模板的默认假设上。`render.py` 的章节是按恋爱关系设计的，
拿一份同事协作记录去蒸馏，就会产出「甜蜜瞬间：黄泉清：『打go的那就稳了』」
这种滑稽结果，而「inside jokes」「称呼与专属用语」只能留空。

这里只做两件事：
1. 用称呼与话题词粗略判断关系类型（判断错了也不影响抽取出的事实）；
2. 提供「同一批内部字段、换个关系换个说法」的标题映射。

刻意不做的：不按关系类型改词表。改词表会让人猜不出某条结论是怎么来的，
而改标题是纯展示层的事，错了也一眼能看出来。
"""

from __future__ import annotations

from collections import Counter

from .models import Msg

__all__ = ["RELATIONS", "detect", "title_for", "section_titles"]

RELATIONS = ("恋人", "朋友", "同事", "家人")

#: 各关系类型的信号词。命中密度最高的胜出。
SIGNALS: dict[str, tuple[str, ...]] = {
    "恋人": ("想你", "喜欢你", "爱你", "宝贝", "宝宝", "抱抱", "亲亲", "么么",
             "老公", "老婆", "亲爱的", "约会", "牵手", "异地", "想我"),
    "家人": ("爸", "妈", "爷爷", "奶奶", "姥姥", "外公", "外婆", "哥", "姐",
             "弟", "妹", "家里", "过年", "压岁钱", "回家"),
    "同事": ("项目", "需求", "排期", "上线", "汇报", "会议", "客户", "甲方", "领导",
             "同事", "面试", "方案", "代码", "排针", "物料", "生产", "实习", "培训",
             "实验室", "开发", "测试", "文档", "汇报", "任务"),
}

#: 内部字段 -> 各关系下的显示标题。字段名不动，只换说法。
TITLES: dict[str, dict[str, str]] = {
    "恋人": {
        "关系时间线": "关系时间线",
        "一起去过的地方": "一起去过的地方",
        "inside_jokes": "inside jokes",
        "争吵模式": "争吵模式",
        "甜蜜瞬间": "甜蜜瞬间",
        "称呼与专属用语": "称呼与专属用语",
    },
    "朋友": {
        "关系时间线": "认识与相处时间线",
        "一起去过的地方": "一起去过的地方",
        "inside_jokes": "inside jokes",
        "争吵模式": "闹别扭的时候",
        "甜蜜瞬间": "相处高光",
        "称呼与专属用语": "互相怎么称呼",
    },
    "同事": {
        "关系时间线": "共事时间线",
        "一起去过的地方": "一起去过 / 提到的地方",
        "inside_jokes": "你们之间的固定说法",
        "争吵模式": "分歧与摩擦",
        "甜蜜瞬间": "配合默契的瞬间",
        "称呼与专属用语": "互相怎么称呼",
    },
    "家人": {
        "关系时间线": "关系时间线",
        "一起去过的地方": "一起去过的地方",
        "inside_jokes": "家里的梗",
        "争吵模式": "争执模式",
        "甜蜜瞬间": "温暖瞬间",
        "称呼与专属用语": "称呼与专属用语",
    },
}

#: 每千字命中多少才算"有信号"
_MIN_DENSITY = 1.0


def detect(msgs: list[Msg], target: str) -> tuple[str, str]:
    """粗略判断关系类型，返回 (类型, 判断依据)。"""
    texts = [m.text for m in msgs if m.speaker == target and m.text.strip()]
    if not texts:
        return "朋友", "没有可用消息，按默认的「朋友」处理"

    joined = "\n".join(texts)
    length = max(1, sum(len(t) for t in texts))
    density = {name: sum(joined.count(w) for w in words) / length * 1000
               for name, words in SIGNALS.items()}

    best, score = max(density.items(), key=lambda kv: kv[1])
    if score < _MIN_DENSITY:
        top = ", ".join(f"{k} {v:.1f}" for k, v in sorted(density.items(), key=lambda kv: -kv[1]))
        return "朋友", f"没有明显的关系信号（每千字命中：{top}），按默认的「朋友」处理"
    return best, f"{best}信号最密（每千字命中 {score:.1f} 次）"


def section_titles(relation: str) -> dict[str, str]:
    return TITLES.get(relation, TITLES["朋友"])


def title_for(relation: str, field: str) -> str:
    return section_titles(relation).get(field, field)


def relation_hint(relation: str) -> str:
    """给 LLM 的一句话提示，让它按关系选措辞。"""
    if relation == "恋人":
        return "这段关系是恋人；亲密表达和撒娇的程度仍以原话为准，关系称谓不能替代行为依据。"
    if relation == "家人":
        return "这段关系是家人，措辞自然随性，不要写成恋人之间的甜言蜜语。"
    if relation == "同事":
        return ("这段关系是同事/工作伙伴：不要写任何恋人向的甜言蜜语。"
                "「甜蜜瞬间」写配合默契、互相搭手的片段；「争吵模式」写工作分歧。")
    return ("这段关系是朋友：措辞随意，不要写恋人向的甜言蜜语。"
            "「甜蜜瞬间」写相处愉快的片段；「争吵模式」写闹别扭的情况。")
