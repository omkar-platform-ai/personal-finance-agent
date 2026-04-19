"""
src/llm.py
─────────────────────────────────────────────────────────────────────────────
LLM client factory — Google Vertex AI Model Garden (ChatAnthropicVertex).

Authentication:
    Uses Google Application Default Credentials (ADC). No API key needed.
    Set up once with:  gcloud auth application-default login
    Or in GCP infra:   attach a service account with roles/aiplatform.user

Required env vars:
    VERTEX_PROJECT        — your GCP project ID
    VERTEX_LOCATION       — region where Claude is enabled (e.g. us-east5)

Optional env vars:
    LLM_MODEL             — override model name (default: claude-opus-4-7)
    LLM_FAST_MODEL        — override fast model  (default: claude-haiku-4-5@20251001)
    VERTEX_FAST_LOCATION  — region for the fast model (default: VERTEX_LOCATION).
                            Use this when the fast model is not served at the
                            same endpoint as the reasoning model — e.g.
                            VERTEX_LOCATION=global serves Opus 4.x but Haiku 4.5
                            is regional-only (us-east5, europe-west4,
                            asia-southeast1).

Note on temperature:
    Claude Opus 4.x models do NOT accept a temperature parameter — it is
    deprecated for this model family. Temperature is only passed for
    Haiku/Sonnet models where it is still supported.
"""
from __future__ import annotations

import logging
import os

from langchain_core.language_models import BaseChatModel
from langchain_google_vertexai.model_garden import ChatAnthropicVertex

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_MODEL  = "claude-opus-4-7"
_DEFAULT_FAST   = "claude-haiku-4-5@20251001"
_DEFAULT_MAXTOK = 4096

# Models that do NOT accept temperature (Opus 4.x family)
_NO_TEMPERATURE_MODELS = ("claude-opus-4",)


def _supports_temperature(model_name: str) -> bool:
    """Return False for models that reject the temperature parameter."""
    return not any(model_name.startswith(m) for m in _NO_TEMPERATURE_MODELS)


def _vertex_project() -> str:
    project = os.getenv("VERTEX_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT", "")
    if not project:
        raise EnvironmentError(
            "VERTEX_PROJECT env var is not set. "
            "Add it to your .env file: VERTEX_PROJECT=my-gcp-project-id"
        )
    return project


def _vertex_location() -> str:
    return os.getenv("VERTEX_LOCATION", "us-east5")


def _vertex_fast_location() -> str:
    """Location for the fast (Haiku) model — falls back to VERTEX_LOCATION."""
    return os.getenv("VERTEX_FAST_LOCATION") or _vertex_location()


def get_llm(
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int = _DEFAULT_MAXTOK,
    location: str | None = None,
) -> BaseChatModel:
    """
    Returns a ChatAnthropicVertex instance pointed at Vertex AI Model Garden.

    Automatically omits temperature for Opus 4.x models where it is deprecated.
    """
    chosen_model = model or os.getenv("LLM_MODEL", _DEFAULT_MODEL)
    project      = _vertex_project()
    location     = location or _vertex_location()

    kwargs: dict = dict(
        model_name=chosen_model,
        project=project,
        location=location,
        max_tokens=max_tokens,
    )

    # Only pass temperature for models that still support it
    if temperature is not None and _supports_temperature(chosen_model):
        kwargs["temperature"] = temperature
        logger.info(
            "Initialising ChatAnthropicVertex: model=%s project=%s location=%s temperature=%s",
            chosen_model, project, location, temperature,
        )
    else:
        logger.info(
            "Initialising ChatAnthropicVertex: model=%s project=%s location=%s (no temperature)",
            chosen_model, project, location,
        )

    return ChatAnthropicVertex(**kwargs)


def get_fast_llm(max_tokens: int = 1024) -> BaseChatModel:
    """
    Haiku — fast and cheap for bulk tasks (categorisation, header normalisation).
    Temperature is still supported on Haiku so we pass 0.0 for deterministic output.

    ``max_tokens`` defaults to 1024 (sufficient for header normalisation).
    Bulk callers like the transaction categoriser pass a larger value because
    a 50-tx batch easily exceeds 1024 output tokens and gets truncated mid-JSON.

    Uses VERTEX_FAST_LOCATION when set, since Haiku 4.5 is not served at the
    `global` Vertex endpoint that Opus 4.x supports.
    """
    return get_llm(
        model=os.getenv("LLM_FAST_MODEL", _DEFAULT_FAST),
        temperature=0.0,
        max_tokens=max_tokens,
        location=_vertex_fast_location(),
    )


def get_reasoning_llm() -> BaseChatModel:
    """
    Claude Opus 4.7 via Vertex AI for financial analysis, goal correlation, Q&A.
    Temperature is NOT passed — deprecated for Opus 4.x.
    """
    return get_llm(
        model=os.getenv("LLM_MODEL", _DEFAULT_MODEL),
        max_tokens=_DEFAULT_MAXTOK,
    )