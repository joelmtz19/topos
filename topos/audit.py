"""Bitácora a prueba de manipulación / tamper-evident audit log.

El problema (hallazgo F3 del red team): la bitácora era un archivo escribible por
todos, así que un agente podía borrarla y tapar sus huellas.

La solución: un demonio que corre como el dueño del mundo recibe las líneas por un
socket y las agrega, encadenadas por hash, a un archivo dentro de `.topos` (modo
700). El agente no puede leer ni truncar ese archivo: sólo mandar líneas. Y el
demonio sella el autor de cada línea con el uid real de quien la manda (SO_PEERCRED),
así que un agente no puede firmar a nombre de otro. `topos verify` revisa la cadena.

The problem (red-team F3): the log was world-writable, so an agent could wipe it.
The fix: a daemon running as the world owner receives lines over a socket and
appends them, hash-chained, to a file inside `.topos` (mode 700). Agents can only
send lines; the daemon stamps each author from the sender's real uid.
"""

import hashlib
import json
import os
import socket
import socketserver
import struct
import time
from pathlib import Path

from .i18n import t

DEFAULT_SOCKET = os.environ.get("TOPOS_AUDIT", "/tmp/topos-audit.sock")
GENESIS = "0" * 64


def _canon(entry):
    """Serialización estable para encadenar: mismas claves, mismo orden, mismo hash."""
    return json.dumps(entry, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def audit_file(meta):
    return Path(meta) / "audit.jsonl"


def entries(meta):
    """Las líneas de la bitácora protegida, como dicts (para leerla o verla)."""
    try:
        for line in audit_file(meta).read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)
    except OSError:
        return


def verify(meta):
    """(problemas, total). Cada problema es (línea, motivo). Lista vacía = cadena intacta."""
    path = audit_file(meta)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], 0
    problems, prev = [], GENESIS
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            problems.append((i, t("no es JSON válido", "not valid JSON")))
            prev = hashlib.sha256(line.encode()).hexdigest()
            continue
        if entry.get("seq") != i:
            problems.append((i, t(f"seq {entry.get('seq')} en la línea {i}: hay un hueco o reorden",
                                  f"seq {entry.get('seq')} at line {i}: gap or reorder")))
        if entry.get("prev") != prev:
            problems.append((i, t("el hash previo no coincide: se editó o se quitó algo antes",
                                  "previous hash mismatch: something before was edited or removed")))
        # El hash encadena la línea tal cual, ya con su seq y su prev dentro.
        prev = hashlib.sha256(line.encode()).hexdigest()
    return problems, len(lines)


class Chain:
    """Va agregando líneas encadenadas; relee el final para retomar tras un reinicio."""

    def __init__(self, meta):
        self.path = audit_file(meta)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seq, self.prev = 0, GENESIS
        try:
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.prev = hashlib.sha256(line.encode()).hexdigest()
                    self.seq += 1
        except OSError:
            pass
        # 600: sólo el dueño; el agente no la lee ni la trunca.
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o600)
            os.close(fd)
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def append(self, entry):
        entry = {**entry, "seq": self.seq, "prev": self.prev}
        line = _canon(entry)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self.prev = hashlib.sha256(line.encode()).hexdigest()
        self.seq += 1


def _peer_uid(conn):
    try:
        creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        _, uid, _ = struct.unpack("3i", creds)
        return uid
    except (OSError, AttributeError):
        return None


def _username(uid):
    try:
        import pwd
        return pwd.getpwuid(uid).pw_name
    except (KeyError, ImportError):
        return str(uid)


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        uid = _peer_uid(self.connection)
        srv = self.server
        # Componentes de confianza (el dueño que monta FUSE, el proxy como root)
        # firman el `agent` que ya trae la línea. Un agente cualquiera no: su línea
        # se firma con su uid real, así no puede hacerse pasar por otro.
        trusted = uid in (None, 0, srv.owner_uid)
        for raw in self.rfile:
            try:
                entry = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            entry.setdefault("t", time.time())
            if not trusted:
                entry["agent"] = _username(uid)
            with srv.lock:
                srv.chain.append(entry)


# En Windows no hay UnixStreamServer; la clase se define igual (sólo se instancia en Linux).
_BASE = getattr(socketserver, "UnixStreamServer", socketserver.BaseServer)


class Server(socketserver.ThreadingMixIn, _BASE):
    daemon_threads = True

    def __init__(self, meta, path):
        if os.path.exists(path):
            os.unlink(path)
        super().__init__(path, Handler)
        os.chmod(path, 0o666)          # cualquiera manda líneas; sólo el demonio agrega
        import threading
        self.lock = threading.Lock()
        self.chain = Chain(meta)
        self.owner_uid = os.getuid() if hasattr(os, "getuid") else 0


def serve(meta, path=DEFAULT_SOCKET):
    with Server(meta, path) as srv:
        srv.serve_forever()


def send(entry, path=DEFAULT_SOCKET):
    """Manda una línea al demonio. True si se entregó; False si no hay demonio."""
    if not hasattr(socket, "AF_UNIX"):
        return False               # Windows: no hay demonio, se usa el archivo llano
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(path)
        s.sendall((json.dumps(entry, ensure_ascii=False) + "\n").encode())
        s.close()
        return True
    except OSError:
        return False
