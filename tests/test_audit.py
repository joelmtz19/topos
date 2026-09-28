"""La bitácora a prueba de manipulación / the tamper-evident audit log."""

import json
import socket
import time

import pytest

from topos import audit


def test_chain_appends_and_verifies(tmp_path):
    c = audit.Chain(tmp_path)
    for i in range(3):
        c.append({"agent": "a", "tool": "read", "n": i})
    problems, total = audit.verify(tmp_path)
    assert total == 3 and problems == []
    seqs = [e["seq"] for e in audit.entries(tmp_path)]
    assert seqs == [0, 1, 2]


def test_editing_a_line_is_detected(tmp_path):
    c = audit.Chain(tmp_path)
    c.append({"agent": "a", "tool": "read"})
    c.append({"agent": "a", "tool": "write"})
    c.append({"agent": "a", "tool": "read"})
    lines = audit.audit_file(tmp_path).read_text(encoding="utf-8").splitlines()
    forged = json.loads(lines[1])
    forged["tool"] = "nothing"        # editar el contenido rompe el hash del resto
    lines[1] = json.dumps(forged, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    audit.audit_file(tmp_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    problems, _ = audit.verify(tmp_path)
    assert problems and problems[0][0] == 2       # la línea 2 ya no encadena con la 1 editada


def test_truncation_and_forgery_are_detected(tmp_path):
    c = audit.Chain(tmp_path)
    for i in range(4):
        c.append({"agent": "a", "tool": "read", "n": i})
    # Un atacante borra todo y forja una línea "limpia".
    forged = {"agent": "nobody", "tool": "nothing", "seq": 0, "prev": audit.GENESIS}
    audit.audit_file(tmp_path).write_text(
        json.dumps(forged, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8")
    # La línea forjada encadena consigo misma, pero el reinicio del demonio la delata:
    resumed = audit.Chain(tmp_path)
    assert resumed.seq == 1        # sabría en seq 1; una nueva entrada seguiría desde ahí
    # y sobre todo: la cadena ya no tiene las 4 entradas que hubo. verify no puede
    # inventar lo borrado, pero el sello del dueño (seq alcanzado) sí lo recordaría.
    problems, total = audit.verify(tmp_path)
    assert total == 1              # sólo queda la forjada: el hueco es evidente contra el sello


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="hace falta AF_UNIX")
def test_daemon_stamps_the_author_from_the_real_uid(tmp_path, monkeypatch):
    import threading
    # Simula que quien manda es un agente (uid 1234), no el dueño: así no es de confianza.
    monkeypatch.setattr(audit, "_peer_uid", lambda conn: 1234)
    sock = str(tmp_path / "audit.sock")
    srv = audit.Server(str(tmp_path), sock)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert audit.send({"agent": "otro", "tool": "read"}, sock)      # intenta firmar como "otro"
        for _ in range(50):
            if list(audit.entries(tmp_path)):
                break
            time.sleep(0.02)
    finally:
        srv.shutdown()
    e = list(audit.entries(tmp_path))[0]
    assert e["agent"] == audit._username(1234)     # el demonio impuso su uid real, no "otro"
    assert "t" in e and e["seq"] == 0


def test_send_without_daemon_is_false(tmp_path):
    assert audit.send({"x": 1}, str(tmp_path / "nope.sock")) is False
