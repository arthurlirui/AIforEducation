"""读史 HistorySandbox — API entrypoint."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .models import AskRequest, NarrationRequest, WorldCommand
from .services import ai_narrator, list_events, get_event, world_model

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI for 历史教育 · 沉浸式三维沙盘推演教学平台",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs",
        "endpoints": ["/api/events", "/api/events/{id}", "/api/narrate", "/api/ask"],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_enabled": bool(settings.llm_api_key)}


@app.get("/api/events")
def api_list_events():
    """Event catalog (summaries without heavy step payloads)."""
    out = []
    for ev in list_events():
        out.append({
            "id": ev.id,
            "title": ev.title,
            "subtitle": ev.subtitle,
            "era": ev.era,
            "year_start": ev.year_start,
            "year_end": ev.year_end,
            "scale": ev.scale,
            "summary": ev.summary,
            "spirit_core": ev.spirit_core,
            "step_count": len(ev.steps),
            "nations": [n.model_dump() for n in ev.nations],
        })
    return out


@app.get("/api/events/{event_id}")
def api_get_event(event_id: str):
    ev = get_event(event_id)
    if ev is None:
        raise HTTPException(status_code=404, detail=f"event not found: {event_id}")
    return ev.model_dump()


@app.post("/api/narrate")
async def api_narrate(req: NarrationRequest):
    result = await ai_narrator.narrate(req.event_id, req.step_id, req.style)
    if result is None:
        raise HTTPException(status_code=404, detail="event or step not found")
    return result.model_dump()


@app.post("/api/ask")
async def api_ask(req: AskRequest):
    result = await ai_narrator.ask(req.event_id, req.step_id, req.question, req.top_k)
    if result is None:
        raise HTTPException(status_code=404, detail="event not found")
    return result.model_dump()


@app.post("/api/simulate")
async def api_simulate(cmd: WorldCommand):
    """World-model interaction: branch the sandbox with a user command."""
    try:
        result = await world_model.simulate_command(
            cmd.event_id, cmd.step_id,
            {
                "command": cmd.command,
                "actor_id": cmd.actor_id,
                "target_nation": cmd.target_nation,
                "target_position": cmd.target_position,
                "question": cmd.question,
                "seed": cmd.seed,
            },
        )
    except world_model.CommandUnavailable as e:
        raise HTTPException(status_code=409, detail={"reason": e.reason, "message": e.detail})
    if result is None:
        raise HTTPException(status_code=422, detail="invalid command for this step")
    return result.model_dump()
