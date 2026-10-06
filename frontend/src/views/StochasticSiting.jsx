import React, { useEffect, useMemo, useState } from 'react';
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from 'react-leaflet';
import { fetchJson } from '../api.js';
import { STUDY_BOUNDS } from '../hazard.js';
import { fmtInt } from '../format.js';

export default function StochasticSiting({ model, scenarioId = 'all', onScenarioChange = () => {} }) {
  const kind = model.startsWith('paper_lp') ? 'paper_lp' : 'saa';
  const profile = model.endsWith('120') ? 'topsis_120' : 'all_candidates';
  const [base, setBase] = useState(null); const [error, setError] = useState(null); const [scenario, setScenario] = useState(scenarioId);
  useEffect(() => setScenario(scenarioId), [scenarioId]);
  useEffect(() => {
    let alive = true; setError(null); setBase(null);
    Promise.all([fetchJson('/api/sites'), fetchJson('/api/demand_points'), fetchJson('/api/hospitals'),
      kind === 'paper_lp' ? fetchJson(`/api/paper-lp/${profile}`) : fetchJson(`/api/saa/${profile}/detail`),
    ]).then(([sites, demand, hospitals, result]) => { if (alive) setBase({ sites, demand, hospitals, result }); })
      .catch((e) => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [kind, profile]);

  const scenarioRows = base?.result?.scenario_rows ?? [];
  const allocations = useMemo(() => {
    const rows = kind === 'paper_lp' ? (base?.result?.casualty_allocation ?? []) : (base?.result?.casualty_allocation ?? []);
    return rows.filter((r) => scenario === 'all' || String(r.scenario_id ?? '') === String(scenario));
  }, [base, kind, scenario]);
  const usedIds = new Set(allocations.filter((r) => (r.facility_set === 'JT' || r.facility_type === 'TMC') && Number(r.assigned_casualties) > 0).map((r) => r.facility_id ?? r.site_id));
  const siteById = Object.fromEntries((base?.sites ?? []).map((s) => [s.site_id, s]));
  const demandById = Object.fromEntries((base?.demand ?? []).map((d) => [d.sub_district_id, d]));
  const hospitals = base?.hospitals ?? [];
  const routes = allocations.map((r) => {
    const d = demandById[r.demand_point_id];
    const id = r.facility_id ?? r.site_id;
    const tmc = siteById[id] ?? siteById[id?.replace(/^JT_/, '')];
    const hid = String(id ?? '').replace(/^JH_/, '');
    const hospital = hospitals.find((h) => String(h.hospital_id) === hid || `JH_${h.hospital_id}` === id);
    const facility = r.facility_set === 'JT' || tmc ? tmc : hospital;
    const lat = facility?.latitude; const lon = facility?.longitude;
    return d && Number.isFinite(Number(lat)) && Number.isFinite(Number(lon))
      ? { d, lat: Number(lat), lon: Number(lon), id, amount: Number(r.assigned_casualties || 0), facility } : null;
  }).filter(Boolean).sort((a, b) => b.amount - a.amount);
  const routeSet = routes.slice(0, 90);
  if (error) return <div className="notice info">Stochastic allocation map unavailable: {error}. The paired outcomes are shown below when both profile summaries are exported.</div>;
  if (!base) return <div className="skeleton skeleton-map" />;
  return <section>
    <div className="map-controls"><label>{kind === 'paper_lp' ? 'Scenario' : 'Recorded policy'}: <select className="scenario" value={scenario} onChange={(e) => { setScenario(e.target.value); onScenarioChange(e.target.value); }}>
      {kind === 'paper_lp' ? <><option value="all">All scenarios</option>{scenarioRows.map((r) => <option key={r.scenario_id} value={r.scenario_id}>Scenario {r.scenario_id}</option>)}</> : <option value="all">Exported detailed policy</option>}
    </select></label><span className="num">{fmtInt(allocations.length)} allocation rows · {fmtInt(usedIds.size)} TMCs used</span></div>
    <div className="map-wrap"><MapContainer center={[37.575, 36.937]} zoom={8} minZoom={7} maxZoom={15} maxBounds={STUDY_BOUNDS} maxBoundsViscosity={1} className="map-container" preferCanvas>
      <TileLayer attribution='&copy; OpenStreetMap contributors &copy; CARTO' url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png" />
      {routeSet.map((r, i) => <Polyline key={`route-${i}`} positions={[[Number(r.d.latitude), Number(r.d.longitude)], [r.lat, r.lon]]} pathOptions={{ color: r.facility?.facility_type === 'hospital' ? '#66849b' : '#3d8061', weight: 1.2, opacity: .42 }} />)}
      {(base.demand ?? []).map((d) => <CircleMarker key={`d-${d.sub_district_id}`} center={[Number(d.latitude), Number(d.longitude)]} radius={6} pathOptions={{ color: '#315879', fillColor: '#86a9c4', fillOpacity: .85 }}><Tooltip>{d.name} · demand point</Tooltip></CircleMarker>)}
      {hospitals.map((h) => <CircleMarker key={`h-${h.hospital_id}`} center={[Number(h.latitude), Number(h.longitude)]} radius={7} pathOptions={{ color: '#9c4c40', fillColor: '#d67c6d', fillOpacity: .9 }}><Tooltip>{h.hospital_name} · hospital</Tooltip></CircleMarker>)}
      {[...usedIds].map((id) => { const s = siteById[id] ?? siteById[String(id).replace(/^JT_/, '')]; return s ? <CircleMarker key={`s-${id}`} center={[Number(s.latitude), Number(s.longitude)]} radius={5} pathOptions={{ color: '#246345', fillColor: '#57a579', fillOpacity: .9 }}><Tooltip>{s.name || id} · TMC used</Tooltip></CircleMarker> : null; })}
    </MapContainer><div className="legend"><b>Allocation overview</b><div>● Demand point</div><div>● Hospital</div><div>● TMC used</div><small>Showing up to 90 largest flows</small></div></div>
    <p className="muted">Paper LP TMCs are called used when they receive casualty flow; the LP has no explicit site-opening decision. Routes show the largest exported allocation flows for readability.</p>
  </section>;
}
