chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
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

    return true;
  }
});
