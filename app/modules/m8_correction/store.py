import json
import sqlite3
from contextlib import closing
from pathlib import Path


class RevisionStore:
    """更正修订独立存档：与原批次表分离，任何修订都不覆盖旧记录。"""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS revisions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, revision_id):
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT payload FROM revisions WHERE id=?", (revision_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, revision_id, data):
        with closing(self.connect()) as db, db:
            result = db.execute(
                "INSERT OR IGNORE INTO revisions VALUES (?, ?)",
                (revision_id, json.dumps(data, ensure_ascii=False)),
            )
            created = result.rowcount == 1
            payload = db.execute(
                "SELECT payload FROM revisions WHERE id=?", (revision_id,)
            ).fetchone()[0]
        return json.loads(payload), not created

    def history(self, source_id=None):
        with closing(self.connect()) as db:
            if source_id is None:
                rows = db.execute("SELECT payload FROM revisions ORDER BY rowid DESC LIMIT 40")
            else:
                rows = db.execute(
                    "SELECT payload FROM revisions WHERE json_extract(payload, '$.更正清单.源批次') = ?"
                    " ORDER BY rowid DESC LIMIT 40",
                    (source_id,),
                )
            return [json.loads(row[0])["更正清单"] for row in rows]
