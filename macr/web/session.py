from __future__ import annotations

import threading
from typing import Callable

from macr.schemas import HumanFeedback
from macr.utils import now_iso


class RunActive(Exception):
    """A live run is already active; only one is allowed at a time."""


class RunSession:
    """One live run: an append-only event buffer, a single live subscriber, and a
    synchronous human-gate bridge between the run thread and the WebSocket handler.
    """

    def __init__(self, run_id: str, command: str):
        self.run_id = run_id
        self.command = command
        self.status = "running"  # running | awaiting_gate | done | error
        self.events: list[dict] = []
        self._lock = threading.Lock()
        self._subscriber: Callable[[dict], None] | None = None
        self._gate_event = threading.Event()
        self._gate_pending = threading.Event()
        self._gate_response: HumanFeedback | None = None

    def emit(self, event: dict) -> None:
        with self._lock:
            self.events.append(event)
            if event.get("type") == "status":
                self.status = event["status"]
            sub = self._subscriber
        if sub is not None:
            sub(event)

    def subscribe(self, push: Callable[[dict], None]) -> list[dict]:
        """Attach the live subscriber and atomically return the buffer snapshot."""
        with self._lock:
            self._subscriber = push
            return list(self.events)

    def unsubscribe(self, push: Callable[[dict], None]) -> None:
        with self._lock:
            if self._subscriber is push:
                self._subscriber = None

    # --- human-gate bridge (run thread side) ---
    def request_gate(self, gate: str, data: dict) -> HumanFeedback:
        """Called from the run thread. Emit a gate request, block until responded."""
        self._gate_event.clear()
        self._gate_response = None
        self.emit({"type": "status", "status": "awaiting_gate"})
        self.emit({"type": "gate_request", "gate": gate, "data": data})
        self._gate_pending.set()
        self._gate_event.wait()
        self._gate_pending.clear()
        self.emit({"type": "status", "status": "running"})
        return self._gate_response  # set by respond_gate before _gate_event.set()

    def wait_for_gate(self, timeout: float | None = None) -> bool:
        """Test/helper: block until the run thread is awaiting a gate."""
        return self._gate_pending.wait(timeout)

    # --- human-gate bridge (WebSocket handler side) ---
    def respond_gate(self, decision: str, feedback: str = "") -> None:
        self._gate_response = HumanFeedback(decision=decision, feedback=feedback, timestamp=now_iso())
        self._gate_event.set()


class RunManager:
    """Holds the single active RunSession. `runner(session, **kwargs)` starts the
    background run (injected for tests; defaults to the real thread runner).
    """

    def __init__(self, runner: Callable[..., None] | None = None):
        self._runner = runner
        self._active: RunSession | None = None
        self._lock = threading.Lock()
        self._counter = 0

    @property
    def active(self) -> RunSession | None:
        return self._active

    def launch(self, *, command: str, task: str, repo: str, test_cmd, options: dict) -> RunSession:
        with self._lock:
            if self._active is not None and self._active.status in ("running", "awaiting_gate"):
                raise RunActive("a live run is already active")
            self._counter += 1
            run_id = f"live-{self._counter}"  # replaced by the real runner with a real run_id
            session = RunSession(run_id=run_id, command=command)
            self._active = session
        runner = self._runner
        if runner is None:
            from macr.web.live import start_live_run as runner  # default real runner
        runner(session, command=command, task=task, repo=repo, test_cmd=test_cmd, options=options)
        return session

    def respond_gate(self, decision: str, feedback: str = "") -> None:
        if self._active is not None:
            self._active.respond_gate(decision, feedback)
