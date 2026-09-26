"""Merge newly downloaded transactions into the existing ledger."""
from collections import defaultdict

from .categorize import SPENDING_CATEGORIES, TRANSFER, UNCATEGORIZED, categorize, is_income, is_spending
from .pairing import mark_cancellations
from .parsers import Txn


def merge(existing: list[Txn], incoming: list[Txn], rules) -> tuple[list[Txn], dict]:
    """Add incoming rows whose ID isn't already present. Existing rows (and any
    Category / Exclude edits made in the sheet) are left untouched."""
    known = {t.id for t in existing}
    new = []
    for t in incoming:
        if t.id in known:
            continue
        known.add(t.id)
        t.category = categorize(t, rules)
        new.append(t)
    merged = existing + new
    cancelled = mark_cancellations(merged, {t.id for t in new})
    # Newest first; stable sort keeps the bank's order within a day.
    merged.sort(key=lambda t: t.date, reverse=True)
    stats = {
        "added": len(new),
        "skipped_duplicates": len(incoming) - len(new),
        "cancelled_pairs": cancelled,
        "uncategorized": sum(t.category == UNCATEGORIZED for t in new),
    }
    return merged, stats


def recategorize(txns: list[Txn], rules, match: list[str] | None = None) -> int:
    """Re-apply rules to rows still marked Uncategorized, or, with `match`, to every
    row whose description contains any of those texts (overwriting its current category)."""
    changed = 0
    for t in txns:
        if t.chase_type == "SPLIT":
            continue
        if match:
            if not any(m.lower() in t.description.lower() for m in match):
                continue
        elif t.category != UNCATEGORIZED:
            continue
        new = categorize(t, rules)
        if new != UNCATEGORIZED and new != t.category:
            t.category = new
            changed += 1
    return changed


def split(txns: list[Txn], txn_id: str, parts: list[str]) -> list[Txn]:
    """Split one transaction across categories, e.g. a roommate's Zelle covering
    rent + utilities: parts = ["Utilities & Phone=40", "Rent"] (one part may omit
    its amount and takes the remainder). The original row gets Exclude = "split"
    and the pieces are inserted under it, so the Summary counts each piece."""
    matches = [t for t in txns if t.id.startswith(txn_id) and t.chase_type != "SPLIT"]
    if len(matches) != 1:
        raise SystemExit(f"ID {txn_id!r} matched {len(matches)} rows; use more characters of the ID.")
    orig = matches[0]
    if orig.exclude == "split":
        raise SystemExit("That row is already split. Delete its [split] rows and clear Exclude to redo it.")

    sign = 1 if orig.amount > 0 else -1
    pieces, remainder_cat = [], None
    for p in parts:
        cat, _, amt = p.partition("=")
        if amt:
            pieces.append((cat.strip(), round(abs(float(amt)), 2)))
        elif remainder_cat is None:
            remainder_cat = cat.strip()
        else:
            raise SystemExit("Only one part may leave out its amount.")
    rest = round(abs(orig.amount) - sum(a for _, a in pieces), 2)
    if remainder_cat:
        pieces.append((remainder_cat, rest))
    elif rest != 0:
        raise SystemExit(f"Parts add up to {abs(orig.amount) - rest:.2f}, not {abs(orig.amount):.2f}.")

    orig.exclude = "split"
    new = [Txn(date=orig.date, description=f"[split] {orig.description}", amount=sign * a,
               account=orig.account, chase_type="SPLIT", category=cat, id=f"{orig.id}-{i}")
           for i, (cat, a) in enumerate(pieces, start=1)]
    i = txns.index(orig)
    txns[i + 1:i + 1] = new
    return new


def monthly_summary(txns: list[Txn]) -> dict[str, dict[str, float]]:
    """{month: {category: dollars spent (positive), "Income": total, "Spent": total}}"""
    out: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for t in txns:
        if t.exclude or t.category == TRANSFER:
            continue
        m = out[t.month]
        if is_income(t.category):
            m["Income"] += t.amount
        elif is_spending(t.category):
            m[t.category] -= t.amount
            m["Spent"] -= t.amount
    return out


def print_summary(txns: list[Txn], months: int = 6) -> None:
    summary = monthly_summary(txns)
    cats = [c for c in SPENDING_CATEGORIES if any(summary[m].get(c) for m in summary)]
    recent = sorted(summary, reverse=True)[:months]
    print(f"{'':20}" + "".join(f"{m:>10}" for m in recent))
    for row in ["Income", "Spent"] + cats:
        print(f"{row:20}" + "".join(f"{summary[m].get(row, 0):10.2f}" for m in recent))
