import json
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    password    TEXT NOT NULL,           -- bcrypt hash
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verifications (
    verification_id TEXT PRIMARY KEY,
    user_id         INTEGER REFERENCES users(user_id),
    client_id       TEXT,
    input_type      TEXT NOT NULL,       -- text | url | image | document | audio | video
    input_content   TEXT NOT NULL,       -- submitted text, URL or file name
    status          TEXT NOT NULL,       -- processing | completed | failed
    verdict         TEXT,
    confidence      INTEGER,
    share_id        TEXT UNIQUE,
    report_json     TEXT,
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS claims (
    claim_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id TEXT NOT NULL REFERENCES verifications(verification_id) ON DELETE CASCADE,
    claim_text      TEXT NOT NULL,
    entities        TEXT,
    keywords        TEXT,
    claim_date      TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id        INTEGER NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    source_name     TEXT,
    source_url      TEXT,
    title           TEXT,
    published_date  TEXT,
    evidence_type   TEXT                 -- supporting | contradicting | neutral
);
CREATE TABLE IF NOT EXISTS verification_results (
    result_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id        INTEGER NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    verdict         TEXT NOT NULL,
    confidence      REAL,
    explanation     TEXT,
    generated_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ver_owner ON verifications(user_id, client_id, created_at);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def conn():
    c = sqlite3.connect(config.DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init():
    with conn() as c:
        c.executescript(SCHEMA)


def create_verification(input_type: str, input_content: str, user_id, client_id) -> str:
    vid = uuid.uuid4().hex[:16]
    with conn() as c:
        c.execute(
            "INSERT INTO verifications (verification_id, user_id, client_id, input_type, input_content, status, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (vid, user_id, client_id, input_type, input_content[:5000], "processing", now()),
        )
    return vid


def fail_verification(vid: str):
    with conn() as c:
        c.execute("UPDATE verifications SET status='failed' WHERE verification_id=?", (vid,))


def save_report(vid: str, report: dict):
    with conn() as c:
        c.execute(
            "UPDATE verifications SET status='completed', verdict=?, confidence=?, report_json=? WHERE verification_id=?",
            (report["verdict"], report["confidence"], json.dumps(report), vid),
        )
        for cl in report["claims"]:
            ents = cl.get("entities", {})
            cur = c.execute(
                "INSERT INTO claims (verification_id, claim_text, entities, keywords, claim_date) VALUES (?,?,?,?,?)",
                (vid, cl["text"], json.dumps(ents), json.dumps(cl.get("keywords", [])),
                 ", ".join(ents.get("dates", []))),
            )
            cid = cur.lastrowid
            for ev in cl["evidence"]:
                c.execute(
                    "INSERT INTO evidence (claim_id, source_name, source_url, title, published_date, evidence_type)"
                    " VALUES (?,?,?,?,?,?)",
                    (cid, ev.get("publisher"), ev.get("url"), ev.get("title"), ev.get("date"),
                     {"supports": "supporting", "refutes": "contradicting"}.get(ev.get("stance"), "neutral")),
                )
            c.execute(
                "INSERT INTO verification_results (claim_id, verdict, confidence, explanation, generated_at)"
                " VALUES (?,?,?,?,?)",
                (cid, cl["verdict"], cl["confidence"], cl["explanation"], now()),
            )


def _owner_clause(user_id, client_id):
    if user_id:
        return "user_id = ?", (user_id,)
    return "client_id = ? AND user_id IS NULL", (client_id or "-",)


def history(user_id, client_id, limit=50):
    where, args = _owner_clause(user_id, client_id)
    with conn() as c:
        rows = c.execute(
            f"SELECT verification_id, input_type, input_content, status, verdict, confidence, created_at"
            f" FROM verifications WHERE {where} AND status != 'processing' ORDER BY created_at DESC LIMIT ?",
            (*args, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get(vid: str, user_id, client_id):
    where, args = _owner_clause(user_id, client_id)
    with conn() as c:
        r = c.execute(f"SELECT * FROM verifications WHERE verification_id=? AND {where}", (vid, *args)).fetchone()
    return dict(r) if r else None


def get_shared(share_id: str):
    with conn() as c:
        r = c.execute("SELECT * FROM verifications WHERE share_id=? AND status='completed'", (share_id,)).fetchone()
    return dict(r) if r else None


def share(vid: str, user_id, client_id) -> str | None:
    row = get(vid, user_id, client_id)
    if not row or row["status"] != "completed":
        return None
    if row["share_id"]:
        return row["share_id"]
    sid = secrets.token_urlsafe(9)
    with conn() as c:
        c.execute("UPDATE verifications SET share_id=? WHERE verification_id=?", (sid, vid))
    return sid


def delete(vid: str, user_id, client_id) -> bool:
    where, args = _owner_clause(user_id, client_id)
    with conn() as c:
        return c.execute(f"DELETE FROM verifications WHERE verification_id=? AND {where}", (vid, *args)).rowcount > 0


def clear(user_id, client_id) -> int:
    where, args = _owner_clause(user_id, client_id)
    with conn() as c:
        return c.execute(f"DELETE FROM verifications WHERE {where}", args).rowcount


def adopt(client_id: str, user_id: int):
    """Move anonymous history into a user's account after sign-in."""
    with conn() as c:
        c.execute("UPDATE verifications SET user_id=? WHERE client_id=? AND user_id IS NULL", (user_id, client_id))


# ---- users
def create_user(name, email, pw_hash):
    with conn() as c:
        cur = c.execute("INSERT INTO users (name, email, password, created_at) VALUES (?,?,?,?)",
                        (name, email.lower(), pw_hash, now()))
        return cur.lastrowid


def user_by_email(email):
    with conn() as c:
        r = c.execute("SELECT * FROM users WHERE email=?", (email.lower(),)).fetchone()
    return dict(r) if r else None


def user_by_id(uid):
    with conn() as c:
        r = c.execute("SELECT user_id, name, email, created_at FROM users WHERE user_id=?", (uid,)).fetchone()
    return dict(r) if r else None
