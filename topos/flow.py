"""Sesiones y lo que han leído / sessions and what they have read.

El flujo de información necesita saber qué leyó cada sesión antes de decidir a
dónde puede ir lo que escribe (un archivo) o lo que envía (un destino de red).
La vista FUSE lo anota y el proxy de red lo consulta, así que vive en disco:
`.topos/sessions.json`. Una sesión es uid + id de sesión de Linux (lo que
comparte una terminal y sus hijos), y la clave lleva el boot_id del kernel para
que un sid reciclado después de reiniciar no herede nada.

Information flow needs what each session has read before deciding where its
writes (a file) or its sends (a network destination) may go. The FUSE view
records it and the network proxy reads it, so it lives on disk.
"""

import json
import os
import time
from pathlib import Path


def boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "sin-boot"


def session_of(pid):
    """El id de sesión de Linux de un proceso (campo 6 de /proc/PID/stat)."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            return int(f.read().rsplit(")", 1)[1].split()[3])
    except (OSError, IndexError, ValueError):
        return pid


class Quota:
    """Archivos distintos que un agente (uid) abrió en la hora. Va por uid, no por sesión,
    así abrir una sesión nueva por archivo (setsid) no reinicia la cuenta — ése era el
    hueco: el tope de extracción por sesión se saltaba con un `setsid` por lectura.

    Distinct files an agent (uid) opened this hour. Keyed by uid, not session, so spawning
    a fresh session per read cannot reset it."""

    def __init__(self, meta, clock=time.time):
        self.path = Path(meta) / "opens.json"
        self.boot = boot_id()
        self.clock = clock

    def _key(self, uid):
        return f"{self.boot}:{uid}:{int(self.clock() // 3600)}"

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        hour = int(self.clock() // 3600)
        return {k: v for k, v in data.items()
                if k.startswith(self.boot + ":") and int(k.rsplit(":", 1)[1]) >= hour - 1}

    def allow(self, uid, vertex, cap):
        """(permitido, cuántos van). Cuenta `vertex` si es nuevo esta hora y cabe en el tope."""
        data = self._load()
        key = self._key(uid)
        seen = set(data.get(key, ()))
        if vertex in seen:
            return True, len(seen)
        if len(seen) >= cap:
            return False, len(seen)
        seen.add(vertex)
        data[key] = sorted(seen)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self.path)
        return True, len(seen)


class Sessions:
    def __init__(self, meta):
        self.path = Path(meta) / "sessions.json"
        self.boot = boot_id()

    def _key(self, uid, sid):
        return f"{self.boot}:{uid}:{sid}"

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        # Lo de arranques anteriores ya no corresponde a ningún proceso vivo.
        return {k: v for k, v in data.items() if k.startswith(self.boot + ":")}

    @staticmethod
    def _entry(v):
        # Formato viejo: una lista de lo leído. Nuevo: {"read": […], "opened": […]}.
        return v if isinstance(v, dict) else {"read": list(v), "opened": []}

    def get(self, uid, sid):
        """Todo lo que le fluyó a la sesión: lo que abrió y las fuentes de eso."""
        return set(self._entry(self._load().get(self._key(uid, sid), [])).get("read", ()))

    def opened(self, uid, sid):
        """Sólo los archivos que la sesión abrió para leer (para el tope de extracción)."""
        return set(self._entry(self._load().get(self._key(uid, sid), [])).get("opened", ()))

    def of_user(self, uid):
        """Todo lo que leyó cualquier sesión de uid: el peor caso, si no se sabe cuál es."""
        prefix = f"{self.boot}:{uid}:"
        out = set()
        for k, v in self._load().items():
            if k.startswith(prefix):
                out |= set(self._entry(v).get("read", ()))
        return out

    def add(self, uid, sid, vertices, opened=None):
        data = self._load()
        key = self._key(uid, sid)
        old = self._entry(data.get(key, []))
        read = set(old.get("read", ())) | set(vertices)
        opens = set(old.get("opened", ())) | ({opened} if opened else set())
        if read == set(old.get("read", ())) and opens == set(old.get("opened", ())):
            return
        data[key] = {"read": sorted(read), "opened": sorted(opens)}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)
