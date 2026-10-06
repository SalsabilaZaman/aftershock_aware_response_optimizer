import React, { useEffect, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmt, fmtInt } from '../format.js';

const cards = [
  ['Risk-blind MILP', 'Select TMC sites and allocate demand without the PGA candidate screen.'],
  ['Risk-aware MILP', 'Select TMC sites from the PGA-filtered candidate set and allocate demand.'],
  ['Paper LP', 'Solve scenario-specific casualty and staffing allocations. A site is “used” when it receives positive flow; the LP does not select openings.'],
  ['SAA', 'Choose a TMC budget policy using sampled scenarios, then evaluate it on exported validation draws.'],
];

export default function ResearchLab({ model, detail, manifest }) {
  const files = manifest?.files ?? {};
  const [result, setResult] = useState(null);
  useEffect(() => {
    setResult(null);
    const request = model.startsWith('paper_lp')
      ? fetchJson(`/api/paper-lp/${model.endsWith('120') ? 'topsis_120' : 'all_candidates'}`)
      : model.startsWith('saa_')
        ? fetchJson(`/api/saa/${model.endsWith('120') ? 'topsis_120' : 'all_candidates'}`)
        : fetchJson(`/api/solutions/${model}`);
    request.then(setResult).catch(() => setResult({ unavailable: true }));
  }, [model]);
  const lpRows = result?.scenario_rows ?? [];
  const weighted = (key) => lpRows.reduce((sum, row) => sum + Number(row.scenario_prob || 0) * Number(row[key] || 0), 0);
  return <section>
    <div className="panel callout"><h3>What the models decide</h3><p className="muted">All figures are read from the exported run bundle. This dashboard does not re-solve models or synthesize missing measures.</p></div>
    <div className="cards">{cards.map(([name, description]) => <article className="panel" key={name}><h3>{name}</h3><p className="muted">{description}</p></article>)}</div>
    <div className="panel"><h3>Objective definitions</h3><dl className="research-objectives"><dt>Z1</dt><dd>Unmet casualties across triage priorities (T1 most severe, then T2 and T3).</dd><dt>Z2</dt><dd>Travel burden from casualty allocations, where supplied.</dd><dt>Z3</dt><dd>Additional medical staff assigned, where supplied.</dd></dl></div>
    <div className="panel" style={{ marginTop: 'var(--space-4)' }}><h3>Selected run · {model}</h3><p className="muted">Generated {manifest?.generated_utc ?? 'date unavailable'} · {manifest?.data_source?.job_id ? `Job ${manifest.data_source.job_id}` : 'Reference export'}</p>
      {detail === 'research' && <>
        <h4>Selected run values</h4>
        {model.startsWith('paper_lp') && result && !result.unavailable ? <p className="muted">Probability weighted: Z1 {fmtInt(weighted('Z1'))} · Z2 {fmt(weighted('Z2'), 2)} · Z3 {fmt(weighted('Z3'), 2)}. Solver status: {lpRows.map((r) => r.solver_status ?? 'not recorded').filter((v, i, a) => a.indexOf(v) === i).join(', ') || 'not recorded'}.</p>
          : model.startsWith('saa_') && result && !result.unavailable ? <p className="muted">Replications: {result.metadata?.replications ?? 'not recorded'} · Validation draws per policy: {result.metadata?.validation_draws_per_policy ?? 'not recorded'} · Budgets: {(result.metadata?.budgets ?? []).join(', ') || 'not recorded'}.</p>
            : <p className="muted">The selected model export does not include objective values or solver/run metadata.</p>}
        <h4>Export inventory</h4><div className="table-scroll"><table className="data"><thead><tr><th>File</th><th>Status</th><th>Rows</th><th>Note</th></tr></thead><tbody>{Object.entries(files).map(([name, v]) => <tr key={name}><td>{name}</td><td>{v.status}</td><td>{v.rows ?? '—'}</td><td>{v.note ?? '—'}</td></tr>)}</tbody></table></div><details><summary>Scenario and validation provenance</summary><pre>{JSON.stringify({ scenarios: manifest?.scenarios, validation: manifest?.validation }, null, 2)}</pre></details></>}
    </div>
    <div className="notice info" style={{ marginTop: 'var(--space-4)' }}>Facility occupancy, period capacity loads and health-state transitions are not included in this published reference snapshot.</div>
  </section>;
}
