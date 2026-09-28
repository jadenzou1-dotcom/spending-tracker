/**
 * Spending dashboard as a private web app, served from the Google Sheet itself.
 *
 * Paste into the Sheet's Apps Script project (Extensions > Apps Script) and deploy
 * as a web app that runs as you and only you can open (see README, "Dashboard on
 * your phone"). Each visit reads Transactions and Goals live; Budget edits are
 * saved back to the Goals tab. Index.html is spending_tracker/dashboard.html,
 * produced by `tools/apps_script.py index`.
 */

function doGet() {
  const page = HtmlService.createTemplateFromFile('Index');
  // "</" inside a <script> would end it early.
  page.data = JSON.stringify(loadData_()).replace(/<\//g, '<\\/');
  return page.evaluate()
    .setTitle('Spending')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

// Same rows the Summary counts: Exclude blank, Transfers (and blank categories) left out.
function loadData_() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const values = ss.getSheetByName('Transactions').getDataRange().getDisplayValues();
  const head = values[0];
  const col = name => head.indexOf(name);
  const [D, DESC, AMT, CAT, EXC, NOTE] = ['Date', 'Description', 'Amount', 'Category', 'Exclude', 'Notes'].map(col);
  const txns = [];
  for (const r of values.slice(1)) {
    const cat = (r[CAT] || '').trim();
    if (!r[D] || !cat || cat === 'Transfer' || (r[EXC] || '').trim()) continue;
    const income = cat === 'Income' || cat.endsWith(' Income');
    txns.push({ d: r[D], m: r[D].slice(0, 7), desc: r[DESC], amt: Number(String(r[AMT]).replace(/[,$]/g, '')),
                cat: cat, note: NOTE >= 0 ? r[NOTE] : '', kind: income ? 'income' : 'spending' });
  }
  const built = Utilities.formatDate(new Date(), ss.getSpreadsheetTimeZone(), 'yyyy-MM-dd HH:mm');
  return { built: built, txns: txns, goals: readGoals_(ss), token: '', remote: 'apps_script' };
}

// Goals tab: B1 = estimated monthly income; rows from 4 = Group | Goal % | categories.
function readGoals_(ss) {
  const sheet = ss.getSheetByName('Goals');
  if (!sheet) return { income: 0, groups: [] };
  const rows = sheet.getDataRange().getDisplayValues();
  const num = s => Number(String(s).replace(/[,$%]/g, '')) || 0;
  const groups = rows.slice(3).filter(r => (r[0] || '').trim()).map(r => ({
    name: r[0].trim(), pct: num(r[1]),
    cats: String(r[2] || '').split(',').map(c => c.trim()).filter(Boolean),
  }));
  return { income: rows[0] && rows[0].length > 1 ? num(rows[0][1]) : 0, groups: groups };
}

// Called by the page's Budget view. Mirrors clean_goals() in spending_tracker/dashboard.py.
function saveGoals(raw) {
  // Plain text only: a leading = + - @ would make the Sheet treat it as a formula.
  const text = (s, n) => String(s == null ? '' : s).replace(/,/g, ' ').trim().replace(/^[=+\-@]+/, '').slice(0, n);
  const groups = [], taken = {};
  for (const g of (raw.groups || []).slice(0, 50)) {
    const name = text(g.name, 60);
    if (!name || groups.some(x => x.name === name)) continue;
    const cats = [];
    for (const c of (g.cats || []).slice(0, 200)) {
      const t = text(c, 80);
      if (t && !taken[t]) { taken[t] = true; cats.push(t); }
    }
    groups.push({ name: name, pct: Math.min(Math.max(Number(g.pct) || 0, 0), 100), cats: cats });
  }
  const income = Math.max(Number(raw.income) || 0, 0);
  const rows = [['Estimated monthly income', income, ''], ['', '', ''],
                ['Group', 'Goal (% of income)', 'Categories (comma-separated; * = everything not listed elsewhere)']]
    .concat(groups.map(g => [g.name, g.pct, g.cats.join(', ')]));
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName('Goals') || ss.insertSheet('Goals');
  sheet.clearContents();
  sheet.getRange(1, 1, rows.length, 3).setNumberFormat('@').setValues(rows.map(r => r.map(String)));
  return true;
}
