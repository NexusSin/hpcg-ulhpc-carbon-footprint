#!/usr/bin/env python3
"""jobprint: the carbon footprint of a SLURM job, step by step.

    python3 jobprint.py JOBID              reads the job's record with sacct
    python3 jobprint.py --record FILE      reads a saved record instead (no cluster needed)

For every step of the job it prints the time the step held its nodes, the energy
the scheduler recorded, and the footprint in gCO2e in three terms:

    node     = E_IT [kWh] * grid                       the node's electricity
    site     = E_IT [kWh] * (PUE - 1) * grid           cooling and power distribution
    embodied = C_emb * nodes * t / T_alloc             the node's manufacture, charged
                                                       by the time the step holds it
then the share of each term, and the reserved cores and memory the job left
unused. The energy comes from the step's usage record (TRESUsageInTot), which
SLURM fills even when its ConsumedEnergyRaw field comes out near zero, and from
ConsumedEnergyRaw otherwise. If the recorded energy is missing or implies less
than 20 W per node, the tool estimates step energy from elapsed time, node count
and rated processor power per node. An asterisk marks each such estimate.

A saved record is the output of
    sacct -j JOBID -P -o JobID,JobName,Cluster,NodeList,NNodes,ElapsedRaw,ConsumedEnergyRaw,AllocTRES,TRESUsageInTot,State
Python 3.6 or newer, standard library only.
"""
import re, subprocess, sys

FIELDS = 'JobID,JobName,Cluster,NodeList,NNodes,ElapsedRaw,ConsumedEnergyRaw,AllocTRES,TRESUsageInTot,State'
YEAR = 365.25 * 86400
GRID = 108.42   # gCO2/kWh, Luxembourg supply mix 2025 (ILR, Regulation ILR/E26/14)
MIN_W = 20      # a node draws more than this whenever it is on: a lower record is a gap

# Per node: PUE of the room, embodied gCO2e outside use, years in service,
# share of the cluster allocated to jobs, rated power of the processors (W),
# cores and memory (GiB). Change these for another site.
SITES = {
    'iris': dict(pue=1.63, emb=1256e3, life=8.8, alloc=0.3294, tdp=280, cores=28, mem=128),
    'aion': dict(pue=1.10, emb=1200e3, life=4.9, alloc=0.5437, tdp=560, cores=128, mem=256),
}

def tres(s):
    """'cpu=28,mem=112G,energy=59000' -> dict, memory in GiB, cpu time in seconds."""
    out = {}
    for part in filter(None, (s or '').split(',')):
        k, _, v = part.partition('=')
        m = re.match(r'^([\d.]+)([KMGT]?)$', v)
        if k == 'mem' and m:
            out[k] = float(m.group(1)) * {'': 1 / 2**30, 'K': 1 / 2**20, 'M': 1 / 2**10, 'G': 1, 'T': 2**10}[m.group(2)]
        elif k == 'cpu' and ':' in v:
            d, _, hms = v.rpartition('-')
            parts = [float(x) for x in hms.split(':')]
            while len(parts) < 3:
                parts.insert(0, 0.0)
            out[k] = (float(d) * 86400 if d else 0) + parts[0] * 3600 + parts[1] * 60 + parts[2]
        elif m:
            out[k] = float(m.group(1))
    return out

def read(lines):
    rows = [l.rstrip('\n').split('|') for l in lines if l.strip()]
    head = rows[0] if rows and rows[0][0] == 'JobID' else FIELDS.split(',')
    return [dict(zip(head, r)) for r in rows if r[0] != 'JobID']

def main():
    if len(sys.argv) == 3 and sys.argv[1] == '--record':
        recs = read(open(sys.argv[2]))
    elif len(sys.argv) == 2 and re.match(r'^\d+$', sys.argv[1]):
        out = subprocess.run(['sacct', '-j', sys.argv[1], '-P', '-o', FIELDS],
                             stdout=subprocess.PIPE, universal_newlines=True, check=True).stdout
        recs = read(out.splitlines())
    else:
        sys.exit(__doc__)
    job = next(r for r in recs if '.' not in r['JobID'])
    cluster = (job.get('Cluster') or job.get('NodeList', '').split('-')[0]).lower()
    site = SITES.get(cluster)
    if site is None:
        sys.exit('no factors for cluster %r: add it to SITES' % cluster)
    alloc = tres(job['AllocTRES'])
    print('job %s on %s, %s node(s): %s cores and %.0f GiB reserved'
          % (job['JobID'], cluster, job.get('NNodes') or 1, int(alloc.get('cpu', 0)), alloc.get('mem', 0)))
    print('factors: grid %.2f g/kWh, PUE %.2f, embodied %.0f kg per node over %.2f allocated years'
          % (GRID, site['pue'], site['emb'] / 1e3, site['life'] * site['alloc']))
    print('%-10s %-12s %8s %9s %9s %9s %9s %9s' % ('step', 'name', 'time s', 'energy kJ', 'node g', 'site g', 'embod. g', 'total g'))
    tot = [0.0, 0.0, 0.0]; estimated = False; used_mem = used_cpu = 0.0
    measured = []                                      # totals of the steps with a real energy record
    for r in recs:
        if not re.match(r'^\d+\.\d+$', r['JobID']):
            continue                                   # numbered steps only: no batch or extern
        t, n = float(r.get('ElapsedRaw') or 0), int(r.get('NNodes') or 1)
        use = tres(r.get('TRESUsageInTot'))
        # the step's usage record carries the energy too, and SLURM fills it even
        # when ConsumedEnergyRaw comes out near zero: prefer it when present
        e = use.get('energy') or float(r.get('ConsumedEnergyRaw') or 0)
        flag = ''
        if t and e / (n * t) < MIN_W:                  # nothing, or too little to be real: rated power
            e, flag, estimated = site['tdp'] * n * t, '*', True
        kwh = e / 3.6e6
        g = [kwh * GRID, kwh * (site['pue'] - 1) * GRID, site['emb'] * n * t / (site['life'] * site['alloc'] * YEAR)]
        tot = [a + b for a, b in zip(tot, g)]
        if not flag:
            measured.append(sum(g))
        used_mem = max(used_mem, use.get('mem', 0)); used_cpu = max(used_cpu, use.get('cpu', 0) / t if t else 0)
        print('%-10s %-12s %8.0f %9.1f%s %8.3f %9.3f %9.3f %9.3f' % (r['JobID'], (r.get('JobName') or '')[:12], t, e / 1e3, flag, g[0], g[1], g[2], sum(g)))
    total = sum(tot)
    if not total:
        sys.exit('no numbered steps in this record')
    steps = sum(1 for r in recs if re.match(r'^\d+\.\d+$', r['JobID']))
    print('total %.2f gCO2e over %d step(s), %.2f per step: node %.0f %%, site %.0f %%, manufacture %.0f %%'
          % (total, steps, total / steps, 100 * tot[0] / total, 100 * tot[1] / total, 100 * tot[2] / total))
    if measured:
        print('steps with recorded energy: %d, %.2f gCO2e per step on average' % (len(measured), sum(measured) / len(measured)))
    if estimated:
        print('* energy estimated from rated processor power, node count and elapsed time '
              'because scheduler energy was missing or implied less than %d W per node' % MIN_W)
    hot = max(range(3), key=lambda i: tot[i])
    print('hotspot: %s' % ['the node\'s electricity', 'the site overhead (PUE)', 'the node\'s manufacture'][hot])
    if alloc.get('cpu') and used_cpu < 0.5 * alloc['cpu']:
        print('lever: the busiest step averaged %.0f busy cores out of %d reserved' % (used_cpu, alloc['cpu']))
    if alloc.get('mem') and used_mem < 0.5 * alloc['mem']:
        print('lever: at most %.0f of %.0f GiB of reserved memory was touched' % (used_mem, alloc['mem']))
    if hot == 2:
        print('lever: manufacture is charged by the time the job holds its nodes; a faster build of the code shortens it')

if __name__ == '__main__':
    main()
