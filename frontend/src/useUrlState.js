import { useCallback, useEffect, useState } from 'react';

// Single source of truth for the two pieces of global state (view, solver
// mode) that used to be duplicated across tabs/dropdowns. Synced to the URL
// via history.replaceState (no react-router — this app has exactly three
// query params, not enough state to justify a routing dependency) so every
// view is deep-linkable and state survives a reload.
//
// `run` is carried in the URL for shareability, but the public Pages build
// serves one fixed reference snapshot rather than dynamically selected runs.
export const VIEWS = ['briefing', 'hazard', 'siting', 'medical', 'robustness', 'research'];
export const MODELS = ['risk_blind', 'risk_aware', 'paper_lp', 'saa'];
export const CANDIDATE_SETS = ['all_candidates', 'topsis_120'];
const DEFAULT_MODEL = 'risk_aware';
const MODES = ['aware', 'blind'];
const DEFAULT_VIEW = 'briefing';
const DEFAULT_MODE = 'aware';

function readParams() {
  const params = new URLSearchParams(window.location.search);
  const view = VIEWS.includes(params.get('view')) ? params.get('view') : 'briefing';
  let mode = MODES.includes(params.get('mode')) ? params.get('mode') : DEFAULT_MODE;
  const rawModel = params.get('model');
  const legacyProfile = rawModel?.endsWith('_topsis_120') ? 'topsis_120' : 'all_candidates';
  const legacyModel = rawModel?.startsWith('paper_lp') ? 'paper_lp' : rawModel?.startsWith('saa_') ? 'saa' : rawModel;
  const model = MODELS.includes(legacyModel) ? legacyModel : (mode === 'blind' ? 'risk_blind' : DEFAULT_MODEL);
  const candidateSet = CANDIDATE_SETS.includes(params.get('candidate_set')) ? params.get('candidate_set') : legacyProfile;
  if (model === 'risk_blind') mode = 'blind';
  if (model === 'risk_aware') mode = 'aware';
  const detail = params.get('detail') === 'research' ? 'research' : 'planner';
  const run = params.get('run') || '';
  return { view, mode, model, candidateSet, detail, run };
}

function writeParams(next) {
  const params = new URLSearchParams(window.location.search);
  params.set('view', next.view);
  params.set('mode', next.mode);
  params.set('model', next.model);
  params.set('candidate_set', next.candidateSet);
  params.set('detail', next.detail);
  if (next.run) params.set('run', next.run);
  else params.delete('run');
  const url = `${window.location.pathname}?${params.toString()}`;
  window.history.replaceState(null, '', url);
}

export function useUrlState() {
  const [state, setState] = useState(readParams);

  useEffect(() => {
    writeParams(state);
  }, [state]);

  const setView = useCallback((view) => setState((s) => ({ ...s, view })), []);
  const setMode = useCallback((mode) => setState((s) => ({ ...s, mode })), []);
  const setModel = useCallback((model) => setState((s) => ({
    ...s, model,
    ...(model === 'risk_blind' ? { mode: 'blind' } : model === 'risk_aware' ? { mode: 'aware' } : {}),
  })), []);
  const setCandidateSet = useCallback((candidateSet) => setState((s) => ({ ...s, candidateSet })), []);
  const setDetail = useCallback((detail) => setState((s) => ({ ...s, detail })), []);
  const setRun = useCallback((run) => setState((s) => ({ ...s, run })), []);

  return {
    view: state.view,
    setView,
    mode: state.mode,
    setMode,
    modeKey: state.mode === 'blind' ? 'risk_blind' : 'risk_aware',
    model: state.model,
    setModel,
    candidateSet: state.candidateSet,
    setCandidateSet,
    detail: state.detail,
    setDetail,
    run: state.run,
    setRun,
  };
}
