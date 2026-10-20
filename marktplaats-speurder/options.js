import { CATEGORIES } from './categories.js';
import {
  DEFAULT_SETTINGS, CONDITIONS, DISTANCES_KM, MAX_PAGES, PAGE_SIZE, newWatch, validateWatch, fetchListings,
  fetchConditions, passesFilters, formatPrice, formatDistance, normalizePostcode, websiteUrl, searchKey, timeAgo,
  watchLabel, el, startOfDay,
} from './lib.js';

const $ = id => document.getElementById(id);
let editingId = null; // id of the search open in the editor, null for a new one
let previewRequest = 0; // so a slow earlier Testen run can't overwrite a later one

// ── Helpers ──────────────────────────────────────────────────────────────────

const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;

function categoryName(l1, l2) {
  const cat = CATEGORIES.find(c => String(c[0]) === String(l1));
  if (!cat) return '';
  const sub = cat[2].find(s => String(s[0]) === String(l2));
  return sub ? `${cat[1]} › ${sub[1]}` : cat[1];
}

function summary(w) {
  const parts = [];
  if (w.query.trim()) parts.push(`“${w.query.trim()}”`);
  if (w.l1) parts.push(categoryName(w.l1, w.l2));
  if (w.priceMin !== '' && w.priceMax !== '') parts.push(`€ ${w.priceMin} – € ${w.priceMax}`);
  else if (w.priceMin !== '') parts.push(`vanaf € ${w.priceMin}`);
  else if (w.priceMax !== '') parts.push(`tot € ${w.priceMax}`);
  if (w.postcode) parts.push(normalizePostcode(w.postcode) + (w.distanceKm ? ` + ${w.distanceKm} km` : ''));
  if (w.conditions.length) parts.push(conditionOptions(w).filter(c => w.conditions.includes(c.id)).map(c => c.label).join('/'));
  if (w.exclude.trim()) parts.push(`zonder: ${w.exclude.trim()}`);
  if (!w.inDescription) parts.push('alleen titel');
  return parts.join(' · ');
}

function statusText(w, st) {
  if (!w.active) return { text: 'Gepauzeerd' };
  if (!st) return { text: 'Wacht op eerste controle…' };
  if (st.lastError) return { text: `⚠ ${st.lastError} (${timeAgo(st.lastCheck)})`, warn: true };
  if (!st.baselineAt) return { text: 'Wacht op eerste controle…' };
  const newToday = st.today?.day === startOfDay(Date.now()) ? st.today.n : 0;
  return { text: `Gecontroleerd ${timeAgo(st.lastCheck)} · ${newToday} nieuw vandaag` };
}

// What the last check skipped, so a quiet search can be explained.
function statsText(st) {
  const s = st?.stats;
  if (!s || st.lastError || !st.baselineAt) return '';
  const parts = [];
  if (s.promoted) parts.push(count(s.promoted, 'betaalde promotie', 'betaalde promoties'));
  if (s.shop) parts.push(count(s.shop, 'winkeladvertentie', 'winkeladvertenties'));
  if (s.old) parts.push(count(s.old, 'oudere advertentie', 'oudere advertenties'));
  let text = parts.length ? `Laatste controle: ${s.rows} bekeken, waarvan ${parts.join(', ')} niet als nieuw geteld.` : '';
  if (st.truncated) text += ' Zeer brede zoekopdracht: niet alles kon worden nagelopen; maak hem specifieker.';
  return text.trim();
}

function toast(msg) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove('show'), 3500);
}

async function getWatches() {
  const { watches = [] } = await chrome.storage.local.get('watches');
  return watches;
}

async function saveWatches(watches) {
  await chrome.storage.local.set({ watches });
}

// Run a check now, so a new or changed search gets its baseline straight away.
function checkNow() {
  chrome.runtime.sendMessage({ type: 'checkNow' }).catch(() => {});
}

// ── Search list ──────────────────────────────────────────────────────────────

async function renderWatches() {
  const { watches = [], state = {} } = await chrome.storage.local.get(['watches', 'state']);
  const box = $('watches');
  box.replaceChildren();

  if (!watches.length) {
    box.append(el('p', { className: 'muted', textContent: 'Nog geen zoekopdrachten. Klik op “+ Nieuwe zoekopdracht” om te beginnen.' }));
    return;
  }

  for (const w of watches) {
    // State of an earlier version of this search (e.g. edited while paused) doesn't count.
    const cur = state[w.id]?.key === searchKey(w) ? state[w.id] : null;
    const st = statusText(w, cur);

    const toggle = el('input', { type: 'checkbox', checked: w.active, title: 'Actief' });
    toggle.onchange = async () => {
      const all = await getWatches();
      const target = all.find(x => x.id === w.id);
      if (!target) return;
      target.active = toggle.checked;
      await saveWatches(all);
      if (toggle.checked) checkNow();
    };

    const edit = el('button', { textContent: 'Bewerken' });
    edit.onclick = () => openEditor(w);

    const del = el('button', { className: 'danger', textContent: 'Verwijderen' });
    del.onclick = async () => {
      if (!confirm(`Zoekopdracht “${watchLabel(w)}” verwijderen?`)) return;
      await saveWatches((await getWatches()).filter(x => x.id !== w.id));
      toast('Zoekopdracht verwijderd.');
    };

    const site = websiteUrl(w, cur?.catKeys);
    const stats = statsText(cur);
    box.append(el('div', { className: 'watch' + (w.active ? '' : ' off') },
      el('label', { className: 'switch' }, toggle),
      el('div', { className: 'info' },
        el('div', { className: 'name', textContent: watchLabel(w) }),
        el('div', { className: 'small muted', textContent: summary(w) }),
        el('div', { className: 'small ' + (st.warn ? 'warn' : 'muted'), textContent: st.text }),
        stats ? el('div', { className: 'small ' + (cur.truncated ? 'warn' : 'muted'), textContent: stats }) : null,
        site ? el('a', { className: 'small', href: site, target: '_blank', rel: 'noopener', textContent: 'Open op Marktplaats ↗' }) : null),
      el('div', { className: 'actions' }, edit, del)));
  }
}

// ── Editor ───────────────────────────────────────────────────────────────────

const editor = $('editor');

function fillSubcategories(l1, selected = '') {
  const l2 = $('l2');
  l2.replaceChildren(el('option', { value: '', textContent: 'Alle subcategorieën' }));
  const cat = CATEGORIES.find(c => String(c[0]) === String(l1));
  for (const [id, name] of cat ? cat[2] : []) l2.append(el('option', { value: String(id), textContent: name }));
  l2.disabled = !cat;
  l2.value = selected;
}

// Condition ids differ per category (a used car is not a used bike), so the options
// come from the category itself; without a category the common ids are used.
let conditionsRequest = 0;

function renderConditions(options, checked) {
  $('conditions').replaceChildren(...options.map(c => el('label', {},
    el('input', { type: 'checkbox', value: String(c.id), name: 'condition', checked: checked.includes(c.id) }),
    el('span', { textContent: c.label }))));
}

// The saved conditions with their labels, followed by the common ones.
function conditionOptions(w) {
  const saved = w.conditions.map((id, i) => ({
    id, label: w.conditionLabels?.[i] || CONDITIONS.find(c => c.id === id)?.label || String(id),
  }));
  return [...saved, ...CONDITIONS.filter(c => !w.conditions.includes(c.id))];
}

function checkedConditions() {
  return [...document.querySelectorAll('input[name=condition]:checked')]
    .map(cb => ({ id: Number(cb.value), label: cb.nextElementSibling.textContent }));
}

// Ticked boxes are read after the request, so clicks made while it loads are kept.
async function loadConditions(l1, l2) {
  const request = ++conditionsRequest;
  if (!l1) {
    renderConditions(CONDITIONS, checkedConditions().map(c => c.id));
    $('conditionsHint').textContent = 'Niets aangevinkt = alles.';
    return;
  }
  $('conditionsHint').textContent = 'Opties van deze categorie ophalen…';
  let options, failed = false;
  try { options = await fetchConditions(l1, l2); } catch { options = CONDITIONS; failed = true; }
  if (request !== conditionsRequest) return; // the category changed meanwhile
  const checked = checkedConditions();
  // Without the category's own list, keep what was ticked rather than silently dropping it.
  if (failed) options = [...checked.filter(c => !options.some(o => o.id === c.id)), ...options];
  renderConditions(options, checked.map(c => c.id));
  $('conditionsHint').textContent = failed ? 'Kon de opties van deze categorie niet ophalen.'
    : options.length ? 'Niets aangevinkt = alles.' : 'Deze categorie heeft geen conditiefilter.';
}

function setupEditorFields() {
  for (const [id, name] of CATEGORIES) $('l1').append(el('option', { value: String(id), textContent: name }));
  $('l1').onchange = () => {
    fillSubcategories($('l1').value);
    loadConditions($('l1').value, '');
  };
  $('l2').onchange = () => loadConditions($('l1').value, $('l2').value);

  for (const km of DISTANCES_KM) $('distanceKm').append(el('option', { value: String(km), textContent: `< ${km} km` }));
  $('postcode').oninput = () => {
    $('distanceKm').disabled = !$('postcode').value.trim();
    if ($('distanceKm').disabled) $('distanceKm').value = '';
  };
}

function openEditor(w) {
  editingId = w ? w.id : null;
  w = w ? structuredClone(w) : newWatch();
  $('editorTitle').textContent = editingId ? 'Zoekopdracht bewerken' : 'Nieuwe zoekopdracht';
  for (const f of ['name', 'query', 'priceMin', 'priceMax', 'postcode', 'exclude']) $(f).value = w[f];
  $('l1').value = w.l1;
  fillSubcategories(w.l1, w.l2);
  $('distanceKm').value = w.distanceKm;
  $('distanceKm').disabled = !w.postcode;
  renderConditions(conditionOptions(w), w.conditions); // right away, so a quick save keeps them
  loadConditions(w.l1, w.l2);
  for (const f of ['inDescription', 'skipAds', 'active']) $(f).checked = w[f];
  $('errors').hidden = true;
  $('preview').hidden = true;
  previewRequest++;
  editor.dataset.id = w.id;
  editor.showModal();
  $(editingId ? 'name' : 'query').focus();
}

function readEditor() {
  return {
    id: editor.dataset.id,
    name: $('name').value.trim(),
    query: $('query').value.trim(),
    l1: $('l1').value,
    l2: $('l1').value ? $('l2').value : '',
    priceMin: $('priceMin').value.trim(),
    priceMax: $('priceMax').value.trim(),
    postcode: normalizePostcode($('postcode').value),
    distanceKm: $('postcode').value.trim() ? $('distanceKm').value : '',
    conditions: checkedConditions().map(c => c.id),
    conditionLabels: checkedConditions().map(c => c.label),
    inDescription: $('inDescription').checked,
    exclude: $('exclude').value.trim(),
    skipAds: $('skipAds').checked,
    active: $('active').checked,
  };
}

function showErrors(errors) {
  $('errors').hidden = !errors.length;
  $('errors').replaceChildren(...errors.map(e => el('div', { textContent: e })));
  return errors.length > 0;
}

$('test').onclick = async () => {
  const w = readEditor();
  if (showErrors(validateWatch(w))) return;
  const box = $('preview');
  box.hidden = false;
  box.replaceChildren(el('span', { className: 'muted', textContent: 'Bezig met zoeken op Marktplaats…' }));
  const request = ++previewRequest;
  try {
    const { listings, total, truncated } = await fetchListings(w, { minOrganic: 5 });
    if (request !== previewRequest) return;
    const promoted = listings.filter(l => l.promoted).length;
    const shop = listings.filter(l => l.shop).length;
    const hits = listings.filter(l => !l.promoted && !l.shop && passesFilters(l, w));
    const lines = [el('div', { textContent: `${total ?? listings.length} advertenties gevonden.` })];
    const skipped = [
      promoted ? count(promoted, 'betaalde promotie', 'betaalde promoties') : '',
      shop ? count(shop, 'winkeladvertentie', 'winkeladvertenties') : '',
    ].filter(Boolean);
    if (skipped.length) {
      lines.push(el('div', { className: 'muted', textContent:
        `Bovenaan de eerste ${listings.length} staan ${skipped.join(' en ')}. ` +
        (w.skipAds ? 'Die tellen nooit als nieuw.' : 'Promoties tellen alleen als ze echt nieuw geplaatst zijn, winkeladvertenties nooit.') }));
    }
    if (hits.length) {
      lines.push(el('div', { textContent: 'Nieuwste gewone advertenties (na jouw filters):' }));
      const list = el('ol');
      for (const l of hits.slice(0, 5)) {
        const where = [l.city, formatDistance(l.distanceM)].filter(Boolean).join(', ');
        list.append(el('li', {},
          el('a', { href: l.url, target: '_blank', rel: 'noopener', textContent: l.title }),
          ` – ${formatPrice(l)}${where ? ` (${where})` : ''}${l.date ? ` · ${l.date.toLowerCase()}` : ''}`));
      }
      lines.push(list);
    } else if (truncated) {
      lines.push(el('div', { textContent: `In de eerste ${MAX_PAGES * PAGE_SIZE} resultaten staan alleen promoties of advertenties die niet door jouw filters komen.` }));
    } else {
      lines.push(el('div', { textContent: 'Er zijn nu geen gewone advertenties die door jouw filters komen.' }));
    }
    box.replaceChildren(...lines);
  } catch (e) {
    if (request !== previewRequest) return;
    box.replaceChildren(el('span', { className: 'warn', textContent: `Zoeken mislukt: ${e.message}` }));
  }
};

$('cancel').onclick = () => editor.close();

$('form').onsubmit = async e => {
  e.preventDefault();
  const w = readEditor();
  if (showErrors(validateWatch(w))) return;
  if (!w.name) w.name = w.query || categoryName(w.l1, w.l2);

  const watches = await getWatches();
  const i = watches.findIndex(x => x.id === w.id);
  if (i >= 0) watches[i] = w; else watches.push(w);
  await saveWatches(watches);
  editor.close();
  toast(i >= 0 ? 'Opgeslagen.' : 'Opgeslagen. Wat nu al online staat telt als bekend; je krijgt alleen nieuw geplaatste advertenties.');
  checkNow();
};

$('add').onclick = () => openEditor(null);

// ── General settings ─────────────────────────────────────────────────────────

async function loadSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  const s = { ...DEFAULT_SETTINGS, ...settings };
  $('intervalMin').value = String(s.intervalMin);
  $('maxNotify').value = String(s.maxNotify);
  $('notify').checked = s.notify;
}

async function saveSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  await chrome.storage.local.set({
    settings: {
      ...DEFAULT_SETTINGS, ...settings,
      intervalMin: Number($('intervalMin').value),
      maxNotify: Number($('maxNotify').value),
      notify: $('notify').checked,
    },
  });
  toast('Instellingen opgeslagen.');
}

for (const id of ['intervalMin', 'maxNotify', 'notify']) $(id).onchange = saveSettings;

// ── Back-up ──────────────────────────────────────────────────────────────────

$('export').onclick = async () => {
  const { watches = [], settings = {} } = await chrome.storage.local.get(['watches', 'settings']);
  const data = { app: 'marktplaats-speurder', version: 1, exported: new Date().toISOString(), settings, watches };
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
  el('a', { href: url, download: `marktplaats-speurder-${new Date().toISOString().slice(0, 10)}.json` }).click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};

$('import').onclick = () => $('importFile').click();

$('importFile').onchange = async () => {
  const file = $('importFile').files[0];
  $('importFile').value = '';
  if (!file) return;
  let data;
  try { data = JSON.parse(await file.text()); } catch { return toast('Dit is geen geldig JSON-bestand.'); }
  if (!Array.isArray(data?.watches)) return toast('Geen zoekopdrachten gevonden in dit bestand.');

  const current = await getWatches();
  if (!confirm(`Je ${current.length} huidige zoekopdracht(en) vervangen door de ${data.watches.length} uit het bestand?`)) return;

  const watches = data.watches.map(w => ({ ...newWatch(), ...w, id: w.id || crypto.randomUUID() }));
  const update = { watches };
  if (data.settings) update.settings = { ...DEFAULT_SETTINGS, ...data.settings };
  await chrome.storage.local.set(update);
  await loadSettings();
  toast(`${watches.length} zoekopdracht(en) geïmporteerd.`);
  checkNow();
};

// ── Start ────────────────────────────────────────────────────────────────────

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && (changes.watches || changes.state)) renderWatches();
});

setupEditorFields();
await loadSettings();
await renderWatches();
setInterval(renderWatches, 30000); // keep the "x min ago" texts fresh
