from pathlib import Path

from topos.progress import ProgressSpace, parse

EJ = Path(__file__).parent.parent / "ejemplos"


def space(name):
    return ProgressSpace(parse((EJ / name).read_text(encoding="utf-8")))


def test_opposite_lock_order_deadlocks():
    s = space("cena.txt")
    reach, good, deadlocks = s.analyze()
    assert deadlocks == [(1, 1)]
    assert "A tiene disco" in s.describe_state((1, 1))
    assert s.final in reach


def test_same_lock_order_has_two_classes():
    s = space("ordenado.txt")
    _, _, deadlocks = s.analyze()
    assert deadlocks == []
    classes = s.classes()
    assert len(classes) == 2
    orders = {s.describe_path(c[0])[1] for c in classes}
    assert any("disco: A → B" in o for o in orders)
    assert any("disco: B → A" in o for o in orders)


def test_capacity_two_leaves_one_class():
    s = space("semaforo2.txt")
    assert s.analyze()[2] == []
    assert len(s.classes()) == 1


def test_release_without_take_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        ProgressSpace(parse("proc A: V(x)"))


def test_english_examples_match_the_spanish_ones():
    for es, en in (("cena.txt", "dining.txt"), ("ordenado.txt", "ordered.txt"),
                   ("semaforo2.txt", "pool2.txt")):
        a, b = space(es), space(en)
        assert a.analyze()[2] == b.analyze()[2]
        assert len(a.classes()) == len(b.classes())
