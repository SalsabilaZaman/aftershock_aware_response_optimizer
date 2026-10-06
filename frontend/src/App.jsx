import React, { useEffect, useState } from 'react';
import { fetchJson } from './api.js';
import { fmtShortDate } from './format.js';
import { useUrlState, VIEWS, MODELS } from './useUrlState.js';
import Hazard from './views/Hazard.jsx';
import AllocationMap from './views/AllocationMap.jsx';
import Compare from './views/Compare.jsx';
import SAAResults from './views/SAAResults.jsx';
import PaperLPResults from './views/PaperLPResults.jsx';
import SiteDetail from './views/SiteDetail.jsx';
import AboutRun from './components/AboutRun.jsx';
import Briefing from './views/Briefing.jsx';
import ResearchLab from './views/ResearchLab.jsx';
import ProfileComparison from './views/ProfileComparison.jsx';
import SAAMedicalResponse from './views/SAAMedicalResponse.jsx';
import StochasticSiting from './views/StochasticSiting.jsx';

const TAB_LABELS = {
  briefing: 'Briefing', hazard: 'Hazard & site ranking', siting: 'Siting plan',
  medical: 'Medical response', robustness: 'Robustness', research: 'Research lab',
};
const MODEL_LABELS = {
  risk_blind: 'Risk-blind MILP', risk_aware: 'Risk-aware MILP',
  paper_lp_all_candidates: 'Paper LP · all candidates', paper_lp_topsis_120: 'Paper LP · TOPSIS top 120',
  saa_all_candidates: 'SAA · all candidates', saa_topsis_120: 'SAA · TOPSIS top 120',
};

const Brand = () => (
  <div className="brand">
    <span className="brand-mark" aria-hidden="true">◆</span>
    <div>
      <h1>Kahramanmaraş casualty response planning</h1>
      <p className="subtitle">
        Allocating earthquake casualties across hospitals and temporary medical centres in
        Kahramanmaraş, weighted by 30-day aftershock hazard.
      </p>
    </div>
  </div>
);

export default function App() {
  const [manifest, setManifest] = useState(null);
  const [sites, setSites] = useState(null);
  const [error, setError] = useState(null);
  const [detailSiteId, setDetailSiteId] = useState(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [modelOptions, setModelOptions] = useState([]);
  const [scenarioId, setScenarioId] = useState('all');
  const { view, setView, model, setModel, detail, setDetail } = useUrlState();

  const exportSelectedRun = async () => {
    const profile = model.endsWith('120') ? 'topsis_120' : 'all_candidates';
    const selectedModeKey = model === 'risk_blind' ? 'risk_blind' : 'risk_aware';
    const bundle = { model_id: model, profile_id: model.startsWith('paper_lp') || model.startsWith('saa_') ? profile : null,
      run_id: manifest?.data_source?.job_id ?? 'reference', exported_at: new Date().toISOString(), selected_view: view };
    try {
      if (model.startsWith('paper_lp')) {
        const [result, siteRows] = await Promise.all([fetchJson(`/api/paper-lp/${profile}`), fetchJson('/api/sites')]);
        bundle.casualty_allocations = result.casualty_allocation;
        bundle.staff_allocations = result.staffing_plan;
        bundle.scenario_results = result.scenario_rows;
        const lpTotal = (key) => result.scenario_rows.reduce((sum, row) => sum + Number(row.scenario_prob || 0) * Number(row[key] || 0), 0);
        bundle.summary = { expected_served_fraction: lpTotal('served_fraction'), expected_unmet_casualties: lpTotal('Z1'), expected_Z2: lpTotal('Z2'), expected_Z3: lpTotal('Z3') };
        bundle.ranked_sites = siteRows.filter((s) => Number.isFinite(Number(s.rank))).sort((a, b) => Number(a.rank) - Number(b.rank));
      } else if (model.startsWith('saa_')) {
        const [result, siteRows] = await Promise.all([fetchJson(`/api/saa/${profile}`), fetchJson('/api/sites')]);
        bundle.budget_results = result.budget_rows;
        bundle.summary = result.budget_rows.reduce((a, b) => Number(b.budget) > Number(a?.budget ?? -Infinity) ? b : a, null);
        bundle.ranked_sites = siteRows.filter((s) => Number.isFinite(Number(s.rank))).sort((a, b) => Number(a.rank) - Number(b.rank));
        try { bundle.policy_detail = await fetchJson(`/api/saa/${profile}/detail`); }
        catch (e) { bundle.detail_unavailable_reason = e.message; bundle.casualty_allocations = []; bundle.staff_allocations = []; }
        bundle.casualty_allocations ??= bundle.policy_detail?.casualty_allocation ?? [];
        bundle.staff_allocations ??= bundle.policy_detail?.staffing ?? [];
      } else {
        const [result, siteRows] = await Promise.all([fetchJson(`/api/solutions/${selectedModeKey}`), fetchJson('/api/sites')]);
        bundle.casualty_allocations = result.casualty_allocation;
        bundle.staff_allocations = result.tmc_selected.map((row) => ({ site_id: row.site_id, staff_assigned: row.staff_assigned ?? null }));
        bundle.summary = { allocated_casualties: result.casualty_allocation.reduce((sum, row) => sum + Number(row.assigned_casualties || 0), 0), selected_tmc_count: result.tmc_selected.length };
        bundle.ranked_sites = siteRows.filter((s) => Number.isFinite(Number(s.rank))).sort((a, b) => Number(a.rank) - Number(b.rank));
        bundle.selected_sites = result.tmc_selected;
      }
      bundle.run_identifiers = { model: model, mode: selectedModeKey, source: manifest?.data_source ?? null, generated_utc: manifest?.generated_utc ?? null };
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url;
      a.download = `earthquake-response-${model}-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(`Export failed: ${e.message}`); }
  };

  const reloadData = () => {
    setError(null);
    fetchJson('/api/scenarios').then(setManifest).catch((e) => setError(e.message));
    fetchJson('/api/sites').then(setSites).catch((e) => setError(e.message));
    fetchJson('/api/model-options').then((r) => setModelOptions(r.choices ?? [])).catch(() => setModelOptions([]));
  };

  useEffect(() => {
    reloadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDetail = (siteId) => setDetailSiteId(siteId);

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-top">
          <Brand />
          <div className="header-controls">
            {manifest?.generated_utc && (
              <span className="badge" title={`Computed ${manifest.generated_utc}`}>
                Reference results · {fmtShortDate(manifest.generated_utc)}
              </span>
            )}
            <button className="link-btn" onClick={() => setAboutOpen(true)}>About this run</button>
            <button className="btn-ghost" onClick={exportSelectedRun}>Export selected run</button>
          </div>
        </div>

        <div className="dashboard-toolbar">
          <nav className="tabs" aria-label="Dashboard views" style={{ flex: 1, borderBottom: 'none', margin: 0 }}>
            {VIEWS.map((id) => (
              <button key={id} className={view === id ? 'active' : ''} onClick={() => setView(id)}>
                {TAB_LABELS[id]}
              </button>
            ))}
          </nav>
          <div className="presentation-switch" aria-label="Presentation detail">
            <button className={detail === 'planner' ? 'active' : ''} onClick={() => setDetail('planner')}>Planner</button>
            <button className={detail === 'research' ? 'active' : ''} onClick={() => setDetail('research')}>Research</button>
          </div>
        </div>
        <div className="model-selector" aria-label="Model variant">
          {MODELS.map((id) => {
            const option = modelOptions.find((item) => item.id === id);
            const available = option?.available ?? false;
            return <button key={id} className={model === id ? 'active' : ''} disabled={!available}
              title={available ? MODEL_LABELS[id] : `${MODEL_LABELS[id]} · results unavailable`}
              onClick={() => setModel(id)}>{MODEL_LABELS[id]}{!available && <small>Unavailable</small>}</button>;
          })}
        </div>
      </header>

      {error && (
        <div className="notice">
          Published result data could not be loaded: {error}. Please try the site again later.
        </div>
      )}

      {view === 'briefing' && <Briefing model={model} manifest={manifest} detail={detail} />}
      {view === 'hazard' && <Hazard manifest={manifest} sites={sites} mode={model === 'risk_blind' ? 'blind' : 'aware'} modeKey={model === 'risk_blind' ? 'risk_blind' : 'risk_aware'} onSelectSite={openDetail} />}
      {view === 'siting' && (model.startsWith('paper_lp') || model.startsWith('saa_')
        ? <><StochasticSiting model={model} scenarioId={scenarioId} onScenarioChange={setScenarioId} /><ProfileComparison model={model} sites={sites} /></>
        : <><AllocationMap modeKey={model === 'risk_blind' ? 'risk_blind' : 'risk_aware'} /><Compare sites={sites} onSelectSite={openDetail} /></>)}
      {view === 'medical' && (model.startsWith('paper_lp')
        ? <PaperLPResults profile={model.endsWith('120') ? 'topsis_120' : 'all_candidates'} scenarioId={scenarioId} onScenarioChange={setScenarioId} detail={detail} />
        : model.startsWith('saa_')
          ? <SAAMedicalResponse profile={model.endsWith('120') ? 'topsis_120' : 'all_candidates'} detail={detail} />
          : <div className="notice info"><b>Medical response detail unavailable for this run.</b><br />The selected model export does not include period-level casualty allocations or staffing by triage. Facility occupancy and health-state transitions are also unavailable in the current results.</div>)}
      {view === 'robustness' && (model.startsWith('saa_')
        ? <SAAResults profile={model.endsWith('120') ? 'topsis_120' : 'all_candidates'} comparison />
        : model.startsWith('paper_lp') ? <ProfileComparison model={model} sites={sites} />
          : <div className="notice info">Robustness results are unavailable for this model. Sensitivity and out-of-sample measures are only shown for exported stochastic runs.</div>)}
      {view === 'research' && <ResearchLab model={model} detail={detail} manifest={manifest} />}

      {detailSiteId && (
        <SiteDetail siteId={detailSiteId} onClose={() => setDetailSiteId(null)} />
      )}
      {aboutOpen && <AboutRun manifest={manifest} onClose={() => setAboutOpen(false)} />}
    </div>
  );
}
