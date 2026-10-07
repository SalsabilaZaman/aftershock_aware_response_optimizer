import React, { useEffect, useState } from 'react';
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip as RTooltip, XAxis, YAxis,
} from 'recharts';
import { fetchJson } from '../api.js';
import { fmt, fmtInt } from '../format.js';
import SortableTable from '../components/SortableTable.jsx';
import ProfileComparison from './ProfileComparison.jsx';

const pct = (value) => value == null ? 'N/A' : `${fmt(value * 100, 1)}%`;

export default function SAAResults({ profile = 'topsis_120', comparison = false }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchJson(`/api/saa/${profile}`).then(setResult).catch((e) => setError(e.message));
  }, [profile]);

  if (error) return <div className="notice">SAA results are unavailable: {error}.</div>;
  if (!result) return <div className="skeleton skeleton-card" />;

  const rows = result.budget_rows;
  const meta = result.metadata;
  const reference25 = rows.find((r) => Number(r.budget) === 25);
  const expected25 = reference25 ? Number(reference25.out_of_sample_expected_unmet_casualties) /
    Math.max(1e-9, 1 - Number(reference25.out_of_sample_expected_served_fraction)) : null;
  const atBudget = (budget) => rows.find((row) => Number(row.budget) === budget);
  const zero = Number(atBudget(0)?.out_of_sample_expected_served_fraction);
  const at25 = Number(atBudget(25)?.out_of_sample_expected_served_fraction);
  const at120 = Number(atBudget(120)?.out_of_sample_expected_served_fraction);
  const benefitCaptured = Number.isFinite(at25) && Number.isFinite(at120) && at120 > zero
    ? (at25 - zero) / (at120 - zero) : null;
  const maxFitGap = Math.max(0, ...rows.map((row) => Math.abs(Number(row.in_sample_expected_served_fraction) - Number(row.out_of_sample_expected_served_fraction))));
  const replicationCount = meta.replications ?? 'N/A';

  return (
    <section>
      <div className="panel callout" style={{ marginBottom: 'var(--space-4)' }}>
        <h3>Stochastic budget sweep</h3>
        <p className="muted">
          Each budget policy is trained on {replicationCount} independent replications
          ({meta.training_scenarios_per_replication ?? 'N/A'} scenarios each) and evaluated
          on the same {meta.validation_draws_per_policy ?? 'N/A'} out-of-sample draws.
          The out-of-sample standard deviation summarizes variation across replication means;
          it is not a confidence interval.
        </p>
        <p className="muted">At the 25-site policy, total expected casualties are about {fmtInt(expected25)}. This scenario-based SAA total differs from the deterministic MILP’s fixed 117,398 projection because the models use different demand and recourse assumptions.</p>
      </div>

      <div className="panel">
        <h3>Expected casualty service by TMC budget</h3>
        {benefitCaptured != null && benefitCaptured >= 0.98 && <p className="notice info">A 25-site policy captures {fmt(benefitCaptured * 100, 1)}% of the service gain achieved by a 120-site budget in this run.</p>}
        <ResponsiveContainer width="100%" height={340}>
          <LineChart data={rows} margin={{ top: 16, right: 24, left: 8, bottom: 28 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--ink-200)" />
            <XAxis dataKey="budget" type="number" domain={['dataMin', 'dataMax']} ticks={meta.budgets} label={{ value: 'Maximum new TMC sites', position: 'insideBottom', offset: -20 }} />
            <YAxis domain={[0, 1]} tickFormatter={pct} width={58} />
            <RTooltip formatter={(value, name) => [pct(value), name]} labelFormatter={(value) => `Budget: ${value} TMCs`} />
            <Line type="monotone" dataKey="out_of_sample_expected_served_fraction" name="Out-of-sample validation" stroke="var(--dist-5)" strokeWidth={2.5} dot={{ r: 4 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
        <p className="muted">Chart shows out-of-sample validation. In-sample and out-of-sample estimates differ by at most {fmt(maxFitGap * 100, 2)} percentage points in this run. The deterministic MILP is a different fixed-demand model and is not drawn as a line on this budget chart.</p>
      </div>

      <SortableTable
        columns={[
          { key: 'budget', label: 'TMC budget', align: 'right', value: (r) => fmtInt(r.budget), sortValue: (r) => r.budget },
          { key: 'in_sample_expected_served_fraction', label: 'In-sample served', align: 'right', value: (r) => pct(r.in_sample_expected_served_fraction), sortValue: (r) => r.in_sample_expected_served_fraction },
          { key: 'out_of_sample_expected_served_fraction', label: 'Out-of-sample served', align: 'right', value: (r) => pct(r.out_of_sample_expected_served_fraction), sortValue: (r) => r.out_of_sample_expected_served_fraction },
          { key: 'out_of_sample_served_fraction_sd_across_replications', label: 'Served SD across replications', align: 'right', value: (r) => `${fmt(r.out_of_sample_served_fraction_sd_across_replications * 100, 2)} pp`, sortValue: (r) => r.out_of_sample_served_fraction_sd_across_replications },
          { key: 'out_of_sample_expected_unmet_casualties', label: 'Expected unmet casualties', align: 'right', value: (r) => fmtInt(r.out_of_sample_expected_unmet_casualties), sortValue: (r) => r.out_of_sample_expected_unmet_casualties },
          { key: 'out_of_sample_unmet_sd_across_replications', label: 'Unmet SD across replications', align: 'right', value: (r) => fmtInt(r.out_of_sample_unmet_sd_across_replications), sortValue: (r) => r.out_of_sample_unmet_sd_across_replications },
        ]}
        rows={rows}
        rowKey={(r) => r.budget}
        csvFilename="saa_budget_sweep.csv"
        defaultSort={{ key: 'budget', dir: 'asc' }}
      />
      {comparison && <div style={{ marginTop: 'var(--space-5)' }}><ProfileComparison model={`saa_${profile}`} /></div>}
    </section>
  );
}
