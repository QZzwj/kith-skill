"""Session-level test split. Test answers stay in local state, outside packages."""
import hashlib

from . import storage, versions, evaluation
from .conversations import split_sessions, reply_exchanges, situation
from .message_index import content_key


def training_feedback(rows, test_msgs):
    quotes = [msg.text for msg in test_msgs if len(msg.text) >= 4]
    return [row for row in rows if not any(quote in ' '.join(str(row.get(key, ''))
            for key in ('user', 'reply', 'note')) for quote in quotes)]


def split(msgs, percent):
    percent = int(percent)
    if not 0 <= percent <= 40:
        raise ValueError('留出比例必须在 0 到 40 之间')
    sessions = split_sessions(msgs)
    if not percent:
        return msgs, [], {'enabled': False}
    if len(sessions) < 3:
        raise ValueError('留出测评至少需要三段完整会话')
    count = min(len(sessions) - 2, max(1, int(len(sessions) * percent / 100)))
    ranked = sorted(range(len(sessions)), key=lambda i: hashlib.sha256(
        '\n'.join(content_key(msg) for msg in sessions[i]).encode()).hexdigest())
    chosen = set(ranked[:count])
    train = [msg for i, session in enumerate(sessions) if i not in chosen for msg in session]
    test = [msg for i, session in enumerate(sessions) if i in chosen for msg in session]
    return train, test, {'enabled': True, 'percent': percent, 'train_sessions': len(sessions) - count,
                         'test_sessions': count, 'test_id': hashlib.sha256(
                             '\n'.join(content_key(m) for m in test).encode()).hexdigest()[:16]}


def save(root, msgs, target, counterpart, metadata):
    cases = []
    for index, exchange in enumerate(reply_exchanges(msgs, target, counterpart), 1):
        label, action = situation(exchange)
        cases.append({'id': 'holdout-' + str(index), 'scenario': label,
                      'scenario_id': '', 'prompt': ' '.join(exchange.incoming),
                      'expected_move': action or '对照原聊天判断语气与接法',
                      'allowed_quotes': exchange.reply, 'origin': 'holdout',
                      'source': exchange.session, 'forbidden': []})
    storage.write(storage.local_dir(root) / 'holdout.json', {
        **metadata, 'target': target, 'fingerprint': versions.fingerprint(root),
        'cases': cases[:100], 'replies': {}, 'test_keys': [content_key(m) for m in msgs]})


def view(root):
    data = storage.load(storage.local_dir(root) / 'holdout.json', {}) or {}
    fresh = data.get('fingerprint') == versions.fingerprint(root)
    report = evaluation.report(data.get('cases', []), data.get('replies') if fresh else {}, [])
    return {**report, **versions.state(root), 'enabled': data.get('enabled', False),
            'stale': bool(data.get('enabled')) and not fresh,
            'test_id': data.get('test_id', ''), 'train_sessions': data.get('train_sessions', 0),
            'test_sessions': data.get('test_sessions', 0)}


def case_for(root, identity, fingerprint):
    data = view(root)
    if data['stale'] or fingerprint != data['fingerprint']:
        raise ValueError('留出测试集已失效，请用完整原记录重新生成留出版本')
    case = next((case for case in data['results'] if case['id'] == identity), None)
    if not case:
        raise ValueError('留出用例不存在')
    return case


def record(root, identity, reply, fingerprint):
    return record_many(root, {identity: reply}, fingerprint)


def record_many(root, replies, fingerprint):
    with storage.lock(root):
        if not isinstance(replies, dict):
            raise ValueError('请提交待检查回复')
        for identity in replies:
            case_for(root, identity, fingerprint)
        if fingerprint != versions.fingerprint(root) or view(root)['stale']:
            raise ValueError('留出测试集已失效，请重新生成')
        data = storage.load(storage.local_dir(root) / 'holdout.json', {})
        data.setdefault('replies', {}).update({identity: str(reply)[:4000] for identity, reply in replies.items()})
        storage.write(storage.local_dir(root) / 'holdout.json', data)
        return view(root)
