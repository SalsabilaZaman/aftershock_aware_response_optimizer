// Reference results are served as static files; uploaded runs use the AARO API.
const API_BASE = (import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:8000' : '')).replace(/\/$/, '');
let activeRunId = '';

export function setActiveRunId(runId) { activeRunId = runId || ''; }
export function getApiBase() { return API_BASE; }

export async function backendFetch(path, options = {}) {
  const url = API_BASE ? `${API_BASE}${path}` : `${import.meta.env.BASE_URL}${path.replace(/^\//, '')}`;
  return fetch(url, options);
}

async function readResponse(res) {
  if (res.ok) return res;
  let detail = res.statusText || `HTTP ${res.status}`;
  try {
    const body = await res.json();
    detail = typeof body.detail === 'string' ? body.detail : body.detail?.message || JSON.stringify(body.detail || body);
  } catch { /* keep the HTTP status */ }
  throw new Error(detail);
}

export async function fetchJson(path) {
  const [endpoint, query = ''] = path.split('?');
  const apiPath = endpoint.replace(/^\/api\/?/, '');
  let route = apiPath.startsWith('paper-lp/') ? apiPath.replace('paper-lp/', 'paper_lp/') : apiPath;
  if (/^saa\/(all_candidates|topsis_120)(\/detail)?$/.test(apiPath)) route = apiPath.replace(/\/detail$/, '');
  if (apiPath === 'scenarios') route = 'scenarios';
  else if (apiPath === 'model-options') route = 'model-options';
  else if (apiPath === 'sites') route = 'sites';
  else if (apiPath === 'hospitals') route = 'hospitals';
  else if (apiPath === 'demand_points') route = 'demand_points';
  else if (apiPath === 'site_status') route = 'site_status';
  else if (/^solutions\/(risk_blind|risk_aware)$/.test(apiPath)) route = apiPath;
  else if (/^sites\/[^/]+$/.test(apiPath)) route = 'sites';

  let res;
  if (activeRunId) {
    const url = new URL(`${API_BASE}/api/${route}.json`, window.location.href);
    url.searchParams.set('run_id', activeRunId);
    res = await fetch(url, { cache: 'no-store' });
  } else {
    const url = new URL(`${import.meta.env.BASE_URL}data/api/${route}.json`, window.location.href);
    res = await fetch(url);
  }
  if (!res.ok) {
    if (activeRunId) await readResponse(res);
    throw new Error(`Published result unavailable (${res.status})`);
  }
  if (!res.headers.get('content-type')?.includes('application/json')) {
    throw new Error(`Published result ${route}.json is missing or not JSON; regenerate it from the reference CSV bundle`);
  }
  const value = await res.json();

  if (apiPath.startsWith('sites/')) {
    const siteId = decodeURIComponent(apiPath.slice('sites/'.length));
    const site = value.find((row) => String(row.site_id) === siteId);
    if (!site) throw new Error(`Unknown site_id ${siteId}`);
    const statusUrl = activeRunId
      ? new URL(`${API_BASE}/api/site_status.json`, window.location.href)
      : new URL(`${import.meta.env.BASE_URL}data/api/site_status.json`, window.location.href);
    if (activeRunId) statusUrl.searchParams.set('run_id', activeRunId);
    const statusResponse = await fetch(statusUrl);
    const statuses = statusResponse.ok ? await statusResponse.json() : [];
    return { ...site, status: statuses.find((row) => String(row.site_id) === siteId) ?? null };
  }

  const params = new URLSearchParams(query);
  if (apiPath.startsWith('paper-lp/') && params.has('scenario_id')) {
    const scenario = Number(params.get('scenario_id'));
    return { ...value,
      casualty_allocation: value.casualty_allocation.filter((row) => Number(row.scenario_id) === scenario),
      unmet_by_triage: value.unmet_by_triage.filter((row) => Number(row.scenario_id) === scenario),
      staffing_plan: value.staffing_plan.filter((row) => Number(row.scenario_id) === scenario),
    };
  }
  return value;
}
