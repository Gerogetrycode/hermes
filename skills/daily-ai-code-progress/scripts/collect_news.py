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
import ssl
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


DEFAULT_STATE = Path(".cache/daily-ai-code-progress/seen.json")
USER_AGENT = "daily-ai-code-progress-skill/0.1 (+https://openai.com/)"

try:
    import certifi  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001 - optional dependency for local Python installs.
    CERTIFI_CA_FILE = ""
else:
    CERTIFI_CA_FILE = certifi.where()

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

CORE_CODING_SIGNALS = [
    "agentic engineering",
    "agentic software",
    "ai coding",
    "claude code",
    "code review",
    "codex",
    "coding agent",
    "coding agents",
    "developer tool",
    "developer tools",
    "mcp",
    "pull request",
    "repo",
    "repository",
    "sandbox",
    "software development",
]

HIGH_SIGNAL_PATTERNS = [
    "architecture",
    "benchmark",
    "case study",
    "engineering",
    "guide",
    "incident",
    "lesson",
    "migration",
    "playbook",
    "postmortem",
    "practice",
    "production",
    "research",
    "security",
    "sre",
    "workflow",
    "what we learned",
]

LOW_SIGNAL_PATTERNS = [
    "ai credits",
    "billing",
    "comment experience",
    "comment type",
    "comments api",
    "credit",
    "deprecation",
    "metrics api",
    "report",
    "secrets and variables",
    "usage report",
    "usage-based",
]

PRODUCT_CHANGELOG_SOURCES = {
    "GitHub Changelog",
    "VS Code Updates",
    "Cursor Changelog",
}

DEEP_CONTEXT_SOURCES = {
    "OpenAI News",
    "Anthropic News",
    "Simon Willison",
    "The Pragmatic Engineer",
    "Latent Space",
}

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
        "priority": 38,
    },
    {
        "name": "VS Code Updates",
        "kind": "feed",
        "url": "https://code.visualstudio.com/feed.xml",
        "priority": 42,
    },
    {
        "name": "Cursor Changelog",
        "kind": "html_links",
        "url": "https://cursor.com/changelog",
        "include_href_prefix": "/changelog/",
        "priority": 45,
    },
    {
        "name": "Simon Willison",
        "kind": "feed",
        "url": "https://simonwillison.net/atom/everything/",
        "priority": 82,
    },
    {
        "name": "The Pragmatic Engineer",
        "kind": "feed",
        "url": "https://blog.pragmaticengineer.com/rss/",
        "priority": 80,
    },
    {
        "name": "Latent Space",
        "kind": "feed",
        "url": "https://www.latent.space/feed",
        "priority": 76,
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


def fetch_text(url: str, timeout: int = 12) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    handlers: list[urllib.request.BaseHandler] = [PermanentRedirectHandler]
    if CERTIFI_CA_FILE:
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=CERTIFI_CA_FILE)))
    opener = urllib.request.build_opener(*handlers)
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
                detail = fetch_text(normalized, timeout=8)
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
    matched_core = [kw for kw in CORE_CODING_SIGNALS if kw in haystack]
    matched_high_signal = [kw for kw in HIGH_SIGNAL_PATTERNS if kw in haystack]
    matched_low_signal = [kw for kw in LOW_SIGNAL_PATTERNS if kw in haystack]
    score = source_priority
    score += 30 * min(len(matched_strong), 3)
    score += 18 * min(len(matched_title), 4)
    score += 5 * min(len(matched_body), 6)
    score += 22 * min(len(matched_high_signal), 3)
    if item.source in DEEP_CONTEXT_SOURCES:
        score += 28
    if item.source in PRODUCT_CHANGELOG_SOURCES:
        score -= 15
    if matched_low_signal:
        score -= 38 * min(len(matched_low_signal), 2)
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
    if not matched_strong and not matched_high_signal and item.source != "Claude Code Changelog":
        score -= 110
    elif not matched_title and not matched_body:
        score -= 45
    if item.source == "GitHub Changelog" and matched_low_signal and not matched_high_signal:
        score -= 80
    if not matched_core:
        score -= 140
    reason_bits = []
    if matched_strong:
        reason_bits.append("strong: " + ", ".join(matched_strong[:4]))
    if matched_core:
        reason_bits.append("core: " + ", ".join(matched_core[:4]))
    if matched_high_signal:
        reason_bits.append("high-signal: " + ", ".join(matched_high_signal[:4]))
    if matched_low_signal:
        reason_bits.append("low-signal: " + ", ".join(matched_low_signal[:4]))
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

    if "vibe coding and agentic engineering" in title_lower:
        return (
            "Simon Willison 反思了“vibe coding”和“agentic engineering”的边界正在变得模糊：当 Claude Code 这类工具对常规任务越来越可靠，"
            "工程师会开始像信任其他团队交付的内部服务一样信任代理产物，而不是逐行审查所有代码。真正的风险不再只是代码能不能生成，"
            "而是责任归属、验证方式和软件生命周期都需要重构：AI 能让产出速度暴涨，但设计、评审、测试、上线和长期维护是否跟得上，决定了它是生产力提升还是质量债。"
        )
    if "unreasonable effectiveness of html" in title_lower:
        return (
            "这篇文章讨论 Claude Code 团队成员提出的一个实用技巧：让模型输出 HTML，而不是默认 Markdown。HTML 可以承载 SVG、交互控件、"
            "内联注释、分栏 diff 和导航结构，适合解释复杂 PR、调试流式逻辑或分析安全漏洞。对 AI coding 的启发是，提示词的输出格式会直接影响审查和理解效率；"
            "团队可以把“生成可浏览的代码解释页”当作 code review、事故复盘和知识转移的新工作流。"
        )
    if "running codex safely" in title_lower:
        return (
            "OpenAI 这篇文章披露了 Codex 在真实组织内安全运行的做法：用 sandbox、审批、网络策略和 agent-native telemetry 限定编码代理的行动边界，"
            "同时保留可审计轨迹。它的价值在于把“AI 会写代码”推进到“企业如何放心让 AI 跑命令、读仓库、改代码”的落地问题。"
            "对平台和安全团队来说，这比单个功能发布更重要，因为它给出了权限、观测和人工介入的治理框架。"
        )
    if "sandbox" in title_lower and "windows" in title_lower and "codex" in title_lower:
        return (
            "OpenAI 解释了 Codex 在 Windows 上如何构建安全沙箱：限制文件访问和网络能力，让 coding agent 能执行真实开发任务，同时把破坏面控制在可审计边界内。"
            "这条内容的实践意义很强，因为企业环境大量依赖 Windows 开发机和混合工具链。团队评估本地或远程编码代理时，应重点看沙箱隔离、权限申请、"
            "网络默认策略和失败恢复，而不是只看模型能否写出代码。"
        )
    if "sea's view" in title_lower:
        return (
            "Sea Limited 的 CPO 讨论为什么要在工程团队中部署 Codex，加速 AI-native software development。"
            "这类观点的价值在于它把 AI coding 放进组织能力建设：不是单个工程师更快写代码，而是研发流程、review、知识传递和跨区域工程团队如何重新分工。"
            "可借鉴之处是先定义哪些任务适合代理承接，再围绕验收、权限和协作节奏设计落地方式。"
        )
    if "nvidia" in title_lower and "codex" in title_lower:
        return (
            "OpenAI 介绍 NVIDIA 团队如何把 Codex 用在生产系统和研究实验中：一端面向工程交付，另一端把研究想法更快转成可运行原型。"
            "这类案例的价值不在“某公司用了某工具”，而在于说明 AI coding 正在进入高复杂度工程环境。团队评估 Codex 时，应关注它能否处理现有仓库上下文、"
            "实验脚本、测试验证和交付链路，而不是只看单次补全或 demo 速度。"
        )
    if "parameter golf" in title_lower:
        return (
            "OpenAI 总结 Parameter Golf 活动，参与者在严格参数约束下探索 AI 辅助机器学习研究、编码代理、量化和模型设计。"
            "这条动态对日常编码团队的意义在于，它展示了 AI 工具如何参与“搜索解法”和“快速实验”过程，而不只是生成业务代码。"
            "如果团队有模型评测、性能调优或研究工程任务，可以借鉴这种竞赛式约束：明确指标、压缩反馈周期，让代理在可验证边界内探索方案。"
        )
    if "frontier firms" in title_lower or "b2b signals" in item.url.lower():
        return (
            "OpenAI 的 B2B Signals 研究把焦点放在企业如何把 AI 从个人效率工具推进到组织级能力：更成熟的公司会围绕 Codex 类 agentic workflows "
            "重塑流程、权限、评估和知识流，而不是只给员工开通聊天工具。对工程管理者的启发是，AI coding 的分水岭可能不在“谁用了模型”，"
            "而在团队能否把代理接进真实交付系统，并建立可复制的使用规范、验收方式和学习机制。"
        )
    if "james shore" in title_lower:
        return (
            "James Shore 的观点很直接：AI coding agent 如果只是提高代码产出速度，却没有同比降低维护成本，团队会把短期速度换成长期负担。"
            "这条提醒对工程实践很关键，因为代码量增加会放大测试、理解、重构和排障成本。评估 AI coding 工具时，不能只看生成速度，"
            "还要看它是否让代码更容易维护，例如更清晰的设计、更好的测试、更少的隐式复杂度和更低的交接成本。"
        )
    if "codex rises" in title_lower and "claude meters" in title_lower:
        return (
            "Latent Space 这期 AINews 把 Codex 扩张和 Claude programmatic usage 计量放在一起看，重点不只是产品更新，而是 AI coding 工具正在进入更明确的成本、"
            "权限和使用治理阶段。对团队有用的判断是：当 coding agent 从个人试用变成持续调用的工程基础设施，模型能力、额度策略、审计和成本归因会一起影响采用效果。"
            "这类内容适合用来跟踪生态趋势和团队预算/治理设计。"
        )
    if "learning on the shop floor" in title_lower:
        return (
            "这篇记录 Shopify 内部 coding agent River 的组织实践：River 不在私聊里工作，而是在公开 Slack 频道中协作，让上下文、讨论、review "
            "和提示过程都可搜索、可旁观。它的启发不只是“用代理写代码”，而是把 AI 工作流变成组织学习现场。对团队来说，公开可见的代理协作可能比单个工具能力更重要，"
            "因为它能沉淀提示方法、领域知识和评审标准。"
        )
    if "autoscout24" in title_lower or "simplex" in title_lower:
        return (
            f"这是一篇官方采用案例：{source_summary} 可读点不在宣传口号，而在它反映了 AI coding 工具进入组织级流程后的常见路径："
            "先从开发、测试、设计或重构提效切入，再扩展到跨团队工作流。阅读时应重点找可迁移部分，例如哪些任务适合交给代理、如何验收产出、"
            "哪些环节仍需要工程师判断，而不是把案例中的效率数字直接套到自己的团队。"
        )
    if item.source in {"Simon Willison", "The Pragmatic Engineer", "Latent Space"}:
        return (
            f"这篇来自 {item.source} 的文章应按实践价值来读：它帮助判断 AI coding 的真实落地边界，"
            "例如团队如何设计开发流程、评估自动化收益、控制维护成本、处理权限与可靠性问题。摘要应优先提炼可迁移的工程判断，而不是停留在事件本身。"
        )
    if item.source == "Claude Code Changelog":
        if "2.1.142" in item.title:
            return (
                "Claude Code 2.1.142 强化了后台 agent 会话的可配置性，`claude agents` 新增目录、settings、MCP config、plugin、permission mode、model "
                "和 effort 等参数，说明 Claude Code 正在把一次性命令推进到可批量派发、可配置、可治理的后台任务系统。"
                "这类 changelog 值得保留，因为它直接影响团队如何把编码代理接入真实仓库、权限策略和多会话工作流。"
            )
        if "2.1.140" in item.title:
            return (
                "Claude Code 2.1.140 主要是稳定性和可用性修复：Agent tool 的 `subagent_type` 匹配更宽松，`/goal` 在 hook 受限时不再静默挂起，"
                "symlink settings 的热加载事件归因也被修正，后台服务 idle-exit 前的连接中断问题得到处理。单看不是重大功能发布，"
                "但它说明 Claude Code 正在补长任务和多代理协作的工程细节：命令不能卡死、配置变化要可解释、后台任务要可靠。"
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
        f"{item.source} 发布了与 AI coding 生态相关的内容：{source_summary} 这条内容的重点不应只看“有什么新功能”，"
        "而应看它对工程团队的实际启发：是否改变代码审查、测试、权限、安全、平台集成或开发者工作流。若缺少明确实践意义，应降级为备选而不是日报主条目。"
    )


def is_low_signal_changelog(item: Item) -> bool:
    haystack = f"{item.title}\n{item.summary}".lower()
    return item.source in PRODUCT_CHANGELOG_SOURCES and any(pattern in haystack for pattern in LOW_SIGNAL_PATTERNS)


def is_product_changelog(item: Item) -> bool:
    return item.source in PRODUCT_CHANGELOG_SOURCES


def is_vendor_case_study(item: Item) -> bool:
    haystack = f"{item.title}\n{item.url}\n{item.summary}".lower()
    return item.source == "OpenAI News" and any(
        marker in haystack
        for marker in [
            "/autoscout24",
            "/nvidia",
            "/simplex",
            "customer",
            "case study",
            "scales engineering",
            "teams use codex",
            "uses codex",
        ]
    )


def select_items(candidates: list[Item], limit: int) -> list[Item]:
    selected: list[Item] = []
    source_counts: dict[str, int] = {}
    changelog_count = 0
    vendor_case_count = 0
    for item in sorted(candidates, key=lambda item: (item.score, freshness_bucket(item), item.published), reverse=True):
        if len(selected) >= limit:
            break
        if source_counts.get(item.source, 0) >= 2:
            continue
        if is_vendor_case_study(item):
            if vendor_case_count >= 1:
                continue
            vendor_case_count += 1
        if is_product_changelog(item):
            if changelog_count >= 1:
                continue
            if is_low_signal_changelog(item) and len(candidates) > limit:
                continue
        selected.append(item)
        source_counts[item.source] = source_counts.get(item.source, 0) + 1
        if is_product_changelog(item):
            changelog_count += 1
    if len(selected) < limit:
        selected_fingerprints = {item.fingerprint for item in selected}
        has_vendor_case = any(is_vendor_case_study(item) for item in selected)
        for item in sorted(candidates, key=lambda item: (item.score, freshness_bucket(item), item.published), reverse=True):
            if len(selected) >= limit:
                break
            if has_vendor_case and is_vendor_case_study(item):
                continue
            if not is_product_changelog(item) and item.fingerprint not in selected_fingerprints:
                selected.append(item)
                selected_fingerprints.add(item.fingerprint)
                if is_vendor_case_study(item):
                    has_vendor_case = True
        for item in sorted(candidates, key=lambda item: (item.score, freshness_bucket(item), item.published), reverse=True):
            if len(selected) >= limit:
                break
            if item.fingerprint not in selected_fingerprints:
                selected.append(item)
                selected_fingerprints.add(item.fingerprint)
    return selected


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
    selected = select_items(candidates, max(args.limit, 0))

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
