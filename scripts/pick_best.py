#!/usr/bin/env python3
"""Green IT 2026 - Section IV: choose the configuration that phase 2 of
scripts/hpcg_opt.sbatch runs 100 times, from the screening rounds of phase 1.

The rule is the one of Section IV-A, applied exactly as scripts/v1_numbers.py
applies it, and the footprint is computed with scripts/pool_runs.py: a
configuration is kept only if HPCG validated every one of its runs, every run did
at least the baseline's number of iterations, and its footprint was lower than the
baseline of the same round in every round. Among those, the largest mean saving
wins. Prints the configuration's name, or 'none'; the comparison goes to stderr.

Reads only snapshots.jsonl and the HPCG reports, never samples.jsonl, which the
sampler is still writing while the job runs. Runs on /usr/bin/python3 (3.6).

usage: pick_best.py RUN_ROOT iris|aion NUMBER_OF_CONFIGURATIONS
"""
import json, re, sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pool_runs as P


def load(root, cluster):
    snaps = {}
    for line in open(str(root / 'snapshots.jsonl')):
        try:
            s = json.loads(line)
        except ValueError:
            continue
        snaps[s['label']] = s
    rows = []
    for lab, a in snaps.items():
        m = re.match(r'^run(\d+)_(\w+?)_start$', lab)
        b = snaps.get(lab.replace('_start', '_end'))
        if not m or b is None:
            continue
        n, v = int(m.group(1)), m.group(2)
        r = P.report(str(root / ('run-%03d-%s' % (n, v)) / 'HPCG-Benchmark*.txt'))
        if not r or r['rating'] != r['rating']:
            continue                                   # no report: the run failed
        x = dict(cluster=cluster, run=n, variant=v, seconds=b['t'] - a['t'], **r)
        x['it_J'] = P.rapl_delta(a, b, 'package') + (P.rapl_delta(a, b, 'dram') if cluster == 'IRIS' else 0.0)
        x['g_total'] = sum(P.grams(x))
        rows.append(x)
    return rows


def rule_of(root):
    """'greener' (default): the rule above. 'faster': also a higher HPCG rating than
    the baseline of the same round in every round. Set by the file keep-rule.txt in
    the allocation's results folder, which can be written while the job runs, up to
    the end of the screening rounds."""
    f = Path(str(root)) / 'keep-rule.txt'
    return f.read_text().strip() if f.exists() and f.read_text().strip() in ('greener', 'faster') else 'greener'


def pick(rows, ncfg, rule='greener'):
    for x in rows:
        x['round'] = (x['run'] - 1) // ncfg
    by = {}
    for x in rows:
        by.setdefault(x['variant'], []).append(x)
    ref = by.get('ref', [])
    if not ref:
        return None, []
    rr = {x['round']: x for x in ref}
    base_it = min(x['iters'] for x in ref)
    table, best = [], None
    for v, sub in sorted(by.items()):
        if v == 'ref':
            continue
        d = [x['g_total'] - rr[x['round']]['g_total'] for x in sub if x['round'] in rr]
        ok = (len(d) == len(rr) and all(x['valid'] for x in sub)
              and all(x['iters'] >= base_it for x in sub) and all(q < 0 for q in d))
        if rule == 'faster':
            ok = ok and all(x['rating'] > rr[x['round']]['rating'] for x in sub if x['round'] in rr)
        save = mean(x['g_total'] for x in ref) - mean(x['g_total'] for x in sub)
        table.append((v, len(sub), sum(q < 0 for q in d), min(x['iters'] for x in sub), save, ok))
        if ok and (best is None or save > best[1]):
            best = (v, save)
    return best, table


if __name__ == '__main__':
    root, cluster, ncfg = Path(sys.argv[1]), {'iris': 'IRIS', 'aion': 'Aion'}[sys.argv[2]], int(sys.argv[3])
    rule = rule_of(root)
    sys.stderr.write('rule: %s\n' % rule)
    best, table = pick(load(root, cluster), ncfg, rule)
    for v, n, lower, it, save, ok in table:
        sys.stderr.write('%-10s runs %2d  lower in %2d  min iterations %4d  mean saving %+.4f g  %s\n'
                         % (v, n, lower, it, save, 'passes' if ok else 'fails'))
    print(best[0] if best else 'none')
