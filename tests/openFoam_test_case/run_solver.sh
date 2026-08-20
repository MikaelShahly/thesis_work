#!/bin/bash
set -eo pipefail
mkdir -p logs
rm -rf processor*
decomposePar 2>&1 | tee logs/decomposePar_solver.log
mpirun --oversubscribe -np 6 simpleFoam -parallel 2>&1 | tee logs/solver_diag.log
reconstructPar 2>&1 | tee logs/reconstructPar.log
rm -rf processor*
