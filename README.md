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
| Tagger, retrained per design | `detopt/tagger.py` | stock FCC model as a stand-in (unvalidated); retraining not written |
| Selection → categories → fit inputs | `detopt/analysis.py` | working, tested |
| Fit inputs → σ(μ_cc) and its MC statistical error | `detopt/fit.py` | working, tested |
| Orchestration and caching | `detopt/evaluate.py` | working, tested |

Each stub raises `NotImplementedError` with a note on what to build.

## Analysis and fit

Reference: A. Del Vecchio, J. Eysermans, L. Gouskos, G. Iakovidis, A. Maloizel,
G. Marchiori, M. Selvaggi, "Measurement of Higgs boson hadronic decays at FCC-ee",
FCC note, 31 March 2025, doi:10.17181/9pr7y-3v657 (FCC Feasibility Study Ref. [64]).
Z(ℓℓ)H follows its Section 5, Z(νν)H its analysis II (Section 7). Its expected
precision on μ_cc at 10.8 ab⁻¹ (statistical only): νν analysis II 1.74% without
and 2.27% with MC-statistics uncertainties (Table 14); ℓℓ 3.47% (Table 5).

`fit.py` returns `sigma_mu_hcc` (Asimov, Fisher matrix, all signal strengths and
background normalisations free, no systematics, no MC-statistics nuisance
parameters) and `sigma_mu_hcc_mcstat` (spread over Poisson-bootstrap replicas of
the MC events). `info_share_without_background_mc` is the share of the μ_cc
information from bins without any background MC; when it is large, σ(μ_cc) is
optimistic in a way the bootstrap cannot show.

Deviations from the note:

1. Tagger: stock ParticleNet model `IDEA_240_dolores_12_04_2023` (7 classes; very
   likely, but not confirmed, the note's "more recent training"), run with Key4hep
   2026-04-08 (EDM4hep 1.0, FCCAnalyses 0.12) instead of the 2023 software. The MC
   primary vertex used for its inputs is our own (most common production vertex of
   status-1 particles): FCCAnalyses looks for generator status 21, which Whizard
   samples do not have. The time-of-flight input is missing and gluon tagging is
   degraded. Not retrained per design. Results are labelled `"validated": false`.
2. Z(ℓℓ)H categories: tagger-score categories (note Section 7.1.2, Table 13) instead
   of the note's neural-network classifier, which also used kinematics and θℓℓ and
   had 7 Higgs + 3 background categories with purity sub-categories.
3. Z(νν)H cuts: analysis II does not give its "kinematics & d_ij" cuts, so analysis I's
   jet cuts are used (jet energies 45–105 / 20–70 GeV, more than 10 / 6 constituents,
   cos Δφ < 0.999), plus |cos θ_jj| < 0.85 and the fit window 40 < m_rec < 145,
   60 < m_jj < 150 GeV. Analysis II's lepton veto ("more than two leptons with
   p > 20 GeV") is read as at least one lepton with 20 < p < 100 GeV (orthogonal to ℓℓ).
4. H → ss̄ is not fitted: it stays in the inclusive ZH samples with H → γγ, Zγ, μμ, ...
   as a fixed "H_other" process (SM yield). H → bb, cc, gg events in the inclusive
   samples are removed with the MC truth (dedicated samples cover them).
5. Samples: Z(uu/dd)H with H → bb, cc, gg only (the note's qqH background has all
   Z → qq and all Higgs decays); ZZ and WW are decay-filtered at generation
   (ZZ → qq + ℓℓ/ττ/νν, WW → qq + ℓν), so e.g. ZZ → ℓℓττ is missing from the ℓℓ
   background.
6. MC statistics: 100k events per sample, against tens to hundreds of millions for the
   note's backgrounds. Same binning as the note (ℓℓ: m_recoil 120–140 GeV in 0.25 GeV
   bins; νν: m_rec × m_jj in 5 × 1 GeV bins); to be coarsened if the MC error or the
   share of information without background MC is large.
7. Fit: Fisher matrix in numpy instead of Combine (identical for the Asimov dataset);
   backgrounds float freely (analysis II used 5% log-normal constraints); MC statistics
   reported as a separate error, not as nuisance parameters, so compare with 1.74%.
8. Scope: 240 GeV only; no Z(qq)H channel; ZH and WW fusion not separated.
9. Detector: stock IDEA card (inner layer 13.7 mm, 0.33% X0) instead of the note's
   winter2023 card (12 mm, 0.30% X0).

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
