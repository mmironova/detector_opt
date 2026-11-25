import json
from pathlib import Path

import pytest

from detopt import analysis, fit, simulate, tagger
from detopt import design as design_module
from detopt.design import Design, card_values, render_card
from detopt.evaluate import DEFAULT_TEMPLATE, evaluate

CARDS = Path(__file__).resolve().parent.parent / "cards"
STOCK_CARD = CARDS / "delphes_card_IDEA.stock.tcl"
KEY4HEP_STOCK_CARD = Path(
    "/cvmfs/sw.hsf.org/key4hep/releases/2026-04-08/x86_64-almalinux9-gcc14.2.0-opt"
    "/delphes/master-e2vu45/cards/delphes_card_IDEA.tcl"
)

BASELINE = design_module.BASELINE.to_dict()
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
    assert card.read_text() == "r 0.0137\nx0 0.000309\nres 3e-06\n"


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


def test_baseline_renders_the_stock_idea_card_exactly(tmp_path):
    card = render_card(design_module.BASELINE, DEFAULT_TEMPLATE, tmp_path / "card.tcl")
    assert card.read_bytes() == STOCK_CARD.read_bytes()


def test_card_values_convert_to_si_units():
    values = card_values(
        Design(inner_radius_mm=15.0, material_x0_percent=0.5, hit_resolution_um=2.0)
    )
    assert values == {
        "inner_radius_mm": "0.015",  # m
        "material_x0_percent": "0.0004685",  # m of silicon: 0.5 % of 0.0937 m
        "hit_resolution_um": "2e-06",  # m
    }


def test_template_keeps_the_silicon_x0_used_for_the_conversion():
    line = next(l for l in DEFAULT_TEMPLATE.read_text().splitlines() if "@@" in l)
    columns = line.split()
    assert columns[5] == "@@material_x0_percent@@"
    assert float(columns[6]) == design_module.SILICON_X0_M


@pytest.mark.skipif(not KEY4HEP_STOCK_CARD.exists(), reason="Key4hep CVMFS not mounted")
def test_stock_reference_is_the_card_of_the_pinned_key4hep_release():
    assert STOCK_CARD.read_bytes() == KEY4HEP_STOCK_CARD.read_bytes()


def test_extended_range_is_built_but_marked_beyond_baseline():
    assert not design_module.BASELINE.beyond_baseline
    cld_radius = Design(**{**BASELINE, "inner_radius_mm": 12.5})
    assert cld_radius.beyond_baseline
    with pytest.raises(ValueError):
        cld_radius.check_allowed()
    cld_radius.check_allowed(beyond_baseline=True)


def test_below_the_extended_range_is_rejected_even_beyond_baseline():
    with pytest.raises(ValueError):
        Design(**{**BASELINE, "inner_radius_mm": 12.4})


def test_beyond_baseline_does_not_change_the_design_hash():
    a = Design(**{**BASELINE, "inner_radius_mm": 12.5})
    b = Design(**{**BASELINE, "inner_radius_mm": 12.5})
    assert a.hash == b.hash
    assert "beyond_baseline" not in a.to_dict()


def test_evaluate_runs_beyond_baseline_designs_only_when_allowed(tmp_path, monkeypatch):
    template = tmp_path / "t.tcl"
    template.write_text(TEMPLATE)
    monkeypatch.setattr(simulate, "simulate", lambda *a: [])
    monkeypatch.setattr(tagger, "train_and_apply", lambda *a: [])
    monkeypatch.setattr(analysis, "make_histograms", lambda *a: None)
    monkeypatch.setattr(fit, "expected_uncertainty", lambda *a: {"sigma_mu_hcc": 0.02})

    design = Design(**{**BASELINE, "inner_radius_mm": 12.5})
    with pytest.raises(ValueError, match="beyond baseline"):
        evaluate(design, n_events=10, seed=1, template=template, root=tmp_path)
    assert not (tmp_path / design.hash).exists()

    result = evaluate(
        design, n_events=10, seed=1, template=template, root=tmp_path, beyond_baseline=True
    )
    assert result["beyond_baseline"] is True
    stored = json.loads((tmp_path / design.hash / "result.json").read_text())
    assert stored["beyond_baseline"] is True

    baseline = evaluate(
        design_module.BASELINE, n_events=10, seed=1, template=template, root=tmp_path
    )
    assert baseline["beyond_baseline"] is False
