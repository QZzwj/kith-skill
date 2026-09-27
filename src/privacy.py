import re


REDACTIONS = [
    (re.compile(r"1[3-9]\d{9}"), "[手机号]"),
    (re.compile(r"\b\d{17}[\dXx]\b"), "[身份证]"),
    (re.compile(r"\b\d{16,19}\b"), "[卡号]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"), "[邮箱]"),
    (re.compile(r"(?:[\u4e00-\u9fa5]{2,8}(?:省|市|区|县|镇|街道|小区|大厦|公寓)){2,}"), "[详细地址]"),
]


def redact(text: str) -> str:
    for pat, tag in REDACTIONS:
        text = pat.sub(tag, text)
    return text


#: 只有本人接得住的指代。公开版里这些话说给别人的分身听，对面接不上。
#: 刻意只标注、不改写也不删：句子本身可能是好素材，误删的代价比标出来大，
#: 而"改写"要动语义，那是模型该干的事，不该由正则偷偷做。
DEIXIS = (
    "咱俩", "咱们", "我们俩", "你我", "跟你说过", "我跟你", "你上次", "我上次",
    "上次说", "上次那个", "上回", "那次", "你还记得", "记得吗", "你之前说", "我之前说",
)

_DEIXIS_RE = re.compile("|".join(re.escape(p) for p in DEIXIS))

PUBLIC_MARK = "（公开版需确认：这里的指代只有本人对得上）"


def flag_deixis(items: dict) -> tuple[dict, int]:
    """给"只有本人对得上"的条目加一句提醒，返回（副本, 命中条数）。"""
    flagged = 0
    out: dict = {}
    for section, value in items.items():
        if not isinstance(value, list):
            out[section] = value
            continue
        marked = []
        for item in value:
            text = str(item)
            if _DEIXIS_RE.search(text):
                flagged += 1
                marked.append(f"{text} {PUBLIC_MARK}")
            else:
                marked.append(item)
        out[section] = marked
    return out, flagged


# ----------------------------------------------------------------------------
# 五、LLM（OpenAI 兼容接口，标准库实现）
# ----------------------------------------------------------------------------
