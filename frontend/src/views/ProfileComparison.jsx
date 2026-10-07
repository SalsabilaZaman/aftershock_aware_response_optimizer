import React, { useEffect, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmtInt, fmtPct } from '../format.js';

function summary(data, kind) {
  if (kind === 'paper_lp') {
    const rows = data.scenario_rows ?? [];
    const weighted = (key) => rows.reduce((s, r) => s + Number(r.scenario_prob || 0) * Number(r[key] || 0), 0);
    const used = new Set((data.casualty_allocation ?? [])
      .filter((r) => {
        const id = String(r.facility_id ?? r.site_id ?? '');
        return Number(r.assigned_casualties) > 0 && id &&
          (r.facility_set === 'JT' || r.facility_type === 'TMC' || id.startsWith('JT_') || !id.startsWith('JH_'));
      })
      .map((r) => String(r.facility_id ?? r.site_id ?? '').replace(/^JT_/, ''))
      .filter(Boolean));
    return { service: weighted('served_fraction'), unmet: weighted('Z1'), sites: used.size, siteIds: used };
  }
  const row = (data.budget_rows ?? []).reduce((a, b) => Number(b.budget) > Number(a?.budget ?? -Infinity) ? b : a, null);
  return row ? { service: Number(row.out_of_sample_expected_served_fraction), unmet: Number(row.out_of_sample_expected_unmet_casualties), sites: null, budget: row.budget, siteIds: new Set() } : null;
}

export default function ProfileComparison({ model }) {
  const kind = model === 'paper_lp' ? 'paper_lp' : 'saa';
  const [data, setData] = useState(null); const [error, setError] = useState(null);
  useEffect(() => {
    setData(null); setError(null);
    const endpoint = kind === 'paper_lp' ? (p) => `/api/paper-lp/${p}` : (p) => `/api/saa/${p}`;
    let alive = true;
    Promise.all([fetchJson('/api/model-options'), fetchJson(endpoint('all_candidates'))])
      .then(async ([options, all]) => {
        const screenedAvailable = options.choices?.find((choice) => choice.id === kind)?.profiles?.topsis_120?.available;
        if (!screenedAvailable) {
          if (alive) setData({ screened: null, all: summary(all, kind), missingProfile: true });
          return;
        }
        const screened = await fetchJson(endpoint('topsis_120'));
        if (alive) setData({ screened: summary(screened, kind), all: summary(all, kind), missingProfile: false });
      })
      .catch((e) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [kind]);
  if (error) return <div className="notice">Screened-versus-all comparison unavailable: {error}. Both validated profile exports are required.</div>;
  if (!data) return <div className="skeleton skeleton-card" />;
  const delta = (key) => data.screened?.[key] == null || data.all?.[key] == null ? 'Unavailable' : fmtInt(data.screened[key] - data.all[key]);
  const shown = data.screened?.siteIds ?? new Set(); const other = data.all?.siteIds ?? new Set();
  const added = [...shown].filter((s) => !other.has(s)).length; const removed = [...other].filter((s) => !shown.has(s)).length;
  if (data.missingProfile) return <div className="notice info">The paired TOPSIS top-120 SAA result is not included in this published bundle; the all-candidate SAA result remains available.</div>;
  const sameService = kind === 'paper_lp' && Math.abs(data.screened.service - data.all.service) < 0.001;
  const fewerSites = (data.all.sites ?? 0) - (data.screened.sites ?? 0);
  return <section>
    <div className="panel callout"><h3>{kind === 'paper_lp' ? 'Screening comparison' : 'SAA candidate-set comparison'}</h3><p className="muted">{sameService ? `Screening to 120 sites loses no service (${fmtPct(data.screened.service)} either way) and uses ${fmtInt(fewerSites)} fewer sites.` : kind === 'paper_lp' ? `Scenario-wise LP service is ${fmtPct(data.screened.service)} with TOPSIS screening and ${fmtPct(data.all.service)} with all candidates.` : 'Paired exported runs compare the same largest available TMC budget.'}</p></div>
    <div className="compare-cols">{[['screened', 'TOPSIS top 120'], ['all', 'All candidates']].map(([key, label]) => <article className="panel" key={key}><h3>{label}</h3><dl className="metric-list"><div className="metric-row"><dt>Demand served</dt><dd>{data[key] ? fmtPct(data[key].service) : 'Unavailable'}</dd></div><div className="metric-row"><dt>Untreated casualties</dt><dd>{data[key] ? fmtInt(data[key].unmet) : 'Unavailable'}</dd></div><div className="metric-row"><dt>{kind === 'paper_lp' ? 'TMCs used (positive flow)' : 'Budget'}</dt><dd>{data[key]?.sites == null ? data[key]?.budget ?? 'Unavailable' : fmtInt(data[key].sites)}</dd></div></dl></article>)}</div>
    <div className="panel" style={{ marginTop: 'var(--space-4)' }}><h3>Screened minus all candidates</h3><dl className="metric-list"><div className="metric-row"><dt>Service difference</dt><dd>{data.screened && data.all ? `${fmtPct(data.screened.service - data.all.service)}` : 'Unavailable'}</dd></div><div className="metric-row"><dt>Untreated difference</dt><dd>{delta('unmet')}</dd></div>{kind === 'paper_lp' && <div className="metric-row"><dt>Used site-set changes</dt><dd>{added} only in screened · {removed} only in all-candidate plan</dd></div>}</dl><p className="muted">Scenario-wise LP sites are described as used because they receive flow; the model has no explicit site-opening decision.</p></div>
  </section>;
}
