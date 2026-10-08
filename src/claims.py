"""Persistent human decisions, kept separate from original chat evidence."""
import hashlib
import re

from . import storage, versions, specificity
from .privacy import redact
from .verify import QUOTE_RE


def identity(target, text):
    # Bind decisions to the observed wording, not a mutable ordinal.
    quotes = sorted(set(QUOTE_RE.findall(text)))
    basis = '\n'.join(quotes) if quotes else re.sub(r'\s+', '', text)
    return hashlib.sha256((target + '\n' + basis).encode()).hexdigest()[:24]


def build(persona, msgs, target):
    cards = []
    for item in specificity.build(persona, msgs, target)['traits']:
        evidence = item['evidence']
        words = {word for row in evidence for word in specificity._tokens(row['quote']) if len(word) >= 3}
        counters = [{'message': index, 'quote': msg.text} for index, msg in enumerate(msgs, 1)
                    if msg.speaker == target and re.search('不|没|别|从来|其实', msg.text)
                    and any(word in msg.text for word in words)
                    and index not in {row['message'] for row in evidence}]
        cards.append({'id': identity(target, item['text']), 'text': item['text'],
                      'evidence': evidence, 'counter_candidates': counters[:5]})
    return {'schema_version': 1, 'target': target, 'cards': cards}


def decisions(root):
    return storage.load(storage.local_dir(root) / 'claim-decisions.json', {}) or {}


def apply(root, persona, target):
    saved = decisions(root)
    result = {key: list(value) for key, value in persona.items()}
    kept = []
    for text in result.get('人物特点', []):
        decision = saved.get(identity(target, text), {})
        if decision.get('status') == 'rejected':
            continue
        if decision.get('status') == 'rewritten':
            kept.append('人工修订（适用范围：' + decision['scope'] + '）：' + decision['replacement'])
        elif decision.get('status') == 'kept':
            kept.append('人工确认（适用范围：' + decision['scope'] + '）：' + text)
        else:
            kept.append(text)
    result['人物特点'] = kept
    return result


def view(root):
    data = storage.load(root / 'references/claims.json', {'cards': []})
    saved = decisions(root)
    return {**data, **versions.state(root),
            'cards': [{**card, 'decision': saved.get(card['id'], {})} for card in data['cards']]}


def prompt(root):
    data = view(root)
    lines = []
    for card in data['cards']:
        decision = card['decision']
        if decision.get('status') == 'rejected':
            lines.append('用户否定此观察，不采用：' + card['text'])
        elif decision.get('status') in ('kept', 'rewritten'):
            lines.append('用户审阅，适用范围：' + decision['scope'] + '；' +
                         (decision.get('replacement') or card['text']))
    return '\n'.join(['【人工审阅；不是原聊天证据】', *lines]) if lines else ''


def save(root, payload):
    with storage.lock(root):
        data = view(root)
        if payload.get('fingerprint') != data['fingerprint']:
            raise ValueError('内容已变化，请刷新后审阅')
        card = next((card for card in data['cards'] if card['id'] == payload.get('claim')), None)
        status = payload.get('status')
        if not card or status not in ('kept', 'rewritten', 'rejected', 'pending'):
            raise ValueError('请选择有效的人物结论和审阅操作')
        scope = redact(str(payload.get('scope') or '').strip())[:500]
        replacement = redact(str(payload.get('replacement') or '').strip())[:2000]
        if status in ('kept', 'rewritten') and not scope:
            raise ValueError('请填写适用范围')
        if status == 'rewritten' and not replacement:
            raise ValueError('请填写修订后的结论')
        saved = decisions(root)
        saved[card['id']] = {'status': status, 'scope': scope, 'replacement': replacement,
                             'time': storage.now(), 'original': card['text']}
        storage.write(storage.local_dir(root) / 'claim-decisions.json', saved)
        return view(root)
