#!/usr/bin/env python3
"""xpskill 的本地 web 前端。

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
import re
import shutil
import socket
import sys
import tempfile
import threading
import uuid
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from . import cli
from .parsers import diagnose, load_messages

__all__ = ["main"]

STATIC_DIR = Path(__file__).resolve().parent / "webui"

#: 一次会话一个临时根目录；进程退出时清掉。只放上传的原始聊天记录
SESSION_DIR = Path(tempfile.mkdtemp(prefix="xpskill-web-"))

#: 打包结果写到「启动 web 服务的当前目录/out」，不进临时目录，方便直接取走 zip
OUT_ROOT = Path.cwd() / "out"

_LOCK = threading.Lock()
_UPLOADS: dict[str, Path] = {}
_JOBS: dict[str, "Job"] = {}

#: 前端允许提交的字段 -> 命令行参数
_PASSTHROUGH = (
    ("me", "--me"), ("target", "--target"), ("display", "--display"), ("desc", "--desc"),
    ("relation", "--relation"), ("model", "--model"), ("base_url", "--base-url"),
    ("api_key", "--api-key"), ("device", "--device"),
)
_SWITCHES = (("no_llm", "--no-llm"), ("strict", "--strict"), ("no_verify", "--no-verify"))


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
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            job.code = cli.main(job.argv)
    except Exception as exc:  # 兜底：任何异常都要落到日志里，不能静默
        job.write(f"\n[web] 执行异常：{type(exc).__name__}: {exc}\n")
        job.code = 1
    finally:
        job.state = "done" if job.code == 0 else "failed"


class _Handler(BaseHTTPRequestHandler):
    server_version = "xpskill-web"
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
            return json.loads(self._body().decode("utf-8"))
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
        if route.startswith("/static/"):
            target = (STATIC_DIR / route[len("/static/"):]).resolve()
            if STATIC_DIR not in target.parents:
                return self._json({"error": "路径不合法"}, 403)
            return self._file(target)
        if route.startswith("/api/job/"):
            job = _JOBS.get(route.rsplit("/", 1)[-1])
            return self._json(job.snapshot() if job else {"error": "任务不存在"}, 200 if job else 404)
        if route.startswith("/api/result/"):
            job = _JOBS.get(route.rsplit("/", 1)[-1])
            return self._json(job.artifacts() if job else {"error": "任务不存在"}, 200 if job else 404)
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
        if parsed.path == "/api/parse":
            return self._parse(parsed)
        if parsed.path == "/api/run":
            return self._run()
        return self._json({"error": "没有这个接口"}, 404)

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
        prog="xpskill-web",
        description="xpskill 的本地 web 前端（只绑定本机，聊天记录不出网）",
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
    url = f"http://{args.host}:{args.port}/"
    print(f"xpskill web 已启动：{url}")
    print(f"  输出目录：{OUT_ROOT}（打包好的 zip 会落在这里）")
    print(f"  临时目录：{SESSION_DIR}（只放上传的聊天记录，退出即删）")
    print("  只监听本机；聊天记录与 API Key 都不会离开这台机器。Ctrl+C 结束。")
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
