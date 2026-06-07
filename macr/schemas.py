from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TASK = "task"
    PROPOSAL = "proposal"
    PLAN = "plan"
    RESULT = "result"
    REVIEW = "review"
    CRITIQUE = "critique"
    REVISION_REQUEST = "revision_request"
    REVISION_RESULT = "revision_result"
    TEST_REPORT = "test_report"
    EVALUATION = "evaluation"
    DECISION = "decision"
    HUMAN_FEEDBACK = "human_feedback"


class Decision(str, Enum):
    PASS = "PASS"
    NEEDS_FIX = "NEEDS_FIX"
    BLOCKED = "BLOCKED"


# --- Role content schemas (these become tool-use input schemas) ---

class PlannerOutput(BaseModel):
    summary: str
    steps: list[str]
    tools_needed: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class ExecutorOutput(BaseModel):
    artifact: str
    notes: str = ""
    evidence: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    level: Literal["blocking", "non_blocking"]
    issue: str
    evidence: str
    recommendation: str


class ReviewerOutput(BaseModel):
    summary: str
    findings: list[Finding] = Field(default_factory=list)
    decision: Literal["approve", "needs_fix"]


class EvaluatorOutput(BaseModel):
    decision: Decision
    reasons: list[str] = Field(default_factory=list)
    confidence: float


class HumanFeedback(BaseModel):
    decision: Literal["approve", "reject"]
    feedback: str = ""
    timestamp: str


class TestResult(BaseModel):
    __test__ = False  # tell pytest this is not a test class despite the name
    command: str
    passed: bool
    exit_code: int
    log: str = ""
    timed_out: bool = False


# --- Envelope + shared state ---

class Message(BaseModel):
    task_id: str
    run_id: str
    agent_id: str
    role: str
    message_type: MessageType
    content: dict
    references: list[str] = Field(default_factory=list)
    timestamp: str
    status: str = "submitted"


def _empty_buckets() -> dict[str, list[dict]]:
    return {"planner": [], "executor": [], "reviewer": [], "evaluator": []}


class SharedState(BaseModel):
    run_id: str
    user_query: str
    task_plan: list[str] = Field(default_factory=list)
    agent_outputs: dict[str, list[dict]] = Field(default_factory=_empty_buckets)
    reviews: list[dict] = Field(default_factory=list)
    decisions: list[dict] = Field(default_factory=list)
    human_feedback: HumanFeedback | None = None
    final_output: str | None = None
    target_repo: str | None = None
    worktree_path: str | None = None
    diffs: list[str] = Field(default_factory=list)
    test_results: list[dict] = Field(default_factory=list)
