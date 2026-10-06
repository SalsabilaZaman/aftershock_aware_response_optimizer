import React, { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet';
import { fetchJson } from '../api.js';
import { P_UNSAFE_BINS, pUnsafeColor, STUDY_BOUNDS } from '../hazard.js';
import { fmt, fmtInt, displaySiteName } from '../format.js';
import { MetricPanel } from '../components/Metrics.jsx';

const PGA_MAX = 0.2;

// Merged scenario overview + hazard map: they were two half-empty tabs
// answering the same question ("where and how bad is the hazard?").
export default function Hazard({ manifest, sites, mode, modeKey, onSelectSite }) {
  const [capacityBySite, setCapacityBySite] = useState({});
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

  const scenario = manifest?.scenarios?.[0];
  const st = scenario?.stats ?? {};

  const bandCounts = useMemo(() => {
    if (!sites) return [];
    return P_UNSAFE_BINS.map((b, i) => {
      const lo = i === 0 ? 0 : P_UNSAFE_BINS[i - 1].max;
      const count = sites.filter((s) => s.P_unsafe != null && s.P_unsafe >= lo && s.P_unsafe < b.max).length;
      return { ...b, lo, count };
    });
  }, [sites]);

  const visibleSites = useMemo(() => {
    if (!sites) return [];
    if (!activeBand) return sites;
    return sites.filter((s) => s.P_unsafe != null && s.P_unsafe >= activeBand.lo && s.P_unsafe < activeBand.max);
  }, [sites, activeBand]);

  if (!manifest || !sites) return <div className="notice info">Loading hazard data…</div>;
  if (!scenario) return <div className="notice">No scenarios in the manifest.</div>;

  const worstSite = sites.reduce(
    (best, s) => (Number.isFinite(s.P_unsafe) && (!best || s.P_unsafe > best.P_unsafe) ? s : best),
    null,
  );
  const highestPUnsafe = worstSite?.P_unsafe ?? null;
  const isOverThreshold = (worstSite?.PGA_representative_g ?? 0) > PGA_MAX;
  const center = [37.575, 36.937];

  const radiusFor = (s) => {
    const cap = capacityBySite[s.site_id];
    if (!cap) return 5;
    return 4 + 6 * Math.sqrt(cap / 500);
  };

  return (
    <section>
      <MetricPanel
        signal={isOverThreshold ? 'hazard' : undefined}
        lead={{
          value: fmt(highestPUnsafe, 3),
          label: 'Highest P(unsafe) among candidate sites',
          sub: isOverThreshold
            ? `Above the 0.2g PGA threshold at the most exposed site (${fmt(worstSite.PGA_representative_g, 2)}g)`
            : '30-day probability of exceeding 0.2g at the most exposed site',
        }}
        support={[
          { label: 'Aftershocks recorded', value: fmtInt(st.aftershocks_in_window) },
          { label: 'Candidate sites', value: fmtInt(st.candidate_sites) },
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
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>'
            url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
          />
          {visibleSites.map((s) => (
            <CircleMarker
              key={s.site_id}
              center={[s.latitude, s.longitude]}
              radius={radiusFor(s)}
              pathOptions={{
                color: 'rgba(20,23,28,0.55)',
                weight: 1,
                fillColor: pUnsafeColor(s.P_unsafe),
                fillOpacity: 0.9,
              }}
              eventHandlers={{ click: () => onSelectSite(s.site_id) }}
            >
              <Tooltip>
                <b>{displaySiteName(s)}</b>
                <br />
                P(unsafe): {fmt(s.P_unsafe, 3)} · PGA {fmt(s.PGA_representative_g)} g
                <br />
                {s.facility_type} · {s.resolution_tier} · click for detail
              </Tooltip>
            </CircleMarker>
          ))}
        </MapContainer>

        <div className="legend">
          <div className="title">P(unsafe): 30-day P[PGA ≥ 0.2 g]</div>
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
            no PSAHA value
          </div>
        </div>
      </div>
    </section>
  );
}
