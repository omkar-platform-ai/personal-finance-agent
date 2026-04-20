# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

From v0.1.0 onward, this file is maintained automatically by
[python-semantic-release](https://python-semantic-release.readthedocs.io/)
based on [Conventional Commits](https://www.conventionalcommits.org/). See
[docs/RELEASING.md](docs/RELEASING.md) for the versioning policy and commit format.

<!-- version list -->

## v0.2.0 (2026-04-20)

### Bug Fixes

- **release**: Drop unsupported {changelog} placeholder from commit_message
  ([`38bee50`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/38bee50c6e8a5dd78681a1d6b5841a8ee8a582f8))

### Chores

- **lint**: Apply ruff format and configure per-file lint exemptions
  ([`dbbae38`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/dbbae386778e88f66c4748af31c8dc2ceed44020))

### Continuous Integration

- Add fully automated semantic-release pipeline
  ([`7a9059a`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/7a9059ae4d7a0596957e6378d5ed13fb7d47630b))

- Fix changelog config path and dry-run Makefile targets
  ([`8df75bd`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/8df75bd0963ae891d03e0208d8bec03143e8cd4a))

- Gate release workflow on CI success via workflow_run
  ([`d7a6b85`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/d7a6b85c9588c743d6fe83f3801fbc38c63a8425))

- Pin release action to v10 and drop unused publish-action
  ([`c3acb0f`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/c3acb0f82c83efe3ff5636cc46e560ed3032489a))

### Documentation

- Add product requirements document
  ([`8ce5c8f`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/8ce5c8f0085a4aa1f7796f5e3b6d3d298da3e95f))

### Features

- **models**: Add currency field to Transaction
  ([`216f3d8`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/216f3d83b85b82189a0cfca6488b3595e10b8e46))

### Testing

- Add conftest to mock Vertex LLM and stub env vars
  ([`779ab8c`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/779ab8c521bdf85c929701d96091529f1edd16e3))

- Clean up imports and xfail 6 pre-existing failures
  ([`55b4a47`](https://github.com/omkar-platform-ai/personal-finance-agent/commit/55b4a474a363560032353c13ee1788010010101d))


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
