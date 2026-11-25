"""Generator-level events -> Delphes fast simulation -> EDM4hep files.

Every design point reads the same generator-level events, produced once by
detopt/generate.py (see that module and detopt/samples.py). Only the Delphes
card changes between designs; the Delphes random seed of each job depends on
(seed, sample, part) only, so design points also share their smearing seeds.

Layout under the run directory:

    sim/manifest.json                        what was run, cross-sections, inputs
    sim/<sample>/part_NNN.edm4hep.root       Delphes output, one per input file
    sim/<sample>/part_NNN.tcl                card used (design card + MaxEvents, RandomSeed)
    sim/<sample>/part_NNN.log
    sim/<sample>/part_NNN.done               job spec; a part is skipped when it matches

``n_events`` is the number of events per sample. Inputs are consumed in the
order of the generator manifest, so a smaller run is a prefix of a larger one.
Runs inside the Key4hep container.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from . import _rootutil, generate
from . import samples as samples_module
from .samples import Sample

OUTPUT_CONFIG = generate.OUTPUT_CONFIG


@dataclass(frozen=True)
class Job:
    sample: str
    source: str
    part: int
    input: str
    events: int
    delphes_seed: int
    card_md5: str


def delphes_seed(seed: int, sample: str, part: int) -> int:
    """Delphes RandomSeed for one job: same for every design, distinct per job."""
    return (seed * 1_000_003 + zlib.crc32(f"{sample}:{part}".encode())) % 2_147_483_646 + 1


def default_workers() -> int:
    if "DETOPT_WORKERS" in os.environ:
        return int(os.environ["DETOPT_WORKERS"])
    if "SLURM_CPUS_PER_TASK" in os.environ:
        return int(os.environ["SLURM_CPUS_PER_TASK"])
    return min(4, os.cpu_count() or 1)  # login node


def plan(card: Path, n_events: int, seed: int, chosen: list[Sample],
         gen_dir: Path | None = None) -> tuple[list[Job], dict[str, dict]]:
    """Jobs to run, and the generator manifest of each sample."""
    card_md5 = hashlib.md5(card.read_bytes()).hexdigest()
    jobs, manifests = [], {}
    for sample in chosen:
        manifest = generate.load_manifest(sample, gen_dir)
        have = generate.available_events(manifest)
        if have < n_events:
            raise RuntimeError(
                f"{sample.name}: {have} generator-level events, {n_events} needed. Run\n"
                f"  ./run.sh python -m detopt.generate --events-per-sample {n_events}"
            )
        manifests[sample.name] = manifest
        sdir = generate.sample_dir(sample, gen_dir)
        remaining = n_events
        for part, inp in enumerate(manifest["inputs"]):
            if remaining == 0:
                break
            take = min(remaining, inp["events"])
            jobs.append(Job(sample.name, sample.source, part, str(sdir / inp["file"]), take,
                            delphes_seed(seed, sample.name, part), card_md5))
            remaining -= take
    return jobs, manifests


def _paths(sim_dir: Path, job: Job) -> dict[str, Path]:
    base = sim_dir / job.sample / f"part_{job.part:03d}"
    return {k: base.with_suffix(ext) for k, ext in
            (("out", ".edm4hep.root"), ("card", ".tcl"), ("log", ".log"), ("done", ".done"))}


def _run_job(job: Job, card_text: str, sim_dir: Path) -> Path:
    p = _paths(sim_dir, job)
    spec = json.dumps(asdict(job), indent=2)
    if p["done"].exists() and p["done"].read_text() == spec and p["out"].exists():
        return p["out"]
    p["out"].parent.mkdir(parents=True, exist_ok=True)
    p["done"].unlink(missing_ok=True)
    p["out"].unlink(missing_ok=True)
    p["card"].write_text(
        card_text
        + "\n# detopt/simulate.py: events and seed of this job\n"
        + f"set MaxEvents {job.events}\nset RandomSeed {job.delphes_seed}\n"
    )
    with open(p["log"], "w") as log:
        if job.source == "stdhep":
            unzip = subprocess.Popen(["pigz", "-dc", job.input], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
            result = subprocess.run(
                ["DelphesSTDHEP_EDM4HEP", str(p["card"]), str(OUTPUT_CONFIG), str(p["out"]), "-"],
                stdin=unzip.stdout, stdout=log, stderr=subprocess.STDOUT,
            )
            unzip.stdout.close()
            unzip.kill()  # Delphes stops at MaxEvents; the rest of the file is not needed
            unzip.wait()
        else:
            result = subprocess.run(
                ["DelphesROOT_EDM4HEP", str(p["card"]), str(OUTPUT_CONFIG), str(p["out"]), job.input],
                stdout=log, stderr=subprocess.STDOUT,
            )
    if result.returncode != 0:
        raise RuntimeError(f"Delphes failed for {job.sample} part {job.part}; see {p['log']}")
    return p["out"]  # checked and marked done by simulate(), in the main thread


def simulate(card: Path, run_dir: Path, n_events: int, seed: int,
             sample_names: list[str] | None = None, workers: int | None = None,
             gen_dir: Path | None = None) -> list[Path]:
    """Run Delphes with this card on the signal and background samples.

    Returns the EDM4hep files written under run_dir / "sim"; sim/manifest.json
    has, per sample, the effective cross-section and the events simulated.
    """
    chosen = samples_module.get(sample_names)
    jobs, manifests = plan(card, n_events, seed, chosen, gen_dir)
    sim_dir = run_dir / "sim"
    card_text = card.read_text()

    errors: list[str] = []
    lock = threading.Lock()

    def run(job: Job) -> Path | None:
        try:
            return _run_job(job, card_text, sim_dir)
        except Exception as exc:  # collect all failures, report together
            with lock:
                errors.append(str(exc))
            return None

    with ThreadPoolExecutor(max_workers=workers or default_workers()) as pool:
        outputs = list(pool.map(run, jobs))
    if errors:
        raise RuntimeError("simulation failed:\n" + "\n".join(errors))

    # Check every output in the main thread (ROOT must not run in worker threads).
    for job in jobs:
        p = _paths(sim_dir, job)
        spec = json.dumps(asdict(job), indent=2)
        if p["done"].exists() and p["done"].read_text() == spec:
            continue
        written = _rootutil.entries(p["out"], "events")
        if written != job.events:
            raise RuntimeError(f"{job.sample} part {job.part}: {written} events written, "
                               f"{job.events} expected; see {p['log']}")
        p["done"].write_text(spec)

    summary = {
        "card": str(card),
        "card_md5": jobs[0].card_md5 if jobs else None,
        "events_per_sample": n_events,
        "seed": seed,
        "key4hep_release": os.environ.get("KEY4HEP_RELEASE", "unknown"),
        "samples": {},
    }
    for sample in chosen:
        m = manifests[sample.name]
        parts = [j for j in jobs if j.sample == sample.name]
        summary["samples"][sample.name] = {
            "role": sample.role,
            "source": sample.source,
            "note": sample.note,
            "cross_section_pb": sample.cross_section_pb,
            "filter_efficiency": m["filter_efficiency"],
            "effective_cross_section_pb": m["effective_cross_section_pb"],
            "events": sum(j.events for j in parts),
            "parts": [
                {
                    "output": str(_paths(sim_dir, j)["out"].relative_to(run_dir)),
                    "input": j.input,
                    "input_checksum_or_seed": next(
                        (i.get("adler32") or i.get("seed")) for i in m["inputs"]
                        if j.input.endswith(i["file"])
                    ),
                    "events": j.events,
                    "delphes_seed": j.delphes_seed,
                }
                for j in parts
            ],
        }
    (sim_dir / "manifest.json").write_text(json.dumps(summary, indent=2))
    return [o for o in outputs if o is not None]
