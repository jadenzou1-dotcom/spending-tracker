"""Google Sheets storage: Transactions, Summary, Charts and Rules tabs.

Transactions is the ledger (edit Category / Exclude / Notes there). Summary and
Charts are rebuilt with live formulas on every run, so edits in the sheet update
them immediately. Rules holds your personal pattern -> category rules, checked
before the defaults.
"""
from collections import defaultdict
from pathlib import Path

import gspread

from .categorize import (ALL_CATEGORIES, DEFAULT_RULES_PATH, INCOME_CATEGORIES, UNCATEGORIZED,
                         is_income, is_spending, load_rules)
from .local_store import HEADERS, row_to_txn
from .parsers import Txn

TX, SUMMARY, RULES, CHARTS = "Transactions", "Summary", "Rules", "Charts"

# Categorical palette (fixed order, colorblind-checked for adjacent stacked segments).
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7"]
OTHER_GRAY = "#9a9a94"


def _rgb(hex_color: str) -> dict:
    return {k: int(hex_color[i:i + 2], 16) / 255 for k, i in (("red", 1), ("green", 3), ("blue", 5))}


def _text(s: str) -> str:
    # Leading apostrophe = store as plain text (no formulas, no date/number guessing).
    return "'" + s if s else ""


def _blank(values: list) -> bool:
    # An empty tab reads back as [[]] (or rows of empty strings), not [].
    return not any(c for row in values for c in row)


def _col(n: int) -> str:
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class SheetStore:
    def __init__(self, cfg: dict):
        creds = Path(cfg["credentials"]).expanduser()
        if not creds.is_absolute():
            creds = Path(__file__).resolve().parent.parent / creds
        gc = gspread.service_account(filename=str(creds))
        self.ss = gc.open_by_key(cfg["sheet_id"])
        self.tx = self._tab(TX, rows=1000, cols=len(HEADERS))

    def _tab(self, name, rows=100, cols=20):
        try:
            return self.ss.worksheet(name)
        except gspread.WorksheetNotFound:
            sheets = self.ss.worksheets()
            # Reuse the blank "Sheet1" a new spreadsheet comes with.
            if len(sheets) == 1 and sheets[0].title.startswith("Sheet") and _blank(sheets[0].get_all_values()):
                sheets[0].update_title(name)
                return sheets[0]
            return self.ss.add_worksheet(name, rows=rows, cols=cols)

    # ---- rules ----
    def read_rules(self) -> list:
        """Rules tab (your overrides) followed by the repo's default rules.
        The tab is created and seeded from rules.local.csv the first time."""
        ws = self._tab(RULES, rows=200, cols=2)
        values = ws.get_all_values()
        if _blank(values):
            local = Path(__file__).resolve().parent.parent / "rules.local.csv"
            personal = load_rules(local) if local.exists() else []
            ws.update(values=[["pattern", "category"]] + [list(r) for r in personal],
                      range_name="A1", value_input_option="RAW")
            ws.freeze(rows=1)
            values = ws.get_all_values()
        mine = [(r[0].strip(), r[1].strip()) for r in values[1:] if len(r) >= 2 and r[0].strip() and r[1].strip()]
        return mine + load_rules(DEFAULT_RULES_PATH)

    def add_rule(self, pattern: str, category: str) -> None:
        # Row 2 = top of the list, so the newest rule wins over older ones.
        self.ss.worksheet(RULES).insert_row([pattern, category], index=2, value_input_option="RAW")

    # ---- transactions ----
    def read(self) -> list[Txn]:
        values = self.tx.get_all_values()
        if _blank(values):
            return []
        header = values[0]
        missing = [h for h in HEADERS if h not in header and h != "Notes"]  # Notes was added later
        if missing:
            # Refuse rather than treat the sheet as empty, which would overwrite it.
            raise SystemExit(f"Transactions tab is missing columns {missing}; fix the header row before running.")
        return [row_to_txn(dict(zip(header, r))) for r in values[1:] if any(r)]

    def write(self, txns: list[Txn]) -> None:
        rows = [HEADERS] + [
            [t.date.isoformat(), _text(t.description), t.amount, t.category, t.exclude,
             t.account, t.chase_category, t.chase_type, _text(t.month), _text(t.id), _text(t.note)]
            for t in txns
        ]
        self.tx.clear()
        self.tx.resize(rows=max(len(rows) + 50, 100), cols=len(HEADERS))
        self.tx.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")

        categories = ALL_CATEGORIES + sorted({t.category for t in txns} - set(ALL_CATEGORIES) - {""})
        sid, n = self.tx.id, len(rows)
        self.ss.batch_update({"requests": [
            {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 1}},
                                       "fields": "gridProperties.frozenRowCount"}},
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold"}},
            _fmt(sid, 0, "DATE", "yyyy-mm-dd"),
            _fmt(sid, 2, "NUMBER", "#,##0.00"),
            {"setDataValidation": {
                "range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": n, "startColumnIndex": 3, "endColumnIndex": 4},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": c} for c in categories]},
                         "showCustomUi": True, "strict": False}}},
            {"autoResizeDimensions": {"dimensions": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": 9}}},
            {"updateDimensionProperties": {"range": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 10, "endIndex": 11},
                                           "properties": {"pixelSize": 260}, "fields": "pixelSize"}},
        ]})
        self._write_summary(txns)

    # ---- summary ----
    def _write_summary(self, txns: list[Txn]) -> None:
        ws = self._tab(SUMMARY)
        months = sorted({t.month for t in txns}, reverse=True)
        # Columns follow *your* data: only categories you actually use, biggest first
        # (all-time total), with Uncategorized last so it's easy to spot.
        totals = defaultdict(float)
        for t in txns:
            if not t.exclude and t.category:
                totals[t.category] += t.amount
        income = sorted((c for c in totals if is_income(c)), key=lambda c: -totals[c]) or INCOME_CATEGORIES[:1]
        cats = sorted((c for c in totals if is_spending(c) and c != UNCATEGORIZED), key=lambda c: totals[c])
        cats.append(UNCATEGORIZED)

        amt, cat, exc, mon = (f"{TX}!${c}$2:${c}" for c in "CDEI")

        def total(month_cell, cat_expr, sign=""):
            return f'={sign}SUM(IFERROR(FILTER({amt},{mon}={month_cell},{cat}={cat_expr},{exc}=""),0))'

        # Columns: A Month | B Income | C Spent | D Net | E % | income sources | spending categories
        first_inc = 6
        first_cat = first_inc + len(income)
        inc_cols = range(first_inc, first_cat)
        cat_cols = range(first_cat, first_cat + len(cats))
        n_last = len(months) + 2
        header = ["Month", "Income", "Spent", "Net", "% of income spent"] + income + cats
        table = [header]
        # Row 2: all-time totals; rows 3+: one per month, newest first.
        table.append(["All time"] + [f"=SUM({_col(i)}3:{_col(i)}{n_last})" for i in range(2, 5)]
                     + ['=IFERROR(C2/B2,"")']
                     + [f"=SUM({_col(i)}3:{_col(i)}{n_last})" for i in [*inc_cols, *cat_cols]])
        for r, m in enumerate(months, start=3):
            table.append([_text(m),
                          f"=SUM({_col(first_inc)}{r}:{_col(first_cat - 1)}{r})",
                          f"=SUM({_col(first_cat)}{r}:{_col(cat_cols[-1])}{r})",
                          f"=B{r}-C{r}", f'=IFERROR(C{r}/B{r},"")']
                         + [total(f"$A{r}", f"{_col(c)}$1") for c in inc_cols]
                         + [total(f"$A{r}", f"{_col(c)}$1", sign="-") for c in cat_cols])

        # Second table: each category as a share of that month's spending.
        start = len(table) + 2
        table += [[], ["Share of spending"] + [""] * (first_cat - 2) + cats]
        for i in range(len(months) + 1):
            src = i + 2
            table.append([f"=A{src}"] + [""] * (first_cat - 2)
                         + [f'=IFERROR({_col(c)}{src}/$C{src},"")' for c in cat_cols])

        ws.clear()
        ws.resize(rows=len(table) + 10, cols=len(header))
        ws.update(values=table, range_name="A1", value_input_option="USER_ENTERED")
        sid = ws.id
        pct_rows = (start, start + len(months) + 1)
        self.ss.batch_update({"requests": [
            {"updateSheetProperties": {"properties": {"sheetId": sid, "gridProperties": {"frozenRowCount": 2, "frozenColumnCount": 1}},
                                       "fields": "gridProperties.frozenRowCount,gridProperties.frozenColumnCount"}},
            _range_fmt(sid, 1, len(months) + 2, 1, len(header), "CURRENCY", "$#,##0"),
            _range_fmt(sid, 1, len(months) + 2, 4, 5, "PERCENT", "0%"),
            _range_fmt(sid, pct_rows[0], pct_rows[1], first_cat - 1, len(header), "PERCENT", "0%"),
            *[{"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r, "endRowIndex": r + 1},
                              "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                              "fields": "userEnteredFormat.textFormat.bold"}} for r in (0, 1, start - 1)],
            {"autoResizeDimensions": {"dimensions": {"sheetId": sid, "dimension": "COLUMNS", "startIndex": 0, "endIndex": len(header)}}},
        ]})
        self._write_charts(months, _col(first_cat), _col(cat_cols[-1]), _col(len(header)), n_last)

    def _write_charts(self, months: list[str], c0: str, c1: str, last: str, n_last: int) -> None:
        """Charts tab, driven by month dropdowns in row 1:
          A-I   bar charts from [B1] to [D1]: stacked spending (top 7 categories in
                that range + "Everything else") and income vs spending
          J->   two pies side by side, for the months in [K1] and [P1]
        Chart data are formulas over Summary, so changing a dropdown re-ranks and
        redraws. The tab is rebuilt on every run but keeps the dropdown choices."""
        ws = self._tab(CHARTS, rows=100, cols=20)
        if not months:
            return
        old = (ws.get("A1:P1") or [[]])[0]

        def kept(c: int, default: str) -> str:
            v = old[c] if c < len(old) else ""
            return v if v in months else default

        prev = months[min(1, len(months) - 1)]
        frm = kept(1, months[min(3, len(months) - 1)])
        to = kept(3, months[0])
        pie1, pie2 = kept(10, prev), kept(15, months[0])

        H, T = 58, 61  # helper row and first chart-data row (1-based, below the charts)
        S = SUMMARY
        mon = f"{S}!$A$3:$A${n_last}"
        grid = f"{S}!$A$1:${last}${n_last}"
        # Dropdown values may come back as dates; normalize to "yyyy-mm" text.
        norm = lambda ref: f'=IF(ISNUMBER({ref}),TEXT({ref},"yyyy-mm"),{ref})'
        FROM, TO, PIE1, PIE2 = (f"${c}${H}" for c in "ABCD")

        def val(month_ref: str, col_expr: str) -> str:
            return f"INDEX({grid},MATCH({month_ref},{S}!$A$1:$A${n_last},0),{col_expr})"

        def col_of(name_ref: str) -> str:
            return f"MATCH({name_ref},{S}!$A$1:${last}$1,0)"

        names = f"{S}!{c0}1:{c1}1"
        in_range = f"(({mon}>={FROM})*({mon}<={TO}))"
        range_totals = f"MMULT(TRANSPOSE({in_range}),{S}!{c0}3:{c1}{n_last})"
        # Top 7 by spending in the range, shown in Summary's column order so colors stay put.
        top7 = (f"=IFERROR(LET(t,FILTER(TRANSPOSE({{{names};{range_totals};SEQUENCE(1,COLUMNS({names}))}}),"
                f"TRANSPOSE({range_totals})>0),"
                f"TRANSPOSE(INDEX(SORT(ARRAY_CONSTRAIN(SORT(t,2,FALSE),7,3),3,TRUE),,1))),\"\")")

        def pie(month: str) -> str:
            row = f"INDEX({S}!{c0}3:{c1}{n_last},MATCH({month},{mon},0),0)"
            pairs = f"TRANSPOSE({{{names};{row}}})"
            return (f"=IFERROR(LET(t,SORT(FILTER({pairs},INDEX({pairs},,2)>0),2,FALSE),"
                    f"IF(ROWS(t)>7,VSTACK(ARRAY_CONSTRAIN(t,7,2),"
                    f"{{\"Everything else\",SUM(INDEX(t,,2))-SUM(ARRAY_CONSTRAIN(INDEX(t,,2),7,1))}}),t)),\"\")")

        N = 24  # max months in the bar charts
        values = [["Bar charts from", _text(frm), "to", _text(to), "", "", "", "", "",
                   "Pie 1", _text(pie1), "", "", "", "Pie 2", _text(pie2)]]
        values += [[] for _ in range(H - 3)]
        values += [["Chart data below (formulas; don't edit)"],
                   [norm("$B$1"), norm("$D$1"), norm("$K$1"), norm("$P$1")]]
        values += [[] for _ in range(T - H - 1)]
        values.append(["Month", top7, "", "", "", "", "", "", "Everything else", "",
                       "Month", "Income", "Spent", "", "Pie 1", "", "", "Pie 2"])
        for i in range(N):
            r = T + 1 + i
            line = [f'=IFERROR(SORT(FILTER({mon},{mon}>={FROM},{mon}<={TO}),1,TRUE),"")' if i == 0 else ""]
            line += [f'=IF(OR($A{r}="",{c}${T}=""),"",IFERROR({val(f"$A{r}", col_of(f"{c}${T}"))},0))'
                     for c in "BCDEFGH"]
            line += [f'=IF($A{r}="","",IFERROR({val(f"$A{r}", 3)},0)-SUM(B{r}:H{r}))', "",
                     f'=IF($A{r}="","",$A{r})',
                     f'=IF($A{r}="","",IFERROR({val(f"$A{r}", 2)},0))',
                     f'=IF($A{r}="","",IFERROR({val(f"$A{r}", 3)},0))', "",
                     pie(PIE1) if i == 0 else "", "", "",
                     pie(PIE2) if i == 0 else ""]
            values.append(line)

        sid = ws.id
        meta = self.ss.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,charts.chartId)"})
        old_charts = [c["chartId"] for sh in meta["sheets"] if sh["properties"]["sheetId"] == sid
                      for c in sh.get("charts", [])]
        # Start from a blank tab: old charts, dropdowns and formats from earlier layouts go too.
        self.ss.batch_update({"requests": [{"deleteEmbeddedObject": {"objectId": cid}} for cid in old_charts] + [
            {"setDataValidation": {"range": {"sheetId": sid}}},
            {"repeatCell": {"range": {"sheetId": sid}, "cell": {}, "fields": "userEnteredFormat"}},
        ]})
        ws.clear()
        ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")

        def src(c: int, r0: int = T - 1, rows: int = N + 1) -> dict:
            return {"sourceRange": {"sources": [{"sheetId": sid, "startRowIndex": r0, "endRowIndex": r0 + rows,
                                                 "startColumnIndex": c, "endColumnIndex": c + 1}]}}

        def anchor(r: int, c: int, w: int, h: int) -> dict:
            return {"overlayPosition": {"anchorCell": {"sheetId": sid, "rowIndex": r, "columnIndex": c},
                                        "widthPixels": w, "heightPixels": h}}

        def columns(title: str, domain: int, cols: list[int], colors: list[str], stacked: bool) -> dict:
            spec = {"chartType": "COLUMN", "legendPosition": "RIGHT_LEGEND", "headerCount": 1,
                    "domains": [{"domain": src(domain)}],
                    "series": [{"series": src(c), "targetAxis": "LEFT_AXIS", "colorStyle": {"rgbColor": _rgb(col)}}
                               for c, col in zip(cols, colors)]}
            if stacked:
                spec["stackedType"] = "STACKED"
            return {"title": title, "basicChart": spec}

        def pie_chart(title: str, col: int) -> dict:
            return {"title": title, "pieChart": {"legendPosition": "RIGHT_LEGEND",
                                                 "domain": src(col, T, 8), "series": src(col + 1, T, 8)}}

        def cells(r0, r1, c0_, c1_, fmt):
            return {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": r0, "endRowIndex": r1,
                                             "startColumnIndex": c0_, "endColumnIndex": c1_},
                                   "cell": {"userEnteredFormat": fmt}, "fields": "userEnteredFormat(" + ",".join(fmt) + ")"}}

        dropdowns = [1, 3, 10, 15]  # B1, D1, K1, P1
        requests = [
            {"setDataValidation": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                                             "startColumnIndex": c, "endColumnIndex": c + 1},
                                   "rule": {"condition": {"type": "ONE_OF_LIST",
                                                          "values": [{"userEnteredValue": m} for m in months]},
                                            "showCustomUi": True, "strict": True}}} for c in dropdowns]
        # Plain-text format keeps a picked "2026-09" from turning into a date.
        requests += [cells(0, 1, c, c + 1, {"numberFormat": {"type": "TEXT"}}) for c in dropdowns]
        requests += [cells(0, 1, c, c + 1, {"textFormat": {"bold": True}}) for c in (0, 2, 9, 14)]
        requests += [
            _range_fmt(sid, T, T + N, 1, 19, "CURRENCY", "$#,##0"),
            {"addChart": {"chart": {"spec": columns("Spending by month (top 7 categories in range)", 0,
                                                    list(range(1, 9)), PALETTE + [OTHER_GRAY], stacked=True),
                                    "position": anchor(2, 0, 880, 400)}}},
            {"addChart": {"chart": {"spec": columns("Income vs spending", 10, [11, 12],
                                                    [PALETTE[0], PALETTE[1]], stacked=False),
                                    "position": anchor(23, 0, 880, 300)}}},
            {"addChart": {"chart": {"spec": pie_chart("Pie 1: month in K1", 14), "position": anchor(2, 9, 480, 400)}}},
            {"addChart": {"chart": {"spec": pie_chart("Pie 2: month in P1", 17), "position": anchor(2, 14, 480, 400)}}},
        ]
        self.ss.batch_update({"requests": requests})

def _fmt(sid, col, kind, pattern):
    return _range_fmt(sid, 1, None, col, col + 1, kind, pattern)


def _range_fmt(sid, r0, r1, c0, c1, kind, pattern):
    rng = {"sheetId": sid, "startRowIndex": r0, "startColumnIndex": c0, "endColumnIndex": c1}
    if r1 is not None:
        rng["endRowIndex"] = r1
    return {"repeatCell": {"range": rng,
                           "cell": {"userEnteredFormat": {"numberFormat": {"type": kind, "pattern": pattern}}},
                           "fields": "userEnteredFormat.numberFormat"}}
