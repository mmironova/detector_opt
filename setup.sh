#!/bin/bash
# Source this file: `source setup.sh`. It only sets variables.

# AlmaLinux 9 image for Key4hep. Check this path against the Key4hep docs,
# then: shifterimg pull $DETOPT_IMAGE
export DETOPT_IMAGE="${DETOPT_IMAGE:-ghcr.io/key4hep/key4hep-images/alma9:latest}"

# Pin a release so results stay reproducible. List them with:
#   source /cvmfs/sw.hsf.org/key4hep/setup.sh --list-releases
export KEY4HEP_RELEASE="${KEY4HEP_RELEASE:-SET-ME}"

# One directory per design point is written here. Use scratch.
export DETOPT_RUNS="${DETOPT_RUNS:-${SCRATCH:-$PWD}/detopt-runs}"
