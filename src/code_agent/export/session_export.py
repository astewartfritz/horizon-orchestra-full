from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from code_agent.session import Session, SessionManager


class SessionExporter:
    """Export individual sessions to various formats."""

    @staticmethod
    def to_json(session: Session, output: str = "") -> str:
        data = {
            "id": session.id,
            "task": session.task,
            "created_at": session.created_at,
            "finished": session.finished,
            "model": str(session.config.llm.model) if session.config and session.config.llm else "",
            "messages": [
                {"role": m.role, "content": m.content}
                for m in getattr(session, "messages", [])
            ],
            "result": session.result,
        }
        text = json.dumps(data, indent=2, default=str)
        if output:
            Path(output).write_text(text)
        return text

    @staticmethod
    def to_markdown(session: Session) -> str:
        lines = [
            f"# Session: {session.id}",
            f"**Task:** {session.task}",
            f"**Created:** {session.created_at}",
            f"**Finished:** {session.finished}",
            f"**Model:** {session.config.llm.model if session.config and session.config.llm else 'N/A'}",
            "",
            "## Conversation",
        ]
        for m in getattr(session, "messages", []):
            role = m.role.upper()
            lines.append(f"\n### {role}\n{m.content}\n")
        if session.result:
            lines.append(f"\n## Result\n{session.result}")
        return "\n".join(lines)

    @staticmethod
    def export_all(format: str = "json", output_dir: str = "session-exports") -> list[str]:
        mgr = SessionManager()
        sessions = mgr.list_sessions()
        exported = []
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        for s_info in sessions:
            sid = s_info["id"]
            session = mgr.load(sid)
            if not session:
                continue
            ext = ".md" if format == "markdown" else ".json"
            fname = out / f"{sid}{ext}"
            if format == "markdown":
                fname.write_text(SessionExporter.to_markdown(session))
            else:
                fname.write_text(SessionExporter.to_json(session))
            exported.append(str(fname))

        return exported
