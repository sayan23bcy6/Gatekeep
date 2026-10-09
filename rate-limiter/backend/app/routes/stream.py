"""SSE endpoint that streams live statistics."""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..stats import stats_event_generator

router = APIRouter(prefix="/stream", tags=["stream"])


@router.get("/stats")
async def stream_stats(request: Request) -> StreamingResponse:
    """Server-Sent Events endpoint – emits a JSON snapshot every second."""
    redis_client = request.app.state.redis

    async def event_stream():
        async for event in stats_event_generator(redis_client):
            if await request.is_disconnected():
                break
            yield event

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
            "Connection": "keep-alive",
        },
    )
