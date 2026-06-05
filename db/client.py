import os
import re
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import psycopg2
import psycopg2.extras
from psycopg2 import sql as pgsql
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


def _row(r) -> dict:
    """RealDictRow -> plain dict, serialising datetimes to ISO strings."""
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()}


def _rows(rs) -> list:
    return [_row(r) for r in rs]


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", (text or "").lower()).strip()


def _fuzzy_find(rows: list, query: str, key: str) -> Optional[dict]:
    norm_query = _normalize(query)
    for r in rows:
        if _normalize(r[key]) == norm_query:
            return r
    for r in rows:
        if norm_query and (norm_query in _normalize(r[key]) or _normalize(r[key]) in norm_query):
            return r
    return None


# ===========================================================================
# Vehicles (public schema — shared with Smart Reminder)
# ===========================================================================

_VEHICLE_COLS = """
    id, nickname, registration_number, status, vehicle_class,
    fuel_type, owner_name, registration_date,
    insurance_valid_until, pucc_valid_until, fitness_valid_until,
    mv_tax_valid_until, permit_valid_until, permit_type
"""

_ORDER_BY_NEAREST = """ORDER BY LEAST(
    COALESCE(insurance_valid_until, '9999-01-01'::date),
    COALESCE(pucc_valid_until,      '9999-01-01'::date),
    COALESCE(fitness_valid_until,   '9999-01-01'::date),
    COALESCE(mv_tax_valid_until,    '9999-01-01'::date),
    COALESCE(permit_valid_until,    '9999-01-01'::date)
)"""

_ALLOWED_VEHICLE_FIELDS = frozenset({
    "insurance_valid_until",
    "pucc_valid_until",
    "fitness_valid_until",
    "mv_tax_valid_until",
    "permit_valid_until",
})


def get_vehicles_filtered(filter_type: str, value: Optional[str] = None, days: int = 30) -> list[dict]:
    if filter_type == "all":
        sql = f"SELECT {_VEHICLE_COLS} FROM public.vehicles ORDER BY registration_number"
        params: dict = {}
    elif filter_type == "expiring_soon":
        sql = f"""
            SELECT {_VEHICLE_COLS} FROM public.vehicles
            WHERE insurance_valid_until BETWEEN CURRENT_DATE AND CURRENT_DATE + %(days)s * INTERVAL '1 day'
               OR pucc_valid_until      BETWEEN CURRENT_DATE AND CURRENT_DATE + %(days)s * INTERVAL '1 day'
               OR fitness_valid_until   BETWEEN CURRENT_DATE AND CURRENT_DATE + %(days)s * INTERVAL '1 day'
               OR mv_tax_valid_until    BETWEEN CURRENT_DATE AND CURRENT_DATE + %(days)s * INTERVAL '1 day'
               OR (permit_valid_until IS NOT NULL
                   AND permit_valid_until BETWEEN CURRENT_DATE AND CURRENT_DATE + %(days)s * INTERVAL '1 day')
            {_ORDER_BY_NEAREST}
        """
        params = {"days": days}
    elif filter_type == "expired":
        sql = f"""
            SELECT {_VEHICLE_COLS} FROM public.vehicles
            WHERE insurance_valid_until < CURRENT_DATE
               OR pucc_valid_until < CURRENT_DATE
               OR fitness_valid_until < CURRENT_DATE
               OR mv_tax_valid_until < CURRENT_DATE
               OR (permit_valid_until IS NOT NULL AND permit_valid_until < CURRENT_DATE)
            {_ORDER_BY_NEAREST}
        """
        params = {}
    elif filter_type == "by_owner":
        sql = f"SELECT {_VEHICLE_COLS} FROM public.vehicles WHERE owner_name ILIKE %(value)s ORDER BY registration_number"
        params = {"value": f"%{value}%"}
    elif filter_type == "by_registration":
        sql = f"SELECT {_VEHICLE_COLS} FROM public.vehicles WHERE registration_number ILIKE %(value)s"
        params = {"value": f"%{value}%"}
    elif filter_type == "by_nickname":
        sql = f"SELECT {_VEHICLE_COLS} FROM public.vehicles WHERE nickname ILIKE %(value)s"
        params = {"value": f"%{value}%"}
    else:
        raise ValueError(f"Unknown filter_type: {filter_type!r}")

    with _cursor() as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def update_vehicle_field(registration_number: str, field: str, new_date: str) -> bool:
    if field not in _ALLOWED_VEHICLE_FIELDS:
        raise ValueError(f"Field {field!r} is not updatable")
    query = pgsql.SQL(
        "UPDATE public.vehicles SET {col} = %(new_date)s, updated_at = now() "
        "WHERE registration_number = %(reg)s"
    ).format(col=pgsql.Identifier(field))
    with _cursor() as cur:
        cur.execute(query, {"new_date": new_date, "reg": registration_number})
        return cur.rowcount > 0


def get_all_vehicles_with_expiry() -> list[dict]:
    with _cursor() as cur:
        cur.execute(f"SELECT {_VEHICLE_COLS} FROM public.vehicles ORDER BY id")
        return [dict(r) for r in cur.fetchall()]


# --- reminder log / snooze (public schema) ---

def reminder_already_sent(vehicle_id: int, expiry_field: str, expiry_date: date, offset: int) -> bool:
    with _cursor() as cur:
        cur.execute(
            """SELECT 1 FROM public.reminder_log
               WHERE vehicle_id = %s AND expiry_field = %s
                 AND expiry_date = %s AND trigger_offset = %s""",
            (vehicle_id, expiry_field, expiry_date, offset),
        )
        return cur.fetchone() is not None


def log_reminder(vehicle_id: int, expiry_field: str, expiry_date: date, offset: int) -> None:
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO public.reminder_log (vehicle_id, expiry_field, expiry_date, trigger_offset)
               VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (vehicle_id, expiry_field, expiry_date, offset),
        )


def is_snoozed(vehicle_id: int, expiry_field: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            """SELECT 1 FROM public.reminder_snooze
               WHERE vehicle_id = %s AND expiry_field = %s
                 AND (snoozed_until IS NULL OR snoozed_until >= CURRENT_DATE)""",
            (vehicle_id, expiry_field),
        )
        return cur.fetchone() is not None


def snooze_reminder(vehicle_id: int, expiry_field: str, snoozed_until, reason: str, created_by: str) -> None:
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO public.reminder_snooze
                   (vehicle_id, expiry_field, snoozed_until, reason, created_by)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (vehicle_id, expiry_field) DO UPDATE
                   SET snoozed_until = EXCLUDED.snoozed_until,
                       reason        = EXCLUDED.reason,
                       created_by    = EXCLUDED.created_by,
                       created_at    = now()""",
            (vehicle_id, expiry_field, snoozed_until, reason, created_by),
        )


def unsnooze_reminder(vehicle_id: int, expiry_field: str) -> bool:
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM public.reminder_snooze WHERE vehicle_id = %s AND expiry_field = %s",
            (vehicle_id, expiry_field),
        )
        return cur.rowcount > 0


# ===========================================================================
# Identity (master schema)
# ===========================================================================

def resolve_user_id(raw_id: str) -> str:
    """Map a platform-specific user id to its canonical id, if an alias exists."""
    with _cursor() as cur:
        cur.execute(
            "SELECT canonical_id FROM master.user_aliases WHERE alias_id = %s",
            (raw_id,),
        )
        row = cur.fetchone()
        return row["canonical_id"] if row else raw_id


# ===========================================================================
# Chat memory (master schema)
# ===========================================================================

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
        cur.execute("SELECT summary FROM master.chat_summary WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        return row["summary"] if row else None


def upsert_summary(user_id: str, summary: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO master.chat_summary (user_id, summary) VALUES (%s, %s) "
            "ON CONFLICT (user_id) DO UPDATE SET summary = EXCLUDED.summary, updated_at = now()",
            (user_id, summary),
        )


def force_summarize(user_id: str, provider) -> str:
    """Summarise all stored messages into the rolling summary, then delete them."""
    with _cursor() as cur:
        cur.execute(
            "SELECT id, role, content FROM master.chat_messages "
            "WHERE user_id = %s ORDER BY created_at ASC",
            (user_id,),
        )
        all_messages = [dict(r) for r in cur.fetchall()]
    if not all_messages:
        return "No conversation history to summarize."

    existing = get_summary(user_id) or "None"
    text = "\n".join(f"{m['role']}: {m['content']}" for m in all_messages)
    new_summary = provider.generate_text(
        "You are the memory manager for OneRing, a personal homelab assistant.\n"
        "Summarise the conversation below into a concise paragraph (max 200 words).\n"
        "Keep only facts: vehicles/games/watches discussed, dates and targets set, stated "
        "preferences. Do not invent anything. Merge with the existing summary.\n\n"
        f"Existing summary: {existing}\n\nMessages:\n{text}"
    )
    upsert_summary(user_id, new_summary)
    with _cursor() as cur:
        cur.execute(
            "DELETE FROM master.chat_messages WHERE id = ANY(%s)",
            ([m["id"] for m in all_messages],),
        )
    return new_summary


# ===========================================================================
# Games (drophunter schema)
# ===========================================================================

def get_games(user_id: Optional[str] = None) -> list[dict]:
    with _cursor() as cur:
        if user_id is not None:
            cur.execute(
                "SELECT * FROM drophunter.games WHERE user_id = %s ORDER BY added_at",
                (user_id,),
            )
        else:
            cur.execute("SELECT * FROM drophunter.games ORDER BY added_at")
        return _rows(cur.fetchall())


def add_game(user_id: str, title: str, itad_id: str, target_price: Optional[float] = None) -> dict:
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO drophunter.games (user_id, title, itad_id, target_price)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (user_id, itad_id) DO UPDATE
                   SET title = EXCLUDED.title, target_price = EXCLUDED.target_price
               RETURNING *""",
            (user_id, title, itad_id, target_price),
        )
        return _row(cur.fetchone())


def _find_game_by_title(user_id: str, title: str) -> Optional[dict]:
    return _fuzzy_find(get_games(user_id), title, "title")


def set_target_price(user_id: str, title: str, target_price: Optional[float]) -> bool:
    game = _find_game_by_title(user_id, title)
    if not game:
        return False
    with _cursor() as cur:
        cur.execute(
            "UPDATE drophunter.games SET target_price = %s WHERE id = %s",
            (target_price, game["id"]),
        )
        return cur.rowcount > 0


def remove_game(user_id: str, title: str) -> bool:
    game = _find_game_by_title(user_id, title)
    if not game:
        return False
    with _cursor() as cur:
        cur.execute("DELETE FROM drophunter.games WHERE id = %s", (game["id"],))
        return cur.rowcount > 0


def insert_price_history(game_id: str, price: float, regular_price: float, store: str) -> dict:
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO drophunter.price_history (game_id, price, regular_price, store)
               VALUES (%s, %s, %s, %s) RETURNING *""",
            (game_id, price, regular_price, store),
        )
        return _row(cur.fetchone())


def get_last_notified_price(game_id: str) -> Optional[float]:
    with _cursor() as cur:
        cur.execute(
            "SELECT price FROM drophunter.notifications_log "
            "WHERE game_id = %s ORDER BY notified_at DESC LIMIT 1",
            (game_id,),
        )
        row = cur.fetchone()
    return float(row["price"]) if row else None


def log_notification(game_id: str, price: float) -> dict:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO drophunter.notifications_log (game_id, price) VALUES (%s, %s) RETURNING *",
            (game_id, price),
        )
        return _row(cur.fetchone())


def get_recent_deals(user_id: str, limit: int = 5) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            """SELECT nl.id, nl.game_id, nl.price, nl.notified_at,
                      g.title AS game_title
               FROM drophunter.notifications_log nl
               JOIN drophunter.games g ON nl.game_id = g.id
               WHERE g.user_id = %s
               ORDER BY nl.notified_at DESC LIMIT %s""",
            (user_id, limit),
        )
        rows = cur.fetchall()
    result = []
    for r in rows:
        d = _row(r)
        d["title"] = d.pop("game_title")
        result.append(d)
    return result


def get_historical_low(game_id: str) -> Optional[float]:
    with _cursor() as cur:
        cur.execute(
            "SELECT price FROM drophunter.price_history "
            "WHERE game_id = %s ORDER BY price ASC LIMIT 1",
            (game_id,),
        )
        row = cur.fetchone()
    return float(row["price"]) if row else None


# ===========================================================================
# Watches (drophunter schema)
# ===========================================================================

def get_watches(user_id: Optional[str] = None) -> list[dict]:
    with _cursor() as cur:
        if user_id is not None:
            cur.execute(
                "SELECT * FROM drophunter.watches WHERE user_id = %s ORDER BY added_at",
                (user_id,),
            )
        else:
            cur.execute("SELECT * FROM drophunter.watches ORDER BY added_at")
        return _rows(cur.fetchall())


def add_watch(user_id: str, name: str, brand: Optional[str], reference_no: Optional[str],
              target_price: float, swisstimehouse_url: str) -> dict:
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO drophunter.watches
                   (user_id, name, brand, reference_no, target_price, swisstimehouse_url)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (user_id, swisstimehouse_url) DO UPDATE SET
                   name = EXCLUDED.name, brand = EXCLUDED.brand,
                   reference_no = EXCLUDED.reference_no, target_price = EXCLUDED.target_price
               RETURNING *""",
            (user_id, name, brand, reference_no, target_price, swisstimehouse_url),
        )
        return _row(cur.fetchone())


def _find_watch_by_name(user_id: str, name: str) -> Optional[dict]:
    return _fuzzy_find(get_watches(user_id), name, "name")


def set_watch_target(user_id: str, name: str, target_price: float) -> bool:
    watch = _find_watch_by_name(user_id, name)
    if not watch:
        return False
    with _cursor() as cur:
        cur.execute(
            "UPDATE drophunter.watches SET target_price = %s WHERE id = %s",
            (target_price, watch["id"]),
        )
        return cur.rowcount > 0


def remove_watch(user_id: str, name: str) -> bool:
    watch = _find_watch_by_name(user_id, name)
    if not watch:
        return False
    with _cursor() as cur:
        cur.execute("DELETE FROM drophunter.watches WHERE id = %s", (watch["id"],))
        return True


def insert_watch_price_history(watch_id: str, swisstimehouse_price: Optional[float],
                               myntra_price: Optional[float] = None) -> dict:
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO drophunter.watch_price_history
                   (watch_id, swisstimehouse_price, myntra_price)
               VALUES (%s, %s, %s) RETURNING *""",
            (watch_id, swisstimehouse_price, myntra_price),
        )
        return _row(cur.fetchone())


def get_last_watch_notified_price(watch_id: str) -> Optional[float]:
    with _cursor() as cur:
        cur.execute(
            "SELECT price FROM drophunter.watch_notifications_log "
            "WHERE watch_id = %s ORDER BY notified_at DESC LIMIT 1",
            (watch_id,),
        )
        row = cur.fetchone()
    return float(row["price"]) if row else None


def log_watch_notification(watch_id: str, price: float, seller: str) -> dict:
    with _cursor() as cur:
        cur.execute(
            """INSERT INTO drophunter.watch_notifications_log (watch_id, price, seller)
               VALUES (%s, %s, %s) RETURNING *""",
            (watch_id, price, seller),
        )
        return _row(cur.fetchone())
