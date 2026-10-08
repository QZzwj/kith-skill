import json

from .analysis import stats_markdown
from .models import Stats
from .relation import title_for
from .memory_ledger import status_label

#: memory.md 的章节顺序。字段名固定，**显示标题按关系类型换**——
#: 同事记录里的「甜蜜瞬间」应该是「配合默契的瞬间」，不然读起来很滑稽。
MEMORY_ORDER = ("关系时间线", "一起去过的地方", "inside_jokes", "争吵模式",
                "甜蜜瞬间", "称呼与专属用语")

#: 背景资料的章节顺序。和人设同一批字段，但去掉「你就是 X」这类扮演指令。
PROFILE_ORDER = ("身份", "人物特点", "情境策略", "说话风格", "口头禅", "接话方式", "情感模式", "温度与分寸",
                 "关系行为", "典型例句", "硬规则")

#: 背景资料的文件名：本人使用时它是「关于你」，公开使用时它是「关于 TA」。
PROFILE_FILE = {"本人": "references/self.md", "公开": "references/other.md"}


def _bullet(persona: dict, key: str, fallback: str, cites=None) -> str:
    items = persona.get(key) or []
    if not items:
        return f"（暂缺：{fallback}）"
    return "\n".join(f"- {x}{cites.mark(key, str(x)) if cites else ''}" for x in items)


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
                    extra_refs: list[str] | None = None, cites=None,
                    scenarios_md: str = "") -> str:
    """主技能。

    ``audience`` 决定它给谁用：
    - ``本人``（默认）：主技能扮演**对方**，你是使用者；``counterpart_profile`` 传入的是你自己的画像。
    - ``公开``：主技能扮演**你自己**，别人来跟你的分身聊；``counterpart_profile`` 传入的是对方的画像。

    具体接法留在正文，统计与原话出处通过参考文件按需读取。
    """
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

    character = (f"## 人物特点\n\n{_bullet(persona, '人物特点', '', cites)}\n\n"
                 if persona.get('人物特点') else "")
    optional = "".join(f"## {key}\n\n{_bullet(persona, key, '', cites)}\n\n"
                       for key in ('情感模式', '关系行为') if persona.get(key))
    trigger = f"以 {display} 的口吻进行日常聊天、接梗和回应熟人，按聊天原话中的情境接法回答；当用户要求模仿 {display}、和 TA 聊天或回忆共同经历时使用。"
    scenario_block = (scenarios_md.strip() + "\n\n" if scenarios_md else "")
    return f"""---
name: {json.dumps(slug, ensure_ascii=False)}
description: {json.dumps(trigger, ensure_ascii=False)}
---

{header}

> {desc or '由聊天记录蒸馏生成'}

## 回应原则

{_bullet(persona, '硬规则', '说话底线', cites)}
{role_lines}
- 不确定的细节不要编：需要共同经历时，先用 skill_search 检索 references/memory.md 再回答。
- 保持 {display} 的语言习惯，不要变得过度礼貌或书面化。
- 冷热按「温度与分寸」那一档来：不要比记录里的 TA 更热情、更黏，也不要更冷淡。
- 先判断用户这句话的情境，再选接法；旧对话只示范措辞和动作，不能把旧地点、承诺和经历当作正在发生。
- 单次观察只用于相似语境；用户认真难过时，按当前意思回应，别机械套用玩笑顶嘴。
- 记忆里的日期是聊天提及日期；计划和旧承诺先确认是否仍有效，不推断已经兑现。
{about}
## 身份与背景

{_bullet(persona, '身份', f'{display} 的基本信息', cites)}
{f'- 关系定位：{relation}。措辞要按这个关系来，不要越界。' if relation else ''}

{character}## 说话风格

{_bullet(persona, '说话风格', '句式与语气特点', cites)}

## 口头禅（按语境少量使用）

{_bullet(persona, '口头禅', '聊天里的高频表达', cites)}
- 不必每次使用；话题词不当口癖，不把几个口头禅堆进同一句。

## 情境与接法

{_bullet(persona, '情境策略', '没有足够材料归纳，按下面真实示范接话', cites)}

{scenario_block}## 接话方式（照这个接话，不只是照这个造句）

{_bullet(persona, '接话方式', '对方说什么时 TA 怎么接', cites)}
- 上面是「对方说 → TA 回」的真实对照：先看对方这句属于哪一类，再按 TA 当时的接法接。

{optional}## 温度与分寸

{_bullet(persona, '温度与分寸', '亲密度与不该越过的边界', cites)}

## 典型例句（模仿这些语感）

{_bullet(persona, '典型例句', '原话样本', cites)}

## 记忆检索提示

- 用户问到「我们」「那次」「记得吗」这类内容时，先用 `skill_search` 在该技能里检索关键词，
  再用 `skill_read` 读取 `references/memory.md` 对应片段，用它的细节回答，不要凭空编。
{refs_lines}- 原话编号在 `references/quotes.md`；需要核对统计和观察范围时读 `references/profile.md`。日常回复不照读统计报告。
- `references/scenarios.json` 保存情境与真实接话；`references/memory-ledger.json` 保存记忆状态、观察日期和出处；`references/evaluation.json` 是回归用例，历史答案仅供对照。
- `references/specificity.json` 与 `references/coverage.json` 保存证据评分和情境覆盖；`references/message-index.json` 可定位原话。分数不代表性格准确率。
- `references/questions.json` 保存证据不足的待确认问题。没有确认的计划、单次观察和模糊记忆只作有限的历史参考，相关话题先询问当前情况。
"""


def render_observations_md(display: str, persona: dict, stats: Stats, target: str) -> str:
    items = persona.get('统计画像') or []
    body = '\n'.join(f'- {item}' for item in items)
    return (f"# {display} · 观察与统计\n\n"
            "> 用于核对材料和观察范围；消息间隔不要求延迟回复，词频不等于性格。\n\n"
            f"{body}\n\n{stats_markdown(stats, target)}\n")


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
> 关系类型：{relation}

{sections}"""


def render_memory_md(display: str, memory: dict, stats: Stats, target: str,
                     relation: str = "朋友", cites=None, ledger: list[dict] | None = None) -> str:
    def section(key: str) -> str:
        title = title_for(relation, key)
        items = memory.get(key) or []
        if not items:
            return f"## {title}\n\n（聊天记录里没有找到相关内容）\n\n"
        return ("## " + title + "\n\n"
                + "\n".join(f"- {x}{cites.mark(key, str(x)) if cites else ''}" for x in items)
                + "\n\n")

    ledger_block = ""
    if ledger:
        rows = []
        for item in ledger:
            timing = item.get("time_start") or "时间未确定"
            if item.get("time_end") and item["time_end"] != item.get("time_start"):
                timing += " → " + item["time_end"]
            confidence = {'repeated_observation': '多次观察', 'single_observation': '单次观察', 'uncertain': '依据不足'}.get(item.get('confidence'), '依据不足')
            validity = '；当前有效性待确认' if item.get('validity') == 'needs_confirmation' else ''
            rows.append(f"- [{status_label(item.get('status', 'mentioned'))}] {item['text']}（提及于 {timing}；{confidence}{validity}）")
        ledger_block = "## 记忆状态与时效\n\n" + "\n".join(rows) + "\n\n"

    return f"""# {display} · 关系记忆（Part A）

> 关系类型：{relation}

{"".join(section(key) for key in MEMORY_ORDER)}
{ledger_block}
> 使用记忆时：计划不能当成已经发生，旧承诺不能自动当成当前承诺；不确定内容先承认不确定。
> 日期表示原聊天的观察范围，不是事情的发生日期或到期日。没有证据时不推断有效期。

{stats_markdown(stats, target)}
"""


# ----------------------------------------------------------------------------
# 七、打包与上传
# ----------------------------------------------------------------------------
