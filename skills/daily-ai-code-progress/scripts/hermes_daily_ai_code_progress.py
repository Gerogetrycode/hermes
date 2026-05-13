#!/usr/bin/env python3
"""Hermes cron runner for the daily AI code progress skill.

Hermes cron requires scripts to live under ~/.hermes/scripts. Install this file
there as daily_ai_code_progress.py and keep the repository path below in sync
with the worktree that owns the skill.
"""

from __future__ import annotations

import os
import html
import json
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path


DEFAULT_REPO = Path("/Users/bytedance/.codex/worktrees/9364/hermes")
FAIYI_LATEST_API = "http://www.faiyi.com/index.php?rest_route=/wp/v2/posts&categories=7&per_page=1"


class MarkdownHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.href_stack: list[str | None] = []
        self.in_link_text = False
        self.current_link_text: list[str] = []
        self.in_li = False
        self.li_counter = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "ol":
            self.li_counter = 0
            self.parts.append("\n")
        elif tag in {"p", "div"}:
            if self.in_li:
                last = self.parts[-1] if self.parts else ""
                if not re.search(r"\n\d+\. $", last):
                    self.parts.append("\n")
            else:
                self.parts.append("\n\n")
        elif tag in {"br", "hr"}:
            self.parts.append("\n")
        elif tag == "li":
            self.in_li = True
            self.li_counter += 1
            self.parts.append(f"\n{self.li_counter}. ")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag == "a":
            self.href_stack.append(attrs_dict.get("href"))
            self.in_link_text = True
            self.current_link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "li":
            self.in_li = False
            self.parts.append("\n")
        elif tag in {"p", "div"}:
            self.parts.append("\n")
        elif tag in {"strong", "b"}:
            self.parts.append("**")
        elif tag == "a":
            href = self.href_stack.pop() if self.href_stack else None
            text = "".join(self.current_link_text).strip()
            if text and href:
                self.parts.append(f"[{text}]({href})")
            elif text:
                self.parts.append(text)
            self.in_link_text = False
            self.current_link_text = []

    def handle_data(self, data: str) -> None:
        if self.in_li and not data.strip():
            return
        if self.in_link_text:
            self.current_link_text.append(data)
        else:
            self.parts.append(data)

    def markdown(self) -> str:
        text = html.unescape("".join(self.parts))
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"(\n\d+\.)\n(?=\*\*)", r"\1 ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()


def fetch_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": "daily-ai-code-progress-hermes/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return json.loads(data.decode(charset, errors="replace"))


def html_to_markdown(value: str) -> str:
    parser = MarkdownHTMLParser()
    parser.feed(value)
    return parser.markdown()


def latest_faiyi_brief() -> str:
    payload = fetch_json(os.environ.get("FAIYI_AI_DAILY_API", FAIYI_LATEST_API))
    if not isinstance(payload, list) or not payload:
        return "## 理想栈 AI动态简报\n\n未能获取最新文章。"
    post = payload[0]
    if not isinstance(post, dict):
        return "## 理想栈 AI动态简报\n\n返回内容格式异常。"

    title = html.unescape(str(post.get("title", {}).get("rendered", "理想栈 AI动态简报")))
    link = str(post.get("link", "http://www.faiyi.com/?cat=7"))
    date = str(post.get("date", ""))
    rendered = str(post.get("content", {}).get("rendered", ""))
    body = html_to_markdown(rendered)

    return "\n".join(
        [
            "## 理想栈 AI动态简报",
            "",
            f"来源：[{title}]({link})",
            f"发布时间：{date}",
            "",
            body or "未能解析正文内容。",
        ]
    )


def main() -> int:
    repo = Path(os.environ.get("DAILY_AI_CODE_REPO", DEFAULT_REPO)).expanduser()
    collector = repo / "skills/daily-ai-code-progress/scripts/collect_news.py"
    state = Path(
        os.environ.get(
            "DAILY_AI_CODE_STATE",
            str(Path.home() / ".hermes/state/daily-ai-code-progress/seen.json"),
        )
    ).expanduser()
    limit = os.environ.get("DAILY_AI_CODE_LIMIT", "5")
    days = os.environ.get("DAILY_AI_CODE_DAYS", "7")

    cmd = [
        sys.executable,
        str(collector),
        "--limit",
        limit,
        "--days",
        days,
        "--state",
        str(state),
    ]
    if os.environ.get("DAILY_AI_CODE_PREVIEW") != "1":
        cmd.append("--mark-sent")

    if not collector.exists():
        print(f"Collector not found: {collector}", file=sys.stderr)
        return 2

    result = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, check=False)
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    output = result.stdout.strip()
    try:
        faiyi = latest_faiyi_brief()
    except Exception as exc:  # noqa: BLE001 - cron output should include fetch failures.
        faiyi = f"## 理想栈 AI动态简报\n\n抓取失败：{exc}"
    print(f"{output}\n\n---\n\n{faiyi}".strip())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
