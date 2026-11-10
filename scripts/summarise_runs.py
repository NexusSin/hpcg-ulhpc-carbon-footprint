#!/usr/bin/env python3
"""Per-run environmental metrics for the ten-run HPCG jobs on IRIS and Aion.

Reads, for each job, the RAPL counter log written between runs (rapl.tsv), the
HPCG report of every run, and the saved sacct record, and prints one row per run
plus the median, range and spread. Counter wrap-around is corrected with the
max_energy_range_uj values logged by the job.

Usage: python3 scripts/summarise_runs.py            (from the green_it folder)
"""
import glob, json, re, statistics as st, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'results'
JOBS = {
    'IRIS': dict(run='run-6064094', sacct='evidence/sacct-6064094.txt', out='hpcg-ten-6064094.out',
                 domains=('pkg0', 'pkg1', 'dram0', 'dram1'), mem_domains=('dram0', 'dram1')),
    'Aion': dict(run='run-aion-15867974', sacct='evidence/sacct-aion-15867974.txt', out='hpcg-aion-15867974.out',
                 domains=('pkg0', 'pkg1', 'core0', 'core1'), mem_domains=()),
}

def ranges(outfile):
    txt = (ROOT / outfile).read_text()
    return [int(x) for x in re.search(r'rapl range\s*:\s*([\d ]+)', txt).group(1).split()]

def rapl(job, cfg):
    rng = ranges(cfg['out'])
    rows = {}
    for line in (ROOT / cfg['run'] / 'rapl.tsv').read_text().splitlines():
        label, ts, vals = line.split('\t')
        rows[label] = (float(ts), [int(v) for v in vals.split()])
    def delta(a, b):
        (t0, v0), (t1, v1) = rows[a], rows[b]
        d = [(y - x) if y >= x else (y - x + r) for x, y, r in zip(v0, v1, rng)]
        return t1 - t0, dict(zip(cfg['domains'], (x / 1e6 for x in d)))
    return delta, rows

def hpcg(report):
    t = Path(report).read_text()
    g = lambda k: float(re.search(re.escape(k) + r'=([0-9.e+-]+)', t).group(1))
    return dict(rating=g('HPCG result is VALID with a GFLOP/s rating of'),
                timed=g('Benchmark Time Summary::Total'),
                flop=g('Floating Point Operations Summary::Total'),
                sets=int(g('Iteration Count Information::Total number of optimized iterations') // 50),
                data_gb=g('Memory Use Information::Total memory used for data (Gbytes)'))

def sacct(path):
    steps = {}
    if not (ROOT / path).exists():
        return steps
    for line in (ROOT / path).read_text().splitlines():
        p = line.split('|')
        m = re.match(r'\d+\.(\d+)$', p[0])
        if not m or len(p) < 8:
            continue
        i = int(m.group(1))
        tin, tout = p[5], p[6]
        mem = re.search(r'mem=(\d+)K', tin)
        rd = re.search(r'fs/disk=(\d+)', tin); wr = re.search(r'fs/disk=(\d+)', tout)
        steps[i] = dict(elapsed=int(p[1]), energy=int(p[2]) if p[2] else None,
                        cputime=int(p[3]), totalcpu=p[4],
                        mem_gib=int(mem.group(1)) / 2**20 if mem else None,
                        rd=int(rd.group(1)) if rd else None, wr=int(wr.group(1)) if wr else None,
                        freq=p[7])
    return steps

def summary(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    med = st.median(vals)
    return dict(median=med, min=min(vals), max=max(vals), spread_pct=100 * (max(vals) - min(vals)) / med,
                mean=st.mean(vals), sd=st.stdev(vals) if len(vals) > 1 else 0.0)

def main():
    result = {}
    for job, cfg in JOBS.items():
        delta, rows = rapl(job, cfg)
        steps = sacct(cfg['sacct'])
        runs = []
        for rep in range(1, 11):
            dt, d = delta(f'rep{rep}_start', f'rep{rep}_end')
            pkg = d['pkg0'] + d['pkg1']
            mem = sum(d[k] for k in cfg['mem_domains']) if cfg['mem_domains'] else None
            rep_file = glob.glob(str(ROOT / cfg['run'] / f'rep-{rep}' / 'HPCG-Benchmark*.txt'))[0]
            h = hpcg(rep_file)
            s = steps.get(rep - 1, {})
            counters = pkg + (mem or 0)
            runs.append(dict(rep=rep, seconds=dt, pkg_J=pkg, dram_J=mem, counters_J=counters,
                             slurm_J=s.get('energy'), elapsed=s.get('elapsed'), power_W=counters / dt,
                             pkg_W=pkg / dt, J_per_GFLOP=counters / (h['flop'] / 1e9),
                             pkgJ_per_GFLOP=pkg / (h['flop'] / 1e9), mem_gib=s.get('mem_gib'),
                             cputime=s.get('cputime'), freq=s.get('freq'), **h))
        idle = {}
        for k in ('idle1', 'idle2'):
            dt, d = delta(f'{k}_start', f'{k}_end')
            idle[k] = dict(pkg_W=(d['pkg0'] + d['pkg1']) / dt,
                           dram_W=sum(d[x] for x in cfg['mem_domains']) / dt if cfg['mem_domains'] else None)
        keys = ['seconds', 'elapsed', 'pkg_J', 'dram_J', 'counters_J', 'slurm_J', 'power_W', 'pkg_W',
                'rating', 'timed', 'flop', 'J_per_GFLOP', 'pkgJ_per_GFLOP', 'mem_gib']
        result[job] = dict(runs=runs, idle=idle, stats={k: summary([r[k] for r in runs]) for k in keys})
        print(f'\n=== {job}: ten runs ===')
        print(' rep    s   pkg_kJ  dram_kJ  total_kJ  slurm_kJ    W   GFLOP/s  timed  sets  J/GFLOP')
        for r in runs:
            f = lambda v, fmt: (fmt % v) if v is not None else '   -'
            print(f"{r['rep']:4d} {r['seconds']:6.1f} {r['pkg_J']/1e3:7.2f} {f(r['dram_J'] and r['dram_J']/1e3, '%7.2f')} "
                  f"{r['counters_J']/1e3:8.2f} {f(r['slurm_J'] and r['slurm_J']/1e3, '%8.2f')} {r['power_W']:6.1f} "
                  f"{r['rating']:8.3f} {r['timed']:6.2f} {r['sets']:4d} {r['J_per_GFLOP']:7.2f}")
        for k, v in result[job]['stats'].items():
            if v:
                print(f"   {k:15s} median {v['median']:12.4f}  min {v['min']:12.4f}  max {v['max']:12.4f}  spread {v['spread_pct']:5.2f} %  sd {v['sd']:.4f}")
        print('   idle:', {k: {a: round(b, 1) if b is not None else None for a, b in v.items()} for k, v in idle.items()})
    (ROOT / 'evidence' / 'ten-run-summary.json').write_text(json.dumps(result, indent=1, default=str))
    print('\nwritten:', ROOT / 'evidence' / 'ten-run-summary.json')

if __name__ == '__main__':
    main()
