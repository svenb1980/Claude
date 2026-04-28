const SF_BASE = 'https://planonsoftware.lightning.force.com';

const btn    = document.getElementById('checkBtn');
const status = document.getElementById('status');

function setStatus(msg, type = '') {
  status.textContent = msg;
  status.className   = type;
}

btn.addEventListener('click', async () => {
  btn.disabled = true;
  setStatus('Checking…');

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const onSF  = tab.url && tab.url.includes('.lightning.force.com');

    if (!onSF) {
      setStatus('Navigating to Salesforce…');
      await chrome.tabs.update(tab.id, { url: SF_BASE });

      await new Promise(resolve => {
        chrome.tabs.onUpdated.addListener(function listener(tabId, info) {
          if (tabId === tab.id && info.status === 'complete') {
            chrome.tabs.onUpdated.removeListener(listener);
            resolve();
          }
        });
      });

      await new Promise(r => setTimeout(r, 4000));
    }

    setStatus('Running check…');

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
