# Live demo

[Overview](../README.md) · [Setup](SETUP.md) · [Features & commands](FEATURES.md) · [Phone dashboard](PHONE-DASHBOARD.md) · [History](HISTORY.md) · **Live demo**

Two links, both filled with **fake data** for a made-up person and open to anyone (no sign-in needed):

- **[Demo spreadsheet](https://docs.google.com/spreadsheets/d/1ewAz3ph69PqMhJkR85uOpalluf4-KS3Aw70xpjA5lgA/edit)**: the real Transactions, Summary, Charts, Rules and Goals tabs, written by the same code a real import uses. View only.
- **Demo dashboard**: the Apps Script web app attached to that spreadsheet, the same one used on the phone. Budget edits work on the page but are never saved. *(Link coming once it's deployed.)*

## How the demo is built

1. `tools/make_demo.py` generates seven months of fake Chase exports (paychecks, rent by Zelle, a roommate's share, groceries, a trip, a cancelled Amazon order, ...) and runs them through the real parser, rules, refund pairing and split.
2. `tools/make_demo.py --sheet <ID>` writes the result into the demo spreadsheet through `SheetStore`, the same class that writes a real Sheet. It refuses to run against the Sheet in your `config.json`.
3. The spreadsheet is shared as "Anyone with the link: Viewer". Only its owner and the service account can edit it.
4. Its Apps Script project uses the demo versions of the files:
   ```bash
   python tools/apps_script.py manifest --demo
   ```
   ```bash
   python tools/apps_script.py code --demo
   ```
   plus the usual `index`.

## How it differs from your own phone dashboard

| | Your dashboard | The demo |
|---|---|---|
| Runs as | whoever opens it | the owner |
| Who can open it | anyone signed in, but data only loads for accounts the Sheet is shared with | anyone, signed in or not |
| Budget edits | saved to the Goals tab | never saved (`saveGoals` refuses when `DEMO` is true) |
| Scope | `spreadsheets.currentonly` | the same: only the demo spreadsheet |

Running as the owner for anyone is exactly the setup [Phone dashboard](PHONE-DASHBOARD.md) warns against for real data. It's fine here because the spreadsheet holds nothing but fake data, the script can't reach any other file, and it never writes.
