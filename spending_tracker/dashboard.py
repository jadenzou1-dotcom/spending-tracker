"""Interactive dashboard: a page built from the ledger, served on this computer only.

`tracker.py dashboard` starts a small server on 127.0.0.1 and opens the page.
Every reload reads the ledger again, and the Budget view's goals are saved back
to the store (the Sheet's Goals tab, or data/goals.csv in --local mode).
`--static` instead writes data/dashboard.html (goals shown but not saved).
Either way the page holds real transactions, so it only ever lives in data/.
"""
import json
import secrets
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .categorize import is_income, is_spending
from .parsers import Txn

TEMPLATE = Path(__file__).with_name("dashboard.html")


def page(txns: list[Txn], goals: dict, token: str = "") -> str:
    # Same rows the Summary counts: Exclude blank, Transfers left out.
    rows = [{"d": t.date.isoformat(), "m": t.month, "desc": t.description, "amt": t.amount,
             "cat": t.category, "note": t.note,
             "kind": "income" if is_income(t.category) else "spending"}
            for t in txns if not t.exclude and (is_income(t.category) or is_spending(t.category))]
    data = {"built": datetime.now().strftime("%Y-%m-%d %H:%M"), "txns": rows, "goals": goals, "token": token}
    # "</" inside a <script> would end it early.
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.read_text().replace("/*DATA*/null", payload)


def build(txns: list[Txn], goals: dict, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page(txns, goals), encoding="utf-8")
    return out


def clean_goals(raw: dict) -> dict:
    """Validate goals posted by the page: groups with a % of income and their categories."""
    groups, taken = [], set()
    for g in raw.get("groups", [])[:50]:
        name = str(g.get("name", "")).strip().replace(",", " ")[:60]
        if not name or name in {x["name"] for x in groups}:
            continue
        # A category belongs to one group at most.
        cats = [c for c in (str(c).strip().replace(",", " ")[:80] for c in g.get("cats", [])[:200])
                if c and c not in taken]
        taken.update(cats)
        groups.append({"name": name, "pct": min(max(float(g.get("pct") or 0), 0.0), 100.0), "cats": cats})
    return {"income": max(float(raw.get("income") or 0), 0.0), "groups": groups}


def serve(store, port: int, open_browser: bool) -> None:
    # The token stops other websites open in the browser from posting to this server.
    token = secrets.token_urlsafe(24)
    lock = threading.Lock()
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, kind="text/plain; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.headers.get("Host") not in hosts or self.path.split("?")[0] != "/":
                return self._send(404, b"Not found")
            with lock:
                html = page(store.read(), store.read_goals(), token)
            self._send(200, html.encode(), "text/html; charset=utf-8")

        def do_POST(self):
            if (self.headers.get("Host") not in hosts or self.path != "/api/goals"
                    or not secrets.compare_digest(self.headers.get("X-Token", ""), token)):
                return self._send(403, b"Forbidden")
            try:
                goals = clean_goals(json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)))))
            except (ValueError, TypeError, AttributeError):
                return self._send(400, b"Bad goals")
            with lock:
                store.write_goals(goals)
            self._send(200, b"ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Dashboard at {url} (reload the page for fresh data). Ctrl-C to stop.")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
