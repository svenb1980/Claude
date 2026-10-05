// Service worker — handles privileged operations content scripts cannot do directly.
//
// Why the REST API calls live here instead of in content.js:
//  1. The "sid" cookie set on *.lightning.force.com is a Lightning-only session and
//     is rejected by /services/data with INVALID_SESSION_ID. The API session is the
//     "sid" cookie on the org's instance domain (*.my.salesforce.com).
//  2. Calling the instance domain from a content script is a cross-origin request and
//     Salesforce does not send CORS headers unless the origin is whitelisted in Setup.
//     Fetches made from an extension service worker with matching host_permissions
//     bypass CORS entirely, so the request succeeds.

const DEFAULT_API_VERSION = 'v59.0';

// myorg.lightning.force.com → myorg.my.salesforce.com
function toInstanceHost(host) {
  const suffix = '.lightning.force.com';
  return host.endsWith(suffix)
    ? host.slice(0, -suffix.length) + '.my.salesforce.com'
    : host;
}

// Locate the API session: the "sid" cookie on the org's instance domain.
async function getApiSession(tabUrl) {
  const pageHost  = new URL(tabUrl).hostname;
  const orgPrefix = pageHost.split('.')[0];

  const instanceUrl = `https://${toInstanceHost(pageHost)}`;
  const direct = await chrome.cookies.get({ url: instanceUrl, name: 'sid' });
  if (direct?.value) return { instanceUrl, sid: direct.value };

  // Fallback: scan every "sid" cookie and pick one on a Salesforce instance domain
  // belonging to the same org (covers sandboxes and enhanced-domain variants).
  const all        = await chrome.cookies.getAll({ name: 'sid' });
  const candidates = all.filter(c => c.domain.includes('salesforce.com'));
  const match      = candidates.find(c => c.domain.includes(orgPrefix)) ?? candidates[0];
  if (!match) return null;

  return {
    instanceUrl: `https://${match.domain.replace(/^\./, '')}`,
    sid:         match.value,
  };
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {

  // Run a SOQL query against the Salesforce REST API on the org's instance domain.
  if (msg.action === 'soqlQuery') {
    (async () => {
      const tabUrl = sender.tab?.url;
      if (!tabUrl) return sendResponse({ error: 'No sender tab URL available.' });

      const session = await getApiSession(tabUrl);
      if (!session) {
        return sendResponse({
          error: 'No Salesforce API session cookie found. Open the org\'s ' +
                 'my.salesforce.com domain once in this browser profile, then retry.',
        });
      }

      const version = msg.apiVersion || DEFAULT_API_VERSION;
      const url = `${session.instanceUrl}/services/data/${version}/query/`
                + `?q=${encodeURIComponent(msg.soql)}`;

      const res = await fetch(url, {
        headers: {
          'Authorization': `Bearer ${session.sid}`,
          'Accept':        'application/json',
        },
      });

      if (!res.ok) {
        return sendResponse({ error: `API ${res.status}: ${(await res.text()).slice(0, 200)}` });
      }

      sendResponse({ data: await res.json() });
    })().catch(err => sendResponse({ error: err.message }));

    return true; // keep channel open for async sendResponse
  }

  // Open a new tab (window.open() from content scripts is blocked by popup blockers)
  if (msg.action === 'openTab') {
    chrome.tabs.create({ url: msg.url, active: true });
    sendResponse({ ok: true });
  }

});

