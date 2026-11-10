#!/bin/bash -l
###############################################################################
# Green IT 2026 - many runs of the frozen HPCG job in ONE exclusive allocation,
# so that every run uses the same node.
#
# What runs is set at submission through environment variables:
#   VARIANTS  the builds to run, among ref (the original code, as measured since
#             2026-09-24), contig, native and opt (scripts/hpcg_build_variant.sh);
#             default: ref
#   ROUNDS    how many times each build runs; default: 100
#   TAG       prefix of the results folder; default: hundred
# With several builds, each round runs every build once, the order rotating from
# round to round, so that a slow drift of the node favours none of them.
#   100 runs of the original code, the measurement of Section III:
#     IRIS: sbatch -C skylake --acctg-freq=energy=5 --time=09:00:00 scripts/hpcg_runs.sbatch
#     Aion: sbatch --ntasks-per-socket=14 --time=04:30:00 scripts/hpcg_runs.sbatch
#
# Measured as in hpcg_full_ten*.sbatch: the RAPL counters in sysfs read between
# runs, never during them; a full node snapshot (scripts/nodemeter.py) at every
# boundary; the node sampled every 2 s; 60 s of idle node before and after.
###############################################################################
#SBATCH --job-name=hpcg-runs
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=28
#SBATCH --cpus-per-task=1
#SBATCH --exclusive
#SBATCH --output=results/hpcg-runs-%j.out
#SBATCH --error=results/hpcg-runs-%j.err

set -uo pipefail

VARIANTS="${VARIANTS:-ref}"
ROUNDS="${ROUNDS:-100}"
TAG="${TAG:-hundred}"
case "$(hostname -s)" in iris-*) CLUSTER=iris ;; aion-*) CLUSTER=aion ;; *) CLUSTER=other ;; esac
HPCG_DIR="${HOME}/green_it/hpcg"
HPCG_COMMIT="114602d458d1034faa52b71e4c15aba9b3a17698"
RUN_ROOT="${HOME}/green_it/results/${TAG}-${CLUSTER}-${SLURM_JOB_ID}"
IDLE_S=60
R=/sys/class/powercap
METER="/usr/bin/python3 ${HOME}/green_it/scripts/nodemeter.py"

mkdir -p "${RUN_ROOT}"
RAPL_LOG="${RUN_ROOT}/rapl.tsv"
SNAP="${RUN_ROOT}/snapshots.jsonl"

# the four RAPL domains in sysfs, microjoules: on IRIS package-0/1 and their DRAM,
# on Aion package-0/1 and their "core" sub-domains (AMD has no DRAM domain)
read_rapl() {
  cat "$R/intel-rapl:0/energy_uj" "$R/intel-rapl:1/energy_uj" \
      "$R/intel-rapl:0:0/energy_uj" "$R/intel-rapl:1:0/energy_uj" | tr '\n' ' '
}
log_rapl() { printf '%s\t%s\t%s\n' "$1" "$(date +%s.%N)" "$(read_rapl)" >> "${RAPL_LOG}"; }
mark() { ${METER} snap "$1" "${SNAP}"; log_rapl "$1"; }

echo "=== provenance ==="
echo "job         : ${SLURM_JOB_ID} (${CLUSTER}), builds [${VARIANTS}] x ${ROUNDS} rounds"
echo "node        : $(hostname -s)"
echo "cpu         : $(lscpu | grep 'Model name' | sed 's/.*: *//')"
echo "os          : $(. /etc/os-release && echo "${PRETTY_NAME}")"
echo "kernel      : $(uname -r)"
echo "slurm       : $(sinfo --version 2>/dev/null || echo NA)"
echo "started     : $(date -Is)"
echo "rapl names  : $(cat "$R/intel-rapl:0/name" "$R/intel-rapl:1/name" "$R/intel-rapl:0:0/name" "$R/intel-rapl:1:0/name" | tr '\n' ' ')"
echo "cpufreq     : $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_driver /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor /sys/devices/system/cpu/cpu0/cpufreq/scaling_max_freq 2>/dev/null | tr '\n' ' ')"
echo "dmi         : $(cat /sys/class/dmi/id/sys_vendor /sys/class/dmi/id/product_name 2>/dev/null | tr '\n' ' ')"
echo "=== memory modules (EDAC; empty where the kernel exposes none) ==="
for d in /sys/devices/system/edac/mc/mc*/dimm*; do
  [ -r "$d/size" ] && echo "${d#/sys/devices/system/edac/mc/} $(cat "$d/dimm_label" 2>/dev/null) $(cat "$d/size") MB"
done
grep MemTotal /proc/meminfo

module purge
module load env/release/2023b
module load toolchain/foss/2023b
echo "=== modules ==="
module list 2>&1
mpicxx --version | head -1

cd "${HPCG_DIR}"
[ "$(git rev-parse HEAD)" = "${HPCG_COMMIT}" ] || git checkout --quiet "${HPCG_COMMIT}"
echo "commit      : $(git rev-parse HEAD), $(git status --porcelain --untracked-files=no | wc -l) modified tracked files"
BUILT=()
for v in ${VARIANTS}; do
  if bash "${HOME}/green_it/scripts/hpcg_build_variant.sh" "${v}" "${HPCG_DIR}/build_${v}_${SLURM_JOB_ID}"; then
    BUILT+=("${v}")
  else
    echo "build ${v}: FAILED, left out"
  fi
done
[ ${#BUILT[@]} -gt 0 ] || { echo "no build succeeded"; exit 1; }
cp "${HOME}/green_it/scripts/hpcg.dat" "${RUN_ROOT}/hpcg.dat"
echo "input       : $(stat -c %s "${RUN_ROOT}/hpcg.dat") bytes, sha256 $(sha256sum "${RUN_ROOT}/hpcg.dat" | cut -d' ' -f1)"

export OMP_NUM_THREADS=1 OMP_PROC_BIND=close OMP_PLACES=cores

# --- idle node, before -------------------------------------------------------
if [ "${CLUSTER}" = aion ]; then PIN="taskset -c 127"; else PIN=""; fi
${PIN} nice -n 19 ${METER} sample 2 "${RUN_ROOT}/samples.jsonl" &
SAMPLER=$!
echo "sampler pid ${SAMPLER}: ${PIN} nice -n 19"
echo "=== idle ${IDLE_S} s, before ==="
mark idle1_start; sleep "${IDLE_S}"; mark idle1_end

# --- the runs: each round runs every build once, in a rotating order ----------
NB=${#BUILT[@]}
TOTAL=$((ROUNDS * NB))
n=0
for r in $(seq 0 $((ROUNDS - 1))); do
  for k in $(seq 0 $((NB - 1))); do
    v="${BUILT[$(( (r + k) % NB ))]}"
    n=$((n + 1))
    RUN_DIR="${RUN_ROOT}/run-$(printf %03d ${n})-${v}"
    mkdir -p "${RUN_DIR}"; cd "${RUN_DIR}"
    cp "${RUN_ROOT}/hpcg.dat" .
    echo "=== run ${n}/${TOTAL} ${v} : start $(date -Is) ==="
    mark "run${n}_${v}_start"
    srun --cpu-bind=cores "${HPCG_DIR}/build_${v}_${SLURM_JOB_ID}/bin/xhpcg" || echo "run ${n} ${v}: srun exit $?"
    mark "run${n}_${v}_end"
    echo "run ${n} ${v} end : $(date -Is) ; $(grep -h 'GFLOP/s rating of' HPCG-Benchmark*.txt 2>/dev/null | tail -1)"
  done
done

# --- idle node, after --------------------------------------------------------
echo "=== idle ${IDLE_S} s, after ==="
mark idle2_start; sleep "${IDLE_S}"; mark idle2_end
kill "${SAMPLER}" 2>/dev/null || true; wait "${SAMPLER}" 2>/dev/null || true

echo "=== finished: $(date -Is) ==="
echo "runs in ${RUN_ROOT}"
