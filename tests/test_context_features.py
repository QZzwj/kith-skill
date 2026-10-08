"""Quality features tested with distinct synthetic sessions and local models."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from src import (ab, checkpoint, claims, cli, holdout, incremental, llm, message_index,
                 quote_links, retrieval, scenarios, semantic, storage, versions, web, feedback)
from src.analysis import analyse
from src.conversations import reply_exchanges
from src.models import Msg
from src.parsers import load_messages
import test_workbench as workbench_tests


def messages():
    result = []
    for i in range(8):
        start = datetime(2026, 1, i + 1, 12)
        result += [Msg(start, '对方', f'谢谢提醒，第{i}段独立场景'),
                   Msg(start + timedelta(minutes=1), '目标', f'请我喝水，第{i}段独立回复')]
    return result


class ContextTests(unittest.TestCase):
    def test_explicit_reply_pairs_original_input_not_adjacent_story(self):
        msgs = [Msg(None, '对方', '谢谢提醒', '1'),
                Msg(None, '对方', '都说朋友要搬走了', '2'),
                Msg(None, '目标', '[回复消息]请我喝水', '3', '1')]
        pair = reply_exchanges(msgs, '目标', '对方')
        self.assertEqual(len(pair), 1)
        self.assertEqual(pair[0].incoming, ['谢谢提醒'])
        self.assertEqual(pair[0].incoming_messages, [1])
        self.assertEqual(pair[0].reply, ['请我喝水'])
        self.assertEqual(pair[0].pairing, 'explicit_reference')
        self.assertTrue(msgs[-1].text.startswith('[回复消息]'))

    def test_duplicate_forward_and_same_speaker_references_are_rejected(self):
        for source in ([Msg(None, '对方', '谢谢', '1'), Msg(None, '对方', '其他', '1')],
                       [Msg(None, '目标', '谢谢', '1')], []):
            msgs = source + [Msg(None, '目标', '[回复消息]请我喝水', '2', '1')]
            self.assertFalse(reply_exchanges(msgs, '目标', '对方'))
        self.assertFalse(reply_exchanges([Msg(None, '目标', '[回复消息]请我喝水', '2', '1'),
                                          Msg(None, '对方', '谢谢', '1')], '目标', '对方'))

    def test_import_and_incremental_preserve_reply_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'chat.json'
            storage.write(path, [{'id': 7, 'speaker': '对方', 'text': '谢谢'},
                                 {'id': 8, 'speaker': '目标', 'text': '[回复消息]请我喝水', 'reply_to_message_id': 7}])
            msgs = load_messages(path)
            self.assertEqual(msgs[1].reply_to, '7')
            self.assertEqual(msgs[0].source_id, '7')
            self.assertEqual(incremental.to_messages(message_index.build(msgs)['messages']), msgs)
            csv = Path(folder) / 'chat.csv'
            csv.write_text('time,nickname,content,message_id,reply_to\n2026-01-01 12:00,对方,谢谢,7,\n2026-01-01 12:01,目标,[回复消息]请我喝水,8,7\n', encoding='utf-8')
            self.assertEqual(load_messages(csv)[1].reply_to, '7')

    def test_explicit_burst_is_not_truncated_and_sessions_are_not_inflated(self):
        msgs = [Msg(datetime(2026, 1, 1), '对方', '谢谢提醒', '1'),
                Msg(datetime(2026, 1, 1, 0, 1), '目标', '[回复消息]请我喝水', '2', '1')]
        for i in range(3):
            msgs.append(Msg(datetime(2026, 1, 1, 0, 2 + i), '目标', '补一句'))
        self.assertFalse(reply_exchanges(msgs, '目标', '对方'))
        msgs = msgs[:2] + [Msg(datetime(2026, 1, 1, 0, 2), '对方', '谢谢提醒', '3'),
                          Msg(datetime(2026, 1, 1, 0, 3), '目标', '[回复消息]请我喝水', '4', '3')]
        self.assertEqual(scenarios.build_scenarios(msgs, '目标', '对方')[0]['sessions'], 1)

    def test_offline_intents_and_ambiguous_routing(self):
        routes = scenarios.build_scenarios(messages(), '目标', '对方')
        self.assertEqual(semantic.assess('都说朋友搬走了', routes)['intent'], 'story')
        self.assertEqual(semantic.assess('我很难过，别开玩笑', routes)['intent'], 'comfort')
        self.assertEqual(semantic.assess('开玩笑啦哈哈', routes)['intent'], 'joke')
        self.assertEqual(semantic.assess('谢谢提醒', routes)['scenario_id'], routes[0]['id'])
        self.assertEqual(semantic.assess('所以呢', routes)['status'], 'uncertain')

    def test_model_routing_must_cite_real_context_and_valid_scenario(self):
        routes = scenarios.build_scenarios(messages(), '目标', '对方')
        history = [{'role': 'assistant', 'content': '刚才说错了'}]
        answer = {'intent': 'interaction', 'scenario_id': routes[0]['id'], 'reason': '核对前文',
                  'evidence': [{'turn': 0, 'quote': '说错了'}, {'turn': 1, 'quote': '所以呢'}]}
        sent = []
        def call(system, user):
            sent.append(json.loads(user))
            return json.dumps(answer, ensure_ascii=False)
        data = semantic.model_assess('所以呢', routes, history, call)
        self.assertEqual(data['method'], 'model')
        self.assertEqual(sent[0]['context'][0]['text'], '刚才说错了')
        for changed in ({'evidence': [{'turn': 0, 'quote': '不存在的话'}]}, {'scenario_id': 'invented'},
                        {'evidence': [{'turn': 10, 'quote': '所以呢'}]}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                semantic.model_assess('所以呢', routes, history, lambda *_: json.dumps({**answer, **changed}))

    def test_session_holdout_is_deterministic_disjoint_and_complete(self):
        train, held, info = holdout.split(messages(), 20)
        self.assertEqual(holdout.split(messages(), 20), (train, held, info))
        self.assertEqual(len(train) + len(held), len(messages()))
        self.assertFalse({message_index.content_key(m) for m in train} & {message_index.content_key(m) for m in held})
        self.assertEqual(len(held) % 2, 0)
        with self.assertRaises(ValueError):
            holdout.split(messages()[:4], 20)

    def test_short_followup_uses_previous_user_context(self):
        history = [{'role': 'user', 'content': '都说朋友搬走了'}, {'role': 'assistant', 'content': '后来呢？'}]
        decision = semantic.assess('所以呢', [], history)
        self.assertEqual(decision['intent'], 'story')
        self.assertEqual(decision['evidence'][0]['quote'], history[0]['content'])


class PackageContextTests(workbench_tests.PackageFixture):
    def generate(self, held=False):
        path = self.out / 'chat.json'
        storage.write(path, message_index.build(messages())['messages'])
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['--input', str(path), '--name', 'demo', '--out', str(self.out),
                                      '--target', '目标', '--me', '对方', '--no-llm',
                                      '--holdout-percent', '20' if held else '0']), 0)

    def test_held_answers_not_in_zip_training_baseline_or_prompt(self):
        self.generate(held=True)
        data = holdout.view(self.root)
        self.assertTrue(data['enabled'])
        self.assertGreater(data['total'], 0)
        local = storage.load(storage.local_dir(self.root) / 'holdout.json')
        train = incremental.baseline(self.root)[1]
        self.assertFalse(set(local['test_keys']) & {row['key'] for row in train['messages']})
        system = web._persona_prompt(web.PlayTarget(self.out, 'demo'), data['results'][0]['prompt'])
        with ZipFile(self.out / 'demo.zip') as archive:
            self.assertFalse(any('holdout' in name or '.kith' in name for name in archive.namelist()))
            content = '\n'.join(archive.read(name).decode('utf-8') for name in archive.namelist())
        for case in data['results']:
            for quote in case['allowed_quotes']:
                self.assertNotIn(quote, content)
                self.assertNotIn(quote, system)
        (self.root / 'SKILL.md').write_text('changed', encoding='utf-8')
        self.assertTrue(holdout.view(self.root)['stale'])
        with self.assertRaises(ValueError):
            holdout.record(self.root, data['results'][0]['id'], '嗯', versions.fingerprint(self.root))

    def test_claim_decisions_survive_regeneration_and_dont_become_evidence(self):
        self.generate()
        data = claims.view(self.root)
        self.assertTrue(data['cards'])
        card = data['cards'][0]
        with self.assertRaises(ValueError):
            claims.save(self.root, {'claim': card['id'], 'status': 'rewritten', 'replacement': '新描述', 'fingerprint': data['fingerprint']})
        claims.save(self.root, {'claim': card['id'], 'status': 'rejected', 'fingerprint': data['fingerprint']})
        self.assertIn('用户否定', claims.prompt(self.root))
        self.generate()
        self.assertEqual(claims.view(self.root)['cards'][0]['decision']['status'], 'rejected')
        persona = storage.load(self.root / 'references/observations.json')['persona']
        self.assertNotIn(card['text'], persona['人物特点'])
        with ZipFile(self.out / 'demo.zip') as archive:
            self.assertNotIn('claim-decisions.json', archive.namelist())

    def test_scoped_keep_and_rewrite_are_compiled_with_human_labels(self):
        self.generate()
        card = claims.view(self.root)['cards'][0]
        payload = {'claim': card['id'], 'fingerprint': versions.fingerprint(self.root), 'scope': '熟人玩笑'}
        claims.save(self.root, {**payload, 'status': 'kept'})
        self.generate()
        self.assertIn('人工确认（适用范围：熟人玩笑）', (self.root / 'SKILL.md').read_text(encoding='utf-8'))
        claims.save(self.root, {**payload, 'fingerprint': versions.fingerprint(self.root),
                               'status': 'rewritten', 'replacement': '收到感谢时可以简短接一句'})
        self.generate()
        self.assertIn('人工修订（适用范围：熟人玩笑）', (self.root / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertEqual(claims.view(self.root)['cards'][0]['decision']['status'], 'rewritten')

    def test_manual_link_updates_evidence_and_persists_on_regeneration(self):
        self.generate()
        reply, source = 4, 1
        state = versions.fingerprint(self.root)
        quote_links.save(self.root, {'reply': reply, 'source': source, 'fingerprint': state})
        full = incremental.to_messages(incremental.baseline(self.root)[1]['messages'])
        self.assertEqual(full[reply - 1].reply_to, full[source - 1].source_id)
        pair = next(e for e in reply_exchanges(full, '目标', '对方') if reply in e.reply_messages)
        self.assertEqual(pair.incoming_messages, [source])
        self.generate()
        full = incremental.to_messages(incremental.baseline(self.root)[1]['messages'])
        self.assertEqual(full[reply - 1].reply_to, full[source - 1].source_id)
        with self.assertRaises(ValueError):
            quote_links.save(self.root, {'reply': 1, 'source': 4, 'fingerprint': versions.fingerprint(self.root)})

    def test_manual_association_preserves_other_structured_references(self):
        msgs = [Msg(None, '对方', '谢谢提醒', 'real-source'), Msg(None, '目标', '请我喝水'),
                Msg(None, '目标', '[回复消息]小事', 'reply', 'real-source')]
        links = {message_index.content_key(msgs[1]): message_index.content_key(msgs[0])}
        applied = quote_links.apply(self.root, msgs, redacted=False, links=links)
        self.assertEqual(applied[0].source_id, 'real-source')
        self.assertEqual(applied[1].reply_to, applied[2].reply_to)

    def test_incremental_export_applies_scoped_trait_decision(self):
        self.generate()
        card = claims.view(self.root)['cards'][0]
        claims.save(self.root, {'claim': card['id'], 'status': 'rewritten', 'scope': '熟人玩笑',
                               'replacement': '只在轻松语境简短接话', 'fingerprint': versions.fingerprint(self.root)})
        added = [Msg(datetime(2026, 2, 1), '对方', '谢谢提醒'),
                 Msg(datetime(2026, 2, 1, 0, 1), '目标', '请我喝水')]
        incremental.apply(self.root, added, {'fingerprint': versions.fingerprint(self.root)})
        skill = (self.root / 'SKILL.md').read_text(encoding='utf-8')
        character = skill.split('## 人物特点\n', 1)[1].split('\n## ', 1)[0]
        self.assertNotIn(card['text'], character)
        self.assertIn('人工修订（适用范围：熟人玩笑）', character)

    def test_retrieval_is_bounded_relevant_and_preserves_memory_status(self):
        storage.write(self.root / 'references/memory-ledger.json', {'memories': [
            {'id': 'water', 'text': '下次请我喝水', 'status': 'plan', 'evidence': [{'message': 2}]},
            {'id': 'unrelated', 'text': '以前去过火星天文馆', 'status': 'mentioned', 'evidence': []}]})
        selected = retrieval.select(self.root, '那次喝水呢', limit=3)
        self.assertLessEqual(len(selected), 3)
        water = next(row for row in selected if row['id'] == 'water')
        self.assertEqual(water['status'], 'plan')
        self.assertEqual(water['messages'], [2])
        self.assertNotIn('unrelated', [row['id'] for row in selected])
        self.assertFalse(retrieval.select(self.root, '量子计算课程'))
        self.assertFalse(retrieval.select(self.root, '喝水', budget=5))

    def test_blind_ab_hides_mapping_until_vote_and_maps_to_actual_side(self):
        config = lambda model: {'model': model, 'base_url': 'http://test.invalid'}
        run = ab.start(self.root, {'fingerprint': versions.fingerprint(self.root),
            'a': config('model-a'), 'b': config('model-b'), 'blind': True, 'followups': ['然后呢？']}, self.routes)
        self.assertNotIn('model-a', storage.dumps(run))
        case = run['cases'][0]
        raw = ab.load(self.root, run['id'])
        self.assertEqual(set(raw['order'][case['id']]), {'a', 'b'})
        payload = {'run': run['id'], 'case': case['id']}
        for side in ('a', 'b'):
            actual = ab.actual_side(raw, side, case)
            self.assertEqual(ab.prepare(self.root, {**payload, 'side': side})[2]['model'], 'model-' + actual)
            ab.save(self.root, {**payload, 'side': side}, {'reply': actual, 'seconds': .1,
                    'fingerprint': run['fingerprint']}, self.routes)
        chosen = ab.choose(self.root, {**payload, 'choice': 'a'})
        self.assertEqual(ab.load(self.root, run['id'])['choices'][case['id']], raw['order'][case['id']][0])
        self.assertIn(case['id'], chosen['revealed_models'])
        self.assertEqual(chosen['choices'][case['id']], 'a')


class CheckpointTests(unittest.TestCase):
    def test_cache_binds_to_input_config_and_never_persists_key(self):
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(checkpoint_path=Path(folder) / 'checkpoint.json', resume=True, api_key='secret-test-key')
            first = checkpoint.Checkpoint(args, 'input-model-1', 2)
            first.record('batch1', '批次一', result={'text': 'secret-test-key'})
            first.record('batch2', '批次二', error=RuntimeError('failed secret-test-key'))
            self.assertNotIn('secret-test-key', args.checkpoint_path.read_text(encoding='utf-8'))
            resumed = checkpoint.Checkpoint(args, 'input-model-1', 2)
            self.assertEqual(resumed.cached('batch1'), {'text': '[API Key]'})
            self.assertIsNone(resumed.cached('batch2'))
            changed = checkpoint.Checkpoint(args, 'input-model-2', 2)
            self.assertIsNone(changed.cached('batch1'))

    def test_cancel_does_not_turn_into_offline_fallback(self):
        fake_job = SimpleNamespace(cancel_requested=True)
        checkpoint.attach(fake_job)
        try:
            with self.assertRaises(checkpoint.Cancelled):
                checkpoint.check_cancel()
        finally:
            checkpoint.attach()

    def test_real_distillation_reuses_success_and_retries_failed_batch(self):
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(checkpoint_path=Path(folder) / 'checkpoint.json', resume=True,
                api_key='test-key', base_url='http://local.invalid', model='test', llm_chars=1000,
                llm_batches=1, timeout=1, max_tokens=0, dry_run_llm=False, desc='', feedback_context='')
            stats = analyse(messages(), '目标')
            corpus = '对方：谢谢提醒\n目标：请我喝水'
            with contextlib.redirect_stderr(io.StringIO()), patch('src.llm.llm_call', side_effect=[
                    '{"人物特点":["收到感谢要回礼，原话「请我喝水」"]}', RuntimeError('synthetic failure')]):
                persona, memory, _ = llm.consult_llm(corpus, '目标', args, stats)
            self.assertTrue(persona)
            self.assertFalse(memory)
            with contextlib.redirect_stderr(io.StringIO()), patch('src.llm.llm_call', return_value='{"共同地点":["食堂"]}') as call:
                persona, memory, _ = llm.consult_llm(corpus, '目标', args, stats)
            self.assertEqual(call.call_count, 1)
            self.assertTrue(persona)
            self.assertEqual(memory['共同地点'], ['食堂'])

    def test_cancel_after_call_keeps_result_and_resumes_remaining_tasks(self):
        with tempfile.TemporaryDirectory() as folder:
            args = SimpleNamespace(checkpoint_path=Path(folder) / 'checkpoint.json', resume=True,
                api_key='test-key', base_url='http://local.invalid', model='test', llm_chars=1000,
                llm_batches=1, timeout=1, max_tokens=0, dry_run_llm=False, desc='', feedback_context='')
            job = SimpleNamespace(cancel_requested=False, progress={}, out_dir=Path(folder), name='demo')
            checkpoint.attach(job)
            def cancel(*args, **kwargs):
                job.cancel_requested = True
                return '{"人物特点":["原话「请我喝水」"]}'
            try:
                with contextlib.redirect_stderr(io.StringIO()), patch('src.llm.llm_call', side_effect=cancel), self.assertRaises(checkpoint.Cancelled):
                    llm.consult_llm('对方：谢谢\n目标：请我喝水', '目标', args, analyse(messages(), '目标'))
                self.assertEqual(job.progress['completed'], 1)
            finally:
                checkpoint.attach()
            with contextlib.redirect_stderr(io.StringIO()), patch('src.llm.llm_call', return_value='{"共同地点":["食堂"]}') as call:
                llm.consult_llm('对方：谢谢\n目标：请我喝水', '目标', args, analyse(messages(), '目标'))
            self.assertEqual(call.call_count, 1)

    def test_endpoint_usage_reaches_job_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            job = SimpleNamespace(cancel_requested=False, progress={}, out_dir=Path(folder), name='demo')
            checkpoint.attach(job)
            args = SimpleNamespace(checkpoint_path=Path(folder) / 'checkpoint.json', resume=False, api_key='test-key')
            try:
                saved = checkpoint.Checkpoint(args, 'signature', 1)
                checkpoint.capture_usage({'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120})
                saved.record('batch', '批次', result={'text': '结果'})
                self.assertEqual(job.progress['usage']['total_tokens'], 120)
            finally:
                checkpoint.attach()


class ContextHttpTests(workbench_tests.PackageFixture):
    request = workbench_tests.HttpTests.request
    stop_server = workbench_tests.HttpTests.stop_server
    generate = PackageContextTests.generate

    def setUp(self):
        super().setUp()
        from http.server import ThreadingHTTPServer
        self.out_patch = patch.object(web, 'OUT_ROOT', self.out)
        self.out_patch.start()
        self.addCleanup(self.out_patch.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), web._Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f'http://127.0.0.1:{self.server.server_port}'
    def test_multiturn_ab_uses_each_models_own_history(self):
        run = ab.start(self.root, {'fingerprint': versions.fingerprint(self.root),
            'a': {'model': 'a'}, 'b': {'model': 'b'}, 'followups': ['然后呢？']}, self.routes)
        seen = []
        def model(base, key, name, system, turns, **kwargs):
            seen.append((name, [dict(t) for t in turns]))
            return name + '-自己的回复'
        with patch('src.web.llm_chat', side_effect=model):
            for side in ('a', 'b'):
                code, data = self.request('ab', {'mode': 'run', 'run': run['id'], 'case': run['cases'][0]['id'],
                                                 'side': side, 'api_key': 'test-key'})
                self.assertEqual(code, 200)
        self.assertEqual(len(seen), 4)
        for name, turns in (seen[1], seen[3]):
            self.assertEqual(turns[-2]['content'], name + '-自己的回复')
        self.assertEqual(len(data['results'][run['cases'][0]['id']]['a']['turns']), 2)

    def test_routing_and_retrieved_sources_return_from_chat(self):
        with patch('src.web.llm_chat', return_value='请我喝水'):
            code, data = self.request('evaluate-model', {'case': self.cases[0]['id'], 'api_key': 'test-key',
                                                       'fingerprint': versions.fingerprint(self.root)})
        self.assertEqual(code, 200)
        self.assertIn('routing', data)
        self.assertTrue(data['retrieved'])
        self.assertTrue(data['retrieved'][0]['messages'])

    def test_held_model_ignores_old_feedback_and_live_annotations(self):
        _, held, _ = holdout.split(messages(), 20)
        old_answer = held[1].text
        feedback.add(self.root, user_text=held[0].text, reply=old_answer, label='太客气', note=old_answer)
        self.generate(held=True)
        self.assertNotIn(old_answer, (self.root / 'SKILL.md').read_text(encoding='utf-8'))
        data = holdout.view(self.root)
        case = data['results'][0]
        feedback.add(self.root, user_text=case['prompt'], reply=old_answer, label='太客气', note=old_answer)
        with patch('src.web.llm_chat', return_value='新的独立回复') as call:
            code, result = self.request('holdout-model', {'case': case['id'], 'api_key': 'test-key',
                                                        'fingerprint': data['fingerprint']})
        self.assertEqual(code, 200)
        self.assertNotIn(old_answer, call.call_args.args[3])
        self.assertEqual(result['report']['checked'], 1)

    def test_manual_link_http_rejects_wrong_speaker_and_stale_state(self):
        self.generate()
        fingerprint = versions.fingerprint(self.root)
        self.assertEqual(self.request('quote-link', {'reply': 2, 'source': 1, 'fingerprint': 'stale'})[0], 400)
        self.assertEqual(self.request('quote-link', {'reply': 3, 'source': 2, 'fingerprint': fingerprint})[0], 400)
        self.assertEqual(self.request('quote-link', {'reply': 2, 'source': 1, 'fingerprint': fingerprint})[0], 200)

    def test_model_context_option_uses_requested_endpoint_and_returns_evidence(self):
        answer = {'intent': 'interaction', 'scenario_id': self.routes[0]['id'], 'reason': '表达感谢',
                  'evidence': [{'turn': 0, 'quote': self.cases[0]['prompt']}]}
        with patch('src.web.llm_call', return_value=json.dumps(answer, ensure_ascii=False)) as context_call, \
                patch('src.web.llm_chat', return_value='请我喝水'):
            code, result = self.request('evaluate-model', {'case': self.cases[0]['id'], 'api_key': 'test-key',
                'base_url': 'http://local.invalid/v1', 'model': 'context-test', 'semantic_model': True,
                'fingerprint': versions.fingerprint(self.root)})
        self.assertEqual(code, 200)
        self.assertEqual(result['routing']['method'], 'model')
        self.assertEqual(context_call.call_args.args[:3], ('http://local.invalid/v1', 'test-key', 'context-test'))

    def test_cancel_endpoint_exits_running_job_without_publishing(self):
        from urllib.request import Request, urlopen
        started, release = threading.Event(), threading.Event()
        job = web.Job('cancel-test', [], self.out, 'cancelled-demo')
        web._JOBS[job.id] = job
        self.addCleanup(lambda: web._JOBS.pop(job.id, None))
        self.addCleanup(release.set)
        def run(argv):
            started.set()
            if not release.wait(5):
                raise RuntimeError('test worker timed out')
            checkpoint.check_cancel()
            return 0
        with patch('src.web.cli.main', side_effect=run):
            worker = threading.Thread(target=web._run_job, args=(job,))
            worker.start()
            self.assertTrue(started.wait(3))
            request = Request(self.base + '/api/cancel/' + job.id, data=b'{}', headers={'Content-Type': 'application/json'})
            with urlopen(request, timeout=5) as response:
                data = json.loads(response.read())
            self.assertTrue(data['cancel_requested'])
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(job.state, 'cancelled')
        self.assertEqual(job.code, 130)
        self.assertFalse((self.out / 'cancelled-demo' / 'SKILL.md').exists())
