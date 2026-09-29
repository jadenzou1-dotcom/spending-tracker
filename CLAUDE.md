# spending-tracker

Chase CSV exports or Plaid sync → Google Sheet (Transactions / Summary / Charts / Rules / Goals tabs, plus a hidden Sync tab holding Plaid's cursor). Run with `.venv/bin/python tracker.py ...`. User-facing docs: README.md (overview + screenshots) and docs/ (SETUP.md, FEATURES.md, PHONE-DASHBOARD.md, HISTORY.md), each page starting with the same link bar.

## Keeping things in sync (always)
- Every change to code, rules.default.csv or docs gets committed **and pushed** to GitHub (`origin main`) in the same turn, so the local folder and the GitHub repo never drift. "Commit" means commit and push.
- Commits are authored by the user's own git identity (Jaden Zou); end each message with the `Co-Authored-By: Claude ...` trailer.
- When behavior, commands or layout change, update the docs (README.md, docs/*.md) and this file before committing. Don't leave old wording behind. Notable decisions and dead ends go in docs/HISTORY.md (timeline + "What didn't work").
- When the dashboard or Sheet layout changes visibly, rerun `.venv/bin/python tools/make_demo.py --shots --sheet 1ewAz3ph69PqMhJkR85uOpalluf4-KS3Aw70xpjA5lgA` so `examples/demo/`, `docs/demo/`, `docs/images/` and the public demo Sheet match (docs/DEMO.md). The demo Sheet's Apps Script uses `tools/apps_script.py ... --demo` (runs as owner for anyone, `DEMO = true` so `saveGoals` never writes); after template changes, re-paste Index there too.
- Before committing, run `git status` and make sure nothing personal is staged (see Privacy).

## Dashboard (where analysis lives)
- The same `dashboard.html` is also the phone version: `apps_script/Code.gs` serves it from the Sheet as a web app (executes as the user accessing it, access "anyone with a Google account": the Sheet's sharing is the real gate, so only accounts it's shared with get data; scope `spreadsheets.currentonly`), filling `/*DATA*/null` via `tools/apps_script.py index` → `<?!= data ?>`. Keep that placeholder, never add other `<?` to the template, and keep `Code.gs`'s data loading and `saveGoals` in step with `dashboard.py` (`page`, `clean_goals`) and `parse_goals`. After changing the template, remind the user to re-paste Index and deploy a new version.
- Refreshing the page picks up template (HTML/JS) changes and new ledger data; Python changes need the server restarted.
- `tracker.py dashboard` serves `spending_tracker/dashboard.html` (no-dependency template, re-read on every request) from 127.0.0.1 with fresh ledger data per reload; `--static` writes `data/dashboard.html` (gitignored: it embeds real transactions). It counts the same rows as the Summary (Exclude blank, no Transfers). Interactive analysis goes here, not into new Sheet tabs; the Sheet keeps Transactions / Summary / Charts.
- Budget goals live in the Sheet's **Goals** tab (B1 estimated monthly take-home income; rows from 4: Group | Goal % of income | comma-separated categories, `*` = everything not listed elsewhere), or `data/goals.csv` with `--local`. Cash savings = 100% minus the groups. Saves only clear columns A–C, so E1's link to the phone dashboard (and anything else past C) survives. Group names and category membership are personal, so they live only there, never in code. The page saves them via POST /api/goals, guarded by a per-run token and a Host check. They're the user's personal numbers: never set them unless asked.

## Plaid sync (the default now)
- `tracker.py sync [--dry-run]` pulls new **posted** transactions from Plaid (`/transactions/sync`, `original_description` so rules match). Rows get the same IDs the CSV parser would give (`_make_id` on posted date), so CSV imports and syncs never duplicate each other. Card rows show Plaid's `authorized_date`, checking rows the posted date. Plaid's detailed category goes in the Chase Category column and is the fallback via `PLAID_CATEGORY_MAP`.
- Credentials: env vars `PLAID_CLIENT_ID` / `PLAID_SECRET` / `PLAID_ACCESS_TOKEN` (locally they fall back to the Mac Keychain, service `spending-tracker-plaid`), `GOOGLE_SERVICE_ACCOUNT_JSON`, `TRACKER_CONFIG`. Never print or commit them.
- Scheduled runs: GitHub Actions in a separate **private** repo using `examples/sync-workflow.yml`, never a workflow in this public repo (its logs are public).
- `tools/plaid_link.py` connects a bank once. Each run uses one of the Trial plan's 10 Items, so don't rerun it casually.

## Monthly workflow (CSV, still supported)
1. User downloads the "all transactions" CSV for **both** accounts (checking and credit card) from each account's activity page on chase.com (download icon → Spreadsheet). Statements & Documents only has PDFs.
2. `tracker.py import ~/Downloads/Chase*_Activity_*.csv`. It removes duplicates by ID, so overlapping ranges are safe.
3. Categorize leftovers (below) and apply any splits or notes the user describes.

## Categorizing "Uncategorized" rows (Claude's job)
- `tracker.py uncategorized` lists them.
- Recurring merchants: `tracker.py add-rule "PATTERN" "Category"` (case-insensitive substring; use a distinctive chunk, not store numbers or dates), then `tracker.py recategorize`. New rules go to the top of the Rules tab and win.
- One-off rows: `tracker.py set <ID> "Category"`.
- Changing a category the user already settled on: only when they ask. Then `tracker.py recategorize --match TEXT` (repeatable). Plain `recategorize` only touches Uncategorized rows, and user edits in the Sheet are otherwise never overwritten.
- When the user explains an obscure charge, record it: `tracker.py note <ID> "what it was"`.
- Ask when a merchant is genuinely ambiguous rather than guessing.
- Summary columns and chart categories are derived from the user's data (ordered by their own totals). Never hard-code a category order or someone's personal categories into the code.
- Generic merchant rules belong in rules.default.csv (committed). Anything personal (landlord, workplace, friends' names, account numbers) goes in the Rules tab via `add-rule`, never in committed files.

## Splitting a row (e.g. roommate Zelle covering rent + utilities)
`tracker.py search "zelle"` to get the ID, then `tracker.py split <ID> "Utilities & Phone=40" Rent`. One part may omit its amount and takes the remainder. The original gets Exclude = "split", and the pieces keep the original's sign, so money received in "Rent" reduces rent spending. To ignore part of a payment, give that part the category Transfer.

## Conventions
- Amounts: negative = money out. Summary shows spending as positive dollars.
- Income: any category ending in " Income" (Work / Other built in; personal income sources come from Rules-tab rules and stay out of committed files). Money received for a shared expense goes in that expense's category, not income.
- Exclude column: blank = counts; anything else = ignored by Summary. Auto-filled with "cancelled" for charge + refund pairs.
- Transfer (card payments, moves between the user's own accounts) never counts as income or spending. This is what prevents double counting card purchases.
- Before risky sheet changes, back up Transactions to `data/backup-*.csv`.
- Every write re-adds warning-only protection on the bank-sourced Transactions columns (all but Category / Exclude / Notes), replacing the previous protection, so stray edits prompt first.
- Writes overwrite Transactions in place and trim leftovers afterwards (never clear first), and the Sheets client retries 429 quota errors. A failed run must never leave the ledger empty.

## Privacy
Gitignored and must stay that way: `config.json`, `service_account.json`, `rules.local.csv`, `data/`, all CSVs except `rules.default.csv`, `examples/*.csv` and `examples/demo/*.csv`. `examples/demo/*.csv` and `docs/demo/` are also committed. All examples and demo files are fake data from `tools/make_demo.py`; never put real transactions, names or accounts there.
