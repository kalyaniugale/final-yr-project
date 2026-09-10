"""SQLite sessions, durable inbox and resumable outgoing batches. One worker only."""
import json
import sqlite3
import time
from pathlib import Path


class SessionStore:
    def __init__(self, path, ttl=86400):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.ttl = ttl
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                sender TEXT PRIMARY KEY, data TEXT NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS inbox (
                id TEXT PRIMARY KEY, sender TEXT NOT NULL, value TEXT NOT NULL,
                created REAL NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                outputs TEXT, next_output INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, retry_at REAL NOT NULL DEFAULT 0);
        """)

    def enqueue(self, events):
        with self.db:
            for event in events:
                self.db.execute("INSERT OR IGNORE INTO inbox(id,sender,value,created) VALUES (?,?,?,?)",
                                (*event, time.time()))

    def get(self, sender):
        row = self.db.execute("SELECT data,updated FROM sessions WHERE sender=?", (sender,)).fetchone()
        if row and row["updated"] > time.time() - self.ttl:
            return json.loads(row["data"])
        return None

    def next_event(self):
        # Preserve sender ordering, without blocking unrelated senders on retries.
        row = self.db.execute("""SELECT * FROM inbox AS i
            WHERE state IN ('pending','ready') AND retry_at<=?
            AND NOT EXISTS (SELECT 1 FROM inbox AS earlier
                WHERE earlier.sender=i.sender AND earlier.state IN ('pending','ready')
                AND earlier.rowid<i.rowid)
            ORDER BY rowid LIMIT 1""", (time.time(),)).fetchone()
        return dict(row) if row else None

    def prepare(self, event, session, outputs):
        # A crash cannot persist the transition without its outgoing messages.
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?)",
                            (event["sender"], json.dumps(session), time.time()))
            self.db.execute("UPDATE inbox SET state='ready',outputs=?,value='' WHERE id=?",
                            (json.dumps(outputs), event["id"]))

    def advance(self, event_id):
        with self.db:
            self.db.execute("UPDATE inbox SET next_output=next_output+1,attempts=0,retry_at=0 WHERE id=?", (event_id,))

    def finish(self, event_id, state="done"):
        with self.db:
            # Keep only the ID tombstone for deduplication, not recipient or payload.
            self.db.execute("UPDATE inbox SET state=?,sender='',value='',outputs=NULL WHERE id=?", (state, event_id))

    def retry(self, event):
        attempts = event["attempts"] + 1
        if attempts >= 5:
            self.finish(event["id"], "failed")
        else:
            with self.db:
                self.db.execute("UPDATE inbox SET attempts=?,retry_at=? WHERE id=?",
                                (attempts, time.time() + min(60, 2 ** attempts), event["id"]))

    def cleanup(self):
        now = time.time()
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE updated<?", (now-self.ttl,))
            # Do not deliver old interactive replies after the session window.
            self.db.execute("UPDATE inbox SET state='expired',sender='',value='',outputs=NULL "
                            "WHERE state IN ('pending','ready') AND created<?", (now-self.ttl,))
            self.db.execute("DELETE FROM inbox WHERE created<? AND state NOT IN ('pending','ready')", (now-7*86400,))

    def close(self):
        self.db.close()
