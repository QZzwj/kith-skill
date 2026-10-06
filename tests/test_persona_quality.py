import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from src import cli, offline, quality, verify
from src.analysis import analyse, reply_gaps, sample_sessions
from src.conversations import (SESSION_SEPARATOR, pack_windows, reply_exchanges,
                               select_exchanges, situation, split_sessions)
from src.llm import _bounded_drafts, _halve, consult_llm
from src.models import Msg, Stats
from src.parsers import load_messages
from src.privacy import redact
from src.relation import detect
from src.web import Job, _example_ok, _exchanges, _persona_name, _play_examples, _rows


def msg(minutes, speaker, text, day=1):
    return Msg(datetime(2025, 1, day, 12, 0) + timedelta(minutes=minutes), speaker, text)


class ConversationBoundaryTests(unittest.TestCase):
    def test_sessions_and_third_speaker_block_cross_pairing(self):
        messages = [
            msg(0, "对方", "旧话"),
            msg(1, "系统", "群里插话"),
            msg(2, "目标", "不应配上"),
            msg(40, "对方", "新会话"),
            msg(41, "目标", "新回复"),
        ]
        exchanges = reply_exchanges(messages, "目标", "对方")
        self.assertEqual([(e.incoming, e.reply) for e in exchanges], [(["新会话"], ["新回复"])])

    def test_burst_is_kept_and_specific_situation_is_detected(self):
        exchange = reply_exchanges([
            msg(0, "对方", "烧烤那次"),
            msg(1, "目标", "……那叫改期"),
            msg(2, "目标", "别急"),
        ], "目标", "对方")[0]
        self.assertEqual(exchange.reply, ["……那叫改期", "别急"])
        self.assertEqual(situation(exchange)[0], "被指出说法或承诺有问题")

    def test_sampling_budget_and_years(self):
        messages = [msg(0, "对方", "一月对话", day=1), msg(1, "目标", "一月回复", day=1),
                    msg(0, "对方", "二月对话", day=2), msg(1, "目标", "二月回复", day=2)]
        sample, used = sample_sessions(messages, "目标", 500, window_chars=500)
        self.assertEqual(used, len(sample))
        self.assertLessEqual(used, 500)
        self.assertIn("2025-01", sample)

    def test_pack_windows_does_not_split_session_separator(self):
        corpus = "【会话 1】\na\n\n---\n\n【会话 2】\nb"
        pieces, dropped = pack_windows(corpus, 18, 2)
        self.assertEqual(dropped, 0)
        self.assertEqual(len(pieces), 2)
        self.assertTrue(all("【会话" in p for p in pieces))

    def test_time_reversal_and_media_break_pairing(self):
        messages = [msg(5, "对方", "昨天那句"), msg(0, "目标", "回到旧记录"),
                    msg(1, "对方", "问题一"), msg(2, "目标", "[图片]"),
                    msg(3, "对方", "问题二"), msg(4, "目标", "回答二")]
        self.assertEqual(len(split_sessions(messages)), 2)
        self.assertEqual([e.reply for e in reply_exchanges(messages, "目标", "对方")], [["回答二"]])

    def test_examples_cover_different_sessions(self):
        messages = []
        for day in (1, 2, 3):
            for minute in (0, 2, 4, 6):
                messages += [msg(minute, "对方", f"谢了 {day}-{minute}", day),
                             msg(minute + 1, "目标", f"请我喝水 {day}-{minute}", day)]
        picks = select_exchanges(reply_exchanges(messages, "目标", "对方"), 3)
        self.assertEqual(len({e.session for e in picks}), 3)

    def test_long_session_keeps_complete_messages_under_each_batch_budget(self):
        messages = [msg(i, "目标" if i % 2 else "对方", f"第{i}句的完整内容") for i in range(20)]
        sample, used = sample_sessions(messages, "目标", 1200, window_chars=240)
        self.assertLessEqual(used, 1200)
        for window in sample.split(SESSION_SEPARATOR):
            self.assertLessEqual(len(window), 240)
            for line in window.splitlines()[1:]:
                self.assertTrue(line.endswith("完整内容"))
        self.assertEqual(sample_sessions(messages, "目标", 40), ("", 0))

    def test_pack_accounts_for_separators_and_skips_oversize_without_truncation(self):
        units = ["a" * 19, "b" * 19, "c" * 200, "d" * 19]
        pieces, dropped = pack_windows(SESSION_SEPARATOR.join(units), 45, 2)
        self.assertEqual(dropped, 1)
        self.assertTrue(all(len(piece) <= 45 for piece in pieces))
        self.assertEqual(sorted(SESSION_SEPARATOR.join(pieces).split(SESSION_SEPARATOR)), sorted([units[0], units[1], units[3]]))

    def test_sample_covers_months_in_chronological_order(self):
        messages = []
        for month in (1, 2, 3):
            base = datetime(2025, month, 1, 12)
            messages += [Msg(base, "对方", f"第{month}月消息"), Msg(base + timedelta(minutes=1), "目标", "短回复")]
        sample, used = sample_sessions(messages, "目标", 1000)
        self.assertEqual(used, len(sample))
        self.assertLess(sample.index("2025-01"), sample.index("2025-02"))
        self.assertLess(sample.index("2025-02"), sample.index("2025-03"))


class StatisticsTests(unittest.TestCase):
    def test_target_late_night_and_reply_gap_do_not_use_other_side_or_new_session(self):
        messages = [
            Msg(datetime(2025, 1, 1, 23, 30), "对方", "对方深夜"),
            Msg(datetime(2025, 1, 1, 23, 31), "目标", "目标回复"),
            Msg(datetime(2025, 1, 2, 12, 0), "对方", "新会话"),
            Msg(datetime(2025, 1, 2, 12, 31), "目标", "不应算半小时以上"),
        ]
        stats = analyse(messages, "目标")
        self.assertEqual(stats.timed_total, 2)
        self.assertEqual(stats.late_night, 1)
        self.assertEqual(stats.reply_gap, 1.0)


class QualityFilterTests(unittest.TestCase):
    def test_generic_and_cross_session_pair_are_removed_and_local_examples_fill(self):
        messages = [msg(0, "对方", "烧烤那次"), msg(1, "目标", "……那叫改期")]
        stats = analyse(messages, "目标")
        persona = {
            "人物特点": ["幽默风趣"],
            "情境策略": ["对方：「烧烤那次」 → 我：「不存在的回复」"],
            "接话方式": ["对方：「烧烤那次」 → 我：「不存在的回复」"],
        }
        result, notes = quality.prepare_persona(persona, messages, "目标", stats)
        self.assertFalse(result["人物特点"])
        self.assertTrue(result["情境策略"])
        self.assertTrue(result["接话方式"])
        self.assertTrue(any("筛除" in note for note in notes))

    def test_both_quotes_exist_but_wrong_sides_or_cross_session_are_rejected(self):
        messages = [msg(0, "对方", "谢谢提醒"), msg(1, "目标", "请我喝水"),
                    msg(0, "对方", "正经点", 2), msg(1, "目标", "很正经", 2)]
        bad = ["对方：「谢谢提醒」 → 我：「很正经」",
               "对方：「请我喝水」 → 我：「谢谢提醒」"]
        result, _ = quality.prepare_persona({"接话方式": bad}, messages, "目标", analyse(messages, "目标"))
        self.assertTrue(result["接话方式"])
        self.assertTrue(all(item not in result["接话方式"] for item in bad))

    def test_pair_formatting_whitespace_is_allowed_but_burst_boundaries_are_preserved(self):
        messages = [msg(0, "对方", "提醒一句"), msg(1, "目标", "别催"), msg(2, "目标", "交了")]
        good = '对方 : “提醒一句”  -> 我 : “别催” “交了”'
        merged = '对方：「提醒一句」 → 我：「别催 交了」'
        result, _ = quality.prepare_persona({"接话方式": [good, merged]}, messages, "目标", analyse(messages, "目标"))
        self.assertEqual(result["接话方式"], [good])

    def test_phrase_requires_target_repetition_and_is_not_a_topic(self):
        messages = [msg(0, "对方", "对方口癖", 1), msg(1, "目标", "食堂二楼 下次一定", 1),
                    msg(0, "对方", "对方口癖", 2), msg(1, "目标", "食堂二楼 下次一定", 2)]
        phrases = ["「食堂二楼」", "「下次一定」", "「对方口癖」"]
        with patch.object(offline, "pseg", None):
            result, _ = quality.prepare_persona({"口头禅": phrases}, messages, "目标", analyse(messages, "目标"))
        self.assertEqual(result["口头禅"], ["「下次一定」"])

    def test_one_session_repeating_does_not_become_a_habit(self):
        messages = [msg(i, "目标", "下次一定") for i in range(5)]
        result, _ = quality.prepare_persona({"口头禅": ["「下次一定」"]}, messages, "目标", analyse(messages, "目标"))
        self.assertFalse(result["口头禅"])
        persona, _ = offline.distill(messages, "目标", analyse(messages, "目标"))
        self.assertFalse(persona["口头禅"])

    def test_supported_specific_trait_survives_and_execution_timing_rule_does_not(self):
        messages = [msg(0, "对方", "谢了"), msg(1, "目标", "请我喝水")]
        good = "收到感谢时顺势要一个小回礼，原话「请我喝水」；仅限相似玩笑语境"
        result, _ = quality.prepare_persona({"人物特点": [good], "硬规则": ["从不使用表情", "隔3分钟再回"]},
                                            messages, "目标", analyse(messages, "目标"))
        self.assertEqual(result["人物特点"], [good])
        self.assertTrue(all("隔3分钟" not in item and "从不" not in item for item in result["硬规则"]))

    def test_typical_quotes_must_belong_to_target(self):
        messages = [msg(0, "对方", "别人的句子"), msg(1, "目标", "自己的句子")]
        result, _ = quality.prepare_persona({"典型例句": ["别人的句子", "自己的句子"]}, messages, "目标", analyse(messages, "目标"))
        self.assertEqual(result["典型例句"], ["自己的句子"])

    def test_demo_local_output_has_grounded_traits_and_all_quotes_verify(self):
        messages = load_messages(Path(__file__).resolve().parents[1] / "samples/demo-chat.json")
        stats = analyse(messages, "潘小雨")
        persona, memory = offline.distill(messages, "潘小雨", stats)
        persona, _ = quality.prepare_persona(persona, messages, "潘小雨", stats)
        self.assertTrue(persona["人物特点"])
        self.assertTrue(any("……那叫改期" in item for item in persona["人物特点"]))
        self.assertTrue(any("请我喝水" in item for item in persona["情境策略"]))
        self.assertTrue(all(f.status not in ("unverified", "date_mismatch")
                            for f in verify.inspect(persona, memory, messages)))
        self.assertEqual(detect(messages, "潘小雨")[0], "朋友")


class LlmInputTests(unittest.TestCase):
    def test_each_request_gets_statistics_and_complete_session_windows(self):
        corpus = ("【会话 1 / 窗口 1】\n对方: 第一段\n目标: 回一\n\n---\n\n"
                  "【会话 2 / 窗口 1】\n对方: 第二段\n目标: 回二")
        calls = []

        def fake_call(base_url, api_key, model, system, user, **kwargs):
            calls.append((system, user))
            if "关系记忆" in system:
                return '{"关系时间线": ["记录中提过某件事"]}'
            return '{"人物特点": ["在具体情境中引用原话"], "接话方式": []}'

        args = SimpleNamespace(llm_chars=50, llm_batches=2, base_url="x", api_key="k",
                               model="m", timeout=1, dry_run_llm=False, max_tokens=0,
                               desc="", no_redact=True)
        stats = Stats(total=4, per_speaker={"目标": 2}, avg_len=3.0, timed_total=4)
        with patch("src.llm.llm_call", side_effect=fake_call):
            persona, memory, _ = consult_llm(corpus, "目标", args, stats)
        self.assertTrue(calls)
        persona_users = [user for system, user in calls if "人格蒸馏" in system and "本轮任务" not in system]
        self.assertTrue(all("完整记录统计" in user for user in persona_users))
        self.assertTrue(all("【会话" in user for user in persona_users))
        self.assertIn("关系时间线", memory)
        self.assertIn("人物特点", persona)
        self.assertEqual(sum("本轮任务" in system for system, _ in calls), 1)

    def test_consolidation_failure_keeps_successful_batches_and_does_not_append_stats_words(self):
        args = SimpleNamespace(llm_chars=100, llm_batches=2, base_url="x", api_key="k",
                               model="m", timeout=1, dry_run_llm=False, max_tokens=0, desc="", no_redact=True)
        corpus = "【会话 1】\n" + "a" * 60 + SESSION_SEPARATOR + "【会话 2】\n" + "b" * 60
        def fake_call(base_url, api_key, model, system, user, **kwargs):
            if "本轮任务" in system:
                raise RuntimeError("整合失败")
            if "关系记忆" in system:
                return '{"关系时间线": ["记忆"]}'
            return '{"口头禅": ["本人表达"]}'
        stats = Stats(phrases={"食堂": 100})
        with patch("src.llm.llm_call", side_effect=fake_call), contextlib.redirect_stderr(io.StringIO()):
            persona, _, _ = consult_llm(corpus, "目标", args, stats)
        self.assertEqual(persona["口头禅"], ["本人表达"])

    def test_drafts_keep_valid_json_under_budget_and_retry_does_not_split_one_marked_window(self):
        drafts = _bounded_drafts([{"人物特点": ["a" * 200, "短特点"]}, {"人物特点": ["第二批特点"]}], 100)
        self.assertLessEqual(len(drafts), 100)
        self.assertIn("第二批特点", drafts)
        json.loads(drafts)
        one_window = "【会话 1】\n" + "a" * 6100 + "\n\n内部空行"
        self.assertEqual(_halve(one_window), [])


class WebExampleTests(unittest.TestCase):
    def test_web_parser_preserves_timestamp_and_session_boundary(self):
        text = ("2025-01-01 12:00 对方：旧话四字\n2025-01-01 12:01 目标：旧回\n"
                "2025-01-01 13:00 对方：新话四字\n2025-01-01 13:01 目标：新回\n")
        rows = _rows(text)
        self.assertIsNotNone(rows[0].ts)
        pairs = _exchanges(rows, "目标", "对方")
        self.assertEqual(pairs, [(["旧话四字"], ["旧回"]), (["新话四字"], ["新回"])])
        self.assertTrue(_example_ok(pairs[0]))

    def test_web_does_not_pair_last_message_on_previous_day(self):
        rows = _rows("2025-01-01 12:00 对方：旧话四字\n2025-01-02 12:00 目标：新回四字")
        self.assertEqual(_exchanges(rows, "目标", "对方"), [])


class CliPackageTests(unittest.TestCase):
    def test_both_public_and_zero_corpus_outputs_have_correct_identity_and_references(self):
        sample = Path(__file__).resolve().parents[1] / "samples/demo-chat.json"
        with tempfile.TemporaryDirectory() as folder:
            # 重跑同名产物时，试聊不能读到上一轮留下的记录或人物身份。
            previous_args = ["--input", str(sample), "--me", "小蒯", "--target", "潘小雨",
                             "--name", "demo", "--out", folder, "--no-llm", "--both"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(previous_args), 0)
            root = Path(folder) / "demo"
            self.assertTrue((root / "references/transcript").is_dir())
            personal_notes = root / "personal-notes.md"
            personal_notes.write_text("用户自行添加的文件", encoding="utf-8")
            args = ["--input", str(sample), "--me", "小蒯", "--target", "潘小雨", "--name", "demo",
                    "--out", folder, "--no-llm", "--both", "--audience", "公开", "--corpus-mb", "0", "--strict"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cli.main(args), 0)
            root = Path(folder) / "demo"
            skill = (root / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn('name: "demo"', skill)
            self.assertIn("# 小蒯 · 人设", skill)
            self.assertNotIn("## 数据统计", skill)
            self.assertTrue((root / "references/profile.md").is_file())
            self.assertTrue((root / "references/quotes.md").is_file())
            self.assertTrue((root / "references/other.md").is_file())
            self.assertFalse((root / "references/transcript").exists())
            self.assertFalse((root / "references/source").exists())
            self.assertFalse((root / "references/README.md").exists())
            self.assertFalse((root / "references/self.md").exists())
            self.assertEqual(personal_notes.read_text(encoding="utf-8"), "用户自行添加的文件")
            job = Job("test", args, Path(folder), "demo")
            self.assertEqual(_persona_name(job), "小蒯")
            with ZipFile(Path(folder) / "demo.zip") as archive:
                self.assertTrue(any(name.endswith("references/quotes.md") for name in archive.namelist()))

    def test_redacted_quotes_are_verified_against_the_same_redacted_messages(self):
        messages = [msg(0, "对方", "谢谢，电话13800138000收到了"), msg(1, "目标", "请我喝水")]
        redacted = [Msg(m.ts, m.speaker, redact(m.text)) for m in messages]
        pair = reply_exchanges(redacted, "目标", "对方")[0].render()
        result, _ = quality.prepare_persona({"接话方式": [pair]}, redacted, "目标", analyse(messages, "目标"))
        self.assertEqual(result["接话方式"], [pair])
        self.assertNotIn("13800138000", pair)


if __name__ == "__main__":
    unittest.main()
