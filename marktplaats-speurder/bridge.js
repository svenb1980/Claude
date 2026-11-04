// Runs inside claude.ai pages (all frames). It stays silent unless the Marktplaats Triage
// artifact says hello; then it passes judging jobs from the extension to that page and the
// page's verdicts back. The page asks Claude through the user's own subscription.
//
//   page   → { source: 'mp-triage', type: 'hello', ready, paused }   on load, every 30 s, on change
//   bridge → { source: 'mp-speurder', type: 'welcome' }
//   bridge → { source: 'mp-speurder', type: 'job', id, search, prompt, items }
//   page   → { source: 'mp-triage', type: 'verdicts', id, verdicts }
//   page   → { source: 'mp-triage', type: 'failed', id, code }

(() => {
  const answers = new Map(); // job id → sendResponse of the background's request

  function onMessage(e) {
    if (e.source !== window || !e.data || e.data.source !== 'mp-triage') return;
    // After an extension reload this copy is cut off from the extension: step aside.
    if (!chrome.runtime?.id) { window.removeEventListener('message', onMessage); return; }
    const d = e.data;
    if (d.type === 'hello') {
      chrome.runtime.sendMessage({ type: 'triagePage', ready: !!d.ready, paused: !!d.paused }).catch(() => {});
      window.postMessage({ source: 'mp-speurder', type: 'welcome' }, '*');
    } else if ((d.type === 'verdicts' || d.type === 'failed') && answers.has(d.id)) {
      answers.get(d.id)(d);
      answers.delete(d.id);
    }
  }

  // Injected again on extension update: replace the previous copy's listener.
  if (window.__mpSpeurderBridge) window.removeEventListener('message', window.__mpSpeurderBridge);
  window.__mpSpeurderBridge = onMessage;
  window.addEventListener('message', onMessage);

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (msg?.type !== 'triageJob') return;
    answers.set(msg.job.id, sendResponse);
    window.postMessage({ source: 'mp-speurder', type: 'job', ...msg.job }, '*');
    return true; // the page answers later
  });
})();
