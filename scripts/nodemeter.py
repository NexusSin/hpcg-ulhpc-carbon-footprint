#!/usr/bin/env python3
"""Read everything a normal user can read about a compute node's activity.

    nodemeter.py snap LABEL OUT.jsonl        one full snapshot, appended as JSON
    nodemeter.py sample SECONDS OUT.jsonl    snapshots every SECONDS until killed

A snapshot holds: RAPL energy counters of every powercap domain (with their
names and wrap ranges), InfiniBand port counters, bytes on every network
interface, sectors read and written on local disks, the node's CPU time split
(/proc/stat), the mean and max core clock (/proc/cpuinfo), every hwmon
temperature, and AMD per-core/per-socket energy (amd_energy) where readable.
Unreadable sources are skipped, never fatal. Python 3.6 compatible.
"""
import glob, json, os, re, signal, sys, time

def rd(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except (OSError, IOError):
        return None

def rapl():
    out = {}
    for d in sorted(glob.glob('/sys/class/powercap/intel-rapl:*')):
        e = rd(d + '/energy_uj')
        if e is None:
            continue
        out[os.path.basename(d)] = dict(name=rd(d + '/name'), uj=int(e),
                                        range=int(rd(d + '/max_energy_range_uj') or 0))
    return out

def infiniband():
    out = {}
    for c in glob.glob('/sys/class/infiniband/*/ports/*/counters'):
        key = c.split('/')[4] + ':' + c.split('/')[6]
        v = {}
        for k in ('port_xmit_data', 'port_rcv_data', 'port_xmit_packets', 'port_rcv_packets'):
            x = rd(c + '/' + k)
            if x is not None:
                v[k] = int(x)
        if v:
            out[key] = v
    return out

def netdev():
    out = {}
    for d in glob.glob('/sys/class/net/*'):
        n = os.path.basename(d)
        if n == 'lo':
            continue
        rx, tx = rd(d + '/statistics/rx_bytes'), rd(d + '/statistics/tx_bytes')
        if rx is not None and tx is not None:
            out[n] = [int(rx), int(tx)]
    return out

def disks():
    out = {}
    txt = rd('/proc/diskstats') or ''
    for line in txt.splitlines():
        p = line.split()
        if len(p) < 10:
            continue
        name = p[2]
        if re.match(r'^(sd[a-z]+|nvme\d+n\d+|vd[a-z]+)$', name):   # whole disks only
            out[name] = [int(p[5]), int(p[9])]                     # sectors read, written
    return out

def cpustat():
    line = (rd('/proc/stat') or '').splitlines()[0].split()
    return [int(x) for x in line[1:9]]   # user nice system idle iowait irq softirq steal

def cpufreq():
    mhz = [float(m) for m in re.findall(r'cpu MHz\s*:\s*([\d.]+)', rd('/proc/cpuinfo') or '')]
    return [round(sum(mhz) / len(mhz), 1), round(max(mhz), 1), len(mhz)] if mhz else None

def temps():
    out = {}
    for d in glob.glob('/sys/class/hwmon/hwmon*'):
        name = rd(d + '/name') or 'hwmon'
        for t in sorted(glob.glob(d + '/temp*_input')):
            v = rd(t)
            if v is None:
                continue
            label = rd(t.replace('_input', '_label')) or os.path.basename(t)
            out['%s/%s/%s' % (os.path.basename(d), name, label)] = int(v)
    return out

def amd_energy():
    out = {}
    for d in glob.glob('/sys/class/hwmon/hwmon*'):
        if rd(d + '/name') != 'amd_energy':
            continue
        for e in glob.glob(d + '/energy*_input'):
            v = rd(e)
            if v is None:
                return {'readable': False}
            out[rd(e.replace('_input', '_label')) or os.path.basename(e)] = int(v)
    return out

def snapshot(label):
    return dict(label=label, t=time.time(), rapl=rapl(), ib=infiniband(), net=netdev(),
                disk=disks(), cpu=cpustat(), freq=cpufreq(), temp=temps(), amd=amd_energy())

def main():
    mode, arg, out = sys.argv[1], sys.argv[2], sys.argv[3]
    if mode == 'snap':
        with open(out, 'a') as f:
            f.write(json.dumps(snapshot(arg)) + '\n')
        return
    period = float(arg)
    stop = {'now': False}
    signal.signal(signal.SIGTERM, lambda *a: stop.update(now=True))
    with open(out, 'a') as f:
        while not stop['now']:
            t0 = time.time()
            s = snapshot('sample')
            s.pop('amd', None) if s.get('amd') and len(s['amd']) > 8 else None   # per-core only at run boundaries
            f.write(json.dumps(s) + '\n'); f.flush()
            time.sleep(max(0.0, period - (time.time() - t0)))

if __name__ == '__main__':
    main()
