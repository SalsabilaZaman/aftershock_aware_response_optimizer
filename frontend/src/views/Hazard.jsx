import React, { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet';
import { fetchJson } from '../api.js';
import { STUDY_BOUNDS } from '../hazard.js';
import { fmt, fmtInt, displaySiteName } from '../format.js';
import { MetricPanel } from '../components/Metrics.jsx';

const PGA_MAX = 0.2;
const PGA_COLORS = ['#dce8e5', '#99beb4', '#e9bd72', '#d47758'];

// Merged scenario overview + hazard map: they were two half-empty tabs
// answering the same question ("where and how bad is the hazard?").
export default function Hazard({ manifest, sites, mode, modeKey, onSelectSite }) {
  const [capacityBySite, setCapacityBySite] = useState({});
  const [siteStatus, setSiteStatus] = useState([]);
  const [activeBand, setActiveBand] = useState(null);

  useEffect(() => {
    let cancelled = false;
    fetchJson(`/api/solutions/${modeKey}`)
      .then((sol) => {
        if (cancelled) return;
        const map = {};
        for (const t of sol.tmc_selected ?? []) map[t.site_id] = t.cap_j;
        setCapacityBySite(map);
      })
      .catch(() => setCapacityBySite({}));
    return () => { cancelled = true; };
  }, [modeKey]);

  useEffect(() => {
    fetchJson('/api/site_status').then(setSiteStatus).catch(() => setSiteStatus([]));
  }, []);

  const scenario = manifest?.scenarios?.[0];
  const st = scenario?.stats ?? {};

  const bandCounts = useMemo(() => {
    const values = (sites ?? []).filter((s) => s.PGA_representative_g != null).map((s) => Number(s.PGA_representative_g)).filter(Number.isFinite).sort((a, b) => a - b);
    if (!values.length) return [];
    const cuts = [0, 0.5, 0.8, 0.95, 1].map((q) => values[Math.min(values.length - 1, Math.floor(q * (values.length - 1)))]);
    return [
      { lo: -Infinity, max: cuts[1], label: `Lowest half · < ${cuts[1].toFixed(2)} g`, color: PGA_COLORS[0] },
      { lo: cuts[1], max: cuts[2], label: `50th–80th percentile · < ${cuts[2].toFixed(2)} g`, color: PGA_COLORS[1] },
      { lo: cuts[2], max: cuts[3], label: `80th–95th percentile · < ${cuts[3].toFixed(2)} g`, color: PGA_COLORS[2] },
      { lo: cuts[3], max: Infinity, label: `Highest 5% · ≥ ${cuts[3].toFixed(2)} g`, color: PGA_COLORS[3] },
    ].map((band) => ({ ...band, count: values.filter((v) => v >= band.lo && v < band.max).length }));
  }, [sites]);

  const visibleSites = useMemo(() => {
    if (!sites) return [];
    if (!activeBand) return sites;
    return sites.filter((s) => s.PGA_representative_g != null && Number.isFinite(Number(s.PGA_representative_g)) && Number(s.PGA_representative_g) >= activeBand.lo && Number(s.PGA_representative_g) < activeBand.max);
  }, [sites, activeBand]);

  if (!manifest || !sites) return <div className="notice info">Loading hazard data…</div>;
  if (!scenario) return <div className="notice">No scenarios in the manifest.</div>;

  const worstSite = sites.reduce(
    (best, s) => (s.PGA_representative_g != null && Number.isFinite(Number(s.PGA_representative_g)) && (!best || Number(s.PGA_representative_g) > Number(best.PGA_representative_g)) ? s : best),
    null,
  );
  const pgaValues = sites.filter((s) => s.PGA_representative_g != null).map((s) => Number(s.PGA_representative_g)).filter(Number.isFinite);
  const unsafeCount = pgaValues.filter((v) => v > PGA_MAX).length;
  const highPgaNonTmc = sites.filter((s) => s.PGA_representative_g != null && Number(s.PGA_representative_g) > PGA_MAX && s.facility_type === 'hospital').length;
  const filteredCandidateCount = siteStatus.filter((s) => s.excluded_by_pga_filter).length;
  const center = [37.575, 36.937];

  const radiusFor = (s) => {
    const cap = capacityBySite[s.site_id];
    if (!cap) return 5;
    return 4 + 6 * Math.sqrt(cap / 500);
  };

  return (
    <section>
      <MetricPanel
        signal={unsafeCount ? 'hazard' : undefined}
        lead={{
          value: `${unsafeCount} / ${fmtInt(pgaValues.length)}`,
          label: 'Candidate sites above 0.2 g PGA',
          sub: `${unsafeCount} of ${fmtInt(pgaValues.length)} sites with PGA exceed the screen, including ${highPgaNonTmc} hospital-type locations not eligible as TMCs. Worst: ${fmt(worstSite?.PGA_representative_g, 3)} g · ${displaySiteName(worstSite)}`,
        }}
        support={[
          { label: 'Aftershocks recorded', value: fmtInt(st.aftershocks_in_window) },
          { label: 'TMC candidates excluded by PGA screen', value: fmtInt(filteredCandidateCount) },
          { label: 'Sites with damage imagery', value: fmtInt(st.sites_aoi04_highres) },
          { label: 'Peak ground acceleration', value: st.pga_g ? `${fmt(st.pga_g.min)}–${fmt(st.pga_g.max)} g` : '—' },
        ]}
      />

      {activeBand && visibleSites.length === 0 && (
        <div className="notice info">No sites fall in the {activeBand.label} band. <button className="link-btn" onClick={() => setActiveBand(null)}>Clear filter</button></div>
      )}
      <div className="map-wrap">
        <MapContainer
          center={center}
          zoom={9}
          minZoom={8}
          maxBounds={STUDY_BOUNDS}
          maxBoundsViscosity={1.0}
          className="map-container"
          preferCanvas
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {visibleSites.map((s) => (
            <CircleMarker
              key={s.site_id}
              center={[s.latitude, s.longitude]}
              radius={radiusFor(s)}
              pathOptions={{
                color: 'rgba(20,23,28,0.55)',
                weight: 1,
                fillColor: s.PGA_representative_g == null ? '#9aa1ab' : (PGA_COLORS[bandCounts.findIndex((b) => Number(s.PGA_representative_g) >= b.lo && Number(s.PGA_representative_g) < b.max)] ?? '#9aa1ab'),
                fillOpacity: 0.9,
              }}
              eventHandlers={{ click: () => onSelectSite(s.site_id) }}
            >
              <Tooltip>
                <b>{displaySiteName(s)}</b>
                <br />
                PGA {fmt(s.PGA_representative_g, 3)} g · P(unsafe): {fmt(s.P_unsafe, 3)}
                <br />
                {s.display_type || s.facility_type} · {s.resolution_tier} · click for detail
              </Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>

        <div className="legend">
          <div className="title">Representative PGA · quantile bands</div>
          {bandCounts.map((b) => (
            <button
              key={b.label}
              className={`legend-row-btn ${activeBand?.label === b.label ? 'active' : ''}`}
              onClick={() => setActiveBand(activeBand?.label === b.label ? null : b)}
            >
              <span className="swatch" style={{ background: b.color }} />
              <span>{b.label}</span>
              <span className="num legend-count">{b.count}</span>
            </button>
          ))}
          <div className="row">
            <span className="swatch" style={{ background: 'var(--hz-null)' }} />
            no PGA value
          </div>
        </div>
      </div>
    </section>
  );
}
