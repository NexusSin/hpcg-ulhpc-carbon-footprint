# External sources behind Section III.B, read 2026-09-29

Each line: what was taken, and from where. The ULHPC pages all carry the footer date 2026-09-25.

| fact used | source |
|---|---|
| Skylake nodes iris-[109-168], 60 nodes, 2 x Xeon Gold 6132 (14c, 2.6 GHz, 140 W), 128 GB DDR4-2400, SSD 120 GB, IB EDR ConnectX-4 | https://hpc-docs.uni.lu/systems/iris/compute/ |
| "December 2017: 60 new regular nodes added yet based on Skylake processors"; "iris-[109-168], Dell PowerEdge C6420" | https://hpc-docs.uni.lu/systems/iris/timeline/ (the compute page says C6320, the Broadwell nodes' server; the timeline is kept) |
| room CDC-S02-005, 7 racks; iris-[057-112] in D07, iris-[113-168] in D09; storage in the same room | https://hpc-docs.uni.lu/systems/iris/ |
| 196 nodes, 5824 cores, 52224 GB RAM; fat tree 1:1.5, EDR 100 Gb/s | https://hpc-docs.uni.lu/systems/iris/ |
| 18 x Mellanox SB7800 36-port EDR switches, 12 leaf + 6 spine | https://hpc-docs.uni.lu/systems/iris/interconnect/ |
| GPFS > 4 PB raw, renewed 2024 (Dell), HDR200 links; shared by Iris and Aion | https://hpc-docs.uni.lu/filesystems/gpfs/ |
| Lustre > 2 PB, converted 2025 | https://hpc-docs.uni.lu/filesystems/lustre/ |
| CDC S-02-005: Airflow, in-row cooling, 300 kW; HPC floor up to 3 MW electrical and 3 MW cold water; S-02-004 DLC (Aion) 1050 kW; no PUE on any page | https://hpc-docs.uni.lu/data-center/ |
| Aion "targeting a PUE very close to 1" | https://hpc-docs.uni.lu/systems/aion/ (course bibliography snapshot, 2026-09-18) |
| ConsumedEnergy "Only in the case of an exclusive job allocation does this value reflect the job's real energy consumption"; Ave/Tot memory = average/total of the highest watermarks over all ranks | https://slurm.schedmd.com/sacct.html (documents 26.05) |
| RAPL plugin sums MSR_PKG_ENERGY_STATUS and MSR_DRAM_ENERGY_STATUS for every package (lines 405-406) | slurm-25-11-8-1 tag, src/plugins/acct_gather_energy/rapl/acct_gather_energy_rapl.c (excerpt saved here) |
| fs/disk = rchar/wchar of /proc/<pid>/io (lines 451-476, 614) | slurm-25-11-8-1 tag, src/plugins/jobacct_gather/common/common_jag.c |
| rchar/wchar = bytes returned by successful read(2)/write(2) and similar calls | proc_pid_io(5), Linux man-pages 6.17 (excerpt saved here) |
| --acctg-freq: overrides JobAcctGatherFrequency; energy interval default 0 unless slurm.conf sets it (IRIS sets energy=30) | https://slurm.schedmd.com/sbatch.html + ev_config.txt |
| Dell C6420 PCF, Feb 2019, 6510 kgCO2e etc. | https://i.dell.com/sites/csdocuments/CorpComm_Docs/en/carbon-footprint-poweredge-c6420.pdf (558 797 bytes, identical to the local copy) |
| PUE by size class: 100-500 kW 1.63, 500-1000 kW 1.64, 1-2 MW 1.55, 2-10 MW 1.47, >10 MW 1.21 (weighted by energy, n=681) | EC DG ENER 2025, doi:10.2833/3168794, Figure 7 |
| worldwide average PUE 1.67 (Uptime Institute 2019) | Lannelongue et al., Adv. Sci. 2021, 8, 2100707, doi:10.1002/advs.202100707 |
| HPCG official runs >= 1800 s; working set >= 1/4 of main memory | hpcg README.md lines 46-58, at the pinned commit |
