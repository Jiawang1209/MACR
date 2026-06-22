import shutil
from argparse import Namespace

import pytest

from macr.cli import _build_worker_backend


def _args(worker_runtime):
    return Namespace(worker_runtime=worker_runtime, no_subagents=False,
                     codex_model=None, timeout=1800)


def test_cli_runtime_returns_none():
    assert _build_worker_backend(_args("cli")) is None


@pytest.mark.skipif(shutil.which("tmux") is None, reason="needs real tmux")
def test_tmux_runtime_builds_executor_backend():
    from macr.runtime.tmux_executor import TmuxExecutorBackend
    be = _build_worker_backend(_args("tmux"))
    try:
        assert isinstance(be, TmuxExecutorBackend)
    finally:
        be._rt._c._t.close()  # tear down the real tmux server
