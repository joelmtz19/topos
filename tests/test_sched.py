"""El demonio coordinando procesos independientes de verdad (sólo Linux)."""

import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

if not hasattr(socket, "AF_UNIX"):
    pytest.skip("hace falta un socket Unix", allow_module_level=True)

from topos.sched import Client, Scheduler  # noqa: E402

EJ = Path(__file__).parent.parent / "ejemplos"


def test_scheduler_refuses_the_trapped_corner():
    s = Scheduler()
    a, _ = s.join("A", "P(disco) P(impresora) V(impresora) V(disco)".split(), {})
    b, _ = s.join("B", "P(impresora) P(disco) V(disco) V(impresora)".split(), {})
    s.step(a)                      # A toma disco
    i = s.order.index(b)
    assert s.space.step(s._state(), i) not in s.good   # B no puede tomar impresora ahora
    s.leave(a)                     # A se cae con disco tomado: se libera
    assert s.step(b) == (0, False)


def test_independent_processes_never_deadlock(tmp_path):
    sock = str(tmp_path / "s.sock")
    topos = [sys.executable, "-m", "topos"]
    server = subprocess.Popen([*topos, "sched", "serve", "--socket", sock])
    try:
        for _ in range(50):
            if Path(sock).exists():
                break
            time.sleep(0.05)
        for _ in range(5):
            procs = [subprocess.Popen([*topos, "sched", "run", n, str(EJ / "filosofos.txt"),
                                       "--socket", sock], stdout=subprocess.PIPE, text=True)
                     for n in ("Ana", "Beto", "Caro")]
            outs = [p.communicate(timeout=20)[0] for p in procs]
            assert all(p.returncode == 0 for p in procs)
            assert "Ana come" in "".join(outs)
        c = Client(sock)
        assert c.call(op="status")["procs"] == []
        c.close()
    finally:
        server.kill()
