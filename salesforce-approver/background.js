// Service worker — handles privileged operations that content scripts cannot do:
//   • Reading HttpOnly cookies (session ID) — blocked by SF's CSP for inline scripts
//   • Opening new tabs — window.open() is blocked by popup blockers in content scripts

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  if (msg.action === 'getSessionId') {
    // Salesforce stores the session in the "sid" cookie on the Lightning domain
    chrome.cookies.get(
      { url: 'https://planonsoftware.lightning.force.com', name: 'sid' },
      cookie => {
        sendResponse({ sid: cookie?.value ?? '' });
      }
    );
    return true; // keep channel open for async sendResponse
  }

  if (msg.action === 'openTab') {
    chrome.tabs.create({ url: msg.url, active: true });
    sendResponse({ ok: true });
  }

});
