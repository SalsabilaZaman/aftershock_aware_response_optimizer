import React, { useEffect, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmt, fmtInt } from '../format.js';
import assumptions from '../../../pipelines/model_assumptions.json';

function AssumptionTable({ items }) {
  return <div className="table-scroll"><table className="data assumption-table"><thead><tr><th>Parameter</th><th>Value</th><th>Meaning</th><th>Source</th></tr></thead>
    <tbody>{items.map((item) => <tr key={item.name}><td>{item.name}</td><td><b>{item.value}</b>{item.unit && item.unit !== '—' ? <div className="muted">{item.unit}</div> : null}</td><td>{item.detail}</td><td><code>{item.source}</code></td></tr>)}</tbody>
  </table></div>;
}

export default function ResearchLab({ model, candidateSet = 'all_candidates', detail, manifest }) {
  const files = manifest?.files ?? {};
  const [result, setResult] = useState(null);
  useEffect(() => {
    setResult(null);
    const request = model === 'paper_lp'
      ? fetchJson(`/api/paper-lp/${candidateSet}`)
      : model === 'saa'
        ? fetchJson(`/api/saa/${candidateSet}`)
        : fetchJson(`/api/solutions/${model}`);
    request.then(setResult).catch(() => setResult({ unavailable: true }));
  }, [model, candidateSet]);
  const modelLabel = manifest?.model_labels?.models?.[model] ?? model;
  const lpRows = result?.scenario_rows ?? [];
  const weighted = (key) => lpRows.reduce((sum, row) => sum + Number(row.scenario_prob || 0) * Number(row[key] || 0), 0);
  return <section>
    <div className="panel" style={{ marginTop: 'var(--space-4)' }}><h3>Selected run · {modelLabel}{['paper_lp', 'saa'].includes(model) ? ` · ${manifest?.model_labels?.candidate_sets?.[candidateSet] ?? candidateSet}` : ''}</h3><p className="muted">Generated {manifest?.generated_utc ?? 'date unavailable'} · {manifest?.data_source?.job_id ? `Job ${manifest.data_source.job_id}` : 'Reference export'}</p>
      {detail === 'research' && <>
        <h4>Selected run values</h4>
        {model === 'paper_lp' && result && !result.unavailable ? <p className="muted">Probability weighted: Z1 {fmtInt(weighted('Z1'))} · Z2 {fmt(weighted('Z2'), 2)} · Z3 {fmt(weighted('Z3'), 2)}. Solver status: {lpRows.map((r) => r.solver_status ?? 'not recorded').filter((v, i, a) => a.indexOf(v) === i).join(', ') || 'not recorded'}.</p>
          : model === 'saa' && result && !result.unavailable ? <p className="muted">Replications: {result.metadata?.replications ?? 'not recorded'} · Validation draws per policy: {result.metadata?.validation_draws_per_policy ?? 'not recorded'} · Budgets: {(result.metadata?.budgets ?? []).join(', ') || 'not recorded'}.</p>
            : <p className="muted">The selected model export does not include objective values or solver/run metadata.</p>}
        <h4>Export inventory</h4><div className="table-scroll"><table className="data"><thead><tr><th>File</th><th>Status</th><th>Rows</th><th>Note</th></tr></thead><tbody>{Object.entries(files).map(([name, v]) => <tr key={name}><td>{name}</td><td>{v.status}</td><td>{v.rows ?? '—'}</td><td>{v.note ?? '—'}</td></tr>)}</tbody></table></div><details><summary>Scenario and validation provenance</summary><pre>{JSON.stringify({ scenarios: manifest?.scenarios, validation: manifest?.validation }, null, 2)}</pre></details></>}
    </div>
    <div className="panel assumptions-panel" style={{ marginTop: 'var(--space-4)' }}>
      <h3>{assumptions.title}</h3>
      <p className="muted">Values below describe the implemented model settings. “Not modeled” means the model does not include that mechanism.</p>
      {assumptions.shared.map((group) => <div key={group.group}>
        <h4>{group.group}</h4><AssumptionTable items={group.items} />
      </div>)}
      <h3 style={{ marginTop: 'var(--space-5)' }}>Assumptions by model</h3>
      {assumptions.models.map((entry) => <details className="assumption-model" key={entry.id} open={entry.id === model}>
        <summary><b>{entry.name}</b><span className="muted"> · {entry.summary}</span></summary>
        <AssumptionTable items={entry.items} />
      </details>)}
    </div>
  </section>;
}
