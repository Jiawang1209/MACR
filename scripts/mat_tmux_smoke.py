"""Manual smoke: drive a REAL tmux via control mode. Requires `tmux` on PATH.
NOT run in CI. Usage: .venv/bin/python scripts/mat_tmux_smoke.py

Caveat: on attach, tmux emits an initial guard block + notifications before our
first command. We consume that banner with one poll() before issuing commands.
"""
import time

from macr.runtime.observer import AgentObserver
from macr.runtime.tmux_control import SubprocessTmuxTransport, TmuxControl
from macr.runtime.tmux_runtime import TmuxRuntime


def main() -> None:
    transport = SubprocessTmuxTransport(session="macr-mat-smoke")
    control = TmuxControl(transport)
    control.poll(timeout=0.5)  # drain attach banner
    rt = TmuxRuntime(control)
    obs = AgentObserver(rt)

    # The attach already created the session; spawn a plain shell as a fake "agent".
    rt._session = "macr-mat-smoke"  # use the attached session
    pane = rt.spawn_agent("smoke-1", ["bash", "--norc"], cwd=".")
    print("spawned agent smoke-1 on pane", pane)

    rt.send_input("smoke-1", "echo MAT_SMOKE_OK")
    time.sleep(0.5)
    snap = rt.snapshot("smoke-1", recent=50)
    print("snapshot:\n", snap)
    assert "MAT_SMOKE_OK" in snap, "did not observe echoed output"

    for info in rt.list_agents():
        print("agent:", info)

    transport.close()
    print("SMOKE OK")


if __name__ == "__main__":
    main()
