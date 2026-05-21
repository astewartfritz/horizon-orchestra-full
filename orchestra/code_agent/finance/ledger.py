"""Transaction engine — ledger, HTAP layer, double-entry bookkeeping, reconciliation."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from typing import Any

from orchestra.code_agent.finance.models import (
    Account, AccountType, FinancialStatement, LedgerEntry, Transaction, TransactionType,
)


class TransactionEngine:
    """Core double-entry transaction engine with balance validation."""

    def __init__(self):
        self.transactions: list[Transaction] = []
        self.accounts: dict[str, Account] = {}

    def create_account(self, code: str, name: str, type: AccountType,
                       parent_id: str = "", currency: str = "USD") -> Account:
        acc = Account(code=code, name=name, type=type, parent_id=parent_id, currency=currency)
        self.accounts[acc.id] = acc
        return acc

    def record_transaction(self, date: str, description: str,
                           entries: list[LedgerEntry],
                           type: TransactionType = TransactionType.JOURNAL,
                           tags: list[str] | None = None) -> Transaction:
        tx = Transaction(
            date=date,
            description=description,
            entries=entries,
            type=type,
            tags=tags or [],
        )
        if not tx.is_balanced:
            raise ValueError(f"Transaction not balanced: debits={tx.debit_total:.2f} credits={tx.credit_total:.2f}")
        self.transactions.append(tx)
        return tx

    def record_double_entry(self, date: str, description: str,
                            debit_account_id: str, credit_account_id: str,
                            amount: float, currency: str = "USD") -> Transaction:
        return self.record_transaction(date, description, [
            LedgerEntry(account_id=debit_account_id, amount=amount, direction="debit", currency=currency),
            LedgerEntry(account_id=credit_account_id, amount=amount, direction="credit", currency=currency),
        ])

    def get_account_balance(self, account_id: str) -> float:
        balance = 0.0
        for tx in self.transactions:
            for entry in tx.entries:
                if entry.account_id == account_id:
                    if entry.direction == "debit":
                        balance += entry.amount
                    else:
                        balance -= entry.amount
        return balance

    def get_account_balances(self) -> dict[str, float]:
        return {aid: self.get_account_balance(aid) for aid in self.accounts}

    def get_trial_balance(self) -> dict[str, Any]:
        debits = sum(t.debit_total for t in self.transactions)
        credits = sum(t.credit_total for t in self.transactions)
        return {
            "total_debits": round(debits, 2),
            "total_credits": round(credits, 2),
            "balanced": abs(debits - credits) < 0.001,
            "transaction_count": len(self.transactions),
        }

    def get_statement(self, period: str = "") -> FinancialStatement:
        stmt = FinancialStatement(period=period or "current")
        for tx in self.transactions:
            for entry in tx.entries:
                acc = self.accounts.get(entry.account_id)
                if not acc:
                    continue
                amt = entry.amount if entry.direction == "debit" else -entry.amount
                if acc.type == AccountType.REVENUE:
                    stmt.revenue += amt
                elif acc.type == AccountType.EXPENSE:
                    stmt.expenses += amt
                elif acc.type == AccountType.ASSET:
                    stmt.total_assets += amt
                elif acc.type == AccountType.LIABILITY:
                    stmt.total_liabilities += amt
                elif acc.type == AccountType.EQUITY:
                    stmt.equity += amt
        stmt.revenue = abs(stmt.revenue)
        stmt.expenses = abs(stmt.expenses)
        stmt.gross_profit = stmt.revenue - stmt.expenses
        stmt.operating_income = stmt.gross_profit
        stmt.net_income = stmt.gross_profit
        return stmt

    def query(self, account_id: str | None = None, date_from: str = "",
              date_to: str = "", min_amount: float = 0, max_amount: float = 0,
              tx_type: TransactionType | None = None) -> list[Transaction]:
        results = list(self.transactions)
        if account_id:
            results = [t for t in results if any(e.account_id == account_id for e in t.entries)]
        if date_from:
            results = [t for t in results if t.date >= date_from]
        if date_to:
            results = [t for t in results if t.date <= date_to]
        if min_amount:
            results = [t for t in results if any(e.amount >= min_amount for e in t.entries)]
        if max_amount:
            results = [t for t in results if any(e.amount <= max_amount for e in t.entries)]
        if tx_type:
            results = [t for t in results if t.type == tx_type]
        return results

    def export_ledger(self, format: str = "json") -> Any:
        if format == "json":
            return [{
                "id": t.id, "date": t.date, "description": t.description,
                "type": t.type.value, "entries": [
                    {"account_id": e.account_id, "amount": e.amount, "direction": e.direction}
                    for e in t.entries
                ],
                "tags": t.tags,
            } for t in self.transactions]
        return self.transactions


class LedgerEngine:
    """HTAP-style ledger with DuckDB integration for analytical queries."""

    def __init__(self, transaction_engine: TransactionEngine | None = None):
        self.tx_engine = transaction_engine or TransactionEngine()
        self._duckdb_available = False
        self._init_duckdb()

    def _init_duckdb(self) -> None:
        try:
            import duckdb
            self._duckdb = duckdb.connect(":memory:")
            self._duckdb_available = True
            self._init_schema()
        except ImportError:
            self._duckdb_available = False

    def _init_schema(self) -> None:
        if not self._duckdb_available:
            return
        self._duckdb.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id VARCHAR, date DATE, description VARCHAR, type VARCHAR,
                account_id VARCHAR, amount DOUBLE, direction VARCHAR,
                currency VARCHAR, tags VARCHAR
            )
        """)

    def sync_to_olap(self) -> int:
        if not self._duckdb_available:
            return 0
        self._duckdb.execute("DELETE FROM transactions")
        count = 0
        for tx in self.tx_engine.transactions:
            for entry in tx.entries:
                self._duckdb.execute(
                    "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    [tx.id, tx.date, tx.description, tx.type.value,
                     entry.account_id, entry.amount, entry.direction,
                     entry.currency, json.dumps(tx.tags)],
                )
                count += 1
        return count

    def olap_query(self, sql: str) -> list[Any]:
        if not self._duckdb_available:
            return [{"error": "DuckDB not available"}]
        self.sync_to_olap()
        try:
            result = self._duckdb.execute(sql).fetchall()
            columns = [desc[0] for desc in self._duckdb.description]
            return [dict(zip(columns, row)) for row in result]
        except Exception as e:
            return [{"error": str(e)}]

    def aggregate_by_account(self) -> list[dict[str, Any]]:
        return self.olap_query("""
            SELECT account_id, direction, SUM(amount) as total, COUNT(*) as count
            FROM transactions GROUP BY account_id, direction ORDER BY total DESC
        """)

    def aggregate_by_period(self, period: str = "month") -> list[dict[str, Any]]:
        return self.olap_query(f"""
            SELECT date_trunc('{period}', date) as period,
                   SUM(CASE WHEN direction='debit' THEN amount ELSE 0 END) as debits,
                   SUM(CASE WHEN direction='credit' THEN amount ELSE 0 END) as credits,
                   COUNT(*) as tx_count
            FROM transactions GROUP BY period ORDER BY period
        """)

    def top_accounts(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.olap_query(f"""
            SELECT account_id, SUM(amount) as total, COUNT(*) as count
            FROM transactions GROUP BY account_id ORDER BY total DESC LIMIT {limit}
        """)


class Reconciliator:
    """Reconciles transactions against expected balances."""

    def __init__(self, tx_engine: TransactionEngine):
        self.tx_engine = tx_engine

    def reconcile(self, account_id: str, expected_balance: float,
                  as_of_date: str = "") -> dict[str, Any]:
        actual = self.tx_engine.get_account_balance(account_id)
        diff = round(expected_balance - actual, 2)

        transactions = self.tx_engine.query(account_id=account_id, date_to=as_of_date)
        return {
            "account_id": account_id,
            "expected_balance": expected_balance,
            "actual_balance": actual,
            "difference": diff,
            "is_reconciled": abs(diff) < 0.01,
            "transaction_count": len(transactions),
            "as_of_date": as_of_date or "all",
        }

    def auto_reconcile(self, account_id: str, expected_balance: float,
                       as_of_date: str = "") -> Transaction | None:
        result = self.reconcile(account_id, expected_balance, as_of_date)
        if result["is_reconciled"]:
            return None
        # Create a reconciliation adjustment entry
        return self.tx_engine.record_transaction(
            date=as_of_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            description=f"Auto-reconciliation adjustment for {account_id}",
            entries=[
                LedgerEntry(account_id=account_id, amount=abs(result["difference"]),
                            direction="debit" if result["difference"] > 0 else "credit",
                            description="Reconciliation adjustment"),
            ],
            type=TransactionType.RECONCILIATION,
        )
