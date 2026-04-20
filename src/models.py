"""
src/models.py
─────────────────────────────────────────────────────────────────────────────
All Pydantic v2 models for the finance coach agent.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────────────

class TransactionCategory(str, Enum):
    FOOD_DINING = "food_dining"
    GROCERIES = "groceries"
    TRANSPORT = "transport"
    FUEL = "fuel"
    UTILITIES = "utilities"
    RENT_EMI = "rent_emi"
    HEALTHCARE = "healthcare"
    ENTERTAINMENT = "entertainment"
    SHOPPING = "shopping"
    TRAVEL = "travel"
    EDUCATION = "education"
    INVESTMENTS = "investments"
    INSURANCE = "insurance"
    SUBSCRIPTIONS = "subscriptions"
    SALARY_INCOME = "salary_income"
    OTHER_INCOME = "other_income"
    TRANSFERS = "transfers"
    FEES_CHARGES = "fees_charges"
    OTHER = "other"


class TransactionType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class GoalType(str, Enum):
    EMERGENCY_FUND = "emergency_fund"
    RETIREMENT = "retirement"
    HOME_PURCHASE = "home_purchase"
    EDUCATION = "education"
    TRAVEL = "travel"
    VEHICLE = "vehicle"
    BUSINESS = "business"
    WEALTH_BUILDING = "wealth_building"
    DEBT_PAYOFF = "debt_payoff"
    OTHER = "other"


class GoalStatus(str, Enum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    BEHIND = "behind"
    ACHIEVED = "achieved"
    NOT_STARTED = "not_started"


# ─── Transaction ──────────────────────────────────────────────────────────────

class Transaction(BaseModel):
    id: str
    date: date
    description: str
    amount: float                          # always positive
    transaction_type: TransactionType
    currency: str = "INR"                  # ISO 4217 code
    category: TransactionCategory = TransactionCategory.OTHER
    subcategory: str | None = None
    merchant: str | None = None
    account: str | None = None
    source_file: str | None = None
    raw_text: str | None = None            # original unparsed row
    confidence: float = 1.0               # LLM categorisation confidence

    @field_validator("amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        return abs(v)

    @property
    def signed_amount(self) -> float:
        return -self.amount if self.transaction_type == TransactionType.DEBIT else self.amount


class TransactionBatch(BaseModel):
    transactions: list[Transaction]
    source_name: str
    source_type: str                       # "csv" | "pdf" | "gmail"
    account_holder: str | None = None
    parsed_at: datetime = Field(default_factory=datetime.now)

    @property
    def total_debits(self) -> float:
        return sum(t.amount for t in self.transactions if t.transaction_type == TransactionType.DEBIT)

    @property
    def total_credits(self) -> float:
        return sum(t.amount for t in self.transactions if t.transaction_type == TransactionType.CREDIT)

    @property
    def net_cashflow(self) -> float:
        return self.total_credits - self.total_debits


# ─── Investment Goal ──────────────────────────────────────────────────────────

class InvestmentGoal(BaseModel):
    id: str
    name: str
    goal_type: GoalType
    target_amount: float
    current_amount: float = 0.0
    monthly_contribution: float = 0.0     # user's planned monthly investment
    target_date: date | None = None
    priority: int = 1                     # 1 = highest priority
    notes: str | None = None

    @property
    def remaining_amount(self) -> float:
        return max(0.0, self.target_amount - self.current_amount)

    @property
    def progress_pct(self) -> float:
        if self.target_amount == 0:
            return 0.0
        return min(100.0, (self.current_amount / self.target_amount) * 100)


# ─── Budget ───────────────────────────────────────────────────────────────────

class CategoryBudget(BaseModel):
    category: TransactionCategory
    monthly_limit: float
    actual_spent: float = 0.0

    @property
    def remaining(self) -> float:
        return self.monthly_limit - self.actual_spent

    @property
    def utilisation_pct(self) -> float:
        if self.monthly_limit == 0:
            return 0.0
        return (self.actual_spent / self.monthly_limit) * 100

    @property
    def is_over_budget(self) -> bool:
        return self.actual_spent > self.monthly_limit


# ─── Analysis Results ─────────────────────────────────────────────────────────

class SpendingInsight(BaseModel):
    title: str
    description: str
    impact: str                            # "high" | "medium" | "low"
    action: str | None = None             # recommended action
    amount_involved: float | None = None


class GoalCorrelation(BaseModel):
    goal: InvestmentGoal
    status: GoalStatus
    monthly_surplus_available: float      # what's left after expenses
    recommended_contribution: float
    gap: float                            # difference vs planned contribution
    insights: list[str]
    months_to_goal: int | None = None


class FinancialSummary(BaseModel):
    period_start: date
    period_end: date
    total_income: float
    total_expenses: float
    net_savings: float
    savings_rate_pct: float
    top_categories: list[dict[str, Any]]
    insights: list[SpendingInsight]
    goal_correlations: list[GoalCorrelation]
    generated_at: datetime = Field(default_factory=datetime.now)


# ─── Agent State (LangGraph) ──────────────────────────────────────────────────

class AgentState(BaseModel):
    """Shared state across all LangGraph nodes."""
    messages: list[dict[str, str]] = Field(default_factory=list)
    transactions: list[Transaction] = Field(default_factory=list)
    goals: list[InvestmentGoal] = Field(default_factory=list)
    summary: FinancialSummary | None = None
    current_query: str = ""
    retrieved_context: str = ""
    final_answer: str = ""
    error: str | None = None
    ingestion_sources: list[str] = Field(default_factory=list)