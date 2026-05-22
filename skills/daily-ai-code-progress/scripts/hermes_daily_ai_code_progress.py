#!/usr/bin/env python3
"""Hermes cron runner for the daily AI builders digest skill."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


DEFAULT_REPO = Path("/Users/bytedance/.codex/worktrees/9364/hermes")


def main() -> int:
    repo = Path(os.environ.get("DAILY_AI_CODE_REPO", DEFAULT_REPO)).expanduser()
    digest_script = repo / "skills/daily-ai-code-progress/scripts/follow_builders_digest.py"
    if not digest_script.exists():
        print(f"Digest script not found: {digest_script}", file=sys.stderr)
        return 2

    cmd = [
        sys.executable,
        str(digest_script),
        "--state",
        os.environ.get(
            "DAILY_AI_CODE_STATE",
            str(Path.home() / ".hermes/state/daily-ai-code-progress/seen.json"),
        ),
    ]
    if os.environ.get("DAILY_AI_CODE_PREVIEW") != "1":
        cmd.extend(["--mark-sent", "--send-feishu"])
    else:
        cmd.append("--include-seen")

    result = subprocess.run(cmd, cwd=repo, text=True, capture_output=True, check=False)
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    if result.stdout:
        print(result.stdout.strip())
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
