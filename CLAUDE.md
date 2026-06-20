# CLAUDE.md

## Project overview

OneRingToRuleThemAll is the Phase 3 Master Bot — a unified homelab assistant that ties together Smart Reminder (vehicle documents) and DropHunter (game/watch prices). One bot, one conversation, full access. It exposes the full interactive toolset of both source bots. The proactive background sweeps (deal alerts, expiry reminders) stay in their own repos (DropHunter / Smart Reminder) — the master bot is interactive only.

## Directory structure

```
ai/
  base.py                  AIProvider ABC (chat + generate_text)
  openrouter_provider.py   OpenRouter HTTP client
  provider.py              get_provider() → OpenRouterProvider
  graph.py                 LangGraph agent: load_memory → agent → execute_tools → save_memory
bot/
  message.py               Platform-agnostic Message dataclass
  telegram_bot.py          python-telegram-bot listener
  discord_bot.py           discord.py listener
  functions.py             Tool definitions (TOOLS list) + dispatch()
db/
  client.py                psycopg2 helpers — master (memory) + public (vehicles/reminders) + drophunter
  migrations/
    001_master_schema.sql  master.chat_messages, master.chat_summary, master_rw role
    002_user_aliases.sql   master.user_aliases (cross-platform identity)
    003_reminders.sql      public.reminder_log + public.reminder_snooze (idempotent)
utils/
  itad.py                  IsThereAnyDeal API client (game prices)
  watches.py               swisstimehouse.com scraper (cloudscraper + schema.org JSON-LD)
  notify.py                notify(text, platform, chat_id, parse_mode) — Telegram / Discord send
tests/
main.py                    Entrypoint — Discord on main thread (primary); Telegram in daemon thread, gated by ENABLE_TELEGRAM (off; blocked in India)
```

## Common commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in tokens
python main.py
pytest
```

## Architecture notes

- **LLM:** OpenRouter via `ai/provider.get_provider()` → `OpenRouterProvider`. Model `OPENROUTER_MODEL` (default `deepseek/deepseek-chat-v3-0324`); optional `OPENROUTER_FALLBACK_MODEL` spills over on 429. Each request retries 3× with exponential backoff on 429/5xx.
- **DB:** Local homelab Postgres (`homelab` DB). Three schemas accessed:
  - `master` — chat memory (chat_messages, chat_summary) + identity (user_aliases)
  - `public` — Smart Reminder vehicles (read + update expiry) + reminder_log / reminder_snooze
  - `drophunter` — DropHunter games/watches (read + write: add/remove/target)
- **Identity:** `resolve_user_id()` maps a platform id (e.g. Telegram `813187457`) to the canonical owner id (Discord `688395953090461801`) so game/watch rows and chat memory are unified across platforms. Game/watch tools are user_id-scoped to the canonical id; vehicle tools are shared (single-owner data).
- **Tools (`bot/functions.py`):** vehicles (`query_vehicles`, `update_vehicle_expiry`, `snooze_reminder`), games (`add_game`, `set_target_price`, `remove_game`, `list_games`, `get_current_price`, `get_historical_low_price`, `get_recent_deals`), watches (`add_watch`, `list_watches`, `get_watch_price`, `set_watch_target`, `remove_watch`), and `clear_memory`. `dispatch()` injects the resolved `user_id` server-side and catches tool errors.
  - **Vehicle columns** are the real schema: `insurance_valid_until`, `pucc_valid_until`, `fitness_valid_until`, `mv_tax_valid_until`, `permit_valid_until` (updates are keyed by `registration_number`).
- **Background sweeps:** The proactive deal-alert and expiry-reminder crons live in the DropHunter and Smart Reminder repos respectively — not here. The master bot's interactive `snooze_reminder` tool writes to `public.reminder_snooze`, which Smart Reminder's cron honours.
- **Memory:** `load_memory` fetches last 10 messages + summary; `save_memory` persists the turn. `clear_memory` force-summarises then deletes stored messages.
- **Platform routing:** Both bots call `run_graph(user_id, text)` and reply with the returned string. Platform-agnostic.

## Environment variables

```
OPENROUTER_API_KEY       sk-or-v1-...
OPENROUTER_MODEL         deepseek/deepseek-chat-v3-0324
DATABASE_URI             postgresql://homelab:password@localhost:5432/homelab
ITAD_API_KEY             from isthereanydeal.com/dev/app
DISCORD_BOT_TOKEN        required (primary transport)
DISCORD_CHANNEL_ID       required
ENABLE_TELEGRAM          1/true/yes to re-enable Telegram (default off; blocked in India)
TELEGRAM_BOT_TOKEN       from @BotFather (only used when ENABLE_TELEGRAM set)
TELEGRAM_CHAT_ID         your chat ID
CRON_NOTIFY_PLATFORM     discord | telegram
CRON_NOTIFY_CHAT_ID      override for cron alert target (defaults to TELEGRAM_CHAT_ID)
LANGFUSE_*               LLM observability
```

## DB setup (fresh install)

```bash
psql -U homelab -d homelab -f db/migrations/001_master_schema.sql
psql -U homelab -d homelab -f db/migrations/002_user_aliases.sql
psql -U homelab -d homelab -f db/migrations/003_reminders.sql
```
