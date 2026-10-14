"""Vertex AI implementations of the embedder and generator used by rag.py."""
from __future__ import annotations

import os
from typing import Sequence

from google import genai
from google.genai import types

EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-005")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


def _client() -> genai.Client:
    # On Cloud Run this authenticates as the service's runtime service account.
    return genai.Client(
        vertexai=True,
        project=os.environ["GCP_PROJECT"],
        location=os.getenv("GCP_LOCATION", "us-central1"),
    )


def make_embedder():
    client = _client()

    def embed(texts: Sequence[str], task_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 100):
            result = client.models.embed_content(
                model=EMBED_MODEL,
                contents=list(texts[start:start + 100]),
                config=types.EmbedContentConfig(task_type=task_type),
            )
            vectors.extend(e.values for e in result.embeddings)
        return vectors

    return embed


def make_generator():
    client = _client()

    def generate(system_prompt: str, user_prompt: str) -> str:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                max_output_tokens=1024,
                # Simple lookup task: skip "thinking" so the whole budget goes to the answer
                thinking_config=types.ThinkingConfig(thinking_budget=0) if "2.5-flash" in GEMINI_MODEL else None,
            ),
        )
        return response.text or ""

    return generate
