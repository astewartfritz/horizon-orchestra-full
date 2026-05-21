from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any


class FullExporter:
    """Export all agent data (sessions, knowledge, logs, configs, profiles) as a single archive."""

    @staticmethod
    def export(output_path: str = "") -> str:
        if not output_path:
            output_path = f"code-agent-export-{datetime.now():%Y%m%d-%H%M%S}.zip"

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            # Sessions
            from orchestra.code_agent.session import SessionManager
            mgr = SessionManager()
            sessions = mgr.list_sessions()
            for s_info in sessions:
                session = mgr.load(s_info["id"])
                if session:
                    data = {
                        "id": session.id, "task": session.task,
                        "created_at": session.created_at,
                        "result": session.result,
                    }
                    zf.writestr(f"sessions/{session.id}.json", json.dumps(data, indent=2, default=str))

            # Knowledge base
            kb_paths = list(Path(".").glob(".code-agent-knowledge*"))
            for kp in kb_paths:
                if kp.is_file():
                    zf.write(str(kp), f"knowledge/{kp.name}")

            # Logs
            log_dir = Path(".agent-logs")
            if log_dir.exists():
                for lf in log_dir.glob("*.jsonl"):
                    zf.write(str(lf), f"logs/{lf.name}")

            # Config
            cfg = Path("code-agent.json")
            if cfg.exists():
                zf.write(str(cfg), "config/code-agent.json")

            # Profiles
            profile_dir = Path(".agent-profiles")
            if profile_dir.exists():
                for pf in profile_dir.glob("*.json"):
                    zf.write(str(pf), f"profiles/{pf.name}")

            # Traces
            traces = Path(".agent-traces.jsonl")
            if traces.exists():
                zf.write(str(traces), "telemetry/traces.jsonl")

            # Scheduler
            sched = Path(".agent-scheduler.json")
            if sched.exists():
                zf.write(str(sched), "scheduler/tasks.json")

            # Traces
            t = Path(".agent-traces.jsonl")
            if t.exists():
                zf.write(str(t), "telemetry/traces.jsonl")

        return output_path

    @staticmethod
    def import_archive(archive_path: str, extract_dir: str = ".agent-import") -> list[str]:
        extracted = []
        out = Path(extract_dir)
        out.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(str(out))
            extracted = zf.namelist()

        return extracted
