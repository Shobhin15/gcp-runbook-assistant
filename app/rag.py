"""Retrieval-augmented generation (RAG) over on-call runbooks.

Kept free of any cloud SDK so it can be unit tested offline: the embedding
and text-generation functions are passed in, and the real Vertex AI versions
live in vertex.py.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

Embedder = Callable[[Sequence[str], str], list[list[float]]]  # (texts, task_type) -> vectors
Generator = Callable[[str, str], str]                          # (system_prompt, user_prompt) -> answer

SYSTEM_PROMPT = (
    "You are an on-call assistant for a site reliability team. Answer ONLY from the runbook "
    "excerpts provided. If the excerpts do not contain the answer, say you don't know and suggest "
    "escalating. Give short, ordered steps and cite the runbook name for each step in [brackets]. "
    "Never invent commands, hostnames, or credentials."
)


@dataclass
class Chunk:
    source: str
    text: str
    vector: list[float] = field(default_factory=list)


def chunk_markdown(source: str, text: str, max_chars: int = 1200) -> list[Chunk]:
    """Split a runbook on '## ' headings, then cap each piece at max_chars."""
    sections = re.split(r"\n(?=## )", text.strip())
    chunks: list[Chunk] = []
    for section in sections:
        section = section.strip()
        while len(section) > max_chars:
            cut = section.rfind("\n", 0, max_chars)
            cut = cut if cut > 0 else max_chars
            chunks.append(Chunk(source, section[:cut].strip()))
            section = section[cut:].strip()
        if section:
            chunks.append(Chunk(source, section))
    return chunks


def load_runbooks(folder: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(folder.glob("*.md")):
        chunks.extend(chunk_markdown(path.stem, path.read_text(encoding="utf-8")))
    return chunks


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class RunbookIndex:
    """A small in-memory vector index. Fine for dozens of runbooks; swap in
    Vertex AI Vector Search when the corpus grows to thousands of documents."""

    def __init__(self, chunks: list[Chunk], embed: Embedder):
        self.embed = embed
        self.chunks = chunks
        vectors = embed([c.text for c in chunks], "RETRIEVAL_DOCUMENT") if chunks else []
        for chunk, vector in zip(chunks, vectors):
            chunk.vector = vector

    def search(self, query: str, k: int = 3, min_score: float = 0.3) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        qvec = self.embed([query], "RETRIEVAL_QUERY")[0]
        scored = sorted(((c, cosine(qvec, c.vector)) for c in self.chunks), key=lambda x: x[1], reverse=True)
        return [(c, s) for c, s in scored[:k] if s >= min_score]


def build_prompt(question: str, hits: list[tuple[Chunk, float]]) -> str:
    excerpts = "\n\n".join(f"[{c.source}]\n{c.text}" for c, _ in hits)
    return f"Runbook excerpts:\n\n{excerpts}\n\nQuestion: {question}"


def answer(question: str, index: RunbookIndex, generate: Generator, k: int = 3) -> dict:
    question = question.strip()
    if not question:
        raise ValueError("question is empty")
    if len(question) > 1000:
        raise ValueError("question is too long (max 1000 characters)")
    hits = index.search(question, k=k)
    if not hits:
        return {
            "answer": "I couldn't find anything relevant in the runbooks. Please escalate to the on-call lead.",
            "sources": [],
        }
    text = generate(SYSTEM_PROMPT, build_prompt(question, hits))
    # One entry per runbook, keeping its best-matching section's score
    best: dict[str, float] = {}
    for c, s in hits:
        best[c.source] = max(s, best.get(c.source, 0.0))
    return {
        "answer": text,
        "sources": [{"runbook": name, "score": round(score, 3)} for name, score in best.items()],
    }
