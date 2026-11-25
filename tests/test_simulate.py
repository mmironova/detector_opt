"""Delphes simulation on the shared generator-level events.

These tests need the Key4hep container and the generator cache:

    ./run.sh python -m detopt.generate --events-per-sample 100   # once
    ./run.sh python -m pytest tests/test_simulate.py
"""

import json
import math
import os
import shutil
import time

import pytest

from detopt import generate, samples
from detopt.design import BASELINE, Design, render_card
from detopt.evaluate import DEFAULT_TEMPLATE
from detopt.simulate import simulate

N_EVENTS = 100


def _cache_ready() -> bool:
    if not os.environ.get("DETOPT_GEN"):
        return False
    return all(
        generate.available_events(generate.load_manifest(s)) >= N_EVENTS for s in samples.SAMPLES
    )


pytestmark = [
    pytest.mark.skipif(
        shutil.which("DelphesSTDHEP_EDM4HEP") is None,
        reason="needs the Key4hep container: ./run.sh python -m pytest",
    ),
    pytest.mark.skipif(
        not _cache_ready(),
        reason="generator cache incomplete: ./run.sh python -m detopt.generate --events-per-sample 100",
    ),
]

WORST = Design(inner_radius_mm=17.5, material_x0_percent=0.66, hit_resolution_um=6.0)


def _card(tmp_path, design, name):
    return render_card(design, DEFAULT_TEMPLATE, tmp_path / name / "card.tcl")


def _events(path):
    from podio.root_io import Reader

    return list(Reader(str(path)).get("events"))


def _mc(event):
    return [
        (p.getPDG(), p.getGeneratorStatus(), p.getMomentum().x, p.getMomentum().y,
         p.getMomentum().z, p.getVertex().x, p.getVertex().y, p.getVertex().z)
        for p in event.get("Particle")
    ]


def _tracks(event):
    return [
        (s.D0, s.Z0, s.phi, s.omega, s.covMatrix[0])
        for t in event.get("EFlowTrack") for s in list(t.getTrackStates())[:1]
    ]


def test_100_events_of_every_sample_in_under_a_minute(tmp_path):
    card = _card(tmp_path, BASELINE, "baseline")
    start = time.monotonic()
    files = simulate(card, tmp_path / "baseline", N_EVENTS, seed=1)
    elapsed = time.monotonic() - start
    assert elapsed < 60, f"took {elapsed:.0f} s"

    manifest = json.loads((tmp_path / "baseline" / "sim" / "manifest.json").read_text())
    assert set(manifest["samples"]) == {s.name for s in samples.SAMPLES}
    for name, info in manifest["samples"].items():
        assert info["events"] == N_EVENTS, name
        assert 0 < info["effective_cross_section_pb"] <= info["cross_section_pb"], name

    assert len(files) == len(samples.SAMPLES)
    for path in files:
        events = _events(path)
        assert len(events) == N_EVENTS, path
        assert sum(len(e.get("EFlowTrack")) for e in events) > 0, path
        assert sum(len(e.get("RecoMCLink")) for e in events) > 0, path
        assert all(len(e.get("Particle")) > 0 for e in events), path


def test_designs_share_generator_events_but_not_tracking(tmp_path):
    names = ["wzp6_ee_nunuH_Hcc_ecm240", "p8_ee_ZZ_ecm240"]
    runs = {}
    for label, design in (("baseline", BASELINE), ("worst", WORST)):
        card = _card(tmp_path, design, label)
        runs[label] = simulate(card, tmp_path / label, 50, seed=1, sample_names=names)

    for base_file, worst_file in zip(runs["baseline"], runs["worst"]):
        base, worst = _events(base_file), _events(worst_file)
        assert [_mc(e) for e in base] == [_mc(e) for e in worst], base_file.parent.name

        def median_sigma_d0(events):
            values = sorted(math.sqrt(t[4]) for e in events for t in _tracks(e))
            return values[len(values) // 2]

        assert median_sigma_d0(worst) > 1.2 * median_sigma_d0(base), base_file.parent.name


def test_seed_fixes_the_smearing(tmp_path):
    names = ["wzp6_ee_nuenueZ_ecm240"]
    card = _card(tmp_path, BASELINE, "card")
    first = simulate(card, tmp_path / "a", 50, seed=1, sample_names=names)
    again = simulate(card, tmp_path / "b", 50, seed=1, sample_names=names)
    other = simulate(card, tmp_path / "c", 50, seed=2, sample_names=names)
    a, b, c = (_events(f[0]) for f in (first, again, other))
    assert [_tracks(e) for e in a] == [_tracks(e) for e in b]
    assert [_mc(e) for e in a] == [_mc(e) for e in c]
    assert [_tracks(e) for e in a] != [_tracks(e) for e in c]
