// Runs a paginated SOQL query in the page's MAIN world so the browser
// automatically attaches the Salesforce session cookies to every fetch.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action !== 'querySOQL') return;

  const tabId = sender.tab?.id;
  if (!tabId) { sendResponse({ error: 'no tab id' }); return true; }

  chrome.scripting.executeScript({
    target: { tabId },
    world:  'MAIN',
    args:   [msg.soql],
    func:   async (soql) => {
      const apiVer  = window.Salesforce?.settings?.apiVersion ?? 'v59.0';
      const headers = { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' };
      let url = `/services/data/${apiVer}/query/?q=${encodeURIComponent(soql)}`;
      const allRecords = [];
      while (url) {
        const res = await fetch(url, { headers });
        if (!res.ok) {
          const text = await res.text();
          return { error: `API ${res.status}: ${text.slice(0, 200)}` };
        }
        const data = await res.json();
        allRecords.push(...(data.records ?? []));
        url = data.nextRecordsUrl ?? null;
      }
      return { records: allRecords };
    },
  })
  .then(results => {
    const r = results?.[0]?.result;
    if (r?.error) sendResponse({ error: r.error });
    else          sendResponse({ records: r?.records ?? [] });
  })
  .catch(err => sendResponse({ error: err.message }));

  return true; // keep channel open for async sendResponse
});
