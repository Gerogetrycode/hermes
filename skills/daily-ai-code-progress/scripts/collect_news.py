#!/usr/bin/env python3
"""Collect candidate items for a daily AI coding progress digest.

The script intentionally uses only the Python standard library so it can run
inside minimal skill environments.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


DEFAULT_STATE = Path(".cache/daily-ai-code-progress/seen.json")
USER_AGENT = "daily-ai-code-progress-skill/0.1 (+https://openai.com/)"

KEYWORDS = [
    "agent",
    "agents",
    "api",
    "automation",
    "cloud agent",
    "claude code",
    "code",
    "code review",
    "codex",
    "coding",
    "copilot",
    "debug",
    "developer",
    "developers",
    "devtools",
    "eval",
    "gpt",
    "function calling",
    "github",
    "ide",
    "mcp",
    "model",
    "pull request",
    "repo",
    "repository",
    "review",
    "sdk",
    "security",
    "software",
    "terminal",
    "tool",
    "tools",
    "usage limits",
    "vscode",
    "visual studio code",
]

STRONG_RELEVANCE = [
    "ai coding",
    "agentic coding",
    "claude code",
    "cloud agent",
    "code review",
    "codex",
    "copilot",
    "coding agent",
    "coding agents",
    "developer tools",
    "mcp",
    "pull request",
    "software development",
]

SOURCES = [
    {
        "name": "OpenAI News",
        "kind": "feed",
        "url": "https://openai.com/news/rss.xml",
        "priority": 100,
    },
    {
        "name": "Claude Code Changelog",
        "kind": "markdown_changelog",
        "url": "https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md",
        "link": "https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md",
        "priority": 98,
    },
    {
        "name": "Anthropic News",
        "kind": "html_links",
        "url": "https://www.anthropic.com/news",
        "include_href_prefix": "/news/",
        "priority": 96,
    },
    {
        "name": "GitHub Changelog",
        "kind": "feed",
        "url": "https://github.blog/changelog/feed/",
        "priority": 70,
    },
    {
        "name": "VS Code Updates",
        "kind": "feed",
        "url": "https://code.visualstudio.com/feed.xml",
        "priority": 60,
    },
    {
        "name": "Cursor Changelog",
        "kind": "html_links",
        "url": "https://cursor.com/changelog",
        "include_href_prefix": "/changelog/",
        "priority": 55,
    },
]


@dataclass
class Item:
    title: str
    url: str
    source: str
    summary: str = ""
    published: str = ""
    score: int = 0
    reason: str = ""
    fingerprint: str = ""


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(PermanentRedirectHandler)
    with opener.open(request, timeout=timeout) as response:
        data = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return data.decode(charset, errors="replace")


class PermanentRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_308(self, req, fp, code, msg, headers):  # noqa: N802 - urllib callback name.
        return self.http_error_301(req, fp, code, msg, headers)


def clean_text(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value or "")
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(element: ET.Element, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in list(element):
        if local_name(child.tag) in wanted:
            return clean_text("".join(child.itertext()))
    return ""


def parse_date(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    parsed = dt.datetime.strptime(value, fmt).replace(tzinfo=dt.timezone.utc)
                    break
                except ValueError:
                    parsed = None
            if parsed is None:
                return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).date().isoformat()


def extract_meta(content: str, names: Iterable[str]) -> str:
    for name in names:
        escaped = re.escape(name)
        patterns = [
            rf'<meta[^>]+(?:name|property)=["\']{escaped}["\'][^>]+content=["\']([^"\']+)["\']',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\']{escaped}["\']',
        ]
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                return clean_text(match.group(1))
    return ""


def extract_page_date(content: str) -> str:
    meta_date = extract_meta(
        content,
        [
            "article:published_time",
            "article:modified_time",
            "date",
            "published",
            "publish-date",
        ],
    )
    parsed = parse_date(meta_date)
    if parsed:
        return parsed
    time_match = re.search(r"<time[^>]+datetime=[\"']([^\"']+)[\"']", content, flags=re.IGNORECASE)
    if time_match:
        return parse_date(time_match.group(1))
    readable = re.search(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
        r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},\s+20\d{2}",
        content,
        flags=re.IGNORECASE,
    )
    if readable:
        return parse_date(readable.group(0))
    return ""


def parse_feed(source: dict) -> list[Item]:
    text = fetch_text(source["url"])
    root = ET.fromstring(text)
    nodes = [node for node in root.iter() if local_name(node.tag) in {"item", "entry"}]
    items: list[Item] = []
    for node in nodes:
        title = child_text(node, ["title"])
        summary = child_text(node, ["description", "summary", "content", "encoded"])
        link = child_text(node, ["link"])
        if not link:
            for child in list(node):
                if local_name(child.tag) == "link":
                    link = child.attrib.get("href", "")
                    if link:
                        break
        published = parse_date(child_text(node, ["pubDate", "published", "updated"]))
        if title and link:
            items.append(
                Item(
                    title=title,
                    url=link,
                    source=source["name"],
                    summary=summary,
                    published=published,
                )
            )
    return items


def slug_to_title(slug: str) -> str:
    slug = slug.strip("/").split("/")[-1]
    return slug.replace("-", " ").replace("_", " ").title()


def parse_html_links(source: dict) -> list[Item]:
    text = fetch_text(source["url"])
    prefix = source["include_href_prefix"]
    seen: set[str] = set()
    items: list[Item] = []
    for raw_href in re.findall(r'href=["\']([^"\']+)["\']', text):
        href = html.unescape(raw_href)
        if not href.startswith(prefix):
            continue
        url = urllib.parse.urljoin(source["url"], href)
        normalized = url.split("#", 1)[0].split("?", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        title = slug_to_title(normalized)
        summary = ""
        published = ""
        if len(items) < 12:
            try:
                detail = fetch_text(normalized, timeout=10)
                title = extract_meta(detail, ["og:title", "twitter:title"]) or title
                summary = extract_meta(detail, ["description", "og:description", "twitter:description"])
                published = extract_page_date(detail)
            except Exception:
                pass
        items.append(
            Item(
                title=title,
                url=normalized,
                source=source["name"],
                summary=summary,
                published=published,
            )
        )
        if len(items) >= 20:
            break
    return items


def parse_markdown_changelog(source: dict) -> list[Item]:
    text = fetch_text(source["url"])
    lines = text.splitlines()
    items: list[Item] = []
    current_title = ""
    bullets: list[str] = []

    def flush() -> None:
        if not current_title:
            return
        useful = [clean_text(line.lstrip("-* ")) for line in bullets if line.strip().startswith(("-", "*"))]
        summary = "; ".join(useful[:5])
        anchor = re.sub(r"[^a-z0-9]+", "", current_title.lower())
        items.append(
            Item(
                title=f"Claude Code {current_title} changelog",
                url=f"{source.get('link', source['url'])}#{anchor}" if anchor else source.get("link", source["url"]),
                source=source["name"],
                summary=summary,
            )
        )

    for line in lines:
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            if current_title:
                flush()
                return items[:1]
            current_title = heading.group(1)
            bullets = []
            continue
        if current_title:
            bullets.append(line)

    flush()
    return items[:1]


def fingerprint(item: Item) -> str:
    basis = f"{item.source}\n{item.url or item.title}\n{item.title}".lower().strip()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def score_item(item: Item, source_priority: int) -> tuple[int, str]:
    haystack = f"{item.title}\n{item.summary}".lower()
    matched_title = [kw for kw in KEYWORDS if kw in item.title.lower()]
    matched_body = [kw for kw in KEYWORDS if kw in haystack and kw not in matched_title]
    matched_strong = [kw for kw in STRONG_RELEVANCE if kw in haystack]
    score = source_priority
    score += 30 * min(len(matched_strong), 3)
    score += 18 * min(len(matched_title), 4)
    score += 5 * min(len(matched_body), 6)
    if "internal fixes" in haystack:
        score -= 40
    if item.published:
        try:
            age_days = (dt.datetime.now(dt.timezone.utc).date() - dt.date.fromisoformat(item.published)).days
            if age_days <= 1:
                score += 45
            elif age_days <= 2:
                score += 35
            elif age_days <= 7:
                score += 20
            elif age_days > 30:
                score -= 20
        except ValueError:
            pass
    if not matched_strong and item.source != "Claude Code Changelog":
        score -= 110
    elif not matched_title and not matched_body:
        score -= 45
    reason_bits = []
    if matched_strong:
        reason_bits.append("strong: " + ", ".join(matched_strong[:4]))
    if matched_title:
        reason_bits.append("title: " + ", ".join(matched_title[:4]))
    if matched_body:
        reason_bits.append("body: " + ", ".join(matched_body[:4]))
    if not reason_bits:
        reason_bits.append("official source, weak coding keywords")
    return score, "; ".join(reason_bits)


def item_age_days(item: Item) -> int:
    if not item.published:
        return 3
    try:
        return (dt.datetime.now(dt.timezone.utc).date() - dt.date.fromisoformat(item.published)).days
    except ValueError:
        return 3


def freshness_bucket(item: Item) -> int:
    age = item_age_days(item)
    if age <= 1:
        return 4
    if age <= 3:
        return 3
    if age <= 7:
        return 2
    if age <= 14:
        return 1
    return 0


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"seen": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"seen": {}}
    if not isinstance(state, dict) or not isinstance(state.get("seen"), dict):
        return {"seen": {}}
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def collect_items(days: int) -> list[Item]:
    cutoff = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=days)
    collected: list[Item] = []
    for source in SOURCES:
        try:
            if source["kind"] == "feed":
                items = parse_feed(source)
            elif source["kind"] == "html_links":
                items = parse_html_links(source)
            elif source["kind"] == "markdown_changelog":
                items = parse_markdown_changelog(source)
            else:
                continue
        except Exception as exc:  # noqa: BLE001 - show source-specific failures without stopping the run.
            print(f"[WARN] {source['name']}: {exc}", file=sys.stderr)
            continue
        for item in items:
            if item.published:
                try:
                    if dt.date.fromisoformat(item.published) < cutoff:
                        continue
                except ValueError:
                    pass
            item.fingerprint = fingerprint(item)
            item.score, item.reason = score_item(item, int(source["priority"]))
            collected.append(item)
    return collected


def dedupe(items: list[Item]) -> list[Item]:
    best: dict[str, Item] = {}
    for item in items:
        key = item.fingerprint
        existing = best.get(key)
        if existing is None or item.score > existing.score:
            best[key] = item
    return list(best.values())


def concise_source_summary(item: Item, max_length: int = 260) -> str:
    text = clean_text(item.summary)
    text = re.sub(r"The post .+ appeared first on .+\.", "", text).strip()
    if not text:
        text = item.title
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "..."


def chinese_digest(item: Item) -> str:
    source_summary = concise_source_summary(item)
    title_lower = item.title.lower()
    summary_lower = source_summary.lower()
    haystack = f"{title_lower} {summary_lower}"

    if item.source == "Claude Code Changelog":
        if "2.1.139" in item.title:
            return (
                "Claude Code 最新 changelog 增加了 agent view 研究预览，可在一个列表里查看运行中、等待用户处理和已完成的 Claude Code 会话；"
                "同时新增 `/goal`，允许给任务设置完成条件并跨轮持续推进，还补强了插件详情、hook 参数、MCP 重连、转录视图导航和多项终端/IDE 修复。"
                "这说明 Claude Code 正在从交互式编码助手走向可观察、可恢复、可治理的长任务工作台。"
            )
        return (
            f"Claude Code 最新 changelog 继续围绕长任务、多会话协作和工程集成增强：{source_summary} 对日常工程团队来说，重点不是单点功能，"
            "而是 Claude Code 正在把一次性问答推进到可观察、可恢复、可治理的后台编码工作流。"
        )
    if "codex" in haystack and "safely" in haystack:
        return (
            "OpenAI 这篇文章披露了 Codex 在真实组织内安全运行的做法：用 sandbox、审批、网络策略和 agent-native telemetry 限定编码代理的行动边界，"
            "同时保留可审计轨迹。它的价值在于把“AI 会写代码”推进到“企业如何放心让 AI 跑命令、读仓库、改代码”的落地问题，适合安全和平台团队参考。"
        )
    if "copilot" in haystack and "code review" in haystack:
        return (
            "GitHub 更新了 Copilot code review 的用量指标，API 现在能按评论类型拆分代码审查建议，帮助企业或组织管理员看清 AI review 的使用结构。"
            "这类指标虽然不是模型能力发布，但对工程管理很实用：团队可以衡量 Copilot 在 PR 审查中的参与度、建议类型和治理效果，进一步评估自动审查是否真正改善交付。"
        )
    if "deprecation" in haystack or "deprecated" in haystack:
        return (
            f"GitHub Copilot 相关模型或功能进入迁移窗口：{source_summary} 这类动态对开发团队的影响通常不是新能力，而是兼容性和默认体验变化。"
            "如果团队在 IDE、PR 审查或内部平台中依赖指定模型，需要提前确认替代模型、截止日期、企业策略和用户沟通，避免自动化流程或开发者习惯在下线日被动中断。"
        )
    if "cloud agent" in haystack or ("copilot" in haystack and "agent" in haystack):
        return (
            "GitHub Copilot 相关更新继续补强云端代理能力，重点在权限、配置或自动化执行链路上做细化。对 AI coding 的意义是，编码代理越来越不只是 IDE 内补全，"
            "而是在云端围绕 issue、PR、仓库策略和企业控制面运行。团队采用时应关注它与现有权限、审计和代码所有权流程的衔接。"
        )
    if "codex" in haystack:
        return (
            f"OpenAI 官方发布与 Codex 相关的进展：{source_summary} 这说明 Codex 仍在从单个编码助手扩展到企业软件交付链路中的代理能力，"
            "覆盖开发、测试、部署环境或组织采用案例。对开发团队的启发是，评估 AI coding 工具时不能只看生成代码质量，也要看它是否能接入现有仓库、权限和工作流。"
        )
    if "claude code" in haystack or "claude api" in haystack:
        return (
            f"Anthropic 官方信息提到 Claude Code 或 Claude API 的相关变化：{source_summary} 对开发者来说，这类更新通常影响编码代理的可用额度、"
            "执行体验或 API 集成方式。若团队正在把 Claude 用于代码生成、重构、测试或自动化任务，需要关注限制、可用性和企业采购条件是否发生变化。"
        )
    if "api" in haystack or "model" in haystack:
        return (
            f"这条来自 {item.source} 的更新涉及模型或 API 能力：{source_summary} 对 AI coding 场景的影响主要体现在工具调用、开发者集成、"
            "多模态输入或自动化链路的能力边界上。它不一定是专门的编码产品发布，但可能改变 IDE 插件、内部平台和工程自动化系统可调用的底层能力。"
        )
    return (
        f"{item.source} 发布了与 AI coding 生态相关的更新：{source_summary} 这条信息的直接相关性需要结合团队使用场景判断，"
        "但它来自官方渠道，适合作为日报候选保留。若今天没有更多 OpenAI 或 Claude 的强相关发布，可以作为补充观察项。"
    )


def render_markdown(items: list[Item], mark_sent: bool) -> str:
    today = dt.datetime.now().date().isoformat()
    status = "已标记为已推送" if mark_sent else "未标记已推送"
    lines = [f"# AI Code 日报 - {today}", "", f"_状态：{status}。默认优先最近 7 天官方来源；若当天无强相关发布，会保留最近几天的重要进展。_", ""]
    if not items:
        lines.append("没有找到新的高质量候选。")
        return "\n".join(lines)
    has_today = any(item.published == today for item in items)
    if not has_today:
        lines.append(f"> 说明：当前官方源里没有找到 {today} 当天发布的强相关 AI coding 动态，下面是最近 7 天内未去重过滤的高相关官方进展。")
        lines.append("")
    for index, item in enumerate(items, 1):
        date_part = item.published or "官方最新条目，未提供日期"
        lines.append(f"## {index}. [{item.title}]({item.url})")
        lines.append("")
        lines.append(f"- 来源：{item.source}")
        lines.append(f"- 日期：{date_part}")
        lines.append(f"- 摘要：{chinese_digest(item)}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect AI coding news candidates with dedupe state.")
    parser.add_argument("--limit", type=int, default=5, help="Number of candidates to print.")
    parser.add_argument("--days", type=int, default=7, help="Maximum age for dated feed items.")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="Path to the sent-item state file.")
    parser.add_argument("--min-score", type=int, default=65, help="Minimum relevance score.")
    parser.add_argument("--include-seen", action="store_true", help="Include items already marked sent.")
    parser.add_argument("--mark-sent", action="store_true", help="Mark printed items as sent in the state file.")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    state = load_state(args.state)
    seen = state.setdefault("seen", {})
    items = dedupe(collect_items(args.days))
    candidates = [
        item
        for item in items
        if item.score >= args.min_score and (args.include_seen or item.fingerprint not in seen)
    ]
    candidates.sort(key=lambda item: (freshness_bucket(item), item.published, item.score), reverse=True)
    selected = candidates[: max(args.limit, 0)]

    if args.mark_sent:
        now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        for item in selected:
            seen[item.fingerprint] = {
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "published": item.published,
                "sent_at": now,
            }
        save_state(args.state, state)

    if args.format == "json":
        print(json.dumps([asdict(item) for item in selected], ensure_ascii=False, indent=2))
    else:
        print(render_markdown(selected, args.mark_sent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
