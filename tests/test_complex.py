from itertools import combinations

from topos.complex import Complex


def boundary(simplex):
    return Complex(combinations(simplex, len(simplex) - 1))


def test_circle():
    assert Complex([("a", "b"), ("b", "c"), ("a", "c")]).betti(1) == [1, 1]


def test_filled_triangle_is_contractible():
    assert Complex([("a", "b", "c")]).betti(2) == [1, 0, 0]


def test_sphere():
    assert boundary("abcd").betti(2) == [1, 0, 1]


def test_disjoint_points():
    assert Complex([("a",), ("b",)]).betti(1) == [2, 0]


def test_torus():
    # Triangulación de Möbius–Császár con 7 vértices.
    tris = [(i, (i + 1) % 7, (i + 3) % 7) for i in range(7)] + \
           [(i, (i + 2) % 7, (i + 3) % 7) for i in range(7)]
    cx = Complex(tuple(str(v) for v in t) for t in tris)
    assert cx.betti(2) == [1, 2, 1]


def test_projective_plane_over_gf2():
    tris = ["124", "126", "135", "136", "145", "234", "235", "256", "346", "456"]
    assert Complex(tris).betti(2) == [1, 1, 1]


def test_holes_are_cycles():
    h = Complex([("a", "b"), ("b", "c"), ("a", "c"), ("c", "d")]).homology(1)
    (cycle,) = h.cycles[1]
    assert sorted(cycle) == [("a", "b"), ("a", "c"), ("b", "c")]


def test_big_relations_use_the_nerve():
    # Tres relaciones de 40 archivos que se tocan en cadena cerrada: un lazo.
    a = [f"a{i}" for i in range(40)]
    b = [f"b{i}" for i in range(40)]
    c = [f"c{i}" for i in range(40)]
    cx = Complex([a + ["x"], b + ["x", "y"], c + ["y", "z"], ["z", "a0"]])
    h = cx.homology(1)
    assert h.space == "nervio"
    assert h.betti == [1, 1]


def test_remove_takes_cofaces():
    cx = Complex([("a", "b", "c")])
    cx.remove(("a", "b"))
    assert sorted(cx.generators) == [("a", "c"), ("b", "c")]
    assert cx.betti(1) == [1, 0]


def test_star_and_link():
    cx = Complex([("a", "b", "c"), ("a", "d")])
    assert cx.star("a") == [("a", "b", "c"), ("a", "d")]
    assert cx.link("a").generators == [("b", "c"), ("d",)]
