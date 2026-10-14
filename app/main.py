"""HTTP API for the runbook assistant (Cloud Run)."""
from __future__ import annotations

import json
import logging
import time
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app import rag

RUNBOOK_DIR = Path(__file__).resolve().parent.parent / "runbooks"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("runbook-assistant")

app = FastAPI(title="Runbook Assistant", version="1.0.0")


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000)


@lru_cache(maxsize=1)
def services():
    from app import vertex  # imported lazily so /healthz works without cloud credentials

    index = rag.RunbookIndex(rag.load_runbooks(RUNBOOK_DIR), vertex.make_embedder())
    return index, vertex.make_generator()


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
