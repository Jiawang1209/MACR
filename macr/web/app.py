from __future__ import annotations

import asyncio
import shlex
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from macr.web.runs import (
    ArtifactError, RunCorrupt, RunNotFound, list_runs, load_run, read_artifact,
)
from macr.web.session import RunActive, RunManager


class LaunchRequest(BaseModel):
    command: str
    task: str
    repo: str
    test_cmd: str
    options: dict = {}


def create_app(runs_dir: Path, spa_dist: Path | None = None,
               manager: RunManager | None = None) -> FastAPI:
    runs_dir = Path(runs_dir)
    app = FastAPI(title="MACR Run Viewer")
    run_manager = manager if manager is not None else RunManager()
    app.state.run_manager = run_manager

    @app.get("/api/runs")
    def get_runs():
        return list_runs(runs_dir)

    @app.get("/api/runs/active")
    def active():
        s = run_manager.active
        if s is None:
            return Response(status_code=204)
        return {"run_id": s.run_id, "command": s.command, "status": s.status}

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

    @app.post("/api/runs/launch")
    def launch(req: LaunchRequest):
        if req.command not in ("collab", "discuss"):
            raise HTTPException(status_code=400, detail=f"unknown command: {req.command}")
        if not req.task.strip():
            raise HTTPException(status_code=400, detail="task must not be blank")
        if not Path(req.repo).is_dir():
            raise HTTPException(status_code=400, detail=f"repo is not a directory: {req.repo}")
        test_cmd = shlex.split(req.test_cmd)
        if not test_cmd:
            raise HTTPException(status_code=400, detail="test_cmd must not be empty")
        try:
            session = run_manager.launch(command=req.command, task=req.task, repo=req.repo,
                                         test_cmd=test_cmd, options=req.options)
        except RunActive:
            raise HTTPException(status_code=409, detail="a live run is already active")
        return {"run_id": session.run_id, "command": session.command}

    @app.websocket("/api/runs/active/ws")
    async def active_ws(websocket: WebSocket):
        await websocket.accept()
        session = run_manager.active
        if session is None:
            await websocket.close()
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def push(event: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, event)

        snapshot = session.subscribe(push)

        async def receive_responses() -> None:
            try:
                while True:
                    msg = await websocket.receive_json()
                    session.respond_gate(msg.get("decision", "reject"), msg.get("feedback", ""))
            except WebSocketDisconnect:
                pass

        recv_task = asyncio.create_task(receive_responses())
        try:
            for ev in snapshot:
                await websocket.send_json(ev)
                if ev["type"] == "done":
                    return
            while True:
                ev = await queue.get()
                await websocket.send_json(ev)
                if ev["type"] in ("done", "error"):
                    return
        except WebSocketDisconnect:
            pass
        finally:
            recv_task.cancel()
            session.unsubscribe(push)

    if spa_dist is not None and Path(spa_dist).is_dir():
        app.mount("/", StaticFiles(directory=str(spa_dist), html=True), name="spa")

    return app
