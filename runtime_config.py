"""Runtime LLM selection shared by NEXUS agents and evaluation.

DeepSeek (`deepseek/deepseek-chat`) is now the default production provider.
Groq GPT-OSS 120B and Gemini remain supported as explicit opt-ins through
environment variables. This module reads configuration only; it never reads,
logs, or returns API key values.
"""

from __future__ import annotations

import os

OFFICIAL_PROVIDER = "deepseek"
OFFICIAL_MODEL = "deepseek-chat"
_DEFAULT_MODELS = {
    "deepseek": OFFICIAL_MODEL,
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-3.5-flash-lite",  # gemini-2.5-flash is closed to new accounts (2026-10); see docs/PROJECT_STATE.md
}


def resolve_runtime_config(
    provider: str | None = None, model: str | None = None,
) -> tuple[str, str]:
    """Return a validated LiteLLM provider/model pair without secrets."""
    selected_provider = (provider or os.environ.get("NEXUS_LLM_PROVIDER", OFFICIAL_PROVIDER)).strip().lower()
    if selected_provider not in _DEFAULT_MODELS:
        raise ValueError("NEXUS_LLM_PROVIDER must be one of: deepseek, groq, gemini")
    selected_model = (model or os.environ.get("NEXUS_LLM_MODEL") or _DEFAULT_MODELS[selected_provider]).strip()
    if not selected_model:
        raise ValueError("NEXUS_LLM_MODEL must not be empty")
    return selected_provider, selected_model


def litellm_model_name(provider: str | None = None, model: str | None = None) -> str:
    selected_provider, selected_model = resolve_runtime_config(provider, model)
    return f"{selected_provider}/{selected_model}"


def is_official_benchmark_config(provider: str | None = None, model: str | None = None) -> bool:
    return resolve_runtime_config(provider, model) == (OFFICIAL_PROVIDER, OFFICIAL_MODEL)
