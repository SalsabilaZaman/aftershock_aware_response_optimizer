import React, { useEffect, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmtInt } from '../format.js';
import SortableTable from '../components/SortableTable.jsx';

export default function SAAMedicalResponse({ profile, detail }) {
  const [result, setResult] = useState(null); const [error, setError] = useState(null);
  useEffect(() => {
    setResult(null); setError(null);
    fetchJson(`/api/saa/${profile}/detail`).then(setResult).catch((e) => setError(e.message));
  }, [profile]);
  if (error) return <div className="notice info">Detailed SAA medical allocations are unavailable for this run: {error}. Budget and out-of-sample performance remain available in Robustness.</div>;
  if (!result) return <div className="skeleton skeleton-card" />;
  const allocations = result.casualty_allocation ?? [];
  const staffing = result.staffing ?? [];
  return <section>
    <div className="panel callout"><h3>Recorded SAA policy recourse</h3><p className="muted">Showing only the detailed policy and validation draw included in this export. This is not a new solve.</p></div>
    <div className="cards"><div className="stat-card"><div className="label">Allocation rows</div><div className="value">{fmtInt(allocations.length)}</div><div className="sub">Recorded casualty assignments</div></div><div className="stat-card"><div className="label">Staff allocation rows</div><div className="value">{fmtInt(staffing.length)}</div><div className="sub">Recorded staff recourse</div></div></div>
    <details open><summary>Casualty allocations</summary><SortableTable rows={allocations} rowKey={(r, i) => `${r.scenario_id ?? ''}-${r.demand_point_id ?? ''}-${r.facility_id ?? ''}-${i}`} columns={Object.keys(allocations[0] ?? {}).map((key) => ({ key, label: key.replaceAll('_', ' '), value: (r) => r[key] ?? '—', align: typeof allocations[0]?.[key] === 'number' ? 'right' : 'left', sortValue: (r) => r[key] }))} csvFilename="saa_medical_allocations.csv" /></details>
    <details><summary>Staffing allocations</summary><SortableTable rows={staffing} rowKey={(r, i) => `${r.facility_id ?? r.site_id ?? ''}-${r.staff_type ?? ''}-${i}`} columns={Object.keys(staffing[0] ?? {}).map((key) => ({ key, label: key.replaceAll('_', ' '), value: (r) => r[key] ?? '—', align: typeof staffing[0]?.[key] === 'number' ? 'right' : 'left', sortValue: (r) => r[key] }))} csvFilename="saa_staffing_allocations.csv" /></details>
    {detail === 'research' && <pre>{JSON.stringify(result.metadata ?? {}, null, 2)}</pre>}
    <div className="notice info" style={{ marginTop: 'var(--space-4)' }}>Period-level allocations, facility occupancy, capacity saturation and health-state transitions are not included in this policy detail.</div>
  </section>;
}
