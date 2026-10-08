"""Private generation checkpoints and cooperative cancellation."""
import hashlib
import json
import threading

from . import storage
from .privacy import redact

_CONTEXT = threading.local()


class Cancelled(BaseException):
    pass


def attach(job=None):
    _CONTEXT.job = job


def check_cancel():
    job = getattr(_CONTEXT, 'job', None)
    if job and job.cancel_requested:
        raise Cancelled('已停止；成功批次已保存，可勾选续跑')


def notify(data):
    job = getattr(_CONTEXT, 'job', None)
    if job:
        with storage.lock(job.out_dir / job.name):
            job.progress.update(data)


def capture_usage(usage):
    if not isinstance(usage, dict):
        return
    current = getattr(_CONTEXT, 'usage', {})
    for key in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        value = usage.get(key)
        if type(value) is int and value >= 0:
            current[key] = current.get(key, 0) + value
    _CONTEXT.usage = current


def identity(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class Checkpoint:
    def __init__(self, args, signature, total):
        self.path = getattr(args, 'checkpoint_path', None)
        old = storage.load(self.path, {}) if self.path and getattr(args, 'resume', False) else {}
        self.data = old if old.get('signature') == signature else {'signature': signature, 'steps': {}}
        self.secret = getattr(args, 'api_key', '')
        self.reused = 0
        self.total = total
        _CONTEXT.usage = {}
        self.publish()

    def publish(self):
        steps = list(self.data['steps'].values())
        if self.path:
            storage.write(self.path, self.data)
        notify({'total': max(self.total, len(steps)), 'completed': sum(s['status'] == 'done' for s in steps),
                'failed': sum(s['status'] == 'failed' for s in steps), 'reused': self.reused,
                'usage': getattr(_CONTEXT, 'usage', {})})

    def cached(self, key):
        check_cancel()
        step = self.data['steps'].get(key, {})
        if step.get('status') == 'done':
            self.reused += 1
            self.publish()
            return step['result']

    def record(self, key, label, result=None, error=None):
        text = json.dumps(result, ensure_ascii=False) if result is not None else ''
        if self.secret:
            text = text.replace(self.secret, '[API Key]')
        step = {'label': label, 'status': 'failed' if error else 'done', 'time': storage.now()}
        if error:
            detail = str(error)
            if self.secret:
                detail = detail.replace(self.secret, '[API Key]')
            step['error'] = redact(detail)[:500]
        else:
            step['result'] = json.loads(text)
        self.data['steps'][key] = step
        self.publish()
