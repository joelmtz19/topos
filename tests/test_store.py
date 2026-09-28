import pytest

from topos.store import Store, StoreError


@pytest.fixture
def s(tmp_path):
    s = Store.init(tmp_path)
    for n in "abc":
        s.add_bytes(n, n.encode())
    s.glue(["a", "b"], "p")
    s.glue(["b", "c"], "q")
    return s


def test_rename_vertex_keeps_relations_and_sheaf(s):
    s.govern("p", ["alice:r"])
    s.set_values("a", ["+alice:r"])
    s.rename_vertex("a", "z")
    assert s.members("p") == ["b", "z"]
    assert s.cat("z") == b"a"
    assert s.sheaf().resolved["b"]["alice:r"] == 1


def test_unglue_touches_only_one_relation(s):
    s.unglue("q", "b")
    assert s.members("q") == ["c"]
    assert s.members("p") == ["a", "b"]


def test_empty_relation_then_glue(s):
    s.create_relation("vacia")
    assert s.members("vacia") == []
    s.glue(["a"], "vacia")
    assert s.members("vacia") == ["a"]
    with pytest.raises(StoreError):
        s.create_relation("p")


def test_rename_relation_carries_govern_and_values(s):
    s.govern("p", ["bob:w"])
    s.set_values("@p", ["-bob:w"])
    s.rename_relation("p", "par")
    assert "p" not in s.relations and s.members("par") == ["a", "b"]
    assert s.state["govern"]["par"] == ["bob:w"]
    assert "@par" in s.state["values"]


def test_removing_a_file_leaves_unrelated_relations_alone(s):
    s.create_relation("vacia")
    s.glue(["c"], "suelto")
    s.remove_vertex("a")
    assert "vacia" in s.relations and s.members("suelto") == ["c"]
    assert s.members("p") == ["b"] or "p" not in s.relations
