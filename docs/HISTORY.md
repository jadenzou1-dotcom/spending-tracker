# History: how it got here, including what didn't work

[Overview](../README.md) · [Setup](SETUP.md) · [Features & commands](FEATURES.md) · [Phone dashboard](PHONE-DASHBOARD.md) · **History** · [Live demo](DEMO.md)

The project went from a CSV importer to an automated tracker with a phone dashboard over a few days (September 26–28, 2026), built with [Claude Code](https://claude.com/claude-code). Several ideas were tried and dropped along the way. They're written up here because the reasons behind the current design are mostly in the dead ends.

## Timeline

| Date | Change | Commit |
|---|---|---|
| Sep 26 | **v1**: parse Chase checking + card CSVs, dedupe by stable ID, mark transfers and cancelled orders, categorize by rules, write Transactions / Summary / Charts / Rules to a Sheet | `d9160ca` |
| Sep 26 | Charts tab becomes interactive: month pickers, stacked monthly spending, income vs spending | `2274747` |
| Sep 26 | Any month range; Summary and charts ordered by *your* spending, not a hard-coded list | `36a41d6` |
| Sep 26 | Two side-by-side month pies, a Net bar, then Saved / Overspent bars (Spent recolored violet so it couldn't be mistaken for red) | `10e892e` `ef1b027` `863829c` |
| Sep 26 | **Plaid sync** with a scheduled run from a private repo; synced rows get the same IDs as CSV rows | `864586a` |
| Sep 26 | Clear error for a non-numeric Amount or bad Date instead of a crash | `ce61fc2` |
| Sep 28 | Warning protection on bank-sourced columns (after a real accident, below) | `b39d068` |
| Sep 28 | Never clear Transactions before writing; retry quota errors (after a real accident, below) | `6e76b14` |
| Sep 28 | Summary column groups shaded; a **Breakdown** tab with a transaction list and heat map | `91027a7` `9204214` |
| Sep 28 | **Breakdown removed**: analysis moves out of the Sheet | `0af4909` |
| Sep 28 | `tracker.py dashboard`: a local interactive page | `61e114e` |
| Sep 28 | Dashboard compares any number of months; **Budget** goals saved to a Goals tab | `6364c26` `4256056` |
| Sep 28 | Dashboard as an **Apps Script web app** for phones (owner-only at first) | `c3cbebb` `4461d2c` |
| Sep 28 | Web app **runs as the visitor**, so any account the Sheet is shared with can open it | `6413120` |
| Sep 28 | Docs split into these pages; fake demo data and screenshots | this change |

## What didn't work

### 1. Charts inside Google Sheets weren't good enough

The first plan was to keep everything in the Sheet: a **Charts** tab with dropdowns to pick months, and charts driven by formulas over the Summary. It took seven commits of iteration, and each one ran into a Sheets limitation:

- **Nothing is clickable.** A chart can't be clicked to see the transactions behind a bar. The workaround was a separate **Breakdown** tab: pick a month and category from dropdowns and a `FILTER` formula lists the matching rows, plus a month × category heat map. That's three dropdowns and a formula for what should be one click.
- **Re-ranking takes helper tables.** Showing "your top 7 categories in the chosen range" meant hidden helper rows below the charts computing ranks with formulas, which the charts then read. Every new idea meant another helper block.
- **Dropdowns fight you.** Sheets kept turning `2026-06` month values into dates, so every formula needed a `TEXT(...)` normalization step.
- **Limited chart styling.** Pie slices only show their name and % on hover. Getting labels meant switching to a labeled legend. A negative "Net" bar in red next to "Spent" was confusing, and fixing it meant splitting Net into separate Saved and Overspent series and recoloring Spent violet.
- **It's slow and fragile.** Every import rebuilt all the formulas and charts through the Sheets API, and a layout change could leave stale colors or dropdowns behind (one commit had to clear stale dropdowns left by an older layout).

After the Breakdown tab, the conclusion was that **the Sheet should be the ledger, not the analysis tool**. Breakdown was deleted (`0af4909`), and analysis moved to a plain HTML page with no framework, where a click can do anything. The Charts tab is still generated for anyone who wants a quick look inside the Sheet, but the dashboard replaced it. The project rule since then: *interactive analysis goes in the dashboard, not into new Sheet tabs.*

### 2. Cloudflare Workers for the scheduled sync

Running `sync` twice a day needed somewhere to run. Cloudflare Workers' free tier was the first idea, but its 10 ms CPU limit per request would have meant rewriting the Python in TypeScript, and the paid tier wasn't worth it for a personal tool. **GitHub Actions** runs the existing Python for free.

### 3. A workflow in the public repo

The obvious place for that workflow was this repo, but **Actions logs on a public repo are public**, and a sync's output includes spending totals (a dry run lists every transaction). The workflow lives in a separate **private** runner repo that checks out this public code and holds the secrets. [`examples/sync-workflow.yml`](../examples/sync-workflow.yml) is the template. Secrets are piped from the Mac Keychain straight into `gh secret set`, so they never appear on screen or in a file.

### 4. A stray fill-right corrupted the ledger

While editing categories in the Sheet, a fill-right overwrote a Description with a date and a Month with a Chase Type. Nothing stopped it, because every column was editable. Now every write re-applies **warning-only protection** to the bank-sourced columns (everything except Category, Exclude and Notes), so an edit there asks first but is still possible.

### 5. A quota error emptied the ledger

Writes used to `clear()` the Transactions tab and then `update()` it. A Sheets **429 quota error** landed between the two calls and left the ledger empty. Writes now overwrite in place and trim leftover rows afterwards, and the client retries 429s with backoff. A failed run can no longer leave an empty Sheet, and if the header looks wrong the tool stops instead of treating the Sheet as empty.

### 6. The phone link only worked for one account

The first web app ran as the owner with access "Only myself". It worked on the laptop, but the phone is signed in to a different personal Google account, which got "You need access". The fix wasn't to make the link public: the app now **runs as the visitor**, and the Sheet's own sharing list decides who sees data. The full reasoning, including the options that were rejected, is in [Phone dashboard](PHONE-DASHBOARD.md). A related snag: with two Google accounts signed in to one browser, Apps Script kept acting as the wrong (default) account, so deployments are done from a browser profile where the owner is the default.

### 7. Smaller lessons

- **Chase lists temporary future-dated rows** that later disappear and re-post under a different description. They're skipped until they settle, or they'd become duplicates.
- **Plaid and CSV dates differ.** Card CSVs show the transaction date and Plaid shows the posted date. Synced card rows display Plaid's `authorized_date` (closest to what the CSV shows) but take their ID from the posted date, exactly like the CSV parser, so a CSV import and a sync never duplicate each other.
- **Identical rows on the same day** (three $0.35 vending charges) get a counter in their ID, so re-importing the same file reproduces the same IDs.
- **Plaid's Trial plan** allows 10 connected logins in total, and each `plaid_link.py` run uses one up, so it's meant to be run once.

## Still open

- Reconnecting Plaid when Chase consent expires (`ITEM_LOGIN_REQUIRED`) through Link update mode.
- Banks other than Chase: each needs a parser that returns the same `Txn` objects.
