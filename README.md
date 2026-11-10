# HPCG on IRIS and Aion

This repository contains the final [paper](paper/pdf/short-paper-hpc-v1.pdf), its [LaTeX source](paper/src/short-paper-hpc-v1.tex), and the measurements behind its comparison of the carbon footprint of HPCG on the University of Luxembourg's IRIS and Aion clusters.

## From the paper to the runs

Each mean below covers 100 valid HPCG 3.1 runs with the same input and 28 MPI processes on one exclusive node. In the baseline directories, these are the `run-*-ref` records. In the optimised directories, they are the `after-*` records. The IRIS optimised allocation also contains 20 runs from ten paired rounds.

| Set | Job | Run records | Scheduler logs | Mean footprint per run |
| --- | --- | --- | --- | --- |
| IRIS baseline | 6151479 | [100 reference runs](results/hundred-iris-6151479/) | [stdout](results/hpcg-runs-6151479.out) · [stderr](results/hpcg-runs-6151479.err) | 5.98 g CO₂e |
| Aion baseline | 16077963 | [100 reference runs](results/hundred-aion-16077963/) | [stdout](results/hpcg-runs-16077963.out) · [stderr](results/hpcg-runs-16077963.err) | 3.13 g CO₂e |
| IRIS optimised | 6311086 | [100 runs with a 2.6 GHz cap](results/opt-iris-6311086/) | [stdout](results/hpcg-opt-6311086.out) · [stderr](results/hpcg-opt-6311086.err) | 5.32 g CO₂e |
| Aion optimised | 16213835 | [100 runs with a 2.0 GHz cap and one process per L3 cache](results/opt-aion-16213835/) | [stdout](results/hpcg-opt-16213835.out) · [stderr](results/hpcg-opt-16213835.err) | 2.51 g CO₂e |

On IRIS, the paper compares the 100 capped runs with nine uncapped reference runs on the same node (5.82 g CO₂e per run), a reduction of 8.7% calculated from the unrounded means. The [exclusion record](results/opt-iris-6311086/left-out-rounds.txt) explains why the first paired round was dropped. The original 100-run baseline used another IRIS node. On Aion, the 20.0% reduction compares the 100 optimised runs with the original 100-run baseline. The cap values in the table are the requests sent to SLURM. The saved `step-maxfreq.txt` files record 2,628,566 kHz on IRIS and 2,000,000 kHz on Aion.

Recorded results include the [baseline CSV](results/hundred-runs.csv), [baseline means](results/means-summary.md), [final analysis output](results/v1-numbers.log), and [generated result tables](paper/src/v1-tables.tex).

The first IRIS pilot was job **6037477** ([records](results/run-6037477/), [stdout](results/hpcg-6037477.out), [stderr](results/hpcg-6037477.err)). The pilot records contain its input and benchmark output. The earliest saved [submission script](scripts/hpcg_frozen.sbatch) runs five repetitions, as recorded in the [following allocation, 6037480](results/hpcg-6037480.out). The paper uses the five-repeat allocation and subsequent measurement and profiling jobs to estimate variation across nodes. [Aion job 16211935](results/opt-aion-16211935/) screened builds and clock caps, and [job 16213781](results/opt-aion-16213781/) completed two rounds comparing the clock cap and process placement before the allocation was stopped. The carbon payback calculation includes the cost of interrupted attempts in that placement test and in the [aborted allocations](results/aborted/). [Evidence](results/evidence/) includes scheduler accounting, energy-counter checks, allocation history and hardware records.

## Run scripts

The [baseline submission script](scripts/hpcg_runs.sbatch) and the [optimisation submission script](scripts/hpcg_opt.sbatch) use [the fixed input](scripts/hpcg.dat), [build settings](scripts/hpcg_build_variant.sh) and [node sampler](scripts/nodemeter.py). The optimisation script can also apply the [configuration selection rule](scripts/pick_best.py). The detailed logs record the settings used for each allocation.

To run on the clusters, put this repository at `~/green_it`. The scripts expect SLURM, the ULHPC software modules, readable processor energy counters and the following upstream HPCG checkout:

```bash
cd ~/green_it
git clone https://github.com/hpcg-benchmark/hpcg.git hpcg
git -C hpcg checkout 114602d458d1034faa52b71e4c15aba9b3a17698
```

Submit the relevant commands from the checkout on the corresponding cluster. These examples reproduce the configurations of the four final allocations.

```bash
# IRIS baseline
ROUNDS=100 VARIANTS=ref TAG=hundred \
  sbatch --export=ALL -C skylake --acctg-freq=energy=5 --time=09:00:00 scripts/hpcg_runs.sbatch

# IRIS optimised: ten paired rounds followed by 100 capped runs
TAG=opt ROUNDS=10 AFTER=100 KEEP=f26 CONFIGS='ref=ref@ f26=ref@2600000' \
  sbatch --export=ALL -C skylake --acctg-freq=energy=5 --time=13:00:00 scripts/hpcg_opt.sbatch

# Aion baseline
ROUNDS=100 VARIANTS=ref TAG=hundred \
  sbatch --export=ALL --ntasks-per-socket=14 --time=04:30:00 scripts/hpcg_runs.sbatch

# Aion optimised: 100 runs of the configuration selected during screening
TAG=opt ROUNDS=0 AFTER=100 KEEP=spread20 CONFIGS='spread20=ref@2000000@spread' \
  sbatch --export=ALL --ntasks-per-socket=14 --time=04:00:00 scripts/hpcg_opt.sbatch
```

## Work with the saved results

From the repository root, reproduce the baseline CSV from the raw records or try the paper's [jobprint tool](tool/README.md) against a saved accounting record:

```bash
python3 scripts/pool_runs.py --csv /tmp/hpcg-baseline.csv
python3 tool/jobprint.py --record tool/sample-iris.txt
```

The four final allocations include node snapshots and sensor samples. Each of the 400 runs has its own input and HPCG output, and the optimised runs also record the binding of each MPI process and the clock limits. The [final analysis script](scripts/v1_numbers.py) combines the run measurements with allocation records and the recorded frequency of HPCG jobs. For carbon payback, it uses the recorded totals of 3,888,124 output tokens for the project and 418,649 for the optimisation session. Run `python3 scripts/v1_numbers.py` from the repository root to regenerate the figures and tables. The paper builds directly from the [saved numbers](paper/src/v1-numbers.tex) and [tables](paper/src/v1-tables.tex):

```bash
cd paper
latexmk src/short-paper-hpc-v1.tex
```

The build uses pdfLaTeX, BibTeX and the IEEEtran class and produces `paper/pdf/short-paper-hpc-v1.pdf`.

## Licence

[MIT](LICENSE).
