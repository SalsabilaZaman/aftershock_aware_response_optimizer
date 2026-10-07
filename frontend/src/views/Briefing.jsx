import React, { useEffect, useMemo, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmt, fmtInt, fmtPct } from '../format.js';

const Metric = ({ label, value, note }) => <div className="stat-card"><div className="label">{label}</div><div className="value">{value}</div><div className="sub">{note}</div></div>;
const sum = (rows, key) => rows.reduce((total, row) => total + Number(row[key] || 0), 0);
const weighted = (rows, key) => rows.reduce((total, row) => total + Number(row.scenario_prob || 0) * Number(row[key] || 0), 0);
function allocationStats(rows) {
  const total = sum(rows, 'assigned_casualties');
  if (!total) return { total: null, avg: null, over30: null };
  return {
    total,
    avg: rows.reduce((s, r) => s + Number(r.distance_km || 0) * Number(r.assigned_casualties || 0), 0) / total,
    over30: rows.filter((r) => Number(r.distance_km) > 30).reduce((s, r) => s + Number(r.assigned_casualties || 0), 0) / total,
  };
}

export default function Briefing({ model, candidateSet = 'all_candidates', manifest, detail }) {
  const [data, setData] = useState(null); const [error, setError] = useState(null);
  useEffect(() => {
    let alive = true; setData(null); setError(null);
    const optional = (path) => fetchJson(path).catch(() => null);
    Promise.all([
      optional('/api/sites'), optional('/api/demand_points'), optional('/api/hospitals'), optional('/api/site_status'),
      optional('/api/solutions/risk_blind'), optional('/api/solutions/risk_aware'), optional(`/api/saa/${candidateSet}`), optional(`/api/paper-lp/${candidateSet}`),
    ]).then(([sites, demand, hospitals, status, blind, aware, saa, paper]) => {
      if (alive) setData({ sites, demand, hospitals, status, blind, aware, saa, paper });
    });
    return () => { alive = false; };
  }, [candidateSet]);

  const siteById = useMemo(() => Object.fromEntries((data?.sites ?? []).map((s) => [s.site_id, s])), [data]);
  const comparison = useMemo(() => {
    if (!data || !data.blind || !data.aware) return null;
    const deterministic = (result, mode) => {
      const allocations = result.casualty_allocation ?? []; const selected = result.tmc_selected ?? [];
      const allocation = allocationStats(allocations);
      return { sites: selected.length, unsafe: mode === 'risk_blind' ? (data.sites ? selected.filter((r) => Number(siteById[r.site_id]?.PGA_representative_g) > 0.2).length : null) : 0,
        avg: allocation.avg, over30: allocation.over30, t1: null, total: allocation.total };
    };
    const saaRows = data.saa?.budget_rows ?? [];
    const target = saaRows.find((r) => Number(r.budget) === 25) ?? saaRows.reduce((best, r) => Number(r.budget) < Number(best?.budget ?? Infinity) ? r : best, null);
    const saaSites = (data.saa?.policy_sites ?? []).filter((r) => Number(r.budget) === Number(target?.budget));
    const saaDemand = target ? Number(target.out_of_sample_expected_unmet_casualties) / Math.max(1e-9, 1 - Number(target.out_of_sample_expected_served_fraction)) : null;
    return {
      blind: deterministic(data.blind, 'risk_blind'), aware: deterministic(data.aware, 'risk_aware'),
      saa: { sites: data.saa?.policy_sites ? new Set(saaSites.map((r) => r.site_id)).size : null,
        unsafe: data.sites && target ? new Set(saaSites.filter((r) => Number(siteById[r.site_id]?.PGA_representative_g) > 0.2).map((r) => r.site_id)).size : null,
        avg: null, over30: null, t1: null, total: saaDemand },
      swaps: data.status ? data.status.filter((r) => r.blind_pick_unsafe && !r.selected_risk_aware).length : null,
      saaBudget: target?.budget,
      paperTotal: data.paper ? weighted(data.paper.scenario_rows ?? [], 'Z1') + (data.paper.scenario_rows ?? []).reduce((total, row) => {
        const served = (data.paper.casualty_allocation ?? []).filter((a) => String(a.scenario_id) === String(row.scenario_id)).reduce((s, a) => s + Number(a.assigned_casualties || 0), 0);
        return total + Number(row.scenario_prob || 0) * served;
      }, 0) : null,
    };
  }, [data, siteById]);

  const stats = useMemo(() => {
    if (!data) return null;
    if (model === 'risk_blind' || model === 'risk_aware') {
      const current = model === 'risk_blind' ? comparison?.blind : comparison?.aware;
      return current ? { total: current.total, sites: current.sites, unsafe: current.unsafe, avg: current.avg, over30: current.over30,
        service: null, unmet: null, t1: null, detail: `${fmtInt(current.sites)} TMC sites selected` } : null;
    }
    const lp = model === 'paper_lp';
    if (lp) {
      const rows = data.paper?.scenario_rows ?? [];
      const t1 = (data.paper?.unmet_by_triage ?? []).filter((r) => r.triage === 'T1')
        .reduce((total, r) => total + Number(rows.find((s) => String(s.scenario_id) === String(r.scenario_id))?.scenario_prob || 0) * Number(r.unmet_casualties || 0), 0);
      const used = new Set((data.paper?.casualty_allocation ?? []).filter((r) => Number(r.assigned_casualties) > 0 &&
        (r.facility_set === 'JT' || String(r.facility_id ?? '').startsWith('JT_') || !String(r.facility_id ?? '').startsWith('JH_')))
        .map((r) => String(r.facility_id ?? '').replace(/^JT_/, '')).filter(Boolean));
      return { total: comparison.paperTotal, sites: used.size, service: weighted(rows, 'served_fraction'), unmet: weighted(rows, 'Z1'), t1,
        detail: 'Independent scenario plans use scenario-weighted demand and have no shared site-opening decision.' };
    }
    const result = data.saa;
    const rows = result?.budget_rows ?? [];
    const row = rows.find((r) => Number(r.budget) === 25) ?? rows.reduce((a, b) => Number(b.budget) > Number(a?.budget ?? -Infinity) ? b : a, null);
    if (!row) return { total: null, sites: null, service: null, unmet: null, detail: 'SAA results are unavailable in this bundle.' };
    const total = Number(row.out_of_sample_expected_unmet_casualties) / Math.max(1e-9, 1 - Number(row.out_of_sample_expected_served_fraction));
    const policySites = (result.policy_sites ?? []).filter((r) => Number(r.budget) === Number(row.budget));
    const sites = policySites.length ? new Set(policySites.map((r) => r.site_id)).size : Number(row.budget);
    return { total, sites, service: Number(row.out_of_sample_expected_served_fraction), unmet: Number(row.out_of_sample_expected_unmet_casualties), t1: null,
      detail: `At the ${row.budget}-site SAA budget, out-of-sample service is ${fmtPct(Number(row.out_of_sample_expected_served_fraction))}. Its shared policy and recourse differ from deterministic assignment.` };
  }, [data, model, comparison]);

  if (error) return <div className="notice">Plan comparison data unavailable: {error}. Regenerate the validated reference export.</div>;
  if (!data || !stats || !comparison) return <div className="skeleton skeleton-card" />;
  const candidateLabel = manifest?.model_labels?.candidate_sets?.[candidateSet] ?? candidateSet;
  const titles = { risk_blind: manifest?.model_labels?.models?.risk_blind ?? 'Risk-blind MILP', risk_aware: manifest?.model_labels?.models?.risk_aware ?? 'Risk-aware MILP', paper_lp: `${manifest?.model_labels?.models?.paper_lp ?? 'Scenario-wise LP'} · ${candidateLabel}`, saa: `SAA · ${candidateLabel}` };
  const columns = [
    ['Plan', null], ['Sites selected', 'sites'], ['Selected sites above 0.2 g', 'unsafe'], ['Average distance', 'avg'], ['Casualties travelling over 30 km', 'over30'], ['Untreated T1', 't1'],
  ];
  const planRows = [['Risk-blind MILP', comparison.blind], ['Risk-aware MILP', comparison.aware], [`SAA · ${comparison.saaBudget}-site budget`, comparison.saa]];
  const num = (key, value, plan) => value == null ? (key === 't1' && plan !== 'SAA' ? 'Not modeled' : 'Unavailable') : key === 'avg' ? `${fmt(value, 1)} km` : key === 'over30' ? fmtPct(value) : fmtInt(value);
  const isExpected = model === 'saa' || model === 'paper_lp';
  const statsSource = manifest?.scenarios?.[0]?.name ?? 'Selected validated run';
  const countDifference = model === 'risk_blind' || model === 'risk_aware'
    ? 'Deterministic MILP assigns all 117,398 projected casualties; its site count reflects area-based capacity and the opening penalty. SAA is a separate stochastic model that selects under a fixed site budget and evaluates out-of-sample demand.'
    : model === 'saa' ? 'SAA total is inferred from expected unmet casualties and service fraction at the selected budget. Deterministic MILP uses a fixed 117,398-casualty projection; SAA evaluates scenario-based demand with recourse.'
      : 'Scenario-wise LP uses scenario-specific demand (about 174,000 expected casualties) and has no first-stage site-opening decision; deterministic MILP allocates the fixed 117,398-casualty projection.';

  return <section>
    <div className="panel callout"><h3>Compare plans</h3><p className="muted">Side-by-side outcome measures. The deterministic safety screen excludes 34 TMC candidates above 0.2 g; {comparison.swaps == null ? 'site swap count unavailable' : `${comparison.swaps} sites are swapped out for safety`}. SAA is shown at its {comparison.saaBudget ?? 'available'}-site budget.</p>
      <div className="table-scroll"><table className="data"><thead><tr>{columns.map(([label]) => <th key={label}>{label}</th>)}</tr></thead><tbody>{planRows.map(([name, row]) => <tr key={name}><th scope="row">{name}</th>{columns.slice(1).map(([, key]) => <td key={key}>{num(key, row[key], name.startsWith('SAA') ? 'SAA' : 'MILP')}</td>)}</tr>)}</tbody></table></div>
      <p className="muted">SAA exports a 25-site policy and expected service/unmet outcomes. Its detailed travel and triage file is one recorded recourse draw, so those measures are unavailable as like-for-like expectations. T1 is not modeled in either deterministic MILP.</p>
    </div>
    <div className="panel callout"><h3>Plan summary · {titles[model]}</h3><p className="muted">{stats.detail}</p></div>
    <div className="cards">
      {stats.service != null && <Metric label="Expected demand served" value={fmtPct(stats.service)} note="Out-of-sample validation" />}
      {stats.t1 != null && <Metric label="Critical (T1) casualties untreated" value={fmtInt(stats.t1)} note="T1 routing is hospital-only within 12 km" />}
      {stats.unmet != null && <Metric label="Expected untreated" value={fmtInt(stats.unmet)} note="All triage levels" />}
      {stats.avg != null && <Metric label="Average distance" value={`${fmt(stats.avg, 1)} km`} note="Casualty-weighted" />}
      {stats.over30 != null && <Metric label="Casualties travelling over 30 km" value={fmtPct(stats.over30)} note="Share of allocated casualties" />}
      {stats.unsafe != null && <Metric label="Selected sites above 0.2 g" value={fmtInt(stats.unsafe)} note="Representative PGA screen" />}
      {stats.sites != null && <Metric label={model === 'paper_lp' ? 'TMC sites used' : 'TMC sites selected'} value={fmtInt(stats.sites)} note={model === 'paper_lp' ? 'Receive positive flow; no opening decision' : 'Facility opening/site budget'} />}
      <Metric label="Total expected casualties" value={stats.total == null ? 'Unavailable' : fmtInt(stats.total)} note={isExpected ? 'Expected across scenarios or validation draws' : 'Fixed deterministic demand projection'} />
    </div>
    <div className="cards"><div className="panel"><h3>Why totals and site counts differ</h3><p className="muted">{countDifference}</p></div><div className="panel"><h3>Opening-penalty sensitivity</h3><p className="muted">At the reference penalty of 1,000 casualty-km per TMC, the deterministic runs open 377 risk-blind or 387 risk-aware sites. In the existing 100–10,000 sweep, that ranges from 426 to 274 sites for risk-blind and 439 to 284 for risk-aware. These are optimization choices under a stated penalty, not a staffing commitment.</p></div></div>
    {model === 'paper_lp' && <div className="notice info">Medical response shows 30,055 critical (T1) casualties untreated. T1 routing is hospital-only within 12 km, so adding TMCs does not change the T1 result.</div>}
    <div className="cards"><div className="panel"><h3>Run context</h3><p className="muted">{statsSource}</p><p className="muted">Data generated: {manifest?.generated_utc ?? 'not recorded'}</p></div><div className="panel"><h3>Decision notes</h3><p className="muted">Untreated means demand the selected model did not allocate to treatment. Facility occupancy and health-state transitions are not included in the deterministic export.</p></div></div>
    {detail === 'research' && <details open><summary>Run identifiers and provenance</summary><p className="muted">Run identifier: {manifest?.data_source?.job_id ?? 'reference bundle'} · Model: {model}</p></details>}
  </section>;
}
