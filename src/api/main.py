"""
src/api/main.py
─────────────────────────────────────────────────────────────────────────────
FastAPI application exposing the finance coach agent as a REST API.

Endpoints:
  POST /ingest/csv           — upload CSV bank statement
  POST /ingest/pdf           — upload PDF bank statement
  POST /ingest/gmail         — fetch statements from Gmail
  POST /ingest/goals         — upload investment goals CSV
  POST /chat                 — conversational Q&A (sync)
  POST /chat/stream          — streaming chat (SSE)
  GET  /summary              — full financial analysis report
  GET  /transactions         — list/filter transactions
  GET  /goals                — list goals with correlation status
  DELETE /reset              — clear all data for fresh start
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Lazy-loaded agent (singleton per process) ─────────────────────────────────
_agent = None


def get_agent():
    global _agent
    if _agent is None:
        from src.agents.finance_agent import FinanceCoachAgent

        _agent = FinanceCoachAgent()
    return _agent


# ── App setup ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs("./data", exist_ok=True)
    logger.info("Finance Coach Agent API starting...")
    get_agent()  # warm up
    yield
    logger.info("Finance Coach Agent API shutting down.")


app = FastAPI(
    title="Personal Finance Coach Agent",
    description="AI-powered finance coach with RAG, LangGraph, and investment goal correlation",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request/Response models ────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_reset: bool = False


class ChatResponse(BaseModel):
    answer: str
    sources_used: int = 0


class IngestResponse(BaseModel):
    success: bool
    transactions_loaded: int
    message: str


class GoalIngestResponse(BaseModel):
    success: bool
    goals_loaded: int
    message: str


# ── Ingestion endpoints ───────────────────────────────────────────────────────


@app.post("/ingest/csv", response_model=IngestResponse, tags=["ingestion"])
async def ingest_csv(
    file: UploadFile = File(...),
    account_name: str | None = Form(default=None, description="Optional account label"),
):
    """Upload a CSV bank/credit card statement."""
    from src.ingestion.document_loader import CSVIngester, TransactionCategoriser

    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a .csv")

    tmp_path = Path(f"/tmp/{file.filename}")
    tmp_path.write_bytes(await file.read())

    try:
        ingester = CSVIngester()
        batch = ingester.ingest(tmp_path, account_name)

        categoriser = TransactionCategoriser()
        batch.transactions = categoriser.categorise(batch.transactions)

        agent = get_agent()
        agent.load_transactions(batch.transactions)

        return IngestResponse(
            success=True,
            transactions_loaded=len(batch.transactions),
            message=f"Loaded {len(batch.transactions)} transactions from {file.filename}",
        )
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/ingest/pdf", response_model=IngestResponse, tags=["ingestion"])
async def ingest_pdf(
    file: UploadFile = File(...),
    account_name: str | None = Form(default=None),
):
    """Upload a PDF bank statement."""
    from src.ingestion.document_loader import PDFIngester, TransactionCategoriser

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "File must be a .pdf")

    pdf_bytes = await file.read()

    ingester = PDFIngester()
    batch = ingester.ingest(
        file_bytes=pdf_bytes,
        file_name=file.filename,
        account_name=account_name,
    )

    categoriser = TransactionCategoriser()
    batch.transactions = categoriser.categorise(batch.transactions)

    agent = get_agent()
    agent.load_transactions(batch.transactions)

    return IngestResponse(
        success=True,
        transactions_loaded=len(batch.transactions),
        message=f"Extracted {len(batch.transactions)} transactions from PDF",
    )


@app.post("/ingest/gmail", response_model=IngestResponse, tags=["ingestion"])
async def ingest_gmail(
    months_back: int = Query(default=3, ge=1, le=12),
):
    """Fetch bank statement attachments from Gmail (requires OAuth setup)."""
    from src.ingestion.document_loader import GmailIngester, TransactionCategoriser

    try:
        ingester = GmailIngester()
        batches = ingester.ingest(months_back=months_back)

        all_transactions = []
        for batch in batches:
            all_transactions.extend(batch.transactions)

        if all_transactions:
            categoriser = TransactionCategoriser()
            all_transactions = categoriser.categorise(all_transactions)

            agent = get_agent()
            agent.load_transactions(all_transactions)

        return IngestResponse(
            success=True,
            transactions_loaded=len(all_transactions),
            message=f"Fetched {len(all_transactions)} transactions from {len(batches)} Gmail attachments",
        )
    except FileNotFoundError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error("Gmail ingestion error: %s", e)
        raise HTTPException(500, f"Gmail ingestion failed: {str(e)}")


@app.post("/ingest/goals", response_model=GoalIngestResponse, tags=["ingestion"])
async def ingest_goals(file: UploadFile = File(...)):
    """Upload investment goals CSV. See docs for expected columns."""
    from src.ingestion.document_loader import InvestmentGoalsLoader

    if not file.filename.endswith(".csv"):
        raise HTTPException(400, "Goals file must be a .csv")

    tmp_path = Path(f"/tmp/{file.filename}")
    tmp_path.write_bytes(await file.read())

    try:
        loader = InvestmentGoalsLoader()
        goals = loader.load(tmp_path)

        agent = get_agent()
        agent.load_goals(goals)

        return GoalIngestResponse(
            success=True,
            goals_loaded=len(goals),
            message=f"Loaded {len(goals)} investment goals",
        )
    finally:
        tmp_path.unlink(missing_ok=True)


# ── Chat endpoints ─────────────────────────────────────────────────────────────


@app.post("/chat", response_model=ChatResponse, tags=["chat"])
async def chat(request: ChatRequest):
    """Single-turn conversational Q&A over your financial data."""
    agent = get_agent()

    if request.session_reset:
        agent.reset_session()

    answer = agent.chat(request.message)
    return ChatResponse(answer=answer)


@app.post("/chat/stream", tags=["chat"])
async def chat_stream(request: ChatRequest):
    """Streaming chat response via Server-Sent Events."""
    agent = get_agent()

    if request.session_reset:
        agent.reset_session()

    async def event_generator():
        async for token in agent.stream_chat(request.message):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Analysis endpoints ────────────────────────────────────────────────────────


@app.get("/summary", tags=["analysis"])
async def get_summary():
    """Generate and return a full financial analysis with goal correlations."""
    from src.agents.analyser import FinancialAnalyser

    agent = get_agent()
    transactions = agent._state.get("transactions", [])
    goals = agent._state.get("goals", [])

    if not transactions:
        raise HTTPException(400, "No transactions loaded. Upload a statement first.")

    analyser = FinancialAnalyser()
    summary = analyser.generate_summary(transactions, goals)
    return summary.model_dump(mode="json")


@app.get("/transactions", tags=["analysis"])
async def list_transactions(
    month: int = Query(default=None, ge=1, le=12),
    year: int = Query(default=None),
    category: str = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
):
    """List transactions with optional filtering."""
    agent = get_agent()
    transactions = agent._state.get("transactions", [])

    if month:
        transactions = [t for t in transactions if t.date.month == month]
    if year:
        transactions = [t for t in transactions if t.date.year == year]
    if category:
        transactions = [t for t in transactions if t.category.value == category]

    transactions = sorted(transactions, key=lambda t: t.date, reverse=True)[:limit]
    return [t.model_dump(mode="json") for t in transactions]


@app.get("/goals", tags=["analysis"])
async def list_goals():
    """List investment goals with correlation status."""
    from src.agents.analyser import FinancialAnalyser

    agent = get_agent()
    goals = agent._state.get("goals", [])
    transactions = agent._state.get("transactions", [])

    if not goals:
        return []

    analyser = FinancialAnalyser()
    correlations = analyser.correlate_goals(transactions, goals)
    return [
        {
            "goal": c.goal.model_dump(mode="json"),
            "status": c.status.value,
            "monthly_surplus_available": c.monthly_surplus_available,
            "recommended_contribution": c.recommended_contribution,
            "gap": c.gap,
            "months_to_goal": c.months_to_goal,
            "insights": c.insights,
        }
        for c in correlations
    ]


@app.get("/stats", tags=["analysis"])
async def get_stats():
    """Quick stats about loaded data."""
    from src.memory.vector_store import COLLECTION_TRANSACTIONS, FinanceVectorStore

    agent = get_agent()
    store = FinanceVectorStore()
    return {
        "transactions_in_memory": len(agent._state.get("transactions", [])),
        "transactions_in_vector_store": store.get_collection_count(COLLECTION_TRANSACTIONS),
        "goals_loaded": len(agent._state.get("goals", [])),
        "conversation_turns": len(agent._state.get("messages", [])) // 2,
    }


@app.delete("/reset", tags=["admin"])
async def reset_all():
    """Clear all loaded data and conversation history."""
    global _agent
    if _agent:
        _agent.clear_all()
    return {"success": True, "message": "All data cleared"}


# ── Health check ──────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "service": "finance-coach-agent"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.api.main:app",
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", 8000)),
        reload=os.getenv("DEBUG", "false").lower() == "true",
        log_level="info",
    )
