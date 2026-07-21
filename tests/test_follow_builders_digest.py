from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = (
    Path(__file__).parents[1]
    / "skills/daily-ai-code-progress/scripts/follow_builders_digest.py"
)
SPEC = importlib.util.spec_from_file_location("follow_builders_digest", SCRIPT)
assert SPEC and SPEC.loader
digest = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = digest
SPEC.loader.exec_module(digest)


class ChineseDigestQualityTest(unittest.TestCase):
    def make_x_item(self):
        return digest.DigestItem(
            title="Aaron Levie: 模型与成本治理",
            url="https://x.com/example/status/1",
            source="X / Aaron Levie",
            published="2026-07-20",
            summary=(
                "Aaron Levie 最近围绕模型与成本治理有值得看的观点。核心信息："
                "A lot of people make the mistake of thinking that when AI costs drop, "
                "that spend on AI drops with it. Usually the opposite happens."
            ),
            score=100,
            raw_content=(
                "A lot of people make the mistake of thinking that when AI costs drop, "
                "that spend on AI drops with it. Usually the opposite happens."
            ),
        )

    def test_fallback_summary_is_chinese_first_without_source_copy(self):
        summary = digest.fallback_chinese_summary(self.make_x_item())

        self.assertGreaterEqual(digest.chinese_text_share(summary), 0.75)
        self.assertNotIn("A lot of people make the mistake", summary)
        self.assertIn("AI 成本、使用量与总支出的关系", summary)

    def test_renderer_uses_safe_chinese_fallback(self):
        markdown = digest.render_builders_markdown(
            [self.make_x_item()], {"feedGeneratedAt": "2026-07-20T07:22:43Z"}
        )

        digest.validate_chinese_digest(markdown)
        self.assertNotIn("Usually the opposite happens", markdown)

    def test_validator_rejects_english_dominant_summary(self):
        markdown = (
            "# AI Builders Digest - 2026-07-21\n\n"
            "- 摘要：这是中文开头。A lot of people make the mistake of thinking that "
            "when AI costs drop, spend drops too, but adoption often increases total usage "
            "across organizations and creates more demand for software and infrastructure.\n"
        )

        with self.assertRaisesRegex(RuntimeError, "not Chinese-first|long English passage"):
            digest.validate_chinese_digest(markdown)

    def test_validator_accepts_chinese_summary_with_product_names(self):
        markdown = (
            "# AI Builders Digest - 2026-07-21\n\n"
            "- 摘要：这条动态讨论了 AI 成本下降后使用量和总支出之间的关系。"
            "对工程团队而言，重点是把 token 预算、失败重试、容量规划和使用审计放进同一套治理框架，"
            "并通过真实业务指标验证模型带来的效率提升，而不是仅根据单次调用价格判断长期成本。\n"
        )

        digest.validate_chinese_digest(markdown)


if __name__ == "__main__":
    unittest.main()
