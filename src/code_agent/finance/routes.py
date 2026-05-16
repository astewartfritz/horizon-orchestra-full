"""API routes for the Orchestra Finance engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from code_agent.finance.ledger import TransactionEngine, LedgerEngine, Reconciliator
from code_agent.finance.models import LedgerEntry, FinancialStatement
from code_agent.finance.analytics import AnalyticsEngine
from code_agent.finance.brain import FinanceBrain
from code_agent.finance.formula import FormulaEngine
from code_agent.finance.events import EventBus, FinanceEvent


def register_finance_routes(app: Any, prefix: str = "/api/finance") -> None:
    """Register all Orchestra Finance API routes on a FastAPI app."""
    tx_engine = TransactionEngine()
    ledger = LedgerEngine(tx_engine)
    formula = FormulaEngine()
    analytics = AnalyticsEngine()
    brain = FinanceBrain(tx_engine, analytics, formula)
    event_bus = EventBus()

    router = APIRouter(prefix=prefix)

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "orchestra-finance"}

    # ── Accounts ─────────────────────────

    @router.post("/accounts")
    async def create_account(body: dict[str, Any]):
        from code_agent.finance.models import AccountType
        acc = tx_engine.create_account(
            code=body["code"],
            name=body["name"],
            type=AccountType(body["type"]),
            currency=body.get("currency", "USD"),
        )
        return {"id": acc.id, "code": acc.code, "name": acc.name, "type": acc.type.value}

    @router.get("/accounts")
    async def list_accounts():
        return {aid: {"code": a.code, "name": a.name, "type": a.type.value}
                for aid, a in tx_engine.accounts.items()}

    @router.get("/accounts/{account_id}/balance")
    async def account_balance(account_id: str):
        balance = tx_engine.get_account_balance(account_id)
        acc = tx_engine.accounts.get(account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"account_id": account_id, "name": acc.name, "balance": round(balance, 2)}

    # ── Transactions ──────────────────────

    @router.post("/transactions")
    async def record_transaction(body: dict[str, Any]):
        entries = [
            LedgerEntry(
                account_id=e["accountId"],
                amount=e["amount"],
                direction=e.get("direction", "debit"),
                description=e.get("description", ""),
            )
            for e in body.get("entries", [])
        ]
        tx = tx_engine.record_transaction(
            date=body["date"],
            description=body.get("description", ""),
            entries=entries,
            tags=body.get("tags", []),
        )
        await event_bus.publish_tx(tx)
        return {"id": tx.id, "date": tx.date, "description": tx.description,
                "balanced": tx.is_balanced, "debits": tx.debit_total, "credits": tx.credit_total}

    @router.get("/transactions")
    async def query_transactions(account_id: str = "", date_from: str = "", date_to: str = ""):
        results = tx_engine.query(
            account_id=account_id or None,
            date_from=date_from,
            date_to=date_to,
        )
        return {
            "count": len(results),
            "transactions": [{
                "id": t.id, "date": t.date, "description": t.description,
                "type": t.type.value, "entries": [
                    {"account_id": e.account_id, "amount": e.amount, "direction": e.direction}
                    for e in t.entries
                ],
            } for t in results],
        }

    @router.get("/ledger/trial-balance")
    async def trial_balance():
        return tx_engine.get_trial_balance()

    @router.get("/statements")
    async def financial_statements(period: str = ""):
        stmt = tx_engine.get_statement(period)
        return {
            "period": stmt.period,
            "revenue": stmt.revenue,
            "expenses": stmt.expenses,
            "gross_profit": stmt.gross_profit,
            "net_income": stmt.net_income,
            "total_assets": stmt.total_assets,
            "total_liabilities": stmt.total_liabilities,
            "equity": stmt.equity,
            "profit_margin": round(stmt.profit_margin, 2),
        }

    # ── Reconciliations ────────────────────

    @router.post("/reconcile/{account_id}")
    async def reconcile(account_id: str, body: dict[str, Any]):
        reconciler = Reconciliator(tx_engine)
        result = reconciler.reconcile(
            account_id,
            expected_balance=body["expected_balance"],
            as_of_date=body.get("as_of_date", ""),
        )
        return result

    @router.post("/reconcile/{account_id}/auto")
    async def auto_reconcile(account_id: str, body: dict[str, Any]):
        reconciler = Reconciliator(tx_engine)
        tx = reconciler.auto_reconcile(
            account_id,
            expected_balance=body["expected_balance"],
            as_of_date=body.get("as_of_date", ""),
        )
        return {"adjustment_created": tx is not None, "transaction_id": tx.id if tx else None}

    # ── Formulas ───────────────────────────

    @router.post("/formula")
    async def evaluate_formula(body: dict[str, Any]):
        formula_str = body.get("formula", "")
        cell_ref = body.get("cell_ref", "")
        sheet_data = body.get("sheet_data", {})

        for ref, val in sheet_data.items():
            formula.set_cell(ref, value=val)

        cell = formula.set_cell(cell_ref or "TEMP", formula=formula_str,
                                ai_generated=body.get("ai_generated", False))
        return {
            "formula": formula_str,
            "result": cell.value,
            "formatted": cell.formatted,
            "cell_ref": cell.ref,
            "value_type": cell.value_type.value,
        }

    @router.post("/formula/bulk")
    async def bulk_formula(body: dict[str, Any]):
        formulas = body.get("formulas", [])
        results = []
        for f in formulas:
            cell = formula.set_cell(f.get("cell_ref", "TEMP"), formula=f["formula"])
            results.append({"cell_ref": cell.ref, "result": cell.value, "formatted": cell.formatted})
        return {"results": results, "count": len(results)}

    # ── Analytics ──────────────────────────

    @router.post("/analytics/forecast")
    async def forecast(body: dict[str, Any]):
        result = analytics.forecast_revenue(
            historical=body["historical"],
            method=body.get("method", "exponential"),
            horizon=body.get("horizon", 3),
        )
        return result

    @router.post("/analytics/monte-carlo")
    async def monte_carlo(body: dict[str, Any]):
        result = analytics.monte_carlo_projection(
            base_revenue=body["base_revenue"],
            volatility=body.get("volatility", 0.15),
            steps=body.get("steps", 12),
            sims=body.get("simulations", 1000),
        )
        return result

    @router.post("/analytics/scenarios")
    async def what_if_scenarios(body: dict[str, Any]):
        stmt = FinancialStatement(**body.get("statement", {}))
        return analytics.what_if_scenarios(stmt)

    @router.post("/analytics/risk")
    async def risk_analysis(body: dict[str, Any]):
        return analytics.risk_analysis(
            portfolio_value=body["portfolio_value"],
            volatility=body.get("volatility", 0.2),
        )

    # ── AI Brain / CFO Copilot ─────────────

    @router.post("/brain/insights")
    async def generate_insights(body: dict[str, Any]):
        stmt = FinancialStatement(**body.get("statement", {}))
        insights = brain.generate_insights(stmt)
        return {
            "insights": [i.to_dict() for i in insights],
            "summary": brain.get_summary(),
        }

    @router.get("/brain/insights")
    async def get_insights(severity: str = ""):
        return {"insights": brain.get_insights(severity or None)}

    @router.post("/brain/query")
    async def ai_query(body: dict[str, Any]):
        result = await brain.llm_analyze(
            prompt=body.get("prompt", ""),
            context=body.get("context"),
        )
        return {"response": result}

    @router.get("/brain/summary")
    async def brain_summary():
        return brain.get_summary()

    # ── Events ─────────────────────────────

    @router.get("/events/stats")
    async def event_stats():
        return event_bus.stats()

    @router.get("/events/replay")
    async def replay_events(event_type: str = "", limit: int = 100):
        return {"events": [e.to_dict() for e in event_bus.replay(event_type or None, limit=limit)]}

    app.include_router(router)
