import { CATEGORIES } from './categories.js';
import {
  DEFAULT_SETTINGS, CONDITIONS, DISTANCES_KM, MAX_PAGES, PAGE_SIZE, newWatch, validateWatch, fetchListings,
  fetchConditions, matchConditions, savedConditions, passesFilters, formatPrice, formatDistance, normalizePostcode,
  websiteUrl, searchKey, timeAgo, watchLabel, el, startOfDay, TRIAGE_URL,
} from './lib.js';
import { MODELS, DEFAULT_MODEL, triage, triagePageStatus, testKey } from './claude.js';

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
  if (w.conditions.length) parts.push(savedConditions(w).map(c => c.label).join('/'));
  if (w.exclude.trim()) parts.push(`zonder: ${w.exclude.trim()}`);
  if (!w.inDescription) parts.push('alleen titel');
  if (w.ai?.trim()) parts.push(`Claude: “${w.ai.length > 60 ? `${w.ai.slice(0, 57).trim()}…` : w.ai.trim()}”`);
  return parts.join(' · ');
}

function statusText(w, st) {
  if (!w.active) return { text: 'Gepauzeerd' };
  if (!st) return { text: 'Wacht op eerste controle…' };
  if (st.lastError) return { text: `⚠ ${st.lastError} (${timeAgo(st.lastCheck)})`, warn: true };
  if (!st.baselineAt) return { text: 'Wacht op eerste controle…' };
  const newToday = st.today?.day === startOfDay(Date.now()) ? st.today.n : 0;
  const text = `Gecontroleerd ${timeAgo(st.lastCheck)} · ${newToday} nieuw vandaag`;
  if (st.triageError) {
    const waiting = st.pending?.length ? ` (${count(st.pending.length, 'advertentie wacht', 'advertenties wachten')} op Claude)` : '';
    return { text: `${text} · ⚠ ${st.triageError}${waiting}`, warn: true };
  }
  if (st.empty) return { text: `${text} · ⚠ Deze zoekopdracht vindt op dit moment niets op Marktplaats; controleer de filters met Testen.`, warn: true };
  return { text };
}

// What the last check skipped, so a quiet search can be explained.
function statsText(st) {
  const s = st?.stats;
  if (!s || st.lastError || !st.baselineAt) return '';
  const parts = [];
  if (s.promoted) parts.push(count(s.promoted, 'betaalde promotie', 'betaalde promoties'));
  if (s.shop) parts.push(count(s.shop, 'winkeladvertentie', 'winkeladvertenties'));
  let text = parts.length ? `Laatste controle: ${s.rows} bekeken, waarvan ${parts.join(', ')} niet als nieuw geteld.` : '';
  const ai = st.aiToday;
  if (ai?.day === startOfDay(Date.now()) && ai.judged) text += ` Claude liet vandaag ${ai.passed} van de ${ai.judged} nieuwe advertenties door.`;
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
  return [...savedConditions(w), ...CONDITIONS.filter(c => !w.conditions.includes(c.id))];
}

function checkedConditions() {
  return [...document.querySelectorAll('input[name=condition]:checked')]
    .map(cb => ({ id: Number(cb.value), label: cb.nextElementSibling.textContent }));
}

// Ticked boxes are read after the request, so clicks made while it loads are kept.
async function loadConditions(l1, l2) {
  const request = ++conditionsRequest;
  if (!l1) {
    renderConditions(CONDITIONS, matchConditions(checkedConditions(), CONDITIONS).map(c => c.id));
    $('conditionsHint').textContent = 'Niets aangevinkt = alles.';
    return;
  }
  $('conditionsHint').textContent = 'Opties van deze categorie ophalen…';
  let options, failed = false;
  try { options = await fetchConditions(l1, l2); } catch { options = CONDITIONS; failed = true; }
  if (request !== conditionsRequest) return; // the category changed meanwhile
  // A tick the category knows under another id (a "Gebruikt" car is 14049, not 32) is
  // moved to that id. Without the category's own list, ticks are kept rather than dropped.
  const checked = matchConditions(checkedConditions(), options, { keepUnknown: failed });
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
  $('ai').value = w.ai || '';
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
    ai: $('ai').value.trim(),
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
    const { listings, total, truncated, complete } = await fetchListings(w, { minOrganic: 5 });
    if (request !== previewRequest) return;
    const promoted = listings.filter(l => l.promoted).length;
    const shop = listings.filter(l => l.shop).length;
    // Marktplaats pads small results with "similar" listings and counts them in its total.
    const related = listings.filter(l => l.related).length;
    const found = complete ? listings.length - related : Math.max(0, (total ?? listings.length) - related);
    const hits = listings.filter(l => !l.promoted && !l.shop && passesFilters(l, w));
    const lines = [el('div', { textContent: `${count(found, 'advertentie', 'advertenties')} gevonden.` +
      (related ? ` Marktplaats vulde aan met ${related} vergelijkbare die niet aan de zoekopdracht voldoen; die tellen niet mee.` : '') })];
    const skipped = [
      promoted ? count(promoted, 'betaalde promotie', 'betaalde promoties') : '',
      shop ? count(shop, 'winkeladvertentie', 'winkeladvertenties') : '',
    ].filter(Boolean);
    if (skipped.length) {
      lines.push(el('div', { className: 'muted', textContent:
        `Bovenaan de eerste ${listings.length} ${promoted + shop === 1 ? 'staat' : 'staan'} ${skipped.join(' en ')}. ` +
        (w.skipAds ? 'Die tellen nooit als nieuw.' : 'Promoties tellen alleen als ze echt nieuw geplaatst zijn, winkeladvertenties nooit.') }));
    }
    if (hits.length) {
      // With a description, let Claude judge the newest ones, as it will for new listings.
      const sample = hits.slice(0, w.ai ? 10 : 5);
      let verdicts = null;
      let aiProblem = '';
      if (w.ai) {
        box.replaceChildren(...lines, el('div', { className: 'muted', textContent: 'Claude beoordeelt de nieuwste advertenties…' }));
        const { claudeKey = '', settings = {} } = await chrome.storage.local.get(['claudeKey', 'settings']);
        try {
          ({ verdicts } = await triage(sample, w.ai, {
            provider: settings.aiProvider || DEFAULT_SETTINGS.aiProvider, apiKey: claudeKey,
            model: settings.aiModel || DEFAULT_MODEL, search: w.name || w.query,
          }));
        } catch (e) {
          aiProblem = e.message;
        }
        if (request !== previewRequest) return;
      }
      const passed = verdicts ? sample.filter(l => verdicts.get(l.id)?.match).length : 0;
      lines.push(el('div', { textContent: verdicts
        ? `Claude laat ${passed} van de ${sample.length} nieuwste gewone advertenties door:`
        : 'Nieuwste gewone advertenties (na jouw filters):' }));
      if (aiProblem) lines.push(el('div', { className: 'warn', textContent: aiProblem }));
      const list = el('ol');
      for (const l of sample) {
        const v = verdicts?.get(l.id);
        const where = [l.city, formatDistance(l.distanceM)].filter(Boolean).join(', ');
        list.append(el('li', { className: v && !v.match ? 'no' : '' },
          v ? (v.match ? '✓ ' : '✗ ') : '',
          el('a', { href: l.url, target: '_blank', rel: 'noopener', textContent: l.title }),
          ` – ${formatPrice(l)}${where ? ` (${where})` : ''}${l.date ? ` · ${l.date.toLowerCase()}` : ''}`,
          v ? el('span', { className: 'why', textContent: ` — ${v.reason}` }) : null));
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
  $('aiModel').value = s.aiModel;
  $(s.aiProvider === 'api' ? 'viaApi' : 'viaPage').checked = true;
  $('apiFields').hidden = s.aiProvider !== 'api';
}

async function saveSettings() {
  const { settings } = await chrome.storage.local.get('settings');
  await chrome.storage.local.set({
    settings: {
      ...DEFAULT_SETTINGS, ...settings,
      intervalMin: Number($('intervalMin').value),
      maxNotify: Number($('maxNotify').value),
      notify: $('notify').checked,
      aiModel: $('aiModel').value,
      aiProvider: $('viaApi').checked ? 'api' : 'claudeai',
    },
  });
  toast('Instellingen opgeslagen.');
}

for (const id of ['intervalMin', 'maxNotify', 'notify']) $(id).onchange = saveSettings;
$('aiModel').onchange = () => { showEstimate(); saveSettings(); };

// ── Claude ───────────────────────────────────────────────────────────────────

const dollars = n => (n > 0 && n < 0.005 ? 'minder dan $0,01' : `$${n.toFixed(2).replace('.', ',')}`);

for (const m of MODELS) $('aiModel').append(el('option', { value: m.id, textContent: m.label }));

// Rough cost per 100 listings: ~200 input and ~60 output tokens each (judged in batches).
function showEstimate() {
  const m = MODELS.find(x => x.id === $('aiModel').value) || MODELS[0];
  $('aiEstimate').textContent = `Ongeveer ${dollars(100 * (200 * m.input + 60 * m.output) / 1e6)} per 100 beoordeelde advertenties.`;
}

function showUsage(u) {
  const judged = u?.day === startOfDay(Date.now()) ? u.listings : 0;
  $('aiUsage').textContent = !judged ? 'Vandaag nog niets beoordeeld.'
    : `Vandaag ${count(judged, 'advertentie', 'advertenties')} beoordeeld${u.cost ? `; via de API geschat ${dollars(u.cost)}` : ''}.`;
}

async function showPageStatus() {
  const { connected, ready, paused } = await triagePageStatus();
  const box = $('pageStatus');
  box.className = 'route-detail small ' + (ready && !paused ? 'ok' : connected ? 'warn' : 'muted');
  box.textContent = ready && paused ? 'De triage-pagina is open maar staat op pauze.'
    : ready ? '✓ De triage-pagina is open en klaar.'
    : connected ? 'De triage-pagina is open: klik daar eenmalig op Starten om Claude toestemming te geven.'
    : 'De triage-pagina is nu niet open. Open hem en laat het tabblad openstaan (vastzetten kan via rechtsklik op het tabblad).';
}

async function loadClaude() {
  const { claudeKey = '', aiUsage } = await chrome.storage.local.get(['claudeKey', 'aiUsage']);
  $('claudeKey').value = claudeKey;
  $('triageLink').href = TRIAGE_URL;
  showEstimate();
  showUsage(aiUsage);
  await showPageStatus();
}

for (const id of ['viaPage', 'viaApi']) {
  $(id).onchange = async () => {
    $('apiFields').hidden = !$('viaApi').checked;
    await saveSettings();
    checkNow(); // listings waiting for Claude may be judged on the new route
  };
}

$('claudeKey').onchange = async () => {
  await chrome.storage.local.set({ claudeKey: $('claudeKey').value.trim() });
  $('keyStatus').className = 'hint';
  $('keyStatus').textContent = 'Opgeslagen. Blijft alleen in deze browser en gaat niet mee in de back-up.';
  toast('API-sleutel opgeslagen.');
  checkNow(); // listings waiting for a key are judged now
};

$('testKey').onclick = async () => {
  const status = $('keyStatus');
  status.className = 'hint';
  status.textContent = 'Bezig met testen…';
  try {
    await testKey($('claudeKey').value.trim(), $('aiModel').value);
    status.textContent = `✓ De sleutel werkt met ${MODELS.find(m => m.id === $('aiModel').value).label.split(' – ')[0]}.`;
  } catch (e) {
    status.className = 'hint warn';
    status.textContent = e.message;
  }
};

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
  if (area === 'local' && changes.aiUsage) showUsage(changes.aiUsage.newValue);
  if (area === 'session' && changes.triagePage) showPageStatus();
});

setupEditorFields();
await loadSettings();
await loadClaude();
await renderWatches();
setInterval(() => { renderWatches(); showPageStatus(); }, 30000); // keep "x min ago" and the page status fresh
