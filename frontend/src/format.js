// Shared number/text formatting so every view renders numbers the same way
// (thousands separators, consistent decimals, explicit units) instead of the
// previous ad hoc fmt() calls scattered per view.

export function fmt(v, digits = 2) {
  return v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(digits);
}

export function fmtInt(v) {
  return v == null || Number.isNaN(v) ? '—' : Math.round(Number(v)).toLocaleString();
}

// "29 Jul 2026" — short human date for chrome (badges); full ISO timestamp
// stays available for a tooltip/drawer rather than being shown twice.
export function fmtShortDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function fmtDistanceKm(v) {
  return v == null || Number.isNaN(v) ? '—' : `${Number(v).toFixed(1)} km`;
}

// Probability as a percentage everywhere (previously 0.258 and 39.4% coexisted).
export function fmtPct(v, digits = 1) {
  return v == null || Number.isNaN(v) ? '—' : `${(Number(v) * 100).toFixed(digits)}%`;
}

// Compact form with an explicit unit — never render a bare unlabeled number.
// e.g. fmtCompact(3577810, 'casualty-km') -> "3.58M casualty-km"
export function fmtCompact(v, unit) {
  if (v == null || Number.isNaN(v)) return '—';
  const n = Number(v);
  const abs = Math.abs(n);
  let short;
  if (abs >= 1e6) short = `${(n / 1e6).toFixed(2)}M`;
  else if (abs >= 1e3) short = `${(n / 1e3).toFixed(1)}k`;
  else short = n.toFixed(0);
  return unit ? `${short} ${unit}` : short;
}

// 43% of candidate sites (344/804) have no OSM `name` tag and were exported
// with a generated Site_<n> placeholder. Rather than show that name-shaped
// but fabricated-looking string, fall back to the real site ID plainly —
// it's already how every other unnamed/ambiguous reference in this app
// (facility IDs in tables, tooltips) is shown, so it reads as "this is the
// identifier" rather than a synthetic name.
const PLACEHOLDER_NAME = /^Site_\d+$/;

export function displaySiteName(site) {
  const name = site?.name;
  if (!name || PLACEHOLDER_NAME.test(name)) {
    return site?.site_id ?? '?';
  }
  return name;
}

export function isPlaceholderName(name) {
  return !name || PLACEHOLDER_NAME.test(name);
}

// Minimal CSV export — values are stringified and comma/quote-escaped.
export function downloadCsv(filename, columns, rows) {
  const escape = (v) => {
    const s = v == null ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const header = columns.map((c) => escape(c.label)).join(',');
  const body = rows.map((r) => columns.map((c) => escape(c.value(r))).join(',')).join('\n');
  const blob = new Blob([`${header}\n${body}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
