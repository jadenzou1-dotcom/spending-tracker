"""Chase statement -> spending tracker.

  python tracker.py import Chase*_Activity_*.csv     add new transactions
  python tracker.py sync [--dry-run]                  add new transactions from Plaid
  python tracker.py recategorize [--match TEXT]       re-apply rules to Uncategorized rows
                                                      (or to every row containing TEXT)
  python tracker.py uncategorized                     list rows that still need a category
  python tracker.py add-rule "PATTERN" "Category"     save a rule (then run recategorize)
  python tracker.py set ID "Category"                 set one row's category (one-offs)
  python tracker.py note ID "what this was"            add a note to a row
  python tracker.py search "zelle"                    find rows (shows IDs)
  python tracker.py split ID "Utilities & Phone=40" Rent
                                                      split one row across categories

Add --local to use data/transactions.csv instead of Google Sheets.
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

from spending_tracker.categorize import DEFAULT_RULES_PATH, UNCATEGORIZED, categorize, load_rules
from spending_tracker.core import merge, print_summary, recategorize, split
from spending_tracker.local_store import LocalStore
from spending_tracker.parsers import parse_chase_csv

ROOT = Path(__file__).resolve().parent
LOCAL_RULES = ROOT / "rules.local.csv"


def load_config() -> dict:
    path = ROOT / "config.json"
    if path.exists():
        return json.loads(path.read_text())
    # Scheduled runs have no config.json; they pass the same JSON as a secret.
    return json.loads(os.environ.get("TRACKER_CONFIG") or "{}")


def local_rules() -> list:
    rules = load_rules(LOCAL_RULES) if LOCAL_RULES.exists() else []
    return rules + load_rules(DEFAULT_RULES_PATH)


def _add_local_rule(pattern: str, category: str) -> None:
    # Insert at the top so the newest rule wins over older ones.
    rows = list(csv.reader(open(LOCAL_RULES, newline="", encoding="utf-8"))) if LOCAL_RULES.exists() else []
    body = [r for r in rows if r and r[0] != "pattern"]
    with open(LOCAL_RULES, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["pattern", "category"], [pattern, category]] + body)


def _line(t) -> str:
    note = f"  [{t.note}]" if t.note else ""
    return f"{t.id[:8]}  {t.date}  {t.amount:>9.2f}  {t.category:18}  {t.exclude:9}  {t.description}{note}"


def open_store(args, cfg):
    if args.local or not cfg.get("sheet_id"):
        if not args.local:
            print("No sheet_id in config.json; using local mode (data/transactions.csv).")
        return LocalStore(ROOT / "data" / "transactions.csv"), local_rules()
    from spending_tracker.sheets import SheetStore
    store = SheetStore(cfg)
    return store, store.read_rules()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--local", action="store_true", help="use data/transactions.csv instead of Google Sheets")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("files", nargs="+")
    syn = sub.add_parser("sync")
    syn.add_argument("--dry-run", action="store_true", help="show what would be added without changing anything")
    rec = sub.add_parser("recategorize")
    rec.add_argument("--match", action="append", help="re-apply rules to all rows containing this text, not just Uncategorized (repeatable)")
    sub.add_parser("uncategorized")
    rule = sub.add_parser("add-rule")
    rule.add_argument("pattern")
    rule.add_argument("category")
    st = sub.add_parser("set")
    st.add_argument("id")
    st.add_argument("category")
    nt = sub.add_parser("note")
    nt.add_argument("id")
    nt.add_argument("text")
    find = sub.add_parser("search")
    find.add_argument("text")
    sp = sub.add_parser("split")
    sp.add_argument("id")
    sp.add_argument("parts", nargs="+", help='"Category=amount" ..., one may omit =amount to take the rest')
    args = p.parse_args()

    cfg = load_config()
    store, rules = open_store(args, cfg)
    if args.cmd == "add-rule":
        if isinstance(store, LocalStore):
            _add_local_rule(args.pattern, args.category)
        else:
            store.add_rule(args.pattern, args.category)
        print(f"Added rule: {args.pattern!r} -> {args.category}")
        return
    txns = store.read()

    if args.cmd == "import":
        incoming = []
        for f in args.files:
            rows = parse_chase_csv(f, cfg.get("accounts"))
            print(f"{Path(f).name}: {len(rows)} rows")
            incoming += rows
        txns, stats = merge(txns, incoming, rules)
        store.write(txns)
        print(f"Added {stats['added']}, skipped {stats['skipped_duplicates']} already present, "
              f"{stats['cancelled_pairs']} cancelled/refunded pairs excluded, "
              f"{stats['uncategorized']} new rows Uncategorized.")
        print()
        print_summary(txns)
    elif args.cmd == "sync":
        from spending_tracker import plaid
        data = plaid.fetch(store.read_cursor())
        incoming = plaid.to_txns(data, cfg.get("accounts"))
        pending = sum(p["pending"] for p in data["added"])
        known = {t.id for t in txns}
        new = [t for t in incoming if t.id not in known]
        print(f"Plaid: {len(incoming)} posted ({len(incoming) - len(new)} already in the ledger), "
              f"{pending} pending skipped until they post.")
        if args.dry_run:
            for t in new:
                t.category = categorize(t, rules)
                print(_line(t))
            print(f"Dry run: would add {len(new)} rows. Nothing was changed.")
            return
        if new:
            txns, stats = merge(txns, incoming, rules)
            store.write(txns)
            print(f"Added {stats['added']}, {stats['cancelled_pairs']} cancelled/refunded pairs excluded, "
                  f"{stats['uncategorized']} new rows Uncategorized.")
        # Save the bookmark only after the rows are written, so a failed run
        # fetches the same transactions again next time (their IDs dedupe).
        store.write_cursor(data["cursor"])
    elif args.cmd == "recategorize":
        n = recategorize(txns, rules, args.match)
        store.write(txns)
        print(f"Categorized {n} rows.")
    elif args.cmd == "uncategorized":
        for t in txns:
            if t.category == UNCATEGORIZED and not t.exclude:
                print(_line(t))
    elif args.cmd in ("set", "note"):
        rows = [t for t in txns if t.id.startswith(args.id)]
        if len(rows) != 1:
            raise SystemExit(f"ID {args.id!r} matched {len(rows)} rows.")
        if args.cmd == "set":
            rows[0].category = args.category
        else:
            rows[0].note = args.text
        store.write(txns)
        print(_line(rows[0]))
    elif args.cmd == "search":
        for t in txns:
            if args.text.lower() in f"{t.description} {t.note}".lower():
                print(_line(t))
    elif args.cmd == "split":
        for t in split(txns, args.id, args.parts):
            print(f"  {t.category:20} {t.amount:9.2f}")
        store.write(txns)


if __name__ == "__main__":
    sys.exit(main())
