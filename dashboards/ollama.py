"""Thin client for the local Ollama server, shared by both dashboard panels.

Generation is streamed rather than awaited in one lump purely for how it feels: on a
CPU-only machine a completion arrives at single-digit tokens per second, so a blocking
call is fifteen silent seconds, while streaming shows the answer taking shape at once.

Nothing here reaches the network beyond localhost.
"""
from __future__ import annotations

import json
from typing import Callable

import requests

BASE_URL = "http://localhost:11434"
GENERATE_URL = f"{BASE_URL}/api/generate"
EMBED_URL = f"{BASE_URL}/api/embed"

# A code-tuned 3B model rather than a general 8B chat model: better at its size on the
# structured work both panels ask for, and it fits in memory on an 8GB machine, which
# llama3.1:8b does not. See docs/adr/0007-local-llm-for-nl-to-sql.md.
CHAT_MODEL = "qwen2.5-coder:3b"
EMBED_MODEL = "nomic-embed-text"

# Hold the model in memory between questions. The default five minutes expires mid-demo
# and costs a ~9 second reload on the next one.
KEEP_ALIVE = "30m"

REQUEST_TIMEOUT = 300


class OllamaUnavailable(RuntimeError):
    """The local Ollama server isn't reachable."""


class ModelError(RuntimeError):
    """Ollama was reached, but it failed to produce a completion."""


def _unavailable(model: str) -> OllamaUnavailable:
    return OllamaUnavailable(
        f"Can't reach Ollama at {BASE_URL}. Install it from ollama.com, run "
        f"`ollama pull {model}` once, and make sure Ollama is running, then retry."
    )


def stream_completion(
    prompt: str,
    on_token: Callable[[str], None] | None = None,
    model: str = CHAT_MODEL,
    max_tokens: int = 400,
    clean: Callable[[str], str] | None = None,
) -> str:
    """Stream one completion. `on_token` receives the text accumulated so far.

    `clean` lets the caller tidy each partial before it is displayed, so a panel showing
    the answer as it arrives never flashes a stray markdown fence.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    parts: list[str] = []
    try:
        with requests.post(
            GENERATE_URL, json=payload, timeout=REQUEST_TIMEOUT, stream=True
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line:
                    continue
                chunk = json.loads(line)
                if chunk.get("error"):
                    raise ModelError(chunk["error"])
                token = chunk.get("response", "")
                if token:
                    parts.append(token)
                    if on_token is not None:
                        text = "".join(parts)
                        on_token(clean(text) if clean else text)
                if chunk.get("done"):
                    break
    except requests.exceptions.ConnectionError as exc:
        raise _unavailable(model) from exc
    except requests.exceptions.Timeout as exc:
        raise ModelError(
            f"Ollama did not answer within {REQUEST_TIMEOUT}s. On a CPU-only machine the "
            f"first question after a pause also pays for loading the model."
        ) from exc

    text = "".join(parts)
    return clean(text) if clean else text


def embed(texts: list[str], model: str = EMBED_MODEL) -> list[list[float]]:
    """Embed a batch of texts. One forward pass each, so far quicker than generation."""
    try:
        response = requests.post(
            EMBED_URL,
            json={"model": model, "input": texts, "keep_alive": KEEP_ALIVE},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise _unavailable(model) from exc
    return response.json()["embeddings"]
