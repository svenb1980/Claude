const btn    = document.getElementById('checkBtn');
const status = document.getElementById('status');

function setStatus(msg, type = '') {
  status.textContent = msg;
  status.className   = type;
}

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
