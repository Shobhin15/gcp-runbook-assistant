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


def _declare(tool) -> types.FunctionDeclaration:
    kinds = {"string": "STRING", "integer": "INTEGER"}
    return types.FunctionDeclaration(
        name=tool.name,
        description=tool.description,
        parameters=types.Schema(
            type="OBJECT",
            properties={
                name: types.Schema(type=kinds[p.type], description=p.description)
                for name, p in tool.params.items()
            },
            required=[name for name, p in tool.params.items() if p.required],
        ),
    )


def _to_contents(history: list[dict]) -> list[types.Content]:
    """Convert agent.py's provider-neutral history into Gemini messages."""
    contents: list[types.Content] = []
    for item in history:
        if item["role"] == "user":
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=item["text"])]))
        elif item["role"] == "model":
            # Replay Gemini's own message so its function-call parts stay intact
            contents.append(item["raw"])
        else:
            part = types.Part.from_function_response(name=item["name"], response=item["result"])
            # Results of one model turn's calls go back together in a single message
            if contents and contents[-1].role == "tool":
                contents[-1].parts.append(part)
            else:
                contents.append(types.Content(role="tool", parts=[part]))
    return contents


def make_chat_model():
    """Gemini with function calling, for the triage agent. The agent loop runs the tools itself."""
    from app.agent import ModelTurn, ToolCall

    client = _client()

    def chat(system_prompt: str, history: list[dict], tools: list) -> ModelTurn:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=_to_contents(history),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                max_output_tokens=1024,
                tools=[types.Tool(function_declarations=[_declare(t) for t in tools])] if tools else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                thinking_config=types.ThinkingConfig(thinking_budget=0) if "2.5-flash" in GEMINI_MODEL else None,
            ),
        )
        content = response.candidates[0].content if response.candidates else None
        parts = (content.parts or []) if content else []
        calls = [ToolCall(p.function_call.name, dict(p.function_call.args or {})) for p in parts if p.function_call]
        text = "".join(p.text for p in parts if p.text and not getattr(p, "thought", False))
        return ModelTurn(text=text, calls=calls, raw=content)

    return chat
