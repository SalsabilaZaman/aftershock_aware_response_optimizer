
import os
import numpy as np
import pandas as pd
from datetime import datetime
import matplotlib.pyplot as plt
from pathlib import Path

# ─────────────────────────────────────────────
# 1. LOAD DATA AND CONVERT TIMES
# ─────────────────────────────────────────────

def load_and_convert_times(catalog_path: str, mainshock_utc: str) -> pd.DataFrame:
    """
    Load aftershock catalog CSV (USGS format) and compute
    elapsed time in days since the mainshock.
    """
    df = pd.read_csv(catalog_path)

    # Parse UTC times — handle mixed datetime formats (some with/without microseconds)
    df['time_utc'] = pd.to_datetime(df['time_utc'], format='mixed', utc=True)
    t0 = pd.to_datetime(mainshock_utc, utc=True)

    df['t_days'] = (df['time_utc'] - t0).dt.total_seconds() / 86400.0
    df = df[df['t_days'] > 0].reset_index(drop=True)
    return df


# ─────────────────────────────────────────────
# 2. MODIFIED OMORI LAW — MLE FIT (Ogata 1983)
# ─────────────────────────────────────────────

def _omori_integral(K: float, c: float, p: float, t1: float, t2: float) -> float:
    """∫ K/(t+c)^p dt over [t1, t2] — expected event count."""
    if abs(p - 1.0) < 1e-9:
        return K * (np.log(t2 + c) - np.log(t1 + c))
    return K * ((t2 + c) ** (1 - p) - (t1 + c) ** (1 - p)) / (1 - p)


def expected_aftershock_count(K: float, c: float, p: float,
                              t1: float, t2: float) -> float:
    """Expected number of aftershocks in [t1, t2] days after the mainshock."""
    return _omori_integral(K, c, p, t1, t2)


def fit_omori_mle(t_days: np.ndarray, T_obs: float,
                  c_grid=None, p_grid=None) -> dict:
    """Maximum-likelihood fit of the modified Omori law n(t) = K/(t+c)^p.

    Ogata (1983) point-process log-likelihood:
        lnL = N·lnK − p·Σ ln(t_i + c) − ∫₀ᵀ K/(t+c)^p dt
    K has the closed-form MLE K̂ = N / ∫₀ᵀ (t+c)^{-p} dt, so we grid-search
    only (c, p) — robust and reproducible for a 30-day catalog.
    """
    if c_grid is None:
        c_grid = np.arange(0.01, 1.01, 0.01)
    if p_grid is None:
        p_grid = np.arange(0.8, 1.61, 0.01)

    N = len(t_days)
    best = {'log_likelihood': -np.inf}
    lnL_surface = np.full((len(c_grid), len(p_grid)), -np.inf)
    for i, c in enumerate(c_grid):
        log_tc = np.log(t_days + c)
        for j, p in enumerate(p_grid):
            A = _omori_integral(1.0, c, p, 0.0, T_obs)  # ∫ (t+c)^-p dt
            K = N / A
            lnL = N * np.log(K) - p * log_tc.sum() - K * A
            lnL_surface[i, j] = lnL
            if lnL > best['log_likelihood']:
                best = {'K': K, 'c': c, 'p': p, 'log_likelihood': lnL}

    best['lnL_surface'] = lnL_surface
    print(f"  Omori MLE: K={best['K']:.3f}, c={best['c']:.3f}, "
          f"p={best['p']:.2f}, lnL={best['log_likelihood']:.1f}")
    return best

def plot_omori_decay(K: float, c: float, p: float,
                     T_obs: float, t_days_observed: np.ndarray):
    """Plot fitted Omori decay rate against observed aftershock histogram."""
    t_plot = np.linspace(0.001, T_obs, 500)
    rate   = K / (t_plot + c)**p

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.semilogy(t_plot, rate, '#e85d3c', lw=2, label='Fitted Omori rate')
    ax.hist(t_days_observed, bins=30, density=True,
            alpha=0.3, color='#4a9eff', label='Observed (density)')
    ax.set_xlabel('Time since mainshock (days)')
    ax.set_ylabel('Aftershock rate (events/day)')
    ax.set_title(f'Modified Omori Fit: K={K:.3f}, c={c:.4f}, p={p:.2f}')
    ax.legend(); ax.grid(True, alpha=0.2)
    plt.tight_layout()

    # Save to repository outputs directory (robust when moved), or PIPELINE_ROOT
    # when running against a job-scoped data bundle (see pipelines/run_demo_job.py)
    out_dir = Path(os.environ.get('PIPELINE_ROOT', Path(__file__).resolve().parents[2])) / 'outputs_psaha'
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(out_dir / 'omori_decay.png'), dpi=150)
    plt.close()


# MAIN EXECUTION
if __name__ == '__main__':
    BASE_DIR = Path(os.environ.get('PIPELINE_ROOT', Path(__file__).resolve().parents[2]))
    DATA_DIR = BASE_DIR / 'data_processed' / 'seismic'
    OUTPUTS_DIR = BASE_DIR / 'outputs_psaha'
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    catalog_path = DATA_DIR / 'aftershock_catalog.csv'
    output_params_path = OUTPUTS_DIR / 'omori_params.csv'
    output_decay_plot = OUTPUTS_DIR / 'omori_decay.png'

    # Load data
    df = load_and_convert_times(
        catalog_path=str(catalog_path),
        mainshock_utc='2023-02-06T01:17:35'
    )

    t_days = df['t_days'].values
    T_obs  = t_days.max()

    result = fit_omori_mle(t_days, T_obs)

    N_30 = expected_aftershock_count(
        result['K'], result['c'], result['p'], 0, 30
    )
    print(f"  Expected aftershocks in 30 days: {N_30:.2f}")

    pd.DataFrame([result]).drop(columns=['lnL_surface']).to_csv(
        output_params_path, index=False
    )

    def plot_omori_decay(K: float, c: float, p: float,
                         T_obs: float, t_days_observed: np.ndarray, output_path=None):
        t_plot = np.linspace(0.001, T_obs, 500)
        rate   = K / (t_plot + c)**p

        fig, ax = plt.subplots(figsize=(9, 4))
        ax.semilogy(t_plot, rate, '#e85d3c', lw=2, label='Fitted Omori rate')
        ax.hist(t_days_observed, bins=30, density=True,
                alpha=0.3, color='#4a9eff', label='Observed (density)')
        ax.set_xlabel('Time since mainshock (days)')
        ax.set_ylabel('Aftershock rate (events/day)')
        ax.set_title(f'Modified Omori Fit: K={K:.3f}, c={c:.4f}, p={p:.2f}')
        ax.legend(); ax.grid(True, alpha=0.2)
        plt.tight_layout()
        if output_path is not None:
            plt.savefig(output_path, dpi=150)
        else:
            plt.show()
        plt.close()

    plot_omori_decay(result['K'], result['c'], result['p'], T_obs, t_days, output_path=output_decay_plot)
