"""AI agent analysis endpoints: the technical/risk/decision pipeline
(src/agent/orchestrator.py) over a configured LLM backend, exposed as
one synchronous call and one Server-Sent-Events streaming call."""

from __future__ import annotations

import contextvars
import json
import queue
import threading
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_config_dep
from src.agent.context import AgentOpinion
from src.agent.dashboard import _public_opinion, build_dashboard
from src.agent.orchestrator import AgentOrchestrator
from src.data.resilience import DataSourceUnavailable
from src.llm.protocol import GenerationError

router = APIRouter()


class AnalyzeRequest(BaseModel):
    symbol: str
    market: str = "us"
    mode: str = "standard"
    # The login area: "trader" gets a short-term trade plan, "investor" a long-term view.
    area: Optional[Literal["trader", "investor"]] = None


@router.post("/agent/analyze")
def analyze(body: AnalyzeRequest, config=Depends(get_config_dep)) -> dict:
    orchestrator = AgentOrchestrator(config=config)
    try:
        ctx = orchestrator.run(body.symbol, body.market, mode=body.mode, area=body.area)
    except GenerationError as exc:
        raise HTTPException(status_code=502, detail=f"LLM backend error: {exc}")
    except DataSourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Market data unavailable: {exc}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return build_dashboard(ctx)


def stream_agent_events(orchestrator: AgentOrchestrator, body: AnalyzeRequest):
    """A plain generator (usable standalone, e.g. in tests, or wrapped in
    a StreamingResponse) that relays pipeline progress as it actually
    happens. AgentOrchestrator.run() is a single blocking call, so it runs
    in a background thread; its on_stage callback pushes events onto a
    queue this generator drains and yields as SSE `data:` lines, rather
    than collecting everything and yielding it only after run() returns."""
    events: "queue.Queue[Any]" = queue.Queue()
    done = object()
    # The worker runs in the request's context: the signed-in user's data
    # scope and AI key (a bare thread would start empty).
    context = contextvars.copy_context()

    def on_stage(event: str, stage: str, payload: object) -> None:
        data: dict = {"event": event, "agent": stage}
        if event == "stage_done" and isinstance(payload, AgentOpinion):
            # No per-agent buy / sell, target or stop, as in the dashboard.
            data["opinion"] = _public_opinion(payload.to_dict())
        elif payload is not None:
            data["message"] = str(payload)
        events.put(data)

    def worker() -> None:
        try:
            ctx = orchestrator.run(body.symbol, body.market, mode=body.mode, on_stage=on_stage, area=body.area)
        except Exception as exc:  # noqa: BLE001 - the one place a critical failure surfaces to the client
            events.put({"event": "error", "message": str(exc)})
        else:
            events.put({"event": "done", "dashboard": build_dashboard(ctx)})
        finally:
            events.put(done)

    threading.Thread(target=context.run, args=(worker,), daemon=True).start()

    while True:
        item = events.get()
        if item is done:
            return
        yield f"data: {json.dumps(item)}\n\n"


@router.post("/agent/analyze/stream")
def analyze_stream(body: AnalyzeRequest, config=Depends(get_config_dep)) -> StreamingResponse:
    orchestrator = AgentOrchestrator(config=config)
    return StreamingResponse(stream_agent_events(orchestrator, body), media_type="text/event-stream")
