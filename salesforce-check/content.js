const sleep = ms => new Promise(r => setTimeout(r, ms));

// ── Overlay ────────────────────────────────────────────────────────────────────

let overlay, logEl;
const logLines = [];

function createOverlay() {
  document.getElementById('__sf-checker-overlay')?.remove();
  overlay = document.createElement('div');
  overlay.id = '__sf-checker-overlay';
  overlay.style.cssText = [
    'position:fixed','top:16px','right:16px','z-index:2147483647',
    'background:#0f1b0f','color:#ccc','font:13px/1.6 monospace',
    'border-radius:10px','padding:16px 20px','width:420px',
    'box-shadow:0 8px 32px rgba(0,0,0,.7)','border:1px solid #2a4a2a',
    'max-height:78vh','overflow-y:auto',
  ].join(';');

  const hdr = document.createElement('div');
  hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px';

  const title = document.createElement('span');
  title.id = '__sf-checker-title';
  title.style.cssText = 'font-size:14px;font-weight:700;color:#69F0AE';
  title.textContent = '📊 Hours Check — running…';

  const x = document.createElement('button');
  x.textContent   = '✕';
  x.style.cssText = 'background:none;border:none;color:#666;cursor:pointer;font-size:14px;padding:0 4px';
  x.onclick       = () => overlay.remove();

  logEl = document.createElement('div');
  hdr.append(title, x);
  overlay.append(hdr, logEl);
  document.body.appendChild(overlay);
}

function log(msg, color = '#ccc') {
  logLines.push(msg);
  chrome.storage.local.set({ sfCheckerLog: logLines.join('\n') });

  if (!logEl) return;
  const line = document.createElement('div');
  line.style.cssText = `color:${color};margin-bottom:2px;word-break:break-word`;
  line.textContent   = msg;
  logEl.appendChild(line);
  overlay.scrollTop  = overlay.scrollHeight;
}

function setTitle(t) {
  const el = document.getElementById('__sf-checker-title');
  if (el) el.textContent = t;
}

// ── Salesforce REST API helpers ────────────────────────────────────────────────

const SF_HEADERS = {
  'X-Requested-With': 'XMLHttpRequest',
  'Accept':           'application/json',
};

function apiVer() {
  return window.Salesforce?.settings?.apiVersion ?? 'v59.0';
}

function getSessionId() {
  return new Promise(resolve => {
    chrome.runtime.sendMessage({ action: 'getSessionId' }, ({ sid } = {}) => resolve(sid || ''));
  });
}

// ── Hours check ────────────────────────────────────────────────────────────────

async function fetchLastWeekHours() {
  const soql = [
    'SELECT pse__Resource__r.Name,',
    '  pse__Monday_Hours__c, pse__Tuesday_Hours__c, pse__Wednesday_Hours__c,',
    '  pse__Thursday_Hours__c, pse__Friday_Hours__c, pse__Saturday_Hours__c,',
    '  pse__Sunday_Hours__c',
    'FROM pse__Timecard_Header__c',
    'WHERE pse__Week_Start_Date__c = LAST_WEEK',
  ].join(' ');

  let url = `/services/data/${apiVer()}/query/?q=${encodeURIComponent(soql)}`;
  const allRecords = [];

  // Follow pagination (Salesforce returns max 2000 rows per page)
  while (url) {
    const res = await fetch(url, { headers: SF_HEADERS });
    if (!res.ok) throw new Error(`Hours API ${res.status}: ${(await res.text()).slice(0, 200)}`);
    const data = await res.json();
    allRecords.push(...(data.records ?? []));
    url = data.nextRecordsUrl ?? null;
  }

  const hoursMap = {};
  for (const rec of allRecords) {
    const name = rec.pse__Resource__r?.Name;
    if (!name) continue;
    const weekTotal = (rec.pse__Monday_Hours__c    || 0)
                    + (rec.pse__Tuesday_Hours__c   || 0)
                    + (rec.pse__Wednesday_Hours__c || 0)
                    + (rec.pse__Thursday_Hours__c  || 0)
                    + (rec.pse__Friday_Hours__c    || 0)
                    + (rec.pse__Saturday_Hours__c  || 0)
                    + (rec.pse__Sunday_Hours__c    || 0);
    hoursMap[name] = (hoursMap[name] ?? 0) + weekTotal;
  }
  return hoursMap;
}

async function checkHours() {
  try {
    const txt      = await fetch(chrome.runtime.getURL('reports.txt')).then(r => r.text());
    const expected = txt.split('\n').map(n => n.trim()).filter(Boolean);

    const hoursMap = await fetchLastWeekHours();

    const incomplete = [];
    for (const name of expected) {
      const logged  = hoursMap[name] ?? 0;
      const missing = 40 - logged;
      if (missing > 0) incomplete.push({ name, logged, missing });
    }

    if (incomplete.length === 0) {
      log('🎉 Everyone has logged 40 hours. Nothing missing!', '#69F0AE');
      return;
    }

    log(`⚠️  ${incomplete.length} person(s) with missing hours:`, '#FFCA28');
    log('', '');
    for (const { name, logged, missing } of incomplete) {
      const bar = logged === 0 ? '(no hours logged)' : `${logged}h logged`;
      log(`  • ${name}`, '#FF7043');
      log(`    ${bar}  →  ${missing}h missing`, '#aaa');
    }

  } catch (err) {
    log(`❌ Hours check failed: ${err.message}`, '#FF5252');
  }
}

async function openHoursReport() {
  const DATA_ID  = '0QkQu0000004jjJKAQ';
  const FALLBACK = '/lightning/r/Report/00OQu000005z8FVMAY/view';

  log('', '');
  log('🔗 Navigating to "Sven - ALL hours last week"…', '#888');

  const appNav = document.querySelector('one-appnav');
  const navBar = appNav?.shadowRoot?.querySelector('one-app-nav-bar');
  const sr     = navBar?.shadowRoot;

  if (sr) {
    const navItem = sr.querySelector(`one-app-nav-bar-item-root[data-id="${DATA_ID}"]`);
    const navLink = navItem?.shadowRoot?.querySelector('a');
    if (navLink && !navItem.classList.contains('hidden')) {
      navLink.click();
      log('✓ Clicked nav bar tab.', '#69F0AE');
      return;
    }

    const menuItem = sr.querySelector(`one-app-nav-bar-menu-item[data-id="${DATA_ID}"]`);
    const menuLink = menuItem?.shadowRoot?.querySelector('a');
    if (menuLink) {
      menuLink.click();
      log('✓ Clicked overflow menu tab.', '#69F0AE');
      return;
    }
  }

  log('⚠️  Nav tab not found — pin the report to your nav bar for one-click access.', '#FFCA28');
}

// ── Main ───────────────────────────────────────────────────────────────────────

async function runCheck() {
  logLines.length = 0;
  chrome.storage.local.set({ sfCheckerLog: '' });
  createOverlay();

  try {
    const sid = await getSessionId();
    if (sid) {
      SF_HEADERS['Authorization'] = `Bearer ${sid}`;
      log('✓ Session ID obtained.', '#555');
    } else {
      log('⚠️  Could not read session ID — API calls may fail.', '#FFCA28');
    }

    log('📊 Checking last week\'s hours…', '#90CAF9');
    await checkHours();
    await openHoursReport();
  } catch (err) {
    log(`❌ Fatal: ${err.message}`, '#FF5252');
  }

  log('', '');
  log('Overlay closes in 30 s.', '#555');
  setTitle('📊 Hours Check — done');
  setTimeout(() => overlay?.remove(), 30000);
}

if (!window.__sfCheckerRunning) {
  window.__sfCheckerRunning = true;
  runCheck().finally(() => delete window.__sfCheckerRunning);
}
