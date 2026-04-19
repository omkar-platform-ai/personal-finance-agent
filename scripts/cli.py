"""
scripts/cli.py
─────────────────────────────────────────────────────────────────────────────
Interactive CLI for the Personal Finance Coach Agent.

Runs entirely in-process — no API server required. Uses the same
``FinanceCoachAgent`` instance the FastAPI app would, so loaded data and
conversation history persist for the lifetime of the session.

Usage:
    uv run python scripts/cli.py                       # interactive REPL
    uv run python scripts/cli.py --csv data/samples/sample_bank_statement.csv \\
                                 --goals data/samples/investment_goals.csv
    uv run python scripts/cli.py --ask "Am I on track for my emergency fund?"

Inside the REPL, slash commands manage data and any other input is sent to
the agent. Type /help for the full command list.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make `src` importable when run as a plain script (not as a package).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from src.agents.finance_agent import FinanceCoachAgent
from src.ingestion.document_loader import (
    CSVIngester,
    InvestmentGoalsLoader,
    TransactionCategoriser,
)

console = Console()

HELP_TEXT = """
[bold]Slash commands[/bold]
  /ingest <path>     Load a bank statement CSV (auto-categorised)
  /goals <path>      Load an investment goals CSV
  /summary           Show how much data is currently loaded
  /reset             Clear all transactions, goals, and chat history
  /help              Show this help
  /quit              Exit the CLI

Anything else you type is sent to the finance coach agent.
"""


# ─── Slash-command handlers ───────────────────────────────────────────────────

def _ingest_csv(agent: FinanceCoachAgent, path: Path, account_name: str | None = None) -> None:
    if not path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        return
    with console.status(f"Ingesting {path.name}..."):
        batch = CSVIngester().ingest(path, account_name)
        txs = TransactionCategoriser().categorise(batch.transactions)
        agent.load_transactions(txs)
    console.print(f"[green]✓[/green] Loaded [bold]{len(txs)}[/bold] transactions from {path.name}")


def _ingest_goals(agent: FinanceCoachAgent, path: Path) -> None:
    if not path.exists():
        console.print(f"[red]File not found:[/red] {path}")
        return
    with console.status(f"Loading goals from {path.name}..."):
        goals = InvestmentGoalsLoader().load(path)
        agent.load_goals(goals)
    console.print(f"[green]✓[/green] Loaded [bold]{len(goals)}[/bold] investment goals")


def _print_summary(agent: FinanceCoachAgent) -> None:
    state = agent._state
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("k", style="dim")
    table.add_column("v", style="bold")
    table.add_row("Transactions", str(len(state.get("transactions", []))))
    table.add_row("Goals", str(len(state.get("goals", []))))
    table.add_row("Conversation turns", str(len(state.get("messages", [])) // 2))
    console.print(Panel(table, title="Loaded data", border_style="cyan", expand=False))


def _ask(agent: FinanceCoachAgent, question: str) -> None:
    with console.status("Thinking..."):
        try:
            answer = agent.chat(question)
        except Exception as exc:
            console.print(f"[red]Agent error:[/red] {exc}")
            return
    console.print(Panel(Markdown(answer), border_style="green", padding=(1, 2)))


# ─── REPL ─────────────────────────────────────────────────────────────────────

def repl(agent: FinanceCoachAgent) -> None:
    console.print(Panel.fit(
        "[bold green]Personal Finance Coach — CLI[/bold green]\n"
        "Type [bold]/help[/bold] for commands, [bold]/quit[/bold] to exit.",
        border_style="green",
    ))

    while True:
        try:
            raw = console.input("\n[bold cyan]you[/bold cyan] > ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]bye[/dim]")
            return

        if not raw:
            continue

        if raw in {"/quit", "/exit", "/q"}:
            console.print("[dim]bye[/dim]")
            return
        if raw in {"/help", "/h", "?"}:
            console.print(HELP_TEXT)
            continue
        if raw == "/summary":
            _print_summary(agent)
            continue
        if raw == "/reset":
            agent.clear_all()
            console.print("[yellow]All loaded data cleared.[/yellow]")
            continue
        if raw.startswith("/ingest"):
            parts = raw.split(maxsplit=1)
            if len(parts) < 2:
                console.print("[red]Usage:[/red] /ingest <path-to-csv>")
                continue
            _ingest_csv(agent, Path(parts[1].strip()))
            continue
        if raw.startswith("/goals"):
            parts = raw.split(maxsplit=1)
            if len(parts) < 2:
                console.print("[red]Usage:[/red] /goals <path-to-csv>")
                continue
            _ingest_goals(agent, Path(parts[1].strip()))
            continue
        if raw.startswith("/"):
            console.print(f"[red]Unknown command:[/red] {raw.split()[0]} — type /help")
            continue

        _ask(agent, raw)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="finance-cli",
        description="Interactive CLI for the Personal Finance Coach Agent.",
    )
    parser.add_argument(
        "--csv", "-c", type=Path,
        help="Bank statement CSV to ingest before starting.",
    )
    parser.add_argument(
        "--goals", "-g", type=Path,
        help="Investment goals CSV to ingest before starting.",
    )
    parser.add_argument(
        "--account", "-a", default=None,
        help="Account label to attach to ingested transactions (e.g. 'HDFC Savings').",
    )
    parser.add_argument(
        "--ask", "-q",
        help="Ask a single question and exit (non-interactive).",
    )
    args = parser.parse_args()

    agent = FinanceCoachAgent()

    if args.csv:
        _ingest_csv(agent, args.csv, args.account)
    if args.goals:
        _ingest_goals(agent, args.goals)

    if args.ask:
        _ask(agent, args.ask)
        return 0

    repl(agent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
