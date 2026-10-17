from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "skills/daily-ai-code-progress/scripts"))
import combined_ai_digest as combined
import agentbox_daily_ai_digest as runner


SUMMARY = "厂商发布了用于智能体开发的新工具，提供按任务隔离权限和追踪调用记录的能力。官方示例展示了代码评审与自动化测试的流程，并说明当前仍处于测试阶段，尚未向所有用户开放。"


def news(id="b01", section="builders", url="https://example.com/release"):
    return combined.NewsItem(id, section, "工具发布", url, url, "官方博客", "2026-10-16", SUMMARY)


def ratings_payload(items):
    return {"ratings": [{"id": item.id, "content_type": "news", "relevance": 26, "information": 26, "credibility": 22,
                         "freshness": 12, "reason": "一手技术更新，包含具体机制。"} for item in items]}


class CombinedDigestTest(unittest.TestCase):
    def test_faiyi_extracts_chinese_items_with_original_links_and_attribution(self):
        payload = [{"date": "2026-10-16T07:00:00", "link": "https://faiyi.com/?p=1", "content": {"rendered": (
            '<ol><li><p><strong>Tool release</strong>（官方博客）</p>'
            '<p><strong>中文摘要：</strong>工具已更新，权限仍受限。</p>'
            '<p><strong>English Summary:</strong>Do not copy this.</p>'
            '<p><a href="https://example.com/release?x=1&amp;y=2">原文链接</a></p></li></ol>'
        )}}]
        rows, meta = combined.parse_faiyi(payload, dt.date(2026, 10, 16))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source, "官方博客")
        self.assertEqual(rows[0].title, "Tool release")
        self.assertEqual(rows[0].text, "工具已更新，权限仍受限。")
        self.assertEqual(rows[0].url, "https://example.com/release?x=1&y=2")
        self.assertEqual(rows[0].published, "简报 2026-10-16")
        self.assertEqual(meta["article_url"], payload[0]["link"])
        with self.assertRaisesRegex(RuntimeError, "stale"):
            combined.parse_faiyi(payload, dt.date(2026, 10, 20))

    def test_aihot_enforces_freshness_and_preserves_both_links(self):
        now = dt.datetime(2026, 10, 16, 12, tzinfo=combined.TZ)
        def item(id, stamp, **extra):
            return {"id": id, "title": "更新", "summary": SUMMARY, "selected": True,
                    "links": {"aihot": f"https://aihot.news/items/{id}", "original": f"https://example.com/{id}"},
                    "source": {"name": "官方"}, "publishedAt": stamp, "discoveredAt": now.isoformat(), **extra}
        payload = {"schemaVersion": 1, "items": [item("new", "2026-10-16T03:00:00Z"),
                     item("old", "2026-10-14T03:00:00Z"), item("undated", None),
                     item("future", "2026-10-17T03:00:00Z"), item("private", now.isoformat(), selected=False)]}
        rows, _ = combined.parse_aihot(payload, now)
        self.assertEqual([row.url for row in rows], ["https://aihot.news/items/new", "https://aihot.news/items/undated"])
        self.assertEqual(rows[0].original_url, "https://example.com/new")
        self.assertEqual(rows[0].published, "10-16 11:00")
        self.assertEqual(rows[1].published, "收录 10-16 12:00")

    def test_url_dedupe_keeps_earliest_source_without_merging_different_articles(self):
        first = news(url="https://twitter.com/author/status/123?s=20")
        second = news("f01", "faiyi", "https://x.com/other/status/123?utm_source=feed")
        distinct = news("a01", "aihot", "https://example.com/other-release")
        rows, duplicates = combined.exact_dedupe([first, second, distinct])
        self.assertEqual(rows, [first, distinct])
        self.assertEqual(duplicates[0]["of"], "b01")
        self.assertNotEqual(combined.canonical_url("https://example.com/?p=1"), combined.canonical_url("https://example.com/?p=2"))

    def test_semantic_plan_can_only_remove_items_for_retained_earlier_items(self):
        items = [news(), news("f01", "faiyi", "https://media.com/coverage")]
        for item in items:
            item.title = "ExampleTool工具发布"
        keep = {"id": "b01", "title": "工具更新", "summary": SUMMARY}
        duplicate = {"id": "f01", "of": "b01", "reason": "same launch", "shared_subject": "ExampleTool",
                     "evidence": {"earlier": SUMMARY[:30], "later": SUMMARY[:30]}}
        plan = {"keep": [keep], "duplicates": [duplicate]}
        rows, duplicates = combined.validate_plan(plan, items, 5)
        self.assertEqual(rows[0]["url"], items[0].url)
        self.assertEqual(len(duplicates), 1)
        with self.assertRaisesRegex(RuntimeError, "earlier"):
            combined.validate_plan({"keep": [{**keep, "id": "f01"}], "duplicates": [{"id": "b01", "of": "f01"}]}, items, 5)
        with self.assertRaisesRegex(RuntimeError, "not retained"):
            combined.validate_plan({"keep": [], "duplicates": [{"id": "f01", "of": "b01"}]}, items, 5)
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            combined.validate_plan({"keep": [{**keep, "id": "invented"}], "duplicates": []}, items, 5)
        with self.assertRaisesRegex(RuntimeError, "specific shared subject"):
            combined.validate_plan({"keep": [keep], "duplicates": [{**duplicate, "shared_subject": "沙箱"}]}, items, 5)
        with self.assertRaisesRegex(RuntimeError, "event evidence"):
            combined.validate_plan({"keep": [keep], "duplicates": [{**duplicate, "evidence": {"earlier": "invented", "later": "invented"}}]}, items, 5)

    def test_invalid_item_is_omitted_on_retry_without_generic_fallback(self):
        items = [news(), news("f01", "faiyi", "https://example.com/other")]
        plan = {"keep": [{"id": "b01", "title": "更新", "summary": SUMMARY},
                         {"id": "f01", "title": "套话", "summary": "对工程团队而言，重点是持续观察工具链成熟度。"}], "duplicates": []}
        with self.assertRaises(RuntimeError):
            combined.validate_plan(plan, items, 5)
        rows, _ = combined.validate_plan(plan, items, 5, partial=True)
        self.assertEqual([row["id"] for row in rows], ["b01"])

    def test_compact_sourced_update_does_not_require_padding_to_legacy_length(self):
        summary = "官方宣布模型快速模式结束研究预览并移除等待名单，符合条件的订阅者现可直接启用，价格与额度规则仍按原方案执行。"
        plan = {"keep": [{"id": "b01", "title": "快速模式开放", "summary": summary}], "duplicates": []}
        rows, _ = combined.validate_plan(plan, [news()], 5)
        self.assertEqual(rows[0]["summary"], summary)
        with self.assertRaises(RuntimeError):
            runner.digest.validate_chinese_digest("- 摘要：" + summary)

    def test_builder_politics_or_generic_startup_commentary_is_not_a_daily_ai_item(self):
        summary = "作者呼吁对当地提案投反对票，认为相关学者不了解创业公司的处境，也没有考虑政策对创新生态的长期影响。"
        plan = {"keep": [{"id": "b01", "title": "投票观点", "summary": summary}], "duplicates": []}
        with self.assertRaisesRegex(RuntimeError, "no concrete AI"):
            combined.validate_plan(plan, [news()], 5)

    def test_final_retry_caps_intermediate_pool_at_the_entire_card_budget(self):
        items = [news(f"b{index:02}", url=f"https://example.com/{index}") for index in range(1, 7)]
        plan = {"keep": [{"id": item.id, "title": "更新", "summary": SUMMARY} for item in items], "duplicates": []}
        with self.assertRaisesRegex(RuntimeError, "limit"):
            combined.validate_plan(plan, items, 5)
        rows, _ = combined.validate_plan(plan, items, 5, partial=True)
        self.assertEqual(len(rows), 5)
        self.assertNotIn("b06", {row["id"] for row in rows})

    def test_card_has_three_sections_and_keeps_aihot_attribution(self):
        items = [news(), news("a01", "aihot", "https://aihot.news/items/a")]
        plan = {"keep": [{"id": item.id, "title": item.title, "summary": SUMMARY} for item in items], "duplicates": []}
        rows, _ = combined.validate_plan(plan, items, 5)
        rows[-1]["original_url"] = "https://example.com/original"
        markdown, card = combined.render(rows, "2026-10-16", 1, {})
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(len(card["body"]["elements"]), 3)
        self.assertEqual([element["tag"] for element in card["body"]["elements"]], ["column_set"] * 3)
        self.assertNotIn("三路精选", json.dumps(card, ensure_ascii=False))
        self.assertNotIn("同一事件仅展示一次", json.dumps(card, ensure_ascii=False))
        self.assertNotIn("分钟", json.dumps(card, ensure_ascii=False))
        self.assertNotIn("去重 1 条", markdown)
        self.assertIn("二 · 理想栈", markdown)
        self.assertIn("没有新增入选内容", markdown)
        self.assertIn("AIHOT /", json.dumps(card, ensure_ascii=False))
        self.assertIn("https://example.com/original", json.dumps(card))

    def test_aihot_keeps_source_title_uncertainty_qualifier(self):
        item = news("a01", "aihot", "https://aihot.news/items/a")
        item.title = "消息称投资者考虑下调估值"
        rows, _ = combined.validate_plan({"keep": [{"id": "a01", "title": "投资者下调估值", "summary": SUMMARY}], "duplicates": []}, [item], 5)
        self.assertEqual(rows[0]["title"], item.title)

    def test_compose_retries_invalid_json_and_only_sends_public_source_material(self):
        valid = {"keep": [{"id": "b01", "title": "工具更新", "summary": SUMMARY}], "duplicates": []}
        def response(content):
            return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": content}}]}).encode()
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "not-public-test-secret"}), patch.object(
            runner.digest, "open_with_retries", side_effect=[response(json.dumps(ratings_payload([news()]))),
                response("not json"), response("```json\n" + json.dumps(valid) + "\n```")]
        ) as request:
            rows, _ = combined.compose([news()])
            self.assertEqual(rows[0]["id"], "b01")
            self.assertEqual(request.call_count, 3)
            body = json.loads(request.call_args.args[0].data)
            self.assertNotIn("not-public-test-secret", json.dumps(body))
            self.assertNotIn("tools", body)

    def test_sections_compare_only_with_previously_displayed_items(self):
        items = [news(), news("f01", "faiyi", "https://example.com/coverage"), news("a01", "aihot", "https://example.com/new")]
        for item in items[:2]:
            item.title = "ExampleTool工具发布"
        def keep(id):
            return {"id": id, "title": "新工具", "summary": SUMMARY}
        plans = [
            {"keep": [keep("b01")], "duplicates": []},
            {"keep": [keep("f01")], "duplicates": [{"id": "f01", "of": "b01", "reason": "same release",
                "shared_subject": "ExampleTool", "evidence": {"earlier": SUMMARY[:30], "later": SUMMARY[:30]}}]},
            {"keep": [keep("a01")], "duplicates": []},
        ]
        responses = [json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(plan)}}]}).encode()
                     for plan in [ratings_payload(items)] + plans]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), patch.object(runner.digest, "open_with_retries", side_effect=responses) as request:
            selected, removed = combined.compose(items)
        self.assertEqual([row["id"] for row in selected], ["b01", "a01"])
        self.assertEqual(removed[0]["id"], "f01")
        last_body = json.loads(request.call_args_list[3].args[0].data)
        material = json.loads(last_body["messages"][1]["content"].rsplit("\n", 1)[-1])
        self.assertEqual([row["id"] for row in material["already_displayed"]], ["b01"])
        self.assertEqual([row["id"] for row in material["current"]], ["a01"])

    def test_compose_allows_more_than_five_from_one_source(self):
        items = [news(f"a{index:02}", "aihot", f"https://example.com/{index}") for index in range(6)]
        plans = [ratings_payload(items), {"keep": [{"id": item.id, "title": "工具更新", "summary": SUMMARY} for item in items], "duplicates": []}]
        responses = [json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(plan)}}]}).encode() for plan in plans]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), patch.object(runner.digest, "open_with_retries", side_effect=responses):
            selected, _ = combined.compose(items, 12)
        self.assertEqual(len(selected), 6)
        self.assertTrue(all(row["section"] == "aihot" for row in selected))

    def test_truncated_source_response_retries_compactly_and_remains_in_audit(self):
        valid = {"keep": [{"id": "b01", "title": "工具更新", "summary": SUMMARY}], "duplicates": []}
        def response(content, finish="stop"):
            return json.dumps({"choices": [{"finish_reason": finish, "message": {"content": content}}]}).encode()
        responses = [response(json.dumps(ratings_payload([news()]))), response("{incomplete", "length"), response(json.dumps(valid))]
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), \
             patch.object(runner.digest, "open_with_retries", side_effect=responses) as request:
            audit = Path(directory) / "audit.json"
            selected, _ = combined.compose([news()], audit_path=audit)
            self.assertEqual(len(selected), 1)
            self.assertEqual(json.loads(audit.read_text())[1]["finish_reason"], "length")
            self.assertIn("上一份输出被截断", json.loads(request.call_args.args[0].data)["messages"][-1]["content"])

    def test_global_budget_can_all_go_to_one_source_and_exceed_five_items(self):
        items = [news(f"a{index:02}", "aihot", f"https://example.com/{index}") for index in range(9)]
        items.append(news("b01", "builders", "https://example.com/b"))
        ratings = combined.validate_ratings(ratings_payload(items), items)
        ratings["b01"].update({"total": 70, "information": 15})
        rows = [{**vars(item), "summary": SUMMARY} for item in items]
        selected = combined.apply_global_budget(rows, ratings, 8)
        self.assertEqual(len(selected), 8)
        self.assertTrue(all(row["section"] == "aihot" for row in selected))

    def test_quality_order_overrides_feed_order_and_omits_low_quality_without_padding(self):
        items = [news("b01"), news("a01", "aihot", "https://example.com/a"), news("f01", "faiyi", "https://example.com/f")]
        ratings = combined.validate_ratings(ratings_payload(items), items)
        ratings["b01"]["total"] = 64
        ratings["a01"].update({"total": 90, "credibility": 25})
        ratings["f01"]["total"] = 80
        rows = [{**vars(item), "summary": SUMMARY} for item in items]
        selected = combined.apply_global_budget(rows, ratings, 12)
        self.assertEqual([row["id"] for row in selected], ["a01", "f01"])
        self.assertEqual(len(selected), 2)
        markdown, _ = combined.render(selected, "2026-10-16", 0, {})
        self.assertLess(markdown.index("一 · Builders"), markdown.index("二 · 理想栈"))
        self.assertLess(markdown.index("二 · 理想栈"), markdown.index("三 · AIHOT"))

    def test_ratings_must_cover_every_candidate_with_valid_weights(self):
        items = [news(), news("a01", "aihot", "https://example.com/a")]
        with self.assertRaisesRegex(RuntimeError, "every candidate"):
            combined.validate_ratings(ratings_payload(items[:1]), items)
        invalid = ratings_payload(items)
        invalid["ratings"][0]["credibility"] = 26
        with self.assertRaisesRegex(RuntimeError, "bounded integers"):
            combined.validate_ratings(invalid, items)

    def test_content_type_is_audited_and_short_insight_can_outrank_news(self):
        items = [news(), news("a01", "aihot", "https://example.com/a")]
        payload = ratings_payload(items)
        payload["ratings"][0].update(content_type="insight", information=29)
        ratings = combined.validate_ratings(payload, items)
        rows = [{**vars(item), "summary": SUMMARY} for item in items]
        selected = combined.apply_global_budget(rows, ratings, 1)
        self.assertEqual(selected[0]["id"], "b01")
        self.assertEqual(selected[0]["quality"]["content_type"], "insight")
        payload["ratings"][0]["content_type"] = "famous-person"
        with self.assertRaisesRegex(RuntimeError, "content_type"):
            combined.validate_ratings(payload, items)

    def test_quality_prompt_distinguishes_insight_from_information_volume(self):
        response = json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(ratings_payload([news()]))}}]}).encode()
        with patch.object(runner.digest, "open_with_retries", return_value=response) as request:
            combined.rate_candidates([news()], "test", [], None)
        body = json.loads(request.call_args.args[0].data)
        self.assertEqual(body["temperature"], 0)
        prompt = body["messages"][1]["content"]
        for rule in ("认知增量而非篇幅", "不因文字短扣分", "当事人经验", "不因作者名气", "不得替作者补", "不给任何信源保留名额"):
            self.assertIn(rule, prompt)
        self.assertIn("不因缺少独立验证自动降至低分", prompt)
        self.assertIn("各维度独立打分", prompt)

    def test_short_builder_insight_is_not_padded_to_old_summary_length(self):
        summary = "作者认为智能体提速后，验证代码将成为团队的新瓶颈。"
        self.assertLess(len(summary), 35)
        rows, _ = combined.validate_plan({"keep": [{"id": "b01", "title": "验证成为瓶颈", "summary": summary}],
                                           "duplicates": []}, [news()], 12)
        self.assertEqual(rows[0]["summary"], summary)

    def test_builder_job_titles_must_come_from_supplied_source(self):
        item = news()
        summary = "Box CEO Aaron Levie认为智能体提速后，验证代码将成为团队的新瓶颈。"
        plan = {"keep": [{"id": "b01", "title": "验证成为瓶颈", "summary": summary}], "duplicates": []}
        with self.assertRaisesRegex(RuntimeError, "job title"):
            combined.validate_plan(plan, [item], 12)
        item.text += " Aaron Levie, CEO: verification is the bottleneck."
        rows, _ = combined.validate_plan(plan, [item], 12)
        self.assertEqual(rows[0]["summary"], summary)

    def test_duplicate_viewpoint_is_attached_once_with_immutable_source_and_link(self):
        items = [news(), news("f01", "faiyi", "https://example.com/opinion")]
        for item in items:
            item.title = "ExampleTool工具发布"
        items[1].source = "作者甲"
        items[1].text += "作者认为，智能体编写代码的速度增长后，验证代码才是新的瓶颈。"
        perspective = {"summary": "作者认为智能体提高编写速度后，验证代码成为新的瓶颈。",
                       "quote": "智能体编写代码的速度增长后，验证代码才是新的瓶颈"}
        duplicate = {"id": "f01", "of": "b01", "reason": "same launch with a distinct viewpoint", "shared_subject": "ExampleTool",
                     "evidence": {"earlier": SUMMARY[:30], "later": SUMMARY[:30]}, "perspective": perspective}
        rows, duplicates = combined.validate_plan({"keep": [{"id": "b01", "title": "工具更新", "summary": SUMMARY}],
                                                     "duplicates": [duplicate]}, items, 12)
        ratings = combined.validate_ratings(ratings_payload(items), items)
        rows = combined.attach_perspectives(rows, duplicates, {item.id: item for item in items}, ratings)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["perspectives"][0]["source"], "作者甲")
        self.assertEqual(rows[0]["perspectives"][0]["url"], items[1].url)
        markdown, card = combined.render(rows, "2026-10-17", 1, {})
        self.assertIn("补充视角 · [作者甲", markdown)
        self.assertIn(items[1].url, json.dumps(card))
        self.assertEqual(combined.attach_perspectives([], duplicates, {item.id: item for item in items}, ratings), [])
        duplicate["perspective"]["quote"] = "这段证据从未出现在原始正文材料中，不能被接受。"
        with self.assertRaisesRegex(RuntimeError, "verbatim"):
            combined.validate_plan({"keep": [{"id": "b01", "title": "工具更新", "summary": SUMMARY}],
                                    "duplicates": [duplicate]}, items, 12)
        with self.assertRaisesRegex(RuntimeError, "verbatim"):
            combined.validate_plan({"keep": [{"id": "b01", "title": "工具更新", "summary": SUMMARY}],
                                    "duplicates": [duplicate]}, items, 12, partial=True)

    def test_perspective_survives_later_section_compose_without_extra_event_slot(self):
        items = [news(), news("f01", "faiyi", "https://example.com/f"), news("a01", "aihot", "https://example.com/a")]
        for item in items:
            item.title = "ExampleTool工具发布"
        items[1].text += "作者认为智能体提速后，验证代码将成为团队的新瓶颈。"
        perspective = {"summary": "作者认为智能体提速后，验证代码将成为团队的新瓶颈。",
                       "quote": "作者认为智能体提速后，验证代码将成为团队的新瓶颈"}
        def keep(id):
            return {"id": id, "title": "工具更新", "summary": SUMMARY}
        plans = [ratings_payload(items), {"keep": [keep("b01")], "duplicates": []},
                 {"keep": [], "duplicates": [{"id": "f01", "of": "b01", "reason": "same launch",
                    "shared_subject": "ExampleTool", "evidence": {"earlier": SUMMARY[:30], "later": SUMMARY[:30]},
                    "perspective": perspective}]}, {"keep": [keep("a01")], "duplicates": []}]
        responses = [json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(plan)}}]}).encode()
                     for plan in plans]
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test"}), patch.object(runner.digest, "open_with_retries", side_effect=responses):
            selected, duplicates = combined.compose(items)
        self.assertEqual([row["id"] for row in selected], ["b01", "a01"])
        self.assertEqual(selected[0]["perspectives"][0]["id"], "f01")
        self.assertEqual(duplicates[0]["perspective"], perspective)

    def test_only_two_highest_quality_viewpoints_are_displayed_per_event(self):
        items = [news()] + [news(f"f{index:02}", "faiyi", f"https://example.com/{index}") for index in range(1, 4)]
        ratings = combined.validate_ratings(ratings_payload(items), items)
        for id, total in (("f01", 70), ("f02", 90), ("f03", 80)):
            ratings[id]["total"] = total
        duplicates = [{"id": item.id, "of": "b01", "perspective": {"summary": SUMMARY, "quote": SUMMARY[:30]}}
                      for item in items[1:]]
        rows = combined.attach_perspectives([{**vars(items[0]), "summary": SUMMARY}], duplicates,
                                           {item.id: item for item in items}, ratings)
        self.assertEqual([row["id"] for row in rows[0]["perspectives"]], ["f02", "f03"])

    def test_prepare_produces_one_card_from_all_three_sources(self):
        builder = runner.digest.DigestItem("更新", "https://example.com/b", "X / author", dt.date.today().isoformat(), SUMMARY, 1)
        f, a = news("f01", "faiyi", "https://example.com/f"), news("a01", "aihot", "https://example.com/a")
        def compose(items, limit, **kwargs):
            return combined.validate_plan({"keep": [{"id": item.id, "title": "更新", "summary": SUMMARY} for item in items], "duplicates": []}, items, limit)
        with tempfile.TemporaryDirectory() as directory, patch.object(runner.digest, "collect_builders_digest", return_value=([builder], {})), \
             patch.object(combined, "collect_faiyi", return_value=([f], {})), patch.object(combined, "collect_aihot", return_value=([a], {})), \
             patch.object(combined, "compose", side_effect=compose):
            manifest = runner.prepare(Path(directory), True)
        self.assertEqual([card["kind"] for card in manifest["cards"]], ["combined"])
        self.assertEqual([row["section"] for row in manifest["selection"]["keep"]], ["builders", "faiyi", "aihot"])

    def test_sample_is_idempotent_and_preserves_completed_daily_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = dt.date.today().isoformat()
            daily = root / "deliveries" / f"{day}.json"
            runner.atomic_json(daily, {"completed": True, "cards": [{"message_id": "om_legacy"}]})
            original = daily.read_bytes()
            manifest = {"date": day, "chat_id": "oc_test", "thread_id": "", "completed": False,
                        "markdown": "body", "selected": [], "cards": [{"kind": "combined", "uuid": "daily-uuid", "card": {}, "message_id": ""}]}
            with patch.object(runner, "prepare", return_value=manifest), patch.object(runner.digest, "send_feishu_card", return_value="om_sample") as send:
                runner.run(root, sample=True)
                runner.run(root, sample=True)
                self.assertEqual(send.call_count, 1)
                self.assertNotEqual(send.call_args.kwargs["message_uuid"], "daily-uuid")
            self.assertEqual(daily.read_bytes(), original)
            self.assertTrue(json.loads((root / "samples" / f"{day}.json").read_text())["completed"])

    def test_inspected_preview_can_be_sent_without_regeneration(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"FEISHU_HOME_CHANNEL": "oc_test", "FEISHU_HOME_CHANNEL_THREAD_ID": ""}):
            root = Path(directory)
            prepared = root / "prepared.json"
            manifest = {"date": dt.date.today().isoformat(), "chat_id": "oc_test", "thread_id": "", "completed": False,
                        "markdown": "inspected body", "selected": [], "cards": [{"kind": "combined", "uuid": "daily", "card": {"schema": "2.0"}, "message_id": ""}]}
            runner.atomic_json(prepared, manifest)
            with patch.object(runner, "prepare") as prepare, patch.object(runner.digest, "send_feishu_card", return_value="om_prepared") as send:
                runner.run(root, sample=True, prepared=prepared)
                prepare.assert_not_called()
                self.assertEqual(send.call_count, 1)
            manifest["chat_id"] = "oc_wrong"
            runner.atomic_json(prepared, manifest)
            with tempfile.TemporaryDirectory() as other, self.assertRaisesRegex(RuntimeError, "target"):
                runner.run(Path(other), sample=True, prepared=prepared)


if __name__ == "__main__":
    unittest.main()
