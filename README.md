# Flats Georgia

Telegram digest of **new** long-term apartment rentals on
[MyHome.ge](https://www.myhome.ge/) that match one fixed filter: **Saburtalo,
Tbilisi; USD 300–500 / month; long-term rent**.

It runs on GitHub Actions on a schedule (Tbilisi time, UTC+4):

| Run | What it sends |
|-----|---------------|
| 11:00 daily | always a digest — the new listings, or "Новых объявлений нет." |
| 14:00 / 17:00 / 20:00 / 23:00 | a message **only if** new matching listings appeared |

Each listing is one block: price (`$` and `₾`), rooms, area, floor, area + nearest
metro, owner/agency, posting time, and the link on its own line. "New" is decided
by the MyHome listing id, which is stable when a listing is bumped — so re-bumped
old listings are never re-sent.

Design: [`SPEC.md`](SPEC.md) · Build plan: [`ROADMAP.md`](ROADMAP.md).

## One-time setup

You need a Telegram bot and two GitHub repository secrets. ~10 minutes.

### 1. Create the bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram, send `/newbot`.
2. Give it a name, then a username ending in `bot`.
3. BotFather replies with a token like `123456789:AAExxxxxxxxxxxxxxxxxxxxxxxxxx`.
   This is **`TELEGRAM_BOT_TOKEN`**.

### 2. Find your chat id

1. Open the chat with your new bot and press **Start** (or send it any message).
   This step is required — a bot cannot message you until you message it first.
2. Open this URL in a browser, with your token pasted in place of `<TOKEN>`
   (keep the word `bot` right before the token, no spaces, no `<>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. In the response find `"chat":{"id":123456789,` — that number is
   **`TELEGRAM_CHAT_ID`**. If the response is `{"ok":true,"result":[]}`, send the
   bot another message and refresh.

### 3. Add the secrets on GitHub

Repository → **Settings** → **Secrets and variables** → **Actions** →
**New repository secret**, twice:

| Name | Value |
|------|-------|
| `TELEGRAM_BOT_TOKEN` | from step 1 |
| `TELEGRAM_CHAT_ID` | from step 2 |

### 4. Enable Actions and do a test run

1. Open the **Actions** tab. If it asks, enable workflows for the repository.
2. Pick **Digest** → **Run workflow** → **Run workflow**.
3. Within a minute or two the bot should message you. The first run sends
   everything currently in the filter (can be ~150–200 listings, paced over a few
   minutes); every run after that only sends what is genuinely new.

### 5. (Recommended) keep the schedule alive

GitHub disables scheduled workflows after 60 days without a real commit, and the
bot's own state commits do not count. Two options:

- Add a third secret **`KEEPALIVE_PAT`** — a
  [fine-grained personal access token](https://github.com/settings/tokens?type=beta)
  scoped to this repo with **Contents: read and write**. The monthly
  **Keepalive** workflow then makes a real commit for you.
- Or just push any commit to the repo at least once every ~50 days.

## Changing the filter or schedule

- **Filter** (district, price, deal type): edit `[filter]` in
  [`config.toml`](config.toml) and push. `urbans = [47]` is MyHome's "Saburtalo"
  area; price is in USD.
- **Schedule**: edit the `cron:` lines in
  [`.github/workflows/digest.yml`](.github/workflows/digest.yml). They are in
  **UTC** — Tbilisi is UTC+4 all year, so subtract 4 hours. Keep `0 7 * * *`
  (11:00 Tbilisi) as the guaranteed daily slot, or update the matching string in
  the "Run digest" step too.
- **Behaviour knobs** (request pacing, how many ids to remember): `[behaviour]`
  in `config.toml`.

If it stops sending, check the **Actions** tab for a red run — the bot also
messages you `⚠️ Flats Georgia: …` when the data source fails.

## Local development

```
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows;  source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
pytest                            # offline
pytest -m live                    # hits the real MyHome API / Telegram (needs .env)
ruff check src tests && ruff format --check src tests
mypy src
```

Run it without sending anything:

```
python -m flats_georgia --dry-run --always-send
```

Secrets for local runs go in a `.env` file (see [`.env.example`](.env.example));
`.env` is git-ignored.

### CLI flags

| Flag | Effect |
|------|--------|
| `--dry-run` | print the digest, send nothing, write no state |
| `--force-full` | treat every current listing as new (re-send the whole filter) |
| `--always-send` | send a message even when nothing is new |

Exit codes: `0` ok · `2` data source failed · `3` sending failed.
