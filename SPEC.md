# Spec: Flats Georgia — MyHome.ge Rent Watcher

## Objective

Deliver a Telegram digest of **new** long-term apartment rental listings from
MyHome.ge that match one fixed filter (Saburtalo district, Tbilisi, USD 300–500
per month). The digest runs on a schedule: one guaranteed message every morning
plus several intraday checks that only message when something new appeared. Each
listing is shown as a clickable link plus a one-line summary (price, area, rooms,
floor, area name, posting time, owner/agency). The digest is ordered by USD price,
most expensive first (listings with no USD price go last).

Consumer: the project owner only (a single private Telegram chat).

Out of scope for this round: managing the filter from inside Telegram; multiple
filter sets; email or any second delivery channel; embedding photos in the
message; a web UI; historical analytics; any listing interaction (favoriting,
contacting).

## Stack

- Python 3.12+
- `httpx` (HTTP client with timeouts + retry/backoff), `tenacity` (retry),
  `tzdata` (IANA zones on Windows / slim runners), `python-dotenv`, stdlib
  `tomllib` for config.
- No web framework. The deliverable is a CLI script run by CI.
- Runtime: GitHub Actions scheduled workflows on a **public** repository
  (unlimited free minutes; cron supported). State is committed back to the repo.
- Delivery: Telegram Bot API (`sendMessage`), one bot, one chat.
- Dev tooling: `pytest`, `ruff` (lint + format), `mypy`.

### External data source (verified 2026-09-06)

Primary — undocumented internal JSON API:

```
GET https://api-statements.tnet.ge/v1/statements
Headers:
  X-Website-Key: myhome
  Accept: application/json
  locale: en
  User-Agent: <a normal desktop browser UA>
Query:
  cities=1                 # Tbilisi
  deal_types=2             # long-term rent (1=sale, 3=lease, 7=daily rent)
  real_estate_types=1      # apartment
  currency_id=2            # USD (1=GEL, 3=EUR)
  price_from=300
  price_to=500
  urbans[]=47              # "Saburtalo" urban area (covers all 5 target metro stations)
  page=<1..N>              # 20 results per page
```

Response shape: `body.result == true`, listings at `body.data.data` (array of 20).
The list response carries **no** total/last_page fields, so paginate with `page=1,2,…`
until a page returns an empty array (and always stop at `max_pages_per_run`). Do
**not** rely on `GET /v1/statements/count` — in testing it ignored the query
filters.

Per-listing fields used: `id` (int, monotonically increasing — the newness
signal), `uuid`, `dynamic_title`, `href_lang` (localized slugs), `address`
(Georgian), `area` (m², number), `room`, `bedroom`, `floor`, `total_floors`,
`urban_name`, `district_name`, `metro_station_id`, `last_updated`
(`YYYY-MM-DD HH:MM:SS`, bump time — not creation), `price` (object keyed
`"1"`=GEL `"2"`=USD `"3"`=EUR, each `{price_total, price_square}`), `user_type`
(`{type: "physical" | "agency", ...}`), `images` (array; `[0].thumb`).

Listing URL: `https://www.myhome.ge/en/pr/{id}/`.

Reference IDs (for display / optional future filtering):
metro stations — State University 1, Vazha-Pshavela 2, Delisi 3,
Medical University 4, Technical University 5. All sit inside `urban_id=47`.
`user_type.type` seen values: `physical` (owner) vs `agent` / `agency` / `broker`
(treated as agency).

### No fallback source (decision, 2026-09-06)

`www.myhome.ge` sits behind bot protection: a plain HTTP client gets **HTTP 403**
for the search page HTML *and* for `/_next/data/…json`. Only
`api-statements.tnet.ge` serves non-browser clients. A headless-browser fallback
was considered and declined for this round (weight and fragility out of
proportion to a rarely-triggered safety net). So the JSON API is the **sole**
source. If it fails, the run sends one failure notice to the Telegram chat and
exits non-zero (see pipeline). `sources/` keeps a single-function seam
(`get_listings`) so a browser fallback can be added later as its own patch
without touching callers.

### Constraints

- Georgia is UTC+4 year-round (no DST).
- **GitHub's scheduled runs do not work reliably for this repo** — observed:
  delayed hours, and whole days with zero runs. The real trigger is an external
  cron (cron-job.org) calling the `workflow_dispatch` REST API every ~30 min with
  a fine-grained PAT (Actions: write). `digest.yml` keeps a `schedule:` block as
  a free backup. The pipeline — not the trigger — owns *what* each run does, so
  trigger cadence only affects latency, never correctness.
- Public-repo scheduled workflows auto-disable after 60 days with no repo
  activity, and commits made by the built-in `GITHUB_TOKEN` do **not** reset that
  timer. Mitigation: a monthly keepalive job that commits with a user PAT, or the
  owner pushes any commit at least every ~50 days. Documented in README.
- Polite scraping caps (config, enforced in code): ≥1.5 s (+0–1 s jitter) between
  page requests, ≤10 pages per run. The Saburtalo/$300–500 pool is >200, so a run
  fetches all 10 pages every time (the list endpoint gives no total to stop
  early); after the first run `filter_new` leaves only a handful.
- Telegram messages are paced `message_pause_seconds` (3 s) apart so a big
  first-run digest does not trip the ~20 messages/minute bulk limit; the sender
  also retries 429/5xx with backoff.
- Each run: quiet hours → exit; else fetch, `filter_new`, then send when **any**
  of: there are new listings; the once-a-day digest is still owed
  (`store.last_digest_date != today` and local hour ≥ `daily_digest_hour = 11`);
  `--always-send`; `--force-full`. Any digest sent at/after hour 11 stamps
  `last_digest_date = today`, so exactly one guaranteed digest goes out per day —
  on the first run that manages to happen at/after 11:00, which survives GitHub
  skipping the 11:xx slots.
- `quiet_hours_local = [0..10]`: a run whose local hour is in this list sends
  **nothing at all** (not even error notices) and exits before fetching —
  `--force-full` and `--dry-run` bypass it. Guards against GitHub delaying an
  evening run past midnight.
- `state/seen_ids.json` carries `ids` (the seen set, capped to `max_stored_ids`)
  and `last_digest_date` (nullable string; absent in pre-Patch-10 files).
- Secrets never enter the repo: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` live only
  in GitHub Actions secrets / local `.env`.

## Commands

- Create env: `python -m venv .venv`
- Activate (Windows): `.venv\Scripts\Activate.ps1`
- Install (runtime): `pip install -e .`
- Install (with dev tooling): `pip install -e ".[dev]"`
- Dry run (prints digest, sends nothing, no state): `python -m flats_georgia --dry-run`
- Real run (the scheduled behaviour): `python -m flats_georgia`
- Re-send everything currently in the filter: `python -m flats_georgia --force-full`
- Send now even if nothing is new / already sent today: `python -m flats_georgia --always-send`
- Tests: `pytest` (offline). Live smoke tests: `pytest -m live`
- Lint: `ruff check src tests` and `ruff format --check src tests`
- Types: `mypy src`

## Testing

- `pytest`, tests in `tests/`, offline by default using saved fixtures in
  `tests/fixtures/` (`api_page1.json`, `api_page2.json`, `api_page_empty.json`).
- Live tests that hit MyHome.ge or Telegram are marked `@pytest.mark.live` and
  skipped unless `pytest -m live` (and required env vars are present).
- Must cover: API pagination + normalization, dedup (first run, steady state,
  state merge), digest formatting incl. Telegram 4096-char chunking, pipeline
  end-to-end with mocked source + mocked Telegram, and the API-failure path
  (one error message sent, non-zero exit).
- CI runs `ruff`, `mypy`, `pytest` on every push and PR.

## Project structure

```
flats-georgia/
  pyproject.toml            # build metadata, ruff/mypy/pytest config
  requirements.txt
  README.md                 # setup: BotFather, chat id, GH secrets, keepalive
  config.toml               # the filter + behaviour knobs (no secrets)
  .env.example              # TELEGRAM_BOT_TOKEN=, TELEGRAM_CHAT_ID=
  src/flats_georgia/
    __init__.py
    __main__.py             # CLI arg parsing -> pipeline.run()
    config.py               # load config.toml + env, expose typed Settings
    models.py               # Listing dataclass + normalization helpers
    sources/
      __init__.py           # SourceError + get_listings(settings) seam
      api.py                # tnet JSON API client + pagination
    dedup.py                # SeenStore: load/filter_new/save (state/seen_ids.json)
    telegram.py             # format_listing, build_messages, send
    pipeline.py             # orchestration: fetch -> filter -> send -> persist
  state/
    seen_ids.json           # {"ids": [int, ...], "updated_at": "..."} — CI commits this
  tests/
    fixtures/
    test_api.py
    test_dedup.py
    test_telegram.py
    test_pipeline.py
  .github/workflows/
    ci.yml                  # ruff + mypy + pytest
    digest.yml              # scheduled + manual runs, commits state back
    keepalive.yml           # monthly PAT commit so schedules stay enabled
```

## Code style

- PEP 8 enforced by `ruff`; `ruff format` for layout.
- Full type hints; `mypy --strict`-ish (at least no untyped defs in `src`).
- Data carriers are `@dataclass(frozen=True, slots=True)`.
- One responsibility per module; `sources/` is the only place that knows MyHome's
  wire format, everything downstream works on `Listing`.
- `httpx` calls always pass `timeout=`; retries via `tenacity` with capped
  exponential backoff; never a bare `except:`.
- `logging` module, not `print` (except the `--dry-run` digest output).

Example shape:

```python
@dataclass(frozen=True, slots=True)
class Listing:
    id: int
    url: str
    title: str
    price_usd: int | None
    price_gel: int | None
    area_m2: float | None
    rooms: str | None
    bedrooms: str | None
    floor: int | None
    total_floors: int | None
    area_name: str          # urban_name
    district: str
    metro_station_id: int | None
    posted_at: datetime | None  # parsed last_updated, tz=Asia/Tbilisi
    is_agency: bool

def normalize_api(raw: dict, *, listing_url_template: str, tz: ZoneInfo) -> Listing:
    ...
```

## Git workflow

- Trunk-based on `main`; short-lived branches `feat/<slug>` or `fix/<slug>`.
- Conventional Commits (`feat:`, `fix:`, `chore:`, `test:`, `ci:`).
- One ROADMAP patch = one PR (or one commit for the solo owner), merged only with
  green CI.
- The `digest.yml` workflow commits `state/seen_ids.json` with message
  `chore(state): update seen ids [skip ci]` using a `concurrency:` group so
  overlapping scheduled runs serialize.
- `.env`, `.venv/`, `__pycache__/` in `.gitignore`. `state/seen_ids.json` is
  tracked.

## Boundaries

Always (no confirmation needed):
- Fetch public listing data for the filter defined in `config.toml`.
- Send the formatted digest to the single configured Telegram chat.
- Update and commit `state/seen_ids.json` on CI runs.
- Log every fetch and send.

Ask first (pause for the owner's approval):
- Changing any `config.toml` filter value (price, area, `urbans`, deal type,
  city) or the cron schedule.
- Adding a delivery channel, a second chat, or a second filter set.
- Adding a new third-party dependency or any paid service.
- Raising the polite-scraping caps (request delay, pages per run, runs per hour).
- Changing repo visibility or moving it to another account.
- Any change that makes the bot write somewhere new (a gist, another repo, an
  external store).

Never:
- Commit or hard-code `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID`; secrets only.
- Send to any chat other than the configured one.
- Exceed the polite-scraping caps, or add parallel/burst requests.
- Attempt to defeat authentication, captchas, rate limiting, or anti-bot
  measures.
- Republish or forward the scraped data anywhere beyond the owner's own digest.
- Clear or rewrite `state/seen_ids.json` without the owner asking.
- Implement a patch that the ROADMAP has not defined and the owner has not
  approved.

## Success criteria

- `ruff check`, `ruff format --check`, `mypy src`, and `pytest` all pass in CI.
- `python -m flats_georgia --dry-run` prints a well-formed digest (from fixtures
  offline, or live) and sends nothing.
- A manual `workflow_dispatch` run of `digest.yml` posts a real Telegram message
  and pushes an updated `state/seen_ids.json`.
- Two runs back-to-back: the second sends nothing. Exactly one digest per day
  goes out at/after 11:00 Tbilisi even if the 11:xx runs were skipped — a later
  run that day catches up.
- With the API forced to fail (test injects repeated 500s), the run sends exactly
  one error message to the chat and exits non-zero.
- Done-means: for one full week the owner receives the morning digest every day
  and intraday messages only when MyHome.ge actually has new matching listings,
  with no duplicates across messages.
