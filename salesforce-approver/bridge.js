// Runs inside claude.ai pages (all frames). It stays silent unless the Action Desk
// artifact says hello, then hands over the approval reports waiting in the extension.
//
//   Action Desk → { source: 'action-desk', type: 'hello' }
//   bridge      → { source: 'sf-approver', type: 'reports', reports: [...] }
//   Action Desk → { source: 'action-desk', type: 'ack', ids: [...] }   (after storing them)

if (!window.__sfApproverBridge) {
window.__sfApproverBridge = true; // injected again on extension update: listen once

window.addEventListener('message', async e => {
  if (e.source !== window || !e.data || e.data.source !== 'action-desk') return;

  try {
    if (e.data.type === 'hello') {
      const { reports = [] } = await chrome.runtime.sendMessage({ action: 'bridgePending' }) || {};
      window.postMessage({ source: 'sf-approver', type: 'reports', reports }, '*');
    }
    if (e.data.type === 'ack' && Array.isArray(e.data.ids)) {
      await chrome.runtime.sendMessage({ action: 'bridgeAck', ids: e.data.ids.map(String) });
    }
  } catch { /* extension reloaded: this page needs a refresh to reconnect */ }
});
}
