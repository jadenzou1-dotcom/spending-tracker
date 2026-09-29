# Features & commands

[Overview](../README.md) · [Setup](SETUP.md) · **Features & commands** · [Phone dashboard](PHONE-DASHBOARD.md) · [History](HISTORY.md)

- [Commands](#commands)
- [The Sheet's tabs](#the-sheets-tabs)
- [Dashboard](#dashboard)
- [How a transaction gets its category](#how-a-transaction-gets-its-category)
- [Categories](#categories)
- [Splitting a payment](#splitting-a-payment)
- [Safety nets](#safety-nets)
- [Project layout](#project-layout)

## Commands

Run as `.venv/bin/python tracker.py COMMAND`. Add `--local` before the command to use `data/transactions.csv` instead of the Sheet. IDs can be shortened to their first 8 characters.

| Command | What it does |
|---|---|
| `import FILE...` | Add new transactions from Chase CSVs (checking and card formats are detected automatically) |
| `sync [--dry-run]` | Add new posted transactions from Plaid |
| `uncategorized` | List rows that still need a category |
| `add-rule "PATTERN" "Category"` | Save a rule (case-insensitive substring of the description). Newest rules win. |
| `recategorize [--match TEXT]` | Re-apply rules to Uncategorized rows, or with `--match` (repeatable) to every row containing TEXT |
| `set ID "Category"` | Set one row's category (for one-offs) |
| `note ID "text"` | Add a note to a row, e.g. what an obscure merchant turned out to be |
| `search TEXT` | Find rows by description or note (shows IDs) |
| `split ID "Utilities & Phone=40" Rent` | Split one row across categories. One part may omit its amount and gets the remainder. |
| `dashboard [--no-open] [--static] [--port N]` | Serve the dashboard at http://127.0.0.1:8765 and open it. `--static` writes `data/dashboard.html` instead. |

Helper scripts in `tools/`:

| Script | What it does |
|---|---|
| `tools/plaid_link.py` | Connect a bank to Plaid once and store the access token in the Keychain |
| `tools/apps_script.py code\|index\|manifest [--print]` | Copy one Apps Script file to the clipboard for pasting (see [Setup §7](SETUP.md#7-dashboard-on-your-phone-optional)) |
| `tools/make_demo.py [--shots]` | Rebuild the fake demo data in `examples/demo/` and `docs/demo/`, and with `--shots` the screenshots in `docs/images/` (needs Google Chrome) |

## The Sheet's tabs

| Tab | Contents | Who edits it |
|---|---|---|
| **Transactions** | Date, Description, Amount, Category, Exclude, Account, Chase Category, Chase Type, Month, ID, Notes. Newest first, header frozen, Category as a dropdown | You edit Category / Exclude / Notes. The other columns come from the bank and warn before an edit |
| **Summary** | Row 2 all-time totals, then one row per month: Income, Spent, Net, % of income spent, one column per income source, one per spending category (biggest first, Uncategorized last). Live `SUM(FILTER(...))` formulas, shaded gray / green / orange by group | Rebuilt on every write |
| **Goals** | B1 estimated monthly take-home income. From row 4: Group, Goal % of income, comma-separated categories (`*` = everything not listed elsewhere) | You, in the Sheet or from the dashboard's Budget view. Saves only rewrite columns A–C |
| **Rules** | `pattern, category`, newest on top | `add-rule`, or by hand |
| **Charts** | Month-range pickers driving stacked monthly spending, income vs spending with Saved / Overspent bars, and two month pies. Superseded by the dashboard (see [History](HISTORY.md)), but still built | Rebuilt on every write; keeps your picker choices |
| **Sync** (hidden) | Plaid's `/transactions/sync` cursor | `sync` |

Money out is negative (as at Chase). The Summary shows spending as positive dollars.

## Dashboard

One self-contained HTML page (`spending_tracker/dashboard.html`) with no libraries or build step, and light and dark themes. It counts exactly the rows the Summary counts: Exclude blank, Transfers left out.

**Compare**
- Monthly stacked bars (last 24 months; 12 on a phone) for the top 8 categories plus "Everything else", with an income line. Click a month to add it to the comparison or take it out, or click a segment to pick that category.
- A table with one column per chosen month (add as many as you like) and one row per category: dollars, % of that month's spending and a bar, plus a donut per month and Income / Spent / Saved rows.
- Click a category to list its transactions for every chosen month side by side, biggest first, with notes. A filter box searches descriptions, notes and categories.

**Budget**
- Pick a month and set your estimated take-home income, or copy that month's actual income with "Use as estimate".
- Plan vs actual bars: each group's share of income, with cash savings hatched.
- Each group shows its goal in % and $, what it spent, actual %, a progress bar, and how much is left or over. Open a group (▸) to see its categories and move one to another group. Add or delete groups.
- **Cash savings** is 100% minus the groups, compared with what you actually kept.

Where it runs:

| | `tracker.py dashboard` | `--static` | Apps Script web app |
|---|---|---|---|
| Where | your computer, 127.0.0.1 only | a file in `data/` | your Google account, any device |
| Data | read from the Sheet on every reload | frozen at build time | read from the Sheet on every load |
| Budget saves | POST /api/goals (per-run token + Host check) | not saved | `google.script.run` → `saveGoals` |

## How a transaction gets its category

First match wins:

1. **Your rules**: the Sheet's Rules tab (or `rules.local.csv` with `--local`), newest first.
2. **Built-in rules**: [`rules.default.csv`](../rules.default.csv), for common merchants.
3. **Chase's transaction type**: card payments, `LOAN_PMT` and `ACCT_XFER` → Transfer; ATM → Cash; Zelle received → Other Income; Zelle sent → Payments to People; fees → Fees.
4. **Chase's category** (card CSVs), e.g. Food & Drink → Dining, Gas → Transport.
5. **Plaid's category** (synced rows, both accounts), e.g. `FOOD_AND_DRINK_GROCERIES` → Groceries, `INCOME_SALARY` → Work Income. The detailed value is looked up first, then its prefix.
6. Otherwise **Uncategorized**.

`recategorize` only touches Uncategorized rows, so categories you set by hand are never overwritten. To change settled rows on purpose, use `recategorize --match TEXT`.

## Categories

**Income**: Work Income and Other Income are built in. Any category ending in ` Income` (e.g. `Family Income`, `Scholarship Income`) counts as income and gets its own Summary column. For example, `add-rule "Online Transfer from CHK ...1111" "Allowance Income"` turns regular transfers from someone else's account into their own income line.

**Spending (starter set)**: Rent, Utilities & Phone, Groceries, Food Delivery, Dining, Snacks, Transport, Travel, Subscriptions, Shopping, Entertainment, Gaming, Health & Fitness, Personal Care, Payments to People, Cash, Fees, Other. These are only suggestions in the dropdown. Any name you type becomes a category, and only categories you actually use appear on the Summary and dashboard.

**Transfer** never counts as income or spending. That's what stops card purchases being counted twice, once on the card and again when checking pays the card.

Conventions:
- **Money received into a spending category reduces it.** Put a roommate's rent Zelle in **Rent** and your rent spending drops by that amount. The same goes for a friend paying you back for dinner (**Dining**).
- **Exclude**: blank means the row counts. Anything typed there makes the Summary and dashboard ignore the row. The tool fills in `cancelled` (charge + refund pairs) and `split`.
- Personal rules (your landlord, employer, friends' names) belong in the Rules tab, never in `rules.default.csv`.

## Splitting a payment

```bash
.venv/bin/python tracker.py search "zelle from"
.venv/bin/python tracker.py split 1a2b3c4d "Utilities & Phone=60" Rent
```

The original row gets Exclude = `split` and the pieces are inserted under it as `[split] ...` rows with the original's sign, so money received in Rent reduces rent. One part may omit its amount and takes the remainder. To ignore part of a payment, give that part the category Transfer. The demo data splits the roommate's monthly $1,135 this way.

## Safety nets

Each of these came from something that actually went wrong (see [History](HISTORY.md)):

- **No empty ledger.** Writes overwrite Transactions in place and trim leftover rows afterwards, never clearing first. Sheets 429 quota errors are retried with backoff.
- **Warning protection** on the bank-sourced columns (everything but Category / Exclude / Notes), re-applied on every write, so a stray paste or fill-right asks before overwriting.
- **Refuses to guess.** If the Transactions header is missing columns, or a row has a non-numeric Amount or a bad Date, the run stops with the row number instead of treating the Sheet as empty.
- **Future-dated rows are skipped.** Chase sometimes lists temporary rows that later re-post under a different description.
- **Formula injection.** Text written to the Sheet (descriptions, notes, goal names) is stored as plain text, never as a formula.

## Project layout

```
tracker.py                  command-line entry point
spending_tracker/
  parsers.py                Chase CSV → Txn (checking + credit card formats), stable IDs
  categorize.py             categories and the rules → type → Chase/Plaid-category cascade
  plaid.py                  Plaid /transactions/sync → Txn (same IDs as CSV rows)
  pairing.py                cancelled-order detection
  core.py                   merge/dedupe, recategorize, split, monthly totals
  sheets.py                 Google Sheets tabs, Summary formulas, Charts tab, Goals
  local_store.py            CSV storage for --local mode
  dashboard.py, .html       the dashboard page and its 127.0.0.1 server
apps_script/                Code.gs + manifest: the dashboard as a private web app
tools/
  plaid_link.py             one-time Plaid Link to connect your bank
  apps_script.py            copies the Apps Script files to the clipboard
  make_demo.py              fake demo data and screenshots
rules.default.csv           built-in merchant rules
examples/                   fake Chase CSVs, the demo ledger, and the scheduled-sync workflow
docs/                       these pages, the demo pages and screenshots
```

Only Chase is supported so far. Adding a bank means adding a parser that returns the same `Txn` objects.
