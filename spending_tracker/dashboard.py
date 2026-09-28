"""Interactive dashboard: one self-contained HTML page built from the ledger.

The page holds a copy of your transactions, so it's written to data/ (gitignored)
and opened locally; nothing is uploaded anywhere. Rerun `tracker.py dashboard`
to refresh it after a sync or import.
"""
import json
from datetime import datetime
from pathlib import Path

from .categorize import is_income, is_spending
from .parsers import Txn

TEMPLATE = Path(__file__).with_name("dashboard.html")


def build(txns: list[Txn], out: Path) -> Path:
    # Same rows the Summary counts: Exclude blank, Transfers left out.
    rows = [{"d": t.date.isoformat(), "m": t.month, "desc": t.description, "amt": t.amount,
             "cat": t.category, "acct": t.account, "note": t.note,
             "kind": "income" if is_income(t.category) else "spending"}
            for t in txns if not t.exclude and (is_income(t.category) or is_spending(t.category))]
    data = {"built": datetime.now().strftime("%Y-%m-%d %H:%M"), "txns": rows}
    # "</" inside a <script> would end it early.
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(TEMPLATE.read_text().replace("/*DATA*/null", payload), encoding="utf-8")
    return out
