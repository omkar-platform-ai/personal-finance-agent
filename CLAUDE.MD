# Personal Finance Coach Agent — Claude Project Context

> Read this file before touching any code. It eliminates the need to re-explain
> architecture, conventions, and decisions in every conversation.

---

## What this project is

An AI-powered personal finance coach that ingests bank statements (CSV, PDF, Gmail),
categorises transactions, tracks investment goals, and answers natural-language
questions about spending — all grounded in the user's real data.

**Live stack:**
- LLM: `claude-opus-4-7` via Google Vertex AI Model Garden (no temperature — deprecated for this model)
- Fast LLM: `claude-haiku-4-5@20251001` via Vertex AI (categorisation batches)
- Orchestration: LangGraph `StateGraph` with typed `GraphState` (TypedDict)
- Vector store: ChromaDB (local persistent) — 3 collections: `transactions`, `investment_goals`, `financial_insights`
- Embeddings: OpenAI `text-embedding-3-small` (falls back to local `all-MiniLM-L6-v2`)
- API: FastAPI with SSE streaming on `/chat/stream`
- Auth: Google Application Default Credentials — **no Anthropic API key anywhere**

---

## Project layout

```
src/
  models.py              ← ALL Pydantic v2 schemas — single source of truth
  llm.py                 ← ChatAnthropicVertex factory — always import from here
  ingestion/
    document_loader.py   ← CSVIngester, PDFIngester, GmailIngester,
                            TransactionCategoriser, InvestmentGoalsLoader
  memory/
    vector_store.py      ← FinanceVectorStore — ChromaDB wrapper
  agents/
    analyser.py          ← FinancialAnalyser — pure Python, stateless, no side effects
    finance_agent.py     ← LangGraph graph + FinanceCoachAgent class
  api/
    main.py              ← FastAPI app, all 10 endpoints, lazy agent singleton
scripts/
  demo.py                ← CLI end-to-end demo (Rich output)
tests/
  test_ingestion.py      ← 25 unit tests
  test_api.py            ← 18 integration tests (mocked agent)
data/samples/
  sample_bank_statement.csv
  investment_goals.csv
```

---

## Architecture — data flow

```
Input (CSV / PDF / Gmail bytes)
  └─▶ Ingester  →  TransactionBatch
        └─▶ TransactionCategoriser (Haiku, batch=50)  →  categorised Transactions
              └─▶ FinanceCoachAgent.load_transactions()
                    ├─▶ agent._state["transactions"]   (in-memory list)
                    └─▶ FinanceVectorStore.index_transactions()  (ChromaDB)

User query  →  FinanceCoachAgent.chat(query)
  └─▶ LangGraph graph:
        route_query  →  "retrieval" | "analysis"
          ├─▶ retrieval_node    (ChromaDB semantic search + live stats)
          └─▶ analysis_node     (FinancialAnalyser.generate_summary())
                └─▶ generate_answer_node  (Opus 4.7 via Vertex)
                      └─▶ final_answer string
```

---

## Key conventions — follow these exactly

### Python
- Python 3.12, Pydantic v2, `from __future__ import annotations` on every file
- Type hints mandatory on all function signatures
- `async def` + `await` for all IO (LLM calls, file reads, DB writes)
- Structured logging: `logger = logging.getLogger(__name__)` — never `print()`
- Error handling: catch specific exceptions, log with context, return gracefully
- Never raise from tool/ingestion code — return error strings instead

### LLM calls
- Always import from `src.llm` — never instantiate `ChatAnthropicVertex` directly
- Use `get_fast_llm()` for: CSV header normalisation, bulk categorisation, goals CSV parsing
- Use `get_reasoning_llm()` for: financial analysis, goal correlation, Q&A generation
- **Never pass `temperature` to Opus 4.x** — it raises a 400 error
- All LLM prompts must end with `Return ONLY the JSON ...` to prevent markdown fences
- Strip fences before `json.loads()`: `raw.replace("```json", "").replace("```", "").strip()`
- Batch size for categorisation: 50 transactions per LLM call (see `BATCH_SIZE = 50`)

### LangGraph state
- `GraphState` is a `TypedDict` — never a Pydantic model
- `messages` uses `Annotated[list, operator.add]` — messages accumulate, not overwrite
- Never mutate state in-place inside nodes — always return `{**state, "key": new_value}`
- Route values: `"retrieval"` | `"analysis"` (set in `route_query`, read by `route_condition`)

### ChromaDB collections
- `transactions` — one doc per Transaction, metadata: id, date, year, month, amount, type, category, merchant
- `investment_goals` — one doc per InvestmentGoal
- `financial_insights` — Q&A pairs stored after each answer for future retrieval
- Always upsert by `tx.id` — safe to re-ingest the same file
- Metadata filter BEFORE vector search — always cheaper and more precise

### API endpoints
- All ingestion endpoints write to `/tmp/` for temp files, clean up in `finally`
- Agent is a lazy singleton: `_agent = None`, initialised on first request
- `load_dotenv()` called at module top-level in `main.py` — env vars always available
- Streaming uses `StreamingResponse` with `text/event-stream` media type
- `check-server` Makefile guard uses `/health` endpoint

### Models (src/models.py)
- `Transaction.amount` is always positive — sign is in `transaction_type`
- Use `tx.signed_amount` when you need negative debits
- `InvestmentGoal.progress_pct` is capped at 100.0
- `GoalStatus` values: `on_track` | `at_risk` | `behind` | `achieved` | `not_started`
- `TransactionCategory` enum values are snake_case strings — use `.value` for JSON

---

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `VERTEX_PROJECT` | YES | — | GCP project ID |
| `VERTEX_LOCATION` | no | `us-east5` | Region with Claude enabled (Opus 4.x supports `global`) |
| `VERTEX_FAST_LOCATION` | no | `VERTEX_LOCATION` | Region for Haiku — must be regional; Haiku 4.5 is not on `global` |
| `LLM_MODEL` | no | `claude-opus-4-7` | Primary model |
| `LLM_FAST_MODEL` | no | `claude-haiku-4-5@20251001` | Bulk task model |
| `CHROMA_PERSIST_PATH` | no | `./data/chroma_db` | Vector store path |
| `OPENAI_API_KEY` | no | — | Embeddings (falls back to local) |
| `GOOGLE_APPLICATION_CREDENTIALS` | no | — | SA key path for server/CI auth |
| `GMAIL_CREDENTIALS_PATH` | no | `./credentials.json` | Gmail OAuth |
| `GMAIL_TOKEN_PATH` | no | `./data/gmail_token.json` | Gmail token cache |

---

## Common tasks — use the skills

For recurring development tasks, load the appropriate skill file from `.claude/skills/`:

| Task | Skill file |
|---|---|
| Add a new API endpoint | `.claude/skills/add-endpoint.md` |
| Add a new transaction category | `.claude/skills/add-category.md` |
| Write or extend tests | `.claude/skills/testing.md` |
| Add a new ingestion source | `.claude/skills/add-ingester.md` |
| Tune an LLM prompt | `.claude/skills/prompt-tuning.md` |
| Add a new LangGraph node | `.claude/skills/add-graph-node.md` |

---

## What NOT to do

- Do not add `temperature` to any `ChatAnthropicVertex` call for Opus 4.x models
- Do not import `ChatAnthropicVertex` directly — always use `src.llm.get_llm()`
- Do not use `print()` — use `logger.info/warning/error()`
- Do not store API keys or secrets in any source file
- Do not use `position: fixed` in any frontend HTML (iframe height collapses)
- Do not create new Pydantic models outside `src/models.py`
- Do not mutate `GraphState` in-place inside LangGraph nodes
- Do not catch bare `Exception` without logging context
- Do not hardcode `/tmp/` paths in tests — use `pytest`'s `tmp_path` fixture
- Do not call `get_reasoning_llm()` for tasks that `get_fast_llm()` can handle

---

## Running the project

```bash
uv sync                          # install deps
gcloud auth application-default login   # auth once
make dev                         # start API on :8000

# In another terminal:
make ingest-sample               # load sample CSV
make ingest-goals                # load goals CSV
make chat                        # test a query
make vertex-check                # verify Vertex AI connection
make test                        # run test suite
```

---

## Known issues / gotchas

1. **`temperature` on Opus 4.x** — raises `400 invalid_request_error`. The `_supports_temperature()` check in `llm.py` handles this — don't bypass it.
2. **ChromaDB upsert** — re-ingesting the same file is safe (upsert by `tx.id`), but will double-count in the in-memory `_state["transactions"]` list. Clear with `DELETE /reset` between test runs.
3. **Gmail first run** — opens a browser tab for OAuth consent. Subsequent runs use the cached token at `GMAIL_TOKEN_PATH`.
4. **PDF extraction quality** — `pdfplumber` struggles with scanned PDFs. Use `pymupdf` as fallback for image-heavy PDFs (see `PDFIngester`).
5. **Embedding fallback** — if `OPENAI_API_KEY` is not set, `HuggingFaceEmbeddings` loads `all-MiniLM-L6-v2` locally on first use (~90MB download, ~2s cold start).
6. **`uv run` required** — all `make` targets use `uv run` to ensure the `.venv` is active. Running `python3` directly will use the system Python and miss all packages.