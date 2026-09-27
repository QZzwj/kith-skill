from .analysis import stats_markdown
from .models import Stats
from .relation import title_for

#: memory.md 的章节顺序。字段名固定，**显示标题按关系类型换**——
#: 同事记录里的「甜蜜瞬间」应该是「配合默契的瞬间」，不然读起来很滑稽。
MEMORY_ORDER = ("关系时间线", "一起去过的地方", "inside_jokes", "争吵模式",
                "甜蜜瞬间", "称呼与专属用语")

#: 背景资料的章节顺序。和人设同一批字段，但去掉「你就是 X」这类扮演指令。
PROFILE_ORDER = ("身份", "说话风格", "口头禅", "情感模式", "关系行为", "典型例句", "硬规则")

#: 背景资料的文件名：本人使用时它是「关于你」，公开使用时它是「关于 TA」。
PROFILE_FILE = {"本人": "references/self.md", "公开": "references/other.md"}


def _bullet(persona: dict, key: str, fallback: str, cites=None) -> str:
    items = persona.get(key) or []
    if not items:
        return f"（暂缺：{fallback}）"
    return "\n".join(f"- {x}{cites.mark(key, str(x)) if cites else ''}" for x in items)


def _top_phrases(stats: Stats) -> str:
    return "、".join(p for p, _ in stats.phrases.most_common(8)) or "（样本太少）"


def _about_section(name: str, profile: dict, audience: str) -> str:
    """主技能里的一节：让模型开口前先知道「对面是谁」。

    这一节就是"更懂你"的落点——本人使用时它写的是你，公开使用时写的是 TA。
    """
    def pick(key: str, limit: int) -> str:
        return "；".join(str(x) for x in (profile.get(key) or [])[:limit])

    why = (f"对话对象就是 {name}。按 TA 的习惯回应，别把 TA 当成陌生人。"
           if audience == "本人" else
           f"对话里可能提到 {name}。下面是 TA 是谁，别把 TA 说成你不认识的人。")
    lines = [f"## 关于 {name}（背景资料）", "", f"- {why}"]
    for label, key, limit in (("TA 的说话风格", "说话风格", 2),
                              ("TA 在意什么", "情感模式", 2),
                              ("相处节奏", "关系行为", 2)):
        text = pick(key, limit)
        if text:
            lines.append(f"- {label}：{text}")
    lines.append(f"- 想更了解 TA，先用 skill_search 检索 {PROFILE_FILE.get(audience, PROFILE_FILE['本人'])}。")
    return "\n" + "\n".join(lines) + "\n\n"      # 前置空行：上一节是 硬规则 的列表，不留空行会粘在一起


def render_skill_md(display: str, slug: str, desc: str, persona: dict, stats: Stats,
                    relation: str = "", audience: str = "本人",
                    counterpart: str = "", counterpart_profile: dict | None = None,
                    extra_refs: list[str] | None = None, cites=None) -> str:
    """主技能。

    ``audience`` 决定它给谁用：
    - ``本人``（默认）：主技能扮演**对方**，你是使用者；``counterpart_profile`` 传入的是你自己的画像。
    - ``公开``：主技能扮演**你自己**，别人来跟你的分身聊；``counterpart_profile`` 传入的是对方的画像。

    不传 ``counterpart_profile`` 时，输出与加这个功能之前完全一致。
    """
    top = _top_phrases(stats)

    if audience == "公开":
        header = f"# {display} · 人设（公开版）"
        role_lines = (
            f"- 你在扮演 {display}，不要自称 AI、不要解释自己是模型。\n"
            f"- 说清身份：你是 {display} 的分身，不是 TA 本人；对面可能并不认识 TA。\n"
            "- 这份文件可能被本人以外的人读到：只讲聊天记录里写过的事，不主动展开私密细节。"
        )
    else:
        header = f"# {display} · 人设（Part B）"
        role_lines = f"- 你就是 {display}，不要自称 AI、不要解释自己是模型。"

    about = (_about_section(counterpart, counterpart_profile, audience)
             if counterpart_profile else "")
    refs_lines = ""
    if extra_refs:
        listed = "、".join(extra_refs)
        refs_lines = (f"- 本技能自带原始材料（{listed}）：问到「哪天」「哪次」「当时原话」时，\n"
                      "  先检索它们再回答，引用命中的原话，不要凭印象编。\n")

    return f"""---
name: {display}
description: 用 {display} 的方式说话的本地人设技能。当用户想以 {display} 的口吻聊天、回忆共同经历时使用。
---

{header}

> {desc or '由聊天记录蒸馏生成'}

## 硬规则（最高优先级）
{_bullet(persona, '硬规则', '说话底线', cites)}
{role_lines}
- 不确定的细节不要编：需要共同经历时，先用 skill_search 检索 references/memory.md 再回答。
- 保持 {display} 的语言习惯，不要变得过度礼貌或书面化。
{about}
## 身份与背景
{_bullet(persona, '身份', f'{display} 的基本信息', cites)}
{f'- 关系定位：{relation}。措辞要按这个关系来，不要越界。' if relation else ''}

## 说话风格
{_bullet(persona, '说话风格', '句式与语气特点', cites)}
- 高频口头禅（统计得到）：{top}

## 口头禅（尽量原样使用）
{_bullet(persona, '口头禅', '聊天里的高频表达', cites)}

## 情感模式
{_bullet(persona, '情感模式', '关心/生气/开心的表达方式', cites)}

## 关系行为
{_bullet(persona, '关系行为', '主动性与回消息节奏', cites)}

## 典型例句（模仿这些语感）
{_bullet(persona, '典型例句', '原话样本', cites)}

## 记忆检索提示
- 用户问到「我们」「那次」「记得吗」这类内容时，先用 `skill_search` 在该技能里检索关键词，
  再用 `skill_read` 读取 `references/memory.md` 对应片段，用它的细节回答，不要凭空编。
{refs_lines}"""


def render_profile_md(display: str, persona: dict, stats: Stats, relation: str,
                      role_note: str, cites=None) -> str:
    """背景资料（``references/self.md`` / ``references/other.md``）。

    用的是同一批人设字段，但**去掉扮演指令**：它是「X 是什么样」，
    不是「你来扮演 X」——免得设备把背景资料也当成人设读。
    """
    sections = "".join(
        f"## {key}\n\n{_bullet(persona, key, key, cites)}\n\n" for key in PROFILE_ORDER)
    return f"""# {display} · 背景资料

> {role_note}
> 关系类型：{relation}；高频表达：{_top_phrases(stats)}

{sections}"""


def render_memory_md(display: str, memory: dict, stats: Stats, target: str,
                     relation: str = "朋友", cites=None) -> str:
    def section(key: str) -> str:
        title = title_for(relation, key)
        items = memory.get(key) or []
        if not items:
            return f"## {title}\n\n（聊天记录里没有找到相关内容）\n\n"
        return ("## " + title + "\n\n"
                + "\n".join(f"- {x}{cites.mark(key, str(x)) if cites else ''}" for x in items)
                + "\n\n")

    return f"""# {display} · 关系记忆（Part A）

> 关系类型：{relation}

{"".join(section(key) for key in MEMORY_ORDER)}
{stats_markdown(stats, target)}
"""


# ----------------------------------------------------------------------------
# 七、打包与上传
# ----------------------------------------------------------------------------
