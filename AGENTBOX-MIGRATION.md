# Daily AI digest on AgentBox

The standalone entrypoint is `skills/daily-ai-code-progress/scripts/agentbox_daily_ai_digest.py`.
It requires Python 3.10+ on Linux/macOS, no Hermes runtime and no third-party packages.
AgentBox runs it as a **Shell command**, not as an unrestricted agent prompt.

## Configuration

Put only this job's credentials in `~/.config/daily-ai-digest/env` (directory mode
700, file mode 600; never commit it):

```dotenv
DEEPSEEK_API_KEY=<existing digest API key>
DAILY_AI_CODE_REMIX_MODEL=deepseek-flash
FEISHU_APP_ID=<existing digest bot>
FEISHU_APP_SECRET=<existing digest bot secret>
FEISHU_HOME_CHANNEL=<existing destination chat>
# FEISHU_HOME_CHANNEL_THREAD_ID=<optional existing thread>
```

Public feed excerpts are sent directly to DeepSeek's Chat Completions endpoint
for Chinese rewriting. No model tools, shell execution, or local files are exposed
to the model. The API contract is documented at
https://api-docs.deepseek.com/api/create-chat-completion/ .
Secrets, chat history and Hermes/AgentBox runtime databases are not migrated.

## Deployment

Target: `10.36.4.231`, AgentBox `hwhg6n01ejtvid96`.
Code: `/home/guoyongshuai.gys/agentbox_code/daily-ai-digest`.
State: `~/.local/state/daily-ai-digest` (`seen.json`, cache, outputs, previews, deliveries).
Copy the old `seen.json` and feed cache; preserve old outputs separately for audit.
Only create a completed-day migration receipt from confirmed prior message IDs,
never from the mere existence of a rendered output file.

AgentBox Shell command:

```sh
/usr/bin/python3 /home/guoyongshuai.gys/agentbox_code/daily-ai-digest/skills/daily-ai-code-progress/scripts/agentbox_daily_ai_digest.py
```

Schedule: `0 8-12 * * *`, timezone `Asia/Shanghai`, timeout 1800 seconds.
AgentBox's extra Feishu result notification stays off: the script sends exactly
the two existing digest cards. First test the command with `--preview`; do not
disable the old local cron until remote preview and configuration are verified.

## Reliability / rollback

- Preview performs real collection and generation, but never sends or marks seen.
- Chinese quality and candidate-link validation retry the model once. If both
  rewrites fail validation, the job uses its deterministic, source-bound Chinese
  renderer and validates that output before allowing delivery.
- `run.lock` prevents concurrent jobs. A day's frozen manifest stores each card's
  payload, UUID and message ID; partial failures resume only unsent cards.
- A completed receipt is saved only after both message IDs and dedupe state.
  UUIDs reduce duplication on ambiguous network failures within Feishu's server
  dedupe window; they are not an unlimited exactly-once guarantee.
- Times are interpreted in Shanghai regardless of the host timezone.
- Keep the original local code/state. To roll back, pause the AgentBox task first,
  reconcile its latest deliveries/seen state, then re-enable the old scheduler
  only in an environment where that runtime is permitted.

Tests: `python3 -m unittest discover -s tests -v`.

## Cutover record — 2026-09-10

- AgentBox job ID `b06aca77` (`Daily AI Code Progress`) is enabled; its saved
  timezone is `Asia/Shanghai`, execution kind is `shell`, and extra delivery is `none`.
- The AgentBox-triggered real preview succeeded in 99.935 seconds. The deployed
  script requested `deepseek-v4-flash`; the API reported `deepseek-flash`.
- Both local and devbox test suites passed (14 tests). The imported `seen.json`
  matched the local SHA-256 before cutover.
- Devbox authenticated as the existing digest bot and read back both of today's
  previously delivered cards in the original chat. Those confirmed message IDs
  were imported into `deliveries/2026-09-10.json`; no duplicate cards were sent.
- The final non-preview command was run by AgentBox and finished successfully in
  89 ms, skipping the already-completed day. This tests the scheduler and skip path;
  a new devbox-originated send has not yet been performed.
- Next scheduled run: **2026-09-11 08:00 Asia/Shanghai**.
- Local Hermes job `39124c1ca232` was paused (not deleted); its prior configuration
  is backed up at `~/.hermes/cron/jobs.json.before-agentbox-migration-20260910-1933`.
