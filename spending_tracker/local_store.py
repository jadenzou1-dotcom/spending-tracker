"""Local CSV storage, used for --local mode and testing without Google Sheets."""
import csv
from datetime import date
from pathlib import Path

from .parsers import Txn

HEADERS = ["Date", "Description", "Amount", "Category", "Exclude", "Account", "Chase Category", "Chase Type", "Month", "ID", "Notes"]


def txn_to_row(t: Txn) -> list:
    return [t.date.isoformat(), t.description, f"{t.amount:.2f}", t.category, t.exclude,
            t.account, t.chase_category, t.chase_type, t.month, t.id, t.note]


def goals_to_rows(goals: dict) -> list:
    return ([["Planned monthly income", goals["income"]], [], ["Category", "Goal", "Unit (% of income or $)"]]
            + [[g["cat"], g["value"], g["unit"]] for g in goals["goals"]])


def parse_goals(rows: list) -> dict:
    def num(s):
        try:
            return float(str(s).replace(",", "").replace("$", "").replace("%", ""))
        except ValueError:
            return 0.0
    income = num(rows[0][1]) if rows and len(rows[0]) > 1 else 0.0
    goals = [{"cat": r[0].strip(), "value": num(r[1]), "unit": "$" if r[2:3] == ["$"] else "%"}
             for r in rows[3:] if len(r) >= 2 and r[0].strip()]
    return {"income": income, "goals": goals}


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

    # Budget goals, same layout as the Sheet's Goals tab.
    def read_goals(self) -> dict:
        p = self.path.with_name("goals.csv")
        if not p.exists():
            return {"income": 0, "goals": []}
        with open(p, newline="", encoding="utf-8") as f:
            return parse_goals(list(csv.reader(f)))

    def write_goals(self, goals: dict) -> None:
        with open(self.path.with_name("goals.csv"), "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(goals_to_rows(goals))
