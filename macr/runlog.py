from __future__ import annotations

import json
from pathlib import Path

from macr.schemas import SharedState


class RunLog:
    """Writes all artifacts for one run into `.macr/runs/<run_id>/`."""

    def __init__(self, run_path: Path):
        self.run_path = run_path
        self.run_path.mkdir(parents=True, exist_ok=True)

    def _write(self, name: str, text: str) -> None:
        (self.run_path / name).write_text(text, encoding="utf-8")

    def write_input(self, task: str) -> None:
        self._write("input.md", f"{task}\n")

    def write_planner(self, content: dict) -> None:
        steps = "\n".join(f"{i}. {s}" for i, s in enumerate(content.get("steps", []), 1))
        risks = "\n".join(f"- {r}" for r in content.get("risks", []))
        self._write(
            "planner.output.md",
            f"# Planner\n\n## Summary\n{content.get('summary', '')}\n\n"
            f"## Steps\n{steps}\n\n## Risks\n{risks}\n",
        )

    def write_executor(self, content: dict, attempt: int) -> None:
        body = (
            f"# Executor (attempt {attempt})\n\n## Artifact\n{content.get('artifact', '')}\n\n"
            f"## Notes\n{content.get('notes', '')}\n"
        )
        self._write(f"executor.output.v{attempt}.md", body)
        self._write("executor.output.md", body)

    def write_reviewer(self, content: dict) -> None:
        findings = "\n".join(
            f"- [{f.get('level')}] {f.get('issue')} — {f.get('recommendation')} ({f.get('evidence')})"
            for f in content.get("findings", [])
        )
        self._write(
            "reviewer.output.md",
            f"# Reviewer\n\n## Summary\n{content.get('summary', '')}\n\n"
            f"## Decision\n{content.get('decision', '')}\n\n## Findings\n{findings}\n",
        )

    def write_evaluator(self, content: dict) -> None:
        self._write("evaluator.output.json", json.dumps(content, ensure_ascii=False, indent=2))

    def write_final(self, text: str) -> None:
        self._write("final.md", text)

    def write_state(self, state: SharedState) -> None:
        self._write("state.json", state.model_dump_json(indent=2))
