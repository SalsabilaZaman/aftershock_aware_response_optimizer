import React from 'react';
import { fmt } from '../format.js';

// Provenance drawer — everything that used to sit in the "Scenario
// parameters" card on the overview tab, taking up prime vertical space for
// content a planner rarely needs and a reviewer wants one click away.
export default function AboutRun({ manifest, onClose }) {
  const scenario = manifest?.scenarios?.[0];
  const st = scenario?.stats ?? {};
  const failing = Object.entries(manifest?.validation ?? {}).filter(([, v]) => v.status === 'fail');
  const isJob = manifest?.data_source?.kind === 'job';

  return (
    <div className="detail-overlay" onClick={onClose}>
      <aside className="detail-drawer" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        <h2>How to read this</h2>

        <h3>What the models decide</h3>
        <ul className="how-to-list">
          <li><b>{manifest?.model_labels?.models?.risk_blind ?? 'Risk-blind MILP'}:</b> choose TMC openings and allocate casualties without the PGA screen.</li>
          <li><b>{manifest?.model_labels?.models?.risk_aware ?? 'Risk-aware MILP'}:</b> optimize after excluding candidate sites above the PGA threshold.</li>
          <li><b>{manifest?.model_labels?.models?.paper_lp ?? 'Scenario-wise LP'}:</b> solve routing and staffing separately for each scenario; it has no shared site-opening decision.</li>
          <li><b>{manifest?.model_labels?.models?.saa ?? 'SAA'}:</b> choose a shared TMC policy under a site budget, then evaluate sampled scenarios.</li>
        </ul>

        <h3>Objective units</h3>
        <dl className="research-objectives">
          <dt>Z1</dt><dd>Unmet casualties, with T1 as the most severe triage class.</dd>
          <dt>Z2</dt><dd>Casualty travel burden, measured in casualty-kilometres.</dd>
          <dt>Z3</dt><dd>Additional staffing. Values are continuous staff equivalents; summing across periods gives staff-periods.</dd>
        </dl>
        <p className="muted">SAA reports four model periods within the first 72 hours. The configuration defines period indices, not a separate clock-time duration for each period.</p>

        <h3>Run configuration</h3>
        <table className="kv">
          <tbody>
            <tr><td>Source</td><td>{isJob ? `Your run · ${manifest.data_source.job_id.slice(0, 8)}` : 'Reference run'}</td></tr>
            <tr><td>Generated</td><td>{manifest?.generated_utc ?? '—'}</td></tr>
            {scenario && (
              <>
                <tr><td>Mainshock</td><td>{scenario.mainshock_utc} UTC (USGS {scenario.usgs_event_id})</td></tr>
                <tr>
                  <td>Bounding box</td>
                  <td>
                    {scenario.bbox
                      ? `${scenario.bbox.west}–${scenario.bbox.east}°E, ${scenario.bbox.south}–${scenario.bbox.north}°N`
                      : '—'}
                  </td>
                </tr>
                <tr><td>Aftershock window</td><td>M ≥ {scenario.min_magnitude}, {scenario.window?.join(' to ')}</td></tr>
                <tr><td>PGA filter threshold</td><td>{scenario.pga_filter_threshold_g ?? '—'} g</td></tr>
                <tr><td>PGA range across sites</td><td>{st.pga_g ? `${fmt(st.pga_g.min)}–${fmt(st.pga_g.max)} g` : '—'}</td></tr>
              </>
            )}
          </tbody>
        </table>

        <h3>Objective units</h3>
        <p className="muted">
          The siting solver's objective is denominated in casualty-kilometres, not currency.
          The travel-burden term is distance × casualties, taken directly. The opening term
          is an explicit, judgement-chosen parsimony penalty in the same units. Opening an
          extra temporary medical centre is only worth it if it reduces total casualty-km by
          at least that amount. It is not a facility setup cost: no defensible per-facility
          cost standard exists for tented sites, unlike the shelter-area standard used for
          capacity. Its sensitivity was checked across a 100&ndash;10,000 range; the paper's
          three central findings hold throughout that range.
        </p>

        <h3>Site names</h3>
        <p className="muted">
          Candidate sites come from OpenStreetMap. Roughly 4 in 10 carry no name tag in the
          source data and are shown by their site ID instead. This affects labelling
          only — location, capacity, and hazard values are derived independently of the name
          field.
        </p>

        {failing.length > 0 && (
          <div className="notice">
            {failing.length} dataset(s) failed validation: {failing.map(([k]) => k).join(', ')}.
            Affected views show missing data rather than a substitute.
          </div>
        )}
      </aside>
    </div>
  );
}
