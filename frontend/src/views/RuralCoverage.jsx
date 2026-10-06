import React, { useEffect, useMemo, useState } from 'react';
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, ReferenceLine, Cell, Legend,
} from 'recharts';
import { fetchJson } from '../api.js';
import { fmt, fmtInt, fmtDistanceKm } from '../format.js';
import { MetricPanel } from '../components/Metrics.jsx';
import SortableTable from '../components/SortableTable.jsx';

const FAR_THRESHOLD_KM = 45; // above this, a sub-district is flagged as structurally underserved

// per-mode casualty-weighted average distance from a demand point to its
// assigned facility.
function weightedAvgByDemand(casualtyAllocation) {
  const acc = {};
  for (const r of casualtyAllocation ?? []) {
    const s = (acc[r.demand_point_id] ??= { dist: 0, cas: 0, name: r.demand_point_name });
    s.dist += r.distance_km * r.assigned_casualties;
    s.cas += r.assigned_casualties;
  }
  const out = {};
  for (const [id, s] of Object.entries(acc)) {
    out[id] = { name: s.name, avgDistanceKm: s.cas > 0 ? s.dist / s.cas : null, casualties: s.cas };
  }
  return out;
}

// Coverage gaps — the project's headline finding. Ranks every sub-district by
// casualty-weighted average distance to its assigned facility, in both
// solver modes. The point is not that the solver is wrong — it minimizes
// distance subject to capacity in both modes — it's that some sub-districts
// stay far under either plan, meaning the gap is in facility density near
// them, not which candidates get filtered for hazard. That's a facility
// pre-positioning policy question, not something a different solve fixes.
export default function RuralCoverage() {
  const [demandPoints, setDemandPoints] = useState(null);
  const [aware, setAware] = useState(null);
  const [blind, setBlind] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchJson('/api/demand_points').then(setDemandPoints).catch((e) => setError(e.message));
    fetchJson('/api/solutions/risk_aware').then(setAware).catch((e) => setError(e.message));
    fetchJson('/api/solutions/risk_blind').then(setBlind).catch((e) => setError(e.message));
  }, []);

  const rows = useMemo(() => {
    if (!demandPoints || !aware || !blind) return [];
    const awareByDemand = weightedAvgByDemand(aware.casualty_allocation);
    const blindByDemand = weightedAvgByDemand(blind.casualty_allocation);
    return demandPoints
      .map((d) => {
        const a = awareByDemand[d.sub_district_id];
        const b = blindByDemand[d.sub_district_id];
        return {
          id: d.sub_district_id,
          name: d.name,
          population: d.population,
          casualties: d.pop_i,
          riskAwareKm: a?.avgDistanceKm ?? null,
          riskBlindKm: b?.avgDistanceKm ?? null,
        };
      })
      .filter((r) => r.riskAwareKm != null)
      .sort((x, y) => y.riskAwareKm - x.riskAwareKm);
  }, [demandPoints, aware, blind]);

  const provinceAvgKm = useMemo(() => {
    if (!rows.length) return null;
    const totalCas = rows.reduce((s, r) => s + r.casualties, 0);
    const totalDist = rows.reduce((s, r) => s + r.riskAwareKm * r.casualties, 0);
    return totalDist / totalCas;
  }, [rows]);

  const underserved = rows.filter((r) => r.riskAwareKm >= FAR_THRESHOLD_KM);

  if (error) {
    return <div className="notice">Coverage data not available: {error}.</div>;
  }
  if (!rows.length) {
    return (
      <section>
        <div className="skeleton skeleton-card" style={{ marginBottom: 'var(--space-4)' }} />
        <div className="skeleton skeleton-table" />
      </section>
    );
  }

  return (
    <section>
      <div className="panel callout" style={{ marginBottom: 'var(--space-4)' }}>
        <h3>Facility access is structurally worse for rural sub-districts</h3>
        <p className="muted">
          The same {underserved.length} rural sub-districts sit far above the {fmt(provinceAvgKm, 1)} km
          province average in both solver modes. The hazard filter is not the cause. These
          districts have too few candidate facilities nearby, which is a pre-positioning
          question for policy rather than something a different solve can fix.
        </p>
      </div>

      <MetricPanel
        signal="distance"
        subEmphasis
        lead={{
          value: underserved.length,
          label: `Sub-districts above ${FAR_THRESHOLD_KM} km`,
          sub: underserved.map((r) => r.name).join(', ') || '—',
        }}
        support={[
          { label: 'Province-wide average distance', value: fmtDistanceKm(provinceAvgKm) },
          { label: 'Farthest sub-district', value: `${fmtDistanceKm(rows[0]?.riskAwareKm)} · ${rows[0]?.name}` },
        ]}
      />

      <div className="panel" style={{ marginTop: 'var(--space-4)' }}>
        <h3>Casualty-weighted average assignment distance by sub-district</h3>
        <ResponsiveContainer width="100%" height={Math.max(280, rows.length * 42)}>
          <BarChart data={rows} layout="vertical" margin={{ top: 8, right: 24, left: 8, bottom: 8 }}>
            <defs>
              <pattern id="hatch-blind" patternUnits="userSpaceOnUse" width="6" height="6" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="var(--dist-2)" />
                <line x1="0" y1="0" x2="0" y2="6" stroke="var(--dist-4)" strokeWidth="2" />
              </pattern>
            </defs>
            <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="var(--ink-200)" />
            <XAxis type="number" unit=" km" stroke="var(--ink-500)" fontSize={12} />
            <YAxis type="category" dataKey="name" width={110} stroke="var(--ink-500)" fontSize={12} />
            <RTooltip formatter={(v) => [`${fmt(v, 1)} km`, undefined]} />
            <Legend />
            <ReferenceLine
              x={provinceAvgKm}
              stroke="var(--ink-500)"
              strokeDasharray="4 3"
              label={{ value: 'province avg', position: 'insideTopRight', fontSize: 11, fill: 'var(--ink-500)' }}
            />
            <Bar dataKey="riskBlindKm" name="Risk-blind" fill="url(#hatch-blind)" stroke="var(--dist-4)" strokeWidth={1} radius={[0, 3, 3, 0]} isAnimationActive={false} />
            <Bar dataKey="riskAwareKm" name="Risk-aware" radius={[0, 3, 3, 0]} isAnimationActive={false}>
              {rows.map((r) => (
                <Cell key={r.id} fill={r.riskAwareKm >= FAR_THRESHOLD_KM ? 'var(--hz-4)' : 'var(--dist-5)'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <SortableTable
        columns={[
          { key: 'name', label: 'Sub-district', align: 'left', value: (r) => r.name },
          { key: 'population', label: 'Population', align: 'right', value: (r) => fmtInt(r.population), sortValue: (r) => r.population },
          { key: 'casualties', label: 'Est. casualties', align: 'right', value: (r) => fmtInt(r.casualties), sortValue: (r) => r.casualties },
          { key: 'riskAwareKm', label: 'Avg. distance, risk-aware', align: 'right', value: (r) => fmt(r.riskAwareKm, 1), sortValue: (r) => r.riskAwareKm },
          { key: 'riskBlindKm', label: 'Avg. distance, risk-blind', align: 'right', value: (r) => fmt(r.riskBlindKm, 1), sortValue: (r) => r.riskBlindKm },
          {
            key: 'status', label: 'Status', align: 'left',
            value: (r) => (r.riskAwareKm >= FAR_THRESHOLD_KM ? 'underserved' : 'within range'),
            render: (r) => (r.riskAwareKm >= FAR_THRESHOLD_KM
              ? <span className="chip unsafe">underserved</span>
              : <span className="chip safe">within range</span>),
          },
        ]}
        rows={rows}
        rowKey={(r) => r.id}
        filterPlaceholder="Filter by sub-district…"
        csvFilename="coverage_gaps.csv"
        defaultSort={{ key: 'riskAwareKm', dir: 'desc' }}
      />
    </section>
  );
}
