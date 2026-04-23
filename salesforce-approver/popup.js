const TARGET_URL = 'https://planonsoftware.lightning.force.com/lightning/n/Mass_Approval_Lightning_Component';

const btn    = document.getElementById('approveBtn');
const status = document.getElementById('status');

function setStatus(msg, type = '') {
  status.textContent = msg;
  status.className   = type;
}

btn.addEventListener('click', async () => {
  btn.disabled = true;
  setStatus('Opening Salesforce…');

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const onTarget = tab.url && tab.url.startsWith('https://planonsoftware.lightning.force.com');

    if (!onTarget) {
      // Navigate the current tab to the Mass Approval page
      await chrome.tabs.update(tab.id, { url: TARGET_URL });

      // Wait for the tab to finish loading before injecting
      await new Promise(resolve => {
        chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
          if (tabId === tab.id && info.status === 'complete') {
            chrome.tabs.onUpdated.removeListener(listener);
            resolve();
          }
        });
      });

      // Extra wait for Lightning framework to boot
      await new Promise(r => setTimeout(r, 3000));
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
