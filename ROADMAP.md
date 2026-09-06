# Roadmap: Flats Georgia — MyHome.ge Rent Watcher

Split-file output (SPEC.md + ROADMAP.md): the plan has more than 3 patches, so
the single-file threshold does not apply.

Each patch is small, independently testable, and has an acceptance criterion, a
boundary, and a place in the order. This document is a plan only — implementation
happens in a fresh session, one patch at a time, each merged only with green CI.

Read `SPEC.md` first: it holds the verified API details, IDs, field names, config
knobs, and the three-tier boundaries that every patch inherits.

## Patches

### Patch 1: Repository skeleton and configuration
Scope: create the structure from SPEC "Project structure"; `pyproject.toml`,
`requirements.txt`, `.gitignore`, `.env.example`, `README.md` stub, `config.toml`
with the fixed filter (`city=1`, `deal_type=2`, `real_estate_type=1`,
`currency=2`, `price_from=300`, `price_to=500`, `urbans=[47]`) and behaviour
knobs (`request_delay_seconds=1.5`, `max_pages_per_run=10`,
`always_send_hours_local=[11]`, `timezone="Asia/Tbilisi"`). `config.py` loads
`config.toml` + env into a typed frozen `Settings`.
Acceptance: `pip install -r requirements.txt` succeeds; `python -c "from
flats_georgia.config import load_settings; print(load_settings())"` prints the
filter and knob values; missing `TELEGRAM_*` env raises a clear error only when
`--dry-run` is not set (tested).
Boundary: no HTTP, no parsing, no Telegram, no CI yaml.
Depends on: none.

### Patch 2: MyHome API client
Scope: `sources/api.py` — call `GET https://api-statements.tnet.ge/v1/statements`
with the SPEC headers and the `Settings` filter, paginate to
`max_pages_per_run`, enforce `request_delay_seconds`, retry transient failures
with `tenacity`. `models.normalize_api` maps a raw dict to `Listing` (URL built
as `https://www.myhome.ge/en/pr/{id}/`, `posted_at` parsed as `Asia/Tbilisi`,
`price_usd`/`price_gel` from `price["2"]`/`price["1"]`, `is_agency` from
`user_type.type`).
Acceptance: unit test against `tests/fixtures/api_page1.json` +
`api_page2.json` yields the expected count of `Listing` objects with correct
`id`, `url`, `price_usd`, `area_m2`, `is_agency`; a `@pytest.mark.live` test
returns ≥1 listing and every `Listing.id` is a positive int.
Boundary: no dedup, no HTML fallback, no Telegram.
Depends on: Patch 1.

### Patch 3: HTML fallback source
Scope: `sources/html_fallback.py` — fetch
`https://www.myhome.ge/en/real-estate/?<params>`, extract `__NEXT_DATA__`, walk
to the `statements` query array, map through the same `models.normalize_api`
(same object shape). `sources/__init__.py` exposes `get_listings(settings)` that
tries the API first and falls back to HTML on exception or empty result, logging
which source served the data.
Acceptance: unit test against `tests/fixtures/search_page.html` yields `Listing`
objects equivalent to the API fixture for the same listings;
`test_sources_failover.py` — with the API client patched to raise, `get_listings`
returns the HTML result; with the API returning `[]`, it also falls back.
Boundary: no dedup, no Telegram.
Depends on: Patch 2.

### Patch 4: Seen-IDs state store
Scope: `dedup.py` — `SeenStore` backed by `state/seen_ids.json`
(`{"ids": [...], "updated_at": "..."}`). `load()`, `filter_new(listings) ->
list[Listing]` (returns listings whose `id` is not stored, preserving order),
`save(listings)` (union, sorted, capped to a configurable `max_stored=20000` most
recent). First run (file absent or `ids` empty): every listing is "new".
Acceptance: with a store seeded from 5 ids, `filter_new` on 8 listings returns the
3 unseen; after `save`, the file contains all 8; absent file → all listings
returned and file created; cap keeps the highest ids.
Boundary: no HTTP, no Telegram, no scheduling logic.
Depends on: Patch 1.

### Patch 5: Telegram formatting and sender
Scope: `telegram.py` — `format_listing(listing) -> str` (one block: title,
`$USD (₾GEL)`, `area m²`, `rooms`, `floor/total`, area name, `posted_at HH:MM`,
`owner`/`agency`, link on its own line); `build_messages(listings, header) ->
list[str]` chunking to ≤4096 chars (never splitting a listing block); `send(text)`
via Bot API `sendMessage` with `disable_web_page_preview=false` for the first,
`true` for the rest. `--dry-run` prints instead of calling the API.
Acceptance: `format_listing` on a fixture `Listing` matches an expected string;
`build_messages` on 60 fixture listings produces multiple messages each ≤4096 and
no block split; with `httpx` mocked, `send` posts the exact payload to the
`sendMessage` URL; `--dry-run` path performs zero HTTP calls (asserted).
Boundary: no fetching, no dedup, no schedule.
Depends on: Patch 1.

### Patch 6: Pipeline orchestration and CLI
Scope: `pipeline.py` `run(settings, *, dry_run, force_full, source, always_send)`
— `get_listings` → (`force_full` ? all : `SeenStore.filter_new`) → if empty and
not (`always_send` or current Tbilisi hour in `always_send_hours_local`): log and
exit 0 without sending → else `build_messages` (header includes date/time and
counts, or "no new listings") → `send` each → `SeenStore.save` (skipped on
`dry_run` and when nothing was fetched). `__main__.py` parses `--dry-run`,
`--force-full`, `--source {api,html}`, `--always-send`. Non-zero exit on
unrecovered fetch/send failure.
Acceptance: `test_pipeline.py` with mocked source + mocked Telegram — new
listings present → correct messages sent and state written; run again → nothing
sent, state unchanged; `always_send` with nothing new → one "no new listings"
message; `dry_run` → no send, no state write; source failure → non-zero exit.
Boundary: no GitHub Actions yaml.
Depends on: Patches 3, 4, 5.

### Patch 7: GitHub Actions — CI and scheduled digest
Scope: `.github/workflows/ci.yml` (ruff + mypy + pytest on push/PR).
`.github/workflows/digest.yml` — `workflow_dispatch` + `schedule` crons at
`07,10,13,16,19` UTC (11:00, 14:00, 17:00, 20:00, 23:00 Tbilisi); checkout, setup
Python 3.12, install, run `python -m flats_georgia` (the 07:00 job also passes
`--always-send`), then commit `state/seen_ids.json` if changed with
`[skip ci]`; `concurrency: group=digest, cancel-in-progress=false`. Secrets
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
Acceptance: `ci.yml` green on the repo; a manual `digest.yml` run posts a real
Telegram message and pushes an updated `state/seen_ids.json`; a second manual run
within minutes posts nothing (only the morning slot would); the commit uses
`[skip ci]` and does not trigger `ci.yml`.
Boundary: no changes to `src/` logic.
Depends on: Patch 6.

### Patch 8: Hardening and docs
Scope: `keepalive.yml` (monthly `workflow_dispatch`/cron that makes an empty
commit with a `KEEPALIVE_PAT` secret so scheduled workflows stay enabled);
failure notification — on an unrecovered exception the process sends one short
error line to the same chat before exiting non-zero; jitter of ±0–1 s added to
`request_delay_seconds`; `README.md` completed with the full setup runbook
(create bot via `@BotFather`, obtain chat id, add the three secrets, enable
Actions, the 60-day keepalive note).
Acceptance: forcing an exception in a test triggers exactly one error message
then a non-zero exit; README lists every secret the workflows reference and the
steps map to what a non-programmer can follow; `keepalive.yml` dry-parses in CI
(`actionlint`).
Boundary: no new listing-processing features; filter and schedule unchanged.
Depends on: Patch 7.

## Deferred (not this round)

Managing the filter from Telegram; multiple filter sets; a min-area / listing
noise filter; photos in the message; email channel; storing state in a gist
instead of the repo. Each is a clean follow-up patch on top of this base.
