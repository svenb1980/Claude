chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'getSessionId') {
    const tabId = sender.tab?.id;
    if (!tabId) { sendResponse({ sid: '' }); return true; }

    // Try MAIN world globals first (works when sforce/UserContext are initialised)
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
    .then(async results => {
      const sid = results?.[0]?.result ?? '';
      if (sid) { sendResponse({ sid }); return; }

      // Fall back to the sid cookie (set by Salesforce on the lightning domain)
      const cookies = await chrome.cookies.getAll({
        domain: 'planonsoftware.lightning.force.com',
        name:   'sid',
      });
      sendResponse({ sid: cookies?.[0]?.value ?? '' });
    })
    .catch(async () => {
      try {
        const cookies = await chrome.cookies.getAll({
          domain: 'planonsoftware.lightning.force.com',
          name:   'sid',
        });
        sendResponse({ sid: cookies?.[0]?.value ?? '' });
      } catch {
        sendResponse({ sid: '' });
      }
    });

    return true;
  }
});
