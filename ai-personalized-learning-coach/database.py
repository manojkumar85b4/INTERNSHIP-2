"""SQLite persistence layer: learner profile, plans, topics, quiz attempts, progress."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime


class DatabaseError(Exception):
    """Raised for any database problem so the UI can show a friendly message."""


def _db_path() -> str:
    return os.getenv("DB_PATH", "learning_coach.db")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def get_conn():
    try:
        conn = sqlite3.connect(_db_path())
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise DatabaseError(f"Database error: {exc}") from exc


SCHEMA = """
CREATE TABLE IF NOT EXISTS learners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    goal TEXT NOT NULL,
    level TEXT NOT NULL,
    duration_days INTEGER NOT NULL,
    daily_minutes INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learner_id INTEGER NOT NULL REFERENCES learners(id),
    title TEXT NOT NULL,
    summary TEXT,
    plan_json TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    day INTEGER NOT NULL,
    title TEXT NOT NULL,
    objectives TEXT NOT NULL,
    estimated_minutes INTEGER NOT NULL,
    activities TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    last_updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    topic_id INTEGER NOT NULL REFERENCES topics(id),
    score INTEGER NOT NULL,
    total INTEGER NOT NULL,
    percent REAL NOT NULL,
    questions_json TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def save_learner(profile: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO learners (subject, goal, level, duration_days, daily_minutes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (profile["subject"], profile["goal"], profile["level"],
             int(profile["duration_days"]), int(profile["daily_minutes"]), _now()),
        )
        return cur.lastrowid


def save_plan(learner_id: int, plan: dict) -> int:
    """Store a plan + its topics; older plans become inactive (regeneration)."""
    with get_conn() as conn:
        conn.execute("UPDATE plans SET is_active = 0")
        cur = conn.execute(
            "INSERT INTO plans (learner_id, title, summary, plan_json, is_active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (learner_id, plan["title"], plan.get("summary", ""), json.dumps(plan), _now()),
        )
        plan_id = cur.lastrowid
        for t in plan["topics"]:
            conn.execute(
                "INSERT INTO topics (plan_id, day, title, objectives, estimated_minutes, "
                "activities, status, last_updated) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                (plan_id, t["day"], t["title"], json.dumps(t["objectives"]),
                 t["estimated_minutes"], json.dumps(t["activities"]), _now()),
            )
        return plan_id


def get_latest_learner():
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM learners ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def get_active_plan():
    with get_conn() as conn:
        row = conn.execute(
            "SELECT p.id, p.title, p.summary, p.created_at, l.subject, l.goal, l.level, "
            "l.duration_days, l.daily_minutes FROM plans p JOIN learners l ON l.id = p.learner_id "
            "WHERE p.is_active = 1 ORDER BY p.id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def _topic_row(row) -> dict:
    d = dict(row)
    d["objectives"] = json.loads(d["objectives"])
    d["activities"] = json.loads(d["activities"])
    return d


def get_topics(plan_id: int) -> list:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM topics WHERE plan_id = ? ORDER BY day, id", (plan_id,)).fetchall()
        return [_topic_row(r) for r in rows]


def update_topic_status(topic_id: int, status: str) -> None:
    with get_conn() as conn:
        conn.execute("UPDATE topics SET status = ?, last_updated = ? WHERE id = ?",
                     (status, _now(), topic_id))


def save_attempt(plan_id: int, topic_id: int, score: int, total: int, percent: float,
                 questions: list, answers: list) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO quiz_attempts (plan_id, topic_id, score, total, percent, questions_json, "
            "answers_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (plan_id, topic_id, score, total, percent, json.dumps(questions), json.dumps(answers), _now()),
        )
        return cur.lastrowid


def get_attempts(plan_id: int, topic_id: int = None, limit: int = 50) -> list:
    sql = ("SELECT a.id, a.topic_id, a.score, a.total, a.percent, a.created_at, "
           "t.title AS topic_title, t.day FROM quiz_attempts a JOIN topics t ON t.id = a.topic_id "
           "WHERE a.plan_id = ?")
    params = [plan_id]
    if topic_id is not None:
        sql += " AND a.topic_id = ?"
        params.append(topic_id)
    sql += " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
