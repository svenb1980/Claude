// ── Utilities ──────────────────────────────────────────────────────────────────

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Generic recursive shadow DOM piercer (used for modals / unknown depths)
function deepQuery(root, selector) {
  const el = root.querySelector(selector);
  if (el) return el;
  for (const child of root.querySelectorAll('*')) {
    if (child.shadowRoot) {
      const found = deepQuery(child.shadowRoot, selector);
      if (found) return found;
    }
  }
  return null;
}

function deepQueryAll(root, selector) {
  const results = Array.from(root.querySelectorAll(selector));
  for (const child of root.querySelectorAll('*')) {
    if (child.shadowRoot) results.push(...deepQueryAll(child.shadowRoot, selector));
  }
  return results;
}

function waitForEl(selector, timeout = 12000) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + timeout;
    const id = setInterval(() => {
      const el = deepQuery(document, selector);
      if (el) { clearInterval(id); resolve(el); return; }
      if (Date.now() > deadline) {
        clearInterval(id);
        reject(new Error(`Timeout waiting for: ${selector}`));
      }
    }, 300);
  });
}

// Trigger LWC-aware value update (plain .value = x is silently ignored)
function setNativeValue(el, value) {
  const proto = el.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  el.dispatchEvent(new Event('input',  { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

// ── Known Shadow DOM Traversal ─────────────────────────────────────────────────
//
// Mass Approval page shadow chain (confirmed via DevTools):
//   document
//   → app_flexipage-lwc-app-flexipage                                  (shadow)
//   → app_flexipage-lwc-app-flexipage-internal                         (shadow)
//   → forcegenerated-flexipage_mass_approval_lightning_component__js   (shadow)
//   → pse-ma_mass-approval                                             (shadow) ← buttons live here
//   → c-ma_mass-approval-grid                                          (shadow)
//   → c-bryntum-widget-host                                            (shadow) ← grid rows live here

const CHAIN_TO_MA = [
  'app_flexipage-lwc-app-flexipage',
  'app_flexipage-lwc-app-flexipage-internal',
  'forcegenerated-flexipage_mass_approval_lightning_component__js',
  'pse-ma_mass-approval',
];

function getMassApprovalRoot() {
  let root = document;
  for (const tag of CHAIN_TO_MA) {
    const el = root.querySelector(tag);
    if (!el) return null;
    root = shadowOrSelf(el);
  }
  return root; // pse-ma_mass-approval shadow root (or element if synthetic shadow)
}

// Some LWC components use Salesforce's synthetic shadow polyfill — shadowRoot is null
// but children are queryable directly on the element. We handle both cases.
function shadowOrSelf(el) {
  return el.shadowRoot ?? el;
}

function getBryntumRoot(maRoot) {
  const gridHost = maRoot.querySelector('c-ma_mass-approval-grid');
  if (!gridHost) return { root: null, error: 'c-ma_mass-approval-grid not found in pse-ma_mass-approval shadow' };

  const gridContent  = shadowOrSelf(gridHost);
  const widgetHost   = gridContent.querySelector('c-bryntum-widget-host');
  if (!widgetHost) return { root: null, error: 'c-bryntum-widget-host not found inside c-ma_mass-approval-grid' };

  const widgetContent = shadowOrSelf(widgetHost);
  // Confirm the Bryntum grid container is reachable
  if (!widgetContent.querySelector('.b-gridbase, .b-grid-row')) {
    return { root: null, error: 'c-bryntum-widget-host found but grid not yet rendered (.b-gridbase missing)' };
  }

  return { root: widgetContent, error: null };
}

// Approve/Reject buttons: lightning-button[data-id="…"] → shadow (or self) → button
function getLightningBtn(maRoot, dataId) {
  const lb = maRoot.querySelector(`lightning-button[data-id="${dataId}"]`);
  return shadowOrSelf(lb)?.querySelector('button') ?? null;
}

// ── Salesforce REST API helpers ────────────────────────────────────────────────
// Content scripts run on the Salesforce origin, so the browser automatically
// attaches the sid cookie to same-origin fetch() calls.
// X-Requested-With prevents Salesforce from treating it as a CSRF attempt.

const SF_HEADERS = {
  'X-Requested-With': 'XMLHttpRequest',
  'Accept':           'application/json',
};

// Try to read the API version the page uses; fall back to v59.0
function apiVer() {
  return window.Salesforce?.settings?.apiVersion ?? 'v59.0';
}

async function sfFetch(soql) {
  const res = await fetch(
    `/services/data/${apiVer()}/query/?q=${encodeURIComponent(soql)}`,
    { headers: SF_HEADERS }
  );
  if (!res.ok) throw new Error(`API ${res.status}: ${(await res.text()).slice(0, 200)}`);
  return res.json();
}

// ── Batch-fetch Assignment names ───────────────────────────────────────────────

async function fetchAssignments(recordIds) {
  const idList = recordIds.map(id => `'${id}'`).join(',');
  const soql   = `SELECT Id, pse__Assignment__r.Name `
               + `FROM pse__Timecard_Header__c `
               + `WHERE Id IN (${idList})`;

  const res = await fetch(
    `/services/data/${apiVer()}/query/?q=${encodeURIComponent(soql)}`,
    { headers: SF_HEADERS }
  );

  if (!res.ok) throw new Error(`API ${res.status}: ${(await res.text()).slice(0, 200)}`);

  const data = await res.json();
  const map  = {};
  for (const rec of data.records) {
    const name = rec.pse__Assignment__r?.Name ?? '';
    map[rec.Id] = { name, isOverhead: /overhead/i.test(name) };
  }
  return map;
}

// ── Overlay ────────────────────────────────────────────────────────────────────

let overlay, logEl;

function createOverlay() {
  document.getElementById('__sf-approver-overlay')?.remove();
  overlay = document.createElement('div');
  overlay.id = '__sf-approver-overlay';
  overlay.style.cssText = [
    'position:fixed','top:16px','right:16px','z-index:2147483647',
    'background:#0f1b0f','color:#ccc','font:13px/1.6 monospace',
    'border-radius:10px','padding:16px 20px','width:420px',
    'box-shadow:0 8px 32px rgba(0,0,0,.7)','border:1px solid #2a4a2a',
    'max-height:78vh','overflow-y:auto',
  ].join(';');

  const hdr   = document.createElement('div');
  hdr.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px';

  const title = document.createElement('span');
  title.id    = '__sf-approver-title';
  title.style.cssText = 'font-size:14px;font-weight:700;color:#69F0AE';
  title.textContent   = '⏱ Hours Approver — running…';

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
  if (!logEl) return;
  const line = document.createElement('div');
  line.style.cssText = `color:${color};margin-bottom:2px;word-break:break-word`;
  line.textContent   = msg;
  logEl.appendChild(line);
  overlay.scrollTop  = overlay.scrollHeight;
}

function setTitle(t) {
  const el = document.getElementById('__sf-approver-title');
  if (el) el.textContent = t;
}

// ── Constants ──────────────────────────────────────────────────────────────────

const REJECTION_COMMENT =
  'Rejected: Overhead assignments are not allowed. Please resubmit with a valid project assignment.';

// Approve modal selectors (confirmed via DevTools inspection)
// Triggered after clicking the Approve button on the main page.
// Confirm button has no data-id — identified by variant="brand" → button text "Approve"
const APPROVE_DIALOG = {
  modal:          'section.slds-modal[data-modal][aria-modal="true"]',
  confirmBtnHost: 'lightning-button[variant="brand"]',
  confirmBtnText: 'Approve',
};

// Reject modal selectors (confirmed via DevTools inspection)
// Modal renders in lightning-overlay-container appended to <body> — outside the LWC page tree.
// deepQuery() pierces all shadow roots recursively, so intermediate hosts are traversed automatically.
// The confirm button lives one shadow root deeper than deepQuery reaches, so we do the final
// pierce manually via .shadowRoot.querySelector() after finding the lightning-button host.
const REJECT_DIALOG = {
  // c-pselib_advanced-text-area[data-id="comments"] → shadow → lightning-textarea → shadow → textarea.slds-textarea
  commentArea:     'textarea.slds-textarea',
  // lightning-button[data-id="comments-action"] → shadow → button[title="Reject Timecard"]
  confirmBtnHost:  'lightning-button[data-id="comments-action"]',
  confirmBtnInner: 'button[title="Reject Timecard"]',
};

// ── Main ───────────────────────────────────────────────────────────────────────

async function runApproval() {
  createOverlay();
  await sleep(4000);

  let approved = 0, rejected = 0, errors = 0;

  try {
    // ── 1. Locate shadow roots ───────────────────────────────────────────────
    log('Locating Mass Approval component…', '#666');
    const maRoot = getMassApprovalRoot();
    if (!maRoot) {
      log('❌ Could not reach pse-ma_mass-approval shadow root.', '#FF5252');
      log('   Verify CHAIN_TO_MA in content.js matches the current page.', '#888');
      return;
    }

    // Retry up to 4 times — the Bryntum grid can take a few seconds to render
    let bryntumRoot = null;
    for (let attempt = 1; attempt <= 4; attempt++) {
      const { root, error } = getBryntumRoot(maRoot);
      if (root) { bryntumRoot = root; break; }
      log(`   Attempt ${attempt}/4 — ${error}`, '#888');
      log(`   Waiting 2 s for grid to finish rendering…`, '#555');
      await sleep(2000);
    }
    if (!bryntumRoot) {
      log('❌ Could not reach Bryntum grid after 4 attempts.', '#FF5252');
      log('   Check that the Mass Approval page is fully loaded before clicking the button.', '#888');
      return;
    }
    log('✓ Grid located.', '#69F0AE');

    // ── 2. Snapshot record IDs for batch API lookup ──────────────────────────
    // We only read IDs now; we re-query the live DOM each iteration because
    // the grid removes a row after it is approved/rejected.
    const initialRows = Array.from(
      bryntumRoot.querySelectorAll('.b-grid-row[role="row"][data-id]')
    );
    const total     = initialRows.length;
    const recordIds = initialRows.map(r => r.dataset.id);

    if (total === 0) {
      log('No pending approval rows — skipping to hours check.', '#FFCA28');
    } else {
      log(`Found ${total} row(s). Fetching assignment names via API…`, '#90CAF9');
    }

    // ── 3 & 4. Batch-fetch + process rows (only if there are any) ────────────
    let assignMap = {};
    if (total > 0) {
      try {
        assignMap = await fetchAssignments(recordIds);
        log(`✓ Assignment data ready (${Object.keys(assignMap).length} records).`, '#69F0AE');
      } catch (apiErr) {
        log(`⚠️  API error: ${apiErr.message}`, '#FFCA28');
        log('   Treating all assignments as non-overhead (safe fallback).', '#888');
        for (const id of recordIds) assignMap[id] = { name: '(unknown)', isOverhead: false };
      }
    }

    // ── 4. Process each row ──────────────────────────────────────────────────
    // After each approval the processed row disappears, so always target the
    // current FIRST row in the live grid rather than holding stale references.
    for (let i = 0; i < total; i++) {
      // Re-query the grid for the current first row
      const row = bryntumRoot.querySelector('.b-grid-row[role="row"][data-id]');
      if (!row) { log('No more rows in grid.', '#888'); break; }

      const id    = row.dataset.id;
      const info  = assignMap[id] ?? { name: '(not in API result)', isOverhead: false };
      const label = row.querySelector('[data-column-id="col-name"] a')?.textContent?.trim() ?? id;

      log('', '');
      log(`── ${i + 1}/${total}: ${label}`, '#90CAF9');
      log(`   Assignment: "${info.name}"`, '#aaa');

      try {
        // Step 1: click the checkbox on the first row
        // Selector confirmed: input[type="checkbox"][data-op-ignore="true"] inside the row
        const chk = row.querySelector('input[type="checkbox"][data-op-ignore="true"]');
        if (chk) {
          if (!chk.checked) chk.click();
          log('   ☑ Checkbox clicked — waiting for SF to enable buttons…', '#888');
        } else {
          log('   ⚠️  Checkbox not found — falling back to row click.', '#FFCA28');
          row.click();
        }
        await sleep(2500); // give SF time to register the selection

        if (info.isOverhead) {
          // ── Reject ─────────────────────────────────────────────────────
          log('   🚫 Overhead detected — rejecting…', '#FF7043');

          const rejectBtn = getLightningBtn(maRoot, 'reject');
          if (!rejectBtn) throw new Error(
            'Reject button not found. Check: lightning-button[data-id="reject"] in pse-ma_mass-approval shadow.'
          );
          rejectBtn.click();
          await sleep(1500);

          // Fill in comment
          const textarea = await waitForEl(REJECT_DIALOG.commentArea, 8000);
          textarea.focus();
          setNativeValue(textarea, REJECTION_COMMENT);
          await sleep(500);

          // Confirm button: find the lightning-button host, then pierce its shadow (or self) for the real button
          const confirmHost = deepQuery(document, REJECT_DIALOG.confirmBtnHost);
          const submitBtn   = shadowOrSelf(confirmHost)?.querySelector(REJECT_DIALOG.confirmBtnInner);
          if (!submitBtn) throw new Error(
            'Reject Timecard button not found in modal. Check REJECT_DIALOG selectors.'
          );
          submitBtn.click();
          await sleep(2500);

          rejected++;
          log('   ✓ Rejected.', '#FF7043');

        } else {
          // ── Approve ────────────────────────────────────────────────────
          log('   ✅ Approving…', '#69F0AE');

          const approveBtn = getLightningBtn(maRoot, 'approve');
          if (!approveBtn) throw new Error(
            'Approve button not found. Check: lightning-button[data-id="approve"] in pse-ma_mass-approval shadow.'
          );
          approveBtn.click();
          await sleep(1500);

          // Wait for the Approve Timecard modal to appear, then confirm
          const modal = await waitForEl(APPROVE_DIALOG.modal, 6000).catch(() => null);
          if (modal) {
            // Find lightning-button[variant="brand"] → pierce shadow → button whose text is "Approve"
            const btnHosts = Array.from(deepQueryAll(document, APPROVE_DIALOG.confirmBtnHost));
            let confirmBtn = null;
            for (const host of btnHosts) {
              const btn = shadowOrSelf(host).querySelector('button');
              if (btn?.textContent?.trim() === APPROVE_DIALOG.confirmBtnText) {
                confirmBtn = btn;
                break;
              }
            }
            if (!confirmBtn) throw new Error(
              'Approve confirm button not found in modal. Check APPROVE_DIALOG selectors.'
            );
            confirmBtn.click();
            await sleep(2000);
          }

          approved++;
          log('   ✓ Approved.', '#69F0AE');
        }

        await sleep(7000); // wait for SF to process and grid to refresh before next row

      } catch (err) {
        log(`   ❌ ${err.message}`, '#FF5252');
        errors++;
      }
    }

  } catch (err) {
    log(`\n❌ Fatal: ${err.message}`, '#FF5252');
  }

  // ── Approval summary ───────────────────────────────────────────────────────
  log('', '');
  log('────────────────────────────────────', '#2a4a2a');
  log(`✅ Approved : ${approved}`, '#69F0AE');
  log(`🚫 Rejected : ${rejected}`, '#FF7043');
  if (errors) log(`⚠️  Errors   : ${errors}  (see log above)`, '#FFCA28');

  // ── Hours report ───────────────────────────────────────────────────────────
  log('', '');
  log('────────────────────────────────────', '#2a4a2a');
  log('📊 Checking last week\'s hours…', '#90CAF9');
  setTitle('⏱ Hours Approver — checking hours…');

  await checkHours();

  // Open the "Sven - ALL hours last week" Salesforce report in a new tab
  await openHoursReport();

  log('', '');
  log('Overlay closes in 30 s.', '#555');
  setTitle('⏱ Hours Approver — done');
  setTimeout(() => overlay?.remove(), 30000);
}

// ── Last-week hours check ──────────────────────────────────────────────────────

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

  // Sum hours per person across all their timecards
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

    // Compare each expected name against logged hours
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
      const bar   = logged === 0 ? '(no hours logged)' : `${logged}h logged`;
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
    // Try the visible nav bar item first
    const navItem = sr.querySelector(`one-app-nav-bar-item-root[data-id="${DATA_ID}"]`);
    const navLink = navItem?.shadowRoot?.querySelector('a');
    if (navLink && !navItem.classList.contains('hidden')) {
      navLink.click();
      log('✓ Clicked nav bar tab.', '#69F0AE');
      return;
    }

    // Fall back to the overflow ("More") menu item
    const menuItem = sr.querySelector(`one-app-nav-bar-menu-item[data-id="${DATA_ID}"]`);
    const menuLink = menuItem?.shadowRoot?.querySelector('a');
    if (menuLink) {
      menuLink.click();
      log('✓ Clicked overflow menu tab.', '#69F0AE');
      return;
    }
  }

  // Last resort: in-page navigation (avoids full page reload vs. new tab)
  log('⚠️  Nav tab not found — using in-page navigation.', '#FFCA28');
  window.location.href = FALLBACK;
}

if (!window.__sfApproverRunning) {
  window.__sfApproverRunning = true;
  runApproval().finally(() => delete window.__sfApproverRunning);
}
