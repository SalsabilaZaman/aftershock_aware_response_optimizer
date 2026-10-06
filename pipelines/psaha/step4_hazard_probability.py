import os
import numpy as np
import pandas as pd
from scipy.stats import norm
from pathlib import Path


def exceedance_probability_single(ln_pga_median: float,
                                  sigma: float,
                                  g_star_g: float) -> float:
    z = (np.log(g_star_g) - ln_pga_median) / sigma
    return 1.0 - norm.cdf(z)


def compute_site_qi(sites_df: pd.DataFrame, catalog: pd.DataFrame,
                    mag_bins, mag_weights, g_star: float,
                    coeffs) -> pd.DataFrame:
    """q_i = P(one random aftershock produces PGA ≥ g* at site i).

    Magnitudes are drawn from the fitted Gutenberg–Richter distribution
    (mag_bins/mag_weights); locations from the observed aftershock epicentres
    (each equally likely — the catalog is the empirical spatial sample):

        q_i = Σ_m w_m · (1/E) Σ_e [1 − Φ((ln g* − ln PGA_med(m, R_ie, S_i)) / σ(m, R_ie, S_i))]

    σ is BSSA14's own heteroscedastic total sigma (varies with magnitude,
    distance and Vs30), not a fixed constant.
    """
    from step3_gmpe import haversine_distance, compute_pga_bssa14

    # distance matrix: sites × epicentres
    d_km = haversine_distance(
        sites_df['latitude'].values[:, None], sites_df['longitude'].values[:, None],
        catalog['latitude'].values[None, :], catalog['longitude'].values[None, :],
    )

    vs30 = sites_df['vs30_ms'].values[:, None]
    q = np.zeros(len(sites_df))
    for m, w in zip(mag_bins, mag_weights):
        ln_med, sigma = compute_pga_bssa14(m, d_km, vs30, coeffs)
        p_exc = 1.0 - norm.cdf((np.log(g_star) - ln_med) / sigma)
        q += w * p_exc.mean(axis=1)   # mean over epicentres

    return pd.DataFrame({'site_id': sites_df['site_id'].values, 'qi': q})


def compute_psaha_output(qi_df: pd.DataFrame, n_expected: float,
                         pga_table: pd.DataFrame) -> pd.DataFrame:
    """Poisson exceedance over the forecast window:
        Λ_i = N_window · q_i,   P_unsafe_i = 1 − exp(−Λ_i)
    PGA_representative_g is the largest median PGA any significant observed
    aftershock produced at the site (step 3 table) — a scenario-style value
    for maps, NOT the probabilistic quantity (that's P_unsafe)."""
    out = qi_df.copy()
    out['Lambda_i'] = n_expected * out['qi']
    out['P_unsafe'] = 1.0 - np.exp(-out['Lambda_i'])
    rep = (pga_table.groupby('site_id')['pga_median_g'].max()
           .rename('PGA_representative_g').reset_index())
    return out.merge(rep, on='site_id', how='left')


if __name__ == '__main__':
    BASE_DIR = Path(os.environ.get('PIPELINE_ROOT', Path(__file__).resolve().parents[2]))
    DATA_DIR = BASE_DIR / 'data_processed'
    OUTPUTS_DIR = BASE_DIR / 'outputs_psaha'

    # Import local modules (sibling files in same folder after move)
    from step1_omori import expected_aftershock_count
    from step2_gutenberg_richter import fit_gutenberg_richter
    from step3_gmpe import BSSA14_PGA_COEFFS

    catalog_path = DATA_DIR / 'seismic' / 'aftershock_catalog.csv'
    sites_path = DATA_DIR / 'sites' / 'candidate_sites.csv'
    soil_path = DATA_DIR / 'sites' / 'site_condition_per_site.csv'
    pga_table_path = OUTPUTS_DIR / 'pga_table.csv'
    omori_params_path = OUTPUTS_DIR / 'omori_params.csv'
    psaha_output_path = OUTPUTS_DIR / 'psaha_output_per_site.csv'

    df_cat = pd.read_csv(catalog_path)
    pga_table = pd.read_csv(pga_table_path)
    sites = pd.read_csv(sites_path)[['site_id', 'latitude', 'longitude']]
    soils = pd.read_csv(soil_path)[['site_id', 'vs30_ms']]
    sites_df = sites.merge(soils, on='site_id')

    omori_params = pd.read_csv(omori_params_path).iloc[0]
    N_30 = expected_aftershock_count(
        omori_params['K'], omori_params['c'], omori_params['p'], 0, 30
    )

    gr = fit_gutenberg_richter(df_cat['magnitude'].values, verbose=False)

    # g* = 0.2 g: EMS-scale threshold above which unreinforced/damaged masonry
    # takes further structural damage — the "unsafe for a field TMC" level.
    # (0.1 g classifies essentially every site in the epicentral region as
    # unsafe — it saturates P_unsafe at 1.0 and cannot discriminate.)
    qi = compute_site_qi(sites_df, df_cat, gr['mag_bins'], gr['mag_weights'],
                         g_star=0.2, coeffs=BSSA14_PGA_COEFFS)
    psaha_out = compute_psaha_output(qi, N_30, pga_table)

    print(psaha_out.describe().to_string())
    print(psaha_out.head(10).to_string(index=False))
    psaha_out.to_csv(psaha_output_path, index=False)
    print(f"\nSaved {len(psaha_out)} rows -> {psaha_output_path}")
