"""Expected uncertainty on the H -> cc signal strength, and its MC statistical error.

Binned Poisson likelihood over all categories and bins of both channels
(analysis.py), evaluated on the Asimov dataset (all parameters at 1):

    nu_k(theta) = sum_p theta_p T_pk + sum_f T_fk

with one free parameter theta_p per Higgs decay (bb, cc, gg, WW, ZZ, tautau)
and per background process, and fixed processes f (other Higgs decays). As in
the note, no systematic uncertainties and no constraints on the free
parameters. For a Poisson likelihood that is linear in the parameters, the
Hessian of -log L at the Asimov point is the Fisher matrix

    F_ij = sum_k T_ik T_jk / nu_k,

so sigma(mu_cc) = sqrt((F^-1)_cc); this is what a fit tool such as Combine
returns for the Asimov dataset.

MC statistical error: the templates come from finite MC samples. Each bootstrap
replica gives every MC event a Poisson(1) weight, rebuilds the templates and
recomputes sigma(mu_cc); the spread of the replicas is the MC statistical error
of sigma(mu_cc). It is not folded into sigma(mu_cc) itself (the note's quoted
numbers include MC-statistics nuisance parameters; its Table 14 also gives
the value without them, 1.74% for Z(nunu)H analysis II).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

N_BOOTSTRAP = 100
BOOTSTRAP_SEED = 20261125


def build_templates(bins: np.ndarray, weights: np.ndarray, process: np.ndarray,
                    n_processes: int, n_bins: int) -> np.ndarray:
    """Expected yield per (process, bin)."""
    flat = process.astype(np.int64) * n_bins + bins.astype(np.int64)
    return np.bincount(flat, weights=weights, minlength=n_processes * n_bins).reshape(n_processes, n_bins)


def asimov_sigmas(templates: np.ndarray, free: list[int], fixed: list[int]) -> dict[int, float]:
    """sigma of each free parameter (index into templates) from the Fisher matrix.

    Parameters whose template is empty in the bins used are dropped (sigma inf).
    """
    nu = templates[free].sum(axis=0) + (templates[fixed].sum(axis=0) if fixed else 0.0)
    use = nu > 0
    active = [p for p in free if templates[p][use].sum() > 0]
    out = {p: float("inf") for p in free}
    if not active:
        return out
    t = templates[active][:, use]
    fisher = (t / nu[use]) @ t.T
    try:
        cov = np.linalg.inv(fisher)
    except np.linalg.LinAlgError:
        cov = np.linalg.pinv(fisher)
    for i, p in enumerate(active):
        out[p] = float(np.sqrt(cov[i, i])) if cov[i, i] > 0 else float("inf")
    return out


def info_without_background_mc(templates: np.ndarray, meta: dict, bin_mask: np.ndarray | None) -> float:
    """Share of the mu_cc Fisher information (F_cc,cc) from bins with no background MC.

    Such bins look background-free only because the background samples are
    finite; a large share means sigma(mu_cc) is optimistic in a way the
    bootstrap cannot show (events that are not there cannot fluctuate).
    """
    procs = meta["processes"]
    t = templates if bin_mask is None else templates[:, bin_mask]
    nu = t.sum(axis=0)
    use = nu > 0
    cc = t[procs.index("H_cc")]
    bkg = t[[procs.index(p) for p in meta["backgrounds"]]].sum(axis=0)
    info = np.where(use, cc**2 / np.where(use, nu, 1.0), 0.0)
    total = info.sum()
    return float(info[bkg <= 0].sum() / total) if total > 0 else float("nan")


def _fit_all(templates: np.ndarray, meta: dict, bin_mask: np.ndarray | None) -> dict[str, float]:
    procs = meta["processes"]
    t = templates if bin_mask is None else templates[:, bin_mask]
    free = [procs.index(p) for p in meta["pois"] + meta["backgrounds"]]
    fixed = [procs.index(p) for p in meta["fixed"]]
    sig = asimov_sigmas(t, free, fixed)
    return {procs[p]: s for p, s in sig.items()}


def expected_uncertainty(histograms: Path, n_bootstrap: int = N_BOOTSTRAP,
                         seed: int = BOOTSTRAP_SEED) -> dict:
    """sigma(mu_cc), its MC statistical error, and the other signal strengths."""
    data = np.load(histograms, allow_pickle=False)
    meta = json.loads(str(data["meta"]))
    bins, weights, process = data["bin"], data["weight"], data["process"]
    n_proc, n_bins = len(meta["processes"]), meta["n_bins"]

    masks = {"combined": None}
    for ch, (lo, hi) in meta["channel_bins"].items():
        m = np.zeros(n_bins, dtype=bool)
        m[lo:hi] = True
        masks[ch] = m

    nominal_t = build_templates(bins, weights, process, n_proc, n_bins)
    nominal = {name: _fit_all(nominal_t, meta, m) for name, m in masks.items()}

    rng = np.random.default_rng(seed)
    replicas = {name: [] for name in masks}
    for _ in range(n_bootstrap):
        w = weights * rng.poisson(1.0, size=len(weights))
        t = build_templates(bins, w, process, n_proc, n_bins)
        for name, m in masks.items():
            replicas[name].append(_fit_all(t, meta, m)["H_cc"])

    def mcstat(values):
        v = np.asarray(values, dtype=float)
        v = v[np.isfinite(v)]
        return float(np.std(v, ddof=1)) if len(v) > 1 else float("nan")

    result = {
        "sigma_mu_hcc": nominal["combined"]["H_cc"],
        "sigma_mu_hcc_mcstat": mcstat(replicas["combined"]),
        "sigma_mu": {p: nominal["combined"][p] for p in meta["pois"]},
        "info_share_without_background_mc": info_without_background_mc(nominal_t, meta, None),
        "per_channel": {
            ch: {
                "sigma_mu_hcc": nominal[ch]["H_cc"],
                "sigma_mu_hcc_mcstat": mcstat(replicas[ch]),
                "info_share_without_background_mc": info_without_background_mc(nominal_t, meta, masks[ch]),
                "sigma_mu": {p: nominal[ch][p] for p in meta["pois"]},
            }
            for ch in meta["channels"]
        },
        "bootstrap": {
            "replicas": n_bootstrap,
            "seed": seed,
            "mean_sigma_mu_hcc": float(np.nanmean(replicas["combined"])) if n_bootstrap else None,
        },
        "mc_events_in_fit": int(len(weights)),
        "lumi_fb": meta["lumi_fb"],
        "tagger": meta.get("tagger"),
    }
    out = Path(histograms).with_name("fit.json")
    out.write_text(json.dumps(result, indent=2))
    return result
