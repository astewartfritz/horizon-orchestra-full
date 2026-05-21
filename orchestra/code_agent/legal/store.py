from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from orchestra.code_agent.legal.models import Client, Matter, TimeEntry, Invoice, TrustEntry

_DB_PATH = Path.home() / ".orchestra_legal.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


def _strip(row, *exclude: str) -> dict:
    """Convert a Row to dict, dropping internal columns."""
    keys_to_drop = set(exclude) | {"created_by"}
    return {k: v for k, v in dict(row).items() if k not in keys_to_drop}


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS clients (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            company TEXT DEFAULT '',
            address TEXT DEFAULT '',
            client_since TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS matters (
            id TEXT PRIMARY KEY,
            matter_number TEXT UNIQUE NOT NULL,
            client_id TEXT NOT NULL,
            title TEXT NOT NULL,
            matter_type TEXT DEFAULT 'other',
            status TEXT DEFAULT 'open',
            fee_arrangement TEXT DEFAULT 'hourly',
            hourly_rate REAL DEFAULT 350.0,
            flat_fee REAL DEFAULT 0.0,
            contingency_pct REAL DEFAULT 0.33,
            retainer_amount REAL DEFAULT 0.0,
            retainer_balance REAL DEFAULT 0.0,
            responsible_attorney TEXT DEFAULT '',
            description TEXT DEFAULT '',
            opposing_party TEXT DEFAULT '',
            court_jurisdiction TEXT DEFAULT '',
            statute_of_limitations TEXT DEFAULT '',
            opened_date TEXT DEFAULT '',
            closed_date TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS time_entries (
            id TEXT PRIMARY KEY,
            matter_id TEXT NOT NULL,
            date TEXT NOT NULL,
            attorney TEXT DEFAULT '',
            hours REAL NOT NULL,
            rate REAL NOT NULL,
            description TEXT NOT NULL,
            activity_code TEXT DEFAULT 'GEN',
            billed INTEGER DEFAULT 0,
            invoice_id TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invoices (
            id TEXT PRIMARY KEY,
            matter_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            invoice_number TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'draft',
            issue_date TEXT DEFAULT '',
            due_date TEXT DEFAULT '',
            subtotal REAL DEFAULT 0.0,
            tax REAL DEFAULT 0.0,
            total REAL DEFAULT 0.0,
            paid_amount REAL DEFAULT 0.0,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS trust_entries (
            id TEXT PRIMARY KEY,
            matter_id TEXT NOT NULL,
            client_id TEXT NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT NOT NULL,
            balance_after REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        );
        """)
        # Idempotent: add created_by to existing tables
        for _t in ("clients", "matters", "time_entries", "invoices"):
            try:
                c.execute(f"ALTER TABLE {_t} ADD COLUMN created_by TEXT NOT NULL DEFAULT ''")
                c.commit()
            except Exception:
                pass


def _now() -> str:
    return datetime.utcnow().isoformat()


def _today() -> str:
    return date.today().isoformat()


# ── Clients ───────────────────────────────────────────────────────────────────

def create_client(data: dict, user_id: str = "") -> Client:
    c = Client(
        id=str(uuid.uuid4()),
        name=data["name"],
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        company=data.get("company", ""),
        address=data.get("address", ""),
        client_since=data.get("client_since", _today()),
        notes=data.get("notes", ""),
        created_at=_now(),
    )
    with _conn() as conn:
        conn.execute(
            """INSERT INTO clients (id,name,email,phone,company,address,client_since,notes,created_at,created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (c.id, c.name, c.email, c.phone, c.company, c.address, c.client_since, c.notes, c.created_at, user_id),
        )
    return c


def get_client(client_id: str) -> Optional[Client]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    return Client(**_strip(row)) if row else None


def list_clients(search: str = "", user_id: str = "") -> list[Client]:
    clauses, params = [], []
    if user_id:
        clauses.append("created_by=?"); params.append(user_id)
    if search:
        clauses.append("(name LIKE ? OR company LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%"])
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with _conn() as conn:
        rows = conn.execute(f"SELECT * FROM clients {where} ORDER BY name", params).fetchall()
    return [Client(**_strip(r)) for r in rows]


def update_client(client_id: str, data: dict) -> Optional[Client]:
    fields = {k: v for k, v in data.items() if k in ("name","email","phone","company","address","notes")}
    if not fields:
        return get_client(client_id)
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with _conn() as conn:
        conn.execute(f"UPDATE clients SET {set_clause} WHERE id=?", (*fields.values(), client_id))
    return get_client(client_id)


# ── Matters ───────────────────────────────────────────────────────────────────

def _next_matter_number() -> str:
    with _conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM matters").fetchone()
    n = (row[0] or 0) + 1
    return f"M-{n:05d}"


def create_matter(data: dict, user_id: str = "") -> Matter:
    m = Matter(
        id=str(uuid.uuid4()),
        matter_number=data.get("matter_number") or _next_matter_number(),
        client_id=data["client_id"],
        title=data["title"],
        matter_type=data.get("matter_type", "other"),
        status=data.get("status", "open"),
        fee_arrangement=data.get("fee_arrangement", "hourly"),
        hourly_rate=float(data.get("hourly_rate", 350.0)),
        flat_fee=float(data.get("flat_fee", 0.0)),
        contingency_pct=float(data.get("contingency_pct", 0.33)),
        retainer_amount=float(data.get("retainer_amount", 0.0)),
        retainer_balance=float(data.get("retainer_balance", 0.0)),
        responsible_attorney=data.get("responsible_attorney", ""),
        description=data.get("description", ""),
        opposing_party=data.get("opposing_party", ""),
        court_jurisdiction=data.get("court_jurisdiction", ""),
        statute_of_limitations=data.get("statute_of_limitations", ""),
        opened_date=data.get("opened_date", _today()),
        closed_date=data.get("closed_date", ""),
        created_at=_now(),
    )
    with _conn() as conn:
        conn.execute(
            """INSERT INTO matters
               (id,matter_number,client_id,title,matter_type,status,fee_arrangement,
                hourly_rate,flat_fee,contingency_pct,retainer_amount,retainer_balance,
                responsible_attorney,description,opposing_party,court_jurisdiction,
                statute_of_limitations,opened_date,closed_date,created_at,created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (m.id, m.matter_number, m.client_id, m.title, m.matter_type, m.status,
             m.fee_arrangement, m.hourly_rate, m.flat_fee, m.contingency_pct,
             m.retainer_amount, m.retainer_balance, m.responsible_attorney,
             m.description, m.opposing_party, m.court_jurisdiction,
             m.statute_of_limitations, m.opened_date, m.closed_date, m.created_at, user_id),
        )
    return m


def get_matter(matter_id: str) -> Optional[Matter]:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM matters WHERE id=?", (matter_id,)).fetchone()
    return Matter(**_strip(row)) if row else None


def list_matters(status: str = "", client_id: str = "", search: str = "", user_id: str = "") -> list[Matter]:
    wheres, params = [], []
    if user_id:
        wheres.append("created_by=?"); params.append(user_id)
    if status:
        wheres.append("status=?"); params.append(status)
    if client_id:
        wheres.append("client_id=?"); params.append(client_id)
    if search:
        wheres.append("(title LIKE ? OR matter_number LIKE ?)"); params += [f"%{search}%", f"%{search}%"]
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    with _conn() as conn:
        rows = conn.execute(f"SELECT * FROM matters {where_sql} ORDER BY created_at DESC", params).fetchall()
    return [Matter(**_strip(r)) for r in rows]


def update_matter(matter_id: str, data: dict) -> Optional[Matter]:
    allowed = {"title","matter_type","status","fee_arrangement","hourly_rate","flat_fee",
               "contingency_pct","retainer_amount","retainer_balance","responsible_attorney",
               "description","opposing_party","court_jurisdiction","statute_of_limitations",
               "opened_date","closed_date"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return get_matter(matter_id)
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with _conn() as conn:
        conn.execute(f"UPDATE matters SET {set_clause} WHERE id=?", (*fields.values(), matter_id))
    return get_matter(matter_id)


# ── Time Entries ──────────────────────────────────────────────────────────────

def create_time_entry(data: dict) -> TimeEntry:
    te = TimeEntry(
        id=str(uuid.uuid4()),
        matter_id=data["matter_id"],
        date=data.get("date", _today()),
        attorney=data.get("attorney", ""),
        hours=float(data["hours"]),
        rate=float(data.get("rate", 350.0)),
        description=data["description"],
        activity_code=data.get("activity_code", "GEN"),
        billed=bool(data.get("billed", False)),
        invoice_id=data.get("invoice_id", ""),
        created_at=_now(),
    )
    with _conn() as conn:
        conn.execute(
            "INSERT INTO time_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (te.id, te.matter_id, te.date, te.attorney, te.hours, te.rate,
             te.description, te.activity_code, int(te.billed), te.invoice_id, te.created_at),
        )
    return te


def list_time_entries(matter_id: str = "", billed: Optional[bool] = None) -> list[TimeEntry]:
    wheres, params = [], []
    if matter_id:
        wheres.append("matter_id=?"); params.append(matter_id)
    if billed is not None:
        wheres.append("billed=?"); params.append(int(billed))
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    with _conn() as conn:
        rows = conn.execute(f"SELECT * FROM time_entries {where_sql} ORDER BY date DESC", params).fetchall()
    return [TimeEntry(billed=bool(r["billed"]), **{k: v for k, v in dict(r).items() if k != "billed"}) for r in rows]


def update_time_entry(entry_id: str, data: dict) -> Optional[TimeEntry]:
    allowed = {"date","attorney","hours","rate","description","activity_code","billed","invoice_id"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return None
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with _conn() as conn:
        conn.execute(f"UPDATE time_entries SET {set_clause} WHERE id=?", (*fields.values(), entry_id))
    with _conn() as conn:
        row = conn.execute("SELECT * FROM time_entries WHERE id=?", (entry_id,)).fetchone()
    return TimeEntry(billed=bool(row["billed"]), **{k: v for k, v in dict(row).items() if k != "billed"}) if row else None


def delete_time_entry(entry_id: str) -> bool:
    with _conn() as conn:
        c = conn.execute("DELETE FROM time_entries WHERE id=?", (entry_id,))
    return c.rowcount > 0


# ── Invoices ──────────────────────────────────────────────────────────────────

def _next_invoice_number() -> str:
    with _conn() as conn:
        row = conn.execute("SELECT COUNT(*) FROM invoices").fetchone()
    n = (row[0] or 0) + 1
    return f"INV-{n:05d}"


def create_invoice_from_matter(matter_id: str) -> Invoice:
    """Bundle all unbilled time entries for a matter into a new draft invoice."""
    entries = list_time_entries(matter_id=matter_id, billed=False)
    matter = get_matter(matter_id)
    if not matter:
        raise ValueError(f"Matter {matter_id} not found")
    subtotal = sum(e.hours * e.rate for e in entries)
    now = _now(); today = _today()
    inv = Invoice(
        id=str(uuid.uuid4()),
        matter_id=matter_id,
        client_id=matter.client_id,
        invoice_number=_next_invoice_number(),
        status="draft",
        issue_date=today,
        due_date="",
        subtotal=round(subtotal, 2),
        tax=0.0,
        total=round(subtotal, 2),
        paid_amount=0.0,
        notes="",
        created_at=now,
    )
    with _conn() as conn:
        conn.execute(
            "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (inv.id, inv.matter_id, inv.client_id, inv.invoice_number, inv.status,
             inv.issue_date, inv.due_date, inv.subtotal, inv.tax, inv.total,
             inv.paid_amount, inv.notes, inv.created_at),
        )
        if entries:
            conn.executemany(
                "UPDATE time_entries SET billed=1, invoice_id=? WHERE id=?",
                [(inv.id, e.id) for e in entries],
            )
    return inv


def list_invoices(status: str = "", matter_id: str = "") -> list[Invoice]:
    wheres, params = [], []
    if status:
        wheres.append("status=?"); params.append(status)
    if matter_id:
        wheres.append("matter_id=?"); params.append(matter_id)
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    with _conn() as conn:
        rows = conn.execute(f"SELECT * FROM invoices {where_sql} ORDER BY created_at DESC", params).fetchall()
    return [Invoice(**dict(r)) for r in rows]


def update_invoice(invoice_id: str, data: dict) -> Optional[Invoice]:
    allowed = {"status","issue_date","due_date","subtotal","tax","total","paid_amount","notes"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return None
    set_clause = ", ".join(f"{k}=?" for k in fields)
    with _conn() as conn:
        conn.execute(f"UPDATE invoices SET {set_clause} WHERE id=?", (*fields.values(), invoice_id))
    with _conn() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    return Invoice(**dict(row)) if row else None


# ── Trust Ledger ──────────────────────────────────────────────────────────────

def add_trust_entry(data: dict) -> TrustEntry:
    matter = get_matter(data["matter_id"])
    if not matter:
        raise ValueError("Matter not found")
    amount = float(data["amount"])
    with _conn() as conn:
        row = conn.execute(
            "SELECT SUM(amount) FROM trust_entries WHERE matter_id=?", (data["matter_id"],)
        ).fetchone()
        current_balance = float(row[0] or 0.0)
    new_balance = round(current_balance + amount, 2)
    te = TrustEntry(
        id=str(uuid.uuid4()),
        matter_id=data["matter_id"],
        client_id=matter.client_id,
        date=data.get("date", _today()),
        amount=amount,
        description=data.get("description", ""),
        balance_after=new_balance,
        created_at=_now(),
    )
    with _conn() as conn:
        conn.execute(
            "INSERT INTO trust_entries VALUES (?,?,?,?,?,?,?,?)",
            (te.id, te.matter_id, te.client_id, te.date, te.amount,
             te.description, te.balance_after, te.created_at),
        )
        conn.execute(
            "UPDATE matters SET retainer_balance=? WHERE id=?",
            (new_balance, data["matter_id"]),
        )
    return te


def list_trust_entries(matter_id: str = "") -> list[TrustEntry]:
    where = "WHERE matter_id=?" if matter_id else ""
    params = [matter_id] if matter_id else []
    with _conn() as conn:
        rows = conn.execute(f"SELECT * FROM trust_entries {where} ORDER BY date DESC", params).fetchall()
    return [TrustEntry(**dict(r)) for r in rows]


# ── Analytics ────────────────────────────────────────────────────────────────

def get_analytics() -> dict:
    with _conn() as conn:
        total_clients = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        open_matters = conn.execute("SELECT COUNT(*) FROM matters WHERE status='open'").fetchone()[0]
        unbilled_hours = conn.execute("SELECT COALESCE(SUM(hours),0) FROM time_entries WHERE billed=0").fetchone()[0]
        unbilled_value = conn.execute("SELECT COALESCE(SUM(hours*rate),0) FROM time_entries WHERE billed=0").fetchone()[0]
        ar_total = conn.execute(
            "SELECT COALESCE(SUM(total-paid_amount),0) FROM invoices WHERE status IN ('sent','overdue')"
        ).fetchone()[0]
        invoiced_mtd = conn.execute(
            f"SELECT COALESCE(SUM(total),0) FROM invoices WHERE issue_date LIKE '{date.today().strftime('%Y-%m')}%'"
        ).fetchone()[0]
        trust_balance = conn.execute("SELECT COALESCE(SUM(amount),0) FROM trust_entries").fetchone()[0]
        recent_matters = conn.execute(
            "SELECT id,matter_number,title,status,matter_type,opened_date FROM matters ORDER BY created_at DESC LIMIT 5"
        ).fetchall()
    return {
        "total_clients": total_clients,
        "open_matters": open_matters,
        "unbilled_hours": round(float(unbilled_hours), 1),
        "unbilled_value": round(float(unbilled_value), 2),
        "ar_total": round(float(ar_total), 2),
        "invoiced_mtd": round(float(invoiced_mtd), 2),
        "trust_balance": round(float(trust_balance), 2),
        "recent_matters": [dict(r) for r in recent_matters],
    }
