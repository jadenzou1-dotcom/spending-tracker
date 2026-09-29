"""Pull posted transactions from Plaid (/transactions/sync) into the same Txn format
as the Chase CSV parser.

Rows get the same IDs a CSV import would give them (account | posted date | amount
| description | n), so a Plaid sync and a CSV import of the same transactions never
add a row twice. Pending transactions are skipped; they arrive again once posted.

Credentials come from environment variables (never from files in this repo):
  PLAID_CLIENT_ID, PLAID_SECRET, PLAID_ACCESS_TOKEN, and optionally PLAID_ENV
  ("production", the default, or "sandbox"). On a Mac, any that aren't set are
  read from the Keychain entries tools/plaid_link.py creates.
"""
import os
import shutil
import subprocess
from collections import Counter
from datetime import date

import requests

from .parsers import Txn, _make_id, clean_description

HOSTS = {"production": "https://production.plaid.com", "sandbox": "https://sandbox.plaid.com"}


def _keychain(name: str) -> str:
    # On a Mac, tools/plaid_link.py saves these to the Keychain.
    if not shutil.which("security"):
        return ""
    r = subprocess.run(["security", "find-generic-password", "-s", "spending-tracker-plaid", "-a", name, "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _credentials() -> dict:
    out, missing = {}, []
    for key, env in (("client_id", "PLAID_CLIENT_ID"), ("secret", "PLAID_SECRET"), ("access_token", "PLAID_ACCESS_TOKEN")):
        out[key] = os.environ.get(env) or _keychain(key)
        if not out[key]:
            missing.append(env)
    if missing:
        raise SystemExit(f"Missing {', '.join(missing)} (see docs/SETUP.md, step 5).")
    return out


def fetch(cursor: str = "") -> dict:
    """Everything that changed since `cursor` ("" = full history), plus the new cursor."""
    url = HOSTS[os.environ.get("PLAID_ENV", "production")] + "/transactions/sync"
    body = {**_credentials(), "count": 500,
            "options": {"include_original_description": True, "include_personal_finance_category": True}}
    out = {"added": [], "modified": [], "removed": [], "accounts": {}}
    while True:
        r = requests.post(url, json={**body, "cursor": cursor}, timeout=60)
        j = r.json()
        if r.status_code != 200:
            # Plaid error bodies never echo the secret; show only the code and message.
            raise SystemExit(f"Plaid error {j.get('error_code')}: {j.get('error_message')}")
        for k in ("added", "modified", "removed"):
            out[k] += j[k]
        out["accounts"].update({a["account_id"]: a for a in j["accounts"]})
        cursor = j["next_cursor"]
        if not j["has_more"]:
            break
    out["cursor"] = cursor
    return out


def to_txns(data: dict, accounts: dict | None = None) -> list[Txn]:
    """Posted transactions from fetch() as Txns. Plaid amounts are positive for
    money out, so the sign is flipped to match the CSVs. Plaid's category goes in
    the Chase Category column, where categorize() falls back to it."""
    seen = Counter()
    out = []
    for p in data["added"]:
        if p["pending"]:
            continue
        acct = data["accounts"][p["account_id"]]
        mask = acct.get("mask") or ""
        account = (accounts or {}).get(mask, f"Chase ...{mask}")
        posted = date.fromisoformat(p["date"])
        amount = round(-p["amount"], 2)
        desc = clean_description(p.get("original_description") or p["name"])
        # Checking CSVs date rows by posting date; card CSVs by purchase date,
        # which Plaid's authorized_date is closest to.
        shown = posted
        if acct.get("type") == "credit" and p.get("authorized_date"):
            shown = date.fromisoformat(p["authorized_date"])
        # Same n as the CSV parser: how many identical rows came before this one.
        base = (account, posted, amount, desc)
        n = seen[base]
        seen[base] += 1
        pfc = (p.get("personal_finance_category") or {}).get("detailed", "")
        out.append(Txn(date=shown, description=desc, amount=amount, account=account,
                       chase_category=pfc, id=_make_id(account, posted, amount, desc, n)))
    return out
