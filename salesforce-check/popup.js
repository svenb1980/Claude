const btn       = document.getElementById('checkBtn');
const status    = document.getElementById('status');
const logSection = document.getElementById('logSection');
const logOutput  = document.getElementById('logOutput');
const clearLog   = document.getElementById('clearLog');

function setStatus(msg, type = '') {
  status.textContent = msg;
  status.className   = type;
}

function showLog(text) {
  if (!text) return;
  logOutput.value = text;
  logSection.style.display = 'block';
  logOutput.scrollTop = logOutput.scrollHeight;
}

// Show last run log when popup opens
chrome.storage.local.get('sfCheckerLog', ({ sfCheckerLog }) => {
  showLog(sfCheckerLog);
});

clearLog.addEventListener('click', () => {
  chrome.storage.local.remove('sfCheckerLog');
  logSection.style.display = 'none';
  logOutput.value = '';
});

btn.addEventListener('click', async () => {
  btn.disabled = true;
  setStatus('Running check…');

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

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
