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
   - Official OpenAI items about Codex, agents, developer tools, API/platform changes, security, evals, or model capability changes relevant to coding.
   - Official Anthropic/Claude items, especially Claude Code, Claude API, MCP, agent, IDE, or developer workflow updates.
   - Official GitHub Copilot, VS Code, and other primary-source developer-tool updates when OpenAI/Claude have fewer strong items.

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
- Prefer primary sources. Use secondary media only if it points to a primary source and the primary source is unavailable.
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
