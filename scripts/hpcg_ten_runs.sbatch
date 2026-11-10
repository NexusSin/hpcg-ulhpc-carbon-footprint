#!/bin/bash -l
###############################################################################
# Green IT 2026 - reference measurement: ten runs of the frozen HPCG job.
#
# Same frozen object as hpcg_frozen.sbatch (commit, input, node type), run ten
# times back to back in ONE exclusive allocation, so the ten srun steps give ten
# separate SLURM energy readings on the same node.
#
# Added on top of SLURM's accounting:
#   - the RAPL counters in sysfs (package-0/1 and their DRAM) are read BETWEEN
#     runs, never during them, so the runs are not disturbed; this splits each
#     run's energy into processors and memory;
#   - the node's idle power, measured for 60 s before and after the ten runs;
#   - the run environment: OS, kernel, SLURM, modules, commit, input checksum.
###############################################################################
#SBATCH --job-name=hpcg-ten
#SBATCH --partition=batch
#SBATCH --constraint=skylake
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=28
#SBATCH --cpus-per-task=1
#SBATCH --exclusive
#SBATCH --time=00:50:00
#SBATCH --acctg-freq=energy=5
#SBATCH --output=results/hpcg-ten-%j.out
#SBATCH --error=results/hpcg-ten-%j.err

set -euo pipefail

HPCG_DIR="${HOME}/green_it/hpcg"
HPCG_COMMIT="114602d458d1034faa52b71e4c15aba9b3a17698"
BUILD_DIR="${HPCG_DIR}/build_ten"
RUN_ROOT="${HOME}/green_it/results/run-${SLURM_JOB_ID}"
REPS=10
IDLE_S=60
R=/sys/class/powercap

mkdir -p "${RUN_ROOT}"
RAPL_LOG="${RUN_ROOT}/rapl.tsv"

# pkg0 pkg1 dram0 dram1, in microjoules (readable by users on IRIS nodes)
read_rapl() {
  cat "$R/intel-rapl:0/energy_uj" "$R/intel-rapl:1/energy_uj" \
      "$R/intel-rapl:0:0/energy_uj" "$R/intel-rapl:1:0/energy_uj" | tr '\n' ' '
}
log_rapl() { printf '%s\t%s\t%s\n' "$1" "$(date +%s.%N)" "$(read_rapl)" >> "${RAPL_LOG}"; }
read_temps() {   # best effort: first temperature of every hwmon device, milli-degC
  local out="" d
  for d in /sys/class/hwmon/hwmon*; do
    [ -r "$d/temp1_input" ] && out+="$(cat "$d/name" 2>/dev/null || echo hwmon)=$(cat "$d/temp1_input") "
  done
  echo "${out:-none}"
}

echo "=== provenance ==="
echo "job         : ${SLURM_JOB_ID}"
echo "node        : $(hostname -s)   nodeclass=${NODECLASS:-unknown}"
echo "cpu         : $(lscpu | grep 'Model name' | sed 's/.*: *//')"
echo "os          : $(. /etc/os-release && echo "${PRETTY_NAME}")"
echo "kernel      : $(uname -r)"
echo "slurm       : $(sinfo --version 2>/dev/null || echo NA)"
echo "started     : $(date -Is)"
echo "rapl range  : $(cat "$R/intel-rapl:0/max_energy_range_uj" "$R/intel-rapl:1/max_energy_range_uj" "$R/intel-rapl:0:0/max_energy_range_uj" "$R/intel-rapl:1:0/max_energy_range_uj" | tr '\n' ' ')"

module purge
module load env/release/2023b
module load toolchain/foss/2023b
echo "=== modules ==="
module list 2>&1
mpicxx --version | head -1
mpirun --version 2>&1 | head -1

# --- build once, at the pinned commit -------------------------------------
cd "${HPCG_DIR}"
git checkout --quiet "${HPCG_COMMIT}"
echo "commit      : $(git rev-parse HEAD)"
rm -rf "${BUILD_DIR}"; mkdir -p "${BUILD_DIR}"; cd "${BUILD_DIR}"
"${HPCG_DIR}/configure" MPI_GCC_OMP > configure.log 2>&1
make -j "${SLURM_CPUS_ON_NODE}" > build.log 2>&1
echo "build       : ok, $(stat -c %s bin/xhpcg) bytes"
cp "${HOME}/green_it/scripts/hpcg.dat" "${RUN_ROOT}/hpcg.dat"
echo "input       : $(stat -c %s "${RUN_ROOT}/hpcg.dat") bytes, sha256 $(sha256sum "${RUN_ROOT}/hpcg.dat" | cut -d' ' -f1)"

export OMP_NUM_THREADS=1 OMP_PROC_BIND=close OMP_PLACES=cores

# --- idle node, before -------------------------------------------------------
echo "=== idle ${IDLE_S} s, before ; temps $(read_temps) ==="
log_rapl idle1_start; sleep "${IDLE_S}"; log_rapl idle1_end

# --- ten runs, all kept ------------------------------------------------------
for rep in $(seq 1 ${REPS}); do
  RUN_DIR="${RUN_ROOT}/rep-${rep}"
  mkdir -p "${RUN_DIR}"; cd "${RUN_DIR}"
  cp "${RUN_ROOT}/hpcg.dat" .
  echo "=== rep ${rep}/${REPS} : step ${SLURM_JOB_ID}.$((rep-1)) : start $(date -Is) ; temps $(read_temps) ==="
  log_rapl "rep${rep}_start"
  srun --cpu-bind=cores "${BUILD_DIR}/bin/xhpcg"
  log_rapl "rep${rep}_end"
  echo "rep ${rep} end : $(date -Is) ; temps $(read_temps)"
done

# --- idle node, after --------------------------------------------------------
echo "=== idle ${IDLE_S} s, after ; temps $(read_temps) ==="
log_rapl idle2_start; sleep "${IDLE_S}"; log_rapl idle2_end

echo "=== finished: $(date -Is) ==="
echo "runs in ${RUN_ROOT}"
