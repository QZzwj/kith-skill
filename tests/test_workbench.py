"""Workbench integration checks using synthetic conversations and local HTTP."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from zipfile import ZipFile

from src import cli, evaluation, feedback, memory_ledger, privacy_review, scenarios, storage, versions, web
from src.models import Msg
from src.package import write_package


def conversation():
    start = datetime(2025, 1, 1, 12)
    return [Msg(start, '对方', '谢了 要不是你我又忘了'),
            Msg(start + timedelta(minutes=1), '目标', '请我喝水'),
            Msg(start + timedelta(days=1), '对方', '谢谢提醒'),
            Msg(start + timedelta(days=1, minutes=1), '目标', '请我喝水')]


class PackageFixture(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.out = Path(self.folder.name)
        self.root = self.out / 'demo'
        self.routes = scenarios.build_scenarios(conversation(), '目标', '对方')
        self.cases = evaluation.build_cases(self.routes)
        self.extra = {
            'references/scenarios.json': storage.dumps(scenarios.package_data(self.routes)),
            'references/evaluation.json': storage.dumps({'cases': self.cases}),
            'references/memory-ledger.json': storage.dumps({'memories': []}),
        }
        self.package()

    def package(self, skill='# 目标 · 人设\n\n请我喝水\n', extra=None):
        return write_package(self.out, 'demo', skill, '# 关系记忆\n',
                             extra=self.extra if extra is None else extra,
                             metadata={'audience': '本人', 'api_key': 'must-not-persist'})


class ScenarioTests(unittest.TestCase):
    def test_routes_are_grounded_in_actual_exchanges_across_sessions(self):
        routes = scenarios.build_scenarios(conversation(), '目标', '对方')
        route = scenarios.route('谢谢你提醒我', routes)
        self.assertIsNotNone(route)
        self.assertEqual(route['sessions'], 2)
        self.assertEqual(route['confidence'], 'repeated_observation')
        self.assertTrue(all(e['reply'] == ['请我喝水'] for e in route['examples']))
        self.assertIn(route['response_move'], scenarios.prompt('谢了', routes))

    def test_serious_distress_does_not_route_to_playful_thanks(self):
        routes = scenarios.build_scenarios(conversation(), '目标', '对方')
        self.assertIsNone(scenarios.route('谢谢，但我真的难受，别开玩笑', routes))
        self.assertEqual(scenarios.prompt('不相关的新话题', routes), '')


class MemoryTests(unittest.TestCase):
    def ledger(self, text, section='关系时间线', evidence=True):
        messages = [Msg(datetime(2025, 2, 3), '目标', text)] if evidence else []
        return memory_ledger.build({section: [f'原话「{text}」']}, messages)[0]

    def test_old_plans_and_promises_need_confirmation_and_dates_are_observations(self):
        for text, status in [('下次去食堂', 'plan'), ('答应你明天去', 'promise')]:
            with self.subTest(status=status):
                entry = self.ledger(text)
                self.assertEqual(entry['status'], status)
                self.assertEqual(entry['validity'], 'needs_confirmation')
                self.assertEqual(entry['time_start'], '2025-02-03')
                self.assertEqual(entry['date_semantics'], 'observed_in_chat')
                self.assertEqual(entry['evidence'][0]['quote'], text)

    def test_mentions_do_not_establish_completed_events(self):
        self.assertEqual(self.ledger('食堂二楼')['status'], 'mentioned')
        self.assertEqual(self.ledger('已经到食堂了')['status'], 'fact')
        entry = self.ledger('已经到食堂了', evidence=False)
        self.assertEqual(entry['status'], 'uncertain')
        self.assertEqual(entry['confidence'], 'uncertain')
        self.assertIsNone(entry['time_start'])

    def test_jokes_uncertainty_and_negation_are_not_completed_promises_or_facts(self):
        self.assertEqual(self.ledger('下次一定', section='inside_jokes')['status'], 'joke')
        self.assertEqual(self.ledger('可能已经去了')['status'], 'uncertain')
        self.assertEqual(self.ledger('我没去过那里')['status'], 'mentioned')
        self.assertEqual(self.ledger('保证不了明天一定去')['status'], 'uncertain')


class PrivacyTests(PackageFixture):
    def test_identifiers_locations_and_binary_sources_are_scanned(self):
        self.package('# 目标\n13800138000 a.person@example.com 11010519491231002X\n南京市\n',
                     {**self.extra, 'references/source/chat.db': b'\x00\xff\x81'})
        report = privacy_review.review(self.root)
        categories = {item['category'] for item in report['items']}
        self.assertTrue({'phone', 'email', 'id_or_card', 'location', 'binary'} <= categories)
        self.assertEqual(report['risk'], 'high')
        for item in report['items']:
            if item['category'] in ('phone', 'email', 'id_or_card'):
                self.assertNotEqual(item['text'], item['redacted'])

    def test_redacted_identifiers_do_not_still_report_as_raw_identifiers(self):
        items = privacy_review.scan_text('联系 [手机号] [邮箱] [身份证]')
        self.assertFalse(any(i['severity'] == 'high' for i in items))

    def test_confirmations_expire_when_any_managed_content_changes(self):
        self.package('# 目标\n13800138000\n')
        report = privacy_review.review(self.root)
        for item in report['items']:
            privacy_review.confirm(self.root, item['id'])
        self.assertEqual(privacy_review.with_confirmations(self.root, report)['unconfirmed'], 0)
        (self.root / 'references/memory.md').write_text('另一份记忆', encoding='utf-8')
        report = privacy_review.review(self.root)
        self.assertGreater(privacy_review.with_confirmations(self.root, report)['unconfirmed'], 0)
        with self.assertRaises(ValueError):
            privacy_review.confirm(self.root, 'missing')


class FeedbackAndEvaluationTests(PackageFixture):
    def test_negative_feedback_adds_regression_case_and_scoped_correction(self):
        route_id = self.routes[0]['id']
        feedback.add(self.root, user_text='谢谢你提醒我', reply='不客气，请问还有什么需要帮助',
                     label='太客气', note='本人会开玩笑要一杯水', scenario_id=route_id)
        rows = feedback.read(self.root)
        report = evaluation.view(self.root, self.routes)
        failed_case = next(c for c in report['results'] if c.get('origin') == 'feedback')
        self.assertEqual(failed_case['prompt'], '谢谢你提醒我')
        self.assertEqual(report['checked'], 0)
        self.assertIn('减少客套', feedback.render_rules(rows, self.routes, text='谢谢提醒'))
        self.assertIn('本人会开玩笑要一杯水', feedback.render_rules(rows, self.routes, text='谢谢提醒'))
        self.assertEqual(feedback.render_rules(rows, self.routes, text='我真的难受'), '')
        self.assertEqual(feedback.summary(self.root)['labels']['太客气'], 1)

    def test_other_feedback_with_note_is_scoped_and_redacted(self):
        feedback.add(self.root, user_text='新的话题', reply='好', label='其他', note='不要提13800138000')
        rules = feedback.render_rules(feedback.read(self.root), self.routes, text='新的话题')
        self.assertIn('不要提[手机号]', rules)
        self.assertNotIn('13800138000', feedback.context(feedback.read(self.root)))
        self.assertEqual(feedback.render_rules(feedback.read(self.root), self.routes, text='不同话题'), '')

    def test_static_checks_do_not_require_copying_the_original_reply(self):
        case = self.cases[0]
        creative = evaluation.static_check(case, '下回记得带水', self.routes)
        self.assertTrue(creative['passed'])
        self.assertFalse(creative['quote_grounded'])
        self.assertFalse(evaluation.static_check(case, '不客气', self.routes)['passed'])
        self.assertFalse(evaluation.static_check(case, '', self.routes)['passed'])

    def test_reports_merge_and_invalidate_after_edits(self):
        fingerprint = versions.fingerprint(self.root)
        first, second = self.cases[:2]
        evaluation.save(self.root, {first['id']: '请我喝水'}, self.routes, fingerprint)
        report = evaluation.save(self.root, {second['id']: '给我带杯水'}, self.routes, fingerprint)
        self.assertEqual(report['checked'], 2)
        (self.root / 'SKILL.md').write_text('# 修改后的人设', encoding='utf-8')
        report = evaluation.view(self.root, self.routes)
        self.assertTrue(report['stale'])
        self.assertEqual(report['checked'], 0)
        with self.assertRaises(ValueError):
            evaluation.save(self.root, {first['id']: '旧回复'}, self.routes, fingerprint)

    def test_regeneration_uses_feedback_and_keeps_review_state_out_of_zip(self):
        sample = Path(__file__).resolve().parents[1] / 'samples/demo-chat.json'
        feedback.add(self.root, user_text='谢谢提醒', reply='不客气', label='太客气')
        argv = ['--input', str(sample), '--me', '小蒯', '--target', '潘小雨',
                '--name', 'demo', '--out', str(self.out), '--no-llm', '--corpus-mb', '0']
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(argv), 0)
        self.assertIn('试聊后的修正', (self.root / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertEqual(feedback.summary(self.root)['total'], 1)
        with ZipFile(self.out / 'demo.zip') as archive:
            self.assertFalse(any('.kith' in name or 'feedback.jsonl' in name for name in archive.namelist()))
            self.assertTrue({'references/scenarios.json', 'references/memory-ledger.json',
                             'references/evaluation.json'} <= set(archive.namelist()))


class VersionTests(PackageFixture):
    def test_rollback_preserves_unsaved_content_user_files_and_feedback(self):
        first = versions.current(self.root)['version']
        custom = self.root / 'references/custom.md'
        custom.write_text('用户自定义参考', encoding='utf-8')
        feedback.add(self.root, user_text='问', reply='答', label='像本人')
        self.package('# 目标 · 人设\n第二版\n', {**self.extra, 'references/new.md': '新增文件'})
        (self.root / 'SKILL.md').write_text('# 手改还未保存\n', encoding='utf-8')
        self.assertTrue(versions.state(self.root)['modified'])
        self.assertIn('SKILL.md', versions.diff(self.root, first)['changed'])
        versions.rollback(self.root, first)
        self.assertIn('请我喝水', (self.root / 'SKILL.md').read_text(encoding='utf-8'))
        self.assertFalse((self.root / 'references/new.md').exists())
        self.assertEqual(custom.read_text(encoding='utf-8'), '用户自定义参考')
        self.assertEqual(feedback.summary(self.root)['total'], 1)
        self.assertFalse(versions.state(self.root)['modified'])
        self.assertTrue(any(b'\xe6\x89\x8b\xe6\x94\xb9' in versions.read_version(self.root, v['version'])['SKILL.md']
                            for v in versions.list_versions(self.root)))
        with ZipFile(self.out / 'demo.zip') as archive:
            self.assertEqual(archive.read('SKILL.md'), (self.root / 'SKILL.md').read_bytes())
        self.assertNotIn('api_key', versions.current(self.root)['metadata'])

    def test_tampered_snapshot_is_rejected_before_modifying_current_files(self):
        first = versions.current(self.root)['version']
        self.package('# 当前内容\n')
        prior = (self.root / 'SKILL.md').read_bytes()
        snapshot = storage.local_dir(self.root) / 'versions' / first / 'files/SKILL.md'
        snapshot.write_text('篡改', encoding='utf-8')
        with self.assertRaises(ValueError):
            versions.rollback(self.root, first)
        self.assertEqual((self.root / 'SKILL.md').read_bytes(), prior)

    def test_invalid_paths_and_local_state_fail_before_package_mutation(self):
        prior = (self.root / 'SKILL.md').read_bytes()
        for name in ['../outside.md', '.kith/feedback.jsonl', 'manifest.json']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.package('# 错误内容', {name: '内容'})
        self.assertEqual((self.root / 'SKILL.md').read_bytes(), prior)

    def test_old_packages_use_zip_to_preserve_unmanaged_references(self):
        root = self.out / 'legacy'
        (root / 'references').mkdir(parents=True)
        (root / 'SKILL.md').write_text('# 旧版', encoding='utf-8')
        (root / 'references/memory.md').write_text('旧记忆', encoding='utf-8')
        (root / 'references/old.md').write_text('旧生成文件', encoding='utf-8')
        custom = root / 'references/custom.md'
        custom.write_text('自定义参考', encoding='utf-8')
        with ZipFile(self.out / 'legacy.zip', 'w') as archive:
            for name in ['SKILL.md', 'references/memory.md', 'references/old.md']:
                archive.write(root / name, name)
        write_package(self.out, 'legacy', '# 新版', '新记忆')
        self.assertFalse((root / 'references/old.md').exists())
        self.assertEqual(custom.read_text(encoding='utf-8'), '自定义参考')
        self.assertEqual(len(versions.list_versions(root)), 2)

    def test_failed_write_restores_previous_package_and_manifest(self):
        prior = versions.current(self.root)
        content = (self.root / 'SKILL.md').read_bytes()
        archive = (self.out / 'demo.zip').read_bytes()
        with patch('src.versions.record', side_effect=OSError('模拟写盘失败')):
            with self.assertRaises(OSError):
                self.package('# 未完成的新版本', {**self.extra, 'references/temporary.md': '新内容'})
        self.assertEqual(versions.current(self.root), prior)
        self.assertEqual((self.root / 'SKILL.md').read_bytes(), content)
        self.assertEqual((self.out / 'demo.zip').read_bytes(), archive)
        self.assertFalse((self.root / 'references/temporary.md').exists())


class HttpTests(PackageFixture):
    def setUp(self):
        super().setUp()
        self.out_patch = patch.object(web, 'OUT_ROOT', self.out)
        self.out_patch.start()
        self.addCleanup(self.out_patch.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), web._Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f'http://127.0.0.1:{self.server.server_port}'

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, action, payload=None, skill='demo'):
        path = f'/api/workbench/{skill}/{action}'
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8') if payload is not None else None
        request = Request(self.base + path, data=data, headers={'Content-Type': 'application/json'})
        try:
            response = urlopen(request, timeout=5)
        except HTTPError as exc:
            response = exc
        with response:
            body = response.read()
            return response.status, body if action == 'download' else json.loads(body)

    def test_get_endpoints_and_feedback_round_trip(self):
        for action in ['package', 'scenarios', 'memory', 'evaluation', 'feedback', 'versions', 'privacy', 'download']:
            with self.subTest(action=action):
                self.assertEqual(self.request(action)[0], 200)
        code, report = self.request('feedback', {'user': '谢谢你提醒我', 'reply': '不客气', 'label': '太客气'})
        self.assertEqual(code, 200)
        self.assertEqual(report['total'], 1)
        self.assertTrue(any(c.get('origin') == 'feedback' for c in self.request('evaluation')[1]['results']))
        self.assertEqual(self.request('feedback', {'label': '错误类型'})[0], 400)
        self.assertEqual(self.request('package', skill='missing')[0], 404)
        self.assertEqual(self.request('package', skill='..')[0], 404)

    def test_model_evaluation_saves_a_single_case_without_persisting_credentials(self):
        data = {'case': self.cases[0]['id'], 'fingerprint': versions.fingerprint(self.root),
                'api_key': 'test-only-key', 'base_url': 'http://local.invalid/v1', 'model': 'local-test'}
        with patch('src.web.llm_chat', return_value='请我喝水') as call:
            code, result = self.request('evaluate-model', data)
        self.assertEqual(code, 200)
        self.assertEqual(result['report']['checked'], 1)
        self.assertIn('【当前情境参考】', call.call_args.args[3])
        self.assertTrue(all(b'test-only-key' not in p.read_bytes() for p in storage.local_dir(self.root).rglob('*') if p.is_file()))

    def test_concurrent_edit_during_model_call_does_not_save_old_reply(self):
        data = {'case': self.cases[0]['id'], 'fingerprint': versions.fingerprint(self.root), 'api_key': 'test-key'}
        def edit(*args, **kwargs):
            (self.root / 'SKILL.md').write_text('# 调用中修改', encoding='utf-8')
            return '旧版本的回复'
        with patch('src.web.llm_chat', side_effect=edit):
            self.assertEqual(self.request('evaluate-model', data)[0], 400)
        self.assertEqual(self.request('evaluation')[1]['checked'], 0)

    def test_save_diff_rollback_and_stale_privacy_confirmation(self):
        version = versions.current(self.root)['version']
        fingerprint = versions.fingerprint(self.root)
        (self.root / 'SKILL.md').write_text('# 手改\n13800138000', encoding='utf-8')
        self.assertEqual(self.request('snapshot', {})[0], 200)
        self.assertIn('SKILL.md', self.request('diff?version=' + version)[1]['changed'])
        privacy = self.request('privacy')[1]
        self.assertEqual(self.request('privacy', {'item': privacy['items'][0]['id'], 'fingerprint': fingerprint})[0], 400)
        self.assertEqual(self.request('privacy', {'item': privacy['items'][0]['id'], 'fingerprint': privacy['fingerprint']})[0], 200)
        self.assertEqual(self.request('rollback', {'version': version})[0], 200)
        self.assertEqual(versions.fingerprint(self.root), fingerprint)

    def test_old_skill_without_structured_references_is_usable(self):
        root = self.out / 'legacy'
        root.mkdir()
        (root / 'SKILL.md').write_text('# 旧技能', encoding='utf-8')
        for action in ['package', 'scenarios', 'memory', 'evaluation', 'feedback', 'versions', 'privacy']:
            with self.subTest(action=action):
                self.assertEqual(self.request(action, skill='legacy')[0], 200)
        self.assertEqual(self.request('evaluation', skill='legacy')[1]['total'], 0)


if __name__ == '__main__':
    unittest.main()
