# Flats Georgia

Telegram digest of **new** long-term apartment rentals on
[MyHome.ge](https://www.myhome.ge/) that match one fixed filter: **Saburtalo,
Tbilisi; USD 300–500 / month; long-term rent**.

The digest logic runs as a GitHub Actions workflow. GitHub's own scheduler turned
out to be unreliable for this repo (whole days with zero runs), so the workflow
is triggered by an external cron — [cron-job.org](https://cron-job.org) — every
~30 minutes (see "External trigger" below). The `schedule:` block in
`digest.yml` stays as a free backup. The pipeline decides what each run does:

- **Once a day**, on the first run at or after 11:00 Tbilisi, it sends a digest —
  the new listings, or "Новых объявлений нет." if there are none. If GitHub skips
  the 11:xx runs (it often does), a later run that day catches up.
- **The rest of the day** it sends a message only when new matching listings
  appeared.
- **00:00–11:00 Tbilisi** (`quiet_hours_local` in `config.toml`) it sends nothing
  at all — enforced in code, so a run GitHub delays past midnight stays silent.

Each listing is one block: price (`$` and `₾`), rooms, area, floor, area + nearest
metro, owner/agency, posting time, and the link on its own line. The digest is
ordered by price, most expensive first. "New" is decided by the MyHome listing
id, which is stable when a listing is bumped — so re-bumped old listings are
never re-sent.

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

### 5. External trigger (required — GitHub's cron does not run reliably)

1. Create a **fine-grained personal access token**:
   [github.com/settings/personal-access-tokens](https://github.com/settings/personal-access-tokens)
   → Generate new token → Resource owner: your account → Repository access: only
   `flats-georgia` → Permissions → Repository permissions → **Actions:
   Read and write** (leave everything else). Copy the token (`github_pat_…`).
2. Test it works, replacing `<PAT>`:
   ```
   curl -X POST -H "Authorization: Bearer <PAT>" -H "Accept: application/vnd.github+json" \
     https://api.github.com/repos/ovcharkadj/flats-georgia/actions/workflows/digest.yml/dispatches \
     -d '{"ref":"main"}'
   ```
   A `204 No Content` (empty) response means success — check the Actions tab for
   a new run.
3. Sign up at [cron-job.org](https://cron-job.org) (free). Create a cronjob:
   - **URL**: `https://api.github.com/repos/ovcharkadj/flats-georgia/actions/workflows/digest.yml/dispatches`
   - **Request method**: `POST`
   - **Request body**: `{"ref":"main"}`
   - **Headers**: `Authorization: Bearer <PAT>` and
     `Accept: application/vnd.github+json`
   - **Schedule**: every 30 minutes (or every hour). Quiet hours and the
     once-a-day rule are handled by the code, so extra triggers are harmless.
4. Save. That's it — the digest now runs on cron-job.org's schedule.

### 6. (Optional) keep the backup schedule alive

GitHub disables the `schedule:` trigger after 60 days without a real commit. Since
it is only a backup you can ignore this, or add a **`KEEPALIVE_PAT`** secret
(fine-grained token, **Contents: read and write**) so the monthly **Keepalive**
workflow makes a commit for you.

## Changing the filter or schedule

- **Filter** (district, price, deal type): edit `[filter]` in
  [`config.toml`](config.toml) and push. `urbans = [47]` is MyHome's "Saburtalo"
  area; price is in USD.
- **Schedule / quiet hours**: the daily-digest hour and quiet window are
  `daily_digest_hour` and `quiet_hours_local` in `config.toml` (Tbilisi local
  hours). How often the digest *runs* is set on cron-job.org, not in the repo.
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
