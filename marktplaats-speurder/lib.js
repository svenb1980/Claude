// Shared logic for the background worker, popup and options page.
//
// Marktplaats has no public API for searching listings. The website itself loads its
// search results from /lrp/api/search (JSON, no key). The parameters below mirror the
// ones the site sends; they are the same ones the open-source marktplaats-py client
// uses (github.com/jensjeflensje/marktplaats-py).
//
// How the endpoint behaves (from other open-source monitors and recorded responses):
// - Newest-first (SORT_INDEX) sorts on a "bump" date: paid promotions (dagtoppers) and
//   paid "omhoog plaatsen" put old listings back on top, dated "Vandaag".
// - Broad searches (a whole category) start with many pages' worth of dagtoppers.
// - Shop ads (Admarkt) have ids starting with "a", are always dated "Vandaag" and are
//   mixed into the results with priorityProduct NONE.
// - Private listings have ids "m<number>"; the number grows with the moment the listing
//   was placed and stays the same when it is bumped. That is the only reliable "is this
//   really new" signal in the search results.
// - Short pages are padded with loosely related listings (searchType "kNN") that do not
//   match the search; with small limits they even come back beyond `limit`.

export const API_URL = 'https://www.marktplaats.nl/lrp/api/search';
export const SITE_URL = 'https://www.marktplaats.nl';
export const PAGE_SIZE = 100;      // the API maximum
export const MAX_PAGES = 3;        // per check, to get past the dagtoppers in broad searches
export const ID_MARGIN = 100000;   // ≈ 6 hours of listings site-wide; tolerates late publication

export const DEFAULT_SETTINGS = {
  intervalMin: 5,       // minutes between checks
  notify: true,         // desktop notifications
  maxNotify: 3,         // per search per check; more becomes one summary notification
};

// attributesById values for the condition filter in most categories. Some categories
// use other ids (a used car is 14049), so the editor reads them from the category.
export const CONDITIONS = [
  { id: 30, label: 'Nieuw' },
  { id: 31, label: 'Zo goed als nieuw' },
  { id: 32, label: 'Gebruikt' },
  { id: 14050, label: 'Refurbished' },
  { id: 13940, label: 'Niet werkend' },
];

export const DISTANCES_KM = [3, 5, 10, 15, 25, 50, 75];

export function newWatch() {
  return {
    id: crypto.randomUUID(),
    name: '',
    query: '',
    l1: '',
    l2: '',
    priceMin: '',
    priceMax: '',
    postcode: '',
    distanceKm: '',
    conditions: [],
    inDescription: true,
    exclude: '',
    skipAds: false,
    active: true,
  };
}

export function normalizePostcode(pc) {
  return String(pc || '').toUpperCase().replace(/\s+/g, '');
}

export function isValidPostcode(pc) {
  return /^\d{4}([A-Z]{2})?$/.test(normalizePostcode(pc));
}

function toCents(euros) {
  if (euros === '' || euros == null) return null;
  const n = Number(String(euros).replace(',', '.'));
  return Number.isFinite(n) && n >= 0 ? Math.round(n * 100) : null;
}

// Returns a list of problems; empty means the search can be saved.
export function validateWatch(w) {
  const errors = [];
  if (!w.query.trim() && !w.l1) errors.push('Vul een zoekterm in of kies een categorie.');
  if (w.priceMin !== '' && toCents(w.priceMin) === null) errors.push('Minimumprijs is geen geldig bedrag.');
  if (w.priceMax !== '' && toCents(w.priceMax) === null) errors.push('Maximumprijs is geen geldig bedrag.');
  const min = toCents(w.priceMin), max = toCents(w.priceMax);
  if (min !== null && max !== null && min > max) errors.push('Minimumprijs is hoger dan maximumprijs.');
  if (w.postcode && !isValidPostcode(w.postcode)) errors.push('Postcode moet 1234AB (of 1234) zijn.');
  if (w.distanceKm && !w.postcode) errors.push('Vul een postcode in om op afstand te filteren.');
  return errors;
}

// since: only listings offered since this moment (ms), filtered by Marktplaats itself.
export function buildSearchUrl(w, { offset = 0, since = null } = {}) {
  const p = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
    query: w.query.trim(),
    searchInTitleAndDescription: w.inDescription ? 'true' : 'false',
    viewOptions: 'list-view',
    sortBy: 'SORT_INDEX',        // newest first
    sortOrder: 'DECREASING',
    postcode: w.postcode ? normalizePostcode(w.postcode) : '',
    distanceMeters: w.postcode && w.distanceKm ? String(Number(w.distanceKm) * 1000) : '1000000',
  });
  if (w.l1) p.set('l1CategoryId', String(w.l1));
  if (w.l1 && w.l2) p.set('l2CategoryIds', String(w.l2)); // plural: the singular is ignored
  const min = toCents(w.priceMin), max = toCents(w.priceMax);
  if (min !== null || max !== null) p.append('attributeRanges[]', `PriceCents:${min ?? 'null'}:${max ?? 'null'}`);
  for (const c of w.conditions || []) p.append('attributesById[]', String(c));
  if (since) p.append('attributesByKey[]', `offeredSince:${since}`);
  return `${API_URL}?${p}`;
}

// The same search on the website, for "open on Marktplaats". Category pages need the
// category slugs, which come back in each search response (catKeys).
export function websiteUrl(w, catKeys) {
  const query = w.query.trim();
  const q = encodeURIComponent(query).replace(/%20/g, '+');
  let path;
  if (w.l1) {
    if (!catKeys?.l1) return null;
    path = `/l/${catKeys.l1}/${w.l2 && catKeys.l2 ? `${catKeys.l2}/` : ''}`;
  } else {
    if (!query) return null;
    path = `/q/${q}/`;
  }
  const f = [];
  if (w.l1 && query) f.push(`q:${q}`);
  f.push('sortBy:SORT_INDEX', 'sortOrder:DECREASING');
  const min = toCents(w.priceMin), max = toCents(w.priceMax);
  if (min !== null) f.push(`PriceCentsFrom:${min}`);
  if (max !== null) f.push(`PriceCentsTo:${max}`);
  if (w.conditions?.length) f.push(`f:${w.conditions.join(',')}`);
  if (w.postcode) f.push(`postcode:${normalizePostcode(w.postcode)}`);
  if (w.postcode && w.distanceKm) f.push(`distanceMeters:${Number(w.distanceKm) * 1000}`);
  return `${SITE_URL}${path}#${f.join('|')}`;
}

// Fingerprint of everything that changes which listings come back. When it changes,
// the next check starts over with a fresh baseline instead of reporting old listings.
// The leading version number forces a fresh baseline when the detection logic changes.
export function searchKey(w) {
  return JSON.stringify([
    2, w.query.trim().toLowerCase(), w.l1, w.l2, toCents(w.priceMin), toCents(w.priceMax),
    w.postcode ? normalizePostcode(w.postcode) : '', w.postcode ? w.distanceKm : '',
    [...(w.conditions || [])].sort(), !!w.inDescription,
  ]);
}

function absUrl(u) {
  if (!u) return '';
  if (u.startsWith('//')) return 'https:' + u;
  if (u.startsWith('/')) return SITE_URL + u;
  return u;
}

export function parseListing(raw) {
  const pic = raw.pictures?.[0];
  const loc = raw.location || {};
  const id = String(raw.itemId || '');
  const traits = Array.isArray(raw.traits) ? raw.traits : [];
  const m = id.match(/^m(\d+)$/);
  return {
    id,
    num: m ? Number(m[1]) : null,   // placement order, private listings only
    title: raw.title || '(geen titel)',
    description: raw.description || '',
    priceCents: raw.priceInfo?.priceCents ?? 0,
    priceType: raw.priceInfo?.priceType || 'UNKNOWN',
    city: loc.cityName || '',
    distanceM: loc.distanceMeters > 0 ? loc.distanceMeters : null,
    image: absUrl(pic?.mediumUrl || pic?.largeUrl || pic?.extraSmallUrl || raw.imageUrls?.[0]),
    url: raw.vipUrl ? absUrl(raw.vipUrl) : `https://link.marktplaats.nl/${id}`,
    seller: raw.sellerInformation?.sellerName || '',
    // Paid promotion: dagtopper or topadvertentie.
    promoted: (!!raw.priorityProduct && raw.priorityProduct !== 'NONE') || traits.some(t => /^DAG_TOPPER/.test(t)),
    // Shop ad from the Admarkt advertising system.
    shop: id.startsWith('a') || traits.includes('ADMARKT_CONSOLE'),
    // Padding: a "similar" listing that does not match the search itself.
    related: raw.searchType === 'kNN',
    date: raw.date || '',
  };
}

// An ordinary private listing that matches the search, ranked by its (bump) date.
export function isOrganic(l) {
  return l.num !== null && !l.promoted && !l.shop && !l.related;
}

const MONTHS = { jan: 0, feb: 1, mrt: 2, apr: 3, mei: 4, jun: 5, jul: 6, aug: 7, sep: 8, okt: 9, nov: 10, dec: 11 };

export function startOfDay(ms) {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

export function daysBefore(ms, n) {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() - n).getTime();
}

// Placement day of a listing (local midnight, ms) from the "date" field, which is
// "Vandaag", "Gisteren", "Eergisteren" or a date like "10 mrt 24". Null if unknown.
export function listingDay(dateStr, now = Date.now()) {
  const raw = String(dateStr || '').trim();
  const s = raw.toLowerCase();
  if (s === 'vandaag') return daysBefore(now, 0);
  if (s === 'gisteren') return daysBefore(now, 1);
  if (s === 'eergisteren') return daysBefore(now, 2);
  const m = s.match(/^(\d{1,2})\s+([a-z]{3})[a-z.]*\s+'?(\d{2}|\d{4})$/);
  if (m && m[2] in MONTHS) {
    const year = m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3]);
    return new Date(year, MONTHS[m[2]], Number(m[1])).getTime();
  }
  const iso = /^\d{4}-\d{2}-\d{2}/.test(raw) ? Date.parse(raw) : NaN;
  return Number.isFinite(iso) ? startOfDay(iso) : null;
}

// Earliest placement day a new listing can have: the day of the previous successful
// check, but never before yesterday (so a closed laptop doesn't bring old listings).
export function gateDay(lastOkAt, now = Date.now()) {
  return Math.max(startOfDay(lastOkAt || now), daysBefore(now, 1));
}

export function excludeWords(w) {
  return String(w.exclude || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}

// The user's own filters on top of the search: shop ads and padding (always), promotions
// (optional), exclude words, and the price range again in case the site loosens its filter.
export function passesFilters(l, w) {
  if (l.shop || l.related) return false;
  if (w.skipAds && l.promoted) return false;
  const title = l.title.toLowerCase();
  if (excludeWords(w).some(word => title.includes(word))) return false;
  if (l.priceCents > 0) {
    const min = toCents(w.priceMin), max = toCents(w.priceMax);
    if (min !== null && l.priceCents < min) return false;
    if (max !== null && l.priceCents > max) return false;
  }
  return true;
}

// Why an unseen listing is not reported as new, or null when it is new.
//   minId:  listings numbered at or below this were placed before the previous check
//   gate:   earliest placement day a new listing can have (see gateDay)
export function rejectReason(l, w, { minId = null, gate = null, now = Date.now() } = {}) {
  if (!passesFilters(l, w)) return 'filtered';
  if (l.num !== null && minId !== null && l.num <= minId) return 'old';
  const day = listingDay(l.date, now);
  if (gate !== null && day !== null && day < gate) return 'old';
  return null;
}

async function fetchPage(w, offset, since) {
  const res = await fetch(buildSearchUrl(w, { offset, since }), {
    headers: { Accept: 'application/json' },
    credentials: 'omit',
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`Marktplaats gaf HTTP ${res.status}`);
  let body;
  try { body = await res.json(); } catch { throw new Error('Marktplaats gaf geen geldige JSON terug'); }
  if (!Array.isArray(body.listings)) throw new Error('Onverwacht antwoord: geen "listings" gevonden');
  const cats = body.searchRequest?.categories || {};
  const l2 = (cats.l2Categories || []).find(c => String(c.id) === String(w.l2));
  return {
    total: body.totalResultCount ?? null,
    // Rows beyond the requested page size are padding, not part of this page.
    listings: body.listings.slice(0, PAGE_SIZE).map(parseListing),
    catKeys: cats.l1Category?.key ? { l1: cats.l1Category.key, l2: l2?.key || '' } : null,
  };
}

// Fetches newest-first pages until it has what it needs:
//   stopAt:     stop once an ordinary listing numbered at or below this shows up
//               (everything after it was already known at the previous check)
//   minOrganic: or once this many ordinary listings were seen
// Stops anyway at the end of the results or after maxPages (then truncated = true).
export async function fetchListings(w, { since = null, stopAt = null, minOrganic = 1, maxPages = MAX_PAGES } = {}) {
  const listings = [];
  const ids = new Set();
  let total = null, catKeys = null, truncated = false;
  for (let page = 0; ; page++) {
    const r = await fetchPage(w, page * PAGE_SIZE, since);
    total ??= r.total;
    catKeys ??= r.catKeys;
    for (const l of r.listings) {
      if (!ids.has(l.id)) { ids.add(l.id); listings.push(l); }
    }
    if (r.listings.length < PAGE_SIZE) break;
    const organic = listings.filter(isOrganic);
    if (stopAt !== null ? organic.some(l => l.num <= stopAt) : organic.length >= minOrganic) break;
    if (page + 1 >= maxPages) { truncated = true; break; }
  }
  return { total, listings, catKeys, truncated };
}

// Condition options (id + label) as the chosen category itself offers them.
export async function fetchConditions(l1, l2) {
  const p = new URLSearchParams({ limit: '1', offset: '0', query: '', viewOptions: 'list-view', l1CategoryId: String(l1) });
  if (l2) p.set('l2CategoryIds', String(l2));
  const res = await fetch(`${API_URL}?${p}`, { headers: { Accept: 'application/json' }, credentials: 'omit' });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = await res.json();
  const facet = (body.facets || []).find(f => f.key === 'condition');
  return (facet?.attributeGroup || [])
    .filter(g => Number.isFinite(g.attributeValueId))
    .map(g => ({ id: g.attributeValueId, label: g.attributeValueLabel || g.attributeValueKey || String(g.attributeValueId) }));
}

const euro = new Intl.NumberFormat('nl-NL', { style: 'currency', currency: 'EUR' });

export function formatPrice(l) {
  const amount = euro.format(l.priceCents / 100);
  switch (l.priceType) {
    case 'FIXED': return amount;
    case 'MIN_BID': return `Bieden vanaf ${amount}`;
    case 'FAST_BID': return 'Bieden';
    case 'FREE': return 'Gratis';
    case 'SEE_DESCRIPTION': return 'Zie omschrijving';
    case 'NOTK': return 'N.o.t.k.';
    case 'RESERVED': return 'Gereserveerd';
    case 'EXCHANGE': return 'Ruilen';
    case 'ON_REQUEST': return 'Op aanvraag';
    default: return l.priceCents > 0 ? amount : '';
  }
}

export function formatDistance(m) {
  if (!m) return '';
  return m < 1000 ? `${m} m` : `${Math.round(m / 1000)} km`;
}

export function timeAgo(ms, now = Date.now()) {
  if (!ms) return 'nog niet';
  const min = Math.floor((now - ms) / 60000);
  if (min < 1) return 'zojuist';
  if (min < 60) return `${min} min geleden`;
  const h = Math.floor(min / 60);
  if (h < 24) return `${h} uur geleden`;
  return new Date(ms).toLocaleString('nl-NL', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
}

// "vandaag", "gisteren" or "17 okt" for a find. The date word was stored relative to
// the moment the listing was found, so it is resolved against foundAt first.
export function placedLabel(f, now = Date.now()) {
  const day = listingDay(f.date, f.foundAt || now);
  if (day === null) return '';
  if (day === startOfDay(now)) return 'vandaag';
  if (day === daysBefore(now, 1)) return 'gisteren';
  return new Date(day).toLocaleDateString('nl-NL', { day: 'numeric', month: 'short' });
}

export function watchLabel(w) {
  return w.name.trim() || w.query.trim() || 'Zoekopdracht';
}

// DOM helper for the popup and options page (not used by the service worker).
export function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter(c => c != null && c !== ''));
  return node;
}
