from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

from macr.web.runs import (
    ArtifactError, RunCorrupt, RunNotFound, list_runs, load_run, read_artifact,
)


def create_app(runs_dir: Path) -> FastAPI:
    runs_dir = Path(runs_dir)
    app = FastAPI(title="MACR Run Viewer")

    @app.get("/api/runs")
    def get_runs():
        return list_runs(runs_dir)

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        try:
            return load_run(runs_dir, run_id)
        except RunNotFound:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        except RunCorrupt as exc:
            raise HTTPException(status_code=422, detail=str(exc))

    @app.get("/api/runs/{run_id}/artifacts/{name:path}", response_class=PlainTextResponse)
    def get_artifact(run_id: str, name: str):
        try:
            return read_artifact(runs_dir, run_id, name)
        except RunNotFound:
            raise HTTPException(status_code=404, detail=f"run not found: {run_id}")
        except ArtifactError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    return app
