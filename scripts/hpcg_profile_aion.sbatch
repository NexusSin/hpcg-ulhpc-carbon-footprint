#!/bin/bash -l
###############################################################################
# Green IT 2026 - the same frozen HPCG job on Aion, for the IRIS/Aion comparison.
#
# Same commit, same input, same shape as hpcg_ten_runs.sbatch on IRIS: 28 MPI
# ranks of one thread, 14 per socket, one exclusive node, ten runs back to back.
#
# Aion's SLURM records no energy (its acct_gather_energy/rapl plugin reads
# Intel-only registers, and ConsumedEnergy is empty for Aion jobs). The kernel
# does expose AMD's RAPL counters in sysfs: package-0/1 and their "core"
# sub-domains; AMD has no DRAM domain. They are read BETWEEN runs, never during
# them, plus 60 s of idle node before and after.
###############################################################################
# INSTRUMENTED VARIANT: three runs, with scripts/nodemeter.py taking a full
# snapshot at every boundary and sampling the node every 2 s throughout.
#SBATCH --job-name=hpcg-prof-aion
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=28
#SBATCH --ntasks-per-socket=14
#SBATCH --cpus-per-task=1
#SBATCH --exclusive
#SBATCH --time=00:25:00
#SBATCH --output=results/hpcg-prof-aion-%j.out
#SBATCH --error=results/hpcg-prof-aion-%j.err

set -euo pipefail

HPCG_DIR="${HOME}/green_it/hpcg"
HPCG_COMMIT="114602d458d1034faa52b71e4c15aba9b3a17698"
BUILD_DIR="${HPCG_DIR}/build_prof_aion"
RUN_ROOT="${HOME}/green_it/results/prof-aion-${SLURM_JOB_ID}"
REPS=3
IDLE_S=60
R=/sys/class/powercap

mkdir -p "${RUN_ROOT}"
RAPL_LOG="${RUN_ROOT}/rapl.tsv"

# pkg0 pkg1 core0 core1, in microjoules
read_rapl() {
  cat "$R/intel-rapl:0/energy_uj" "$R/intel-rapl:1/energy_uj" \
      "$R/intel-rapl:0:0/energy_uj" "$R/intel-rapl:1:0/energy_uj" | tr '\n' ' '
}
log_rapl() { printf '%s\t%s\t%s\n' "$1" "$(date +%s.%N)" "$(read_rapl)" >> "${RAPL_LOG}"; }
read_temps() {
  local out="" d
  for d in /sys/class/hwmon/hwmon*; do
    [ -r "$d/temp1_input" ] && out+="$(cat "$d/name" 2>/dev/null || echo hwmon)=$(cat "$d/temp1_input") "
  done
  echo "${out:-none}"
}

echo "=== provenance ==="
echo "job         : ${SLURM_JOB_ID} (Aion)"
echo "node        : $(hostname -s)"
echo "cpu         : $(lscpu | grep 'Model name' | sed 's/.*: *//')"
echo "os          : $(. /etc/os-release && echo "${PRETTY_NAME}")"
echo "kernel      : $(uname -r)"
echo "slurm       : $(sinfo --version 2>/dev/null || echo NA)"
echo "started     : $(date -Is)"
echo "rapl names  : $(cat "$R/intel-rapl:0/name" "$R/intel-rapl:1/name" "$R/intel-rapl:0:0/name" "$R/intel-rapl:1:0/name" | tr '\n' ' ')"
echo "rapl range  : $(cat "$R/intel-rapl:0/max_energy_range_uj" "$R/intel-rapl:1/max_energy_range_uj" "$R/intel-rapl:0:0/max_energy_range_uj" "$R/intel-rapl:1:0/max_energy_range_uj" | tr '\n' ' ')"

module purge
module load env/release/2023b
module load toolchain/foss/2023b
echo "=== modules ==="
module list 2>&1
mpicxx --version | head -1
mpirun --version 2>&1 | head -1

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

echo "=== idle ${IDLE_S} s, before ; temps $(read_temps) ==="
SNAP="${RUN_ROOT}/snapshots.jsonl"
taskset -c 127 nice -n 19 /usr/bin/python3 "${HOME}/green_it/scripts/nodemeter.py" sample 2 "${RUN_ROOT}/samples.jsonl" &
SAMPLER=$!
echo "sampler pid ${SAMPLER}: taskset -c 127 nice -n 19"
/usr/bin/python3 "${HOME}/green_it/scripts/nodemeter.py" snap idle1_start "${SNAP}"; log_rapl idle1_start; sleep "${IDLE_S}"; /usr/bin/python3 "${HOME}/green_it/scripts/nodemeter.py" snap idle1_end "${SNAP}"; log_rapl idle1_end

for rep in $(seq 1 ${REPS}); do
  RUN_DIR="${RUN_ROOT}/rep-${rep}"
  mkdir -p "${RUN_DIR}"; cd "${RUN_DIR}"
  cp "${RUN_ROOT}/hpcg.dat" .
  echo "=== rep ${rep}/${REPS} : step ${SLURM_JOB_ID}.$((rep-1)) : start $(date -Is) ; temps $(read_temps) ==="
  /usr/bin/python3 "${HOME}/green_it/scripts/nodemeter.py" snap "rep${rep}_start" "${SNAP}"; log_rapl "rep${rep}_start"
  if [ "${rep}" -eq 1 ]; then BIND=verbose,cores; else BIND=cores; fi
  srun --cpu-bind="${BIND}" "${BUILD_DIR}/bin/xhpcg"
  log_rapl "rep${rep}_end"; /usr/bin/python3 "${HOME}/green_it/scripts/nodemeter.py" snap "rep${rep}_end" "${SNAP}"
  echo "rep ${rep} end : $(date -Is) ; temps $(read_temps)"
done

echo "=== idle ${IDLE_S} s, after ; temps $(read_temps) ==="
/usr/bin/python3 "${HOME}/green_it/scripts/nodemeter.py" snap idle2_start "${SNAP}"; log_rapl idle2_start; sleep "${IDLE_S}"; log_rapl idle2_end; /usr/bin/python3 "${HOME}/green_it/scripts/nodemeter.py" snap idle2_end "${SNAP}"
kill "${SAMPLER}" 2>/dev/null || true; wait "${SAMPLER}" 2>/dev/null || true
echo "amd_energy readable: $(/usr/bin/python3 "${HOME}/green_it/scripts/nodemeter.py" snap probe /dev/stdout | /usr/bin/python3 -c 'import json,sys; a=json.loads(sys.stdin.readline())["amd"]; print(bool(a) and a.get("readable",True))')"

echo "=== finished: $(date -Is) ==="
echo "runs in ${RUN_ROOT}"
