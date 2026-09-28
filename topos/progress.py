"""Procesos como caminos: grafos de progreso de Dijkstra y topología dirigida.

Un programa concurrente es una lista de procesos, cada uno una secuencia de
operaciones P(s) (tomar semáforo), V(s) (soltarlo) o pasos locales. El estado
global es un punto de la rejilla ∏[0, n_i]; los estados donde un semáforo
excede su capacidad forman la región prohibida. Una ejecución es un camino
dirigido del origen al final que evita esa región.

- Deadlock: estado alcanzable, no final, sin ningún paso posible.
- Zona insegura: estados alcanzables desde los que ya no se llega al final.
- Dos ejecuciones son dihomotópicas si una se deforma en la otra volteando
  pasos independientes dentro de cuadrados permitidos (aproximación cúbica:
  un cuadrado es permitido si sus cuatro esquinas lo son). Las clases son las
  maneras realmente distintas de rodear la región prohibida.
"""

import re
from collections import Counter, deque
from dataclasses import dataclass
from itertools import islice

OP = re.compile(r"^(P|V)\(([\w.-]+)\)$")


@dataclass
class Program:
    capacity: dict
    names: list
    ops: list  # por proceso: [(tipo, semáforo | None, texto)]


def parse(text):
    capacity, names, ops = {}, [], []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#")[0].strip()
        if not line:
            continue
        head, *rest = line.split()
        if head == "sem" and len(rest) == 2:
            capacity[rest[0]] = int(rest[1])
        elif head == "proc" and ":" in line:
            name, body = line[4:].split(":", 1)
            steps = []
            for word in body.split():
                m = OP.match(word)
                steps.append((m[1], m[2], word) if m else ("op", None, word))
            names.append(name.strip())
            ops.append(steps)
        else:
            raise ValueError(f"línea {n}: no entiendo {raw.strip()!r}")
    if not names:
        raise ValueError("el programa no tiene procesos")
    return Program(capacity, names, ops)


class TooManyPaths(Exception):
    pass


class ProgressSpace:
    def __init__(self, program):
        self.p = program
        self.lens = tuple(len(o) for o in program.ops)
        self.origin = tuple(0 for _ in self.lens)
        self.final = self.lens
        self.hold = []
        for name, steps in zip(program.names, program.ops):
            held, table = Counter(), [Counter()]
            for kind, sem, _ in steps:
                if kind == "P":
                    held[sem] += 1
                elif kind == "V":
                    if not held[sem]:
                        raise ValueError(f"{name} suelta {sem} sin haberlo tomado")
                    held[sem] -= 1
                table.append(+held)
            self.hold.append(table)

    def allowed(self, s):
        total = Counter()
        for i, k in enumerate(s):
            total.update(self.hold[i][k])
        return all(n <= self.p.capacity.get(sem, 1) for sem, n in total.items())

    def step(self, s, i):
        return s[:i] + (s[i] + 1,) + s[i + 1:]

    def successors(self, s):
        for i, k in enumerate(s):
            if k < self.lens[i]:
                t = self.step(s, i)
                if self.allowed(t):
                    yield i, t

    def analyze(self):
        reach = {self.origin}
        queue = deque([self.origin])
        while queue:
            for _, t in self.successors(queue.popleft()):
                if t not in reach:
                    reach.add(t)
                    queue.append(t)

        good = set()
        if self.final in reach:
            good.add(self.final)
            queue.append(self.final)
        while queue:
            s = queue.popleft()
            for i, k in enumerate(s):
                if k:
                    p = s[:i] + (k - 1,) + s[i + 1:]
                    if p in reach and p not in good:
                        good.add(p)
                        queue.append(p)

        deadlocks = sorted(s for s in reach
                           if s != self.final and not any(self.successors(s)))
        self._safe = good
        return reach, good, deadlocks

    def paths(self):
        """Todas las ejecuciones completas, como tuplas de índices de proceso."""
        if not hasattr(self, "_safe"):
            self.analyze()
        stack = [(self.origin, ())]
        while stack:
            s, path = stack.pop()
            if s == self.final:
                yield path
                continue
            for i, t in self.successors(s):
                if t in self._safe:
                    stack.append((t, path + (i,)))

    def classes(self, max_paths=200_000):
        """Clases de dihomotopía: lista de listas de caminos."""
        paths = list(islice(self.paths(), max_paths + 1))
        if len(paths) > max_paths:
            raise TooManyPaths(f"más de {max_paths} ejecuciones; sube --max-paths")
        parent = {p: p for p in paths}

        def find(p):
            while parent[p] != p:
                parent[p] = parent[parent[p]]
                p = parent[p]
            return p

        for path in paths:
            s = self.origin
            for t in range(len(path) - 1):
                a, b = path[t], path[t + 1]
                if a != b and self.allowed(self.step(s, b)):
                    flipped = path[:t] + (b, a) + path[t + 2:]
                    parent[find(path)] = find(flipped)
                s = self.step(s, a)

        groups = {}
        for p in paths:
            groups.setdefault(find(p), []).append(p)
        return sorted(groups.values(), key=lambda g: min(g))

    # -- descripciones legibles -------------------------------------------

    def describe_state(self, s):
        parts = []
        for i, k in enumerate(s):
            name = self.p.names[i]
            held = ", ".join(sorted(self.hold[i][k])) or "nada"
            if k < self.lens[i]:
                parts.append(f"{name} tiene {held} y espera {self.p.ops[i][k][2]}")
            else:
                parts.append(f"{name} terminó")
        return "; ".join(parts)

    def describe_path(self, path):
        """Orden en que cada semáforo se toma: el invariante que distingue clases."""
        pos = list(self.origin)
        order = {}
        for i in path:
            kind, sem, _ = self.p.ops[i][pos[i]]
            if kind == "P":
                order.setdefault(sem, []).append(self.p.names[i])
            pos[i] += 1
        runs, last = [], None
        for i in path:
            name = self.p.names[i]
            if runs and last == name:
                runs[-1][1] += 1
            else:
                runs.append([name, 1])
            last = name
        schedule = " ".join(f"{n}×{c}" if c > 1 else n for n, c in runs)
        sems = "; ".join(f"{s}: {' → '.join(o)}" for s, o in sorted(order.items()))
        return schedule, sems
