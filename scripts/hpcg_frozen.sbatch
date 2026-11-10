#!/bin/bash -l
###############################################################################
# Green IT 2026 - frozen measurement object, HPCG
#
# Protocol follows the short-paper template, III.B:
#   "an exclusive node so nothing else shares it, FIVE runs with all five kept
#    and the median reported [...] Say whether the caches were warm when each
#    run started, and give the spread from your fastest run to your slowest."
#
# Five runs are five srun STEPS inside ONE allocation. That gives five separate
# per-step ConsumedEnergy readings on identical silicon, and makes run 1 the
# cold-cache case with runs 2-5 warm - which is precisely the question the
# template asks about.
#
# Three choices that are not cosmetic:
#   --constraint=skylake  'batch' mixes broadwell (iris-001..108) and skylake
#                         (iris-109..168). Both advertise 28 cores and 114 GB,
#                         so without this you silently sample two CPU
#                         generations and the before/after stops being a
#                         comparison of anything.
#   --exclusive           RAPL counts the whole package; a shared node folds a
#                         stranger's work into the reading.
#   --acctg-freq=energy=5 the site sets AcctGatherNodeFreq=0, which disables
#                         periodic polling. Without this the energy fields come
#                         back zero. Verified non-zero on job 6037477,
#                         2026-09-24.
###############################################################################
#SBATCH --job-name=hpcg-frozen
#SBATCH --partition=batch
#SBATCH --constraint=skylake
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=28
#SBATCH --cpus-per-task=1
#SBATCH --exclusive
#SBATCH --time=00:45:00
#SBATCH --acctg-freq=energy=5
#SBATCH --output=results/hpcg-%j.out
#SBATCH --error=results/hpcg-%j.err

set -euo pipefail

HPCG_DIR="${HOME}/green_it/hpcg"
HPCG_COMMIT="114602d458d1034faa52b71e4c15aba9b3a17698"
BUILD_DIR="${HPCG_DIR}/build_frozen"
RUN_ROOT="${HOME}/green_it/results/run-${SLURM_JOB_ID}"
REPS=5

echo "=== provenance ==="
echo "job         : ${SLURM_JOB_ID}"
echo "node        : $(hostname -s)   nodeclass=${NODECLASS:-unknown}"
echo "cpu         : $(lscpu | grep 'Model name' | sed 's/.*: *//')"
echo "started     : $(date -Is)"

module purge
module load env/release/2023b
module load toolchain/foss/2023b
echo "=== toolchain ==="
mpicxx --version | head -1

# --- build once, at the pinned commit -------------------------------------
cd "${HPCG_DIR}"
git checkout --quiet "${HPCG_COMMIT}"
echo "commit      : $(git rev-parse HEAD)"

rm -rf "${BUILD_DIR}"
mkdir -p "${BUILD_DIR}"
cd "${BUILD_DIR}"
"${HPCG_DIR}/configure" MPI_GCC_OMP > configure.log 2>&1
make -j "${SLURM_CPUS_ON_NODE}" > build.log 2>&1
echo "build       : ok"

export OMP_NUM_THREADS=1
export OMP_PROC_BIND=close
export OMP_PLACES=cores

# --- five runs, all kept ---------------------------------------------------
for rep in $(seq 1 ${REPS}); do
  RUN_DIR="${RUN_ROOT}/rep-${rep}"
  mkdir -p "${RUN_DIR}"
  cd "${RUN_DIR}"
  cp "${HOME}/green_it/scripts/hpcg.dat" .
  cp "${BUILD_DIR}/bin/xhpcg" .

  if [ "${rep}" -eq 1 ]; then CACHE="cold (first touch of this allocation)";
  else CACHE="warm (rep $((rep-1)) just finished on this node)"; fi

  echo "=== rep ${rep}/${REPS} : step ${SLURM_JOB_ID}.$((rep-1)) : caches ${CACHE} ==="
  echo "rep ${rep} start: $(date -Is)"
  srun --cpu-bind=cores ./xhpcg
  echo "rep ${rep} end  : $(date -Is)"
done

echo "=== finished: $(date -Is) ==="
echo "runs in ${RUN_ROOT}"
echo
echo "Now collect with:  ./scripts/collect_energy.sh ${SLURM_JOB_ID}"
