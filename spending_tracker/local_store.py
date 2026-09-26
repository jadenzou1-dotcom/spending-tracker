"""Local CSV storage, used for --local mode and testing without Google Sheets."""
import csv
from datetime import date
from pathlib import Path

from .parsers import Txn

HEADERS = ["Date", "Description", "Amount", "Category", "Exclude", "Account", "Chase Category", "Chase Type", "Month", "ID", "Notes"]


def txn_to_row(t: Txn) -> list:
    return [t.date.isoformat(), t.description, f"{t.amount:.2f}", t.category, t.exclude,
            t.account, t.chase_category, t.chase_type, t.month, t.id, t.note]


def row_to_txn(r: dict) -> Txn:
    return Txn(
        date=date.fromisoformat(r["Date"]), description=r["Description"],
        amount=round(float(str(r["Amount"]).replace(",", "").replace("$", "")), 2),
        account=r["Account"], chase_category=r["Chase Category"], chase_type=r["Chase Type"],
        category=r["Category"], exclude=r["Exclude"], id=r["ID"], note=r.get("Notes") or "",
    )


class LocalStore:
    def __init__(self, path):
        self.path = Path(path)

    def read(self) -> list[Txn]:
        if not self.path.exists():
            return []
        with open(self.path, newline="", encoding="utf-8") as f:
            return [row_to_txn(r) for r in csv.DictReader(f)]

    def write(self, txns: list[Txn]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(HEADERS)
            w.writerows(txn_to_row(t) for t in txns)

    # Plaid's sync bookmark, next to the ledger.
    def read_cursor(self) -> str:
        p = self.path.with_name("plaid_cursor.txt")
        return p.read_text().strip() if p.exists() else ""

    def write_cursor(self, cursor: str) -> None:
        self.path.with_name("plaid_cursor.txt").write_text(cursor)
