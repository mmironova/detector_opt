#!/bin/bash
# One design point per array task. Not yet run on Perlmutter.
#
#   sbatch --array=1-10 slurm/evaluate_array.sh designs.txt
#
# One design on a whole debug node (30 min limit, charged as a full node):
#   sbatch --qos=debug --time=00:30:00 --cpus-per-task=256 --array=1 slurm/evaluate_array.sh designs/baseline.txt
#
# designs.txt has one design per line:
#   <inner_radius_mm> <material_x0_percent> <hit_resolution_um> [beyond-baseline]
# The optional fourth column allows a design outside design.BOUNDS
# (up to design.EXTENDED_BOUNDS), e.g. "12.5 0.3298 3 beyond-baseline".

#SBATCH --job-name=detopt
#SBATCH --qos=shared
#SBATCH --constraint=cpu
#SBATCH --cpus-per-task=32
#SBATCH --time=02:00:00
#SBATCH --account=atlas
#SBATCH --output=slurm-%A_%a.out

set -euo pipefail

designs="$1"
read -r radius material resolution extra < <(sed -n "${SLURM_ARRAY_TASK_ID}p" "$designs")
case "${extra:-}" in
    "") flags=() ;;
    beyond-baseline) flags=(--beyond-baseline) ;;
    *) echo "unknown fourth column '$extra' in $designs line $SLURM_ARRAY_TASK_ID" >&2; exit 1 ;;
esac

cd "$SLURM_SUBMIT_DIR"
source ./setup.sh

# Work on scratch; $DETOPT_RUNS on CFS stays the durable record.
outputs="$DETOPT_RUNS"
work="${DETOPT_SCRATCH_RUNS:?SCRATCH is not set, so DETOPT_SCRATCH_RUNS is empty}"

hash=$(./run.sh python -c \
    'import sys; from detopt.design import Design; print(Design(*map(float, sys.argv[1:4])).hash)' \
    "$radius" "$material" "$resolution")
echo "design $radius $material $resolution -> $hash (work: $work/$hash, outputs: $outputs/$hash)"

# Never recompute: seed scratch with a result already kept on CFS, so evaluate
# returns it from cache (it still checks that n_events and seed match).
mkdir -p "$work/$hash"
if [ -f "$outputs/$hash/result.json" ] && [ ! -f "$work/$hash/result.json" ]; then
    cp "$outputs/$hash/result.json" "$work/$hash/"
fi

DETOPT_RUNS="$work" ./run.sh python -m detopt.evaluate \
    --inner-radius-mm "$radius" \
    --material-x0-percent "$material" \
    --hit-resolution-um "$resolution" \
    --n-events "${DETOPT_N_EVENTS:-100000}" \
    --seed 1 \
    ${flags[@]+"${flags[@]}"}

# Copy the summary back to CFS. Bulky files (EDM4hep, ntuples, templates) stay on scratch.
mkdir -p "$outputs/$hash"
for f in result.json design.json card.tcl hists/fit.json hists/summary.json sim/manifest.json; do
    if [ -f "$work/$hash/$f" ]; then cp "$work/$hash/$f" "$outputs/$hash/$(basename "$f")"; fi
done
