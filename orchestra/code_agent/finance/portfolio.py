"""SQLite-backed portfolio and position tracking."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Optional

_DB_PATH = Path.home() / ".orchestra_finance.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH))
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS portfolios (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            benchmark TEXT DEFAULT 'SPY',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            portfolio_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            name TEXT DEFAULT '',
            shares REAL NOT NULL,
            avg_cost REAL NOT NULL,
            asset_class TEXT DEFAULT 'equity',
            sector TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            opened_date TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS port_transactions (
            id TEXT PRIMARY KEY,
            portfolio_id TEXT NOT NULL,
            ticker TEXT NOT NULL,
            type TEXT NOT NULL,
            shares REAL DEFAULT 0,
            price REAL DEFAULT 0,
            amount REAL DEFAULT 0,
            date TEXT NOT NULL,
            notes TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deals (
            id TEXT PRIMARY KEY,
            company TEXT NOT NULL,
            sector TEXT DEFAULT '',
            stage TEXT DEFAULT 'sourcing',
            size_m REAL DEFAULT 0,
            ev_multiple REAL DEFAULT 0,
            source TEXT DEFAULT '',
            lead TEXT DEFAULT '',
            description TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            next_step TEXT DEFAULT '',
            next_step_date TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)


def _now() -> str:
    return datetime.utcnow().isoformat()


def _today() -> str:
    return date.today().isoformat()


# ── Portfolios ────────────────────────────────────────────────────────────────

def create_portfolio(data: dict) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "name": data["name"],
        "description": data.get("description", ""),
        "benchmark": data.get("benchmark", "SPY"),
        "created_at": _now(),
    }
    with _conn() as c:
        c.execute("INSERT INTO portfolios VALUES (:id,:name,:description,:benchmark,:created_at)", row)
    return row


def list_portfolios() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM portfolios ORDER BY created_at").fetchall()]


def get_portfolio(pid: str) -> Optional[dict]:
    with _conn() as c:
        r = c.execute("SELECT * FROM portfolios WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


# ── Positions ─────────────────────────────────────────────────────────────────

def upsert_position(data: dict) -> dict:
    """Create or update a position (buy more shares = recalculate avg cost)."""
    pid = data["portfolio_id"]
    ticker = data["ticker"].upper()
    shares = float(data["shares"])
    cost = float(data["avg_cost"])

    with _conn() as c:
        existing = c.execute(
            "SELECT * FROM positions WHERE portfolio_id=? AND ticker=?", (pid, ticker)
        ).fetchone()
        if existing:
            old_shares = existing["shares"]
            old_cost = existing["avg_cost"]
            new_shares = old_shares + shares
            new_cost = ((old_shares * old_cost) + (shares * cost)) / new_shares if new_shares else cost
            c.execute(
                "UPDATE positions SET shares=?, avg_cost=? WHERE id=?",
                (new_shares, new_cost, existing["id"]),
            )
            row = dict(existing)
            row["shares"] = new_shares
            row["avg_cost"] = new_cost
        else:
            row = {
                "id": str(uuid.uuid4()),
                "portfolio_id": pid,
                "ticker": ticker,
                "name": data.get("name", ""),
                "shares": shares,
                "avg_cost": cost,
                "asset_class": data.get("asset_class", "equity"),
                "sector": data.get("sector", ""),
                "notes": data.get("notes", ""),
                "opened_date": data.get("opened_date", _today()),
                "created_at": _now(),
            }
            c.execute(
                "INSERT INTO positions VALUES (:id,:portfolio_id,:ticker,:name,:shares,:avg_cost,:asset_class,:sector,:notes,:opened_date,:created_at)",
                row,
            )
    return row


def list_positions(portfolio_id: str) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM positions WHERE portfolio_id=? ORDER BY ticker", (portfolio_id,)
        ).fetchall()]


def update_position(pos_id: str, data: dict) -> Optional[dict]:
    allowed = {"shares", "avg_cost", "name", "asset_class", "sector", "notes"}
    fields = {k: v for k, v in data.items() if k in allowed}
    if not fields:
        return None
    sql = ", ".join(f"{k}=?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE positions SET {sql} WHERE id=?", (*fields.values(), pos_id))
        r = c.execute("SELECT * FROM positions WHERE id=?", (pos_id,)).fetchone()
    return dict(r) if r else None


def delete_position(pos_id: str) -> bool:
    with _conn() as c:
        return c.execute("DELETE FROM positions WHERE id=?", (pos_id,)).rowcount > 0


def add_transaction(data: dict) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "portfolio_id": data["portfolio_id"],
        "ticker": data["ticker"].upper(),
        "type": data["type"],  # buy / sell / dividend
        "shares": float(data.get("shares", 0)),
        "price": float(data.get("price", 0)),
        "amount": float(data.get("amount", 0)),
        "date": data.get("date", _today()),
        "notes": data.get("notes", ""),
        "created_at": _now(),
    }
    with _conn() as c:
        c.execute(
            "INSERT INTO port_transactions VALUES (:id,:portfolio_id,:ticker,:type,:shares,:price,:amount,:date,:notes,:created_at)",
            row,
        )
    return row


def list_transactions(portfolio_id: str, ticker: str = "") -> list[dict]:
    with _conn() as c:
        if ticker:
            rows = c.execute(
                "SELECT * FROM port_transactions WHERE portfolio_id=? AND ticker=? ORDER BY date DESC",
                (portfolio_id, ticker.upper()),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM port_transactions WHERE portfolio_id=? ORDER BY date DESC",
                (portfolio_id,),
            ).fetchall()
    return [dict(r) for r in rows]


# ── Deal Flow ─────────────────────────────────────────────────────────────────

def create_deal(data: dict) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "company": data["company"],
        "sector": data.get("sector", ""),
        "stage": data.get("stage", "sourcing"),
        "size_m": float(data.get("size_m", 0)),
        "ev_multiple": float(data.get("ev_multiple", 0)),
        "source": data.get("source", ""),
        "lead": data.get("lead", ""),
        "description": data.get("description", ""),
        "status": data.get("status", "active"),
        "next_step": data.get("next_step", ""),
        "next_step_date": data.get("next_step_date", ""),
        "created_at": _now(),
        "updated_at": _now(),
    }
    with _conn() as c:
        c.execute(
            "INSERT INTO deals VALUES (:id,:company,:sector,:stage,:size_m,:ev_multiple,:source,:lead,:description,:status,:next_step,:next_step_date,:created_at,:updated_at)",
            row,
        )
    return row


def list_deals(stage: str = "", status: str = "active") -> list[dict]:
    wheres, params = [], []
    if stage:
        wheres.append("stage=?"); params.append(stage)
    if status:
        wheres.append("status=?"); params.append(status)
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""
    with _conn() as c:
        return [dict(r) for r in c.execute(
            f"SELECT * FROM deals {where_sql} ORDER BY updated_at DESC", params
        ).fetchall()]


def update_deal(deal_id: str, data: dict) -> Optional[dict]:
    allowed = {"company","sector","stage","size_m","ev_multiple","source","lead",
               "description","status","next_step","next_step_date"}
    fields = {k: v for k, v in data.items() if k in allowed}
    fields["updated_at"] = _now()
    sql = ", ".join(f"{k}=?" for k in fields)
    with _conn() as c:
        c.execute(f"UPDATE deals SET {sql} WHERE id=?", (*fields.values(), deal_id))
        r = c.execute("SELECT * FROM deals WHERE id=?", (deal_id,)).fetchone()
    return dict(r) if r else None


def delete_deal(deal_id: str) -> bool:
    with _conn() as c:
        return c.execute("DELETE FROM deals WHERE id=?", (deal_id,)).rowcount > 0


def get_deal_analytics() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM deals WHERE status='active'").fetchone()[0]
        by_stage = {r["stage"]: r["cnt"] for r in c.execute(
            "SELECT stage, COUNT(*) as cnt FROM deals WHERE status='active' GROUP BY stage"
        ).fetchall()}
        total_size = c.execute("SELECT COALESCE(SUM(size_m),0) FROM deals WHERE status='active'").fetchone()[0]
        closed_size = c.execute("SELECT COALESCE(SUM(size_m),0) FROM deals WHERE stage='closed'").fetchone()[0]
    return {
        "total_active": total,
        "by_stage": by_stage,
        "total_pipeline_m": round(float(total_size), 1),
        "closed_size_m": round(float(closed_size), 1),
    }
