"""Google Sheets storage: Transactions, Summary, Charts and Rules tabs.

Transactions is the ledger (edit Category / Exclude / Notes there). Summary and
Charts are rebuilt with live formulas on every run, so edits in the sheet update
them immediately. Rules holds your personal pattern -> category rules, checked
before the defaults.
"""
from pathlib import Path

import gspread

from .categorize import (ALL_CATEGORIES, DEFAULT_RULES_PATH, INCOME_CATEGORIES, SPENDING_CATEGORIES,
                         is_income, is_spending, load_rules)
from .core import monthly_summary
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
        used = {t.category for t in txns}
        income = INCOME_CATEGORIES + sorted(c for c in used if is_income(c) and c not in INCOME_CATEGORIES)
        extra = sorted(c for c in used if is_spending(c) and c not in SPENDING_CATEGORIES)
        cats = SPENDING_CATEGORIES[:-2] + extra + SPENDING_CATEGORIES[-2:]  # custom ones before Other/Uncategorized

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
        self._write_charts(months, {c: _col(i) for c, i in zip(cats, cat_cols)}, txns)

    def _write_charts(self, months: list[str], cat_col: dict[str, str], txns: list[Txn]) -> None:
        """Charts tab: pick a month and a start month from dropdowns; the charts
        (stacked monthly spending, income vs spending, selected-month pie) follow.
        Chart data are formulas over Summary; the tab is rebuilt on every run but
        keeps the dropdown choices."""
        ws = self._tab(CHARTS, rows=100, cols=18)
        if not months:
            return
        old = ws.get("B1:E1")
        picked = old[0][0] if old and old[0] and old[0][0] in months else months[0]
        start = old[0][3] if old and len(old[0]) > 3 and old[0][3] in months else months[min(3, len(months) - 1)]

        # Top 7 categories by spending since the start month, kept in the fixed
        # category order so each one keeps its color from run to run.
        totals = monthly_summary([t for t in txns if t.month >= start])
        spend = {c: sum(m.get(c, 0) for m in totals.values()) for c in cat_col}
        top = [c for c in sorted(spend, key=spend.get, reverse=True) if spend[c] > 0][:7]
        top = [c for c in cat_col if c in top]

        T = 61  # 1-based row where the chart-data tables start (below the charts)
        N = 24  # max months shown in the monthly charts
        row = f"MATCH($A{{r}},{SUMMARY}!$A$3:$A,0)"
        pick = f"MATCH($B$1,{SUMMARY}!$A$3:$A,0)"

        def at(col: str, match: str) -> str:
            return f"INDEX({SUMMARY}!${col}$3:${col},{match})"

        values = [["Month", "", "", "From", ""],
                  ["Income", f"=IFERROR({at('B', pick)},0)", "Spent", f"=IFERROR({at('C', pick)},0)",
                   "Net", f"=IFERROR({at('D', pick)},0)"]]
        values += [[] for _ in range(T - 3)]
        values.append(["Month"] + top + ["Everything else", "", "Month", "Income", "Spent", "",
                       "Category", "Amount"])
        c0, c1 = cat_col[next(iter(cat_col))], list(cat_col.values())[-1]
        pairs = (f"TRANSPOSE({{{SUMMARY}!{c0}1:{c1}1;"
                 f"INDEX({SUMMARY}!{c0}3:{c1},{pick},0)}})")
        pie = (f"=IFERROR(LET(t,SORT(FILTER({pairs},INDEX({pairs},,2)>0),2,FALSE),"
               f"IF(ROWS(t)>7,VSTACK(ARRAY_CONSTRAIN(t,7,2),"
               f"{{\"Everything else\",SUM(INDEX(t,,2))-SUM(ARRAY_CONSTRAIN(INDEX(t,,2),7,1))}}),t)),\"\")")
        for i in range(N):
            r = T + 1 + i
            m = row.format(r=r)
            line = [f'=SORT(FILTER({SUMMARY}!A3:A,{SUMMARY}!A3:A>=$E$1,{SUMMARY}!B3:B<>""),1,TRUE)' if i == 0 else ""]
            line += [f'=IF($A{r}="","",IFERROR({at(cat_col[c], m)},0))' for c in top]
            line += [f'=IF($A{r}="","",IFERROR({at("C", m)},0)-SUM(B{r}:{_col(1 + len(top))}{r}))', "",
                     f'=IF($A{r}="","",$A{r})',
                     f'=IF($A{r}="","",IFERROR({at("B", m)},0))',
                     f'=IF($A{r}="","",IFERROR({at("C", m)},0))', "",
                     pie if i == 0 else ""]
            values.append(line)
        values[0][1], values[0][4] = _text(picked), _text(start)

        ws.clear()
        ws.update(values=values, range_name="A1", value_input_option="USER_ENTERED")

        sid = ws.id
        ncol = len(top) + 2               # Month + top + Everything else
        inc = ncol + 1                    # Month / Income / Spent block
        pie_c = inc + 4                   # Category / Amount block
        meta = self.ss.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,charts.chartId)"})
        old_charts = [c["chartId"] for sh in meta["sheets"] if sh["properties"]["sheetId"] == sid
                      for c in sh.get("charts", [])]

        def rng(c: int, rows: int = N + 1) -> dict:
            return {"sourceRange": {"sources": [{"sheetId": sid, "startRowIndex": T - 1, "endRowIndex": T - 1 + rows,
                                                 "startColumnIndex": c, "endColumnIndex": c + 1}]}}

        def anchor(r: int, h: int) -> dict:
            return {"overlayPosition": {"anchorCell": {"sheetId": sid, "rowIndex": r, "columnIndex": 0},
                                        "widthPixels": 820, "heightPixels": h}}

        def columns(title: str, cols: list[int], colors: list[str], stacked: bool) -> dict:
            spec = {"chartType": "COLUMN", "legendPosition": "RIGHT_LEGEND", "headerCount": 1,
                    "domains": [{"domain": rng(cols[0] - 1 if not stacked else 0)}],
                    "series": [{"series": rng(c), "targetAxis": "LEFT_AXIS", "colorStyle": {"rgbColor": _rgb(col)}}
                               for c, col in zip(cols, colors)]}
            if stacked:
                spec["stackedType"] = "STACKED"
            return {"title": title, "basicChart": spec}

        requests = [{"deleteEmbeddedObject": {"objectId": cid}} for cid in old_charts]
        requests += [
            {"setDataValidation": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                                             "startColumnIndex": c, "endColumnIndex": c + 1},
                                   "rule": {"condition": {"type": "ONE_OF_LIST",
                                                          "values": [{"userEnteredValue": m} for m in months]},
                                            "showCustomUi": True, "strict": True}}} for c in (1, 4)]
        requests += [
            {"repeatCell": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 2, "startColumnIndex": c,
                                      "endColumnIndex": c + 1},
                            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                            "fields": "userEnteredFormat.textFormat.bold"}} for c in (0, 2, 3, 4)]
        requests += [
            _range_fmt(sid, 1, 2, 0, 6, "CURRENCY", "$#,##0"),
            _range_fmt(sid, T, T + N, 1, pie_c + 2, "CURRENCY", "$#,##0"),
            {"addChart": {"chart": {"spec": columns("Spending by month", list(range(1, ncol)),
                                                    PALETTE[:len(top)] + [OTHER_GRAY], stacked=True),
                                    "position": anchor(2, 380)}}},
            {"addChart": {"chart": {"spec": {"title": "Breakdown for the month picked in B1", "pieChart": {
                "legendPosition": "RIGHT_LEGEND",
                "domain": {"sourceRange": {"sources": [{"sheetId": sid, "startRowIndex": T, "endRowIndex": T + 8,
                                                        "startColumnIndex": pie_c, "endColumnIndex": pie_c + 1}]}},
                "series": {"sourceRange": {"sources": [{"sheetId": sid, "startRowIndex": T, "endRowIndex": T + 8,
                                                        "startColumnIndex": pie_c + 1, "endColumnIndex": pie_c + 2}]}}}},
                                    "position": anchor(22, 340)}}},
            {"addChart": {"chart": {"spec": columns("Income vs spending", [inc + 1, inc + 2],
                                                    [PALETTE[0], PALETTE[1]], stacked=False),
                                    "position": anchor(40, 320)}}},
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
