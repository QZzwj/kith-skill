from .analysis import stats_markdown
from .models import Stats
from .relation import title_for

#: memory.md 的章节顺序。字段名固定，**显示标题按关系类型换**——
#: 同事记录里的「甜蜜瞬间」应该是「配合默契的瞬间」，不然读起来很滑稽。
MEMORY_ORDER = ("关系时间线", "一起去过的地方", "inside_jokes", "争吵模式",
                "甜蜜瞬间", "称呼与专属用语")


def render_skill_md(display: str, slug: str, desc: str, persona: dict, stats: Stats,
                    relation: str = "") -> str:
    def bullet(key: str, fallback: str) -> str:
        items = persona.get(key) or []
        if not items:
            return f"（暂缺：{fallback}）"
        return "\n".join(f"- {x}" for x in items)

    top = "、".join(p for p, _ in stats.phrases.most_common(8)) or "（样本太少）"
    return f"""---
name: {display}
description: 用 {display} 的方式说话的本地人设技能。当用户想以 {display} 的口吻聊天、回忆共同经历时使用。
---

# {display} · 人设（Part B）

> {desc or '由聊天记录蒸馏生成'}

## 硬规则（最高优先级）
{bullet('硬规则', '说话底线')}
- 你就是 {display}，不要自称 AI、不要解释自己是模型。
- 不确定的细节不要编：需要共同经历时，先用 skill_search 检索 references/memory.md 再回答。
- 保持 {display} 的语言习惯，不要变得过度礼貌或书面化。

## 身份与背景
{bullet('身份', f'{display} 的基本信息')}
{f'- 关系定位：{relation}。措辞要按这个关系来，不要越界。' if relation else ''}

## 说话风格
{bullet('说话风格', '句式与语气特点')}
- 高频口头禅（统计得到）：{top}

## 口头禅（尽量原样使用）
{bullet('口头禅', '聊天里的高频表达')}

## 情感模式
{bullet('情感模式', '关心/生气/开心的表达方式')}

## 关系行为
{bullet('关系行为', '主动性与回消息节奏')}

## 典型例句（模仿这些语感）
{bullet('典型例句', '原话样本')}

## 记忆检索提示
- 用户问到「我们」「那次」「记得吗」这类内容时，先用 `skill_search` 在该技能里检索关键词，
  再用 `skill_read` 读取 `references/memory.md` 对应片段，用它的细节回答，不要凭空编。
"""


def render_memory_md(display: str, memory: dict, stats: Stats, target: str,
                     relation: str = "朋友") -> str:
    def section(key: str) -> str:
        title = title_for(relation, key)
        items = memory.get(key) or []
        if not items:
            return f"## {title}\n\n（聊天记录里没有找到相关内容）\n\n"
        return f"## {title}\n\n" + "\n".join(f"- {x}" for x in items) + "\n\n"

    return f"""# {display} · 关系记忆（Part A）

> 关系类型：{relation}

{"".join(section(key) for key in MEMORY_ORDER)}
{stats_markdown(stats, target)}
"""


# ----------------------------------------------------------------------------
# 七、打包与上传
# ----------------------------------------------------------------------------
