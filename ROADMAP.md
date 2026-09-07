# Roadmap: Flats Georgia — MyHome.ge Rent Watcher

Split-file output (SPEC.md + ROADMAP.md): the plan has more than 3 patches, so
the single-file threshold does not apply.

Each patch is small, independently testable, and has an acceptance criterion, a
boundary, and a place in the order. Implementation is one patch at a time, each
committed only with lint + types + tests green.

Read `SPEC.md` first: it holds the verified API details, IDs, field names, config
knobs, and the three-tier boundaries that every patch inherits.

**Revision 2 (2026-09-06):** the HTML fallback (old Patch 3) is dropped — MyHome's
web pages return HTTP 403 to non-browser clients, so the JSON API is the sole
source (see SPEC "No fallback source"). The API-failure notification, previously
folded into Patch 8, is now part of the pipeline (Patch 5). Patches renumbered.

**Status (2026-09-07): LIVE. Patches 1–11 done and pushed.** The digest runs from
an external cron (cron-job.org) that hits the `workflow_dispatch` API every ~30
min; the GitHub `schedule:` block is a backup. Telegram delivery, quiet hours,
once-a-day digest, price ordering — all verified live. Patches 8–11 were added
after first-run feedback (see their notes). Repo: github.com/ovcharkadj/flats-georgia.

To continue in a fresh session: open it in this folder (memory auto-loads),
re-attach `ПРАВИЛАОБЩЕНИЯ.md`, and read `SPEC.md` + this file first. Nothing to
copy — code lives in git here and on GitHub.

### Patch 8: Order the digest by price (most expensive first)
Scope: `pipeline._by_price_desc` sorts the selected listings by `price_usd`
descending before formatting; listings with no USD price sort last. Applied on
both the normal and `--force-full` paths.
Acceptance: `test_digest_is_ordered_most_expensive_first` — a mix of prices and a
priceless listing come out 500 → 420 → 350 → (no price) in the message body.
Boundary: filter, schedule, and delivery unchanged; ordering only.
Depends on: Patch 5.

### Patch 9: Quiet hours + trimmed schedule (owner got a 01:09 notification)
Scope: `quiet_hours_local` (00:00–10:59 Tbilisi) in config; `pipeline.run` exits
early before fetching when the current local hour is quiet, unless `--force-full`
or `--dry-run`. `digest.yml`: drop the 23:00 Tbilisi cron, split the intraday
cron into `0 10/13/16` (14:00/17:00/20:00 Tbilisi).
Acceptance: a run at 01:09 with `always_send` sends nothing, hits no source, writes
no state; `--force-full` at 01:09 still runs; `test_workflows` asserts the new
cron set and the absence of `0 19 * * *`.
Boundary: filter unchanged; only schedule and the quiet-hours gate.
Depends on: Patch 6, Patch 8.

### Patch 10: Self-healing schedule (GitHub keeps skipping the 11:00 run)
Scope: GitHub dropped the `0 7 * * *` run entirely one morning. Move the "when"
decision out of cron into the pipeline. State gains `last_digest_date`; a run
sends when there are new listings OR the daily digest is still owed
(`last_digest_date != today` and local hour ≥ `daily_digest_hour`); any digest
sent at/after that hour stamps the date. `always_send_hours_local` →
`daily_digest_hour`. `digest.yml`: one cron `17,47 7-19 * * *` (poll twice an
hour, off the hour); manual dispatch passes `--always-send`; state commit does
`git pull --rebase --autostash` before push.
Acceptance: a first run of the day at 12:37 sends the digest and stamps the date;
a later same-day run with nothing new stays silent; `SeenStore` round-trips
`last_digest_date` and tolerates its absence in old files; `test_workflows`
asserts the single off-the-hour cron.
Boundary: filter unchanged; scheduling/decision logic only.
Depends on: Patch 9.

### Patch 11: External trigger (GitHub's cron ran 0 times in a day)
Scope: GitHub's scheduler did not fire once in ~18h. `digest.yml` gets a
`workflow_dispatch` boolean input `always_send` (default false); the run step
keys `--always-send` off `inputs.always_send`, not off the event type, so an
external cron (cron-job.org) hitting the dispatch API every ~30 min gets normal
pipeline behaviour. The `schedule:` block stays as a no-cost backup. README gets
the cron-job.org + fine-grained-PAT runbook.
Acceptance: `test_workflows` asserts the `always_send` input exists and the run
step branches on `inputs.always_send`; digest.yml parses.
Boundary: no code/filter change; workflow trigger + docs only.
Depends on: Patch 10.

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

### Patch 3: Seen-IDs state store
Scope: `dedup.py` — `SeenStore` backed by `state/seen_ids.json`
(`{"ids": [...], "updated_at": "..."}`). `load()`, `filter_new(listings) ->
list[Listing]` (returns listings whose `id` is not stored, preserving order),
`save(listings)` (union, sorted, capped to `max_stored_ids` most recent). First
run (file absent or `ids` empty): every listing is "new".
Acceptance: with a store seeded from 5 ids, `filter_new` on 8 listings returns the
3 unseen; after `save`, the file contains all 8; absent file → all listings
returned and file created; cap keeps the highest ids; a malformed state file is
reported, not silently treated as empty.
Boundary: no HTTP, no Telegram, no scheduling logic.
Depends on: Patch 1.

### Patch 4: Telegram formatting and sender
Scope: `telegram.py` — `format_listing(listing) -> str` (one block: title,
`$USD (₾GEL)`, `area m²`, `rooms`, `floor/total`, area name, `posted_at HH:MM`,
`owner`/`agency`, link on its own line); `build_messages(listings, header) ->
list[str]` chunking to ≤4096 chars (never splitting a listing block);
`TelegramSender.send_message(text)` via Bot API `sendMessage`;
`TelegramSender.send_error(text)` for the failure notice. A `DryRunSender` prints
instead of calling the API.
Acceptance: `format_listing` on a fixture `Listing` contains the price, area,
link and owner/agency marker; `build_messages` on 60 fixture listings produces
messages each ≤4096 with no block split; with `httpx` mocked, `send_message`
posts the expected payload to the `sendMessage` URL; `DryRunSender` performs zero
HTTP calls (asserted).
Boundary: no fetching, no dedup, no schedule.
Depends on: Patch 1.

### Patch 5: Pipeline orchestration and CLI
Scope: `sources/__init__.get_listings(settings)` (thin seam over the API client).
`pipeline.run(settings, *, dry_run, force_full, always_send) -> int` —
`get_listings` → (`force_full` ? all : `SeenStore.filter_new`) → if empty and not
(`always_send` or current Tbilisi hour in `always_send_hours_local`): log, exit 0
without sending → else `build_messages` (header with date/time + counts, or "no
new listings") → send each → `SeenStore.save` (skipped on `dry_run`). On
`SourceError` / send failure: send one error notice (unless `dry_run`), return a
non-zero code. `__main__.py` parses `--dry-run`, `--force-full`, `--always-send`
and calls `sys.exit(run(...))`.
Acceptance: `test_pipeline.py` with mocked source + mocked sender — new listings →
correct messages sent and state written; run again → nothing sent, state
unchanged; `always_send` with nothing new → one "no new listings" message;
`dry_run` → no send, no state write; `SourceError` → exactly one error notice and
non-zero return; error path under `dry_run` → no send, still non-zero.
Boundary: no GitHub Actions yaml.
Depends on: Patches 2, 3, 4.

### Patch 6: GitHub Actions — CI and scheduled digest
Scope: `.github/workflows/ci.yml` (ruff + ruff format --check + mypy + pytest on
push/PR, Python 3.12). `.github/workflows/digest.yml` — `workflow_dispatch` +
`schedule` crons at `07,10,13,16,19` UTC (11:00/14:00/17:00/20:00/23:00 Tbilisi);
checkout, setup Python 3.12, `pip install -e .`, run `python -m flats_georgia`
(the 07:00 slot also passes `--always-send`), then commit `state/seen_ids.json`
if changed with `chore(state): update seen ids [skip ci]`;
`concurrency: group=digest, cancel-in-progress=false`. Secrets
`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
Acceptance: `ci.yml` green on the repo; a manual `digest.yml` run posts a real
Telegram message and pushes an updated `state/seen_ids.json`; a second manual run
within minutes posts nothing (only the morning slot would); the state commit uses
`[skip ci]` and does not trigger `ci.yml`.
Boundary: no changes to `src/` logic.
Depends on: Patch 5.

### Patch 7: Hardening and docs
Scope: `keepalive.yml` (monthly cron making a real commit via `KEEPALIVE_PAT`,
falling back to the default token, so scheduled workflows stay enabled); ±0–jitter
added to `request_delay_seconds` in the API client; `message_pause_seconds` gap
between Telegram messages (first-run flood vs the ~20/min bulk limit); `README.md`
completed with the full setup runbook (bot via `@BotFather`, chat id, secrets,
enable Actions, the 60-day keepalive note, how to change the filter/schedule).
Acceptance: jitter keeps each inter-page wait within `[delay, delay + jitter]`
(tested); messages are paced by `message_pause_seconds` (tested); README lists
every secret the workflows reference; `tests/test_workflows.py` parses all three
workflows and asserts the cron slots, the always-send branch, and the `[skip ci]`
state commit.
Boundary: no new listing-processing features; filter and schedule unchanged.
Depends on: Patch 6.

## Deferred (not this round)

Browser-based fallback source (only if the API proves unstable); managing the
filter from Telegram; multiple filter sets; a min-area / listing noise filter;
photos in the message; email channel; storing state in a gist instead of the
repo. Each is a clean follow-up patch on top of this base.
