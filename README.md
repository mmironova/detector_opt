# detopt

Feasibility study for physics-driven detector optimization.

One command turns a detector design into a physics number:

```
./run.sh python -m detopt.evaluate --inner-radius-mm 13.7 --material-x0-percent 0.3 --hit-resolution-um 3
```

It returns the expected uncertainty on the H→cc signal strength in ZH at FCC-ee,
for an IDEA-like vertex detector described by three parameters.
The stock IDEA baseline is 13.7 mm, 0.32978 % X0 (0.309 mm of silicon) and 3 µm
(`detopt.design.BASELINE`); allowed ranges and their sources are in `detopt/design.py`.
Designs outside those ranges but inside `EXTENDED_BOUNDS` (inner radius down to 12.5 mm)
run only with `--beyond-baseline` and are labelled `"beyond_baseline": true` in `result.json`.

## Chain

| Stage | Module | Status |
|---|---|---|
| Design → Delphes card | `detopt/design.py` | working, tested |
| Generator-level events, made once for all designs | `detopt/generate.py`, `detopt/samples.py` | working |
| Generator files → Delphes → EDM4hep | `detopt/simulate.py` | working, tested |
| Tagger, retrained per design | `detopt/tagger.py` | stub |
| Selection → histograms | `detopt/analysis.py` | stub |
| Histograms → σ(μ) | `detopt/fit.py` | stub |
| Orchestration and caching | `detopt/evaluate.py` | working, tested |

Each stub raises `NotImplementedError` with a note on what to build.

## Setup on Perlmutter

1. Check `ls /cvmfs/sw.hsf.org`. If it is missing, ask NERSC to mount it.
2. Pull the container image named in `setup.sh` with `shifterimg pull`.
3. Edit `setup.sh`: pin `KEY4HEP_RELEASE`, set `DETOPT_RUNS` to an output path outside the repo. Slurm jobs work in `DETOPT_SCRATCH_RUNS` (default `$SCRATCH/detopt-runs`) and copy summaries back to `DETOPT_RUNS`.
4. Done: `cards/idea_template.tcl` is the stock IDEA card with the innermost vertex layer templated (see `cards/README.md`).
5. Produce the shared generator-level events once (into `DETOPT_GEN`, default `$SCRATCH/detopt-gen`):
   `sbatch slurm/generate.sh` (100k events per sample), or for tests only
   `./run.sh python -m detopt.generate --events-per-sample 100`.
   Samples and cross-sections are in `detopt/samples.py`.

`run.sh` and the Slurm script have not been run on Perlmutter yet.

## Tests

```
python -m pytest tests                # pure Python; simulation tests skip
./run.sh python -m pytest tests       # everything, needs the generator cache
```

These need only Python, not Key4hep.
