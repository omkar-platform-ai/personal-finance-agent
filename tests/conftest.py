"""
tests/conftest.py
─────────────────────────────────────────────────────────────────────────────
Global test setup: provides dummy Vertex env vars and replaces
ChatAnthropicVertex with a MagicMock so tests can construct ingesters,
categorisers, and analysers without real GCP credentials.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ.setdefault("VERTEX_PROJECT", "ci-test-project")
os.environ.setdefault("VERTEX_LOCATION", "us-east5")

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _mock_vertex_chat(monkeypatch):
    monkeypatch.setattr("src.llm.ChatAnthropicVertex", MagicMock)
