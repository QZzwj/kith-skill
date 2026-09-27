import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

from .models import Stats
from .relation import relation_hint


PERSONA_PROMPT = """你在做「人格蒸馏」：从一段真实聊天记录里，还原 TA 这个人说话和行为的样子。
只输出 JSON，不要任何解释。字段要求：

{
  "说话风格": ["短句/长句、标点习惯、语气词、有没有错别字、爱不爱用表情、爱不爱发语音文字描述", "..."],
  "口头禅": ["原样引用的高频口头语或句式，最多 12 条"],
  "情感模式": ["怎么表达关心、生气、开心、失落；回避还是直球", "..."],
  "关系行为": ["主动找人吗、回消息快慢、吵架后怎么收场、纪念日/生日的做法", "..."],
  "硬规则": ["像 TA 说话时必须遵守的底线，例如『从不说肉麻的话』『不会秒回，通常隔几分钟』", "..."],
  "典型例句": ["能体现 TA 风格的原话，3-8 条，只写句子本身，不要带时间、不要带说话人"],
  "依据": ["<上面某条结论> ← <支撑它的原话>", "..."]
}

要求：所有内容都必须能从聊天记录里找到依据，不确定就不要写，不要编造。
「依据」要为「口头禅」和「典型例句」的每一条指出出处，格式是「结论 ← 原话」，
原话必须逐字摘抄并带上时间或说话人；找不到出处的条目就不要写进上面的字段。
时间与说话人只写在「依据」里，「典型例句」保持干净的一句话。
聊天记录中被标记为「{target}」的一方就是要蒸馏的对象。"""

MEMORY_PROMPT = """你在整理「关系记忆档案」：把聊天记录里的共同经历提取成结构化条目。
只输出 JSON，不要任何解释。字段要求：

{
  "关系时间线": ["YYYY-MM 或 大致时间 + 发生了什么（在一起/异地/争吵/和好等）", "..."],
  "一起去过的地方": ["地点 + 当时的细节", "..."],
  "inside_jokes": ["只有你们懂的梗，附上来历", "..."],
  "争吵模式": ["因为什么吵、怎么升级、怎么和好", "..."],
  "甜蜜瞬间": ["具体场景 + 原话片段", "..."],
  "称呼与专属用语": ["互相怎么叫、专属词汇", "..."],
  "依据": ["<上面某条结论> ← <支撑它的原话>", "..."]
}

只写聊天记录里真实出现的，不要脑补；没有的就给空数组。
「依据」要为每条结论指出出处，格式是「结论 ← 原话」，原话必须逐字摘抄并带上时间。"""


def _require_ascii(value: str, label: str) -> str:
    """URL 与 HTTP 头值只能是 ASCII；非 ASCII 时 urllib 只报难懂的 latin-1 错误。"""
    if "\n" in value or "\r" in value:
        raise RuntimeError(f"{label} 含换行符，请检查是否从文件粘贴时带了多余空白。")
    if not value.isascii():
        bad = "".join(dict.fromkeys(ch for ch in value if not ch.isascii()))
        raise RuntimeError(
            f"{label} 含非 ASCII 字符 {bad!r}；URL 和请求头只能用 ASCII 编码，"
            "请检查是否把占位符或中文误当成了 API Key / 接口地址。"
        )
    return value


def _preview(raw: str, head: int = 200, tail: int = 300) -> str:
    """报错时给头 + 尾：截断看尾巴（JSON 有没有收尾），乱码看开头。"""
    if len(raw) <= head + tail:
        return raw
    return f"{raw[:head]} …（省略 {len(raw) - head - tail} 字符）… {raw[-tail:]}"


def _limit_hint(max_tokens: int) -> str:
    """输出被截断时给出的补救建议。

    「响应体截断」和「finish_reason=length」两条报错共用它：
    以前只有后一条会提 --max-tokens，前一条（网关直接切断、连 finish_reason
    都读不到）反而只说"不是 JSON"，用户看不出该动哪个参数。
    """
    if max_tokens:
        return f"把 --max-tokens 调大（当前 {max_tokens}）"
    return "用 --max-tokens 显式给一个更大的上限（思考型模型的推理也会占用这份预算）"


def _json_fault(exc: json.JSONDecodeError, raw: str) -> str:
    """把「JSON 坏了」说到能定位：原因 + 出错位置附近的原文。

    只报「不是 JSON」时，我们和用户都只能猜——是少了引号、混进了控制字符，
    还是两块响应粘在一起。带上位置和附近原文，下一次运行自己就把原因交代清楚。
    """
    pos = min(max(exc.pos, 0), len(raw))
    window = raw[max(0, pos - 40): pos + 40].replace("\n", "\\n").replace("\r", "\\r")
    return f"JSON 解析失败：{exc.msg}（位置 {pos}，附近「…{window}…」）"


def _salvage_body(raw: str) -> dict | None:
    """响应体不是「恰好一个 JSON」时，挖出里面的第一个 JSON 对象。

    网关把多个响应块首尾相接、或在对象后面多吐一段（都会让 json.loads 报
    「Extra data」）时，整体解析失败，可第一个对象本身是好的——raw_decode
    只吃第一个对象，后面的垃圾不管。
    """
    start = raw.find("{")
    if start < 0:
        return None
    try:
        body, _ = json.JSONDecoder().raw_decode(raw[start:])
    except json.JSONDecodeError:
        return None
    return body if isinstance(body, dict) else None


def _chunk_content(obj: dict) -> str:
    """从一块响应里取补全正文：流式的 `delta` 和非流式的 `message` 都认。"""
    parts = []
    for choice in obj.get("choices") or []:
        message = choice.get("delta") or choice.get("message") or {}
        piece = message.get("content")
        if isinstance(piece, str):
            parts.append(piece)
    return "".join(parts)


def _sse_text(raw: str) -> str:
    """网关忽略 stream=false、把响应原样裹成 SSE 时，把各块里的补全内容拼回来。"""
    parts = []
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        parts.append(_chunk_content(obj))
    return "".join(parts)


def _message_content(body: dict, url: str, raw: str, max_tokens: int) -> str:
    """取出正文，并把「截断」和「只回了思考过程」这两种失败说清楚。

    以前这两类都会在下一步被 extract_json 悄悄吞掉，最后表现为"产出是空的"
    —— 用户拿到的是一份没内容的 SKILL.md，却看不到哪里断了。
    """
    choices = body.get("choices") or []
    choice = (choices[0] if choices else {}) or {}
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):  # 少数网关把 content 拆成分段数组
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    content = content or ""
    finish = choice.get("finish_reason")
    if not content.strip():
        reasoning = message.get("reasoning_content") or ""
        if reasoning.strip():
            raise RuntimeError(
                f"模型只回了思考过程（reasoning_content {len(reasoning)} 字符），正文为空"
                f"（finish_reason={finish}）from {url}：换一个非思考型模型，或关掉思考模式")
        raise RuntimeError(f"LLM 返回空内容（finish_reason={finish}）from {url}：{_preview(raw)}")
    if finish == "length":
        raise RuntimeError(
            f"LLM 输出被截断（finish_reason=length，正文 {len(content)} 字符，JSON 没收尾）"
            f"from {url}：{_limit_hint(max_tokens)}")
    return content


def llm_call(base_url: str, api_key: str, model: str, system: str, user: str,
             timeout: int = 600, dry_run: bool = False, max_tokens: int = 0) -> str:
    base_url = _require_ascii(base_url, "接口地址（--base-url）")
    api_key = _require_ascii(api_key, "API Key（--api-key / 环境变量）")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.3,
    }
    if max_tokens > 0:
        payload["max_tokens"] = max_tokens
    if dry_run:
        print(f"[dry-run] POST {url}  ({len(user)} 字符)", file=sys.stderr)
        return "{}"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"LLM HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"LLM connection failed for {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        # 读超时不会被包成 URLError，以前它会带着英文原文一路冒到用户面前
        # （"The read operation timed out"），看不出是我们等太久还是对面不回。
        # 报出实际等了多久：卡在设为上限的那一刻是我们的问题，卡在别的数值另有原因。
        raise RuntimeError(
            f"等待 {time.monotonic() - started:.0f} 秒仍没等到响应（读超时上限 {timeout} 秒）"
            f"from {url}：这个模型生成完整 JSON 本来就慢，"
            "用 --timeout 把上限调大（默认 600 秒）") from exc
    if not raw.strip():
        raise RuntimeError(f"LLM returned an empty response from {url}")
    raw = raw.lstrip("\ufeff").strip()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        # ① 网关可能把流式响应原样吐出来（每行 `data: {...}`），拼回来再试
        sse = _sse_text(raw)
        if sse.strip():
            return sse
        # ② 对象后面还粘着别的东西（网关把多个响应块首尾相接，或多吐了一段）时，
        #    整体解析会因「Extra data」失败，但第一个对象是好的。
        salvaged = _salvage_body(raw)
        if salvaged is not None:
            if isinstance(salvaged.get("choices"), list):
                if '"delta"' in raw:               # 流式块：正文在 delta 里
                    return _chunk_content(salvaged)
                return _message_content(salvaged, url, raw, max_tokens)
            if '"choices"' not in raw:
                # ③ 个别网关直接把补全文本当响应体返回，交给 extract_json 去淘 JSON
                return raw
        if '"choices"' in raw or raw.startswith('{"id"'):
            raise RuntimeError(
                f"LLM 响应体是截断/损坏的 JSON（{len(raw)} 字符，读不到 finish_reason）"
                f"from {url}：{_json_fault(exc, raw)}；{_limit_hint(max_tokens)}；{_preview(raw)}")
        if "{" in raw:
            return raw
        raise RuntimeError(f"LLM 返回的不是 JSON（{len(raw)} 字符）from {url}："
                           f"{_json_fault(exc, raw)}；{_preview(raw)}")
    if not isinstance(body, dict):
        raise RuntimeError(f"LLM 返回的不是 JSON 对象 from {url}：{_preview(str(body))}")
    return _message_content(body, url, raw, max_tokens)


def extract_json(text: str) -> dict:
    """从模型输出里淘出那个 JSON 对象。

    模型常常在 JSON 前后带一段说明或思考过程，思考过程里也会出现花括号，
    所以取代码块优先、再**从最后一个 `{` 往前**试着解析，而不是简单地
    「第一个 `{` 到最后一个 `}`」——那样会把两段无关的括号一并吞进来。
    """
    text = text.strip()
    fenced = re.findall(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced[-1].strip()
    try:
        body = json.loads(text)
        if isinstance(body, dict):
            return body
    except json.JSONDecodeError:
        pass
    for start in reversed([i for i, ch in enumerate(text) if ch == "{"]):
        end = text.rfind("}")
        while end > start:
            try:
                body = json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                end = text.rfind("}", start, end)
                continue
            if isinstance(body, dict):
                return body
            break
    return {}


def merge_dicts(items: list[dict]) -> dict:
    merged: dict[str, list[str]] = defaultdict(list)
    for item in items:
        if not isinstance(item, dict):
            continue
        for key, value in item.items():
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, list):
                continue
            for entry in value:
                entry = str(entry).strip()
                if entry and entry not in merged[key]:
                    merged[key].append(entry)
    return dict(merged)


def consult_llm(corpus: str, target: str, args, stats: Stats,
                relation: str = "朋友") -> tuple[dict, dict]:
    """把语料分片喂给 LLM，再合并成 persona / memory 两份结构化结果。"""
    # 关系类型只影响措辞要求，不改变字段结构
    persona_system = PERSONA_PROMPT.replace("{target}", target) + "\n\n" + relation_hint(relation)
    memory_system = MEMORY_PROMPT + "\n\n" + relation_hint(relation)
    limit = args.llm_chars
    pieces = []
    cur = []
    size = 0
    for para in corpus.split("\n\n"):
        if size + len(para) > limit and cur:
            pieces.append("\n\n".join(cur))
            cur, size = [], 0
        cur.append(para)
        size += len(para)
    if cur:
        pieces.append("\n\n".join(cur))
    pieces = pieces[: max(1, args.llm_batches)]

    personas, memories = [], []
    failures: list[str] = []
    # 读超时是客户端设的等待上限，调大不会拖慢正常请求。
    # 人设那一次跑 114 秒是常态，而关系记忆要写的 JSON 更长（上一次的用量是
    # 44122 token），180 秒的老默认值经常不够——它就表现为「The read operation timed out」。
    timeout = getattr(args, "timeout", 0) or 600
    # LLM 调用是分钟级的，先把总规模说清楚。
    # 只报"正在做第几批"而不报总数和单次耗时，用户没法估算还要等多久——
    # 加上这一行 + 每次调用后的用时，进度才是可读的。
    print(f"  · 共 {len(pieces)} 批，每批 2 次调用（人格分析 + 关系记忆）"
          f"，合计 {len(pieces) * 2} 次请求", file=sys.stderr)

    for i, piece in enumerate(pieces, 1):
        # 两次调用各自兜住异常：一次失败不该把刚刚跑成的那一次一起带走
        # （人格分析可能刚花了两分钟、四万 token，扔掉它代价太大）。
        for label, system, sink in (("人格分析", persona_system, personas),
                                    ("关系记忆", memory_system, memories)):
            print(f"  · 第 {i}/{len(pieces)} 批 · {label}…（输入 {len(piece)} 字符）",
                  file=sys.stderr)
            started = time.monotonic()
            try:
                out = llm_call(args.base_url, args.api_key, args.model, system, piece,
                               timeout=timeout, dry_run=args.dry_run_llm,
                               max_tokens=getattr(args, "max_tokens", 0))
            except Exception as e:
                failures.append(f"第 {i} 批 · {label}：{e}")
                print(f"      {label}失败：{e}", file=sys.stderr)
                continue
            sink.append(extract_json(out))
            print(f"      {label}完成：用时 {time.monotonic() - started:.1f} 秒，"
                  f"返回 {len(out)} 字符", file=sys.stderr)

    if failures and not personas and not memories:
        # 全挂：交给调用方去走本地抽取式蒸馏，别在这里硬撑
        raise RuntimeError(failures[0] if len(failures) == 1
                           else f"{len(failures)} 次调用全都失败，例如 {failures[0]}")

    persona = merge_dicts(personas)
    memory = merge_dicts(memories)
    # 把脚本统计出来的口头禅作为兜底/补充
    ph = persona.setdefault("口头禅", [])
    for p, c in stats.phrases.most_common(20):
        if c >= 4 and p not in ph and len(ph) < 16:
            ph.append(p)
    return persona, memory


# ----------------------------------------------------------------------------
# 六、渲染成设备端技能
# ----------------------------------------------------------------------------
