const TARGET_URL = 'https://planonsoftware.lightning.force.com/lightning/n/Mass_Approval_Lightning_Component';

const btn    = document.getElementById('approveBtn');
const status = document.getElementById('status');

const autoRun    = document.getElementById('autoRun');
const deskStatus = document.getElementById('deskStatus');

chrome.storage.local.get(['autoRun', 'pending', 'lastDelivered']).then(({ autoRun: on = true, pending = [], lastDelivered }) => {
  autoRun.checked = on;
  const when = lastDelivered ? new Date(lastDelivered).toLocaleString() : 'never';
  deskStatus.textContent = pending.length
    ? `${pending.length} report(s) waiting for Action Desk — open it in this browser. Last delivered: ${when}.`
    : `Action Desk is up to date. Last delivered: ${when}.`;
});
autoRun.addEventListener('change', () => chrome.storage.local.set({ autoRun: autoRun.checked }));

function setStatus(msg, type = '') {
  status.textContent = msg;
  status.className   = type;
}

btn.addEventListener('click', async () => {
  btn.disabled = true;
  setStatus('Opening Salesforce…');

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const onTarget = tab.url && tab.url.includes('Mass_Approval_Lightning_Component');

    if (!onTarget) {
      // Navigate to the Mass Approval page (works from any tab, including other SF pages)
      setStatus('Navigating to Mass Approval…');
      await chrome.tabs.update(tab.id, { url: TARGET_URL });

      // Wait for the tab to finish loading
      await new Promise(resolve => {
        chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
          if (tabId === tab.id && info.status === 'complete') {
            chrome.tabs.onUpdated.removeListener(listener);
            resolve();
          }
        });
      });

      // With auto-run on, background.js starts the automation once the page is up
      if (autoRun.checked) {
        setStatus('Running — check the page overlay.', 'ok');
        setTimeout(() => window.close(), 2000);
        return;
      }

      // Extra wait for Lightning framework and LWC components to boot
      await new Promise(r => setTimeout(r, 4000));
    }

    setStatus('Running automation…');

    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      files:  ['content.js']
    });

    setStatus('Running — check the page overlay.', 'ok');
    setTimeout(() => window.close(), 2000);

  } catch (err) {
    setStatus(`Error: ${err.message}`, 'error');
    btn.disabled = false;
  }
});
