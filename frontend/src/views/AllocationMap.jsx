import React, { useEffect, useMemo, useState } from 'react';
import { MapContainer, TileLayer, CircleMarker, Polyline, Tooltip } from 'react-leaflet';
import { fetchJson } from '../api.js';
import { DISTANCE_BINS, distanceColor, STUDY_BOUNDS } from '../hazard.js';
import { fmt, fmtInt, fmtCompact, fmtDistanceKm } from '../format.js';
import { MetricPanel } from '../components/Metrics.jsx';
import SortableTable from '../components/SortableTable.jsx';

// Siting plan — demand-point to assigned-facility allocation. Solver mode is
// a prop now (the global header control), not local state — this view used
// to have its own mode dropdown duplicating the same choice.
export default function AllocationMap({ modeKey }) {
  const [selectedDemand, setSelectedDemand] = useState('all');
  const [demandPoints, setDemandPoints] = useState(null);
  const [hospitals, setHospitals] = useState(null);
  const [solution, setSolution] = useState(null);
  const [error, setError] = useState(null);
  const [lineMode, setLineMode] = useState('none'); // 'none' | 'worst20' | 'all'

  useEffect(() => {
    fetchJson('/api/demand_points').then(setDemandPoints).catch((e) => setError(e.message));
    fetchJson('/api/hospitals').then(setHospitals).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    setSolution(null);
    fetchJson(`/api/solutions/${modeKey}`).then(setSolution).catch((e) => setError(e.message));
  }, [modeKey]);

  const demandById = useMemo(
    () => Object.fromEntries((demandPoints ?? []).map((d) => [d.sub_district_id, d])),
    [demandPoints],
  );

  const facilityById = useMemo(() => {
    const map = {};
    for (const t of solution?.tmc_selected ?? []) {
      map[t.site_id] = { lat: t.latitude, lon: t.longitude, name: t.site_id, type: t.facility_type, cap: t.cap_j };
    }
    for (const h of hospitals ?? []) {
      map[`JH_${h.hospital_id}`] = {
        lat: h.latitude, lon: h.longitude, name: h.hospital_name,
        type: 'hospital', cap: h.effective_capacity_postquake,
      };
    }
    return map;
  }, [solution, hospitals]);

  const rows = useMemo(() => {
    if (!solution || !demandPoints || !hospitals) return [];
    return (solution.casualty_allocation ?? [])
      .map((a) => {
        const d = demandById[a.demand_point_id];
        const f = facilityById[a.facility_id];
        if (!d || !f) return null;
        return { ...a, dLat: d.latitude, dLon: d.longitude, fLat: f.lat, fLon: f.lon, fName: f.name, fType: f.type };
      })
      .filter(Boolean);
  }, [solution, demandById, facilityById, demandPoints, hospitals]);

  const filteredRows = useMemo(
    () => (selectedDemand === 'all' ? rows : rows.filter((r) => r.demand_point_id === selectedDemand)),
    [rows, selectedDemand],
  );

  const visibleFacilityIds = useMemo(
    () => new Set(filteredRows.map((r) => r.facility_id)),
    [filteredRows],
  );

  const stats = useMemo(() => {
    if (!filteredRows.length) return null;
    const totalCas = filteredRows.reduce((s, r) => s + r.assigned_casualties, 0);
    const weightedAvg = filteredRows.reduce((s, r) => s + r.distance_km * r.assigned_casualties, 0) / totalCas;
    const maxRow = filteredRows.reduce((m, r) => (r.distance_km > m.distance_km ? r : m), filteredRows[0]);
    const farCas = filteredRows.filter((r) => r.distance_km >= 30).reduce((s, r) => s + r.assigned_casualties, 0);
    return {
      weightedAvg,
      maxRow,
      farPct: (100 * farCas) / totalCas,
      totalTravelBurden: filteredRows.reduce((s, r) => s + r.travel_burden_casualty_km, 0),
    };
  }, [filteredRows]);

  const linesToDraw = useMemo(() => {
    if (lineMode === 'none') return [];
    if (lineMode === 'all') return filteredRows;
    return [...filteredRows].sort((a, b) => b.distance_km - a.distance_km).slice(0, 20);
  }, [filteredRows, lineMode]);

  const maxAssigned = useMemo(
    () => filteredRows.reduce((m, r) => Math.max(m, r.assigned_casualties), 1),
    [filteredRows],
  );

  // per-demand-point weighted average distance, colors the demand marker itself
  const demandStats = useMemo(() => {
    const acc = {};
    for (const r of filteredRows) {
      const s = (acc[r.demand_point_id] ??= { dist: 0, cas: 0 });
      s.dist += r.distance_km * r.assigned_casualties;
      s.cas += r.assigned_casualties;
    }
    return acc;
  }, [filteredRows]);

  const columns = useMemo(() => [
    { key: 'demand_point_name', label: 'Demand point', align: 'left', value: (r) => r.demand_point_name },
    { key: 'fName', label: 'Facility', align: 'left', value: (r) => r.fName },
    { key: 'fType', label: 'Type', align: 'left', value: (r) => r.fType,
      render: (r) => <span className={`chip ${r.fType === 'hospital' ? 'safe' : 'neutral'}`}>{r.fType}</span> },
    { key: 'distance_km', label: 'Distance (km)', align: 'right', value: (r) => fmt(r.distance_km, 2), sortValue: (r) => r.distance_km },
    { key: 'assigned_casualties', label: 'Assigned casualties', align: 'right', value: (r) => fmtInt(r.assigned_casualties), sortValue: (r) => r.assigned_casualties },
    { key: 'travel_burden_casualty_km', label: 'Travel burden (casualty-km)', align: 'right', value: (r) => fmt(r.travel_burden_casualty_km, 0), sortValue: (r) => r.travel_burden_casualty_km },
  ], []);

  if (error) {
    return <div className="notice">Allocation data not available: {error}.</div>;
  }
  if (!demandPoints || !hospitals || !solution) {
    return (
      <section>
        <div className="skeleton skeleton-card" style={{ marginBottom: 'var(--space-4)' }} />
        <div className="skeleton skeleton-map" />
      </section>
    );
  }

  const center = [37.575, 36.937];

  return (
    <section>
      <div className="filter-row">
        <label>
          Demand point:{' '}
          <select
            className="scenario"
            value={selectedDemand}
            onChange={(e) => setSelectedDemand(e.target.value)}
          >
            <option value="all">All demand points</option>
            {demandPoints.map((d) => (
              <option key={d.sub_district_id} value={d.sub_district_id}>{d.name}</option>
            ))}
          </select>
        </label>
        <span className="num" style={{ color: 'var(--ink-500)' }}>{filteredRows.length} assignments</span>
      </div>

      {stats && (
        <MetricPanel
          lead={{
            value: fmtDistanceKm(stats.weightedAvg),
            label: 'Casualty-weighted average distance',
          }}
          support={[
            { label: 'Longest assignment', value: `${fmtDistanceKm(stats.maxRow.distance_km)} · ${stats.maxRow.demand_point_name} → ${stats.maxRow.fName}` },
            { label: 'Casualties travelling over 30 km', value: `${fmt(stats.farPct, 1)}%` },
            { label: 'Travel burden', value: fmtCompact(stats.totalTravelBurden, 'casualty-km') },
          ]}
        />
      )}

      <div className="map-controls">
        <label><input type="radio" checked={lineMode === 'none'} onChange={() => setLineMode('none')} /> No lines</label>
        <label><input type="radio" checked={lineMode === 'worst20'} onChange={() => setLineMode('worst20')} /> Show worst 20 assignments</label>
        <label><input type="radio" checked={lineMode === 'all'} onChange={() => setLineMode('all')} /> Show all assignments</label>
      </div>

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
          {linesToDraw.map((r, i) => (
            <React.Fragment key={i}>
              <Polyline
                positions={[[r.dLat, r.dLon], [r.fLat, r.fLon]]}
                pathOptions={{ color: '#ffffff', weight: 3 + 4 * (r.assigned_casualties / maxAssigned), opacity: 0.6 }}
              />
              <Polyline
                positions={[[r.dLat, r.dLon], [r.fLat, r.fLon]]}
                pathOptions={{ color: distanceColor(r.distance_km), weight: 1 + 4 * (r.assigned_casualties / maxAssigned), opacity: 0.35 }}
              >
                <Tooltip sticky>
                  <b>{r.demand_point_name}</b> → {r.fName} ({r.fType})
                  <br />
                  {fmt(r.distance_km, 2)} km · {fmtInt(r.assigned_casualties)} casualties
                </Tooltip>
              </Polyline>
            </React.Fragment>
          ))}

          {demandPoints
            .filter((d) => selectedDemand === 'all' || d.sub_district_id === selectedDemand)
            .map((d) => {
              const s = demandStats[d.sub_district_id];
              const avgDist = s ? s.dist / s.cas : null;
              return (
                <CircleMarker
                  key={d.sub_district_id}
                  center={[d.latitude, d.longitude]}
                  radius={5 + 6 * Math.sqrt(d.pop_i / 40000)}
                  pathOptions={{
                    color: 'rgba(20,23,28,0.6)', weight: 1.5,
                    fillColor: avgDist != null ? distanceColor(avgDist) : '#9aa1ab',
                    fillOpacity: 0.9,
                  }}
                >
                  <Tooltip>
                    <b>{d.name}</b> (demand point)
                    <br />
                    {fmtInt(d.pop_i)} casualties
                    <br />
                    avg distance to facility: {fmtDistanceKm(avgDist)}
                  </Tooltip>
                </CircleMarker>
              );
            })}

          {Object.entries(facilityById)
            .filter(([id]) => visibleFacilityIds.has(id))
            .map(([id, f]) => (
              <CircleMarker
                key={id}
                center={[f.lat, f.lon]}
                radius={4}
                pathOptions={{
                  color: 'rgba(20,23,28,0.6)', weight: 1,
                  fillColor: f.type === 'hospital' ? '#1f4d5c' : '#6fa8bb',
                  fillOpacity: 0.95,
                }}
              >
                <Tooltip>
                  <b>{f.name}</b>
                  <br />
                  {f.type} · capacity {fmtInt(f.cap)}
                </Tooltip>
              </CircleMarker>
            ))}
        </MapContainer>

        <div className="legend">
          <div className="title">Assignment distance</div>
          {DISTANCE_BINS.map((b) => (
            <div className="row" key={b.label}>
              <span className="swatch square" style={{ background: b.color }} />
              {b.label}
            </div>
          ))}
        </div>
      </div>

      <h3 style={{ margin: '1.25rem 0 0.4rem', fontSize: '0.95rem' }}>
        Casualty allocation{selectedDemand !== 'all' ? ` (${demandById[selectedDemand]?.name ?? ''})` : ''}
      </h3>
      <SortableTable
        columns={columns}
        rows={filteredRows}
        rowKey={(r) => `${r.demand_point_id}-${r.facility_id}`}
        filterPlaceholder="Filter by demand point or facility…"
        csvFilename="casualty_allocation.csv"
      />
    </section>
  );
}
