"""Planificador topológico: ejecuta los procesos de un programa como hilos reales.

Cada hilo, antes de dar un paso, le pide permiso al monitor. El monitor conoce
el punto del espacio de progreso donde está la ejecución y concede el paso sólo
si el punto siguiente sigue siendo *bueno*: alcanzable y desde el que todavía se
llega al final. Así la ejecución rodea la región prohibida por el lado correcto
y nunca entra a la zona sin retorno. Es evitar deadlocks por geometría, sin
imponer un orden global a los candados.

En modo ingenuo no hay monitor: cada semáforo es un threading.Semaphore real y
un vigilante declara deadlock cuando todos los hilos vivos llevan un rato
bloqueados sin que nadie avance.

Los pasos locales pueden correr comandos:  do imprime: lp informe.pdf
Sin `do`, un paso local sólo tarda un poco (el jitter), como trabajo simulado.
"""

import random
import subprocess
import threading
import time
from dataclasses import dataclass, field

from .progress import ProgressSpace
from .i18n import t


@dataclass
class Outcome:
    finished: bool
    path: list = field(default_factory=list)      # índice de proceso de cada paso
    state: tuple = ()
    waits: int = 0                                # veces que el monitor hizo esperar a alguien
    output: list = field(default_factory=list)    # (proceso, paso, salida del comando)
    error: str = ""


def split_commands(text):
    """Separa las líneas `do NOMBRE: comando` del resto del programa."""
    commands, rest = {}, []
    for raw in text.splitlines():
        line = raw.split("#")[0].strip()
        if line.startswith("do ") and ":" in line:
            name, cmd = line[3:].split(":", 1)
            commands[name.strip()] = cmd.strip()
        else:
            rest.append(raw)
    return commands, "\n".join(rest)


class Runner:
    def __init__(self, program, commands=None, jitter=0.02, seed=None, patience=0.5):
        self.space = ProgressSpace(program)
        self.p = program
        self.commands = commands or {}
        self.jitter = jitter
        self.rng = random.Random(seed)
        self.patience = patience
        _, self.good, _ = self.space.analyze()

    def _work(self, i, k, out):
        kind, _, word = self.p.ops[i][k]
        if kind == "op" and word in self.commands:
            r = subprocess.run(self.commands[word], shell=True, capture_output=True, text=True)
            if r.returncode:
                cmd, err = self.commands[word], r.stderr.strip()
                raise RuntimeError(t(f"{self.p.names[i]}: `{cmd}` salió con {r.returncode}: {err}",
                                     f"{self.p.names[i]}: `{cmd}` exited with {r.returncode}: {err}"))
            out.append((self.p.names[i], word, r.stdout.rstrip()))

    def _pause(self, lock):
        with lock:
            d = self.rng.uniform(0, self.jitter)
        time.sleep(d)

    def run(self, naive=False):
        return self._naive() if naive else self._guided()

    # -- con monitor -------------------------------------------------------

    def _guided(self):
        state = list(self.space.origin)
        cond = threading.Condition()
        res = Outcome(False)
        errors = []

        if self.space.origin not in self.good:
            res.state = self.space.origin
            res.error = t("ninguna ejecución termina: no hay camino que planificar",
                          "no execution finishes: there is no path to schedule")
            return res

        def proc(i):
            try:
                for k in range(self.space.lens[i]):
                    self._pause(cond)
                    with cond:
                        waited = False
                        while True:
                            nxt = self.space.step(tuple(state), i)
                            if nxt in self.good:
                                break
                            waited = True
                            cond.wait()
                        res.waits += waited
                        state[i] += 1
                        res.path.append(i)
                        cond.notify_all()
                    self._work(i, k, res.output)
            except Exception as e:  # noqa: BLE001 — se reporta al final
                errors.append(str(e))

        threads = [threading.Thread(target=proc, args=(i,)) for i in range(len(self.p.names))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        res.state = tuple(state)
        res.finished = res.state == self.space.final and not errors
        res.error = "; ".join(errors)
        return res

    # -- sin monitor -------------------------------------------------------

    def _naive(self):
        sems = {s: threading.Semaphore(self.p.capacity.get(s, 1))
                for steps in self.p.ops for kind, s, _ in steps if s}
        state = list(self.space.origin)
        lock = threading.Lock()
        res = Outcome(False)
        errors = []
        stop = threading.Event()
        blocked = set()
        done = set()

        def advance(i):
            with lock:
                state[i] += 1
                res.path.append(i)

        def proc(i):
            try:
                for k, (kind, sem, _) in enumerate(self.p.ops[i]):
                    self._pause(lock)
                    if kind == "P":
                        with lock:
                            blocked.add(i)
                        while not sems[sem].acquire(timeout=0.05):
                            if stop.is_set():
                                return
                        with lock:
                            blocked.discard(i)
                    elif kind == "V":
                        sems[sem].release()
                    advance(i)
                    self._work(i, k, res.output)
            except Exception as e:  # noqa: BLE001
                errors.append(str(e))
            finally:
                with lock:
                    done.add(i)

        threads = [threading.Thread(target=proc, args=(i,), daemon=True)
                   for i in range(len(self.p.names))]
        for t in threads:
            t.start()
        # Deadlock: todos los que no han terminado esperan un semáforo, y así
        # siguen durante `patience` segundos (un release en camino lo rompería).
        since = None
        while any(t.is_alive() for t in threads):
            time.sleep(0.02)
            with lock:
                alive = set(range(len(threads))) - done
                snapshot = (tuple(state), frozenset(blocked))
                all_blocked = alive and alive <= blocked
            if not all_blocked:
                since = None
                continue
            if since is None or since[1] != snapshot:
                since = (time.monotonic(), snapshot)
            elif time.monotonic() - since[0] > self.patience and not errors:
                stop.set()
                res.error = "deadlock"
                break
        for t in threads:
            t.join(1)
        res.state = tuple(state)
        res.finished = res.state == self.space.final and not errors and not res.error
        if errors:
            res.error = "; ".join(errors)
        return res
