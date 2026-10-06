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
export const MODELS = ['risk_blind', 'risk_aware', 'paper_lp_all_candidates', 'paper_lp_topsis_120', 'saa_all_candidates', 'saa_topsis_120'];
const DEFAULT_MODEL = 'risk_aware';
const MODES = ['aware', 'blind'];
const DEFAULT_VIEW = 'briefing';
const DEFAULT_MODE = 'aware';

function readParams() {
  const params = new URLSearchParams(window.location.search);
  const view = VIEWS.includes(params.get('view')) ? params.get('view') : 'briefing';
  let mode = MODES.includes(params.get('mode')) ? params.get('mode') : DEFAULT_MODE;
  const model = MODELS.includes(params.get('model')) ? params.get('model') : (mode === 'blind' ? 'risk_blind' : DEFAULT_MODEL);
  if (model === 'risk_blind') mode = 'blind';
  if (model === 'risk_aware') mode = 'aware';
  const detail = params.get('detail') === 'research' ? 'research' : 'planner';
  const run = params.get('run') || '';
  return { view, mode, model, detail, run };
}

function writeParams(next) {
  const params = new URLSearchParams(window.location.search);
  params.set('view', next.view);
  params.set('mode', next.mode);
  params.set('model', next.model);
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
    detail: state.detail,
    setDetail,
    run: state.run,
    setRun,
  };
}
