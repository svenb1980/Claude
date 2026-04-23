// Service worker — opens a new tab on behalf of the content script
// (window.open() from content scripts is blocked by popup blockers)

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'openTab') {
    chrome.tabs.create({ url: msg.url, active: true });
    sendResponse({ ok: true });
  }
});
