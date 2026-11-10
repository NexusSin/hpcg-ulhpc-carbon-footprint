#!/usr/bin/env python3
"""Check that every run of a fully instrumented job has every measured quantity.

Reads results/<run>/ written by scripts/hpcg_full_ten*.sbatch (rapl.tsv,
snapshots.jsonl, samples.jsonl, rep-N/HPCG-Benchmark*.txt) and the saved sacct
record, and prints one row per run: time, processor energy (and memory energy on
Intel), HPCG rating, network and disk bytes, CPU use, clock, hottest sensor, and
whether the scheduler logged the step. Ends with a completeness verdict.
Usage: python3 scripts/check_full_runs.py results/full-aion-15882666 [sacct.txt]
"""
import glob, json, re, statistics as st, sys
from pathlib import Path

run = Path(sys.argv[1])
sacct = Path(sys.argv[2]) if len(sys.argv) > 2 else None

def load(p):
    return [json.loads(l) for l in open(p) if l.strip()]

snaps = {s['label']: s for s in load(run / 'snapshots.jsonl')}
samples = load(run / 'samples.jsonl')
reps = sorted(int(m.group(1)) for k in snaps for m in [re.match(r'rep(\d+)_start$', k)] if m)

def rapl(a, b, which):
    tot = 0.0
    for k, v in a['rapl'].items():
        if v['name'] is None or not v['name'].startswith(which) or k not in b['rapl']:
            continue
        d = b['rapl'][k]['uj'] - v['uj']
        tot += (d + v['range'] if d < 0 else d) / 1e6
    return tot

def ib(s, key):
    return 4 * sum(v.get(key, 0) for v in s['ib'].values())

steps = {}
if sacct and sacct.exists():
    for line in open(sacct):
        p = line.rstrip('\n').split('|')
        m = re.match(r'^\d+\.(\d+)$', p[0])
        if m:
            steps[int(m.group(1)) + 1] = (p[1], p[4] if len(p) > 4 else '')

rows, missing = [], []
for r in reps:
    a, b = snaps.get('rep%d_start' % r), snaps.get('rep%d_end' % r)
    rep_file = glob.glob(str(run / ('rep-%d' % r) / 'HPCG-Benchmark*.txt'))
    txt = Path(rep_file[0]).read_text() if rep_file else ''
    valid = 'HPCG result is VALID' in txt
    rating = re.search(r'GFLOP/s rating of=([\d.]+)', txt)
    if not (a and b):
        missing.append((r, 'counter snapshots')); continue
    win = [s for s in samples if a['t'] <= s['t'] <= b['t']]
    cpu = [y - x for x, y in zip(a['cpu'], b['cpu'])]
    temps = {}
    for s in win:
        for k, v in s['temp'].items():
            temps[k] = max(temps.get(k, -1), v)
    row = dict(rep=r, s=b['t'] - a['t'], pkg=rapl(a, b, 'package'), dram=rapl(a, b, 'dram'),
               rating=float(rating.group(1)) if rating else None, valid=valid,
               ib_out=(ib(b, 'port_xmit_data') - ib(a, 'port_xmit_data')) / 1e6,
               ib_in=(ib(b, 'port_rcv_data') - ib(a, 'port_rcv_data')) / 1e6,
               eth=sum((b['net'][n][0] - v[0]) + (b['net'][n][1] - v[1]) for n, v in a['net'].items() if n in b['net']) / 1e6,
               disk_w=sum(512 * (b['disk'][n][1] - v[1]) for n, v in a['disk'].items() if n in b['disk']) / 1e6,
               busy=100 * (1 - (cpu[3] + cpu[4]) / sum(cpu)), samples=len(win),
               hot=max(temps.values()) / 1000 if temps else None, n_temp=len(temps),
               step=steps.get(r, ('not checked', ''))[0])
    for key in ('rating', 'hot'):
        if row[key] is None:
            missing.append((r, key))
    if not valid:
        missing.append((r, 'valid HPCG report'))
    if row['samples'] < 10:
        missing.append((r, 'samples'))
    rows.append(row)

print('%-4s %7s %8s %7s %8s %6s %13s %7s %7s %6s %6s %5s %s' % ('run', 'time s', 'pkg kJ', 'mem kJ', 'GFLOP/s', 'valid',
      'IB out/in MB', 'eth MB', 'disk MB', 'busy%', 'hot C', 'samp', 'scheduler step'))
for x in rows:
    print('%-4d %7.1f %8.2f %7.2f %8.3f %6s %6.1f/%-6.1f %7.2f %7.2f %6.1f %6.1f %5d %s' % (
        x['rep'], x['s'], x['pkg'] / 1e3, x['dram'] / 1e3, x['rating'] or 0, 'yes' if x['valid'] else 'NO',
        x['ib_out'], x['ib_in'], x['eth'], x['disk_w'], x['busy'], x['hot'] or 0, x['samples'], x['step']))
if rows:
    print('median time %.1f s, median processor energy %.2f kJ, spread %.2f %%' % (
        st.median(x['s'] for x in rows), st.median(x['pkg'] for x in rows) / 1e3,
        100 * (max(x['pkg'] for x in rows) - min(x['pkg'] for x in rows)) / st.median(x['pkg'] for x in rows)))
print('runs found: %d; temperature sensors per run: %s' % (len(rows), sorted(set(x['n_temp'] for x in rows))))
print('COMPLETE: every run has every quantity' if len(rows) == 10 and not missing else 'INCOMPLETE: %s' % missing)
