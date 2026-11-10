#!/usr/bin/env python3
"""Everything the instrumented runs measured, per run and per cluster.

Reads results/prof-*/snapshots.jsonl (full snapshot at each boundary) and
samples.jsonl (every 2 s), written by scripts/nodemeter.py, and prints per run:
energy by RAPL domain, network bytes (InfiniBand and Ethernet), local-disk bytes,
node CPU use, mean clock, temperatures, peak power, and on AMD the energy of the
cores the job used against the idle ones. Also writes a power-over-time series
for the profiled runs. Usage: python3 scripts/summarise_profile.py
"""
import glob, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / 'results'
JOBS = {'IRIS': 'prof-6064383', 'Aion': 'prof-aion-15868360'}

def load(p):
    return [json.loads(l) for l in open(p) if l.strip()]

def rapl_delta(a, b):
    out = {}
    for k, v in a['rapl'].items():
        w = b['rapl'].get(k)
        if not w:
            continue
        d = w['uj'] - v['uj']
        if d < 0:
            d += v['range']
        out.setdefault(v['name'], 0.0)
        out[v['name']] += d / 1e6
    return out

def sum_ib(s, key):
    return 4 * sum(v.get(key, 0) for v in s['ib'].values())   # counters count 4-byte words

def busy_cores_from_err(err):
    cores = set()
    for m in re.finditer(r'task +\d+ .*mask (0x[0-9A-Fa-f]+)', open(err).read()):
        x = int(m.group(1), 16); c = 0
        while x:
            if x & 1:
                cores.add(c)
            x >>= 1; c += 1
        if len(cores) >= 28:
            break
    return cores

def main():
    res = {}
    for job, d in JOBS.items():
        base = ROOT / d
        snaps = {s['label']: s for s in load(base / 'snapshots.jsonl')}
        samples = load(base / 'samples.jsonl')
        errf = glob.glob(str(ROOT / ('hpcg-prof-*%s.err' % d.split('-')[-1])))
        busy = busy_cores_from_err(errf[0]) if errf else set()
        runs = []
        for rep in range(1, 4):
            a, b = snaps['rep%d_start' % rep], snaps['rep%d_end' % rep]
            dt = b['t'] - a['t']
            e = rapl_delta(a, b)
            pkg = sum(v for k, v in e.items() if k.startswith('package'))
            dram = sum(v for k, v in e.items() if k == 'dram')
            win = [s for s in samples if a['t'] <= s['t'] <= b['t']]
            # power per 2 s interval inside the run
            pw = []
            for s0, s1 in zip(win, win[1:]):
                ee = rapl_delta(s0, s1)
                pw.append(sum(v for k, v in ee.items() if k.startswith('package') or k == 'dram') / (s1['t'] - s0['t']))
            cpu = [y - x for x, y in zip(a['cpu'], b['cpu'])]
            busy_frac = 1 - (cpu[3] + cpu[4]) / sum(cpu)
            net = {n: [b['net'][n][0] - v[0], b['net'][n][1] - v[1]] for n, v in a['net'].items() if n in b['net']}
            disk = {n: [512 * (b['disk'][n][0] - v[0]), 512 * (b['disk'][n][1] - v[1])] for n, v in a['disk'].items() if n in b['disk']}
            tmax = {}
            for s in win:
                for k, v in s['temp'].items():
                    tmax[k] = max(tmax.get(k, -1), v)
            freq = [s['freq'][0] for s in win if s.get('freq')]
            amd = None
            if a.get('amd') and b.get('amd') and a['amd'].get('readable', True) and len(a['amd']) > 4:
                de = {k: (b['amd'][k] - v) / 1e6 for k, v in a['amd'].items() if k in b['amd']}
                corek = {int(re.sub(r'\D', '', k)): v for k, v in de.items() if 'core' in k.lower()}
                amd = dict(busy_J=sum(v for c, v in corek.items() if c in busy),
                           idle_J=sum(v for c, v in corek.items() if c not in busy),
                           sockets_J=sum(v for k, v in de.items() if 'socket' in k.lower()),
                           n_busy=len([c for c in corek if c in busy]), n_idle=len([c for c in corek if c not in busy]))
            runs.append(dict(rep=rep, seconds=dt, rapl=e, pkg_J=pkg, dram_J=dram,
                             ib_tx=sum_ib(b, 'port_xmit_data') - sum_ib(a, 'port_xmit_data'),
                             ib_rx=sum_ib(b, 'port_rcv_data') - sum_ib(a, 'port_rcv_data'),
                             net=net, disk=disk, node_busy=busy_frac,
                             freq_mean=sum(freq) / len(freq) if freq else None,
                             temp_start={k: v for k, v in a['temp'].items()}, temp_max=tmax,
                             power_mean=(pkg + dram) / dt, power_peak=max(pw) if pw else None,
                             power_min=min(pw) if pw else None, amd=amd))
        # idle
        ia, ib = snaps['idle1_start'], snaps['idle1_end']
        ie = rapl_delta(ia, ib); idt = ib['t'] - ia['t']
        idle = dict(power={k: v / idt for k, v in ie.items()},
                    net={n: [ib['net'][n][0] - v[0], ib['net'][n][1] - v[1]] for n, v in ia['net'].items() if n in ib['net']},
                    ib_tx=sum_ib(ib, 'port_xmit_data') - sum_ib(ia, 'port_xmit_data'),
                    ib_rx=sum_ib(ib, 'port_rcv_data') - sum_ib(ia, 'port_rcv_data'), seconds=idt,
                    temp={k: v for k, v in ib['temp'].items()})
        # power series over the whole job, for the figure
        series = []
        for s0, s1 in zip(samples, samples[1:]):
            ee = rapl_delta(s0, s1)
            series.append([s1['t'], sum(v for k, v in ee.items() if k.startswith('package')) / (s1['t'] - s0['t']),
                           sum(v for k, v in ee.items() if k == 'dram') / (s1['t'] - s0['t'])])
        bounds = {k: v['t'] for k, v in snaps.items()}
        res[job] = dict(runs=runs, idle=idle, busy_cores=sorted(busy), series=series, bounds=bounds)
        print('\n=== %s (%s) ===' % (job, d))
        for r in runs:
            print(' rep %d: %.1f s  pkg %.2f kJ  dram %.2f kJ  mean %.0f W  peak %s W  busy %.1f %%  freq %s MHz  IB tx/rx %.2f/%.2f MB' % (
                r['rep'], r['seconds'], r['pkg_J'] / 1e3, r['dram_J'] / 1e3, r['power_mean'],
                '%.0f' % r['power_peak'] if r['power_peak'] else '-', 100 * r['node_busy'],
                '%.0f' % r['freq_mean'] if r['freq_mean'] else '-', r['ib_tx'] / 1e6, r['ib_rx'] / 1e6))
            print('        net', {k: [round(x / 1e6, 3) for x in v] for k, v in r['net'].items()},
                  ' disk MB', {k: [round(x / 1e6, 3) for x in v] for k, v in r['disk'].items()})
            print('        temp max', {k.split('/', 1)[1]: v / 1000 for k, v in r['temp_max'].items()})
            if r['amd']:
                print('        amd_energy', {k: round(v, 1) if isinstance(v, float) else v for k, v in r['amd'].items()})
        print(' idle', {k: round(v, 1) for k, v in idle['power'].items()}, 'W; IB tx/rx MB %.3f/%.3f' % (idle['ib_tx'] / 1e6, idle['ib_rx'] / 1e6))
        print(' idle temps', {k.split('/', 1)[1]: v / 1000 for k, v in idle['temp'].items()})
        print(' busy cores:', len(busy))
    (ROOT / 'evidence' / 'profile-summary.json').write_text(json.dumps(res, indent=1))
    print('\nwritten', ROOT / 'evidence' / 'profile-summary.json')

if __name__ == '__main__':
    main()
