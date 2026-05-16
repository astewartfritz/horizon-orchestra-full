from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from code_agent.reviewer import CodeReviewer


REVIEW_SEVERITIES = {"critical", "high", "medium", "low", "info"}


@dataclass
class ReviewComment:
    file: str = ""
    line: int = 0
    severity: str = "medium"
    message: str = ""
    category: str = "style"
    suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewSession:
    id: str = ""
    target: str = ""
    comments: list[ReviewComment] = field(default_factory=list)
    summary: str = ""
    score: float = 0.0
    timestamp: float = 0.0
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "target": self.target,
                "comments": [c.to_dict() for c in self.comments],
                "summary": self.summary, "score": self.score,
                "status": self.status}


class ReviewDashboard:
    """Track and manage code reviews over time."""

    def __init__(self, storage_path: str = ".agent-reviews"):
        self.path = Path(storage_path)
        self.path.mkdir(parents=True, exist_ok=True)

    async def review_file(self, file_path: str) -> ReviewSession:
        reviewer = CodeReviewer()
        content = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        review_text = await reviewer.review(content)

        session = ReviewSession(
            id=f"rev_{int(time.time())}",
            target=file_path,
            timestamp=time.time(),
            status="completed",
        )
        session.summary = review_text[:1000]
        session.comments = self._parse_comments(review_text, file_path)
        session.score = self._calculate_score(session.comments)
        self._save(session)
        return session

    def _parse_comments(self, review_text: str, file_path: str) -> list[ReviewComment]:
        comments = []
        for line in review_text.split("\n"):
            line_lower = line.lower().strip()
            for sev in REVIEW_SEVERITIES:
                if sev in line_lower and len(line) > 20:
                    comments.append(ReviewComment(
                        file=file_path,
                        severity=sev,
                        message=line.strip()[:200],
                    ))
                    break
        return comments

    def _calculate_score(self, comments: list[ReviewComment]) -> float:
        weights = {"critical": 10, "high": 5, "medium": 2, "low": 1, "info": 0}
        total = sum(weights.get(c.severity, 1) for c in comments)
        return max(0.0, 10.0 - total * 0.5)

    def list_reviews(self) -> list[dict[str, Any]]:
        reviews = []
        for f in sorted(self.path.glob("*.json"), reverse=True)[:50]:
            try:
                data = json.loads(f.read_text())
                reviews.append({"id": data["id"], "target": data.get("target", ""),
                               "score": data.get("score", 0),
                               "comments": len(data.get("comments", [])),
                               "status": data.get("status", "")})
            except (json.JSONDecodeError, OSError):
                pass
        return reviews

    def get_trend(self) -> dict[str, Any]:
        reviews = self.list_reviews()
        if not reviews:
            return {"reviews_count": 0, "avg_score": 0}
        scores = [r["score"] for r in reviews if r["score"] > 0]
        return {
            "reviews_count": len(reviews),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "high_severity": sum(1 for r in reviews if r.get("comments", 0) > 5),
        }

    def get_html_dashboard(self) -> str:
        data = self.get_trend()
        reviews = self.list_reviews()[:20]
        rows = "".join(
            f"<tr><td>{r['target'][:40]}</td><td>{r['score']}</td>"
            f"<td>{r['comments']}</td><td>{r['status']}</td></tr>"
            for r in reviews
        )
        return f"""<!DOCTYPE html>
<html><head><title>Code Review Dashboard</title>
<style>
body {{ font-family: system-ui; margin: 2rem; background: #0d1117; color: #c9d1d9; }}
h1 {{ color: #58a6ff; }}
.metric {{ display: inline-block; margin: 1rem 2rem 1rem 0; }}
.metric .value {{ font-size: 2rem; font-weight: bold; color: #58a6ff; }}
.metric .label {{ font-size: 0.8rem; color: #8b949e; }}
table {{ width: 100%; border-collapse: collapse; }}
th, td {{ padding: 0.5rem; text-align: left; border-bottom: 1px solid #30363d; }}
th {{ color: #58a6ff; }}
</style></head><body>
<h1>Code Review Dashboard</h1>
<div class="metric"><div class="value">{data['reviews_count']}</div><div class="label">Reviews</div></div>
<div class="metric"><div class="value">{data['avg_score']}</div><div class="label">Avg Score</div></div>
<table><tr><th>File</th><th>Score</th><th>Issues</th><th>Status</th></tr>{rows}</table></body></html>"""

    def _save(self, session: ReviewSession) -> None:
        f = self.path / f"{session.id}.json"
        f.write_text(json.dumps(session.to_dict(), indent=2))
