"""
src/_silence.py
─────────────────────────────────────────────────────────────────────────────
Suppress noisy third-party output that pollutes CLI / API logs:

  • LangChain deprecation warnings (Chroma, HuggingFaceEmbeddings, ...)
  • Hugging Face Hub download progress bars
  • transformers "BertModel LOAD REPORT" printed during local embedding load
  • INFO-level chatter from transformers / sentence_transformers / huggingface_hub

Imported (and invoked) at the top of ``src/memory/vector_store.py`` so every
entry point — API server, demo, CLI, tests — gets a quiet runtime without
having to remember to call it.
"""

from __future__ import annotations

import logging
import os
import warnings

_DONE = False


def silence_noisy_libraries() -> None:
    """Idempotent — safe to call multiple times."""
    global _DONE
    if _DONE:
        return

    # LangChain deprecation warnings (e.g. Chroma moved to langchain-chroma).
    # We intentionally stay on langchain_community for now; the deprecation
    # text is noise for users until we migrate. Filtering by category is
    # required — LangChain's @deprecated decorator emits via warn_deprecated()
    # in a way that message-pattern filters miss.
    try:
        from langchain_core._api.deprecation import LangChainDeprecationWarning

        warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
    except ImportError:
        warnings.filterwarnings(
            "ignore",
            message=r".*was deprecated in LangChain.*",
        )

    # Hugging Face download progress bars — pure noise outside of debugging.
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

    # transformers prints a "BertModel LOAD REPORT" via its own logger when
    # loading a model whose checkpoint has extra/missing keys (harmless for
    # all-MiniLM-L6-v2). Lower its verbosity to error.
    try:
        from transformers import logging as hf_logging

        hf_logging.set_verbosity_error()
        hf_logging.disable_progress_bar()
    except ImportError:
        pass

    # Standard logging fallback for libraries that don't honour the above.
    for name in ("transformers", "sentence_transformers", "huggingface_hub"):
        logging.getLogger(name).setLevel(logging.ERROR)

    _DONE = True
