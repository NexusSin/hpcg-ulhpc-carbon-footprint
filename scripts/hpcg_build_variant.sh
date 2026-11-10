#!/bin/bash
###############################################################################
# Green IT 2026 - build one variant of the frozen HPCG commit into a directory.
#
#   hpcg_build_variant.sh ref DIR    the reference build, exactly as measured
#                                    since 2026-09-24: configure MPI_GCC_OMP
#   hpcg_build_variant.sh contig DIR the reference build plus -DHPCG_CONTIGUOUS_ARRAYS only
#   hpcg_build_variant.sh native DIR the reference build plus -march=native only
#   hpcg_build_variant.sh o2 DIR     the reference build with -O2 in place of -O3,
#                                    to measure what HPCG's own -O3 contributes
#   hpcg_build_variant.sh opt DIR    the combined build used in early tests: the same
#                                    source and the same flags, plus
#                                      -DHPCG_CONTIGUOUS_ARRAYS (HPCG's own switch:
#                                       each matrix level in one block of memory
#                                       instead of one small block per row), and
#                                      -march=native (code generated for the
#                                       processor of the node that builds it)
#
# Must run on a compute node with toolchain/foss/2023b loaded, so that
# -march=native targets the node that will run the binary. The source tree is
# not modified: the extra flags are passed to make on the command line.
###############################################################################
set -euo pipefail
VARIANT="$1"; DIR="$2"
HPCG_DIR="${HOME}/green_it/hpcg"
BASE_FLAGS='$(HPCG_DEFS) -O3 -ffast-math -ftree-vectorize -ftree-vectorizer-verbose=0 -fopenmp'

rm -rf "${DIR}"; mkdir -p "${DIR}"; cd "${DIR}"
"${HPCG_DIR}/configure" MPI_GCC_OMP > configure.log 2>&1
case "${VARIANT}" in
  ref)    make -j "${SLURM_CPUS_ON_NODE:-4}" > build.log 2>&1 ;;
  contig) make -j "${SLURM_CPUS_ON_NODE:-4}" HPCG_OPTS=-DHPCG_CONTIGUOUS_ARRAYS > build.log 2>&1 ;;
  native) make -j "${SLURM_CPUS_ON_NODE:-4}" CXXFLAGS="${BASE_FLAGS} -march=native" > build.log 2>&1 ;;
  o2)     make -j "${SLURM_CPUS_ON_NODE:-4}" CXXFLAGS="${BASE_FLAGS/-O3/-O2}" > build.log 2>&1 ;;
  opt)    make -j "${SLURM_CPUS_ON_NODE:-4}" HPCG_OPTS=-DHPCG_CONTIGUOUS_ARRAYS \
               CXXFLAGS="${BASE_FLAGS} -march=native" > build.log 2>&1 ;;
  *) echo "unknown variant ${VARIANT}" >&2; exit 2 ;;
esac
# the compile line actually used, for the record
grep -m1 'src/CG.o' build.log | sed 's/^/compile     : /' || true
echo "build ${VARIANT}   : ok, $(stat -c %s bin/xhpcg) bytes, native=$(gcc -march=native -Q --help=target 2>/dev/null | awk '/-march=/{print $2; exit}')"
