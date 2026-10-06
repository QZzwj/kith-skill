"""结论校验：给蒸馏出的人设做「外部判决」，而不是让 LLM 自查。

三类检查，全部只用标准库，不联网、不加载模型：

1. **引用核验** —— 条目里声称是原话的部分（「」包起来的内容、或整条就是例句），
   必须在聊天记录里找得到。允许改写（覆盖率够高），不允许凭空出现。
2. **日期核验** —— 条目里出现的时间点必须落在记录的时间范围内。
3. **依据核验** —— 如果 LLM 按要求附上了「结论 ← 出处」，就检查那个出处是否真实存在。
   这是最硬的一条：引用了不存在的原话，等于自证编造。

它同时是 ``offline.py`` 的自检：离线抽取的条目本来就来自原文，
如果连粗筛都过不了，说明抽取逻辑有 bug，而不是记录有问题。

刻意**不做**的事：不判断「语义上是否成立」。把「我那天没说」洗成「我说了」
这类反转需要语义模型，代价是几百 MB 依赖，与项目的零依赖定位冲突；
这里只做「引用是否为真」，那是可判定的。
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from .models import Msg

__all__ = ["Corpus", "Finding", "inspect", "apply", "format_report"]


# ----------------------------------------------------------------------------
# 规则
# ----------------------------------------------------------------------------

#: 整条就是一句原话、不需要引号包裹的章节
VERBATIM_FIELDS = frozenset({"典型例句"})

#: 这些章节里的引号是"示意"而不是"引用"，核验会误伤
#: 「温度与分寸」里会写"记录里没有出现过「想你」这类表达"——被引号包起来的正是
#: 记录里**不存在**的话，拿它去语料里找必然查无依据，标出来是假警报。
NO_QUOTE_CHECK = frozenset({"硬规则", "温度与分寸", "统计画像"})

#: 中文引号 / 直角引号里的内容通常就是"这是原话"的意思
QUOTE_RE = re.compile(r"[「『“\"]([^「」『』“”\"]{2,120})[」』”\"]")

YEAR_MONTH_RE = re.compile(r"(\d{4})\s*[-/年.]\s*(\d{1,2})")
MONTH_DAY_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")

#: LLM 按 prompt 要求给出的「结论 ← 出处」，箭头两侧允许有空白
CITE_SEP_RE = re.compile(r"\s*(?:←|<-|<—|<=|⇐)\s*")

#: 归一化时要去掉的字符（标点、空白、下划线）
_NON_WORD_RE = re.compile(r"[\s\W_]+")

#: 引用前缀：括号里的时间、时间戳、说话人 + 冒号（名字是否可信由语料裁定）
_LEAD_BRACKET_RE = re.compile(r"^\s*[\[【][^\]】]{0,32}[\]】]\s*")
_LEAD_STAMP_RE = re.compile(r"^\s*\d{1,4}[\d\-/.月日:：]{0,18}\s*")
_LEAD_NAME_RE = re.compile(r"^\s*([^\s:：]{1,20})\s*[:：]\s*(.+)$", re.S)

_WRAP_CHARS = "「」『』“”\"'‘’"

#: 判定为改写命中的覆盖率下限
FUZZY_THRESHOLD = 0.75


def _norm(text: str) -> str:
    """全角转半角、统一小写、去标点空白，只留下实义字符。"""
    return _NON_WORD_RE.sub("", unicodedata.normalize("NFKC", text or "").lower())


def _bigrams(text: str) -> set[str]:
    if len(text) < 2:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def _variants(claim: str) -> list[str]:
    """引用常写成「时间 说话人: 原话」，逐段剥掉前缀再试。

    否则"2024-03-15 小雨: 早点睡吧"里的时间与人名会被算进覆盖率，
    把一句真实的引用硬压到阈值以下。

    要从**最短的尾巴**往回剥、并且剥到底：时间里的冒号会把前缀切成好几段
    （「[09-21 01:05]」→ "[09-21" / "01" / "05]"），只剥固定几段的话，
    剩下的尾巴里始终混着时间，"打板来"这种短句永远走不到。
    """
    out = [_norm(claim)]
    parts = [p for p in re.split(r"[\s,，:：]+", claim) if p]
    for i in range(len(parts) - 1, 0, -1):
        if len(out) > 5:          # 更长的尾巴没意义，还平白多算几遍覆盖率
            break
        variant = _norm(" ".join(parts[i:]))
        if variant and variant not in out:
            out.append(variant)
    return out


def _strip_cite_prefix(claim: str, speakers: frozenset[str]) -> str:
    """剥掉引用前面的「时间 说话人:」前缀，只留原话本身。

    「依据要带上时间或说话人」是 prompt 自己提的要求，可核验比的是原话：
    不剥掉，时间和人名就会一起进覆盖率，把一句真实的引用压到阈值以下
    （报告里 23 条假警报有 21 条出在这里）。

    只剥三种东西——括号里的时间、时间戳、以及**语料里真出现过的**说话人加冒号，
    免得把「他说: 我不去」这种正文里自带的冒号也当成前缀吃掉。
    """
    out = claim.strip()
    while out:
        before = out
        out = _LEAD_BRACKET_RE.sub("", out, count=1)
        out = _LEAD_STAMP_RE.sub("", out, count=1)
        match = _LEAD_NAME_RE.match(out)
        if match and _norm(match.group(1)) in speakers and match.group(2).strip():
            out = match.group(2).strip()
        if out == before:
            break
    return out


def _coverage(needle: str, haystack: str) -> float:
    """needle 有多少比例能在 haystack 里按顺序找到。"""
    matcher = SequenceMatcher(None, needle, haystack, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / max(1, len(needle))


def _short(text: str, limit: int = 34) -> str:
    text = _clean_ws(text)
    return text if len(text) <= limit else text[:limit] + "…"


def _clean_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# ----------------------------------------------------------------------------
# 语料索引
# ----------------------------------------------------------------------------

@dataclass
class Corpus:
    """把聊天记录做成可快速查找的索引。"""

    raw_lines: list[str]          # 原始行，用于展示"最相近的原话"
    lines: list[str]              # 归一化后的行
    joined: str                   # 归一化后按行拼接，跨行不连通
    flat: str                     # 归一化后直接拼接，允许跨消息的引用
    postings: dict[str, list[int]]
    months: set[str]
    day_pairs: set[tuple[int, int]]
    speakers: frozenset[str]      # 归一化的说话人名字，用来判定引用前缀是不是"人名 + 冒号"
    times: list[str]              # 每行的时间（"2026-03-12 15:04"，无时间则空）——当引用出处用
    line_speakers: list[str]      # 每行的说话人——同上

    @classmethod
    def build(cls, msgs: list[Msg]) -> "Corpus":
        raw_lines: list[str] = []
        lines: list[str] = []
        times: list[str] = []
        line_speakers: list[str] = []
        postings: dict[str, list[int]] = {}
        for msg in msgs:
            when = msg.ts.strftime("%Y-%m-%d %H:%M") if msg.ts else ""
            for raw in (msg.text or "").split("\n"):
                raw = raw.strip()
                norm = _norm(raw)
                if len(norm) < 2:
                    continue
                idx = len(lines)
                raw_lines.append(raw)
                lines.append(norm)
                times.append(when)
                line_speakers.append(msg.speaker or "")
                for gram in _bigrams(norm):
                    postings.setdefault(gram, []).append(idx)
        months = {f"{m.ts.year}-{m.ts.month:02d}" for m in msgs if m.ts}
        day_pairs = {(m.ts.month, m.ts.day) for m in msgs if m.ts}
        speakers = frozenset(_norm(m.speaker) for m in msgs if m.speaker)
        return cls(raw_lines, lines, "\n".join(lines), "".join(lines),
                   postings, months, day_pairs, speakers, times, line_speakers)

    def locate(self, claim: str, threshold: float = FUZZY_THRESHOLD) -> tuple[float, int]:
        """给"引用出处"用：返回（覆盖率, 命中行下标）。

        和 :meth:`find` 的差别：**精确命中时也要给出那一行**——find 精确命中返回空
        nearest（校验只关心"有没有"），但当出处用就得指向具体某句、附上时间与说话人。
        """
        base = _norm(claim)
        if len(base) < 2:
            return 0.0, -1
        needles = [base]
        stripped = _norm(_strip_cite_prefix(claim, self.speakers))
        if len(stripped) >= 2 and stripped != base:
            needles.append(stripped)
        needles += [v for v in _variants(claim)[1:] if len(v) >= 2]
        best_score, best_idx = 0.0, -1
        for needle in needles:
            score, idx = self._coverage_of(needle)
            if score > best_score:
                best_score, best_idx = score, idx
            if best_score >= 0.999:
                break
        return round(best_score, 3), (best_idx if best_score >= threshold else -1)

    def span(self) -> str:
        if not self.months:
            return "未知"
        ordered = sorted(self.months)
        return f"{ordered[0]} ~ {ordered[-1]}"

    def _coverage_of(self, needle: str) -> tuple[float, int]:
        """needle 在语料里最相近的一行（下标），以及它的覆盖率。"""
        hits: Counter[int] = Counter()
        for gram in _bigrams(needle):
            for idx in self.postings.get(gram, ()):
                hits[idx] += 1
        best, best_idx = 0.0, -1
        for idx, _ in hits.most_common(24):
            score = _coverage(needle, self.lines[idx])
            if score > best:
                best, best_idx = score, idx
            if best >= 0.999:
                break
        return best, best_idx

    def find(self, claim: str, threshold: float = FUZZY_THRESHOLD) -> tuple[str, float, str]:
        """返回 (状态, 覆盖率, 最相近的原话)。状态：verified / fuzzy / unverified / skip。"""
        base = _norm(claim)
        if len(base) < 2:
            return "skip", 1.0, ""
        if base in self.joined or base in self.flat:
            return "verified", 1.0, ""

        # 先剥掉「时间 说话人:」前缀按整句比；剥不动再退化成一截一截的尾巴。
        # 尾巴不设 4 字门槛：口癖（「md」「几把」）和短句（「美滋滋」）本来就 2~3 字，
        # 门槛设 4 等于把它们一律判成「查无依据」。
        needles = [base]
        stripped = _norm(_strip_cite_prefix(claim, self.speakers))
        if len(stripped) >= 2 and stripped != base:
            needles.append(stripped)
        needles += [v for v in _variants(claim)[1:] if len(v) >= 2]
        for needle in needles:
            if needle in self.joined or needle in self.flat:
                return "verified", 1.0, ""

        best_score, best_idx = 0.0, -1
        for needle in needles:
            score, idx = self._coverage_of(needle)
            if score > best_score:
                best_score, best_idx = score, idx
        best_raw = self.raw_lines[best_idx] if best_idx >= 0 else ""
        status = "fuzzy" if best_score >= threshold else "unverified"
        return status, round(best_score, 3), best_raw


# ----------------------------------------------------------------------------
# 校验结果
# ----------------------------------------------------------------------------

@dataclass
class Finding:
    section: str          # 章节名
    item: str             # 条目原文（用于回写标注）
    claim: str            # 被核验的那部分
    status: str           # verified | fuzzy | unverified | date_mismatch | skip
    score: float = 1.0
    nearest: str = ""     # 最相近的原话，供人工核查
    note: str = ""


def _claims_of(section: str, text: str) -> list[str]:
    """挑出条目里"声称是原话"的部分。"""
    if section in VERBATIM_FIELDS:
        inner = text.strip().strip(_WRAP_CHARS).strip()
        return [inner] if len(_norm(inner)) >= 2 else []
    if section in NO_QUOTE_CHECK:
        return []
    return [q.strip() for q in QUOTE_RE.findall(text) if len(_norm(q)) >= 2]


def _check_quotes(section: str, text: str, corpus: Corpus, threshold: float) -> list[Finding]:
    out: list[Finding] = []
    for claim in _claims_of(section, text):
        status, score, nearest = corpus.find(claim, threshold)
        if status == "skip":
            continue
        out.append(Finding(section, text, claim, status, score, nearest))
    return out


def _check_dates(section: str, text: str, corpus: Corpus) -> list[Finding]:
    if len(corpus.months) < 2:
        return []  # 样本太短，时间范围不足以判真假
    out: list[Finding] = []
    for year, month in YEAR_MONTH_RE.findall(text):
        key = f"{year}-{int(month):02d}"
        if key not in corpus.months:
            out.append(Finding(section, text, key, "date_mismatch", 0.0,
                               note=f"记录里没有 {key}（范围 {corpus.span()}）"))
    for month, day in MONTH_DAY_RE.findall(text):
        pair = (int(month), int(day))
        if pair not in corpus.day_pairs:
            out.append(Finding(section, text, f"{pair[0]}月{pair[1]}日", "date_mismatch", 0.0,
                               note="记录里没有这一天的消息"))
    return out


def _check_evidence(section: str, text: str, corpus: Corpus, threshold: float) -> list[Finding]:
    """核验 LLM 自己给出的「结论 ← 出处」。引用不存在 = 自证编造。"""
    parts = CITE_SEP_RE.split(text, maxsplit=1)
    if len(parts) < 2:
        return [Finding(section, text, text, "unverified", 0.0,
                        note="没有用 ← 标明出处")]
    cited = parts[1].strip()
    status, score, nearest = corpus.find(cited, threshold)
    if status in ("verified", "fuzzy", "skip"):
        return []
    return [Finding(section, text, cited, "unverified", score, nearest,
                    note="引用的原话在记录里找不到")]


def inspect(persona: dict, memory: dict, msgs: list[Msg],
            threshold: float = FUZZY_THRESHOLD) -> list[Finding]:
    """只做检查、不改内容。返回所有值得注意的结论。"""
    corpus = Corpus.build(msgs)
    findings: list[Finding] = []
    for section, items in list(persona.items()) + list(memory.items()):
        if not isinstance(items, list):
            continue
        for item in items:
            text = _clean_ws(str(item))
            if not text:
                continue
            if section == "依据":
                findings.extend(_check_evidence(section, text, corpus, threshold))
                findings.extend(_check_dates(section, text, corpus))
                continue
            findings.extend(_check_quotes(section, text, corpus, threshold))
            findings.extend(_check_dates(section, text, corpus))
    return findings


# ----------------------------------------------------------------------------
# 按结论改写 / 剔除
# ----------------------------------------------------------------------------

_MARK = {
    "unverified": "（未在记录中找到依据）",
    "date_mismatch": "（记录中查无此时间）",
}


def apply(persona: dict, memory: dict, findings: list[Finding],
          strict: bool = False) -> tuple[dict, dict]:
    """把有问题的条目标注出来；``strict=True`` 时直接剔除。"""
    marks: dict[tuple[str, str], str] = {}
    for finding in findings:
        note = _MARK.get(finding.status)
        if note:
            key = (finding.section, finding.item)
            marks[key] = marks.get(key, "") + note
    if not marks:
        return persona, memory

    def rebuild(section: str, items):
        if not isinstance(items, list):
            return items
        out = []
        for item in items:
            note = marks.get((section, _clean_ws(str(item))))
            if not note:
                out.append(item)
            elif not strict:
                out.append(f"{item} {note}")
        return out

    return ({s: rebuild(s, v) for s, v in persona.items()},
            {s: rebuild(s, v) for s, v in memory.items()})


def format_report(findings: list[Finding], limit: int = 12) -> str:
    """给 CLI 用的可读报告。"""
    if not findings:
        return "      没有可核验的结论（记录太短，或产出里没有引用类内容）"

    counts = Counter(f.status for f in findings)
    lines = [
        f"      {len(findings)} 条可核验结论：原文命中 {counts['verified']}、"
        f"改写命中 {counts['fuzzy']}、未找到依据 {counts['unverified']}、"
        f"时间不符 {counts['date_mismatch']}"
    ]

    problems = [f for f in findings if f.status in ("unverified", "date_mismatch")]
    if not problems:
        return lines[0]
    lines.append("      需要人工确认的条目：")
    for finding in problems[:limit]:
        tail = f" ← 最相近的原话：「{_short(finding.nearest)}」" if finding.nearest else ""
        note = f"（{finding.note}）" if finding.note else ""
        lines.append(f"        · [{finding.section}] 「{_short(finding.claim)}」{note}{tail}")
    if len(problems) > limit:
        lines.append(f"        …… 另有 {len(problems) - limit} 条")
    return "\n".join(lines)
