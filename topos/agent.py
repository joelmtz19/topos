"""Agentes dentro de topos / agents inside topos.

Un modelo abierto que actúa sólo a través del mundo montado, así que la seguridad
no depende de lo que el modelo decida obedecer:

- Cada agente es un usuario de Linux inscrito en el haz. Empieza sin nada y sólo
  lee o escribe lo que el haz le concede; quien lo niega es el kernel, vía FUSE.
- Sus herramientas sólo ven rutas dentro del mundo montado.
- Si se declaran recursos (--resources a.md b.md), el agente los toma por el
  planificador topológico antes de empezar, los suelta al terminar y sólo puede
  escribir en ellos: dos agentes que los piden en orden opuesto no se atoran.
- Cada llamada a herramienta queda en una bitácora con su resultado.

An open model that acts only through the mounted world, so safety does not depend
on what the model chooses to obey: each agent is a Linux user enrolled in the
sheaf, what it is not granted the kernel denies, declared resources go through
the topological scheduler, and every tool call is logged.

The model runs on Ollama (qwen3:4b by default).
"""

import json
import os
import re
import time
import urllib.request
from pathlib import Path

from .i18n import t

DEFAULT_MODEL = os.environ.get("TOPOS_MODEL") or os.environ.get("TOPOS_MODELO") or "qwen3:4b"
DEFAULT_OLLAMA = os.environ.get("TOPOS_OLLAMA", "")
LOG = Path(os.environ.get("TOPOS_LOG") or os.environ.get("TOPOS_BITACORA")
           or "/var/log/topos/agents.jsonl")
MAX_STEPS = 16

SYSTEM_ES = """Eres {name}, un agente dentro de topOS, un sistema operativo topológico.
Tu mundo es un sistema de archivos donde los archivos son vértices y las carpetas de
relations/ son relaciones: un archivo puede estar en varias relaciones a la vez.

  files/<archivo>                  todos los archivos
  relations/<relación>/<archivo>   los archivos de cada relación
  star/<archivo>/<relación>/…      todo lo relacionado con un archivo
  holes                            ciclos de relaciones que nada junta

Sólo puedes actuar con tus herramientas. Algunas cosas te van a ser negadas: los
permisos los decide el sistema, no tú. Si algo se te niega, no insistas ni busques
rodeos; dilo en tu resumen y sigue con lo que sí puedes hacer.
Cuando termines, llama a `finish` con un resumen breve en español.

Relaciones que existen: {relations}
{resources}"""

SYSTEM_EN = """You are {name}, an agent inside topOS, a topological operating system.
Your world is a filesystem where files are vertices and the folders under
relations/ are relations: one file can be in several relations at once.

  files/<file>                     every file
  relations/<relation>/<file>      the files of each relation
  star/<file>/<relation>/…         everything related to a file
  holes                            cycles of relations that nothing ties together

You can only act through your tools. Some things will be denied to you: the
system decides permissions, not you. If something is denied, do not insist or
look for a way around it; say so in your summary and continue with what you can do.
When you are done, call `finish` with a short summary in English.

Existing relations: {relations}
{resources}"""


def tools():
    """(nombre, descripción, parámetros) en el idioma activo; los nombres son fijos."""
    return [
        ("list", t("Lista una carpeta del mundo (por ejemplo 'relations' o 'relations/trabajo').",
                   "List a folder of the world (e.g. 'relations' or 'relations/work')."),
         {"path": t("ruta dentro del mundo", "path inside the world")}),
        ("read", t("Lee un archivo del mundo (por ejemplo 'files/notas.md').",
                   "Read a file of the world (e.g. 'files/notes.md')."),
         {"path": t("ruta del archivo", "file path")}),
        ("write", t("Escribe (o crea) un archivo, reemplazando lo que tenía. Para crearlo dentro "
                    "de una relación usa 'relations/<relación>/<archivo>'.",
                    "Write (or create) a file, replacing its content. To create it inside a "
                    "relation use 'relations/<relation>/<file>'."),
         {"path": t("ruta del archivo", "file path"), "content": t("texto completo", "full text")}),
        ("append", t("Agrega texto al final de un archivo sin tocar lo que ya tiene.",
                     "Append text to the end of a file without touching what it has."),
         {"path": t("ruta del archivo", "file path"), "text": t("texto a agregar", "text to append")}),
        ("relate", t("Agrega un archivo existente a una relación (la crea si no existe).",
                     "Add an existing file to a relation (creating it if needed)."),
         {"file": t("nombre del archivo", "file name"), "relation": t("nombre de la relación", "relation name")}),
        ("finish", t("Termina la tarea con un resumen de lo que hiciste y lo que no pudiste.",
                     "Finish the task with a summary of what you did and what you could not do."),
         {"summary": t("resumen breve", "short summary")}),
    ]


TOOL_NAMES = {"list", "read", "write", "append", "relate", "finish"}

# Los modelos (y la gente) los llaman también en español / Spanish names are accepted too.
TOOL_ALIASES = {"listar": "list", "leer": "read", "escribir": "write", "anexar": "append",
                "agregar": "append", "relacionar": "relate", "terminar": "finish",
                "ls": "list", "cat": "read", "done": "finish", "end": "finish"}

# Los modelos chicos le cambian el nombre a los argumentos; mejor entenderlos que fallar.
# Small models rename arguments; better to understand them than to fail.
ARG_ALIASES = {
    "path": ("ruta", "archivo", "file", "filename", "ruta_archivo", "carpeta", "folder",
             "directory", "directorio", "dir"),
    "content": ("contenido", "texto", "text", "contenido_nuevo", "body"),
    "text": ("texto", "contenido", "content", "linea", "línea", "line"),
    "file": ("archivo", "ruta", "path", "filename", "nombre", "name"),
    "relation": ("relacion", "relación", "etiqueta", "label"),
    "summary": ("resumen", "mensaje", "message", "respuesta", "resultado", "result"),
}


def canonical_tool(name):
    name = str(name or "").strip()
    return TOOL_ALIASES.get(name.lower(), name)


def normalize_args(name, args):
    params = next((p for n, _, p in tools() if n == name), None)
    if params is None or not isinstance(args, dict):
        return args
    out = {k: v for k, v in args.items() if k in params}
    extra = {k: v for k, v in args.items() if k not in params}
    for p in params:
        if p in out:
            continue
        for alias in ARG_ALIASES.get(p, ()):
            if alias in extra:
                out[p] = extra.pop(alias)
                break
    if name == "relate" and "file" in out:
        out["file"] = Path(str(out["file"])).name   # 'files/x.md' → 'x.md'
    missing = [p for p in params if p not in out]
    if len(missing) == 1 and len(extra) == 1:
        out[missing[0]] = extra.popitem()[1]
    return out


def calls_from_text(text):
    """Llamadas que el modelo escribió como JSON en el texto en vez de como tool_calls.

    Several small models (phi4-mini, for one) know which tool to use but write the
    call as a ```json … ``` block that Ollama does not parse as a call.
    """
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
            name = canonical_tool(f.get("name"))
            args = f.get("arguments", f.get("parameters", {}))
            if name in TOOL_NAMES and isinstance(args, (dict, str)):
                calls.append({"function": {"name": name, "arguments": args}})
    return calls


def strip_thinking(text):
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()


def tool_specs():
    return [{"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object",
                       "properties": {k: {"type": "string", "description": v}
                                      for k, v in params.items()},
                       "required": list(params)}}}
            for name, desc, params in tools()]


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
    raise RuntimeError(t("no encuentro Ollama; pasa --ollama URL o define TOPOS_OLLAMA",
                         "cannot find Ollama; pass --ollama URL or set TOPOS_OLLAMA"))


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
    """Las herramientas del agente: rutas relativas a la raíz del montaje, nada más.
    The agent's tools: paths relative to the mount root, nothing else."""

    def __init__(self, root, writable=None):
        self.root = Path(root).resolve()
        self.writable = writable      # None = sin restricción de recursos / no resource limit

    def _path(self, rel):
        p = (self.root / str(rel).strip().lstrip("/")).resolve()
        if p != self.root and self.root not in p.parents:
            raise Denied(t(f"{rel!r} está fuera del mundo", f"{rel!r} is outside the world"))
        return p

    def list(self, path=""):
        p = self._path(path)
        return "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in p.iterdir())) \
            or t("(vacío)", "(empty)")

    def read(self, path):
        return self._path(path).read_text(encoding="utf-8", errors="replace")

    def _writable(self, path):
        p = self._path(path)
        if self.writable is not None and p.name not in self.writable:
            held = ", ".join(sorted(self.writable)) or t("ninguno", "none")
            raise Denied(t(f"{p.name} no está entre los recursos que reservaste ({held})",
                           f"{p.name} is not among the resources you reserved ({held})"))
        return p

    def write(self, path, content):
        p = self._writable(path)
        p.write_text(content, encoding="utf-8")
        rel = p.relative_to(self.root)
        size = len(content.encode())
        return t(f"escrito {rel} ({size} bytes)", f"wrote {rel} ({size} bytes)")

    def append(self, path, text):
        p = self._writable(path)
        before = p.read_text(encoding="utf-8") if p.exists() else ""
        sep = "" if not before or before.endswith("\n") else "\n"
        p.write_text(before + sep + text.rstrip("\n") + "\n", encoding="utf-8")
        rel = p.relative_to(self.root)
        return t(f"agregado al final de {rel}", f"appended to {rel}")

    def relate(self, file, relation):
        rel = self._path(f"relations/{relation}")
        if not rel.exists():
            rel.mkdir()
        os.link(self._path(f"files/{file}"), rel / file)
        return t(f"{file} ahora también está en {relation}", f"{file} is now also in {relation}")


def run_tool(world, name, args):
    """Devuelve (estado, texto) con estado en ok | denied | error."""
    name = canonical_tool(name)
    fn = getattr(world, name, None) if name in TOOL_NAMES - {"finish"} else None
    if fn is None:
        return "error", t(f"no existe la herramienta {name}", f"no such tool {name}")
    try:
        return "ok", fn(**args)
    except (Denied, PermissionError) as e:
        return "denied", t(f"negado: {e}", f"denied: {e}")
    except TypeError as e:
        return "error", t(f"argumentos inválidos: {e}", f"invalid arguments: {e}")
    except OSError as e:
        return "error", f"{e.strerror or e}: {args}"


def log(entry):
    # Primero el demonio de bitácora (a prueba de manipulación): guarda encadenado en
    # `.topos`, donde el agente no puede borrar. Si no hay demonio (Windows, pruebas,
    # `agent eval`), cae al archivo de siempre, que es el modo sin garantías.
    # The tamper-evident daemon first; fall back to the plain file when there is none.
    from . import audit
    if audit.send(entry):
        return
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o666)
        try:
            os.fchmod(fd, 0o666)      # la comparten todos los agentes / shared by all agents
        except (OSError, AttributeError):
            pass
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


MARKS = {"ok": "✓", "denied": "✗", "error": "!"}


def run(name, task, root, llm, resources=None, sched_socket=None, echo=print, world=None):
    """Corre una tarea y devuelve el resumen final del agente / run a task, return the summary."""
    world = world or World(root, set(resources) if resources else None)
    relations = ", ".join(sorted(os.listdir(world.root / "relations"))) or t("(ninguna)", "(none)")
    res_note = (t(f"Reservaste estos recursos y sólo puedes escribir en ellos: {', '.join(resources)}",
                  f"You reserved these resources and may only write to them: {', '.join(resources)}")
                if resources else "")
    system = t(SYSTEM_ES, SYSTEM_EN).format(name=name, relations=relations, resources=res_note)
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    client = _reserve(name, resources, sched_socket, echo) if resources else None
    summary = t("(el agente no terminó)", "(the agent did not finish)")
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
                # Un modelo chico a veces piensa en voz alta en vez de actuar.
                # A small model sometimes thinks out loud instead of acting.
                if nudges < 2:
                    nudges += 1
                    messages.append({"role": "user", "content": t(
                        "Actúa con tus herramientas, sin explicar. Cuando acabes, llama a `finish`.",
                        "Act with your tools, without explaining. When you are done, call `finish`.")})
                    continue
                summary = msg["content"] or summary
                break
            done = False
            for call in calls:
                fn = canonical_tool(call["function"]["name"])
                args = call["function"].get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args or "{}")
                    except json.JSONDecodeError:
                        args = {}
                args = normalize_args(fn, args)
                if fn == "finish":
                    summary, done = args.get("summary", ""), True
                    status, out = "ok", t("terminado", "finished")
                else:
                    status, out = run_tool(world, fn, args)
                shown = ", ".join(f"{k}={_short(v)}" for k, v in args.items() if k != "content")
                echo(f"  {MARKS[status]} {fn}({shown})" + ("" if status == "ok" else f"  → {out}"))
                log({"t": time.time(), "agent": name, "tool": fn, "args": args,
                     "status": status, "result": _short(out, 300)})
                messages.append({"role": "tool", "tool_name": fn, "content": str(out)})
            if done:
                break
    finally:
        if client:
            _release(client, resources)
    log({"t": time.time(), "agent": name, "tool": "end", "status": "ok", "result": summary})
    return summary


def _reserve(name, resources, socket_path, echo):
    """Toma los recursos por el planificador: P(r1) … P(rn) work, en el orden dado."""
    from .sched import DEFAULT_SOCKET, Client
    client = Client(socket_path or DEFAULT_SOCKET)
    plan = [f"P({r})" for r in resources] + ["work"] + [f"V({r})" for r in reversed(resources)]
    client.call(op="join", name=name, plan=plan)
    for r in resources:
        if client.call(op="step")["waited"]:
            echo(t(f"  … esperé {r}: el monitor me apartó de la zona sin retorno",
                   f"  … waited for {r}: the monitor kept me out of the point of no return"))
    client.call(op="step")          # work
    return client


def _release(client, resources):
    for _ in resources:
        client.call(op="step")
    client.close()


def _short(v, n=60):
    s = str(v).replace("\n", " ")
    return s if len(s) <= n else s[:n - 1] + "…"
