"""离线抽取式蒸馏：不调用任何 LLM，把聊天记录直接变成可用的人设与关系记忆。

和 ``llm.consult_llm()`` 的根本区别是**这里不生成任何新句子**：
- 说话风格、情感模式、关系行为来自文体计量学（stylometry）统计；
- 口头禅、典型例句、称呼、地点、梗来自原文抽取；
- 每条结论后面都附统计依据，便于人工核对真假。

因此它输出的东西比 LLM 更保守，但每一条都能在记录里找到出处。
jieba 是可选增强（装了分词更准），不装也能完整跑通。
"""

from __future__ import annotations

import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from .models import CONFLICT_WORDS, SESSION_GAP, STOP_PHRASES, Msg, Stats

try:  # 可选增强：装了就用，没装不影响任何功能
    import logging

    import jieba  # pyright: ignore[reportMissingImports]
    import jieba.posseg as pseg  # pyright: ignore[reportMissingImports]

    jieba.setLogLevel(logging.ERROR)  # 否则首次运行会往 stderr 打建词典的日志
except Exception:  # pragma: no cover - 取决于环境
    jieba = None
    pseg = None

_HAS_JIEBA = jieba is not None and pseg is not None

__all__ = ["distill", "engine"]


def engine() -> str:
    """当前使用的分词引擎，用于在 CLI 里如实告知用户。"""
    return "jieba" if _HAS_JIEBA else "内置 n-gram"


# ----------------------------------------------------------------------------
# 词表
# ----------------------------------------------------------------------------

#: 句末标点。没以这些结尾的消息，等于"不打标点直接断句"。
SENT_END = "。！？!?…~～"

TONE_PARTICLES = ("啊", "吧", "呢", "哦", "喔", "呀", "嘛", "咯", "哇", "嘿",
                  "唉", "诶", "咦", "嗯", "哈", "啦", "嘞", "哟", "嗷", "呜")

LAUGH = ("笑死我了", "笑死", "哈哈", "嘿嘿", "嘻嘻", "呵呵", "hhh", "2333", "233", "emmm")

#: 正向情感表达（长词在前，正则交替按顺序匹配）
POS_WORDS = (
    "超级喜欢", "好喜欢你", "开心", "高兴", "幸福", "喜欢", "爱你", "想你", "想你啦",
    "想你了", "好棒", "厉害", "可爱", "心疼", "谢谢", "辛苦", "放心", "抱抱", "亲亲",
    "么么", "宝贝", "乖乖", "乖", "甜的", "好甜", "真好", "太棒", "太好了", "嘿嘿",
    "棒", "赞", "乖啦",
    # 非恋爱关系里也常见的正向表达，否则同事/朋友类记录会一律算成"正向 0 次"
    "不错", "挺好", "没问题", "好事", "稳了", "可以啊", "辛苦了", "感谢", "靠谱",
)

NEG_WORDS = (
    "气死", "烦死", "无语", "难受", "委屈", "伤心", "难过", "生气", "讨厌", "崩溃",
    "不想理", "别理我", "算了", "随便", "别说了", "冷战", "分手", "吵架", "对不起",
    "道歉", "后悔", "孤独", "想哭", "烦", "累", "唉", "烦人", "受不了", "没意思",
)

#: 低气压信号词：比 NEG_WORDS 更收敛，避免把"没事 就是想你了"这种甜话当成低落
LOW_WORDS = ("唉", "不开心", "难过", "委屈", "没意思", "想哭", "孤独", "难受",
             "烦", "算了", "不想", "累了")

#: 关心类句式：体现"怎么表达在意"
CARE_WORDS = (
    "早点睡", "早点休息", "注意身体", "注意安全", "多喝热水", "记得吃饭",
    "吃饭了吗", "吃了吗", "别熬夜", "别累着", "照顾好自己", "路上小心", "带伞",
    "多穿", "别感冒", "小心点", "别忘了", "到家了", "到家", "睡了吗",
)

#: 称呼候选：用于从记录里找出双方怎么互相叫
PET_NAMES = (
    "宝贝", "宝宝", "老婆", "老公", "亲爱的", "亲爱的", "笨蛋", "傻子", "蠢货",
    "憨憨", "狗子", "猪猪", "小可爱", "崽崽", "小猪", "大宝", "乖乖", "臭宝",
)

CALL_PATTERNS = (
    re.compile(r"(?:叫|喊|称呼)(?:你|我|他|她|TA|ta)?\s*[「『\"'“‘]?(?P<name>[\u4e00-\u9fa5A-Za-z0-9]{1,6})[」』\"'”’]?"),
    re.compile(r"@(?P<name>[\u4e00-\u9fa5A-Za-z0-9_\-]{1,12})"),
)

#: 地点后缀：抓"一起去过的地方"。前缀限制在 4 字内并配合 _trim_place，
#: 否则"等下去滨江天街"会被整段当成地名；也刻意不收"奶茶/咖啡"这类消费品。
PLACE_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z0-9]{1,4}"
    r"(?:省|市|区|县|镇|村|街道|路|街|巷|站|机场|火车站|地铁|公园|广场|学校|大学|"
    r"医院|餐厅|饭店|酒店|超市|商场|电影院|图书馆|楼下|门口)"
)

#: 地名开头的动词/连词（"去滨江天街"→"滨江天街"）
PLACE_LEAD_TRIM = set("等下去了到在逛还就也又都再这那我你他她的是很太")

#: n-gram 挖掘时要丢掉的纯符号/数字串
_NOISE_RE = re.compile(r"^[\W\d_]+$")
#: 方括号媒体/表情占位
BRACKET_TAG_RE = re.compile(r"\[[^\[\]]{0,24}\]")
BRACKET_ONLY_RE = re.compile(r"^(?:\s*\[[^\[\]]{0,24}\]\s*)+$")
#: 叠词，例如"哈哈哈""嗯嗯""好好好"
_DUP_RE = re.compile(r"([\u4e00-\u9fa5])\1")
#: 表情记号，例如 [偷笑]
EMOJI_RE = re.compile(r"\[[^\[\]]{1,8}\]")
#: 非文本消息占位符（很多导出格式会把图片/语音写成这种记号）
MEDIA_RE = re.compile(
    r"\[(?:图片|照片|表情|语音|视频|文件|链接|动画表情|位置|转账|红包|撤回|系统提示|"
    r"回复消息|合并转发|引用|图片消息|语音消息)\]"
)

#: n-gram 里要丢掉的通用词（避免把"我们""这个"当口头禅）
GENERIC_NGRAMS = {
    "我们", "你们", "他们", "这个", "那个", "什么", "怎么", "可以", "没有", "不是",
    "现在", "已经", "还是", "真的", "就是", "然后", "因为", "所以", "但是", "如果",
    "一样", "一点", "有点", "时候", "知道", "觉得", "可能", "应该", "今天", "明天",
    "昨天", "晚上", "早上", "下午", "一下", "一个", "这里", "那里", "自己", "别人",
    "事情", "问题", "东西", "地方", "时间", "感觉", "有点", "不太", "好像", "反正",
    # 代词 + 时间/动词的固定组合：出现频率高但不是口癖
    "我今天", "我昨天", "我明天", "我前天", "你说", "我说", "他说", "她说", "你想",
    "我想", "你在", "我在", "我知道", "我不知道", "你不知道", "我觉得", "我是不是",
    "你是不是", "你能", "我能", "你会", "我会", "你要", "我要", "你在干嘛", "在干嘛",
}

#: 抽地点时要丢掉的动词短语（"去吃饭""在上班"不是地点）
PLACE_BLOCKLIST = {
    "吃饭", "睡觉", "上班", "下班", "上课", "玩", "看剧", "逛街", "洗澡",
    "干嘛", "哪里", "这里", "那里", "厕所", "一下", "哪儿",
}


def _fragments(words: set[str], lo: int = 2, hi: int = 5) -> set[str]:
    """一个词的所有 2~5 字子串，用来判断某个 n-gram 是不是通用词的碎片。"""
    out: set[str] = set()
    for word in words:
        for n in range(lo, hi + 1):
            for i in range(len(word) - n + 1):
                out.add(word[i:i + n])
    return out


#: 一次查表代替逐条子串扫描，否则 n-gram 挖掘会退化成 O(词表 × 语料)。
#: 中文笑声词（笑死/嘿嘿）故意保留，它们是有效的口癖；只排除 em/emm/mm/23 这类碎片。
NOISE_FRAGMENTS = _fragments(set(GENERIC_NGRAMS) | set(STOP_PHRASES)) | {
    f for f in _fragments(set(LAUGH)) if f.isascii()
}


# ----------------------------------------------------------------------------
# 基础工具
# ----------------------------------------------------------------------------

def _pct(part: float, whole: float) -> float:
    return part / whole * 100 if whole else 0.0


def _median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def _percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[idx]


def _fmt_minutes(minutes: float) -> str:
    if minutes <= 0:
        return "0 分钟"
    if minutes < 1:
        return "不到 1 分钟"
    if minutes < 60:
        return f"{minutes:.0f} 分钟"
    if minutes < 60 * 24:
        return f"{minutes / 60:.1f} 小时"
    return f"{minutes / 1440:.1f} 天"


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _tone_counter(texts: list[str]) -> Counter[str]:
    """语气词频次。先删掉叠字串，否则「嘿嘿」「哈哈」会被算成语气词「嘿」「哈」。"""
    tone: Counter[str] = Counter()
    for text in texts:
        stripped = _DUP_RE.sub("", text)
        for particle in TONE_PARTICLES:
            count = stripped.count(particle)
            if count:
                tone[particle] += count
    return tone


def _laugh_counter(texts: list[str]) -> Counter[str]:
    """笑声词频次。叠字串若本身就是笑声（嘿嘿），不再重复计入叠词。"""
    laughs: Counter[str] = Counter(_LAUGH_RE.findall("\n".join(texts)))
    for text in texts:
        for match in _DUP_RE.finditer(text):
            run = match.group(0)
            if not any(run in word for word in LAUGH):
                laughs[run] += 1
    return laughs


#: 算作"说话习惯"的词性：副词、连词、叹词、拟声词、习用语、动词、形容词、语气词。
#: 名词/代词/数词/量词/时间词被排除——那些是话题词（电源、实验室、那我），不是口癖。
_KEEP_TAGS = frozenset({"a", "ad", "an", "c", "d", "df", "dg", "e", "i", "l",
                        "o", "v", "vd", "y", "z"})
_tag_cache: dict[str, bool] = {}


def _looks_like_topic(token: str) -> bool:
    """用词性判断候选是"话题词"还是"说话习惯"。没有 jieba 时一律放行。"""
    if pseg is None:
        return False
    cached = _tag_cache.get(token)
    if cached is not None:
        return cached
    keep = any(flag in _KEEP_TAGS or flag[:2] in _KEEP_TAGS
               for _, flag in pseg.cut(token))
    _tag_cache[token] = not keep
    return not keep


def _best_example(candidates: list[str]) -> str:
    """在候选里挑信息量最高的一条：够长、带情绪词、不是纯笑声。"""
    def score(text: str) -> float:
        return (min(len(text), 40) * 0.1
                + 2.0 * len(_POS_RE.findall(text))
                + 2.0 * len(_NEG_RE.findall(text))
                + (3.0 if not _LAUGH_RE.fullmatch(text.strip()) else 0.0))

    return max(candidates, key=score) if candidates else ""


def _is_noise(token: str) -> bool:
    if not token or token.strip() != token:
        return True
    if _NOISE_RE.match(token):
        return True
    if "[" in token or "]" in token:
        return True  # 方括号标记是媒体/回复占位，不是口癖
    return token in NOISE_FRAGMENTS


def _trim_place(raw: str) -> str:
    """两头都截断：去掉开头的动词/连词，遇到语气词/动词就收尾。"""
    start = 0
    while start < len(raw) and raw[start] in PLACE_LEAD_TRIM:
        start += 1
    out: list[str] = []
    for ch in raw[start:]:
        if ch in PLACE_TRIM_CHARS:
            break
        out.append(ch)
    return "".join(out)


def _lines(msgs: list[Msg], target: str | None = None) -> list[str]:
    """按行摊平，去掉媒体占位，避免跨行的消息污染 n-gram。

    不去掉的话，[图片] 会被切出"图片"、[回复消息] 会被切出"回复消息"，
    它们频次很高，会直接霸占口头禅前几名。
    """
    out: list[str] = []
    for m in msgs:
        if target is not None and m.speaker != target:
            continue
        for line in (m.text or "").split("\n"):
            line = BRACKET_TAG_RE.sub(" ", line).strip()
            if line:
                out.append(line)
    return out


def _is_media_only(text: str) -> bool:
    """整条消息就是一个或多个媒体/表情占位，没有实际文字。"""
    return bool(BRACKET_ONLY_RE.match((text or "").strip()))


def _counterpart(stats: Stats, target: str) -> str | None:
    """对话的另一方：除蒸馏对象外消息最多的那个人。

    不能随便挑一个。用 set 取"除 target 外的说话人"时，多人群聊会拿到
    「系统消息」这种没有对话意义的说话人，而且 set 的迭代顺序跟着哈希种子变，
    导致同一份数据两次运行结果不同。用它把"另一方"的语义钉死。
    """
    for name, _ in stats.per_speaker.most_common():
        if name != target:
            return name
    return None


def _sessions(msgs: list[Msg], gap: timedelta = SESSION_GAP) -> list[list[Msg]]:
    """按时间间隔切分会话（和 sample_sessions 同一套规则）。"""
    sessions: list[list[Msg]] = []
    cur: list[Msg] = []
    prev: datetime | None = None
    for m in msgs:
        if m.ts and prev and m.ts - prev > gap:
            if cur:
                sessions.append(cur)
            cur = []
        cur.append(m)
        if m.ts:
            prev = m.ts
    if cur:
        sessions.append(cur)
    return sessions


# ----------------------------------------------------------------------------
# 一、短语挖掘（口头禅 / 口癖）
# ----------------------------------------------------------------------------

def _mine_ngrams(texts: list[str], lo: int = 2, hi: int = 5, min_count: int = 3,
                 limit: int = 60) -> list[tuple[str, int]]:
    """字符 n-gram 短语挖掘：不需要任何分词器。"""
    counts: Counter[str] = Counter()
    budget, used = 400_000, 0  # 超大记录时限制挖掘规模，保证响应速度
    for text in texts:
        length = len(text)
        if length > 200:  # 长文本多为粘贴内容，不是说话习惯
            continue
        if used > budget:
            break
        used += length
        for n in range(lo, min(hi, length) + 1):
            for i in range(length - n + 1):
                gram = text[i:i + n]
                if _is_noise(gram):
                    continue
                counts[gram] += 1

    ranked = [(g, c) for g, c in counts.items() if c >= min_count]
    ranked.sort(key=lambda x: (-x[1], -len(x[0])))

    kept: list[tuple[str, int]] = []
    for gram, count in ranked:
        # 若某个更长短语覆盖了它、且出现次数不少于它，说明短串只是碎片
        if any(gram != longer and gram in longer and count <= longer_count
               for longer, longer_count in kept):
            continue
        kept.append((gram, count))

    kept.sort(key=lambda x: (-(x[1] * len(x[0]) ** 0.5), -x[1]))
    return kept[:limit]


def _mine_jieba(lines: list[str], limit: int = 80
                ) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """一次分词同时拿到「词」和「相邻词组合」两套候选。

    组合必须落在词边界上，否则会切出"么不""个吗"这种跨词碎片
    （它们频次不低、看着又像口癖，但根本不是短语）。
    """
    if pseg is None:
        return [], []
    words: Counter[str] = Counter()
    grams: Counter[str] = Counter()
    budget, used = 300_000, 0
    for line in lines:
        if len(line) > 200:
            continue
        if used > budget:
            break
        used += len(line)
        pairs = [(w.strip(), flag) for w, flag in pseg.cut(line) if w.strip()]
        for word, flag in pairs:
            if len(word) < 2 or _is_noise(word):
                continue
            if flag in _KEEP_TAGS or flag[:2] in _KEEP_TAGS:
                words[word] += 1
        tokens = [w for w, _ in pairs]
        for size in (2, 3):
            for i in range(len(tokens) - size + 1):
                gram = "".join(tokens[i:i + size])
                if len(gram) >= 2 and not _is_noise(gram):
                    grams[gram] += 1
    return words.most_common(limit), grams.most_common(limit)


def _mine_edges(texts: list[str], where: str, n: int = 3, min_count: int = 3,
                limit: int = 10) -> list[tuple[str, int]]:
    """句首 / 句尾 n-gram：很多人的口癖固定在句子开头或结尾。"""
    counts: Counter[str] = Counter()
    for text in texts:
        if not (n <= len(text) <= 80):
            continue
        gram = text[:n] if where == "head" else text[-n:]
        # 纯 ASCII 的句首/句尾片段基本是技术词的碎片（ldo、led），不是中文说话习惯
        if _is_noise(gram) or gram.isascii() or _looks_like_topic(gram):
            continue
        counts[gram] += 1
    return [(g, c) for g, c in counts.most_common(limit) if c >= min_count]


def _phrase_items(target_lines: list[str], other_lines: list[str] | None = None,
                  limit: int = 12, exclude: set[str] | None = None) -> list[str]:
    """挑口癖。

    只按频次挑会得到"不要""还有"这种谁都在用的词。真正的判据是
    **这个人用得明显比对话另一方多**——所以拿对方的词频当基线做比值。
    """
    if pseg is not None:
        words, ngrams = _mine_jieba(target_lines)   # 按词边界组合，不切出跨词碎片
    else:
        words, ngrams = [], _mine_ngrams(target_lines)
    heads = _mine_edges(target_lines, "head")
    tails = _mine_edges(target_lines, "tail")
    banned = exclude or set()

    def count_in(token: str, lines: list[str]) -> int:
        """非重叠计数：滑动窗口会把"好好好"里的"好好"数两次，这里重算。"""
        return sum(line.count(token) for line in lines)

    target_chars = max(1, sum(len(line) for line in target_lines))
    baseline = other_lines or []
    baseline_chars = sum(len(line) for line in baseline)
    use_baseline = baseline_chars >= 200  # 对方样本太少时比值不可信

    def distinct(token: str, target_count: int) -> float:
        if not use_baseline:
            return 1.0
        mine = target_count / target_chars
        theirs = count_in(token, baseline) / baseline_chars
        return (mine + 1e-6) / (theirs + 1e-6)

    candidates: list[tuple[str, int, float]] = []
    seen: set[str] = set()
    for token, _ in words + ngrams:
        if token in seen:
            continue
        seen.add(token)
        # 地名是地点线索、说话人名字是称呼，都不算口癖
        if any(token == b or (len(b) >= 2 and (token in b or b in token)) for b in banned):
            continue
        # 词性上属于话题词的（电源、实验室、那我）也丢掉
        if _looks_like_topic(token):
            continue
        target_count = count_in(token, target_lines)
        if target_count < 3:
            continue
        candidates.append((token, target_count, distinct(token, target_count)))

    if use_baseline:  # 只留 TA 明显更常用的说法
        candidates = [c for c in candidates if c[2] >= 1.5]

    # 去掉被更长候选覆盖的碎片
    candidates.sort(key=lambda c: (-c[1], -len(c[0])))
    picked: list[tuple[str, int, float]] = []
    for token, count, score in candidates:
        if any(token != other and token in other and count <= other_count
               for other, other_count, _ in picked):
            continue
        picked.append((token, count, score))

    # 频次与独特性都要：出现得多、并且主要是这个人在用
    picked.sort(key=lambda c: -(c[1] ** 0.5 * c[2] * len(c[0]) ** 0.5))
    items = [f"「{t}」（出现 {c} 次）" for t, c, _ in picked[:limit]]
    if heads:
        items.append("句首习惯：" + "、".join(f"「{g}」×{c}" for g, c in heads[:5]))
    if tails:
        items.append("句尾习惯：" + "、".join(f"「{g}」×{c}" for g, c in tails[:5]))
    return items


# ----------------------------------------------------------------------------
# 二、说话风格（文体计量学）
# ----------------------------------------------------------------------------

def _style_items(msgs: list[Msg], target: str, stats: Stats) -> list[str]:
    texts = [m.text for m in msgs if m.speaker == target and m.text.strip()]
    if not texts:
        return []
    n = len(texts)
    lengths = [len(t) for t in texts]

    items: list[str] = []

    # 消息长度
    short_ratio = _pct(sum(1 for x in lengths if x <= 8), n)
    long_ratio = _pct(sum(1 for x in lengths if x >= 40), n)
    items.append(
        f"消息长度：中位数 {_median(lengths):.0f} 字、平均 {statistics.mean(lengths):.1f} 字，"
        f"{short_ratio:.0f}% 的消息不超过 8 字、{long_ratio:.0f}% 超过 40 字"
    )

    # 标点习惯
    no_end = sum(1 for t in texts if t.strip() and t.strip()[-1] not in SENT_END)
    period = sum(1 for t in texts if t.strip().endswith("。"))
    wave = sum(1 for t in texts if t.strip().endswith(("~", "～")))
    mark = sum(1 for t in texts if t.strip().endswith(("！", "!")))
    items.append(
        f"标点：{_pct(no_end, n):.0f}% 的消息直接断句不打标点；句号 {_pct(period, n):.0f}%、"
        f"波浪号 {_pct(wave, n):.0f}%、感叹号 {_pct(mark, n):.0f}%"
    )

    # 语气词：先去掉叠字串，避免"嘿嘿""哈哈"被当成语气词
    tone = _tone_counter(texts)
    if tone:
        items.append("语气词：" + "、".join(f"{p}×{c}" for p, c in tone.most_common(6)))

    # 叠词与笑声
    laughs = _laugh_counter(texts)
    if laughs:
        items.append("叠词/笑声：" + "、".join(f"{w}×{c}" for w, c in laughs.most_common(6)))

    # 表情与表情包（把 [图片]/[语音] 之类留给"非文字消息"那条，别重复统计）
    emoji: Counter[str] = Counter(e for t in texts for e in EMOJI_RE.findall(t)
                                  if not MEDIA_RE.fullmatch(e))
    if emoji:
        with_emoji = sum(1 for t in texts if any(not MEDIA_RE.fullmatch(e) for e in EMOJI_RE.findall(t)))
        items.append(
            f"表情：{_pct(with_emoji, n):.0f}% 的消息带表情标记，最常用 "
            + "、".join(f"{e}×{c}" for e, c in emoji.most_common(6))
        )

    media: Counter[str] = Counter(m for t in texts for m in MEDIA_RE.findall(t))
    if media:
        items.append("非文字消息：" + "、".join(f"{k}×{v}" for k, v in media.most_common(6)))

    # 句式倾向
    question = sum(1 for t in texts if t.rstrip().endswith(("?", "？", "吗", "呢", "吧")))
    exclaim = sum(1 for t in texts if t.rstrip().endswith(("！", "!", "哈哈", "啦")))
    multi_line = sum(1 for t in texts if "\n" in t)
    items.append(
        f"句式：{_pct(question, n):.0f}% 是问句、{_pct(exclaim, n):.0f}% 是感叹收尾；"
        f"{_pct(multi_line, n):.0f}% 的消息是分多行发的"
    )

    # 连发习惯：同一会话里连续多条属于谁
    bursts = 0
    prev_speaker = None
    for m in msgs:
        if m.speaker == target and prev_speaker == target:
            bursts += 1
        prev_speaker = m.speaker
    if bursts:
        items.append(f"连发习惯：有 {bursts} 次是在自己上一条之后紧接着再发（喜欢拆成几句说）")

    # 深夜活跃（复用 stats）
    if stats.total:
        items.append(f"作息：{stats.late_night / stats.total * 100:.0f}% 的消息出现在 23:00–05:00")
    return items


# ----------------------------------------------------------------------------
# 三、情感模式
# ----------------------------------------------------------------------------

def _compile(words: tuple[str, ...]) -> re.Pattern[str]:
    # 长词在前，避免"喜欢你"被"喜欢"截断
    ordered = sorted(set(words), key=len, reverse=True)
    return re.compile("|".join(re.escape(w) for w in ordered))


_POS_RE = _compile(POS_WORDS)
_NEG_RE = _compile(NEG_WORDS)
_CARE_RE = _compile(CARE_WORDS)
# 长词优先的非重叠匹配，避免"emmm"和"emm"、"2333"和"233"被重复计数
_LAUGH_RE = _compile(LAUGH)

#: "去/到/在/逛" 后面跟着的多半是地点：先宽松捕获，再用 PLACE_TRIM_CHARS 收尾
PLACE_VERB_RE = re.compile(r"(?:去|到|在|逛)(?:了|过)?([\u4e00-\u9fa5A-Za-z0-9]{2,8})")

#: 地点名里几乎不会出现的字（语气词/动词/副词/代词/标点），捕获到它就地截断。
#: 这样"去城西银泰了"→"城西银泰"、"去西湖好不好"→"西湖"、"在干嘛呀"→"干"（太短被丢弃）。
PLACE_TRIM_CHARS = set(
    "了好不要没想会能是我你他她它这那什么怎么吗呢吧啊呀哦嘛啦的"
    "吃喝睡玩买说看做走来回给让把被和跟对太很都还也就只再又真挺蛮超特"
    "，,。！!？?、；;：:（）()　 \t\n"
)


def _emotion_items(msgs: list[Msg], target: str, relation: str = "朋友") -> list[str]:
    texts = [m.text for m in msgs if m.speaker == target and m.text.strip()]
    if not texts:
        return []
    n = len(texts)
    items: list[str] = []

    pos = sum(len(_POS_RE.findall(t)) for t in texts)
    neg = sum(len(_NEG_RE.findall(t)) for t in texts)
    care = sum(len(_CARE_RE.findall(t)) for t in texts)
    total_hits = pos + neg
    if total_hits:
        balance = pos / total_hits * 100
        items.append(
            f"情绪基调：正向表达 {pos} 次、负向 {neg} 次（正向占 {balance:.0f}%）"
            + ("，整体偏暖" if balance >= 65 else "，负面情绪占比不低" if balance <= 40 else "，正负相当")
        )

    pos_msgs = sum(1 for t in texts if _POS_RE.search(t))
    neg_msgs = sum(1 for t in texts if _NEG_RE.search(t))
    items.append(f"表达频率：{_pct(pos_msgs, n):.0f}% 的消息带正向词，{_pct(neg_msgs, n):.0f}% 带负向词")

    if care:
        examples = []
        for t in texts:
            found = _CARE_RE.findall(t)
            if found and t not in examples and not _is_media_only(t):
                examples.append(t)
            if len(examples) >= 2:
                break
        items.append(
            f"关心方式：{care} 次关心类表达（{_pct(sum(1 for t in texts if _CARE_RE.search(t)), n):.0f}% 的消息）"
            + ("，例如「" + "」「".join(_clean(e)[:30] for e in examples) + "」" if examples else "")
        )

    # 生气/冲突时的表达
    conflict_msgs = [t for t in texts
                     if any(w in t for w in CONFLICT_WORDS) and not _is_media_only(t)]
    if conflict_msgs:
        hits: Counter[str] = Counter(w for t in conflict_msgs for w in CONFLICT_WORDS if w in t)
        items.append(
            f"冲突表达：{len(conflict_msgs)} 条消息含冲突词（{_pct(len(conflict_msgs), n):.0f}%），"
            "高频词 " + "、".join(f"{w}×{c}" for w, c in hits.most_common(5))
            + "；示例「" + _clean(conflict_msgs[0])[:30] + "」"
        )

    # 开心
    happy = [t for t in texts if _LAUGH_RE.search(t) and not _is_media_only(t)]
    if happy:
        rich = [t for t in happy if len(t.strip()) > 3] or happy
        items.append(
            f"开心时：{_pct(len(happy), n):.0f}% 的消息带笑声（{len(happy)} 条），"
            f"例如「{_clean(_best_example(rich))[:30]}」"
        )

    # 失落/低气压：排除同时带正向词的（"没事 就是想你了"不是低落）
    low = [t for t in texts if any(w in t for w in LOW_WORDS)
           and not _POS_RE.search(t) and not _is_media_only(t)]
    if low:
        items.append(
            f"低气压时：{_pct(len(low), n):.0f}% 的消息出现过这类信号词"
            f"（{'、'.join(LOW_WORDS[:6])}），例如「{_clean(_best_example(low))[:30]}」"
        )

    # 直球程度
    direct = [t for t in texts
              if any(w in t for w in ("想你", "喜欢你", "爱你", "好想你"))
              and not _is_media_only(t)]
    if direct:
        label = "直球程度" if relation == "恋人" else "直接表达"
        items.append(f"{label}：{len(direct)} 次直接说出想念 / 在意，"
                     f"例如「{_clean(_best_example(direct))[:30]}」")
    elif relation == "恋人":
        items.append("直球程度：记录里没有直接的想你 / 喜欢你这类表达，"
                     "情绪更靠行为和日常关心传达")
    # 非恋爱关系里，"没有直球表达"是废话，不写
    return items


# ----------------------------------------------------------------------------
# 四、关系行为
# ----------------------------------------------------------------------------

def _reply_gaps(msgs: list[Msg]) -> dict[str, list[float]]:
    """统计每个说话者的"回复延迟"（分钟）：换人发言时，间隔算后者的。"""
    gaps: dict[str, list[float]] = defaultdict(list)
    prev: Msg | None = None
    for m in msgs:
        if prev and prev.ts and m.ts and m.speaker != prev.speaker:
            delta = (m.ts - prev.ts).total_seconds() / 60
            if 0 <= delta <= 60 * 24 * 7:  # 超过一周的空档不算"回复"
                gaps[m.speaker].append(delta)
        prev = m
    return gaps


def _relation_items(msgs: list[Msg], target: str, stats: Stats) -> list[str]:
    items: list[str] = []
    counterpart = _counterpart(stats, target)

    gaps = _reply_gaps(msgs)
    mine = gaps.get(target, [])
    if mine:
        items.append(
            f"回复速度：{target} 通常隔 {_fmt_minutes(_median(mine))}回（中位数），"
            f"最慢的 10% 要 {_fmt_minutes(_percentile(mine, 0.9))}以上"
        )
    if mine and counterpart and gaps.get(counterpart):
        their_med, my_med = _median(gaps[counterpart]), _median(mine)
        if abs(their_med - my_med) < 1:
            verdict = "双方节奏相近"
        elif their_med < my_med:
            verdict = "对方回得更快"
        else:
            verdict = "TA 回得更快"
        items.append(f"对比：对方通常隔 {_fmt_minutes(their_med)}回，{verdict}")

    # 主动性
    starts = stats.session_starts.get(target, 0)
    other_starts = sum(v for k, v in stats.session_starts.items() if k != target)
    if starts or other_starts:
        items.append(
            f"主动性：{target} 主动开口 {starts} 次，对方 {other_starts} 次"
            + ("（TA 更常找人）" if starts > other_starts else "（对方更常找人）" if other_starts > starts else "（基本对等）")
        )

    # 谁结束会话
    if counterpart:
        closers: Counter[str] = Counter()
        for sess in _sessions(msgs):
            last = next((m for m in reversed(sess) if m.text.strip()), None)
            if last:
                closers[last.speaker] += 1
        if closers:
            top, cnt = closers.most_common(1)[0]
            total = sum(closers.values())
            items.append(f"收线：{_pct(cnt, total):.0f}% 的会话由 {top} 说最后一句（共 {total} 个会话）")

    # 消息量对比
    if counterpart:
        mine_n = stats.per_speaker.get(target, 0)
        theirs_n = stats.per_speaker.get(counterpart, 0)
        if mine_n and theirs_n:
            ratio = mine_n / (mine_n + theirs_n) * 100
            items.append(
                f"话量：{target} {mine_n} 条 vs {counterpart} {theirs_n} 条（{target} 占 {ratio:.0f}%）"
                + ("，TA 话更多" if ratio > 58 else "，对方话更多" if ratio < 42 else "")
            )

    # 消息长度对称性
    my_len = [len(m.text) for m in msgs if m.speaker == target and m.text.strip()]
    if counterpart:
        their_len = [len(m.text) for m in msgs if m.speaker == counterpart and m.text.strip()]
        if my_len and their_len:
            items.append(
                f"篇幅对称：{target} 平均 {statistics.mean(my_len):.1f} 字，对方平均 {statistics.mean(their_len):.1f} 字"
            )

    # 长期空档
    dated = [m.ts for m in msgs if m.ts]
    if len(dated) >= 2:
        dated.sort()
        worst = max(((b - a).days, a, b) for a, b in zip(dated, dated[1:]))
        if worst[0] >= 14:
            items.append(f"最长失联：{worst[1]:%Y-%m-%d} 到 {worst[2]:%Y-%m-%d} 之间有 {worst[0]} 天没有消息")
    return items


# ----------------------------------------------------------------------------
# 五、典型例句（原文抽取，不是生成）
# ----------------------------------------------------------------------------

def _example_items(msgs: list[Msg], target: str, phrases: list[str], limit: int = 8) -> list[str]:
    keywords = [p.split("」")[0].lstrip("「") for p in phrases if p.startswith("「")]
    scored: list[tuple[float, str]] = []
    for m in msgs:
        if m.speaker != target:
            continue
        text = _clean(m.text)
        if not (6 <= len(text) <= 60):
            continue
        if _is_noise(text) or text.startswith("["):
            continue
        score = 0.0
        score += 3.0 * sum(1 for k in keywords if k and k in text)
        score += 1.5 * len(_POS_RE.findall(text))
        score += 1.5 * len(_NEG_RE.findall(text))
        score += 1.0 * len(_CARE_RE.findall(text))
        score += 0.8 * len(EMOJI_RE.findall(text))
        score += min(len(text), 40) * 0.04
        scored.append((score, text))

    scored.sort(key=lambda x: -x[0])
    out: list[str] = []
    for _, text in scored:
        # 太像的只留一条：既排除互为子串的，也排除同一个开场白的
        if any(text in other or other in text or text[:3] == other[:3] for other in out):
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return [f"「{t}」" for t in out]


# ----------------------------------------------------------------------------
# 六、关系记忆（抽取式）
# ----------------------------------------------------------------------------

def _timeline_items(msgs: list[Msg]) -> list[str]:
    dated = [m.ts for m in msgs if m.ts]
    if len(dated) < 2:
        return []
    dated.sort()
    items = [f"{dated[0]:%Y-%m} 到 {dated[-1]:%Y-%m} 有记录（约 {(dated[-1] - dated[0]).days + 1} 天）"]

    monthly = Counter(f"{d.year}-{d.month:02d}" for d in dated)
    if len(monthly) >= 3:
        top = monthly.most_common(3)
        items.append("消息最密集的月份：" + "、".join(f"{k}（{v} 条）" for k, v in top))

    # 断联区间：按天找连续空白
    days = sorted({d.date() for d in dated})
    gaps = [(b - a).days for a, b in zip(days, days[1:]) if (b - a).days >= 14]
    if gaps:
        items.append(f"有 {len(gaps)} 段明显的空窗期（≥14 天没消息），最长 {max(gaps)} 天")
    return items


def _find_places(msgs: list[Msg]) -> tuple[Counter[str], dict[str, str]]:
    """两条线索结合：地名词尾（"西湖区"）+ 动词后置（"去城西银泰"）。"""
    hits: Counter[str] = Counter()
    sample: dict[str, str] = {}
    for m in msgs:
        text = m.text or ""
        found = [p for p in (_trim_place(raw) for raw in PLACE_RE.findall(text))
                 if len(p) >= 2 and p not in PLACE_BLOCKLIST]
        found += [p for p in (_trim_place(raw) for raw in PLACE_VERB_RE.findall(text))
                  if len(p) >= 2 and p not in PLACE_BLOCKLIST and p not in GENERIC_NGRAMS]
        for place in found:
            hits[place] += 1
            sample.setdefault(place, _clean(text))
    return hits, sample


def _place_items(msgs: list[Msg], limit: int = 8) -> list[str]:
    hits, sample = _find_places(msgs)
    ranked = hits.most_common()
    chosen = [(p, c) for p, c in ranked if c >= 2][:limit]
    if len(chosen) < 3:  # 记录偏短时放宽，宁可标注"提到 1 次"也别整节空着
        chosen += [(p, c) for p, c in ranked if c == 1][:3 - len(chosen)]
    return [f"{p}（提到 {c} 次）——「{sample[p][:36]}」" for p, c in chosen]


def _call_items(msgs: list[Msg], limit: int = 8) -> list[str]:
    hits: Counter[str] = Counter()
    for m in msgs:
        for pat in CALL_PATTERNS:
            for name in pat.findall(m.text or ""):
                if 1 <= len(name) <= 6 and not name.isdigit() and name not in GENERIC_NGRAMS:
                    hits[name] += 1
        for pet in PET_NAMES:
            c = (m.text or "").count(pet)
            if c:
                hits[pet] += c
    out = [f"「{name}」×{count}" for name, count in hits.most_common(limit) if count >= 2]
    return out


def _joke_items(msgs: list[Msg], target: str, counterpart: str | None,
                limit: int = 6) -> list[str]:
    """inside joke 的近似：两边都在用、且频次够高的短语。"""
    if not counterpart:
        return []
    mine = Counter(dict(_mine_ngrams(_lines(msgs, target), min_count=3, limit=200)))
    theirs = Counter(dict(_mine_ngrams(_lines(msgs, counterpart), min_count=3, limit=200)))
    shared = [(g, min(mine[g], theirs[g])) for g in mine.keys() & theirs.keys()]
    # 频次相同时按长度和字形排，避免集合迭代顺序让输出抖动
    shared.sort(key=lambda x: (-x[1], -len(x[0]), x[0]))
    return [f"「{g}」（双方各用约 {c} 次，是你们之间的固定说法）" for g, c in shared[:limit]]


def _quarrel_items(msgs: list[Msg], limit: int = 4) -> list[str]:
    """找冲突密度最高的会话，给出起因原话和收场信号。"""
    scored = []
    for sess in _sessions(msgs):
        text = "\n".join(m.text for m in sess)
        hits = sum(1 for w in CONFLICT_WORDS if w in text)
        if hits >= 2 and len(sess) >= 4:
            scored.append((hits * len(sess) ** 0.3, sess, hits))
    scored.sort(key=lambda x: -x[0])

    out = []
    for _, sess, hits in scored[:limit]:
        conflict = [m for m in sess if any(w in m.text for w in CONFLICT_WORDS)]
        if not conflict:
            continue
        first = conflict[0]
        when = f"{first.ts:%Y-%m-%d}" if first.ts else "某次"
        lead = [m for m in conflict if m is not first][:2] or conflict[:2]
        detail = "；".join(f"{m.speaker}：「{_clean(m.text)[:24]}」" for m in lead)
        tail = next((m for m in reversed(sess)
                     if any(w in m.text for w in ("对不起", "抱歉", "别生气", "好啦", "抱抱", "亲亲"))), None)
        line = f"{when} 前后有过一次冲突（命中 {hits} 类冲突词）：{detail}"
        if tail and tail not in lead:
            line += f"；收场信号来自 {tail.speaker}：「{_clean(tail.text)[:24]}」"
        out.append(line)
    return out


def _sweet_items(msgs: list[Msg], limit: int = 6) -> list[str]:
    scored: list[tuple[float, str]] = []
    for m in msgs:
        text = _clean(m.text)
        if not (6 <= len(text) <= 60) or _is_noise(text):
            continue
        score = 2.0 * len(_POS_RE.findall(text)) + 1.5 * len(_CARE_RE.findall(text))
        if score <= 0:
            continue
        scored.append((score, f"{m.speaker}：「{text[:40]}」"))
    scored.sort(key=lambda x: -x[0])
    out: list[str] = []
    for _, text in scored:
        if any(text in other or other in text for other in out):
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


# ----------------------------------------------------------------------------
# 七、硬规则（从统计反推的、可验证的底线）
# ----------------------------------------------------------------------------

def _rule_items(msgs: list[Msg], target: str, stats: Stats) -> list[str]:
    texts = [m.text for m in msgs if m.speaker == target and m.text.strip()]
    if not texts:
        return []
    n = len(texts)
    rules: list[str] = []

    gaps = _reply_gaps(msgs).get(target, [])
    if gaps:
        med = _median(gaps)
        if med < 3:
            rules.append(f"回消息快，通常 {_fmt_minutes(med)}内就回")
        elif med < 60:
            rules.append(f"不会秒回：通常隔 {_fmt_minutes(med)} 才回一句，别表现得太即时")
        else:
            rules.append(f"回消息很慢，中位间隔 {_fmt_minutes(med)}；不要写成秒回的人")

    no_end = sum(1 for t in texts if t.strip()[-1] not in SENT_END)
    if no_end / n > 0.6:
        rules.append(f"不打标点直接断句（{_pct(no_end, n):.0f}% 的消息没有句尾标点），不要写成书面语的完整句子")
    elif no_end / n < 0.2:
        rules.append("句子标点完整，习惯写完整的句子")

    lengths = [len(t) for t in texts]
    if _median(lengths) <= 8:
        rules.append(f"偏好短句（中位 {_median(lengths):.0f} 字），一次说一点，不要长篇大论")

    if stats.total:
        late = stats.late_night / stats.total * 100
        if late >= 25:
            rules.append(f"深夜型选手（{late:.0f}% 的消息在 23:00–05:00），夜里更活跃")

    particles = _tone_counter(texts)
    if particles:
        top = "".join(p for p, _ in particles.most_common(4))
        rules.append(f"常用语气词「{top}」，说话要带这些尾巴")

    emoji: Counter[str] = Counter(e for t in texts for e in EMOJI_RE.findall(t)
                                  if not MEDIA_RE.fullmatch(e))
    if emoji:
        rules.append("会用表情标记：" + "、".join(e for e, _ in emoji.most_common(4)))
    else:
        rules.append("从不使用表情或表情包")

    rules.append("以上规则来自统计；没被记录过的细节不要编造，宁可不回答")
    return rules


# ----------------------------------------------------------------------------
# 组装
# ----------------------------------------------------------------------------

def _identity_items(desc: str) -> list[str]:
    if desc:
        return [desc]
    return ["记录里没有直接的身份信息；建议用 --desc 补充职业、关系、认识方式等背景"]


def distill(msgs: list[Msg], target: str, stats: Stats, desc: str = "",
            relation: str = "朋友") -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """返回 (persona, memory)，结构对齐 render.py 需要的字段。"""
    target_lines = _lines(msgs, target)
    counterpart = _counterpart(stats, target)
    other_lines = _lines([m for m in msgs if m.speaker == counterpart])
    place_hits, _ = _find_places(msgs)
    # 地名已经单独成节、说话人名字属于称呼，都不该再混进口头禅
    phrase_items = _phrase_items(target_lines, other_lines,
                                 exclude=set(place_hits) | {m.speaker for m in msgs})
    style_items = _style_items(msgs, target, stats)

    persona = {
        "身份": _identity_items(desc),
        "说话风格": style_items,
        "口头禅": phrase_items,
        "情感模式": _emotion_items(msgs, target, relation),
        "关系行为": _relation_items(msgs, target, stats),
        "典型例句": _example_items(msgs, target, phrase_items),
        "硬规则": _rule_items(msgs, target, stats),
    }
    memory = {
        "关系时间线": _timeline_items(msgs),
        "一起去过的地方": _place_items(msgs),
        "inside_jokes": _joke_items(msgs, target, counterpart),
        "争吵模式": _quarrel_items(msgs),
        "甜蜜瞬间": _sweet_items(msgs),
        "称呼与专属用语": _call_items(msgs),
    }
    return persona, memory
