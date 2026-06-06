from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    """UTC timestamp in ISO-8601 with a trailing Z, second precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def next_run_id(runs_dir: Path, today: str | None = None) -> str:
    """Return R<today>_<NNN>, NNN one past the highest existing for `today`.

    today defaults to the current UTC date as YYYYMMDD.
    """
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
    pattern = re.compile(rf"^R{today}_(\d{{3}})$")
    highest = 0
    if runs_dir.exists():
        for child in runs_dir.iterdir():
            m = pattern.match(child.name)
            if m:
                highest = max(highest, int(m.group(1)))
    return f"R{today}_{highest + 1:03d}"
