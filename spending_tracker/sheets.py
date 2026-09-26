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
from .local_store import HEADERS, row_to_txn
from .parsers import Txn

TX, SUMMARY, RULES, CHARTS = "Transactions", "Summary", "Rules", "Charts"


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
        self._write_charts(f"{_col(first_cat)}", f"{_col(cat_cols[-1])}")

    def _write_charts(self, c0: str, c1: str) -> None:
        """Charts tab: top 7 spending categories + "Everything else", all time and latest month.
        The tables are formulas over Summary, so the pies update whenever Summary does."""
        ws = self._tab(CHARTS, rows=60, cols=6)

        def top(row: int) -> str:
            pairs = f"TRANSPOSE({{{SUMMARY}!{c0}1:{c1}1;{SUMMARY}!{c0}{row}:{c1}{row}}})"
            return (f"=LET(t,SORT(FILTER({pairs},INDEX({pairs},,2)>0),2,FALSE),"
                    f"IF(ROWS(t)>7,VSTACK(ARRAY_CONSTRAIN(t,7,2),"
                    f"{{\"Everything else\",SUM(INDEX(t,,2))-SUM(ARRAY_CONSTRAIN(INDEX(t,,2),7,1))}}),t))")

        ws.clear()
        ws.update(values=[["All time", "", "", "=\"Latest month (\"&Summary!A3&\")\"", ""], [top(2), "", "", top(3), ""]],
                  range_name="A1", value_input_option="USER_ENTERED")
        sid = ws.id
        requests = [_range_fmt(sid, 1, 10, c, c + 1, "CURRENCY", "$#,##0") for c in (1, 4)]
        meta = self.ss.fetch_sheet_metadata({"fields": "sheets(properties.sheetId,charts.chartId)"})
        if not any(sh.get("charts") for sh in meta["sheets"] if sh["properties"]["sheetId"] == sid):
            for i, (title, col) in enumerate([("All-time spending", 0), ("Latest month", 3)]):
                requests.append({"addChart": {"chart": {
                    "spec": {"title": title, "pieChart": {
                        "legendPosition": "RIGHT_LEGEND",
                        "domain": {"sourceRange": {"sources": [{"sheetId": sid, "startRowIndex": 1, "endRowIndex": 10,
                                                                "startColumnIndex": col, "endColumnIndex": col + 1}]}},
                        "series": {"sourceRange": {"sources": [{"sheetId": sid, "startRowIndex": 1, "endRowIndex": 10,
                                                                "startColumnIndex": col + 1, "endColumnIndex": col + 2}]}}}},
                    "position": {"overlayPosition": {"anchorCell": {"sheetId": sid, "rowIndex": 11 + 19 * i, "columnIndex": 0},
                                                     "widthPixels": 520, "heightPixels": 340}}}}})
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
