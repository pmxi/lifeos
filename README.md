https://github.com/python-telegram-bot/python-telegram-bot
https://core.telegram.org/api
Full API Reference for Telegram Bot API
https://core.telegram.org/bots/api

Telegram bot
uv run lifeos
Interactive REPL for debugging
LOG_LEVEL=DEBUG uv run lifeos-cli


type check
uv run ty check
linter check
uv run ruff check
format check?
sort imports?
Anything else?

Gmail/Google Calendar MCP
https://github.com/taylorwilsdon/google_workspace_mcp 1.1k stars
https://github.com/j3k0/mcp-google-workspace 17 stars
https://github.com/bastienchabal/gmail-mcp 0 stars

Priority queue
- Allow lifeos calling itself
- Improve schema
- Fetch my phone charger
- Test with Telegram
- make command for format files
- Set up docker
- add color to logging

Setup (Calendar + Auth)
- Create a Google Cloud project (new is recommended for clean separation).
- Enable the Google Calendar API in that project.
- Create a Google Cloud OAuth client (Desktop app) and download the client secret JSON:
  - In Google Cloud Console, go to API & Services → Credentials.
  - Click “Create Credentials” → “OAuth client ID”.
  - If prompted, configure the OAuth consent screen (External is fine) and add your email as a test user.
  - Choose “Desktop app” as the application type and create the client.
  - Download the JSON file and keep its path for `GOOGLE_CLIENT_SECRET_PATH`.
- Add a `.env` file in the repo root with:
  - `OPENAI_API_KEY=...`
  - `GOOGLE_CLIENT_SECRET_PATH=/absolute/path/to/client_secret.json`
  - Optional: `GOOGLE_TOKEN_PATH=.secrets/google_token.json` (default)
  - Optional: `GOOGLE_USER_EMAIL=you@example.com`
- Tokens default to `.secrets/google_token.json` (gitignored).
- Authenticate locally:
  - `uv run lifeos-google-auth`
- Run the CLI:
  - `uv run lifeos-cli`


competitors
    https://github.com/clawdbot/clawdbot
        https://news.ycombinator.com/item?id=46760237
    poke.com
