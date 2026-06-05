# OneRingToRuleThemAll

> *One bot to rule them all, one bot to find them, one bot to bring them all, and in the homelab bind them.*

The Phase 3 **Master Bot** of the homelab — a single Telegram/Discord assistant that ties together
**Smart Reminder** (vehicle documents) and **DropHunter** (game & watch price drops) behind one
conversation with full memory.

## What it does

- 💬 Chat over **Telegram** (and optionally **Discord**) — platform-agnostic, replies on whichever you message from
- 🚗 Query and update **vehicle document expiry** (insurance, pollution, fitness, tax, permit)
- 🎮 Check **tracked games** and ⌚ **watches** you're hunting for price drops
- 🧠 Remembers conversation history per user (Postgres-backed)

## Architecture

```
ai/
  base.py                  AIProvider ABC
  openrouter_provider.py   OpenRouter HTTP client with retry + optional model fallback
  graph.py                 LangGraph agent: load_memory → agent → execute_tools → save_memory
bot/
  message.py               Platform-agnostic Message dataclass
  telegram_bot.py          python-telegram-bot listener
  discord_bot.py           discord.py listener
  functions.py             Tool definitions (TOOLS) + dispatch()
db/
  client.py                psycopg2 helpers — master (memory) + public/drophunter (data)
  migrations/
    001_master_schema.sql  master.chat_messages, master.chat_summary, master_rw role
utils/
  notify.py                notify(text, platform, chat_id)
main.py                    Entrypoint — Discord in daemon thread, Telegram on main thread
```

- **LLM:** OpenRouter. Model set via `OPENROUTER_MODEL` (default `deepseek/deepseek-chat-v3-0324` —
  cheap and reliable tool-calling). Each request retries 3× with exponential backoff, and can spill
  to `OPENROUTER_FALLBACK_MODEL` if configured.
- **DB:** Local homelab Postgres (`homelab` DB), three schemas: `master` (chat memory),
  `public` (shared vehicles, read + update), `drophunter` (games/watches, read-only).

## Setup

### 1. Database

The bot expects the shared homelab Postgres (container `homelab-postgres`). Apply the master schema:

```bash
docker exec -i homelab-postgres psql -U homelab -d homelab < db/migrations/001_master_schema.sql
```

### 2. Environment

```bash
cp .env.example .env
```

Fill in:

| Var | Notes |
|-----|-------|
| `OPENROUTER_API_KEY` | from openrouter.ai |
| `OPENROUTER_MODEL` | default `deepseek/deepseek-chat-v3-0324` |
| `DATABASE_URI` | `postgresql://homelab:…@postgres:5432/homelab` (compose overrides host to `postgres`) |
| `TELEGRAM_BOT_TOKEN` | from @BotFather |
| `TELEGRAM_CHAT_ID` | from @userinfobot |
| `DISCORD_BOT_TOKEN` / `DISCORD_CHANNEL_ID` | optional |

### 3. Run (Docker — recommended)

Joins the existing `master_db_postgres_default` network so it can reach `homelab-postgres`:

```bash
docker compose up --build -d
docker logs onering-bot -f
```

### Run (local, with uv)

```bash
uv pip install -r requirements.txt
python main.py
```

Then message your bot on Telegram.

## Tests

```bash
pytest
```

## Where this sits

Part of a 7-phase homelab automation project:

| Phase | Project | Role |
|-------|---------|------|
| 1 | Smart Reminder System | Vehicle document reminders |
| 2 | DropHunter | Game/watch price hunting |
| **3** | **OneRingToRuleThemAll** | **This — unified master bot** |
| 4 | — | Grafana MCP (metrics via natural language) |
| 5 | — | Backups (restic + S3 Glacier) |
| 6 | — | WhatsApp transport (Baileys) |
