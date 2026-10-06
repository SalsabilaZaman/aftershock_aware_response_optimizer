import React from 'react';

// Replaces the uniform stat-card row: one large, ranked lead metric plus a
// hairline-separated definition-list strip for supporting values.
//
// `signal` names which ramp colours the lead value: 'hazard' | 'risk' |
// 'distance' | undefined. It must be passed only when the number itself
// represents a crossed, named threshold (see redesign brief patch 01 §3) —
// omit it (or pass undefined) for a neutral fact, which renders --ink-900,
// the highest-contrast text on the card. `subEmphasis` bumps the sub-caption
// from --ink-500 to --ink-700 for cases where the sub line is itself an
// answer (e.g. "which six sub-districts"), not just supplementary detail.
export function MetricPanel({ lead, support, signal, subEmphasis }) {
  return (
    <div className="metric-panel">
      <div className={`lead-metric ${signal ? `tone-signal-${signal}` : ''}`}>
        <div className="lead-value num">{lead.value}</div>
        <div className="lead-label">{lead.label}</div>
        {lead.sub && <div className={`lead-sub ${subEmphasis ? 'emphasis' : ''}`}>{lead.sub}</div>}
      </div>
      {support?.length > 0 && (
        <dl className="metric-list">
          {support.map((s) => (
            <div className="metric-row" key={s.label}>
              <dt>{s.label}</dt>
              <dd className="num">{s.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
