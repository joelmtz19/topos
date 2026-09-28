"""Flujo de información: las marcas viajan con los datos (sólo Linux).
Information flow: labels travel with the data (Linux only).

alice puede leer finanzas y escribir en trabajo; bob sólo lee trabajo. Cada
operación de alice es legal, pero si copia la nómina a un resumen en trabajo,
bob no debe poder leerlo: es la fuga con permisos legítimos.
"""

import errno
import os

import pytest

fuse = pytest.importorskip("fuse")

from topos.fuse_view import ToposFS  # noqa: E402
from topos.store import Store  # noqa: E402

ALICE, BOB, CAROL = (1001, "alice"), (1002, "bob"), (1003, "carol")


@pytest.fixture
def fs(tmp_path):
    s = Store.init(tmp_path)
    s.add_bytes("payroll", b"Ana 38417")
    s.add_bytes("meeting", b"Ana manda la propuesta")
    s.add_bytes("todo", b"- (vacio)")
    s.glue(["payroll"], "finance")
    s.glue(["meeting", "todo"], "work")
    for user in ("alice", "bob", "carol"):
        s.enroll(user)
    s.set_values("@finance", ["+alice:r", "+carol:r"])
    s.set_values("@work", ["+alice:rw", "+bob:r", "+carol:rw"])
    s.save()
    return ToposFS(str(tmp_path))


def be(fs, who, session=1):
    uid, name = who
    fs._caller = lambda: (uid, uid)
    fs._user = lambda: name
    fs._session = lambda: (uid, session)


def be_owner(fs):
    fs._caller = lambda: (os.getuid(), os.getgid())
    fs._user = lambda: "owner"
    fs._session = lambda: (os.getuid(), 0)


def read(fs, path):
    fs.open(path, os.O_RDONLY)
    return fs.read(path, 1 << 20, 0, None)


def write_new(fs, path, data):
    fh = fs.create(path, 0o644)
    fs.write(path, data, 0, fh)
    fs.release(path, fh)


def denied(fn, *args):
    with pytest.raises(fuse.FuseOSError) as e:
        fn(*args)
    return e.value.errno == errno.EACCES


def test_copying_payroll_into_work_does_not_leak_it(fs):
    be(fs, ALICE)
    assert read(fs, "/relations/finance/payroll") == b"Ana 38417"
    write_new(fs, "/relations/work/summary", b"Ana gana 38417")
    assert Store(fs.root).sources("summary") == {"payroll"}

    be(fs, BOB)
    assert read(fs, "/relations/work/todo") == b"- (vacio)"      # lo demás de trabajo, sí
    assert fs.getattr("/files/summary")["st_mode"] & 0o400 == 0
    assert denied(fs.open, "/relations/work/summary", os.O_RDONLY)

    be(fs, ALICE)
    assert read(fs, "/files/summary") == b"Ana gana 38417"      # quien lee la fuente, lee la copia


def test_a_session_that_read_nothing_secret_leaves_no_mark(fs):
    be(fs, ALICE, session=1)
    read(fs, "/files/payroll")
    be(fs, ALICE, session=2)                                     # otra terminal / otro proceso
    write_new(fs, "/relations/work/notes", b"sin secretos")
    assert Store(fs.root).sources("notes") == set()
    be(fs, BOB)
    assert read(fs, "/files/notes") == b"sin secretos"


def test_marks_are_transitive(fs):
    be(fs, ALICE)
    read(fs, "/files/payroll")
    write_new(fs, "/relations/work/summary", b"38417")
    be(fs, CAROL)                                               # carol puede leer finanzas
    read(fs, "/files/summary")
    write_new(fs, "/relations/work/digest", b"resumen del resumen")
    assert Store(fs.root).sources("digest") == {"summary", "payroll"}
    be(fs, BOB)
    assert denied(fs.open, "/files/digest", os.O_RDONLY)


def test_atomic_save_keeps_the_marks(fs):
    be(fs, ALICE)
    read(fs, "/files/payroll")
    write_new(fs, "/relations/work/summary.tmp", b"38417")
    fs.rename("/relations/work/summary.tmp", "/relations/work/todo")   # como `sed -i`
    assert Store(fs.root).sources("todo") == {"payroll"}
    be(fs, BOB)
    assert denied(fs.open, "/files/todo", os.O_RDONLY)


def test_only_the_owner_writes_clean_and_declassifies(fs):
    be_owner(fs)
    read(fs, "/files/payroll")
    write_new(fs, "/relations/work/public", b"cifra aprobada")
    assert Store(fs.root).sources("public") == set()            # el dueño no se marca

    be(fs, ALICE)
    read(fs, "/files/payroll")
    write_new(fs, "/relations/work/summary", b"38417")
    s = Store(fs.root)
    s.declassify("summary")
    s.save()
    be(fs, BOB)
    assert read(fs, "/files/summary") == b"38417"


def test_deleting_the_source_does_not_release_the_copy(fs):
    be(fs, ALICE)
    read(fs, "/files/payroll")
    write_new(fs, "/relations/work/summary", b"38417")
    s = Store(fs.root)
    s.remove_vertex("payroll")
    s.add_bytes("payroll", b"otro archivo con el mismo nombre")   # no hereda el lugar de la fuente
    s.set_values("payroll", ["+bob:r"])
    s.save()
    be(fs, BOB)
    assert denied(fs.open, "/files/summary", os.O_RDONLY)
    be(fs, ALICE)
    assert denied(fs.open, "/files/summary", os.O_RDONLY)       # ni siquiera quien la escribió
