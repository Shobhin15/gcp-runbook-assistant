"""HTTP API for the runbook assistant (Cloud Run)."""
from __future__ import annotations

import json
import logging
import os
import time
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import agent, rag

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("runbook-assistant")

app = FastAPI(title="Runbook Assistant", version="1.0.0")


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


class Incident(BaseModel):
    incident: str = Field(min_length=1, max_length=1000)


@lru_cache(maxsize=1)
def services():
    from app import vertex  # imported lazily so /healthz works without cloud credentials

    index = rag.RunbookIndex(rag.load_runbooks(RUNBOOK_DIR), vertex.make_embedder())
    return index, vertex.make_generator()


@lru_cache(maxsize=1)
def triage_services():
    from app import tools, vertex  # lazy, like services()

    index, _ = services()
    project, location = os.environ["GCP_PROJECT"], os.getenv("GCP_LOCATION", "us-central1")
    return vertex.make_chat_model(), tools.default_tools(index, project, location)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "runbooks": len(list(RUNBOOK_DIR.glob("*.md")))}


@app.post("/ask")
def ask(body: Question):
    start = time.monotonic()
    index, generate = services()
    try:
        result = rag.answer(body.question, index, generate)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Structured log line: Cloud Logging parses JSON, so these fields become searchable.
    log.info(json.dumps({
        "event": "ask",
        "latency_ms": round((time.monotonic() - start) * 1000),
        "sources": [s["runbook"] for s in result["sources"]],
        "answered": bool(result["sources"]),
    }))
    return result


@app.post("/triage")
def triage(body: Incident):
    """Agentic triage: Gemini chooses read-only tools (runbooks, error logs, service status),
    then proposes a next step for a human to approve. Every tool call is in the response."""
    start = time.monotonic()
    model, toolset = triage_services()
    try:
        result = agent.triage(body.incident, model, toolset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    log.info(json.dumps({
        "event": "triage",
        "latency_ms": round((time.monotonic() - start) * 1000),
        "tool_calls": [f"{s['tool']}:{s['status']}" for s in result["steps"]],
        "sources": result["sources"],
    }))
    return result
