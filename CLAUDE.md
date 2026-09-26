# spending-tracker

Chase CSV exports → Google Sheet (Transactions / Summary / Charts / Rules tabs). Run with `.venv/bin/python tracker.py ...`. User-facing docs are in README.md.

## Keeping things in sync (always)
- Every change to code, rules.default.csv or docs gets committed **and pushed** to GitHub (`origin main`) in the same turn, so the local folder and the GitHub repo never drift. "Commit" means commit and push.
- Commits are authored by the user's own git identity (Jaden Zou); end each message with the `Co-Authored-By: Claude ...` trailer.
- When behavior, commands or layout change, update README.md and this file before committing. Don't leave old wording behind.
- Before committing, run `git status` and make sure nothing personal is staged (see Privacy).

## Monthly workflow
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
- Generic merchant rules belong in rules.default.csv (committed). Anything personal (landlord, workplace, friends' names, account numbers) goes in the Rules tab via `add-rule`, never in committed files.

## Splitting a row (e.g. roommate Zelle covering rent + utilities)
`tracker.py search "zelle"` to get the ID, then `tracker.py split <ID> "Utilities & Phone=40" Rent`. One part may omit its amount and takes the remainder. The original gets Exclude = "split", and the pieces keep the original's sign, so money received in "Rent" reduces rent spending. To ignore part of a payment, give that part the category Transfer.

## Conventions
- Amounts: negative = money out. Summary shows spending as positive dollars.
- Income: any category ending in " Income" (Work / Other built in; personal income sources come from Rules-tab rules and stay out of committed files). Money received for a shared expense goes in that expense's category, not income.
- Exclude column: blank = counts; anything else = ignored by Summary. Auto-filled with "cancelled" for charge + refund pairs.
- Transfer (card payments, moves between the user's own accounts) never counts as income or spending. This is what prevents double counting card purchases.
- Before risky sheet changes, back up Transactions to `data/backup-*.csv`.

## Privacy
Gitignored and must stay that way: `config.json`, `service_account.json`, `rules.local.csv`, `data/`, all CSVs except `rules.default.csv` and `examples/*.csv`. The examples are fake data; never put real transactions there.
