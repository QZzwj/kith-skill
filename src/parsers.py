import csv
import email
import email.header
import io
import json
import mailbox
import quopri
import re
import sqlite3
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from .models import Msg


TIME_PATTERNS = [
    re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?"),
    re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})(?::(\d{2}))?"),
    re.compile(r"^(\d{1,2})[-/.](\d{1,2})[ T](\d{1,2}):(\d{2})"),  # 无年份
]
LINE_WITH_NAME = re.compile(r"^(?P<who>[^:：\[\]]{1,24})\s*[:：]\s*(?P<text>.+)$")
WEIBO_EMOJI = re.compile(r"\[[^\[\]]{1,8}\]")
SENTENCE_SPLIT = re.compile(r"[。！？!?~～\.,，、\s]+")


def _mk_ts(groups) -> datetime | None:
    try:
        nums = [int(g) if g else 0 for g in groups]
        if len(nums) == 6:
            y, mo, d, h, mi, s = nums
        elif len(nums) == 4:  # 无年份
            y, mo, d, h, mi, s = datetime.now().year, nums[0], nums[1], nums[2], nums[3], 0
        else:
            return None
        if not (1970 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            return None
        return datetime(y, mo, d, h, min(mi, 59), min(s, 59))
    except Exception:
        return None


def _parse_time_prefix(line: str):
    stripped = line.lstrip()
    # 很多导出格式把时间放在中括号里：[2023-06-01 23:40] 昵称: 内容
    if stripped.startswith("["):
        end = stripped.find("]")
        if 0 < end <= 32:
            inner = stripped[1:end].strip()
            rest = stripped[end + 1:].lstrip()
            for pat in TIME_PATTERNS:
                m = pat.match(inner)
                if m:
                    ts = _mk_ts(m.groups())
                    if ts:
                        return ts, rest
    for pat in TIME_PATTERNS:
        m = pat.match(stripped)
        if m:
            ts = _mk_ts(m.groups())
            if ts:
                return ts, stripped[m.end():].strip()
    return None, line


def _pick_column(header: list[str], keys: tuple) -> int | None:
    """按 keys 的顺序挑第一个命中的列，保证优先取更可靠的那一列。"""
    for key in keys:
        for i, name in enumerate(header):
            if key in name:
                return i
    return None


# QQ 导出的 txt 里有大量分隔与说明行，必须丢掉，否则会混进消息正文
BANNER_KEYS = ("消息记录", "消息分组", "消息对象", "===========")


def _is_banner(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if len(stripped) >= 3 and set(stripped) <= set("=-= "):
        return True
    return any(stripped.startswith(key) for key in BANNER_KEYS)


def parse_csv(path: Path) -> list[Msg]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return []

    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if any(str(c).strip() for c in r)]
    if not rows:
        return []

    header = [str(c).strip().lower() for c in rows[0]]
    # 按优先级挑列：微信系工具导出的表头差异很大（WeChatMsg / 留痕 / PyWxDump…）
    idx_time = _pick_column(header, ("strtime", "createtime", "time", "date", "时间", "日期"))
    idx_who = _pick_column(header, ("nickname", "remark", "昵称", "备注", "sendername",
                                    "sender", "发送", "name", "talker", "用户", "from"))
    idx_text = _pick_column(header, ("strcontent", "content", "text", "消息", "内容",
                                     "正文", "displaycontent", "msg"))
    # WeChatMsg 之类会给出 IsSender：1=本人，0=对方；比靠昵称判断可靠得多
    idx_sender = _pick_column(header, ("issender", "is_sender"))
    idx_id = _pick_column(header, ('message_id', 'msgid', 'localid', '消息id'))
    idx_reply = _pick_column(header, ('reply_to', 'replytomsgid', '引用id'))
    body = rows[1:] if idx_text is not None else rows
    if idx_text is None:                       # 无表头：按 时间, 昵称, 内容 猜
        idx_time, idx_who, idx_text = 0, 1, 2

    out: list[Msg] = []
    for row in body:
        if len(row) <= max(filter(None, (idx_time, idx_who, idx_text)) or [0]):
            continue
        ts_raw = str(row[idx_time]).strip()
        ts = None
        for pat in TIME_PATTERNS:
            mm = pat.match(ts_raw)
            if mm:
                ts = _mk_ts(mm.groups())
                break
        if ts is None:
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", ""))
            except Exception:
                ts = None
        who = str(row[idx_who]).strip() if idx_who is not None else ""
        if idx_sender is not None and len(row) > idx_sender:
            flag = str(row[idx_sender]).strip().lower()
            who = "我" if flag in ("1", "true", "yes") else (who or "对方")
        txt = str(row[idx_text]).strip() if idx_text is not None else ""
        if txt:
            out.append(Msg(ts, who or "未知", txt,
                           str(row[idx_id]) if idx_id is not None and idx_id < len(row) else '',
                           str(row[idx_reply]) if idx_reply is not None and idx_reply < len(row) else ''))
    return out


def _parse_any_timestamp(value) -> datetime | None:
    """兼容 Unix 秒/毫秒、ISO-8601、常见导出文本时间。"""
    if isinstance(value, (int, float)) and value > 0:
        try:
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value)
        except (OverflowError, OSError, ValueError):
            return None
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    for pat in TIME_PATTERNS:
        match = pat.match(text)
        if match:
            ts = _mk_ts(match.groups())
            if ts:
                return ts
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _json_text(value) -> str:
    """提取 Telegram 的 text 片段、Facebook/WhatsApp 的正文等。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
        return "".join(parts).strip()
    if isinstance(value, dict):
        return _json_text(value.get("text") or value.get("content") or value.get("body") or "")
    return ""


def _json_items(data):
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in ("messages", "list", "items", "posts", "comments", "statuses", "data"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return []


#: wx-cli（微信 PC 4.x 导出）的 JSON：顶层 chat/username/chat_type + messages[]，
#: 每条消息是 {content, local_id, sender, time, timestamp, type}。
def _looks_like_wx_json(data) -> bool:
    """是否是 wx-cli 的微信导出 JSON。

    这类记录的两个坑（都实测过）：

    * **对面没有 sender**：私聊里 ``sender`` 只在本人发言时填本人的昵称，
      对方的消息是空串（不是缺失字段）。不处理的话通用逻辑会把它落到「未知」——
      实测一份 5.1 万条的记录有 23594 条（46%）因此失去归属。
    * **本人填的是真实昵称**：所以 ``--me`` 的默认值「我」对不上，自动判断时
      会把自己的消息当成要蒸馏的对象。私聊只有两个人，非空的那一侧必然是
      本地账号自己，因此这里直接归一到「我」；对方用会话名（顶层 ``chat``）补上。
    """
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        return False
    if "chat" not in data or "username" not in data:
        return False
    sample = [it for it in data["messages"][:50] if isinstance(it, dict)]
    if not sample:
        return False
    hit = sum(1 for it in sample if {"content", "time", "type"} <= it.keys())
    return hit * 2 >= len(sample)


def parse_wechat_db(path: Path, channel: str | None = None) -> list[Msg]:
    """读取已解密的微信 EnMicroMsg.db 的 MSG 表。"""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        where = "WHERE Type = 1"
        params: list[object] = []
        if channel:
            where += " AND StrTalker = ?"
            params.append(channel)
        rows = conn.execute(
            f"SELECT StrContent, CreateTime, IsSender, StrTalker FROM MSG {where} "
            "ORDER BY CreateTime ASC",
            params,
        ).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        raise ValueError(f"无法读取微信 SQLite 数据库：{exc}") from exc

    out: list[Msg] = []
    for text, raw_ts, is_sender, talker in rows:
        text = str(text or "").strip()
        if not text:
            continue
        ts = None
        if isinstance(raw_ts, (int, float)) and raw_ts > 0:
            try:
                ts = datetime.fromtimestamp(raw_ts / 1000 if raw_ts > 1e11 else raw_ts)
            except (OverflowError, OSError, ValueError):
                pass
        speaker = "我" if is_sender == 1 else str(talker or "对方")
        out.append(Msg(ts, speaker, text))
    return out


def parse_qq_txt(path: Path, text: str) -> list[Msg]:
    """QQ 消息管理器导出（.txt，或 .mht 转出来的纯文本）。

    形如：
        2023-01-01 12:00:00 小雨(123456)
        在干嘛
    """
    out: list[Msg] = []
    cur_who, cur_ts = "", None
    qq_head = re.compile(r"^(?P<ts>\d{4}-\d{1,2}-\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?)\s+(?P<who>.+?)(?:\(\d+\)|<[^>]+>)?\s*$")
    for line in text.splitlines():
        line = line.rstrip()
        if _is_banner(line):
            continue
        m = qq_head.match(line)
        if m:
            cur_ts = None
            for pat in TIME_PATTERNS:
                mm = pat.match(m.group("ts"))
                if mm:
                    cur_ts = _mk_ts(mm.groups())
                    break
            cur_who = m.group("who").strip()
            continue
        if cur_who:
            out.append(Msg(cur_ts, cur_who, line.strip()))
    return out


WHATSAPP_HEAD = re.compile(
    r"^\[?(?P<date>\d{1,4}[/-]\d{1,2}[/-]\d{1,4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s*[APap][Mm])?)\]?\s*"
    r"-?\s*(?P<who>[^:]+):\s*(?P<text>.*)$"
)


def parse_whatsapp_txt(text: str) -> list[Msg]:
    """解析 WhatsApp 导出 TXT，支持多行消息和 12/24 小时制。"""
    out: list[Msg] = []
    current: Msg | None = None
    for line in text.splitlines():
        match = WHATSAPP_HEAD.match(line.strip())
        if match:
            if current and current.text.strip():
                out.append(current)
            ts = None
            date_text, time_text = match.group("date"), match.group("time")
            for fmt in (
                "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
                "%d/%m/%y %H:%M:%S", "%d/%m/%y %H:%M",
                "%m/%d/%Y %I:%M %p", "%m/%d/%y %I:%M %p",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
            ):
                try:
                    ts = datetime.strptime(f"{date_text} {time_text}", fmt)
                    break
                except ValueError:
                    continue
            current = Msg(ts, match.group("who").strip(), match.group("text").strip())
        elif current and line.strip():
            current.text += "\n" + line.strip()
    if current and current.text.strip():
        out.append(current)
    return out


def parse_generic_txt(text: str) -> list[Msg]:
    out: list[Msg] = []
    cur_ts, cur_who = None, ""
    for line in text.splitlines():
        line = line.strip()
        if _is_banner(line):
            continue
        ts, rest = _parse_time_prefix(line)
        if ts:
            cur_ts = ts
            nm = LINE_WITH_NAME.match(rest)
            if nm:
                cur_who = nm.group("who").strip()
                out.append(Msg(cur_ts, cur_who, nm.group("text").strip()))
                continue
            line = rest
        nm = LINE_WITH_NAME.match(line)
        if nm and len(nm.group("who")) <= 20:
            cur_who = nm.group("who").strip()
            out.append(Msg(cur_ts, cur_who, nm.group("text").strip()))
        elif out:
            out[-1].text += " " + line
    return out


def parse_json_log(path: Path) -> list[Msg]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return []
    items = _json_items(data)
    wx = _looks_like_wx_json(data)
    #: 私聊的对面与会话名同一个人（wx-cli 不给对端填 sender，只给本人填昵称）
    wx_partner = (str(data.get("chat") or "").strip()
                  if wx and isinstance(data, dict) and not data.get("is_group") else "")
    out: list[Msg] = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        txt = _json_text(
            it.get("text") or it.get("body") or it.get("content")
            or it.get("message") or it.get("post") or it.get("full_text") or it.get("msg") or ""
        )

        # QQChatExporter stores sender as an object. Prefer the display name
        # and fall back through the other human-readable identity fields.
        who = (it.get("speaker") or it.get("sender") or it.get("sender_name") or it.get("author")
               or it.get("user") or it.get("talker") or it.get("name")
               or it.get("from") or it.get("actor") or "")
        if isinstance(who, dict):
            who = (who.get("name") or who.get("remark") or who.get("nickname")
                   or who.get("uin") or who.get("uid") or "")
        t = it.get("created_at") or it.get("createdAt") or it.get("timestamp_ms")
        t = t if t is not None else (it.get("time") or it.get("timestamp") or it.get("date") or "")
        ts = _parse_any_timestamp(t)
        speaker = str(who).strip()
        if wx:
            # 系统提示（撤回/位置共享等）也是空 sender，靠 type 先摘出来，
            # 免得把系统提示算成某一方说的话。
            if str(it.get("type", "")).strip() == "系统":
                speaker = "系统消息"
            elif wx_partner and speaker:
                # 私聊非空的那一侧＝本地账号自己（实测「文件传输助手」全是本人发言且 sender 为昵称）
                speaker = "我"
            elif wx_partner:
                speaker = wx_partner
        if txt:
            identity = it.get('source_id', it.get('message_id', it.get('id', it.get('msgid', ''))))
            quoted = it.get('reply_to_message_id', it.get('reply_to', it.get('replyTo', '')))
            if isinstance(quoted, dict):
                quoted = quoted.get('message_id', quoted.get('id', ''))
            out.append(Msg(ts, speaker or "未知", txt,
                           str(identity) if isinstance(identity, (str, int)) else '',
                           str(quoted) if isinstance(quoted, (str, int)) else ''))
    return out


def parse_twitter_js(path: Path) -> list[Msg]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    # 归档文件形如 `window.YTD.tweets.part0 = [...]`，赋值左侧可能是带点的长路径
    text = re.sub(r"^(?:window\.)?[\w.]+\s*=\s*", "", text.strip(), count=1)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if path.name.lower() in ("direct-messages.js", "direct_messages.js"):
        items = []
        for conv in data if isinstance(data, list) else []:
            obj = conv.get("dmConversation", conv) if isinstance(conv, dict) else {}
            for entry in obj.get("messages", []):
                msg = entry.get("messageCreate", entry) if isinstance(entry, dict) else {}
                items.append({"text": msg.get("text"), "sender": msg.get("senderId"),
                              "createdAt": msg.get("createdAt")})
        return _messages_from_items(items)
    items = []
    for item in data if isinstance(data, list) else []:
        items.append(item.get("tweet", item) if isinstance(item, dict) else item)
    return _messages_from_items(items)


def _messages_from_items(items) -> list[Msg]:
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = _json_text(item.get("text") or item.get("full_text") or item.get("body")
                          or item.get("content") or item.get("message") or item.get("post") or "")
        if not text:
            continue
        sender = item.get("sender") or item.get("sender_name") or item.get("author")
        if isinstance(sender, dict):
            sender = sender.get("name") or sender.get("username") or sender.get("id")
        ts = _parse_any_timestamp(item.get("createdAt") or item.get("created_at")
                                  or item.get("timestamp_ms") or item.get("timestamp")
                                  or item.get("date") or item.get("time"))
        out.append(Msg(ts, str(sender or "未知"), text))
    return out


def parse_mbox(path: Path) -> list[Msg]:
    out = []
    try:
        box = mailbox.mbox(str(path))
        for message in box:
            body = ""
            if message.is_multipart():
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode(part.get_content_charset() or "utf-8", "replace")
                            break
            else:
                payload = message.get_payload(decode=True)
                if payload:
                    body = payload.decode(message.get_content_charset() or "utf-8", "replace")
            body = body.strip()
            if not body:
                continue
            subject = str(email.header.make_header(email.header.decode_header(message.get("Subject", ""))))
            if subject:
                body = f"{subject}\n\n{body}"
            sender = message.get("From", "")
            ts = None
            if message.get("Date"):
                try:
                    parsed = parsedate_to_datetime(message.get("Date"))
                    ts = parsed.replace(tzinfo=None) if parsed else None
                except (TypeError, ValueError, OverflowError):
                    pass
            out.append(Msg(ts, sender, body))
    except Exception as exc:
        raise ValueError(f"无法读取 mbox：{exc}") from exc
    return out


class _TextExtractor(HTMLParser):
    """把 HTML / MHT 抽成纯文本，块级标签换算行。"""

    BLOCK_TAGS = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "td", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def strip_html(text: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(text)
    except Exception:
        pass
    plain = "".join(parser.parts).replace("\u00a0", " ")
    plain = re.sub(r"[ \t]+", " ", plain)
    plain = re.sub(r"\n{3,}", "\n\n", plain)
    return plain


def decode_quoted_printable(text: str) -> str:
    """QQ 的 .mht 常用 quoted-printable，先还原成可读文本（没有转义就原样返回）。"""
    if not re.search(r"=[0-9A-Fa-f]{2}", text):
        return text
    try:
        return quopri.decodestring(text.encode("utf-8", "ignore")).decode("utf-8", "ignore")
    except Exception:
        return text


def strip_mime_envelope(text: str) -> str:
    """丢掉 MHT/MHTML 的 MIME 信封，只留第一个 part 的正文。

    信封是：
        From: ...
        Content-Type: multipart/related; boundary="----=_NextPart_000"
        <空行>
        ------=_NextPart_000
        Content-Type: text/html; charset="utf-8"
        <空行>
        <正文>

    strip_html 只去标签，不去信封，于是 `MIME-Version: 1.0` 这类头会原样留下——
    而下游的「昵称: 内容」通用解析器恰好以冒号为分隔符，会把它们当成聊天消息
    （实测解析结果里冒出说话人 `MIME-Version`、首条消息 `1.0`）。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    head = text.split("\n\n", 1)[0]
    # 先确认开头确实是一段 MIME 头再动手。
    # 必须这么保守：正文里出现一行以 `--` 开头的内容是完全可能的，
    # 只看边界就切会把边界之前的聊天记录整段丢掉。
    if not re.search(r"^(MIME-Version|Content-Type|Content-Transfer-Encoding"
                     r"|From|Subject|Date):", head, re.MULTILINE):
        return text
    m = re.search(r"^--(\S+)", text, re.MULTILINE)
    if not m:
        return text                      # 没有 MIME 边界，不是多变体文件
    token = m.group(1).rstrip("-")       # 边界标识（去掉结尾的连字符）
    if not token:
        return text
    body = text[m.end():]
    # 第一个 part 自己的头部（Content-Type / Content-Transfer-Encoding）到第一个空行为止
    part = re.search(r"\n[ \t]*\n", body)
    if part:
        body = body[part.end():]
    # 只按**同一个**边界标识切，丢掉后续 part 和结束边界。
    # 不能见到 `--` 开头就切：正文里完全可能出现以 -- 开头的一行，
    # 那样会把这条消息之后的所有聊天记录一起丢掉。
    return re.split(r"^--" + re.escape(token), body, flags=re.MULTILINE)[0]


def read_text_any(path: Path) -> str | None:
    raw = path.read_bytes()
    # utf-8 必须排在 gb18030 前面：gb18030 几乎能"解码"任何字节，会掩盖真正的 UTF-8
    for enc in ("utf-8-sig", "utf-8", "gb18030", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return None


def _looks_like_whatsapp(text: str) -> bool:
    """首行是 WhatsApp 头部、且至少命中两行，才认为它是 WhatsApp 导出。"""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or not WHATSAPP_HEAD.match(lines[0]):
        return False
    return sum(1 for line in lines if WHATSAPP_HEAD.match(line)) >= 2


#: 图片/文件类标记常带哈希文件名：[图片:B572F40F778BC9CC9C3EB0D5036505AB.jpg]
MEDIA_TAG_RE = re.compile(
    r"\[(图片|照片|表情|语音|视频|文件|链接|位置|动画表情|回复消息|合并转发|转账|红包)"
    r"\s*[:：][^\[\]]{0,240}\]"
)
#: wx-cli 给图片消息的正文带了内部主键尾巴：[图片] local_id=18750
LOCAL_ID_TAIL_RE = re.compile(r"\s+local_id=\d+\s*$")
#: QQ 表情码：整条消息由一个或多个 "/睁眼" 这样的码组成（faceType 2）
FACE_RUN_RE = re.compile(r"(?:/[^\s/:：，。！？、]{1,12})+")
#: 文件收发提示：对方已接收文件「xxx.docx」
FILE_NOTICE_RE = re.compile(r"^(?:对方|我|你)?已?(?:接收|发送)文件[「『\"].*[」』\"]$")


def normalize_message_text(text: str) -> str:
    """把导出格式里的媒体标记收拾干净。

    不做这一步，图片的哈希文件名（……F40F778BC9CC.jpg）和表情码（/睁眼）
    会被当成口头禅，十六进制片段 A5 / EB / 9A 会占据头几名——
    这在真实导出数据里非常普遍。
    """
    if not text:
        return text
    text = LOCAL_ID_TAIL_RE.sub("", text)
    text = MEDIA_TAG_RE.sub(lambda m: f"[{m.group(1)}]", text)
    stripped = text.strip()
    if FILE_NOTICE_RE.match(stripped):
        return "[文件]"
    if FACE_RUN_RE.search(text) and not FACE_RUN_RE.sub("", text).strip():
        return "[表情]"
    return text


#: 逐个试解析器时用的编码顺序，和 read_text_any 保持一致
ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "utf-16")


def diagnose(path: Path) -> dict:
    """回报每个解析器能解出多少条，用来解释"为什么只解析出 N 条"。

    解析是整条流水线的入口，错在这里后面全白做，但 load_messages 是完全静默的：
    用户只会看到"没解析出任何消息"，分不清是格式不支持、编码猜错，
    还是走了错误的解析器。
    """
    raw = path.read_bytes()
    decodable = []
    for enc in ENCODINGS:
        try:
            raw.decode(enc)
        except UnicodeDecodeError:
            continue
        decodable.append(enc)

    candidates: list[dict] = []

    def probe(name: str, fn) -> None:
        try:
            msgs = fn()
        except Exception as exc:  # 单个解析器出错不该拖垮整份报告
            candidates.append({"parser": name, "count": 0, "error": str(exc)[:160]})
            return
        candidates.append({
            "parser": name,
            "count": len(msgs),
            "speakers": len({m.speaker for m in msgs}),
            "with_ts": sum(1 for m in msgs if m.ts),
        })

    suffix = path.suffix.lower()
    if suffix in (".db", ".sqlite", ".sqlite3") or raw[:16] == b"SQLite format 3\x00":
        probe("微信 SQLite（MSG 表）", lambda: parse_wechat_db(path))
    if suffix == ".csv":
        probe("CSV 表格", lambda: parse_csv(path))
    if suffix == ".json":
        probe("JSON 消息数组", lambda: parse_json_log(path))
    if suffix == ".js":
        probe("Twitter/X 归档", lambda: parse_twitter_js(path))
    if suffix == ".mbox":
        probe("mbox 邮件归档", lambda: parse_mbox(path))

    text = read_text_any(path)
    if text is not None:
        body = text
        # .mht 与 .mhtml 是同一格式的两种扩展名（QQ 消息管理器导出 .mht，
        # 浏览器另存网页给 .mhtml），必须一起处理，否则会拿 MIME 源码当正文。
        if suffix in (".mht", ".mhtml", ".html", ".htm"):
            if suffix in (".mht", ".mhtml"):
                body = decode_quoted_printable(strip_mime_envelope(body))
            body = strip_html(body)
        probe("QQ 消息管理器导出", lambda: parse_qq_txt(path, body))
        probe("WhatsApp 导出", lambda: parse_whatsapp_txt(body))
        probe("通用「昵称: 内容」文本", lambda: parse_generic_txt(body))

    return {"candidates": candidates, "decodable_encodings": decodable}


def load_messages(path: Path, channel: str | None = None,
                  trace: list[str] | None = None) -> list[Msg]:
    """解析任意支持的格式，并规范化媒体标记后返回。

    传入 ``trace`` 会收到实际接走这份文件的解析器名——路由过程原本是完全静默的，
    出了问题只能看到"没解析出任何消息"。
    """
    from dataclasses import replace
    return [replace(m, text=normalize_message_text(m.text))
            for m in _load_messages(path, channel, trace)]


def _load_messages(path: Path, channel: str | None = None,
                   trace: list[str] | None = None) -> list[Msg]:
    def picked(name: str, msgs: list[Msg]) -> list[Msg]:
        if trace is not None:
            trace.append(name)
        return msgs

    if path.is_dir():
        msgs: list[Msg] = []
        for child in sorted(path.rglob("*")):
            if child.is_file() and child.suffix.lower() in (
                    ".txt", ".csv", ".json", ".mht", ".mhtml", ".html", ".htm",
                    ".js", ".mbox"):
                msgs.extend(_load_messages(child, channel=channel, trace=trace))
        return msgs

    suffix = path.suffix.lower()
    if suffix in (".db", ".sqlite", ".sqlite3") or path.read_bytes()[:16] == b"SQLite format 3\x00":
        return picked("微信 SQLite（MSG 表）", parse_wechat_db(path, channel=channel))
    if suffix == ".csv":
        return picked("CSV 表格", parse_csv(path))
    if suffix == ".json":
        return picked("JSON 消息数组", parse_json_log(path))
    if suffix == ".js":
        return picked("Twitter/X 归档", parse_twitter_js(path))
    if suffix == ".mbox":
        return picked("mbox 邮件归档", parse_mbox(path))

    text = read_text_any(path)
    if text is None:
        return picked("（无法识别编码）", [])
    if suffix in (".mht", ".mhtml", ".html", ".htm"):
        if suffix in (".mht", ".mhtml"):
            text = decode_quoted_printable(strip_mime_envelope(text))
        text = strip_html(text)

    qq = parse_qq_txt(path, text)
    # 只有确实解析出说话人，才认为这是 QQ 导出格式；否则说明是别的排版
    if len(qq) >= 5 and any(m.speaker != "未知" for m in qq):
        return picked("QQ 消息管理器导出", qq)
    if _looks_like_whatsapp(text):
        return picked("WhatsApp 导出", parse_whatsapp_txt(text))
    return picked("通用「昵称: 内容」文本", parse_generic_txt(text))


# ----------------------------------------------------------------------------
# 二、统计画像（不花钱的那一半）
# ----------------------------------------------------------------------------
