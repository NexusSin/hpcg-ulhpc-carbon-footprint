# jobprint

Prints the carbon footprint of a SLURM job, step by step, in grams of CO2e
(GWP100), and the levers that would lower it.

## What it does

For every numbered step of the job it reads the time the step held its nodes
and the energy the scheduler recorded (from the step's usage record,
`TRESUsageInTot`, or else `ConsumedEnergyRaw`), and splits the footprint into
three terms:

- **node**: the node's electricity, `E_IT [kWh] x grid`;
- **site**: cooling and power distribution, `E_IT x (PUE - 1) x grid`;
- **manufacture**: the node's embodied carbon, charged by the time the step holds
  the node out of the time the node is allocated to jobs over its life.

The tool names the largest term and flags low CPU or memory use. When scheduler
energy is missing, as in the study's Aion records, or implies less than 20 W
per node, the tool estimates step energy by multiplying rated processor power
per node by the node count and elapsed time. It marks each estimate with `*`.

The factors for IRIS and Aion are at the top of `jobprint.py`. For another
site, add its node and facility factors to `SITES` and check that `GRID`,
the electricity emissions factor, applies to that site.

## How to run it

On a cluster login node, with SLURM's accounting available:

    python3 jobprint.py 1234567

Without a cluster, on the saved record of one job of the study (100 runs of the
HPCG benchmark on one node, identifiers replaced):

    python3 jobprint.py --record sample-iris.txt

It needs Python 3.6 or newer and nothing else. A saved record of your own job is
the output of

    sacct -j JOBID -P -o JobID,JobName,Cluster,NodeList,NNodes,ElapsedRaw,ConsumedEnergyRaw,AllocTRES,TRESUsageInTot,State

## What it prints

On the sample record: 100 steps of about 6.0 gCO2e each (node 31 %, site 19 %,
manufacture 50 %), the manufacture named as the hotspot, and 27 of 112 GiB of
reserved memory touched. The steps average 5.97 gCO2e, against the 5.98 g that
the paper reports for the same 100 runs from the processors' own counters. In
this record SLURM's `ConsumedEnergyRaw` field holds only 1 to 27 J for 28 of the
steps; their usage records hold the right energy, which is why the script reads
those first.
