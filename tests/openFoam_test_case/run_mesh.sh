#!/bin/bash
set -eo pipefail
mkdir -p logs
surfaceFeatureExtract 2>&1 | tee logs/surfaceFeatureExtract.log
blockMesh 2>&1 | tee logs/blockMesh.log
rm -rf processor*
rm -f 0/cellLevel 0/pointLevel
decomposePar -no-fields -force 2>&1 | tee logs/decomposePar.log
mpirun --oversubscribe -np 6 snappyHexMesh -overwrite -parallel 2>&1 | tee logs/snappyHexMesh.log
reconstructParMesh -constant 2>&1 | tee logs/reconstructParMesh.log
rm -rf processor*
checkMesh -allGeometry -allTopology 2>&1 | tee logs/checkMesh.log
