// Service worker — handles privileged operations content scripts cannot do directly.
//
// No Salesforce API: since late October 2026 Salesforce rejects the browser's session
// cookies for /services/data (401 INVALID_SESSION_ID). The overhead check reads the
// assignment from the Mass Approval grid (content.js), and the hours check downloads
// the hours report as CSV with the normal browser login (like the report's Export), or,
// where the org doesn't serve that, reads the report page in a background tab.
// Fetches from this service worker carry the org's cookies and are not blocked by CORS,
// because the extension has host permissions for the Salesforce domains.

// myorg.lightning.force.com → myorg.my.salesforce.com
function toInstanceHost(host) {
  const suffix = '.lightning.force.com';
  return host.endsWith(suffix)
    ? host.slice(0, -suffix.length) + '.my.salesforce.com'
    : host;
}

// ── Auto-run when the Mass Approval page opens ────────────────────────────────
// Lightning is a single-page app, so a manifest content script would miss in-app
// navigation. tabs.onUpdated reports both full loads and in-app URL changes.

const MASS_APPROVAL = /^https:\/\/[^/]+\.lightning\.force\.com\/lightning\/n\/Mass_Approval_Lightning_Component/;
const lastAutoRun   = new Map(); // tabId → ms; one automatic start per tab per minute

chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (info.status !== 'complete' && !info.url) return;
  if (!MASS_APPROVAL.test(tab.url || '')) return;

  const { autoRun = true } = await chrome.storage.local.get('autoRun');
  if (!autoRun) return;
  if (Date.now() - (lastAutoRun.get(tabId) || 0) < 60000) return;
  lastAutoRun.set(tabId, Date.now());

  await new Promise(r => setTimeout(r, 4000)); // let Lightning and the LWC components boot
  try {
    await chrome.scripting.executeScript({ target: { tabId }, func: () => { window.__sfApproverAuto = true; } });
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
  } catch (e) { /* tab closed or navigated away */ }
});

chrome.tabs.onRemoved.addListener(tabId => lastAutoRun.delete(tabId));

// Chrome only adds manifest content scripts to pages opened after an install or update:
// put the bridge into claude.ai tabs that are already open, so Action Desk needs no reload.
chrome.runtime.onInstalled.addListener(async () => {
  const pages = chrome.runtime.getManifest().content_scripts?.[0]?.matches || [];
  for (const tab of await chrome.tabs.query({ url: pages })) {
    chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ['bridge.js'] }).catch(() => {});
  }
});

// ── Reports waiting for Action Desk ───────────────────────────────────────────
// content.js saves a report after each run; bridge.js (running inside the Action
// Desk artifact) collects them and acknowledges once Action Desk has stored them.

// Hand new reports to any open Action Desk right away (bridge.js passes them on).
async function pushToActionDesk() {
  const pages = chrome.runtime.getManifest().content_scripts?.[0]?.matches || [];
  for (const tab of await chrome.tabs.query({ url: pages })) {
    chrome.tabs.sendMessage(tab.id, { action: 'pushReports' }).catch(() => {});
  }
}

// One change to the waiting list at a time: a report saved while an ack is being
// handled must not be lost (both read the list, change it and write it back).
let pendingChain = Promise.resolve();
const withPending = fn => (pendingChain = pendingChain.then(fn, fn));

async function pendingReports() {
  const { pending = [] } = await chrome.storage.local.get('pending');
  return pending;
}

// ── Hours check: everyone in reports.txt must have 40 hours in the hours report ──
// Runs the saved report through the Analytics API, so its own filters (period, team)
// apply and the numbers match what the report page shows.

const HOURS_REPORT_ID = '00OQu000005z8FVMAY';
const HOURS_REQUIRED  = 40;

// "André de Kleijn" and "Kleijn, André de" both become "andre de kleijn" sorted by word
const nameKey = n => String(n || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  .toLowerCase().replace(/[^a-z\s]/g, ' ').split(/\s+/).filter(Boolean).sort().join(' ');

// The report as CSV, exactly what Export → Details Only gives. Some orgs answer this old
// export link with a web page instead (a sign-in page, or a redirect to Lightning): then
// we return why, and the caller reads the report page itself.
async function downloadReportCsv(tabUrl) {
  const instanceUrl = `https://${toInstanceHost(new URL(tabUrl).hostname)}`;
  const res  = await fetch(`${instanceUrl}/${HOURS_REPORT_ID}?export=1&enc=UTF-8&xf=csv`, { credentials: 'include' });
  const text = await res.text();
  if (res.ok && !/^\s*</.test(text)) return { csv: text };
  const title = (text.match(/<title[^>]*>([^<]*)/i) || [])[1]?.trim();
  return { why: `download gave ${res.status}${title ? ` "${title}"` : ''} from ${new URL(res.url || instanceUrl).host}` };
}

// ── Reading the report page ───────────────────────────────────────────────────
// Opens the report in a background tab and reads the table shown on screen, in every
// frame and through shadow DOM (Lightning renders reports in an iframe, sometimes with
// lightning-datatable). Runs inside the page, so it must be self-contained.
function readReportTables() {
  const clean = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
  const tables = [];
  (function walk(root) {
    root.querySelectorAll('table').forEach(t => tables.push(t));
    root.querySelectorAll('*').forEach(el => el.shadowRoot && walk(el.shadowRoot));
  })(document);
  const found = [];
  for (const t of tables) {
    // Expand rowspan/colspan, so grouped rows carry their group's value (the person).
    const grid = [];
    [...t.rows].forEach((tr, r) => {
      grid[r] = grid[r] || [];
      let c = 0;
      for (const cell of tr.cells) {
        while (grid[r][c] !== undefined) c++;
        const txt = clean(cell);
        for (let i = 0; i < (cell.rowSpan || 1); i++)
          for (let j = 0; j < (cell.colSpan || 1); j++) (grid[r + i] = grid[r + i] || [])[c + j] = txt;
        c += cell.colSpan || 1;
      }
    });
    const headIdx = [...t.rows].findIndex(tr => tr.querySelector('th') && [...tr.cells].some(c => /hour|uren/i.test(clean(c))));
    if (headIdx < 0) { if (grid[0]) found.push({ heads: grid[0] }); continue; }
    found.push({ heads: grid[headIdx], rows: grid.slice(headIdx + 1).map(r => [...r].map(v => v ?? '')) });
  }
  return found.find(f => f.rows?.length) || { tables: tables.length, heads: found.map(f => f.heads.join(' | ')).slice(0, 3) };
}

async function readReportPage(tabUrl) {
  const origin = new URL(tabUrl).origin;
  const tab = await chrome.tabs.create({ url: `${origin}/lightning/r/Report/${HOURS_REPORT_ID}/view`, active: false });
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let seen = null, lastCount = -1;
  try {
    for (const end = Date.now() + 60000; Date.now() < end;) {
      await sleep(2500);
      const results = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, func: readReportTables }).catch(() => []);
      const answers = results.map(r => r.result).filter(Boolean);
      const hit = answers.find(a => a.rows?.length);
      if (hit) {
        if (hit.rows.length === lastCount) return hit; // two reads alike: the table has finished loading
        lastCount = hit.rows.length;
        continue;
      }
      seen = answers;
    }
    const heads = (seen || []).flatMap(a => a.heads || []).filter(Boolean);
    throw new Error(`Couldn't read the hours report page${heads.length ? ` (tables found: ${heads.join(' / ')})` : ' (no table found)'}.`);
  } finally {
    chrome.tabs.remove(tab.id).catch(() => {});
  }
}

// Minimal CSV reader: quoted fields, doubled quotes, commas and newlines inside quotes.
function parseCsv(text) {
  const rows = []; let row = [], field = '', quoted = false;
  text = text.replace(/^﻿/, '');
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ',') { row.push(field); field = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field); rows.push(row); row = []; field = '';
    } else field += c;
  }
  if (field || row.length) { row.push(field); rows.push(row); }
  return rows;
}

// "40", "40.00", "40,00", "1.234,50" and "1,234.50" all read as numbers.
function toNumber(v) {
  let t = String(v || '').replace(/[^\d.,-]/g, '');
  if (t.includes(',') && t.includes('.')) t = t.lastIndexOf(',') > t.lastIndexOf('.') ? t.replace(/\./g, '').replace(',', '.') : t.replace(/,/g, '');
  else if (t.includes(',')) t = t.replace(',', '.');
  const n = parseFloat(t);
  return Number.isFinite(n) ? n : 0;
}

const DAY = /(mon|tues|wednes|thurs|fri|satur|sun)day|maandag|dinsdag|woensdag|donderdag|vrijdag|zaterdag|zondag/i;

// Hours per person from the CSV, plus the weeks it covers when it has a date column.
function hoursFromCsv(text) {
  const rows = parseCsv(text);
  // The data ends at the first empty line; Salesforce adds the report name, filters and a
  // copyright notice after it.
  const end  = rows.findIndex((r, i) => i > 0 && r.every(c => !c.trim()));
  const [head, ...data] = end > 0 ? rows.slice(0, end) : rows;
  if (!head || !data.length) throw new Error('The report download was empty.');
  return hoursFromRows(head, data);
}

// Subtotal and total lines on the report page would count a person's hours twice.
const TOTAL_ROW = /^(sub ?total|grand total|total|totaal|subtotaal|eindtotaal)\b/i;

function hoursFromRows(head, data) {
  const label = head.map(h => String(h).trim());
  data = data.filter(r => !r.some(c => TOTAL_ROW.test(String(c).trim())));

  const nameCol  = label.findIndex(h => /resource|employee|contact|person|medewerker/i.test(h) && !/id$/i.test(h));
  const hourCols = label.map((h, i) => /hour|uren/i.test(h) && !DAY.test(h) ? i : -1).filter(i => i >= 0);
  const totalCol = hourCols.find(i => /total|totaal/i.test(label[i])) ?? hourCols[0] ?? -1;
  const dayCols  = label.map((h, i) => DAY.test(h) && /hour|uren/i.test(h) ? i : -1).filter(i => i >= 0);
  if (nameCol < 0 || (totalCol < 0 && !dayCols.length)) {
    throw new Error(`Could not find a person column and an hours column in the report (columns: ${label.join(', ')}).`);
  }
  const dateCol = label.findIndex(h => /week|start date|date|datum/i.test(h));

  const hours = new Map(); // nameKey → { name, hours }
  const dates = [];
  for (const r of data) {
    const name = (r[nameCol] || '').trim();
    const k = nameKey(name);
    if (!k) continue;
    const h = totalCol >= 0 ? toNumber(r[totalCol]) : dayCols.reduce((s, i) => s + toNumber(r[i]), 0);
    const e = hours.get(k) || { name, hours: 0 };
    e.hours += h;
    hours.set(k, e);
    if (dateCol >= 0 && r[dateCol]) dates.push(r[dateCol].trim());
  }
  const uniq = [...new Set(dates)];
  const period = !uniq.length ? `report of ${new Date().toISOString().slice(0, 10)}`
               : uniq.length === 1 ? `week of ${uniq[0]}` : `${uniq[0]} – ${uniq[uniq.length - 1]}`;
  return { hours, period };
}

async function hoursCheck(tabUrl) {
  const expected = (await fetch(chrome.runtime.getURL('reports.txt')).then(r => r.text()))
    .split('\n').map(n => n.trim()).filter(Boolean);

  if (!tabUrl) throw new Error('No Salesforce tab to take the login from.');
  const dl = await downloadReportCsv(tabUrl).catch(err => ({ why: err.message }));
  let parsed;
  if (dl.csv) parsed = hoursFromCsv(dl.csv);
  else {
    try { const t = await readReportPage(tabUrl); parsed = hoursFromRows(t.heads, t.rows); }
    catch (err) { throw new Error(`${err.message} The CSV ${dl.why}.`); }
  }
  const { hours, period } = parsed;
  const missing = expected
    .map(name => ({ name, hours: Math.round((hours.get(nameKey(name))?.hours ?? 0) * 100) / 100, inReport: hours.has(nameKey(name)) }))
    .filter(p => p.hours < HOURS_REQUIRED);

  return { period, required: HOURS_REQUIRED, checked: expected.length, missing, truncated: false };
}

// Must match BUILD in content.js. Chrome reads content.js from disk on every run but keeps
// this service worker until the extension is reloaded, so after copying new files without
// clicking reload the two can differ.
const BUILD = '1.4.2';

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.action === 'build') { sendResponse({ build: BUILD }); return; }

  if (msg.action === 'hoursCheck') {
    hoursCheck(sender.tab?.url)
      .then(result => sendResponse({ result }))
      .catch(err => sendResponse({ error: err.message }));
    return true;
  }

  if (msg.action === 'saveReport') {
    withPending(async () => {
      // A run with nothing approved only carries the hours check: one per period, the latest wins.
      if (!msg.report.rows?.length && !msg.report.fatal && msg.report.hours) {
        msg.report.id = `hours-${msg.report.hours.period || 'unknown'}`.replace(/[^\w-]+/g, '-').slice(0, 60);
      }
      const pending = (await pendingReports()).filter(r => r.id !== msg.report.id);
      pending.push(msg.report);
      await chrome.storage.local.set({ pending: pending.slice(-20) });
      sendResponse({ ok: true });
      pushToActionDesk();
    });
    return true;
  }

  if (msg.action === 'bridgePending') {
    pendingReports().then(reports => sendResponse({ reports }));
    return true;
  }

  if (msg.action === 'bridgeAck') {
    withPending(async () => {
      const ids = new Set(msg.ids || []);
      const pending = (await pendingReports()).filter(r => !ids.has(r.id));
      await chrome.storage.local.set({ pending, lastDelivered: Date.now() });
      sendResponse({ ok: true });
    });
    return true;
  }

  // Open a new tab (window.open() from content scripts is blocked by popup blockers)
  if (msg.action === 'openTab') {
    chrome.tabs.create({ url: msg.url, active: true });
    sendResponse({ ok: true });
  }

});

