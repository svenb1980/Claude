// Shared logic for the background worker, popup and options page.
//
// Marktplaats has no public API for searching listings. The website itself loads its
// search results from /lrp/api/search (JSON, no key). The parameters below mirror the
// ones the site sends; they are the same ones the open-source marktplaats-py client
// uses (github.com/jensjeflensje/marktplaats-py).

export const API_URL = 'https://www.marktplaats.nl/lrp/api/search';
export const SITE_URL = 'https://www.marktplaats.nl';
export const PAGE_SIZE = 30;

export const DEFAULT_SETTINGS = {
  intervalMin: 5,       // minutes between checks
  notify: true,         // desktop notifications
  maxNotify: 3,         // per search per check; more becomes one summary notification
};

// attributesById values for the condition filter (same ids in every category).
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
    skipAds: true,
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

export function buildSearchUrl(w, limit = PAGE_SIZE) {
  const p = new URLSearchParams({
    limit: String(limit),
    offset: '0',
    query: w.query.trim(),
    searchInTitleAndDescription: w.inDescription ? 'true' : 'false',
    viewOptions: 'list-view',
    sortBy: 'SORT_INDEX',        // newest first
    sortOrder: 'DECREASING',
    postcode: w.postcode ? normalizePostcode(w.postcode) : '',
    distanceMeters: w.postcode && w.distanceKm ? String(Number(w.distanceKm) * 1000) : '1000000',
  });
  if (w.l1) p.set('l1CategoryId', String(w.l1));
  if (w.l1 && w.l2) p.set('l2CategoryIds', String(w.l2));
  const min = toCents(w.priceMin), max = toCents(w.priceMax);
  if (min !== null || max !== null) p.append('attributeRanges[]', `PriceCents:${min ?? 'null'}:${max ?? 'null'}`);
  for (const c of w.conditions || []) p.append('attributesById[]', String(c));
  return `${API_URL}?${p}`;
}

// The same search on the website, for "open on Marktplaats". Only for searches with a
// query: category pages use text slugs in the URL that we don't have.
export function websiteUrl(w) {
  if (!w.query.trim()) return null;
  const q = encodeURIComponent(w.query.trim()).replace(/%20/g, '+');
  const f = ['sortBy:SORT_INDEX', 'sortOrder:DECREASING'];
  const min = toCents(w.priceMin), max = toCents(w.priceMax);
  if (min !== null) f.push(`PriceCentsFrom:${min}`);
  if (max !== null) f.push(`PriceCentsTo:${max}`);
  if (w.postcode) f.push(`postcode:${normalizePostcode(w.postcode)}`);
  if (w.postcode && w.distanceKm) f.push(`distanceMeters:${Number(w.distanceKm) * 1000}`);
  return `${SITE_URL}/q/${q}/#${f.join('|')}`;
}

// Fingerprint of everything that changes which listings come back. When it changes,
// the next check starts over with a fresh baseline instead of reporting old listings.
export function searchKey(w) {
  return JSON.stringify([
    w.query.trim().toLowerCase(), w.l1, w.l2, toCents(w.priceMin), toCents(w.priceMax),
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
  return {
    id: raw.itemId,
    title: raw.title || '(geen titel)',
    description: raw.description || '',
    priceCents: raw.priceInfo?.priceCents ?? 0,
    priceType: raw.priceInfo?.priceType || 'UNKNOWN',
    city: loc.cityName || '',
    distanceM: loc.distanceMeters > 0 ? loc.distanceMeters : null,
    image: absUrl(pic?.mediumUrl || pic?.largeUrl || pic?.extraSmallUrl || raw.imageUrls?.[0]),
    url: raw.vipUrl ? absUrl(raw.vipUrl) : `https://link.marktplaats.nl/${raw.itemId}`,
    seller: raw.sellerInformation?.sellerName || '',
    ad: !!raw.priorityProduct && raw.priorityProduct !== 'NONE',
    date: raw.date || '',
  };
}

const MONTHS = { jan: 0, feb: 1, mrt: 2, apr: 3, mei: 4, jun: 5, jul: 6, aug: 7, sep: 8, okt: 9, nov: 10, dec: 11 };

export function startOfDay(ms) {
  const d = new Date(ms);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

// Placement day of a listing (local midnight, ms) from the "date" field, which is
// "Vandaag", "Gisteren", "Eergisteren" or a date like "10 mrt 24". Null if unknown.
export function listingDay(dateStr, now = Date.now()) {
  const raw = String(dateStr || '').trim();
  const s = raw.toLowerCase();
  const today = new Date(startOfDay(now));
  const daysAgo = n => new Date(today.getFullYear(), today.getMonth(), today.getDate() - n).getTime();
  if (s === 'vandaag') return daysAgo(0);
  if (s === 'gisteren') return daysAgo(1);
  if (s === 'eergisteren') return daysAgo(2);
  const m = s.match(/^(\d{1,2})\s+([a-z]{3})[a-z.]*\s+'?(\d{2}|\d{4})$/);
  if (m && m[2] in MONTHS) {
    const year = m[3].length === 2 ? 2000 + Number(m[3]) : Number(m[3]);
    return new Date(year, MONTHS[m[2]], Number(m[1])).getTime();
  }
  const iso = /^\d{4}-\d{2}-\d{2}/.test(raw) ? Date.parse(raw) : NaN;
  return Number.isFinite(iso) ? startOfDay(iso) : null;
}

export function excludeWords(w) {
  return String(w.exclude || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}

// Client-side filters on top of the search: exclude words, paid ads, and the price
// range again in case the site loosens its own filter.
export function passesFilters(l, w) {
  if (w.skipAds && l.ad) return false;
  const title = l.title.toLowerCase();
  if (excludeWords(w).some(word => title.includes(word))) return false;
  if (l.priceCents > 0) {
    const min = toCents(w.priceMin), max = toCents(w.priceMax);
    if (min !== null && l.priceCents < min) return false;
    if (max !== null && l.priceCents > max) return false;
  }
  return true;
}

export async function fetchListings(w, limit = PAGE_SIZE) {
  const res = await fetch(buildSearchUrl(w, limit), {
    headers: { Accept: 'application/json' },
    credentials: 'omit',
    cache: 'no-store',
  });
  if (!res.ok) throw new Error(`Marktplaats gaf HTTP ${res.status}`);
  let body;
  try { body = await res.json(); } catch { throw new Error('Marktplaats gaf geen geldige JSON terug'); }
  if (!Array.isArray(body.listings)) throw new Error('Onverwacht antwoord: geen "listings" gevonden');
  return { total: body.totalResultCount ?? null, listings: body.listings.map(parseListing) };
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

export function watchLabel(w) {
  return w.name.trim() || w.query.trim() || 'Zoekopdracht';
}

// DOM helper for the popup and options page (not used by the service worker).
export function el(tag, props = {}, ...children) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children.filter(c => c != null && c !== ''));
  return node;
}
