"""Flavour tagger.

The goal (CLAUDE.md) is a tagger retrained for every design point
(``train_and_apply``, not written yet). Until then the stock FCC ParticleNet
model for IDEA at 240 GeV is used as a stand-in (DETOPT_TAGGER=stock, the
default): it is applied while the analysis ntuples are made
(``add_stock_scores``), so ``train_and_apply`` only passes the files through.

Stock model: IDEA_240_dolores_12_04_2023, 7 outputs (g, u, s, c, b, tau, d),
from root://eospublic.cern.ch//eos/experiment/fcc/ee/jet_flavour_tagging/winter2023/models/.
It was trained in 2023 with older software. Known issues on our files (Key4hep
2026-04-08, EDM4hep 1.0, FCCAnalyses 0.12), not yet solved:

- FCCAnalyses takes the primary vertex from the MC particle with generator
  status 21, which Whizard samples do not contain; it then uses a random decay
  vertex. Fixed here: ``detopt_primary_vertex`` (most common production vertex
  of status-1 particles) replaces it.
- The time-of-flight mass input is always the electron mass.
- Gluon jets get low g and sizeable b/c scores (mean g score about 0.2 for
  H -> gg jets), so some other input still differs from the training.

Results made with this tagger are labelled unvalidated (see ``description``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

STOCK_MODEL_NAME = "IDEA_240_dolores_12_04_2023"
STOCK_MODEL_EOS = (
    "root://eospublic.cern.ch//eos/experiment/fcc/ee/jet_flavour_tagging/winter2023/models/"
    f"{STOCK_MODEL_NAME}/fccee_flavtagging_edm4hep_wc"
)
# Output order of the stock model.
STOCK_CLASSES = ("G", "U", "S", "C", "B", "TAU", "D")

COLLECTIONS = {
    "GenParticles": "Particle",
    "PFParticles": "ReconstructedParticles",
    "PFTracks": "EFlowTrack",
    "PFPhotons": "EFlowPhoton",
    "PFNeutralHadrons": "EFlowNeutralHadron",
    "TrackState": "_EFlowTrack_trackStates",
    "TrackerHits": "TrackerHits",
    "CalorimeterHits": "CalorimeterHits",
    "dNdx": "EFlowTrack_dNdx",
    "PathLength": "EFlowTrack_L",
    "Bz": "magFieldBz",
}

PRIMARY_VERTEX_CPP = r"""
TLorentzVector detopt_primary_vertex(const ROOT::VecOps::RVec<edm4hep::MCParticleData>& mc) {
  // Most common production vertex of generator-status-1 particles: all prompt
  // particles share it exactly. Works for Whizard (no status-21 entries) and Pythia8.
  std::map<std::tuple<float, float, float>, std::pair<int, float>> count;
  for (const auto& p : mc) {
    if (p.generatorStatus != 1) continue;
    auto& c = count[{p.vertex.x, p.vertex.y, p.vertex.z}];
    c.first += 1;
    c.second = p.time;
  }
  TLorentzVector best(0, 0, 0, 0);
  int n = -1;
  for (const auto& [v, c] : count)
    if (c.first > n) { n = c.first; best.SetXYZT(std::get<0>(v), std::get<1>(v), std::get<2>(v), c.second); }
  return best;
}
"""


def mode() -> str:
    return os.environ.get("DETOPT_TAGGER", "stock")


def description() -> dict:
    if mode() == "stock":
        return {
            "name": f"stock FCC ParticleNet {STOCK_MODEL_NAME}",
            "retrained_per_design": False,
            "validated": False,
            "note": "primary vertex replaced; time-of-flight input missing; gluon tagging degraded",
        }
    return {"name": mode(), "retrained_per_design": True, "validated": False}


def stock_model_dir() -> Path:
    gen = os.environ.get("DETOPT_GEN")
    if not gen:
        raise RuntimeError("DETOPT_GEN is not set; source setup.sh")
    return Path(gen) / "_models" / STOCK_MODEL_NAME


def ensure_stock_model() -> tuple[Path, Path]:
    """Download the stock model once (into $DETOPT_GEN/_models); return (json, onnx)."""
    d = stock_model_dir()
    d.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("json", "onnx"):
        local = d / f"fccee_flavtagging_edm4hep_wc.{ext}"
        if not local.exists():
            subprocess.run(["xrdcp", "--nopbar", f"{STOCK_MODEL_EOS}.{ext}", str(local)], check=True)
        paths.append(local)
    return paths[0], paths[1]


def fccanalyses_python() -> Path:
    exe = shutil.which("fccanalysis")
    if exe is None:
        raise RuntimeError("fccanalysis not found: run inside the container")
    return Path(exe).resolve().parent.parent / "python"


def add_stock_scores(df, jets: str, constituents: str):
    """Define the stock model's per-jet scores on an RDataFrame with clustered jets.

    Returns (df, {class: column}) with columns ``recojet_is<class>`` (one value per jet).
    Must run in a process where libFCCAnalyses is loaded (see analysis._init_root).
    """
    import ROOT  # noqa: PLC0415

    sys.path.insert(0, str(fccanalyses_python()))
    from addons.ONNXRuntime.jetFlavourHelper import JetFlavourHelper  # noqa: PLC0415

    if not hasattr(ROOT, "detopt_primary_vertex"):
        ROOT.gInterpreter.Declare(PRIMARY_VERTEX_CPP)
    preproc, model = ensure_stock_model()
    helper = JetFlavourHelper(COLLECTIONS, jets, constituents, "")
    helper.definition["pv"] = f"detopt_primary_vertex({COLLECTIONS['GenParticles']})"
    df = helper.define(df)
    df = helper.inference(str(preproc), str(model), df)
    return df, {c: f"recojet_is{c}" for c in STOCK_CLASSES}


def train_and_apply(sim_files: list[Path], run_dir: Path, seed: int) -> list[Path]:
    """Train a jet-flavour tagger on this design's simulation and apply it.

    With DETOPT_TAGGER=stock (default) nothing is trained: the stock model is
    applied by analysis.py while it makes the ntuples, and the simulation files
    are passed through unchanged.

    To build (retrained tagger):
    - inputs: per-track impact parameters and their significances, plus jet
      kinematics; these are what the vertex detector parameters change
    - a small network that trains in minutes on one GPU; same architecture,
      same seed and same training events for every design
    - split events: train on one part, write scores for the other part only
    - return files with b, c and light scores per jet under run_dir / "tagged"
    """
    if mode() == "stock":
        return list(sim_files)
    raise NotImplementedError("tagger: training step not written yet")
