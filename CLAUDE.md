LifeOS is a personal life operating system to proactively helps you manage your life.

## Philosophy

**Proactive, not passive.** Existing productivity tools are dumb lists that wait for you to check them. LifeOS reaches out. It notices when things are overdue, reminds you at the right time, and helps you stay on top of your life without you having to constantly check an app.

**Conversational interface.** Natural language is the UI. No forms, no buttons, no learning curve. Just tell it what you need like you would tell a human assistant.

**Privacy-first.** Self-hosted, local database, your data stays yours. The only external call is to the LLM API.

**Central nervous system.** The long-term vision is a single place that understands all aspects of your life - tasks, calendar, notes, habits - and helps you navigate it all. Not another app to check, but the one interface that ties everything together.

## Quick Start

```bash
uv run lifeos        # Run Telegram bot
uv run lifeos-cli    # Run CLI for debugging
uv run ty check      # Type check
```

## Architecture

The LLM has a single tool: `execute_sql`. It writes raw SQLite queries to manage tasks, reminders, and notes. No abstraction layers.

## Project Structure

```
src/lifeos/
    __main__.py   # Entry point for Telegram bot
    cli.py        # Entry point for CLI debugging
    bot.py        # Telegram handlers, reminder scheduler
    agent.py      # OpenAI Responses API, execute_sql tool
    db.py         # SQLite connection, schema
    logging.py    # Logging setup (UTC, RFC 3339)
```

## Key Files

- `agent.py`: Uses OpenAI Responses API (not Chat Completions). Tool calls return `function_call` type items.
- `bot.py`: `run_bot()` is synchronous - `Application.run_polling()` manages its own event loop.
- `db.py`: Schema has `tasks`, `reminders`, `notes` tables.

## Environment Variables

```
TELEGRAM_BOT_TOKEN      # Required for bot
OPENAI_API_KEY          # Required
PARAS_TELEGRAM_USER_ID  # Auth + reminders (chat_id == user_id for DMs)
LOG_LEVEL               # DEBUG, INFO (default), WARNING, ERROR
DB_PATH                 # Default: lifeos.db
```

## Conventions

- Logging: stdlib `logging`, UTC timestamps in RFC 3339 format
- Types: Use `ty` for type checking, `# type: ignore` with TODO for known issues
- Bot personality: Direct, terse, no pleasantries
