import React, { useEffect, useMemo, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmtInt, fmtPct } from '../format.js';

const isFiniteNumber = (x) => Number.isFinite(Number(x));
const Metric = ({ label, value, note }) => <div className="stat-card"><div className="label">{label}</div><div className="value">{value}</div><div className="sub">{note}</div></div>;

export default function Briefing({ model, manifest, detail }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    setResult(null); setError(null);
    const request = model.startsWith('paper_lp')
      ? fetchJson(`/api/paper-lp/${model.endsWith('120') ? 'topsis_120' : 'all_candidates'}`)
      : model.startsWith('saa_')
        ? fetchJson(`/api/saa/${model.endsWith('120') ? 'topsis_120' : 'all_candidates'}`)
      : fetchJson(`/api/solutions/${model}`);
    request.then(setResult).catch((e) => setError(e.message));
  }, [model]);

  const stats = useMemo(() => {
    if (!result) return null;
    if (model.startsWith('paper_lp')) {
      const rows = result.scenario_rows ?? [];
      const weighted = (key) => rows.reduce((sum, row) => sum + Number(row.scenario_prob || 0) * Number(row[key] || 0), 0);
      const worst = rows.reduce((a, b) => Number(b.Z1) > Number(a?.Z1 ?? -Infinity) ? b : a, null);
      const used = new Set((result.casualty_allocation ?? []).filter((r) => r.facility_set === 'JT' && Number(r.assigned_casualties) > 0).map((r) => r.facility_id));
      return { served: weighted('served_fraction'), untreated: weighted('Z1'), used: used.size, staff: weighted('staff_added'), worst: worst?.Z1, expected: true };
    }
    if (model.startsWith('saa_')) {
      const rows = result.budget_rows ?? [];
      const row = rows.reduce((a, b) => Number(b.budget) > Number(a?.budget ?? -Infinity) ? b : a, null);
      return row ? { served: Number(row.out_of_sample_expected_served_fraction), untreated: Number(row.out_of_sample_expected_unmet_casualties), used: null, staff: null, budget: row.budget, expected: true } : null;
    }
    const allocations = result.casualty_allocation ?? [];
    const served = allocations.reduce((sum, r) => sum + Number(r.assigned_casualties || 0), 0);
    const used = new Set((result.tmc_selected ?? []).map((r) => r.site_id));
    const staffRows = (result.tmc_selected ?? []).filter((r) => r.staff_assigned != null && r.staff_assigned !== '');
    const staff = staffRows.length ? staffRows.reduce((s, r) => s + Number(r.staff_assigned || 0), 0) : null;
    return { served: null, untreated: null, allocated: served, used: used.size, staff, expected: false };
  }, [result, model]);

  if (error) return <div className="notice">This model result is unavailable: {error}. Select an available model or regenerate its validated export.</div>;
  if (!stats) return <div className="skeleton skeleton-card" />;
  const title = ({ risk_blind: 'Risk-blind MILP', risk_aware: 'Risk-aware MILP', paper_lp_all_candidates: 'Paper LP · all candidates', paper_lp_topsis_120: 'Paper LP · TOPSIS top 120', saa_all_candidates: 'SAA · all candidates', saa_topsis_120: 'SAA · TOPSIS top 120' })[model];
  const statsSource = manifest?.scenarios?.[0]?.name ?? 'Selected validated run';
  return <section>
    <div className="panel callout"><h3>Recommendation · {title}</h3><p className="muted">{model.startsWith('paper_lp') ? `Independent scenario plans serve ${fmtPct(stats.served)} of weighted demand. ${fmtInt(stats.used)} TMC sites receive casualty flow (used; this LP has no site-opening decision).` : model.startsWith('saa_') ? `At the largest exported budget (${stats.budget}), out-of-sample expected service is ${fmtPct(stats.served)}.` : `The selected deterministic plan assigns ${fmtInt(stats.allocated)} casualties across facilities and selects ${fmtInt(stats.used)} TMCs.`} Review the supporting evidence in the siting, medical response, and robustness views.</p></div>
    <div className="cards">
      <Metric label={stats.expected ? 'Expected demand served' : 'Casualties allocated'} value={stats.expected ? fmtPct(stats.served) : fmtInt(stats.allocated)} note={stats.expected ? 'Probability weighted or out-of-sample' : 'Single deterministic result'} />
      <Metric label={stats.expected ? 'Expected untreated' : 'Untreated demand'} value={isFiniteNumber(stats.untreated) ? fmtInt(stats.untreated) : 'Unavailable'} note={stats.expected ? 'T1 (most severe), T2, T3' : 'Not exported for this MILP run'} />
      <Metric label={model.startsWith('paper_lp') ? 'TMCs used' : 'TMCs selected'} value={stats.used == null ? 'Unavailable' : fmtInt(stats.used)} note={model.startsWith('paper_lp') ? 'Positive casualty flow; no explicit opening variable' : 'Site decision in exported run'} />
      <Metric label="Additional staff" value={stats.staff == null ? 'Unavailable' : fmtInt(stats.staff)} note="As reported by this run" />
    </div>
    <div className="cards">
      <div className="panel"><h3>Run context</h3><p className="muted">{statsSource}</p><p className="muted">Data generated: {manifest?.generated_utc ?? 'not recorded'}</p></div>
      <div className="panel"><h3>Decision notes</h3><p className="muted">Untreated means demand the selected model did not allocate to treatment. Facility occupancy, capacity saturation and health-state transitions are unavailable in the exported results.</p></div>
    </div>
    {detail === 'research' && <details open><summary>Objective values and run detail</summary><div className="panel"><p className="muted">{stats.expected && model.startsWith('paper_lp') ? `Probability-weighted Z1: ${fmtInt(stats.untreated)} · Worst scenario Z1: ${fmtInt(stats.worst)} · Z2/Z3 are available in Medical Response.` : 'Objective values, solver metadata, and processing metrics are only shown when the selected export supplies them.'}</p><p className="muted">Run identifier: {manifest?.data_source?.job_id ?? 'reference bundle'} · Model: {model}</p></div></details>}
  </section>;
}
