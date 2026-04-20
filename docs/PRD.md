# Product Requirements Document — Personal Finance Coach Agent

**Owner:** Personal project
**Status:** v0.1 — working prototype
**Last updated:** 2026-04-20

---

## 1. Summary

An AI-powered personal finance coach that ingests a user's bank statements
(CSV, PDF, or Gmail), automatically categorises transactions, tracks progress
against investment goals, and answers natural-language questions about the
user's money — grounded in their real data, not hypothetical advice.

The product is delivered as (a) a FastAPI service with SSE streaming, and
(b) an in-process REPL for interactive use without the server.

---

## 2. Problem statement

Retail users juggle multiple accounts, cards, and goals. Existing personal
finance tools either:

- Require manual categorisation of every transaction, or
- Use rigid rule-based classifiers that mis-label merchants, or
- Produce static dashboards that can't answer free-form questions like
  *"If I redirect my dining budget into the home down payment, when do I hit
  the target?"*

There is no lightweight tool that combines **automatic LLM-based
categorisation** with **conversational analysis** grounded in the user's
actual transactions and goals.

---

## 3. Goals

### 3.1 Product goals

- **G1 — Zero-setup ingestion.** Accept bank statements in the formats users
  already have (CSV export, PDF statement, Gmail inbox) without requiring
  schema mapping.
- **G2 — Accurate auto-categorisation.** Classify every transaction into one
  of 19 categories with per-row confidence, using an LLM rather than rules.
- **G3 — Grounded Q&A.** Every answer must cite or be derived from the user's
  loaded transactions and goals. No generic financial advice.
- **G4 — Goal correlation.** Tie spending patterns to the user's investment
  goals — flag at-risk goals and suggest concrete contribution changes.
- **G5 — Local-first privacy.** Transactions and goals live in a local
  ChromaDB. No third-party analytics. LLM calls go through the user's own
  Google Cloud project.

### 3.2 Non-goals

- Not a budgeting app with bill-pay, account linking, or transaction entry.
- Not a tax or compliance tool — no tax computation, no regulatory advice.
- Not a multi-tenant SaaS — single-user, single-machine scope for v0.1.
- Not a mobile app — CLI + HTTP API only.
- No real-time bank account aggregation (Plaid-style). Ingestion is
  file/email-based.

---

## 4. Target users & personas

| Persona | Context | Why they care |
|---|---|---|
| Self-directed saver | Exports bank CSVs monthly, tracks goals in a spreadsheet | Wants faster, conversational analysis without building dashboards |
| Privacy-conscious technologist | Comfortable running a local Python service, has a GCP project | Doesn't want to hand transaction data to a third-party SaaS |
| Goal-oriented planner | Has 3–8 concrete investment goals with target dates | Wants ongoing feedback on whether current spending supports the plan |

All personas are assumed to be comfortable with the command line and able to
run `gcloud auth application-default login`.

---

## 5. User stories

### 5.1 Ingestion

- **US-1** — As a user, I can upload a CSV bank statement and have every row
  parsed and categorised without mapping columns manually.
- **US-2** — As a user, I can upload a PDF statement and have it parsed into
  the same transaction schema as a CSV.
- **US-3** — As a user, I can authorise Gmail and have bank-statement emails
  from the last N months ingested automatically.
- **US-4** — As a user, I can upload an investment-goals CSV with arbitrary
  column names and have it normalised into the goal schema.
- **US-5** — As a user, I can re-ingest the same file safely without
  duplicates in the vector store.

### 5.2 Analysis & chat

- **US-6** — As a user, I can ask "Where did most of my money go last
  month?" and get an answer derived from my transactions.
- **US-7** — As a user, I can ask "Am I on track for my emergency fund?"
  and get a goal-specific answer that references my planned contributions
  and current progress.
- **US-8** — As a user, I can ask hypothetical questions ("If I redirect my
  dining budget into goal X, when do I hit the target?") and get a
  data-grounded projection.
- **US-9** — As a user, I can get a complete financial summary (income,
  expenses, savings rate, top categories, insights, goal correlations) as
  a single structured response.
- **US-10** — As a user, I can stream the agent's response token-by-token
  via SSE.

### 5.3 Session management

- **US-11** — As a user, I can reset all loaded data between sessions.
- **US-12** — As a user, I can see a summary of how much data is currently
  loaded.

---

## 6. Functional requirements

### 6.1 Ingestion

| ID | Requirement |
|---|---|
| FR-1 | Accept CSV uploads via `POST /ingest/csv` with account name. |
| FR-2 | Accept PDF uploads via `POST /ingest/pdf`. Fall back to `pymupdf` when `pdfplumber` fails on scanned PDFs. |
| FR-3 | Fetch bank-statement emails from Gmail via `POST /ingest/gmail?months_back=N`. OAuth consent on first run, cached token after. |
| FR-4 | Normalise arbitrary CSV headers via LLM before parsing. |
| FR-5 | Categorise transactions in batches of 50 via the fast LLM (`claude-haiku-4-5`). |
| FR-6 | Upsert by `Transaction.id` to allow safe re-ingestion. |
| FR-7 | Accept investment-goals CSV via `POST /ingest/goals` with LLM header normalisation. |

### 6.2 Analysis

| ID | Requirement |
|---|---|
| FR-8 | Expose `GET /summary` returning a `FinancialSummary` (income, expenses, savings rate, top categories, insights, goal correlations). |
| FR-9 | Expose `GET /transactions` with filters (category, date range, amount range). |
| FR-10 | Expose `GET /goals` returning each goal with status (`on_track` / `at_risk` / `behind` / `achieved` / `not_started`). |
| FR-11 | Expose `GET /stats` returning counts of loaded transactions, goals, and sources. |

### 6.3 Conversational agent

| ID | Requirement |
|---|---|
| FR-12 | Expose `POST /chat` returning a complete response. |
| FR-13 | Expose `POST /chat/stream` with SSE streaming (`text/event-stream`). |
| FR-14 | Route each query in LangGraph to either `retrieval` (RAG + live stats) or `analysis` (computed summary). |
| FR-15 | Every answer must be produced by `claude-opus-4-7` via Vertex AI. |
| FR-16 | Persist Q&A pairs to the `financial_insights` ChromaDB collection for future retrieval. |

### 6.4 Admin

| ID | Requirement |
|---|---|
| FR-17 | Expose `DELETE /reset` to clear all transactions, goals, and chat history. |
| FR-18 | Expose `GET /health` for liveness checks (used by Makefile guards). |

### 6.5 CLI

| ID | Requirement |
|---|---|
| FR-19 | Provide an in-process REPL (`scripts/cli.py`) that uses the same `FinanceCoachAgent` as the API. |
| FR-20 | Support slash commands: `/ingest`, `/goals`, `/summary`, `/reset`, `/help`, `/quit`. |
| FR-21 | Support one-shot non-interactive mode via `--ask "..."`. |

---

## 7. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-1 | **Privacy.** Transactions and goals must not leave the user's machine or their own GCP project. No third-party analytics. |
| NFR-2 | **Auth.** All LLM access uses Google Application Default Credentials. No Anthropic API key anywhere in the codebase. |
| NFR-3 | **Performance.** Categorisation batch of 50 rows completes in a single Haiku call. API responses for `/summary` under 5s on 1,000 transactions. |
| NFR-4 | **Resilience.** Ingestion never raises — errors are returned as structured error strings and logged with context. |
| NFR-5 | **Reproducibility.** `uv sync` + `.env` + `gcloud auth application-default login` is sufficient to run the full stack. |
| NFR-6 | **Test coverage.** 43+ tests covering ingestion and API contract. |
| NFR-7 | **Observability.** Structured logging via `logging.getLogger(__name__)`. No `print()` in production code. |

---

## 8. Architecture

### 8.1 Stack

| Layer | Technology |
|---|---|
| Reasoning LLM | `claude-opus-4-7` via Vertex AI Model Garden |
| Fast LLM | `claude-haiku-4-5@20251001` via Vertex AI (categorisation, header normalisation) |
| Orchestration | LangGraph `StateGraph` with `TypedDict` state |
| Vector store | ChromaDB (local persistent) |
| Embeddings | OpenAI `text-embedding-3-small` (fallback: local `all-MiniLM-L6-v2`) |
| API | FastAPI + SSE streaming |
| Auth | Google Application Default Credentials |
| Runtime | Python 3.12, `uv` package manager |

### 8.2 Graph flow

```
route_query
   ├── "analysis"  ──▶ analysis_node   (FinancialAnalyser + goal correlation)
   └── "retrieval" ──▶ retrieval_node  (ChromaDB + live stats)
                              │
                       generate_answer  (Opus 4.7)
                              │
                            [END]
```

### 8.3 ChromaDB collections

| Collection | Purpose | Upsert key |
|---|---|---|
| `transactions` | One doc per `Transaction` with metadata (date, year, month, amount, type, category, merchant) | `Transaction.id` |
| `investment_goals` | One doc per `InvestmentGoal` | `InvestmentGoal.id` |
| `financial_insights` | Q&A pairs from past conversations for retrieval augmentation | generated id |

Metadata filters are always applied *before* vector search.

---

## 9. Data model (canonical — `src/models.py`)

| Model | Key fields |
|---|---|
| `Transaction` | `id`, `date`, `description`, `amount` (always positive), `transaction_type` (`debit`/`credit`), `category`, `subcategory`, `merchant`, `account`, `confidence` |
| `TransactionBatch` | `transactions`, `source_name`, `source_type` (`csv`/`pdf`/`gmail`), `account_holder` |
| `InvestmentGoal` | `id`, `name`, `goal_type`, `target_amount`, `current_amount`, `monthly_contribution`, `target_date`, `priority`, `notes` |
| `CategoryBudget` | `category`, `monthly_limit`, `actual_spent` |
| `SpendingInsight` | `title`, `description`, `impact`, `action`, `amount_involved` |
| `GoalCorrelation` | `goal`, `status`, `monthly_surplus_available`, `recommended_contribution`, `gap`, `insights`, `months_to_goal` |
| `FinancialSummary` | `period_start`, `period_end`, `total_income`, `total_expenses`, `net_savings`, `savings_rate_pct`, `top_categories`, `insights`, `goal_correlations` |

### 9.1 Controlled vocabularies

- **`TransactionCategory`:** `food_dining`, `groceries`, `transport`, `fuel`,
  `utilities`, `rent_emi`, `healthcare`, `entertainment`, `shopping`,
  `travel`, `education`, `investments`, `insurance`, `subscriptions`,
  `salary_income`, `other_income`, `transfers`, `fees_charges`, `other`.
- **`GoalType`:** `emergency_fund`, `retirement`, `home_purchase`,
  `education`, `travel`, `vehicle`, `business`, `wealth_building`,
  `debt_payoff`, `other`.
- **`GoalStatus`:** `on_track`, `at_risk`, `behind`, `achieved`,
  `not_started`.

---

## 10. API surface

| Method | Path | Purpose |
|---|---|---|
| POST | `/ingest/csv` | Upload CSV bank statement |
| POST | `/ingest/pdf` | Upload PDF bank statement |
| POST | `/ingest/gmail` | Fetch and ingest bank emails |
| POST | `/ingest/goals` | Upload investment goals CSV |
| POST | `/chat` | Non-streaming chat |
| POST | `/chat/stream` | SSE streaming chat |
| GET | `/summary` | Full `FinancialSummary` |
| GET | `/transactions` | Filtered transactions |
| GET | `/goals` | Goals with computed status |
| GET | `/stats` | Load counts |
| DELETE | `/reset` | Clear all state |
| GET | `/health` | Liveness check |

---

## 11. Constraints & assumptions

- **Single user, single machine.** No authentication layer on the API.
- **GCP account required.** User must have Claude models enabled in Vertex
  AI Model Garden and authenticated via ADC.
- **No `temperature` on Opus 4.x.** Vertex AI rejects the parameter with
  400. The LLM factory handles this automatically — it must not be bypassed.
- **Haiku 4.5 is regional-only.** Not available on `global`. Must be served
  from a regional endpoint (e.g. `us-east5`, `europe-west4`, `asia-southeast1`).
- **Currency assumption.** Sample data is INR; the code is currency-agnostic
  but no explicit currency field is stored on a transaction today. An
  explicit `currency` field on `Transaction` is committed for v0.2.
- **Embeddings default.** v0.1 ships with local `all-MiniLM-L6-v2` as the
  default to keep the stack fully local/private. OpenAI `text-embedding-3-small`
  remains an opt-in upgrade via `OPENAI_API_KEY` and is on the roadmap for
  a later release.

---

## 12. Success metrics

| Metric | Target |
|---|---|
| Categorisation accuracy (spot-checked against sample CSV) | ≥ 90% correct category out of 19 |
| `/summary` latency, 1k transactions | < 5s |
| Ingestion idempotency on re-upload | 0 duplicate docs in `transactions` collection |
| Test suite | 43+ tests passing on every change |
| Setup time for a new user (after GCP prerequisites) | < 10 minutes to first chat response |

---

## 13. Risks & mitigations

| Risk | Mitigation |
|---|---|
| PDF parsing fails on scanned statements | `pdfplumber` → `pymupdf` fallback inside `PDFIngester` |
| LLM returns categories outside the enum | Prompt constrains to enum values; post-parse validation snaps unknowns to `OTHER` |
| Embedding provider outage (OpenAI) | Automatic fallback to local `all-MiniLM-L6-v2` |
| User re-ingests the same file and doubles in-memory state | `DELETE /reset` documented; ChromaDB side is upsert-safe |
| Vertex AI rejects `temperature` for Opus 4.x | `_supports_temperature()` guard in `src/llm.py` |
| Gmail OAuth token expiry | Token cached at `GMAIL_TOKEN_PATH`, refresh flow on next invocation |

---

## 14. Out of scope for v0.1 (future work)

- Multi-user / multi-tenant deployment with auth.
- Real-time account aggregation (Plaid, Salt Edge, account-aggregator APIs).
- Browser UI beyond the CLI and curl-able API.
- Budget creation and alerting (schema exists via `CategoryBudget` but no
  endpoint yet).
- Multi-currency transactions (base `currency` field lands in v0.2; true
  multi-currency conversion is later).
- Scheduled ingestion (cron-driven Gmail pulls).
- Export of summaries to PDF / email.
- Tax-lot tracking for investment goals.

---

## 15. Resolved decisions & open questions

### Resolved
- **Embeddings default:** local `all-MiniLM-L6-v2` for v0.1. OpenAI
  `text-embedding-3-small` moves to a later release as an opt-in upgrade.
- **Currency field:** add explicit `currency` on `Transaction` in v0.2.

### Open
- Is a lightweight web UI worth building, or is the API + CLI sufficient
  for the target personas?
