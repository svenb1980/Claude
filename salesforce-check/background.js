chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.action !== 'querySOQL') return;

  const tabId = sender.tab?.id;
  if (!tabId) { sendResponse({ error: 'no tab id' }); return true; }

  chrome.scripting.executeScript({
    target: { tabId },
    world:  'MAIN',
    args:   [msg.soql],
    func:   async (soql) => {
      const tryGet = fn => { try { const v = fn(); return v || null; } catch(e) { return null; } };

      // Search every known SF session ID location
      const sidSources = [
        ['sforce.connection',      () => window.sforce?.connection?.sessionId],
        ['sforce.one.getSid',      () => typeof window.sforce?.one?.getSid === 'function' ? window.sforce.one.getSid() : null],
        ['UserContext',            () => window.UserContext?.sessionId],
        ['SFDC._sessionId',        () => window.SFDC?._sessionId],
        ['Aura.context_.token',    () => window.Aura?.context_?.token],
        ['$A.getToken',            () => window.$A?.getToken?.()],
        ['$A.getContext.getToken', () => window.$A?.getContext?.()?.getToken?.()],
        ['inline JSON token',      () => {
          for (const s of document.querySelectorAll('script')) {
            const m = s.textContent?.match(/"token"\s*:\s*"([A-Za-z0-9!._\-]{20,})"/);
            if (m) return m[1];
          }
          return null;
        }],
        ['sessionStorage',         () => {
          for (let i = 0; i < sessionStorage.length; i++) {
            const k = sessionStorage.key(i) ?? '';
            if (/session|token|sid/i.test(k)) {
              const v = sessionStorage.getItem(k) ?? '';
              if (v.length > 15 && !v.startsWith('{')) return v;
            }
          }
          return null;
        }],
        ['document.cookie sid',    () => document.cookie.match(/(?:^|;)\s*sid=([^;]+)/)?.[1] ?? null],
      ];

      let sid = '';
      let sidSource = 'none';
      for (const [label, fn] of sidSources) {
        const v = tryGet(fn);
        if (v && typeof v === 'string' && v.length > 5) { sid = v; sidSource = label; break; }
      }

      const apiVer = window.Salesforce?.settings?.apiVersion ?? 'v59.0';
      const headers = { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' };
      if (sid) headers['Authorization'] = `Bearer ${sid}`;

      let url = `/services/data/${apiVer}/query/?q=${encodeURIComponent(soql)}`;
      const allRecords = [];
      while (url) {
        const res = await fetch(url, { headers });
        if (!res.ok) {
          const text = await res.text();
          return { error: `API ${res.status}: ${text.slice(0, 200)}`, sidSource };
        }
        const data = await res.json();
        allRecords.push(...(data.records ?? []));
        url = data.nextRecordsUrl ?? null;
      }
      return { records: allRecords, sidSource };
    },
  })
  .then(results => {
    const r = results?.[0]?.result;
    if (r?.error) sendResponse({ error: r.error, sidSource: r.sidSource });
    else          sendResponse({ records: r?.records ?? [], sidSource: r?.sidSource });
  })
  .catch(err => sendResponse({ error: err.message, sidSource: 'executeScript failed' }));

  return true;
});
