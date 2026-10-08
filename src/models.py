from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class Msg:
    ts: datetime | None
    speaker: str
    text: str
    source_id: str = ''
    reply_to: str = ''


@dataclass
class Stats:
    total: int = 0
    per_speaker: Counter = field(default_factory=Counter)
    hours: Counter = field(default_factory=Counter)
    late_night: int = 0
    timed_total: int = 0       # 蒸馏对象带时间的消息数；深夜占比不能借用对方的作息
    emoji: Counter = field(default_factory=Counter)
    phrases: Counter = field(default_factory=Counter)
    conflict_hits: Counter = field(default_factory=Counter)
    avg_len: float = 0.0
    session_starts: Counter = field(default_factory=Counter)
    first_ts: datetime | None = None
    last_ts: datetime | None = None
    #: 下面四个是「温度」的客观线索：光看"说了什么"量不出亲疏，
    #: 回复快慢、连不连发、爱不爱反问、表情密度才是聊天里的体温。
    reply_gap: float = 0.0      # TA 的回复间隔中位数（分钟）
    burst_ratio: float = 0.0    # TA 的消息里「紧接着自己上一条」的比例（喜欢拆成几句说）
    question_ratio: float = 0.0 # TA 的消息里问句的比例（爱不爱把话抛回去）
    emoji_ratio: float = 0.0    # TA 的消息里带表情标记的比例


CONFLICT_WORDS = ["吵", "生气", "不理", "分手", "烦", "算了", "随便", "别说了",
                  "冷战", "道歉", "对不起", "后悔",
                  # 日常带刺的表达：闹别扭时不说"分手"但会说这些
                  "别跟我", "你发消息就是", "没催", "别催", "改期", "正经点",
                  "行吧", "就这", "不想说", "没打算", "你又", "每次都"]
STOP_PHRASES = {"哈哈", "哈哈哈", "嗯嗯", "哦哦", "好的", "在的", "然后", "就是",
                "什么", "怎么", "可以", "没有", "不是", "我们", "你们", "他们",
                "哈哈哈哈哈", "这个", "那个", "现在", "已经", "还是", "真的"}

SESSION_GAP = timedelta(minutes=30)


# ----------------------------------------------------------------------------
# 一、解析聊天记录（多格式嗅探）
