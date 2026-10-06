// Sequential single-hue-family ramp for P_unsafe (a magnitude, not
// categories): light→dark, monotonic lightness, OrRd-derived and
// colourblind-safe. These hex values are the single source of truth for the
// hazard ramp — styles.css's --hz-* variables are defined to match, kept in
// sync manually since canvas-rendered map markers can't resolve CSS custom
// properties. Light steps get a dark marker stroke so low contrast against
// the basemap never hides a site.
export const P_UNSAFE_BINS = [
  { max: 0.6, color: '#fee8c8', label: '< 0.60' },
  { max: 0.8, color: '#fdbb84', label: '0.60 – 0.80' },
  { max: 0.95, color: '#e34a33', label: '0.80 – 0.95' },
  { max: 0.99, color: '#b30000', label: '0.95 – 0.99' },
  { max: Infinity, color: '#7f0000', label: '≥ 0.99' },
];

export function pUnsafeColor(p) {
  if (p == null || Number.isNaN(p)) return '#9aa1ab'; // no data → gray, never fabricated
  return P_UNSAFE_BINS.find((b) => p < b.max)?.color ?? '#7f0000';
}

// Single-hue sequential ramp for allocation distance (demand point →
// assigned facility), light→dark. The previous green→yellow→orange→red ramp
// was not colourblind-safe; this one is monotonic in one hue.
export const DISTANCE_BINS = [
  { max: 5, color: '#f0f4f5', label: '< 5 km' },
  { max: 15, color: '#b8ced4', label: '5 – 15 km' },
  { max: 30, color: '#7ba3ad', label: '15 – 30 km' },
  { max: 60, color: '#3f7080', label: '30 – 60 km' },
  { max: Infinity, color: '#17323d', label: '≥ 60 km' },
];

export function distanceColor(km) {
  if (km == null || Number.isNaN(km)) return '#9aa1ab';
  return DISTANCE_BINS.find((b) => km < b.max)?.color ?? '#17323d';
}

// Study-area bbox from scenario_manifest.json (south/north/west/east), used
// to keep both maps locked to the Kahramanmaraş/Gaziantep region instead of
// allowing pan/zoom out to a world view.
export const STUDY_BOUNDS = [
  [36.5, 35.5],
  [38.5, 38.5],
];
