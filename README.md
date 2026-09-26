# spending-tracker

Turn Chase bank and credit card exports into a categorized, month-by-month spending tracker in Google Sheets.

Download your transaction CSVs from Chase, run one command, and your Google Sheet gets:

- **Transactions**: every transaction from every account, newest first, with a category dropdown, an Exclude column and a Notes column
- **Summary**: income, spending, net and % of income spent per month, plus a column per income source and spending category, **ordered by your own totals** (biggest first), all as live formulas
- **Charts**: pick any month range (e.g. the last 3 months, or March to June) to see stacked monthly spending for your top 7 categories in that range, income vs spending, and a pie for any single month, with hover for exact amounts
- **Rules**: your own "merchant → category" rules, editable from any computer

It handles the parts that make bank data annoying:

| Problem | What the tool does |
|---|---|
| Credit card payments show up in checking *and* on the card, which counts spending twice | Card payments and moves between your own accounts are categorized **Transfer** and never count as spending or income |
| Re-downloading overlapping date ranges | Every transaction gets a stable ID, so re-importing the same file adds nothing |
| Cancelled orders (charge, then refund) | A charge followed within 10 days by an equal refund from the same merchant gets `cancelled` in Exclude on both rows. A charge → refund → charge leaves the second charge counted. |
| Chase's PDFs have no categories, and its CSV categories are coarse | Your rules run first, then Chase's transaction type, then Chase's category (card CSVs only). Anything left is `Uncategorized` for you (or Claude) to sort. |
| One payment covering several things (e.g. a roommate's Zelle for rent + utilities) | `split` divides one row across categories |

## Quick start (no Google account needed)

```bash
git clone https://github.com/jadenzou1-dotcom/spending-tracker.git
cd spending-tracker
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tracker.py --local import examples/*.csv
```

`--local` writes to `data/transactions.csv` instead of a Google Sheet and prints a monthly summary. The example files are fake data in Chase's exact CSV format.

## Setup with Google Sheets

1. **Create a Google Sheet** (blank) and copy its ID from the URL: `docs.google.com/spreadsheets/d/<THIS PART>/edit`.
2. **Create a Google Cloud project** at [console.cloud.google.com](https://console.cloud.google.com) (free, no billing needed).
3. **Enable the Google Sheets API**: APIs & Services → Library → Google Sheets API → Enable.
4. **Create a service account**: IAM & Admin → Service Accounts → Create service account (no roles needed).
5. **Download a key**: open the service account → Keys → Add key → Create new key → JSON. Save it as `service_account.json` in this folder (it's gitignored).
6. **Share your Sheet** with the service account's email (`client_email` in the JSON, ending in `iam.gserviceaccount.com`) as an **Editor**.
7. **Configure**: `cp config.example.json config.json`, then fill in `sheet_id` and name your accounts by their last 4 digits:
   ```json
   {
     "sheet_id": "1AbC...",
     "credentials": "service_account.json",
     "accounts": { "1234": "Checking", "5678": "Credit Card" }
   }
   ```

## Monthly workflow

1. On chase.com, open **each account** (checking *and* credit card), click the **download icon** above the transaction list, and choose **Spreadsheet (CSV)**. The Statements & Documents page only has PDFs, so use the account's activity page. "All transactions" is fine, since duplicates are skipped.
2. Import both files:
   ```bash
   .venv/bin/python tracker.py import ~/Downloads/Chase*_Activity_*.csv
   ```
3. Sort whatever is left:
   ```bash
   .venv/bin/python tracker.py uncategorized
   .venv/bin/python tracker.py add-rule "TRADER JOE" Groceries
   .venv/bin/python tracker.py recategorize
   ```

You can also edit Category, Exclude and Notes directly in the Sheet. Your edits are kept on every re-import.

## Commands

| Command | What it does |
|---|---|
| `import FILE...` | Add new transactions from Chase CSVs |
| `uncategorized` | List rows that still need a category |
| `add-rule "PATTERN" "Category"` | Save a rule (case-insensitive substring of the description). Newest rules win. |
| `recategorize [--match TEXT]` | Re-apply rules to Uncategorized rows, or with `--match` to every row containing TEXT |
| `set ID "Category"` | Set one row's category (for one-offs) |
| `note ID "text"` | Add a note to a row, e.g. what an obscure merchant name turned out to be |
| `search TEXT` | Find rows by description or note (shows IDs) |
| `split ID "Utilities & Phone=40" Rent` | Split one row across categories. One part may omit its amount and gets the remainder. |

Add `--local` before any command to use `data/transactions.csv` instead of the Sheet. IDs can be shortened to their first 8 characters.

## Setting up your categories

The Summary and Charts are built from **whatever categories you use**. There's no fixed list of columns: each category gets a column, biggest spending first, and the charts pick your top 7 for the months you choose. So the first job after your first import is sorting your transactions:

1. `import` your CSVs. [`rules.default.csv`](rules.default.csv) sorts common merchants (DoorDash, Uber, Netflix, Trader Joe's, …), and card transactions fall back to Chase's own category.
2. Everything else is `Uncategorized`. Go through it with `uncategorized`, and for each merchant you'll see again, `add-rule` it; for one-offs, `set` it or pick from the dropdown in the Sheet. Use the categories below or make up your own.
3. Re-run `recategorize` after adding rules. The Summary and Charts rebuild around your categories.

This is the part [Claude Code](https://claude.com/claude-code) is good at: open it in this folder and say "go through my uncategorized transactions". It proposes rules, asks about merchants it can't identify, and records what you tell it in the Notes column (see [Using it with Claude Code](#using-it-with-claude-code)).

## Categories

**Income:** Work Income, Other Income. Any category ending in `Income` (e.g. `Scholarship Income`) counts as income and gets its own Summary column. For example, a rule like `add-rule "Online Transfer from CHK ...1111" "Allowance Income"` turns regular transfers from someone else's account into their own income line.

**Spending (starter set):** Rent, Utilities & Phone, Groceries, Food Delivery, Dining, Snacks, Transport, Travel, Subscriptions, Shopping, Entertainment, Gaming, Health & Fitness, Personal Care, Payments to People, Cash, Fees, Other. These are only suggestions in the Category dropdown. Any name you type (in the Sheet or in a rule) becomes a category, and only categories you actually use appear on the Summary. `Uncategorized` is always the last column so leftovers are easy to spot.

**Transfer** never counts as income or spending.

A few conventions:

- **Money received into a spending category reduces it.** Put a roommate's rent Zelle in **Rent** and your rent spending drops by that amount. Same for a friend paying you back for dinner (**Dining**).
- **Exclude:** leave it blank and the row counts. Type anything there and the Summary ignores that row.
- **Rules order:** your Rules tab is checked first (top to bottom), then [`rules.default.csv`](rules.default.csv).

## Using it with Claude Code

The repo includes a [`CLAUDE.md`](CLAUDE.md), so [Claude Code](https://claude.com/claude-code) knows the workflow. Drop your CSVs in Downloads and say "import my statements", and it will:

- import the files
- suggest rules for new merchants
- ask about anything ambiguous
- apply splits you describe in plain English ("the Zelle from my roommate was $40 utilities and the rest rent")

## Privacy

Everything personal stays on your machine or in your own Google account. `.gitignore` excludes `config.json`, `service_account.json`, `rules.local.csv`, `data/` and every CSV except the examples and default rules. Nothing is sent anywhere except the Google Sheets API, using your own service account.

## Project layout

```
tracker.py                  command-line entry point
spending_tracker/
  parsers.py                Chase CSV → transactions (checking + credit card formats)
  categorize.py             categories and the rules → type → Chase-category cascade
  pairing.py                cancelled-order detection
  core.py                   merge/dedupe, recategorize, split, monthly totals
  sheets.py                 Google Sheets tabs, Summary formulas, Charts tab
  local_store.py            CSV storage for --local mode
rules.default.csv           built-in merchant rules
examples/                   fake Chase CSVs to try it out
```

Only Chase is supported so far. Adding a bank means adding a parser that returns the same `Txn` objects.

## License

MIT
