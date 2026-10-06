// Published demo mode reads a frozen JSON export from GitHub Pages.
export async function fetchJson(path) {
  const [endpoint, query = ''] = path.split('?');
  const apiPath = endpoint.replace(/^\/api\/?/, '');
  let route = apiPath.startsWith('paper-lp/') ? apiPath.replace('paper-lp/', 'paper_lp/') : apiPath;
  if (apiPath === 'scenarios') route = 'scenarios';
  else if (apiPath === 'model-options') route = 'model-options';
  else if (apiPath === 'sites') route = 'sites';
  else if (apiPath === 'hospitals') route = 'hospitals';
  else if (apiPath === 'demand_points') route = 'demand_points';
  else if (apiPath === 'site_status') route = 'site_status';
  else if (/^solutions\/(risk_blind|risk_aware)$/.test(apiPath)) route = apiPath;
  else if (/^sites\/[^/]+$/.test(apiPath)) route = 'sites';

  const url = new URL(`${import.meta.env.BASE_URL}data/api/${route}.json`, window.location.href);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Published result unavailable (${res.status})`);
  const value = await res.json();

  if (apiPath.startsWith('sites/')) {
    const siteId = decodeURIComponent(apiPath.slice('sites/'.length));
    const site = value.find((row) => String(row.site_id) === siteId);
    if (!site) throw new Error(`Unknown site_id ${siteId}`);
    const statusUrl = new URL(`${import.meta.env.BASE_URL}data/api/site_status.json`, window.location.href);
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
