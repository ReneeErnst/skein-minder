"""FastAPI web server for SkeinMinder."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from skeinminder.ravelry.normalizer import StashItem
from skeinminder.web.events import LAST_RUN_PATH, stream_graph_events

_logger = logging.getLogger(__name__)
_STATIC_DIR = Path(__file__).parent / "static"


class _RecommendRequest(BaseModel):
    """Request body for POST /recommend."""

    goal: str
    use_fixture: bool = False


class _BrowserLogEntry(BaseModel):
    """Request body for POST /api/logs."""

    level: Literal["warn", "error"]
    message: str
    timestamp: str | None = None


def create_app(
    stash: list[StashItem],
    ravelry_username: str,
    use_fixture: bool = False,
) -> FastAPI:
    """Create and configure the SkeinMinder FastAPI app."""
    _streams: dict[str, asyncio.Queue[str | None]] = {}
    _resume_futures: dict[str, asyncio.Future[bool]] = {}

    app = FastAPI(title="SkeinMinder")

    async def _run_graph(stream_id: str, goal: str, req_use_fixture: bool) -> None:
        queue = _streams.get(stream_id)
        if queue is None:
            return
        future = _resume_futures.get(stream_id)
        try:
            async for event in stream_graph_events(
                goal,
                stash,
                ravelry_username,
                req_use_fixture,
                thread_id=stream_id,
                resume_future=future,
            ):
                await queue.put(event)
        finally:
            await queue.put(None)
            _resume_futures.pop(stream_id, None)

    @app.post("/recommend")
    async def start_recommend(request: _RecommendRequest) -> dict[str, str]:
        """Start a graph run; events stream via GET /stream/{stream_id}."""
        stream_id = str(uuid.uuid4())
        _streams[stream_id] = asyncio.Queue()
        _resume_futures[stream_id] = asyncio.get_running_loop().create_future()
        asyncio.create_task(
            _run_graph(stream_id, request.goal, request.use_fixture or use_fixture)
        )
        return {"stream_id": stream_id}

    @app.get("/stream/{stream_id}")
    async def stream_events(stream_id: str) -> StreamingResponse:
        """Server-Sent Events stream for a graph run."""
        queue = _streams.get(stream_id)
        if queue is None:
            raise HTTPException(status_code=404, detail="Stream not found")

        async def generator() -> Any:
            try:
                while True:
                    event = await queue.get()
                    if event is None:
                        break
                    yield event
            finally:
                _streams.pop(stream_id, None)
                future = _resume_futures.get(stream_id)
                if future is not None and not future.done():
                    future.set_result(False)

        return StreamingResponse(generator(), media_type="text/event-stream")

    @app.post("/approve/{stream_id}", status_code=202)
    async def approve_run(stream_id: str) -> dict[str, str]:
        """Resume a paused graph run with user approval."""
        future = _resume_futures.get(stream_id)
        if future is None:
            raise HTTPException(
                status_code=404, detail="No paused run found for this id"
            )
        if not future.done():
            future.set_result(True)
        return {"status": "accepted"}

    @app.post("/cancel/{stream_id}", status_code=202)
    async def cancel_run(stream_id: str) -> dict[str, str]:
        """Cancel a paused graph run."""
        future = _resume_futures.get(stream_id)
        if future is None:
            raise HTTPException(
                status_code=404, detail="No paused run found for this id"
            )
        if not future.done():
            future.set_result(False)
        return {"status": "accepted"}

    @app.get("/replay")
    async def replay() -> Any:
        """Return the last saved run payload for demo fallback."""
        if not LAST_RUN_PATH.exists():
            raise HTTPException(status_code=404, detail="No previous run found")
        return json.loads(LAST_RUN_PATH.read_text())

    @app.post("/api/logs", status_code=204)
    async def browser_log(entry: _BrowserLogEntry) -> None:
        """Receive browser console.warn / console.error and write to server log."""
        if entry.level == "error":
            _logger.error("[browser] %s", entry.message)
        else:
            _logger.warning("[browser] %s", entry.message)

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app
