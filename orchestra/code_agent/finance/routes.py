"""API routes for the Orchestra Finance engine."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from orchestra.code_agent.finance.ledger import TransactionEngine, LedgerEngine, Reconciliator
from orchestra.code_agent.finance.models import LedgerEntry, FinancialStatement
from orchestra.code_agent.finance.analytics import AnalyticsEngine
from orchestra.code_agent.finance.brain import FinanceBrain
from orchestra.code_agent.finance.formula import FormulaEngine
from orchestra.code_agent.finance.events import EventBus, FinanceEvent


def register_finance_routes(app: Any, prefix: str = "/api/finance") -> None:
    """Register all Orchestra Finance API routes on a FastAPI app."""
    from orchestra.code_agent.finance import portfolio as pf
    pf.init_db()

    # Per-user engine instances — finance data is isolated per authenticated user
    _engines: dict[str, TransactionEngine] = {}
    _ledgers: dict[str, LedgerEngine] = {}

    def _get_engine(uid: str) -> TransactionEngine:
        if uid not in _engines:
            _engines[uid] = TransactionEngine()
            _ledgers[uid] = LedgerEngine(_engines[uid])
        return _engines[uid]

    formula = FormulaEngine()
    analytics = AnalyticsEngine()
    event_bus = EventBus()
    brain = FinanceBrain()

    router = APIRouter(prefix=prefix)

    from fastapi import Depends, Request
    from orchestra.code_agent.ui.handlers.user_dep import optional_user_id

    def _engine(uid: str | None = Depends(optional_user_id)) -> TransactionEngine:
        return _get_engine(uid or "_anonymous")

    @router.get("/health")
    async def health():
        return {"status": "ok", "service": "orchestra-finance"}

    # ── Accounts ─────────────────────────

    @router.post("/accounts")
    async def create_account(body: dict[str, Any], eng: TransactionEngine = Depends(_engine)):
        from orchestra.code_agent.finance.models import AccountType
        acc = eng.create_account(
            code=body["code"],
            name=body["name"],
            type=AccountType(body["type"]),
            currency=body.get("currency", "USD"),
        )
        return {"id": acc.id, "code": acc.code, "name": acc.name, "type": acc.type.value}

    @router.get("/accounts")
    async def list_accounts(eng: TransactionEngine = Depends(_engine)):
        return {aid: {"code": a.code, "name": a.name, "type": a.type.value}
                for aid, a in eng.accounts.items()}

    @router.get("/accounts/{account_id}/balance")
    async def account_balance(account_id: str, eng: TransactionEngine = Depends(_engine)):
        acc = eng.accounts.get(account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Account not found")
        balance = eng.get_account_balance(account_id)
        return {"account_id": account_id, "name": acc.name, "balance": round(balance, 2)}

    # ── Transactions ──────────────────────

    @router.post("/transactions")
    async def record_transaction(body: dict[str, Any], eng: TransactionEngine = Depends(_engine)):
        entries = [
            LedgerEntry(
                account_id=e["accountId"],
                amount=e["amount"],
                direction=e.get("direction", "debit"),
                description=e.get("description", ""),
            )
            for e in body.get("entries", [])
        ]
        tx = eng.record_transaction(
            date=body["date"],
            description=body.get("description", ""),
            entries=entries,
            tags=body.get("tags", []),
        )
        await event_bus.publish_tx(tx)
        return {"id": tx.id, "date": tx.date, "description": tx.description,
                "balanced": tx.is_balanced, "debits": tx.debit_total, "credits": tx.credit_total}

    @router.get("/transactions")
    async def query_transactions(
        account_id: str = "", date_from: str = "", date_to: str = "",
        eng: TransactionEngine = Depends(_engine),
    ):
        results = eng.query(
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
    async def trial_balance(eng: TransactionEngine = Depends(_engine)):
        return eng.get_trial_balance()

    @router.get("/statements")
    async def financial_statements(period: str = "", eng: TransactionEngine = Depends(_engine)):
        stmt = eng.get_statement(period)
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
    async def reconcile(account_id: str, body: dict[str, Any], eng: TransactionEngine = Depends(_engine)):
        reconciler = Reconciliator(eng)
        result = reconciler.reconcile(
            account_id,
            expected_balance=body["expected_balance"],
            as_of_date=body.get("as_of_date", ""),
        )
        return result

    @router.post("/reconcile/{account_id}/auto")
    async def auto_reconcile(account_id: str, body: dict[str, Any], eng: TransactionEngine = Depends(_engine)):
        reconciler = Reconciliator(eng)
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
        import os, shutil, asyncio, re
        prompt = body.get("prompt", "")
        context = body.get("context") or {}
        api_key = body.get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        provider = body.get("provider", "anthropic")
        model = body.get("model", "claude-opus-4-7")

        system = """You are an expert CFO and portfolio manager. Answer financial questions concisely with specific numbers, insights, and actionable recommendations. Be direct and data-driven."""
        full_prompt = system + "\n\nCONTEXT:\n" + __import__("json").dumps(context) + "\n\nQUESTION: " + prompt

        if api_key:
            try:
                from orchestra.code_agent.llm.base import LLM, Message
                llm = LLM(provider=provider, model=model, api_key=api_key, temperature=0.3)
                resp = await llm.chat([Message(role="user", content=full_prompt)])
                return {"response": resp.content}
            except Exception as e:
                pass

        # Fallback: Claude Code CLI
        try:
            cli = shutil.which("claude") or "claude"
            cmd = [cli, "--print", "--output-format", "text",
                   "--permission-mode", "bypassPermissions", "--max-turns", "3"]
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(input=full_prompt.encode()), timeout=120)
            return {"response": stdout.decode("utf-8", errors="replace").strip()}
        except Exception as e:
            return {"response": f"Error: {e}"}

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

    # ── Market Data ────────────────────────

    @router.get("/market/quote/{symbol}")
    async def market_quote(symbol: str):
        try:
            from orchestra.code_agent.finance.market import get_client
            client = get_client()
            data = await client.quote(symbol.upper())
            if data.get("price") is None:
                raise HTTPException(status_code=404, detail=f"No data for {symbol}")
            return data
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/market/historical/{symbol}")
    async def market_historical(
        symbol: str,
        range: str = Query("6mo", description="1d 5d 1mo 3mo 6mo 1y 2y 5y ytd max"),
        interval: str = Query("1d", description="1m 5m 15m 30m 60m 1d 1wk 1mo"),
    ):
        try:
            from orchestra.code_agent.finance.market import get_client
            client = get_client()
            data = await client.historical(symbol.upper(), range=range, interval=interval)
            return {"symbol": symbol.upper(), "range": range, "interval": interval, "candles": data}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/market/news")
    async def market_news(
        symbol: str = Query("", description="Ticker symbol or leave blank for general market news"),
        limit: int = Query(10, ge=1, le=50),
    ):
        try:
            from orchestra.code_agent.finance.market import get_client
            client = get_client()
            articles = await client.news(symbol.upper() if symbol else "", limit=limit)
            return {"symbol": symbol.upper() or "MARKET", "count": len(articles), "articles": articles}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/market/batch")
    async def market_batch(
        symbols: str = Query(..., description="Comma-separated list of tickers, e.g. AAPL,MSFT,NVDA"),
    ):
        try:
            from orchestra.code_agent.finance.market import get_client
            client = get_client()
            syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]
            if not syms:
                raise HTTPException(status_code=400, detail="No symbols provided")
            data = await client.batch_quotes(syms)
            return {"count": len(data), "quotes": data}
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/market/search")
    async def market_search(q: str = Query(..., min_length=1, description="Search query")):
        try:
            from orchestra.code_agent.finance.market import get_client
            client = get_client()
            results = await client.search(q)
            return {"query": q, "results": results}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/market/movers")
    async def market_movers(
        direction: str = Query("gainers", description="gainers | losers | active"),
    ):
        if direction not in ("gainers", "losers", "active"):
            raise HTTPException(status_code=400, detail="direction must be gainers, losers, or active")
        try:
            from orchestra.code_agent.finance.market import get_client
            client = get_client()
            data = await client.movers(direction)
            return {"direction": direction, "count": len(data), "movers": data}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/market/indices")
    async def market_indices():
        try:
            from orchestra.code_agent.finance.market import get_client
            client = get_client()
            data = await client.indices()
            return {"indices": data}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    # ── Portfolios ──────────────────────────
    @router.get("/portfolios")
    async def list_portfolios():
        return pf.list_portfolios()

    @router.post("/portfolios")
    async def create_portfolio(body: dict[str, Any]):
        if not body.get("name"):
            raise HTTPException(400, "name required")
        return pf.create_portfolio(body)

    @router.get("/portfolios/{pid}/positions")
    async def list_positions(pid: str):
        return pf.list_positions(pid)

    @router.post("/portfolios/{pid}/positions")
    async def add_position(pid: str, body: dict[str, Any]):
        body["portfolio_id"] = pid
        if not body.get("ticker") or body.get("shares") is None or body.get("avg_cost") is None:
            raise HTTPException(400, "ticker, shares, avg_cost required")
        pos = pf.upsert_position(body)
        # Also record a buy transaction
        pf.add_transaction({"portfolio_id": pid, "ticker": body["ticker"],
                             "type": "buy", "shares": body["shares"], "price": body["avg_cost"],
                             "date": body.get("opened_date", "")})
        return pos

    @router.patch("/portfolios/{pid}/positions/{pos_id}")
    async def update_position(pid: str, pos_id: str, body: dict[str, Any]):
        result = pf.update_position(pos_id, body)
        if not result:
            raise HTTPException(404, "Position not found")
        return result

    @router.delete("/portfolios/{pid}/positions/{pos_id}")
    async def delete_position(pid: str, pos_id: str):
        if not pf.delete_position(pos_id):
            raise HTTPException(404, "Position not found")
        return {"deleted": True}

    @router.get("/portfolios/{pid}/transactions")
    async def list_port_transactions(pid: str, ticker: str = ""):
        return pf.list_transactions(pid, ticker=ticker)

    @router.post("/portfolios/{pid}/transactions")
    async def add_port_transaction(pid: str, body: dict[str, Any]):
        body["portfolio_id"] = pid
        return pf.add_transaction(body)

    # ── Deal Flow ────────────────────────────
    @router.get("/deals")
    async def list_deals(stage: str = "", status: str = "active"):
        return pf.list_deals(stage=stage, status=status)

    @router.post("/deals")
    async def create_deal(body: dict[str, Any]):
        if not body.get("company"):
            raise HTTPException(400, "company required")
        return pf.create_deal(body)

    @router.patch("/deals/{deal_id}")
    async def update_deal(deal_id: str, body: dict[str, Any]):
        result = pf.update_deal(deal_id, body)
        if not result:
            raise HTTPException(404, "Deal not found")
        return result

    @router.delete("/deals/{deal_id}")
    async def delete_deal(deal_id: str):
        if not pf.delete_deal(deal_id):
            raise HTTPException(404, "Deal not found")
        return {"deleted": True}

    @router.get("/deals/analytics")
    async def deal_analytics():
        return pf.get_deal_analytics()

    # ── SEC EDGAR ───────────────────────────────────────────────────────────────

    @router.get("/edgar/{ticker}/filings")
    async def edgar_filings(
        ticker: str,
        forms: str = Query("10-K,10-Q,8-K", description="Comma-separated form types"),
    ):
        """
        List recent SEC filings for a public company.
        Returns filing dates, accession numbers, and direct EDGAR viewer links.
        """
        from orchestra.code_agent.finance.edgar import filings_summary
        form_list = [f.strip() for f in forms.split(",") if f.strip()]
        try:
            return await filings_summary(ticker, form_types=form_list or None)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"EDGAR fetch failed: {e}")

    @router.get("/edgar/{ticker}/financials")
    async def edgar_financials(ticker: str):
        """
        Pull 5-year XBRL financial history: revenue, net income, EPS, assets, equity, FCF.
        Data comes directly from SEC EDGAR — no third-party data vendor required.
        """
        from orchestra.code_agent.finance.edgar import key_financials
        try:
            return await key_financials(ticker)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"EDGAR fetch failed: {e}")

    @router.get("/edgar/{ticker}/cik")
    async def edgar_cik(ticker: str):
        """Resolve a ticker to its SEC CIK number."""
        from orchestra.code_agent.finance.edgar import ticker_to_cik
        cik = ticker_to_cik(ticker)
        if not cik:
            raise HTTPException(status_code=404, detail=f"Ticker '{ticker}' not found in SEC database")
        return {"ticker": ticker.upper(), "cik": cik, "edgar_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"}

    # ── LBO / PE Returns ─────────────────────────────────────────────────────

    @router.post("/lbo")
    async def lbo_model(body: dict[str, Any]):
        """
        Full LBO model with debt schedule, operating projections, and returns.

        Required: revenue, ebitda_margin, entry_multiple, debt_ebitda
        Optional: interest_rate, amort_pct, cash_sweep, revenue_growth,
                  margin_expansion, capex_pct_rev, tax_rate, hold_years,
                  exit_multiple, mgmt_fee_pct, transaction_costs
        """
        from orchestra.code_agent.finance.lbo import LBOInputs, run_lbo
        from dataclasses import asdict
        required = ("revenue", "ebitda_margin", "entry_multiple", "debt_ebitda")
        missing = [k for k in required if k not in body]
        if missing:
            raise HTTPException(400, f"Missing required fields: {missing}")
        try:
            inp = LBOInputs(**{k: v for k, v in body.items() if k in LBOInputs.__dataclass_fields__})
            result = run_lbo(inp)
            return {
                "summary": {
                    "entry_ev": result.entry_ev,
                    "entry_ebitda": result.entry_ebitda,
                    "entry_debt": result.entry_debt,
                    "total_equity_invested": result.total_equity_invested,
                    "exit_ebitda": result.exit_ebitda,
                    "exit_ev": result.exit_ev,
                    "exit_debt": result.exit_debt,
                    "net_exit_equity": result.net_exit_equity,
                    "moic": result.moic,
                    "irr_pct": round(result.irr * 100, 1),
                    "hold_years": result.exit_year,
                },
                "equity_bridge": result.equity_bridge,
                "debt_schedule": result.debt_schedule,
                "projections": [asdict(p) for p in result.projections],
                "sensitivity_moic": result.sensitivity,
            }
        except (TypeError, ValueError) as e:
            raise HTTPException(400, str(e))

    @router.post("/returns")
    async def simple_returns(body: dict[str, Any]):
        """Quick MOIC / IRR for a simple investment (no LBO complexity needed)."""
        from orchestra.code_agent.finance.lbo import simple_returns as _sr
        required = ("invested", "proceeds", "years")
        missing = [k for k in required if k not in body]
        if missing:
            raise HTTPException(400, f"Missing: {missing}")
        return _sr(
            invested=float(body["invested"]),
            proceeds=float(body["proceeds"]),
            years=float(body["years"]),
            dividends=float(body.get("dividends", 0)),
        )

    app.include_router(router)
