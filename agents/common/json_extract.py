"""Tolerant JSON extraction from free-form model text. ADK-free so every venv can import it."""

from __future__ import annotations

import json
import re

_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", re.DOTALL | re.IGNORECASE)


def extract_json(text: str):
    """Best-effort structured extraction from a model's free-form reply.

    Tries a fenced ```json block first, then the raw stripped text, then the
    largest top-level {...}/[...] span in the text. Returns None (never raises)
    if nothing in the text parses as JSON -- callers must treat that as "the
    model gave no usable structured output" and fail safe, not guess.
    """
    if not text:
        return None
    candidates: list[str] = []
    fenced = _FENCED_JSON_RE.search(text)
    if fenced:
        candidates.append(fenced.group(1))
    stripped = text.strip()
    candidates.append(stripped)
    first = min((i for i in (stripped.find("{"), stripped.find("[")) if i != -1), default=-1)
    if first != -1:
        last = max(stripped.rfind("}"), stripped.rfind("]"))
        if last > first:
            candidates.append(stripped[first : last + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    return None
