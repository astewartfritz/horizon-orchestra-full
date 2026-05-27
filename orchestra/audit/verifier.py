"""Chain verification, compliance reporting, and tamper detection.

Suitable for HIPAA, SOC 2, and FCA audit reviews.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orchestra.audit.log import AuditEntry, AuditLog


class AuditVerifier:
    """Verifies audit chain integrity and produces compliance reports."""

    def __init__(self, audit_log: AuditLog):
        self.log = audit_log

    def verify(self) -> dict[str, Any]:
        return self.log.full_audit()

    def verify_range(self, from_id: int, to_id: int) -> dict[str, Any]:
        chain_fails = self.log.verify_chain(from_id, to_id)
        sig_fails = self.log.verify_signatures(from_id, to_id)
        return {
            "range": [from_id, to_id],
            "chain_integrity": len(chain_fails) == 0,
            "signatures_valid": len(sig_fails) == 0,
            "tampered": len(chain_fails) + len(sig_fails),
            "chain_failures": chain_fails,
            "signature_failures": sig_fails,
        }

    def report(self, output_path: str | Path | None = None) -> dict[str, Any]:
        """Generate a compliance report with chain verification and stats."""
        audit = self.verify()
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "audit_db": str(self.log.db_path),
            "total_entries": audit["total_entries"],
            "chain_intact": audit["chain_integrity"],
            "all_signatures_valid": audit["signatures_valid"],
            "tampered_entries": audit["tampered"],
            "status": "PASS"
            if (audit["chain_integrity"] and audit["signatures_valid"])
            else "FAIL",
        }
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, indent=2))
        return report

    def export_for_compliance(self, output_dir: str | Path,
                              title: str = "Compliance Export") -> dict[str, Path]:
        """Full compliance export: JSON-Lines, CSV, and verification report."""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        json_path = out / f"audit_{timestamp}.jsonl"
        csv_path = out / f"audit_{timestamp}.csv"
        report_path = out / f"audit_{timestamp}_report.json"

        jl = self.log.export_json(json_path)
        csv = self.log.export_csv(csv_path)
        self.report(report_path)
        return {"jsonl": jl, "csv": csv, "report": report_path}


def verify_db(db_path: str | Path, key: str | None = None) -> dict[str, Any]:
    """One-shot: open an audit DB and run full verification."""
    al = AuditLog(db_path, key=key)
    try:
        return al.full_audit()
    finally:
        al.close()
