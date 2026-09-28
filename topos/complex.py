"""Complejos simpliciales finitos y su homología sobre GF(2).

Un complejo se guarda por sus generadores: los símplices maximales. Las caras se
derivan bajo demanda y sólo hasta la dimensión que hace falta, porque una
relación entre 30 archivos tiene 2^30 caras y no cabe en memoria.

Cuando el esqueleto primal sale caro, la homología se calcula en el nervio de
los generadores. Cada generador es un símplice cerrado (contráctil) y la
intersección de dos es una cara o vacía, así que por el teorema del nervio
ambos espacios tienen el mismo tipo de homotopía y la misma homología.
"""

from dataclasses import dataclass, field
from itertools import combinations
from math import comb

from . import gf2

Simplex = tuple


def simplex(vertices):
    s = tuple(sorted(set(vertices)))
    if not s:
        raise ValueError("un símplice necesita al menos un vértice")
    return s


def token(s):
    """Nombre legible de un símplice: a+b+c."""
    return "+".join(s)


class Complex:
    def __init__(self, generators=()):
        self._gens = set()
        for g in generators:
            self.add(g)

    # -- estructura --------------------------------------------------------

    def add(self, g):
        s = simplex(g)
        fs = set(s)
        if any(fs <= set(h) for h in self._gens):
            return
        self._gens = {h for h in self._gens if not set(h) <= fs}
        self._gens.add(s)

    def remove(self, g):
        """Quita el símplice g y todas sus cocaras (el resto sigue siendo complejo)."""
        s = simplex(g)
        fs = set(s)
        survivors = []
        for h in self._gens:
            if fs <= set(h):
                # Lo que queda de h sin g lo generan las caras h - v con v en g.
                survivors += [tuple(x for x in h if x != v) for v in s]
            else:
                survivors.append(h)
        self._gens = set()
        for h in survivors:
            if h:
                self.add(h)

    @property
    def generators(self):
        return sorted(self._gens, key=lambda s: (-len(s), s))

    @property
    def vertices(self):
        return sorted({v for g in self._gens for v in g})

    def __contains__(self, g):
        fs = set(simplex(g))
        return any(fs <= set(h) for h in self._gens)

    def dim(self):
        return max((len(g) - 1 for g in self._gens), default=-1)

    def star(self, v):
        """Símplices maximales que contienen a v: la vecindad abierta mínima de v."""
        return [g for g in self.generators if v in g]

    def link(self, v):
        return Complex(tuple(x for x in g if x != v) for g in self.star(v) if len(g) > 1)

    def skeleton(self, k):
        """Todas las caras de dimensión <= k, agrupadas por dimensión."""
        faces = [set() for _ in range(k + 1)]
        for g in self._gens:
            for d in range(min(k, len(g) - 1) + 1):
                faces[d].update(combinations(g, d + 1))
        return [sorted(f) for f in faces]

    def cost(self, k):
        """Cota superior del número de caras de dimensión <= k."""
        return sum(comb(len(g), d + 1) for g in self._gens for d in range(k + 1))

    def nerve(self):
        """Nervio del recubrimiento por generadores: vértices = generadores."""
        gens = self.generators
        names = {g: token(g) for g in gens}
        covers = {}
        for g in gens:
            for v in g:
                covers.setdefault(v, []).append(names[g])
        return Complex(covers.values()), names

    # -- homología ---------------------------------------------------------

    def homology(self, maxdim=1, namer=None, basis=True):
        """Números de Betti (y ciclos representantes) hasta `maxdim`.

        `namer` traduce un generador a un nombre cuando se calcula en el nervio.
        """
        if not self._gens:
            return Homology([0] * (maxdim + 1), {}, "primal")
        nerve, names = self.nerve()
        # El primal se lee mejor (ciclos de archivos); el nervio sólo si ahorra mucho.
        if 4 * nerve.cost(maxdim + 1) < self.cost(maxdim + 1):
            if namer:
                rename = {names[g]: namer(g) for g in names}
                nerve = Complex(tuple(rename[x] for x in s) for s in nerve.generators)
            betti, cycles = _homology(nerve, maxdim, basis)
            return Homology(betti, cycles, "nervio")
        betti, cycles = _homology(self, maxdim, basis)
        return Homology(betti, cycles, "primal")

    def betti(self, maxdim=1):
        return self.homology(maxdim, basis=False).betti


@dataclass
class Homology:
    betti: list
    cycles: dict = field(default_factory=dict)
    space: str = "primal"

    @property
    def euler(self):
        return sum((-1) ** k * b for k, b in enumerate(self.betti))


def _homology(cx, maxdim, want_basis):
    sk = cx.skeleton(maxdim + 1)
    index = [{s: i for i, s in enumerate(level)} for level in sk]

    def boundary(k):
        if k == 0:
            return [0] * len(sk[0])
        rows = index[k - 1]
        return [sum(1 << rows[f] for f in combinations(s, k)) for s in sk[k]]

    cols = [boundary(k) for k in range(maxdim + 2)]
    ranks = [gf2.rank(c) for c in cols]
    betti = [len(sk[k]) - ranks[k] - ranks[k + 1] for k in range(maxdim + 1)]

    cycles = {}
    if want_basis:
        for k in range(maxdim + 1):
            if not betti[k]:
                continue
            images = gf2.Eliminator()
            for c in cols[k + 1]:
                images.add(c)
            reps = []
            for z in gf2.kernel(cols[k]):
                if images.add(z):
                    reps.append([sk[k][i] for i in gf2.bits(z)])
            cycles[k] = reps
    return betti, cycles
