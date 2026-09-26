"""Detect cancelled orders / refunds: a charge followed shortly by an equal credit.

Both rows get Exclude = "cancelled" so neither counts toward spending.
A charge -> refund -> charge sequence leaves the second charge counted.
"""
import re
from datetime import timedelta

from .categorize import is_spending
from .parsers import Txn

WINDOW = timedelta(days=10)
CANCELLED = "cancelled"


def _words(t: Txn) -> set[str]:
    return set(re.findall(r"[A-Z]{4,}", t.description.upper()))


def mark_cancellations(txns: list[Txn], new_ids: set[str]) -> int:
    """Pair credits with earlier matching charges. Only pairs touching a newly
    imported row are marked, so clearing "cancelled" by hand in the sheet sticks."""
    used: set[str] = set()
    pairs = 0
    credits = sorted(
        (t for t in txns if t.amount > 0 and is_spending(t.category) and not t.exclude),
        key=lambda t: t.date,
    )
    for c in credits:
        candidates = [
            t for t in txns
            if t.account == c.account
            and t.amount < 0
            and round(t.amount + c.amount, 2) == 0
            and not t.exclude
            and t.id not in used
            and timedelta(0) <= c.date - t.date <= WINDOW
            and _words(t) & _words(c)
        ]
        if not candidates:
            continue
        charge = max(candidates, key=lambda t: t.date)  # closest charge before the credit
        if c.id not in new_ids and charge.id not in new_ids:
            continue
        charge.exclude = c.exclude = CANCELLED
        used.update((charge.id, c.id))
        pairs += 1
    return pairs
