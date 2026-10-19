// Service worker: checks every active search on a timer, remembers which listings it
// has already seen, and reports new ones (popup list, badge, desktop notification).
//
// Storage (chrome.storage.local):
//   watches   – the searches, edited on the options page
//   settings  – interval and notification settings (see DEFAULT_SETTINGS)
//   state     – per search: key (search fingerprint), seen ids, highest listing number
//               (maxId), last (successful) check, last error, counts for the status line
//   finds     – new listings, newest first, each with the searches that found it;
//               only written here
//   readUntil – listings found after this time count as unread; only written by the popup

import {
  DEFAULT_SETTINGS, ID_MARGIN, fetchListings, rejectReason, gateDay, searchKey, formatPrice, formatDistance, watchLabel,
} from './lib.js';

const ALARM = 'check';
const SEEN_MAX = 2000;   // ids remembered per search
const FINDS_MAX = 300;   // listings kept in the popup
const ICON = 'icons/icon128.png';

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function getSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  return { ...DEFAULT_SETTINGS, ...settings };
}

async function ensureAlarm() {
  const { intervalMin } = await getSettings();
  const alarm = await chrome.alarms.get(ALARM);
  if (alarm?.periodInMinutes === intervalMin) return;
  await chrome.alarms.create(ALARM, {
    periodInMinutes: intervalMin,
    delayInMinutes: alarm ? intervalMin : 0.5,
  });
}

// Serialises every read-modify-write of state and finds.
let lock = Promise.resolve();
function locked(fn) {
  const run = lock.then(fn, fn);
  lock = run.catch(() => {});
  return run;
}

// A check requested while one is running (e.g. a search was just saved) runs once more
// afterwards, so it sees the latest searches.
let running = null;
let again = false;
function checkAll() {
  if (running) { again = true; return running; }
  running = (async () => {
    do { again = false; await locked(doCheckAll); } while (again);
  })().finally(() => { running = null; });
  return running;
}

async function doCheckAll() {
  const { watches = [], state = {}, finds = [] } = await chrome.storage.local.get(['watches', 'state', 'finds']);
  const settings = await getSettings();

  for (const id of Object.keys(state)) {
    if (!watches.some(w => w.id === id)) delete state[id];
  }

  const active = watches.filter(w => w.active);
  for (const [i, w] of active.entries()) {
    if (i > 0) await sleep(1500); // be gentle on Marktplaats

    const key = searchKey(w);
    const st = state[w.id]?.key === key ? state[w.id] : { key, seen: [], maxId: null, baselineAt: null, lastOkAt: null };
    st.lastCheck = Date.now();

    try {
      const now = Date.now();
      const baseline = !st.baselineAt;
      const gate = baseline ? null : gateDay(st.lastOkAt, now);
      // The baseline records the highest listing number, paging past the dagtoppers on
      // top until it has seen ordinary listings. Later checks ask Marktplaats for listings
      // offered since the gate day and page on until they reach an already known one.
      const res = await fetchListings(w, baseline ? { minOrganic: 1 } : { since: gate, stopAt: st.maxId });
      const { listings } = res;

      const seen = new Set(st.seen);
      const minId = st.maxId !== null ? st.maxId - ID_MARGIN : null;
      const stats = {
        rows: listings.length,
        promoted: listings.filter(l => l.promoted).length,
        shop: listings.filter(l => l.shop).length,
        old: 0,
      };
      const hits = [];
      if (!baseline) {
        for (const l of listings) {
          if (seen.has(l.id)) continue;
          const why = rejectReason(l, w, { minId, gate, now });
          if (why === 'old') stats.old++;
          if (!why) hits.push(l);
        }
      }

      const nums = listings.filter(l => l.num !== null).map(l => l.num);
      if (nums.length) st.maxId = Math.max(st.maxId ?? 0, ...nums);
      st.seen = [...new Set([...listings.map(l => l.id), ...st.seen])].slice(0, SEEN_MAX);
      Object.assign(st, {
        total: res.total, truncated: res.truncated, catKeys: res.catKeys || st.catKeys || null,
        stats, lastOkAt: now, lastError: null,
      });
      if (baseline) st.baselineAt = now;

      // A listing found by several searches is kept once, with all their names.
      const label = watchLabel(w);
      const fresh = [];
      for (const l of hits) {
        const known = finds.find(f => f.id === l.id);
        if (known) {
          known.watchIds ??= [known.watchId];
          known.watchNames ??= [known.watchName];
          if (!known.watchIds.includes(w.id)) { known.watchIds.push(w.id); known.watchNames.push(label); }
        } else {
          fresh.push({ ...l, description: l.description.slice(0, 160), watchIds: [w.id], watchNames: [label], foundAt: now });
        }
      }
      st.lastNew = fresh.length;
      if (fresh.length) {
        finds.unshift(...fresh);
        finds.splice(FINDS_MAX);
        notify(w, fresh, settings);
      }
    } catch (e) {
      st.lastError = e?.message || String(e);
    }

    state[w.id] = st;
    await chrome.storage.local.set({ state, finds });
  }

  await updateBadge();
}

async function createNotification(id, opts) {
  try {
    await chrome.notifications.create(id, { type: 'basic', priority: 1, ...opts });
  } catch {
    // Usually the listing photo could not be downloaded; fall back to our own icon.
    await chrome.notifications.create(id, { type: 'basic', priority: 1, ...opts, iconUrl: ICON });
  }
}

function notify(w, hits, settings) {
  if (!settings.notify) return;
  const label = watchLabel(w);
  if (hits.length > settings.maxNotify) {
    createNotification(`list:${w.id}`, {
      iconUrl: hits[0].image || ICON,
      title: `${hits.length} nieuwe advertenties: ${label}`,
      message: hits.slice(0, 3).map(h => h.title).join('\n'),
      contextMessage: 'Klik om de lijst te openen',
    });
    return;
  }
  for (const h of hits) {
    createNotification(`open:${h.url}`, {
      iconUrl: h.image || ICON,
      title: h.title,
      message: [formatPrice(h), h.city, formatDistance(h.distanceM)].filter(Boolean).join(' · '),
      contextMessage: `Nieuw voor: ${label}`,
    });
  }
}

async function updateBadge() {
  const { finds = [], readUntil = 0, watches = [], state = {} } =
    await chrome.storage.local.get(['finds', 'readUntil', 'watches', 'state']);
  const unread = finds.filter(f => f.foundAt > readUntil).length;
  const failing = watches.some(w => w.active && state[w.id]?.lastError);
  if (unread) {
    await chrome.action.setBadgeBackgroundColor({ color: '#0e7490' });
    await chrome.action.setBadgeText({ text: unread > 99 ? '99+' : String(unread) });
  } else if (failing) {
    await chrome.action.setBadgeBackgroundColor({ color: '#c2410c' });
    await chrome.action.setBadgeText({ text: '!' });
  } else {
    await chrome.action.setBadgeText({ text: '' });
  }
}

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  const { settings } = await chrome.storage.local.get('settings');
  if (!settings) await chrome.storage.local.set({ settings: DEFAULT_SETTINGS });
  await ensureAlarm();
  if (reason === 'install') chrome.runtime.openOptionsPage();
});

chrome.runtime.onStartup.addListener(ensureAlarm);

chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === ALARM) checkAll();
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  if (changes.settings) ensureAlarm();
  if (changes.readUntil || changes.watches) updateBadge();
});

chrome.notifications.onClicked.addListener(id => {
  const url = id.startsWith('open:') ? id.slice(5) : chrome.runtime.getURL('popup.html?view=tab');
  chrome.tabs.create({ url });
  chrome.notifications.clear(id);
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'checkNow') {
    checkAll().then(() => sendResponse({ ok: true }), e => sendResponse({ ok: false, error: e.message }));
    return true;
  }
  if (msg?.type === 'clearFinds') {
    locked(() => chrome.storage.local.set({ finds: [] }))
      .then(updateBadge)
      .then(() => sendResponse({ ok: true }));
    return true;
  }
});

ensureAlarm();
