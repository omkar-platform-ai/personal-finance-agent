"""
src/agents/analyser.py
─────────────────────────────────────────────────────────────────────────────
Financial analysis engine:
  • Spending aggregation by category / month
  • Budget tracking
  • Investment goal correlation and gap analysis
  • Insight generation (LLM-powered)
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from src.llm import get_reasoning_llm
from src.models import (
    CategoryBudget,
    FinancialSummary,
    GoalCorrelation,
    GoalStatus,
    InvestmentGoal,
    SpendingInsight,
    Transaction,
    TransactionCategory,
    TransactionType,
)

logger = logging.getLogger(__name__)

INSIGHT_SYSTEM = """You are a personal finance coach analysing a user's spending data.
Generate 3-5 specific, actionable insights based on the spending data provided.
Each insight must be grounded in the actual numbers.

Return a JSON array of objects, each with:
  - "title": short (5-8 word) insight title
  - "description": 2-3 sentence explanation with specific numbers
  - "impact": "high" | "medium" | "low"
  - "action": concrete 1-sentence recommendation
  - "amount_involved": float (the ₹ amount this insight relates to, or null)

Return ONLY the JSON array."""

GOAL_CORRELATION_SYSTEM = """You are a financial planning expert.
Analyse whether the user's spending patterns support their investment goals.
For each goal, provide:
  - Whether they can afford the planned monthly contribution
  - What spending categories are eating into goal contributions  
  - A specific, actionable recommendation

Data provided:
  Monthly income: ₹{income}
  Monthly expenses: ₹{expenses}
  Current monthly surplus: ₹{surplus}
  Total planned monthly investments: ₹{planned_investments}

Return a JSON array of insights (one per goal), each with:
  - "goal_name": the goal name
  - "status": "on_track" | "at_risk" | "behind" | "not_started"
  - "recommended_contribution": the monthly amount they should actually invest
  - "gap": planned - recommended (negative means shortfall)
  - "insights": list of 2-3 specific insight strings
  - "months_to_goal": integer estimate or null

Return ONLY the JSON array."""


class FinancialAnalyser:
    """Core analysis engine. Stateless — pass in data, get results back."""

    def __init__(self) -> None:
        self._llm = get_reasoning_llm()

    # ── Aggregation ───────────────────────────────────────────────────────────

    def aggregate_by_category(
        self,
        transactions: list[Transaction],
        tx_type: TransactionType = TransactionType.DEBIT,
    ) -> dict[str, float]:
        """Sum transaction amounts by category."""
        totals: dict[str, float] = defaultdict(float)
        for tx in transactions:
            if tx.transaction_type == tx_type:
                totals[tx.category.value] += tx.amount
        return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))

    def aggregate_by_month(
        self,
        transactions: list[Transaction],
    ) -> dict[str, dict[str, float]]:
        """
        Returns {
          "2024-03": {"income": X, "expenses": Y, "net": Z},
          ...
        }
        """
        monthly: dict[str, dict[str, float]] = defaultdict(
            lambda: {"income": 0.0, "expenses": 0.0, "net": 0.0}
        )
        for tx in transactions:
            key = f"{tx.date.year}-{tx.date.month:02d}"
            if tx.transaction_type == TransactionType.CREDIT:
                monthly[key]["income"] += tx.amount
            else:
                monthly[key]["expenses"] += tx.amount
        for key in monthly:
            monthly[key]["net"] = monthly[key]["income"] - monthly[key]["expenses"]
        return dict(sorted(monthly.items()))

    def get_date_range(self, transactions: list[Transaction]) -> tuple[date, date]:
        if not transactions:
            today = date.today()
            return today - timedelta(days=30), today
        dates = [tx.date for tx in transactions]
        return min(dates), max(dates)

    def compute_savings_rate(self, income: float, expenses: float) -> float:
        if income <= 0:
            return 0.0
        return max(0.0, ((income - expenses) / income) * 100)

    def detect_recurring_subscriptions(
        self,
        transactions: list[Transaction],
    ) -> list[dict[str, Any]]:
        """Find likely recurring charges (same merchant, similar amount, monthly)."""
        from collections import Counter

        merchant_months: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
        for tx in transactions:
            if tx.transaction_type == TransactionType.DEBIT and tx.merchant:
                merchant_months[tx.merchant].append(
                    (tx.date.year, tx.date.month, tx.amount)
                )

        recurring = []
        for merchant, entries in merchant_months.items():
            if len(entries) >= 2:
                amounts = [e[2] for e in entries]
                avg = sum(amounts) / len(amounts)
                variance = max(abs(a - avg) / avg for a in amounts) if avg > 0 else 1
                if variance < 0.1:  # within 10% = likely subscription
                    recurring.append({
                        "merchant": merchant,
                        "monthly_amount": round(avg, 2),
                        "annual_cost": round(avg * 12, 2),
                        "occurrences": len(entries),
                    })
        return sorted(recurring, key=lambda x: x["monthly_amount"], reverse=True)

    # ── Budget tracking ───────────────────────────────────────────────────────

    def compute_budget_status(
        self,
        transactions: list[Transaction],
        budgets: list[CategoryBudget] | None = None,
    ) -> list[CategoryBudget]:
        """
        If budgets provided: check actuals vs limits.
        If not: auto-generate reasonable budget limits based on income.
        """
        category_spend = self.aggregate_by_category(transactions)

        if not budgets:
            # Auto-generate: use 80% of average spend as limit (encourages savings)
            budgets = [
                CategoryBudget(
                    category=TransactionCategory(cat),
                    monthly_limit=round(amount * 0.9, 2),
                    actual_spent=amount,
                )
                for cat, amount in category_spend.items()
                if cat not in (
                    TransactionCategory.SALARY_INCOME.value,
                    TransactionCategory.OTHER_INCOME.value,
                    TransactionCategory.INVESTMENTS.value,
                )
            ]
        else:
            for b in budgets:
                b.actual_spent = category_spend.get(b.category.value, 0.0)

        return budgets

    # ── Goal correlation ──────────────────────────────────────────────────────

    def correlate_goals(
        self,
        transactions: list[Transaction],
        goals: list[InvestmentGoal],
    ) -> list[GoalCorrelation]:
        """
        Determine if spending patterns support investment goals.
        Uses both rule-based logic and LLM for qualitative insights.
        """
        if not goals:
            return []

        monthly = self.aggregate_by_month(transactions)
        if not monthly:
            return []

        # Use last 3 months average
        recent_months = list(monthly.values())[-3:]
        avg_income = sum(m["income"] for m in recent_months) / len(recent_months)
        avg_expenses = sum(m["expenses"] for m in recent_months) / len(recent_months)
        monthly_surplus = avg_income - avg_expenses

        total_planned = sum(g.monthly_contribution for g in goals)

        # LLM-powered qualitative analysis
        llm_insights = self._llm_goal_analysis(
            goals, avg_income, avg_expenses, monthly_surplus, total_planned
        )
        llm_map = {item["goal_name"]: item for item in llm_insights}

        correlations: list[GoalCorrelation] = []
        surplus_remaining = monthly_surplus

        for goal in sorted(goals, key=lambda g: g.priority):
            llm_data = llm_map.get(goal.name, {})

            # Rule-based: can we actually afford this contribution?
            recommended = min(goal.monthly_contribution, max(0.0, surplus_remaining))
            surplus_remaining -= recommended
            gap = goal.monthly_contribution - recommended

            # Determine status
            if goal.current_amount >= goal.target_amount:
                status = GoalStatus.ACHIEVED
            elif recommended >= goal.monthly_contribution * 0.9:
                status = GoalStatus.ON_TRACK
            elif recommended >= goal.monthly_contribution * 0.5:
                status = GoalStatus.AT_RISK
            elif recommended > 0:
                status = GoalStatus.BEHIND
            else:
                status = GoalStatus.NOT_STARTED

            # Override with LLM status if available
            try:
                if llm_data.get("status"):
                    status = GoalStatus(llm_data["status"])
            except ValueError:
                pass

            # Months to goal estimate
            months_to_goal = None
            if recommended > 0 and goal.remaining_amount > 0:
                months_to_goal = int(goal.remaining_amount / recommended)

            correlations.append(GoalCorrelation(
                goal=goal,
                status=status,
                monthly_surplus_available=monthly_surplus,
                recommended_contribution=round(recommended, 2),
                gap=round(gap, 2),
                insights=llm_data.get("insights", []),
                months_to_goal=months_to_goal,
            ))

        return correlations

    def _llm_goal_analysis(
        self,
        goals: list[InvestmentGoal],
        income: float,
        expenses: float,
        surplus: float,
        planned_investments: float,
    ) -> list[dict[str, Any]]:
        goals_summary = [
            {
                "name": g.name,
                "type": g.goal_type.value,
                "target": g.target_amount,
                "current": g.current_amount,
                "monthly_planned": g.monthly_contribution,
                "priority": g.priority,
            }
            for g in goals
        ]
        prompt = GOAL_CORRELATION_SYSTEM.format(
            income=f"{income:,.0f}",
            expenses=f"{expenses:,.0f}",
            surplus=f"{surplus:,.0f}",
            planned_investments=f"{planned_investments:,.0f}",
        )
        try:
            response = self._llm.invoke([
                SystemMessage(content=prompt),
                HumanMessage(content=json.dumps(goals_summary, ensure_ascii=False)),
            ])
            raw = response.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception as exc:
            logger.error("LLM goal analysis failed: %s", exc)
            return []

    # ── Full summary ──────────────────────────────────────────────────────────

    def generate_summary(
        self,
        transactions: list[Transaction],
        goals: list[InvestmentGoal],
    ) -> FinancialSummary:
        """Generate a complete financial summary with insights and goal correlations."""
        period_start, period_end = self.get_date_range(transactions)
        debits = [t for t in transactions if t.transaction_type == TransactionType.DEBIT]
        credits = [t for t in transactions if t.transaction_type == TransactionType.CREDIT]

        total_income = sum(t.amount for t in credits)
        total_expenses = sum(t.amount for t in debits)
        net_savings = total_income - total_expenses
        savings_rate = self.compute_savings_rate(total_income, total_expenses)

        category_totals = self.aggregate_by_category(transactions)
        top_categories = [
            {"category": cat, "amount": amt, "pct": (amt / total_expenses * 100) if total_expenses > 0 else 0}
            for cat, amt in list(category_totals.items())[:8]
        ]

        insights = self._generate_insights(transactions, category_totals, total_income, total_expenses)
        goal_correlations = self.correlate_goals(transactions, goals)

        return FinancialSummary(
            period_start=period_start,
            period_end=period_end,
            total_income=round(total_income, 2),
            total_expenses=round(total_expenses, 2),
            net_savings=round(net_savings, 2),
            savings_rate_pct=round(savings_rate, 1),
            top_categories=top_categories,
            insights=insights,
            goal_correlations=goal_correlations,
        )

    def _generate_insights(
        self,
        transactions: list[Transaction],
        category_totals: dict[str, float],
        total_income: float,
        total_expenses: float,
    ) -> list[SpendingInsight]:
        subscriptions = self.detect_recurring_subscriptions(transactions)
        spending_data = {
            "category_totals": category_totals,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "savings_rate_pct": self.compute_savings_rate(total_income, total_expenses),
            "recurring_subscriptions": subscriptions[:10],
            "num_transactions": len(transactions),
        }
        try:
            response = self._llm.invoke([
                SystemMessage(content=INSIGHT_SYSTEM),
                HumanMessage(content=json.dumps(spending_data, ensure_ascii=False)),
            ])
            raw = response.content.strip().replace("```json", "").replace("```", "")
            parsed = json.loads(raw)
            return [
                SpendingInsight(
                    title=i.get("title", ""),
                    description=i.get("description", ""),
                    impact=i.get("impact", "medium"),
                    action=i.get("action"),
                    amount_involved=i.get("amount_involved"),
                )
                for i in parsed
            ]
        except Exception as exc:
            logger.error("Insight generation failed: %s", exc)
            return []