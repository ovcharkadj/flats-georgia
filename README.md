# Flats Georgia

Telegram digest of **new** long-term apartment rentals on
[MyHome.ge](https://www.myhome.ge/) that match one fixed filter
(Saburtalo, Tbilisi; USD 300–500 / month; long-term rent).

Runs on GitHub Actions on a schedule. Sends a guaranteed digest every morning
(11:00 Asia/Tbilisi) plus intraday checks that only message when something new
appeared. Each listing is shown as a link plus a one-line summary.

See [`SPEC.md`](SPEC.md) for the design and [`ROADMAP.md`](ROADMAP.md) for the
build plan.

## Status

Under construction, patch by patch (see `ROADMAP.md`). Not yet runnable
end to end.

## Local development

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
ruff check src tests
mypy src
```

Configuration lives in [`config.toml`](config.toml) (filter + behaviour, no
secrets). Secrets go in a local `.env` (see [`.env.example`](.env.example)) or
GitHub Actions secrets.

## Setup runbook

The full step-by-step (create the bot, find your chat id, add GitHub secrets,
enable Actions) is filled in by Patch 8. Short version:

1. Create a bot with [@BotFather](https://t.me/BotFather) → `TELEGRAM_BOT_TOKEN`.
2. Message the bot once, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → `chat.id` is
   `TELEGRAM_CHAT_ID`.
3. Add both as repository secrets under
   Settings → Secrets and variables → Actions.
