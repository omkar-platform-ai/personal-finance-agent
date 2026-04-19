# Personal Finance Coach Agent

AI-powered personal finance coach built with **LangGraph**, **RAG**, and **Claude Opus 4.7** via **Google Vertex AI Model Garden**.

Ingests bank statements from CSV, PDF, or Gmail — then lets you have a natural conversation about your money and investment goals.

---

## Stack

| Layer | Technology |
|---|---|
| LLM | Claude Opus 4.7 via Vertex AI Model Garden |
| Fast LLM | Claude Haiku 4.5 via Vertex AI (categorisation) |
| Orchestration | LangGraph stateful agent |
| Vector store | ChromaDB (local) |
| Embeddings | OpenAI text-embedding-3-small or local all-MiniLM |
| API | FastAPI + SSE streaming |
| Auth | Google Application Default Credentials (ADC) |

---

## Project Structure

```
finance-agent/
├── src/
│   ├── models.py                   # Pydantic v2 schemas
│   ├── llm.py                      # ChatAnthropicVertex factory
│   ├── ingestion/
│   │   └── document_loader.py      # CSV / PDF / Gmail ingestion + LLM categoriser
│   ├── memory/
│   │   └── vector_store.py         # ChromaDB RAG store
│   ├── agents/
│   │   ├── analyser.py             # Spending analysis + goal correlation engine
│   │   └── finance_agent.py        # LangGraph agent graph
│   └── api/
│       └── main.py                 # FastAPI application (10 endpoints)
├── scripts/demo.py                 # Scripted demo on sample data
├── scripts/cli.py                  # Interactive REPL (in-process, no API server)
├── tests/                          # 43 unit + integration tests
├── data/samples/                   # Sample CSV statement + goals
├── pyproject.toml
├── .env.example                    # Copy to .env and fill in
├── Dockerfile
└── docker-compose.yml
```

---

## Prerequisites

### 1. Enable Claude on Vertex AI Model Garden

1. Go to [Vertex AI Model Garden](https://console.cloud.google.com/vertex-ai/model-garden)
2. Search for **Claude Opus 4.7** → click **Enable**
3. Accept the Anthropic terms of service
4. Note your **Project ID** and choose a **region** (e.g. `us-east5`)

### 2. Authenticate locally

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

### 3. Service account (for CI / Docker / Cloud Run)

```bash
# Create a service account
gcloud iam service-accounts create finance-agent \
  --display-name="Finance Agent"

# Grant Vertex AI User role
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:finance-agent@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Download key (local only — use Workload Identity on GKE/Cloud Run)
gcloud iam service-accounts keys create sa-key.json \
  --iam-account=finance-agent@YOUR_PROJECT_ID.iam.gserviceaccount.com

export GOOGLE_APPLICATION_CREDENTIALS=./sa-key.json
```

---

## Quick Start

```bash
# 1. Clone and install
git clone <repo>
cd finance-agent
uv sync                          # or: pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
# Edit .env:  set VERTEX_PROJECT and VERTEX_LOCATION

# 3. Authenticate (local dev)
gcloud auth application-default login

# 4. Run the scripted demo on sample data
make demo

# 5. Or open the interactive CLI (no API server needed)
make cli                         # empty REPL — use /ingest and /goals to load data
make cli-sample                  # REPL pre-loaded with sample CSV + goals

# 6. Or start the API
make dev                         # API at http://localhost:8000
make ingest-sample               # load sample bank statement CSV
make ingest-goals                # load investment goals CSV
make chat                        # ask a question
```

---

## Interactive CLI

A standalone REPL that talks to the same `FinanceCoachAgent` the API uses, but
runs in-process — no FastAPI server required.

```bash
make cli                         # empty REPL
make cli-sample                  # REPL pre-loaded with sample data

# Or invoke directly with flags
uv run python3 scripts/cli.py --csv data/samples/sample_bank_statement.csv \
                              --goals data/samples/investment_goals.csv \
                              --account "HDFC Savings"

# One-shot mode (non-interactive)
uv run python3 scripts/cli.py --ask "Am I on track for my emergency fund?"
```

### Slash commands inside the REPL

| Command | Description |
|---|---|
| `/ingest <path>` | Load a bank statement CSV (auto-categorised) |
| `/goals <path>` | Load an investment goals CSV |
| `/summary` | Show how much data is currently loaded |
| `/reset` | Clear all transactions, goals, and chat history |
| `/help` | Show command help |
| `/quit` | Exit |

Anything else you type is sent to the finance coach agent. Conversation
history persists for the lifetime of the session.

### Example prompts

Once you've loaded transactions and goals, try questions like:

**Spending analysis**
- `Where did most of my money go last month?`
- `Show me all food and dining transactions over ₹1,000.`
- `What's my average monthly spend on subscriptions?`
- `Which merchant did I pay the most to in the last 90 days?`
- `Compare my discretionary spend in March vs February.`
- `Are there any recurring charges I might have forgotten about?`

**Income & cashflow**
- `What was my total income last month and how much did I save?`
- `What's my month-over-month savings rate trend?`
- `How much surplus do I have available to invest each month?`

**Investment goals**
- `Am I on track for my emergency fund?`
- `Which of my goals are at risk and why?`
- `If I redirect my dining budget into the home down payment goal, when do I hit the target?`
- `Rank my goals by how far behind they are.`
- `How much should I contribute monthly to retire by 60?`

**Coaching & recommendations**
- `Give me a complete overview of my finances.`
- `What are the top 3 things I should change to save more?`
- `Suggest a realistic monthly budget based on my actual spending.`
- `Where are the biggest leaks in my budget?`

The agent grounds every answer in your loaded transactions and goals — no
hypothetical advice without your data behind it.

---

## API Usage

### Upload bank statement (CSV)

```bash
curl -X POST http://localhost:8000/ingest/csv \
  -F "file=@data/samples/sample_bank_statement.csv" \
  -F "account_name=HDFC Savings"
```

### Upload PDF statement

```bash
curl -X POST http://localhost:8000/ingest/pdf \
  -F "file=@my_statement.pdf"
```

### Fetch from Gmail

```bash
curl -X POST "http://localhost:8000/ingest/gmail?months_back=3"
```

### Upload investment goals

```bash
curl -X POST http://localhost:8000/ingest/goals \
  -F "file=@data/samples/investment_goals.csv"
```

### Chat

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Am I on track for my emergency fund?"}'
```

### Full financial summary

```bash
curl http://localhost:8000/summary
```

---

## Investment Goals CSV Format

The agent uses LLM header normalisation — any reasonable column names work.

```csv
name,goal_type,target_amount,current_amount,monthly_contribution,target_date,priority,notes
Emergency Fund,emergency_fund,300000,85000,10000,2025-12-31,1,6 months expenses
Home Down Payment,home_purchase,2500000,150000,15000,2028-06-30,2,30% down
Retirement Corpus,retirement,20000000,500000,5000,,3,Target age 60
```

**Valid `goal_type` values:** `emergency_fund`, `retirement`, `home_purchase`,
`education`, `travel`, `vehicle`, `business`, `wealth_building`, `debt_payoff`, `other`

---

## LangGraph Architecture

```
[route_query]
     │
     ├── "analysis" ──→ [analysis_node]   (FinancialAnalyser + goal correlation)
     │                         │
     └── "retrieval" ─→ [retrieval_node]  (ChromaDB RAG + live stats)
                               │
                      [generate_answer]   (Claude Opus 4.7 via Vertex AI)
                               │
                             [END]
```

---

## Vertex AI Model Used

| Purpose | Model | Why |
|---|---|---|
| Financial analysis, Q&A, goal correlation | `claude-opus-4-7` | Best reasoning for complex multi-step financial logic |
| Transaction categorisation, header normalisation | `claude-haiku-4-5` | 50-row batches need speed + low cost |

Both served via **Vertex AI Model Garden** — no direct Anthropic API key needed.
Auth is handled entirely by Google ADC / service account.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `VERTEX_PROJECT` | Yes | — | GCP project ID |
| `VERTEX_LOCATION` | No | `us-east5` | Vertex AI region for the primary model |
| `VERTEX_FAST_LOCATION` | No | falls back to `VERTEX_LOCATION` | Region override for the fast model (Haiku 4.5 is regional-only — set to `us-east5`, `europe-west4`, or `asia-southeast1`; not available on `global`) |
| `LLM_MODEL` | No | `claude-opus-4-7` | Primary model |
| `LLM_FAST_MODEL` | No | `claude-haiku-4-5` | Bulk task model |
| `LLM_TEMPERATURE` | No | `0.1` | LLM temperature |
| `OPENAI_API_KEY` | No | — | For embeddings (falls back to local if blank) |
| `CHROMA_PERSIST_PATH` | No | `./data/chroma_db` | Vector store path |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | — | Path to SA key JSON (server/CI auth) |
