"""Assign a spending category to each transaction.

Order: your rules (first matching pattern wins) -> Chase transaction type ->
Chase's own category (credit card CSVs only) or Plaid's category (rows from
`sync`) -> "Uncategorized".
"""
import csv
import re
from pathlib import Path

from .parsers import Txn

TRANSFER, UNCATEGORIZED = "Transfer", "Uncategorized"
# Any category named "... Income" counts as income, so you can add your own
# (e.g. "Scholarship Income") and it gets its own column on the Summary.
INCOME_CATEGORIES = ["Work Income", "Other Income"]

# Column order on the Summary sheet.
SPENDING_CATEGORIES = [
    "Rent", "Utilities & Phone", "Groceries", "Food Delivery", "Dining", "Snacks", "Transport",
    "Travel", "Subscriptions", "Shopping", "Entertainment", "Gaming", "Health & Fitness", "Personal Care",
    "Payments to People", "Cash", "Fees", "Other", UNCATEGORIZED,
]
ALL_CATEGORIES = INCOME_CATEGORIES + [TRANSFER] + SPENDING_CATEGORIES


def is_income(category: str) -> bool:
    return category == "Income" or category.endswith(" Income")


def is_spending(category: str) -> bool:
    return bool(category) and category != TRANSFER and not is_income(category)

TYPE_MAP = {
    "Payment": TRANSFER,          # card: paying the card bill (already counted as purchases)
    "LOAN_PMT": TRANSFER,         # checking: payment to a Chase card
    "ACCT_XFER": TRANSFER,        # checking: moving money between your own accounts
    "ATM": "Cash",
    "FEE_TRANSACTION": "Fees",
    "QUICKPAY_CREDIT": "Other Income",    # Zelle received
    "PARTNERFI_TO_CHASE": "Other Income",
    "QUICKPAY_DEBIT": "Payments to People",
    "CHASE_TO_PARTNERFI": "Payments to People",
}

CHASE_CATEGORY_MAP = {
    "Food & Drink": "Dining",
    "Groceries": "Groceries",
    "Travel": "Travel",
    "Gas": "Transport",
    "Automotive": "Transport",
    "Shopping": "Shopping",
    "Home": "Shopping",
    "Entertainment": "Entertainment",
    "Bills & Utilities": "Utilities & Phone",
    "Health & Wellness": "Health & Fitness",
    "Fees & Adjustments": "Fees",
    "Personal": "Other",
    "Education": "Other",
    "Gifts & Donations": "Other",
    "Professional Services": "Other",
}

# Plaid's personal_finance_category (rows from `sync`). The detailed value is
# looked up first, then its primary group (the prefix, e.g. FOOD_AND_DRINK).
PLAID_CATEGORY_MAP = {
    "TRANSFER_IN_ACCOUNT_TRANSFER": TRANSFER,
    "TRANSFER_OUT_ACCOUNT_TRANSFER": TRANSFER,
    "LOAN_PAYMENTS_CREDIT_CARD_PAYMENT": TRANSFER,   # checking side of paying the card
    "LOAN_DISBURSEMENTS_OTHER_DISBURSEMENT": TRANSFER,  # card side of the same payment
    "TRANSFER_IN_TRANSFER_IN_FROM_APPS": "Other Income",    # Zelle / Venmo received
    "TRANSFER_OUT_TRANSFER_OUT_FROM_APPS": "Payments to People",
    "TRANSFER_OUT_WITHDRAWAL": "Cash",
    "INCOME_SALARY": "Work Income",
    "INCOME_WAGES": "Work Income",
    "INCOME": "Other Income",
    "RENT_AND_UTILITIES_RENT": "Rent",
    "RENT_AND_UTILITIES": "Utilities & Phone",
    "FOOD_AND_DRINK_GROCERIES": "Groceries",
    "FOOD_AND_DRINK_VENDING_MACHINES": "Snacks",
    "FOOD_AND_DRINK": "Dining",
    "GENERAL_MERCHANDISE_CONVENIENCE_STORES": "Groceries",
    "GENERAL_MERCHANDISE": "Shopping",
    "HOME_IMPROVEMENT": "Shopping",
    "ENTERTAINMENT_VIDEO_GAMES": "Gaming",
    "ENTERTAINMENT_TV_AND_MOVIES": "Subscriptions",
    "ENTERTAINMENT": "Entertainment",
    "TRANSPORTATION": "Transport",
    "TRAVEL": "Travel",
    "MEDICAL": "Health & Fitness",
    "PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS": "Health & Fitness",
    "PERSONAL_CARE": "Personal Care",
    "BANK_FEES": "Fees",
    "GENERAL_SERVICES": "Other",
    "GOVERNMENT_AND_NON_PROFIT": "Other",
}


def _plaid_category(pfc: str) -> str | None:
    if pfc in PLAID_CATEGORY_MAP:
        return PLAID_CATEGORY_MAP[pfc]
    for key in sorted(PLAID_CATEGORY_MAP, key=len, reverse=True):
        if pfc.startswith(key + "_"):
            return PLAID_CATEGORY_MAP[key]
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).upper().strip()


def load_rules(path) -> list[tuple[str, str]]:
    rules = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2 or not row[0].strip() or row[0].startswith("#") or row[0] == "pattern":
                continue
            rules.append((row[0].strip(), row[1].strip()))
    return rules


def categorize(t: Txn, rules: list[tuple[str, str]]) -> str:
    desc = _norm(t.description)
    for pattern, category in rules:
        if _norm(pattern) in desc:
            return category
    if t.chase_type in TYPE_MAP:
        return TYPE_MAP[t.chase_type]
    if t.chase_category in CHASE_CATEGORY_MAP:
        return CHASE_CATEGORY_MAP[t.chase_category]
    return _plaid_category(t.chase_category) or UNCATEGORIZED


DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "rules.default.csv"
