import React, { useEffect, useState } from 'react';
import { fetchJson, setActiveRunId } from './api.js';
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
import RunWorkspace from './views/RunWorkspace.jsx';
import { downloadCsvZip } from './exportBundle.js';

const TAB_LABELS = {
  briefing: 'Briefing', hazard: 'Hazard & site ranking', siting: 'Siting plan',
  medical: 'Medical response', robustness: 'Robustness', research: 'Research lab',
};
const Brand = () => (
  <div className="brand">
    <div>
      <div className="brand-kicker">AARO · AFTERSHOCK-AWARE RESPONSE OPTIMIZER</div>
      <h1>Earthquake Response Planning</h1>
      <p className="subtitle">Allocate casualties across medical facilities while accounting for aftershock risk.</p>
    </div>
  </div>
);

export default function App() {
  const [manifest, setManifest] = useState(null);
  const [sites, setSites] = useState(null);
  const [error, setError] = useState(null);
  const [detailSiteId, setDetailSiteId] = useState(null);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [modelOptions, setModelOptions] = useState({ choices: [], candidate_sets: {}, candidate_set_label: 'Candidate set' });
  const [scenarioId, setScenarioId] = useState('all');
  const { view, setView, model, setModel, candidateSet, setCandidateSet, detail, setDetail, run, setRun, screen, setScreen } = useUrlState();
  setActiveRunId(run);

  const exportSelectedRun = async () => {
    const profile = candidateSet;
    const selectedModeKey = model === 'risk_blind' ? 'risk_blind' : 'risk_aware';
    const bundle = { model_id: model, profile_id: ['paper_lp', 'saa'].includes(model) ? profile : null,
      run_id: manifest?.data_source?.job_id ?? 'reference', exported_at: new Date().toISOString(), selected_view: view };
    try {
      if (model === 'paper_lp') {
        const [result, siteRows] = await Promise.all([fetchJson(`/api/paper-lp/${profile}`), fetchJson('/api/sites')]);
        bundle.casualty_allocations = result.casualty_allocation;
        bundle.staff_allocations = result.staffing_plan;
        bundle.unmet_by_triage = result.unmet_by_triage;
        bundle.scenario_results = result.scenario_rows;
        bundle.sensitivity_results = result.sensitivity_rows;
        const lpTotal = (key) => result.scenario_rows.reduce((sum, row) => sum + Number(row.scenario_prob || 0) * Number(row[key] || 0), 0);
        bundle.summary = { expected_served_fraction: lpTotal('served_fraction'), expected_unmet_casualties: lpTotal('Z1'), expected_Z2: lpTotal('Z2'), expected_Z3: lpTotal('Z3') };
        bundle.ranked_sites = siteRows.filter((s) => Number.isFinite(Number(s.rank))).sort((a, b) => Number(a.rank) - Number(b.rank));
      } else if (model === 'saa') {
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
      const csvFiles = {};
      for (const key of ['casualty_allocations', 'staff_allocations', 'unmet_by_triage', 'scenario_results', 'sensitivity_results', 'budget_results', 'ranked_sites', 'selected_sites']) {
        if (Array.isArray(bundle[key]) && bundle[key].length) csvFiles[`${key}.csv`] = bundle[key];
      }
      if (Array.isArray(bundle.policy_detail?.unmet) && bundle.policy_detail.unmet.length) {
        csvFiles['unmet.csv'] = bundle.policy_detail.unmet;
      }
      const summary = [
        'Earthquake Response Planning — exported results',
        `Model: ${model}`,
        `Candidate profile: ${profile ?? 'not applicable'}`,
        `Run ID: ${bundle.run_id}`,
        `Exported UTC: ${bundle.exported_at}`,
        `Source generated UTC: ${bundle.run_identifiers?.generated_utc ?? 'unknown'}`,
        `Selected dashboard view: ${view}`,
        '',
        'Summary metrics:',
        ...Object.entries(bundle.summary ?? {}).map(([key, value]) => `  ${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`),
        '',
        'CSV files:',
        ...Object.keys(csvFiles).map((name) => `  ${name}`),
        '',
        'Source identifiers:',
        ...Object.entries(bundle.run_identifiers ?? {}).map(([key, value]) => `  ${key}: ${typeof value === 'object' ? JSON.stringify(value) : value}`),
      ].join('\n');
      await downloadCsvZip(csvFiles, summary,
        `earthquake-response-${model}-${new Date().toISOString().slice(0, 10)}.zip`);
    } catch (e) { setError(`Export failed: ${e.message}`); }
  };

  const reloadData = () => {
    setError(null);
    fetchJson('/api/scenarios').then(setManifest).catch((e) => setError(e.message));
    fetchJson('/api/sites').then(setSites).catch((e) => setError(e.message));
    fetchJson('/api/model-options').then(setModelOptions).catch(() => setModelOptions({ choices: [], candidate_sets: {} }));
  };

  useEffect(() => {
    if (!run) {
      reloadData();
    } else {
      setManifest(null);
      setSites(null);
      setModelOptions({ choices: [], candidate_sets: {}, candidate_set_label: 'Candidate set' });
      setError(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run]);

  const openDetail = (siteId) => setDetailSiteId(siteId);
  const selectedModelOption = modelOptions.choices.find((item) => item.id === model);
  const modelLabels = manifest?.model_labels?.models ?? {};
  const selectedModelLabel = selectedModelOption?.label ?? modelLabels[model] ?? model;
  const candidateSetLabel = modelOptions.candidate_sets?.[candidateSet] ?? manifest?.model_labels?.candidate_sets?.[candidateSet] ?? candidateSet;
  const isCandidateProfileModel = model === 'paper_lp' || model === 'saa';
  const selectedProfileAvailable = isCandidateProfileModel
    ? selectedModelOption?.profiles?.[candidateSet]?.available : selectedModelOption?.available;

  if (screen === 'welcome') {
    return (
      <div className="app welcome-page">
        <header className="welcome-header"><Brand /></header>
        <RunWorkspace
          runId={run}
          onSelectRun={setRun}
          onEnterDashboard={() => setScreen('dashboard')}
          onRunComplete={() => { reloadData(); setScreen('dashboard'); }}
        />
      </div>
    );
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-top">
          <Brand />
          <div className="header-controls">
            <button className="btn-ghost" onClick={() => setScreen('welcome')}>Home · change run</button>
            {manifest?.generated_utc && (
              <span className="badge" title={`Computed ${manifest.generated_utc}`}>
                {manifest.data_source?.kind === 'job' ? 'Saved run' : 'Reference results'} · {fmtShortDate(manifest.generated_utc)}
              </span>
            )}
            <button className="link-btn" onClick={() => setAboutOpen(true)}>How to read this</button>
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
        {view !== 'hazard' && <div className="model-controls">
          <div className="model-selector" aria-label="Model">
            {MODELS.map((id) => {
              const option = modelOptions.choices.find((item) => item.id === id);
              const label = option?.label ?? modelLabels[id] ?? id;
              return <button key={id} className={model === id ? 'active' : ''} aria-pressed={model === id} onClick={() => setModel(id)}>{label}</button>;
            })}
          </div>
          {isCandidateProfileModel && <div className="candidate-set-selector" role="group" aria-label={modelOptions.candidate_set_label ?? 'Candidate set'}>
            <span>{modelOptions.candidate_set_label ?? 'Candidate set'}</span>
            {Object.entries(modelOptions.candidate_sets ?? {}).map(([id, label]) => <button key={id} className={candidateSet === id ? 'active' : ''} aria-pressed={candidateSet === id} onClick={() => setCandidateSet(id)}>{label}</button>)}
          </div>}
        </div>}
      </header>

      {error && (
        <div className="notice">
          {run ? 'Selected run data' : 'Published result data'} could not be loaded: {error}. Please try again later.
        </div>
      )}

      <main key={run || 'reference'}>
      {view === 'briefing' && <Briefing model={model} candidateSet={candidateSet} manifest={manifest} detail={detail} />}
      {view === 'hazard' && <Hazard manifest={manifest} sites={sites} onSelectSite={openDetail} />}
      {view === 'siting' && (isCandidateProfileModel
        ? <><StochasticSiting model={model} profile={candidateSet} scenarioId={scenarioId} onScenarioChange={setScenarioId} /><ProfileComparison model={model} sites={sites} /></>
        : <><AllocationMap modeKey={model} /><Compare sites={sites} onSelectSite={openDetail} /></>)}
      {view === 'medical' && (model === 'paper_lp'
        ? <PaperLPResults profile={candidateSet} scenarioId={scenarioId} onScenarioChange={setScenarioId} detail={detail} />
        : model === 'saa'
          ? <SAAMedicalResponse profile={candidateSet} detail={detail} />
          : <div className="notice info"><b>Medical response detail unavailable for this run.</b><br />The selected model export does not include period-level casualty allocations or staffing by triage. Facility occupancy and health-state transitions are also unavailable in the current results.</div>)}
      {view === 'robustness' && (model === 'saa'
        ? <SAAResults profile={candidateSet} comparison />
        : model === 'paper_lp' ? <ProfileComparison model={model} sites={sites} />
          : <div className="notice info">Robustness results are unavailable for this model. Sensitivity and out-of-sample measures are only shown for exported stochastic runs.</div>)}
      {view === 'research' && <ResearchLab model={model} />}

      {view !== 'hazard' && selectedProfileAvailable === false && <div className="notice info" role="status">{selectedModelLabel}{isCandidateProfileModel ? ` · ${candidateSetLabel}` : ''} results are not included in this data bundle.</div>}

      {detailSiteId && (
        <SiteDetail siteId={detailSiteId} onClose={() => setDetailSiteId(null)} />
      )}
      {aboutOpen && <AboutRun manifest={manifest} onClose={() => setAboutOpen(false)} />}
      </main>
    </div>
  );
}
