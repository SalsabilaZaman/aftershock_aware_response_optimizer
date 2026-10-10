import React, { useEffect, useRef, useState } from 'react';
import { backendFetch, getApiBase } from '../api.js';

const STAGES = [
  ['psaha', 'PSAHA hazard steps'],
  ['solve_risk_blind', 'Solve: risk-blind'],
  ['solve_risk_aware', 'Solve: risk-aware'],
  ['allocation_map', 'Allocation map'],
  ['dashboard_export', 'Dashboard export'],
  ['api_export', 'Prepare dashboard data'],
];

const INPUTS = [
  ['data_processed/seismic/aftershock_catalog.csv', 'time_utc, latitude, longitude, magnitude'],
  ['data_processed/sites/candidate_sites.csv', 'site_id, latitude, longitude, facility_type'],
  ['data_processed/sites/site_condition_per_site.csv', 'site_id, vs30_ms'],
  ['data_processed/sites/site_area_per_site.csv', 'site_id, site_area_m2'],
  ['data_processed/casualties/sub_districts_raw.csv', 'sub_district_id, name, population; latitude and longitude recommended'],
  ['data_processed/casualties/casualty_projections.csv', 'sub_district_id, scenario_id, period, T1_count, T2_count, T3_count'],
  ['data_processed/hospitals/hospital_data.csv', 'hospital_id, hospital_name, latitude, longitude, bed_capacity_total'],
];

function displayError(body, fallback) {
  const detail = body?.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.issues) return `${detail.message}:\n• ${detail.issues.join('\n• ')}`;
  return detail?.message || fallback;
}

export default function RunWorkspace({ runId, onSelectRun, onEnterDashboard, onRunComplete }) {
  const [runs, setRuns] = useState([]);
  const [file, setFile] = useState(null);
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState(false);
  const [apiReady, setApiReady] = useState(false);
  const [error, setError] = useState('');
  const pollRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    backendFetch('/api/runs').then((res) => {
      if (!cancelled) setApiReady(res.ok);
    }).catch(() => { if (!cancelled) setApiReady(false); });
    return () => { cancelled = true; };
  }, []);

  const refreshRuns = async () => {
    try {
      const res = await backendFetch('/api/runs');
      if (!res.ok) return;
      const value = await res.json();
      setRuns(value.runs ?? []);
    } catch { /* Reference results remain available without the run service. */ }
  };

  useEffect(() => {
    refreshRuns();
    return () => clearInterval(pollRef.current);
  }, []);

  const poll = (id) => {
    clearInterval(pollRef.current);
    const check = async () => {
      try {
        const res = await backendFetch(`/api/runs/${id}/status`);
        const value = await res.json();
        if (!res.ok) throw new Error(displayError(value, res.statusText));
        setStatus(value);
        if (value.state === 'done' || value.state === 'error') {
          clearInterval(pollRef.current);
          setBusy(false);
          refreshRuns();
          if (value.state === 'done') onRunComplete?.();
        }
      } catch (e) {
        setError(e.message);
        clearInterval(pollRef.current);
        setBusy(false);
      }
    };
    check();
    pollRef.current = setInterval(check, 2000);
  };

  useEffect(() => {
    if (!runId) {
      setStatus(null);
      setBusy(false);
      return;
    }
    let cancelled = false;
    backendFetch(`/api/runs/${runId}/status`).then(async (res) => {
      const value = await res.json();
      if (!res.ok) throw new Error(displayError(value, res.statusText));
      if (cancelled) return;
      setStatus(value);
      if (value.state === 'running' || value.state === 'queued') {
        setBusy(true);
        poll(runId);
      } else if (value.state === 'done') {
        setBusy(false);
        onRunComplete?.();
      }
      refreshRuns();
    }).catch((e) => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; clearInterval(pollRef.current); };
  }, [runId]);

  const startRun = async () => {
    if (!file) return;
    setError('');
    setStatus(null);
    setBusy(true);
    try {
      const body = new FormData();
      body.append('file', file);
      const res = await backendFetch('/api/runs/upload', { method: 'POST', body });
      const value = await res.json();
      if (!res.ok) throw new Error(displayError(value, res.statusText));
      onSelectRun(value.run_id);
      setStatus({ state: 'running', stages: [] });
      refreshRuns();
      poll(value.run_id);
    } catch (e) {
      setError(e.message);
      setBusy(false);
    }
  };

  const stageState = (stage) => {
    const entries = status?.stages?.filter((item) => item.stage === stage) ?? [];
    if (!entries.length) return 'pending';
    if (entries.some((item) => item.status === 'error')) return 'error';
    if (entries.some((item) => item.status === 'running')) return 'running';
    return entries.every((item) => item.status === 'ok') ? 'ok' : 'pending';
  };
  const currentName = runId ? runs.find((item) => item.run_id === runId)?.name ?? runId : 'Kahramanmaraş · February 2023';

  return <div className="run-workspace" aria-label="Saved analyses and new analysis">
    <section className="run-section saved-analysis-section">
    <div className="run-workspace-heading">
      <h2>Open a saved analysis</h2>
      <label className="run-picker" aria-label="Select analysis">
        <select value={runId || 'reference'} onChange={(event) => onSelectRun(event.target.value === 'reference' ? '' : event.target.value)}>
          <option value="reference">Saved reference analysis · Kahramanmaraş, February 2023</option>
          {runs.map((item) => <option value={item.run_id} key={item.run_id}>{item.name} · {item.state}</option>)}
        </select>
      </label>
      <button className="btn-primary" disabled={busy} onClick={onEnterDashboard}>
        Open analysis
      </button>
    </div>
    </section>

    <section className="run-section new-analysis-section">
      <div className="run-upload-row">
        <div><h2>Run a new analysis</h2><p className="muted">Upload a prepared dataset ZIP file.</p></div>
        <input className="dataset-file-input" type="file" accept=".zip,application/zip" disabled={busy || !apiReady} onChange={(event) => setFile(event.target.files?.[0] ?? null)} aria-label="Choose prepared dataset ZIP" />
        <button className="btn-primary" disabled={!file || busy || !apiReady} onClick={startRun}>{busy ? 'Running…' : 'Upload & run'}</button>
      </div>

    {!apiReady && <div className="pipeline-status" role="status">New analyses are currently unavailable.</div>}
    {!apiReady && import.meta.env.DEV && <details className="pipeline-diagnostics"><summary>Developer details</summary><code>{getApiBase() ? `Check the pipeline API at ${getApiBase()}.` : 'Configure VITE_API_BASE_URL to connect the pipeline API.'}</code></details>}
    {error && <div className="notice" role="alert">{error}</div>}

    {runId && status && <div className="run-progress">
      <h3>{status.state === 'done' ? `Run complete · ${currentName}` : status.state === 'error' ? `Run failed · ${currentName}` : `Solving · ${currentName}`}</h3>
      <ul className="stage-list">{STAGES.map(([id, label]) => {
        const state = stageState(id);
        const icon = state === 'ok' ? '✓' : state === 'error' ? '✗' : state === 'running' ? '…' : '·';
        return <li className={`stage stage-${state}`} key={id}><span className="stage-icon">{icon}</span> {label}</li>;
      })}</ul>
      {status.state === 'error' && <pre className="log-tail">{status.stages?.find((stage) => stage.stage === status.failed_stage)?.stderr_tail || status.error_tail || `Failed at ${status.failed_stage || 'pipeline'}`}</pre>}
      {status.state === 'done' && <p className="muted">This run is saved and selected. Dashboard tabs now show its results.</p>}
    </div>}

    <details className="run-input-reference"><summary>Required datasets and columns</summary>
      <p className="muted">Put these prepared CSVs at the exact paths shown inside <code>data_processed/</code>. Coordinates are in decimal degrees; site area is square metres; Vs30 is metres per second.</p>
      <div className="table-scroll"><table className="data"><thead><tr><th>File path</th><th>Required columns</th></tr></thead><tbody>{INPUTS.map(([path, columns]) => <tr key={path}><td><code>{path}</code></td><td>{columns}</td></tr>)}</tbody></table></div>
      <p className="muted">The uploaded ZIP may contain a single enclosing folder. The pipeline uses these processed files; it does not fetch or extract raw datasets.</p>
    </details>
    </section>
  </div>;
}
