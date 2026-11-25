"""Generator-level events, produced once and shared by every design point.

    ./run.sh python -m detopt.generate --events-per-sample 100000

Runs inside the Key4hep container (needs xrdcp, Delphes and ROOT). Writes to
$DETOPT_GEN (default $SCRATCH/detopt-gen):

    $DETOPT_GEN/<sample>/manifest.json
    $DETOPT_GEN/<sample>/files/events_*.stdhep.gz   (source "stdhep": the official files)
    $DETOPT_GEN/<sample>/chunks/*_NNN.root          (source "stdhep": the same events, converted)
    $DETOPT_GEN/<sample>/chunk_NNN.root             (source "pythia8")

Every input simulate() reads is a Delphes generator-level ROOT file (Particle
branch) of at most STDHEP_CHUNK_EVENTS events, read with DelphesROOT_EDM4HEP.
The official stdhep files are converted once with Delphes (DelphesSTDHEP and
cards/generator_only.tcl) and split, because the k4SimDelphes executables
ignore SkipEvents: without chunks, one 100k-event file would be one long job.
The conversion stores single-precision values; the simulated events agree with
reading the stdhep file directly to floating-point rounding (checked: same
particles, same tracks, relative differences ~1e-7).

The manifest lists the inputs in the order simulate() consumes them, with
their event counts and checksums (stdhep) or seeds (pythia8), and for filtered
Pythia8 samples the measured filter efficiency. A copy of every manifest goes
to $DETOPT_RUNS/_generator/ on CFS. Scratch is purged, but the cache can be
rebuilt exactly: the official files never change and the Pythia8 seeds are fixed.

Running it again only adds what is missing, so it can be resumed.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import _rootutil
from . import samples as samples_module
from .samples import EOS_SERVER, Sample

REPO = Path(__file__).resolve().parent.parent
CARDS = REPO / "cards"
GENERATOR_ONLY_CARD = CARDS / "generator_only.tcl"
COUNT_CARD = CARDS / "count_events.tcl"
OUTPUT_CONFIG = CARDS / "edm4hep_output_config.tcl"

# Events per converted stdhep chunk (one Delphes job each in simulate()).
STDHEP_CHUNK_EVENTS = 10000

# Generated (not accepted) events per Pythia8 chunk.
PYTHIA_CHUNK_EVENTS = {True: 25000, False: 10000}  # keyed by "has a filter"

def gen_root() -> Path:
    path = os.environ.get("DETOPT_GEN")
    if not path:
        raise RuntimeError("DETOPT_GEN is not set; source setup.sh (it defaults to $SCRATCH/detopt-gen)")
    return Path(path)


def sample_dir(sample: Sample, root: Path | None = None) -> Path:
    return (root or gen_root()) / sample.name


def load_manifest(sample: Sample, root: Path | None = None) -> dict | None:
    path = sample_dir(sample, root) / "manifest.json"
    return json.loads(path.read_text()) if path.exists() else None


def available_events(manifest: dict | None) -> int:
    if not manifest:
        return 0
    if manifest["source"] == "stdhep":
        return sum(i["events"] for i in manifest.get("inputs", []) if i["file"].endswith(".root"))
    return sum(i["events"] for i in manifest["inputs"])


def _new_manifest(sample: Sample) -> dict:
    return {
        "sample": sample.name,
        "source": sample.source,
        "cross_section_pb": sample.cross_section_pb,
        "filter_boson": sample.filter_boson,
        "key4hep_release": os.environ.get("KEY4HEP_RELEASE", "unknown"),
        "inputs": [],
    }


def _write_manifest(sample: Sample, manifest: dict, root: Path) -> None:
    if sample.source == "pythia8":
        generated = sum(i["generated"] for i in manifest["inputs"])
        accepted = available_events(manifest)
        manifest["filter_efficiency"] = accepted / generated if generated else None
    else:
        manifest["filter_efficiency"] = 1.0
    eff = manifest["filter_efficiency"]
    manifest["effective_cross_section_pb"] = sample.cross_section_pb * eff if eff else None
    text = json.dumps(manifest, indent=2)
    path = sample_dir(sample, root) / "manifest.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(text)
    tmp.replace(path)
    runs = os.environ.get("DETOPT_RUNS")
    if runs:
        copy = Path(runs) / "_generator" / f"{sample.name}.json"
        copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_text(text)


def _run(cmd: list[str], log: Path, **kwargs) -> None:
    with open(log, "w") as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, **kwargs)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))} failed ({result.returncode}); see {log}")


def count_stdhep_events(path: Path, workdir: Path) -> int:
    """Number of events in a (gzipped) stdhep file, read once with Delphes."""
    out = workdir / "count.edm4hep.root"
    log = workdir / "count.log"
    with open(log, "w") as f:
        unzip = subprocess.Popen(["pigz", "-dc", str(path)], stdout=subprocess.PIPE)
        delphes = subprocess.run(
            ["DelphesSTDHEP_EDM4HEP", str(COUNT_CARD), str(OUTPUT_CONFIG), str(out), "-"],
            stdin=unzip.stdout, stdout=f, stderr=subprocess.STDOUT,
        )
        unzip.stdout.close()
        unzip.wait()
    if delphes.returncode != 0 or unzip.returncode != 0:
        raise RuntimeError(f"counting events in {path} failed; see {log}")
    return root_entries(out, "events")


def root_entries(path: Path, tree: str) -> int:
    """Entries of a ROOT tree, read in a separate process (safe from threads)."""
    return int(_rootutil.run("entries", path, tree))


def _eos_files(sample: Sample) -> list[str]:
    out = subprocess.run(
        ["xrdfs", EOS_SERVER, "ls", sample.eos_dir],
        capture_output=True, text=True, check=True,
    ).stdout
    return sorted(p for p in out.split() if p.endswith(".stdhep.gz"))


def _adler32_remote(eos_path: str) -> str:
    out = subprocess.run(
        ["xrdfs", EOS_SERVER, "query", "checksum", eos_path],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    return out[1] if len(out) > 1 else ""


def _adler32_local(path: Path) -> str:
    return subprocess.run(
        ["xrdadler32", str(path)], capture_output=True, text=True, check=True
    ).stdout.split()[0]


def _convert_and_split(sample: Sample, sdir: Path, entry: dict) -> list[dict]:
    """Convert one downloaded stdhep file to Delphes generator-level ROOT chunks."""
    local = sdir / entry["file"]
    (sdir / "chunks").mkdir(exist_ok=True)
    stem = local.name.split(".")[0]
    full = sdir / "chunks" / f"{stem}.full.root"
    full.unlink(missing_ok=True)
    with open(sdir / "chunks" / f"{stem}.log", "w") as log:
        unzip = subprocess.Popen(["pigz", "-dc", str(local)], stdout=subprocess.PIPE)
        conv = subprocess.run(["DelphesSTDHEP", str(GENERATOR_ONLY_CARD), str(full)],
                              stdin=unzip.stdout, stdout=log, stderr=subprocess.STDOUT)
        unzip.stdout.close()
        unzip.wait()
    if conv.returncode != 0 or unzip.returncode != 0:
        raise RuntimeError(f"converting {local} failed; see {sdir / 'chunks' / (stem + '.log')}")
    counts = _rootutil.run("split", full, sdir / "chunks" / stem, STDHEP_CHUNK_EVENTS)
    full.unlink()
    if sum(counts) != entry["events"]:
        raise RuntimeError(f"{local}: {sum(counts)} events converted, {entry['events']} counted")
    first = 0
    chunks = []
    for k, n in enumerate(counts):
        chunks.append({"file": f"chunks/{stem}_{k:03d}.root", "events": n, "source_file": entry["file"],
                       "first_event": first, "adler32": entry["adler32"]})
        first += n
    return chunks


def prepare_stdhep(sample: Sample, target: int, root: Path) -> dict:
    sdir = sample_dir(sample, root)
    (sdir / "files").mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(sample, root) or _new_manifest(sample)
    # Older manifests listed the stdhep files as inputs; keep them as stdhep_files.
    if "stdhep_files" not in manifest:
        manifest["stdhep_files"] = [i for i in manifest["inputs"] if i["file"].endswith(".stdhep.gz")]
        manifest["inputs"] = [i for i in manifest["inputs"] if i["file"].endswith(".root")]
    converted = {i["source_file"] for i in manifest["inputs"]}
    for entry in manifest["stdhep_files"]:
        if entry["file"] not in converted:
            manifest["inputs"] += _convert_and_split(sample, sdir, entry)
            _write_manifest(sample, manifest, root)
    have = {i["eos_path"] for i in manifest["stdhep_files"]}
    for eos_path in _eos_files(sample):
        if available_events(manifest) >= target:
            break
        if eos_path in have:
            continue
        local = sdir / "files" / Path(eos_path).name
        partial = local.with_suffix(".part")
        _run(["xrdcp", "--force", "--nopbar", f"{EOS_SERVER}/{eos_path}", str(partial)],
             sdir / "download.log")
        remote_sum, local_sum = _adler32_remote(eos_path), _adler32_local(partial)
        if remote_sum and remote_sum != local_sum:
            partial.unlink()
            raise RuntimeError(f"adler32 mismatch for {eos_path}: {remote_sum} != {local_sum}")
        partial.replace(local)
        with tempfile.TemporaryDirectory(dir=sdir) as tmp:
            events = count_stdhep_events(local, Path(tmp))
        entry = {
            "file": str(local.relative_to(sdir)),
            "eos_path": eos_path,
            "adler32": local_sum,
            "events": events,
        }
        manifest["stdhep_files"].append(entry)
        manifest["inputs"] += _convert_and_split(sample, sdir, entry)
        _write_manifest(sample, manifest, root)
        print(f"{sample.name}: {local.name} {events} events, total {available_events(manifest)}", flush=True)
    if available_events(manifest) < target:
        print(f"WARNING {sample.name}: only {available_events(manifest)} events on EOS", flush=True)
    _write_manifest(sample, manifest, root)
    return manifest


def _pythia_sigma_pb(log: Path) -> float | None:
    """Pythia's estimated cross-section (last 'sum' line of its statistics), in pb."""
    sums = [l for l in log.read_text(errors="replace").splitlines() if l.startswith(" | sum ")]
    if not sums:
        return None
    numbers = re.findall(r"[-+]?\d+(?:\.\d+)?(?:e[-+]?\d+)?", sums[-1])
    return float(numbers[3]) * 1e9 if len(numbers) >= 4 else None  # mb -> pb


def generate_pythia_chunk(sample: Sample, k: int, root: Path) -> dict:
    """Generate chunk k of a Pythia8 sample (fixed seed), apply its filter."""
    sdir = sample_dir(sample, root)
    n_gen = PYTHIA_CHUNK_EVENTS[sample.filter_boson is not None]
    seed = sample.seed_base + k
    cmd = sdir / f"chunk_{k:03d}.cmd"
    cmd.write_text(
        (CARDS / "pythia" / f"{sample.name}.cmd").read_text()
        + "\n! detopt/generate.py\n"
        + f"Main:numberOfEvents = {n_gen}\nRandom:setSeed = on\nRandom:seed = {seed}\n"
        + "Next:numberCount = 0\nNext:numberShowInfo = 0\n"
        + "Next:numberShowProcess = 0\nNext:numberShowEvent = 0\n"
    )
    raw = sdir / f"chunk_{k:03d}.unfiltered.root"
    log = sdir / f"chunk_{k:03d}.log"
    raw.unlink(missing_ok=True)
    _run(["DelphesPythia8", str(GENERATOR_ONLY_CARD), str(cmd), str(raw)], log)
    generated = root_entries(raw, "Delphes")
    out = sdir / f"chunk_{k:03d}.root"
    if sample.filter_boson is not None:
        accepted = int(_rootutil.run("filter", raw, out, sample.filter_boson))
        raw.unlink()
    else:
        raw.replace(out)
        accepted = generated
    return {
        "file": out.name,
        "seed": seed,
        "generated": generated,
        "events": accepted,
        "pythia_sigma_pb": _pythia_sigma_pb(log),
    }


def prepare_pythia8(sample: Sample, target: int, root: Path, workers: int) -> dict:
    sample_dir(sample, root).mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(sample, root) or _new_manifest(sample)
    while available_events(manifest) < target:
        done = {i["seed"] - sample.seed_base for i in manifest["inputs"]}
        next_k = max(done, default=-1) + 1
        if not manifest["inputs"]:
            n_new = 1  # first chunk measures the filter efficiency
        else:
            per_chunk = available_events(manifest) / len(manifest["inputs"])
            n_new = max(1, math.ceil((target - available_events(manifest)) / per_chunk))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            new = list(pool.map(lambda k: generate_pythia_chunk(sample, k, root),
                                range(next_k, next_k + n_new)))
        manifest["inputs"] = sorted(manifest["inputs"] + new, key=lambda i: i["seed"])
        _write_manifest(sample, manifest, root)
        print(f"{sample.name}: {len(manifest['inputs'])} chunks, {available_events(manifest)} events, "
              f"efficiency {manifest['filter_efficiency']:.4f}", flush=True)
    _write_manifest(sample, manifest, root)
    return manifest


def prepare(sample: Sample, target: int, root: Path | None = None, workers: int = 4) -> dict:
    root = root or gen_root()
    if sample.source == "stdhep":
        return prepare_stdhep(sample, target, root)
    return prepare_pythia8(sample, target, root, workers)


def main() -> None:
    parser = argparse.ArgumentParser(description="Produce the shared generator-level events once.")
    parser.add_argument("--events-per-sample", type=int, required=True)
    parser.add_argument("--samples", nargs="*", help="default: all samples")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("SLURM_CPUS_PER_TASK", 4)))
    args = parser.parse_args()

    for tool in ("xrdcp", "xrdfs", "pigz", "DelphesSTDHEP_EDM4HEP", "DelphesSTDHEP", "DelphesPythia8"):
        if shutil.which(tool) is None:
            raise SystemExit(f"{tool} not found: run this inside the container (./run.sh ...)")

    chosen = samples_module.get(args.samples)
    # stdhep downloads run side by side; Pythia8 chunks share the remaining workers.
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {s.name: pool.submit(prepare, s, args.events_per_sample, None,
                                       max(1, args.workers // 2)) for s in chosen}
        failed = []
        for name, fut in futures.items():
            try:
                m = fut.result()
                eff = m["filter_efficiency"]
                print(f"DONE {name}: {available_events(m)} events, "
                      f"{len(m['inputs'])} inputs, efficiency {eff:.4f}", flush=True)
            except Exception as exc:  # report every sample before failing
                failed.append(name)
                print(f"FAILED {name}: {exc}", flush=True)
    if failed:
        raise SystemExit(f"failed samples: {failed}")


if __name__ == "__main__":
    main()
