#!/bin/bash
# Source this file: `source setup.sh`. It only sets variables.

# AlmaLinux 9 image for Key4hep. Check this path against the Key4hep docs,
# then: shifterimg pull $DETOPT_IMAGE
export DETOPT_IMAGE="${DETOPT_IMAGE:-ghcr.io/key4hep/key4hep-images/alma9:latest}"

# Pin a release so results stay reproducible. List them with:
#   source /cvmfs/sw.hsf.org/key4hep/setup.sh --list-releases
# 2026-04-08: newest dated release with an x86_64-almalinux9-gcc14.2.0-opt build.
export KEY4HEP_RELEASE="${KEY4HEP_RELEASE:-2026-04-08}"

# One directory per design point is written here (on CFS, next to the repo, not inside it).
# This is the durable record: small runs write here directly.
export DETOPT_RUNS="${DETOPT_RUNS:-/global/cfs/cdirs/atlas/mironova/detector_opt/outputs}"

# Larger runs (Slurm) work here and copy their summary files back to $DETOPT_RUNS.
# Scratch is purged, so nothing here is the only copy of a result.
export DETOPT_SCRATCH_RUNS="${DETOPT_SCRATCH_RUNS:-${SCRATCH:+$SCRATCH/detopt-runs}}"

# Generator-level events shared by every design point (detopt/generate.py).
# On scratch: it is purged, but can be rebuilt exactly (fixed files and seeds);
# manifests are also copied to $DETOPT_RUNS/_generator/.
export DETOPT_GEN="${DETOPT_GEN:-${SCRATCH:+$SCRATCH/detopt-gen}}"
