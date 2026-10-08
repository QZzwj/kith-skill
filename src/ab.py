"""Local A/B runs with fixed regression cases and human preferences."""
import re
import uuid
import secrets

from . import storage, versions, evaluation
from .privacy import redact


def _path(root, identity):
    if not re.fullmatch(r'[a-f0-9]{16}', str(identity or '')):
        raise ValueError('对比编号不合法')
    return storage.local_dir(root) / 'ab' / (identity + '.json')


def load(root, identity):
    run = storage.load(_path(root, identity))
    if not run:
        raise ValueError('对比不存在')
    return run


def _config(raw):
    if not isinstance(raw, dict) or not str(raw.get('model') or '').strip():
        raise ValueError('请填写 A 和 B 的模型名称')
    temperature = float(raw.get('temperature', .7))
    if not 0 <= temperature <= 2:
        raise ValueError('温度必须在 0 到 2 之间')
    return {'model': str(raw['model']).strip()[:200], 'base_url': str(raw.get('base_url') or '').strip()[:1000],
            'temperature': temperature, 'recipe': redact(str(raw.get('recipe') or ''))[:4000]}


def start(root, payload, routes):
    if payload.get('fingerprint') != versions.fingerprint(root):
        raise ValueError('内容已变化，请刷新后开始对比')
    if payload.get('pool') == 'holdout':
        from . import holdout
        held = holdout.view(root)
        if not held['enabled'] or held['stale']:
            raise ValueError('没有有效留出集，请先开启留出生成')
        cases = held['results']
    else:
        cases = evaluation.cases_for(root, routes)
    if not cases:
        raise ValueError('没有可供对比的回归用例')
    identity = uuid.uuid4().hex[:16]
    run = {'id': identity, 'created_at': storage.now(), 'fingerprint': payload['fingerprint'],
           'configs': {side: _config(payload.get(side)) for side in ('a', 'b')},
           'cases': cases, 'results': {}, 'choices': {}}
    followups = payload.get('followups', [])
    if not isinstance(followups, list) or len(followups) > 5 or any(not isinstance(s, str) or not s.strip() for s in followups):
        raise ValueError('追问必须是最多五条非空文本')
    run['followups'] = [redact(s.strip())[:1000] for s in followups]
    run['blind'] = bool(payload.get('blind'))
    run['order'] = {case['id']: ['a', 'b'] if secrets.randbelow(2) else ['b', 'a'] for case in cases}
    storage.write(_path(root, identity), run)
    return public(root, run)


def decorate(root, run):
    return {**run, 'stale': run['fingerprint'] != versions.fingerprint(root),
            'total': len(run['cases']), 'completed': sum(len(v) for v in run['results'].values())}


def public(root, run):
    data = decorate(root, run)
    if not run.get('blind'):
        return data
    reveal = bool(run.get('cases')) and all(case['id'] in run['choices'] for case in run['cases'])
    results, choices = {}, {}
    for case in run['cases']:
        order = run['order'][case['id']]
        results[case['id']] = {display: run['results'].get(case['id'], {}).get(actual)
                              for display, actual in zip(('a', 'b'), order)
                              if actual in run['results'].get(case['id'], {})}
        choice = run['choices'].get(case['id'])
        if choice:
            choices[case['id']] = ('a', 'b')[order.index(choice)] if choice in order else choice
    revealed_models = {case['id']: {display: run['configs'][actual]['model']
                       for display, actual in zip(('a', 'b'), run['order'][case['id']])}
                       for case in run['cases'] if case['id'] in run['choices']}
    summary = {side: {'model': run['configs'][side]['model'],
                     'wins': sum(choice == side for choice in run['choices'].values()),
                     'passed': sum(bool(pair.get(side, {}).get('passed')) for pair in run['results'].values()),
                     'seconds': round(sum(pair.get(side, {}).get('seconds', 0) for pair in run['results'].values()), 1)}
               for side in ('a', 'b')} if reveal else {}
    return {**data, 'configs': run['configs'] if reveal else {side: {'model': '选择完成后揭晓', 'base_url': '', 'recipe': ''} for side in ('a', 'b')},
            'results': results, 'choices': choices, 'order': run['order'] if reveal else {},
            'revealed': reveal, 'revealed_models': revealed_models, 'summary': summary}


def actual_side(run, display, case):
    if display not in ('a', 'b'):
        return display
    return run['order'][case['id']][('a', 'b').index(display)] if run.get('blind') else display


def view(root):
    runs = [storage.load(path) for path in (storage.local_dir(root) / 'ab').glob('*.json')]
    runs.sort(key=lambda run: run['created_at'], reverse=True)
    return {'runs': [public(root, run) for run in runs], **versions.state(root)}


def prepare(root, payload):
    run = load(root, payload.get('run'))
    if run['fingerprint'] != versions.fingerprint(root):
        raise ValueError('技能已变化，这份对比失效，请新建对比')
    side = payload.get('side')
    if side not in ('a', 'b'):
        raise ValueError('请选择 A 或 B')
    case = next((case for case in run['cases'] if case['id'] == payload.get('case')), None)
    if not case:
        raise ValueError('用例不存在')
    issue = evaluation.case_issue(case)
    if issue:
        raise ValueError('用例证据不足：' + issue + '；请重新生成技能并新建对比')
    return run, case, run['configs'][actual_side(run, side, case)]


def save(root, payload, result, routes):
    with storage.lock(root):
        run, case, _ = prepare(root, payload)
        if result['fingerprint'] != run['fingerprint']:
            raise ValueError('调用期间技能变化，未保存旧回复')
        side = actual_side(run, payload['side'], case)
        turns = result.get('turns', [])
        run['results'].setdefault(case['id'], {})[side] = {
            **evaluation.static_check(case, redact(result['reply']), routes), 'seconds': result['seconds'],
            'turns': [{**turn, 'reply': redact(turn['reply'])} for turn in turns],
            'turn_checks': [evaluation.static_check({**case, 'prompt': turn['prompt'], 'origin': 'feedback'}, turn['reply'], routes) for turn in turns]}
        run['choices'].pop(case['id'], None)
        storage.write(_path(root, run['id']), run)
        return public(root, run)


def choose(root, payload):
    run, case, _ = prepare(root, {**payload, 'side': 'a'})
    if set(run['results'].get(case['id'], {})) != {'a', 'b'}:
        raise ValueError('两侧都完成后才能选择')
    if payload.get('choice') not in ('a', 'b', 'tie', 'neither'):
        raise ValueError('选择必须为 A、B、相当或都不合适')
    run['choices'][case['id']] = actual_side(run, payload['choice'], case)
    storage.write(_path(root, run['id']), run)
    return public(root, run)
