"""Selection, categories and fit inputs. The last test needs the container:

    ./run.sh python -m pytest tests/test_analysis.py
"""

import json
import math
import os
import shutil
import time

import numpy as np
import pytest

from detopt import analysis, fit, generate, samples


def _scores(**k):
    base = {c: np.zeros(len(next(iter(k.values())))) for c in analysis.SCORE_CLASSES}
    base.update({c: np.asarray(v, dtype=float) for c, v in k.items()})
    return base


def test_categories_follow_the_largest_summed_score_and_table_13():
    # C-like: purity edges 1.0 and 1.8 (note Table 13).
    cat = analysis.categorise(_scores(C=[0.9, 1.4, 1.9], B=[0.5, 0.3, 0.05]))
    c = analysis.FLAVOURS.index("C") * 3
    assert list(cat) == [c + 0, c + 1, c + 2]


def test_events_led_by_light_or_tau_scores_are_not_categorised():
    cat = analysis.categorise(_scores(U=[1.2], TAU=[0.3], C=[0.5]))
    assert list(cat) == [-1]


def test_fit_bins_are_unique_and_respect_the_ranges():
    ll = analysis.fit_bin("ll", np.array([0, 0, 11, 5]),
                          {"m_recoil": np.array([120.1, 139.9, 125.0, 141.0])})
    assert ll[3] == -1 and len(set(ll[:3])) == 3
    nn = analysis.fit_bin("nunu", np.array([0, 11]),
                          {"m_rec": np.array([91.0, 91.0]), "m_jj": np.array([125.0, 125.0])})
    lo, hi = analysis.channel_offset("nunu"), analysis.total_bins()
    assert all(lo <= b < hi for b in nn)


def test_every_sample_has_a_fit_process():
    for s in samples.SAMPLES:
        assert analysis.process_name(s.name, 24) in analysis.PROCESSES
    # Inclusive ZH: H -> bb, cc, gg events are dropped (dedicated samples cover them).
    assert analysis.process_name("wzp6_ee_nunuH_ecm240", 4) is None
    assert analysis.process_name("wzp6_ee_nunuH_ecm240", 3) == "H_other"


def _ready(names):
    if shutil.which("DelphesSTDHEP_EDM4HEP") is None or not os.environ.get("DETOPT_GEN"):
        return False
    return all(generate.available_events(generate.load_manifest(samples.BY_NAME[n])) >= 100 for n in names)


SUBSET = ["wzp6_ee_mumuH_Hcc_ecm240", "wzp6_ee_nunuH_Hcc_ecm240", "p8_ee_ZZ_ecm240"]


@pytest.mark.skipif(not _ready(SUBSET), reason="needs the container and the generator cache")
def test_analysis_and_fit_on_100_events_in_under_a_minute(tmp_path):
    from detopt.design import BASELINE, render_card
    from detopt.evaluate import DEFAULT_TEMPLATE
    from detopt.simulate import simulate

    run = tmp_path / "run"
    card = render_card(BASELINE, DEFAULT_TEMPLATE, run / "card.tcl")
    files = simulate(card, run, 100, seed=1, sample_names=SUBSET)

    start = time.monotonic()
    templates = analysis.make_histograms(files, run)
    result = fit.expected_uncertainty(templates, n_bootstrap=20)
    elapsed = time.monotonic() - start
    assert elapsed < 60, f"took {elapsed:.0f} s"

    summary = json.loads((run / "hists" / "summary.json").read_text())
    ll = summary["cutflow_weighted"]["ll"]["wzp6_ee_mumuH_Hcc_ecm240"]
    # 0.1956 fb x 10.8 ab^-1 before cuts; most events pass the ll selection.
    assert math.isclose(ll["all"], 0.1956 * 10800, rel_tol=1e-6)
    assert 0.6 < ll["d23 > 0, d34 > 0"] / ll["all"] <= 1.0
    assert summary["cutflow_weighted"]["nunu"]["wzp6_ee_mumuH_Hcc_ecm240"]["no lepton with 20 < p < 100 GeV"] == 0
    assert math.isfinite(result["sigma_mu_hcc"]) and result["sigma_mu_hcc"] > 0
    assert result["tagger"]["validated"] is False
