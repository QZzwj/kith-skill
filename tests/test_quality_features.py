"""Focused checks for evidence quality, traceability, updates and A/B review."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src import ab, coverage, incremental, message_index, questions, specificity, storage, versions, cli
import contextlib
import io
from zipfile import ZipFile
from src.conversations import reply_exchanges
from src.models import Msg
from src.package import write_package
from src import evaluation, scenarios, offline


class QualityFeatureTests(unittest.TestCase):
    def setUp(self):
        day = datetime(2026, 1, 1, 12)
        self.messages = [
            Msg(day, '对方', '谢谢提醒'), Msg(day + timedelta(minutes=1), '目标', '请我喝水'),
            Msg(day + timedelta(days=2), '对方', '谢谢你又提醒我'),
            Msg(day + timedelta(days=2, minutes=1), '目标', '请我喝水'),
        ]

    def test_specificity_counts_target_quotes_and_cross_session_evidence(self):
        data = specificity.build({'人物特点': ['喜欢回礼：原话「请我喝水」']}, self.messages, '目标')
        item = data['traits'][0]
        self.assertEqual(item['quote_count'], 2)
        self.assertEqual(item['session_count'], 2)
        self.assertIn('请我喝', item['unique_words'])
        self.assertGreater(item['score'], 0)
        self.assertTrue(all(row['speaker'] == '目标' for row in item['evidence']))

    def test_coverage_keeps_missing_routes_and_maps_message_indices(self):
        routes = scenarios.build_scenarios(self.messages, '目标', '对方')
        data = coverage.build(routes, self.messages, '目标', '对方')
        thanks = next(row for row in data['matrix'] if row['label'] == '对方表达感谢')
        self.assertEqual(thanks['status'], 'covered')
        self.assertEqual(thanks['observed_inputs'], 2)
        self.assertTrue(thanks['message_indices'])
        missing = next(row for row in data['matrix'] if row['label'] == '被催或被提醒')
        self.assertIn(missing['status'], {'evidence_insufficient', 'missing_response'})

    def test_message_ids_are_stable_and_exchange_examples_point_back(self):
        first, second = message_index.build(self.messages), message_index.build(self.messages)
        self.assertEqual(first, second)
        exchanges = reply_exchanges(self.messages, '目标', '对方')
        self.assertEqual(exchanges[0].incoming_messages, [1])
        self.assertEqual(exchanges[0].reply_messages, [2])

    def test_questions_can_be_confirmed_or_rejected_without_entering_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'demo'
            write_package(root.parent, root.name, '# demo\n', '# memory\n',
                          extra={'references/questions.json': storage.dumps({'questions': [
                              {'id': 'q1', 'type': 'trait', 'status': 'pending', 'question': '是否适用？'}
                          ]})})
            view = questions.view(root)
            questions.answer(root, {'question': 'q1', 'status': 'confirmed', 'answer': '只适用于夜间聊天',
                                    'fingerprint': view['fingerprint']})
            self.assertEqual(questions.view(root)['questions'][0]['status'], 'confirmed')
            with (root.parent / 'demo.zip').open('rb') as fh:
                self.assertNotIn(b'answers.json', fh.read())

    def test_incremental_dedup_and_conflict_signal(self):
        existing = message_index.build(self.messages)
        added = [self.messages[0], Msg(datetime(2026, 1, 5, 12), '目标', '不去食堂了')]
        result = incremental.detect(
            existing, added, [{'id': 'm1', 'status': 'fact', 'text': '去过食堂',
                               'evidence': [{'quote': '已经去过食堂'}]}])
        self.assertEqual(result['duplicate_count'], 1)
        self.assertEqual(result['added_count'], 1)
        self.assertTrue(result['requires_review'])

    def test_ab_run_records_both_sides_and_human_choice(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'demo'
            routes = scenarios.build_scenarios(self.messages, '目标', '对方')
            write_package(root.parent, root.name, '# demo\n', '# memory\n', extra={
                'references/scenarios.json': storage.dumps(scenarios.package_data(routes)),
                'references/evaluation.json': storage.dumps({'cases': evaluation.build_cases(routes)}),
            })
            run = ab.start(root, {'fingerprint': versions.fingerprint(root),
                                  'a': {'model': 'local-a'}, 'b': {'model': 'local-b'}}, routes)
            case = run['cases'][0]
            for side in ('a', 'b'):
                run = ab.save(root, {'run': run['id'], 'case': case['id'], 'side': side},
                              {'fingerprint': run['fingerprint'], 'reply': '请我喝水', 'seconds': .1}, routes)
            run = ab.choose(root, {'run': run['id'], 'case': case['id'], 'choice': 'a', 'side': 'a'})
            self.assertEqual(run['choices'][case['id']], 'a')
            self.assertEqual(run['completed'], 2)

    def test_other_speaker_and_missing_times_do_not_inflate_personality(self):
        data = specificity.build({'人物特点': ['原话「谢谢提醒」', '温柔体贴']}, self.messages, '目标')
        self.assertTrue(all(t['quote_count'] == 0 and t['generalization_risk'] == 'high' for t in data['traits']))
        data = specificity.build({'人物特点': ['原话「请我喝水」']}, [Msg(None, '目标', '请我喝水')] * 4, '目标')
        self.assertEqual(data['traits'][0]['session_count'], 0)
        self.assertEqual(data['traits'][0]['generalization_risk'], 'medium')

    def test_no_reply_is_missing_response_and_one_session_is_insufficient(self):
        data = coverage.build([], [Msg(datetime(2026, 1, 1), '对方', '谢谢你')], '目标', '对方')
        row = next(r for r in data['matrix'] if r['label'] == '对方表达感谢')
        self.assertEqual(row['status'], 'missing_response')
        self.assertEqual(row['message_indices'], [1])
        routes = scenarios.build_scenarios(self.messages[:2], '目标', '对方')
        data = coverage.build(routes, self.messages[:2], '目标', '对方')
        self.assertEqual(next(r for r in data['matrix'] if r['label'] == '对方表达感谢')['status'], 'evidence_insufficient')

    def test_answers_require_scope_are_redacted_and_invalidate_after_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'demo'
            write_package(root.parent, root.name, '# demo\n', '# memory\n', extra={
                'references/questions.json': storage.dumps({'questions': [{'id': 'q', 'status': 'pending', 'question': '有效吗？'}]})})
            payload = {'question': 'q', 'status': 'confirmed', 'fingerprint': versions.fingerprint(root)}
            with self.assertRaisesRegex(ValueError, '适用范围'):
                questions.answer(root, payload)
            questions.answer(root, {**payload, 'answer': '现在有效 13800138000'})
            self.assertNotIn('13800138000', questions.prompt(root))
            questions.answer(root, {**payload, 'status': 'rejected'})
            self.assertIn('不要采用', questions.prompt(root))
            (root / 'SKILL.md').write_text('# modified', encoding='utf-8')
            self.assertTrue(questions.view(root)['stale'])
            self.assertEqual(questions.prompt(root), '')

    def test_incremental_merge_preserves_numbers_conflicts_custom_files_and_rollback(self):
        sample = Path(__file__).resolve().parents[1] / 'samples/demo-chat.json'
        with tempfile.TemporaryDirectory() as folder:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['--input', str(sample), '--me', '小蒯', '--target', '潘小雨',
                    '--name', 'demo', '--out', folder, '--no-llm', '--corpus-mb', '0']), 0)
            root = Path(folder) / 'demo'
            original = versions.current(root)['version']
            old_info, old_index = incremental.baseline(root)
            old_ledger = storage.load(root / 'references/memory-ledger.json')['memories']
            old_fact = next(item for item in old_ledger
                            if item['status'] in ('fact', 'plan', 'promise') and item['evidence'])
            custom = root / 'notes.md'
            custom.write_text('manual notes', encoding='utf-8')
            new = [Msg(datetime(2026, 10, 6, 12), '小蒯', '谢谢你提醒我'),
                   Msg(datetime(2026, 10, 6, 12, 1), '潘小雨', '请我喝水'),
                   Msg(datetime(2026, 10, 6, 12, 2), '潘小雨', '取消了：' + old_fact['evidence'][0]['quote'])]
            report = incremental.apply(root, new, {'fingerprint': versions.fingerprint(root)})
            self.assertTrue(report['applied'])
            self.assertEqual(report['added_count'], 3)
            self.assertTrue(report['requires_review'])
            self.assertIn(old_fact['id'], [item['memory_id'] for item in report['conflicts']])
            def assert_conflict_pending():
                ledger = storage.load(root / 'references/memory-ledger.json')['memories']
                conflicted = next(item for item in ledger if item['id'] == old_fact['id'])
                self.assertEqual(conflicted['status'], 'uncertain')
                self.assertEqual(conflicted['validity'], 'needs_confirmation')
                self.assertTrue(any(item['type'] == 'conflict' and item['source_id'] == old_fact['id']
                                    for item in questions.view(root)['questions']))
            assert_conflict_pending()
            for name in ('SKILL.md', 'references/memory.md'):
                self.assertIn('确认前不要作为当前事实', (root / name).read_text(encoding='utf-8'))
            merged_info, merged_index = incremental.baseline(root)
            self.assertEqual(merged_index['messages'][:len(old_index['messages'])], old_index['messages'])
            self.assertNotEqual(old_info['baseline_id'], merged_info['baseline_id'])
            self.assertEqual(custom.read_text(), 'manual notes')
            version = versions.current(root)['version']
            no_change = incremental.apply(root, new, {'fingerprint': versions.fingerprint(root)})
            self.assertFalse(no_change['applied'])
            self.assertEqual(versions.current(root)['version'], version)
            unrelated = [Msg(datetime(2026, 10, 7, 12), '潘小雨', '今天看到了两只小猫')]
            incremental.apply(root, unrelated, {'fingerprint': versions.fingerprint(root)})
            assert_conflict_pending()
            versions.rollback(root, original)
            self.assertEqual(incremental.baseline(root)[0]['baseline_id'], old_info['baseline_id'])
            self.assertEqual(incremental.preview(root, new, versions.fingerprint(root))['added_count'], 3)
            with ZipFile(Path(folder) / 'demo.zip') as archive:
                self.assertFalse(any('.kith' in name for name in archive.namelist()))

    def test_incremental_llm_only_receives_new_chat_and_failure_preserves_package(self):
        sample = Path(__file__).resolve().parents[1] / 'samples/demo-chat.json'
        with tempfile.TemporaryDirectory() as folder:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(['--input', str(sample), '--me', '小蒯', '--target', '潘小雨',
                    '--name', 'demo', '--out', folder, '--no-llm', '--corpus-mb', '0']), 0)
            root = Path(folder) / 'demo'
            old_info, old_index = incremental.baseline(root)
            duplicate = incremental.to_messages(old_index['messages'])[0]
            incoming = [duplicate, Msg(datetime(2026, 10, 6, 12), '小蒯', '星河书店几点开门'),
                        Msg(datetime(2026, 10, 6, 12, 1), '潘小雨', '星河书店十点开门')]
            fingerprint = versions.fingerprint(root)
            payload = {'fingerprint': fingerprint, 'use_llm': True, 'api_key': 'test-key-not-for-export',
                       'base_url': 'http://127.0.0.1', 'model': 'local-substitute'}
            with patch('src.llm.consult_llm', return_value=({}, {}, {})):
                with self.assertRaisesRegex(ValueError, '没有完整结果'):
                    incremental.apply(root, incoming, payload)
            self.assertEqual(versions.fingerprint(root), fingerprint)
            self.assertEqual(incremental.baseline(root)[0]['baseline_id'], old_info['baseline_id'])
            added = incoming[1:]
            def substitute(corpus, target, args, stats, relation):
                self.assertIn('星河书店', corpus)
                self.assertNotIn('烧烤', corpus)
                self.assertNotIn(duplicate.text, corpus)
                persona, memory = offline.distill(added, target, stats, relation=relation)
                return persona, memory, {}
            with patch('src.llm.consult_llm', side_effect=substitute) as mocked:
                report = incremental.apply(root, incoming, payload)
            mocked.assert_called_once()
            self.assertEqual(report['engine'], 'llm')
            self.assertEqual(report['added_count'], 2)
            self.assertEqual(report['duplicate_count'], 1)
            self.assertTrue(all(b'test-key-not-for-export' not in path.read_bytes()
                                for path in Path(folder).rglob('*') if path.is_file()))

    def test_ab_invalidates_after_edit_and_never_saves_config_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'demo'
            routes = scenarios.build_scenarios(self.messages, '目标', '对方')
            write_package(root.parent, root.name, '# demo', '# memory', extra={
                'references/evaluation.json': storage.dumps({'cases': evaluation.build_cases(routes)})})
            config = {'model': 'local', 'api_key': 'must-not-persist', 'temperature': .4, 'recipe': '更随口'}
            run = ab.start(root, {'fingerprint': versions.fingerprint(root), 'a': config, 'b': config}, routes)
            self.assertNotIn('api_key', run['configs']['a'])
            with self.assertRaisesRegex(ValueError, '两侧'):
                ab.choose(root, {'run': run['id'], 'case': run['cases'][0]['id'], 'choice': 'a'})
            (root / 'SKILL.md').write_text('# changed', encoding='utf-8')
            self.assertTrue(ab.view(root)['runs'][0]['stale'])
            with self.assertRaisesRegex(ValueError, '失效'):
                ab.prepare(root, {'run': run['id'], 'case': run['cases'][0]['id'], 'side': 'a'})
            self.assertTrue(all(b'must-not-persist' not in p.read_bytes() for p in storage.local_dir(root).rglob('*') if p.is_file()))


if __name__ == '__main__':
    unittest.main()
