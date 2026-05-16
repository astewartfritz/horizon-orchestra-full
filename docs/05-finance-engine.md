# Finance Engine — Dashboards & Spreadsheets

> **Module:** `src/code_agent/finance/` (65 tests) + `channels/ts/src/finance/orchestrator.ts`

AI-native finance platform with double-entry ledger, formula engine with Excel + AI-native syntax, time-series analytics, Monte Carlo simulation, and CFO copilot.

---

## Architecture

```
Web Dashboard (/finance/app)
  │ REST API
  ▼
Python Finance Engine
  ├── FormulaEngine     (DSL parser + dependency graph)
  ├── TransactionEngine (double-entry ledger)
  ├── LedgerEngine      (DuckDB HTAP)
  ├── AnalyticsEngine   (forecasting + Monte Carlo + scenarios)
  ├── FinanceBrain      (AI insights + CFO copilot)
  └── EventBus          (Kafka-style pub/sub)
  │
  ▼
TypeScript Orchestrator (channels/ts/src/finance/orchestrator.ts)
  Formula routing, cache, event dispatch
```

---

## Formula Engine — `formula.py`

### Supported Functions

| Category | Functions |
|----------|-----------|
| **Standard** | `SUM`, `AVG`, `MAX`, `MIN`, `COUNT`, `STDEV` |
| **Logical** | `IF(condition, true_val, false_val)` |
| **Math** | `ROUND`, `ABS`, +, -, *, /, ^, %, <, >, = |
| **Finance** | `NPV`, `PMT`, `FV`, `CAGR` (WiP) |
| **AI-native** | `AI_PROJECT(metric, scenario, horizon=N)`, `EXPLAIN_VARIANCE(actual, forecast)`, `FORECAST(metric, periods)`, `RISK_ANALYSIS(portfolio, volatility)` |

### Cell References & Ranges
```
=A1            # Single cell
=SUM(A1:A5)    # Range
=IF(B1>100, C1, D1)  # Conditional
=A1+B1*C1      # Operator precedence
```

### Dependency Graph
- Tracks cell dependencies for incremental recalculation
- Topological sort for correct evaluation order
- Auto-recalculate on dependency changes

```python
engine = FormulaEngine()
engine.set_cell("A1", value=10)
engine.set_cell("B1", formula="=A1*2")  # → 20
engine.set_cell("A1", value=50)
engine.recalc({"A1"})  # → B1 becomes 100
```

---

## Transaction Engine — `ledger.py`

Double-entry bookkeeping with balance validation.

```python
tx_engine = TransactionEngine()
cash = tx_engine.create_account("1000", "Cash", AccountType.ASSET)
rev = tx_engine.create_account("4000", "Revenue", AccountType.REVENUE)
tx = tx_engine.record_double_entry("2026-01-15", "Consulting revenue",
                                    cash.id, rev.id, 5000)
# tx.is_balanced → True

# Trial balance
tx_engine.get_trial_balance()
# {"total_debits": 5000, "total_credits": 5000, "balanced": true}

# Financial statements
stmt = tx_engine.get_statement("2026-Q1")
# stmt.revenue, stmt.expenses, stmt.gross_profit, stmt.profit_margin
```

### HTAP Queries (DuckDB)

```python
ledger = LedgerEngine(tx_engine)
ledger.aggregate_by_account()
ledger.aggregate_by_period("month")
ledger.top_accounts(limit=10)
```

### Reconciliation

```python
reconciler = Reconciliator(tx_engine)
result = reconciler.reconcile(cash.id, expected_balance=4800.0)
# {"is_reconciled": false, "difference": -200.0}
tx = reconciler.auto_reconcile(cash.id, 4800.0)  # creates adjustment entry
```

---

## Analytics Engine — `analytics.py`

| Feature | Method | Parameters |
|---------|--------|------------|
| Time-series forecast | `exponential`, `linear`, `moving_average` | Historical data, horizon |
| Seasonal decompose | Additive model | Period |
| Monte Carlo | Geometric Brownian motion | Base value, volatility, steps, sims |
| Value at Risk | 95% / 99% confidence | Portfolio value, volatility |
| What-if scenarios | Bullish, moderate, cost-optimized, downturn | Base statement |

```python
analytics = AnalyticsEngine()
analytics.forecast_revenue([100, 110, 120, 130], horizon=3, method="exponential")
analytics.monte_carlo_projection(base_revenue=100000, volatility=0.15, steps=12, sims=1000)
analytics.what_if_scenarios(statement)
analytics.risk_analysis(portfolio_value=500000, volatility=0.2)
```

---

## Finance Brain — `brain.py`

AI-powered financial insights and CFO copilot.

```python
brain = FinanceBrain()
insights = brain.generate_insights(statement)
# [CFOInsight("Low Profit Margin", severity="warning"), ...]

# AI formula functions (registered with FormulaEngine)
# =AI_PROJECT("revenue", "market_downturn", horizon=12)
# =EXPLAIN_VARIANCE(QTD_actual, QTD_forecast)

# LLM-powered analysis
result = await brain.llm_analyze("What is our cash flow trend?", context={...})
```

### Insight Categories

| Category | Triggers | Severity |
|----------|----------|----------|
| Profitability | Margin < 5% or > 20% | warning/info |
| Growth | Revenue/expense ratio < 1.2 | critical |
| Liquidity | Asset/liability ratio < 1.5 | warning |
| Efficiency | Negative net income | critical |

---

## Event Bus — `events.py`

Kafka-style pub/sub for financial events.

```python
bus = EventBus()

async def handler(event):
    print(f"Received: {event.event_type}")

bus.subscribe("tx.created", handler)
bus.subscribe_all(wildcard_handler)

await bus.publish(FinanceEvent(event_type="tx.created", data={"amount": 5000}))
await bus.publish_tx(transaction)  # convenience method

bus.replay("tx.created", limit=50)
bus.stats()  # total events, subscribers, per-type counts
```

## API Routes — `routes.py`

18 REST endpoints under `/api/finance/`:
- Accounts: POST create, GET list, GET balance
- Transactions: POST record, GET query
- Ledger: GET trial balance
- Statements: GET financial statements
- Reconciliation: POST reconcile, POST auto-reconcile
- Formulas: POST evaluate, POST bulk
- Analytics: POST forecast, Monte Carlo, scenarios, risk
- Brain: POST insights, POST query, GET summary
- Events: GET stats, GET replay

---

## TypeScript Orchestrator

`channels/ts/src/finance/orchestrator.ts` provides:
- Formula evaluation with caching (TTL-based)
- Bulk formula recalculation
- Transaction recording
- AI query proxying
- Event bus monitoring
- Fallback client-side formula eval when Python backend unavailable

## Frontend — `/finance/app`

3-tab dashboard:
| Tab | Content |
|-----|---------|
| **Dashboard** | 4 KPI cards, 3 Canvas charts (bar/pie/line), transactions table, Add Transaction button, CSV export |
| **Spreadsheet** | 12×7 editable grid, formula bar with cell ref display, =SUM/=AVG/=MAX/=MIN/=COUNT + AI_PROJECT/EXPLAIN_VARIANCE/FORECAST/RISK_ANALYSIS, add row/col, CSV export |
| **Insights** | CFO Copilot chat, AI insights list, what-if scenarios, forecast + risk display, AI formula reference |

---

## Test Coverage (65 tests)

- Models: Account auto-ID, Transaction balanced/unbalanced, FinancialStatement profit-margin/debt-to-equity/zero-division, SheetCell numeric-value/has-formula, SheetRange sum/avg/max/min/empty
- CellRef: parse A1/Z100/AA1, to_string, invalid
- DependencyGraph: add/get/recalc-order/remove/clear
- FormulaParser: plain, SUM/AVG/MAX/MIN/COUNT, IF true/false, arithmetic, div-by-zero, ABS, ROUND
- FormulaEngine: set/get, formula, recalc, grid, clear
- TransactionEngine: create/record/double-entry/balance/query/statement/trial-balance/export
- Reconciliator: match/mismatch
- Analytics: moving avg, exponential, linear regression, seasonal, Monte Carlo, VaR, scenarios, growth
- FinanceBrain: insights/severity/summary
- EventBus: publish/subscribe/wildcard/replay/stats
