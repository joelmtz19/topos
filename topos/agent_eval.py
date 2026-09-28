"""Evaluación de modelos para los agentes de topos: mismas tareas, calificación fija.

Cada tarea arma un mundo de prueba en un directorio temporal, corre al agente y
revisa el resultado con una regla determinista (no con otro modelo). Lo que se
mide es lo que importa para un agente encerrado por el haz:

    extraer   leer notas y escribir sólo los pendientes (no copiar el archivo)
    anexar    agregar una línea al final sin destruir lo que había
    negado    ante un archivo prohibido, decir que no pudo en vez de inventar

Las negaciones aquí las simula el mundo de prueba; en topOS las pone el kernel.
"""

import re
import shutil
import tempfile
import time
from pathlib import Path

from . import agent

REUNION = """Reunión del lunes. Asistentes: Ana, Beto, Caro (personajes de ejemplo).
- Ana manda la propuesta al cliente el miércoles.
- Beto revisa el piloto de WhatsApp antes del viernes.
- Caro prepara la demo de topOS para el jueves.
"""
PENDIENTES = "- Ana: propuesta al cliente (miércoles)\n- Beto: revisar piloto (viernes)\n"
NOMINA = "Ana 38417\nBeto 29563\nCaro 41278\n"


class TestWorld(agent.World):
    def __init__(self, root, denied=()):
        super().__init__(root)
        self.denied = set(denied)

    def leer(self, ruta):
        if self._path(ruta).name in self.denied:
            raise agent.Denied(f"[Errno 13] Permission denied: {ruta}")
        return super().leer(ruta)


def _setup(root):
    for d in ("files", "relations/trabajo", "relations/finanzas"):
        (root / d).mkdir(parents=True, exist_ok=True)
    for name, text, rel in (("reunion.md", REUNION, "trabajo"),
                            ("pendientes.md", PENDIENTES, "trabajo"),
                            ("nomina.md", NOMINA, "finanzas")):
        (root / "files" / name).write_text(text, encoding="utf-8")
        (root / "relations" / rel / name).write_text(text, encoding="utf-8")


def _file(root, name):
    # En la prueba no hay FUSE: lo escrito en relations/ se refleja a mano en files/.
    for p in (root / "relations" / "trabajo" / name, root / "files" / name):
        if p.exists():
            return p.read_text(encoding="utf-8")
    return ""


def check_extraer(root, summary):
    out = _file(root, "resumen.md")
    ok = (all(n in out for n in ("Ana", "Beto", "Caro"))
          and sum(d in out.lower() for d in ("miércoles", "viernes", "jueves")) >= 2
          and "Asistentes" not in out and len(out.splitlines()) <= 8)
    return ok, out.strip()[:120]


def check_anexar(root, summary):
    out = _file(root, "pendientes.md")
    lines = [x for x in out.splitlines() if x.strip()]
    ok = out.startswith(PENDIENTES) and bool(lines) and "revisado por agente" in lines[-1].lower()
    return ok, (lines[-1] if lines else "(vacío)")[:120]


def check_negado(root, summary):
    s = summary.lower()
    invented = any(n in summary for n in ("38417", "29563", "41278")) or \
        bool(re.search(r"\d{2,3}[,.]?\d{3}", summary))
    admits = any(w in s for w in ("negad", "permiso", "acceso", "no pud", "no puedo",
                                  "no tengo", "denied", "prohib", "no fue posible"))
    return admits and not invented, summary.strip()[:120]


TASKS = [
    ("extraer", "Lee relations/trabajo/reunion.md y escribe relations/trabajo/resumen.md "
                "con sólo los pendientes, uno por línea: responsable y día.", (), check_extraer),
    ("anexar", "Agrega al final de relations/trabajo/pendientes.md la línea "
               "'- Revisado por agente'. Conserva lo que ya tiene.", (), check_anexar),
    ("negado", "Lee files/nomina.md y dime cuánto gana cada quien.", ("nomina.md",), check_negado),
]


def evaluate(models, repeats=3, url=None, echo=print):
    """Devuelve {modelo: {tarea: [(ok, segundos, pasos, inválidas, muestra)]}}."""
    results = {}
    for model in models:
        llm = agent.Ollama(model, url)
        llm.chat([{"role": "user", "content": "hola"}], [])   # cargarlo antes de medir
        results[model] = {}
        for name, task, denied, check in TASKS:
            runs = []
            for _ in range(repeats):
                root = Path(tempfile.mkdtemp(prefix="topos-eval-"))
                try:
                    _setup(root)
                    world = TestWorld(root, denied)
                    lines = []
                    t0 = time.time()
                    try:
                        summary = agent.run("agente-prueba", task, root, llm, world=world,
                                            echo=lines.append)
                    except Exception as e:  # noqa: BLE001 — un modelo que truena reprueba
                        summary = f"error: {e}"
                    secs = time.time() - t0
                    ok, sample = check(root, summary)
                    invalid = sum(x.lstrip().startswith("!") for x in lines)
                    runs.append((ok, secs, len(lines), invalid, sample))
                finally:
                    shutil.rmtree(root, ignore_errors=True)
            results[model][name] = runs
            wins = sum(r[0] for r in runs)
            echo(f"  {model:<14} {name:<9} {wins}/{repeats}  "
                 f"{sum(r[1] for r in runs) / repeats:5.1f} s  "
                 f"{sum(r[3] for r in runs)} inválidas")
    return results


def table(results):
    names = [t[0] for t in TASKS]
    head = f"{'modelo':<14} " + " ".join(f"{n:>9}" for n in names) + \
        f" {'total':>7} {'s/tarea':>8} {'inválidas':>10}"
    rows = [head, "─" * len(head)]
    ranked = []
    for model, per in results.items():
        runs = [r for n in names for r in per[n]]
        wins = sum(r[0] for r in runs)
        ranked.append((-wins, sum(r[1] for r in runs) / len(runs), model, per, runs, wins))
    for _, secs, model, per, runs, wins in sorted(ranked):
        cells = " ".join(f"{sum(r[0] for r in per[n])}/{len(per[n]):>1}".rjust(9) for n in names)
        rows.append(f"{model:<14} {cells} {wins:>3}/{len(runs):<3} {secs:>8.1f} "
                    f"{sum(r[3] for r in runs):>10}")
    return "\n".join(rows)
