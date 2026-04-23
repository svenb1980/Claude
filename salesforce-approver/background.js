// Service worker — handles tab switching (content scripts can't use chrome.tabs directly)

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'switchToHoursTab') {
    chrome.tabs.query({}, tabs => {
      // Find the hours overview tab by title keywords
      const target = tabs.find(t =>
        t.title && /sven/i.test(t.title) && /hours/i.test(t.title)
      );
      if (target) {
        chrome.tabs.update(target.id, { active: true });
        chrome.windows.update(target.windowId, { focused: true });
        sendResponse({ found: true });
      } else {
        sendResponse({ found: false });
      }
    });
    return true; // keep channel open for async sendResponse
  }
});
