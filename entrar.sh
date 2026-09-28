#!/usr/bin/env bash
# Un shell dentro del mundo topológico: el almacén vive en /var/topos (monta ahí
# un volumen para que sobreviva) y se ve montado en /mundo con las herramientas
# de siempre. Al salir del shell se desmonta.
set -eu
export TOPOS_HOME=/var/topos
[ -f "$TOPOS_HOME/.topos/state.json" ] || (mkdir -p "$TOPOS_HOME" && cd "$TOPOS_HOME" && topos init >/dev/null)
mkdir -p /mundo
topos mount /mundo --background
trap 'cd /; fusermount -u /mundo' EXIT
cat <<'MSG'
Estás en /mundo. Los archivos son vértices; las carpetas de relations/ son relaciones.
  echo hola > files/a.txt            un vértice nuevo
  mkdir relations/tesis              una relación vacía
  ln files/a.txt relations/tesis/    un archivo en muchas relaciones a la vez
  topos glue a.txt b.txt --as par    pegar símplices;  cat holes  para ver los huecos
MSG
cd /mundo
PS1='topos:\w\$ ' bash --norc -i || true
