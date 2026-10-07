import React, { useEffect, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmtInt } from '../format.js';
import SortableTable from '../components/SortableTable.jsx';

export default function SAAMedicalResponse({ profile, detail }) {
  const [result, setResult] = useState(null); const [error, setError] = useState(null);
  const [summary, setSummary] = useState(null);
  useEffect(() => {
    setResult(null); setError(null);
    Promise.all([fetchJson(`/api/saa/${profile}/detail`), fetchJson(`/api/saa/${profile}`)])
      .then(([detailResult, modelResult]) => { setResult(detailResult); setSummary(modelResult); })
      .catch((e) => setError(e.message));
  }, [profile]);
  if (error) return <div className="notice info">Detailed SAA medical allocations are unavailable for this run: {error}. Budget and out-of-sample performance remain available in Robustness.</div>;
  if (!result) return <div className="skeleton skeleton-card" />;
  const allocations = result.casualty_allocation ?? [];
  const staffing = result.staffing ?? [];
  const budget25 = (summary?.budget_rows ?? []).find((r) => Number(r.budget) === 25);
  const expectedCasualties = budget25 ? Number(budget25.out_of_sample_expected_unmet_casualties) /
    Math.max(1e-9, 1 - Number(budget25.out_of_sample_expected_served_fraction)) : null;
  return <section>
    <div className="panel callout"><h3>Recorded SAA policy recourse</h3><p className="muted">Showing only the detailed policy and validation draw included in this export. This is not a new solve. At the 25-site policy, total expected casualties are about {fmtInt(expectedCasualties)}; the deterministic MILP uses a fixed 117,398-casualty projection, so the totals differ by demand assumptions.</p></div>
    <div className="cards"><div className="stat-card"><div className="label">Allocation rows</div><div className="value">{fmtInt(allocations.length)}</div><div className="sub">Recorded casualty assignments</div></div><div className="stat-card"><div className="label">Staff allocation rows</div><div className="value">{fmtInt(staffing.length)}</div><div className="sub">Recorded staff recourse</div></div></div>
    <details open><summary>Casualty allocations</summary><SortableTable rows={allocations} rowKey={(r, i) => `${r.scenario_id ?? ''}-${r.demand_point_id ?? ''}-${r.facility_id ?? ''}-${i}`} columns={Object.keys(allocations[0] ?? {}).filter((key) => !['policy', 'draw_id', 'scenario_id', 'facility_id', 'demand_point_id', 'facility_set', 'facility_type', 'facility_label', 'demand_point_label', 'facility_type_label'].includes(key)).map((key) => ({ key, label: key.replaceAll('_', ' '), value: (r) => r[key] ?? '—', align: typeof allocations[0]?.[key] === 'number' ? 'right' : 'left', sortValue: (r) => r[key] })).concat([
      { key: 'demand_point_label', label: 'Demand point', value: (r) => r.demand_point_label ?? '—' },
      { key: 'facility_label', label: 'Facility', value: (r) => r.facility_label ?? '—' },
      { key: 'facility_type_label', label: 'Type', value: (r) => r.facility_type_label ?? '—' },
    ])} csvFilename="saa_medical_allocations.csv" /></details>
    <details><summary>Staffing allocations</summary><SortableTable rows={staffing} rowKey={(r, i) => `${r.facility_id ?? r.site_id ?? ''}-${r.staff_type ?? ''}-${i}`} columns={Object.keys(staffing[0] ?? {}).filter((key) => !['policy', 'draw_id', 'scenario_id', 'facility_id', 'site_id', 'facility_label', 'facility_type_label'].includes(key)).map((key) => ({ key, label: key.replaceAll('_', ' '), value: (r) => r[key] ?? '—', align: typeof staffing[0]?.[key] === 'number' ? 'right' : 'left', sortValue: (r) => r[key] })).concat([{ key: 'facility_label', label: 'Facility', value: (r) => r.facility_label ?? '—' }])} csvFilename="saa_staffing_allocations.csv" /></details>
    {detail === 'research' && <pre>{JSON.stringify(result.metadata ?? {}, null, 2)}</pre>}
    <div className="notice info" style={{ marginTop: 'var(--space-4)' }}>Period-level allocations, facility occupancy, capacity saturation and health-state transitions are not included in this policy detail.</div>
  </section>;
}
