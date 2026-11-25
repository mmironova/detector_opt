# detopt

Feasibility study for physics-driven detector optimization.

One command turns a detector design into a physics number:

```
./run.sh python -m detopt.evaluate --inner-radius-mm 13.7 --material-x0-percent 0.3 --hit-resolution-um 3
```

It returns the expected uncertainty on the H→cc signal strength in ZH at FCC-ee,
for an IDEA-like vertex detector described by three parameters.

## Chain

| Stage | Module | Status |
|---|---|---|
| Design → Delphes card | `detopt/design.py` | working, tested |
| Generator files → Delphes → EDM4hep | `detopt/simulate.py` | stub |
| Tagger, retrained per design | `detopt/tagger.py` | stub |
| Selection → histograms | `detopt/analysis.py` | stub |
| Histograms → σ(μ) | `detopt/fit.py` | stub |
| Orchestration and caching | `detopt/evaluate.py` | working, tested |

Each stub raises `NotImplementedError` with a note on what to build.

## Setup on Perlmutter

1. Check `ls /cvmfs/sw.hsf.org`. If it is missing, ask NERSC to mount it.
2. Pull the container image named in `setup.sh` with `shifterimg pull`.
3. Edit `setup.sh`: pin `KEY4HEP_RELEASE`, set `DETOPT_RUNS` to a scratch path.
4. Copy the stock IDEA Delphes card into `cards/` and template it (see `cards/README.md`).

`run.sh` and the Slurm script have not been run on Perlmutter yet.

## Tests

```
python -m pytest tests
```

These need only Python, not Key4hep.
