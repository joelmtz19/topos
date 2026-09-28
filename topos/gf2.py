"""Álgebra lineal sobre GF(2).

Un vector es un entero de Python: el bit i es la coordenada i. Sumar es XOR,
así que la eliminación gaussiana cabe en unas líneas y no hace falta numpy.
"""


class Eliminator:
    """Base escalonada incremental: cada pivote es el bit más alto de su vector.

    Junto a cada vector guarda `comb`, la combinación de entradas que lo produjo,
    para poder recuperar núcleos.
    """

    def __init__(self):
        self.pivots = {}

    def reduce(self, v, comb=0):
        while v:
            p = v.bit_length() - 1
            if p not in self.pivots:
                break
            pv, pc = self.pivots[p]
            v ^= pv
            comb ^= pc
        return v, comb

    def add(self, v, comb=0):
        """Agrega v a la base. Devuelve True si era independiente."""
        v, comb = self.reduce(v, comb)
        if v:
            self.pivots[v.bit_length() - 1] = (v, comb)
            return True
        return False


def rank(vectors):
    e = Eliminator()
    return sum(e.add(v) for v in vectors)


def kernel(columns):
    """Base del núcleo de la matriz cuyas columnas son `columns`.

    Cada vector del núcleo se devuelve como entero sobre los índices de columna.
    """
    e = Eliminator()
    ker = []
    for j, col in enumerate(columns):
        v, comb = e.reduce(col, 1 << j)
        if v:
            e.pivots[v.bit_length() - 1] = (v, comb)
        else:
            ker.append(comb)
    return ker


def bits(v):
    """Índices de los bits encendidos de v, en orden."""
    out = []
    while v:
        low = v & -v
        out.append(low.bit_length() - 1)
        v ^= low
    return out
