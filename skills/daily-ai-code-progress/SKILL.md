---
name: daily-ai-code-progress
description: Produce a concise daily digest of AI coding industry progress, selecting about five non-duplicate items from authoritative sources, with priority for official OpenAI and Anthropic/Claude announcements, Claude Code changes, and other official developer-tool channels.
license: MIT
metadata:
  hermes:
    tags: [ai-coding, daily-digest, openai, claude, cron, research]
    related_skills: [hermes-agent]
---

# Daily AI Code Progress

Use this skill to produce a short daily digest of AI coding and coding-agent progress.

## Workflow

1. Run the bundled collector from the repository root:

   ```bash
   python3 skills/daily-ai-code-progress/scripts/collect_news.py --limit 8
   ```

2. Select about 5 items. Prefer:
   - Deep official or practitioner content about AI coding, coding agents, engineering workflows, security, evals, or production adoption.
   - Official OpenAI and Anthropic/Claude items when they explain Codex, Claude Code, agent workflows, governance, safety, or developer platform changes with practical impact.
   - High-signal practitioner analysis, especially when it turns product changes into engineering judgment or reusable workflow patterns.
   - Product changelogs only when they materially change coding-agent behavior, migration plans, permissions, security, or team workflows; avoid filling the digest with minor GitHub/VS Code/Cursor changelog items.

3. Avoid repeats. The collector excludes items already marked in its state file. After finalizing a digest, mark the sent items:

   ```bash
   python3 skills/daily-ai-code-progress/scripts/collect_news.py --limit 5 --mark-sent
   ```

4. Write the digest in Chinese unless the user asks otherwise. Keep it compact but informative:
   - Title: `AI Code 日报 - YYYY-MM-DD`
   - 5 bullets max unless there is a clearly exceptional day.
   - Use clickable Markdown titles: `[title](url)`.
   - Each item should include source, date, and a Chinese summary of roughly 150-250 Chinese characters.
   - Mention when there are no same-day strong official updates and the digest is using recent high-quality items instead.
   - Mention "今天没有足够新的权威信息" if fewer than 3 strong items remain after dedupe.

## Quality Rules

- Do not include an item only because it is AI-adjacent; it must matter to coding, software delivery, developer tools, agent workflows, model APIs used by developers, or code/security workflows.
- Prefer sources with interpretation or reusable practice over low-context release notes. Primary sources are valuable, but official does not automatically mean worth reading.
- Limit product changelog entries to at most one item unless there is a genuinely major coding-agent change.
- Limit vendor customer stories to at most one item unless they contain concrete implementation detail that can transfer to other engineering teams.
- Do not duplicate the broad AI-industry roundup at `faiyi.com`; this skill should be narrower and stronger on AI coding, agentic engineering, developer workflow, and production adoption.
- Do not invent dates, claims, metrics, availability, or product behavior. If a source is ambiguous, say so briefly or skip it.
- Keep old but newly discovered items only when they are still useful and were not previously sent.
- If the collector returns weak candidates, browse official OpenAI and Claude/Anthropic pages manually before falling back to broader sources.

## State

By default the collector stores sent fingerprints in:

```text
.cache/daily-ai-code-progress/seen.json
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
  --deliver feishu:oc_adfe3ff6a5862a75e694c8def63af1fd \
  --skill daily-ai-code-progress \
  --script daily_ai_code_progress.py \
  --no-agent \
  --workdir /Users/bytedance/.codex/worktrees/9364/hermes \
  'Deliver the generated AI Code daily digest.'
```

The runner marks selected AI Code items as sent by default so repeated cron runs do not resend the same links. It also fetches the latest post from `http://www.faiyi.com/?cat=7` through the WordPress REST API and appends that post's current content to the end of the digest. For a manual preview, run:

```bash
DAILY_AI_CODE_PREVIEW=1 python3 ~/.hermes/scripts/daily_ai_code_progress.py
```
