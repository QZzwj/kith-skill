import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from collections.abc import Callable

from .models import Stats
from .relation import relation_hint


#: 上游「什么都没给」时重试几次（等 3 秒、再等 9 秒）。限流窗口和上游抖动都是秒级的，
#: 一次空响应就把整段关系记忆丢掉太亏：那一段往往要重跑好几分钟才补得回来。
RETRIES = 2
RETRY_WAIT = 3.0
#: 小于这个长度的语料不值得对半拆：碎片本身不足以让模型提取关系记忆。
MIN_SPLIT_CHARS = 6000


class UpstreamUnavailable(RuntimeError):
    """上游这次什么都没给我们，但**同样的请求重试是有意义的**。

    表现有三种：HTTP 200 的空壳（`choices` 为空、`usage` 全 0）、429、5xx。
    实测（2026-09-27，ModelScope + deepseek-ai/DeepSeek-V4.1-Flash）那次的响应体是
    `{"object":"","created":0,"choices":null,"usage":{...全是 0}}`：请求被受理了、
    一次正文都没生成就返回，同一批的另一次调用也一起空 —— 属于限流/上游抖动，
    不是输入太长，也不是我们参数写错。重试能把这类丢掉的调用捞回来。
    """


class LLMTimeoutError(RuntimeError):
    """等满 timeout 秒也没等到响应。

    同尺寸**重试没意义**（还要再等同样久），把这一批**拆小**才有用：输出短了，
    上游才写得完。它和 UpstreamUnavailable 的区别值得分开：一个是「你没给我」，
    一个是「我等够了」。
    """


PERSONA_PROMPT = """你在做「人格蒸馏」：从一段真实聊天记录里，还原 TA 这个人说话和行为的样子。
只输出 JSON，不要任何解释。字段要求：

{
  "说话风格": ["短句/长句、标点习惯、语气词、有没有错别字、爱不爱用表情、爱不爱发语音文字描述", "..."],
  "口头禅": ["原样引用的高频口头语或句式，最多 12 条"],
  "接话方式": ["真实对话里「对方说了什么 → TA 怎么接」的对照，5-8 条，两边都逐字摘抄、不要改写，"
               "写成『对方：「…」 → 我：「…」』；挑能看出 TA 接话习惯的（先哄还是先笑、抛回来还是岔开、"
               "一句话拆成几条发）"],
  "情感模式": ["怎么表达关心、生气、开心、失落；回避还是直球", "..."],
  "温度与分寸": ["这段关系里 TA 的亲密度到哪一档（克制 / 熟但得体 / 亲近 / 很黏），靠哪些行为体现；"
                 "以及哪些话 TA 在记录里从没说过（肉麻的话、长篇表白、过度关心），"
                 "写出「别比记录更热」的边界", "..."],
  "关系行为": ["主动找人吗、回消息快慢、吵架后怎么收场、纪念日/生日的做法", "..."],
  "硬规则": ["像 TA 说话时必须遵守的底线，例如『从不说肉麻的话』『不会秒回，通常隔几分钟』", "..."],
  "典型例句": ["能体现 TA 风格的原话，3-8 条，只写句子本身，不要带时间、不要带说话人"],
  "依据": ["<上面某条结论> ← <支撑它的原话>", "..."]
}

要求：所有内容都必须能从聊天记录里找到依据，不确定就不要写，不要编造。
「依据」要为「口头禅」「典型例句」「接话方式」的每一条指出出处，格式是「结论 ← 原话」，
原话必须逐字摘抄并带上时间或说话人；找不到出处的条目就不要写进上面的字段。
时间与说话人只写在「依据」里，「典型例句」保持干净的一句话。
「接话方式」是模仿时最有用的一节：它教的是"怎么接话"，不要写成对语气的概括——
概括教不出"人家抱怨一句 TA 是先哄还是先笑"。
「温度与分寸」要给出可数的依据（关心 / 称呼 / 直球 / 表情各出现多少次），不要用"很亲密"这种空话。
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

#: 公开版的措辞约束。这份人设会给本人以外的人用，
#: 而"只有本人接得住"的指代和私密细节正是公开版最容易出事的地方——
#: 与其事后靠正则标注，不如在生成时就要求改写成背景陈述。
PUBLIC_HINT = """

【用途】这份人设会被「本人以外的人」使用，请按公开版来写：
- 不写只有本人对得上的指代（咱俩、你上次说的、那次、你还记得），改成平实的背景陈述；
- 不写私密细节：住址、联系方式、收入、健康、感情状况这类，记录里没有的不要提；
- 提到第三方时用「TA」「那位朋友」这类中性说法，不要堆真名。"""


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
        # 空壳（choices 为空 / 一个 token 都没产出）走「重试有意义」那条路，别把
        # 上游的一次抖动说成内容问题——用户看到「返回空内容」只会去改输入。
        usage = body.get("usage") or {}
        produced = usage.get("completion_tokens") or usage.get("total_tokens") or 0
        if not choices or not produced:
            raise UpstreamUnavailable(
                f"上游没生成任何内容（HTTP 200，choices {'为空' if not choices else '无正文'}、"
                f"用量 {produced} token）from {url}：模型一次正文都没吐，"
                "常见于限流或上游抖动，不是输入的问题（同一批的其它调用也一起空过）。"
                f"响应体：{_preview(raw)}")
        raise RuntimeError(f"LLM 返回空内容（finish_reason={finish}）from {url}：{_preview(raw)}")
    if finish == "length":
        raise RuntimeError(
            f"LLM 输出被截断（finish_reason=length，正文 {len(content)} 字符，JSON 没收尾）"
            f"from {url}：{_limit_hint(max_tokens)}")
    return content


def _retrying(attempt_fn: Callable[[], str], retries: int, hint: str) -> str:
    """上游「什么都没给」时的退避重试（蒸馏和陪聊共用一套）。

    重试只针对 ``UpstreamUnavailable``（空壳 / 429 / 5xx / 连不上）——那是"现在不行"，
    等几秒多半就行；读超时和输出截断不在此列：前者是我们等够了，后者要动参数，
    重试只是把同样的等待和同样的失败再来一遍。
    """
    for attempt in range(retries + 1):
        try:
            return attempt_fn()
        except UpstreamUnavailable as exc:
            if attempt >= retries:
                raise UpstreamUnavailable(
                    f"{exc}（已重试 {retries} 次仍如此：{hint}）") from exc
            wait = RETRY_WAIT * (3 ** attempt)
            print(f"  · 上游没给内容，{wait:.0f} 秒后重试"
                  f"（第 {attempt + 2}/{retries + 1} 次）", file=sys.stderr)
            time.sleep(wait)
    # 循环要么返回、要么抛出，走不到这里；写出来是为了让类型检查器也看得出这一点
    raise ValueError(f"retries 不能为负（当前 {retries}）")


def llm_call(base_url: str, api_key: str, model: str, system: str, user: str,
             timeout: int = 600, dry_run: bool = False, max_tokens: int = 0,
             retries: int = RETRIES, temperature: float = 0.3) -> str:
    """调用一次补全接口，上游「什么都没给」时自动重试。

    温度默认 0.3：抽取类任务要的是**稳**——同一份记录跑两遍，结论应该是一样的。
    陪聊要的相反，是**活**，所以单独走 :func:`llm_chat`（见 :data:`CHAT_TEMPERATURE`）。
    """
    return _retrying(
        lambda: _llm_call_once(base_url, api_key, model, system, user, timeout=timeout,
                               dry_run=dry_run, max_tokens=max_tokens,
                               temperature=temperature),
        retries, "可以直接重跑一次，或调小 --llm-chars 让每次请求更小、更快返回")


#: 陪聊用的温度。抽取（:func:`llm_call`）要的是稳，陪聊要的是活：
#: 0.95 出来的话还是偏"有礼貌"，1.1 上下才松开；再往上（1.5 以上）不是更活，
#: 而是开始把话说飘——试聊页留了三档，想调直接在那儿挑，不必改代码。
CHAT_TEMPERATURE = 1.1


def llm_chat(base_url: str, api_key: str, model: str, system: str, turns: list[dict],
             timeout: int = 180, temperature: float = CHAT_TEMPERATURE, max_tokens: int = 0,
             retries: int = RETRIES) -> str:
    """陪聊：把整段对话按**真正的多轮消息**发过去。

    以前试聊把历史压成一条 user 消息（"我：…\\nTA：…"），模型收到的是"一份要接着写的
    记录"，于是答得像在续写文档；拆成 user/assistant 轮次，它才会按对话的本能接话。

    温度也单独给一个：0.3 是为抽取调的，拿来聊天只会得到一套没毛病、也没体温的客套话。
    """
    return _retrying(
        lambda: _llm_call_once(base_url, api_key, model, system, "", timeout=timeout,
                               max_tokens=max_tokens, temperature=temperature, turns=turns),
        retries, "再发一次，或换个模型试试")


def _llm_call_once(base_url: str, api_key: str, model: str, system: str, user: str,
                   timeout: int = 600, dry_run: bool = False, max_tokens: int = 0,
                   temperature: float = 0.3, turns: list[dict] | None = None) -> str:
    base_url = _require_ascii(base_url, "接口地址（--base-url）")
    api_key = _require_ascii(api_key, "API Key（--api-key / 环境变量）")
    url = base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": model,
        # turns 给了就用它（多轮对话），没给就是"system + 一条 user"的老样子
        "messages": [{"role": "system", "content": system}]
                    + (turns if turns else [{"role": "user", "content": user}]),
        "temperature": temperature,
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
        text = f"LLM HTTP {exc.code} from {url}: {detail}"
        # 限流（429）和网关 5xx 属于"现在不行"，退避重试有意义；
        # 400/401/404 这类是参数或权限问题，重试只是把同样的错再刷一遍。
        if exc.code in (408, 409, 425, 429, 500, 502, 503, 504):
            raise UpstreamUnavailable(text) from exc
        raise RuntimeError(text) from exc
    except urllib.error.URLError as exc:
        raise UpstreamUnavailable(f"LLM connection failed for {url}: {exc.reason}") from exc
    except TimeoutError as exc:
        # 读超时不会被包成 URLError，以前它会带着英文原文一路冒到用户面前
        # （"The read operation timed out"），看不出是我们等太久还是对面不回。
        # 报出实际等了多久：卡在设为上限的那一刻是我们的问题，卡在别的数值另有原因。
        raise LLMTimeoutError(
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


def _with_stats_phrases(persona: dict, stats: Stats | None) -> dict:
    """把脚本统计出来的口头禅补进人设，作为模型的兜底。

    必须用**这个人自己的**统计：拿对方的统计来补，等于把别人的口癖安到 TA 头上。
    """
    if stats is None or not persona:
        return persona
    ph = persona.setdefault("口头禅", [])
    for p, c in stats.phrases.most_common(20):
        if c >= 4 and p not in ph and len(ph) < 16:
            ph.append(p)
    return persona


def _halve(text: str) -> list[str]:
    """把一批语料按段落对半切开；不值得切时返回 ``[]``。

    什么时候值得切：上游「没给内容」或「等超时」而这一批又是整份记录（几千到几万字符）时。
    关系记忆要写的 JSON 比人设长得多（实测一次用量 44122 token），整份语料塞进去，
    有的模型就是写不完 —— 拆成两半让它每次少写点，反而能成。
    太短就不切：碎片不足以让模型看出关系脉络，切了只是徒增两次调用。
    """
    if len(text) < MIN_SPLIT_CHARS:
        return []
    paras = text.split("\n\n")
    if len(paras) < 2:
        return []
    mid, acc, cut = len(text) // 2, 0, 0
    for idx, para in enumerate(paras, 1):
        acc += len(para) + 2
        if acc >= mid:
            cut = idx
            break
    left, right = paras[:cut], paras[cut:]
    if not left or not right:
        return []
    return ["\n\n".join(left), "\n\n".join(right)]


def consult_llm(corpus: str, target: str, args, stats: Stats,
                relation: str = "朋友", also: str = "", also_stats: Stats | None = None,
                audience: str = "本人") -> tuple[dict, dict, dict]:
    """把语料分片喂给 LLM，再合并成 persona / memory 两份结构化结果。

    双向蒸馏时 ``also`` 是另一方的名字：每批会多跑一次，把 TA 也做成一份画像
    （只做人设，不重复做关系记忆——关系只有一份）。``audience`` 为「公开」时，
    给主技能的人设 prompt 追加一段措辞约束：不写只有本人对得上的指代与私密细节。
    """
    # 关系类型只影响措辞要求，不改变字段结构
    persona_system = PERSONA_PROMPT.replace("{target}", target) + "\n\n" + relation_hint(relation)
    if audience == "公开":
        persona_system += PUBLIC_HINT
    memory_system = MEMORY_PROMPT + "\n\n" + relation_hint(relation)
    also_system = (PERSONA_PROMPT.replace("{target}", also) + "\n\n" + relation_hint(relation)
                   if also else "")
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

    personas, memories, also_profile = [], [], []
    failures: list[str] = []
    # 读超时是客户端设的等待上限，调大不会拖慢正常请求。
    # 人设那一次跑 114 秒是常态，而关系记忆要写的 JSON 更长（上一次的用量是
    # 44122 token），180 秒的老默认值经常不够——它就表现为「The read operation timed out」。
    timeout = getattr(args, "timeout", 0) or 600
    # LLM 调用是分钟级的，先把总规模说清楚。
    # 只报"正在做第几批"而不报总数和单次耗时，用户没法估算还要等多久——
    # 加上这一行 + 每次调用后的用时，进度才是可读的。
    tasks = [("人格分析", persona_system, personas),
             ("关系记忆", memory_system, memories)]
    if also:
        tasks.append((f"{also} 的画像", also_system, also_profile))
    print(f"  · 共 {len(pieces)} 批，每批 {len(tasks)} 次调用"
          f"（{' + '.join(t[0] for t in tasks)}）"
          f"，合计 {len(pieces) * len(tasks)} 次请求", file=sys.stderr)

    def run_one(tag: str, label: str, system: str, text: str, depth: int = 0) -> list[dict]:
        """跑一次调用并解析；上游没给内容 / 等超时时，把这一批对半拆开再试（只拆一层）。

        只拆一层：真拆成了，两半各自都能返回；还是不行说明问题不在长度上，继续拆只会
        让碎片更没有上下文。``extract_json`` 也放进 try —— 一段坏 JSON 不该把整轮
        LLM 结果一起带走（以前它会直接冒到调用方，成功的那半也一起作废）。
        """
        started = time.monotonic()
        try:
            out = llm_call(args.base_url, args.api_key, args.model, system, text,
                           timeout=timeout, dry_run=args.dry_run_llm,
                           max_tokens=getattr(args, "max_tokens", 0))
            parsed = extract_json(out)
        except (UpstreamUnavailable, LLMTimeoutError) as e:
            halves = _halve(text) if depth == 0 else []
            if halves:
                print(f"      {label}：{e}", file=sys.stderr)
                print(f"      {label}改拆成 {len(halves)} 份重试"
                      f"（各 {len(halves[0])} / {len(halves[1])} 字符）", file=sys.stderr)
                got: list[dict] = []
                for part in halves:
                    got += run_one(tag, label, system, part, depth + 1)
                # 两半各自都记过一次失败了，别再重复一遍同样的原因
                return got
            failures.append(f"{tag}：{e}")
            print(f"      {label}失败：{e}", file=sys.stderr)
            return []
        except Exception as e:
            failures.append(f"{tag}：{e}")
            print(f"      {label}失败：{e}", file=sys.stderr)
            return []
        print(f"      {label}完成：用时 {time.monotonic() - started:.1f} 秒，"
              f"返回 {len(out)} 字符", file=sys.stderr)
        return [parsed]

    for i, piece in enumerate(pieces, 1):
        # 每次调用各自兜住异常：一次失败不该把刚刚跑成的那一次一起带走
        # （人格分析可能刚花了两分钟、四万 token，扔掉它代价太大）。
        for label, system, sink in tasks:
            tag = f"第 {i}/{len(pieces)} 批 · {label}"
            print(f"  · {tag}…（输入 {len(piece)} 字符）", file=sys.stderr)
            sink.extend(run_one(tag, label, system, piece))

    if failures and not personas and not memories and not also_profile:
        # 全挂：交给调用方去走本地抽取式蒸馏，别在这里硬撑
        raise RuntimeError(failures[0] if len(failures) == 1
                           else f"每一处都失败了（{len(failures)} 处），例如 {failures[0]}")

    persona = _with_stats_phrases(merge_dicts(personas), stats)
    memory = merge_dicts(memories)
    background = _with_stats_phrases(merge_dicts(also_profile), also_stats)
    return persona, memory, background


# ----------------------------------------------------------------------------
# 六、渲染成设备端技能
# ----------------------------------------------------------------------------
