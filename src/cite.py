"""结论的出处体系：每条结论配 1~2 条**带时间与说话人的原话**，编号后汇总成参考文献表。

为什么单独一层：人设文档里"TA 爱说「懂了」""你们吵架的模式是……"这类结论，读者无法
判断是原话还是概括。这里给每条能对上的结论挂上 `[n]`，文末给出参考文献表，形如

    - 口头禅「懂了」出现 12 次（多为答应事情时） [3][7]
    ……
    ## 参考文献
    3. 2026-03-12 15:04 黄泉清：懂了
    7. 2026-05-02 09:18 黄泉清：懂了懂了

配不上原话的（统计口径、占比、均值这类）就不挂编号——**宁缺勿编**：挂了编号的
一定能在记录里搜到原句。
"""
from __future__ import annotations

from .models import Msg
from .verify import FUZZY_THRESHOLD, QUOTE_RE, VERBATIM_FIELDS, Corpus

#: 每条结论最多挂几个出处：够看清"这句话从哪来"，又不至于把文档铺满编号
PER_ITEM = 2

#: 引用比校验更严：挂上编号就等于"这是原话"，所以只认接近逐字命中的（校验那边 0.75
#: 就够，因为它的产出是"疑似"标记；这里的产出是"出处"，不能是疑似）。
CITE_THRESHOLD = 0.9

#: 少于 3 个字的说法不当引用对象：「的」「啊」这种碎片配不出有意义的出处
MIN_CLAIM = 3

#: 出处太长就截断：有人的一条消息能糊上来 300 字乱码，整段抄进参考文献没法看
MAX_REF_CHARS = 100


def claims_of(section: str, item: str) -> list[str]:
    """条目里"声称是原话"的部分：整句原话章节取全文，其余取引号里的内容。

    没有引号的条目也拿整条去试一次——离线抽取的条目常常把原话直接写进正文，
    试不中就自然配不上编号。
    """
    if section in VERBATIM_FIELDS:
        inner = item.strip().strip("「」『』“”\"'‘’").strip()
        return [inner] if inner else []
    quotes = [q.strip() for q in QUOTE_RE.findall(item) if len(q.strip()) >= 2]
    return quotes or [item.strip()]


class Citations:
    """一次运行内共享的引用编号表。"""

    def __init__(self, msgs: list[Msg], threshold: float = CITE_THRESHOLD,
                 per_item: int = PER_ITEM, redact=None) -> None:
        self.corpus = Corpus.build(msgs)
        self.threshold = threshold
        self.per_item = per_item
        #: 传 privacy.redact 时，出处里的手机号/身份证/地址等一律换成 [标签]——
        #: 参考文献表是直接从聊天记录里抠出来的原文，和 references 下的记录同源，
        #: 那边脱了这边不脱就等于没脱。
        self.redact = redact
        self._number: dict[str, int] = {}      # 出处行 → 编号

    # ---------------------------------------------------------------- 生成

    def _ref_of(self, idx: int) -> str:
        """把命中行整理成一条参考文献：`2026-03-12 15:04 黄泉清：懂了`。"""
        text = self.corpus.raw_lines[idx].strip()
        if len(text) > MAX_REF_CHARS:
            text = text[:MAX_REF_CHARS] + "…"
        when = self.corpus.times[idx] if idx < len(self.corpus.times) else ""
        who = self.corpus.line_speakers[idx] if idx < len(self.corpus.line_speakers) else ""
        head = " ".join(x for x in (when, who) if x)
        ref = f"{head}：{text}" if head else text
        return self.redact(ref) if self.redact else ref

    def mark(self, section: str, item: str) -> str:
        """给一条结论配引用标记（如 ``" [3][7]"``，前置一个空格）；配不上返回空串。"""
        numbers: list[int] = []
        for claim in claims_of(section, item)[: self.per_item]:
            if len(claim.strip()) < MIN_CLAIM:
                continue
            score, idx = self.corpus.locate(claim, self.threshold)
            if idx < 0 or score < self.threshold:
                continue
            ref = self._ref_of(idx)
            number = self._number.setdefault(ref, len(self._number) + 1)
            if number not in numbers:
                numbers.append(number)
        return "".join(f" [{n}]" for n in numbers)

    # ---------------------------------------------------------------- 汇总

    def table(self, title: str = "参考文献") -> str:
        """文末的参考文献表。没有引用时返回空串。"""
        if not self._number:
            return ""
        rows = sorted(self._number.items(), key=lambda kv: kv[1])
        body = "\n".join(f"{n}. {ref}" for ref, n in rows)
        return (f"\n\n## {title}\n\n"
                f"> 正文里的 `[n]` 指下面这些原话（时间是消息发出时间，姓名是说话人）；"
                f"共 {len(rows)} 条。带上编号的结论都能在记录里搜到原句。\n\n"
                f"{body}\n")

    @property
    def count(self) -> int:
        return len(self._number)
