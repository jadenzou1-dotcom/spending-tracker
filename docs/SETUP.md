# Setup

[Overview](../README.md) · **Setup** · [Features & commands](FEATURES.md) · [Phone dashboard](PHONE-DASHBOARD.md) · [History](HISTORY.md)

Everything here runs on free tiers: Google Cloud (no billing), Plaid's Trial plan, GitHub Actions and Apps Script. Each part is optional after step 1. Stop wherever you like.

1. [Install and try the demo](#1-install-and-try-the-demo)
2. [Connect a Google Sheet](#2-connect-a-google-sheet)
3. [Import Chase CSVs](#3-import-chase-csvs-monthly)
4. [Sort your categories](#4-sort-your-categories)
5. [Automatic daily sync with Plaid](#5-automatic-sync-with-plaid-optional)
6. [Dashboard on your computer](#6-dashboard-on-your-computer)
7. [Dashboard on your phone](#7-dashboard-on-your-phone-optional)

## 1. Install and try the demo

Needs Python 3.10+.

```bash
git clone https://github.com/jadenzou1-dotcom/spending-tracker.git
cd spending-tracker
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tracker.py --local import examples/demo/Chase*.csv
.venv/bin/python tracker.py --local dashboard
```

`--local` uses `data/transactions.csv` (and `data/goals.csv`) instead of a Google Sheet. The files in [`examples/demo/`](../examples/demo/) are fake exports in Chase's exact CSV formats. A plain import leaves the landlord's and roommate's Zelle payments in generic categories. That's the sorting step 4 is for. To start from the demo person's own rules, run `cp examples/demo/rules.csv rules.local.csv` before importing. [`docs/demo/dashboard.html`](demo/dashboard.html) is the fully sorted result (open it in a browser after cloning). Delete `data/` and `rules.local.csv` when you're done trying it.

## 2. Connect a Google Sheet

1. **Create a blank Google Sheet** and copy its ID from the URL: `docs.google.com/spreadsheets/d/<THIS PART>/edit`.
2. **Create a Google Cloud project** at [console.cloud.google.com](https://console.cloud.google.com). It's free and needs no billing.
3. **Enable the Google Sheets API**: APIs & Services → Library → Google Sheets API → Enable.
4. **Create a service account**: IAM & Admin → Service Accounts → Create service account (no roles needed).
5. **Download a key**: open the service account → Keys → Add key → Create new key → JSON. Save it as `service_account.json` in this folder (gitignored).
6. **Share your Sheet** with the service account's email (`client_email` in the JSON, ending in `iam.gserviceaccount.com`) as an **Editor**.
7. **Configure**: `cp config.example.json config.json`, fill in `sheet_id`, and name your accounts by their last 4 digits:
   ```json
   {
     "sheet_id": "1AbC...",
     "credentials": "service_account.json",
     "accounts": { "1234": "Checking", "5678": "Credit Card" }
   }
   ```

The first import creates the Transactions, Summary, Charts and Rules tabs. The Goals tab appears the first time you save a budget.

## 3. Import Chase CSVs (monthly)

1. On chase.com, open **each account** (checking *and* credit card), click the **download icon** above the transaction list, and choose **Spreadsheet (CSV)**. Statements & Documents only has PDFs, so use the account's activity page. "All transactions" is fine, since duplicates are skipped.
2. Import both files:
   ```bash
   .venv/bin/python tracker.py import ~/Downloads/Chase*_Activity_*.csv
   ```

It prints how many rows were added, skipped as already present, paired as cancelled, and left Uncategorized, followed by a short monthly summary. You can import overlapping ranges any time.

## 4. Sort your categories

The Summary and dashboard are built from **whatever categories you use**. There's no fixed list of columns: each category you use gets one, biggest spending first.

1. [`rules.default.csv`](../rules.default.csv) already sorts common merchants (DoorDash, Uber, Netflix, Trader Joe's, utilities, ...). Card rows fall back to Chase's category, synced rows to Plaid's.
2. List what's left and write a rule for each merchant you'll see again:
   ```bash
   .venv/bin/python tracker.py uncategorized
   .venv/bin/python tracker.py add-rule "TRADER JOE" Groceries
   .venv/bin/python tracker.py recategorize
   ```
3. For one-offs, `set ID "Category"` or pick from the dropdown in the Sheet. `note ID "what it was"` records what an obscure charge turned out to be.

Rules are case-insensitive substrings of the description. Your rules (the Sheet's Rules tab, newest on top) are checked before the defaults. See [Features & commands](FEATURES.md#categories) for the category conventions, or let [Claude Code](../README.md#using-it-with-claude-code) do this pass for you.

## 5. Automatic sync with Plaid (optional)

Instead of downloading CSVs, connect Chase to [Plaid](https://plaid.com) once and have GitHub Actions run `tracker.py sync` twice a day. It adds new **posted** transactions (pending ones wait until they post) and categorizes them like an import. Synced rows get the same IDs a CSV import would, so you can mix the two freely.

1. **Plaid account.** Sign up at [dashboard.plaid.com](https://dashboard.plaid.com). New US/Canada teams can take the free **Trial plan**: real bank data, up to 10 connected logins, Chase included, no compliance forms. Your client_id and secret are under **Build → Keys** (use the Production secret).
2. **Connect Chase once:**
   ```bash
   .venv/bin/python tools/plaid_link.py
   ```
   It opens Plaid Link in your browser. Log in to Chase and **share every account** you want tracked (checking and card). On a Mac the keys and the resulting access token go into the Keychain (service `spending-tracker-plaid`) and are never printed. It lists each account's last 4 digits; name them in `config.json` as in step 2. Each run uses up one of the Trial plan's 10 logins, so run it once.
3. **Try it locally:** `tracker.py sync --dry-run` shows what would be added without changing anything. Then run `tracker.py sync`.
4. **Schedule it in a private repo.** Actions logs on a public repo are public, so create a separate **private** repo (e.g. `spending-tracker-runner`), copy [`examples/sync-workflow.yml`](../examples/sync-workflow.yml) to `.github/workflows/sync.yml` in it, and add these secrets under Settings → Secrets and variables → Actions:

   | Secret | Value |
   |---|---|
   | `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ACCESS_TOKEN` | from steps 1–2 |
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | the contents of `service_account.json` |
   | `TRACKER_CONFIG` | the contents of `config.json` |

   With the [GitHub CLI](https://cli.github.com) you can set them without the values ever appearing on screen:
   ```bash
   security find-generic-password -s spending-tracker-plaid -a access_token -w | gh secret set PLAID_ACCESS_TOKEN -R you/spending-tracker-runner
   ```
   ```bash
   gh secret set TRACKER_CONFIG -R you/spending-tracker-runner < config.json
   ```

   The workflow checks out this public repo's code and runs `tracker.py sync` twice a day (GitHub may start scheduled runs a little late). **Actions → Sync transactions → Run workflow** runs it right away.

`sync` reads credentials from `PLAID_CLIENT_ID`, `PLAID_SECRET`, `PLAID_ACCESS_TOKEN` (falling back to the Mac Keychain), `GOOGLE_SERVICE_ACCOUNT_JSON` (instead of the `credentials` file) and `TRACKER_CONFIG` (instead of `config.json`).

**Known limitation:** Chase consent eventually expires (Plaid error `ITEM_LOGIN_REQUIRED`). Reconnecting with Plaid Link's update mode isn't built into `plaid_link.py` yet; until it is, CSV imports still work.

## 6. Dashboard on your computer

```bash
.venv/bin/python tracker.py dashboard
```

It serves the page at http://127.0.0.1:8765 and opens it (Ctrl-C to stop). Reload for fresh data from the Sheet. Budget edits save to the Sheet's Goals tab. `--static` writes a single file to `data/dashboard.html` instead (goals not editable). See [Features & commands](FEATURES.md#dashboard) for what's on it.

## 7. Dashboard on your phone (optional)

The same page runs as a web app inside your Google account, attached to your Sheet. It's free and needs no hosting or domain. [Phone dashboard](PHONE-DASHBOARD.md) explains how access is locked down. The setup takes about 5 minutes on your computer:

1. Open your Sheet, then **Extensions → Apps Script**. Name the project (e.g. "Spending dashboard").
2. Click **Project Settings** (gear icon) and tick **Show "appsscript.json" manifest file in editor**. Back in the **Editor**:
   - Run `python tools/apps_script.py manifest`, open `appsscript.json`, select all and paste.
   - Run `python tools/apps_script.py code`, open `Code.gs`, select all and paste.
   - Click **+ → HTML**, name it `Index` (it becomes `Index.html`), run `python tools/apps_script.py index`, select all and paste.
   - Save (⌘S).
3. **Deploy → New deployment**, gear → **Web app**. Execute as: **User accessing the web app**. Who has access: **Anyone with Google account** (the Sheet's sharing is what actually limits it). Click **Deploy**.
4. Click **Authorize access** and pick your account. Google warns that it "hasn't verified this app" because it's your own unpublished script: click **Advanced → Go to ... (unsafe)**, then **Allow**. It only asks for access to this one spreadsheet.
5. Copy the **Web app URL**. Optionally put it in the Goals tab's E1 as `=HYPERLINK("<url>", "Open spending dashboard")`; budget saves never touch columns past C.
6. To use it from another Google account of yours (e.g. the one on your phone), share the Sheet with that account as an **Editor**. Open the URL signed in as that account and add it to your home screen. Each account approves access once.

Each `tools/apps_script.py` command copies one file to the clipboard. None of them contain your data. When the dashboard changes later, paste the new `Index` (and `Code.gs` if it changed), then **Deploy → Manage deployments → ✏️ → Version: New version → Deploy**. The URL stays the same.
