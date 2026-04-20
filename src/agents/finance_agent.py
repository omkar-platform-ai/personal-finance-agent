"""
src/agents/finance_agent.py
─────────────────────────────────────────────────────────────────────────────
LangGraph-powered conversational finance agent.

Graph topology:
  [user_input]
       │
  [route_query]  ──→  [retrieval]  ──→  [generate_answer]
       │                                        │
       └──→  [analysis_request]  ──────────────→┘
                                                │
                                          [END / stream]

The agent can:
  1. Answer semantic Q&A over transactions ("What did I spend on dining last month?")
  2. Generate full financial analysis + goal correlation report
  3. Give budget advice ("Am I on track for my emergency fund?")
  4. Spot anomalies ("What were my biggest unexpected expenses?")
"""

from __future__ import annotations

import logging
import operator
from collections.abc import AsyncGenerator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from src.agents.analyser import FinancialAnalyser
from src.llm import get_reasoning_llm
from src.memory.vector_store import FinanceVectorStore
from src.models import FinancialSummary, InvestmentGoal, Transaction

logger = logging.getLogger(__name__)

# ─── LangGraph State ──────────────────────────────────────────────────────────


class GraphState(TypedDict):
    messages: Annotated[list[dict[str, str]], operator.add]
    transactions: list[Transaction]
    goals: list[InvestmentGoal]
    summary: FinancialSummary | None
    current_query: str
    retrieved_context: str
    final_answer: str
    error: str | None
    route: str  # "retrieval" | "analysis" | "direct"


# ─── System Prompt ─────────────────────────────────────────────────────────────

FINANCE_SYSTEM = """You are a personal finance coach with deep expertise in:
- Spending analysis and budget optimisation
- Investment goal planning and progress tracking
- Saving strategies and debt management
- Indian personal finance context (₹, EMIs, SIPs, PPF, etc.)

You have access to the user's actual transaction data and investment goals.
Always ground your answers in the real data provided in the context.
Be specific with numbers. Give actionable advice. Be encouraging but honest.

When discussing amounts, always use ₹ (Indian Rupees).
If data is insufficient to answer, say so clearly and ask for more information.

Tone: Professional but warm. Like a trusted CFP who also knows tech."""


# ─── Node Functions ───────────────────────────────────────────────────────────


def route_query(state: GraphState) -> GraphState:
    """Decide whether query needs retrieval, full analysis, or direct answer."""
    query = state["current_query"].lower()

    analysis_triggers = [
        "summary",
        "analysis",
        "report",
        "overview",
        "breakdown",
        "goals",
        "investment",
        "savings rate",
        "how am i doing",
    ]
    retrieval_triggers = [
        "how much",
        "what did i",
        "show me",
        "list",
        "find",
        "when did",
        "which",
        "top",
        "biggest",
        "most",
    ]

    if any(t in query for t in analysis_triggers):
        route = "analysis"
    elif any(t in query for t in retrieval_triggers) or "?" in query:
        route = "retrieval"
    else:
        route = "retrieval"  # default to retrieval for safety

    logger.debug("Query routed to: %s", route)
    return {**state, "route": route}


def retrieval_node(state: GraphState) -> GraphState:
    """
    Retrieve relevant transactions and insights from vector store.
    Builds a rich context string for the generation node.
    """
    query = state["current_query"]
    store = FinanceVectorStore()

    # Semantic search over transactions
    tx_docs = store.search_transactions(query, k=15)

    # Also search goals
    goal_docs = store.search_goals(query, k=5)

    # Search past insights
    insight_docs = store.search_insights(query, k=3)

    # Also compute live stats for the query
    transactions = state.get("transactions", [])
    goals = state.get("goals", [])

    analyser = FinancialAnalyser()

    # Build context
    context_parts: list[str] = []

    if tx_docs:
        context_parts.append("=== RELEVANT TRANSACTIONS ===")
        for doc in tx_docs[:12]:
            context_parts.append(f"• {doc.page_content}")

    if goal_docs:
        context_parts.append("\n=== INVESTMENT GOALS ===")
        for doc in goal_docs:
            context_parts.append(f"• {doc.page_content}")

    if transactions:
        # Add live aggregated stats
        monthly = analyser.aggregate_by_month(transactions)
        if monthly:
            context_parts.append("\n=== MONTHLY SUMMARY ===")
            for month, data in list(monthly.items())[-3:]:
                context_parts.append(
                    f"• {month}: Income ₹{data['income']:,.0f} | "
                    f"Expenses ₹{data['expenses']:,.0f} | "
                    f"Net ₹{data['net']:,.0f}"
                )

        category_totals = analyser.aggregate_by_category(transactions)
        if category_totals:
            context_parts.append("\n=== TOP SPENDING CATEGORIES (All Time) ===")
            for cat, amt in list(category_totals.items())[:8]:
                context_parts.append(f"• {cat}: ₹{amt:,.0f}")

    if insight_docs:
        context_parts.append("\n=== PREVIOUS INSIGHTS ===")
        for doc in insight_docs:
            context_parts.append(f"• {doc.page_content}")

    if goals:
        context_parts.append("\n=== GOAL PROGRESS ===")
        for g in goals:
            context_parts.append(
                f"• {g.name}: ₹{g.current_amount:,.0f} / ₹{g.target_amount:,.0f} "
                f"({g.progress_pct:.1f}%) — Monthly planned: ₹{g.monthly_contribution:,.0f}"
            )

    retrieved_context = (
        "\n".join(context_parts) if context_parts else "No transaction data loaded yet."
    )

    return {**state, "retrieved_context": retrieved_context}


def analysis_node(state: GraphState) -> GraphState:
    """Run full financial analysis and build comprehensive context."""
    transactions = state.get("transactions", [])
    goals = state.get("goals", [])

    if not transactions:
        return {
            **state,
            "retrieved_context": "No transactions loaded. Please upload a bank statement first.",
        }

    analyser = FinancialAnalyser()
    summary = analyser.generate_summary(transactions, goals)

    context_parts = [
        f"=== FINANCIAL SUMMARY ({summary.period_start} to {summary.period_end}) ===",
        f"Total Income: ₹{summary.total_income:,.0f}",
        f"Total Expenses: ₹{summary.total_expenses:,.0f}",
        f"Net Savings: ₹{summary.net_savings:,.0f}",
        f"Savings Rate: {summary.savings_rate_pct:.1f}%",
        "",
        "=== TOP SPENDING CATEGORIES ===",
    ]

    for cat in summary.top_categories:
        context_parts.append(
            f"• {cat['category']}: ₹{cat['amount']:,.0f} ({cat['pct']:.1f}% of expenses)"
        )

    if summary.insights:
        context_parts.append("\n=== KEY INSIGHTS ===")
        for insight in summary.insights:
            context_parts.append(
                f"• [{insight.impact.upper()}] {insight.title}: {insight.description}"
            )
            if insight.action:
                context_parts.append(f"  → Action: {insight.action}")

    if summary.goal_correlations:
        context_parts.append("\n=== INVESTMENT GOAL ANALYSIS ===")
        for corr in summary.goal_correlations:
            context_parts.append(
                f"• {corr.goal.name} [{corr.status.value.upper()}]: "
                f"Planned ₹{corr.goal.monthly_contribution:,.0f}/month, "
                f"Recommended ₹{corr.recommended_contribution:,.0f}/month, "
                f"Gap: ₹{corr.gap:,.0f}"
            )
            for ins in corr.insights:
                context_parts.append(f"  - {ins}")
            if corr.months_to_goal:
                context_parts.append(f"  → Est. {corr.months_to_goal} months to goal")

    return {**state, "retrieved_context": "\n".join(context_parts), "summary": summary}


def generate_answer_node(state: GraphState) -> GraphState:
    """Generate the final conversational answer using retrieved context."""
    llm = get_reasoning_llm()
    query = state["current_query"]
    context = state["retrieved_context"]

    # Build conversation history
    history = state.get("messages", [])

    messages = [SystemMessage(content=FINANCE_SYSTEM)]

    # Add recent history (last 6 turns)
    for msg in history[-6:]:
        if msg["role"] == "user":
            messages.append(HumanMessage(content=msg["content"]))
        else:
            messages.append(AIMessage(content=msg["content"]))

    # Current query with context
    messages.append(
        HumanMessage(
            content=f"""
Context from your financial data:
{context}

User question: {query}

Please provide a helpful, specific answer grounded in the data above.
Use ₹ for amounts. Be actionable and encouraging."""
        )
    )

    response = llm.invoke(messages)
    answer = response.content

    # Store insight in vector store for future retrieval
    if len(answer) > 100:
        try:
            store = FinanceVectorStore()
            store.index_insight(
                f"Q: {query}\nA: {answer[:500]}",
                metadata={"type": "qa_pair"},
            )
        except Exception:
            pass  # Non-critical

    return {
        **state,
        "final_answer": answer,
        "messages": [
            *state.get("messages", []),
            {"role": "user", "content": query},
            {"role": "assistant", "content": answer},
        ],
    }


def route_condition(state: GraphState) -> str:
    return state.get("route", "retrieval")


# ─── Build Graph ──────────────────────────────────────────────────────────────


def build_finance_graph() -> Any:
    """Build and compile the LangGraph finance agent."""
    graph = StateGraph(GraphState)

    graph.add_node("route_query", route_query)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("generate_answer", generate_answer_node)

    graph.set_entry_point("route_query")

    graph.add_conditional_edges(
        "route_query",
        route_condition,
        {
            "retrieval": "retrieval",
            "analysis": "analysis",
        },
    )

    graph.add_edge("retrieval", "generate_answer")
    graph.add_edge("analysis", "generate_answer")
    graph.add_edge("generate_answer", END)

    return graph.compile()


# ─── Agent Class ──────────────────────────────────────────────────────────────


class FinanceCoachAgent:
    """
    High-level interface to the finance coach.
    Manages state across multiple turns in a session.
    """

    def __init__(self) -> None:
        self._graph = build_finance_graph()
        self._state: GraphState = {
            "messages": [],
            "transactions": [],
            "goals": [],
            "summary": None,
            "current_query": "",
            "retrieved_context": "",
            "final_answer": "",
            "error": None,
            "route": "retrieval",
        }
        self._store = FinanceVectorStore()
        logger.info("FinanceCoachAgent initialised")

    def load_transactions(self, transactions: list[Transaction]) -> None:
        """Load transactions into agent state and index in vector store."""
        self._state["transactions"].extend(transactions)
        self._store.index_transactions(transactions)
        logger.info("Loaded %d transactions into agent", len(transactions))

    def load_goals(self, goals: list[InvestmentGoal]) -> None:
        """Load investment goals into agent state and index."""
        self._state["goals"].extend(goals)
        self._store.index_goals(goals)
        logger.info("Loaded %d investment goals into agent", len(goals))

    def chat(self, user_message: str) -> str:
        """Synchronous single-turn Q&A."""
        state = {
            **self._state,
            "current_query": user_message,
            "retrieved_context": "",
            "final_answer": "",
            "error": None,
        }
        result = self._graph.invoke(state)

        # Persist message history
        self._state["messages"] = result.get("messages", [])

        # Persist summary if generated
        if result.get("summary"):
            self._state["summary"] = result["summary"]

        return result.get("final_answer", "I couldn't generate an answer. Please try again.")

    async def stream_chat(self, user_message: str) -> AsyncGenerator[str, None]:
        """Async streaming chat response."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        llm = get_reasoning_llm()

        # Run the graph synchronously first to get context
        state = {
            **self._state,
            "current_query": user_message,
            "retrieved_context": "",
            "final_answer": "",
            "error": None,
        }

        # Run retrieval/analysis node only (not generation)
        route = route_query(state)
        if route["route"] == "analysis":
            state_with_context = analysis_node(route)
        else:
            state_with_context = retrieval_node(route)

        context = state_with_context["retrieved_context"]

        # Stream the generation
        history = self._state.get("messages", [])
        messages = [SystemMessage(content=FINANCE_SYSTEM)]
        for msg in history[-6:]:
            if msg["role"] == "user":
                messages.append(HumanMessage(content=msg["content"]))
            else:
                messages.append(AIMessage(content=msg["content"]))

        messages.append(
            HumanMessage(
                content=f"""
Context from your financial data:
{context}

User question: {user_message}

Please provide a helpful, specific answer grounded in the data above."""
            )
        )

        full_answer = ""
        async for chunk in llm.astream(messages):
            token = chunk.content
            full_answer += token
            yield token

        # Update state
        self._state["messages"] = [
            *history,
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": full_answer},
        ]

    def reset_session(self) -> None:
        """Clear conversation history but keep loaded data."""
        self._state["messages"] = []
        logger.info("Session reset")

    def clear_all(self) -> None:
        """Full reset including transactions and goals."""
        self._state = {
            "messages": [],
            "transactions": [],
            "goals": [],
            "summary": None,
            "current_query": "",
            "retrieved_context": "",
            "final_answer": "",
            "error": None,
            "route": "retrieval",
        }
        self._store.clear_all()
