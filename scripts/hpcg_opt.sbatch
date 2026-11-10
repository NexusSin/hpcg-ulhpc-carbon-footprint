#!/bin/bash -l
###############################################################################
# Green IT 2026 - Section IV: optimising the HPCG job WITHOUT touching its code.
# Every configuration runs the same commit, the same hpcg.dat and 28 processes on
# one node reserved for the job alone; only what the cluster offers changes:
# compiler flags (passed to make), the processor clock (SLURM's --cpu-freq, per
# job step) and where the 28 processes sit on the node (SLURM's --cpu-bind).
# Everything runs in ONE exclusive allocation, so on one node.
#
# Phase 1, screening: each round runs every configuration once, the order
#   rotating from round to round, so a slow drift of the node favours none.
# Phase 2, after: scripts/pick_best.py applies the rule of Section IV-A to the
#   screening rounds, and the configuration it keeps runs AFTER times in a row:
#   the protocol of the 100-run baseline of Section III, applied to the change.
#
#   CONFIGS  space-separated name=build@cap[@bind]:
#              build  ref (HPCG's own build, -O3), o2 or native
#                     (scripts/hpcg_build_variant.sh)
#              cap    clock cap in kHz; empty: the default clock, turbo allowed
#              bind   empty: SLURM's default placement, as in Section III;
#                     spread (Aion only): one process per 4-core L3 cache group
#                     instead of three or four sharing one, each process still
#                     in the same one of the node's 8 memory domains
#   ROUNDS   screening rounds; default 10 (0: no screening)
#   AFTER    runs of the kept configuration after the screening; default 0
#   KEEP     the configuration to run AFTER times, chosen from earlier
#            allocations; empty: the one scripts/pick_best.py keeps
#   TAG      results folder prefix; default opt
#
#   100 runs of a configuration chosen before, no screening (Aion, 2026-11-09):
#     sbatch --ntasks-per-socket=14 --time=04:00:00 --export=ALL,ROUNDS=0,AFTER=100,\
#       KEEP=spread20,CONFIGS="spread20=ref@2000000@spread" scripts/hpcg_opt.sbatch
#
#   IRIS: sbatch -C skylake --acctg-freq=energy=5 --time=13:00:00 --export=ALL,AFTER=100,\
#           CONFIGS="ref=ref@ o2=o2@ native=native@ f26=ref@2600000 f20=ref@2000000" scripts/hpcg_opt.sbatch
#   Aion: sbatch --ntasks-per-socket=14 --time=06:30:00 --export=ALL,AFTER=100,\
#           CONFIGS="ref=ref@ f20=ref@2000000 spread=ref@@spread spread20=ref@2000000@spread" scripts/hpcg_opt.sbatch
#
# Measured as in hpcg_runs.sbatch: RAPL counters in sysfs read between runs, a
# node snapshot (scripts/nodemeter.py) at every boundary, the node sampled every
# 2 s, 60 s of idle node before and after. Labels run<n>_<config> and folders
# run-<nnn>-<config> in phase 1, after<n>_<config> and after-<nnn>-<config> in
# phase 2. Each run records the clock limit and the cores of all 28 processes.
###############################################################################
#SBATCH --job-name=hpcg-opt
#SBATCH --partition=batch
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=28
#SBATCH --cpus-per-task=1
#SBATCH --exclusive
#SBATCH --output=results/hpcg-opt-%j.out
#SBATCH --error=results/hpcg-opt-%j.err

set -uo pipefail

CONFIGS="${CONFIGS:-ref=ref@ o2=o2@ native=native@ f26=ref@2600000 f20=ref@2000000}"
ROUNDS="${ROUNDS:-10}"
AFTER="${AFTER:-0}"
TAG="${TAG:-opt}"
case "$(hostname -s)" in iris-*) CLUSTER=iris ;; aion-*) CLUSTER=aion ;; *) CLUSTER=other ;; esac
HPCG_DIR="${HOME}/green_it/hpcg"
HPCG_COMMIT="114602d458d1034faa52b71e4c15aba9b3a17698"
RUN_ROOT="${HOME}/green_it/results/${TAG}-${CLUSTER}-${SLURM_JOB_ID}"
IDLE_S=60
R=/sys/class/powercap
METER="/usr/bin/python3 ${HOME}/green_it/scripts/nodemeter.py"
CF=/sys/devices/system/cpu/cpu0/cpufreq

mkdir -p "${RUN_ROOT}"
RAPL_LOG="${RUN_ROOT}/rapl.tsv"
SNAP="${RUN_ROOT}/snapshots.jsonl"

read_rapl() {
  cat "$R/intel-rapl:0/energy_uj" "$R/intel-rapl:1/energy_uj" \
      "$R/intel-rapl:0:0/energy_uj" "$R/intel-rapl:1:0/energy_uj" | tr '\n' ' '
}
log_rapl() { printf '%s\t%s\t%s\n' "$1" "$(date +%s.%N)" "$(read_rapl)" >> "${RAPL_LOG}"; }
mark() { ${METER} snap "$1" "${SNAP}"; log_rapl "$1"; }

echo "=== provenance ==="
echo "job         : ${SLURM_JOB_ID} (${CLUSTER}), configs [${CONFIGS}] x ${ROUNDS} rounds, then ${AFTER} runs of the kept one"
echo "node        : $(hostname -s)"
echo "cpu         : $(lscpu | grep 'Model name' | sed 's/.*: *//')"
echo "numa        : $(lscpu | grep -E '^NUMA node[0-9]' | sed 's/.*: *//' | tr '\n' ' ')"
echo "kernel      : $(uname -r)"
echo "slurm       : $(sinfo --version 2>/dev/null || echo NA)"
echo "started     : $(date -Is)"
echo "cpufreq     : driver $(cat $CF/scaling_driver) governor $(cat $CF/scaling_governor) min $(cat $CF/cpuinfo_min_freq) max $(cat $CF/cpuinfo_max_freq) avail [$(cat $CF/scaling_available_frequencies 2>/dev/null)] governors [$(cat $CF/scaling_available_governors)]"
MINF=$(cat $CF/cpuinfo_min_freq)

module purge
module load env/release/2023b
module load toolchain/foss/2023b
mpicxx --version | head -1

cd "${HPCG_DIR}"
[ "$(git rev-parse HEAD)" = "${HPCG_COMMIT}" ] || git checkout --quiet "${HPCG_COMMIT}"
echo "commit      : $(git rev-parse HEAD), $(git status --porcelain --untracked-files=no | wc -l) modified tracked files"

# --- configurations and builds: each distinct build once -----------------------
NAMES=(); BUILDOF=(); CAPOF=(); BINDOF=()
for c in ${CONFIGS}; do
  NAMES+=("${c%%=*}")
  IFS=@ read -r b cap bind <<< "${c#*=}"
  BUILDOF+=("${b}"); CAPOF+=("${cap}"); BINDOF+=("${bind}")
done
for b in $(printf '%s\n' "${BUILDOF[@]}" | sort -u); do
  bash "${HOME}/green_it/scripts/hpcg_build_variant.sh" "${b}" "${HPCG_DIR}/build_${b}_${SLURM_JOB_ID}" \
    || echo "build ${b}: FAILED"
done
cp "${HOME}/green_it/scripts/hpcg.dat" "${RUN_ROOT}/hpcg.dat"
echo "input       : $(stat -c %s "${RUN_ROOT}/hpcg.dat") bytes, sha256 $(sha256sum "${RUN_ROOT}/hpcg.dat" | cut -d' ' -f1)"

# spread (Aion: 8 memory domains of 16 cores, each 4 L3 groups of 4 cores).
# SLURM's default, recorded in step-cores.txt, fills the domains in order,
# processes 0-3 in domain 0, 4-7 in domain 1, 8-11, 12-15, then 16-18, 19-21,
# 22-24, 25-27, each domain's processes on its first L3 group (cores 16k..16k+3).
# spread keeps every process in the same domain, so neighbours in HPCG's process
# grid stay as close as before, and gives each its own L3 group (core 16k+4j).
SPREAD=""
if [ "${CLUSTER}" = aion ]; then
  l=()
  for i in $(seq 0 27); do
    if [ "$i" -lt 16 ]; then k=$(( i / 4 )); j=$(( i % 4 )); else k=$(( 4 + (i - 16) / 3 )); j=$(( (i - 16) % 3 )); fi
    l+=($(( 16 * k + 4 * j )))
  done
  SPREAD=$(IFS=,; echo "${l[*]}")
  echo "spread      : map_cpu:${SPREAD}"
fi

export OMP_NUM_THREADS=1 OMP_PROC_BIND=close OMP_PLACES=cores

if [ "${CLUSTER}" = aion ]; then PIN="taskset -c 127"; else PIN=""; fi
${PIN} nice -n 19 ${METER} sample 2 "${RUN_ROOT}/samples.jsonl" &
SAMPLER=$!
echo "=== idle ${IDLE_S} s, before ==="
mark idle1_start; sleep "${IDLE_S}"; mark idle1_end

# one run: kind (run|after), number, index of the configuration
run_one() {
  local kind=$1 n=$2 i=$3
  local v="${NAMES[$i]}" b="${BUILDOF[$i]}" cap="${CAPOF[$i]}" bind="${BINDOF[$i]}"
  local BIN="${HPCG_DIR}/build_${b}_${SLURM_JOB_ID}/bin/xhpcg"
  [ -x "${BIN}" ] || { echo "${kind} ${n} ${v}: no binary, skipped"; return; }
  local FREQ_OPT=() BIND_OPT=(--cpu-bind=cores) LAUNCH=(srun)
  [ -n "${cap}" ] && FREQ_OPT=(--cpu-freq="${MINF}-${cap}:Performance")
  if [ "${bind}" = spread ]; then
    [ -n "${SPREAD}" ] || { echo "${kind} ${n} ${v}: spread is defined for Aion only, skipped"; return; }
    # a step gets only the cores SLURM picks for its 28 processes unless it asks for
    # the whole node (the job holds it anyway, --exclusive); srun ignores --whole
    # while the job's --cpus-per-task, passed down as these two variables, is set
    BIND_OPT=(--whole --cpu-bind=map_cpu:"${SPREAD}")
    LAUNCH=(env -u SLURM_CPUS_PER_TASK -u SLURM_TRES_PER_TASK srun)
  fi
  local RUN_DIR="${RUN_ROOT}/${kind}-$(printf %03d "${n}")-${v}"
  mkdir -p "${RUN_DIR}"; cd "${RUN_DIR}"
  cp "${RUN_ROOT}/hpcg.dat" .
  echo "=== ${kind} ${n} ${v} (build ${b}, cap ${cap:-none}, bind ${bind:-default}) : start $(date -Is) ==="
  mark "${kind}${n}_${v}_start"
  # every process records its cores, rank 0 the clock limits of the step; then each becomes HPCG
  "${LAUNCH[@]}" "${BIND_OPT[@]}" "${FREQ_OPT[@]}" bash -c \
    'echo "${SLURM_PROCID} $(grep Cpus_allowed_list /proc/self/status | cut -f2)" >> step-cores.txt
     [ "${SLURM_PROCID}" = 0 ] && cat /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq | sort | uniq -c > step-maxfreq.txt
     exec "$0"' "${BIN}" || echo "${kind} ${n} ${v}: srun exit $?"
  mark "${kind}${n}_${v}_end"
  echo "${kind} ${n} ${v} end : $(date -Is) ; max-freq $(tr -s ' \n' ' ' < step-maxfreq.txt 2>/dev/null) ; cores $(sort -n step-cores.txt 2>/dev/null | cut -d' ' -f2 | tr '\n' ' ') ; $(grep -h 'GFLOP/s rating of' HPCG-Benchmark*.txt 2>/dev/null | tail -1) ; $(grep -h -o 'result is [A-Z]*' HPCG-Benchmark*.txt 2>/dev/null | tail -1)"
}

# --- phase 1: screening ----------------------------------------------------------
# the run number advances even when a run is skipped, so that round = (n-1) / NC
NC=${#NAMES[@]}
TOTAL=$((ROUNDS * NC))
n=0
for r in $(seq 0 $((ROUNDS - 1))); do
  for k in $(seq 0 $((NC - 1))); do
    n=$((n + 1))
    echo "--- run ${n}/${TOTAL}"
    run_one run "${n}" $(( (r + k) % NC ))
  done
done

# --- phase 2: the kept configuration, AFTER runs in a row ---------------------------
if [ "${AFTER}" -gt 0 ]; then
  if [ -n "${KEEP:-}" ]; then
    WIN="${KEEP}"                    # chosen from earlier allocations' rounds
    echo "=== kept, as chosen from earlier allocations: ${WIN} ==="
  else
    WIN=$(/usr/bin/python3 "${HOME}/green_it/scripts/pick_best.py" "${RUN_ROOT}" "${CLUSTER}" "${NC}" 2> "${RUN_ROOT}/pick.log")
    sed 's/^/pick        : /' "${RUN_ROOT}/pick.log"
    echo "=== kept by the rule of Section IV-A: ${WIN:-none} ==="
  fi
  idx=-1; for i in "${!NAMES[@]}"; do [ "${NAMES[$i]}" = "${WIN}" ] && idx=$i; done
  if [ "${idx}" -ge 0 ]; then
    for m in $(seq 1 "${AFTER}"); do run_one after "${m}" "${idx}"; done
  else
    echo "no configuration kept: phase 2 skipped"
  fi
fi

echo "=== idle ${IDLE_S} s, after ==="
mark idle2_start; sleep "${IDLE_S}"; mark idle2_end
kill "${SAMPLER}" 2>/dev/null || true; wait "${SAMPLER}" 2>/dev/null || true
for b in $(printf '%s\n' "${BUILDOF[@]}" | sort -u); do rm -rf "${HPCG_DIR}/build_${b}_${SLURM_JOB_ID}"; done
echo "=== finished: $(date -Is) ==="
