"""Watchlist + Alerts — price alerts, earnings alerts, volume spikes.

Persistent watchlists with configurable alert conditions.
Integrates with the notification system for real-time delivery.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["WatchlistManager"]
log = logging.getLogger("orchestra.finance.watchlist")


@dataclass
class Alert:
    id: str
    symbol: str
    condition: str       # price_above, price_below, volume_spike, pct_change
    threshold: float
    triggered: bool = False
    triggered_at: float = 0
    created_at: float = field(default_factory=time.time)


@dataclass
class Watchlist:
    name: str
    symbols: list[str] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


class WatchlistManager:
    """Manage watchlists and alerts."""

    def __init__(self, persist_path: str = "") -> None:
        self._path = Path(persist_path) if persist_path else Path.home() / ".horizon" / "watchlists.json"
        self._watchlists: dict[str, Watchlist] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                for name, wl in data.items():
                    self._watchlists[name] = Watchlist(
                        name=name,
                        symbols=wl.get("symbols", []),
                        alerts=[Alert(**a) for a in wl.get("alerts", [])],
                    )
            except Exception:
                                import logging as _log; _log.getLogger('finance.watchlist').debug('Suppressed exception', exc_info=True)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for name, wl in self._watchlists.items():
            data[name] = {
                "symbols": wl.symbols,
                "alerts": [
                    {"id": a.id, "symbol": a.symbol, "condition": a.condition,
                     "threshold": a.threshold, "triggered": a.triggered,
                     "triggered_at": a.triggered_at, "created_at": a.created_at}
                    for a in wl.alerts
                ],
            }
        self._path.write_text(json.dumps(data, indent=2))

    async def create_watchlist(self, name: str, symbols: list[str]) -> dict[str, Any]:
        self._watchlists[name] = Watchlist(name=name, symbols=symbols)
        self._save()
        return {"created": True, "name": name, "symbols": symbols}

    async def add_symbol(self, watchlist: str, symbol: str) -> dict[str, Any]:
        wl = self._watchlists.get(watchlist)
        if not wl:
            return {"error": f"Watchlist '{watchlist}' not found"}
        if symbol not in wl.symbols:
            wl.symbols.append(symbol)
            self._save()
        return {"added": True, "symbol": symbol, "watchlist": watchlist}

    async def remove_symbol(self, watchlist: str, symbol: str) -> dict[str, Any]:
        wl = self._watchlists.get(watchlist)
        if not wl:
            return {"error": f"Watchlist '{watchlist}' not found"}
        wl.symbols = [s for s in wl.symbols if s != symbol]
        self._save()
        return {"removed": True, "symbol": symbol}

    async def get_watchlist(self, name: str) -> dict[str, Any]:
        """Get a watchlist with live quotes."""
        wl = self._watchlists.get(name)
        if not wl:
            return {"error": f"Watchlist '{name}' not found"}
        # Return symbols — caller can use fin_batch_quotes for live data
        return {
            "name": name,
            "symbols": wl.symbols,
            "alert_count": len(wl.alerts),
            "alerts": [
                {"symbol": a.symbol, "condition": a.condition, "threshold": a.threshold, "triggered": a.triggered}
                for a in wl.alerts
            ],
        }

    async def add_alert(
        self, watchlist: str, symbol: str,
        condition: str, threshold: float,
    ) -> dict[str, Any]:
        """Add a price/volume alert."""
        wl = self._watchlists.get(watchlist)
        if not wl:
            return {"error": f"Watchlist '{watchlist}' not found"}
        alert = Alert(
            id=f"{symbol}_{condition}_{int(time.time())}",
            symbol=symbol, condition=condition, threshold=threshold,
        )
        wl.alerts.append(alert)
        self._save()
        return {"created": True, "alert_id": alert.id, "symbol": symbol, "condition": condition, "threshold": threshold}

    async def check_alerts(self, market_data_engine: Any) -> list[dict[str, Any]]:
        """Check all alerts against current prices. Returns triggered alerts."""
        triggered = []
        for wl in self._watchlists.values():
            for alert in wl.alerts:
                if alert.triggered:
                    continue
                try:
                    quote = await market_data_engine.quote(alert.symbol)
                    price = quote.get("price", 0)
                    volume = quote.get("volume", 0)
                    change_pct = quote.get("change_pct", 0)

                    fire = False
                    if alert.condition == "price_above" and price >= alert.threshold:
                        fire = True
                    elif alert.condition == "price_below" and price <= alert.threshold:
                        fire = True
                    elif alert.condition == "volume_spike" and volume >= alert.threshold:
                        fire = True
                    elif alert.condition == "pct_change" and abs(change_pct) >= alert.threshold:
                        fire = True

                    if fire:
                        alert.triggered = True
                        alert.triggered_at = time.time()
                        triggered.append({
                            "alert_id": alert.id,
                            "symbol": alert.symbol,
                            "condition": alert.condition,
                            "threshold": alert.threshold,
                            "current_price": price,
                            "current_volume": volume,
                            "change_pct": change_pct,
                        })
                except Exception:
                                        import logging as _log; _log.getLogger('finance.watchlist').debug('Suppressed exception', exc_info=True)
        if triggered:
            self._save()
        return triggered

    async def list_watchlists(self) -> list[dict[str, Any]]:
        return [
            {"name": wl.name, "symbols": len(wl.symbols), "alerts": len(wl.alerts)}
            for wl in self._watchlists.values()
        ]

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "fin_create_watchlist", "description": "Create a watchlist with symbols.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}, "symbols": {"type": "array", "items": {"type": "string"}}}, "required": ["name", "symbols"]}}},
            {"type": "function", "function": {"name": "fin_watchlist", "description": "Get a watchlist with its symbols and alerts.", "parameters": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}}},
            {"type": "function", "function": {"name": "fin_add_alert", "description": "Add a price/volume alert to a watchlist.", "parameters": {"type": "object", "properties": {"watchlist": {"type": "string"}, "symbol": {"type": "string"}, "condition": {"type": "string", "enum": ["price_above", "price_below", "volume_spike", "pct_change"]}, "threshold": {"type": "number"}}, "required": ["watchlist", "symbol", "condition", "threshold"]}}},
            {"type": "function", "function": {"name": "fin_list_watchlists", "description": "List all watchlists.", "parameters": {"type": "object", "properties": {}}}},
        ]
