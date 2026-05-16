"""Tests for the Orchestra Finance engine."""

from __future__ import annotations

import pytest

from code_agent.finance.analytics import (
    AnalyticsEngine,
    MonteCarloSimulation,
    ScenarioGenerator,
    TimeSeriesForecast,
)
from code_agent.finance.brain import CFOInsight, FinanceBrain
from code_agent.finance.events import EventBus, FinanceEvent
from code_agent.finance.formula import CellRef, DependencyGraph, FormulaEngine, FormulaParser
from code_agent.finance.ledger import LedgerEngine, Reconciliator, TransactionEngine
from code_agent.finance.models import (
    Account,
    AccountType,
    FinancialStatement,
    LedgerEntry,
    SheetCell,
    SheetRange,
    Transaction,
    TransactionType,
)


# ── Models ─────────────────────────────────

class TestAccount:
    def test_auto_id(self):
        a = Account(code="1000", name="Cash", type=AccountType.ASSET)
        assert len(a.id) == 12

    def test_account_type_enum(self):
        assert AccountType.ASSET.value == "asset"
        assert AccountType.REVENUE.value == "revenue"


class TestTransaction:
    def test_auto_id_and_timestamp(self):
        tx = Transaction(date="2026-01-01", description="Test")
        assert len(tx.id) == 12
        assert tx.created_at != ""

    def test_is_balanced_true(self):
        tx = Transaction(date="2026-01-01", description="Balanced", entries=[
            LedgerEntry("acc1", amount=100, direction="debit"),
            LedgerEntry("acc2", amount=100, direction="credit"),
        ])
        assert tx.is_balanced is True

    def test_is_balanced_false(self):
        tx = Transaction(date="2026-01-01", description="Unbalanced", entries=[
            LedgerEntry("acc1", amount=100, direction="debit"),
            LedgerEntry("acc2", amount=50, direction="credit"),
        ])
        assert tx.is_balanced is False


class TestFinancialStatement:
    def test_profit_margin(self):
        s = FinancialStatement(revenue=100000, expenses=60000, net_income=40000)
        assert s.profit_margin == 40.0

    def test_debt_to_equity(self):
        s = FinancialStatement(total_liabilities=50000, equity=100000)
        assert s.debt_to_equity == 0.5

    def test_zero_division(self):
        s = FinancialStatement()
        assert s.profit_margin == 0.0
        assert s.debt_to_equity == 0.0


class TestSheetCell:
    def test_numeric_value(self):
        c = SheetCell(ref="A1", value="42")
        assert c.numeric_value == 42.0

    def test_numeric_value_default(self):
        c = SheetCell(ref="A1")
        assert c.numeric_value == 0.0

    def test_has_formula(self):
        c = SheetCell(ref="A1", formula="=SUM(B1:B5)")
        assert c.has_formula is True
        c2 = SheetCell(ref="A1", value="42")
        assert c2.has_formula is False


class TestSheetRange:
    def test_values(self):
        r = SheetRange(cells=[SheetCell(ref="A1", value=1), SheetCell(ref="A2", value=2)])
        assert r.sum == 3
        assert r.avg == 1.5
        assert r.max == 2
        assert r.min == 1

    def test_empty_range(self):
        r = SheetRange()
        assert r.sum == 0
        assert r.avg == 0.0


# ── CellRef ────────────────────────────────

class TestCellRef:
    def test_parse_a1(self):
        ref = CellRef.parse("A1")
        assert ref is not None
        assert ref.col == 0
        assert ref.row == 0

    def test_parse_z100(self):
        ref = CellRef.parse("Z100")
        assert ref is not None
        assert ref.col == 25
        assert ref.row == 99

    def test_parse_aa1(self):
        ref = CellRef.parse("AA1")
        assert ref is not None
        assert ref.col == 26

    def test_to_string(self):
        assert CellRef.to_string(0, 0) == "A1"
        assert CellRef.to_string(25, 99) == "Z100"
        assert CellRef.to_string(26, 0) == "AA1"

    def test_parse_invalid(self):
        assert CellRef.parse("") is None
        assert CellRef.parse("1A") is None


# ── DependencyGraph ────────────────────────

class TestDependencyGraph:
    def test_add_and_get_dependents(self):
        g = DependencyGraph()
        g.add_dependency("C1", ["A1", "B1"])
        assert g.get_dependencies("C1") == {"A1", "B1"}
        assert g.get_dependents("A1") == {"C1"}

    def test_recalc_order(self):
        g = DependencyGraph()
        g.add_dependency("B1", ["A1"])
        g.add_dependency("C1", ["B1"])
        order = g.get_recalc_order({"A1"})
        assert "A1" in order
        assert "B1" in order
        assert "C1" in order
        # C1 should be first (deepest dependent, needs recalc first)
        assert order[0] == "C1"

    def test_remove_cell(self):
        g = DependencyGraph()
        g.add_dependency("B1", ["A1"])
        g.remove_cell("A1")
        assert g.get_dependents("A1") == set()
        assert g.get_dependencies("B1") == set()

    def test_clear(self):
        g = DependencyGraph()
        g.add_dependency("B1", ["A1"])
        g.clear()
        assert g.get_dependencies("B1") == set()


# ── FormulaParser ──────────────────────────

class TestFormulaParser:
    def test_plain_value(self):
        p = FormulaParser()
        val, deps = p.parse("hello")
        assert val == "hello"
        assert deps == []

    def test_sum_range(self):
        data = {"A1": 10, "A2": 20, "A3": 30}
        p = FormulaParser(cell_getter=lambda r: data.get(r, 0))
        val, deps = p.parse("=SUM(A1:A3)")
        assert val == 60
        assert len(deps) >= 1

    def test_avg_range(self):
        data = {"A1": 10, "A2": 20, "A3": 30}
        p = FormulaParser(cell_getter=lambda r: data.get(r, 0))
        val, _ = p.parse("=AVG(A1:A3)")
        assert val == 20.0

    def test_max_min(self):
        data = {"A1": 5, "A2": 15, "A3": 10}
        p = FormulaParser(cell_getter=lambda r: data.get(r, 0))
        assert p.parse("=MAX(A1:A3)")[0] == 15
        assert p.parse("=MIN(A1:A3)")[0] == 5

    def test_count(self):
        data = {"A1": 1, "A2": 2, "A3": 3}
        p = FormulaParser(cell_getter=lambda r: data.get(r, 0))
        assert p.parse("=COUNT(A1:A3)")[0] == 3

    def test_if_true(self):
        p = FormulaParser()
        val, _ = p.parse("=IF(1>0,100,200)")
        assert val == 100

    def test_if_false(self):
        p = FormulaParser()
        val, _ = p.parse("=IF(0>1,100,200)")
        assert val == 200

    def test_arithmetic(self):
        p = FormulaParser()
        assert p.parse("=10+20")[0] == 30
        assert p.parse("=10-5")[0] == 5
        assert p.parse("=10*5")[0] == 50
        assert p.parse("=10/2")[0] == 5.0
        assert p.parse("=2^3")[0] == 8

    def test_division_by_zero(self):
        p = FormulaParser()
        assert p.parse("=10/0")[0] == "#DIV/0"

    def test_abs(self):
        p = FormulaParser()
        val, _ = p.parse("=ABS(-42)")
        assert val == 42.0

    def test_round(self):
        p = FormulaParser()
        val, _ = p.parse("=ROUND(3.14159,2)")
        assert val == 3.14


# ── FormulaEngine ──────────────────────────

class TestFormulaEngine:
    def test_set_cell_plain_value(self):
        e = FormulaEngine()
        cell = e.set_cell("A1", value="42")
        assert cell.value == "42"

    def test_set_cell_with_formula(self):
        e = FormulaEngine()
        e.set_cell("A1", value=10)
        e.set_cell("A2", value=20)
        cell = e.set_cell("A3", formula="=SUM(A1:A2)")
        assert cell.value == 30

    def test_get_cell(self):
        e = FormulaEngine()
        e.set_cell("B5", value="hello")
        cell = e.get_cell("B5")
        assert cell is not None
        assert cell.value == "hello"
        assert e.get_cell("nonexistent") is None

    def test_recalc(self):
        e = FormulaEngine()
        e.set_cell("A1", value=10)
        e.set_cell("B1", formula="=A1*2")
        assert e.get_cell("B1").value == 20
        e.set_cell("A1", value=50)
        e.recalc({"A1"})
        assert e.get_cell("B1").value == 100

    def test_to_grid(self):
        e = FormulaEngine()
        e.set_cell("A1", value=10)
        e.set_cell("B1", value=20)
        grid = e.to_grid()
        assert len(grid) > 0

    def test_clear(self):
        e = FormulaEngine()
        e.set_cell("A1", value=1)
        e.clear()
        assert e.get_cell("A1") is None


# ── TransactionEngine ──────────────────────

class TestTransactionEngine:
    def test_create_account(self):
        eng = TransactionEngine()
        acc = eng.create_account("1000", "Cash", AccountType.ASSET)
        assert acc.id in eng.accounts

    def test_record_transaction_balanced(self):
        eng = TransactionEngine()
        cash = eng.create_account("1000", "Cash", AccountType.ASSET)
        revenue = eng.create_account("4000", "Revenue", AccountType.REVENUE)
        tx = eng.record_double_entry("2026-01-01", "Sale", cash.id, revenue.id, 1000)
        assert tx.is_balanced

    def test_record_transaction_unbalanced_raises(self):
        eng = TransactionEngine()
        with pytest.raises(ValueError, match="not balanced"):
            eng.record_transaction("2026-01-01", "Bad", [
                LedgerEntry("acc1", amount=100, direction="debit"),
            ])

    def test_get_account_balance(self):
        eng = TransactionEngine()
        cash = eng.create_account("1000", "Cash", AccountType.ASSET)
        revenue = eng.create_account("4000", "Revenue", AccountType.REVENUE)
        eng.record_double_entry("2026-01-01", "Sale 1", cash.id, revenue.id, 500)
        eng.record_double_entry("2026-01-02", "Sale 2", cash.id, revenue.id, 300)
        assert eng.get_account_balance(cash.id) == 800.0
        assert eng.get_account_balance(revenue.id) == -800.0

    def test_get_trial_balance(self):
        eng = TransactionEngine()
        cash = eng.create_account("1000", "Cash", AccountType.ASSET)
        rev = eng.create_account("4000", "Rev", AccountType.REVENUE)
        eng.record_double_entry("2026-01-01", "Test", cash.id, rev.id, 1000)
        tb = eng.get_trial_balance()
        assert tb["balanced"] is True
        assert tb["total_debits"] == 1000.0

    def test_get_statement(self):
        eng = TransactionEngine()
        cash = eng.create_account("1000", "Cash", AccountType.ASSET)
        rev = eng.create_account("4000", "Rev", AccountType.REVENUE)
        exp = eng.create_account("5000", "Rent", AccountType.EXPENSE)
        eng.record_double_entry("2026-01-01", "Sale", cash.id, rev.id, 10000)
        eng.record_double_entry("2026-01-02", "Rent", exp.id, cash.id, 3000)
        stmt = eng.get_statement("2026-Q1")
        assert stmt.revenue == 10000
        assert stmt.expenses == 3000
        assert stmt.gross_profit == 7000

    def test_query(self):
        eng = TransactionEngine()
        cash = eng.create_account("1000", "Cash", AccountType.ASSET)
        rev = eng.create_account("4000", "Rev", AccountType.REVENUE)
        eng.record_double_entry("2026-01-01", "Sale", cash.id, rev.id, 500)
        eng.record_double_entry("2026-01-15", "Sale", cash.id, rev.id, 500)
        results = eng.query(date_from="2026-01-10")
        assert len(results) == 1

    def test_export_ledger_json(self):
        eng = TransactionEngine()
        cash = eng.create_account("1000", "Cash", AccountType.ASSET)
        rev = eng.create_account("4000", "Rev", AccountType.REVENUE)
        eng.record_double_entry("2026-01-01", "Sale", cash.id, rev.id, 1000)
        export = eng.export_ledger("json")
        assert len(export) == 1
        assert export[0]["description"] == "Sale"


# ── Reconciliator ──────────────────────────

class TestReconciliator:
    def test_reconcile_matched(self):
        eng = TransactionEngine()
        cash = eng.create_account("1000", "Cash", AccountType.ASSET)
        rev = eng.create_account("4000", "Rev", AccountType.REVENUE)
        eng.record_double_entry("2026-01-01", "Sale", cash.id, rev.id, 5000)
        r = Reconciliator(eng)
        result = r.reconcile(cash.id, 5000.0)
        assert result["is_reconciled"] is True

    def test_reconcile_mismatched(self):
        eng = TransactionEngine()
        cash = eng.create_account("1000", "Cash", AccountType.ASSET)
        rev = eng.create_account("4000", "Rev", AccountType.REVENUE)
        eng.record_double_entry("2026-01-01", "Sale", cash.id, rev.id, 5000)
        r = Reconciliator(eng)
        result = r.reconcile(cash.id, 4800.0)
        assert result["is_reconciled"] is False
        assert result["difference"] == -200.0


# ── Analytics ──────────────────────────────

class TestTimeSeriesForecast:
    def test_moving_average(self):
        ts = TimeSeriesForecast([10, 20, 30, 40, 50])
        ma = ts.moving_average(3)
        assert len(ma) == 5
        assert ma[-1] == 40.0  # avg(30,40,50)

    def test_exponential_smoothing(self):
        ts = TimeSeriesForecast([100, 110, 120, 130])
        smoothed = ts.exponential_smoothing(alpha=0.5, forecast_horizon=2)
        assert len(smoothed) == 6  # 4 original + 2 forecast

    def test_linear_regression(self):
        ts = TimeSeriesForecast([10, 20, 30, 40, 50])
        forecast = ts.linear_regression(forecast_horizon=3)
        assert len(forecast) == 8  # 5 original + 3 forecast
        assert forecast[-1] > forecast[-2]  # upward trend

    def test_seasonal_decompose(self):
        ts = TimeSeriesForecast([100, 120, 110, 130, 100, 120, 110, 130])
        result = ts.seasonal_decompose(period=4)
        assert "trend" in result
        assert "seasonal" in result
        assert len(result["trend"]) == 8


class TestMonteCarloSimulation:
    def test_run_returns_expected_keys(self):
        mc = MonteCarloSimulation(base_value=100000, volatility=0.1)
        result = mc.run(steps=12, simulations=500)
        assert result["simulations"] == 500
        assert result["final_mean"] > 0
        assert len(result["percentiles"]) == 5

    def test_value_at_risk(self):
        mc = MonteCarloSimulation(base_value=100000, volatility=0.2)
        var = mc.value_at_risk(confidence=0.95, horizon=1)
        assert var["confidence"] == 0.95
        assert "var_absolute" in var


class TestScenarioGenerator:
    def test_generate_scenarios(self):
        base = FinancialStatement(revenue=100000, expenses=70000)
        gen = ScenarioGenerator(base)
        scenarios = gen.generate_scenarios()
        assert len(scenarios) == 6
        assert "base" in scenarios
        assert "bullish" in scenarios
        assert scenarios["bullish"].revenue > scenarios["base"].revenue

    def test_apply_growth(self):
        base = FinancialStatement(revenue=100000, expenses=70000)
        gen = ScenarioGenerator(base)
        s = gen.apply_growth(0.1, 0.05)
        assert abs(s.revenue - 110000.0) < 0.01
        assert abs(s.expenses - 73500.0) < 0.01


# ── FinanceBrain ───────────────────────────

class TestFinanceBrain:
    def test_generate_insights(self):
        brain = FinanceBrain()
        stmt = FinancialStatement(
            revenue=100000, expenses=95000, net_income=5000,
            total_assets=200000, total_liabilities=150000,
        )
        insights = brain.generate_insights(stmt)
        assert len(insights) > 0

    def test_insights_severity(self):
        brain = FinanceBrain()
        stmt = FinancialStatement(
            revenue=50000, expenses=55000, net_income=-5000,
            total_assets=100000, total_liabilities=80000,
        )
        insights = brain.generate_insights(stmt)
        severities = [i.severity for i in insights]
        assert "critical" in severities  # operating at loss

    def test_get_summary(self):
        brain = FinanceBrain()
        summary = brain.get_summary()
        assert "total_insights" in summary
        assert "llm_available" in summary

    def test_cfo_insight_to_dict(self):
        insight = CFOInsight(
            title="Test", description="Desc", severity="warning",
            category="revenue", metric="growth", value=10.5,
            recommendation="Do something", confidence=0.8,
        )
        d = insight.to_dict()
        assert d["title"] == "Test"
        assert d["severity"] == "warning"


# ── EventBus ───────────────────────────────

class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_and_subscribe(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe("test.event", handler)
        await bus.publish(FinanceEvent(event_type="test.event", data={"key": "val"}))
        assert len(received) == 1
        assert received[0].event_type == "test.event"

    @pytest.mark.asyncio
    async def test_wildcard_subscriber(self):
        bus = EventBus()
        received = []

        async def handler(event):
            received.append(event.event_type)

        bus.subscribe_all(handler)
        await bus.publish(FinanceEvent(event_type="tx.created"))
        await bus.publish(FinanceEvent(event_type="insight.generated"))
        assert len(received) == 2

    def test_replay(self):
        bus = EventBus()
        bus._history = [
            FinanceEvent(event_type="tx.created"),
            FinanceEvent(event_type="tx.created"),
            FinanceEvent(event_type="insight.generated"),
        ]
        replayed = bus.replay("tx.created")
        assert len(replayed) == 2
        all_events = bus.replay()
        assert len(all_events) == 3

    def test_stats(self):
        bus = EventBus()
        bus._history = [
            FinanceEvent(event_type="tx.created"),
            FinanceEvent(event_type="insight.generated"),
        ]
        stats = bus.stats()
        assert stats["total_events"] == 2
