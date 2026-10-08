"""Local A/B runs with fixed regression cases and human preferences."""
import re
import uuid

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
    cases = evaluation.cases_for(root, routes)
    if not cases:
        raise ValueError('没有可供对比的回归用例')
    identity = uuid.uuid4().hex[:16]
    run = {'id': identity, 'created_at': storage.now(), 'fingerprint': payload['fingerprint'],
           'configs': {side: _config(payload.get(side)) for side in ('a', 'b')},
           'cases': cases, 'results': {}, 'choices': {}}
    storage.write(_path(root, identity), run)
    return decorate(root, run)


def decorate(root, run):
    return {**run, 'stale': run['fingerprint'] != versions.fingerprint(root),
            'total': len(run['cases']), 'completed': sum(len(v) for v in run['results'].values())}


def view(root):
    runs = [storage.load(path) for path in (storage.local_dir(root) / 'ab').glob('*.json')]
    runs.sort(key=lambda run: run['created_at'], reverse=True)
    return {'runs': [decorate(root, run) for run in runs], **versions.state(root)}


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
    return run, case, run['configs'][side]


def save(root, payload, result, routes):
    with storage.lock(root):
        run, case, _ = prepare(root, payload)
        if result['fingerprint'] != run['fingerprint']:
            raise ValueError('调用期间技能变化，未保存旧回复')
        run['results'].setdefault(case['id'], {})[payload['side']] = {
            **evaluation.static_check(case, redact(result['reply']), routes), 'seconds': result['seconds']}
        run['choices'].pop(case['id'], None)
        storage.write(_path(root, run['id']), run)
        return decorate(root, run)


def choose(root, payload):
    run, case, _ = prepare(root, {**payload, 'side': 'a'})
    if set(run['results'].get(case['id'], {})) != {'a', 'b'}:
        raise ValueError('两侧都完成后才能选择')
    if payload.get('choice') not in ('a', 'b', 'tie', 'neither'):
        raise ValueError('选择必须为 A、B、相当或都不合适')
    run['choices'][case['id']] = payload['choice']
    storage.write(_path(root, run['id']), run)
    return decorate(root, run)
