import React, { useEffect, useMemo, useState } from 'react';
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { fetchJson } from '../api.js';
import { fmt, fmtInt } from '../format.js';
import SortableTable from '../components/SortableTable.jsx';

const pct = (value) => value == null ? 'N/A' : `${fmt(value * 100, 1)}%`;

export default function PaperLPResults({ profile = 'all_candidates', scenarioId = 'all', onScenarioChange = () => {}, detail = 'planner' }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const query = scenarioId === 'all' ? '' : `?scenario_id=${encodeURIComponent(scenarioId)}`;
    fetchJson(`/api/paper-lp/${profile}${query}`).then(setResult).catch((e) => setError(e.message));
  }, [profile, scenarioId]);

  const unmetRows = useMemo(() => {
    if (!result) return [];
    const totals = new Map();
    const probabilities = new Map(result.scenario_rows.map((row) => [row.scenario_id, row.scenario_prob]));
    result.unmet_by_triage.forEach((row) => {
      const next = totals.get(row.triage) ?? 0;
      const weight = scenarioId === 'all' ? (probabilities.get(row.scenario_id) ?? 0) : 1;
      totals.set(row.triage, next + weight * row.unmet_casualties);
    });
    return ['T1', 'T2', 'T3'].map((triage) => ({ triage, unmet: totals.get(triage) ?? 0 }));
  }, [result, scenarioId]);

  if (error) return <div className="notice">Paper-style LP results are unavailable in this published reference snapshot: {error}.</div>;
  if (!result) return <div className="skeleton skeleton-card" />;

  const rows = result.scenario_rows.filter((r) => scenarioId === 'all' || String(r.scenario_id) === String(scenarioId));
  const weighted = (key) => scenarioId === 'all'
    ? rows.reduce((sum, row) => sum + row.scenario_prob * (row[key] ?? 0), 0)
    : Number(rows[0]?.[key] ?? 0);
  const worst = [...rows].sort((a, b) => b.Z1 - a.Z1)[0];
  const scenarioColumns = [
    { key: 'scenario_id', label: 'Scenario', value: (r) => r.scenario_id, align: 'right', sortValue: (r) => r.scenario_id },
    { key: 'scenario_prob', label: 'Probability', value: (r) => pct(r.scenario_prob), align: 'right', sortValue: (r) => r.scenario_prob },
    { key: 'Z1', label: 'Z1 · unmet', value: (r) => fmtInt(r.Z1), align: 'right', sortValue: (r) => r.Z1 },
    { key: 'Z2', label: 'Z2 · travel', value: (r) => fmtInt(r.Z2), align: 'right', sortValue: (r) => r.Z2 },
    { key: 'Z3', label: 'Z3 · staff', value: (r) => fmt(r.Z3, 2), align: 'right', sortValue: (r) => r.Z3 },
    { key: 'served_fraction', label: 'Served', value: (r) => pct(r.served_fraction), align: 'right', sortValue: (r) => r.served_fraction },
    { key: 'tmcs_with_casualties_or_staff', label: 'TMCs used', value: (r) => fmtInt(r.tmcs_with_casualties_or_staff), align: 'right', sortValue: (r) => r.tmcs_with_casualties_or_staff },
    { key: 'staff_added', label: 'Staff added', value: (r) => fmt(r.staff_added, 1), align: 'right', sortValue: (r) => r.staff_added },
  ];
  const allocationColumns = Object.keys(result.casualty_allocation[0] ?? {}).map((key) => ({
    key, label: key.replaceAll('_', ' '), value: (r) => r[key] ?? '—',
    align: typeof result.casualty_allocation[0]?.[key] === 'number' ? 'right' : 'left', sortValue: (r) => r[key],
  }));
  const staffingColumns = Object.keys(result.staffing_plan[0] ?? {}).map((key) => ({
    key, label: key.replaceAll('_', ' '), value: (r) => r[key] ?? '—',
    align: typeof result.staffing_plan[0]?.[key] === 'number' ? 'right' : 'left', sortValue: (r) => r[key],
  }));

  return (
    <section>
      <div className="panel callout" style={{ marginBottom: 'var(--space-4)' }}>
        <h3>Paper-style scenario-wise LP</h3>
        <p className="muted">
          Independent continuous LPs across {rows.length} scenarios, solved lexicographically with HiGHS.
          All hospitals and candidate TMCs are available; location decisions are not shared across scenarios.
          The SAA budget sweep remains a separate view.
        </p>
      </div>
      <div className="filter-row"><label>Scenario: <select className="scenario" value={scenarioId} onChange={(e) => onScenarioChange(e.target.value)}><option value="all">All scenarios (probability weighted)</option>{result.scenario_rows.map((r) => <option key={r.scenario_id} value={r.scenario_id}>Scenario {r.scenario_id} · {pct(r.scenario_prob)} probability</option>)}</select></label></div>
      <div className="cards">
        <div className="stat-card"><div className="label">{scenarioId === 'all' ? 'Probability-weighted served' : 'Scenario demand served'}</div><div className="value">{pct(weighted('served_fraction'))}</div></div>
        <div className="stat-card"><div className="label">{scenarioId === 'all' ? 'Expected untreated · Z1' : 'Untreated · Z1'}</div><div className="value">{fmtInt(weighted('Z1'))}</div></div>
        <div className="stat-card"><div className="label">{scenarioId === 'all' ? 'Expected travel burden · Z2' : 'Travel burden · Z2'}</div><div className="value">{fmtInt(weighted('Z2'))}</div></div>
        <div className="stat-card"><div className="label">{scenarioId === 'all' ? 'Expected added staff · Z3' : 'Added staff · Z3'}</div><div className="value">{fmt(weighted('Z3'), 1)}</div></div>
        <div className="stat-card serious"><div className="label">Worst Z1 · scenario {worst?.scenario_id}</div><div className="value">{fmtInt(worst?.Z1)}</div><div className="sub">Served {pct(worst?.served_fraction)}</div></div>
      </div>
      <div className="panel">
        <h3>{scenarioId === 'all' ? 'Probability-weighted' : `Scenario ${scenarioId}`} unmet demand by triage</h3>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={unmetRows} margin={{ top: 12, right: 20, left: 12, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--ink-200)" />
            <XAxis dataKey="triage" /><YAxis /><Tooltip formatter={(value) => fmtInt(value)} />
            <Bar dataKey="unmet" name="Unmet casualties" fill="var(--dist-4)" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <SortableTable columns={scenarioColumns} rows={rows} rowKey={(r) => r.scenario_id}
        csvFilename="paper_lp_scenarios.csv" defaultSort={{ key: 'scenario_id', dir: 'asc' }} />
      <details><summary>Detailed casualty and staffing allocations</summary>
        <h4>Casualty allocation</h4><SortableTable columns={allocationColumns} rows={result.casualty_allocation} rowKey={(r) => `${r.scenario_id ?? ''}-${r.demand_point_id ?? ''}-${r.facility_id ?? ''}-${r.triage ?? ''}`} csvFilename="paper_lp_casualty_allocations.csv" />
        <h4>Staff allocation</h4><SortableTable columns={staffingColumns} rows={result.staffing_plan} rowKey={(r) => `${r.scenario_id ?? ''}-${r.facility_id ?? r.site_id ?? ''}-${r.staff_type ?? ''}`} csvFilename="paper_lp_staffing_allocations.csv" />
      </details>
      {result.sensitivity_rows.length > 0 && (
        <SortableTable
          columns={[
            { key: 'parameter', label: 'Sensitivity parameter', value: (r) => r.parameter },
            { key: 'value', label: 'Value', value: (r) => fmt(r.value, 2), align: 'right', sortValue: (r) => r.value },
            { key: 'metric', label: 'Metric', value: (r) => r.metric },
            { key: 'probability_weighted_value', label: 'Weighted result', value: (r) => fmt(r.probability_weighted_value, 3), align: 'right', sortValue: (r) => r.probability_weighted_value },
          ]}
          rows={result.sensitivity_rows} rowKey={(r) => `${r.parameter}-${r.value}-${r.metric}`}
          csvFilename="paper_lp_sensitivity.csv" defaultSort={{ key: 'parameter', dir: 'asc' }} />
      )}
      {detail === 'research' && <details open><summary>Solver and lexicographic objective details</summary><p className="muted">Solver: HiGHS where recorded. Z1 is unmet demand, Z2 is casualty travel burden, and Z3 is added staff. Scenario status and processing metrics appear only when included in the run export.</p><pre>{JSON.stringify(result.metadata ?? {}, null, 2)}</pre></details>}
    </section>
  );
}
