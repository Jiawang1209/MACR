from __future__ import annotations

from pydantic import BaseModel, Field


class Stage(BaseModel):
    """One row in a run's normalized timeline."""
    kind: str          # plan|turn|consensus|plan_review|executor|tests|reviewer|evaluator|gate
    label: str
    agent: str | None = None   # claude|codex|human|None
    status: str | None = None  # approve|reject|PASS|NEEDS_FIX|BLOCKED|passed|failed|None
    body: dict = Field(default_factory=dict)


class Artifact(BaseModel):
    """A downloadable raw file in the run dir."""
    name: str
    kind: str          # diff|test_log|final


class RunSummary(BaseModel):
    run_id: str
    command_type: str  # run|collab|discuss
    task: str
    decision: str | None = None
    broken: bool = False


class RunDetail(BaseModel):
    run_id: str
    command_type: str
    task: str
    repo: str | None = None
    worktree: str | None = None
    decision: str | None = None
    stages: list[Stage] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
