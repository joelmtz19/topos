"""El planificador topológico como servicio: coordina procesos independientes.

`topos run` protege los hilos de un solo programa. Aquí cada proceso es un
programa aparte (otra terminal, otro usuario) que se conecta a un socket Unix,
declara su plan (la misma sintaxis: P(s), V(s), pasos locales) y antes de cada
paso pide permiso. El demonio es a la vez los semáforos y el monitor: con los
planes de todos los procesos conectados arma el espacio de progreso y sólo
concede pasos que dejan la ejecución en la región buena.

Cuando un proceso entra o sale (o se cae: el socket se cierra) el espacio se
rearma. Si se cae con semáforos tomados, se liberan, porque ya no ocupa ningún
punto del espacio.

Protocolo: una línea JSON por mensaje.
    → {"op": "join", "name": "A", "plan": ["P(disco)", "imprime", …], "capacity": {…}}
    ← {"id": 3, "name": "A"}
    → {"op": "step"}            ← {"k": 0, "waited": false}   (bloquea hasta que toca)
    → {"op": "status"}          ← {"procs": […], "good": true}
"""

import json
import os
import socketserver
import threading

from .progress import OP, Program, ProgressSpace
from .i18n import t

DEFAULT_SOCKET = os.environ.get("TOPOS_SCHED", "/tmp/topos-sched.sock")
MAX_POINTS = 2_000_000


def plan_steps(words):
    steps = []
    for w in words:
        m = OP.match(w)
        steps.append((m[1], m[2], w) if m else ("op", None, w))
    return steps


class Scheduler:
    def __init__(self):
        self.cond = threading.Condition()
        self.procs = {}          # id → {"name", "steps", "pos"}
        self.capacity = {}
        self.next_id = 1
        self.good = set()
        self.order = []

    # Todo lo que sigue se llama con self.cond tomado.

    def _rebuild(self):
        self.order = sorted(self.procs)
        if not self.order:
            self.good = set()
            return
        points = 1
        for i in self.order:
            points *= len(self.procs[i]["steps"]) + 1
        if points > MAX_POINTS:
            raise ValueError(t(f"el espacio de progreso tendría {points} puntos; demasiados",
                                 f"the progress space would have {points} points; too many"))
        program = Program(self.capacity, [self.procs[i]["name"] for i in self.order],
                          [self.procs[i]["steps"] for i in self.order])
        self.space = ProgressSpace(program)
        _, self.good, _ = self.space.analyze()
        self.cond.notify_all()

    def _state(self):
        return tuple(self.procs[i]["pos"] for i in self.order)

    def join(self, name, words, capacity):
        steps = plan_steps(words)
        with self.cond:
            for sem, n in capacity.items():
                self.capacity.setdefault(sem, int(n))
            names = {p["name"] for p in self.procs.values()}
            pid = self.next_id
            self.next_id += 1
            unique = name if name not in names else f"{name}#{pid}"
            self.procs[pid] = {"name": unique, "steps": steps, "pos": 0}
            try:
                self._rebuild()
            except Exception:
                del self.procs[pid]
                self._rebuild()
                raise
            return pid, unique

    def step(self, pid):
        with self.cond:
            p = self.procs[pid]
            if p["pos"] >= len(p["steps"]):
                raise ValueError(t("ese proceso ya terminó su plan", "that process already finished its plan"))
            waited = False
            while True:
                i = self.order.index(pid)
                nxt = self.space.step(self._state(), i)
                if nxt in self.good:
                    break
                waited = True
                self.cond.wait()
            k = p["pos"]
            p["pos"] += 1
            self.cond.notify_all()
            return k, waited

    def leave(self, pid):
        with self.cond:
            if self.procs.pop(pid, None) is not None:
                self._rebuild()

    def status(self):
        with self.cond:
            procs = []
            for i in self.order:
                p = self.procs[i]
                k = p["pos"]
                nxt = p["steps"][k][2] if k < len(p["steps"]) else t("(terminó)", "(finished)")
                procs.append({"id": i, "name": p["name"], "pos": k,
                              "len": len(p["steps"]), "next": nxt})
            state = self._state()
            return {"procs": procs,
                    "describe": self.space.describe_state(state) if self.order else "",
                    "good": state in self.good if self.order else True}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        sched, pid = self.server.sched, None
        try:
            for line in self.rfile:
                msg = json.loads(line)
                try:
                    if msg["op"] == "join":
                        pid, name = sched.join(msg["name"], msg["plan"], msg.get("capacity", {}))
                        reply = {"id": pid, "name": name}
                    elif msg["op"] == "step" and pid is not None:
                        k, waited = sched.step(pid)
                        reply = {"k": k, "waited": waited}
                    elif msg["op"] == "status":
                        reply = sched.status()
                    else:
                        reply = {"error": f"no entiendo {msg!r}"}
                except (ValueError, KeyError) as e:
                    reply = {"error": str(e)}
                self.wfile.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()
        finally:
            if pid is not None:
                sched.leave(pid)


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path):
        if os.path.exists(path):
            os.unlink(path)
        super().__init__(path, Handler)
        os.chmod(path, 0o666)   # cualquier usuario del sistema puede coordinarse aquí
        self.sched = Scheduler()


def serve(path=DEFAULT_SOCKET):
    with Server(path) as srv:
        srv.serve_forever()


class Client:
    def __init__(self, path=DEFAULT_SOCKET):
        import socket
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.f = self.sock.makefile("rwb")

    def call(self, **msg):
        self.f.write((json.dumps(msg) + "\n").encode())
        self.f.flush()
        reply = json.loads(self.f.readline())
        if "error" in reply:
            raise ValueError(reply["error"])
        return reply

    def close(self):
        self.sock.close()
