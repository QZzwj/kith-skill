"""完整会话和有上下文的接话示范；蒸馏与试聊共用同一套边界。"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta

from .models import Msg, SESSION_GAP

SESSION_SEPARATOR = "\n\n---\n\n"

# These exports indicate a reply to a quoted message, but Msg does not carry
# its target. Keep the source intact and avoid inventing an adjacent pair.
_UNRESOLVED_REPLY = re.compile(r"\[\s*(?:回复消息|引用消息|引用回复)(?:\s*[:：][^\]]*)?\s*\]")


def has_unresolved_reply(text: str) -> bool:
    return bool(_UNRESOLVED_REPLY.search(text))


def reply_text(text: str) -> str:
    return _UNRESOLVED_REPLY.sub('', text).strip()


def pack_windows(corpus: str, limit: int, batches: int) -> tuple[list[str], int]:
    """装入完整窗口，计入分隔符；超长窗口不截断，也不拆成伪连续对话。"""
    if limit <= 0 or batches <= 0:
        return [], int(bool(corpus.strip()))
    units = [part.strip() for part in corpus.split(SESSION_SEPARATOR) if part.strip()]
    bins: list[list[tuple[int, str]]] = []
    sizes: list[int] = []
    dropped = 0
    for index, unit in sorted(enumerate(units), key=lambda item: -len(item[1])):
        if len(unit) > limit:
            dropped += 1
            continue
        slot = next((i for i, size in enumerate(sizes)
                     if size + len(SESSION_SEPARATOR) + len(unit) <= limit), None)
        if slot is None:
            if len(bins) >= batches:
                dropped += 1
                continue
            bins.append([])
            sizes.append(0)
            slot = len(bins) - 1
        sizes[slot] += len(unit) + (len(SESSION_SEPARATOR) if bins[slot] else 0)
        bins[slot].append((index, unit))
    bins.sort(key=lambda items: min(index for index, _ in items))
    return [SESSION_SEPARATOR.join(unit for _, unit in sorted(items)) for items in bins], dropped


def split_sessions(msgs: list[Msg], gap: timedelta = SESSION_GAP) -> list[list[Msg]]:
    sessions: list[list[Msg]] = []
    current: list[Msg] = []
    previous = None
    for msg in msgs:
        if msg.ts and previous and (msg.ts < previous or msg.ts - previous > gap):
            if current:
                sessions.append(current)
            current = []
        current.append(msg)
        if msg.ts:
            previous = msg.ts
    if current:
        sessions.append(current)
    return sessions


@dataclass
class Exchange:
    incoming: list[str]
    reply: list[str]
    session: int
    incoming_messages: list[int] = field(default_factory=list)
    reply_messages: list[int] = field(default_factory=list)
    pairing: str = 'adjacent'

    def render(self) -> str:
        return ("对方：" + "".join(f"「{x}」" for x in self.incoming)
                + " → 我：" + "".join(f"「{x}」" for x in self.reply))


def reply_exchanges(msgs: list[Msg], target: str, counterpart: str) -> list[Exchange]:
    """只配对同一会话内相邻的完整发言；第三人或纯媒体发言不能被跨过去。"""
    out: list[Exchange] = []
    offset = 0
    session_for = []
    for session_id, session in enumerate(split_sessions(msgs)):
        session_for.extend([session_id] * len(session))
        runs: list[tuple[str, list[tuple[int, str]]]] = []
        for index, msg in enumerate(session, offset + 1):
            if runs and runs[-1][0] == msg.speaker:
                runs[-1][1].append((index, msg.text))
            else:
                runs.append((msg.speaker, [(index, msg.text)]))
        offset += len(session)
        for (who, incoming), (speaker, reply) in zip(runs, runs[1:]):
            if who != counterpart or speaker != target:
                continue
            if any(msgs[i - 1].reply_to or has_unresolved_reply(text) for i, text in incoming + reply):
                continue
            def text_only(lines):
                return [(index, x.strip()) for index, x in lines if x.strip()
                        and not re.fullmatch(r"(?:\s*\[[^\[\]]*\]\s*)+", x)]
            left_rows, right_rows = text_only(incoming), text_only(reply)
            left, right = [x for _, x in left_rows], [x for _, x in right_rows]
            if not left or not right or len(left) > 3 or len(right) > 3:
                continue
            if max(len("".join(left)), len("".join(right))) > 80:
                continue
            out.append(Exchange(left, right, session_id, [i for i, _ in left_rows], [i for i, _ in right_rows]))
    ids = defaultdict(list)
    for index, msg in enumerate(msgs, 1):
        if msg.source_id:
            ids[msg.source_id].append(index)
    for index, msg in enumerate(msgs, 1):
        candidates = ids.get(msg.reply_to, []) if msg.reply_to else []
        if msg.speaker != target or len(candidates) != 1 or candidates[0] >= index:
            continue
        source_index = candidates[0]
        source = msgs[source_index - 1]
        if source.speaker != counterpart or source.reply_to or has_unresolved_reply(source.text):
            continue
        left, right = [source.text], [reply_text(msg.text)]
        reply_ids = [index]
        for next_index in range(index + 1, len(msgs) + 1):
            following = msgs[next_index - 1]
            if following.speaker != target or following.reply_to or has_unresolved_reply(following.text):
                break
            if following.ts and msg.ts and (following.ts < msg.ts or following.ts - msg.ts > SESSION_GAP):
                break
            right.append(following.text)
            reply_ids.append(next_index)
        media = any(re.fullmatch(r'(?:\s*\[[^\[\]]*\]\s*)+', text) for text in left + right)
        if len(right) <= 3 and not media and all(left + right) and max(len(''.join(left)), len(''.join(right))) <= 80:
            out.append(Exchange(left, right, session_for[index - 1], [source_index], reply_ids, 'explicit_reference'))
    out.sort(key=lambda exchange: exchange.reply_messages[0])
    return out


# 规则只命名可在两侧原话中观察到的接法，不据关键词推断内心或永久性格。
# 未落入这些情境的对话仍可作为原话示范，不强行归类。
_SITUATIONS = (
    ("被指出说法或承诺有问题",
     r"你(?:上次|上周|之前|刚才|那天|刚刚|不是|明明|曾经).{0,10}(?:说|答应|承诺)"
     r"|你说的.{0,8}(?:不对|不是|错|矛盾)|(?:不是|明明)说(?:好|过)|说好的"
     r"|说好.{0,12}(?:呢|怎么|咋|没|不)|放鸽子|又鸽|你.{0,6}(?:改口|食言|反悔)"
     r"|(?:说法|承诺).{0,6}(?:不对|有问题|变了)|^[^，。！？\s]{1,10}那次[?？!！。]*$",
     r"那叫|这叫|那是|这周|准确|不是.{0,8}是",
     "抓住对方说法中的一点，短句修正或换个说法接回去"),
    ("被催或被提醒", r"催|写|交|报告|做完|弄完|忘|截止",
     r"别催|别跟我|你发消息|催|等会|等下|知道了|别急",
     "先回应催促本身，再按当前进度接话；保留原话里的顶嘴或缓冲语气"),
    ("对方表达感谢", r"谢|多亏|要不是你|帮大忙",
     r"请我|请客|欠我|喝水|喝奶茶|不客气|没事|应该的|小事",
     "用原话里的回礼要求或简短答语接住感谢"),
    ("对方抱怨没被叫上", r"不叫我|没叫我|不带我|没带我",
     r"下次|叫你|带你|忘了|抱歉",
     "顺着抱怨回应下一次的安排，用短句补一句承诺"),
    ("对方要求正经一点", r"正经|认真|别闹|别逗",
     r"正经|认真|就是|明明",
     "沿着刚才的话题继续接梗，保留原话中一本正经的措辞"),
    ("对方给出答应或确认", r"真的|行$|可以|好$|答应|没问题|我跟你|说定",
     r"说定|约定|那就|等你|等我|记住|稳了",
     "把对方的确认接成具体约定或下一步"),
    ("对方报告进度或结果", r"通过|好了|完成|成功|起了|到了|发了|报名",
     r"收到|好|等会|我也|我已经|骑车|送你|恭喜",
     "接上对方的进度，报自己的状态或给一个下一步"),
)


def matches_input(label: str, text: str) -> bool:
    return any(name == label and re.search(left, text)
               for name, left, _, _ in _SITUATIONS)


def situation(exchange: Exchange) -> tuple[str, str]:
    incoming, reply = " ".join(exchange.incoming), " ".join(exchange.reply)
    if has_unresolved_reply(incoming) or has_unresolved_reply(reply):
        return "日常接话", ""
    for label, left, right, action in _SITUATIONS:
        if re.search(left, incoming) and re.search(right, reply):
            return label, action
    return "日常接话", ""


def select_exchanges(exchanges: list[Exchange], limit: int = 8) -> list[Exchange]:
    """兼顾接法、措辞和会话覆盖；不让一场长聊天占满示范。"""
    if limit < 1:
        return []
    pool: list[Exchange] = []
    seen: set[tuple] = set()
    for exchange in exchanges:
        key = (tuple(exchange.incoming), tuple(exchange.reply))
        if key not in seen:
            seen.add(key)
            pool.append(exchange)
    picked: list[Exchange] = []
    labels: defaultdict[str, int] = defaultdict(int)
    sessions: defaultdict[int, int] = defaultdict(int)
    reply_chars: set[str] = set()
    while pool and len(picked) < limit:
        def score(exchange: Exchange) -> float:
            label, action = situation(exchange)
            text = "".join(exchange.reply)
            novelty = len(set(text) - reply_chars) / max(1, len(set(text)))
            return (3 * bool(action) + 2 * novelty + min(len(text), 30) / 30
                    - 3 * labels[label] - 2 * sessions[exchange.session])
        best = max(pool, key=score)
        pool.remove(best)
        picked.append(best)
        labels[situation(best)[0]] += 1
        sessions[best.session] += 1
        reply_chars.update("".join(best.reply))
    return picked


def situation_items(exchanges: list[Exchange], limit: int = 6) -> list[str]:
    groups: defaultdict[str, list[Exchange]] = defaultdict(list)
    actions = {}
    for exchange in exchanges:
        label, action = situation(exchange)
        if action:
            groups[label].append(exchange)
            actions[label] = action
    items = []
    ranked = sorted(groups, key=lambda key: -len({e.session for e in groups[key]}))
    for label in ranked[:limit]:
        examples = groups[label]
        count = len({e.session for e in examples})
        confidence = (f"在 {count} 段会话中出现" if count > 1
                      else "单次观察，仅用于相似语境")
        quotes = "；".join(e.render() for e in select_exchanges(examples, 2))
        items.append(f"{label}：{actions[label]}（{confidence}）。原话：{quotes}")
    return items
