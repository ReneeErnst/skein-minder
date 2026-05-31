"""FastAPI web server for SkeinMinder."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from skeinminder.ravelry.normalizer import StashItem
from skeinminder.web.events import LAST_RUN_PATH, stream_graph_events

_STATIC_DIR = Path(__file__).parent / "static"


class _RecommendRequest(BaseModel):
    """Request body for POST /recommend."""

    goal: str
    use_fixture: bool = False


def create_app(
    stash: list[StashItem],
    ravelry_username: str,
    use_fixture: bool = False,
) -> FastAPI:
    """Create and configure the SkeinMinder FastAPI app.

    Stash is loaded once at startup and shared across all requests.
    Each POST /recommend creates an asyncio.Queue for SSE delivery.
    """
    _streams: dict[str, asyncio.Queue[str | None]] = {}

    app = FastAPI(title="SkeinMinder")

    async def _run_graph(stream_id: str, goal: str, req_use_fixture: bool) -> None:
        queue = _streams.get(stream_id)
        if queue is None:
            return
        try:
            async for event in stream_graph_events(
                goal, stash, ravelry_username, req_use_fixture
            ):
                await queue.put(event)
        finally:
            await queue.put(None)

    @app.post("/recommend")
    async def start_recommend(request: _RecommendRequest) -> dict[str, str]:
        """Start a graph run; events stream via GET /stream/{stream_id}."""
        stream_id = str(uuid.uuid4())
        _streams[stream_id] = asyncio.Queue()
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

        return StreamingResponse(generator(), media_type="text/event-stream")

    @app.post("/approve/{stream_id}", status_code=202)
    async def approve_run(stream_id: str) -> dict[str, str]:
        """Phase 9 seam: approve a paused run. Not yet wired to graph interrupt."""
        return {"status": "accepted"}

    @app.post("/cancel/{stream_id}", status_code=202)
    async def cancel_run(stream_id: str) -> dict[str, str]:
        """Phase 9 seam: cancel a paused run. Not yet wired to graph interrupt."""
        return {"status": "accepted"}

    @app.get("/replay")
    async def replay() -> Any:
        """Return the last saved run payload for demo fallback."""
        if not LAST_RUN_PATH.exists():
            raise HTTPException(status_code=404, detail="No previous run found")
        return json.loads(LAST_RUN_PATH.read_text())

    @app.get("/")
    async def root() -> FileResponse:
        return FileResponse(_STATIC_DIR / "index.html")

    app.mount("/", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    return app
