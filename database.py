"""SQLite persistence: short per-operation connections, parameterized SQL and WAL."""
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL CHECK(kind IN ('meeting','reminder')),
                title TEXT NOT NULL,
                starts_at INTEGER NOT NULL,
                ends_at INTEGER NOT NULL,
                notify_at INTEGER NOT NULL,
                timezone TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'scheduled',
                created_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS events_time ON events(status, starts_at);
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER NOT NULL UNIQUE,
                message TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                read INTEGER NOT NULL DEFAULT 0
            );
            ''')

    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        try:
            with c:
                yield c
        finally:
            c.close()

    def add(self, kind, title, starts_at, ends_at, notify_at, timezone, location=''):
        with self.connect() as c:
            row = c.execute('''INSERT INTO events
                (kind,title,starts_at,ends_at,notify_at,timezone,location,created_at)
                VALUES (?,?,?,?,?,?,?,?)''',
                (kind,title,starts_at,ends_at,notify_at,timezone,location,int(time.time())))
            return row.lastrowid

    def get(self, event_id):
        with self.connect() as c:
            row = c.execute('SELECT * FROM events WHERE id=?', (event_id,)).fetchone()
            return dict(row) if row else None

    def upcoming(self, now=None, limit=100):
        now = int(time.time()) if now is None else now
        with self.connect() as c:
            return [dict(r) for r in c.execute('''SELECT * FROM events
                WHERE status='scheduled' AND ends_at>=? ORDER BY starts_at LIMIT ?''', (now,limit))]

    def conflicts(self, start, end):
        with self.connect() as c:
            return [dict(r) for r in c.execute('''SELECT * FROM events WHERE kind='meeting'
                AND status='scheduled' AND starts_at<? AND ends_at>?''', (end,start))]

    def cancel(self, event_id):
        with self.connect() as c:
            result = c.execute("UPDATE events SET status='cancelled' WHERE id=? AND status='scheduled'", (event_id,))
            c.execute('UPDATE notifications SET read=1 WHERE event_id=?', (event_id,))
            return bool(result.rowcount)

    def queue_due(self, now=None):
        now = int(time.time()) if now is None else now
        with self.connect() as c:
            c.execute('''INSERT OR IGNORE INTO notifications(event_id,message,created_at)
                SELECT id, CASE WHEN kind='meeting' THEN 'Meeting: ' ELSE 'Reminder: ' END || title, ?
                FROM events WHERE notify_at<=? AND status='scheduled' ''', (now,now))

    def notifications(self):
        with self.connect() as c:
            return [dict(r) for r in c.execute('''SELECT n.*, e.starts_at, e.kind FROM notifications n
                JOIN events e ON e.id=n.event_id WHERE n.read=0 ORDER BY n.id LIMIT 100''')]

    def acknowledge(self, notification_id):
        with self.connect() as c:
            return bool(c.execute('UPDATE notifications SET read=1 WHERE id=?', (notification_id,)).rowcount)
