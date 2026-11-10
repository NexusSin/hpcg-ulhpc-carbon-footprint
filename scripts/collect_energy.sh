#!/bin/bash -l
###############################################################################
# Life-cycle-inventory numbers for one frozen HPCG job (5 reps, 5 srun steps).
#
# Usage: ./collect_energy.sh <jobid>
#
# Prints one row per rep, then the median and the spread, which is what the
# short-paper template asks III.B to report.
#
# ConsumedEnergyRaw is joules, from SLURM's acct_gather_energy/rapl plugin.
# The site sets AcctGatherNodeFreq=0 (no periodic polling), so the job script
# asks for sampling with --acctg-freq=energy=5. Verified to return non-zero on
# job 6037477, 2026-09-24. If a rep reports 0, do not use it.
###############################################################################
set -uo pipefail

JOBID="${1:?usage: collect_energy.sh <jobid>}"
RUN_ROOT="${HOME}/green_it/results/run-${JOBID}"

echo "=== raw accounting ==="
sacct -j "${JOBID}" \
  --format=JobID%18,JobName%12,State%11,Elapsed,ElapsedRaw,ConsumedEnergyRaw,MaxRSS,NodeList%10

echo
echo "=== per rep ==="
printf "%-5s %-16s %10s %8s %9s %10s %12s\n" \
       "rep" "step" "energy_J" "sec" "power_W" "GFLOP/s" "MFLOPs/W"

TMP=$(mktemp)
rep=0
while read -r step energy sec; do
  [ -z "${step}" ] && continue
  rep=$((rep+1))
  gf=$(grep -h "Final Summary::HPCG result is VALID with a GFLOP/s rating of=" \
        "${RUN_ROOT}/rep-${rep}"/HPCG-Benchmark*.txt 2>/dev/null \
        | head -1 | sed 's/.*=//')
  [ -z "${gf}" ] && gf="NA"
  if [ "${energy}" = "0" ] || [ -z "${energy}" ]; then
    printf "%-5s %-16s %10s %8s %9s %10s %12s   <-- NO ENERGY, discard\n" \
           "${rep}" "${step}" "${energy:-0}" "${sec}" "-" "${gf}" "-"
    continue
  fi
  pw=$(awk "BEGIN{printf \"%.1f\", ${energy}/${sec}}")
  if [ "${gf}" = "NA" ]; then eff="NA"; else
    eff=$(awk "BEGIN{printf \"%.1f\", ${gf}*1000/${pw}}"); fi
  printf "%-5s %-16s %10s %8s %9s %10s %12s\n" \
         "${rep}" "${step}" "${energy}" "${sec}" "${pw}" "${gf}" "${eff}"
  echo "${energy} ${sec} ${gf}" >> "${TMP}"
done < <(sacct -n -j "${JOBID}" --format=JobID%30,JobName%12,ElapsedRaw,ConsumedEnergyRaw \
         | awk '$2=="xhpcg"{print $1, $4, $3}')

echo
echo "=== median and spread (what III.B reports) ==="
if [ ! -s "${TMP}" ]; then
  echo "No usable reps. RAPL accounting did not report - do not build the"
  echo "inventory on this job."
  rm -f "${TMP}"; exit 1
fi

awk '
{ e[NR]=$1; s[NR]=$2; if ($3!="NA") g[NR]=$3; n=NR }
function med(a, c,  i,v,m) {
  c=0; for (i=1;i<=n;i++) if (a[i]!="") { c++; v[c]=a[i] }
  if (c==0) return "NA"
  for (i=1;i<=c;i++) for (m=i+1;m<=c;m++) if (v[m]<v[i]) { t=v[i]; v[i]=v[m]; v[m]=t }
  return (c%2) ? v[(c+1)/2] : (v[c/2]+v[c/2+1])/2
}
function mn(a,  i,x) { x=""; for(i=1;i<=n;i++) if(a[i]!="" && (x==""||a[i]<x)) x=a[i]; return x }
function mx(a,  i,x) { x=""; for(i=1;i<=n;i++) if(a[i]!="" && (x==""||a[i]>x)) x=a[i]; return x }
END {
  me=med(e); ms=med(s); mg=med(g)
  printf "reps kept      : %d of 5\n", n
  printf "energy  median : %.0f J   (%.4f kWh)   min %.0f  max %.0f  spread %.1f%%\n", \
         me, me/3600000, mn(e), mx(e), 100*(mx(e)-mn(e))/mn(e)
  printf "elapsed median : %.0f s              min %.0f  max %.0f  spread %.1f%%\n", \
         ms, mn(s), mx(s), 100*(mx(s)-mn(s))/mn(s)
  printf "power   median : %.1f W\n", me/ms
  if (mg!="NA") {
    printf "GFLOP/s median : %.4f            min %.4f  max %.4f\n", mg, mn(g), mx(g)
    printf "efficiency     : %.1f MFLOP/J  (BENCHMARK VIEW - rating vs power)\n", mg*1000/(me/ms)
    printf "                 for an LCA use useful FLOPs / total joules instead;\n"
    printf "                 see docs/inventory.md section 9 - the two differ ~2.4x\n"
  }
  printf "\nrep 1 is the cold-cache run. Compare its row above against reps 2-5\n"
  printf "before reporting the median: the template asks whether the first run\n"
  printf "stands apart.\n"
}' "${TMP}"

rm -f "${TMP}"
