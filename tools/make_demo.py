"""Build the demo: fake Chase exports for a made-up person, run them through the
real pipeline, and write what each part of the tracker would show.

  .venv/bin/python tools/make_demo.py            rebuild examples/demo/ and docs/demo/
  .venv/bin/python tools/make_demo.py --shots    also redo docs/images/*.png (needs Google Chrome)
  .venv/bin/python tools/make_demo.py --sheet ID also fill that Google Sheet (the public demo, docs/DEMO.md)

Everything here is invented (names, merchants' store numbers, amounts). Outputs:
  examples/demo/Chase1234_Activity_*.csv, Chase5678_Activity_*.csv   fake bank exports
  examples/demo/rules.csv, goals.csv          what the Rules and Goals tabs would hold
  examples/demo/transactions.csv, summary.csv the Transactions and Summary tabs
  docs/demo/dashboard.html                    the real dashboard page with the fake data
  docs/demo/sheet.html                        a static picture of the Sheet's tabs
"""
import csv
import html
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spending_tracker import dashboard  # noqa: E402
from spending_tracker.categorize import (DEFAULT_RULES_PATH, INCOME_CATEGORIES, UNCATEGORIZED,  # noqa: E402
                                         is_income, is_spending, load_rules)
from spending_tracker.core import merge, split  # noqa: E402
from spending_tracker.local_store import HEADERS, goals_to_rows, txn_to_row  # noqa: E402
from spending_tracker.parsers import parse_chase_csv  # noqa: E402
from spending_tracker.sheets import GROUP_TINTS  # noqa: E402

TODAY = date(2026, 9, 28)
START = date(2026, 3, 1)
ACCOUNTS = {"1234": "Checking", "5678": "Credit Card"}
EXAMPLES = ROOT / "examples" / "demo"
DOCS = ROOT / "docs" / "demo"
IMAGES = ROOT / "docs" / "images"

# What the demo person would have added with `add-rule` (their Rules tab).
PERSONAL_RULES = [
    ("MAPLE ST PROPERTIES", "Rent"),
    ("Zelle payment from JORDAN LEE", "Rent"),
    ("NORTHWIND LABS", "Work Income"),
    ("Zelle payment from MOM", "Family Income"),
    ("CRUNCH FITNESS", "Health & Fitness"),
]

GOALS = {"income": 4400, "groups": [
    {"name": "Housing", "pct": 30, "cats": ["Rent", "Utilities & Phone"]},
    {"name": "Food", "pct": 15, "cats": ["Groceries", "Dining", "Food Delivery", "Snacks"]},
    {"name": "Getting around", "pct": 6, "cats": ["Transport", "Travel"]},
    {"name": "Subscriptions", "pct": 2, "cats": ["Subscriptions"]},
    {"name": "Fun & everything else", "pct": 17, "cats": ["*"]},
]}

# (description, Chase category, low, high, visits per month)
CARD_SPOTS = [
    ("TRADER JOE S #552", "Groceries", 28, 74, 4),
    ("WHOLE FOODS MKT #10233", "Groceries", 18, 55, 1.5),
    ("SWEETGREEN CAMBRIDGE", "Food & Drink", 13, 17, 3),
    ("CAVA 0421", "Food & Drink", 12, 16, 2),
    ("TATTE BAKERY CAFE", "Food & Drink", 6, 14, 3),
    ("DD *DOORDASH THAIKITCHEN", "Food & Drink", 24, 42, 2),
    ("UBER *EATS PENDING", "Food & Drink", 19, 36, 1),
    ("UBER *TRIP HELP.UBER.COM", "Travel", 11, 29, 2.5),
    ("AMAZON MKTPL*ZX81Q2", "Shopping", 12, 68, 2.5),
    ("TARGET 00012345", "Shopping", 15, 60, 1),
    ("CVS/PHARMACY #01234", "Health & Wellness", 7, 26, 1),
    ("STEAMGAMES.COM 4259522985", "Shopping", 5, 40, 0.6),
    ("AMC ASSEMBLY ROW 12", "Entertainment", 16, 24, 0.5),
    ("GREAT CLIPS #4410", "Personal", 24, 30, 0.5),
    ("7-ELEVEN 35512", "Food & Drink", 3, 9, 1.5),
]
CARD_MONTHLY = [  # (day, description, Chase category, amount)
    (3, "NETFLIX.COM", "Entertainment", 15.49),
    (9, "SPOTIFY USA", "Entertainment", 11.99),
    (14, "CRUNCH FITNESS", "Health & Wellness", 29.99),
    (21, "CLAUDE.AI SUBSCRIPTION", "Shopping", 20.00),
    (18, "VERIZON WRLS P007", "Bills & Utilities", 65.00),
]


def build_exports(rng: random.Random) -> tuple[list, list]:
    """Fake rows in Chase's two CSV formats, newest first like the real downloads."""
    card, chk = [], []
    month_card = {}  # month -> card spending, paid from checking the next month
    d = START
    while d < TODAY:
        m0 = d.replace(day=1)
        nxt = (m0 + timedelta(days=32)).replace(day=1)
        days = (min(nxt, TODAY) - m0).days
        for desc, ccat, lo, hi, per in CARD_SPOTS:
            n = int(per * days / 30 + rng.random())
            for _ in range(n):
                day = m0 + timedelta(days=rng.randrange(days))
                card.append([day, desc, ccat, "Sale", -round(rng.uniform(lo, hi), 2)])
        for day, desc, ccat, amt in CARD_MONTHLY:
            if m0.replace(day=day) < TODAY:
                card.append([m0.replace(day=day), desc, ccat, "Sale", -amt])
        if m0.month == 7:  # a trip
            card += [[date(2026, 7, 2), "JETBLUE AIRWAYS 2792100", "Travel", "Sale", -236.40],
                     [date(2026, 7, 10), "AIRBNB * HMQ2ZX8", "Travel", "Sale", -412.75],
                     [date(2026, 7, 12), "PORTLAND LOBSTER CO", "Food & Drink", "Sale", -58.20]]
        if m0.month == 5:
            card.append([date(2026, 5, 16), "BEST BUY 00011122", "Shopping", "Sale", -349.99])
        m = m0.strftime("%Y-%m")
        month_card[m] = -sum(r[4] for r in card if r[0].strftime("%Y-%m") == m)

        # Checking: paychecks, rent, roommate, card payment, utilities, the odd debit-card buy.
        for pay in (m0.replace(day=15), (nxt - timedelta(days=1))):
            if pay < TODAY:
                chk.append([pay, "NORTHWIND LABS PAYROLL PPD ID: 9000000001", 2210.43, "ACH_CREDIT"])
        if m0.replace(day=1) < TODAY:
            chk.append([m0.replace(day=1), "Zelle payment to MAPLE ST PROPERTIES 20260" + m0.strftime("%m") + "01", -2150.00, "QUICKPAY_DEBIT"])
        if m0.replace(day=3) < TODAY:
            chk.append([m0.replace(day=3), "Zelle payment from JORDAN LEE 88" + m0.strftime("%m%d") + "1234", 1135.00, "QUICKPAY_CREDIT"])
        if m0.replace(day=22) < TODAY:
            chk.append([m0.replace(day=22), "EVERSOURCE ENERGY BILL PAYMT", -round(rng.uniform(58, 96), 2), "ACH_DEBIT"])
            chk.append([m0.replace(day=24), "XFINITY INTERNET", -70.00, "ACH_DEBIT"])
        if m0.month in (4, 8):
            chk.append([m0.replace(day=19), "Zelle payment from MOM 77" + m0.strftime("%m%d") + "5555", 150.00, "QUICKPAY_CREDIT"])
        if m0.month == 6:
            chk.append([date(2026, 6, 8), "ATM WITHDRAWAL 004411 06/08 MASS AVE", -60.00, "ATM"])
            chk.append([date(2026, 6, 20), "Online Transfer to SAV ...9012 transaction#: 18804411", -500.00, "ACCT_XFER"])
        prev = (m0 - timedelta(days=1)).strftime("%Y-%m")
        if prev in month_card and m0.replace(day=6) < TODAY:
            amt = round(month_card[prev], 2)
            chk.append([m0.replace(day=6), f"Payment to Chase card ending in 5678 {m0:%m}/06", -amt, "LOAN_PMT"])
            card.append([m0.replace(day=6), "Payment Thank You-Mobile", "", "Payment", amt])
        d = nxt

    # Things for the demo to show off: a cancelled order, an unrecognized shop,
    # and a Venmo that needed a note.
    card += [[date(2026, 9, 11), "AMAZON MKTPL*RT55K1", "Shopping", "Sale", -129.99],
             [date(2026, 9, 15), "AMAZON MKTPL*RT55K1", "Shopping", "Return", 129.99]]
    chk += [[date(2026, 9, 19), "SQ *HONEYCOMB MARKET 09/19", -18.50, "DEBIT_CARD"],
            [date(2026, 9, 25), "PP*KESTREL GOODS 09/25", -42.00, "DEBIT_CARD"],
            [date(2026, 8, 30), "VENMO PAYMENT 1039554421", -36.00, "DEBIT_CARD"]]
    return card, chk


def write_exports(card, chk) -> list[Path]:
    EXAMPLES.mkdir(parents=True, exist_ok=True)
    for old in EXAMPLES.glob("Chase*_Activity_*.csv"):
        old.unlink()
    stamp = TODAY.strftime("%Y%m%d")
    card_path, chk_path = EXAMPLES / f"Chase5678_Activity_{stamp}.csv", EXAMPLES / f"Chase1234_Activity_{stamp}.csv"
    card.sort(key=lambda r: r[0], reverse=True)
    with open(card_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Transaction Date", "Post Date", "Description", "Category", "Type", "Amount", "Memo"])
        for d, desc, ccat, typ, amt in card:
            post = min(d + timedelta(days=1), TODAY - timedelta(days=1))
            w.writerow([f"{d:%m/%d/%Y}", f"{post:%m/%d/%Y}", desc, ccat, typ, f"{amt:.2f}", ""])
    chk.sort(key=lambda r: r[0], reverse=True)
    bal = 6140.18
    with open(chk_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Details", "Posting Date", "Description", "Amount", "Type", "Balance", "Check or Slip #"])
        for d, desc, amt, typ in chk:
            w.writerow(["CREDIT" if amt > 0 else "DEBIT", f"{d:%m/%d/%Y}", desc, f"{amt:.2f}", typ, f"{bal:.2f}", ""])
            bal = round(bal - amt, 2)
    return [chk_path, card_path]


def run_pipeline(paths):
    rules = PERSONAL_RULES + load_rules(DEFAULT_RULES_PATH)
    incoming = [t for p in paths for t in parse_chase_csv(p, ACCOUNTS, today=TODAY)]
    txns, stats = merge([], incoming, rules)
    # What the person did afterwards, the same way they'd do it from the command line:
    for t in txns:
        # tracker.py split <ID> "Utilities & Phone=60" Rent  (roommate's share of utilities)
        if t.description.startswith("Zelle payment from JORDAN LEE") and t.exclude != "split":
            split(txns, t.id, ["Utilities & Phone=60", "Rent"])
    notes = {"VENMO PAYMENT": ("Payments to People", "Concert tickets, Sam paid me back in cash"),
             "PP*KESTREL GOODS": ("Shopping", "Birthday present for Riley")}
    for t in txns:
        for key, (cat, note) in notes.items():
            if t.description.startswith(key):
                t.note = note
                if cat:
                    t.category = cat
        if t.description.startswith("SQ *HONEYCOMB"):
            t.category = UNCATEGORIZED  # left for the next `uncategorized` pass
    return txns, stats


def summary_rows(txns) -> list[list]:
    """The Summary tab's values (the Sheet computes the same thing with formulas)."""
    months = sorted({t.month for t in txns}, reverse=True)
    counted = [t for t in txns if not t.exclude and t.category]
    totals = {}
    for t in counted:
        totals[t.category] = totals.get(t.category, 0) + t.amount
    income = sorted((c for c in totals if is_income(c)), key=lambda c: -totals[c]) or INCOME_CATEGORIES[:1]
    cats = sorted((c for c in totals if is_spending(c) and c != UNCATEGORIZED), key=lambda c: totals[c]) + [UNCATEGORIZED]

    def row(label, rows):
        inc = [float(sum(t.amount for t in rows if t.category == c)) for c in income]
        sp = [0.0 - float(sum(t.amount for t in rows if t.category == c)) for c in cats]
        i, s = sum(inc), sum(sp)
        return [label, i, s, i - s, s / i if i else ""] + inc + sp

    return ([["Month", "Income", "Spent", "Net", "% of income spent"] + income + cats, row("All time", counted)]
            + [row(m, [t for t in counted if t.month == m]) for m in months]), len(income)


def write_tables(txns, summary):
    with open(EXAMPLES / "transactions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADERS)
        w.writerows(txn_to_row(t) for t in txns)
    with open(EXAMPLES / "summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        for r in summary:
            w.writerow([f"{v:.2f}" if isinstance(v, float) else v for v in r])
    with open(EXAMPLES / "rules.csv", "w", newline="") as f:
        csv.writer(f).writerows([["pattern", "category"], *PERSONAL_RULES])
    with open(EXAMPLES / "goals.csv", "w", newline="") as f:
        csv.writer(f).writerows(goals_to_rows(GOALS))


# ---------- a static picture of the Sheet (Transactions / Summary / Rules / Goals) ----------
SHEET_CSS = """
*{box-sizing:border-box}body{margin:0;font:13px Arial,Helvetica,sans-serif;color:#1f1f1f;background:#f9fbfd}
.top{display:flex;align-items:center;gap:10px;padding:10px 14px 6px;background:#f9fbfd}
.logo{width:26px;height:34px;border-radius:3px;background:#0f9d58;position:relative}
.logo:after{content:"";position:absolute;left:6px;right:6px;top:12px;bottom:8px;border:2px solid #fff;border-radius:1px}
.title{font-size:18px}.menu{font-size:13px;color:#444;margin-top:2px}.menu span{margin-right:12px}
.demo{margin-left:auto;background:#fff4d6;border:1px solid #f0d27a;border-radius:12px;padding:3px 10px;font-size:12px}
.bar{height:34px;margin:4px 10px;background:#edf2fa;border-radius:18px}
.fx{display:flex;align-items:center;height:26px;border-top:1px solid #e1e1e1;border-bottom:1px solid #c7c7c7;background:#fff;padding-left:8px;color:#5f6368;font-size:12px}
.fx b{font-style:italic;font-family:Georgia,serif;margin:0 10px 0 50px;color:#5f6368}
.wrap{overflow:hidden;background:#fff}
table{border-collapse:collapse;white-space:nowrap}
td,th{border:1px solid #e2e3e3;height:21px;padding:0 5px;font-weight:normal}
th{background:#f8f9fa;color:#5f6368;font-size:11px;text-align:center;min-width:38px}
td.n{text-align:right}td.b{font-weight:bold}
.sel{display:inline-block;width:0;height:0;border:4px solid transparent;border-top-color:#777;margin:0 0 -2px 6px;float:right;margin-top:7px}
.chip{display:inline-block;padding:0 7px;border-radius:9px;background:#e8eaed;font-size:12px;line-height:17px}
.frozen-r td,.frozen-r th{border-bottom:3px solid #c0c4c8}
.tabs{display:flex;gap:2px;padding:0 10px;background:#f9fbfd;border-top:1px solid #dadce0;height:38px;align-items:center}
.tabs a{padding:8px 16px;color:#444;text-decoration:none;border-radius:4px 4px 0 0}
.tabs a.on{background:#e1e9f7;color:#0b57d0;font-weight:bold}
.tabs a.hid{color:#aaa}
.page{display:none}.page.on{display:block}
"""


def _cell(v, cls="", style=""):
    return f'<td class="{cls}" style="{style}">{v}</td>'


def sheet_html(txns, summary, n_income, rules, goals) -> str:
    letters = [chr(65 + i) for i in range(26)]
    cat_style = "background:#fff"

    # Transactions
    rows = [HEADERS] + [txn_to_row(t) for t in txns[:60]]
    t_html = "<tr><th></th>" + "".join(f"<th>{letters[i]}</th>" for i in range(len(HEADERS))) + "</tr>"
    for r, vals in enumerate(rows, start=1):
        cls = ' class="frozen-r"' if r == 1 else ""
        t_html += f"<tr{cls}><th>{r}</th>"
        for c, v in enumerate(vals):
            v = html.escape(str(v))
            if r == 1:
                t_html += _cell(v, "b")
            elif c == 2:
                t_html += _cell(f"{float(v):,.2f}", "n")
            elif c == 3:
                t_html += _cell(f'<span class="chip">{v}</span><span class="sel"></span>', "", cat_style)
            elif c == 9:
                t_html += _cell(v, "", "color:#777")
            else:
                t_html += _cell(v)
        t_html += "</tr>"

    # Summary, shaded like sheets.py does it
    width = len(summary[0])
    first_inc, first_cat = 5, 5 + n_income  # 0-based columns
    def group(c):
        return "totals" if c < first_inc else "income" if c < first_cat else "spending"
    s_html = "<tr><th></th>" + "".join(f"<th>{letters[i]}</th>" for i in range(width)) + "</tr>"
    for r, vals in enumerate(summary, start=1):
        cls = ' class="frozen-r"' if r == 2 else ""
        s_html += f"<tr{cls}><th>{r}</th>"
        for c, v in enumerate(vals):
            head, body = GROUP_TINTS[group(c)]
            style = f"background:{head if r == 1 else body}"
            if c in (first_inc - 1, first_cat - 1):
                style += ";border-right:3px solid #5f5f5a"
            bold = "b" if r <= 2 else ""
            if isinstance(v, float) and c == 4:
                txt = f"{v:.0%}"
            elif isinstance(v, float):
                txt = ("-$" if v < -0.005 else "$") + f"{abs(v):,.0f}"
            else:
                txt = html.escape(str(v))
            s_html += _cell(txt, f"{bold} {'n' if isinstance(v, float) else ''}", style)
        s_html += "</tr>"

    r_html = "<tr><th></th><th>A</th><th>B</th></tr>" + "".join(
        f"<tr><th>{i}</th>" + _cell(html.escape(p), "b" if i == 1 else "") + _cell(html.escape(c), "b" if i == 1 else "") + "</tr>"
        for i, (p, c) in enumerate([("pattern", "category"), *rules], start=1))

    g_rows = goals_to_rows(goals)
    g_rows[0] = g_rows[0] + ["", "", '<a href="dashboard.html" style="color:#0b57d0">Open spending dashboard</a>']
    g_html = "<tr><th></th>" + "".join(f"<th>{x}</th>" for x in "ABCDE") + "</tr>"
    for i, r in enumerate(g_rows, start=1):
        r = r + [""] * (5 - len(r))
        g_html += f"<tr><th>{i}</th>" + "".join(
            _cell(v if c == 4 else html.escape(str(v)), "b" if i == 3 or (i == 1 and c == 0) else "") for c, v in enumerate(r)) + "</tr>"

    pages = {"transactions": ("Transactions", t_html), "summary": ("Summary", s_html),
             "rules": ("Rules", r_html), "goals": ("Goals", g_html)}
    body = "".join(f'<div class="page" id="p-{k}"><div class="wrap"><table>{t}</table></div></div>' for k, (_, t) in pages.items())
    tabs = "".join(f'<a href="#{k}" data-t="{k}">{n}</a>' for k, (n, _) in pages.items())
    tabs = tabs.replace('<a href="#rules"', '<a href="dashboard.html" title="Replaced by the dashboard">Charts</a><a href="#rules"')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Spending Tracker (demo)</title>
<style>{SHEET_CSS}</style></head><body>
<div class="top"><div class="logo"></div><div><div class="title">Spending Tracker (demo)</div>
<div class="menu"><span>File</span><span>Edit</span><span>View</span><span>Insert</span><span>Format</span><span>Data</span><span>Tools</span><span>Extensions</span><span>Help</span></div></div>
<div class="demo">Fake data · picture of the Google Sheet</div></div>
<div class="bar"></div><div class="fx">A1<b>fx</b></div>
{body}
<div class="tabs">{tabs}</div>
<script>
function show() {{
  const k = (location.hash || "#transactions").slice(1);
  document.querySelectorAll(".page").forEach(p => p.classList.toggle("on", p.id === "p-" + k));
  document.querySelectorAll(".tabs a[data-t]").forEach(a => a.classList.toggle("on", a.dataset.t === k));
}}
addEventListener("hashchange", show); show();
</script></body></html>"""


# ---------- screenshots ----------
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def shoot(page: Path, out: Path, width: int, height: int, extra_js: str = "", hash_: str = "", scale: float = 2,
          phones: list[str] | None = None):
    """Headless Chrome screenshot. extra_js runs after the page's own script (e.g. to switch
    views). With `phones`, the page is shown in 390px-wide phone frames side by side, one per
    script in the list (headless Chrome won't make its window narrower than ~500px)."""
    src = page.read_text()
    with tempfile.TemporaryDirectory() as tmp:
        if phones:
            frames = ""
            for i, js in enumerate(phones):
                (Path(tmp) / f"phone{i}.html").write_text(src.replace("</body>", f"<script>{js}</script></body>"))
                frames += f'<iframe src="phone{i}.html"></iframe>'
            src = ("<!doctype html><style>body{margin:0;background:#e9e7e1;display:flex;gap:40px;justify-content:center;"
                   "padding:36px}iframe{width:390px;height:" + str(height - 72) + "px;border:10px solid #1c1c1e;"
                   "border-radius:44px;background:#fff}</style>" + frames)
        elif extra_js:
            src = src.replace("</body>", f"<script>{extra_js}</script></body>")
        tmp_page = Path(tmp) / page.name
        tmp_page.write_text(src)
        out.unlink(missing_ok=True)
        # Chrome writes the file but doesn't always exit afterwards, so stop it once it has.
        proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                                 f"--force-device-scale-factor={scale}", f"--window-size={width},{height}",
                                 "--virtual-time-budget=3000", f"--user-data-dir={tmp}/profile",
                                 f"--screenshot={out}", tmp_page.as_uri() + hash_],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(120):
            if proc.poll() is not None or (out.exists() and out.stat().st_size):
                break
            time.sleep(0.5)
        time.sleep(1)
        proc.kill()
        proc.wait()
        if not out.exists():
            raise SystemExit(f"No screenshot for {out.name}")
    print(f"  {out.relative_to(ROOT)}")


def screenshots():
    IMAGES.mkdir(parents=True, exist_ok=True)
    dash, sheet = DOCS / "dashboard.html", DOCS / "sheet.html"
    light = 'document.documentElement.dataset.theme="light";'
    three = light + 'state.months=["2026-07","2026-08","2026-09"];pickCat("Dining");'
    shoot(dash, IMAGES / "dashboard-compare.png", 1280, 1500, three)
    shoot(dash, IMAGES / "dashboard-transactions.png", 1280, 520,
          three + 'document.querySelectorAll("#view-compare > .card").forEach((c, i) => { if (i < 2) c.style.display = "none"; });')
    shoot(dash, IMAGES / "dashboard-budget.png", 1280, 720, light + 'setView("budget");state.bMonth="2026-08";renderBudget();')
    # On the phone the page comes from Apps Script, which says "reload" rather than "rerun".
    phone = light + 'document.getElementById("built").textContent=`${spend.length} spending transactions · loaded ${DATA.built} · reload for fresh data`;'
    shoot(dash, IMAGES / "phone.png", 1000, 900, phones=[
        phone + 'setView("compare");', phone + 'setView("budget");state.bMonth="2026-08";renderBudget();'])
    shoot(sheet, IMAGES / "sheet-transactions.png", 1280, 760, hash_="#transactions")
    shoot(sheet, IMAGES / "sheet-summary.png", 1280, 420, hash_="#summary")
    shoot(sheet, IMAGES / "sheet-goals.png", 1280, 360, hash_="#goals")


def fill_sheet(sheet_id: str, txns) -> None:
    """Write the demo into a Google Sheet shared with the service account, through the
    same code a real import uses. Refuses the Sheet named in config.json (your real one)."""
    import json
    from spending_tracker.sheets import RULES, SheetStore
    cfg_path = ROOT / "config.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.exists() else {}
    if sheet_id == cfg.get("sheet_id"):
        raise SystemExit("That's the Sheet in config.json, your real one. Give the demo Sheet's ID.")
    store = SheetStore({"sheet_id": sheet_id, "credentials": cfg.get("credentials", "service_account.json")})
    rules = store._tab(RULES, rows=50, cols=2)
    rules.clear()
    rules.update(values=[["pattern", "category"], *map(list, PERSONAL_RULES)], range_name="A1", value_input_option="RAW")
    rules.freeze(rows=1)
    store.write(txns)
    store.write_goals(GOALS)
    print(f"Filled https://docs.google.com/spreadsheets/d/{sheet_id}")


def main():
    rng = random.Random(7)
    paths = write_exports(*build_exports(rng))
    txns, stats = run_pipeline(paths)
    summary, n_income = summary_rows(txns)
    write_tables(txns, summary)
    DOCS.mkdir(parents=True, exist_ok=True)
    # Marked as a demo so Budget edits say they aren't saved.
    page = re.sub(r'"built":"[^"]*"', '"built":"2026-09-28 08:00","demo":true', dashboard.page(txns, GOALS), count=1)
    (DOCS / "dashboard.html").write_text(page, encoding="utf-8")
    (DOCS / "sheet.html").write_text(sheet_html(txns, summary, n_income, PERSONAL_RULES, GOALS), encoding="utf-8")
    print(f"{len(txns)} ledger rows ({stats['cancelled_pairs']} cancelled pair) -> examples/demo/, docs/demo/")
    if "--sheet" in sys.argv:
        fill_sheet(sys.argv[sys.argv.index("--sheet") + 1], txns)
    if "--shots" in sys.argv:
        screenshots()


if __name__ == "__main__":
    main()
