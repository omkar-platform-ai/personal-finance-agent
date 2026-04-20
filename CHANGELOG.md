# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

From v0.1.0 onward, this file is maintained automatically by
[python-semantic-release](https://python-semantic-release.readthedocs.io/)
based on [Conventional Commits](https://www.conventionalcommits.org/). See
[docs/RELEASING.md](docs/RELEASING.md) for the versioning policy and commit format.

<!-- version list -->

## [0.1.0] — 2026-04-20

### Added
- CSV, PDF, and Gmail bank statement ingestion with LLM-driven auto-categorisation.
- Investment goals CSV ingestion with LLM header normalisation.
- LangGraph `StateGraph` agent routing between retrieval (RAG) and analysis (computed summary) paths.
- FastAPI service exposing 12 endpoints — ingestion, chat, SSE streaming, analysis, and admin.
- Interactive REPL (`scripts/cli.py`) with slash commands, in-process agent, and one-shot mode.
- ChromaDB vector store with three collections: `transactions`, `investment_goals`, `financial_insights`.
- Claude Opus 4.7 reasoning model + Haiku 4.5 fast categoriser, both served via Vertex AI Model Garden.
- Local `all-MiniLM-L6-v2` embeddings as default, with optional OpenAI `text-embedding-3-small` upgrade.
- 43 unit and integration tests.
- Dockerfile and docker-compose for containerised runs.
- Product Requirements Document at [docs/PRD.md](docs/PRD.md).
