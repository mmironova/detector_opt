#!/bin/bash
# One design point per array task. Not yet run on Perlmutter.
#
#   sbatch --array=1-10 slurm/evaluate_array.sh designs.txt
#
# designs.txt has one design per line:
#   <inner_radius_mm> <material_x0_percent> <hit_resolution_um>

#SBATCH --job-name=detopt
#SBATCH --qos=shared
#SBATCH --constraint=cpu
#SBATCH --cpus-per-task=8
#SBATCH --time=02:00:00
#SBATCH --account=SET-ME
#SBATCH --output=slurm-%A_%a.out

set -euo pipefail

designs="$1"
read -r radius material resolution < <(sed -n "${SLURM_ARRAY_TASK_ID}p" "$designs")

cd "$SLURM_SUBMIT_DIR"
./run.sh python -m detopt.evaluate \
    --inner-radius-mm "$radius" \
    --material-x0-percent "$material" \
    --hit-resolution-um "$resolution" \
    --n-events "${DETOPT_N_EVENTS:-100000}" \
    --seed 1
