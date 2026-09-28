#!/usr/bin/env bash
# Construye topOS: distro/out/topOS.iso (arrancable) y distro/out/topOS-wsl.tar.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p distro/out
docker build -f distro/Dockerfile --target base -t topos-os .
id=$(docker create topos-os)
docker export -o distro/out/topOS-wsl.tar "$id"
docker rm "$id" >/dev/null
docker build -f distro/Dockerfile --target export -o distro/out .
ls -lh distro/out
