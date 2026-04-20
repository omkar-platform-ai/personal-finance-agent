"""
src/memory/vector_store.py
─────────────────────────────────────────────────────────────────────────────
ChromaDB-backed vector store for transactions, goals, and insights.
Supports semantic search so the conversational agent can answer questions
like "What did I spend on food last month?" with grounded context.
"""

from __future__ import annotations

# Silence transformers / langchain deprecation noise *before* the offending
# imports run. This module is on the import path of every entry point that
# touches the vector store (API, demo, CLI, tests).
from src._silence import silence_noisy_libraries

silence_noisy_libraries()

import logging
import os
from typing import Any

import chromadb
from chromadb.config import Settings
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings

from src.models import InvestmentGoal, Transaction, TransactionCategory

logger = logging.getLogger(__name__)

CHROMA_PATH = os.getenv("CHROMA_PERSIST_PATH", "./data/chroma_db")

# Collections
COLLECTION_TRANSACTIONS = "transactions"
COLLECTION_GOALS = "investment_goals"
COLLECTION_INSIGHTS = "financial_insights"


def _get_embeddings():
    """Use OpenAI embeddings (cost-effective) or sentence-transformers locally."""
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        return OpenAIEmbeddings(
            model="text-embedding-3-small",
            api_key=openai_key,
        )
    # Fallback: local sentence-transformers (no API key needed)
    from langchain_community.embeddings import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")


class FinanceVectorStore:
    """
    Wraps ChromaDB with domain-specific indexing for finance data.

    Stores:
      - Each transaction as a Document with rich metadata for filtering
      - Each investment goal with description and progress
      - Generated insights for future retrieval
    """

    def __init__(self) -> None:
        self._embeddings = _get_embeddings()
        self._client = chromadb.PersistentClient(
            path=CHROMA_PATH,
            settings=Settings(anonymized_telemetry=False),
        )
        logger.info("FinanceVectorStore initialised at %s", CHROMA_PATH)

    # ── Transaction indexing ──────────────────────────────────────────────────

    def index_transactions(self, transactions: list[Transaction]) -> None:
        """Embed and store all transactions. Safe to call multiple times (upsert)."""
        if not transactions:
            return

        docs: list[Document] = []
        for tx in transactions:
            # Rich natural-language text for embedding
            text = (
                f"{tx.date} | {tx.transaction_type.value.upper()} | "
                f"₹{tx.amount:,.2f} | {tx.merchant or tx.description} | "
                f"Category: {tx.category.value} | {tx.subcategory or ''}"
            )
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "id": tx.id,
                        "date": str(tx.date),
                        "year": tx.date.year,
                        "month": tx.date.month,
                        "amount": tx.amount,
                        "type": tx.transaction_type.value,
                        "category": tx.category.value,
                        "merchant": tx.merchant or "",
                        "account": tx.account or "",
                        "source": tx.source_file or "",
                    },
                )
            )

        vectorstore = Chroma(
            collection_name=COLLECTION_TRANSACTIONS,
            embedding_function=self._embeddings,
            client=self._client,
        )
        # Upsert by ID
        vectorstore.add_documents(docs, ids=[tx.id for tx in transactions])
        logger.info("Indexed %d transactions into vector store", len(docs))

    def search_transactions(
        self,
        query: str,
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[Document]:
        """Semantic search over transactions with optional metadata filters."""
        vectorstore = Chroma(
            collection_name=COLLECTION_TRANSACTIONS,
            embedding_function=self._embeddings,
            client=self._client,
        )
        where = filters or None
        results = vectorstore.similarity_search(query, k=k, filter=where)
        return results

    def get_transactions_by_filter(
        self,
        month: int | None = None,
        year: int | None = None,
        category: TransactionCategory | None = None,
        min_amount: float | None = None,
    ) -> list[Document]:
        """Metadata-filtered retrieval (no embedding needed)."""
        where: dict[str, Any] = {}
        if month:
            where["month"] = month
        if year:
            where["year"] = year
        if category:
            where["category"] = category.value

        vectorstore = Chroma(
            collection_name=COLLECTION_TRANSACTIONS,
            embedding_function=self._embeddings,
            client=self._client,
        )
        # Use a broad query to trigger metadata filter path
        results = vectorstore.similarity_search(
            "transaction spending",
            k=500,
            filter=where if where else None,
        )
        if min_amount:
            results = [r for r in results if r.metadata.get("amount", 0) >= min_amount]
        return results

    # ── Goal indexing ─────────────────────────────────────────────────────────

    def index_goals(self, goals: list[InvestmentGoal]) -> None:
        """Embed and store investment goals."""
        if not goals:
            return

        docs: list[Document] = []
        for goal in goals:
            text = (
                f"Investment goal: {goal.name} | Type: {goal.goal_type.value} | "
                f"Target: ₹{goal.target_amount:,.0f} | "
                f"Current: ₹{goal.current_amount:,.0f} | "
                f"Monthly planned: ₹{goal.monthly_contribution:,.0f} | "
                f"Progress: {goal.progress_pct:.1f}% | "
                f"Target date: {goal.target_date or 'not set'} | "
                f"Priority: {goal.priority} | {goal.notes or ''}"
            )
            docs.append(
                Document(
                    page_content=text,
                    metadata={
                        "id": goal.id,
                        "name": goal.name,
                        "goal_type": goal.goal_type.value,
                        "target_amount": goal.target_amount,
                        "current_amount": goal.current_amount,
                        "monthly_contribution": goal.monthly_contribution,
                        "priority": goal.priority,
                    },
                )
            )

        vectorstore = Chroma(
            collection_name=COLLECTION_GOALS,
            embedding_function=self._embeddings,
            client=self._client,
        )
        vectorstore.add_documents(docs, ids=[g.id for g in goals])
        logger.info("Indexed %d investment goals", len(docs))

    def search_goals(self, query: str, k: int = 5) -> list[Document]:
        vectorstore = Chroma(
            collection_name=COLLECTION_GOALS,
            embedding_function=self._embeddings,
            client=self._client,
        )
        return vectorstore.similarity_search(query, k=k)

    # ── Insights indexing ─────────────────────────────────────────────────────

    def index_insight(self, insight_text: str, metadata: dict[str, Any] | None = None) -> None:
        """Store a generated insight for future retrieval."""
        vectorstore = Chroma(
            collection_name=COLLECTION_INSIGHTS,
            embedding_function=self._embeddings,
            client=self._client,
        )
        import uuid

        vectorstore.add_documents(
            [Document(page_content=insight_text, metadata=metadata or {})],
            ids=[str(uuid.uuid4())],
        )

    def search_insights(self, query: str, k: int = 5) -> list[Document]:
        vectorstore = Chroma(
            collection_name=COLLECTION_INSIGHTS,
            embedding_function=self._embeddings,
            client=self._client,
        )
        return vectorstore.similarity_search(query, k=k)

    # ── Stats helpers ─────────────────────────────────────────────────────────

    def get_collection_count(self, collection: str = COLLECTION_TRANSACTIONS) -> int:
        try:
            col = self._client.get_collection(collection)
            return col.count()
        except Exception:
            return 0

    def clear_all(self) -> None:
        """Wipe all collections — use only in testing."""
        for name in [COLLECTION_TRANSACTIONS, COLLECTION_GOALS, COLLECTION_INSIGHTS]:
            try:
                self._client.delete_collection(name)
            except Exception:
                pass
        logger.warning("All vector store collections cleared")
