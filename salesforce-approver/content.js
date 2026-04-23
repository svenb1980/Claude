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
    root = el.shadowRoot ?? el;
  }
  return root; // pse-ma_mass-approval shadow root
}

function getBryntumRoot(maRoot) {
  const gridHost   = maRoot.querySelector('c-ma_mass-approval-grid');
  const widgetHost = gridHost?.shadowRoot?.querySelector('c-bryntum-widget-host');
  return widgetHost?.shadowRoot ?? null;
}

// Approve/Reject buttons: lightning-button[data-id="…"] → its shadowRoot → button
function getLightningBtn(maRoot, dataId) {
  const lb = maRoot.querySelector(`lightning-button[data-id="${dataId}"]`);
  return lb?.shadowRoot?.querySelector('button') ?? null;
}

// ── Salesforce REST API — batch-fetch Assignment names ─────────────────────────
// Runs entirely on-domain so existing session cookies authenticate the request.
// No page navigation needed.

async function fetchAssignments(recordIds) {
  // Try to read the API version the page already uses; fall back to v59.0
  const ver = window.Salesforce?.settings?.apiVersion
    ?? document.querySelector('script[src*="/api/v"]')?.src?.match(/\/v(\d+\.\d+)\//)?.[1]?.replace(/^/, 'v')
    ?? 'v59.0';

  const idList = recordIds.map(id => `'${id}'`).join(',');
  const soql   = `SELECT Id, pse__Assignment__r.Name `
               + `FROM pse__Timecard_Header__c `
               + `WHERE Id IN (${idList})`;

  const res = await fetch(
    `/services/data/${ver}/query/?q=${encodeURIComponent(soql)}`,
    { headers: { 'X-Requested-With': 'XMLHttpRequest', Accept: 'application/json' } }
  );

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`REST API ${res.status}: ${text.slice(0, 200)}`);
  }

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
  await sleep(2500);

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

    const bryntumRoot = getBryntumRoot(maRoot);
    if (!bryntumRoot) {
      log('❌ Could not reach c-bryntum-widget-host shadow root.', '#FF5252');
      return;
    }
    log('✓ Grid located.', '#69F0AE');

    // ── 2. Collect approval rows ─────────────────────────────────────────────
    const rows = Array.from(
      bryntumRoot.querySelectorAll('.b-grid-row[role="row"][data-id]')
    );
    if (rows.length === 0) {
      log('No pending approval rows found. Nothing to do.', '#FFCA28');
      return;
    }
    log(`Found ${rows.length} row(s). Fetching assignment names via API…`, '#90CAF9');

    // ── 3. Batch-fetch Assignment names — no page navigation needed ──────────
    const recordIds = rows.map(r => r.dataset.id);
    let assignMap = {};
    try {
      assignMap = await fetchAssignments(recordIds);
      log(`✓ Assignment data ready (${Object.keys(assignMap).length} records).`, '#69F0AE');
    } catch (apiErr) {
      log(`⚠️  API error: ${apiErr.message}`, '#FFCA28');
      log('   Treating all assignments as non-overhead (safe fallback).', '#888');
      for (const id of recordIds) assignMap[id] = { name: '(unknown)', isOverhead: false };
    }

    // ── 4. Process each row ──────────────────────────────────────────────────
    for (let i = 0; i < rows.length; i++) {
      const row  = rows[i];
      const id   = row.dataset.id;
      const info = assignMap[id] ?? { name: '(not in API result)', isOverhead: false };
      const label = row.querySelector('[data-column-id="col-name"] a')?.textContent?.trim() ?? id;

      log('', '');
      log(`── ${i + 1}/${rows.length}: ${label}`, '#90CAF9');
      log(`   Assignment: "${info.name}"`, '#aaa');

      try {
        // Select this row via its checkbox (data-op-ignore="true" is the stable selector;
        // the id/name attributes are dynamic session values and must not be used)
        const chk = row.querySelector(
          '[data-column-id="ma_selection-column"] input[type="checkbox"][data-op-ignore="true"]'
        );
        if (chk) {
          if (!chk.checked) chk.click();
        } else {
          row.click(); // fallback: click the row itself
        }
        await sleep(700);

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

          // Confirm button: find the lightning-button host, then pierce its shadow for the real button
          const confirmHost = deepQuery(document, REJECT_DIALOG.confirmBtnHost);
          const submitBtn   = confirmHost?.shadowRoot?.querySelector(REJECT_DIALOG.confirmBtnInner);
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

          // Handle optional confirm dialog
          const confirmDlgBtn = deepQuery(document,
            '[role="dialog"] button[title="Approve"], [role="dialog"] footer button:last-child'
          );
          if (confirmDlgBtn) { confirmDlgBtn.click(); await sleep(1500); }

          approved++;
          log('   ✓ Approved.', '#69F0AE');
        }

        await sleep(800);

      } catch (err) {
        log(`   ❌ ${err.message}`, '#FF5252');
        errors++;
      }
    }

  } catch (err) {
    log(`\n❌ Fatal: ${err.message}`, '#FF5252');
  }

  // ── Summary ────────────────────────────────────────────────────────────────
  log('', '');
  log('────────────────────────────────────', '#2a4a2a');
  log(`✅ Approved : ${approved}`, '#69F0AE');
  log(`🚫 Rejected : ${rejected}`, '#FF7043');
  if (errors) log(`⚠️  Errors   : ${errors}  (see log above)`, '#FFCA28');
  log('Overlay closes in 15 s.', '#555');
  setTitle('⏱ Hours Approver — done');
  setTimeout(() => overlay?.remove(), 15000);
}

if (!window.__sfApproverRunning) {
  window.__sfApproverRunning = true;
  runApproval().finally(() => delete window.__sfApproverRunning);
}
