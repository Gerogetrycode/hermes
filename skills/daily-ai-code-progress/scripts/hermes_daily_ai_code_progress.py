#!/usr/bin/env python3
"""Hermes cron runner for the daily AI builders digest skill."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path


DEFAULT_REPO = Path("/Users/bytedance/Documents/hermes/myskill")


def main() -> int:
    repo = Path(os.environ.get("DAILY_AI_CODE_REPO", DEFAULT_REPO)).expanduser()
    digest_script = repo / "skills/daily-ai-code-progress/scripts/follow_builders_digest.py"
    if not digest_script.exists():
        print(f"Digest script not found: {digest_script}", file=sys.stderr)
        return 2

    preview = os.environ.get("DAILY_AI_CODE_PREVIEW") == "1"
    force = os.environ.get("DAILY_AI_CODE_FORCE") == "1"
    output_dir = Path(os.environ.get(
        "DAILY_AI_CODE_OUTPUT_DIR",
        str(Path.home() / ".hermes/state/daily-ai-code-progress/outputs"),
    ))
    if not preview and not force:
        today_prefix = datetime.now().strftime("%Y-%m-%d")
        if any(output_dir.glob(f"{today_prefix}_*.md")):
            print(f"Daily AI code progress already generated for {today_prefix}; set DAILY_AI_CODE_FORCE=1 to rerun.")
            return 0

    cmd = [
        sys.executable,
        str(digest_script),
        "--state",
        os.environ.get(
            "DAILY_AI_CODE_STATE",
            str(Path.home() / ".hermes/state/daily-ai-code-progress/seen.json"),
        ),
        "--output-dir",
        str(output_dir),
    ]
    if not preview:
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
