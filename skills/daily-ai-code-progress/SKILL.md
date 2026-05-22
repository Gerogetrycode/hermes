---
name: daily-ai-code-progress
description: Produce a concise daily AI builders and AI coding digest using follow-builders central feeds, then send it as a Feishu card alongside a separate faiyi.com daily AI brief card.
license: MIT
metadata:
  hermes:
    tags: [ai-coding, daily-digest, openai, claude, cron, research]
    related_skills: [hermes-agent]
---

# Daily AI Code Progress

Use this skill to produce a short daily digest of AI builders, AI coding, and coding-agent progress.

## Workflow

1. Run the bundled follow-builders based collector from the repository root:

   ```bash
   python3 skills/daily-ai-code-progress/scripts/follow_builders_digest.py --include-seen
   ```

2. The collector uses the public central feeds from [`zarazhangrui/follow-builders`](https://github.com/zarazhangrui/follow-builders), pinned in code with the source commit used during integration. The source data is:
   - `feed-x.json`: AI builders' recent X posts.
   - `feed-podcasts.json`: podcast episode metadata and transcript excerpts.
   - `feed-blogs.json`: official/company blog posts and summaries.
   - The follow-builders prompt rules for skipping low-signal content and remixing summaries.

3. By default the script prepares candidates locally, then invokes local Hermes in non-interactive mode to remix the final builders card. This is intentional: source collection, state, and Feishu delivery are deterministic, while final selection and Chinese summaries use agent reasoning. Use `--no-agent-remix` only as a fallback when the local Hermes model is unavailable.

4. Prefer:
   - Original builder posts from X when they contain product, technical, or market insight.
   - Podcast episodes with concrete discussion of MCP, APIs, coding agents, developer tools, model economics, or security.
   - Official/blog content when it has practical engineering implications.

5. Avoid repeats. The collector excludes items already marked in its state file. After finalizing a digest, mark the sent items and send Feishu cards:

   ```bash
   python3 skills/daily-ai-code-progress/scripts/follow_builders_digest.py --mark-sent --send-feishu
   ```

6. Write the builders digest in Chinese unless the user asks otherwise. Keep it compact but informative:
   - Title: `AI Builders Digest - YYYY-MM-DD`
   - 5 bullets max unless there is a clearly exceptional day.
   - Use clickable Markdown titles: `[title](url)`.
   - Each item should include source, date, and a Chinese summary of roughly 150-250 Chinese characters.
   - Prefer builder-level insight over generic product announcements.
   - Do not reuse fixed boilerplate sentences across items.

7. Keep the faiyi.com daily AI brief separate. The runner fetches the latest post from `http://www.faiyi.com/?cat=7` through the WordPress REST API and sends it as a second Feishu card. Do not merge the two briefs into one message.

## Quality Rules

- Do not include an item only because it is AI-adjacent; it must matter to coding, software delivery, developer tools, agent workflows, model APIs used by developers, or code/security workflows.
- Prefer original builder viewpoints and substantive podcast/blog discussions over low-context release notes.
- Treat `follow-builders` as the source of collection breadth; local logic should focus on scoring, dedupe, Chinese summaries, and Feishu delivery.
- Use agent remix for final selection because comparing builders' posts, podcast transcripts, and official blogs requires semantic judgment. Local keyword rules are only a reliability fallback.
- Do not duplicate the broad AI-industry roundup at `faiyi.com`; this skill should be narrower and stronger on builders, AI coding, agentic engineering, developer workflow, and production adoption.
- Do not invent dates, claims, metrics, availability, or product behavior. If a source is ambiguous, say so briefly or skip it.
- Keep old but newly discovered items only when they are still useful and were not previously sent.

## State

By default the collector stores sent fingerprints and local rendered outputs under:

```text
~/.hermes/state/daily-ai-code-progress/
```

Use `--state PATH` when a different durable state location is needed for an automation.

## Hermes Cron

For local Hermes scheduling, install the skill into Hermes and run it with the bundled runner:

```bash
mkdir -p ~/.hermes/skills/research/daily-ai-code-progress
cp skills/daily-ai-code-progress/SKILL.md ~/.hermes/skills/research/daily-ai-code-progress/SKILL.md
mkdir -p ~/.hermes/scripts
cp skills/daily-ai-code-progress/scripts/hermes_daily_ai_code_progress.py ~/.hermes/scripts/daily_ai_code_progress.py
```

Recommended cron job:

```bash
hermes cron create '0 11 * * *' \
  --name 'Daily AI Code Progress' \
  --deliver local \
  --skill daily-ai-code-progress \
  --script daily_ai_code_progress.py \
  --no-agent \
  --workdir /Users/bytedance/.codex/worktrees/9364/hermes \
  'Deliver the generated AI Code daily digest.'
```

The runner sends two Feishu interactive cards itself: one AI Builders card and one faiyi.com card. Keep Hermes cron delivery set to `local` so the cron system does not send a third combined text message. For a manual preview without sending cards or marking state, run:

```bash
DAILY_AI_CODE_PREVIEW=1 python3 ~/.hermes/scripts/daily_ai_code_progress.py
```
