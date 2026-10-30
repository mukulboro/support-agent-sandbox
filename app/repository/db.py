import json
import sqlite3
from datetime import datetime
from pathlib import Path


class AuditStore:
    """Finished-conversation audits in SQLite, plus the human reviewer's decision on each one."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    ended_by TEXT NOT NULL,
                    title TEXT NOT NULL,
                    score INTEGER NOT NULL,
                    ended_well INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    reasons TEXT NOT NULL,
                    issues TEXT NOT NULL,
                    suggestions TEXT NOT NULL,
                    record TEXT NOT NULL,
                    review TEXT NOT NULL DEFAULT 'pending',
                    review_note TEXT NOT NULL DEFAULT ''
                )
            """)

    def connect(self) -> sqlite3.Connection:
        """A new connection per call: audits are written from background threads."""
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def save(self, audit: dict, record: dict) -> int:
        """audit is the auditor's result; record is the finished conversation (id, messages, traces, ended_by)."""
        first_question = next((m["content"] for m in record["messages"] if m["role"] == "user"), "")
        with self.connect() as db:
            cursor = db.execute(
                "INSERT INTO audits (created_at, conversation_id, ended_by, title, score, ended_well, outcome, reasons,"
                " issues, suggestions, record) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now().isoformat(timespec="seconds"), record["id"], record["ended_by"], first_question[:100],
                    audit["score"], int(audit["ended_well"]), audit["outcome"], audit["reasons"],
                    json.dumps(audit["issues"]), json.dumps(audit["suggestions"]), json.dumps(record),
                ),
            )
            return cursor.lastrowid

    def list(self, review: str | None = None) -> list[dict]:
        """Audits without the full conversation, newest first. Pass review="pending" to see only unreviewed ones."""
        query = "SELECT * FROM audits" + (" WHERE review = ?" if review else "") + " ORDER BY id DESC"
        with self.connect() as db:
            rows = db.execute(query, (review,) if review else ()).fetchall()
        return [self.to_dict(row, with_record=False) for row in rows]

    def get(self, audit_id: int) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM audits WHERE id = ?", (audit_id,)).fetchone()
        return self.to_dict(row, with_record=True) if row else None

    def set_review(self, audit_id: int, decision: str, note: str) -> bool:
        """Records the human's decision ("approved" or "rejected") on the auditor's suggestions."""
        with self.connect() as db:
            cursor = db.execute("UPDATE audits SET review = ?, review_note = ? WHERE id = ?", (decision, note, audit_id))
            return cursor.rowcount > 0

    def to_dict(self, row: sqlite3.Row, with_record: bool) -> dict:
        audit = dict(row)
        audit["ended_well"] = bool(audit["ended_well"])
        audit["issues"] = json.loads(audit["issues"])
        audit["suggestions"] = json.loads(audit["suggestions"])
        audit["record"] = json.loads(audit["record"]) if with_record else None
        if not with_record:
            del audit["record"]
        return audit
