import json
import math

import numpy as np

from detopt import fit


def test_single_parameter_matches_the_counting_formula():
    # One free signal strength, fixed background: sigma = 1 / sqrt(sum s^2 / (s + b)).
    s = np.array([10.0, 40.0, 5.0])
    b = np.array([100.0, 20.0, 1.0])
    sig = fit.asimov_sigmas(np.stack([s, b]), free=[0], fixed=[1])
    assert math.isclose(sig[0], 1 / math.sqrt(np.sum(s**2 / (s + b))), rel_tol=1e-12)


def test_free_background_normalisation_costs_precision():
    s = np.array([10.0, 40.0, 5.0, 0.0])
    b = np.array([100.0, 20.0, 1.0, 50.0])
    fixed_b = fit.asimov_sigmas(np.stack([s, b]), free=[0], fixed=[1])[0]
    free_b = fit.asimov_sigmas(np.stack([s, b]), free=[0, 1], fixed=[])[0]
    assert free_b > fixed_b


def test_empty_template_is_reported_as_unconstrained():
    s = np.array([10.0, 40.0])
    empty = np.zeros(2)
    sig = fit.asimov_sigmas(np.stack([s, empty]), free=[0, 1], fixed=[])
    assert math.isfinite(sig[0]) and sig[1] == float("inf")


def _toy_file(tmp_path, n_mc, seed=1):
    """Two processes in 20 bins, normalised to fixed expected yields."""
    rng = np.random.default_rng(seed)
    meta = {
        "processes": ["H_cc", "ZZ", "H_other"], "pois": ["H_cc"], "backgrounds": ["ZZ"],
        "fixed": ["H_other"], "channels": ["ll"], "n_bins": 20, "channel_bins": {"ll": [0, 20]},
        "lumi_fb": 1.0,
    }
    sig_bins = np.clip(rng.normal(10, 2, n_mc).astype(int), 0, 19)
    bkg_bins = rng.integers(0, 20, n_mc)
    bins = np.concatenate([sig_bins, bkg_bins])
    weights = np.concatenate([np.full(n_mc, 500.0 / n_mc), np.full(n_mc, 5000.0 / n_mc)])
    process = np.concatenate([np.zeros(n_mc), np.ones(n_mc)]).astype(np.int16)
    path = tmp_path / f"toy_{n_mc}.npz"
    np.savez(path, meta=json.dumps(meta), bin=bins, weight=weights, process=process,
             channel=np.zeros(2 * n_mc, dtype=np.int8), sample=np.zeros(2 * n_mc, dtype=np.int16))
    return path


def test_expected_uncertainty_reports_sigma_and_mc_error(tmp_path):
    r = fit.expected_uncertainty(_toy_file(tmp_path, 2000), n_bootstrap=50)
    assert 0 < r["sigma_mu_hcc"] < 1
    assert 0 < r["sigma_mu_hcc_mcstat"] < r["sigma_mu_hcc"]
    assert r["per_channel"]["ll"]["sigma_mu_hcc"] == r["sigma_mu_hcc"]
    assert (tmp_path / "fit.json").exists()


def test_mc_error_shrinks_like_one_over_sqrt_n(tmp_path):
    small = fit.expected_uncertainty(_toy_file(tmp_path, 2000), n_bootstrap=200)
    large = fit.expected_uncertainty(_toy_file(tmp_path, 32000), n_bootstrap=200)
    ratio = small["sigma_mu_hcc_mcstat"] / large["sigma_mu_hcc_mcstat"]
    assert 2.5 < ratio < 6.5  # expected 4 for 16 times more MC events
    # Same physics, so the sigma itself agrees within the MC errors.
    assert abs(small["sigma_mu_hcc"] - large["sigma_mu_hcc"]) < 5 * small["sigma_mu_hcc_mcstat"]
