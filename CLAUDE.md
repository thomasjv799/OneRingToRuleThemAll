# CLAUDE.md

## Project overview

OneRingToRuleThemAll is the Phase 3 Master Bot — a unified homelab assistant that ties together Smart Reminder (vehicle documents) and DropHunter (game/watch prices). One bot, one conversation, full access.

## Directory structure

```
ai/
  base.py                  AIProvider ABC
  openrouter_provider.py   OpenRouter HTTP client (model via OPENROUTER_MODEL env var)
  graph.py                 LangGraph agent: load_memory → agent → execute_tools → save_memory
bot/
  message.py               Platform-agnostic Message dataclass
  telegram_bot.py          python-telegram-bot listener
  discord_bot.py           discord.py listener
  functions.py             Tool definitions (TOOLS list) + dispatch()
db/
  client.py                psycopg2 helpers — master schema (memory) + public/drophunter (data)
  migrations/
    001_master_schema.sql  Schema DDL — master.chat_messages, master.chat_summary, master_rw role
utils/
  notify.py                notify(text, platform, chat_id) — Telegram / Discord send
tests/
main.py                    Entrypoint — Discord in daemon thread, Telegram on main thread
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

- **LLM:** OpenRouter. Model `OPENROUTER_MODEL` (default `deepseek/deepseek-chat-v3-0324` — paid, cheap, reliable tool-calling). Each request retries 3× with exponential backoff. Optional `OPENROUTER_FALLBACK_MODEL` spills over if set (used when running a free primary model that hits 429). Free tier (`moonshotai/kimi-k2.6:free`) is left commented in `.env` — it rate-limits too aggressively for interactive use.
- **DB:** Local homelab Postgres (`homelab` DB). Three schemas accessed:
  - `master` — this bot's chat memory (chat_messages, chat_summary)
  - `public` — shared Smart Reminder vehicles table (read + update expiry)
  - `drophunter` — DropHunter games/watches (read-only)
- **Memory:** `load_memory` fetches last 10 messages + summary. `save_memory` persists the turn. No rolling summarisation yet — add when context grows large.
- **Tools:** Defined in `bot/functions.py` as OpenAI-format tool schemas. `dispatch()` routes by name and injects `user_id` server-side.
- **Platform routing:** Both bots call `run_graph(user_id, text)` and reply with the returned string. Platform-agnostic.

## Environment variables

```
OPENROUTER_API_KEY         sk-or-v1-...
OPENROUTER_MODEL           moonshotai/kimi-k2.6:free
OPENROUTER_FALLBACK_MODEL  deepseek/deepseek-chat-v3-0324
DATABASE_URI            postgresql://homelab:password@localhost:5432/homelab
TELEGRAM_BOT_TOKEN      from @BotFather
TELEGRAM_CHAT_ID        your chat ID
DISCORD_BOT_TOKEN       optional
DISCORD_CHANNEL_ID      optional
```

## DB setup (fresh install)

```bash
psql -U homelab -d homelab -f db/migrations/001_master_schema.sql
```
