import { formatPrice, formatDistance, placedLabel, timeAgo, watchLabel, el } from './lib.js';

const isTab = new URLSearchParams(location.search).get('view') === 'tab';
if (isTab) document.body.classList.add('tab');

const $ = id => document.getElementById(id);
let filter = 'all';
let readUntil = 0; // as it was when the popup opened, so new items stay highlighted

// Finds from before version 1.1 carry a single watchId/watchName.
const findWatchIds = f => f.watchIds || [f.watchId];
const findWatchNames = f => f.watchNames || [f.watchName];

async function render() {
  const { watches = [], state = {}, finds = [], settings = {} } =
    await chrome.storage.local.get(['watches', 'state', 'finds', 'settings']);
  const active = watches.filter(w => w.active);

  // Status line: last check and any failing searches.
  const status = $('status');
  status.replaceChildren();
  if (active.length) {
    const last = Math.max(0, ...active.map(w => state[w.id]?.lastCheck || 0));
    status.append(`${active.length} actieve zoekopdracht${active.length === 1 ? '' : 'en'} · laatst gecontroleerd ${timeAgo(last)} · elke ${settings.intervalMin || 5} min`);
    for (const w of active) {
      const err = state[w.id]?.lastError;
      if (err) status.append(el('span', { className: 'err', textContent: `⚠ ${watchLabel(w)}: ${err}` }));
    }
  }

  // Filter chips per search.
  const chips = $('chips');
  chips.replaceChildren();
  if (finds.length && watches.length > 1) {
    const counts = {};
    for (const f of finds) for (const id of findWatchIds(f)) counts[id] = (counts[id] || 0) + 1;
    const chip = (id, text) => {
      const b = el('button', { className: 'chip' + (filter === id ? ' on' : ''), textContent: text });
      b.onclick = () => { filter = id; render(); };
      return b;
    };
    chips.append(chip('all', `Alles (${finds.length})`));
    for (const w of watches) if (counts[w.id]) chips.append(chip(w.id, `${watchLabel(w)} (${counts[w.id]})`));
  }

  // The list itself.
  const list = $('list');
  list.replaceChildren();
  const shown = finds.filter(f => filter === 'all' || findWatchIds(f).includes(filter));

  if (!watches.length) {
    const add = el('button', { className: 'primary', textContent: 'Zoekopdracht toevoegen' });
    add.onclick = () => chrome.runtime.openOptionsPage();
    list.append(el('div', { className: 'empty' },
      el('p', { textContent: 'Je hebt nog geen zoekopdrachten.' }), add));
  } else if (!shown.length) {
    list.append(el('div', { className: 'empty' },
      el('p', { textContent: 'Nog niets nieuws gevonden.' }),
      el('p', { className: 'small', textContent: 'Nieuwe advertenties verschijnen hier zodra ze op Marktplaats komen. Advertenties die er al stonden toen je de zoekopdracht toevoegde, worden overgeslagen.' })));
  }

  for (const f of shown) {
    const img = el('img', { className: 'thumb', alt: '', loading: 'lazy' });
    if (f.image) img.src = f.image;
    const where = [f.city, formatDistance(f.distanceM)].filter(Boolean).join(' · ');
    list.append(el('a', {
      className: 'item' + (f.foundAt > readUntil ? ' unread' : ''),
      href: f.url, target: '_blank', rel: 'noopener', title: f.description,
    },
      img,
      el('div', { className: 'body' },
        el('div', { className: 'title', textContent: f.title }),
        el('div', {}, el('span', { className: 'price', textContent: formatPrice(f) }),
          where ? el('span', { className: 'meta', textContent: `  ${where}` }) : null),
        el('div', { className: 'meta', textContent: [
          findWatchNames(f).join(', '),
          placedLabel(f) ? `geplaatst ${placedLabel(f)}` : '',
          `gevonden ${timeAgo(f.foundAt)}`,
        ].filter(Boolean).join(' · ') }))));
  }

  $('clear').hidden = !finds.length;
  $('openTab').hidden = isTab;
}

$('check').onclick = async () => {
  const btn = $('check');
  btn.disabled = true;
  btn.textContent = '…';
  await chrome.runtime.sendMessage({ type: 'checkNow' });
  btn.disabled = false;
  btn.textContent = '⟳';
};

$('settings').onclick = () => chrome.runtime.openOptionsPage();
$('openTab').onclick = () => chrome.tabs.create({ url: chrome.runtime.getURL('popup.html?view=tab') });
$('clear').onclick = () => {
  if (confirm('Alle gevonden advertenties uit de lijst verwijderen?')) chrome.runtime.sendMessage({ type: 'clearFinds' });
};

chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== 'local') return;
  if (changes.finds || changes.state || changes.watches || changes.settings) render();
  if (changes.finds) chrome.storage.local.set({ readUntil: Date.now() }); // seen while open
});

({ readUntil = 0 } = await chrome.storage.local.get('readUntil'));
await render();
await chrome.storage.local.set({ readUntil: Date.now() });
