#!/usr/bin/env python3
"""Build and deliver a daily AI builders digest using follow-builders feeds."""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import html
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, asdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable


FOLLOW_BUILDERS_REPO = "https://github.com/zarazhangrui/follow-builders"
FOLLOW_BUILDERS_COMMIT = "3b1d3c7b8269e158e05dd79f8a3aabb9e8e8e60a"
FEED_X_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-x.json"
FEED_PODCASTS_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-podcasts.json"
FEED_BLOGS_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-blogs.json"
FAIYI_LATEST_API = "http://www.faiyi.com/index.php?rest_route=/wp/v2/posts&categories=7&per_page=1"
DEFAULT_STATE = Path.home() / ".hermes/state/daily-ai-code-progress/seen.json"
DEFAULT_OUTPUT_DIR = Path.home() / ".hermes/state/daily-ai-code-progress/outputs"
DEFAULT_CACHE_DIR = Path.home() / ".hermes/state/daily-ai-code-progress/cache"
USER_AGENT = "daily-ai-code-progress-follow-builders/0.2"
DEFAULT_HERMES_CLI = "/Users/bytedance/Documents/hermes/hermes-agent/hermes"
DEFAULT_DIGEST_LIMIT = 10
MAX_DIGEST_LIMIT = 10

try:
    import certifi  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001 - optional dependency.
    CERTIFI_CA_FILE = ""
else:
    CERTIFI_CA_FILE = certifi.where()


AI_CODING_TERMS = [
    "agent",
    "agents",
    "agentic",
    "api",
    "automation",
    "claude code",
    "code",
    "codex",
    "coding",
    "copilot",
    "developer",
    "devtools",
    "eval",
    "github",
    "ide",
    "mcp",
    "model",
    "openai",
    "programmatic",
    "prompt",
    "repo",
    "sdk",
    "security",
    "software",
    "tool",
    "tools",
    "workflow",
]

CORE_AI_CODING_TERMS = [
    "agent",
    "agents",
    "agentic",
    "ai-native",
    "api",
    "claude code",
    "code",
    "codex",
    "coding",
    "copilot",
    "delegate tasks to agents",
    "developer tool",
    "developer tools",
    "devtools",
    "eval",
    "github",
    "ide",
    "mcp",
    "model context protocol",
    "prompt",
    "repo",
    "sandbox",
    "sdk",
]

LOW_VALUE_TERMS = [
    "glad you're liking",
    "great event",
    "like button",
    "pod link",
    "subscribe",
    "you found it",
]

TOPIC_RULES = [
    ("MCP / API 工具层", ["mcp", "api", "sdk", "stainless", "oauth", "tool"]),
    ("coding agent 工作流", ["codex", "claude code", "coding agent", "agentic", "delegate"]),
    ("模型与成本治理", ["meter", "usage", "pricing", "capacity", "cost", "quota"]),
    ("安全与沙箱", ["sandbox", "security", "permission", "scope", "oauth"]),
    ("工程组织与产品", ["workflow", "developer", "product", "startup", "company"]),
]

FALLBACK_SIGNAL_RULES = [
    ("AI 成本、使用量与总支出的关系", ["cost", "pricing", "spend", "budget", "capex", "token"]),
    ("个人评测集、模型比较与选型方法", ["personal eval", "benchmark", "eval set", "model selection"]),
    ("一次性软件和按需生成工具", ["disposable", "discarded after usage", "single-use"]),
    ("agent 的购买、支付权限与止损控制", ["overspend", "buy things", "selling", "payment", "pay"]),
    ("skills、system prompt 与 agent 配置", ["skills", "system prompt", "instructions.md"]),
    ("Claude Code、Codex 与 coding agent 工作流", ["claude code", "codex", "coding agent"]),
    ("MCP、API 与工具接口", ["mcp", "api", "sdk", "tool calling"]),
    ("权限隔离、安全评测与沙箱", ["security", "cybersecurity", "sandbox", "permission"]),
    ("真实仓库、测试、评审与交付流程", ["repository", "repo", "test", "review", "ci"]),
    ("产品采用、组织协作与工程效率", ["workflow", "developer", "product", "company", "team"]),
]


@dataclass
class DigestItem:
    title: str
    url: str
    source: str
    published: str
    summary: str
    score: int
    fingerprint: str = ""
    raw_content: str = ""


class PermanentRedirectHandler(urllib.request.HTTPRedirectHandler):
    def http_error_308(self, req, fp, code, msg, headers):  # noqa: N802
        return self.http_error_301(req, fp, code, msg, headers)


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
            self.parts.append("\n" if self.in_li else "\n\n")
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
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()


def build_opener() -> urllib.request.OpenerDirector:
    handlers: list[urllib.request.BaseHandler] = [PermanentRedirectHandler]
    if CERTIFI_CA_FILE:
        handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=CERTIFI_CA_FILE)))
    return urllib.request.build_opener(*handlers)


def retry_config() -> tuple[int, float]:
    attempts = int(os.environ.get("DAILY_AI_CODE_FETCH_RETRIES", "4"))
    base_sleep = float(os.environ.get("DAILY_AI_CODE_FETCH_RETRY_SLEEP", "5"))
    return max(attempts, 1), max(base_sleep, 0.0)


def open_with_retries(request: urllib.request.Request, timeout: int) -> bytes:
    attempts, base_sleep = retry_config()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with build_opener().open(request, timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # noqa: BLE001 - network/DNS/TLS errors all use different exception types.
            last_error = exc
            if attempt >= attempts:
                break
            sleep_for = base_sleep * attempt
            print(
                f"warning: fetch attempt {attempt}/{attempts} failed for {request.full_url}: {exc}; retrying in {sleep_for:g}s",
                file=sys.stderr,
            )
            time.sleep(sleep_for)
    assert last_error is not None
    raise last_error


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    attempts, base_sleep = retry_config()
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with build_opener().open(request, timeout=timeout) as response:
                data = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
            return data.decode(charset, errors="replace")
        except Exception as exc:  # noqa: BLE001 - network/DNS/TLS errors all use different exception types.
            last_error = exc
            if attempt >= attempts:
                break
            sleep_for = base_sleep * attempt
            print(
                f"warning: fetch attempt {attempt}/{attempts} failed for {url}: {exc}; retrying in {sleep_for:g}s",
                file=sys.stderr,
            )
            time.sleep(sleep_for)
    assert last_error is not None
    raise last_error


def fetch_json(url: str, timeout: int = 20) -> object:
    return json.loads(fetch_text(url, timeout=timeout))


def cached_feed_path(cache_dir: Path, name: str) -> Path:
    return cache_dir / f"{name}.json"


def fetch_feed_json(url: str, name: str, cache_dir: Path, timeout: int = 20) -> tuple[dict, str]:
    cache_path = cached_feed_path(cache_dir, name)
    try:
        payload = fetch_json(url, timeout=timeout)
        if not isinstance(payload, dict):
            raise RuntimeError(f"feed {name} returned non-object JSON")
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return payload, "live"
    except Exception as exc:  # noqa: BLE001 - fallback to the last good feed snapshot.
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                print(f"warning: using cached {name} feed after fetch failure: {exc}", file=sys.stderr)
                return cached, "cache"
        print(f"warning: {name} feed unavailable and no cache exists: {exc}", file=sys.stderr)
        return {}, "unavailable"


def clean_text(value: str) -> str:
    value = re.sub(r"https?://\S+", "", value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def short_text(value: str, max_chars: int) -> str:
    value = clean_text(value)
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1].rstrip() + "..."


def parse_date(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return value[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()


def fingerprint(parts: Iterable[str]) -> str:
    basis = "\n".join(parts).lower().strip()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def classify_topic(text: str) -> str:
    lower = text.lower()
    for label, terms in TOPIC_RULES:
        if any(term in lower for term in terms):
            return label
    return "AI builders 动态"


def fallback_focuses(item: DigestItem, limit: int = 3) -> list[str]:
    text = f"{item.title}\n{item.summary}\n{item.raw_content}".lower()
    focuses = [label for label, terms in FALLBACK_SIGNAL_RULES if any(term in text for term in terms)]
    return focuses[:limit] or ["AI 工具在真实业务中的使用方式、适用边界与工程影响"]


def fallback_chinese_summary(item: DigestItem) -> str:
    """Render a Chinese-first summary without copying long source excerpts.

    This path is used when the semantic remix model is unavailable. It stays
    conservative: describe detected themes without adding a generic implication
    sentence that the source itself may not support.
    """
    topic = classify_topic(f"{item.title}\n{item.summary}\n{item.raw_content}")
    focus = "、".join(fallback_focuses(item))
    if item.source.startswith("X / "):
        author = item.source.removeprefix("X / ").strip() or "这位 builder"
        return (
            f"{author} 的这条动态聚焦「{topic}」，可识别的主题包括{focus}。"
            "原帖信息较短，建议打开链接核对作者的具体表述、例子和前提。"
        )
    if item.source.startswith("Podcast / "):
        show = item.source.removeprefix("Podcast / ").strip() or "这期播客"
        return (
            f"这期 {show} 围绕「{topic}」展开，讨论重点包括{focus}。"
            "本地摘要只保留可识别主题，具体观点以节目原文为准。"
        )
    return (
        f"这篇来自 {item.source} 的内容围绕「{topic}」展开，重点涉及{focus}。"
        "具体机制、数据和适用范围以原文为准。"
    )


def chinese_text_share(text: str) -> float:
    chinese_chars = len(re.findall(r"[\u3400-\u9fff]", text))
    latin_chars = len(re.findall(r"[A-Za-z]", text))
    total = chinese_chars + latin_chars
    return chinese_chars / total if total else 0.0


def validate_chinese_digest(markdown: str) -> None:
    summaries = re.findall(r"(?m)^-\s*摘要：\s*(.+)$", markdown)
    if not summaries:
        raise RuntimeError("Hermes remix returned no digest summaries")
    for index, summary in enumerate(summaries, 1):
        chinese_chars = len(re.findall(r"[\u3400-\u9fff]", summary))
        if chinese_chars < 60 or chinese_text_share(summary) < 0.45:
            raise RuntimeError(f"Hermes remix summary {index} is not Chinese-first")
        if re.search(r"(?:\b[A-Za-z][A-Za-z'’-]*\b[\s,;:()'’-]*){20,}", summary):
            raise RuntimeError(f"Hermes remix summary {index} contains a long English passage")
        if re.search(r"(?:实践含义是|价值在于|意义在于|对(?:工程)?团队而言|对(?:工程)?团队的(?:价值|意义)在于)", summary):
            raise RuntimeError(f"Hermes remix summary {index} uses generic commentary boilerplate")


def signal_score(text: str) -> int:
    lower = text.lower()
    score = 0
    score += 24 * sum(1 for term in CORE_AI_CODING_TERMS if term in lower)
    score += 12 * sum(1 for term in AI_CODING_TERMS if term in lower)
    score -= 35 * sum(1 for term in LOW_VALUE_TERMS if term in lower)
    if len(clean_text(text)) > 160:
        score += 15
    return score


def has_core_ai_coding_signal(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in CORE_AI_CODING_TERMS)


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
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def collect_x_items(feed: dict) -> list[DigestItem]:
    items: list[DigestItem] = []
    for account in feed.get("x", []) or []:
        if not isinstance(account, dict):
            continue
        tweets = [tweet for tweet in account.get("tweets", []) or [] if isinstance(tweet, dict)]
        scored: list[tuple[int, dict]] = []
        for tweet in tweets:
            text = clean_text(str(tweet.get("text", "")))
            if not text:
                continue
            if not has_core_ai_coding_signal(text):
                continue
            score = signal_score(text)
            score += min(int(tweet.get("likes") or 0), 500) // 8
            score += min(int(tweet.get("retweets") or 0), 100) // 2
            if score >= 35:
                scored.append((score, tweet))
        if not scored:
            continue
        scored.sort(key=lambda pair: pair[0], reverse=True)
        top = [tweet for _, tweet in scored[:3]]
        combined = " ".join(str(tweet.get("text", "")) for tweet in top)
        topic = classify_topic(combined)
        name = str(account.get("name") or account.get("handle") or "AI builder")
        handle = str(account.get("handle") or "").strip()
        published = parse_date(str(top[0].get("createdAt") or ""))
        url = str(top[0].get("url") or (f"https://x.com/{handle}" if handle else ""))
        snippets = "；".join(short_text(str(tweet.get("text", "")), 120) for tweet in top[:2])
        summary = f"{name} 最近围绕「{topic}」发布了相关动态。核心信息：{snippets}。"
        item = DigestItem(
            title=f"{name}: {topic}",
            url=url,
            source=f"X / {name}",
            published=published,
            summary=summary,
            score=scored[0][0] + 20,
            raw_content="\n\n".join(clean_text(str(tweet.get("text", ""))) for tweet in top),
        )
        item.fingerprint = fingerprint([item.source, item.url, item.title])
        items.append(item)
    return items


def transcript_excerpt(transcript: str, terms: list[str], max_chars: int = 420) -> str:
    text = clean_text(re.sub(r"Speaker \d+\s*\|\s*\d+:\d+\s*-\s*\d+:\d+", " ", transcript))
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    selected = [s for s in sentences if any(term in s.lower() for term in terms)]
    chosen = " ".join(selected[:4]) or " ".join(sentences[:4])
    return short_text(chosen, max_chars)


def collect_podcast_items(feed: dict) -> list[DigestItem]:
    items: list[DigestItem] = []
    for podcast in feed.get("podcasts", []) or []:
        if not isinstance(podcast, dict):
            continue
        title = str(podcast.get("title") or podcast.get("name") or "Podcast")
        transcript = str(podcast.get("transcript") or "")
        haystack = f"{title}\n{transcript}"
        score = signal_score(haystack) + 45
        if score < 60:
            continue
        topic = classify_topic(haystack)
        excerpt = transcript_excerpt(transcript, AI_CODING_TERMS)
        source_name = str(podcast.get("name") or "Podcast")
        summary = (
            f"这一期 {source_name} 适合关注「{topic}」。"
            f"要点是：{excerpt}"
        )
        item = DigestItem(
            title=title,
            url=str(podcast.get("url") or ""),
            source=f"Podcast / {source_name}",
            published=parse_date(str(podcast.get("publishedAt") or "")),
            summary=summary,
            score=score,
            raw_content=excerpt,
        )
        item.fingerprint = fingerprint([item.source, item.url, item.title])
        items.append(item)
    return items


def collect_blog_items(feed: dict) -> list[DigestItem]:
    items: list[DigestItem] = []
    for blog in feed.get("blogs", []) or []:
        if not isinstance(blog, dict):
            continue
        title = str(blog.get("title") or blog.get("name") or "Blog post")
        body = str(blog.get("summary") or blog.get("content") or blog.get("text") or "")
        haystack = f"{title}\n{body}"
        score = signal_score(haystack) + 35
        if score < 60:
            continue
        topic = classify_topic(haystack)
        summary = (
            f"这篇文章的主线是「{topic}」。{short_text(body or title, 320)}"
        )
        item = DigestItem(
            title=title,
            url=str(blog.get("url") or blog.get("link") or ""),
            source=str(blog.get("source") or blog.get("name") or "Blog"),
            published=parse_date(str(blog.get("publishedAt") or blog.get("date") or "")),
            summary=summary,
            score=score,
            raw_content=short_text(body or title, 1200),
        )
        item.fingerprint = fingerprint([item.source, item.url, item.title])
        items.append(item)
    return items


def collect_builders_digest(limit: int, state_path: Path, include_seen: bool, cache_dir: Path) -> tuple[list[DigestItem], dict]:
    feed_x, x_status = fetch_feed_json(os.environ.get("FOLLOW_BUILDERS_FEED_X_URL", FEED_X_URL), "feed-x", cache_dir)
    feed_podcasts, podcasts_status = fetch_feed_json(
        os.environ.get("FOLLOW_BUILDERS_FEED_PODCASTS_URL", FEED_PODCASTS_URL),
        "feed-podcasts",
        cache_dir,
    )
    feed_blogs, blogs_status = fetch_feed_json(
        os.environ.get("FOLLOW_BUILDERS_FEED_BLOGS_URL", FEED_BLOGS_URL),
        "feed-blogs",
        cache_dir,
    )
    feeds = {
        "x": feed_x,
        "podcasts": feed_podcasts,
        "blogs": feed_blogs,
    }
    state = load_state(state_path)
    seen = state.setdefault("seen", {})
    items = collect_podcast_items(feeds["podcasts"]) + collect_blog_items(feeds["blogs"]) + collect_x_items(feeds["x"])
    candidates = [item for item in items if include_seen or item.fingerprint not in seen]
    candidates.sort(key=lambda item: (item.score, item.published), reverse=True)

    selected: list[DigestItem] = []
    source_families: set[str] = set()
    for item in candidates:
        family = item.source.split("/", 1)[0].strip()
        if family in source_families and len(source_families) < 3:
            continue
        selected.append(item)
        source_families.add(family)
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        selected_ids = {item.fingerprint for item in selected}
        for item in candidates:
            if item.fingerprint not in selected_ids:
                selected.append(item)
                selected_ids.add(item.fingerprint)
            if len(selected) >= limit:
                break

    meta = {
        "feedGeneratedAt": feeds["x"].get("generatedAt") or feeds["podcasts"].get("generatedAt") or feeds["blogs"].get("generatedAt"),
        "xBuilders": len(feeds["x"].get("x", []) or []),
        "podcastEpisodes": len(feeds["podcasts"].get("podcasts", []) or []),
        "blogPosts": len(feeds["blogs"].get("blogs", []) or []),
        "feedStatus": {
            "x": x_status,
            "podcasts": podcasts_status,
            "blogs": blogs_status,
        },
    }
    return selected[:limit], meta


def mark_sent(items: list[DigestItem], state_path: Path) -> None:
    state = load_state(state_path)
    seen = state.setdefault("seen", {})
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for item in items:
        seen[item.fingerprint] = {
            "title": item.title,
            "url": item.url,
            "source": item.source,
            "published": item.published,
            "sent_at": now,
        }
    save_state(state_path, state)


def render_builders_markdown(items: list[DigestItem], meta: dict) -> str:
    today = dt.datetime.now().date().isoformat()
    lines = [
        f"# AI Builders Digest - {today}",
        "",
        f"_来源：follow-builders central feed；feed 更新时间：{meta.get('feedGeneratedAt') or 'unknown'}_",
        "",
    ]
    if not items:
        lines.append("没有找到新的高质量 builders 动态。")
        return "\n".join(lines)
    for index, item in enumerate(items, 1):
        date_part = item.published or "未提供日期"
        lines.extend(
            [
                f"## {index}. [{item.title}]({item.url})",
                "",
                f"- 来源：{item.source}",
                f"- 日期：{date_part}",
                f"- 摘要：{fallback_chinese_summary(item)}",
                "",
            ]
        )
    lines.append(f"_Feed skill: {FOLLOW_BUILDERS_REPO} @ {FOLLOW_BUILDERS_COMMIT[:7]}_")
    return "\n".join(lines)


def build_remix_prompt(items: list[DigestItem], meta: dict, limit: int) -> str:
    today = dt.datetime.now().date().isoformat()
    payload = {
        "date": today,
        "source": {
            "repo": FOLLOW_BUILDERS_REPO,
            "integrated_commit": FOLLOW_BUILDERS_COMMIT,
            "feeds": ["feed-x.json", "feed-podcasts.json", "feed-blogs.json"],
            "stats": meta,
        },
        "candidates": [
            {
                "fingerprint": item.fingerprint,
                "title": item.title,
                "url": item.url,
                "source": item.source,
                "published": item.published,
                "topic": classify_topic(f"{item.title}\n{item.summary}\n{item.raw_content}"),
                "local_hint": item.summary,
                "source_excerpt": short_text(item.raw_content or item.summary, 1400),
            }
            for item in items
            if item.url
        ],
    }
    return (
        "你是 AI builders digest 的编辑。下面是从 follow-builders central feed 取得的候选源数据，"
        "包括 X builders posts、podcast transcript excerpt、官方/公司 blog 摘要。\n\n"
        f"任务：从候选中精选高质量内容，输出一张中文 Markdown 简报。常规目标是 5 条；如果当天确实有更多高质量内容，可以扩展到最多 {limit} 条。\n\n"
        "编辑标准：\n"
        "1. 优先选择对 AI coding、agent 工作流、MCP/API 工具层、IDE、sandbox、eval、repo/CI、模型 API 落地有实践意义的内容。\n"
        "2. 跳过泛创业鸡汤、寒暄、纯推广、只有热度但缺少工程含义的动态。\n"
        "3. 可以选择 podcast/blog/X 任意来源，但不要为了来源多样性牺牲质量。\n"
        "4. 每条摘要写 120-220 个中文字符，讲清楚来源本身说了什么、提到的例子/机制/限制是什么；"
        "只有当来源明确支持时，才用一句短点评说明可读性或影响。\n"
        "   摘要正文必须以中文为主。产品名、代码标识符可以保留英文，但不要复制完整英文句子；任何英文直接引语不得超过 20 个英文单词。\n"
        "5. 不要复用固定套话，尤其不要写“相比零散 changelog”“实践含义是”“价值在于”“意义在于”“对工程团队而言”这类反复句式；"
        "如果找不到贴合原帖的点评，就只做事实摘要。\n"
        "6. 只使用 JSON 中已有信息，不要编造数据、发布日期、产品能力或人物身份。\n"
        "7. 每条标题必须使用原始链接，格式为 `## 1. [标题](URL)`，并保留来源和日期。\n\n"
        "8. 不要输出筛选说明、候选统计、额外解释或 Markdown 代码围栏；只输出最终简报正文。\n\n"
        "输出格式必须是：\n"
        f"# AI Builders Digest - {today}\n\n"
        "_来源：follow-builders central feed；feed 更新时间：..._\n\n"
        "## 1. [标题](URL)\n\n"
        "- 来源：...\n"
        "- 日期：...\n"
        "- 摘要：...\n\n"
        f"数量要求：不要硬凑条数；低质量日可以少于 5 条，高质量日可以多于 5 条，但最多 {limit} 条。末尾加一行 `_Feed skill: {FOLLOW_BUILDERS_REPO} @ {FOLLOW_BUILDERS_COMMIT[:7]}_`。\n\n"
        "候选源数据 JSON：\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def clean_hermes_output(output: str) -> str:
    lines = [
        line
        for line in output.splitlines()
        if not line.startswith("session_id:") and not line.startswith("⚠️")
    ]
    text = "\n".join(lines).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:markdown|md)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    return text


def card_display_markdown(markdown: str, *, strip_top_title: bool = True) -> str:
    text = markdown.strip()
    if strip_top_title:
        text = re.sub(r"^#{1,6}\s+.+?(?:\n+|$)", "", text, count=1)
    text = re.sub(r"(?m)^_来源：(.+?)_$", r"来源：\1", text)
    text = re.sub(r"(?m)^_Feed skill: .+?_$", "", text)
    text = re.sub(r"(?m)^##\s+(\d+)\.\s+(\[.+?\]\(.+?\))\s*$", r"**\1. \2**", text)
    text = re.sub(r"(?m)^##\s+(.+?)\s*$", r"**\1**", text)
    text = re.sub(r"(?m)^#\s+(.+?)\s*$", r"**\1**", text)
    text = re.sub(r"(?m)^-\s+(来源|日期|摘要)：", r"\1：", text)
    text = re.sub(r"(?m)^(\d+)\.\s*\n\*\*(.+?)\*\*", r"**\1. \2**", text)
    text = re.sub(r"(?m)^(\d+)\.\s*$", r"**\1.**", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def remix_with_hermes_agent(items: list[DigestItem], meta: dict, limit: int) -> str:
    hermes_cli = os.environ.get("HERMES_CLI", DEFAULT_HERMES_CLI)
    hermes_python = os.environ.get("HERMES_PYTHON", sys.executable)
    remix_provider = os.environ.get("DAILY_AI_CODE_REMIX_PROVIDER", "").strip()
    remix_model = os.environ.get("DAILY_AI_CODE_REMIX_MODEL", "").strip()
    timeout = int(os.environ.get("DAILY_AI_CODE_REMIX_TIMEOUT", "240"))
    cmd = [
        hermes_python,
        hermes_cli,
        "chat",
        "-Q",
        "--ignore-rules",
        "--source",
        "tool",
        "--max-turns",
        "3",
    ]
    if remix_provider:
        cmd.extend(["--provider", remix_provider])
    if remix_model:
        cmd.extend(["-m", remix_model])
    cmd.extend(["-q", build_remix_prompt(items, meta, limit)])
    result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Hermes remix failed: {result.stderr.strip() or result.stdout.strip()}")
    markdown = clean_hermes_output(result.stdout)
    if "# AI Builders Digest" not in markdown:
        raise RuntimeError("Hermes remix returned unexpected output")
    validate_chinese_digest(markdown)
    return markdown


def mark_sent_from_markdown(markdown: str, items: list[DigestItem], state_path: Path, fallback_limit: int) -> None:
    urls = set(re.findall(r"https?://[^\s)]+", markdown))
    selected = [item for item in items if item.url and item.url in urls]
    if not selected:
        selected = items[:fallback_limit]
    mark_sent(selected, state_path)


def html_to_markdown(value: str) -> str:
    parser = MarkdownHTMLParser()
    parser.feed(value)
    return parser.markdown()


def latest_faiyi_brief() -> str:
    payload = fetch_json(os.environ.get("FAIYI_AI_DAILY_API", FAIYI_LATEST_API), timeout=30)
    if not isinstance(payload, list) or not payload:
        return "## 理想栈 AI动态简报\n\n未能获取最新文章。"
    post = payload[0]
    if not isinstance(post, dict):
        return "## 理想栈 AI动态简报\n\n返回内容格式异常。"
    title_data = post.get("title") if isinstance(post.get("title"), dict) else {}
    content_data = post.get("content") if isinstance(post.get("content"), dict) else {}
    title = html.unescape(str(title_data.get("rendered") or "理想栈 AI动态简报"))
    link = str(post.get("link") or "http://www.faiyi.com/?cat=7")
    date = str(post.get("date") or "")
    rendered = str(content_data.get("rendered") or "")
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


def markdown_chunks(markdown: str, max_chars: int = 4200) -> list[str]:
    paragraphs = markdown.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        if len(paragraph) <= max_chars:
            current = paragraph
        else:
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start : start + max_chars])
            current = ""
    if current:
        chunks.append(current)
    return chunks


def build_card(title: str, markdown: str, template: str, max_chars: int) -> dict:
    clipped = markdown
    if len(clipped) > max_chars:
        clipped = clipped[: max_chars - 120].rstrip() + "\n\n_内容较长，已截断；请打开原文链接查看完整内容。_"
    elements = [{"tag": "markdown", "content": chunk} for chunk in markdown_chunks(clipped)]
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title[:80]}, "template": template},
        "elements": elements,
    }


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def feishu_base_url() -> str:
    domain = os.environ.get("FEISHU_DOMAIN", "feishu").strip().lower()
    return "https://open.larksuite.com" if domain == "lark" else "https://open.feishu.cn"


def feishu_token() -> str:
    app_id = os.environ.get("FEISHU_APP_ID", "").strip()
    app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("FEISHU_APP_ID/FEISHU_APP_SECRET are required to send cards")
    url = f"{feishu_base_url()}/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    payload = json.loads(open_with_retries(request, timeout=20).decode("utf-8"))
    token = payload.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"failed to get Feishu tenant token: {payload}")
    return str(token)


def send_feishu_card(chat_id: str, card: dict, thread_id: str = "") -> str:
    token = feishu_token()
    receive_id = thread_id or chat_id
    receive_id_type = "thread_id" if thread_id else ("open_id" if chat_id.startswith("ou_") else "chat_id")
    url = f"{feishu_base_url()}/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    body = {
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card, ensure_ascii=False),
        "uuid": str(uuid.uuid4()),
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    payload = json.loads(open_with_retries(request, timeout=30).decode("utf-8"))
    if payload.get("code") not in (0, None):
        raise RuntimeError(f"Feishu card send failed: {payload}")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(data.get("message_id") or "")


def save_local_output(markdown: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{dt.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.md"
    path.write_text(markdown, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build AI builders and faiyi digests, optionally sending Feishu cards.")
    parser.add_argument("--limit", type=int, default=int(os.environ.get("DAILY_AI_CODE_LIMIT", str(DEFAULT_DIGEST_LIMIT))))
    parser.add_argument("--state", type=Path, default=Path(os.environ.get("DAILY_AI_CODE_STATE", str(DEFAULT_STATE))))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--cache-dir", type=Path, default=Path(os.environ.get("DAILY_AI_CODE_CACHE_DIR", str(DEFAULT_CACHE_DIR))))
    parser.add_argument("--mark-sent", action="store_true")
    parser.add_argument("--send-feishu", action="store_true")
    parser.add_argument("--chat-id", default=os.environ.get("FEISHU_HOME_CHANNEL", ""))
    parser.add_argument("--thread-id", default=os.environ.get("FEISHU_HOME_CHANNEL_THREAD_ID", ""))
    parser.add_argument("--include-seen", action="store_true")
    parser.add_argument("--no-agent-remix", action="store_true", help="Use local rule-based summaries instead of Hermes agent remix.")
    args = parser.parse_args()

    load_dotenv(Path.home() / ".hermes/.env")
    include_seen = args.include_seen or os.environ.get("DAILY_AI_CODE_PREVIEW") == "1"
    digest_limit = min(max(args.limit, 1), MAX_DIGEST_LIMIT)
    candidate_limit = max(digest_limit * 3, 12)
    items, meta = collect_builders_digest(candidate_limit, args.state, include_seen=include_seen, cache_dir=args.cache_dir)
    use_agent_remix = not args.no_agent_remix and os.environ.get("DAILY_AI_CODE_DISABLE_AGENT_REMIX") != "1"
    if use_agent_remix and items:
        try:
            builders_markdown = remix_with_hermes_agent(items, meta, digest_limit)
        except Exception as exc:  # noqa: BLE001 - cron should still deliver a fallback digest.
            print(f"warning: {exc}; falling back to local rule-based digest", file=sys.stderr)
            builders_markdown = render_builders_markdown(items[:digest_limit], meta)
    else:
        builders_markdown = render_builders_markdown(items[:digest_limit], meta)
    faiyi_markdown = latest_faiyi_brief()
    full_output = f"{builders_markdown}\n\n---\n\n{faiyi_markdown}"
    output_path = save_local_output(full_output, args.output_dir)

    sent: list[str] = []
    if args.send_feishu:
        chat_id = args.chat_id or os.environ.get("FEISHU_HOME_CHANNEL", "")
        if not chat_id:
            raise RuntimeError("missing Feishu chat id; set FEISHU_HOME_CHANNEL or pass --chat-id")
        today = dt.datetime.now().date().isoformat()
        builders_card = build_card(
            f"AI Builders Digest - {today}",
            card_display_markdown(builders_markdown),
            "blue",
            18000,
        )
        faiyi_card = build_card(
            f"理想栈 AI动态简报 - {today}",
            card_display_markdown(faiyi_markdown),
            "green",
            24000,
        )
        sent.append(send_feishu_card(chat_id, builders_card, thread_id=args.thread_id))
        sent.append(send_feishu_card(chat_id, faiyi_card, thread_id=args.thread_id))

    if args.mark_sent:
        mark_sent_from_markdown(builders_markdown, items, args.state, digest_limit)

    print(full_output)
    if sent:
        print("\n---\n")
        print(f"Feishu cards sent: {', '.join(sent)}")
    print(f"\nLocal output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
