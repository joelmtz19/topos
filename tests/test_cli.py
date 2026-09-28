import pytest

from topos.cli import main


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOPOS_HOME", raising=False)
    for n in "abcd":
        (tmp_path / f"{n}.txt").write_text(n)
    assert main(["init"]) == 0
    assert main(["add", "a.txt", "b.txt", "c.txt", "d.txt"]) == 0
    return tmp_path


def test_glue_betti_holes(store, capsys):
    main(["glue", "a.txt", "b.txt", "--as", "p"])
    main(["glue", "b.txt", "c.txt", "--as", "q"])
    main(["glue", "a.txt", "c.txt", "--as", "r"])
    capsys.readouterr()
    main(["betti"])
    out = capsys.readouterr().out
    assert "β0 = 2" in out and "β1 = 1" in out
    main(["glue", "a.txt", "b.txt", "c.txt", "--as", "tapa"])
    main(["betti"])
    assert "β1 = 0" in capsys.readouterr().out


def test_perm_roundtrip_with_negative_values(store, capsys):
    main(["glue", "a.txt", "b.txt", "--as", "p"])
    assert main(["perm", "govern", "p", "alice:rw"]) == 0
    assert main(["perm", "set", "a.txt", "+alice:rw"]) == 0
    assert main(["perm", "set", "@p", "-alice:w"]) == 0
    capsys.readouterr()
    assert main(["perm", "check"]) == 2
    assert "alice:w" in capsys.readouterr().out
    main(["perm", "show"])
    assert "r!·" in capsys.readouterr().out


def test_import_tree(tmp_path, monkeypatch, capsys):
    (tmp_path / "src" / "sub").mkdir(parents=True)
    (tmp_path / "src" / "x").write_text("x")
    (tmp_path / "src" / "sub" / "y").write_text("y")
    (tmp_path / "src" / "sub" / "z").write_text("z")
    monkeypatch.chdir(tmp_path)
    main(["init"])
    main(["import", "src"])
    main(["rels"])
    assert "sub: sub∕y+sub∕z" in capsys.readouterr().out
