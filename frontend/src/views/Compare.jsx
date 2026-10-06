import React, { useEffect, useMemo, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmt, displaySiteName } from '../format.js';
import { MetricPanel } from '../components/Metrics.jsx';
import SortableTable from '../components/SortableTable.jsx';

// Risk comparison — the core research argument. AHP/TOPSIS was dropped from
// the methodology, so "risk-blind vs risk-aware" compares the facility-
// location MILP solved WITHOUT the PGA candidate filter vs WITH it. The
// delta — sites a hazard-unaware plan opens that the hazard filter rejects —
// is the headline element, not a footnote. This view always shows both
// modes, so it ignores the global solver-mode control by design.
export default function Compare({ sites, onSelectSite }) {
  const [status, setStatus] = useState(null);
  const [error, setError] = useState(null);
  const [onlyDelta, setOnlyDelta] = useState(true);

  useEffect(() => {
    fetchJson('/api/site_status').then(setStatus).catch((e) => setError(e.message));
  }, []);

  const siteById = useMemo(
    () => Object.fromEntries((sites ?? []).map((s) => [s.site_id, s])),
    [sites],
  );

  const enriched = useMemo(() => {
    if (!status) return [];
    return status.map((r) => ({
      ...r,
      p_unsafe: siteById[r.site_id]?.P_unsafe ?? null,
      pga: siteById[r.site_id]?.PGA_representative_g ?? null,
      name: displaySiteName(siteById[r.site_id] ?? { site_id: r.site_id }),
      type: siteById[r.site_id]?.facility_type ?? '',
    }));
  }, [status, siteById]);

  // Fixed set the summary sentence describes, independent of the onlyDelta
  // toggle below (which only affects what the table shows).
  const affected = useMemo(
    () => enriched.filter((r) => r.blind_pick_unsafe || r.excluded_by_pga_filter),
    [enriched],
  );

  const rows = useMemo(
    () => enriched.filter((r) => (onlyDelta ? r.blind_pick_unsafe || r.excluded_by_pga_filter : true)),
    [enriched, onlyDelta],
  );

  const maxPga = Math.max(1e-9, ...enriched.map((r) => r.pga ?? 0));
  const PGA_MAX = 0.2;
  const affectedWithPga = affected.filter((r) => r.pga != null);
  const allAffectedOverThreshold = affectedWithPga.length > 0 && affectedWithPga.every((r) => r.pga > PGA_MAX);
  const maxAffectedPga = Math.max(0, ...affectedWithPga.map((r) => r.pga));

  if (error) {
    return <div className="notice">Comparison data not available: {error}.</div>;
  }
  if (!status) {
    return (
      <section>
        <div className="skeleton skeleton-card" style={{ marginBottom: 'var(--space-4)' }} />
        <div className="skeleton skeleton-table" />
      </section>
    );
  }

  const nUnsafePicks = status.filter((r) => r.blind_pick_unsafe).length;
  const nExcluded = status.filter((r) => r.excluded_by_pga_filter).length;
  const nBlind = status.filter((r) => r.selected_risk_blind).length;
  const nAware = status.filter((r) => r.selected_risk_aware).length;
  const delta = nAware - nBlind;
  const deltaPct = nBlind ? (delta / nBlind) * 100 : 0;

  const columns = [
    { key: 'name', label: 'Site', align: 'left', value: (r) => r.name },
    { key: 'type', label: 'Type', align: 'left', value: (r) => r.type },
    {
      key: 'pga', label: 'PGA (g)', align: 'right', value: (r) => fmt(r.pga), sortValue: (r) => r.pga,
      render: (r) => (
        <span className="sparkbar-cell">
          {r.pga != null && (
            <span className="sparkbar-fill" style={{ width: `${(r.pga / maxPga) * 100}%` }} />
          )}
          <span>{fmt(r.pga)}</span>
        </span>
      ),
    },
    { key: 'p_unsafe', label: 'P(unsafe)', align: 'right', value: (r) => fmt(r.p_unsafe, 3), sortValue: (r) => r.p_unsafe },
    {
      key: 'blind', label: 'Risk-blind plan', align: 'left',
      value: (r) => (r.selected_risk_blind ? 'opened' : r.candidate_risk_blind ? 'not opened' : '—'),
    },
    {
      key: 'aware', label: 'Risk-aware plan', align: 'left',
      value: (r) => (r.excluded_by_pga_filter ? 'excluded (hazard)' : r.selected_risk_aware ? 'opened' : 'not opened'),
    },
    {
      key: 'verdict', label: 'Verdict', align: 'left',
      value: (r) => (r.blind_pick_unsafe ? 'unsafe blind pick' : r.excluded_by_pga_filter ? 'filtered out' : r.selected_risk_aware ? 'safe open' : 'unused'),
      render: (r) => (
        r.blind_pick_unsafe ? <span className="chip unsafe">⚠ unsafe blind pick</span>
        : r.excluded_by_pga_filter ? <span className="chip neutral">filtered out</span>
        : r.selected_risk_aware ? <span className="chip safe">✓ safe open</span>
        : <span className="chip neutral">unused</span>
      ),
    },
  ];

  return (
    <section>
      <MetricPanel
        signal="risk"
        lead={{
          value: nUnsafePicks,
          label: 'Unsafe sites the risk-blind plan opens',
          sub: 'Opened without hazard information, rejected once it is applied',
        }}
        support={[
          { label: 'Sites ruled out by hazard', value: nExcluded },
          { label: 'Sites opened, risk-blind', value: nBlind },
          { label: 'Sites opened, risk-aware', value: nAware },
        ]}
      />

      <div className="panel" style={{ marginBottom: 'var(--space-4)' }}>
        <h3>Sites opened, by mode</h3>
        <p className="muted">
          Hazard-aware siting opens {Math.abs(delta)} {delta >= 0 ? 'more' : 'fewer'} sites
          ({delta >= 0 ? '+' : ''}{fmt(deltaPct, 1)}%) and avoids {nUnsafePicks} likely-unsafe ones.
          {allAffectedOverThreshold && (
            <> All {affected.length} affected sites exceed the 0.2g threshold, up to {fmt(maxAffectedPga, 2)}g.</>
          )}
        </p>
      </div>

      <div className="filter-row">
        <label>
          <input type="checkbox" checked={onlyDelta} onChange={(e) => setOnlyDelta(e.target.checked)} />{' '}
          show only sites affected by the hazard filter
        </label>
      </div>

      <SortableTable
        columns={columns}
        rows={rows}
        rowKey={(r) => r.site_id}
        filterPlaceholder="Filter by site name or type…"
        csvFilename="risk_comparison.csv"
        onRowClick={(r) => onSelectSite(r.site_id)}
        defaultSort={{ key: 'pga', dir: 'desc' }}
      />
    </section>
  );
}
