from topos.sheaf import analyze, parse_values


def test_values_propagate_along_governed_relations():
    r = analyze(["a", "b", "c"], {"proy": [("a", "b")]},
                {"proy": ["alice:r"]}, {"a": parse_values(["+alice:r"])})
    assert r.resolved["b"]["alice:r"] == 1
    assert r.resolved["c"]["alice:r"] == "?"
    assert not r.conflicts


def test_conflict_is_witnessed_by_a_path():
    rels = {"p": [("a", "b")], "q": [("b", "c")]}
    gov = {"p": ["alice:w"], "q": ["alice:w"]}
    vals = {"a": parse_values(["+alice:w"]), "@q": parse_values(["-alice:w"])}
    r = analyze(["a", "b", "c"], rels, gov, vals)
    (c,) = r.conflicts
    assert c.bit == "alice:w"
    assert c.path[0] == "a" and c.path[-1] in {"b", "c"}
    assert r.mode("b", "alice") == "·!·"


def test_cohomology_counts_components_and_loops():
    rels = {"p": [("a", "b")], "q": [("b", "c")], "s": [("a", "c")]}
    gov = {k: ["bob:x"] for k in rels}
    r = analyze(["a", "b", "c", "d"], rels, gov, {})
    assert r.h0["bob:x"] == 2      # {a,b,c} y {d}
    assert r.h1["bob:x"] == 1      # el triángulo hueco
