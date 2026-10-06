import React, { useEffect, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmtInt, fmtPct } from '../format.js';

function summary(data, kind) {
  if (kind === 'paper_lp') {
    const rows = data.scenario_rows ?? [];
    const weighted = (key) => rows.reduce((s, r) => s + Number(r.scenario_prob || 0) * Number(r[key] || 0), 0);
    const used = new Set((data.casualty_allocation ?? []).filter((r) => r.facility_set === 'JT' && Number(r.assigned_casualties) > 0).map((r) => r.facility_id));
    return { service: weighted('served_fraction'), unmet: weighted('Z1'), sites: used.size, siteIds: used };
  }
  const row = (data.budget_rows ?? []).reduce((a, b) => Number(b.budget) > Number(a?.budget ?? -Infinity) ? b : a, null);
  return row ? { service: Number(row.out_of_sample_expected_served_fraction), unmet: Number(row.out_of_sample_expected_unmet_casualties), sites: null, budget: row.budget, siteIds: new Set() } : null;
}

export default function ProfileComparison({ model }) {
  const kind = model.startsWith('paper_lp') ? 'paper_lp' : 'saa';
  const [data, setData] = useState(null); const [error, setError] = useState(null);
  useEffect(() => {
    setData(null); setError(null);
    const endpoint = kind === 'paper_lp' ? (p) => `/api/paper-lp/${p}` : (p) => `/api/saa/${p}`;
    Promise.all(['topsis_120', 'all_candidates'].map((p) => fetchJson(endpoint(p))))
      .then(([screened, all]) => setData({ screened: summary(screened, kind), all: summary(all, kind) }))
      .catch((e) => setError(e.message));
  }, [kind]);
  if (error) return <div className="notice">Screened-versus-all comparison unavailable: {error}. Both validated profile exports are required.</div>;
  if (!data) return <div className="skeleton skeleton-card" />;
  const delta = (key) => data.screened?.[key] == null || data.all?.[key] == null ? 'Unavailable' : fmtInt(data.screened[key] - data.all[key]);
  const shown = data.screened?.siteIds ?? new Set(); const other = data.all?.siteIds ?? new Set();
  const added = [...shown].filter((s) => !other.has(s)).length; const removed = [...other].filter((s) => !shown.has(s)).length;
  return <section>
    <div className="panel callout"><h3>{kind === 'paper_lp' ? 'Paper LP · TOPSIS screening comparison' : 'SAA · TOPSIS screening comparison'}</h3><p className="muted">Paired exported runs: screened TOPSIS top 120 versus all prepared candidates. Outcomes are shown at the highest exported budget for SAA.</p></div>
    <div className="compare-cols">{[['screened', 'TOPSIS top 120'], ['all', 'All candidates']].map(([key, label]) => <article className="panel" key={key}><h3>{label}</h3><dl className="metric-list"><div className="metric-row"><dt>Demand served</dt><dd>{data[key] ? fmtPct(data[key].service) : 'Unavailable'}</dd></div><div className="metric-row"><dt>Untreated casualties</dt><dd>{data[key] ? fmtInt(data[key].unmet) : 'Unavailable'}</dd></div><div className="metric-row"><dt>{kind === 'paper_lp' ? 'TMCs used (positive flow)' : 'Budget'}</dt><dd>{data[key]?.sites == null ? data[key]?.budget ?? 'Unavailable' : fmtInt(data[key].sites)}</dd></div></dl></article>)}</div>
    <div className="panel" style={{ marginTop: 'var(--space-4)' }}><h3>Screened minus all candidates</h3><dl className="metric-list"><div className="metric-row"><dt>Service difference</dt><dd>{data.screened && data.all ? `${fmtPct(data.screened.service - data.all.service)}` : 'Unavailable'}</dd></div><div className="metric-row"><dt>Untreated difference</dt><dd>{delta('unmet')}</dd></div>{kind === 'paper_lp' && <div className="metric-row"><dt>Used site-set changes</dt><dd>{added} only in screened · {removed} only in all-candidate plan</dd></div>}</dl><p className="muted">Paper LP sites are described as used because they receive flow; the LP has no explicit site-opening decision.</p></div>
  </section>;
}
