"""Permisos como haz celular sobre el complejo de archivos.

Un bit de permiso es `usuario:letra` (alice:r). Cada relación puede *gobernar*
algunos bits: los archivos que junta deben coincidir en ellos. El haz F tiene
en cada vértice todos los bits, y en cada símplice de dimensión >= 1 los bits
que gobiernan las relaciones que lo contienen; las restricciones son
proyecciones. Así F se parte en una suma directa sobre bits,

    F = ⊕_b  GF(2) constante sobre K_b,

donde K_b son los vértices más los símplices de las relaciones que gobiernan b.
Por eso H^k(F) = ⊕_b H^k(K_b) y sus dimensiones son números de Betti.

Los valores declarados (+alice:r en un archivo o en una relación) son datos
locales sobre un subcomplejo A. Se pegan en una sección global justo cuando su
imagen bajo el conector H^0(A) → H^1(K_b, A) es cero, es decir, cuando ninguna
componente de K_b recibe un 1 y un 0 a la vez. Cada conflicto se reporta con
el camino que lo atestigua.
"""

from collections import deque
from dataclasses import dataclass, field

from .complex import Complex
from .i18n import t

LETTERS = "rwx"


def expand(spec):
    """'alice:rw' → ['alice:r', 'alice:w']."""
    user, _, letters = spec.partition(":")
    if not user or not letters or set(letters) - set(LETTERS):
        raise ValueError(t(f"bit inválido: {spec!r} (usa usuario:rwx)", f"invalid bit: {spec!r} (use user:rwx)"))
    return [f"{user}:{c}" for c in letters]


def parse_values(specs):
    """['+alice:rw', '-bob:x'] → {'alice:r': 1, 'alice:w': 1, 'bob:x': 0}."""
    out = {}
    for spec in specs:
        if spec[:1] not in "+-" or len(spec) < 2:
            raise ValueError(t(f"valor inválido: {spec!r} (usa +usuario:rw o -usuario:x)",
                             f"invalid value: {spec!r} (use +user:rw or -user:x)"))
        for b in expand(spec[1:]):
            out[b] = 1 if spec[0] == "+" else 0
    return out


@dataclass
class Conflict:
    bit: str
    grant: tuple  # (vértice, fuente)
    deny: tuple
    path: list

    def describe(self):
        path = " → ".join(self.path)
        return t(f"{self.bit}: {self.grant[1]} concede en {self.grant[0]}, "
                 f"{self.deny[1]} niega en {self.deny[0]}; camino {path}",
                 f"{self.bit}: {self.grant[1]} grants on {self.grant[0]}, "
                 f"{self.deny[1]} denies on {self.deny[0]}; path {path}")


@dataclass
class SheafReport:
    bits: list
    resolved: dict          # vértice → bit → 1 | 0 | '?' | '!'
    conflicts: list
    h0: dict = field(default_factory=dict)   # bit → dim H^0(K_b)
    h1: dict = field(default_factory=dict)   # bit → dim H^1(K_b)
    enrolled: tuple = ()   # usuarios dentro del haz aunque no tengan bits: todo se les niega

    @property
    def users(self):
        return sorted({b.split(":")[0] for b in self.bits} | set(self.enrolled))

    def mode(self, vertex, user):
        """Cadena tipo 'r-x': letra concedida, '-' negada, '·' indeterminada, '!' conflicto."""
        out = ""
        for c in LETTERS:
            state = self.resolved.get(vertex, {}).get(f"{user}:{c}", "?")
            out += {1: c, 0: "-", "?": "·", "!": "!"}[state]
        return out


def analyze(vertices, relations, govern, values, enrolled=()):
    """
    vertices:  nombres de archivo
    relations: etiqueta → lista de símplices
    govern:    etiqueta → bits que gobierna
    values:    destino → {bit: 0|1}; destino es un archivo o '@etiqueta'
    """
    sources = []  # (vértice, bit, valor, fuente)
    for target, bits in values.items():
        members = (sorted({v for s in relations.get(target[1:], []) for v in s})
                   if target.startswith("@") else [target])
        for v in members:
            for b, val in bits.items():
                sources.append((v, b, val, target))

    all_bits = sorted({b for bs in govern.values() for b in bs}
                      | {s[1] for s in sources})
    resolved = {v: {} for v in vertices}
    report = SheafReport(all_bits, resolved, [], enrolled=tuple(enrolled))

    for b in all_bits:
        simplices = [s for label, bs in govern.items() if b in bs
                     for s in relations.get(label, [])]
        adj = {v: set() for v in vertices}
        for s in simplices:
            for u in s:
                adj.setdefault(u, set()).update(x for x in s if x != u)

        k_b = Complex([(v,) for v in vertices] + simplices)
        betti = k_b.betti(1)
        report.h0[b], report.h1[b] = betti[0], betti[1]

        for comp in _components(adj):
            here = [s for s in sources if s[1] == b and s[0] in comp]
            ones = [s for s in here if s[2] == 1]
            zeros = [s for s in here if s[2] == 0]
            if ones and zeros:
                g, d = ones[0], zeros[0]
                report.conflicts.append(Conflict(
                    b, (g[0], g[3]), (d[0], d[3]), _path(adj, g[0], d[0])))
                state = "!"
            else:
                state = 1 if ones else 0 if zeros else "?"
            for v in comp:
                if v in resolved:
                    resolved[v][b] = state
    return report


def _components(adj):
    seen = set()
    for start in sorted(adj):
        if start in seen:
            continue
        comp, queue = set(), [start]
        while queue:
            v = queue.pop()
            if v not in comp:
                comp.add(v)
                queue.extend(adj[v] - comp)
        seen |= comp
        yield comp


def _path(adj, a, b):
    prev = {a: None}
    queue = deque([a])
    while queue:
        v = queue.popleft()
        if v == b:
            break
        for w in sorted(adj[v]):
            if w not in prev:
                prev[w] = v
                queue.append(w)
    path, v = [], b
    while v is not None:
        path.append(v)
        v = prev[v]
    return path[::-1]
