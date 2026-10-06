import os
import numpy as np
import pandas as pd
from pathlib import Path

# BSSA14 (Boore, Stewart, Seyhan & Atkinson 2014, Earthquake Spectra 30(3),
# "NGA-West2 Equations for Predicting PGA, PGV, and 5%-Damped PSA for
# Shallow Crustal Earthquakes"), PGA-period coefficients only (Table 8 of
# the paper / the "pga" row of their electronic supplement). Values below
# are transcribed from the openquake-hazardlib reference implementation
# (openquake.hazardlib.gsim.boore_2014, GEM Foundation, AGPL-3.0), which
# packages the paper's published coefficient table verbatim — not re-derived
# or estimated. Only the PGA row is used; this project doesn't need SA(T).
BSSA14_PGA_COEFFS = {
    'e0': 0.4473, 'e1': 0.4856, 'e2': 0.2459, 'e3': 0.4539,
    'e4': 1.4310, 'e5': 0.05053, 'e6': -0.1662, 'Mh': 5.5,
    'c1': -1.1340, 'c2': 0.1917, 'c3': -0.008088, 'h': 4.5, 'Dc3': 0.0,
    'c': -0.600, 'Vc': 1500.0, 'f4': -0.150, 'f5': -0.00701,
    'R1': 110.0, 'R2': 270.0, 'DfR': 0.100, 'DfV': 0.070,
    'f1': 0.695, 'f2': 0.495, 'tau1': 0.398, 'tau2': 0.348,
}
BSSA14_CONSTS = {
    'Mref': 4.5, 'Rref': 1.0, 'Vref': 760.0, 'f1': 0.0, 'f3': 0.1,
    'v1': 225.0, 'v2': 300.0,
}

# The EAFZ 2023 sequence (mainshock, the Mw7.5 Elbistan event, and the
# aftershocks) is a predominantly strike-slip rupture system, so the
# style-of-faulting term is fixed to BSSA14's strike-slip coefficient (e1)
# for every event rather than solved from a per-event rake angle, which the
# aftershock catalog does not carry.


def haversine_distance(lat1: float, lon1: float,
                        lat2: float, lon2: float) -> float:
    R_earth = 6371.0
    φ1, φ2 = np.radians(lat1), np.radians(lat2)
    dφ = np.radians(lat2 - lat1)
    dλ = np.radians(lon2 - lon1)
    a = np.sin(dφ/2)**2 + np.cos(φ1) * np.cos(φ2) * np.sin(dλ/2)**2
    return R_earth * 2 * np.arcsin(np.sqrt(a))


def compute_pga_bssa14(magnitude, rjb_km, vs30,
                        coeffs=BSSA14_PGA_COEFFS, consts=BSSA14_CONSTS):
    """BSSA14 median PGA[g] and total aleatory sigma (ln units).

    magnitude: scalar or array (event magnitude, Mw)
    rjb_km: array — Joyner-Boore distance. No finite-fault geometry exists
        for the aftershock catalog, so epicentral distance is used as a
        point-source proxy for Rjb; BSSA14's own fictitious-depth term
        R = sqrt(Rjb^2 + h^2) already accounts for near-field saturation,
        which is the reason a bare epicentral distance is an accepted
        point-source approximation here.
    vs30: array, broadcastable against rjb_km — site Vs30 in m/s.

    Returns (ln_pga_median, sigma_total), both broadcast to the shape of
    (magnitude, rjb_km, vs30) together.
    """
    M = np.asarray(magnitude, dtype=float)
    Rjb = np.asarray(rjb_km, dtype=float)
    Vs30 = np.asarray(vs30, dtype=float)

    Mh = coeffs['Mh']
    dmag = M - Mh
    mag_term = np.where(
        M <= Mh,
        coeffs['e4'] * dmag + coeffs['e5'] * dmag ** 2,
        coeffs['e6'] * dmag,
    )
    FE = coeffs['e1'] + mag_term  # strike-slip event term (see module note)

    R = np.sqrt(Rjb ** 2 + coeffs['h'] ** 2)
    FP = ((coeffs['c1'] + coeffs['c2'] * (M - consts['Mref']))
          * np.log(R / consts['Rref'])
          + (coeffs['c3'] + coeffs['Dc3']) * (R - consts['Rref']))

    ln_pga_rock = FE + FP  # median PGA on Vref=760 m/s rock (no site term)
    pga_rock_g = np.exp(ln_pga_rock)

    v_star = np.minimum(Vs30, coeffs['Vc'])
    FLIN = coeffs['c'] * np.log(v_star / consts['Vref'])

    v_s = np.minimum(Vs30, 760.0)
    f2 = coeffs['f4'] * (np.exp(coeffs['f5'] * (v_s - 360.0))
                          - np.exp(coeffs['f5'] * 400.0))
    FNL = consts['f1'] + f2 * np.log((pga_rock_g + consts['f3']) / consts['f3'])

    ln_pga_median = FE + FP + FLIN + FNL

    tau = np.where(M <= 4.5, coeffs['tau1'],
                   np.where(M >= 5.5, coeffs['tau2'],
                            coeffs['tau1'] + (coeffs['tau2'] - coeffs['tau1']) * (M - 4.5)))
    phi = np.where(M <= 4.5, coeffs['f1'],
                   np.where(M >= 5.5, coeffs['f2'],
                            coeffs['f1'] + (coeffs['f2'] - coeffs['f1']) * (M - 4.5)))
    # broadcast phi (magnitude-only so far) up to the (Rjb, Vs30) shape
    phi = phi + np.zeros_like(ln_pga_median)
    dist_adj = np.where(
        Rjb > coeffs['R2'], coeffs['DfR'],
        np.where(Rjb > coeffs['R1'],
                 coeffs['DfR'] * (np.log(np.maximum(Rjb, 1e-9) / coeffs['R1'])
                                   / np.log(coeffs['R2'] / coeffs['R1'])),
                 0.0),
    )
    site_adj = np.where(
        Vs30 <= consts['v1'], -coeffs['DfV'],
        np.where(Vs30 <= consts['v2'],
                 -coeffs['DfV'] * (np.log(consts['v2'] / np.maximum(Vs30, 1e-9))
                                    / np.log(consts['v2'] / consts['v1'])),
                 0.0),
    )
    phi = phi + dist_adj + site_adj
    sigma_total = np.sqrt(tau ** 2 + phi ** 2)

    return ln_pga_median, sigma_total


def compute_pga_table(sites_df: pd.DataFrame, catalog: pd.DataFrame,
                      min_magnitude: float = 5.0,
                      coeffs=BSSA14_PGA_COEFFS) -> pd.DataFrame:
    """Per-site median PGA (and BSSA14 sigma) for each significant aftershock
    (M >= min_magnitude). Only significant events are tabulated here — the
    full-catalog exceedance integration in step 4 recomputes distances in
    memory; this table is the inspectable per-scenario PGA record (and
    feeds PGA_representative_g)."""
    sig = catalog[catalog['magnitude'] >= min_magnitude].reset_index(drop=True)
    rows = []
    for _, ev in sig.iterrows():
        d_km = haversine_distance(sites_df['latitude'].values, sites_df['longitude'].values,
                                  ev['latitude'], ev['longitude'])
        ln_med, sigma = compute_pga_bssa14(ev['magnitude'], d_km, sites_df['vs30_ms'].values, coeffs)
        rows.append(pd.DataFrame({
            'site_id': sites_df['site_id'].values,
            'event_id': ev['event_id'],
            'magnitude': ev['magnitude'],
            'distance_km': d_km,
            'ln_pga_median': ln_med,
            'pga_median_g': np.exp(ln_med),
            'sigma': sigma,
        }))
    return pd.concat(rows, ignore_index=True).sort_values(['site_id', 'event_id'])

if __name__ == '__main__':
    BASE_DIR = Path(os.environ.get('PIPELINE_ROOT', Path(__file__).resolve().parents[2]))
    DATA_DIR = BASE_DIR / 'data_processed'
    OUTPUTS_DIR = BASE_DIR / 'outputs_psaha'

    catalog_path = DATA_DIR / 'seismic' / 'aftershock_catalog.csv'
    sites_path = DATA_DIR / 'sites' / 'candidate_sites.csv'
    soil_path = DATA_DIR / 'sites' / 'site_condition_per_site.csv'
    pga_table_path = OUTPUTS_DIR / 'pga_table.csv'

    OUTPUTS_DIR.mkdir(exist_ok=True)

    sites = pd.read_csv(sites_path)[['site_id', 'latitude', 'longitude']]
    soils = pd.read_csv(soil_path)[['site_id', 'vs30_ms']]
    sites_df = pd.merge(sites, soils, on='site_id')

    catalog = pd.read_csv(catalog_path)
    catalog['event_id'] = range(len(catalog))

    pga_table = compute_pga_table(sites_df, catalog)
    print(pga_table.head(8).to_string(index=False))
    pga_table.to_csv(pga_table_path, index=False)
