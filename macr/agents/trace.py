from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from macr.schemas import SubagentRecord


def _iter_json_lines(lines: list[str]) -> Iterator[dict]:
    """Parse each line as JSON; silently skip anything that isn't a JSON object."""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            yield obj


def _walk(obj) -> Iterator[dict]:
    """Yield every dict nested anywhere inside obj."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def parse_claude_stream(lines: list[str]) -> tuple[str, list[SubagentRecord]]:
    """Best-effort: recover the final result text + subagent records from claude stream-json.

    Defensive against unknown/missing fields (spec §7). Never raises.
    """
    objs = list(_iter_json_lines(lines))

    final_text = ""
    for o in objs:
        result = o.get("result")
        if isinstance(result, str):
            final_text = result  # last one wins (the terminal result event)

    type_by_id: dict[str, str] = {}
    for o in objs:
        for d in _walk(o):
            if d.get("type") == "tool_use" and d.get("name") in ("Agent", "Task"):
                tid = d.get("id")
                if tid:
                    subtype = (d.get("input") or {}).get("subagent_type")
                    type_by_id[tid] = subtype or "unknown"

    refs: list[str] = []
    seen: set[str] = set()
    for o in objs:
        parent = o.get("parent_tool_use_id")
        if isinstance(parent, str) and parent and parent not in seen:
            seen.add(parent)
            refs.append(parent)

    records = [
        SubagentRecord(source="claude", agent_type=type_by_id.get(ref, "unknown"), ref=ref)
        for ref in refs
    ]
    return final_text, records


def parse_codex_stream(lines: list[str]) -> tuple[str, list[SubagentRecord]]:
    """Best-effort: recover the final agent message + spawned sub-thread records from codex --json.

    Defensive against unknown/missing fields (spec §7). Never raises.
    """
    objs = list(_iter_json_lines(lines))

    threads: list[str] = []
    for o in objs:
        if o.get("type") == "thread.started":
            tid = o.get("thread_id") or (o.get("thread") or {}).get("id")
            if isinstance(tid, str) and tid:
                threads.append(tid)

    final_text = ""
    for o in objs:
        if o.get("type") == "item.completed":
            item = o.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                final_text = item["text"]  # last agent message wins

    sub_ids = threads[1:] if len(threads) > 1 else []  # first thread is the root session
    records = [SubagentRecord(source="codex", agent_type="unknown", ref=t) for t in sub_ids]
    return final_text, records


def stream_error(lines: list[str], *, source: str) -> str | None:
    """Extract a human-readable error message from a CLI's JSONL stdout, else None.

    Surfaces the real failure (e.g. codex usage limit) instead of an incidental
    stderr line when a CLI exits non-zero. Never raises: malformed lines are skipped.
    """
    for obj in _iter_json_lines(lines):
        t = obj.get("type")
        if source == "codex":
            if t == "error" and obj.get("message"):
                return str(obj["message"])
            if t == "turn.failed":
                msg = (obj.get("error") or {}).get("message")
                if msg:
                    return str(msg)
        else:  # claude (best-effort across stream-json event shapes)
            if t == "error" and obj.get("message"):
                return str(obj["message"])
            err = obj.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if obj.get("is_error") and obj.get("result"):
                return str(obj["result"])
    return None


class TraceSink:
    """Persists one role-invocation's raw event stream + parsed subagent summary."""

    def __init__(self, directory: Path, label: str):
        self.directory = Path(directory)
        self.label = label
        self.records: list[SubagentRecord] = []

    def capture(self, raw_lines: list[str], subagents: list[SubagentRecord]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        (self.directory / f"{self.label}.events.jsonl").write_text(
            "\n".join(raw_lines), encoding="utf-8"
        )
        (self.directory / f"{self.label}.subagents.json").write_text(
            json.dumps([s.model_dump() for s in subagents], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.records = list(subagents)
