"""Tools exposed to the LLM: vehicles (Smart Reminder), games + watches (DropHunter), memory."""
import logging
from datetime import date, timedelta
from typing import Optional

import db.client as db
from utils import docker_status, metrics, openrouter_usage
from utils.itad import get_all_prices, get_historical_low, search_game
from utils.watches import fetch_swisstimehouse

logger = logging.getLogger("onering.functions")

_VEHICLE_FIELDS: dict[str, str] = {
    "insurance_valid_until": "Insurance",
    "pucc_valid_until": "Pollution (PUCC)",
    "fitness_valid_until": "Fitness / RC validity",
    "mv_tax_valid_until": "MV Tax",
    "permit_valid_until": "Permit",
}


# ---------------------------------------------------------------------------
# Vehicle functions
# ---------------------------------------------------------------------------

def _fmt_expiry(val: Optional[date], today: date) -> str:
    if val is None:
        return "N/A"
    remaining = (val - today).days
    if remaining < 0:
        return f"{val} (EXPIRED {-remaining}d ago)"
    if remaining == 0:
        return f"{val} (expires TODAY)"
    return f"{val} (in {remaining}d)"


def _format_vehicles(vehicles: list[dict]) -> str:
    if not vehicles:
        return "No vehicles found."
    today = date.today()
    parts = []
    for v in vehicles:
        name = v.get("nickname") or v["registration_number"]
        owner = v.get("owner_name") or "Unknown"
        lines = [f"{name} ({v['registration_number']}) — {owner}"]
        for field, label in _VEHICLE_FIELDS.items():
            val = v.get(field)
            if val is not None:
                lines.append(f"  {label}: {_fmt_expiry(val, today)}")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def query_vehicles(user_id: str, filter: str, value: str = None, days: int = 30) -> str:
    vehicles = db.get_vehicles_filtered(filter_type=filter, value=value, days=days)
    return _format_vehicles(vehicles)


def update_vehicle_expiry(user_id: str, registration_number: str, field: str, new_date: str) -> str:
    if field not in _VEHICLE_FIELDS:
        return f"Unknown field '{field}'."
    if db.update_vehicle_field(registration_number, field, new_date):
        return f"Updated {_VEHICLE_FIELDS[field]} for {registration_number} to {new_date}."
    return f"Vehicle {registration_number} not found."


def snooze_reminder(user_id: str, registration_number: str, field: str,
                    mode: str, days: int = 30, reason: str = "") -> str:
    label = _VEHICLE_FIELDS.get(field, field)
    vehicles = db.get_vehicles_filtered("by_registration", value=registration_number)
    if not vehicles:
        return f"Vehicle {registration_number} not found."
    vid = vehicles[0]["id"]

    if mode == "unsnooze":
        removed = db.unsnooze_reminder(vid, field)
        return (f"Snooze cleared for {label} on {registration_number}." if removed
                else f"No active snooze for {label} on {registration_number}.")

    until = None
    if mode == "snooze_days":
        until = date.today() + timedelta(days=days)
    db.snooze_reminder(vid, field, until, reason, user_id)
    if until:
        return f"Reminders for {label} on {registration_number} snoozed until {until}."
    return f"Reminders for {label} on {registration_number} permanently ignored."


# ---------------------------------------------------------------------------
# Game functions
# ---------------------------------------------------------------------------

def add_game(user_id: str, title: str, target_price: float = None) -> str:
    game = search_game(title)
    if game is None:
        return f"Sorry, '{title}' was not found on IsThereAnyDeal."
    db.add_game(user_id, game["title"], game["id"], target_price=target_price)
    if target_price is not None:
        return f"Tracking **{game['title']}**. I'll alert you when it drops below ₹{target_price:.2f}."
    return f"Tracking **{game['title']}**. I'll alert you when a deal drops."


def set_target_price(user_id: str, title: str, target_price: float = None) -> str:
    if not db.set_target_price(user_id, title, target_price):
        return f"**{title}** wasn't found in your watchlist."
    if target_price is None:
        return f"Removed target price for **{title}**. I'll now alert on historical lows."
    return f"Target price for **{title}** set to ₹{target_price:.2f}."


def remove_game(user_id: str, title: str) -> str:
    if db.remove_game(user_id, title):
        return f"No longer tracking **{title}**."
    return f"**{title}** wasn't in your watchlist."


def list_games(user_id: str) -> str:
    games = db.get_games(user_id)
    if not games:
        return "Your watchlist is empty. Try 'track <game name>' to add a game."
    lines = []
    for g in games:
        line = f"• {g['title']}"
        if g.get("target_price") is not None:
            line += f" (target: ₹{float(g['target_price']):.2f})"
        lines.append(line)
    return "**Games you're tracking:**\n" + "\n".join(lines)


def get_current_price(user_id: str, title: str) -> str:
    game = search_game(title)
    if game is None:
        return f"Sorry, '{title}' was not found on IsThereAnyDeal."
    prices = get_all_prices(game["id"])
    if not prices:
        return f"No current deals found for **{game['title']}**."
    lines = [f"**{game['title']}** prices:"]
    for p in prices[:10]:
        lines.append(f"• {p['store']}: ₹{p['price']:.2f} ({p['cut']}% off, was ₹{p['regular_price']:.2f})")
    return "\n".join(lines)


def get_historical_low_price(user_id: str, title: str) -> str:
    game = search_game(title)
    if game is None:
        return f"Sorry, '{title}' was not found on IsThereAnyDeal."
    low = get_historical_low(game["id"])
    if low is None:
        return f"No historical low data found for **{game['title']}**."
    return f"The all-time historical low for **{game['title']}** is ₹{low:.2f}."


def get_recent_deals(user_id: str) -> str:
    deals = db.get_recent_deals(user_id)
    if not deals:
        return "No recent deals found."
    lines = "\n".join(
        f"• **{d['title']}** — ₹{float(d['price']):.2f}"
        f" (alerted {d['notified_at'][:10] if d.get('notified_at') else 'unknown date'})"
        for d in deals
    )
    return f"**Recent deals I found:**\n{lines}"


# ---------------------------------------------------------------------------
# Watch functions
# ---------------------------------------------------------------------------

def add_watch(user_id: str, url: str, target_price: float = None) -> str:
    watch = fetch_swisstimehouse(url)
    if watch is None:
        return ("Sorry, I couldn't read a price from that link. "
                "Make sure it's a swisstimehouse.com product page.")
    if target_price is None:
        return (f"**{watch['name']}** is currently ₹{watch['price']:.2f} on Swiss Time House. "
                f"What target price (in ₹) should I alert you below?")
    db.add_watch(user_id, name=watch["name"], brand=watch["brand"],
                 reference_no=watch["reference"], target_price=target_price, swisstimehouse_url=url)
    return (f"Tracking **{watch['name']}** (currently ₹{watch['price']:.2f}). "
            f"I'll alert you when it drops below ₹{target_price:.2f}.")


def list_watches(user_id: str) -> str:
    watches = db.get_watches(user_id)
    if not watches:
        return "Your watch list is empty. Add one with a swisstimehouse.com product link."
    lines = ["**Watches you're tracking:**"]
    for w in watches:
        line = f"• {w['name']}"
        if w.get("target_price") is not None:
            line += f" (target: ₹{float(w['target_price']):.2f})"
        lines.append(line)
    return "\n".join(lines)


def get_watch_price(user_id: str, name: str) -> str:
    match = db._find_watch_by_name(user_id, name)
    if not match or not match.get("swisstimehouse_url"):
        return f"**{name}** isn't on your watch list."
    fetched = fetch_swisstimehouse(match["swisstimehouse_url"])
    if fetched is None:
        return f"I couldn't fetch the current price for **{match['name']}** right now."
    return f"**{match['name']}** is currently ₹{fetched['price']:.2f} on Swiss Time House."


def set_watch_target(user_id: str, name: str, target_price: float) -> str:
    if not db.set_watch_target(user_id, name, target_price):
        return f"**{name}** wasn't found in your watch list."
    return f"Target price for **{name}** set to ₹{target_price:.2f}."


def remove_watch(user_id: str, name: str) -> str:
    if db.remove_watch(user_id, name):
        return f"No longer tracking **{name}**."
    return f"**{name}** wasn't in your watch list."


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def clear_memory(user_id: str) -> str:
    from ai.provider import get_provider
    summary = db.force_summarize(user_id, get_provider())
    return f"Memory cleared and summarized. Key facts retained: {summary[:300]}"


# ---------------------------------------------------------------------------
# Monitoring functions (Prometheus / Loki / Docker)
# ---------------------------------------------------------------------------

_HEALTH_METRICS = [("CPU", "cpu_percent", "%"), ("RAM", "ram_percent", "%"),
                   ("Disk", "disk_percent", "%"), ("Temp", "cpu_temp", "°C")]


def get_system_health(user_id: str) -> str:
    parts = []
    for label, name, unit in _HEALTH_METRICS:
        try:
            val = metrics.canned_value(name)
            parts.append(f"{label}: {val:.1f}{unit}" if val is not None else f"{label}: n/a")
        except Exception as exc:
            logger.error("metric %s failed: %s", name, exc)
            parts.append(f"{label}: error")
    return "Server health — " + ", ".join(parts)


def get_metric_range(user_id: str, metric: str, duration: str = "1h") -> str:
    if metric not in metrics.CANNED:
        return f"Unknown metric '{metric}'. Known: {', '.join(metrics.CANNED)}."
    try:
        series = metrics.range_query(metrics.CANNED[metric], duration=duration)
    except Exception as exc:
        return f"Prometheus is unreachable ({exc})."
    points = series[0][1] if series else []
    return metrics.summarize_range(f"{metric} over {duration}", points)


def get_container_status(user_id: str, name: str = None) -> str:
    try:
        containers = docker_status.fetch_containers()
    except Exception as exc:
        return f"Docker status unavailable (socket not mounted? {exc})."
    return docker_status.summarize_containers(containers, name=name)


def search_logs(user_id: str, container: str, level: str = None, duration: str = "1h") -> str:
    selector = '{container="%s"}' % container
    if level:
        selector += ' |~ "(?i)%s"' % level
    try:
        rows = metrics.loki_query(selector, duration=duration, limit=30)
    except Exception as exc:
        return f"Loki is unreachable ({exc})."
    if not rows:
        return f"No logs for {container} in the last {duration}."
    lines = [line for _, line in rows][:30]
    return f"Last {len(lines)} log lines for {container}:\n" + "\n".join(lines)


def query_prometheus(user_id: str, promql: str, range: str = None) -> str:
    try:
        if range:
            series = metrics.range_query(promql, duration=range)
            points = series[0][1] if series else []
            return metrics.summarize_range(f"query over {range}", points)
        rows = metrics.instant(promql)
    except Exception as exc:
        return f"Prometheus query failed ({exc})."
    if not rows:
        return "Query returned no data."
    return "\n".join(f"{m or 'value'}: {v:.3f}" for m, v in rows[:20])


def query_loki(user_id: str, logql: str, duration: str = "1h") -> str:
    try:
        rows = metrics.loki_query(logql, duration=duration, limit=30)
    except Exception as exc:
        return f"Loki query failed ({exc})."
    if not rows:
        return "Query returned no log lines."
    return "\n".join(line for _, line in rows[:30])


def get_openrouter_balance(user_id: str) -> str:
    if not openrouter_usage.key_configured():
        return "OpenRouter not configured — OPENROUTER_API_KEY is missing."
    try:
        info = openrouter_usage.parse_credits(openrouter_usage.fetch_credits())
    except Exception as exc:
        return f"Could not fetch OpenRouter balance ({exc})."
    return (f"OpenRouter balance: ${info['balance']:.2f} "
            f"(purchased ${info['purchased']:.2f}, used ${info['used']:.2f}).")


def get_openrouter_usage(user_id: str) -> str:
    if not openrouter_usage.key_configured():
        return "OpenRouter not configured — OPENROUTER_API_KEY is missing."
    try:
        usage = openrouter_usage.parse_key_usage(openrouter_usage.fetch_key())
    except Exception as exc:
        return f"Could not fetch OpenRouter usage ({exc})."
    return openrouter_usage.summarize_usage(usage)


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_vehicles",
            "description": (
                "Query vehicles. Use for questions about expiry dates, document status, "
                "owners, or vehicle details."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filter": {
                        "type": "string",
                        "enum": ["all", "expiring_soon", "expired", "by_owner",
                                 "by_registration", "by_nickname"],
                        "description": "Filter type to apply",
                    },
                    "value": {
                        "type": "string",
                        "description": "Filter value for by_owner/by_registration/by_nickname",
                    },
                    "days": {
                        "type": "integer",
                        "description": "Lookahead days for expiring_soon (default 30)",
                    },
                },
                "required": ["filter"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_vehicle_expiry",
            "description": (
                "Update an expiry date on a vehicle. STRICT: call query_vehicles first, show "
                "old → new to the user, ask 'Confirm?', and only call this after confirmation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_number": {"type": "string", "description": "e.g. KL04AS1371"},
                    "field": {
                        "type": "string",
                        "enum": list(_VEHICLE_FIELDS.keys()),
                        "description": "The expiry field to update",
                    },
                    "new_date": {"type": "string", "description": "New date in YYYY-MM-DD format"},
                },
                "required": ["registration_number", "field", "new_date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "snooze_reminder",
            "description": (
                "Snooze or permanently ignore cron reminders for a vehicle document. "
                "Use mode='unsnooze' to clear a snooze."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "registration_number": {"type": "string", "description": "e.g. KL04AS1371"},
                    "field": {"type": "string", "enum": list(_VEHICLE_FIELDS.keys())},
                    "mode": {
                        "type": "string",
                        "enum": ["ignore", "snooze_days", "unsnooze"],
                        "description": "ignore=permanent, snooze_days=for N days, unsnooze=clear",
                    },
                    "days": {"type": "integer", "description": "Days to snooze (mode=snooze_days)"},
                    "reason": {"type": "string", "description": "Optional reason"},
                },
                "required": ["registration_number", "field", "mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_game",
            "description": (
                "Add a game to the watchlist to track its price. Optionally set a target price "
                "threshold in INR to only alert when the price drops below that amount."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The name of the game to track."},
                    "target_price": {"type": "number", "description": "Optional INR threshold."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_target_price",
            "description": (
                "Set or update a target price (INR) for a tracked game. "
                "Omit target_price to remove the threshold and revert to historical-low alerts."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "The name of the tracked game."},
                    "target_price": {"type": "number", "description": "INR threshold; omit to clear."},
                },
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_game",
            "description": "Remove a game from the watchlist.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Game to remove."}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_games",
            "description": "List all games currently on the watchlist.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_price",
            "description": "Get the current best price for a game across all stores.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Game to look up."}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_historical_low_price",
            "description": "Get the all-time historical low price for a game from IsThereAnyDeal.",
            "parameters": {
                "type": "object",
                "properties": {"title": {"type": "string", "description": "Game to look up."}},
                "required": ["title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_deals",
            "description": "Show recent deal alerts that were sent.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_watch",
            "description": (
                "Track a watch's price from a swisstimehouse.com product URL. Provide a target "
                "price in INR. If no target price is given, returns the current price and asks for one."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "A swisstimehouse.com product URL."},
                    "target_price": {"type": "number", "description": "Target alert price in INR."},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_watches",
            "description": "List all watches currently being tracked.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_watch_price",
            "description": "Get the current price of a tracked watch from swisstimehouse.com.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Name of the tracked watch."}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_watch_target",
            "description": "Set or update the target price (INR) for a tracked watch.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the tracked watch."},
                    "target_price": {"type": "number", "description": "New target price in INR."},
                },
                "required": ["name", "target_price"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_watch",
            "description": "Remove a watch from the watch list.",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string", "description": "Watch to remove."}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_memory",
            "description": (
                "Clear and summarize the conversation history. Use when the user asks to "
                "'clear memory', 'reset conversation', or 'start fresh'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {"type": "function", "function": {
        "name": "get_system_health",
        "description": "Current server health snapshot: CPU %, RAM %, disk %, and CPU temperature.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_metric_range",
        "description": "A system metric over a time window, summarized as min/max/avg/latest.",
        "parameters": {"type": "object", "properties": {
            "metric": {"type": "string", "enum": ["cpu_percent", "ram_percent", "disk_percent", "cpu_temp"]},
            "duration": {"type": "string", "description": "e.g. 1h, 24h, 7d (default 1h)"}},
            "required": ["metric"]}}},
    {"type": "function", "function": {
        "name": "get_container_status",
        "description": "Docker container status: total/running/stopped/unhealthy counts and per-container health. Optionally filter by name.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "Optional container name substring."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "search_logs",
        "description": "Search a container's recent logs via Loki. Optional level filter (e.g. error).",
        "parameters": {"type": "object", "properties": {
            "container": {"type": "string", "description": "Container name."},
            "level": {"type": "string", "description": "Optional case-insensitive match (e.g. error, warn)."},
            "duration": {"type": "string", "description": "Lookback, e.g. 1h, 6h (default 1h)."}},
            "required": ["container"]}}},
    {"type": "function", "function": {
        "name": "query_prometheus",
        "description": "Run a raw PromQL query (escape hatch). Pass range like 6h for a range query.",
        "parameters": {"type": "object", "properties": {
            "promql": {"type": "string", "description": "Raw PromQL expression."},
            "range": {"type": "string", "description": "Optional window for a range query, e.g. 6h."}},
            "required": ["promql"]}}},
    {"type": "function", "function": {
        "name": "query_loki",
        "description": "Run a raw LogQL query against Loki (escape hatch).",
        "parameters": {"type": "object", "properties": {
            "logql": {"type": "string", "description": "Raw LogQL expression."},
            "duration": {"type": "string", "description": "Lookback window, e.g. 1h (default 1h)."}},
            "required": ["logql"]}}},
    {"type": "function", "function": {
        "name": "get_openrouter_balance",
        "description": "Current OpenRouter credit balance and lifetime purchased/used amounts.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_openrouter_usage",
        "description": "OpenRouter spend rollups: today, this week, and this month.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]


_FUNCTION_MAP = {
    "query_vehicles": query_vehicles,
    "update_vehicle_expiry": update_vehicle_expiry,
    "snooze_reminder": snooze_reminder,
    "add_game": add_game,
    "set_target_price": set_target_price,
    "remove_game": remove_game,
    "list_games": list_games,
    "get_current_price": get_current_price,
    "get_historical_low_price": get_historical_low_price,
    "get_recent_deals": get_recent_deals,
    "add_watch": add_watch,
    "list_watches": list_watches,
    "get_watch_price": get_watch_price,
    "set_watch_target": set_watch_target,
    "remove_watch": remove_watch,
    "clear_memory": clear_memory,
    "get_system_health": get_system_health,
    "get_metric_range": get_metric_range,
    "get_container_status": get_container_status,
    "search_logs": search_logs,
    "query_prometheus": query_prometheus,
    "query_loki": query_loki,
    "get_openrouter_balance": get_openrouter_balance,
    "get_openrouter_usage": get_openrouter_usage,
}


def dispatch(name: str, args: dict, user_id: str) -> str:
    """Execute a tool by name, injecting the resolved user_id as the first argument."""
    fn = _FUNCTION_MAP.get(name)
    if fn is None:
        logger.error("Unknown tool requested: %s", name)
        return f"Unknown tool: {name}"
    try:
        return fn(user_id, **(args or {}))
    except Exception as exc:
        logger.error("Tool %s failed: %s", name, exc, exc_info=True)
        return f"Sorry, the {name} action failed: {exc}"
