# macr/runtime — Multi-Agent Term runtime (Phase 0)

The runtime + observation layer between MACR's control plane and tmux. One
tmux pane = one agent; MACR drives them via control mode and observes state.

- `agent_state.py` — `AgentState`/`AgentApp`, `Detection`, `parse_marker` (OSC
  7748, conf 100), `detect` (screen heuristic, 70..92), `aggregate`.
- `tmux_control.py` — `TmuxTransport` (Protocol; `Subprocess`/`Fake`), `TmuxControl`
  (parses `%begin/%end/%error` guard frames + `%`-notifications).
- `tmux_runtime.py` — `TmuxRuntime`: open_session / spawn_agent / send_input /
  snapshot / list_agents / kill; maps `agent_id ↔ %pane`.
- `observer.py` — `AgentObserver`: fuses OSC markers + pane facts + heuristic.

Tested entirely with `FakeTmuxTransport` (no real tmux/CLI). Real-tmux smoke:
`scripts/mat_tmux_smoke.py` (manual). Design: `docs/superpowers/specs/2026-06-22-multi-agent-term-design.md`.

Phase 0 emits only `observed`/`reported` states — `verified` remains the
control plane's Stage D gate + tests; `approved` the human gate.
