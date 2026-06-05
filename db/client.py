import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

_conn = None


def _ensure_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(os.environ["DATABASE_URI"])
        _conn.autocommit = True
    return _conn


@contextmanager
def _cursor():
    conn = _ensure_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
    except psycopg2.OperationalError:
        global _conn
        _conn = None
        raise


# --- vehicles (public schema, shared with Smart Reminder) ---

def get_vehicles() -> list[dict]:
    with _cursor() as cur:
        cur.execute("SELECT * FROM public.vehicles ORDER BY name")
        return [dict(r) for r in cur.fetchall()]


def get_vehicle(vehicle_id: int) -> dict | None:
    with _cursor() as cur:
        cur.execute("SELECT * FROM public.vehicles WHERE id = %s", (vehicle_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def update_vehicle_expiry(vehicle_id: int, field: str, value: str) -> bool:
    allowed = {
        "insurance_expiry", "pollution_expiry", "fitness_expiry",
        "tax_expiry", "permit_expiry",
    }
    if field not in allowed:
        raise ValueError(f"Unknown expiry field: {field}")
    with _cursor() as cur:
        cur.execute(
            f"UPDATE public.vehicles SET {field} = %s WHERE id = %s",
            (value, vehicle_id),
        )
        return cur.rowcount > 0


# --- identity (master schema) ---

def resolve_user_id(raw_id: str) -> str:
    """Map a platform-specific user id to its canonical id, if an alias exists."""
    with _cursor() as cur:
        cur.execute(
            "SELECT canonical_id FROM master.user_aliases WHERE alias_id = %s",
            (raw_id,),
        )
        row = cur.fetchone()
        return row["canonical_id"] if row else raw_id


# --- chat memory (master schema) ---

def get_chat_history(user_id: str, limit: int = 20) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT role, content FROM master.chat_messages "
            "WHERE user_id = %s ORDER BY created_at DESC LIMIT %s",
            (user_id, limit),
        )
        return list(reversed([dict(r) for r in cur.fetchall()]))


def save_message(user_id: str, role: str, content: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO master.chat_messages (user_id, role, content) VALUES (%s, %s, %s)",
            (user_id, role, content),
        )


def get_summary(user_id: str) -> str | None:
    with _cursor() as cur:
        cur.execute(
            "SELECT summary FROM master.chat_summary WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        return row["summary"] if row else None


def upsert_summary(user_id: str, summary: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO master.chat_summary (user_id, summary) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET summary = EXCLUDED.summary, updated_at = now()",
            (user_id, summary),
        )


# --- drophunter read-only helpers ---

def get_games(user_id: str) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT title, itad_id, target_price FROM drophunter.games WHERE user_id = %s",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def get_watches(user_id: str) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT swisstimehouse_url, target_price FROM drophunter.watches WHERE user_id = %s",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]
