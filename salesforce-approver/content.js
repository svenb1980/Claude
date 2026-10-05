// Wrapped so the script can be injected again into the same page (top-level const would clash).
(() => {

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
// The query itself runs in background.js: the sid cookie on *.lightning.force.com
// is a Lightning-only session that /services/data rejects (INVALID_SESSION_ID), and
// calling the org's *.my.salesforce.com instance domain from here would be blocked
// by CORS. The service worker has host permissions for both and bypasses CORS.

// Try to read the API version the page uses; fall back to v59.0
function apiVer() {
  return window.Salesforce?.settings?.apiVersion ?? 'v59.0';
}

async function soqlQuery(soql) {
  const resp = await chrome.runtime.sendMessage({
    action:     'soqlQuery',
    soql,
    apiVersion: apiVer(),
  });
  if (!resp)       throw new Error('No response from background service worker.');
  if (resp.error)  throw new Error(resp.error);
  return resp.data;
}

// ── Batch-fetch Assignment names ───────────────────────────────────────────────

async function fetchAssignments(recordIds) {
  const idList = recordIds.map(id => `'${id}'`).join(',');
  const soql   = `SELECT Id, pse__Assignment__r.Name `
               + `FROM pse__Timecard_Header__c `
               + `WHERE Id IN (${idList})`;

  const data = await soqlQuery(soql);

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

// ── Run report (handed to Action Desk via background.js → bridge.js) ─────────

const report = {
  id:        `sf-${Date.now()}`,
  startedAt: Date.now(),
  auto:      !!window.__sfApproverAuto,
  approved:  0, rejected: 0, errors: 0,
  rows:      [],   // { label, assignment, outcome: 'approved' | 'rejected' | 'error', error? }
  fatal:     '',
};

function fatal(msg) {
  report.fatal = msg;
  log(`❌ ${msg}`, '#FF5252');
}

// Automatic runs wait a moment so you can still stop them.
async function countdown(seconds) {
  let cancelled = false;
  const line = document.createElement('div');
  line.style.cssText = 'display:flex;justify-content:space-between;align-items:center;gap:12px;color:#FFCA28;margin-bottom:8px';
  const text = document.createElement('span');
  const stop = document.createElement('button');
  stop.textContent   = 'Cancel';
  stop.style.cssText = 'background:#3a2a10;color:#FFCA28;border:1px solid #FFCA28;border-radius:6px;cursor:pointer;padding:2px 10px;font:inherit';
  stop.onclick       = () => { cancelled = true; };
  line.append(text, stop);
  logEl.appendChild(line);
  for (let s = seconds; s > 0 && !cancelled; s--) {
    text.textContent = `Mass Approval opened — starting automatically in ${s} s…`;
    await sleep(1000);
  }
  line.remove();
  return !cancelled;
}

// ── Main ───────────────────────────────────────────────────────────────────────

async function runApproval() {
  createOverlay();
  if (report.auto && !(await countdown(10))) {
    report.cancelled = true;
    setTitle('⏱ Hours Approver — cancelled');
    log('Cancelled. Use the extension button to run it later.', '#888');
    setTimeout(() => overlay?.remove(), 5000);
    return;
  }
  await sleep(4000);

  let approved = 0, rejected = 0, errors = 0;

  try {
    // ── 1. Locate shadow roots ───────────────────────────────────────────────
    log('Locating Mass Approval component…', '#666');
    const maRoot = getMassApprovalRoot();
    if (!maRoot) {
      fatal('Could not reach pse-ma_mass-approval shadow root.');
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
      fatal('Could not reach Bryntum grid after 4 attempts.');
      log('   Check that the Mass Approval page is fully loaded before clicking the button.', '#888');
      return;
    }
    log('✓ Grid located.', '#69F0AE');

    // ── 2. Process rows until none remain ───────────────────────────────────
    // The Bryntum grid virtualizes DOM rows (renders only visible rows).
    // Snapshotting rendered rows can miss items (commonly ~19 visible rows).
    // Instead, iterate until no more rows are present and fetch assignment
    // info per-record on-demand.

    let assignMap = {};
    let processed = 0;
    const attempted = new Set(); // ids already handled — a row that stays put means it failed
    // Loop over the *current* first row repeatedly until the grid is empty
    while (true) {
      const row = bryntumRoot.querySelector('.b-grid-row[role="row"][data-id]');
      if (!row) { log('No more rows in grid.', '#888'); break; }

      const id    = row.dataset.id;
      if (attempted.has(id)) {
        log(`Row ${id} is still in the grid after processing — stopping to avoid a loop.`, '#FF5252');
        break;
      }
      attempted.add(id);
      const label = row.querySelector('[data-column-id="col-name"] a')?.textContent?.trim() ?? id;

      // Ensure we have assignment info for this record (fetch per-record if missing)
      if (!assignMap[id]) {
        try {
          const single = await fetchAssignments([id]);
          assignMap[id] = single[id] ?? { name: '(unknown)', isOverhead: false };
        } catch (apiErr) {
          log(`⚠️  API error fetching ${id}: ${apiErr.message}`, '#FFCA28');
          assignMap[id] = { name: '(unknown)', isOverhead: false };
        }
      }

      const info = assignMap[id] ?? { name: '(not in API result)', isOverhead: false };

      log('', '');
      log(`── ${processed + 1}: ${label}`, '#90CAF9');
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
          report.rows.push({ label, assignment: info.name, outcome: 'rejected' });
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
          report.rows.push({ label, assignment: info.name, outcome: 'approved' });
          log('   ✓ Approved.', '#69F0AE');
        }

        await sleep(7000); // wait for SF to process and grid to refresh before next row

        // Count this processed row and guard against runaway loops
        processed++;
        if (processed > 5000) { log('Aborting: processed > 5000 rows (safety cap).', '#FF5252'); break; }

      } catch (err) {
        log(`   ❌ ${err.message}`, '#FF5252');
        errors++;
        report.rows.push({ label, assignment: info.name, outcome: 'error', error: err.message });
      }
    }

  } catch (err) {
    log(`\n❌ Fatal: ${err.message}`, '#FF5252');
    report.fatal = err.message;
  }
  Object.assign(report, { approved, rejected, errors });

  // ── Approval summary ───────────────────────────────────────────────────────
  log('', '');
  log('────────────────────────────────────', '#2a4a2a');
  log(`✅ Approved : ${approved}`, '#69F0AE');
  log(`🚫 Rejected : ${rejected}`, '#FF7043');
  if (errors) log(`⚠️  Errors   : ${errors}  (see log above)`, '#FFCA28');
}

// ── Hours check ────────────────────────────────────────────────────────────────
// background.js runs the hours report; everyone in reports.txt needs 40 hours in it.

async function runHoursCheck() {
  log('', '');
  log('📊 Checking the hours report…', '#90CAF9');
  try {
    const resp = await chrome.runtime.sendMessage({ action: 'hoursCheck', apiVersion: apiVer() });
    if (!resp)      throw new Error('No response from background service worker.');
    if (resp.error) throw new Error(resp.error);
    const h = resp.result;
    report.hours = h;
    log(`   Period: ${h.period}`, '#888');
    if (h.truncated) log('   ⚠️  Report has more than 2,000 rows — totals may be incomplete.', '#FFCA28');
    if (!h.missing.length) {
      log(`🎉 All ${h.checked} people have ${h.required} hours.`, '#69F0AE');
      return;
    }
    log(`⚠️  ${h.missing.length} of ${h.checked} need to fill in hours:`, '#FFCA28');
    for (const p of h.missing) {
      log(`  • ${p.name} — ${p.inReport ? `${p.hours}h of ${h.required}h` : 'not in the report'}`, '#FF7043');
    }
  } catch (err) {
    report.hours = { error: err.message };
    log(`❌ Hours check failed: ${err.message}`, '#FF5252');
  }
}

function finish() {
  const longer = report.hours?.missing?.length;
  log('', '');
  log(`Overlay closes in ${longer ? 30 : 10} s.`, '#555');
  setTitle('⏱ Hours Approver — done');
  setTimeout(() => overlay?.remove(), longer ? 30000 : 10000);
}

// Keep a report when something happened, went wrong, or someone is short on hours.
function saveReport() {
  if (report.cancelled) return;
  const hoursNews = report.hours && (report.hours.error || report.hours.missing?.length);
  if (!report.rows.length && !report.fatal && !hoursNews) return;
  report.finishedAt = Date.now();
  chrome.runtime.sendMessage({ action: 'saveReport', report }).catch(() => {});
}

if (!window.__sfApproverRunning) {
  window.__sfApproverRunning = true;
  runApproval()
    .catch(err => { report.fatal = err.message; })
    .then(async () => {
      if (report.cancelled) return;
      await runHoursCheck();
      finish();
    })
    .finally(() => {
      saveReport();
      delete window.__sfApproverRunning;
      delete window.__sfApproverAuto;
    });
}

})();
