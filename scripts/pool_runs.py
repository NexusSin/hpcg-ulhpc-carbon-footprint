#!/usr/bin/env python3
"""Collect the reference runs of the frozen HPCG job, per cluster, and convert
each run to grams of CO2e with the factors declared in Section III.C. The paper's
baseline is the 100-run allocation on each cluster (results/hundred-<cluster>-<id>);
the earlier, smaller sets load only with load(old=True).

Sources, all under results/ (the job IDs stay here; the paper names nodes A, B...):
  IRIS  job 6037480  (5 runs, 2026-09-24)  SLURM ConsumedEnergyRaw = packages + DRAM
        job 6064094  (10 runs, 2026-09-29) RAPL sysfs, evidence/ten-run-summary.json
        job 6064383  (3 runs, 2026-09-29)  RAPL sysfs, evidence/profile-summary.json
        job 6075604  (10 runs, 2026-10-01) RAPL sysfs, full-6075604/snapshots.jsonl
        hundred-iris-<id>                  RAPL sysfs, ref runs (opt runs reported apart)
  Aion  job 15867974 (10 runs), 15868360 (3), 15882666 (10), hundred-aion-<id>
Usage: python3 scripts/pool_runs.py [--csv out.csv]
"""
import glob, json, re, statistics as st, sys
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / 'results'
YEAR = 365.25 * 86400

# --- declared factors (Section III.C) ---------------------------------------
GRID = 108.42          # g CO2/kWh, ILR, national supply mix 2025 (Reg. ILR/E26/14)
SITE = {
    # PUE; embodied g CO2e outside use; years in service; allocated share
    'IRIS': dict(pue=1.63, emb=1256e3, life=8.8, alloc=0.3294, tdp=2 * 140),
    'Aion': dict(pue=1.10, emb=1200e3, life=4.9, alloc=0.5437, tdp=2 * 280),   # PUE: operator's DLC target, 'very close to 1'
}

def report(path_glob):
    """Rating, timed seconds, optimized iterations, validity, residual of one HPCG report."""
    f = sorted(glob.glob(path_glob))
    if not f:
        return {}
    t = Path(f[-1]).read_text()
    g = lambda k: (re.search(re.escape(k) + r'=([-\d.e+]+)', t) or [None, None])[1]
    return dict(rating=float(g('GFLOP/s rating of') or 'nan'),
                timed=float(g('Benchmark Time Summary::Total') or 'nan'),
                iters=int(float(g('Total number of optimized iterations') or 0)),
                flop=float(g('Floating Point Operations Summary::Total') or 'nan'),
                valid='result is VALID' in t,
                resid=float(g('Scaled residual mean') or 'nan'))

def rapl_delta(a, b, prefix):
    tot = 0.0
    for k, v in a['rapl'].items():
        if v['name'] and v['name'].startswith(prefix) and k in b['rapl']:
            d = b['rapl'][k]['uj'] - v['uj']
            tot += (d + v['range'] if d < 0 else d) / 1e6
    return tot

def components(a, b, samples):
    """Every reading between two snapshots: network, disk, CPU, clock, temperature, power."""
    ib = lambda s, k: 4 * sum(v.get(k, 0) for v in s['ib'].values())     # counters in 4-byte words
    dr = sum(b['disk'][d][0] - a['disk'][d][0] for d in a['disk'] if d in b['disk']) * 512
    dw = sum(b['disk'][d][1] - a['disk'][d][1] for d in a['disk'] if d in b['disk']) * 512
    eth = [n for n in a['net'] if not n.startswith(('ib', 'lo')) and n in b['net']]
    dc = [y - x for x, y in zip(a['cpu'], b['cpu'])]
    win = [s for s in samples if a['t'] <= s['t'] <= b['t']]
    hot_of = lambda s: max((v for k, v in s['temp'].items() if 'coretemp' in k or 'k10temp' in k), default=None)
    hots = [h for h in map(hot_of, win) if h is not None]
    # power over each 2-s sampling interval: packages, plus memory where reported
    def joules(x, y):
        tot = 0.0
        for k, v in x['rapl'].items():
            if v['name'] and v['name'].startswith(('package', 'dram')) and k in y['rapl']:
                d = y['rapl'][k]['uj'] - v['uj']
                tot += (d + v['range'] if d < 0 else d) / 1e6
        return tot
    pw = [joules(x, y) / (y['t'] - x['t']) for x, y in zip(win, win[1:]) if y['t'] > x['t']]
    return dict(ib_out=ib(b, 'port_xmit_data') - ib(a, 'port_xmit_data'),
                ib_in=ib(b, 'port_rcv_data') - ib(a, 'port_rcv_data'),
                eth_out=sum(b['net'][n][1] - a['net'][n][1] for n in eth),
                eth_in=sum(b['net'][n][0] - a['net'][n][0] for n in eth),
                disk_r=dr, disk_w=dw,
                busy=1 - (dc[3] + dc[4]) / sum(dc) if sum(dc) else None,
                clock=st.mean(s['freq'][0] for s in win) if win else None,
                hot=max(hots) / 1000 if hots else None,
                temp=st.mean(hots) / 1000 if hots else None,
                peak_W=max(pw) if pw else None)

def idle_power(root):
    """Mean power of the idle node before and after the runs (packages + memory)."""
    snaps = {}
    for line in open(root / 'snapshots.jsonl'):
        if line.strip():
            x = json.loads(line); snaps[x['label']] = x
    out = []
    for lab in ('idle1', 'idle2'):
        a, b = snaps.get(lab + '_start'), snaps.get(lab + '_end')
        if a and b:
            j = sum((lambda d, v: (d + v['range'] if d < 0 else d) / 1e6)(b['rapl'][k]['uj'] - v['uj'], v)
                    for k, v in a['rapl'].items()
                    if v['name'] and v['name'].startswith(('package', 'dram')) and k in b['rapl'])
            out.append(j / (b['t'] - a['t']))
    return out

def step_memory(sacct_file, job):
    """Memory touched by each step (GiB), from the scheduler's usage record."""
    mem = {}
    p = RES / 'evidence' / sacct_file
    if not p.exists():
        return mem
    for line in open(p):
        f = line.rstrip('\n').split('|')
        m = re.match(r'^' + job + r'\.(\d+)$', f[0])
        u = re.search(r'mem=([\d.]+)([KMG]?)', f[-1]) if m else None
        if u:
            mem[int(m.group(1)) + 1] = float(u.group(1)) / {'K': 2**20, 'M': 2**10, 'G': 1, '': 2**30}[u.group(2)]
    return mem

def from_snapshots(cluster, node, job, root, pattern, variant_of):
    snaps = {}
    for line in open(root / 'snapshots.jsonl'):
        if line.strip():
            s = json.loads(line); snaps[s['label']] = s
    samples = [json.loads(l) for l in open(root / 'samples.jsonl') if l.strip()] \
        if (root / 'samples.jsonl').exists() else []
    rows = []
    for lab in snaps:
        m = re.match(pattern, lab)
        if not m:
            continue
        a, b = snaps[lab], snaps.get(lab.replace('_start', '_end'))
        if b is None:
            continue
        key, variant, rundir = variant_of(m)
        pkg, dram = rapl_delta(a, b, 'package'), rapl_delta(a, b, 'dram')
        r = report(str(root / rundir / 'HPCG-Benchmark*.txt'))
        rows.append(dict(cluster=cluster, node=node, job=job, run=key, variant=variant,
                         seconds=b['t'] - a['t'], pkg_J=pkg, dram_J=dram if cluster == 'IRIS' else None,
                         **r, **components(a, b, samples)))
    return rows

def load(old=False):
    """Runs of the 100-run allocations; with old=True also the earlier, smaller sets."""
    rows = []
    if old:
        rows += load_old()
    for d in sorted(RES.glob('hundred-*-*')):
        cluster = 'IRIS' if '-iris-' in d.name else 'Aion'
        job = d.name.rsplit('-', 1)[1]
        out = RES / f'hpcg-runs-{job}.out'
        node = (re.search(r'node\s+:\s+(\S+)', out.read_text()) or [None, d.name])[1] if out.exists() else d.name
        new = from_snapshots(cluster, node, job, d, r'^run(\d+)_(\w+?)_start$',
                             lambda m: (int(m.group(1)), m.group(2), f'run-{int(m.group(1)):03d}-{m.group(2)}'))
        mem = step_memory(f'sacct-{job}.txt', job)
        for x in new:
            x['mem_gib'] = mem.get(x['run'])
        rows += new
    for x in rows:
        x['it_J'] = (x['pkg_J'] + (x['dram_J'] or 0)) if x.get('pkg_J') is not None else x.get('slurm_J')
    return rows

def load_old():
    """The sets measured before the 100-run allocations (2026-09-24 to 10-01)."""
    rows = []
    # IRIS, 2026-09-24, five runs, SLURM energy per step (packages + DRAM)
    for line in open(RES / 'evidence/ev_6037480.txt'):
        p = line.split('|')
        m = re.match(r'^6037480\.(\d)$', p[0])
        if m and len(p) > 12 and p[2] == 'COMPLETED':
            rep = int(m.group(1)) + 1
            r = report(str(RES / f'run-6037480/rep-{rep}/HPCG-Benchmark*.txt'))
            rows.append(dict(cluster='IRIS', node='iris-109', job='6037480', run=rep, variant='ref',
                             seconds=float(p[6]), pkg_J=None, dram_J=None, slurm_J=float(p[10]), **r))
    # ten runs of 2026-09-29, both clusters
    ten = json.load(open(RES / 'evidence/ten-run-summary.json'))
    for cluster, node, job, d in (('IRIS', 'iris-130', '6064094', 'run-6064094'),
                                  ('Aion', 'aion-0296', '15867974', 'run-aion-15867974')):
        for x in ten[cluster]['runs']:
            r = report(str(RES / d / f"rep-{x['rep']}/HPCG-Benchmark*.txt"))
            rows.append(dict(cluster=cluster, node=node, job=job, run=x['rep'], variant='ref',
                             seconds=x['seconds'], pkg_J=x['pkg_J'], dram_J=x['dram_J'], **r))
    # three instrumented runs of 2026-09-29, both clusters
    prof = json.load(open(RES / 'evidence/profile-summary.json'))
    for cluster, node, job, d in (('IRIS', 'iris-151', '6064383', 'prof-6064383'),
                                  ('Aion', 'aion-0216', '15868360', 'prof-aion-15868360')):
        for x in prof[cluster]['runs']:
            r = report(str(RES / d / f"rep-{x['rep']}/HPCG-Benchmark*.txt"))
            hot = [v for k, v in x['temp_max'].items() if 'coretemp' in k or 'k10temp' in k]
            rows.append(dict(cluster=cluster, node=node, job=job, run=x['rep'], variant='ref',
                             seconds=x['seconds'], pkg_J=x['pkg_J'],
                             dram_J=x['dram_J'] if cluster == 'IRIS' else None, **r,
                             ib_out=x['ib_tx'], ib_in=x['ib_rx'],
                             disk_w=sum(v[1] for v in x['disk'].values()), busy=x['node_busy'],
                             clock=x['freq_mean'], hot=max(hot) / 1000 if hot else None))
    # fully instrumented ten-run jobs of 2026-09-30 / 10-01
    for cluster, node, job, d in (('IRIS', 'iris-116', '6075604', 'full-6075604'),
                                  ('Aion', 'aion-0338', '15882666', 'full-aion-15882666')):
        rows += from_snapshots(cluster, node, job, RES / d, r'^rep(\d+)_start$',
                               lambda m: (int(m.group(1)), 'ref', f'rep-{m.group(1)}'))
    for x in rows:
        x['it_J'] = (x['pkg_J'] + (x['dram_J'] or 0)) if x.get('pkg_J') is not None else x.get('slurm_J')
    return rows

def grams(x):
    """Operational (node, site overhead) and embodied grams of one run."""
    s = SITE[x['cluster']]
    kwh = x['it_J'] / 3.6e6
    node = kwh * GRID
    over = kwh * (s['pue'] - 1) * GRID
    emb = s['emb'] * x['seconds'] / (s['life'] * YEAR * s['alloc'])
    return node, over, emb

def summary(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    return dict(n=len(v), mean=st.mean(v), sd=st.stdev(v) if len(v) > 1 else 0.0,
                median=st.median(v), min=min(v), max=max(v))

if __name__ == '__main__':
    rows = load()
    for x in rows:
        x['g_node'], x['g_site'], x['g_emb'] = grams(x)
        x['g_total'] = x['g_node'] + x['g_site'] + x['g_emb']
    if '--csv' in sys.argv:
        import csv
        keys = ['cluster', 'node', 'job', 'run', 'variant', 'seconds', 'pkg_J', 'dram_J', 'it_J', 'rating',
                'timed', 'iters', 'valid', 'resid', 'g_node', 'g_site', 'g_emb', 'g_total']
        with open(sys.argv[sys.argv.index('--csv') + 1], 'w', newline='') as f:
            w = csv.DictWriter(f, keys, extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    for cluster in ('IRIS', 'Aion'):
        ref = [x for x in rows if x['cluster'] == cluster and x['variant'] == 'ref']
        print(f'=== {cluster}: {len(ref)} reference runs on {len(set(x["node"] for x in ref))} nodes')
        for node in dict.fromkeys(x['node'] for x in ref):
            sub = [x for x in ref if x['node'] == node]
            m = lambda k: st.mean(x[k] for x in sub)
            print(f'  {node:10s} n={len(sub):3d}  t={m("seconds"):6.1f} s  E={m("it_J")/1e3:6.2f} kJ  '
                  f'rating={m("rating"):6.2f}  iters={sub[0]["iters"]}  valid={all(x["valid"] for x in sub)}  '
                  f'g={m("g_total"):5.2f} (node {m("g_node"):.2f} site {m("g_site"):.2f} emb {m("g_emb"):.2f})')
        for k in ('seconds', 'it_J', 'rating', 'g_node', 'g_site', 'g_emb', 'g_total'):
            s = summary([x[k] for x in ref])
            print(f'  pooled {k:8s} mean {s["mean"]:10.3f}  sd {s["sd"]:9.3f}  median {s["median"]:10.3f}  '
                  f'min {s["min"]:10.3f}  max {s["max"]:10.3f}')
        opt = [x for x in rows if x['cluster'] == cluster and x['variant'] == 'opt']
        if opt:
            print(f'  optimised runs: {len(opt)}')
