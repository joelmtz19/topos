"""Servidor MCP de topos / topos MCP server.

Cualquier agente que hable MCP (Claude Desktop, Claude Code, Cursor, Goose…)
trabaja dentro de un mundo de topos montado: lee, escribe, relaciona archivos y
ve la forma del mundo (huecos, Betti, estrellas).

Any MCP-speaking agent (Claude Desktop, Claude Code, Cursor, Goose…) works inside
a mounted topos world: it reads, writes and relates files, and sees the world's
shape (holes, Betti numbers, stars).

La seguridad no vive aquí / Security does not live here: run the server as the
agent's own Linux user, enrolled in the sheaf, and the kernel denies whatever the
sheaf does not grant — whatever the client or the model decides:

    sudo -u agent-x topos mcp --world /home/topos/mundo

Transporte: JSON-RPC 2.0 por stdin/stdout, un mensaje por línea. Sólo stdlib.
Transport: JSON-RPC 2.0 over stdin/stdout, one message per line. Stdlib only.
"""

import getpass
import json
import sys
import time

from . import __version__, agent
from .i18n import t

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")


def _schema(props):
    return {"type": "object",
            "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
            "required": list(props)}


def tool_list(readonly=False):
    out = []
    for name, desc, params in agent.tools():
        if name == "finish" or (readonly and name in ("write", "append", "relate")):
            continue
        out.append({"name": name, "description": desc, "inputSchema": _schema(params)})
    out += [
        {"name": "holes",
         "description": t("Los huecos del mundo: componentes y ciclos de relaciones que nada junta. "
                          "Un hueco suele ser algo que falta.",
                          "The world's holes: components and cycles of relations that nothing ties "
                          "together. A hole is often something missing."),
         "inputSchema": _schema({})},
        {"name": "betti",
         "description": t("Los números de Betti del mundo (β0 componentes, β1 ciclos).",
                          "The world's Betti numbers (β0 components, β1 cycles)."),
         "inputSchema": _schema({})},
        {"name": "star",
         "description": t("Todo lo relacionado con un archivo: sus relaciones y los archivos de cada una.",
                          "Everything related to a file: its relations and the files in each one."),
         "inputSchema": _schema({"file": t("nombre del archivo", "file name")})},
    ]
    return out


class Server:
    def __init__(self, world, readonly=False, resources=None, user=None):
        self.world = agent.World(world, set(resources) if resources else None)
        self.readonly = readonly
        self.user = user or getpass.getuser()
        self.tools = {x["name"] for x in tool_list(readonly)}

    # -- herramientas topológicas / topological tools -----------------------

    def _report(self, name):
        p = self.world.root / name
        if not p.is_file():
            raise agent.Denied(t(f"{self.world.root} no parece un mundo de topos montado",
                                 f"{self.world.root} does not look like a mounted topos world"))
        return p.read_text(encoding="utf-8")

    def _star(self, file):
        base = self.world._path(f"star/{file}")
        if not base.is_dir():
            raise FileNotFoundError(2, t("no existe", "no such file"), file)
        lines = []
        for rel in sorted(p.name for p in base.iterdir()):
            members = sorted(p.name for p in (base / rel).iterdir())
            lines.append(f"{rel}: {', '.join(members)}")
        return "\n".join(lines) or t(f"{file} no está en ninguna relación", f"{file} is in no relation")

    def call(self, name, args):
        """(estado, texto) — estado en ok | denied | error."""
        name = agent.canonical_tool(name)
        if name not in self.tools:
            if name in ("write", "append", "relate") and self.readonly:
                return "denied", t("este servidor es de sólo lectura", "this server is read-only")
            return "error", t(f"no existe la herramienta {name}", f"no such tool {name}")
        args = agent.normalize_args(name, args or {})
        try:
            if name in ("holes", "betti"):
                return "ok", self._report(name)
            if name == "star":
                return "ok", self._star(args.get("file", ""))
        except (agent.Denied, PermissionError) as e:
            return "denied", t(f"negado: {e}", f"denied: {e}")
        except OSError as e:
            return "error", f"{e.strerror or e}"
        return agent.run_tool(self.world, name, args)

    # -- JSON-RPC ------------------------------------------------------------

    def handle(self, msg):
        """Un mensaje entrante → la respuesta, o None si es una notificación."""
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            return None            # notificaciones: initialized, cancelled… no llevan respuesta
        try:
            result = self._dispatch(method, msg.get("params") or {})
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32601, "message": f"method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _dispatch(self, method, params):
        if method == "initialize":
            asked = params.get("protocolVersion")
            return {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "topos", "version": __version__},
                "instructions": t(
                    "Trabajas dentro de un mundo de topos: los archivos son vértices y las carpetas "
                    "de relations/ son relaciones (un archivo puede estar en varias). Los permisos "
                    "los hace cumplir el sistema: si algo se te niega, dilo y no busques rodeos. "
                    "Usa `holes` y `star` para entender cómo se relacionan las cosas.",
                    "You are working inside a topos world: files are vertices and the folders under "
                    "relations/ are relations (one file can be in several). Permissions are enforced "
                    "by the system: if something is denied, say so and do not look for a way around "
                    "it. Use `holes` and `star` to understand how things relate."),
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": tool_list(self.readonly)}
        if method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            status, out = self.call(name, args)
            agent.log({"t": time.time(), "agent": self.user, "via": "mcp", "tool": name,
                       "args": args, "status": status, "result": agent._short(out, 300)})
            return {"content": [{"type": "text", "text": str(out)}], "isError": status != "ok"}
        raise KeyError(method)


def serve(world, readonly=False, resources=None, stdin=None, stdout=None):
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for stream in (stdin, stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")   # Windows abre stdio en cp1252
    server = Server(world, readonly, resources)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            batch = msg if isinstance(msg, list) else [msg]
            replies = [r for r in (server.handle(m) for m in batch if isinstance(m, dict)) if r]
            reply = replies if isinstance(msg, list) else (replies[0] if replies else None)
        if reply:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
