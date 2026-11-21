"""Tiny query history in a local SQLite file (history.db, created automatically)."""
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "history.db"
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.execute("CREATE TABLE IF NOT EXISTS history("
              "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, "
              "question TEXT NOT NULL, route TEXT, status TEXT)")
    return c


def add(question: str, route: str, status: str):
    with _lock:
        c = _conn()
        try:
            c.execute("INSERT INTO history(ts, question, route, status) VALUES(?,?,?,?)",
                      (datetime.now().isoformat(sep=" ", timespec="seconds"), question[:500], route, status))
            c.commit()
        finally:
            c.close()


def query(date: str = "", limit: int = 100) -> dict:
    """date = 'YYYY-MM-DD' -> only that day. Empty -> latest overall.
    'count' is the number of queries on that day (today when no date is given)."""
    day = date or datetime.now().strftime("%Y-%m-%d")
    with _lock:
        c = _conn()
        try:
            count = c.execute("SELECT COUNT(*) FROM history WHERE substr(ts,1,10)=?", (day,)).fetchone()[0]
            if date:
                rows = c.execute("SELECT id,ts,question,route,status FROM history "
                                 "WHERE substr(ts,1,10)=? ORDER BY id DESC LIMIT ?", (date, limit)).fetchall()
            else:
                rows = c.execute("SELECT id,ts,question,route,status FROM history "
                                 "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        finally:
            c.close()
    return {"day": day, "count": count,
            "items": [dict(id=r[0], ts=r[1], question=r[2], route=r[3], status=r[4]) for r in rows]}