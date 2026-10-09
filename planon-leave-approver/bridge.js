// Draait in claude.ai-pagina's (alle frames). Blijft stil tot Cyberdeck hallo zegt en geeft dan de
// wachtende verlofrapporten door.
//
//   Cyberdeck → { source: 'action-desk', type: 'hello' }
//   bridge    → { source: 'leave-approver', type: 'reports', reports: [...] }
//   Cyberdeck → { source: 'action-desk', type: 'leave-ack', ids: [...] }   (na opslaan)
//   Cyberdeck → { source: 'action-desk', type: 'leave-run' }               (klik op een Planon-link)
//
// background.js duwt nieuwe rapporten ook direct hierheen zodra een run klaar is.

(() => {
  let deskHere = false; // alleen frames waar Cyberdeck hallo zei krijgen rapporten

  async function sendReports() {
    const { reports = [] } = await chrome.runtime.sendMessage({ action: 'bridgePending' }) || {};
    window.postMessage({ source: 'leave-approver', type: 'reports', reports }, '*');
  }

  async function onMessage(e) {
    if (e.source !== window || !e.data || e.data.source !== 'action-desk') return;
    // Na herladen van de extensie is deze kopie afgesloten: maak plaats voor de nieuwe.
    if (!chrome.runtime?.id) { window.removeEventListener('message', onMessage); return; }
    try {
      if (e.data.type === 'hello') { deskHere = true; await sendReports(); }
      if (e.data.type === 'leave-ack' && Array.isArray(e.data.ids)) {
        await chrome.runtime.sendMessage({ action: 'bridgeAck', ids: e.data.ids.map(String) });
      }
      if (e.data.type === 'leave-run') await chrome.runtime.sendMessage({ action: 'armRun' });
    } catch { /* extensie herladen tijdens de aanroep: de volgende hello bereikt de nieuwe kopie */ }
  }

  // Opnieuw ingevoegd bij een update: vervang de listener van de vorige kopie.
  if (window.__plvBridge) window.removeEventListener('message', window.__plvBridge);
  window.__plvBridge = onMessage;
  window.addEventListener('message', onMessage);

  chrome.runtime.onMessage.addListener(msg => {
    if (msg.action === 'pushReports' && deskHere) sendReports().catch(() => {});
  });
})();
