"""Parse Chase "Download account activity" CSVs into a common Txn format.

Sign convention (same as Chase): negative = money out, positive = money in.
"""
import csv
import hashlib
import html
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

CHECKING_HEADER = ["Details", "Posting Date", "Description", "Amount", "Type", "Balance", "Check or Slip #"]
CARD_HEADER = ["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"]


@dataclass
class Txn:
    date: date
    description: str
    amount: float
    account: str
    chase_category: str = ""
    chase_type: str = ""
    category: str = ""
    exclude: str = ""
    id: str = ""
    note: str = ""

    @property
    def month(self) -> str:
        return self.date.strftime("%Y-%m")


def clean_description(s: str) -> str:
    s = html.unescape(" ".join(s.split()))
    return re.sub(r"^POS (DEBIT|CREDIT) ", "", s)


def _date(s: str) -> date:
    return datetime.strptime(s.strip(), "%m/%d/%Y").date()


def _make_id(account: str, posted: date, amount: float, description: str, n: int) -> str:
    # n = how many identical rows came before this one in the same file (e.g. three
    # $0.35 vending charges on one day), so re-importing the same range reproduces
    # the same IDs and nothing is added twice.
    raw = f"{account}|{posted.isoformat()}|{amount:.2f}|{description}|{n}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def parse_chase_csv(path, accounts: dict | None = None, today: date | None = None) -> list[Txn]:
    path = Path(path)
    m = re.search(r"Chase(\d{4})", path.name)
    last4 = m.group(1) if m else "????"
    account = (accounts or {}).get(last4, f"Chase ...{last4}")
    today = today or date.today()

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        rows = [dict(zip(header, r)) for r in reader if any(c.strip() for c in r)]

    if header[:7] == CHECKING_HEADER:
        kind = "checking"
    elif header[:7] == CARD_HEADER:
        kind = "card"
    else:
        raise ValueError(f"{path.name}: not a recognized Chase activity CSV (header: {header})")

    seen = Counter()
    out = []
    for r in rows:
        desc = clean_description(r["Description"])
        amount = round(float(r["Amount"].replace(",", "")), 2)
        if kind == "checking":
            posted = shown = _date(r["Posting Date"])
            chase_cat = ""
        else:
            posted, shown = _date(r["Post Date"]), _date(r["Transaction Date"])
            chase_cat = r["Category"].strip()
        # Chase sometimes lists temporary future-dated rows that later disappear
        # and re-post under a different description; skip them until they settle.
        if posted > today:
            continue
        base = (posted, amount, desc)
        n = seen[base]
        seen[base] += 1
        out.append(Txn(
            date=shown,
            description=desc,
            amount=amount,
            account=account,
            chase_category=chase_cat,
            chase_type=r["Type"].strip(),
            id=_make_id(account, posted, amount, desc, n),
        ))
    return out
