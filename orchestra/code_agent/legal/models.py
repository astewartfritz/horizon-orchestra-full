from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class MatterStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    INACTIVE = "inactive"
    PENDING = "pending"


class MatterType(str, Enum):
    LITIGATION = "litigation"
    CORPORATE = "corporate"
    REAL_ESTATE = "real_estate"
    ESTATE_PLANNING = "estate_planning"
    FAMILY = "family"
    CRIMINAL = "criminal"
    IMMIGRATION = "immigration"
    EMPLOYMENT = "employment"
    IP = "ip"
    BANKRUPTCY = "bankruptcy"
    TAX = "tax"
    OTHER = "other"


class FeeArrangement(str, Enum):
    HOURLY = "hourly"
    FLAT_FEE = "flat_fee"
    CONTINGENCY = "contingency"
    RETAINER = "retainer"
    PRO_BONO = "pro_bono"


class InvoiceStatus(str, Enum):
    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    WRITTEN_OFF = "written_off"


@dataclass
class Client:
    id: str
    name: str
    email: str = ""
    phone: str = ""
    company: str = ""
    address: str = ""
    client_since: str = ""
    notes: str = ""
    created_at: str = ""


@dataclass
class Matter:
    id: str
    matter_number: str
    client_id: str
    title: str
    matter_type: str = MatterType.OTHER
    status: str = MatterStatus.OPEN
    fee_arrangement: str = FeeArrangement.HOURLY
    hourly_rate: float = 350.0
    flat_fee: float = 0.0
    contingency_pct: float = 0.33
    retainer_amount: float = 0.0
    retainer_balance: float = 0.0
    responsible_attorney: str = ""
    description: str = ""
    opposing_party: str = ""
    court_jurisdiction: str = ""
    statute_of_limitations: str = ""
    opened_date: str = ""
    closed_date: str = ""
    created_at: str = ""


@dataclass
class TimeEntry:
    id: str
    matter_id: str
    date: str
    attorney: str
    hours: float
    rate: float
    description: str
    activity_code: str = "GEN"
    billed: bool = False
    invoice_id: str = ""
    created_at: str = ""


@dataclass
class Invoice:
    id: str
    matter_id: str
    client_id: str
    invoice_number: str
    status: str = InvoiceStatus.DRAFT
    issue_date: str = ""
    due_date: str = ""
    subtotal: float = 0.0
    tax: float = 0.0
    total: float = 0.0
    paid_amount: float = 0.0
    notes: str = ""
    created_at: str = ""


@dataclass
class TrustEntry:
    id: str
    matter_id: str
    client_id: str
    date: str
    amount: float
    description: str
    balance_after: float = 0.0
    created_at: str = ""
