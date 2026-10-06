import statistics
from collections import Counter
from datetime import timedelta

from .conversations import SESSION_SEPARATOR, split_sessions
from .models import CONFLICT_WORDS, SESSION_GAP, STOP_PHRASES, Msg, Stats
from .parsers import SENTENCE_SPLIT, WEIBO_EMOJI


def reply_gaps(msgs: list[Msg]) -> dict[str, list[float]]:
    """每个人的回复延迟（分钟）：换人发言时，间隔算在后开口那个人的头上。

    离线蒸馏和统计数据都要用它，放一份才不会两边口径打架
    （一个算"隔了 3 分钟回"、另一个算"隔了 8 分钟回"，用户只会觉得这工具不准）。
    """
    gaps: dict[str, list[float]] = {}
    prev: Msg | None = None
    for m in msgs:
        if prev and prev.ts and m.ts and m.speaker != prev.speaker:
            delta = (m.ts - prev.ts).total_seconds() / 60
            if 0 <= delta <= SESSION_GAP.total_seconds() / 60:
                gaps.setdefault(m.speaker, []).append(delta)
        prev = m
    return gaps


def analyse(msgs: list[Msg], target: str) -> Stats:
    st = Stats()
    st.total = len(msgs)
    lengths = []
    mine = bursts = questions = with_emoji = 0
    prev: Msg | None = None
    for m in msgs:
        st.per_speaker[m.speaker] += 1
        if m.ts:
            st.first_ts = min(st.first_ts, m.ts) if st.first_ts else m.ts
            st.last_ts = max(st.last_ts, m.ts) if st.last_ts else m.ts
        if m.speaker != target:
            prev = m
            continue
        mine += 1
        if m.ts:
            st.timed_total += 1
            st.hours[m.ts.hour] += 1
            if m.ts.hour >= 23 or m.ts.hour <= 5:
                st.late_night += 1
        if (prev is not None and prev.speaker == target
                and (not prev.ts or not m.ts or timedelta(0) <= m.ts - prev.ts <= SESSION_GAP)):
            bursts += 1                      # 连着发：一句话拆成好几条说
        lengths.append(len(m.text))
        emos = WEIBO_EMOJI.findall(m.text)
        if emos:
            with_emoji += 1
        if m.text.rstrip().endswith(("?", "？", "吗", "呢", "吧")):
            questions += 1                   # 爱把话抛回去的人，对话是有来有回的
        for emo in emos:
            st.emoji[emo] += 1
        for word in CONFLICT_WORDS:
            if word in m.text:
                st.conflict_hits[word] += 1
        for seg in SENTENCE_SPLIT.split(m.text):
            seg = seg.strip()
            if "[" in seg or "]" in seg:
                continue  # [图片] [表情] 这类占位不是口头禅
            if 2 <= len(seg) <= 8 and seg not in STOP_PHRASES and not seg.isdigit():
                st.phrases[seg] += 1
        prev = m

    st.avg_len = round(statistics.mean(lengths), 1) if lengths else 0.0
    if mine:
        st.burst_ratio = round(bursts / mine * 100, 1)
        st.question_ratio = round(questions / mine * 100, 1)
        st.emoji_ratio = round(with_emoji / mine * 100, 1)
    gaps = reply_gaps(msgs).get(target, [])
    st.reply_gap = round(statistics.median(gaps), 1) if gaps else 0.0

    for session in split_sessions(msgs):
        if any(m.ts for m in session):
            st.session_starts[session[0].speaker] += 1
    return st


def _fmt_gap(minutes: float) -> str:
    """回复间隔的人话写法。0 表示"算不出来"（没有可配对的相邻消息）。"""
    if minutes <= 0:
        return "—"
    if minutes < 1:
        return "不到 1 分钟"
    if minutes < 60:
        return f"{minutes:.0f} 分钟"
    if minutes < 60 * 24:
        return f"{minutes / 60:.1f} 小时"
    return f"{minutes / 1440:.1f} 天"


def stats_markdown(st: Stats, target: str) -> str:
    span = ""
    if st.first_ts and st.last_ts:
        days = (st.last_ts - st.first_ts).days + 1
        span = f"{st.first_ts:%Y-%m-%d} ~ {st.last_ts:%Y-%m-%d}（约 {days} 天）"
    top_phrases = [p for p, c in st.phrases.most_common(18) if c >= 3]
    top_emoji = [f"{e}×{c}" for e, c in st.emoji.most_common(12)]
    late_ratio = f"{st.late_night / st.timed_total * 100:.0f}%" if st.timed_total else "未知"
    lines = [
        "## 数据统计（脚本自动提取，未经过 LLM，可当作风味的客观线索）",
        "",
        f"- 消息总数：{st.total}；时间跨度：{span or '未知'}",
        f"- 双方消息量：{'、'.join(f'{k} {v} 条' for k, v in st.per_speaker.most_common())}",
        f"- {target} 的主动开口次数：{st.session_starts.get(target, 0)} 次"
        f"（对方 {sum(v for k, v in st.session_starts.items() if k != target)} 次）",
        f"- {target} 平均消息长度：{st.avg_len} 字",
        f"- 深夜（23:00–05:00）消息占比：{late_ratio}",
        # 下面四条是"体温"：一个人说得短不短、回得快不快、爱不爱把话抛回来，
        # 比"他说过什么"更能决定模仿出来像不像。
        f"- 回复节奏：{target} 通常隔 {_fmt_gap(st.reply_gap)}回（中位数）",
        f"- 说话节奏：{st.burst_ratio:.0f}% 的消息是紧接着自己上一条发的（拆成几句说），"
        f"{st.question_ratio:.0f}% 是问句，{st.emoji_ratio:.0f}% 带表情标记",
    ]
    if top_phrases:
        lines.append(f"- 高频口头禅候选：{'、'.join(top_phrases)}")
    if top_emoji:
        lines.append(f"- 常用表情/表情包记号：{'、'.join(top_emoji)}")
    if st.conflict_hits:
        lines.append(f"- 冲突相关词频：{'、'.join(f'{k}×{v}' for k, v in st.conflict_hits.most_common(8))}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# 三、采样：按会话切分，优先深夜 / 冲突 / 长会话
# ----------------------------------------------------------------------------

def sample_sessions(msgs: list[Msg], target: str, budget_chars: int,
                    window_chars: int | None = None) -> tuple[str, int]:
    """按月份和情境覆盖选完整会话，保持年份、顺序和严格字符预算。"""
    if budget_chars <= 0:
        return "", 0
    window_budget = min(budget_chars, window_chars) if window_chars is not None else budget_chars
    if window_budget <= 60:
        return "", 0
    candidates = []
    for index, session in enumerate(split_sessions(msgs)):
        if not any(m.speaker == target for m in session):
            continue
        lines = [f"[{m.ts:%Y-%m-%d %H:%M}] {m.speaker}: {m.text}" if m.ts
                 else f"[时间未知] {m.speaker}: {m.text}" for m in session]
        # 超长会话按相邻的完整发言段切窗口；不截断消息，也不把窗口接成连续对话。
        runs: list[list[str]] = []
        previous_speaker = None
        for msg, line in zip(session, lines):
            if runs and msg.speaker == previous_speaker:
                runs[-1].append(line)
            else:
                runs.append([line])
            previous_speaker = msg.speaker
        windows: list[str] = []
        current: list[str] = []
        for run in runs:
            body = "\n".join(run)
            if len(body) + 60 > window_budget:
                if current:
                    windows.append("\n".join(current))
                current = []
                continue
            if len("\n".join(current + run)) + 60 > window_budget and current:
                windows.append("\n".join(current))
                current = []
            current.extend(run)
        if current:
            windows.append("\n".join(current))
        month = next((f"{m.ts:%Y-%m}" for m in session if m.ts), "未知")
        for window_id, body in enumerate(windows):
            if not any(f"] {target}:" in line for line in body.splitlines()):
                continue
            conflict = sum(word in body for word in ("生气", "别催", "别跟我", "吵架", "冷战", "对不起"))
            scene = ("摩擦" if conflict else "商量" if any(w in body for w in ("要不要", "一起", "说定", "周末"))
                     else "日常")
            marked = f"【会话 {index + 1} / 窗口 {window_id + 1}；与其他会话独立】\n{body}"
            candidates.append((index, window_id, month, scene, marked))
    chosen = []
    months, scenes, sessions = Counter(), Counter(), Counter()
    used = 0
    while candidates:
        def score(item):
            index, window, month, scene, body = item
            return (min(body.count("\n"), 40) / 40 - 3 * months[month]
                    - 3 * scenes[scene] - 4 * sessions[index])
        item = max(candidates, key=score)
        candidates.remove(item)
        cost = len(item[4]) + (len(SESSION_SEPARATOR) if chosen else 0)
        if used + cost > budget_chars:
            continue       # 大会话装不下时仍可选后面更短的会话
        chosen.append(item)
        used += cost
        months[item[2]] += 1
        scenes[item[3]] += 1
        sessions[item[0]] += 1
    sample = SESSION_SEPARATOR.join(item[4] for item in sorted(chosen))
    return sample, len(sample)


# ----------------------------------------------------------------------------
# 四、脱敏
# ----------------------------------------------------------------------------
