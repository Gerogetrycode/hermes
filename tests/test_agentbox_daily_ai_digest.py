from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/daily-ai-code-progress/scripts"))
import agentbox_daily_ai_digest as runner


class AgentBoxDigestTest(unittest.TestCase):
    def manifest(self):
        return {
            "date": dt.date.today().isoformat(), "chat_id": "oc_test", "thread_id": "",
            "completed": False, "markdown": "preview body", "selected": [],
            "cards": [
                {"kind": "builders", "uuid": "uuid-1", "card": {}, "message_id": ""},
                {"kind": "faiyi", "uuid": "uuid-2", "card": {}, "message_id": ""},
            ],
        }

    def test_partial_send_resumes_without_resending_first_card(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "delivery.json"
            manifest = self.manifest()
            with patch.object(runner.digest, "send_feishu_card", side_effect=["om_first", RuntimeError("network")]):
                with self.assertRaisesRegex(RuntimeError, "network"):
                    runner.deliver(root, target, manifest)
            pending = json.loads(target.read_text())
            self.assertFalse(pending["completed"])
            self.assertEqual(pending["cards"][0]["message_id"], "om_first")
            self.assertFalse((root / "seen.json").exists())
            with patch.object(runner.digest, "send_feishu_card", return_value="om_second") as send:
                runner.deliver(root, target, pending)
                send.assert_called_once_with("oc_test", {}, thread_id="", message_uuid="uuid-2")
            self.assertTrue(json.loads(target.read_text())["completed"])
            self.assertTrue((root / "seen.json").exists())

    def test_completed_day_does_not_collect_or_send(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runner.atomic_json(root / "deliveries" / f"{dt.date.today()}.json", {"completed": True})
            with patch.object(runner, "prepare") as prepare, patch.object(runner, "deliver") as deliver:
                self.assertEqual(runner.run(root), 0)
                prepare.assert_not_called()
                deliver.assert_not_called()

    def test_output_file_alone_does_not_skip_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outputs").mkdir()
            (root / "outputs" / f"{dt.date.today()}.md").write_text("unsent output")
            with patch.object(runner, "prepare", return_value=self.manifest()), patch.object(runner, "deliver") as deliver:
                runner.run(root)
                deliver.assert_called_once()

    def test_preview_does_not_send_mark_seen_or_create_delivery_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(runner, "prepare", return_value=self.manifest()), patch.object(runner, "deliver") as deliver:
                runner.run(root, preview=True)
                deliver.assert_not_called()
            self.assertFalse((root / "seen.json").exists())
            self.assertFalse((root / "deliveries").exists())
            self.assertTrue((root / "previews" / f"{dt.date.today()}.md").exists())

    def test_generation_failure_never_sends_or_marks_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(runner, "prepare", side_effect=RuntimeError("402")), patch.object(runner, "deliver") as deliver:
                with self.assertRaisesRegex(RuntimeError, "402"):
                    runner.run(root)
                deliver.assert_not_called()
            self.assertFalse((root / "deliveries").exists())

    def test_lock_prevents_concurrent_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (root / "run.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with patch.object(runner, "prepare") as prepare:
                    self.assertEqual(runner.run(root), 0)
                    prepare.assert_not_called()

    def test_corrupt_dedupe_state_is_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "seen.json").write_text("{bad json")
            with patch.object(runner, "prepare") as prepare:
                with self.assertRaises(json.JSONDecodeError):
                    runner.run(root)
                prepare.assert_not_called()

    def test_empty_message_receipt_is_an_error(self):
        with patch.object(runner.digest, "feishu_token", return_value="test"), patch.object(
            runner.digest, "open_with_retries", return_value=b'{"code":0,"data":{}}'
        ):
            with self.assertRaisesRegex(RuntimeError, "no message_id"):
                runner.digest.send_feishu_card("oc_test", {})

    def test_remix_uses_flash_without_tools_and_keeps_key_out_of_body(self):
        summary = "这条动态讨论了模型调用成本下降与使用规模扩张之间的关系。" * 5
        item = runner.digest.DigestItem(title="成本", url="https://x.com/a/status/1", source="X / a", published="2026-09-10", summary=summary, score=1)
        markdown = f"# AI Builders Digest - {dt.date.today()}\n\n## 1. [成本]({item.url})\n\n- 来源：X / a\n- 日期：2026-09-10\n- 摘要：{summary}\n"
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": markdown}}]}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-only-secret", "DAILY_AI_CODE_REMIX_MODEL": "deepseek-flash"}), patch.object(
            runner.digest, "open_with_retries", return_value=json.dumps(payload).encode()
        ) as request:
            self.assertEqual(runner.remix([item], {}, 5), markdown.strip())
            body = json.loads(request.call_args.args[0].data)
            self.assertEqual(body["model"], "deepseek-flash")
            self.assertNotIn("tools", body)
            self.assertNotIn("test-only-secret", json.dumps(body))
        runner.validate_remix(markdown, [item], 5)
        with self.assertRaisesRegex(RuntimeError, "outside"):
            runner.validate_remix(markdown.replace(item.url, "https://evil.example/"), [item], 5)
        with self.assertRaisesRegex(RuntimeError, "Chinese summary"):
            runner.validate_remix(markdown.replace("- 摘要：", "- 正文："), [item], 5)

    def test_remix_retries_once_after_validation_failure(self):
        summary = "这条动态讨论了模型调用成本下降与使用规模扩张之间的关系。" * 5
        item = runner.digest.DigestItem(
            title="成本", url="https://x.com/a/status/1", source="X / a",
            published="2026-09-10", summary=summary, score=1,
        )
        valid = (
            f"# AI Builders Digest - {dt.date.today()}\n\n"
            f"## 1. [成本]({item.url})\n\n- 来源：X / a\n- 日期：2026-09-10\n- 摘要：{summary}\n"
        )
        invalid = valid.replace(summary, "对工程团队而言，重点是持续观察工具链成熟度。")
        payloads = [
            {"choices": [{"finish_reason": "stop", "message": {"content": invalid}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": valid}}]},
        ]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test", "DAILY_AI_CODE_REMIX_MODEL": "deepseek-flash"}), patch.object(
            runner.digest, "open_with_retries", side_effect=[json.dumps(value).encode() for value in payloads]
        ) as request:
            self.assertEqual(runner.remix([item], {}, 5), valid.strip())
            self.assertEqual(request.call_count, 2)
            retry_body = json.loads(request.call_args.args[0].data)
            self.assertIn("上一版未通过校验", retry_body["messages"][-1]["content"])

    def test_remix_keeps_only_valid_sections_after_two_invalid_responses(self):
        bad_item = runner.digest.DigestItem(
            title="模型成本", url="https://x.com/a/status/2", source="X / a",
            published="2026-09-10",
            summary="这条动态讨论模型调用成本、使用规模和总支出之间的关系。" * 5,
            score=1,
        )
        good_item = runner.digest.DigestItem(
            title="工具更新", url="https://x.com/b/status/3", source="X / b",
            published="2026-09-10", summary="这条动态讨论工具更新。" * 5, score=1,
        )
        good_summary = "这条动态介绍工具调用和权限管理的新做法，并解释了更新对实际开发流程的影响。" * 3
        invalid = (
            f"# AI Builders Digest - {dt.date.today()}\n\n"
            f"## 1. [模型成本]({bad_item.url})\n\n- 来源：X / a\n- 日期：2026-09-10\n"
            "- 摘要：对工程团队而言，重点是持续观察工具链成熟度。\n"
            f"\n## 2. [工具更新]({good_item.url})\n\n- 来源：X / b\n- 日期：2026-09-10\n"
            f"- 摘要：{good_summary}\n"
        )
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": invalid}}]}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), patch.object(
            runner.digest, "open_with_retries", side_effect=[json.dumps(payload).encode()] * 2
        ) as request:
            result = runner.remix([bad_item, good_item], {"feedGeneratedAt": "2026-09-10T00:00:00Z"}, 5)
            self.assertEqual(request.call_count, 2)
            self.assertIn(good_summary, result)
            self.assertIn("部分摘要未通过质量校验", result)
            self.assertNotIn(bad_item.url, result)
            self.assertNotIn("这份保底摘要", result)
            self.assertNotIn("对工程团队而言", result)
            runner.validate_remix(result, [bad_item, good_item], 5)

    def test_remix_fails_closed_when_no_summary_is_valid(self):
        item = runner.digest.DigestItem(
            title="模型成本", url="https://x.com/a/status/2", source="X / a",
            published="2026-09-10", summary="模型成本变化。", score=1,
        )
        invalid = (
            f"# AI Builders Digest - {dt.date.today()}\n\n"
            f"## 1. [模型成本]({item.url})\n\n- 来源：X / a\n- 日期：2026-09-10\n"
            "- 摘要：对工程团队而言，重点是持续观察工具链成熟度。\n"
        )
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": invalid}}]}
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), patch.object(
            runner.digest, "open_with_retries", side_effect=[json.dumps(payload).encode()] * 2
        ):
            with self.assertRaisesRegex(RuntimeError, "no valid Chinese summaries"):
                runner.remix([item], {}, 5)


if __name__ == "__main__":
    unittest.main()
