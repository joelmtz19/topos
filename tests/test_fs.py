"""Operaciones de la vista FUSE llamadas directo, sin montar (sólo Linux)."""

import errno
import os

import pytest

fuse = pytest.importorskip("fuse")

from topos.fuse_view import ToposFS  # noqa: E402
from topos.store import Store  # noqa: E402


@pytest.fixture
def fs(tmp_path, monkeypatch):
    s = Store.init(tmp_path)
    for n in "abc":
        s.add_bytes(n, n.encode())
    s.glue(["a", "b"], "p")
    s.save()
    f = ToposFS(str(tmp_path))
    monkeypatch.setattr(f, "_user", lambda: "alice")
    monkeypatch.setattr(f, "_caller", lambda: (1000, 1000))
    return f


def store(fs):
    return Store(fs.root)


def write(fs, path, data, flags=os.O_WRONLY | os.O_TRUNC):
    fh = fs.open(path, flags)
    fs.write(path, data, 0, fh)
    fs.release(path, fh)


def errno_of(fn, *args):
    with pytest.raises(fuse.FuseOSError) as e:
        fn(*args)
    return e.value.errno


def test_write_changes_content_not_structure(fs):
    write(fs, "/relations/p/a", b"nuevo")
    s = store(fs)
    assert s.cat("a") == b"nuevo" and s.members("p") == ["a", "b"]
    assert fs.getattr("/files/a")["st_size"] == 5


def test_create_in_relation_glues_new_vertex(fs):
    fh = fs.create("/relations/p/d", 0o644)
    fs.write("/relations/p/d", b"hola", 0, fh)
    assert fs.read("/files/d", 4, 0, None) == b"hola"   # visible antes de cerrar
    fs.release("/relations/p/d", fh)
    assert store(fs).members("p") == ["a", "b", "d"]


def test_link_and_unlink_move_membership_only(fs):
    fs.mkdir("/relations/r", 0o755)
    fs.link("/relations/r/c", "/files/c")
    assert store(fs).members("r") == ["c"]
    assert errno_of(fs.rmdir, "/relations/r") == errno.ENOTEMPTY
    fs.unlink("/relations/r/c")
    assert "c" in store(fs).vertices
    fs.rmdir("/relations/r")
    assert "r" not in store(fs).relations
    fs.unlink("/files/c")
    assert "c" not in store(fs).vertices


def test_rename_between_relations_and_atomic_save(fs):
    fs.mkdir("/relations/r", 0o755)
    fs.rename("/relations/p/a", "/relations/r/a")
    s = store(fs)
    assert s.members("p") == ["b"] and s.members("r") == ["a"]
    # guardado atómico: temporal + rename encima conserva el lugar de b
    fh = fs.create("/files/b.tmp", 0o644)
    fs.write("/files/b.tmp", b"B2", 0, fh)
    fs.release("/files/b.tmp", fh)
    fs.rename("/files/b.tmp", "/files/b")
    s = store(fs)
    assert s.cat("b") == b"B2" and "b.tmp" not in s.vertices and s.members("p") == ["b"]
    fs.rename("/relations/r", "/relations/nueva")
    assert store(fs).members("nueva") == ["a"]


def test_sheaf_governs_writes_and_chmod(fs):
    s = store(fs)
    s.govern("p", ["alice:rw"])
    s.set_values("a", ["+alice:r", "-alice:w"])
    s.save()
    assert fs.getattr("/files/b")["st_mode"] & 0o777 == 0o400   # b hereda por el pegado
    assert errno_of(fs.open, "/files/b", os.O_WRONLY) == errno.EACCES
    assert errno_of(fs.unlink, "/files/b") == errno.EACCES
    assert fs.getattr("/files/c")["st_mode"] & 0o777 == 0      # sin sección: se niega
    # alice no puede darse w a sí misma; el dueño del mundo sí puede dársela.
    assert errno_of(fs.chmod, "/files/a", 0o600) == errno.EACCES
    fs._caller = lambda: (os.getuid(), os.getgid())
    fs.chmod("/files/a", 0o600)
    fs._caller = lambda: (1000, 1000)
    assert fs.getattr("/files/b")["st_mode"] & 0o777 == 0o600
    write(fs, "/files/b", b"ya puedo")
    assert store(fs).cat("b") == b"ya puedo"
    fs.chmod("/files/a", 0o400)          # quitarse permisos siempre se vale
    assert fs.getattr("/files/b")["st_mode"] & 0o777 == 0o400


def test_reports_and_star_are_read_only(fs):
    assert errno_of(fs.open, "/betti", os.O_WRONLY) == errno.EROFS
    assert errno_of(fs.open, "/star/a/p/b", os.O_WRONLY) == errno.EROFS
    assert errno_of(fs.mkdir, "/files/x", 0o755) == errno.EPERM


def test_mtimes_follow_writes_and_touch(fs):
    before = fs.getattr("/files/a")["st_mtime"]
    fs.utimens("/files/a", (0, 1_000_000))
    assert fs.getattr("/files/a")["st_mtime"] == 1_000_000
    write(fs, "/files/a", b"otra vez")
    assert fs.getattr("/files/a")["st_mtime"] >= before
    assert fs.getattr("/relations/p")["st_mtime"] == fs.getattr("/files/a")["st_mtime"]
    fs.rename("/files/a", "/files/z")
    assert fs.getattr("/files/z")["st_mtime"] >= before


def test_access_and_owner_match_the_sheaf(fs):
    assert fs.getattr("/files/a")["st_uid"] == 1000
    s = store(fs)
    s.govern("p", ["alice:r"])
    s.set_values("a", ["+alice:r"])
    s.save()
    assert fs.access("/files/b", os.R_OK) == 0
    assert errno_of(fs.access, "/files/b", os.W_OK) == errno.EACCES
    assert errno_of(fs.access, "/star", os.W_OK) == errno.EROFS


def test_enrolled_user_starts_with_nothing(fs):
    s = store(fs)
    s.enroll("alice")
    s.save()
    assert fs.getattr("/files/a")["st_mode"] & 0o777 == 0
    assert errno_of(fs.open, "/files/a", os.O_RDONLY) == errno.EACCES
    fh = fs.create("/files/propio.md", 0o644)      # lo que crea sí es suyo
    fs.write("/files/propio.md", b"mio", 0, fh)
    fs.release("/files/propio.md", fh)
    assert fs.getattr("/files/propio.md")["st_mode"] & 0o777 == 0o600


def test_gluing_cannot_escalate_privileges(fs):
    s = store(fs)
    s.add_bytes("secreto", b"nomina")
    s.create_relation("mia")
    s.glue(["c"], "mia")
    s.govern("mia", ["alice:r"])
    s.set_values("@mia", ["+alice:r"])
    s.enroll("alice")
    s.save()
    assert fs.getattr("/files/secreto")["st_mode"] & 0o777 == 0
    # pegar el secreto en su relación le daría r por extensión de la sección
    assert errno_of(fs.link, "/relations/mia/secreto", "/files/secreto") == errno.EACCES
    assert "secreto" not in store(fs).members("mia")
    assert errno_of(fs.rename, "/relations/p/a", "/relations/mia/a") == errno.EACCES
