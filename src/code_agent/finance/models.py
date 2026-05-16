"""Data models for the Orchestra Finance engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any


class AccountType(Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    REVENUE = "revenue"
    EXPENSE = "expense"


class TransactionType(Enum):
    DEBIT = "debit"
    CREDIT = "credit"
    TRANSFER = "transfer"
    JOURNAL = "journal"
    RECONCILIATION = "reconciliation"


class SheetValueType(Enum):
    STRING = "string"
    NUMBER = "number"
    FORMULA = "formula"
    DATE = "date"
    CURRENCY = "currency"
    PERCENTAGE = "percentage"
    BOOLEAN = "boolean"
    ERROR = "error"


@dataclass
class Account:
    id: str = ""
    code: str = ""
    name: str = ""
    type: AccountType = AccountType.ASSET
    parent_id: str = ""
    currency: str = "USD"
    description: str = ""
    is_active: bool = True

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]


@dataclass
class Transaction:
    id: str = ""
    date: str = ""
    description: str = ""
    type: TransactionType = TransactionType.JOURNAL
    entries: list[LedgerEntry] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    @property
    def is_balanced(self) -> bool:
        return abs(self.debit_total - self.credit_total) < 0.001

    @property
    def debit_total(self) -> float:
        return sum(e.amount for e in self.entries if e.direction == "debit")

    @property
    def credit_total(self) -> float:
        return sum(e.amount for e in self.entries if e.direction == "credit")


@dataclass
class LedgerEntry:
    account_id: str
    account_name: str = ""
    amount: float = 0.0
    direction: str = "debit"  # debit or credit
    currency: str = "USD"
    description: str = ""


@dataclass
class FinancialStatement:
    period: str = ""
    revenue: float = 0.0
    expenses: float = 0.0
    gross_profit: float = 0.0
    operating_income: float = 0.0
    net_income: float = 0.0
    total_assets: float = 0.0
    total_liabilities: float = 0.0
    equity: float = 0.0
    cash_flow_operating: float = 0.0
    cash_flow_investing: float = 0.0
    cash_flow_financing: float = 0.0

    @property
    def profit_margin(self) -> float:
        return (self.net_income / self.revenue * 100) if self.revenue else 0.0

    @property
    def debt_to_equity(self) -> float:
        return self.total_liabilities / self.equity if self.equity else 0.0


@dataclass
class SheetCell:
    ref: str = ""           # "A1", "B2"
    value: Any = ""
    value_type: SheetValueType = SheetValueType.STRING
    formula: str = ""       # Raw formula string like "=SUM(A1:A5)"
    formatted: str = ""     # Display value
    dependencies: list[str] = field(default_factory=list)  # Cells this depends on
    dependents: list[str] = field(default_factory=list)    # Cells that depend on this
    style: dict[str, Any] = field(default_factory=dict)
    ai_generated: bool = False
    last_updated: str = ""

    @property
    def has_formula(self) -> bool:
        return bool(self.formula)

    @property
    def numeric_value(self) -> float:
        try:
            return float(self.value) if self.value else 0.0
        except (ValueError, TypeError):
            return 0.0


@dataclass
class SheetRange:
    start_ref: str = ""
    end_ref: str = ""
    cells: list[SheetCell] = field(default_factory=list)

    @property
    def values(self) -> list[Any]:
        return [c.value for c in self.cells]

    @property
    def numeric_values(self) -> list[float]:
        return [c.numeric_value for c in self.cells]

    @property
    def sum(self) -> float:
        return sum(self.numeric_values)

    @property
    def avg(self) -> float:
        v = self.numeric_values
        return sum(v) / len(v) if v else 0.0

    @property
    def max(self) -> float:
        return max(self.numeric_values) if self.numeric_values else 0.0

    @property
    def min(self) -> float:
        return min(self.numeric_values) if self.numeric_values else 0.0
