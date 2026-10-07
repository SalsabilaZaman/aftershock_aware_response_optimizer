import React, { useEffect, useState } from 'react';
import { fetchJson } from '../api.js';
import { fmt, displaySiteName } from '../format.js';

// View 4 — per-site breakdown, opened from the map or the comparison table.
export default function SiteDetail({ siteId, onClose }) {
  const [site, setSite] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    setSite(null);
    setError(null);
    fetchJson(`/api/sites/${siteId}`).then(setSite).catch((e) => setError(e.message));
  }, [siteId]);

  const st = site?.status;
  const modeVerdict = (selected, excluded) =>
    excluded ? 'excluded: PGA above threshold' : selected ? 'opened as TMC' : 'candidate, not opened';

  return (
    <div className="detail-overlay" onClick={onClose}>
      <aside className="detail-drawer" onClick={(e) => e.stopPropagation()}>
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        {error && <div className="notice">Site not available: {error}</div>}
        {!site && !error && <div className="notice info">Loading {siteId}…</div>}
        {site && (
          <>
            <h2>{displaySiteName(site)}</h2>
            <p style={{ color: 'var(--ink-700)', margin: '0.1rem 0 0.4rem' }}>
              {site.display_type || site.facility_type} · Source ID {site.site_id} ·{' '}
              {site.resolution_tier === 'AOI04_highres' ? 'high-resolution damage imagery' : 'standard-resolution imagery'}
            </p>
            {st?.blind_pick_unsafe && (
              <span className="chip unsafe">⚠ opened by the risk-blind plan, unsafe per PSAHA</span>
            )}
            <table className="kv">
              <tbody>
                <tr><td>Representative PGA (max M≥5 scenario)</td><td>{fmt(site.PGA_representative_g)} g</td></tr>
                <tr><td>P(unsafe): 30-day P[PGA ≥ 0.2 g]</td><td>{fmt(site.P_unsafe, 4)}</td></tr>
                <tr><td>Expected exceedances Λ</td><td>{fmt(site.Lambda_i)}</td></tr>
                <tr><td>Slope</td><td>{fmt(site.slope_deg)}°</td></tr>
                <tr><td>Elevation</td><td>{fmt(site.elevation_m, 0)} m</td></tr>
                <tr><td>Distance to nearest road</td><td>{fmt(site.dist_to_road_m, 0)} m</td></tr>
                <tr><td>Vs30 (site condition)</td><td>{fmt(site.vs30_ms, 0)} m/s</td></tr>
                <tr>
                  <td>Damage within 500 m (Copernicus)</td>
                  <td>
                    {site.resolution_tier === 'AOI04_highres'
                      ? `${fmt(site.damage_count_500m, 0)} buildings`
                      : 'outside high-resolution coverage area'}
                  </td>
                </tr>
              </tbody>
            </table>

            <h3 style={{ margin: '1rem 0 0.3rem', fontSize: '0.95rem' }}>Solver outcome by mode</h3>
            {st ? (
              <table className="kv">
                <tbody>
                  <tr>
                    <td>Risk-blind (no hazard filter)</td>
                    <td>{modeVerdict(st.selected_risk_blind, false)}</td>
                  </tr>
                  <tr>
                    <td>Risk-aware (PGA filter)</td>
                    <td>{modeVerdict(st.selected_risk_aware, st.excluded_by_pga_filter)}</td>
                  </tr>
                </tbody>
              </table>
            ) : (
              <p style={{ color: 'var(--ink-700)', fontSize: '0.85rem' }}>
                No solver comparison for this site (existing hospital, or the dual-mode
                solve has not been run).
              </p>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
