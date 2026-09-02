# Bazaar Tracker

Home-grown run tracker for The Bazaar. Reads `Player.log` live, stores each
run locally as it happens (SQLite), and pushes the finished run to Supabase
once it ends.

Replaces the log-parsing part of the cloned Bazaar Chronicle project, whose
markers for run-end / rank / board detection no longer match the current
client (1.0.12222). See `docs` conversation history / the design doc for the
full rationale and known limitations (shop contents aren't observable from
the log; final numeric stats still need OCR).

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in SUPABASE_URL / SUPABASE_SERVICE_KEY
```

Run the schema in `supabase/schema.sql` once in your Supabase project's SQL
editor before the tracker tries to sync anything.

## Validate the parser (no game required)

```bash
python -m tracker.main --replay tests/sample_run.log
```

Prints event counts and a per-run summary. Runs entirely offline against a
real, complete run log (hero Jules, Ranked, defeat) -- no screenshots, no
OCR, no network calls.

## Run live

```bash
python -m tracker.main
```

Or just double-click `run_tracker.bat`.

Tails the real `Player.log`, writes to `%APPDATA%\Bazaar Tracker\tracker.sqlite3`
as the game plays, captures + OCRs the final board screenshot a few seconds
after each run ends, and syncs finished runs to Supabase in the background
(every `sync_interval_seconds`, default 30s). Needs the game actually
running to see anything happen.

It also opens a local dashboard at `http://127.0.0.1:8765` (starts
automatically, no separate command):

- **Local** -- this machine's own SQLite data, always available even offline.
- **Global** -- everyone's synced runs read straight from Supabase, with a
  quick win-rate leaderboard by player. Needs `SUPABASE_URL`/key in `.env`.

## Sharing with friends

Each friend runs their own copy of this tracker on their own machine,
pointed at *your* Supabase project, so everyone's runs land in the same
place and the Global tab shows the whole group.

1. In your Supabase project, go to Settings -> API and copy the **anon**
   key (not `service_role` -- that one stays yours only).
2. Run `supabase/migration_0002_player_identity_and_rls.sql` once in your
   SQL editor if you already ran the original `schema.sql` before this was
   added -- it adds player identity and locks the anon key down to
   read + insert only (RLS), so nobody can edit or delete anyone else's runs
   with it, only add their own and see everyone's.
3. Give each friend: your `SUPABASE_URL` and that anon key. They put both
   in their own `.env`, using `SUPABASE_KEY=` (not `SUPABASE_SERVICE_KEY=`,
   that variable name is reserved for the project owner) for the key.
4. Who's who is read straight from the game log (`[ProfileCache] Username: ...`),
   no login step needed on their end.

## Building the .exe

```bash
pip install pyinstaller
```

To bundle OCR so the .exe works with zero setup on another machine, install
Tesseract (the official Windows build:
https://github.com/UB-Mannheim/tesseract/wiki), then copy from its install
folder into this project:

```
third_party/tesseract/tesseract.exe
third_party/tesseract/*.dll            (all of them)
third_party/tesseract/tessdata/eng.traineddata
```

This adds ~90MB to the build -- Tesseract's Windows distribution ships a lot
of DLLs for features (PDF export, the training tools, a Java-based viewer)
that this project never uses, but trimming that list requires knowing
exactly which ones `tesseract.exe`'s core OCR path actually loads, so the
safe default here is "bundle all of them" rather than risk a silent OCR
failure from missing one. `third_party/` is gitignored -- each machine
building the exe needs its own copy of these files, they aren't versioned.

If `third_party/tesseract/tesseract.exe` isn't present at build time, the
build still works, it just falls back to whatever Tesseract is on the
target machine's PATH at runtime (or fails OCR silently if there isn't one).

```bash
pyinstaller BazaarTracker.spec
```

Output: `dist/BazaarTracker/BazaarTracker.exe`. Copy `.env` into that same
folder before running it -- secrets are never bundled into the exe on
purpose, each machine keeps its own `.env` next to it.

## Known limitations

- Shop contents (items offered but not bought) aren't in the log text --
  item "frequency" stats are a biased purchase-only proxy, not a true drop rate.
- Per-fight win/loss isn't observable, only the run's final result.
- `MoveItemCommand` never logs the destination, so item repositioning within
  a run isn't tracked, only purchases and sales.
- Final numeric stats (wins, gold, prestige, level, income, max_health) are
  never in the log text -- OCR on the end-of-run screenshot is still required.
- A hero's starting board items are never logged as `Card Purchased` (only
  bought items are), so if one gets sold early it shows up as a sale with no
  matching purchase row. Confirmed on the sample run: 10 of 36 sales are
  unmatched starting items, all sold for 0-1 gold. Not a bug -- `sold_at`
  just stays attached to nothing for those, `add_item_sale` silently no-ops.
- The log format has already changed once with a client update. If a future
  update breaks a marker again, `--replay` against a fresh log is the fastest
  way to find out.
