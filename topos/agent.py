"""Agentes dentro de topos: un modelo abierto que actúa sólo a través del mundo montado.

La idea es que la seguridad no dependa de lo que el modelo decida obedecer:

- Cada agente es un usuario de Linux inscrito en el haz. Empieza sin nada y sólo
  lee o escribe lo que el haz le concede; quien lo niega es el kernel, vía FUSE.
- Sus herramientas sólo ven rutas dentro del mundo montado.
- Si al lanzarlo se declaran recursos (--recursos a.md b.md), el agente los toma
  por el planificador topológico antes de empezar y los suelta al terminar, y
  sólo puede escribir en ellos. Dos agentes que piden los mismos recursos en
  orden opuesto no se atoran: el monitor rodea la zona sin retorno.
- Cada llamada a herramienta queda en una bitácora con su resultado.

El modelo corre en Ollama (por omisión qwen3:4b); el ciclo es el de siempre:
el modelo pide herramientas, el runtime las ejecuta y le devuelve lo que pasó.
"""

import json
import os
import time
import urllib.request
from pathlib import Path

DEFAULT_MODEL = os.environ.get("TOPOS_MODELO", "qwen3:4b")
DEFAULT_OLLAMA = os.environ.get("TOPOS_OLLAMA", "")
LOG = Path(os.environ.get("TOPOS_BITACORA", "/var/log/topos/agentes.jsonl"))
MAX_STEPS = 16

SYSTEM = """Eres {name}, un agente dentro de topOS, un sistema operativo topológico.
Tu mundo es un sistema de archivos donde los archivos son vértices y las carpetas de
relations/ son relaciones: un archivo puede estar en varias relaciones a la vez.

  files/<archivo>                  todos los archivos
  relations/<relación>/<archivo>   los archivos de cada relación
  star/<archivo>/<relación>/…      todo lo relacionado con un archivo
  holes                            ciclos de relaciones que nada junta

Sólo puedes actuar con tus herramientas. Algunas cosas te van a ser negadas: los
permisos los decide el sistema, no tú. Si algo se te niega, no insistas ni busques
rodeos; dilo en tu resumen y sigue con lo que sí puedes hacer.
Cuando termines, llama a `terminar` con un resumen breve en español.

Relaciones que existen: {relations}
{resources}"""

TOOLS = [
    ("listar", "Lista una carpeta del mundo (por ejemplo 'relations' o 'relations/trabajo').",
     {"ruta": "ruta dentro del mundo"}),
    ("leer", "Lee un archivo del mundo (por ejemplo 'files/notas.md').",
     {"ruta": "ruta del archivo"}),
    ("escribir", "Escribe (o crea) un archivo, reemplazando lo que tenía. Para crearlo dentro "
     "de una relación usa 'relations/<relación>/<archivo>'.",
     {"ruta": "ruta del archivo", "contenido": "texto completo"}),
    ("anexar", "Agrega texto al final de un archivo sin tocar lo que ya tiene.",
     {"ruta": "ruta del archivo", "texto": "texto a agregar"}),
    ("relacionar", "Agrega un archivo existente a una relación (la crea si no existe).",
     {"archivo": "nombre del archivo", "relacion": "nombre de la relación"}),
    ("terminar", "Termina la tarea con un resumen de lo que hiciste y lo que no pudiste.",
     {"resumen": "resumen breve"}),
]


# Los modelos chicos le cambian el nombre a los argumentos; mejor entenderlos que fallar.
ALIASES = {
    "ruta": ("path", "archivo", "file", "filename", "ruta_archivo", "carpeta", "directorio"),
    "contenido": ("content", "texto", "text", "contenido_nuevo"),
    "texto": ("text", "contenido", "content", "linea", "línea"),
    "archivo": ("ruta", "path", "file", "filename", "nombre"),
    "relacion": ("relación", "relation", "etiqueta", "label"),
    "resumen": ("mensaje", "message", "summary", "respuesta", "resultado"),
}


def normalize_args(name, args):
    params = next((p for n, _, p in TOOLS if n == name), None)
    if params is None or not isinstance(args, dict):
        return args
    out = {k: v for k, v in args.items() if k in params}
    extra = {k: v for k, v in args.items() if k not in params}
    for p in params:
        if p in out:
            continue
        for alias in ALIASES.get(p, ()):
            if alias in extra:
                out[p] = extra.pop(alias)
                break
    if name == "relacionar" and "archivo" in out:
        out["archivo"] = Path(str(out["archivo"])).name   # 'files/x.md' → 'x.md'
    missing = [p for p in params if p not in out]
    if len(missing) == 1 and len(extra) == 1:
        out[missing[0]] = extra.popitem()[1]
    return out


def calls_from_text(text):
    """Llamadas que el modelo escribió como JSON en el texto en vez de como tool_calls.

    Varios modelos chicos (phi4-mini, por ejemplo) saben qué herramienta usar pero la
    escriben en un bloque ```json … ``` que Ollama no reconoce como llamada.
    """
    names = {n for n, _, _ in TOOLS}
    calls, dec, i = [], json.JSONDecoder(), 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            i += 1
            continue
        i = end
        for o in obj if isinstance(obj, list) else [obj]:
            if not isinstance(o, dict):
                continue
            f = o.get("function") if isinstance(o.get("function"), dict) else o
            name = f.get("name")
            args = f.get("arguments", f.get("parameters", {}))
            if name in names and isinstance(args, (dict, str)):
                calls.append({"function": {"name": name, "arguments": args}})
    return calls


def strip_thinking(text):
    import re
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def tool_specs():
    return [{"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object",
                       "properties": {k: {"type": "string", "description": v}
                                      for k, v in params.items()},
                       "required": list(params)}}}
            for name, desc, params in TOOLS]


def find_ollama():
    """Ollama puede estar aquí, en el anfitrión de Docker o en el Windows de WSL."""
    candidates = ["http://localhost:11434", "http://host.docker.internal:11434"]
    try:
        import subprocess
        route = subprocess.run(["ip", "route", "show", "default"], capture_output=True,
                               text=True).stdout.split()
        if "via" in route:
            candidates.append(f"http://{route[route.index('via') + 1]}:11434")
    except OSError:
        pass
    for url in candidates:
        try:
            urllib.request.urlopen(f"{url}/api/version", timeout=2).read()
            return url
        except OSError:
            continue
    raise RuntimeError("no encuentro Ollama; pasa --ollama URL o define TOPOS_OLLAMA")


class Ollama:
    def __init__(self, model=DEFAULT_MODEL, url=None):
        self.model = model
        self.url = (url or DEFAULT_OLLAMA or find_ollama()).rstrip("/")

    def chat(self, messages, tools):
        body = {"model": self.model, "messages": messages, "tools": tools, "stream": False,
                "think": False, "options": {"temperature": 0.2}}
        req = urllib.request.Request(f"{self.url}/api/chat", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.loads(r.read())["message"]


class Denied(Exception):
    pass


class World:
    """Las herramientas del agente: rutas relativas a la raíz del montaje, nada más."""

    def __init__(self, root, writable=None):
        self.root = Path(root).resolve()
        self.writable = writable      # None = sin restricción de recursos

    def _path(self, rel):
        p = (self.root / rel.strip().lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise Denied(f"{rel!r} está fuera del mundo")
        return p

    def listar(self, ruta=""):
        p = self._path(ruta)
        return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())) \
            or "(vacío)"

    def leer(self, ruta):
        return self._path(ruta).read_text(encoding="utf-8", errors="replace")

    def _writable(self, ruta):
        p = self._path(ruta)
        if self.writable is not None and p.name not in self.writable:
            raise Denied(f"{p.name} no está entre los recursos que reservaste "
                         f"({', '.join(sorted(self.writable)) or 'ninguno'})")
        return p

    def escribir(self, ruta, contenido):
        p = self._writable(ruta)
        p.write_text(contenido, encoding="utf-8")
        return f"escrito {p.relative_to(self.root)} ({len(contenido.encode())} bytes)"

    def anexar(self, ruta, texto):
        p = self._writable(ruta)
        before = p.read_text(encoding="utf-8") if p.exists() else ""
        sep = "" if not before or before.endswith("\n") else "\n"
        p.write_text(before + sep + texto.rstrip("\n") + "\n", encoding="utf-8")
        return f"agregado al final de {p.relative_to(self.root)}"

    def relacionar(self, archivo, relacion):
        rel = self._path(f"relations/{relacion}")
        if not rel.exists():
            rel.mkdir()
        os.link(self._path(f"files/{archivo}"), rel / archivo)
        return f"{archivo} ahora también está en {relacion}"


def run_tool(world, name, args):
    """Devuelve (estado, texto) con estado en ok | negado | error."""
    fn = getattr(world, name, None)
    if fn is None or name.startswith("_"):
        return "error", f"no existe la herramienta {name}"
    try:
        return "ok", fn(**args)
    except (Denied, PermissionError) as e:
        return "negado", f"negado: {e}"
    except TypeError as e:
        return "error", f"argumentos inválidos: {e}"
    except OSError as e:
        return "error", f"{e.strerror or e}: {args}"


def log(entry):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
        try:
            os.fchmod(fd, 0o666)      # la comparten todos los agentes
        except (OSError, AttributeError):
            pass
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run(name, task, root, llm, resources=None, sched_socket=None, echo=print, world=None):
    """Corre una tarea. Devuelve el resumen final del agente."""
    world = world or World(root, set(resources) if resources else None)
    relations = ", ".join(sorted(os.listdir(world.root / "relations"))) or "(ninguna)"
    res_note = (f"Reservaste estos recursos y sólo puedes escribir en ellos: {', '.join(resources)}"
                if resources else "")
    messages = [{"role": "system", "content": SYSTEM.format(name=name, relations=relations,
                                                           resources=res_note)},
                {"role": "user", "content": task}]
    client = _reserve(name, resources, sched_socket, echo) if resources else None
    summary = "(el agente no terminó)"
    nudges = 0
    try:
        for _ in range(MAX_STEPS):
            msg = llm.chat(messages, tool_specs())
            msg["content"] = strip_thinking(msg.get("content"))
            messages.append(msg)
            calls = msg.get("tool_calls") or calls_from_text(msg["content"])
            if calls and not msg.get("tool_calls"):
                msg["tool_calls"] = calls
            if not calls:
                # Un modelo chico a veces se pone a pensar en voz alta en vez de actuar.
                if nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content":
                                     "Actúa con tus herramientas, sin explicar. "
                                     "Cuando acabes, llama a `terminar`."})
                    continue
                summary = msg["content"] or summary
                break
            done = False
            for call in calls:
                fn = call["function"]["name"]
                args = call["function"].get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except json.JSONDecodeError:
                        args = {}
                args = normalize_args(fn, args)
                if fn == "terminar":
                    summary, done = args.get("resumen", ""), True
                    status, out = "ok", "terminado"
                else:
                    status, out = run_tool(world, fn, args)
                shown = ", ".join(f"{k}={_short(v)}" for k, v in args.items() if k != "contenido")
                mark = {"ok": "✓", "negado": "✗", "error": "!"}[status]
                echo(f"  {mark} {fn}({shown})" + ("" if status == "ok" else f"  → {out}"))
                log({"t": time.time(), "agente": name, "tool": fn, "args": args,
                     "estado": status, "resultado": _short(out, 300)})
                messages.append({"role": "tool", "tool_name": fn, "content": str(out)})
            if done:
                break
    finally:
        if client:
            _release(client, resources)
    log({"t": time.time(), "agente": name, "tool": "fin", "estado": "ok", "resultado": summary})
    return summary


def _reserve(name, resources, socket_path, echo):
    """Toma los recursos por el planificador: P(r1) … P(rn) trabajo, en el orden dado."""
    from .sched import DEFAULT_SOCKET, Client
    client = Client(socket_path or DEFAULT_SOCKET)
    plan = [f"P({r})" for r in resources] + ["trabajo"] + [f"V({r})" for r in reversed(resources)]
    client.call(op="join", name=name, plan=plan)
    for r in resources:
        if client.call(op="step")["waited"]:
            echo(f"  … esperé {r}: el monitor me apartó de la zona sin retorno")
    client.call(op="step")          # trabajo
    return client


def _release(client, resources):
    for _ in resources:
        client.call(op="step")
    client.close()


def _short(v, n=60):
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"
