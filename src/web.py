#!/usr/bin/env python3
"""kith-skill 的本地 web 前端。

它存在的理由是把 CLI 里**看不见的部分**搬上台面：

- 解析诊断：这份文件到底被哪个解析器接走了、解出几条、谁在说话。
  CLI 只会在失败时印一句"没解析出任何消息"。
- 蒸馏过程：实时日志，而不是跑完才一次性吐出来。
- 校验依据：每条结论的出处与"最相近的原话"。

实现上刻意保持克制：
- 只用标准库（``http.server``），不给项目引入任何运行依赖；
- 默认只绑定 ``127.0.0.1``，聊天记录不出本机；
- 流水线直接调用 :func:`cli.main` 并捕获输出，**不复制一行业务逻辑**。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import mimetypes
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import (cli, storage, versions, scenarios, evaluation, feedback, privacy_review,
               specificity, coverage, message_index, questions, incremental, ab)
from .conversations import reply_exchanges, select_exchanges
from .llm import CHAT_TEMPERATURE, llm_call, llm_chat
from .models import Msg
from .parsers import diagnose, load_messages

__all__ = ["main"]

STATIC_DIR = Path(__file__).resolve().parent / "webui"

#: 一次会话一个临时根目录；进程退出时清掉。只放上传的原始聊天记录
SESSION_DIR = Path(tempfile.mkdtemp(prefix="kith-skill-web-"))

#: 打包结果写到「启动 web 服务的当前目录/out」，不进临时目录，方便直接取走 zip
OUT_ROOT = Path.cwd() / "out"

_LOCK = threading.Lock()
_RUN_LOCK = threading.Lock()
_UPLOADS: dict[str, Path] = {}
_JOBS: dict[str, "Job"] = {}

#: 前端允许提交的字段 -> 命令行参数
_PASSTHROUGH = (
    ("me", "--me"), ("target", "--target"), ("display", "--display"), ("desc", "--desc"),
    ("relation", "--relation"), ("model", "--model"), ("base_url", "--base-url"),
    ("api_key", "--api-key"), ("device", "--device"), ("audience", "--audience"),
)
_SWITCHES = (("no_llm", "--no-llm"), ("strict", "--strict"), ("no_verify", "--no-verify"),
             ("both", "--both"))


class Job:
    """一次蒸馏运行。日志按写入顺序累积，前端轮询取走。"""

    def __init__(self, job_id: str, argv: list[str], out_dir: Path, name: str):
        self.id = job_id
        self.argv = argv
        self.out_dir = out_dir
        self.name = name
        self.log: list[str] = []
        self.state = "queued"          # queued | running | done | failed
        self.code: int | None = None

    def write(self, text: str) -> None:
        if not text:
            return
        with _LOCK:
            self.log.append(text)
            # 只留最近的 200k 字符，避免长跑把内存撑爆
            if sum(len(x) for x in self.log) > 200_000:
                self.log = self.log[-200:]

    def text(self) -> str:
        with _LOCK:
            return "".join(self.log)

    def snapshot(self) -> dict:
        return {"id": self.id, "state": self.state, "code": self.code,
                "log": self.text(), "name": self.name}

    def artifacts(self) -> dict:
        """产出文件的内容，供前端预览。"""
        skill = self.out_dir / self.name / "SKILL.md"
        memory = self.out_dir / self.name / "references" / "memory.md"
        zip_path = self.out_dir / f"{self.name}.zip"
        return {
            "skill": skill.read_text(encoding="utf-8") if skill.exists() else "",
            "memory": memory.read_text(encoding="utf-8") if memory.exists() else "",
            "verify": _slice_verify(self.text()),
            "has_zip": zip_path.exists(),
            "zip_name": zip_path.name if zip_path.exists() else "",
            "zip_size": zip_path.stat().st_size if zip_path.exists() else 0,
        }


class _Writer(io.TextIOBase):
    """把 print 的输出直接接进 job 日志。"""

    def __init__(self, job: Job):
        self.job = job

    def write(self, text: str) -> int:
        self.job.write(text)
        return len(text)

    def flush(self) -> None:
        return None


_VERIFY_START = re.compile(r"^\[5/6\]", re.MULTILINE)
_VERIFY_END = re.compile(r"^\[6/6\]", re.MULTILINE)


def _slice_verify(log: str) -> str:
    """从日志里切出校验那一段，单独给前端渲染。"""
    start = _VERIFY_START.search(log)
    if not start:
        return ""
    rest = log[start.end():]
    end = _VERIFY_END.search(rest)
    body = rest[:end.start()] if end else rest
    return body.strip("\n")


def _safe_name(raw: str) -> str:
    """上传文件名只用来展示和猜后缀，不能带路径。"""
    name = Path(unquote(raw or "chat.txt")).name
    return re.sub(r"[^\w.\-\u4e00-\u9fa5]+", "_", name)[:80] or "chat.txt"


#: 试聊页在本次运行没带接口配置时用的兜底值，与 cli.py 的默认值保持一致
DEFAULT_BASE_URL = "https://api-inference.modelscope.cn/v1"
DEFAULT_MODEL = "Qwen/Qwen3-235B-A22B"

#: 试聊用的收尾指令。人设文件是写给"设备上的 skill 系统"看的：带编号依据、
#: 一长串参考文献、写给人读的统计口径，甚至有一句"先用 skill_search 检索"。
#: 整份照读，模型就会用报告的腔调说话——那正是试聊里最败兴的东西。
#: 这里把它拉回来：你就是这个人，此刻在微信上跟老朋友说话。
PLAY_HINT = """【现在是本地试聊：你就是 {name}，正在微信上跟老朋友聊天】

照下面这些说话，别把它们当资料复述：

- 句长、标点和连发方式按此人的技能与原话来；需要分几条时用换行，不统一压成短句。
- 先判断当前话题的情境与情绪，再参考「情境与接法」和「接话方式」；单次示范只用于相似语境。
- 学回应动作和措辞，不照搬旧事实、地点或承诺；认真难过时不要机械套用嬉闹顶嘴。
- 亲疏按「温度与分寸」那一档来：别比 TA 在记录里更黏、更客气、更会哄，也别更冷。
- 别解释、别总结、别列条目、别写 markdown，也别问"还需要我做什么"这种话。
- 不必每句都反问。他随口说说，你随口接一句；冷场也没关系。
- 聊到共同经历时用下面记忆里的细节（人名、地点、梗）；记不清就说不知道或含糊带过，别编。
- 不要提"记录、统计、依据、人设、AI"这些词，也别说明自己在扮演谁。
"""

#: 试聊里塞进来的对话轮数上限：留给模型的历史越多，越容易跑偏且越贵。
PLAY_TURNS = 20

#: 试聊时塞几段真实对话当"怎么接话"的示范
PLAY_EXAMPLES = 5
#: 示范里"对方说的"和"你说的"各自最长多少字：太长的交换不代表日常语感
_EX_MAX = (28, 26)
#: 命中这些标记的交换直接跳过：媒体占位读起来是乱码，脱敏标签容易被断章取义
_EX_BAD = re.compile(r"\[(?:图片|视频|语音|文件|链接|表情|通话|引用|微信转账|红包|位置|名片|"
                     r"手机号|身份证|银行卡|邮箱|地址)\]")
#: 原记录逐行形如 `2024-02-04 19:15 黄泉清：云台是什么`
_EX_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}|（无时间）)\s+(.+?)[:：](.*)$")
#: 回复/引用类的前缀标记：`[回复消息]什么？` 这种，标记剥掉、正文留下
_EX_STRIP = re.compile(r"^(?:\[(?:回复消息|引用|拍一拍|知识增加)\])+")
#: 各种 `[…]` 标记（表情、媒体、引用），用来量"除去标记还剩多少真话"
_EX_TAG = re.compile(r"\[[^\]]*\]")

#: 报告里"写给人看"的章节，陪聊时要去掉——读者不该是模型
_DROP_SECTIONS = ("参考文献", "记忆检索提示", "数据统计")
#: 提到这些词的行也去掉：skill_search 是设备上才有的工具，试聊里它只会把模型带偏
_DROP_LINE = re.compile(r"skill_search|skill_read|--desc|--no-redact")

#: 示范对话的缓存：键是（transcript 目录, 目录里最新 mtime）→（示范文本, 段数）。
#: 每开一次试聊页都要算一遍，二十几份 transcript 读起来不便宜，而它们几乎不变。
_EXAMPLE_CACHE: dict[tuple, tuple[str, int]] = {}


class PlayTarget:
    """试聊对象：产物目录 + 名字 +（可选）上次运行留下的接口默认值。

    以前试聊只认内存里的 `Job`，工作台一重启就得重新跑一次蒸馏——可产物明明还
    躺在 `out/<技能名>/` 里。这里把"试聊要的那几样"抽出来，磁盘上的历史 skill
    也能当人设。argv 直接摆成命令行的形状，好让 `_argv_value` / `_play_info`
    跟 `Job` 共用一套代码。
    """

    def __init__(self, out_dir: Path, name: str,
                 base_url: str = "", model: str = "", api_key: str = "") -> None:
        self.out_dir = Path(out_dir)
        self.name = name
        self.argv: list[str] = []
        for flag, value in (("--base-url", base_url), ("--model", model), ("--api-key", api_key)):
            if value:
                self.argv += [flag, value]


def _skill_root(name: str) -> Path | None:
    """`out/<名字>/` 且真的有 SKILL.md 才算一份 skill。

    只认 out 的直接子目录：`Path(...).name` 先削掉任何路径成分，再校验父目录，
    免得 `?skill=../../etc` 这种把服务端读文件的接口带出目录。
    """
    clean = str(name or '').strip()
    if not re.fullmatch(r'[\w.\-]+', clean) or clean.lower() in ('.', '..', '.kith'):
        return None
    root = (OUT_ROOT / clean).resolve()
    if root.parent != OUT_ROOT.resolve() or not (root / "SKILL.md").is_file():
        return None
    return root


def _skill_list() -> list[dict]:
    """磁盘上之前生成过的 skill，新的排前面。

    "导入之前的 skill" 靠的就是它：产物本来就落在 `out/` 下（不随进程消失），
    这里只是把有 SKILL.md 的那些列出来。
    """
    if not OUT_ROOT.is_dir():
        return []
    items = []
    for child in OUT_ROOT.iterdir():
        if child.name.startswith('.') or not _skill_root(child.name):
            continue
        target = PlayTarget(OUT_ROOT, child.name)
        files = _persona_files(target)
        items.append({
            "name": child.name,
            "title": _persona_title(target),
            "files": len(files),
            "chars": sum(p.stat().st_size for p in files),
            "mtime": int(child.stat().st_mtime),
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def _argv_value(target: Job | PlayTarget, flag: str) -> str:
    """从这次运行的命令行里取一个参数值（试聊复用它，省得再填一遍）。"""
    argv = target.argv
    if flag in argv and argv.index(flag) + 1 < len(argv):
        return argv[argv.index(flag) + 1]
    return ""


def _persona_files(target: Job | PlayTarget) -> list[Path]:
    """这次运行的产物文件，按喂给模型的顺序。"""
    root = target.out_dir / target.name
    files = [root / "SKILL.md", root / "references" / "memory.md"]
    for extra in ("self.md", "other.md"):
        path = root / "references" / extra
        if path.exists():
            files.append(path)
    return [p for p in files if p.exists()]


def _rows(text: str) -> list[Msg]:
    """保留时间戳，试聊示范与蒸馏使用相同的会话边界。"""
    rows = []
    for line in text.splitlines():
        match = _EX_LINE.match(line.strip())
        if match:
            said = _EX_STRIP.sub("", match.group(3)).strip()
            try:
                ts = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M")
            except ValueError:
                ts = None
            rows.append(Msg(ts, match.group(2).strip(), said))
    return rows


def _persona_name(target: Job | PlayTarget) -> str:
    """人设在原记录里叫什么。

    优先读带路文件中的主身份，避免公开版错误取到 --target 的对方身份；
    无带路文件时再取命令行，最后交给调用方按出现次数猜。
    """
    readme = target.out_dir / target.name / "references" / "README.md"
    if readme.exists():
        match = re.search(r"^#\s*参考资料[（(]([^）)]+)[）)]", readme.read_text(encoding="utf-8"),
                          re.M)
        if match:
            return match.group(1).strip()
    if _argv_value(target, "--audience") == "公开":
        return _argv_value(target, "--me").split(",")[0].strip()
    return _argv_value(target, "--target").strip()


def _sides(rows: list[Msg], speaker: str) -> tuple[str, str]:
    """认出原记录里的两侧：TA 的名字，以及"对方"的名字。

    对方的自称**不固定**：这次运行给了 --me 就是那个名字（老菜叶），没给才是「我」。
    所以不能写死，按出现次数认人——除系统消息外，除 TA 外出现最多的那个。
    """
    names = Counter(m.speaker for m in rows if m.speaker != "系统消息" and m.speaker != speaker)
    if not speaker:
        names = Counter(m.speaker for m in rows if m.speaker != "系统消息")
        speaker = names.most_common(1)[0][0] if names else ""
        names = Counter(m.speaker for m in rows if m.speaker != "系统消息" and m.speaker != speaker)
    return speaker, (names.most_common(1)[0][0] if names else "")


def _exchanges(rows: list[Msg], speaker: str,
               other: str) -> list[tuple[list[str], list[str]]]:
    """把原记录切成「对方连着说几句 → TA 连着回几句」。

    连着发的几条合成一段（而不是逐条配一对），因为"他喜欢把一件事拆成几条说"
    本身就是这个人的习惯，示范里要看得见。
    """
    return [(e.incoming, e.reply) for e in reply_exchanges(rows, speaker, other)]


def _example_ok(pair: tuple[list[str], list[str]]) -> bool:
    """这段交换能不能当示范：要短、要干净、要说的是人话。

    - "对方"那句不能太短：`不是``啊？`这类是从上一句截下来的半截话，
      拿来当示范只会教出没头没尾的接话；太长也不行（长句多是聊正事，不代表日常语气）。
    - 两侧都得有**实打实的内容**：`[晕]`、`[强]` 这种只剩表情标记的，
      教不会任何说话方式（统计标记不算内容，所以先把 `[…]` 剥掉再量）。
    """
    mine, theirs = pair
    if not mine or not theirs or len(theirs) > 3:
        return False
    mine_text, theirs_text = "\n".join(mine), "\n".join(theirs)
    if _EX_BAD.search(mine_text) or _EX_BAD.search(theirs_text):
        return False
    if len(_EX_TAG.sub("", mine_text).strip()) < 3:
        return False
    if len(_EX_TAG.sub("", theirs_text).strip()) < 2:
        return False
    return (4 <= len(mine_text) <= _EX_MAX[0] and len(theirs_text) <= _EX_MAX[1]
            and all(x.strip() for x in theirs))


def _spread(items: list, n: int) -> list:
    """等距取 n 个：跨月份、跨时段取样，别只看某一段时间的语气。"""
    if n < 1 or not items:
        return []
    if len(items) <= n:
        return list(items)
    step = (len(items) - 1) / (n - 1) if n > 1 else 0
    return [items[round(i * step)] for i in range(n)]


def _play_examples(target: Job | PlayTarget) -> tuple[str, int]:
    """挑几段真实对话，当"TA 平时怎么接话"的示范。返回（示范文本, 段数）。

    人设文件给的是结论（"中位 4 字""爱拆成几条发"），可"短到什么程度、梗怎么接"
    只有原记录看得出来；而满篇统计口径读下来，模型很容易答成一份分析报告。

    示范只写进 system，不当成真正的对话轮次——否则五段示范摆在那，
    模型很可能接着最后一段聊，而不是接眼前这句话。
    """
    folder = target.out_dir / target.name / "references" / "transcript"
    if not folder.is_dir():
        return "", 0
    paths = sorted(folder.glob("*.md"))
    if not paths:
        return "", 0
    try:
        key = (str(folder), tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths),
               _persona_name(target))
    except OSError:
        return "", 0
    with _LOCK:
        cached = _EXAMPLE_CACHE.get(key)
    if cached is not None:
        return cached

    speaker = _persona_name(target)
    valid = []
    session_offset = 0
    for path in _spread(paths, 3):
        try:
            rows = _rows(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        speaker, other = _sides(rows, speaker)
        if speaker and other:
            examples = reply_exchanges(rows, speaker, other)
            for example in examples:
                example.session += session_offset
            valid += [e for e in examples if _example_ok((e.incoming, e.reply))]
            session_offset = max((e.session for e in examples), default=session_offset - 1) + 1

    picks = select_exchanges(valid, PLAY_EXAMPLES)
    if not picks:
        return "", 0
    lines = ["【你平时就这么说话（原记录节选，只学腔调，不要接着它们聊）】", ""]
    for exchange in picks:
        mine, theirs = exchange.incoming, exchange.reply
        lines += [f"对方：{x}" for x in mine]
        lines += [f"我：{x}" for x in theirs]        # 模型视角：我＝人物本人
        lines.append("")
    block = "\n".join(lines).rstrip()
    with _LOCK:
        if len(_EXAMPLE_CACHE) > 32:
            _EXAMPLE_CACHE.clear()
        _EXAMPLE_CACHE[key] = (block, len(picks))
    return block, len(picks)


def _strip_report_noise(text: str) -> str:
    """滤掉人设文档里的"报告气"。

    SKILL.md / memory.md 是给人看的蒸馏报告：45 条参考文献、一句"先用 skill_search
    检索"、几行 0%/92% 的统计口径、以及开头那句来历说明。这些对陪聊没用处，
    留着只会让模型照着报告的腔调说话。其余（说话风格、口头禅、典型例句、记忆）全部保留。
    """
    out: list[str] = []
    skip = front = False
    for i, line in enumerate(text.splitlines()):
        stripped = line.strip()
        if i == 0 and stripped == "---":          # 开头的 YAML front matter
            front = True
            continue
        if front:
            front = stripped != "---"
            continue
        if stripped.startswith("## "):
            skip = any(stripped[3:].startswith(name) for name in _DROP_SECTIONS)
            if skip:
                continue
        if skip or stripped.startswith(">"):      # 「> LLM 蒸馏 + ……」这类来历说明
            continue
        if _DROP_LINE.search(line):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _persona_prompt(target: Job | PlayTarget, text: str = "") -> str:
    """把产物拼成陪聊用的那段 system。

    试聊不做检索：整套塞进去（本地测试，几 KB）比模拟 skill_search 更接近"人设完整"。
    顺序是「怎么说话 → 平时怎么接话（真实节选）→ 这次的规矩」——示范贴着指令放，
    离"该你开口了"最近，模型才更可能照着那个腔调接。
    """
    blocks = []
    for path in _persona_files(target):
        cleaned = _strip_report_noise(path.read_text(encoding="utf-8"))
        if cleaned:
            blocks.append(cleaned)
    examples, _ = _play_examples(target)
    if examples:
        blocks.append(examples)
    root = target.out_dir / target.name
    routes = _routes(root)
    current = scenarios.prompt(text, routes)
    if current:
        blocks.append(current)
    corrections = feedback.render_rules(feedback.read(root), routes, text=text)
    if corrections:
        blocks.append(corrections)
    review_prompt = questions.prompt(root)
    if review_prompt:
        blocks.append(review_prompt)
    blocks.append('记忆里的日期只表示当时提及。历史计划与旧承诺的当前有效性需要确认；不推断已经兑现，也不重新许诺。')
    blocks.append(PLAY_HINT.format(name=_persona_title(target)))
    return "\n\n---\n\n".join(blocks)


def _persona_title(target: Job | PlayTarget) -> str:
    """从 SKILL.md 的一级标题取个人话的名字，给页面当标签用。

    标题长这样：`# HQQ · 人设（Part B）`——`·` 后面是给文档看的内部说明，
    摆到界面上就是噪音（"正在跟 HQQ · 人设（Part B）对话"）。只取前半段。
    """
    skill = target.out_dir / target.name / "SKILL.md"
    if skill.exists():
        for line in skill.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                return line[2:].split("·")[0].strip() or target.name
    return target.name


def _play_info(target: Job | PlayTarget) -> dict:
    """试聊页开局要的东西：对话谁、用的哪几个文件、接口配置填什么。"""
    files = _persona_files(target)
    root = target.out_dir / target.name
    return {
        "title": _persona_title(target),
        "name": target.name,
        "files": [p.relative_to(root).as_posix() for p in files],
        "chars": sum(p.stat().st_size for p in files),
        "examples": _play_examples(target)[1],
        # 页面开局要显示当前温度（可能就是环境变量定的那个值，不一定是默认档）
        "temperature": _chat_temperature({}),
        "base_url": _argv_value(target, "--base-url") or DEFAULT_BASE_URL,
        "model": _argv_value(target, "--model") or DEFAULT_MODEL,
        "has_key": bool(_argv_value(target, "--api-key")),
        "offline": "--no-llm" in target.argv,
        **versions.state(root),
    }


#: 试聊温度的边界。上限 2.0 是：再往上不是"更活"，而是输出不成句的东西。
CHAT_TEMP_MAX = 2.0


def _chat_temperature(payload: dict) -> float:
    """试聊用多热：页面给的优先，其次环境变量 LLM_CHAT_TEMPERATURE，最后是默认值。

    做成可调是因为它是**口味**而不是正确性：同一个模型，0.7 像在回工作邮件、
    1.3 才像半夜在群里说话。让用户每试一档就改一次代码重启一次，等于不让他调。
    非法值（非数字、负数）忽略，超上限截到 2.0——总比把接口参数塞崩好。
    """
    for raw in (payload.get("temperature"), os.environ.get("LLM_CHAT_TEMPERATURE")):
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if value < 0:
            continue
        return min(value, CHAT_TEMP_MAX)
    return CHAT_TEMPERATURE


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (0x3000 <= code <= 0x30FF          # 中日标点 / 假名
            or 0x4E00 <= code <= 0x9FFF       # 汉字
            or 0xFF00 <= code <= 0xFFEF)      # 全角


def _unwrap_hard_breaks(text: str) -> str:
    """收拾"一句一行"的回复。

    模型很喜欢每句话自己占一行（有时每行只有两个字），直接塞进气泡就是
    `white-space: pre-wrap` 下的一竖排短行——一屏全是换行，读起来像电报。
    但**两三行**短句正好是微信连发的样子（也是这个人物的习惯），要留下；
    只有行数更多时才把它们接成完整句子（中日文之间不留空格，避免多出空隙）。
    """
    lines = [ln.strip() for ln in text.replace("\r\n", "\n").strip().split("\n")]
    lines = [ln for ln in lines if ln]
    if 1 < len(lines) <= 3:
        return "\n".join(lines)

    def join_block(block: str) -> str:
        joined = ""
        for line in (ln.strip() for ln in block.split("\n")):
            if not line:
                continue
            if joined and not (_is_cjk(joined[-1]) or _is_cjk(line[0])):
                joined += " "
            joined += line
        return joined

    blocks = re.split(r"\n\s*\n", "\n".join(lines))
    return "\n".join(b for b in (join_block(block) for block in blocks) if b)


def _history_turns(messages: list) -> list[dict]:
    """前端传来的对话 → 真正的多轮消息。

    以前这里把整段历史压成一条 user 消息（"我：…\\nTA：…"），模型收到的是
    "一份要接着写的记录"，于是答得像在续写文档；拆成 user/assistant 轮次，
    它才会按对话的本能接话。
    """
    turns = []
    for item in messages[-PLAY_TURNS:]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("content") or "").strip()
        if text:
            turns.append({"role": "assistant" if item.get("role") == "assistant" else "user",
                          "content": text})
    while turns and turns[-1]["role"] != "user":   # 必须以对方的话收尾，模型才有得接
        turns.pop()
    return turns


def _build_argv(payload: dict, input_path: Path, out_dir: Path) -> list[str]:
    name = (payload.get("name") or "persona").strip() or "persona"
    argv = ["--input", str(input_path), "--name", name, "--out", str(out_dir)]
    for key, flag in _PASSTHROUGH:
        value = str(payload.get(key) or "").strip()
        if value:
            argv += [flag, value]
    for key, flag in _SWITCHES:
        if payload.get(key):
            argv.append(flag)
    return argv


def _run_job(job: Job) -> None:
    job.state = "running"
    writer = _Writer(job)
    try:
        with _RUN_LOCK, contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            job.code = cli.main(job.argv)
    except Exception as exc:  # 兜底：任何异常都要落到日志里，不能静默
        job.write(f"\n[web] 执行异常：{type(exc).__name__}: {exc}\n")
        job.code = 1
    finally:
        job.state = "done" if job.code == 0 else "failed"


def _routes(root: Path) -> list[dict]:
    return (storage.load(root / 'references/scenarios.json', {}) or {}).get('scenarios', [])


def _reply(target: Job | PlayTarget, payload: dict, messages: list) -> dict:
    """One model call shared by trial chat and explicit regression runs."""
    turns = _history_turns(messages)
    if not turns:
        raise ValueError('没有收到对话内容')
    api_key = str(payload.get('api_key') or '').strip() or _argv_value(target, '--api-key')
    if not api_key:
        raise ValueError('请填写 API Key 后再调用模型')
    root = target.out_dir / target.name
    with storage.lock(root):
        state = versions.state(root)
        system = _persona_prompt(target, turns[-1]['content'])
        matched = scenarios.route(turns[-1]['content'], _routes(root)) or {}
    started = time.monotonic()
    if payload.get('recipe'):
        system += '\n\n【本次对比配方】\n' + str(payload['recipe'])[:4000]
    reply = llm_chat(str(payload.get('base_url') or '').strip() or _argv_value(target, '--base-url') or DEFAULT_BASE_URL,
                     api_key, str(payload.get('model') or '').strip() or _argv_value(target, '--model') or DEFAULT_MODEL,
                     system, turns, temperature=_chat_temperature(payload))
    reply = re.sub(r'^\s*(?:TA|对方|你|我)\s*[:：]\s*', '', reply.strip())
    return {'reply': _unwrap_hard_breaks(reply), 'seconds': round(time.monotonic() - started, 1),
            'skill': root.name, 'scenario_id': matched.get('id', ''), **state}


class _Handler(BaseHTTPRequestHandler):
    server_version = "kith-skill-web"
    protocol_version = "HTTP/1.1"

    # ---------------------------------------------------------------- 工具
    def log_message(self, fmt, *args):  # 关掉逐请求日志，保持终端干净
        return

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # 前端在开发期会频繁改，默认不缓存；字体例外（见 _file），
        # 否则每次刷新都要重下几 MB。
        self.send_header("Cache-Control", self.cache_control)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    cache_control = "no-store"

    def _json(self, payload, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _file(self, path: Path, ctype: str | None = None) -> None:
        if not path.is_file():
            return self._json({"error": f"找不到 {path.name}"}, 404)
        ctype = ctype or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith(("javascript", "json")):
            ctype += "; charset=utf-8"
        previous, self.cache_control = self.cache_control, (
            "public, max-age=86400" if ctype.startswith("font/") else "no-store")
        try:
            self._send(200, path.read_bytes(), ctype)
        finally:
            self.cache_control = previous

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _payload(self) -> dict:
        try:
            value = json.loads(self._body().decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}

    # ---------------------------------------------------------------- GET
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 的约定
        # 先解码再找文件：浏览器会把非 ASCII 文件名发成 %E8%8A%AF…，
        # 不解码就会去磁盘上找一个名叫 "%E8%8A%AF%E6%B4%BE.png" 的文件，必然 404。
        # 解码后的路径仍要过下面那条 STATIC_DIR 目录校验，跳不出去。
        route = unquote(urlparse(self.path).path)
        if route in ("/", "/index.html"):
            return self._file(STATIC_DIR / "index.html")
        if route in ("/play", "/play.html"):
            return self._file(STATIC_DIR / "play.html")
        if route.startswith("/static/"):
            target = (STATIC_DIR / route[len("/static/"):]).resolve()
            if STATIC_DIR not in target.parents:
                return self._json({"error": "路径不合法"}, 403)
            return self._file(target)
        if route.startswith('/api/workbench/'):
            return self._workbench(route)
        if route.startswith("/api/job/"):
            job = _JOBS.get(route.rsplit("/", 1)[-1])
            return self._json(job.snapshot() if job else {"error": "任务不存在"}, 200 if job else 404)
        if route.startswith("/api/result/"):
            job = _JOBS.get(route.rsplit("/", 1)[-1])
            return self._json(job.artifacts() if job else {"error": "任务不存在"}, 200 if job else 404)
        if route == "/api/skills":
            return self._json({"skills": _skill_list()})
        if route.startswith("/api/play-skill/"):
            # 磁盘上的历史产物：工作台重启过、或想聊另一个人设时走这条
            root = _skill_root(route[len("/api/play-skill/"):])
            if not root:
                return self._json({"error": "out/ 下没有这个 skill（得有一份 SKILL.md）"}, 404)
            return self._json(_play_info(PlayTarget(OUT_ROOT, root.name)))
        if route.startswith("/api/play/"):
            job = _JOBS.get(route.rsplit("/", 1)[-1])
            if not job:
                return self._json({"error": "找不到这次运行——试聊要跟它在同一个工作台进程里，"
                                            "服务重启过就重新跑一次蒸馏"}, 404)
            return self._json(_play_info(job))
        if route.startswith("/api/zip/"):
            job = _JOBS.get(route.rsplit("/", 1)[-1])
            if not job:
                return self._json({"error": "任务不存在"}, 404)
            zip_path = job.out_dir / f"{job.name}.zip"
            if not zip_path.exists():
                return self._json({"error": "还没有产物"}, 404)
            name = quote(zip_path.name)
            return self._send(200, zip_path.read_bytes(), "application/zip",
                              {"Content-Disposition": f"attachment; filename*=UTF-8''{name}"})
        return self._json({"error": "没有这个接口"}, 404)

    # ---------------------------------------------------------------- POST
    def do_POST(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith('/api/workbench/'):
            return self._workbench(unquote(parsed.path), post=True)
        if parsed.path == "/api/parse":
            return self._parse(parsed)
        if parsed.path == "/api/run":
            return self._run()
        if parsed.path == "/api/chat":
            return self._chat()
        return self._json({"error": "没有这个接口"}, 404)

    def _workbench(self, route: str, post: bool = False) -> None:
        parts = route[len('/api/workbench/'):].split('/')
        if len(parts) != 2:
            return self._json({'error': '路径不合法'}, 400)
        name, action = parts
        root = _skill_root(name)
        if not root:
            return self._json({'error': '找不到这份技能'}, 404)
        payload = self._payload() if post else {}
        try:
            if post and action == 'evaluate-model':
                case = next((c for c in evaluation.cases_for(root, _routes(root)) if c['id'] == payload.get('case')), None)
                if not case:
                    raise ValueError('用例不存在')
                if payload.get('fingerprint') != versions.fingerprint(root):
                    raise ValueError('技能内容已变化，请刷新后重新测评')
                job = next((j for j in reversed(list(_JOBS.values())) if j.name == name and j.state == 'done'), None)
                result = _reply(job or PlayTarget(OUT_ROOT, name), payload, [{'role': 'user', 'content': case['prompt']}])
                # A concurrent edit must not attribute an old response to new content.
                if result['fingerprint'] != payload.get('fingerprint'):
                    raise ValueError('技能内容已变化，请重新测评')
                report = evaluation.save(root, {case['id']: result['reply']}, _routes(root), result['fingerprint'])
                return self._json({'case': case['id'], **result, 'report': report})
            if post and action == 'incremental':
                if payload.get('token'):
                    uploaded = _UPLOADS.get(str(payload['token']))
                    if not uploaded or not uploaded.is_file():
                        raise ValueError('上传已失效，请重新选择增量记录')
                    incoming = load_messages(uploaded)
                else:
                    incoming = incremental.to_messages(payload.get('messages', []))
                if not incoming:
                    raise ValueError('增量记录为空，请选择文件或填写消息数组')
                mode = payload.get('mode', 'preview')
                if mode == 'apply':
                    return self._json(incremental.apply(root, incoming, payload))
                if mode != 'preview':
                    raise ValueError('增量操作只支持预览或合并')
                with storage.lock(root):
                    return self._json(incremental.preview(root, incoming, str(payload.get('fingerprint') or '')))
            if post and action == 'ab' and payload.get('mode') == 'run':
                with storage.lock(root):
                    run, case, config = ab.prepare(root, payload)
                api_payload = {**payload, **config}
                if not str(api_payload.get('api_key') or '').strip():
                    raise ValueError('A/B 运行需要填写 API Key；只保存在本次请求内')
                result = _reply(PlayTarget(OUT_ROOT, name), api_payload,
                                [{'role': 'user', 'content': case['prompt']}])
                return self._json(ab.save(root, payload, result, _routes(root)))
            with storage.lock(root):
                if not post and action == 'package':
                    return self._json(Job('', [], root.parent, name).artifacts())
                if not post and action == 'download':
                    archive = root.parent / (name + '.zip')
                    if not archive.is_file():
                        return self._json({'error': '技能包不存在，请重新生成'}, 404)
                    return self._send(200, archive.read_bytes(), 'application/zip',
                                      {'Content-Disposition': "attachment; filename*=UTF-8''" + quote(archive.name)})
                if not post and action == 'scenarios':
                    return self._json({'scenarios': _routes(root)})
                if not post and action == 'specificity':
                    return self._json(storage.load(root / 'references/specificity.json', {'items': [], 'traits': [], 'summary': {}}))
                if not post and action == 'coverage':
                    return self._json(storage.load(root / 'references/coverage.json', {'matrix': [], 'summary': {}}))
                if not post and action == 'messages':
                    return self._json(storage.load(root / 'references/message-index.json', {'messages': []}))
                if not post and action == 'memory':
                    return self._json(storage.load(root / 'references/memory-ledger.json', {'memories': []}))
                if action == 'questions':
                    if post:
                        return self._json(questions.answer(root, payload))
                    return self._json(questions.view(root))
                if action == 'incremental':
                    report = storage.load(storage.local_dir(root) / 'incremental-report.json', {})
                    try:
                        info, _ = incremental.baseline(root)
                        error = ''
                    except ValueError as exc:
                        info, error = {}, str(exc)
                    return self._json({**info, 'last_report': report, 'available': not error,
                                       'error': error, **versions.state(root)})
                if action == 'ab':
                    if not post:
                        return self._json(ab.view(root))
                    mode = payload.get('mode', 'start')
                    routes = _routes(root)
                    if mode == 'start':
                        return self._json(ab.start(root, payload, routes))
                    if mode == 'choose':
                        return self._json(ab.choose(root, payload))
                    raise ValueError('A/B 操作不支持')
                if action == 'evaluation':
                    routes = _routes(root)
                    if post:
                        replies = payload.get('replies')
                        if not isinstance(replies, dict):
                            raise ValueError('请提交每个用例的待检查回复')
                        return self._json(evaluation.save(root, replies, routes, str(payload.get('fingerprint') or '')))
                    return self._json(evaluation.view(root, routes))
                if action == 'feedback':
                    if post:
                        if payload.get('label') not in feedback.LABELS or not payload.get('user') or not payload.get('reply'):
                            raise ValueError('请填写有效反馈类型、输入和回复')
                        feedback.add(root, user_text=str(payload['user']), reply=str(payload['reply']),
                                     label=payload['label'], note=str(payload.get('note') or ''),
                                     version=str(payload.get('version') or ''), scenario_id=str(payload.get('scenario_id') or ''))
                    return self._json(feedback.summary(root))
                if not post and action == 'versions':
                    return self._json({**versions.state(root), 'versions': versions.list_versions(root)})
                if not post and action == 'diff':
                    value = parse_qs(urlparse(self.path).query).get('version', [''])[0]
                    return self._json(versions.diff(root, value))
                if post and action == 'rollback':
                    return self._json(versions.rollback(root, str(payload.get('version') or '')))
                if post and action == 'snapshot':
                    from .package import write_package
                    files = versions.current_files(root)
                    if 'SKILL.md' not in files or 'references/memory.md' not in files:
                        raise ValueError('技能主文件不完整，不能保存')
                    extra = {key: value for key, value in files.items()
                             if key not in ('SKILL.md', 'references/memory.md')}
                    current_info = versions.current(root)
                    write_package(root.parent, name, files['SKILL.md'], files['references/memory.md'],
                                  extra=extra, metadata=current_info.get('metadata', {}), reason='手动保存')
                    return self._json(versions.state(root))
                if action == 'privacy':
                    if post:
                        if payload.get('fingerprint') != versions.fingerprint(root):
                            raise ValueError('内容已变化，请重新扫描后确认')
                        privacy_review.confirm(root, str(payload.get('item') or ''), bool(payload.get('confirmed', True)))
                    return self._json(privacy_review.with_confirmations(root, privacy_review.review(root)))
                return self._json({'error': '没有这个接口'}, 404)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            return self._json({'error': str(exc)}, 400)
        except Exception as exc:
            return self._json({'error': str(exc)}, 502)

    def _chat(self) -> None:
        """试聊：拿这次运行的产物当人设，直接问模型要一句话。

        走的是 :func:`llm.llm_call`，所以超时、SSE 抢救、报错定位这些都已经有了；
        接口配置优先用页面传来的，页面没给就用本次运行的命令行参数。
        """
        payload = self._payload()
        # 人设优先认这次运行的 job；没有就用磁盘上的 skill（工作台重启过、或想聊别的产物）
        target = _JOBS.get(str(payload.get("job") or ""))
        if not target:
            root = _skill_root(str(payload.get("skill") or ""))
            target = PlayTarget(OUT_ROOT, root.name) if root else None
        if not target:
            return self._json({"error": "找不到人设：既没有这次运行的 job，"
                                        "out/ 下也没有这个 skill"}, 404)
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            return self._json({"error": "没有收到对话内容"}, 400)

        try:
            result = _reply(target, payload, messages)
        except Exception as exc:
            return self._json({"error": str(exc)})
        return self._json(result)

    def _parse(self, parsed) -> None:
        raw_name = parse_qs(parsed.query).get("name", ["chat.txt"])[0]
        filename = _safe_name(raw_name)
        data = self._body()
        if not data:
            return self._json({"error": "没有收到文件内容"}, 400)

        token = uuid.uuid4().hex[:12]
        folder = SESSION_DIR / token
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / filename
        target.write_bytes(data)
        _UPLOADS[token] = target

        trace: list[str] = []
        try:
            msgs = load_messages(target, trace=trace)
        except Exception as exc:
            return self._json({"token": token, "file": filename, "size": len(data),
                               "total": 0, "error": f"{type(exc).__name__}: {exc}"})
        used = trace[-1] if trace else ""

        speakers = [{"name": name, "count": count}
                    for name, count in Counter(m.speaker for m in msgs).most_common()]
        stamps = sorted(m.ts for m in msgs if m.ts)
        try:
            report = diagnose(target)
        except Exception as exc:
            report = {"candidates": [], "decodable_encodings": [], "error": str(exc)[:160]}
        for candidate in report.get("candidates", []):
            candidate["used"] = candidate["parser"] == used

        return self._json({
            "token": token,
            "file": filename,
            "size": len(data),
            "parser": used,
            "total": len(msgs),
            "speakers": speakers,
            "first": stamps[0].strftime("%Y-%m-%d %H:%M") if stamps else "",
            "last": stamps[-1].strftime("%Y-%m-%d %H:%M") if stamps else "",
            "no_ts": sum(1 for m in msgs if not m.ts),
            "candidates": report.get("candidates", []),
            "encodings": report.get("decodable_encodings", []),
            "error": None,
        })

    def _run(self) -> None:
        payload = self._payload()
        token = str(payload.get("token") or "")
        uploaded = _UPLOADS.get(token)
        if not uploaded or not uploaded.exists():
            return self._json({"error": "上传已失效，请重新上传文件"}, 400)

        name = (payload.get("name") or "persona").strip() or "persona"
        name = re.sub(r"[^\w.\-]+", "_", name)[:60] or "persona"
        job_id = uuid.uuid4().hex[:12]
        out_dir = OUT_ROOT
        out_dir.mkdir(parents=True, exist_ok=True)

        job = Job(job_id, _build_argv({**payload, "name": name}, uploaded, out_dir), out_dir, name)
        _JOBS[job_id] = job
        threading.Thread(target=_run_job, args=(job,), daemon=True).start()
        return self._json({"job": job_id})


def _port_busy(host: str, port: int) -> bool:
    """端口上是不是已经有服务在回话。

    必须主动探一次：Windows 允许两个进程绑同一个端口（`http.server` 默认开着
    SO_REUSEADDR，实测第二个 `python -m src.web` 会"启动成功"），可它在抢浏览器
    连接时未必赢——用户明明重启了，页面却还在用旧代码，然后去怀疑代码本身。
    """
    with socket.socket() as probe:
        probe.settimeout(0.5)
        target = "127.0.0.1" if host in ("", "0.0.0.0") else host
        return probe.connect_ex((target, port)) == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="kith-skill-web",
        description="kith-skill 的本地 web 前端（只绑定本机，聊天记录不出网）",
    )
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认只绑本机）")
    parser.add_argument("--port", type=int, default=8765, help="端口（默认 8765）")
    parser.add_argument("--no-open", action="store_true", help="不要自动打开浏览器")
    args = parser.parse_args(argv)

    if not STATIC_DIR.is_dir():
        print(f"找不到前端文件：{STATIC_DIR}")
        return 2

    if _port_busy(args.host, args.port):
        print(f"端口 {args.port} 上已经有一个服务在运行——多半是你上次开的工作台还开着。",
              file=sys.stderr)
        print("  它手里是旧代码，浏览器继续访问这个端口就还是旧行为。"
              "先把它停掉（Ctrl+C，或按 PID 结束进程），或者换个端口："
              f"--port {args.port + 1}", file=sys.stderr)
        return 2

    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    url = f"http://{args.host}:{server.server_port}/"
    print(f"kith-skill web 已启动：{url}")
    print(f"  输出目录：{OUT_ROOT}（打包好的 zip 会落在这里）")
    print(f"  临时目录：{SESSION_DIR}（只放上传的聊天记录，退出即删）")
    print("  默认只监听本机；启用 LLM、试聊或模型测评时，会向配置的接口发送内容。Ctrl+C 结束。")
    # 这一句要显式写出来：本进程是常驻的，Python 只在启动时加载模块，
    # 改完 src/ 再刷新页面也没用——用户会看到"命令行能用、工作台不行"，
    # 然后去怀疑代码或接口，而不是怀疑这个进程。
    print("  注意：本进程启动时把 src/ 的代码读进了内存，改完代码要重启它才生效"
          "（命令行每次都是新进程，所以改动立刻可见）")
    if not args.no_open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        server.server_close()
        shutil.rmtree(SESSION_DIR, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
