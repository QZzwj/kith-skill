"""skill 的"参考资料"层：把记录本体按预算装进 ``references/``。

人设文档（SKILL.md / references/memory.md）是**提炼过的结论**，一共只有十几 KB；
设备侧要"记得住事、接得住具体问法"，靠的是能检索到的原始材料。这里生成三样：

- ``references/transcript/YYYY-MM.md``：逐月逐条的完整记录（体积大头，天然到 MB 量级）
- ``references/evidence.md``：每条结论对应的原话与上下文（结论可不可信看这里）
- ``references/README.md``：带路文件（有哪些文件、多大、怎么检索、收了多少个月）

体积受 ``budget_mb``（默认 8MB，对应"skill 常见 2~10MB"）约束：两个附录先装，
transcript 从**最新月份往回**装，超预算的旧月份不收——并在带路文件里如实写明，
免得用户以为"记录丢了"。
"""
from __future__ import annotations

import re
from collections import Counter, OrderedDict
from pathlib import Path

from . import offline
from .models import Msg
from .verify import QUOTE_RE, VERBATIM_FIELDS, Corpus

#: 派生材料（逐月原记录 + 结论依据）的默认预算：8MB。
DEFAULT_BUDGET_MB = 8.0
#: 原始导出文件的上限：再大就不附（一个 500MB 的导出会把 skill 包撑爆）
SOURCE_CAP_MB = 50.0

TRANSCRIPT_DIR = "references/transcript"
EVIDENCE_FILE = "references/evidence.md"
TOPICS_FILE = "references/topics.md"
README_FILE = "references/README.md"
SOURCE_DIR = "references/source"

_WS_RE = re.compile(r"\s+")

#: 参考资料的文件内容：派生材料是文本，原始导出按字节原样装（可能是 .db/.mbox 这类非文本）
Payload = str | bytes


# ----------------------------------------------------------------------------
# 摊平与分月
# ----------------------------------------------------------------------------

def _ts_text(msg: Msg) -> str:
    return msg.ts.strftime("%Y-%m-%d %H:%M") if msg.ts else "（无时间）"


def _line(msg: Msg) -> str:
    return f"{_ts_text(msg)} {msg.speaker}：{_WS_RE.sub(' ', msg.text or '').strip()}"


def _month_key(msg: Msg) -> str:
    return msg.ts.strftime("%Y-%m") if msg.ts else "未标时间"


def by_month(msgs: list[Msg]) -> "OrderedDict[str, list[Msg]]":
    """按月分桶，键按时间正序。"""
    buckets: dict[str, list[Msg]] = {}
    for msg in msgs:
        buckets.setdefault(_month_key(msg), []).append(msg)
    return OrderedDict(sorted(buckets.items()))


def _b(text: str | bytes) -> int:
    return len(text) if isinstance(text, bytes) else len(text.encode("utf-8"))


def _size(text: str | bytes) -> str:
    size = _b(text)
    return f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / 1024 / 1024:.1f} MB"


# ----------------------------------------------------------------------------
# 一、transcript：逐月逐条
# ----------------------------------------------------------------------------

def build_transcript(buckets: "OrderedDict[str, list[Msg]]",
                     budget_bytes: int) -> tuple[dict[str, str], list[str], list[str]]:
    """从最新月份往回装到预算用完。返回（文件、收下的月份、丢掉的月份）。"""
    kept: dict[str, str] = {}
    used = 0
    dropped: list[str] = []
    for month in sorted(buckets, reverse=True):
        rows = buckets[month]
        body = f"# {month}（{len(rows)} 条）\n\n" + "\n".join(_line(m) for m in rows) + "\n"
        if kept and used + _b(body) > budget_bytes:
            dropped.append(month)
            continue
        kept[month] = body
        used += _b(body)
    # 正序返回，按时间读
    return ({f"{TRANSCRIPT_DIR}/{m}.md": kept[m] for m in sorted(kept)},
            sorted(kept), sorted(dropped))


# ----------------------------------------------------------------------------
# 二、evidence：每条结论的原文依据
# ----------------------------------------------------------------------------

def _claims(section: str, item: str) -> list[str]:
    """条目里"声称是原话"的部分：整句原话章节取全文，其余取引号里的内容。"""
    if section in VERBATIM_FIELDS:
        inner = item.strip().strip("「」『』“”\"'‘’").strip()
        return [inner] if inner else []
    quotes = [q.strip() for q in QUOTE_RE.findall(item) if len(q.strip()) >= 2]
    return quotes or [item.strip()]


def _context(corpus: Corpus, nearest: str, span: int = 1) -> list[str]:
    """最相近那句的前后各一行——只看一句容易断章取义。"""
    if not nearest:
        return []
    lines = corpus.raw_lines
    try:
        idx = lines.index(nearest)
    except ValueError:
        return [nearest]
    return lines[max(0, idx - span):idx + span + 1]


#: 主题档案：从记录里挖出的高频词，每个词一章，配上带出处的原话。
#: 它不是"原始流水"（逐条按时间堆），而是**按主题重组**过的摘编——每条都有时间与说话人。
TOPIC_LIMIT = 32            # 最多几个主题
TOPIC_EXCERPTS = 400        # 每个主题最多收几条原话（够多才有分量，又不至于把包撑爆）
TOPIC_MIN_COUNT = 10        # 出现次数低于这个不当主题
TOPIC_MIN_LEN = 2
TOPIC_MAX_LEN = 6

#: 主题词的噪声过滤：这些词高频但没有主题价值
_TOPIC_STOP = {
    "什么", "怎么", "这个", "那个", "可以", "没有", "不是", "就是", "然后", "因为",
    "所以", "但是", "如果", "已经", "还是", "真的", "现在", "我们", "你们", "他们",
    "自己", "知道", "感觉", "应该", "可能", "一下", "一个", "时候", "问题", "东西",
    "今天", "明天", "昨天", "哈哈", "嗯嗯", "哦哦", "好的", "在的", "然后", "是的",
    # 媒体占位：它们在记录里出现几百上千次，但那是"发了张图"，不是话题
    "表情", "图片", "语音", "视频", "引用", "链接", "文件", "位置", "系统", "动画",
    "合并", "转账", "红包", "回复", "附件", "文件传输助手",
}


def _cjk_only(token: str) -> bool:
    return all("\u4e00" <= ch <= "\u9fff" for ch in token)


def _degenerate(token: str) -> bool:
    """「鹿鹿」「哈哈哈哈哈」这类——同字叠出来的串不是主题。"""
    return len(set(token)) <= 1 or (len(set(token)) == 2 and len(token) >= 5)


def mine_topics(msgs: list[Msg], limit: int = TOPIC_LIMIT,
                min_count: int = TOPIC_MIN_COUNT) -> list[tuple[str, int]]:
    """挖高频主题词：2~6 字汉字 n-gram，去掉停用词、叠字串与互相包含的碎片。

    去碎片这一步是必须的：n-gram 会把「实验室」拆成「验室」「实验」，把
    「飞车我耍」拆成「车我」「飞车我」「车我耍」。规则是**保留最长的那个**——
    新的候选如果包含已选词，就把已选词换掉；如果被已选词包含，就丢弃。
    """
    counter: Counter[str] = Counter()
    for msg in msgs:
        text = _WS_RE.sub("", msg.text or "")
        for size in range(TOPIC_MIN_LEN, TOPIC_MAX_LEN + 1):
            for i in range(len(text) - size + 1):
                token = text[i:i + size]
                if _cjk_only(token) and not _degenerate(token) and token not in _TOPIC_STOP:
                    counter[token] += 1

    picked: list[tuple[str, int]] = []
    for token, count in counter.most_common(800):
        if count < min_count or len(picked) >= limit:
            break
        if _degenerate(token) or not offline.topic_word(token):
            continue                      # 虚词碎片（「你的」「了一」）与跨词串直接丢
        if any(token in longer for longer, _ in picked):
            continue                      # 已被更长的主题词覆盖
        picked = [(w, c) for w, c in picked if w not in token]   # 反过来覆盖掉更短的
        picked.append((token, count))
    return sorted(picked, key=lambda kv: kv[1], reverse=True)[:limit]


def build_topics(msgs: list[Msg], limit: int = TOPIC_LIMIT,
                 per_topic: int = TOPIC_EXCERPTS) -> str:
    """按主题重组的原话档案（每条带时间与说话人）。"""
    topics = mine_topics(msgs, limit=limit)
    if not topics:
        return ""
    out = ["# 主题档案", "",
           "> 不是按时间堆的原始流水，而是**按主题重组**过的摘编：每个词下面挑若干条"
           "原话（带时间与说话人），用来回答「我们聊过什么、当时是怎么说的」。", ""]
    for token, count in topics:
        picked = _topic_excerpts(msgs, token, per_topic)
        if not picked:
            continue
        first, last = picked[0][0].ts, picked[-1][0].ts
        span = (f"{first:%Y-%m} ~ {last:%Y-%m}" if len(picked) > 1 else f"{first:%Y-%m}")
        who = Counter(m.speaker for m, _ in picked)
        share = "、".join(f"{name} {n} 条" for name, n in who.most_common(3))
        out += [f"## 「{token}」（提到 {count} 次，{span}）", "",
                f"> 抽样 {len(picked)} 条；发言人：{share}", ""]
        out += [f"- {line}" for _, line in picked]
        out.append("")
    return "\n".join(out) + "\n"


def _topic_excerpts(msgs: list[Msg], token: str, want: int) -> list[tuple[Msg, str]]:
    """沿时间均匀抽样：每个主题都给出跨年月的原话，而不是全挤在同一天。"""
    hits = [m for m in msgs if m.ts and token in (m.text or "")]
    if not hits:
        return []
    step = max(1, len(hits) // want)
    return [(m, _line(m)) for m in hits[::step][:want]]


def build_evidence(persona: dict, memory: dict, msgs: list[Msg]) -> str:
    """把每条结论和它命中的原话摆在一起；没有原话可对的说清楚是统计口径。"""
    corpus = Corpus.build(msgs)
    out = ["# 结论与原文依据", "",
           "> 这是「结论 ← 原话」的对照表，用来核对上面几份文档里的说法："
           "带覆盖率的是按顺序匹配上的引用，覆盖率低就多半是概括而不是原话。", ""]
    sections = [(k, v) for k, v in list(persona.items()) + list(memory.items())
                if isinstance(v, list) and v]
    for section, items in sections:
        out += [f"## {section}", ""]
        for item in items:
            out.append(f"- **{item.strip()}**")
            for claim in _claims(section, item):
                status, score, nearest = corpus.find(claim)
                if status == "skip" or not nearest:
                    out.append("  - （没有直接原话可对：属于统计口径或概括）")
                    continue
                mark = {"verified": "原话命中", "fuzzy": "近似命中"}.get(status, "未找到依据")
                out.append(f"  - {mark} {score:.2f}：「{nearest.strip()}」")
                for line in _context(corpus, nearest):
                    if line != nearest:
                        out.append(f"    - 上下文：{line.strip()}")
        out.append("")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------
# 三、带路文件
# ----------------------------------------------------------------------------

def build_readme(target: str, files: dict[str, Payload], months: list[str],
                 dropped: list[str], budget_mb: float, notes: list[str] | None = None,
                 source_name: str = "", redacted: bool = False,
                 source_redacted: bool = False) -> str:
    listing = "\n".join(f"- `{rel}`（{_size(text)}）" for rel, text in sorted(files.items()))
    span = f"{months[0]} ~ {months[-1]}" if months else "（无）"
    budget_note = (f"> 派生材料的预算 {budget_mb:g}MB 已用满，这些更早的月份没装进来："
                   f"{'、'.join(dropped)}。想全都要就调大 `--corpus-mb` 重跑。\n"
                   if dropped else "")
    privacy_note = (
        "> 本目录的聊天记录**已脱敏**：手机号 / 身份证 / 银行卡 / 邮箱 / 详细地址一律"
        "替换成 `[手机号]` 这类标签（`--no-redact` 可关）。引用原话时照抄标签即可，"
        "不要凭上下文把数字补回去。\n" if redacted else
        "> 本目录的聊天记录**未脱敏**（跑的时候带了 `--no-redact`）：里面有原始手机号、"
        "身份证、地址等信息，别把这份包外发。\n")
    extra_note = "".join(f"> {line}\n" for line in (notes or []))
    source_hint = (
        f"- `source/{source_name}` 是**原始导出文件的脱敏副本**：字段一个不少（消息类型、"
        f"本地 id、时间戳、媒体占位都在），只有手机号 / 身份证 / 地址这类换成了 `[标签]`。"
        f"想换口径重新蒸馏、或查上面摘编里没有的字段，直接用它。\n"
        if source_name and source_redacted else
        f"- `source/{source_name}` 是**原始导出文件原样附上**的：想换口径重新蒸馏、"
        f"或者查上面摘编里没有的字段（图片/文件类型、内部 id 等），直接用它。"
        f"注意它**没法脱敏**（原样字节），别外发。\n"
        if source_name else "")
    return f"""# 参考资料（{target}）

> 人设文档是提炼后的结论；这里放的是**原始材料**——具体到"哪天说的、原话是什么"，
> 靠检索这些文件回答。问到共同经历时先检索，再引用命中的原话，不要凭印象编。

{budget_note}{privacy_note}{extra_note}
## 文件

{listing}

## 收了多少记录

- 记录本体：{span}，共 {len(months)} 个月（每月一个文件）

## 怎么用

- 关键词直接搜（时间、地点、人名、口头禅、事件词都能搜），命中后引用原话作答。
- `transcript/` 逐行形如 `2026-09-27 15:46 黄泉清：内容`，媒体/表情是 `[图片]`「[表情]」这类占位。
- `topics.md` 是按主题重组过的摘编（每个主题若干条带时间出处的原话），回答
  「我们聊过什么、当时是怎么说的」先看它。
- 只跟结论有关的核对，看 `evidence.md`：每条结论后面跟着它命中的原话与上下文。
{source_hint}"""


# ----------------------------------------------------------------------------
# 组装
# ----------------------------------------------------------------------------

def build(msgs: list[Msg], *, target: str = "", persona: dict | None = None,
          memory: dict | None = None, budget_mb: float = DEFAULT_BUDGET_MB,
          source: Path | None = None, allow_source: bool = True,
          source_cap_mb: float = SOURCE_CAP_MB,
          redact=None) -> dict[str, Payload]:
    """生成参考资料（相对路径 → 内容）。``budget_mb <= 0`` 返回空。

    ``redact`` 传 ``privacy.redact`` 时，本层里的聊天记录一律脱敏（手机号、身份证、
    银行卡、邮箱、详细地址 → ``[手机号]`` 这类标签）。默认就该传——references 下放的
    是**聊天记录**，即使是"本人版"也难免被转发、被设备上的其他 agent 读到。

    ``source`` 是这次解析用的原始文件：**默认就附**——它是"以后能换口径重新蒸馏、能查
    摘编里没有的字段"的兜底，也是包体积能到 1~2MB 量级的原因。脱敏开着时附的是
    **脱敏副本**（字段一个不少，敏感数字换成标签）；读不成文本的二进制只能原样附。
    ``allow_source=False``（公开版）时不附。
    """
    if budget_mb <= 0 or not msgs:
        return {}
    budget = int(max(0.5, budget_mb) * 1024 * 1024)

    files: dict[str, Payload] = {}
    if persona or memory:
        files[EVIDENCE_FILE] = build_evidence(persona or {}, memory or {}, msgs)
    topics = build_topics(msgs)
    if topics:
        files[TOPICS_FILE] = topics

    notes: list[str] = []
    source_name = ""
    source_redacted = False
    if source is not None and allow_source:
        try:
            size = source.stat().st_size
        except OSError:
            size = 0
        if size and size <= source_cap_mb * 1024 * 1024:
            payload = read_source(source, redact)
            files[f"{SOURCE_DIR}/{source.name}"] = payload
            source_name = source.name
            source_redacted = redact is not None and isinstance(payload, str)
        elif size:
            notes.append(f"原始导出 {source.name}（{size / 1024 / 1024:.1f}MB）超过 "
                         f"{source_cap_mb:g}MB，没有附进来；需要就说一声放进 "
                         f"{SOURCE_DIR}/。")

    buckets = by_month(msgs)
    # 原始导出**不占**派生材料的预算：它的额度由 source_cap_mb 单独管。混在一起算的后果是
    # 一个 9MB 的导出直接把 8MB 预算吃光，逐月记录被挤成 0 个月（这个坑真踩过一次：
    # 带上 --source 后 transcript 只剩最新一个月，包反而更小）。
    used = sum(_b(v) for rel, v in files.items()
               if not rel.startswith(f"{SOURCE_DIR}/"))
    left = budget - used
    transcript, months, dropped = build_transcript(buckets, max(0, left))
    files.update(transcript)

    # 脱敏放在最后、对**所有文本**统一做一遍：逐月记录、结论依据、主题档案都是从
    # 聊天记录里抠出来的，正文里换了标签、附录里还是原号就等于没脱。
    # 原始导出（bytes）没法脱敏——它本来就是原样字节，带路文件里会写明。
    if redact is not None:
        files = {rel: (redact(text) if isinstance(text, str) else text)
                 for rel, text in files.items()}

    # 带路文件最后生成：里面的体积清单与实际文件一致，也带上脱敏状态
    files[README_FILE] = build_readme(target, files, months, dropped, budget_mb,
                                      notes=notes, source_name=source_name,
                                      redacted=redact is not None,
                                      source_redacted=source_redacted)
    return {rel: text for rel, text in files.items() if text}


def read_source(path: Path, redact=None) -> Payload:
    """读原始导出文件准备附进包。

    ``redact`` 开着时按 UTF-8 当文本读回来（随后统一过一遍脱敏，这样"字段全保留、
    敏感数字换标签"两件事同时成立）；读不成文本（.db/.mbox 这类二进制）只能原样附字节，
    带路文件里会写明它没脱敏。不脱敏时保持字节级一致。
    """
    if redact is None:
        return path.read_bytes()
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return path.read_bytes()


def total_bytes(files: dict[str, Payload]) -> int:
    return sum(_b(v) for v in files.values())
