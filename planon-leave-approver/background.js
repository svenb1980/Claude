// Service worker: bewaart de rapporten van elke run tot Cyberdeck ze heeft opgeslagen, en geeft ze
// via bridge.js door aan open claude.ai-tabbladen.

const bridgePages = () =>
  chrome.runtime.getManifest().content_scripts.find(c => c.js.includes('bridge.js'))?.matches || [];

// Chrome voegt manifest-content-scripts alleen toe aan pagina's die na installatie/update openen:
// zet de bridge in claude.ai-tabbladen die al open staan, zodat Cyberdeck niet herladen hoeft.
chrome.runtime.onInstalled.addListener(async () => {
  for (const tab of await chrome.tabs.query({ url: bridgePages() })) {
    chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ['bridge.js'] }).catch(() => {});
  }
});

async function pushToCyberdeck() {
  for (const tab of await chrome.tabs.query({ url: bridgePages() })) {
    chrome.tabs.sendMessage(tab.id, { action: 'pushReports' }).catch(() => {});
  }
}

// Eén wijziging tegelijk aan de wachtlijst: een rapport dat binnenkomt terwijl een ack wordt verwerkt
// mag niet verloren gaan (beide lezen de lijst, passen hem aan en schrijven hem terug).
let pendingChain = Promise.resolve();
const withPending = fn => (pendingChain = pendingChain.then(fn, fn));

async function pendingReports() {
  const { pending = [] } = await chrome.storage.local.get('pending');
  return pending;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action === 'saveReport') {
    withPending(async () => {
      const pending = (await pendingReports()).filter(r => r.id !== msg.report.id);
      pending.push(msg.report);
      await chrome.storage.local.set({ pending: pending.slice(-20) });
      sendResponse({ ok: true });
      pushToCyberdeck();
    });
    return true;
  }

  if (msg.action === 'bridgePending') {
    pendingReports().then(reports => sendResponse({ reports }));
    return true;
  }

  if (msg.action === 'bridgeAck') {
    withPending(async () => {
      const ids = new Set(msg.ids || []);
      const pending = (await pendingReports()).filter(r => !ids.has(r.id));
      await chrome.storage.local.set({ pending, lastDelivered: Date.now() });
      sendResponse({ ok: true });
    });
    return true;
  }

  // Klik op een Planon-link in Cyberdeck: de eerstvolgende lijst die opent draait ook als automatisch starten uit staat.
  if (msg.action === 'armRun') {
    chrome.storage.local.set({ plvArmed: Date.now() }).then(() => sendResponse({ ok: true }));
    return true;
  }
});
