"""Real-process workbench smoke check, using synthetic data and a model substitute.

Run with ``python tests/smoke.py``. No external service or API key is needed.
"""
from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
TEST_KEY = 'local-test-only-key'


def request(base: str, path: str, payload=None, *, raw=None):
    data = raw if raw is not None else (
        None if payload is None else json.dumps(payload, ensure_ascii=False).encode())
    headers = {'Content-Type': 'application/octet-stream' if raw is not None else 'application/json'}
    req = Request(base + path, data=data, headers=headers if data is not None else {})
    with urlopen(req, timeout=15) as response:
        body = response.read()
        return response.status, (json.loads(body.decode())
            if response.headers.get_content_type() == 'application/json' else body)


def worker() -> int:
    """Run the actual entry point; stdin controls graceful shutdown for all OSes."""
    from http.server import ThreadingHTTPServer
    from unittest.mock import patch
    from src import web

    def controlled_server(*args, **kwargs):
        server = ThreadingHTTPServer(*args, **kwargs)

        def control():
            if sys.stdin.readline().strip() == 'stop':
                server.shutdown()

        threading.Thread(target=control, daemon=True).start()
        print(json.dumps({'smoke_ready': True, 'port': server.server_port,
                          'session': str(web.SESSION_DIR)}), flush=True)
        return server

    with patch.object(web, 'ThreadingHTTPServer', side_effect=controlled_server), \
         patch.object(web, 'llm_chat', return_value='请我喝水'):
        return web.main(['--port', '0', '--no-open'])


def check_zip(data: bytes) -> None:
    with ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert 'SKILL.md' in names and 'references/memory.md' in names
        assert all('.kith' not in name and 'feedback' not in name for name in names), names
        assert all(TEST_KEY.encode() not in archive.read(name) for name in names)


def run() -> dict:
    checks, output = [], []
    ready = queue.Queue()
    with tempfile.TemporaryDirectory(prefix='kith-smoke-') as folder:
        root = Path(folder)
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        process = subprocess.Popen([sys.executable, '-u', str(Path(__file__).resolve()), '--worker'],
            cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, encoding='utf-8')

        def collect():
            for line in process.stdout:
                output.append(line.rstrip())
                try:
                    item = json.loads(line)
                    if item.get('smoke_ready'):
                        ready.put(item)
                except (ValueError, AttributeError):
                    pass

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        session = None
        try:
            try:
                info = ready.get(timeout=15)
            except queue.Empty:
                raise AssertionError('Server did not start: ' + '\n'.join(output))
            session = Path(info['session'])
            assert session.is_dir(), session
            base = f"http://127.0.0.1:{info['port']}"
            status, html = request(base, '/')
            assert status == 200 and b'kith-skill' in html
            status, skills = request(base, '/api/skills')
            assert status == 200 and skills == {'skills': []}
            checks.append('independent process startup, home page and /api/skills')

            status, parsed = request(base, '/api/parse?name=demo-chat.json',
                                     raw=(REPO / 'samples/demo-chat.json').read_bytes())
            assert status == 200 and parsed['total'] == 123, parsed
            assert any(session.rglob('*.json')), 'Uploaded input did not reach the session directory'
            status, job = request(base, '/api/run', {'token': parsed['token'], 'name': 'smoke',
                'me': '小蒯', 'target': '潘小雨', 'no_llm': True, 'api_key': TEST_KEY})
            assert status == 200, job
            job_id = job['job']
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                _, result = request(base, '/api/job/' + job_id)
                if result['state'] in ('done', 'failed'):
                    break
                time.sleep(.05)
            assert result['state'] == 'done' and result['code'] == 0, result
            checks.append('sample upload, parse and offline generation via HTTP')
            skill_root = root / 'out/smoke'
            for name in ('SKILL.md', 'references/memory.md', 'references/scenarios.json',
                         'references/evaluation.json', 'references/specificity.json',
                         'references/coverage.json', 'references/message-index.json',
                         'references/questions.json'):
                assert (skill_root / name).is_file(), name
            assert (root / 'out/smoke.zip').is_file()
            _, skills = request(base, '/api/skills')
            assert any(item['name'] == 'smoke' for item in skills['skills'])
            checks.append('SKILL, memory, scenarios, evaluation, quality artifacts and ZIP')

            _, trial = request(base, '/api/chat', {'skill': 'smoke', 'api_key': TEST_KEY,
                'base_url': 'http://local.invalid/v1', 'model': 'local-substitute',
                'messages': [{'role': 'user', 'content': '谢谢你提醒我'}]})
            assert trial.get('reply') == '请我喝水', trial
            checks.append('trial chat with local model substitute')
            _, feedback = request(base, '/api/workbench/smoke/feedback', {'label': '像本人',
                'user': '谢谢你提醒我', 'reply': trial['reply'], 'version': trial['fingerprint']})
            assert feedback['total'] == 1, feedback
            assert (root / 'out/.kith/smoke/feedback.jsonl').is_file()
            checks.append('feedback persisted outside package')
            _, privacy = request(base, '/api/workbench/smoke/privacy')
            assert 'items' in privacy, privacy
            checks.append('privacy review')
            _, archive = request(base, '/api/workbench/smoke/download')
            check_zip(archive)
            assert all(TEST_KEY.encode() not in path.read_bytes()
                       for path in (root / 'out').rglob('*') if path.is_file())
            checks.append('ZIP excludes local state, feedback and API key')
        finally:
            if process.poll() is None:
                try:
                    process.stdin.write('stop\n')
                    process.stdin.flush()
                    process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    process.kill()
                    process.wait(timeout=5)
            reader.join(timeout=3)
            process.stdin.close()
            process.stdout.close()
        assert process.returncode == 0, (process.returncode, output)
        assert session is not None and not session.exists(), session
        assert not reader.is_alive()
        checks.append('entry-point cleanup and normal process exit (code 0)')
    assert not root.exists(), root
    checks.append('temporary workspace removed')
    return {'passed': checks, 'model': 'local substitute'}


if __name__ == '__main__':
    if '--worker' in sys.argv:
        raise SystemExit(worker())
    print(json.dumps(run(), ensure_ascii=False, indent=2))
