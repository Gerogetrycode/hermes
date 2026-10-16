---
name: daily-ai-code-progress
description: Combine Builders, faiyi.com, and AIHOT into one concise Chinese Feishu card with three sections and event deduplication.
license: MIT
metadata:
  hermes:
    tags: [ai-coding, daily-digest, openai, claude, cron, research]
    related_skills: [hermes-agent]
---

# Daily AI Code Progress

Use this skill to produce a short daily digest of AI builders, AI coding, and coding-agent progress.

## Scheduled delivery (AgentBox)

The production entrypoint is `scripts/agentbox_daily_ai_digest.py`. It collects three sources and sends **one Card 2.0 card** with sections in this fixed priority order:

1. Builders: follow-builders X posts, podcasts, and blogs.
2. 理想栈: Chinese news items parsed from the latest faiyi.com daily brief, retaining original links and article publication date.
3. AIHOT: the selected items from the past 24 hours via its JSON `/api/v1/items` interface, using `User-Agent: aihot-api/2.0.0`. Link the title to the AIHOT reading page and retain source attribution and original links.

Normalize original URLs to remove exact duplicates, then use the existing direct DeepSeek provider to select and summarize candidates and identify same-event reports across different titles, languages, or sites. A duplicate refers only to a retained item in an earlier section (or earlier in the same section). Different events from the same company must remain separate. Keep at most five items per section, with concise Chinese summaries, key numbers, and source qualifiers. No generic fallback summaries.

The card has one overview and three separate source blocks. Empty sections remain visible with a short explanation. Candidate inputs, selected items, duplicate mappings, source timestamps, and delivery receipts are persisted for inspection. Normal daily runs use `deliveries/YYYY-MM-DD.json`; completed legacy two-card receipts remain valid and are not resent. Incomplete legacy receipts can still resume.

Run `python3 scripts/agentbox_daily_ai_digest.py --preview` for a non-sending preview. To send one explicitly requested same-day example after an older daily delivery, use `--sample`; it has its own idempotent receipt under `samples/YYYY-MM-DD.json` and does not overwrite the normal daily receipt. Use the configured production env/state paths on AgentBox. The cron remains `0 8-12 * * *` in Asia/Shanghai with no extra scheduler delivery.

To send an inspected preview unchanged, use `--sample --sample-from-preview PATH`. The preview must have today's date, the configured target, one combined Card 2.0 payload, and no prior receipt. Summaries are compact Chinese paragraphs; short factual updates need not be padded to the legacy Builders summary length. Duplicate mappings carry the shared subject and source excerpts for review.

## Legacy collector / local diagnostics

The standalone collector below remains available for Builders diagnostics. Its legacy two-card send mode is not the production scheduled delivery path.

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

5. Avoid repeats. The collector excludes items already marked in its state file. For production delivery and sent-state updates, use the AgentBox entrypoint. To inspect raw candidates without sending:

   ```bash
   python3 skills/daily-ai-code-progress/scripts/follow_builders_digest.py --include-seen --no-agent-remix
   ```

6. Write the builders digest in Chinese unless the user asks otherwise. Keep it compact but informative:
   - Title: `AI Builders Digest - YYYY-MM-DD`
   - Aim for about 5 items on normal days; include more only when the sources are genuinely high quality, and keep the digest at 10 items or fewer.
   - Use clickable Markdown titles: `[title](url)`.
   - Each item should include source, date, and a Chinese summary of roughly 120-220 Chinese characters.
   - Prefer builder-level insight over generic product announcements.
   - Do not append generic "practice implication" or "team value" sentences to every item. Add a short comment only when it is grounded in the source itself; otherwise keep the item as a factual summary.
   - Do not reuse fixed boilerplate sentences across items.

7. Production delivery merges this content with faiyi.com and AIHOT through the AgentBox entrypoint described above.

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

## Legacy Hermes Cron

The old local Hermes job was paused during the AgentBox cutover. Do not enable it alongside the AgentBox job. Its historical runner and collector remain for diagnostics and compatibility; scheduled single-card delivery uses `agentbox_daily_ai_digest.py`.
