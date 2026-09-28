"""A nombre de quien pregunta, y el tope de extracción (sólo Linux).
On behalf of the asker, and the extraction cap (Linux only).

Un chatbot de soporte (bot) puede leer toda la base de clientes para hacer su
trabajo. Cuando atiende a ana, sólo debe ver lo que ana puede ver: sus propios
datos, no los de otros clientes.
"""

import errno
import os

import pytest

fuse = pytest.importorskip("fuse")

from topos.fuse_view import ToposFS  # noqa: E402
from topos.store import Store  # noqa: E402


@pytest.fixture
def fs(tmp_path):
    s = Store.init(tmp_path)
    for n in ("ana.json", "beto.json", "caro.json", "faq.md"):
        s.add_bytes(n, n.encode())
    s.glue(["ana.json", "beto.json", "caro.json"], "customers")
    s.glue(["faq.md"], "public")
    for u in ("bot", "ana"):
        s.enroll(u)
    s.set_values("@customers", ["+bot:r"])
    s.set_values("@public", ["+bot:r", "+ana:r"])
    s.set_values("ana.json", ["+ana:r"])
    s.save()
    f = ToposFS(str(tmp_path))
    f._caller = lambda: (1001, 1001)
    f._user = lambda: "bot"
    f._session = lambda: (1001, 1)
    return f


def op(fs, name, *args):
    return fs(name, *args)          # por __call__, como lo llama FUSE


def denied(fs, name, *args):
    with pytest.raises(fuse.FuseOSError) as e:
        op(fs, name, *args)
    return e.value.errno


def test_the_bot_alone_reads_every_customer(fs):
    for n in ("ana.json", "beto.json", "caro.json"):
        op(fs, "open", f"/files/{n}", os.O_RDONLY)


def test_on_behalf_of_ana_it_only_sees_what_ana_sees(fs):
    assert op(fs, "read", "/as/ana/files/ana.json", 100, 0, None) == b"ana.json"
    op(fs, "open", "/as/ana/files/ana.json", os.O_RDONLY)
    op(fs, "open", "/as/ana/relations/public/faq.md", os.O_RDONLY)
    assert denied(fs, "open", "/as/ana/files/beto.json", os.O_RDONLY) == errno.EACCES
    assert op(fs, "getattr", "/as/ana/files/caro.json")["st_mode"] & 0o777 == 0


def test_the_view_lists_principals_and_does_not_nest(fs):
    assert set(op(fs, "readdir", "/as", None)) >= {"ana", "bot"}
    assert "as" not in op(fs, "readdir", "/as/ana", None)
    assert denied(fs, "getattr", "/as/nadie/files/faq.md") == errno.ENOENT
    assert denied(fs, "getattr", "/as/ana/as/bot/files/beto.json") == errno.ENOENT


def test_cannot_hop_out_of_the_view_by_renaming(fs):
    assert denied(fs, "rename", "/as/ana/files/faq.md", "/files/faq2.md") == errno.EXDEV


def test_extraction_cap_per_session(fs):
    s = Store(fs.root)
    s.set_limit("bot", 2)
    s.save()
    op(fs, "open", "/files/ana.json", os.O_RDONLY)
    op(fs, "open", "/files/beto.json", os.O_RDONLY)
    op(fs, "open", "/files/ana.json", os.O_RDONLY)                     # repetir no cuenta
    assert denied(fs, "open", "/files/caro.json", os.O_RDONLY) == errno.EACCES
    fs._session = lambda: (1001, 2)                                     # otra conversación
    op(fs, "open", "/files/caro.json", os.O_RDONLY)
