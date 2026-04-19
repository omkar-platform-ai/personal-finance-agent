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
├── scripts/demo.py                 # CLI demo with Rich output
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

# 4. Run the CLI demo on sample data
make demo

# 5. Or start the API
make dev                         # API at http://localhost:8000
make ingest-sample               # load sample bank statement CSV
make ingest-goals                # load investment goals CSV
make chat                        # ask a question
```

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
| Transaction categorisation, header normalisation | `claude-haiku-4-5@20251001` | 50-row batches need speed + low cost |

Both served via **Vertex AI Model Garden** — no direct Anthropic API key needed.
Auth is handled entirely by Google ADC / service account.

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `VERTEX_PROJECT` | Yes | — | GCP project ID |
| `VERTEX_LOCATION` | No | `us-east5` | Vertex AI region |
| `LLM_MODEL` | No | `claude-opus-4-7` | Primary model |
| `LLM_FAST_MODEL` | No | `claude-haiku-4-5@20251001` | Bulk task model |
| `LLM_TEMPERATURE` | No | `0.1` | LLM temperature |
| `OPENAI_API_KEY` | No | — | For embeddings (falls back to local if blank) |
| `CHROMA_PERSIST_PATH` | No | `./data/chroma_db` | Vector store path |
| `GOOGLE_APPLICATION_CREDENTIALS` | No | — | Path to SA key JSON (server/CI auth) |
