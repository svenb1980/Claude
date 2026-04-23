// Service worker — handles privileged operations content scripts cannot do directly

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  // Read the Salesforce session ID by executing in the page's MAIN JS world.
  // chrome.scripting.executeScript with world:'MAIN' bypasses Salesforce's CSP
  // and has access to window.sforce and other Salesforce globals.
  if (msg.action === 'getSessionId') {
    const tabId = sender.tab?.id;
    if (!tabId) { sendResponse({ sid: '' }); return true; }

    chrome.scripting.executeScript({
      target: { tabId },
      world:  'MAIN',
      func: () => {
        try {
          return window.sforce?.connection?.sessionId
              || (typeof window.sforce?.one?.getSid === 'function' && window.sforce.one.getSid())
              || window.UserContext?.sessionId
              || window.SFDC?._sessionId
              || '';
        } catch (e) { return ''; }
      }
    })
    .then(results => sendResponse({ sid: results?.[0]?.result ?? '' }))
    .catch(err   => sendResponse({ sid: '', error: err.message }));

    return true; // keep channel open for async sendResponse
  }

  // Open a new tab (window.open() from content scripts is blocked by popup blockers)
  if (msg.action === 'openTab') {
    chrome.tabs.create({ url: msg.url, active: true });
    sendResponse({ ok: true });
  }

});
