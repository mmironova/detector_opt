#!/bin/bash
# Produce the shared generator-level events once (downloads + Pythia8 chunks).
# Not yet run on Perlmutter.
#
#   sbatch slurm/generate.sh            # 100000 events per sample
#   DETOPT_N_EVENTS=20000 sbatch slurm/generate.sh
#
# Writes to $DETOPT_GEN (scratch); safe to resubmit, it only adds what is missing.

#SBATCH --job-name=detopt-gen
#SBATCH --qos=shared
#SBATCH --constraint=cpu
#SBATCH --cpus-per-task=32
#SBATCH --time=04:00:00
#SBATCH --account=atlas
#SBATCH --output=slurm-gen-%j.out

set -euo pipefail

cd "$SLURM_SUBMIT_DIR"
./run.sh python -m detopt.generate \
    --events-per-sample "${DETOPT_N_EVENTS:-100000}" \
    --workers "$SLURM_CPUS_PER_TASK"
