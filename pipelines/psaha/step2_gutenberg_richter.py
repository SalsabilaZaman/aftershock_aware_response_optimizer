
import os
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib.pyplot as plt
from pathlib import Path

def fit_gutenberg_richter(magnitudes: np.ndarray,
                           M_min: float = None,
                           bin_width: float = 0.2,
                           verbose: bool = True) -> dict:
    # ... unchanged body ...
    if M_min is None:
        M_min = np.floor(magnitudes.min() * 10) / 10

    m_bins = np.arange(M_min, magnitudes.max() + bin_width, bin_width)
    N_cum  = np.array([np.sum(magnitudes >= m) for m in m_bins])
    valid  = N_cum > 0
    m_fit  = m_bins[valid]
    y_fit  = np.log10(N_cum[valid])
    slope, intercept, r_val, p_val, se = stats.linregress(m_fit, y_fit)
    a_hat =  intercept
    b_hat = -slope
    raw_weights  = 10**(-b_hat * m_bins)
    norm_weights = raw_weights / raw_weights.sum()
    return {
        'a': a_hat, 'b': b_hat, 'r_squared': r_val**2,
        'mag_bins': m_bins,
        'mag_weights': norm_weights,
        'N_cum': N_cum[valid],
        'm_fit': m_fit
    }


def plot_gr_fit(result: dict, output_path=None):
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.scatter(result['m_fit'], np.log10(result['N_cum']),
               color='#4a9eff', zorder=3, label='Observed')
    m_line = np.linspace(result['m_fit'].min(), result['m_fit'].max(), 100)
    y_line = result['a'] - result['b'] * m_line
    ax.plot(m_line, y_line, '#e85d3c', lw=2,
            label=f"GR fit: log N = {result['a']:.2f} − {result['b']:.2f}M")
    ax.set_xlabel('Magnitude M'); ax.set_ylabel('log₁₀ N(M ≥ m)')
    ax.set_title('Gutenberg–Richter Frequency–Magnitude Distribution')
    ax.legend(); ax.grid(True, alpha=0.2)
    plt.tight_layout()
    if output_path is not None:
        plt.savefig(output_path, dpi=150)
    else:
        # default to repo outputs, or PIPELINE_ROOT for a job-scoped bundle
        out_dir = Path(os.environ.get('PIPELINE_ROOT', Path(__file__).resolve().parents[2])) / 'outputs_psaha'
        out_dir.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(out_dir / 'gutenberg_richter.png'), dpi=150)
    plt.close()


if __name__ == '__main__':
    BASE_DIR = Path(os.environ.get('PIPELINE_ROOT', Path(__file__).resolve().parents[2]))
    DATA_DIR = BASE_DIR / 'data_processed' / 'seismic'
    OUTPUTS_DIR = BASE_DIR / 'outputs_psaha'
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    catalog_path = DATA_DIR / 'aftershock_catalog.csv'
    gr_params_path = OUTPUTS_DIR / 'gr_params.csv'
    gr_weights_path = OUTPUTS_DIR / 'gr_weights.npy'
    gr_plot_path = OUTPUTS_DIR / 'gutenberg_richter.png'

    df = pd.read_csv(catalog_path)
    gr = fit_gutenberg_richter(df['magnitude'].values)
    plot_gr_fit(gr, output_path=gr_plot_path)

    pd.DataFrame([{'a': gr['a'], 'b': gr['b'], 'r_squared': gr['r_squared']}]
    ).to_csv(gr_params_path, index=False)
    np.save(gr_weights_path,
            {'bins': gr['mag_bins'], 'weights': gr['mag_weights']})
