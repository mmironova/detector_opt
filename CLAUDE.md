# Working in this repo

## Goal
`python -m detopt.evaluate` takes three vertex-detector parameters and returns
the expected uncertainty on the H→cc signal strength (ZH, FCC-ee, IDEA baseline).
Everything else serves that one command.

## Environment
- Runs on NERSC Perlmutter. Key4hep does not source natively there.
- Run anything that needs Key4hep through the container: `./run.sh <command>`.
- `setup.sh` holds the image name, the pinned Key4hep release and the output path.
- Pure-Python code and `tests/` run without the container; `tests/test_simulate.py` needs it.
- Generator-level events are made once (`detopt/generate.py`, into `$DETOPT_GEN` on scratch) and shared
  by every design. Never regenerate them per design.

## Rules
- Login nodes: tests and jobs of about 100 events only. Anything heavier goes through Slurm (`slurm/`).
- Outputs go under `$DETOPT_RUNS/<design_hash>/` (`/global/cfs/cdirs/atlas/mironova/detector_opt/outputs`), never into the repo.
- Larger runs (Slurm) work in `$DETOPT_SCRATCH_RUNS` (`$SCRATCH/detopt-runs`) and copy `result.json`, `design.json` and `card.tcl` back to `$DETOPT_RUNS/<design_hash>/`.
- A design point is never recomputed: `evaluate` reads `result.json` if it exists.
- Use common random seeds across design points so differences are not noise.
- The tagger is retrained for every design point. Do not reuse a tagger across designs.
  Until that exists, the stock FCC model is a stand-in (`DETOPT_TAGGER=stock`); results say so.
- Do not change the pinned Key4hep release without saying so.

## Build order
1. `simulate.py`: stock IDEA card first, then the templated card.
2. `analysis.py` and `fit.py`: reproduce the published baseline sensitivity.
3. `tagger.py`: small network on track impact-parameter features.
4. Slurm job array over ten design points; record the cost per point.

Each stage gets a test that runs in under a minute.
