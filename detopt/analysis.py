"""Event selection, categories and fit inputs for ZH -> Z(ll / nunu) H(jj) at 240 GeV.

Follows A. Del Vecchio et al., "Measurement of Higgs boson hadronic decays at
FCC-ee", FCC note, 31 March 2025, doi:10.17181/9pr7y-3v657 (FCC Feasibility
Study Ref. [64]); local copy refs/fccnote_hadronic_higgs_3jjdh-6fz97.pdf.

- Z(ll)H: selection of Section 5.1.
- Z(nunu)H: analysis II (Section 7), which categorises events with the tagger
  scores directly. Its numeric "kinematics & d_ij" cuts are not given in the
  note, so the jet cuts of analysis I (Section 6.1) are used, plus analysis II's
  |cos theta_jj| < 0.85 and fit window.
- Both channels: categories from the summed jet scores K = K1 + K2 (Section
  7.1.2): B/C/S/G-like by the largest component, three purities each (Table 13).

Deviations from the note are listed in README.md ("Analysis and fit").

Stage 1 (``make_ntuple``, one worker process per file and channel): selection,
exclusive Durham clustering into two jets, stock-tagger scores, observables.
Stage 2 (``make_histograms``): categories and fit bins for every selected MC
event, with its process and weight, written to run_dir/hists/templates.npz.
fit.py builds the templates (and their bootstrap replicas) from that file.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

SQRT_S = 240.0
LUMI_FB = 10800.0  # 10.8 ab^-1, as in the note
CHANNELS = ("ll", "nunu")

# Fit observables and binning (note Sections 5.3 and 7.1.3).
BINNING = {
    "ll": {"m_recoil": (120.0, 140.0, 80)},
    "nunu": {"m_rec": (40.0, 145.0, 21), "m_jj": (60.0, 150.0, 90)},
}

# Event categories: largest summed score, then purity (note Table 13).
FLAVOURS = ("B", "C", "S", "G")
PURITY_EDGES = {"B": (1.1, 1.9), "C": (1.0, 1.8), "S": (1.1, 1.7), "G": (1.2, 1.5)}
PURITIES = ("low", "mid", "high")
SCORE_CLASSES = ("G", "U", "S", "C", "B", "TAU", "D")  # stock model outputs

# Fit processes.
POIS = ("H_bb", "H_cc", "H_gg", "H_WW", "H_ZZ", "H_tautau")
BACKGROUNDS = ("ZZ", "WW", "Zqq", "nunuZ", "Zll", "qqH")
FIXED = ("H_other",)  # H -> ss, gamma gamma, Z gamma, mumu, ...: fixed to the SM
PROCESSES = POIS + BACKGROUNDS + FIXED

# Truth Higgs decay codes (from detopt_higgs_decay) -> process of inclusive ZH samples.
_INCLUSIVE_DECAY = {24: "H_WW", 23: "H_ZZ", 15: "H_tautau"}
_DEDICATED_DECAYS = (5, 4, 21)  # covered by the dedicated H -> bb, cc, gg samples


def process_name(sample: str, higgs_decay: int) -> str | None:
    """Fit process of an event; None if it must be dropped (double counting)."""
    if sample in ("wzp6_ee_eeH_ecm240", "wzp6_ee_mumuH_ecm240", "wzp6_ee_nunuH_ecm240"):
        if higgs_decay in _DEDICATED_DECAYS:
            return None
        return _INCLUSIVE_DECAY.get(higgs_decay, "H_other")
    for zh in ("eeH", "mumuH", "nunuH"):
        for h in ("bb", "cc", "gg"):
            if sample == f"wzp6_ee_{zh}_H{h}_ecm240":
                return f"H_{h}"
    fixed = {
        "p8_ee_ZZ_ecm240": "ZZ",
        "p8_ee_WW_ecm240": "WW",
        "p8_ee_Zqq_ecm240": "Zqq",
        "wzp6_ee_nuenueZ_ecm240": "nunuZ",
        "wzp6_ee_ee_Mee_30_150_ecm240": "Zll",
        "wzp6_ee_mumu_ecm240": "Zll",
        "wzp6_ee_qqH_Hbb_ecm240": "qqH",
        "wzp6_ee_qqH_Hcc_ecm240": "qqH",
        "wzp6_ee_qqH_Hgg_ecm240": "qqH",
    }
    if sample not in fixed:
        raise KeyError(f"no fit process for sample {sample}")
    return fixed[sample]


# --------------------------------------------------------------------------- stage 1

_HELPERS_CPP = r"""
#include <algorithm>
#include <cmath>
using RPD = edm4hep::ReconstructedParticleData;

struct DetoptZ {
  bool found = false; int flavour = 0; int i1 = -1; int i2 = -1;
  float mll = -1.f, mrecoil = -1.f, cos_theta = -2.f, p1 = -1.f, p2 = -1.f; int n_extra = 0;
};

static float detopt_p(const RPD& r) {
  return std::sqrt(r.momentum.x * r.momentum.x + r.momentum.y * r.momentum.y + r.momentum.z * r.momentum.z);
}

// Z -> ll candidate (note Section 5.1): same-flavour opposite-sign e or mu pair,
// both with 25 < p < 80 GeV, mass closest to 91.2 GeV. n_extra counts the other
// electrons and muons with p > 25 GeV.
DetoptZ detopt_z_to_ll(const ROOT::VecOps::RVec<int>& el, const ROOT::VecOps::RVec<int>& mu,
                       const ROOT::VecOps::RVec<RPD>& rp, float sqrts) {
  DetoptZ best; float bestd = 1e9f;
  auto scan = [&](const ROOT::VecOps::RVec<int>& idx, int fl) {
    for (size_t a = 0; a < idx.size(); ++a) for (size_t b = a + 1; b < idx.size(); ++b) {
      const RPD& la = rp[idx[a]]; const RPD& lb = rp[idx[b]];
      if (la.charge * lb.charge >= 0) continue;
      const float pa = detopt_p(la), pb = detopt_p(lb);
      if (pa < 25 || pa > 80 || pb < 25 || pb > 80) continue;
      TLorentzVector va, vb;
      va.SetXYZM(la.momentum.x, la.momentum.y, la.momentum.z, la.mass);
      vb.SetXYZM(lb.momentum.x, lb.momentum.y, lb.momentum.z, lb.mass);
      const TLorentzVector z = va + vb;
      const float d = std::abs(z.M() - 91.2f);
      if (d < bestd) {
        bestd = d; best.found = true; best.flavour = fl; best.i1 = idx[a]; best.i2 = idx[b];
        best.mll = z.M(); best.cos_theta = z.CosTheta(); best.p1 = std::max(pa, pb); best.p2 = std::min(pa, pb);
        TLorentzVector rec(0, 0, 0, sqrts); rec -= z; best.mrecoil = rec.M();
      }
    }
  };
  scan(el, 11); scan(mu, 13);
  if (best.found) {
    for (auto idx : {el, mu}) for (int i : idx)
      if (i != best.i1 && i != best.i2 && detopt_p(rp[i]) > 25) best.n_extra += 1;
  }
  return best;
}

ROOT::VecOps::RVec<RPD> detopt_without(const ROOT::VecOps::RVec<RPD>& rp, int i1, int i2) {
  ROOT::VecOps::RVec<RPD> out;
  for (int i = 0; i < (int)rp.size(); ++i) if (i != i1 && i != i2) out.push_back(rp[i]);
  return out;
}

int detopt_n_leptons(const ROOT::VecOps::RVec<int>& el, const ROOT::VecOps::RVec<int>& mu,
                     const ROOT::VecOps::RVec<RPD>& rp, float pmin, float pmax) {
  int n = 0;
  for (auto idx : {el, mu}) for (int i : idx) { const float p = detopt_p(rp[i]); if (p > pmin && p < pmax) ++n; }
  return n;
}

// Truth Higgs decay: 5 bb, 4 cc, 3 ss, 21 gg, 24 WW, 23 ZZ, 15 tautau, 22 gamma gamma,
// 2322 Z gamma, 13 mumu, 0 other, -1 no Higgs in the record.
int detopt_higgs_decay(const ROOT::VecOps::RVec<edm4hep::MCParticleData>& mc, const ROOT::VecOps::RVec<int>& dau) {
  for (size_t i = 0; i < mc.size(); ++i) {
    if (mc[i].PDG != 25) continue;
    std::vector<int> d;
    for (unsigned k = mc[i].daughters_begin; k < mc[i].daughters_end; ++k)
      if (k < dau.size() && dau[k] >= 0 && dau[k] < (int)mc.size()) d.push_back(std::abs(mc[dau[k]].PDG));
    if (d.empty() || std::find(d.begin(), d.end(), 25) != d.end()) continue;  // not the last copy
    auto n = [&](int x) { return (int)std::count(d.begin(), d.end(), x); };
    for (int x : {5, 4, 3, 21, 24, 23, 15, 22, 13}) if (n(x) >= 2) return x;
    if (n(23) && n(22)) return 2322;
    return 0;
  }
  return -1;
}

struct DetoptJJ { float e1 = 0, e2 = 0, n1 = 0, n2 = 0, mjj = 0, mrec = 0, cos_theta = 0, cos_dphi = 0; int lead = 0; };

// Dijet quantities; jets ordered by energy (lead = index of the more energetic jet).
DetoptJJ detopt_dijet(const ROOT::VecOps::RVec<float>& e, const ROOT::VecOps::RVec<float>& p,
                      const ROOT::VecOps::RVec<float>& theta, const ROOT::VecOps::RVec<float>& phi,
                      const ROOT::VecOps::RVec<int>& nconst, float sqrts) {
  DetoptJJ r;
  if (e.size() < 2) return r;
  const int a = e[0] >= e[1] ? 0 : 1, b = 1 - a;
  TLorentzVector ja, jb;
  ja.SetPxPyPzE(p[a] * std::sin(theta[a]) * std::cos(phi[a]), p[a] * std::sin(theta[a]) * std::sin(phi[a]), p[a] * std::cos(theta[a]), e[a]);
  jb.SetPxPyPzE(p[b] * std::sin(theta[b]) * std::cos(phi[b]), p[b] * std::sin(theta[b]) * std::sin(phi[b]), p[b] * std::cos(theta[b]), e[b]);
  const TLorentzVector jj = ja + jb;
  TLorentzVector rec(0, 0, 0, sqrts); rec -= jj;
  r.lead = a; r.e1 = e[a]; r.e2 = e[b]; r.n1 = nconst[a]; r.n2 = nconst[b];
  r.mjj = jj.M(); r.mrec = rec.M(); r.cos_theta = jj.CosTheta(); r.cos_dphi = std::cos(ja.DeltaPhi(jb));
  return r;
}
"""


def _init_root():
    import ROOT  # noqa: PLC0415

    ROOT.gROOT.SetBatch(True)
    ROOT.gSystem.Load("libFCCAnalyses")
    ROOT.dummyLoader()  # makes the FCCAnalyses headers available to the interpreter
    ROOT.gInterpreter.Declare("using namespace FCCAnalyses;")
    ROOT.gInterpreter.Declare(_HELPERS_CPP)
    return ROOT


def make_ntuple(sim_file: Path, out_file: Path, channel: str) -> dict:
    """Select one channel in one simulated file; write selected events with scores.

    Returns the raw (unweighted) cutflow. Run in its own process (ROOT, JIT).
    """
    from . import tagger  # noqa: PLC0415

    ROOT = _init_root()
    sys.path.insert(0, str(tagger.fccanalyses_python()))
    from addons.FastJet.jetClusteringHelper import ExclusiveJetClusteringHelper  # noqa: PLC0415

    df = ROOT.RDataFrame("events", str(sim_file))
    df = df.Define("higgs_decay", "detopt_higgs_decay(Particle, _Particle_daughters.index)")
    steps = [("all", df)]
    if channel == "ll":
        df = df.Define("zc", f"detopt_z_to_ll(Electron_objIdx.index, Muon_objIdx.index, ReconstructedParticles, {SQRT_S})")
        for name, col, expr in (
            ("z_flavour", None, "zc.flavour"), ("m_ll", None, "zc.mll"), ("m_recoil", None, "zc.mrecoil"),
            ("cos_theta_ll", None, "zc.cos_theta"), ("p_l1", None, "zc.p1"), ("p_l2", None, "zc.p2"),
            ("n_extra_leptons", None, "zc.n_extra"),
        ):
            df = df.Define(name, expr)
        df = df.Filter("zc.found"); steps.append(("SFOS pair, 25 < p < 80 GeV", df))
        df = df.Filter("m_ll > 81 && m_ll < 101"); steps.append(("81 < m_ll < 101 GeV", df))
        df = df.Filter("m_recoil > 120 && m_recoil < 140"); steps.append(("120 < m_recoil < 140 GeV", df))
        df = df.Filter("n_extra_leptons == 0"); steps.append(("no other lepton with p > 25 GeV", df))
        df = df.Define("rp_for_jets", "detopt_without(ReconstructedParticles, zc.i1, zc.i2)")
        jc = ExclusiveJetClusteringHelper("rp_for_jets", 2, "")
        df = jc.define(df)
        df = df.Define("d23", "JetClusteringUtils::get_exclusive_dmerge(_jet, 2)") \
               .Define("d34", "JetClusteringUtils::get_exclusive_dmerge(_jet, 3)")
        df = df.Define("jj", f"detopt_dijet(jet_e, jet_p, jet_theta, jet_phi, jet_nconst, {SQRT_S})")
        df = df.Filter("event_njet == 2 && d23 > 0 && d34 > 0"); steps.append(("d23 > 0, d34 > 0", df))
        extra = ["z_flavour", "m_ll", "m_recoil", "cos_theta_ll", "p_l1", "p_l2", "d23", "d34"]
    elif channel == "nunu":
        df = df.Define("n_veto_leptons",
                       "detopt_n_leptons(Electron_objIdx.index, Muon_objIdx.index, ReconstructedParticles, 20, 100)")
        df = df.Filter("n_veto_leptons == 0"); steps.append(("no lepton with 20 < p < 100 GeV", df))
        jc = ExclusiveJetClusteringHelper("ReconstructedParticles", 2, "")
        df = jc.define(df)
        df = df.Define("jj", f"detopt_dijet(jet_e, jet_p, jet_theta, jet_phi, jet_nconst, {SQRT_S})")
        df = df.Filter("event_njet == 2 && jj.e1 > 45 && jj.e1 < 105 && jj.e2 > 20 && jj.e2 < 70")
        steps.append(("45 < E_j1 < 105, 20 < E_j2 < 70 GeV", df))
        df = df.Filter("jj.n1 > 10 && jj.n2 > 6"); steps.append(("n_const > 10, 6", df))
        df = df.Filter("jj.cos_dphi < 0.999"); steps.append(("cos dphi_jj < 0.999", df))
        df = df.Filter("std::abs(jj.cos_theta) < 0.85"); steps.append(("|cos theta_jj| < 0.85", df))
        df = df.Filter("jj.mrec > 40 && jj.mrec < 145 && jj.mjj > 60 && jj.mjj < 150")
        steps.append(("40 < m_rec < 145, 60 < m_jj < 150 GeV", df))
        extra = []
    else:
        raise ValueError(f"unknown channel {channel}")

    counts = [(name, d.Count()) for name, d in steps]
    df, score_cols = tagger.add_stock_scores(df, jc.jets, jc.constituents)
    for cls, col in score_cols.items():
        df = df.Define(f"j1_{cls}", f"{col}[jj.lead]").Define(f"j2_{cls}", f"{col}[1 - jj.lead]")
    for name in ("e1", "e2", "n1", "n2", "mjj", "mrec", "cos_theta", "cos_dphi"):
        df = df.Define(f"jj_{name}", f"jj.{name}")
    columns = (["higgs_decay"] + extra
               + [f"jj_{n}" for n in ("e1", "e2", "n1", "n2", "mjj", "mrec", "cos_theta", "cos_dphi")]
               + [f"j{k}_{c}" for k in (1, 2) for c in score_cols])
    out_file.parent.mkdir(parents=True, exist_ok=True)
    df.Snapshot("events", str(out_file), columns)
    return {name: int(c.GetValue()) for name, c in counts}


def _ntuple_worker(sim_file: Path, out_file: Path, channel: str, log: Path) -> dict:
    """Run make_ntuple in a separate process; return its cutflow."""
    from . import tagger  # noqa: PLC0415

    spec = out_file.with_suffix(".json")
    key = {"input": str(sim_file), "input_size": sim_file.stat().st_size, "channel": channel,
           "tagger": tagger.description()}
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if spec.exists() and out_file.exists():
        saved = json.loads(spec.read_text())
        if saved.get("key") == key:
            return saved["cutflow"]
    with open(log, "w") as f:
        result = subprocess.run(
            [sys.executable, "-m", "detopt.analysis", "ntuple", str(sim_file), str(out_file), channel],
            stdout=f, stderr=subprocess.STDOUT, cwd=Path(__file__).resolve().parent.parent,
        )
    lines = [l for l in log.read_text(errors="replace").splitlines() if l.startswith("CUTFLOW ")]
    if result.returncode != 0 or not lines:
        raise RuntimeError(f"ntuple failed for {sim_file} ({channel}); see {log}")
    cutflow = json.loads(lines[-1][len("CUTFLOW "):])
    spec.write_text(json.dumps({"key": key, "cutflow": cutflow}, indent=2))
    return cutflow


# --------------------------------------------------------------------------- stage 2

def categorise(scores: dict[str, np.ndarray]) -> np.ndarray:
    """Category index per event from summed jet scores K (note Section 7.1.2).

    flavour index (B, C, S, G) * 3 + purity (low, mid, high); -1 if the largest
    summed score is U, D or TAU.
    """
    stacked = np.stack([scores[c] for c in SCORE_CLASSES])
    winner = np.argmax(stacked, axis=0)
    cat = np.full(stacked.shape[1], -1, dtype=np.int32)
    for f_index, flavour in enumerate(FLAVOURS):
        sel = winner == SCORE_CLASSES.index(flavour)
        lo, hi = PURITY_EDGES[flavour]
        k = scores[flavour][sel]
        purity = np.where(k < lo, 0, np.where(k <= hi, 1, 2))
        cat[sel] = f_index * 3 + purity
    return cat


def n_categories() -> int:
    return len(FLAVOURS) * len(PURITIES)


def bins_per_category(channel: str) -> int:
    return int(np.prod([n for (_, _, n) in BINNING[channel].values()]))


def channel_offset(channel: str) -> int:
    off = 0
    for ch in CHANNELS:
        if ch == channel:
            return off
        off += n_categories() * bins_per_category(ch)
    raise ValueError(channel)


def total_bins() -> int:
    return sum(n_categories() * bins_per_category(ch) for ch in CHANNELS)


def fit_bin(channel: str, category: np.ndarray, obs: dict[str, np.ndarray]) -> np.ndarray:
    """Global bin index per event (-1 outside the fit range or uncategorised)."""
    local = np.zeros(len(category), dtype=np.int64)
    ok = category >= 0
    for name, (lo, hi, n) in BINNING[channel].items():
        i = np.floor((obs[name] - lo) / (hi - lo) * n).astype(np.int64)
        ok &= (i >= 0) & (i < n)
        local = local * n + np.clip(i, 0, n - 1)
    out = channel_offset(channel) + category.astype(np.int64) * bins_per_category(channel) + local
    return np.where(ok, out, -1)


def _read_ntuple(path: Path) -> dict[str, np.ndarray]:
    import ROOT  # noqa: PLC0415

    f = ROOT.TFile.Open(str(path))
    has_events = bool(f and f.Get("events") and f.Get("events").GetEntries() > 0)
    f.Close()
    if not has_events:
        return {}
    return {k: np.asarray(v) for k, v in ROOT.RDataFrame("events", str(path)).AsNumpy().items()}


def make_histograms(tagged_files: list[Path], run_dir: Path, workers: int | None = None) -> Path:
    """Select ZH candidates and write the fit inputs; returns run_dir/hists/templates.npz.

    tagged_files are the simulation outputs (run_dir/sim/<sample>/part_NNN.edm4hep.root);
    with the stock tagger the scores are computed here.
    """
    from . import simulate, tagger  # noqa: PLC0415

    run_dir = Path(run_dir).resolve()
    manifest = json.loads((run_dir / "sim" / "manifest.json").read_text())
    if tagger.mode() == "stock":
        tagger.ensure_stock_model()

    jobs = []
    for f in (Path(t).resolve() for t in tagged_files):
        sample = f.parent.name
        for channel in CHANNELS:
            out = run_dir / "ntuples" / sample / f"{f.name.split('.')[0]}_{channel}.root"
            jobs.append((sample, f, out, channel))

    errors, lock = [], threading.Lock()

    def run(job):
        sample, f, out, channel = job
        try:
            return _ntuple_worker(f, out, channel, out.with_suffix(".log"))
        except Exception as exc:
            with lock:
                errors.append(str(exc))
            return None

    with ThreadPoolExecutor(max_workers=workers or simulate.default_workers()) as pool:
        cutflows = list(pool.map(run, jobs))
    if errors:
        raise RuntimeError("analysis ntuples failed:\n" + "\n".join(errors))

    # Stage 2 runs in the main thread (ROOT).
    process_index = {p: i for i, p in enumerate(PROCESSES)}
    samples = sorted({j[0] for j in jobs})
    arrays = {"bin": [], "weight": [], "process": [], "channel": [], "sample": []}
    yields: dict = {ch: {} for ch in CHANNELS}
    cutflow_weighted: dict = {ch: {} for ch in CHANNELS}
    for (sample, f, out, channel), cutflow in zip(jobs, cutflows):
        info = manifest["samples"][sample]
        weight = info["effective_cross_section_pb"] * 1e3 * LUMI_FB / info["events"]
        cf = cutflow_weighted[channel].setdefault(sample, {})
        for step, n in cutflow.items():
            cf[step] = cf.get(step, 0.0) + n * weight
        d = _read_ntuple(out)
        if not d:
            continue
        scores = {c: d[f"j1_{c}"] + d[f"j2_{c}"] for c in SCORE_CLASSES}
        cat = categorise(scores)
        obs = ({"m_recoil": d["m_recoil"]} if channel == "ll"
               else {"m_rec": d["jj_mrec"], "m_jj": d["jj_mjj"]})
        b = fit_bin(channel, cat, obs)
        procs = np.array([process_name(sample, int(h)) or "" for h in d["higgs_decay"]])
        keep = (b >= 0) & (procs != "")
        n = int(keep.sum())
        arrays["bin"].append(b[keep])
        arrays["weight"].append(np.full(n, weight))
        arrays["process"].append(np.array([process_index[p] for p in procs[keep]], dtype=np.int16))
        arrays["channel"].append(np.full(n, CHANNELS.index(channel), dtype=np.int8))
        arrays["sample"].append(np.full(n, samples.index(sample), dtype=np.int16))
        for c in range(n_categories()):
            in_cat = keep & (cat == c)
            for p in set(procs[in_cat]):
                key = f"{FLAVOURS[c // 3]}-like {PURITIES[c % 3]}"
                yields[channel].setdefault(key, {}).setdefault(p, 0.0)
                yields[channel][key][p] += float((procs[in_cat] == p).sum() * weight)

    meta = {
        "note": "doi:10.17181/9pr7y-3v657",
        "lumi_fb": LUMI_FB,
        "channels": list(CHANNELS),
        "binning": {ch: {k: list(v) for k, v in BINNING[ch].items()} for ch in CHANNELS},
        "categories": [f"{f}-like {p}" for f in FLAVOURS for p in PURITIES],
        "processes": list(PROCESSES),
        "pois": list(POIS),
        "backgrounds": list(BACKGROUNDS),
        "fixed": list(FIXED),
        "samples": samples,
        "n_bins": total_bins(),
        "channel_bins": {ch: [channel_offset(ch), channel_offset(ch) + n_categories() * bins_per_category(ch)]
                         for ch in CHANNELS},
        "tagger": tagger.description(),
    }
    hists = run_dir / "hists"
    hists.mkdir(parents=True, exist_ok=True)
    out = hists / "templates.npz"
    cat_arrays = {k: (np.concatenate(v) if v else np.zeros(0)) for k, v in arrays.items()}
    np.savez_compressed(out, meta=json.dumps(meta), **cat_arrays)
    (hists / "summary.json").write_text(json.dumps(
        {"meta": meta, "yields": yields, "cutflow_weighted": cutflow_weighted}, indent=2))
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage-1 worker: one file, one channel.")
    parser.add_argument("command", choices=["ntuple"])
    parser.add_argument("sim_file", type=Path)
    parser.add_argument("out_file", type=Path)
    parser.add_argument("channel", choices=CHANNELS)
    args = parser.parse_args()
    cutflow = make_ntuple(args.sim_file, args.out_file, args.channel)
    print("CUTFLOW " + json.dumps(cutflow), flush=True)
    os._exit(0)  # skip ROOT/ONNX teardown, which can crash after a successful run


if __name__ == "__main__":
    main()
