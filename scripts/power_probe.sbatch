#!/bin/bash -l
###############################################################################
# Gap 1 probe, v2: how much of node power does SLURM's figure actually cover?
#
# The compute node exposes FOUR readable RAPL domains:
#   intel-rapl:0 / :1        package-0, package-1
#   intel-rapl:0:0 / :1:0    dram, dram
# SLURM's acct_gather_energy/rapl reports PACKAGE only, so DRAM is a component
# we can measure but its number omits. This samples every 5 s across a whole
# HPCG run and prints a power profile, so the setup phase and the scored CG
# phase can be told apart.
#
# v1 bug: no module load, so srun could not resolve the OpenMPI runtime and the
# "load" sample silently read an idle node. Fixed below; the run is now checked.
###############################################################################
#SBATCH --job-name=power-probe
#SBATCH --partition=batch
#SBATCH --constraint=skylake
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=28
#SBATCH --cpus-per-task=1
#SBATCH --exclusive
#SBATCH --time=00:20:00
#SBATCH --acctg-freq=energy=5
#SBATCH --output=results/probe-%j.out
#SBATCH --error=results/probe-%j.err

set -uo pipefail
echo "node: $(hostname -s)  class=${NODECLASS:-?}  start=$(date -Is)"

PKG=(); DRAM=()
for d in /sys/class/powercap/intel-rapl:[0-9]; do
  [ -r "$d/energy_uj" ] && PKG+=("$d/energy_uj")
  for s in "$d":*; do
    [ -r "$s/energy_uj" ] || continue
    [ "$(cat "$s/name" 2>/dev/null)" = "dram" ] && DRAM+=("$s/energy_uj")
  done
done
echo "package domains: ${#PKG[@]}   dram domains: ${#DRAM[@]}"

# Per-domain delta with wraparound correction. RAPL energy_uj counters wrap at
# max_energy_range_uj (~2.62e11 uJ on this part); a naive after-before then goes
# hugely negative and reads as about -26 kW. Observed on job 6037562.
delta_uj() {   # $1=energy file, $2=before value -> prints corrected delta
  local f=$1 before=$2 after maxf max
  after=$(cat "$f" 2>/dev/null || echo 0)
  if [ "$after" -lt "$before" ]; then
    maxf="${f%/energy_uj}/max_energy_range_uj"
    max=$(cat "$maxf" 2>/dev/null || echo 0)
    echo $(( after - before + max ))
  else
    echo $(( after - before ))
  fi
}

profile() {  # $1=label $2=duration $3=interval
  local label=$1
  local dur=$2
  local iv=$3
  local n=$((dur/iv))
  local i f pj dj
  local -a pbefore dbefore
  for ((i=0;i<n;i++)); do
    pbefore=(); dbefore=()
    for f in "${PKG[@]}";  do pbefore+=("$(cat "$f")"); done
    for f in "${DRAM[@]}"; do dbefore+=("$(cat "$f")"); done
    sleep "$iv"
    pj=0; dj=0
    for ((k=0;k<${#PKG[@]};k++));  do pj=$(( pj + $(delta_uj "${PKG[$k]}"  "${pbefore[$k]}") )); done
    for ((k=0;k<${#DRAM[@]};k++)); do dj=$(( dj + $(delta_uj "${DRAM[$k]}" "${dbefore[$k]}") )); done
    printf "  %-6s t=%3ds  package %6.1f W   dram %5.1f W   total %6.1f W\n" \
      "$label" "$((i*iv))" \
      "$(awk "BEGIN{print $pj/1000000/$iv}")" \
      "$(awk "BEGIN{print $dj/1000000/$iv}")" \
      "$(awk "BEGIN{print ($pj+$dj)/1000000/$iv}")"
  done
}

echo
echo "=== A. IDLE (30 s) ==="
profile idle 30 10

module purge
module load env/release/2023b
module load toolchain/foss/2023b

BUILD="${HOME}/green_it/hpcg/build_frozen"
if [ ! -x "${BUILD}/bin/xhpcg" ]; then
  echo "rebuilding xhpcg"
  cd "${HOME}/green_it/hpcg"
  rm -rf "${BUILD}"; mkdir -p "${BUILD}"; cd "${BUILD}"
  "${HOME}/green_it/hpcg/configure" MPI_GCC_OMP >/dev/null 2>&1
  make -j "${SLURM_CPUS_ON_NODE}" >/dev/null 2>&1
fi
ldd "${BUILD}/bin/xhpcg" | grep -qi "not found" && { echo "FATAL: unresolved libs"; ldd "${BUILD}/bin/xhpcg" | grep -i "not found"; exit 1; }
echo "xhpcg links cleanly"

RUN="${HOME}/green_it/results/probe-${SLURM_JOB_ID}"
mkdir -p "${RUN}"; cd "${RUN}"
cp "${BUILD}/bin/xhpcg" .
cp "${HOME}/green_it/scripts/hpcg.dat" .
export OMP_NUM_THREADS=1 OMP_PROC_BIND=close OMP_PLACES=cores

echo
echo "=== B. UNDER LOAD - full run, sampled every 10 s ==="
echo "    (setup+validation run first; the scored CG phase is the middle stretch)"
srun --cpu-bind=cores ./xhpcg > run.log 2>&1 &
SRUN_PID=$!
sleep 2
kill -0 $SRUN_PID 2>/dev/null || { echo "FATAL: srun died immediately"; cat run.log; exit 1; }
profile load 180 10
wait $SRUN_PID; RC=$?
echo "  srun exit=${RC}"

echo
echo "=== C. IDLE again (20 s) ==="
profile idle2 20 10

echo
echo "=== HPCG result ==="
grep -h "Final Summary::HPCG result" HPCG-Benchmark*.txt 2>/dev/null || echo "  (no result file)"
echo "=== done: $(date -Is) ==="
