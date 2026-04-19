"""
scripts/demo.py
─────────────────────────────────────────────────────────────────────────────
End-to-end demo of the finance coach agent.
Runs without a server — directly calls agent code.

Usage:
    uv run python scripts/demo.py
    # or
    python scripts/demo.py
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown

from src.agents.finance_agent import FinanceCoachAgent
from src.ingestion.document_loader import (
    CSVIngester,
    InvestmentGoalsLoader,
    TransactionCategoriser,
)

console = Console()

DEMO_QUESTIONS = [
    "Give me a complete overview of my finances",
    "What are my top 3 spending categories and how do they impact my investment goals?",
    "Am I on track for my emergency fund?",
    "Which subscriptions am I paying that I should consider cancelling?",
    "How much can I realistically invest each month given my current spending?",
    "What changes should I make to hit my home down payment goal by 2028?",
]


def main():
    console.print(Panel.fit(
        "[bold green]Personal Finance Coach Agent — Demo[/bold green]\n"
        "Loading sample data and running Q&A...",
        border_style="green"
    ))

    # ── 1. Ingest transactions ─────────────────────────────────────────────
    console.print("\n[cyan]Step 1: Ingesting bank statement CSV...[/cyan]")
    ingester = CSVIngester()
    batch = ingester.ingest("data/samples/sample_bank_statement.csv", account_name="HDFC Savings")

    console.print(f"  ✓ Parsed [bold]{len(batch.transactions)}[/bold] transactions")

    console.print("[cyan]Step 2: Categorising transactions with LLM...[/cyan]")
    categoriser = TransactionCategoriser()
    transactions = categoriser.categorise(batch.transactions)

    # Show categorisation table
    table = Table(title="Sample Categorised Transactions", show_header=True)
    table.add_column("Date", style="dim")
    table.add_column("Description")
    table.add_column("Amount", justify="right", style="red")
    table.add_column("Category", style="cyan")
    table.add_column("Merchant")

    for tx in transactions[:10]:
        table.add_row(
            str(tx.date),
            tx.description[:40],
            f"₹{tx.amount:,.0f}",
            tx.category.value,
            tx.merchant or "-",
        )
    console.print(table)

    # ── 2. Load investment goals ────────────────────────────────────────────
    console.print("\n[cyan]Step 3: Loading investment goals...[/cyan]")
    goals_loader = InvestmentGoalsLoader()
    goals = goals_loader.load("data/samples/investment_goals.csv")

    goals_table = Table(title="Investment Goals", show_header=True)
    goals_table.add_column("Goal", style="bold")
    goals_table.add_column("Target", justify="right")
    goals_table.add_column("Current", justify="right")
    goals_table.add_column("Monthly", justify="right")
    goals_table.add_column("Progress", justify="right")

    for g in goals:
        goals_table.add_row(
            g.name,
            f"₹{g.target_amount:,.0f}",
            f"₹{g.current_amount:,.0f}",
            f"₹{g.monthly_contribution:,.0f}",
            f"{g.progress_pct:.1f}%",
        )
    console.print(goals_table)

    # ── 3. Initialise agent ─────────────────────────────────────────────────
    console.print("\n[cyan]Step 4: Initialising Finance Coach Agent...[/cyan]")
    agent = FinanceCoachAgent()
    agent.load_transactions(transactions)
    agent.load_goals(goals)
    console.print("  ✓ Agent ready")

    # ── 4. Q&A Demo ─────────────────────────────────────────────────────────
    console.print("\n" + "="*60)
    console.print("[bold yellow]CONVERSATIONAL Q&A DEMO[/bold yellow]")
    console.print("="*60)

    for question in DEMO_QUESTIONS:
        console.print(f"\n[bold blue]Q: {question}[/bold blue]")
        answer = agent.chat(question)
        console.print(Panel(Markdown(answer), border_style="green", padding=(1, 2)))
        console.print()

    # ── 5. Interactive mode ─────────────────────────────────────────────────
    console.print("\n[bold yellow]Enter your own questions (type 'quit' to exit):[/bold yellow]")
    while True:
        try:
            user_input = input("\nYou: ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                break
            if not user_input:
                continue
            answer = agent.chat(user_input)
            console.print(f"\n[green]Coach:[/green] {answer}")
        except (KeyboardInterrupt, EOFError):
            break

    console.print("\n[dim]Demo complete.[/dim]")


if __name__ == "__main__":
    main()