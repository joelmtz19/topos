"""La memoria de Linux como espacio topológico.

Los puntos son trozos de memoria física identificables: intervalos elementales
de cada archivo mapeado (dev, inode) y, por proceso, su memoria anónima
privada. Cada proceso p ve un subconjunto U_p; la topología es la generada por
esos U_p.

- Cociente de Kolmogorov (T0): dos puntos que ningún proceso distingue se
  identifican. Lo que queda son las clases que el sistema sí puede separar.
- Nervio del recubrimiento {U_p}: un símplice por cada grupo de procesos que
  comparte algún punto. β0 cuenta islas de aislamiento; β1 detecta ciclos de
  compartición (A–B, B–C, C–A) sin un punto común a los tres.

Con --writable sólo cuentan los mapeos compartidos y escribibles (rw-s), que
son los canales de IPC reales; si no, casi todo proceso comparte libc y el
nervio es un gran símplice contráctil.
"""

import json
import re
from pathlib import Path

from .complex import Complex

MAPS = re.compile(r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S{4})\s+([0-9a-f]+)\s+(\S+)\s+(\d+)\s*(.*)$")


def snapshot(proc="/proc"):
    """{pid: {'name': comm, 'maps': [líneas]}} de todos los procesos legibles."""
    root = Path(proc)
    if not (root / "self" / "maps").exists():
        raise OSError(f"{proc} no tiene mapas de memoria; esto necesita Linux (usa Docker)")
    out = {}
    for d in root.iterdir():
        if not d.name.isdigit():
            continue
        try:
            out[d.name] = {"name": (d / "comm").read_text().strip(),
                           "maps": (d / "maps").read_text().splitlines()}
        except OSError:
            continue  # proceso que terminó o que no podemos leer
    return out


def load(path):
    return json.loads(Path(path).read_text())


def build(snap, writable_only=False):
    """Devuelve (procesos, puntos) con puntos = {nombre: frozenset(procesos)}."""
    procs = {pid: f"{info['name']}[{pid}]" for pid, info in snap.items()}
    intervals = {}
    points = {}
    for pid, info in snap.items():
        me = procs[pid]
        for line in info["maps"]:
            m = MAPS.match(line)
            if not m:
                continue
            start, end, perms, off, dev, inode, path = m.groups()
            shared_rw = perms[1] == "w" and perms[3] == "s"
            if inode == "0" or (writable_only and not shared_rw):
                if not writable_only:
                    points.setdefault(f"privada:{me}", set()).add(me)
                continue
            lo = int(off, 16)
            hi = lo + int(end, 16) - int(start, 16)
            intervals.setdefault((dev, inode, path or "?"), []).append((lo, hi, me))

    for (dev, inode, path), ivs in intervals.items():
        cuts = sorted({x for lo, hi, _ in ivs for x in (lo, hi)})
        for a, b in zip(cuts, cuts[1:]):
            who = {p for lo, hi, p in ivs if lo <= a and b <= hi}
            if who:
                points[f"{path}@{a:x}"] = who
    return sorted(procs.values()), {k: frozenset(v) for k, v in points.items()}


def kolmogorov(points):
    """Clases de puntos indistinguibles: conjunto de procesos → puntos."""
    classes = {}
    for name, who in points.items():
        classes.setdefault(who, []).append(name)
    return classes


def nerve(procs, points):
    return Complex([(p,) for p in procs] + [tuple(w) for w in set(points.values())])


def shared_pairs(points):
    pairs = {}
    for who in points.values():
        ws = sorted(who)
        for i, a in enumerate(ws):
            for b in ws[i + 1:]:
                pairs[(a, b)] = pairs.get((a, b), 0) + 1
    return sorted(pairs.items(), key=lambda kv: -kv[1])
