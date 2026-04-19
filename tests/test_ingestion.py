"""
tests/test_ingestion.py
─────────────────────────────────────────────────────────────────────────────
Tests for CSV/PDF ingestion, categorisation, and goal loading.
Run with: pytest tests/ -v
"""
from __future__ import annotations

import os
import csv
import uuid
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

# Make sure src is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import (
    Transaction,
    TransactionBatch,
    TransactionCategory,
    TransactionType,
    InvestmentGoal,
    GoalType,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Write a minimal CSV statement to a temp file."""
    p = tmp_path / "test_statement.csv"
    rows = [
        ["Date", "Description", "Debit", "Credit", "Balance"],
        ["01/03/2025", "Salary Credit", "", "95000", "95000"],
        ["02/03/2025", "Swiggy Order", "450", "", "94550"],
        ["03/03/2025", "BigBasket", "3200", "", "91350"],
        ["05/03/2025", "Netflix", "649", "", "90701"],
        ["15/03/2025", "Rent Payment", "22000", "", "68701"],
    ]
    with open(p, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    return p


@pytest.fixture
def sample_goals_csv(tmp_path: Path) -> Path:
    p = tmp_path / "goals.csv"
    rows = [
        ["name", "goal_type", "target_amount", "current_amount", "monthly_contribution", "target_date", "priority"],
        ["Emergency Fund", "emergency_fund", "300000", "85000", "10000", "2025-12-31", "1"],
        ["Home Purchase", "home_purchase", "2500000", "150000", "15000", "2028-06-30", "2"],
    ]
    with open(p, "w", newline="") as f:
        csv.writer(f).writerows(rows)
    return p


@pytest.fixture
def mock_transactions() -> list[Transaction]:
    return [
        Transaction(
            id=str(uuid.uuid4()),
            date=date(2025, 3, 1),
            description="Salary Credit",
            amount=95000.0,
            transaction_type=TransactionType.CREDIT,
            category=TransactionCategory.SALARY_INCOME,
        ),
        Transaction(
            id=str(uuid.uuid4()),
            date=date(2025, 3, 2),
            description="Swiggy Order 8834729",
            amount=450.0,
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.FOOD_DINING,
            merchant="Swiggy",
        ),
        Transaction(
            id=str(uuid.uuid4()),
            date=date(2025, 3, 3),
            description="BigBasket Groceries",
            amount=3200.0,
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.GROCERIES,
            merchant="BigBasket",
        ),
        Transaction(
            id=str(uuid.uuid4()),
            date=date(2025, 3, 5),
            description="Netflix Subscription",
            amount=649.0,
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.SUBSCRIPTIONS,
            merchant="Netflix",
        ),
        Transaction(
            id=str(uuid.uuid4()),
            date=date(2025, 3, 15),
            description="Rent Payment",
            amount=22000.0,
            transaction_type=TransactionType.DEBIT,
            category=TransactionCategory.RENT_EMI,
        ),
    ]


@pytest.fixture
def mock_goals() -> list[InvestmentGoal]:
    return [
        InvestmentGoal(
            id=str(uuid.uuid4()),
            name="Emergency Fund",
            goal_type=GoalType.EMERGENCY_FUND,
            target_amount=300000.0,
            current_amount=85000.0,
            monthly_contribution=10000.0,
            priority=1,
        ),
        InvestmentGoal(
            id=str(uuid.uuid4()),
            name="Home Down Payment",
            goal_type=GoalType.HOME_PURCHASE,
            target_amount=2500000.0,
            current_amount=150000.0,
            monthly_contribution=15000.0,
            priority=2,
        ),
    ]


# ─── Model Tests ──────────────────────────────────────────────────────────────

class TestTransactionModel:
    def test_amount_always_positive(self):
        tx = Transaction(
            id="1", date=date.today(), description="test",
            amount=-500.0, transaction_type=TransactionType.DEBIT,
        )
        assert tx.amount == 500.0

    def test_signed_amount_debit_negative(self):
        tx = Transaction(
            id="1", date=date.today(), description="test",
            amount=500.0, transaction_type=TransactionType.DEBIT,
        )
        assert tx.signed_amount == -500.0

    def test_signed_amount_credit_positive(self):
        tx = Transaction(
            id="1", date=date.today(), description="salary",
            amount=95000.0, transaction_type=TransactionType.CREDIT,
        )
        assert tx.signed_amount == 95000.0

    def test_default_category_is_other(self):
        tx = Transaction(
            id="1", date=date.today(), description="mystery",
            amount=100.0, transaction_type=TransactionType.DEBIT,
        )
        assert tx.category == TransactionCategory.OTHER


class TestTransactionBatch:
    def test_total_debits(self, mock_transactions):
        batch = TransactionBatch(
            transactions=mock_transactions,
            source_name="test.csv",
            source_type="csv",
        )
        expected = 450 + 3200 + 649 + 22000
        assert batch.total_debits == expected

    def test_total_credits(self, mock_transactions):
        batch = TransactionBatch(
            transactions=mock_transactions,
            source_name="test.csv",
            source_type="csv",
        )
        assert batch.total_credits == 95000.0

    def test_net_cashflow(self, mock_transactions):
        batch = TransactionBatch(
            transactions=mock_transactions,
            source_name="test.csv",
            source_type="csv",
        )
        assert batch.net_cashflow == 95000 - (450 + 3200 + 649 + 22000)


class TestInvestmentGoal:
    def test_remaining_amount(self, mock_goals):
        goal = mock_goals[0]  # Emergency Fund
        assert goal.remaining_amount == 300000 - 85000

    def test_progress_pct(self, mock_goals):
        goal = mock_goals[0]
        expected = (85000 / 300000) * 100
        assert abs(goal.progress_pct - expected) < 0.01

    def test_progress_pct_zero_target(self):
        goal = InvestmentGoal(
            id="1", name="test", goal_type=GoalType.OTHER,
            target_amount=0.0, current_amount=0.0, monthly_contribution=0.0,
        )
        assert goal.progress_pct == 0.0

    def test_achieved_goal_capped_at_100(self):
        goal = InvestmentGoal(
            id="1", name="test", goal_type=GoalType.TRAVEL,
            target_amount=50000.0, current_amount=60000.0,
            monthly_contribution=5000.0,
        )
        assert goal.progress_pct == 100.0


# ─── CSV Ingestion Tests ──────────────────────────────────────────────────────

class TestCSVIngester:
    @patch("src.ingestion.document_loader.CSVIngester._normalise_headers")
    def test_basic_csv_ingestion(self, mock_normalise, sample_csv):
        """Test CSV parsing with mocked LLM header normalisation."""
        from src.ingestion.document_loader import CSVIngester

        # _normalise_headers returns the inverted form: {standardName: originalCol}
        mock_normalise.return_value = {
            "date": "Date",
            "description": "Description",
            "debit_amount": "Debit",
            "credit_amount": "Credit",
            "balance": "Balance",
        }

        ingester = CSVIngester()
        batch = ingester.ingest(sample_csv, account_name="Test Account")

        assert batch.source_type == "csv"
        assert len(batch.transactions) == 5
        assert batch.account_holder == "Test Account"

    @patch("src.ingestion.document_loader.CSVIngester._normalise_headers")
    def test_debit_credit_split_columns(self, mock_normalise, sample_csv):
        from src.ingestion.document_loader import CSVIngester

        mock_normalise.return_value = {
            "date": "Date",
            "description": "Description",
            "debit_amount": "Debit",
            "credit_amount": "Credit",
        }

        ingester = CSVIngester()
        batch = ingester.ingest(sample_csv)

        debits = [t for t in batch.transactions if t.transaction_type == TransactionType.DEBIT]
        credits = [t for t in batch.transactions if t.transaction_type == TransactionType.CREDIT]

        assert len(credits) == 1   # Salary
        assert len(debits) == 4    # Swiggy, BigBasket, Netflix, Rent

    @patch("src.ingestion.document_loader.CSVIngester._normalise_headers")
    def test_salary_is_credit(self, mock_normalise, sample_csv):
        from src.ingestion.document_loader import CSVIngester

        mock_normalise.return_value = {
            "date": "Date", "description": "Description",
            "debit_amount": "Debit", "credit_amount": "Credit",
        }

        ingester = CSVIngester()
        batch = ingester.ingest(sample_csv)
        credits = [t for t in batch.transactions if t.transaction_type == TransactionType.CREDIT]
        assert credits[0].amount == 95000.0


# ─── Analyser Tests ───────────────────────────────────────────────────────────

class TestFinancialAnalyser:
    def test_aggregate_by_category(self, mock_transactions):
        from src.agents.analyser import FinancialAnalyser
        analyser = FinancialAnalyser()
        totals = analyser.aggregate_by_category(mock_transactions, TransactionType.DEBIT)

        assert totals["food_dining"] == 450.0
        assert totals["groceries"] == 3200.0
        assert totals["rent_emi"] == 22000.0

    def test_aggregate_by_month(self, mock_transactions):
        from src.agents.analyser import FinancialAnalyser
        analyser = FinancialAnalyser()
        monthly = analyser.aggregate_by_month(mock_transactions)

        assert "2025-03" in monthly
        assert monthly["2025-03"]["income"] == 95000.0
        assert monthly["2025-03"]["expenses"] == 450 + 3200 + 649 + 22000

    def test_savings_rate(self):
        from src.agents.analyser import FinancialAnalyser
        analyser = FinancialAnalyser()
        rate = analyser.compute_savings_rate(100000.0, 60000.0)
        assert rate == 40.0

    def test_savings_rate_zero_income(self):
        from src.agents.analyser import FinancialAnalyser
        analyser = FinancialAnalyser()
        rate = analyser.compute_savings_rate(0.0, 1000.0)
        assert rate == 0.0

    def test_date_range(self, mock_transactions):
        from src.agents.analyser import FinancialAnalyser
        analyser = FinancialAnalyser()
        start, end = analyser.get_date_range(mock_transactions)
        assert start == date(2025, 3, 1)
        assert end == date(2025, 3, 15)

    def test_detect_recurring_subscriptions(self):
        from src.agents.analyser import FinancialAnalyser

        transactions = [
            Transaction(id=str(uuid.uuid4()), date=date(2025, 1, 5), description="Netflix",
                       amount=649.0, transaction_type=TransactionType.DEBIT,
                       category=TransactionCategory.SUBSCRIPTIONS, merchant="Netflix"),
            Transaction(id=str(uuid.uuid4()), date=date(2025, 2, 5), description="Netflix",
                       amount=649.0, transaction_type=TransactionType.DEBIT,
                       category=TransactionCategory.SUBSCRIPTIONS, merchant="Netflix"),
            Transaction(id=str(uuid.uuid4()), date=date(2025, 3, 5), description="Netflix",
                       amount=649.0, transaction_type=TransactionType.DEBIT,
                       category=TransactionCategory.SUBSCRIPTIONS, merchant="Netflix"),
        ]

        analyser = FinancialAnalyser()
        subs = analyser.detect_recurring_subscriptions(transactions)
        assert len(subs) == 1
        assert subs[0]["merchant"] == "Netflix"
        assert subs[0]["monthly_amount"] == 649.0
        assert subs[0]["annual_cost"] == 649.0 * 12

    @patch.object(__import__("src.agents.analyser", fromlist=["FinancialAnalyser"]).FinancialAnalyser, "_generate_insights", return_value=[])
    @patch.object(__import__("src.agents.analyser", fromlist=["FinancialAnalyser"]).FinancialAnalyser, "_llm_goal_analysis", return_value=[])
    def test_generate_summary_no_llm(self, mock_goals_llm, mock_insights, mock_transactions, mock_goals):
        from src.agents.analyser import FinancialAnalyser
        analyser = FinancialAnalyser()
        summary = analyser.generate_summary(mock_transactions, mock_goals)

        assert summary.total_income == 95000.0
        assert summary.total_expenses == 450 + 3200 + 649 + 22000
        assert summary.net_savings == 95000 - (450 + 3200 + 649 + 22000)
        assert 0 < summary.savings_rate_pct < 100


# ─── Goal Correlation Tests ───────────────────────────────────────────────────

class TestGoalCorrelation:
    @patch.object(__import__("src.agents.analyser", fromlist=["FinancialAnalyser"]).FinancialAnalyser, "_llm_goal_analysis", return_value=[])
    def test_correlate_goals_basic(self, mock_llm, mock_transactions, mock_goals):
        from src.agents.analyser import FinancialAnalyser
        from src.models import GoalStatus

        analyser = FinancialAnalyser()
        correlations = analyser.correlate_goals(mock_transactions, mock_goals)

        assert len(correlations) == 2
        for c in correlations:
            assert c.monthly_surplus_available >= 0
            assert c.recommended_contribution >= 0
            assert isinstance(c.status, GoalStatus)

    @patch.object(__import__("src.agents.analyser", fromlist=["FinancialAnalyser"]).FinancialAnalyser, "_llm_goal_analysis", return_value=[])
    def test_priority_order_matters(self, mock_llm, mock_transactions, mock_goals):
        """Higher priority goal should be funded first."""
        from src.agents.analyser import FinancialAnalyser

        analyser = FinancialAnalyser()
        correlations = analyser.correlate_goals(mock_transactions, mock_goals)

        # First goal (priority 1 = Emergency Fund) should have >= contribution than second
        assert correlations[0].recommended_contribution >= correlations[1].recommended_contribution

    @patch.object(__import__("src.agents.analyser", fromlist=["FinancialAnalyser"]).FinancialAnalyser, "_llm_goal_analysis", return_value=[])
    def test_empty_goals_returns_empty(self, mock_llm, mock_transactions):
        from src.agents.analyser import FinancialAnalyser
        analyser = FinancialAnalyser()
        correlations = analyser.correlate_goals(mock_transactions, [])
        assert correlations == []


# ─── Goals CSV Loader Tests ───────────────────────────────────────────────────

class TestInvestmentGoalsLoader:
    @patch("src.ingestion.document_loader.InvestmentGoalsLoader.GOALS_NORMALISE_PROMPT", "")
    @patch("src.ingestion.document_loader.get_fast_llm")
    def test_load_goals_csv(self, mock_get_llm, sample_goals_csv):
        from src.ingestion.document_loader import InvestmentGoalsLoader
        import json

        mock_llm = MagicMock()
        mock_response = MagicMock()
        # LLM returns {originalCol: standardName}; loader inverts internally.
        mock_response.content = json.dumps({
            "name": "name", "goal_type": "goal_type",
            "target_amount": "target_amount", "current_amount": "current_amount",
            "monthly_contribution": "monthly_contribution", "target_date": "target_date",
            "priority": "priority", "notes": None,
        })
        mock_llm.invoke.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        loader = InvestmentGoalsLoader()
        goals = loader.load(sample_goals_csv)

        assert len(goals) == 2
        assert goals[0].name == "Emergency Fund"
        assert goals[0].target_amount == 300000.0
        assert goals[0].current_amount == 85000.0
        assert goals[0].monthly_contribution == 10000.0
        assert goals[1].goal_type == GoalType.HOME_PURCHASE


# ─── Helper Function Tests ────────────────────────────────────────────────────

class TestHelpers:
    def test_to_float_standard(self):
        from src.ingestion.document_loader import _to_float
        assert _to_float("1234.56") == 1234.56

    def test_to_float_with_commas(self):
        from src.ingestion.document_loader import _to_float
        assert _to_float("1,23,456.78") == 123456.78

    def test_to_float_none(self):
        from src.ingestion.document_loader import _to_float
        assert _to_float(None) is None

    def test_to_float_empty(self):
        from src.ingestion.document_loader import _to_float
        assert _to_float("") is None

    def test_parse_date_ymd(self):
        from src.ingestion.document_loader import _parse_date_flexible
        assert _parse_date_flexible("2025-03-15") == date(2025, 3, 15)

    def test_parse_date_dmy_slash(self):
        from src.ingestion.document_loader import _parse_date_flexible
        assert _parse_date_flexible("15/03/2025") == date(2025, 3, 15)

    def test_parse_date_mdy_slash(self):
        from src.ingestion.document_loader import _parse_date_flexible
        assert _parse_date_flexible("03/15/2025") == date(2025, 3, 15)

    def test_parse_date_invalid_raises(self):
        from src.ingestion.document_loader import _parse_date_flexible
        with pytest.raises(ValueError):
            _parse_date_flexible("not-a-date")

    def test_chunk_text_short(self):
        from src.ingestion.document_loader import _chunk_text
        text = "Hello\nWorld"
        chunks = _chunk_text(text, max_chars=1000)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_chunk_text_splits_long(self):
        from src.ingestion.document_loader import _chunk_text
        text = "\n".join([f"Line {i}: " + "x" * 100 for i in range(50)])
        chunks = _chunk_text(text, max_chars=1000)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= 1100  # small tolerance for final lines