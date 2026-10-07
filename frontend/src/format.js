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

const PLACEHOLDER_NAME = /^Site_\d+$/;

const TYPE_LABELS = {
  social_facility: 'Social facility', community_centre: 'Community centre',
  school: 'School', hospital: 'Hospital', sports_centre: 'Sports centre',
  place_of_worship: 'Place of worship', stadium: 'Stadium', college: 'College',
  university: 'University', clinic: 'Clinic', shelter: 'Shelter',
};

export function displayFacilityType(type) {
  if (!type) return 'Facility';
  return TYPE_LABELS[type] ?? String(type).replaceAll('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function displaySiteName(site, demandPoints = []) {
  if (site?.display_name) return site.display_name;
  const name = site?.name;
  if (name && !PLACEHOLDER_NAME.test(name)) return name;
  if (site?.site_id && Number.isFinite(Number(site.latitude)) && Number.isFinite(Number(site.longitude)) && demandPoints.length) {
    const nearest = demandPoints.reduce((best, demand) => {
      const dLat = Number(demand.latitude) - Number(site.latitude);
      const dLon = Number(demand.longitude) - Number(site.longitude);
      const distance = dLat * dLat + dLon * dLon;
      return !best || distance < best.distance ? { name: demand.name, distance } : best;
    }, null);
    if (nearest?.name) return `${displayFacilityType(site.facility_type)} near ${nearest.name} (${site.site_id})`;
  }
  return site?.site_id ?? '?';
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
