"""Connect a bank to Plaid once and get the long-lived access token `sync` uses.

  python tools/plaid_link.py

Asks for your Plaid client_id and secret (the secret isn't echoed), opens Plaid's
hosted Link page in your browser, waits for you to log in to your bank, then
exchanges the result for an access token. On a Mac the client_id, secret and
token are saved to the Keychain (service "spending-tracker-plaid") and never
printed; elsewhere the token is printed once so you can store it as a secret.
Each run creates a new Plaid Item (a Trial plan allows 10), so run it once.
"""
import getpass
import os
import shutil
import subprocess
import sys
import time
import webbrowser

import requests

BASE = {"production": "https://production.plaid.com",
        "sandbox": "https://sandbox.plaid.com"}[os.environ.get("PLAID_ENV", "production")]
SERVICE = "spending-tracker-plaid"
KEYCHAIN = shutil.which("security") is not None

CID = input("Plaid client_id: ").strip()
SECRET = getpass.getpass("Plaid secret (hidden): ").strip()


def call(path, **body):
    r = requests.post(BASE + path, json={"client_id": CID, "secret": SECRET, **body}, timeout=30)
    j = r.json()
    if r.status_code != 200:
        sys.exit(f"{path} failed: {j.get('error_code')}: {j.get('error_message')}")
    return j


def keychain_put(account, value):
    subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", account, "-w", value], check=True)


tok = call("/link/token/create",
           client_name="Spending Tracker",
           language="en",
           country_codes=["US"],
           user={"client_user_id": "spending-tracker-owner"},
           products=["transactions"],
           transactions={"days_requested": 730},   # the most history Plaid allows
           hosted_link={})
link_token, url = tok["link_token"], tok["hosted_link_url"]
print("\nOpening Plaid Link in your browser. If it doesn't open, paste this URL:\n" + url)
webbrowser.open(url)
print("\nPick your bank, and share every account you want tracked. Waiting (up to 30 min)...")

public_token = None
deadline = time.time() + 30 * 60
while time.time() < deadline and not public_token:
    time.sleep(5)
    for s in call("/link/token/get", link_token=link_token).get("link_sessions") or []:
        for res in (s.get("results") or {}).get("item_add_results") or []:
            public_token = res["public_token"]
        if not public_token and s.get("exit"):
            sys.exit(f"Link was closed without connecting: {s['exit']}")
if not public_token:
    sys.exit("Timed out. Run the script again.")

ex = call("/item/public_token/exchange", public_token=public_token)
if KEYCHAIN:
    for k, v in (("client_id", CID), ("secret", SECRET), ("access_token", ex["access_token"]), ("item_id", ex["item_id"])):
        keychain_put(k, v)
    print(f"\nConnected. Saved to the Keychain (service '{SERVICE}').")
else:
    print(f"\nConnected. Store this as PLAID_ACCESS_TOKEN and keep it private:\n{ex['access_token']}")

print("Accounts Plaid can see (use these last-4 digits in config.json \"accounts\"):")
for a in call("/accounts/get", access_token=ex["access_token"])["accounts"]:
    print(f"  ...{a.get('mask')}  {a.get('name')}  ({a.get('type')}/{a.get('subtype')})")
