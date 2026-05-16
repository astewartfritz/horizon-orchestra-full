"""HTAP engine — DuckDB-powered OLTP/OLAP for logistics planning."""

from __future__ import annotations

from typing import Any


class HTAPEngine:
    """Hybrid Transactional/Analytical Processing engine.
    
    Uses DuckDB for in-memory analytics. Falls back to list/dict operations
    when DuckDB is not available.
    """

    def __init__(self):
        self._duckdb = None
        self._available = False
        self._init()

    def _init(self):
        try:
            import duckdb
            self._duckdb = duckdb.connect(":memory:")
            self._available = True
            self._init_schema()
        except ImportError:
            self._available = False

    def _init_schema(self):
        if not self._available:
            return
        self._duckdb.execute("""
            CREATE TABLE IF NOT EXISTS lanes (
                lane_id VARCHAR, origin VARCHAR, dest VARCHAR,
                distance_km DOUBLE, avg_rate DOUBLE, volume INT,
                carrier_count INT, on_time_rate DOUBLE
            )
        """)
        self._duckdb.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id VARCHAR, lane_id VARCHAR, date DATE,
                weight DOUBLE, rate DOUBLE, carrier VARCHAR,
                transit_days INT, on_time BOOLEAN
            )
        """)
        self._duckdb.execute("""
            CREATE TABLE IF NOT EXISTS capacity (
                date DATE, lane_id VARCHAR, available_trucks INT,
                booked_trucks INT, rate_per_truck DOUBLE
            )
        """)

    def query(self, sql: str) -> list[dict[str, Any]]:
        if not self._available:
            return [{"error": "DuckDB not available. Install with: pip install duckdb"}]
        try:
            result = self._duckdb.execute(sql).fetchall()
            cols = [desc[0] for desc in self._duckdb.description]
            return [dict(zip(cols, row)) for row in result]
        except Exception as e:
            return [{"error": str(e)}]

    def insert_lanes(self, rows: list[dict[str, Any]]) -> int:
        if not self._available:
            return 0
        count = 0
        for row in rows:
            self._duckdb.execute(
                "INSERT INTO lanes VALUES (?,?,?,?,?,?,?,?)",
                [row.get(k) for k in ("lane_id", "origin", "dest", "distance_km",
                                       "avg_rate", "volume", "carrier_count", "on_time_rate")])
            count += 1
        return count

    def insert_shipments(self, rows: list[dict[str, Any]]) -> int:
        if not self._available:
            return 0
        count = 0
        for row in rows:
            self._duckdb.execute(
                "INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?)",
                [row.get(k) for k in ("id", "lane_id", "date", "weight",
                                       "rate", "carrier", "transit_days", "on_time")])
            count += 1
        return count

    # ── Analytical queries ──────────────────

    def top_lanes_by_volume(self, limit: int = 10) -> list[dict[str, Any]]:
        return self.query(f"SELECT * FROM lanes ORDER BY volume DESC LIMIT {limit}")

    def avg_rate_by_lane(self) -> list[dict[str, Any]]:
        return self.query("SELECT lane_id, origin, dest, avg_rate, volume FROM lanes ORDER BY avg_rate DESC")

    def on_time_performance(self) -> list[dict[str, Any]]:
        return self.query("""
            SELECT s.lane_id, l.origin, l.dest,
                   COUNT(*) as shipments,
                   SUM(CASE WHEN s.on_time THEN 1 ELSE 0 END) as on_time,
                   ROUND(SUM(CASE WHEN s.on_time THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) as on_time_pct
            FROM shipments s JOIN lanes l ON s.lane_id = l.lane_id
            GROUP BY s.lane_id, l.origin, l.dest ORDER BY on_time_pct
        """)

    def capacity_utilization(self) -> list[dict[str, Any]]:
        return self.query("""
            SELECT lane_id, date, available_trucks, booked_trucks,
                   ROUND(booked_trucks * 100.0 / NULLIF(available_trucks, 0), 1) as utilization_pct
            FROM capacity ORDER BY date
        """)

    def lane_summary_stats(self) -> dict[str, Any]:
        r = self.query("""
            SELECT COUNT(*) as total_lanes,
                   ROUND(AVG(avg_rate), 2) as avg_rate,
                   ROUND(AVG(distance_km), 1) as avg_distance,
                   SUM(volume) as total_volume,
                   ROUND(AVG(on_time_rate), 1) as avg_on_time
            FROM lanes
        """)
        return r[0] if r else {}
