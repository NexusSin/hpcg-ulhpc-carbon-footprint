#!/usr/bin/env python3
"""Compute every figure of the paper v1 (D1) and write it as LaTeX.

    python3 scripts/v1_numbers.py

writes paper/src/v1-numbers.tex (one \\newcommand per figure, used in the text)
and paper/src/v1-tables.tex (the data tables of Appendix A). Rerun it after new
runs land in results/, then rebuild with latexmk; nothing in the text needs
retyping. Inputs: the run records read by scripts/pool_runs.py, the published output-token
totals used in the carbon payback calculation, and
results/evidence/hpcg-frequency.txt (HPCG jobs per year, from sacct).
Node names and job IDs are deliberately not written: the paper is reviewed
double-blind, and on these clusters a job ID identifies its owner.
"""
import json, math, re, statistics as st, sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pool_runs as P

ROOT = Path(__file__).resolve().parent.parent
RES_DIR = {'IRIS': ROOT / 'results/hundred-iris-6151479', 'Aion': ROOT / 'results/hundred-aion-16077963'}
OUT_NUM = ROOT / 'paper/src/v1-numbers.tex'
OUT_TAB = ROOT / 'paper/src/v1-tables.tex'
WH_PER_KTOK = 1.03                     # course factor, Wh per 1000 output tokens
LED_W, CAR_G_KM, RESIDENT_G_DAY = 5, 291, 28_000   # Session 2 comparators
ALT_GRID = {'Ember': 123, 'EU': 209}   # g/kWh, the sensitivity values (Session 2)
CL = {'IRIS': 'Iris', 'Aion': 'Aion'}

def sig(x, n=2):
    """x to n significant digits, as text with thin-space thousands."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 'n/a'
    if x == 0:
        return '0'
    d = n - 1 - int(math.floor(math.log10(abs(x))))
    v = round(x, d)
    s = f'{v:.{max(d, 0)}f}'
    return thou(s)

def fix(x, d=1):
    return thou(f'{x:.{d}f}')

def thou(s):
    neg = s.startswith('-'); s = s.lstrip('-')
    whole, _, frac = s.partition('.')
    if len(whole) >= 4:
        whole = re.sub(r'(?<=\d)(?=(\d{3})+$)', r'\\,', whole)
    return ('$-$' if neg else '') + whole + ('.' + frac if frac else '')

def pct(x, d=0):
    return fix(100 * x, d) + '\\,\\%'

macros = {}
def M(name, value):
    assert re.fullmatch(r'[A-Za-z]+', name), name
    macros[name] = value

# --- runs ---------------------------------------------------------------------
rows = P.load()
for x in rows:
    x['g_node'], x['g_site'], x['g_emb'] = P.grams(x)
    x['g_total'] = x['g_node'] + x['g_site'] + x['g_emb']
    x['dates'] = None

def mean(v): return st.mean(v)
def sd(v): return st.stdev(v) if len(v) > 1 else 0.0

node_label = {}
pooled = {}
# declared factors: known before any run
for cluster, pre in CL.items():
    s_ = P.SITE[cluster]
    M(pre + 'Alloc', pct(s_['alloc'], 2)); M(pre + 'Life', fix(s_['life'], 1))
    M(pre + 'Talloc', fix(s_['life'] * s_['alloc'], 2))
    M(pre + 'EmbKg', thou(f"{s_['emb']/1000:.0f}"))
    M(pre + 'Pue', f"{s_['pue']:.2f}".rstrip('0') if s_['pue'] == 1.1 else f"{s_['pue']:.2f}")
    M(pre + 'Tdp', str(s_['tdp']))
    M(pre + 'Wue', {'IRIS': '0.193', 'Aion': '0.413'}[cluster])
    for nm, pue in {'IRIS': (('Low', 1.43), ('High', 1.83)), 'Aion': (('Low', 1.00), ('High', 1.55))}[cluster]:
        M(pre + 'Pue' + nm, f'{pue:.2f}')
for cluster, pre in CL.items():
    ref = [x for x in rows if x['cluster'] == cluster and x['variant'] == 'ref']
    if not ref:
        continue                                  # no runs yet: placeholders below
    nodes = list(dict.fromkeys(x['node'] for x in ref))
    for i, n in enumerate(nodes):
        node_label[(cluster, n)] = 'ABCDEFGH'[i]
    g = lambda k: [x[k] for x in ref]
    pooled[cluster] = dict(ref=ref, nodes=nodes)
    M(pre + 'Runs', str(len(ref))); M(pre + 'Nodes', str(len(nodes)))
    output_bytes = []
    for run in ref:
        folder = P.RES / f"hundred-{cluster.lower()}-{run['job']}" / f"run-{run['run']:03d}-ref"
        output_bytes.append(sum(f.stat().st_size for f in folder.glob('*.txt')))
    M(pre + 'OutputKB', fix(mean(output_bytes) / 1000, 2))
    M(pre + 'Time', fix(mean(g('seconds')), 0)); M(pre + 'TimeSd', fix(sd(g('seconds')), 0))
    M(pre + 'Energy', fix(mean(g('it_J')) / 1e3, 1)); M(pre + 'EnergySd', fix(sd(g('it_J')) / 1e3, 1))
    M(pre + 'EnergyWh', fix(mean(g('it_J')) / 3600, 1))
    M(pre + 'Rating', fix(mean(g('rating')), 1))
    M(pre + 'Power', fix(mean([x['it_J'] / x['seconds'] for x in ref]), 0))
    split = [x for x in ref if x.get('pkg_J') is not None]
    M(pre + 'Pkg', fix(mean([x['pkg_J'] for x in split]) / 1e3, 1))
    M(pre + 'PkgShareRuns', str(len(split)))
    if cluster == 'IRIS':
        M(pre + 'Dram', fix(mean([x['dram_J'] for x in split]) / 1e3, 1))
    tot = g('g_total')
    M(pre + 'Grams', sig(mean(tot))); M(pre + 'GramsSd', sig(sd(tot), 1))
    M(pre + 'GramsThree', sig(mean(tot), 3))
    M(pre + 'GramsRunMin', sig(min(tot), 3)); M(pre + 'GramsRunMax', sig(max(tot), 3))
    for k, nm in (('g_node', 'Node'), ('g_site', 'Site'), ('g_emb', 'Emb')):
        M(pre + 'G' + nm, sig(mean(g(k))))
        M(pre + 'Share' + nm, pct(mean(g(k)) / mean(tot)))
    # embodied versus operational: the ratio the interpretation asks for
    gop = mean([x['g_node'] + x['g_site'] for x in ref])
    M(pre + 'GOp', sig(gop)); M(pre + 'ShareOp', pct(gop / mean(tot)))
    M(pre + 'EmbOpRatio', fix(mean(g('g_emb')) / gop, 1))
    for name, gfac in ALT_GRID.items():
        M(pre + 'EmbOpRatio' + name, fix(mean(g('g_emb')) / (gop * gfac / P.GRID), 1))
    per_node = [mean([x['g_total'] for x in ref if x['node'] == n]) for n in nodes]
    M(pre + 'GramsNodeMin', sig(min(per_node), 3)); M(pre + 'GramsNodeMax', sig(max(per_node), 3))
    tn = [mean([x['seconds'] for x in ref if x['node'] == n]) for n in nodes]
    M(pre + 'TimeNodeMin', fix(min(tn), 0)); M(pre + 'TimeNodeMax', fix(max(tn), 0))
    within = max((max(v) - min(v)) / mean(v) for v in
                 ([x['it_J'] for x in ref if x['node'] == n] for n in nodes) if len(v) > 1)
    M(pre + 'WithinNodeSpread', pct(within, 1))
    M(pre + 'NodeSpread', pct((max(per_node) - min(per_node)) / mean(tot), 0))
    # comparators, at the declared grid factor
    led_g = LED_W / 1000 * P.GRID
    M(pre + 'LedHours', sig(mean(tot) / led_g)); M('LedGrams', sig(led_g))
    M(pre + 'CarMetres', sig(mean(tot) / CAR_G_KM * 1000))
    M(pre + 'ResidentShare', sig(100 * mean(tot) / RESIDENT_G_DAY) + '\\,\\%')
    # top-down check: rated power of the two processors times the run time
    s = P.SITE[cluster]
    pk = [x for x in split]
    top = mean([s['tdp'] * x['seconds'] for x in pk])
    M(pre + 'TopDown', fix(top / 1e3, 1)); M(pre + 'Tdp', str(s['tdp']))
    M(pre + 'PkgOverTop', pct(mean([x['pkg_J'] for x in pk]) / top))
    # Whole-run emissions per GFLOP reported for HPCG's timed phase.
    M(pre + 'MgPerGflop', sig(mean([x['g_total'] * 1e12 / x['flop'] for x in ref])))
    for name, gfac in ALT_GRID.items():
        alt = mean([(x['g_node'] + x['g_site']) * gfac / P.GRID + x['g_emb'] for x in ref])
        M(pre + 'Grams' + name, sig(alt))
    nodeonly = mean([x['g_node'] + x['g_emb'] for x in ref])
    M(pre + 'GramsNoSite', sig(nodeonly))
    # component readings of the instrumented runs
    inst = [x for x in ref if x.get('ib_out') is not None]
    M(pre + 'InstRuns', str(len(inst)))
    rng = lambda k, f, d: f'{fix(min(f(x[k]) for x in inst), d)}--{fix(max(f(x[k]) for x in inst), d)}'
    M(pre + 'IbOut', rng('ib_out', lambda v: v / 1e6, 0)); M(pre + 'IbIn', rng('ib_in', lambda v: v / 1e6, 0))
    M(pre + 'DiskW', rng('disk_w', lambda v: v / 1e6, 1))
    M(pre + 'Busy', fix(100 * mean([x['busy'] for x in inst]), 1) + '\\,\\%')
    M(pre + 'Clock', fix(mean([x['clock'] for x in inst]) / 1000, 1))
    M(pre + 'Hot', fix(max(x['hot'] for x in inst), 0))
    # water, per kWh of IT energy by size class (EC 2025, Figure 12)
    wue = {'IRIS': 0.193, 'Aion': 0.413}[cluster]
    M(pre + 'Wue', f'{wue:.3f}'); M(pre + 'Water', fix(mean(g('it_J')) / 3.6e6 * wue * 1000, 1))
    # PUE sensitivity
    for nm, pue in {'IRIS': (('Low', 1.43), ('High', 1.83)), 'Aion': (('Low', 1.00), ('High', 1.55))}[cluster]:
        alt = mean([x['g_node'] + x['g_site'] * (pue - 1) / (s['pue'] - 1) + x['g_emb'] for x in ref])
        M(pre + 'Pue' + nm, f'{pue:.2f}'); M(pre + 'GramsPue' + nm, sig(alt))
    M(pre + 'Alloc', pct(s['alloc'], 2)); M(pre + 'Life', fix(s['life'], 1))
    M(pre + 'Talloc', fix(s['life'] * s['alloc'], 2))
    M(pre + 'EmbKg', thou(f"{s['emb']/1000:.0f}")); M(pre + 'Pue', f"{s['pue']:.2f}".rstrip('0') if s['pue'] == 1.1 else f"{s['pue']:.2f}")

M('Grid', f'{P.GRID:.2f}'); M('GridRound', fix(P.GRID, 0))
M('LedGrams', sig(LED_W / 1000 * P.GRID))
both = 'IRIS' in pooled and 'Aion' in pooled
ir, ai = (pooled['IRIS']['ref'], pooled['Aion']['ref']) if both else ([], [])
if both:
  d_tot = mean([x['g_total'] for x in ir]) - mean([x['g_total'] for x in ai])
  for k, nm in (('g_node', 'Node'), ('g_site', 'Site'), ('g_emb', 'Emb')):
    dk = mean([x[k] for x in ir]) - mean([x[k] for x in ai])
    M('Gap' + nm, sig(dk)); M('GapShare' + nm, pct(dk / d_tot))
  M('Gap', sig(d_tot))
  M('GapRatio', fix(mean([x['g_total'] for x in ir]) / mean([x['g_total'] for x in ai]), 1))
  for name, gfac in ALT_GRID.items():
    alt = lambda v: mean([(x['g_node'] + x['g_site']) * gfac / P.GRID + x['g_emb'] for x in v])
    M('GapRatio' + name, fix(alt(ir) / alt(ai), 1))
  M('GapRatioWork', fix(mean([x['g_total'] / x['flop'] for x in ir]) /
                        mean([x['g_total'] / x['flop'] for x in ai]), 1))

# --- what the two checks asked to be sized (2026-10-27) ------------------------------
if both:
    gi = {k: mean([x[k] for x in ir]) for k in ('g_node', 'g_site', 'g_emb', 'seconds', 'rating', 'dram_J', 'pkg_J')}
    ga = {k: mean([x[k] for x in ai]) for k in ('g_node', 'g_site', 'g_emb', 'seconds', 'rating')}
    pi0, pa0 = P.SITE['IRIS']['pue'], P.SITE['Aion']['pue']
    tot = lambda g, pue, pue0: g['g_node'] + g['g_site'] * (pue - 1) / (pue0 - 1) + g['g_emb']
    site = lambda g, pue, pue0: g['g_site'] * (pue - 1) / (pue0 - 1)
    shares, saves = [], []
    for pi in (1.43, pi0, 1.83):
        for pa in (1.00, pa0, 1.55):
            ti, ta = tot(gi, pi, pi0), tot(ga, pa, pa0)
            shares.append((site(gi, pi, pi0) - site(ga, pa, pa0)) / (ti - ta)); saves.append(1 - ta / ti)
    M('GapShareSiteMin', pct(min(shares))); M('GapShareSiteMax', pct(max(shares)))
    M('AionSave', pct(1 - tot(ga, pa0, pa0) / tot(gi, pi0, pi0)))
    M('AionSaveMin', pct(min(saves))); M('AionSaveMax', pct(max(saves)))
    # IRIS's memory energy, which Aion cannot report
    gmem = gi['dram_J'] / 3.6e6 * P.GRID * pi0
    gap = tot(gi, pi0, pi0) - tot(ga, pa0, pa0)
    M('IrisMemGrams', sig(gmem)); M('IrisMemGapShare', pct(gmem / gap))
    M('IrisGramsPkgOnly', sig(tot(gi, pi0, pi0) - gmem)); M('GapRatioPkgOnly', fix((tot(gi, pi0, pi0) - gmem) / tot(ga, pa0, pa0), 1))
    # Dell's stated standard deviation, applied to the manufacture term
    M('IrisEmbSdGrams', sig(gi['g_emb'] * 6410 / 6510))
    # per unit of work: per second of node time, and the ratings
    M('PerSecondRatio', fix((tot(gi, pi0, pi0) / gi['seconds']) / (tot(ga, pa0, pa0) / ga['seconds']), 1))
    M('RatingRatio', fix(ga['rating'] / gi['rating'], 1))
    flop = lambda v: mean([x['flop'] for x in v]) / 1e9
    M('GapRatioWorkTimed', fix((tot(gi, pi0, pi0) / flop(ir)) / (tot(ga, pa0, pa0) / flop(ai)), 1))
    # the measurement itself: all runs of Section III
    M('MeasureKg', fix(sum(x['g_total'] for x in ir + ai) / 1000, 2))

# --- how much nodes of one cluster differ: the project's earlier, shorter sets on other
# nodes (same commit and input) together with the 100-run node -------------------------
for cluster, pre in CL.items():
    per_node = {}
    for x in P.load(old=True):
        if x['cluster'] == cluster and x['variant'] == 'ref' and x.get('it_J'):
            per_node.setdefault(x['node'], []).append(sum(P.grams(x)))
    if len(per_node) > 1:
        nm = [mean(v) for v in per_node.values()]
        M(pre + 'NodeCount', str(len(nm)))
        M(pre + 'NodeGramsMin', sig(min(nm), 2)); M(pre + 'NodeGramsMax', sig(max(nm), 2))

# --- Section IV: the optimisation runs. Every configuration is compared with the
# baseline build run in the same allocation (same node), round by round. Each
# allocation's configurations are read from its job log. On each cluster, the
# allocation that tests the compiler flags (it has o2) gives the flag and clock
# results; on Aion a second allocation tests the placement of the processes. The
# allocation that ran phase 2 (100 runs of the kept configuration) decides what is
# kept, with the rule of scripts/pick_best.py, which the job itself applied. ----------
sys.path.insert(0, str(ROOT / 'scripts'))
import pick_best as PB

CAPS = {'IRIS': ('2.6', '2.0'), 'Aion': ('2.0', '1.5')}
LBL = {'IRIS': {'ref': 'Ref', 'o2': 'Otwo', 'native': 'Native', 'f26': 'CapA', 'f20': 'CapB'},
       'Aion': {'ref': 'Ref', 'o2': 'Otwo', 'native': 'Native', 'f20': 'CapA', 'f15': 'CapB',
                'spread': 'Spread', 'spread20': 'SpreadCap'}}
CFG = {c: [(v, T) for v, T in LBL[c].items()] for c in LBL}       # for the text below

def spct(x, d=1):
    return ('+' if x > 0 else '') + pct(x, d)

def configs_of(job):
    out = ROOT / 'results' / f'hpcg-opt-{job}.out'
    m = re.search(r'configs \[([^\]]*)\]', out.read_text()) if out.exists() else None
    return [c.split('=')[0] for c in m.group(1).split()] if m else []

def enrich(runs, d, kind):
    runs = [x for x in runs if x.get('rating') is not None and x['rating'] == x['rating']]
    for x in runs:
        x['it_J'] = x['pkg_J'] + (x['dram_J'] or 0)
        x['g_node'], x['g_site'], x['g_emb'] = P.grams(x)
        x['g_op'] = x['g_node'] + x['g_site']
        x['g_total'] = x['g_op'] + x['g_emb']
        x['power'] = x['it_J'] / x['seconds']
    return runs

def analyse(d, cluster, pre):
    """Macros pre+<config>+<quantity> for one allocation; returns its runs, grouped."""
    job = d.name.rsplit('-', 1)[1]
    names = configs_of(job)
    after = enrich(P.from_snapshots(cluster, d.name, job, d, r'^after(\d+)_(\w+?)_start$',
                                    lambda m: (int(m.group(1)), m.group(2), f'after-{int(m.group(1)):03d}-{m.group(2)}')), d, 'after')
    if 'ref' not in names:            # only the runs of a configuration chosen before
        return dict(d=d, job=job, names=names, by={}, runs=[], dropped=[], after=after, ref=[], best=None, pre=pre) if after else None
    runs = enrich(P.from_snapshots(cluster, d.name, job, d, r'^run(\d+)_(\w+?)_start$',
                                   lambda m: (int(m.group(1)), m.group(2), f'run-{int(m.group(1)):03d}-{m.group(2)}')), d, 'run')
    ncfg = len(names)
    for x in runs:
        x['round'] = (x['run'] - 1) // ncfg
    # Rounds left out of every comparison: listed, counting from 1, in left-out-rounds.txt
    # in the allocation's folder, with the reason. Their runs still count in the cost.
    lf = d / 'left-out-rounds.txt'
    skip = {int(t) - 1 for t in re.findall(r'^\s*(\d+)', lf.read_text(), re.M)} if lf.exists() else set()
    dropped = [x for x in runs if x['round'] in skip]
    runs = [x for x in runs if x['round'] not in skip]
    by = {v: [x for x in runs if x['variant'] == v] for v in names}
    ref = by['ref']
    if not ref:
        return None
    refround = {x['round']: x for x in ref}
    base_it = min(x['iters'] for x in ref)
    mm = lambda v, k: mean([x[k] for x in v])
    M(pre + 'OptRuns', str(len(runs) + len(dropped) + len(after)))
    M(pre + 'OptRounds', str(len({x['round'] for x in runs + dropped if x['variant'] == 'ref'})))
    M(pre + 'OptCampaignGrams', sig(sum(x['g_total'] for x in runs + dropped + after)))
    M(pre + 'RefGramsOpt', sig(mm(ref, 'g_total'), 3))
    for v in names:
        sub, T = by[v], LBL[cluster].get(v, v.capitalize())
        if not sub:
            continue
        M(pre + T + 'N', str(len(sub)))
        M(pre + T + 'Time', fix(mm(sub, 'seconds'), 1)); M(pre + T + 'Energy', fix(mm(sub, 'it_J') / 1e3, 1))
        M(pre + T + 'Power', fix(mm(sub, 'power'), 0)); M(pre + T + 'Clock', fix(mm(sub, 'clock') / 1000, 1))
        M(pre + T + 'Timed', fix(mm(sub, 'timed'), 1))
        M(pre + T + 'Rating', fix(mm(sub, 'rating'), 1)); M(pre + T + 'Grams', sig(mm(sub, 'g_total'), 3))
        M(pre + T + 'Iters', '/'.join(sorted({str(x['iters']) for x in sub})))
        M(pre + T + 'Valid', 'all' if all(x['valid'] for x in sub) else f"{sum(x['valid'] for x in sub)} of {len(sub)}")
        if v == 'ref':
            continue
        rel = lambda k: (mm(sub, k) - mm(ref, k)) / mm(ref, k)
        for k, nm in (('seconds', 'Time'), ('it_J', 'Energy'), ('rating', 'Rating'), ('g_total', 'Grams'),
                      ('g_op', 'Op'), ('g_emb', 'Emb'), ('power', 'Power'), ('timed', 'Timed')):
            M(pre + T + nm + 'Pct', spct(rel(k)))
        # Relative change in grams per floating-point operation of the timed phase.
        M(pre + T + 'PerWorkPct', spct((mean([x['g_total'] / x['flop'] for x in sub]) - mean([x['g_total'] / x['flop'] for x in ref]))
                                       / mean([x['g_total'] / x['flop'] for x in ref])))
        M(pre + T + 'RestPct', spct((mean([x['seconds'] - x['timed'] for x in sub]) - mean([x['seconds'] - x['timed'] for x in ref]))
                                   / mean([x['seconds'] - x['timed'] for x in ref])))
        diffs = [x['g_total'] - refround[x['round']]['g_total'] for x in sub if x['round'] in refround]
        M(pre + T + 'Lower', f"{sum(1 for q in diffs if q < 0)} of {len(diffs)}")
        M(pre + T + 'SameWork', 'yes' if all(x['iters'] >= base_it for x in sub) else 'no')
        M(pre + T + 'Save', sig(mm(ref, 'g_total') - mm(sub, 'g_total'), 2))
    best, _ = PB.pick(runs, ncfg, PB.rule_of(d))
    log = (ROOT / 'results' / f'hpcg-opt-{job}.out')
    m = re.search(r'kept by the rule of Section IV-A: (\S+)', log.read_text()) if log.exists() else None
    if m and after and m.group(1) != (best[0] if best else 'none'):
        print(f'WARNING: job {job} kept {m.group(1)}, the analysis keeps {best}', file=sys.stderr)
    return dict(d=d, job=job, names=names, by=by, runs=runs, dropped=dropped, after=after, ref=ref, best=best, pre=pre)

ALLOC = {}                                       # cluster -> list of analysed allocations
for d in sorted((ROOT / 'results').glob('opt-*-*')):
    if (d / 'snapshots.jsonl').exists():
        cluster = 'IRIS' if '-iris-' in d.name else 'Aion'
        names = configs_of(d.name.rsplit('-', 1)[1])
        # 'Pl': Aion's placement allocations; the flags allocation and IRIS's cap
        # allocation (ref and f26 only) write the plain cluster prefix
        pre = CL[cluster] + ('Pl' if any(n.startswith('spread') for n in names) else '')
        a = analyse(d, cluster, pre)
        if a:
            ALLOC.setdefault(cluster, []).append(a)

opt, keep = {}, {}
for cluster, pre in CL.items():
    caphi, caplo = CAPS[cluster]
    M(pre + 'CapA', caphi); M(pre + 'CapB', caplo)
    al = ALLOC.get(cluster, [])
    main = [a for a in al if 'o2' in a['names']]
    if main:
        opt[cluster] = main[0]
    plc = [a for a in al if 'spread' in a['names']]
    if plc:
        opt[cluster + 'Pl'] = plc[0]
    # The comparison: the 100 runs of Section III against the 100 runs of the change
    # kept. The change is the one the 100 runs ran; the rounds of the allocation that
    # tested it against the baseline on one node are the evidence for choosing it.
    NAME = {'Otwo': '\\texttt{-O2}', 'Native': '\\texttt{-march=native}',
            'CapA': f'the {caphi}\\,GHz clock cap', 'CapB': f'the {caplo}\\,GHz clock cap',
            'Spread': 'one process per L3 cache', 'SpreadCap': 'one process per L3 cache with the 2.0\\,GHz cap'}
    aft_al = [a for a in al if a['after']]
    scr = [a for a in al if a['ref']]
    if aft_al:
        A = aft_al[-1]; v = A['after'][0]['variant']
    else:
        best_a = [a for a in scr if a['best']]
        A = None; v = max(best_a, key=lambda a: a['best'][1])['best'][0] if best_a else None
    src = ([a for a in scr if a['by'].get(v)] or [None])[-1] if v else None
    if not al:
        continue
    k = keep[cluster] = dict(A=A, src=src, bestv=v, after=A['after'] if A else [], save=0.0, best=v)
    if v is None:
        M(pre + 'BestName', 'none of the configurations'); M(pre + 'BestSave', '0'); M(pre + 'BestSavePct', '0\\,\\%')
        continue
    T = LBL[cluster].get(v, v)
    M(pre + 'BestName', NAME[T]); k['bestT'] = T
    if src:                                   # the paired evidence, round by round on one node
        ref = src['ref']; sub = src['by'][v]; rr = {x['round']: x for x in ref}
        d_ = [x['g_total'] - rr[x['round']]['g_total'] for x in sub if x['round'] in rr]
        r0 = mean([x['g_total'] for x in ref])
        M(pre + 'PairedSave', sig(-mean(d_), 2)); M(pre + 'PairedSavePct', pct(-mean(d_) / r0, 1))
        M(pre + 'PairedLower', f"{sum(q < 0 for q in d_)} of {len(d_)}"); M(pre + 'PairedRounds', str(len(d_)))
        k['save'] = -mean(d_)
    base = mean([x['g_total'] for x in pooled[cluster]['ref']]) if cluster in pooled else None
    aft = k['after']
    if aft and base:
        g = [x['g_total'] for x in aft]
        # what the 100 runs are compared with: the unchanged job on the same node when the
        # allocation ran it (IRIS, whose nodes differ widely), else the 100 runs of Section III
        same = A['ref'] if A and len(A['ref']) >= 5 else None
        cmp_ = same or pooled[cluster]['ref']
        c0 = mean([x['g_total'] for x in cmp_])
        k['save'] = c0 - mean(g); k['cmp_same_node'] = bool(same)
        M(pre + 'CmpWhat', (f"the {len(same)} runs of the unchanged job on the same node" if same
                            else f"the {len(cmp_)} runs of the unchanged job in Section~\\ref{{sec:lcia}}"))
        M(pre + 'CmpN', str(len(cmp_))); M(pre + 'CmpGrams', sig(c0, 3))
        M(pre + 'BestSave', sig(c0 - mean(g), 2)); M(pre + 'BestSavePct', pct((c0 - mean(g)) / c0, 1))
        M(pre + 'AftN', str(len(aft))); M(pre + 'HundredGrams', sig(base, 3))
        M(pre + 'AftGrams', sig(mean(g), 3)); M(pre + 'AftGramsSd', sig(st.stdev(g), 1) if len(g) > 1 else '0')
        M(pre + 'AftGramsMin', sig(min(g), 3)); M(pre + 'AftGramsMax', sig(max(g), 3))
        M(pre + 'AftVsHundred', spct((mean(g) - base) / base)); M(pre + 'AftVsCmp', spct((mean(g) - c0) / c0))
        if same:
            M(pre + 'SameNodeVsHundred', spct((c0 - base) / base))
            k['same_vs_base'] = (c0 - base) / base       # this node's unchanged runs against Section III's
        for key, nm, f_ in (('seconds', 'Time', lambda x: fix(x, 1)), ('it_J', 'Energy', lambda x: fix(x / 1e3, 1)),
                            ('rating', 'Rating', lambda x: fix(x, 1)), ('power', 'Power', lambda x: fix(x, 0))):
            val = lambda x: x[key] if key != 'power' else x['it_J'] / x['seconds']
            ma, mb = mean([val(x) for x in aft]), mean([val(x) for x in cmp_])
            M(pre + 'Aft' + nm, f_(ma)); M(pre + 'Cmp' + nm, f_(mb)); M(pre + 'Aft' + nm + 'Pct', spct((ma - mb) / mb))
        M(pre + 'AftIters', '/'.join(sorted({str(x['iters']) for x in aft})))
        M(pre + 'CmpIters', '/'.join(sorted({str(x['iters']) for x in cmp_})))
        k['work'] = ('same' if {x['iters'] for x in aft} == {x['iters'] for x in cmp_} else
                     'less' if min(x['iters'] for x in aft) < min(x['iters'] for x in cmp_) else 'more')
        M(pre + 'AftValid', 'all' if all(x['valid'] for x in aft) else f"{sum(x['valid'] for x in aft)} of {len(aft)}")
    elif src:
        M(pre + 'BestSave', macros[pre + 'PairedSave']); M(pre + 'BestSavePct', macros[pre + 'PairedSavePct'])
        if base:
            M(pre + 'AfterGrams', sig(base - k['save']))

# Recorded output-token totals for this study, as of 2026-11-10 07:25 UTC.
# The optimisation session is included in the project total. Section V uses
# these as alternative lower and upper estimates of the cost of assistance.
PROJECT_OUTPUT_TOKENS = 3_888_124
OPTIMISATION_OUTPUT_TOKENS = 418_649

def token_emissions_g(output_tokens):
    return output_tokens / 1000 * WH_PER_KTOK / 1000 * P.GRID

project_assistance_g = token_emissions_g(PROJECT_OUTPUT_TOKENS)
optimisation_assistance_g = token_emissions_g(OPTIMISATION_OUTPUT_TOKENS)
M('AssistOut', thou(str(PROJECT_OUTPUT_TOKENS)))
M('AssistGrams', sig(project_assistance_g))
M('AssistOptGrams', sig(optimisation_assistance_g))

# --- Section V: carbon payback ------------------------------------------------------
freq = {}
fp = ROOT / 'results/evidence/hpcg-frequency.txt'
if fp.exists():
    for line in open(fp):
        m = re.match(r'(\w+):.*?other_users_jobs=(\d+) other_users=(\d+)', line)
        if m:
            freq['IRIS' if m.group(1) == 'iris' else 'Aion'] = (int(m.group(2)), int(m.group(3)))
# Runs that failed at launch or were cut off when their allocation was stopped held the
# node too, so they count in the cost. A run with no end snapshot is charged up to the
# last sample of its allocation (every 2 s). Allocations stopped before they could test
# anything sit in results/aborted/.
def lost_runs(d, cluster, counted):
    snaps, last = {}, None
    for line in open(d / 'snapshots.jsonl'):
        try:
            s = json.loads(line)
        except ValueError:
            continue
        snaps[s['label']] = s
    if (d / 'samples.jsonl').exists():
        for line in open(d / 'samples.jsonl'):
            try:
                s = json.loads(line)
            except ValueError:
                continue
            if last is None or s['t'] > last['t']:
                last = s
    out = []
    for lab, a in snaps.items():
        m = re.match(r'^(run|after)(\d+)_(\w+?)_start$', lab)
        if not m or (m.group(1), int(m.group(2))) in counted:
            continue
        b = snaps.get(lab.replace('_start', '_end')) or (last if last and last['t'] > a['t'] else None)
        if b is None:
            continue
        x = dict(cluster=cluster, seconds=b['t'] - a['t'])
        x['it_J'] = P.rapl_delta(a, b, 'package') + (P.rapl_delta(a, b, 'dram') if cluster == 'IRIS' else 0.0)
        x['g_total'] = sum(P.grams(x))
        out.append(x)
    return out

LOST = defaultdict(list)
for d in sorted((ROOT / 'results').glob('opt-*-*')) + sorted((ROOT / 'results/aborted').glob('opt-*-*')):
    if (d / 'snapshots.jsonl').exists():
        cluster = 'IRIS' if '-iris-' in d.name else 'Aion'
        a = next((a for a in ALLOC.get(cluster, []) if a['d'] == d), None)
        counted = ({('run', x['run']) for x in a['runs'] + a['dropped']} | {('after', x['run']) for x in a['after']}) if a else set()
        LOST[cluster] += lost_runs(d, cluster, counted)
for c, v in LOST.items():
    print(f'{c}: {len(v)} runs failed or cut off, {sum(x["seconds"] for x in v):.0f} s, '
          f'{sum(x["g_total"] for x in v):.1f} g', file=sys.stderr)
camp_all = (sum(sum(x['g_total'] for x in a['runs'] + a['dropped'] + a['after']) for al in ALLOC.values() for a in al)
            + sum(x['g_total'] for v in LOST.values() for x in v))
M('OptCampaignGramsAll', sig(camp_all))
M('PaybackCostLo', sig(optimisation_assistance_g + camp_all)); M('PaybackCostHi', sig(project_assistance_g + camp_all))
for cluster, pre in CL.items():
    if cluster in freq:
        M(pre + 'HpcgJobs', str(freq[cluster][0])); M(pre + 'HpcgUsers', str(freq[cluster][1]))
    if cluster not in keep:
        continue
    save = keep[cluster]['save']
    lo, hi = optimisation_assistance_g + camp_all, project_assistance_g + camp_all
    if save > 0:
        M(pre + 'PaybackLo', thou(f'{lo / save:.0f}')); M(pre + 'PaybackHi', thou(f'{hi / save:.0f}'))
        if cluster in freq and freq[cluster][0] > 0:
            M(pre + 'PaybackYearsLo', thou(f'{lo / save / freq[cluster][0]:.0f}'))
            M(pre + 'PaybackYearsHi', thou(f'{hi / save / freq[cluster][0]:.0f}'))
    else:
        for k in ('PaybackLo', 'PaybackHi', 'PaybackYearsLo', 'PaybackYearsHi'):
            M(pre + k, 'never')


# --- the sentences of IV-C, V and V-A that depend on the sign of a result ------------
# Written here, not in the .tex, so that the text cannot contradict the runs: every
# branch is chosen from the measured rounds. A change is "lower" or "higher" only if
# it is so in every round; otherwise it is within the variation between rounds.
def verdict(key, v):
    sub = opt[key]['by'][v]; ref = opt[key]['by']['ref']
    rr = {x['round']: x for x in ref}
    d = [x['g_total'] - rr[x['round']]['g_total'] for x in sub if x['round'] in rr]
    if d and all(q < 0 for q in d): return 'lower'
    if d and all(q > 0 for q in d): return 'higher'
    return 'same'

def rel(key, v, k):
    sub = opt[key]['by'][v]; ref = opt[key]['by']['ref']
    return (mean([x[k] for x in sub]) - mean([x[k] for x in ref])) / mean([x[k] for x in ref])

def ap(x):          # an absolute percentage, for prose
    return pct(abs(x), 1)

VD = {'lower': 'lower in every round', 'higher': 'higher in every round', 'same': 'not consistently in either direction'}
LABEL = lambda c, T: {'Otwo': '\\texttt{-O2}', 'Native': '\\texttt{-march=native}',
                      'CapA': f'the {CAPS[c][0]}\\,GHz cap', 'CapB': f'the {CAPS[c][1]}\\,GHz cap',
                      'Spread': 'one process per L3 cache',
                      'SpreadCap': 'one process per L3 cache with the 2.0\\,GHz cap'}[T]

done = [c for c in ('IRIS', 'Aion') if c in opt]
flags, caps, result = [], [], []
for c in done:
    vo, vn = verdict(c, 'o2'), verdict(c, 'native')
    so = {'higher': f"without \\texttt{{-O3}} every round on {c} emitted more, so the flag is worth {ap(rel(c, 'o2', 'g_total'))} there",
          'lower': f"on {c}, \\texttt{{-O2}} emitted less than \\texttt{{-O3}} in every round",
          'same': f"on {c} the two levels cannot be told apart from the variation between rounds"}[vo]
    sn = {'higher': f"\\texttt{{-march=native}} emitted more in every round",
          'lower': f"\\texttt{{-march=native}} emitted less in every round, by {ap(rel(c, 'native', 'g_total'))}",
          'same': f"\\texttt{{-march=native}} made no difference beyond that variation"}[vn]
    flags.append(f"{so[0].upper() + so[1:]}, and {sn}.")
    for v, T in [(v, T) for v, T in CFG[c] if T in ('CapA', 'CapB') and opt[c]['by'].get(v)]:
        cap = CAPS[c][0] if T == 'CapA' else CAPS[c][1]
        sub, ref = opt[c]['by'][v], opt[c]['by']['ref']
        base_it = min(x['iters'] for x in ref)
        same = [x for x in sub if x['iters'] >= base_it]
        lead = f"At {cap}\\,GHz on {c}, "
        if len(same) < len(sub):
            # runs that did fewer iterations did less work: compare only the runs that did
            # at least the baseline's work, each against the baseline of its own round
            other = sorted({x['iters'] for x in sub if x['iters'] < base_it})
            lead = (f"At {cap}\\,GHz on {c}, {len(sub) - len(same)} of the {len(sub)} runs did "
                    f"{'/'.join(map(str, other))} iterations instead of {base_it} and are "
                    f"left out. In the {len(same)} that did the same work, ")
            rr = {x['round']: x for x in ref}
            ref = [rr[x['round']] for x in same if x['round'] in rr]
            same = [x for x in same if x['round'] in rr]
        r = lambda k: (mean([x[k] for x in same]) - mean([x[k] for x in ref])) / mean([x[k] for x in ref])
        rr = {x['round']: x for x in opt[c]['by']['ref']}
        d = [x['g_total'] - rr[x['round']]['g_total'] for x in same if x['round'] in rr]
        vd = VD['lower'] if d and all(q < 0 for q in d) else VD['higher'] if d and all(q > 0 for q in d) else VD['same']
        caps.append(f"{lead}the power changed by {spct(r('power'))} and the run time by "
                    f"{spct(r('seconds'))}, so the energy changed by {spct(r('it_J'))}, the operational "
                    f"emissions by {spct(r('g_op'))}, the manufacture charged to the run by "
                    f"{spct(r('g_emb'))}, and the footprint by {spct(r('g_total'))} ({vd}).")

# placement (Aion, second allocation)
plc = []
if 'AionPl' in opt:
    a = opt['AionPl']; by = a['by']; ref = by['ref']
    base_it = min(x['iters'] for x in ref)
    def work(v):
        its = sorted({x['iters'] for x in by[v]})
        return '' if its == [base_it] else f", doing {'/'.join(map(str, its))} iterations instead of {base_it}"
    if by.get('spread'):
        plc.append(f"Giving each process its own L3 cache changed the rating by {spct(rel('AionPl', 'spread', 'rating'))}, the run "
                   f"time by {spct(rel('AionPl', 'spread', 'seconds'))} and the power by {spct(rel('AionPl', 'spread', 'power'))}"
                   f"{work('spread')}, so the footprint changed by {spct(rel('AionPl', 'spread', 'g_total'))} "
                   f"({VD[verdict('AionPl', 'spread')]}) and the footprint per unit of work by "
                   f"{macros.get('AionPlSpreadPerWorkPct', '?')}.")
    if by.get('spread20'):
        plc.append(f"With the 2.0\\,GHz cap as well, the footprint changed by {spct(rel('AionPl', 'spread20', 'g_total'))} "
                   f"({VD[verdict('AionPl', 'spread20')]}){work('spread20')}.")
    if by.get('f20'):
        plc.append(f"The 2.0\\,GHz cap alone changed it by {spct(rel('AionPl', 'f20', 'g_total'))} "
                   f"({VD[verdict('AionPl', 'f20')]}) in this allocation"
                   + (f", against {spct(rel('Aion', 'f20', 'g_total'))} in the first." if 'Aion' in opt and opt['Aion']['by'].get('f20') else '.'))
M('OptPlacementText', ' '.join(plc) or '\\textcolor{red}{[pending]}')

for c in ('IRIS', 'Aion'):
    pre = CL[c]
    if c not in keep:
        result.append(f"The runs on {c} had not finished when this version was built.")
        continue
    k = keep[c]
    if not k['best']:
        result.append(f"On {c}, no configuration passes the rule of Section~\\ref{{sec:optproc}}, so the job stays as it was "
                      f"at {macros[pre + 'Grams']}\\,g per run.")
        continue
    tested = (f" In the {'rounds on this node' if k.get('cmp_same_node') else 'test rounds on one node'}, it emitted "
              f"less than the unchanged job in {macros[pre + 'PairedLower']} "
              f"rounds, by {macros[pre + 'PairedSavePct']} on average." if pre + 'PairedLower' in macros else '')
    n_aft = len(k['after'])
    if n_aft >= 100:
        d_ = k.get('same_vs_base', 0.0)
        node_note = (f" On another node, the 100 runs of Section~\\ref{{sec:lcia}} emitted {macros[pre + 'HundredGrams']}\\,g, "
                     f"and this node's unchanged runs {pct(abs(d_), 1)} {'less' if d_ < 0 else 'more'}: a difference between "
                     f"{c}'s nodes, which is why the comparison rests on the same node." if k.get('cmp_same_node') else '')
        # two means that round alike would read "12.4 instead of 12.4"
        ra, rb = macros[pre + 'AftRating'], macros[pre + 'CmpRating']
        rating_txt = (f"rated {ra}\\,GFLOP/s, the same to one decimal" if ra == rb
                      else f"rated {ra} instead of {rb}\\,GFLOP/s")
        # HPCG fixes the duration, not the work: say so if the two did different work
        work_note = ('' if k.get('work', 'same') == 'same' else
                     f" The unchanged runs did {macros[pre + 'CmpIters']} iterations, so the runs after optimisation did "
                     f"{k['work']} work" + (", which the rule of Section~\\ref{sec:optproc} excludes." if k['work'] == 'less' else "."))
        # a round left out of the same-node comparison: which, why, and the change with it
        A_, left_note = k['A'], ''
        if A_ and A_['dropped'] and k.get('cmp_same_node'):
            dref = [x for x in A_['dropped'] if x['variant'] == 'ref']
            dsub = [x for x in A_['dropped'] if x['variant'] == k['bestv']]
            oref, osub = A_['ref'], A_['by'].get(k['bestv'], [])
            rounds = sorted({x['round'] + 1 for x in A_['dropped']})
            nr = len({x['round'] for x in A_['runs'] + A_['dropped'] if x['variant'] == 'ref'})
            rng = lambda xs, key, dd: f"{fix(min(x[key] for x in xs), dd)} to {fix(max(x[key] for x in xs), dd)}"
            g_aft = mean([x['g_total'] for x in k['after']])
            c_all = mean([x['g_total'] for x in oref + dref])
            if rounds == [1] and len(dref) == 1:
                x1 = dref[0]
                # say "same clock and CPU use" only if the records show it
                same_cl = (abs(x1['clock'] / mean([x['clock'] for x in oref]) - 1) < 0.02
                           and abs(x1['busy'] - mean([x['busy'] for x in oref])) < 0.01)
                why = ("its clock and CPU use were those of the other runs, and nothing else the job recorded explains it"
                       if same_cl else f"its mean clock was {fix(x1['clock'] / 1000, 2)}\\,GHz, against "
                                       f"{rng([dict(c=x['clock'] / 1000) for x in oref], 'c', 2)}\\,GHz for the others")
                left_note = (f" The first of the {nr} rounds on this node is left out of that comparison: its unchanged "
                             f"run took {fix(x1['seconds'], 0)}\\,s and rated {fix(x1['rating'], 1)}\\,GFLOP/s, against "
                             f"{rng(oref, 'seconds', 0)}\\,s and {rng(oref, 'rating', 1)}\\,GFLOP/s for the other {len(oref)}"
                             + (f", and the capped run of that round was slow too ({fix(dsub[0]['seconds'], 0)}\\,s against "
                                f"{rng(osub, 'seconds', 0)}\\,s)" if len(dsub) == 1 and osub else '')
                             + f"; {why}. With that round, the change would be {spct((g_aft - c_all) / c_all)}.")
            else:
                left_note = (f" Round{'s' if len(rounds) > 1 else ''} {' and '.join(map(str, rounds))} of the {nr} on this "
                             f"node {'are' if len(rounds) > 1 else 'is'} left out of that comparison; with "
                             f"{'them' if len(rounds) > 1 else 'it'}, the change would be {spct((g_aft - c_all) / c_all)}.")
        result.append(
            f"On {c}, the change kept is {macros[pre + 'BestName']}. Its {n_aft} runs emitted {macros[pre + 'AftGrams']}\\,g "
            f"per run (standard deviation {macros[pre + 'AftGramsSd']}\\,g), against {macros[pre + 'CmpGrams']}\\,g for "
            f"{macros[pre + 'CmpWhat']}, a change of {macros[pre + 'AftVsCmp']}. A run took {macros[pre + 'AftTime']}\\,s "
            f"instead of {macros[pre + 'CmpTime']}\\,s ({macros[pre + 'AftTimePct']}), used {macros[pre + 'AftEnergy']} "
            f"instead of {macros[pre + 'CmpEnergy']}\\,kJ ({macros[pre + 'AftEnergyPct']}) and "
            f"{rating_txt} ({macros[pre + 'AftRatingPct']}); "
            f"HPCG validated {macros[pre + 'AftValid']} of them, each with {macros[pre + 'AftIters']} iterations."
            f"{left_note}{work_note}{tested}{node_note}")
    elif n_aft > 0:
        result.append(f"On {c}, the change kept is {macros[pre + 'BestName']}; its 100 runs were still running when this "
                      f"version was built ({n_aft} done).{tested}")
    else:
        result.append(f"On {c}, the change chosen is {macros[pre + 'BestName']}; its 100 runs had not run when this "
                      f"version was built.{tested}")

val, explained = [], False
for c in ('IRIS', 'Aion'):
    scr_c = [a for a in ALLOC.get(c, []) if a['ref']]
    for a in scr_c:
        rs = a['runs'] + a['dropped']                 # every run made, left-out rounds included
        byall = {v: [x for x in rs if x['variant'] == v] for v in a['names']}
        nv = sum(1 for x in rs if x['valid']); base_it = min(x['iters'] for x in byall['ref'])
        res = {x['resid'] for x in rs}
        where = c if len(scr_c) == 1 else f"{c} ({'flags and clock' if 'o2' in a['names'] else 'placement'})"
        # IRIS's rounds chose nothing (the cap was set beforehand): they are not screening runs
        kc = keep.get(c) or {}
        chose = not (kc.get('cmp_same_node') and kc.get('A') is not None and kc['A']['d'] == a['d'])
        s = (f"On {where}, HPCG validated {'all ' + str(len(rs)) if nv == len(rs) else str(nv) + ' of ' + str(len(rs))} "
             f"{'screening runs' if chose else 'runs of its rounds'}"
             f"{', all with the same scaled residual' if len(res) == 1 else ''}.")
        odd, more = [], []
        for v in a['names']:
            sub, T = byall[v], LBL[c].get(v)
            if v == 'ref' or not sub or T is None:
                continue
            lo = [x for x in sub if x['iters'] < base_it]; hi = [x for x in sub if x['iters'] > base_it]
            if lo:
                odd.append(f"{LABEL(c, T)}, which did {'/'.join(sorted({str(x['iters']) for x in lo}))} in {len(lo)} of its {len(sub)} runs")
            if hi:
                more.append(f"{LABEL(c, T)}, which did {'/'.join(sorted({str(x['iters']) for x in hi}))} in {len(hi)} of its {len(sub)} runs")
        if not odd and not more:
            s += f" Every configuration did the baseline's {base_it} iterations."
        else:
            if odd:
                s += f" Every configuration did at least the baseline's {base_it} iterations except {' and '.join(odd)}."
            if more:
                s += f" More iterations than the baseline: {' and '.join(more)}."
            if not explained:
                s += (" HPCG repeats its set of 50 iterations as many times as fit in the 60\\,s that \\texttt{hpcg.dat} "
                      "requests, plus one, so a configuration that runs a set slightly slower can do one set fewer, which "
                      "the rule of Section~\\ref{sec:optproc} excludes, and a faster one a set more.")
                explained = True
        val.append(s)
M('OptValidityText', ' '.join(val) or '\\textcolor{red}{[pending]}')
M('OptFlagsText', ' '.join(flags) or '\\textcolor{red}{[pending]}')
M('OptCapText', ' '.join(caps) or '\\textcolor{red}{[pending]}')
M('OptResultText', ' '.join(result))
# the tables' note on rounds left out; empty when none is
lo = []
for c in ('IRIS', 'Aion'):
    for a in ALLOC.get(c, []):
        if a['dropped']:
            rounds = sorted({x['round'] + 1 for x in a['dropped']})
            nr = len({x['round'] for x in a['runs'] + a['dropped'] if x['variant'] == 'ref'})
            which = 'the first' if rounds == [1] else f"round{'s' if len(rounds) > 1 else ''} {' and '.join(map(str, rounds))}"
            lo.append(f"On {c}, {which} of the {nr} rounds {'are' if len(rounds) > 1 else 'is'} left out "
                      f"(Section~\\ref{{sec:afteropt}}).")
M('OptLeftOutNote', (' ' + ' '.join(lo)) if lo else '')

# the abstract's and V-A's one-line summary of the kept changes
dk = [c for c in ('IRIS', 'Aion') if c in keep]
bests = {c: ((macros[CL[c] + 'BestName'], macros[CL[c] + 'BestSavePct']) if keep[c]['best'] and keep[c]['save'] > 0 else ('', '')) for c in dk}
named = {c: b[0] for c, b in bests.items() if b[0]}
if len(named) == 2 and len(set(named.values())) == 1:
    best_txt = f"{named['IRIS']} cuts a run by {bests['IRIS'][1]} on IRIS and {bests['Aion'][1]} on Aion"
else:
    parts = [f"{bests[c][0]} cuts a run by {bests[c][1]} on {c}" if bests[c][0] else
             (f"{macros[CL[c] + 'BestName']} does not lower it on {c}" if keep[c]['best'] else
              f"no setting lowers the footprint on {c} in every round") for c in dk]
    best_txt = ' and '.join(parts) + ''.join(f"; the runs on {c} are still pending" for c in ('IRIS', 'Aion') if c not in keep)
M('OptBestText', best_txt)
if done:
    fl = lambda v: ' and '.join(f"{spct(rel(c, v, 'g_total'))} on {c}" for c in done)
    M('OptFlagsPctText', f"Going back from \\texttt{{-O3}} to \\texttt{{-O2}} changed the footprint of a run by {fl('o2')}; "
                         f"adding \\texttt{{-march=native}} changed it by {fl('native')}.")

# carbon payback, in prose
pb = []
for c in dk:
    pre = CL[c]
    if keep[c]['save'] > 0:
        if c in freq and freq[c][0] > 0:
            n = freq[c][0]
            unit = 'allocation' if n == 1 else 'allocations'
            yrs = (f" The {n} matching {unit} on {c} would imply approximately "
                   f"{macros[pre + 'PaybackYearsLo']} to {macros[pre + 'PaybackYearsHi']} years under this assumption.")
        elif c in freq:
            yrs = f" The search found no matching allocations on {c} from which to estimate a time to payback."
        else:
            yrs = f" An allocation count for {c} was unavailable."
        pb.append(f"On {c} the estimated payback is {macros[pre + 'PaybackLo']} to {macros[pre + 'PaybackHi']} runs.{yrs}")
    else:
        pb.append(f"On {c} nothing is saved, so the cost is never repaid.")
M('PaybackText', ' '.join(pb) or '\\textcolor{red}{[pending]}')
sv = [c for c in dk if keep[c]['save'] > 0]
if sv:
    lo_c, hi_c = optimisation_assistance_g + camp_all, project_assistance_g + camp_all
    rlo = min(lo_c / keep[c]['save'] for c in sv); rhi = max(hi_c / keep[c]['save'] for c in sv)
    M('PaybackMeaningText', f"The optimisation cost {macros['PaybackCostLo']} to {macros['PaybackCostHi']}\\,g. "
                            f"At the savings measured here, it would take about {thou(f'{rlo:.0f}')} to "
                            f"{thou(f'{rhi:.0f}')} comparable runs to recover that cost.")
else:
    M('PaybackMeaningText', f"Nothing was saved, so the {macros['PaybackCostLo']} to {macros['PaybackCostHi']}\\,g spent "
                            f"finding that out is never repaid.")
M('OptCampaignText', ' and '.join(f"{sum(len(a['runs']) + len(a['dropped']) + len(a['after']) for a in ALLOC[c])} runs on {c}"
                                  + (f" (plus {len(LOST[c])} whose results were not used, in allocations "
                                     f"stopped early)" if LOST.get(c) else '')
                                  for c in ('IRIS', 'Aion') if c in ALLOC) or '\\textcolor{red}{[pending]}')
M('OptSaveText', ' and '.join(f"{macros[CL[c] + 'BestSave']}\\,g on {c}" for c in dk) or '\\textcolor{red}{[pending]}')

# --- figures still to come get a visible placeholder, so the draft always builds ------
used = set(re.findall(r'\\((?:Iris|Aion|Gap|Assist|Led|Grid|Opt|Payback)[A-Za-z]*)', (ROOT / 'paper/src/short-paper-hpc-v1.tex').read_text()))
for k in used - {'OptTableRows', 'RunsTableRows', 'OtherMeansRows', 'BeforeAfterRows'}:
    macros.setdefault(k, '\\textcolor{red}{[pending]}')

# --- write ---------------------------------------------------------------------------
with open(OUT_NUM, 'w') as f:
    f.write('% Generated by scripts/v1_numbers.py; do not edit by hand, rerun the script.\n')
    for k in sorted(macros):
        f.write(f'\\newcommand{{\\{k}}}{{{macros[k]}}}\n')

def row_node(cluster, n, v):
    m = lambda k: mean([x[k] for x in v])
    e = '' if cluster == 'Aion' else (f"{fix(m('pkg_J')/1e3,1)} + {fix(m('dram_J')/1e3,1)}"
                                      if all(x.get('pkg_J') is not None for x in v) else 'SLURM only')
    return (f"{cluster} & {node_label[(cluster, n)]} & {len(v)} & {fix(m('seconds'),1)} & "
            f"{fix(m('it_J')/1e3,2)} & {e} & {fix(m('rating'),2)} & {m('iters'):.0f} & "
            f"{sig(m('g_node'),3)} & {sig(m('g_site'),3)} & {sig(m('g_emb'),3)} & {sig(m('g_total'),3)} \\\\")

with open(OUT_TAB, 'w') as f:
    f.write('% Generated by scripts/v1_numbers.py; do not edit by hand, rerun the script.\n')
    f.write('\\newcommand{\\RunsTableRows}{%\n')
    for cluster in [c for c in CL if c in pooled]:
        ref = pooled[cluster]['ref']
        m = lambda k, sc=1: mean([x[k] / sc for x in ref])
        pk = '' if cluster == 'Aion' else f"{m('pkg_J', 1e3):.1f} + {m('dram_J', 1e3):.1f}"
        work = thou(f"{mean([x['flop'] for x in ref]) / 1e9:.0f}")
        f.write(f"{cluster} & {len(ref)} & {fix(m('seconds'), 1)} & {fix(m('it_J', 1e3), 1)} & {pk} & "
                f"{fix(mean([x['it_J'] / x['seconds'] for x in ref]), 0)} & {fix(m('rating'), 1)} & "
                f"{work} & "
                + ' & '.join(sig(m(k), 2) for k in ('g_node', 'g_site', 'g_emb')) + f" & {sig(m('g_total'), 2)} \\\\\n")
    f.write('}\n')
    # Table V: the mean of every other measured quantity
    f.write('\\newcommand{\\OtherMeansRows}{%\n')
    if 'IRIS' in pooled and 'Aion' in pooled:
        I, A = pooled['IRIS']['ref'], pooled['Aion']['ref']
        mm = lambda v, k, sc=1: mean([x[k] / sc for x in v if x.get(k) is not None])
        idle = {c: mean(P.idle_power(RES_DIR[c])) for c in ('IRIS', 'Aion')}
        rows_ = [
            ('Timed phase / rest of the run (s)', lambda v: f"{mm(v, 'timed'):.0f} / {mean([x['seconds'] - x['timed'] for x in v]):.0f}"),
            ('Peak power over 2\\,s (W)', lambda v: f"{mm(v, 'peak_W'):.0f}"),
            ('Node CPU busy', lambda v: f"{100 * mm(v, 'busy'):.1f}\\,\\%"),
            ('Mean core clock (GHz)', lambda v: f"{mm(v, 'clock') / 1000:.1f}"),
            ('Processor temperature, mean / hottest (\\textdegree C)', lambda v: f"{mm(v, 'temp'):.0f} / {mm(v, 'hot'):.0f}"),
            ('Memory touched (GiB)', lambda v: f"{mm(v, 'mem_gib'):.1f}"),
            ('InfiniBand out / in (MB)', lambda v: f"{mm(v, 'ib_out', 1e6):.1f} / {mm(v, 'ib_in', 1e6):.1f}"),
            ('Ethernet out / in (MB)', lambda v: f"{mm(v, 'eth_out', 1e6):.2f} / {mm(v, 'eth_in', 1e6):.2f}"),
            ('Local SSD read / written (MB)', lambda v: f"{mm(v, 'disk_r', 1e6):.2f} / {mm(v, 'disk_w', 1e6):.1f}"),
        ]
        for label, fn in rows_:
            f.write(f"{label} & {fn(I)} & {fn(A)} \\\\\n")
        f.write(f"Idle node power, before and after (W) & {idle['IRIS']:.0f} & {idle['Aion']:.0f} \\\\\n")
    f.write('}\n')
    # Table VII: before and after, 100 runs each (and IRIS's same-node baseline)
    f.write('\\newcommand{\\BeforeAfterRows}{%\n')
    first = True
    for cluster, pre in CL.items():
        if not first:
            f.write('\\midrule\n')
        first = False
        k = keep.get(cluster)
        before = pooled[cluster]['ref'] if cluster in pooled else []
        rows_ = [('unchanged, Section~\\ref{sec:lcia}', before)]
        if k and k['A'] and len(k['A']['ref']) >= 5:
            rows_.append(('unchanged, same node', k['A']['ref']))
        if k and len(k['after']) >= 1:
            T = LBL[cluster].get(k['bestv'], k['bestv'])
            rows_.append(({'CapA': f"cap {CAPS[cluster][0]}\\,GHz", 'CapB': f"cap {CAPS[cluster][1]}\\,GHz",
                           'Spread': 'spread', 'SpreadCap': 'spread, cap 2.0\\,GHz'}.get(T, k['bestv']), k['after']))
        cmp_rows = (k['A']['ref'] if k and k.get('cmp_same_node') else before)
        c0 = mean([x['g_total'] for x in cmp_rows]) if cmp_rows else None
        for j, (name, sub) in enumerate(rows_):
            if not sub:
                continue
            m = lambda key: mean([(x['it_J'] / x['seconds']) if key == 'power' else x[key] for x in sub])
            gop = mean([x['g_node'] + x['g_site'] for x in sub])
            dg = spct((m('g_total') - c0) / c0) if (c0 and j == len(rows_) - 1 and len(rows_) > 1 and k and k['after']) else ''
            f.write(f"{cluster if j == 0 else ''} & {name} & {len(sub)} & {fix(m('seconds'), 1)} & "
                    f"{fix(m('it_J') / 1e3, 1)} & {fix(m('power'), 0)} & {fix(m('rating'), 1)} & "
                    f"{'/'.join(sorted({str(x['iters']) for x in sub}))} & {sig(gop, 3)} & {sig(m('g_emb'), 3)} & "
                    f"{sig(m('g_total'), 3)} & {dg} \\\\\n")
        if not (k and k['after']):
            f.write(f" & \\multicolumn{{11}}{{l}}{{100 runs after optimisation still to come}} \\\\\n")
    f.write('}\n')

    # Table VIII: the test rounds that chose the change (allocations with the unchanged job)
    f.write('\\newcommand{\\OptTableRows}{%\n')
    first = True
    for cluster, pre in CL.items():
        al = [a for a in ALLOC.get(cluster, []) if a['ref']]
        if not al:
            continue
        if not first:
            f.write('\\midrule\n')
        first = False
        for j, a in enumerate(al):
            if j:
                f.write('\\cmidrule(l){2-12}\n')
            by, ref = a['by'], a['ref']
            r0 = mean([x['g_total'] for x in ref])
            base_it = min(x['iters'] for x in ref)
            head = cluster if len(al) == 1 else f"{cluster} ({j + 1})"
            for v in a['names']:
                T = LBL[cluster].get(v, v)
                name0 = {'Ref': 'unchanged', 'Otwo': '\\texttt{-O2}', 'Native': '\\texttt{-march=native}',
                         'CapA': f"cap {CAPS[cluster][0]}\\,GHz", 'CapB': f"cap {CAPS[cluster][1]}\\,GHz",
                         'Spread': 'spread', 'SpreadCap': 'spread, cap 2.0\\,GHz'}.get(T, v)
                groups = [(name0, by[v])]
                if v != 'ref' and {x['iters'] for x in by[v]} != {base_it}:
                    groups = [(f"{name0}, {it} it.", [x for x in by[v] if x['iters'] == it])
                              for it in sorted({x['iters'] for x in by[v]}, reverse=True)]
                for name, sub in groups:
                    if not sub:
                        continue
                    m = lambda key: mean([x[key] for x in sub])
                    dg = '' if v == 'ref' else spct((m('g_total') - r0) / r0)
                    f.write(f"{head if v == 'ref' else ''} & {name} & {len(sub)} & {fix(m('clock') / 1000, 1)} & "
                            f"{fix(m('seconds'), 1)} & {fix(m('it_J') / 1e3, 1)} & {fix(m('power'), 0)} & "
                            f"{fix(m('rating'), 1)} & {sig(m('g_op'), 3)} & {sig(m('g_emb'), 3)} & "
                            f"{sig(m('g_total'), 3)} & {dg} \\\\\n")
    f.write('}\n')

print(f'{len(macros)} macros -> {OUT_NUM.relative_to(ROOT)}\ntables -> {OUT_TAB.relative_to(ROOT)}')
for k in sorted(macros):
    print(f'  {k} = {macros[k]}')
