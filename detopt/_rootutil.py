"""Small ROOT helpers.

ROOT (cppyy) must not be used from Python worker threads, so code that runs in
threads calls these through ``run(...)``, which starts a separate process.
Code in the main thread may call the functions directly.

    python -m detopt._rootutil entries FILE TREE
    python -m detopt._rootutil filter SRC DST BOSON
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# C++ decision for the generation filter (see samples.Sample.filter_boson):
# exactly one boson with this |PDG id| decays to quarks (d u s c b) and exactly
# one to leptons or neutrinos (e mu tau and their neutrinos). Only the last
# copy of each boson in the event record is looked at.
FILTER_CPP = r"""
bool detopt_boson_filter(const ROOT::RVec<int>& pid, const ROOT::RVec<int>& d1,
                         const ROOT::RVec<int>& d2, int boson) {
  int nHad = 0, nLep = 0;
  const int n = pid.size();
  for (int i = 0; i < n; ++i) {
    if (std::abs(pid[i]) != boson || d1[i] < 0) continue;
    int kind = 0; bool last = true, any = false;
    for (int j = d1[i]; j <= std::max(d1[i], d2[i]) && j < n; ++j) {
      if (j < 0) continue;
      const int a = std::abs(pid[j]); any = true;
      if (a == boson) { last = false; break; }
      if (a >= 1 && a <= 5) kind = 1;
      else if (a >= 11 && a <= 16 && kind == 0) kind = 2;
    }
    if (!last || !any || kind == 0) continue;
    if (kind == 1) ++nHad; else ++nLep;
  }
  return nHad == 1 && nLep == 1;
}
"""


def entries(path: str | Path, tree: str) -> int:
    import ROOT  # noqa: PLC0415  (only available in the container)

    f = ROOT.TFile.Open(str(path))
    if not f or f.IsZombie():
        raise RuntimeError(f"cannot open {path}")
    t = f.Get(tree)
    n = int(t.GetEntries()) if t else 0
    f.Close()
    return n


def filter_chunk(src: str | Path, dst: str | Path, boson: int) -> int:
    """Copy the events of a Delphes generator tree that pass the filter; return how many."""
    import ROOT  # noqa: PLC0415

    ROOT.gInterpreter.Declare(FILTER_CPP)
    passing = ROOT.RDataFrame("Delphes", str(src)).Filter(
        f"detopt_boson_filter(Particle.PID, Particle.D1, Particle.D2, {int(boson)})"
    ).Take["ULong64_t"]("rdfentry_").GetValue()
    fin = ROOT.TFile.Open(str(src))
    tree = fin.Get("Delphes")
    keep = ROOT.TEntryList("keep", "keep", tree)
    for i in passing:
        keep.Enter(int(i))
    n_kept = int(keep.GetN())  # read before fin.Close(): the file owns the entry list
    tree.SetEntryList(keep)
    fout = ROOT.TFile(str(dst), "RECREATE")
    tree.CopyTree("").Write()
    fout.Close()
    fin.Close()
    return n_kept


def run(*args: str) -> int:
    """Call this module in a separate process; return its integer result."""
    result = subprocess.run(
        [sys.executable, "-m", "detopt._rootutil", *map(str, args)],
        capture_output=True, text=True, cwd=Path(__file__).resolve().parent.parent,
    )
    lines = [l for l in result.stdout.splitlines() if l.startswith("{")]
    if result.returncode != 0 or not lines:
        raise RuntimeError(f"_rootutil {' '.join(map(str, args))} failed:\n{result.stderr[-2000:]}")
    return int(json.loads(lines[-1])["result"])


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    if cmd == "entries":
        value = entries(rest[0], rest[1])
    elif cmd == "filter":
        value = filter_chunk(rest[0], rest[1], int(rest[2]))
    else:
        raise SystemExit(f"unknown command {cmd}")
    print(json.dumps({"result": value}))
