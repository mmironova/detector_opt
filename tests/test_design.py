import json

import pytest

from detopt import analysis, fit, simulate, tagger
from detopt.design import Design, render_card
from detopt.evaluate import evaluate

BASELINE = dict(inner_radius_mm=13.7, material_x0_percent=0.3, hit_resolution_um=3.0)
TEMPLATE = "r @@inner_radius_mm@@\nx0 @@material_x0_percent@@\nres @@hit_resolution_um@@\n"


def test_hash_is_stable_and_distinguishes_designs():
    a = Design(**BASELINE)
    b = Design(**BASELINE)
    c = Design(**{**BASELINE, "inner_radius_mm": 15.0})
    assert a.hash == b.hash
    assert a.hash != c.hash


def test_out_of_bounds_is_rejected():
    with pytest.raises(ValueError):
        Design(**{**BASELINE, "inner_radius_mm": 1.0})


def test_render_card_fills_every_placeholder(tmp_path):
    template = tmp_path / "t.tcl"
    template.write_text(TEMPLATE)
    card = render_card(Design(**BASELINE), template, tmp_path / "out" / "card.tcl")
    assert card.read_text() == "r 13.7\nx0 0.3\nres 3.0\n"


def test_render_card_rejects_missing_or_unknown_placeholders(tmp_path):
    missing = tmp_path / "missing.tcl"
    missing.write_text("r @@inner_radius_mm@@\n")
    with pytest.raises(ValueError):
        render_card(Design(**BASELINE), missing, tmp_path / "a.tcl")

    unknown = tmp_path / "unknown.tcl"
    unknown.write_text(TEMPLATE + "b @@field_tesla@@\n")
    with pytest.raises(ValueError):
        render_card(Design(**BASELINE), unknown, tmp_path / "b.tcl")


def test_evaluate_runs_the_chain_once_and_then_uses_the_cache(tmp_path, monkeypatch):
    template = tmp_path / "t.tcl"
    template.write_text(TEMPLATE)
    calls = []

    monkeypatch.setattr(simulate, "simulate", lambda *a: calls.append("sim") or [])
    monkeypatch.setattr(tagger, "train_and_apply", lambda *a: calls.append("tag") or [])
    monkeypatch.setattr(analysis, "make_histograms", lambda *a: calls.append("ana"))
    monkeypatch.setattr(
        fit, "expected_uncertainty", lambda *a: calls.append("fit") or {"sigma_mu_hcc": 0.02}
    )

    design = Design(**BASELINE)
    first = evaluate(design, n_events=10, seed=1, template=template, root=tmp_path)
    second = evaluate(design, n_events=10, seed=1, template=template, root=tmp_path)

    assert calls == ["sim", "tag", "ana", "fit"]
    assert first == second
    assert first["sigma_mu_hcc"] == 0.02
    stored = json.loads((tmp_path / design.hash / "result.json").read_text())
    assert stored["design"] == BASELINE
