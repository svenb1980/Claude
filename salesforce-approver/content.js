// ── Utilities ──────────────────────────────────────────────────────────────────

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Recursively pierce Salesforce Shadow DOM (LWC uses shadow roots everywhere)
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
        reject(new Error(`Timeout waiting for selector: ${selector}`));
      }
    }, 300);
  });
}

// Trigger React/LWC-style input events so Salesforce registers the value change
function setNativeValue(el, value) {
  const nativeInput = Object.getOwnPropertyDescriptor(
    el.tagName === 'TEXTAREA'
      ? window.HTMLTextAreaElement.prototype
      : window.HTMLInputElement.prototype,
    'value'
  );
  nativeInput.set.call(el, value);
  el.dispatchEvent(new Event('input',  { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
}

// ── Status Overlay ─────────────────────────────────────────────────────────────

let overlay, logEl;

function createOverlay() {
  // Remove any previous overlay from a prior run
  document.getElementById('__sf-approver-overlay')?.remove();

  overlay = document.createElement('div');
  overlay.id = '__sf-approver-overlay';
  overlay.style.cssText = [
    'position:fixed', 'top:16px', 'right:16px', 'z-index:2147483647',
    'background:#1a1a2e', 'color:#eee', 'font:13px/1.6 monospace',
    'border-radius:10px', 'padding:16px 20px', 'width:400px',
    'box-shadow:0 8px 32px rgba(0,0,0,.6)', 'border:1px solid #333',
    'max-height:75vh', 'overflow-y:auto'
  ].join(';');

  const title = document.createElement('div');
  title.style.cssText = 'font-size:15px;font-weight:700;margin-bottom:10px;color:#69F0AE';
  title.textContent = '⏱ Hours Approver — running…';

  const closeBtn = document.createElement('button');
  closeBtn.textContent = '✕';
  closeBtn.style.cssText = 'float:right;background:none;border:none;color:#888;cursor:pointer;font-size:14px;margin-top:-2px';
  closeBtn.onclick = () => overlay.remove();

  title.prepend(closeBtn);
  overlay.appendChild(title);

  logEl = document.createElement('div');
  overlay.appendChild(logEl);
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

function setTitle(text) {
  const t = overlay?.querySelector('div');
  if (t) t.childNodes[t.childNodes.length - 1].textContent = ' ' + text;
}

// ── ⚠️  SELECTORS — edit these if automation can't find elements ───────────────
//
// How to find the right selectors:
//   1. Open the Mass Approval page in Chrome
//   2. Press F12 → open DevTools
//   3. Click the "Select element" cursor (top-left of DevTools)
//   4. Click the element you want to target
//   5. In the Elements panel, right-click the highlighted node
//      → Copy → Copy selector  (or Copy JS path)
//   6. Paste that value into the relevant selector below
//
// Note: Salesforce uses Shadow DOM. If "Copy selector" gives you something like
//       "c-mass-approval >>> table >>> tr", the ">>>" means cross-shadow.
//       You may need to split that across multiple deepQuery() calls.

const SEL = {
  // Table rows in the Primary Approval Requests list
  // Common patterns: 'tr[data-row-key]', 'tbody tr', 'lightning-datatable tr'
  tableRow: 'tr[data-row-key], tbody tr',

  // A link or button inside a row to open the timecard detail
  rowLink: 'a[data-label], a[href], button[title]',

  // Assignment field on the detail page
  // Common: '[data-field="Assignment__c"]', '[data-label="Assignment"]'
  assignmentField: '[data-field="Assignment__c"], [data-label="Assignment"], .assignment-field',

  // Approve button on the detail page
  approveBtn: 'button[title="Approve"], button[name="approve"], button[label="Approve"]',

  // Reject button on the detail page
  rejectBtn: 'button[title="Reject"], button[name="reject"], button[label="Reject"]',

  // Comment textarea inside the reject modal/dialog
  commentArea: 'lightning-textarea textarea, textarea[placeholder], [role="dialog"] textarea',

  // Submit/Confirm button inside the reject modal
  confirmBtn: 'button[title="Submit"], button[title="Confirm"], [role="dialog"] button[type="submit"], footer button:last-child',

  // Approve confirm button (some approval flows show a confirm dialog)
  approveConfirmBtn: '[role="dialog"] button[title="Approve"], [role="dialog"] footer button:last-child',
};

// ── Main Automation ────────────────────────────────────────────────────────────

const REJECTION_COMMENT =
  'Rejected: Overhead assignments are not allowed. Please resubmit with a valid project assignment.';

async function runApproval() {
  createOverlay();
  log('Waiting for the page to settle…', '#888');
  await sleep(3000);

  let approved = 0, rejected = 0, errors = 0;

  try {
    // ── Find approval rows ───────────────────────────────────────────────────
    let rows = deepQueryAll(document, SEL.tableRow)
      .filter(r => r.querySelectorAll('td').length > 0);

    log(`Found ${rows.length} approval row(s).`, '#90CAF9');

    if (rows.length === 0) {
      log('', '#888');
      log('⚠️  No rows found. Possible reasons:', '#FFCA28');
      log('   • No pending approvals right now', '#888');
      log('   • Selectors need updating — see SEL.tableRow in content.js', '#888');
      log('   • Page still loading — try clicking the button again', '#888');
      return;
    }

    // ── Process each row ─────────────────────────────────────────────────────
    for (let i = 0; i < rows.length; i++) {
      log('', '#444');
      log(`── Row ${i + 1} / ${rows.length} ──────────────────────`, '#555');

      try {
        // Open the timecard
        const link = rows[i].querySelector(SEL.rowLink) || rows[i];
        link.click();
        log('  Opened timecard…', '#888');
        await sleep(2500);

        // Read Assignment field
        const assignEl = deepQuery(document, SEL.assignmentField);
        const assignText = (assignEl?.textContent || assignEl?.value || '').trim();
        log(`  Assignment: "${assignText || '(not found)'}"`, '#ccc');

        if (!assignEl) {
          log('  ⚠️  Assignment field not found — check SEL.assignmentField', '#FFCA28');
        }

        const isOverhead = /overhead/i.test(assignText);

        if (isOverhead) {
          // ── Reject ──
          log('  🚫 Overhead — rejecting…', '#FF5252');

          const rejectBtn = deepQuery(document, SEL.rejectBtn);
          if (!rejectBtn) throw new Error('Reject button not found — check SEL.rejectBtn');
          rejectBtn.click();
          await sleep(1200);

          const textarea = await waitForEl(SEL.commentArea, 8000);
          textarea.focus();
          setNativeValue(textarea, REJECTION_COMMENT);
          await sleep(400);

          const confirmBtn = deepQuery(document, SEL.confirmBtn);
          if (!confirmBtn) throw new Error('Confirm/Submit button not found in reject dialog — check SEL.confirmBtn');
          confirmBtn.click();
          await sleep(2000);

          rejected++;
          log('  ✓ Rejected.', '#FF5252');

        } else {
          // ── Approve ──
          log('  ✅ Approving…', '#69F0AE');

          const approveBtn = deepQuery(document, SEL.approveBtn);
          if (!approveBtn) throw new Error('Approve button not found — check SEL.approveBtn');
          approveBtn.click();
          await sleep(1200);

          // Confirm dialog (not always present)
          const confirmBtn = deepQuery(document, SEL.approveConfirmBtn);
          if (confirmBtn) {
            confirmBtn.click();
            await sleep(1500);
          }

          approved++;
          log('  ✓ Approved.', '#69F0AE');
        }

        await sleep(1200);

        // Re-query rows — SF may have re-rendered the list
        rows = deepQueryAll(document, SEL.tableRow)
          .filter(r => r.querySelectorAll('td').length > 0);

      } catch (err) {
        log(`  ❌ ${err.message}`, '#FF5252');
        errors++;
        // Try to get back to the list
        history.back();
        await sleep(2500);
        rows = deepQueryAll(document, SEL.tableRow)
          .filter(r => r.querySelectorAll('td').length > 0);
      }
    }

  } catch (err) {
    log(`\n❌ Fatal: ${err.message}`, '#FF5252');
  }

  // ── Summary ──────────────────────────────────────────────────────────────
  log('', '#444');
  log('────────────────────────────────────', '#333');
  log(`✅ Approved : ${approved}`, '#69F0AE');
  log(`🚫 Rejected : ${rejected}`, '#FF5252');
  if (errors) log(`⚠️  Errors   : ${errors}`, '#FFCA28');
  log('', '#444');
  log('Done. This overlay closes in 15 seconds.', '#555');
  setTitle('Hours Approver — done');
  setTimeout(() => overlay?.remove(), 15000);
}

// Guard against double-injection
if (!window.__sfApproverRunning) {
  window.__sfApproverRunning = true;
  runApproval().finally(() => delete window.__sfApproverRunning);
}
