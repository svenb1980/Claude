// ── Utilities ──────────────────────────────────────────────────────────────────

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Generic recursive shadow DOM query (used for detail pages)
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

// Wait for a selector to appear anywhere in the document (including shadow DOM)
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

// Trigger LWC-compatible value change (plain .value = x is ignored by framework)
function setNativeValue(el, value) {
  const proto = el.tagName === 'TEXTAREA'
    ? window.HTMLTextAreaElement.prototype
    : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, value);
  el.dispatchEvent(new Event('input',  { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

// ── Bryntum Grid: shadow DOM traversal ────────────────────────────────────────
//
// The grid lives 6 shadow roots deep. All are open mode, so we can traverse.
// Chain: document
//   → app_flexipage-lwc-app-flexipage            (shadow)
//   → app_flexipage-lwc-app-flexipage-internal   (shadow)
//   → forcegenerated-flexipage_mass_approval_lightning_component__js (shadow)
//   → pse-ma_mass-approval                       (shadow)
//   → c-ma_mass-approval-grid                    (shadow)
//   → c-bryntum-widget-host                      (shadow) ← grid lives here

const SHADOW_CHAIN = [
  'app_flexipage-lwc-app-flexipage',
  'app_flexipage-lwc-app-flexipage-internal',
  'forcegenerated-flexipage_mass_approval_lightning_component__js',
  'pse-ma_mass-approval',
  'c-ma_mass-approval-grid',
  'c-bryntum-widget-host',
];

function getBryntumRoot() {
  let root = document;
  for (const tag of SHADOW_CHAIN) {
    const el = root.querySelector(tag);
    if (!el) return null;
    root = el.shadowRoot ?? el;
  }
  return root;
}

// ── Grid selectors (inside c-bryntum-widget-host shadow root) ─────────────────

const GRID = {
  // Confirm grid is loaded
  container: '.b-gridbase, #b-grid-2',
  // Each approval row
  row:       '.b-grid-row[role="row"][data-id]',
  // Link to the timecard record inside a row
  rowLink:   '[data-column-id="col-name"] a[href*="/lightning/r/"]',
};

// ── Detail page selectors (standard SF Lightning record page) ─────────────────
// ⚠️  If any of these don't match, inspect the timecard detail page in DevTools
//    and update the selector. The key ones are: assignmentField, approveBtn, rejectBtn.

const SEL = {
  // Assignment field — try these in order; first match wins
  assignmentField: [
    '[data-field="Assignment__c"]',
    '[data-label="Assignment"]',
    '.assignment-field',
    'records-hoverable-link[data-field-name="Assignment__c"]',
    '[field-name="Assignment__c"]',
  ].join(', '),

  // Approve/Reject buttons on the record page (highlights panel or action bar)
  approveBtn: [
    'button[title="Approve"]',
    'button[name="approve"]',
    'button[label="Approve"]',
    'a[title="Approve"]',
  ].join(', '),

  rejectBtn: [
    'button[title="Reject"]',
    'button[name="reject"]',
    'button[label="Reject"]',
    'a[title="Reject"]',
  ].join(', '),

  // Comment textarea inside the reject modal
  commentArea: 'lightning-textarea textarea, [role="dialog"] textarea, textarea[placeholder]',

  // Submit button inside reject modal
  confirmBtn: [
    '[role="dialog"] button[title="Submit"]',
    '[role="dialog"] button[title="Confirm"]',
    '[role="dialog"] footer button:last-child',
    'button[title="Submit"]',
  ].join(', '),

  // Confirm for approve (some flows show a confirmation dialog)
  approveConfirm: [
    '[role="dialog"] button[title="Approve"]',
    '[role="dialog"] footer button:last-child',
  ].join(', '),
};

// ── Status Overlay ─────────────────────────────────────────────────────────────

let overlay, logEl;

function createOverlay() {
  document.getElementById('__sf-approver-overlay')?.remove();

  overlay = document.createElement('div');
  overlay.id = '__sf-approver-overlay';
  overlay.style.cssText = [
    'position:fixed', 'top:16px', 'right:16px', 'z-index:2147483647',
    'background:#0f1b0f', 'color:#ccc', 'font:13px/1.6 monospace',
    'border-radius:10px', 'padding:16px 20px', 'width:420px',
    'box-shadow:0 8px 32px rgba(0,0,0,.7)', 'border:1px solid #2a4a2a',
    'max-height:78vh', 'overflow-y:auto',
  ].join(';');

  const header = document.createElement('div');
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:12px';

  const title = document.createElement('span');
  title.id = '__sf-approver-title';
  title.style.cssText = 'font-size:14px;font-weight:700;color:#69F0AE';
  title.textContent = '⏱ Hours Approver — running…';

  const closeBtn = document.createElement('button');
  closeBtn.textContent = '✕';
  closeBtn.style.cssText = 'background:none;border:none;color:#666;cursor:pointer;font-size:14px;padding:0 4px';
  closeBtn.onclick = () => overlay.remove();

  header.append(title, closeBtn);
  logEl = document.createElement('div');
  overlay.append(header, logEl);
  document.body.appendChild(overlay);
}

function log(msg, color = '#ccc') {
  if (!logEl) return;
  const line = document.createElement('div');
  line.style.cssText = `color:${color};margin-bottom:2px;word-break:break-word`;
  line.textContent = msg;
  logEl.appendChild(line);
  overlay.scrollTop = overlay.scrollHeight;
}

function setOverlayTitle(text) {
  const t = document.getElementById('__sf-approver-title');
  if (t) t.textContent = text;
}

// ── Main ───────────────────────────────────────────────────────────────────────

const REJECTION_COMMENT =
  'Rejected: Overhead assignments are not allowed. Please resubmit with a valid project assignment.';

async function runApproval() {
  createOverlay();
  log('Waiting for grid to load…', '#666');
  await sleep(3000);

  let approved = 0, rejected = 0, errors = 0;

  try {
    // ── Locate the Bryntum grid ──────────────────────────────────────────────
    const bryntumRoot = getBryntumRoot();

    if (!bryntumRoot) {
      log('❌ Could not find the Bryntum grid shadow root.', '#FF5252');
      log('   The LWC shadow chain may have changed. Check SHADOW_CHAIN in content.js.', '#888');
      return;
    }

    const gridEl = bryntumRoot.querySelector(GRID.container);
    if (!gridEl) {
      log('❌ Grid container not found inside c-bryntum-widget-host.', '#FF5252');
      log('   Expected selector: ' + GRID.container, '#888');
      return;
    }

    log('✓ Grid found.', '#69F0AE');

    // ── Collect all rows ─────────────────────────────────────────────────────
    let rows = Array.from(bryntumRoot.querySelectorAll(GRID.row));
    log(`Found ${rows.length} approval row(s).`, '#90CAF9');

    if (rows.length === 0) {
      log('', '');
      log('⚠️  No rows found inside the grid.', '#FFCA28');
      log('   If approvals are present, check GRID.row in content.js.', '#888');
      log('   Current selector: ' + GRID.row, '#555');
      return;
    }

    // Collect record IDs and links upfront (DOM may change after navigation)
    const items = rows.map(row => {
      const link = row.querySelector(GRID.rowLink);
      return {
        id:   row.dataset.id,
        href: link?.href,
        name: link?.textContent?.trim() ?? row.dataset.id,
      };
    }).filter(item => item.href);

    log(`Processing ${items.length} timecard(s)…`, '#aaa');

    // ── Process each timecard ────────────────────────────────────────────────
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      log('', '');
      log(`── ${i + 1}/${items.length}: ${item.name}`, '#90CAF9');

      try {
        // Navigate to the timecard detail page
        window.location.href = item.href;
        await sleep(4000); // wait for page load + LWC boot

        // Read Assignment field
        const assignEl = deepQuery(document, SEL.assignmentField);
        const assignText = (assignEl?.textContent || assignEl?.value || '').trim();
        log(`   Assignment: "${assignText || '(field not found — check SEL.assignmentField)'}"`,
          assignEl ? '#ccc' : '#FFCA28');

        const isOverhead = /overhead/i.test(assignText);

        if (isOverhead) {
          // ── Reject ──────────────────────────────────────────────────────
          log('   🚫 Overhead — rejecting…', '#FF7043');

          const rejectBtn = deepQuery(document, SEL.rejectBtn);
          if (!rejectBtn) throw new Error('Reject button not found. Check SEL.rejectBtn.');
          rejectBtn.click();
          await sleep(1500);

          const textarea = await waitForEl(SEL.commentArea, 8000);
          textarea.focus();
          setNativeValue(textarea, REJECTION_COMMENT);
          await sleep(500);

          const confirmBtn = deepQuery(document, SEL.confirmBtn);
          if (!confirmBtn) throw new Error('Submit button not found in reject dialog. Check SEL.confirmBtn.');
          confirmBtn.click();
          await sleep(2500);

          rejected++;
          log('   ✓ Rejected.', '#FF7043');

        } else {
          // ── Approve ─────────────────────────────────────────────────────
          log('   ✅ Approving…', '#69F0AE');

          const approveBtn = deepQuery(document, SEL.approveBtn);
          if (!approveBtn) throw new Error('Approve button not found. Check SEL.approveBtn.');
          approveBtn.click();
          await sleep(1500);

          // Confirm dialog (not always present)
          const confirmBtn = deepQuery(document, SEL.approveConfirm);
          if (confirmBtn) { confirmBtn.click(); await sleep(1500); }

          approved++;
          log('   ✓ Approved.', '#69F0AE');
        }

        // Navigate back to the Mass Approval list for the next row
        window.location.href =
          'https://planonsoftware.lightning.force.com/lightning/n/Mass_Approval_Lightning_Component';
        await sleep(4000);

      } catch (err) {
        log(`   ❌ ${err.message}`, '#FF5252');
        errors++;
        // Best-effort: return to list
        window.location.href =
          'https://planonsoftware.lightning.force.com/lightning/n/Mass_Approval_Lightning_Component';
        await sleep(4000);
      }
    }

  } catch (err) {
    log(`\n❌ Fatal: ${err.message}`, '#FF5252');
  }

  // ── Summary ──────────────────────────────────────────────────────────────
  log('', '');
  log('────────────────────────────────────', '#2a4a2a');
  log(`✅ Approved : ${approved}`, '#69F0AE');
  log(`🚫 Rejected : ${rejected}`, '#FF7043');
  if (errors) log(`⚠️  Errors   : ${errors}  (check log above)`, '#FFCA28');
  log('Done. Overlay closes in 15 seconds.', '#555');
  setOverlayTitle('⏱ Hours Approver — done');
  setTimeout(() => overlay?.remove(), 15000);
}

if (!window.__sfApproverRunning) {
  window.__sfApproverRunning = true;
  runApproval().finally(() => delete window.__sfApproverRunning);
}
