"""La red dentro de topos: el destino es un lector más / the destination is one more reader.

Un agente no sale directo a la red: el firewall del kernel (nftables, por uid)
sólo le deja hablar con este proxy. El proxy averigua quién llama (usuario y
sesión de Linux, por /proc) y decide con dos reglas:

  1. ¿Este agente puede hablarle a este host?     topos net allow agent-x api.github.com
  2. ¿Pueden salir hacia allá los datos que esta sesión ya leyó? Enviar es dejar
     leer: el host es el lector `net/<host>` en el haz, y tiene que poder leer
     cada archivo que la sesión leyó.        topos perm set @finance +net/api.banco.com:r

Los destinos de confianza (`topos net trust ollama`) reciben cualquier cosa: es
para el modelo local, que tiene que ver los datos para trabajar.

An agent never reaches the network directly: the kernel firewall (nftables, per
uid) only lets it talk to this proxy, which identifies the caller (user + Linux
session via /proc) and applies two rules: may this agent talk to this host, and
may the data this session has read go there (the host is the reader net/<host>).
"""

import errno
import os
import select
import socket
import socketserver
import time
from pathlib import Path

from . import agent
from .flow import Sessions, session_of
from .i18n import t
from .store import Store

DEFAULT_PORT = 3128


# -- la decisión / the decision ----------------------------------------------

def host_matches(host, pattern):
    host, pattern = host.lower().rstrip("."), pattern.lower()
    if pattern.startswith("*."):
        return host == pattern[2:] or host.endswith(pattern[1:])
    return host == pattern


def decide(store, user, read, host):
    """(permitido, motivo). `read` = lo que la sesión ya leyó."""
    r = store.sheaf()
    if user not in r.users:
        return True, t("usuario sin política de red", "user has no network policy")
    if not any(host_matches(host, p) for p in store.net["allow"].get(user, [])):
        return False, t(f"{user} no tiene permitido conectarse a {host}",
                        f"{user} is not allowed to connect to {host}")
    if any(host_matches(host, p) for p in store.net["trusted"]):
        return True, t(f"{host} es de confianza", f"{host} is trusted")
    principal = f"net/{host.lower()}"
    for src in sorted(read):
        if src not in store.state["vertices"] or r.mode(src, principal)[0] != "r":
            shown = src.lstrip("/")
            return False, t(f"esta sesión leyó {shown} y {host} no puede recibirlo",
                            f"this session read {shown} and {host} may not receive it")
    return True, t("permitido", "allowed")


# -- quién llama / who is calling ---------------------------------------------

def _hex_addr(ip, port):
    if ":" in ip:
        packed = socket.inet_pton(socket.AF_INET6, ip)
        words = [packed[i:i + 4][::-1].hex().upper() for i in range(0, 16, 4)]
        return "".join(words) + f":{port:04X}"
    return socket.inet_aton(ip)[::-1].hex().upper() + f":{port:04X}"


def peer_socket(client_ip, client_port, proc="/proc"):
    """(uid, inode) del socket del cliente, buscándolo en /proc/net/tcp{,6}."""
    want = _hex_addr(client_ip, client_port)
    for table in ("tcp", "tcp6"):
        try:
            lines = Path(proc, "net", table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            f = line.split()
            if len(f) > 9 and f[1] == want:
                return int(f[7]), int(f[9])
    return None, None


def pid_of_inode(inode, proc="/proc"):
    target = f"socket:[{inode}]"
    for d in Path(proc).iterdir():
        if not d.name.isdigit():
            continue
        try:
            for fd in (d / "fd").iterdir():
                if os.readlink(fd) == target:
                    return int(d.name)
        except OSError:
            continue
    return None


def identify(client_ip, client_port):
    """(uid, usuario, sid | None). Sin sid, se toma el peor caso: todas sus sesiones."""
    uid, inode = peer_socket(client_ip, client_port)
    if uid is None:
        return None, None, None
    pid = pid_of_inode(inode) if inode else None
    import pwd
    try:
        name = pwd.getpwuid(uid).pw_name
    except KeyError:
        name = str(uid)
    return uid, name, session_of(pid) if pid else None


# -- el proxy / the proxy ------------------------------------------------------

class Handler(socketserver.StreamRequestHandler):
    # Sin búfer: lo que venga después de los encabezados se queda en el socket y
    # lo reenvía el relé, en vez de quedarse atrapado aquí.
    rbufsize = 0

    def handle(self):
        srv = self.server
        head = self._read_head()
        if not head:
            return
        method, target, version = (head[0].split(" ", 2) + ["", ""])[:3]
        if method.upper() == "CONNECT":
            host, _, port = target.rpartition(":")
            port = int(port or 443)
        elif target.lower().startswith("http://"):
            rest = target[7:]
            hostport, _, path = rest.partition("/")
            host, _, port = hostport.partition(":")
            port = int(port or 80)
        else:
            return self._reply(400, "bad request")
        host = host.strip("[]")

        uid, user, sid = srv.identify(*self.client_address[:2])
        if uid is None:
            return self._reply(403, t("no sé quién llama", "cannot identify the caller"))
        store = Store(srv.root)
        sessions = Sessions(store.meta)
        read = sessions.get(uid, sid) if sid is not None else sessions.of_user(uid)
        ok, why = decide(store, user, read, host)
        agent.log({"t": time.time(), "agent": user, "via": "net", "tool": "connect",
                   "args": {"host": host, "port": port}, "status": "ok" if ok else "denied",
                   "result": why})
        if not ok:
            return self._reply(403, why)
        try:
            upstream = socket.create_connection((host, port), timeout=15)
        except OSError as e:
            return self._reply(502, str(e))
        with upstream:
            if method.upper() == "CONNECT":
                self._reply(200, "Connection established", close=False)
            else:
                # Petición HTTP normal: se reenvía en forma de origen y sin keep-alive.
                lines = [f"{method} /{path} {version}"]
                lines += [h for h in head[1:] if not h.lower().startswith(("proxy-", "connection:"))]
                lines.append("Connection: close")
                upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            self._relay(upstream)

    def _read_head(self):
        lines = []
        while True:
            line = self.rfile.readline(65536)
            if not line or line in (b"\r\n", b"\n"):
                break
            lines.append(line.decode("latin-1").rstrip("\r\n"))
            if len(lines) > 100:
                break
        return lines

    def _reply(self, code, text, close=True):
        body = b"" if code == 200 else (text + "\n").encode()
        head = f"HTTP/1.1 {code} {text.splitlines()[0] if text else ''}\r\n"
        if code != 200:
            head += f"Content-Type: text/plain; charset=utf-8\r\nContent-Length: {len(body)}\r\n"
            head += "X-Topos: denied\r\n" if code == 403 else ""
        self.wfile.write((head + "\r\n").encode() + body)
        self.wfile.flush()

    def _relay(self, upstream):
        socks = [self.connection, upstream]
        while True:
            ready, _, _ = select.select(socks, [], [], 60)
            if not ready:
                return
            for s in ready:
                data = s.recv(65536)
                if not data:
                    return
                (upstream if s is self.connection else self.connection).sendall(data)


class Proxy(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, root, port=DEFAULT_PORT, host="127.0.0.1"):
        super().__init__((host, port), Handler)
        self.root = root
        self.identify = identify


def serve(root, port=DEFAULT_PORT):
    with Proxy(root, port) as p:
        p.serve_forever()


# -- el candado del kernel / the kernel lock -----------------------------------

def ruleset(uids, port=DEFAULT_PORT):
    """nftables: los uids de los agentes sólo pueden conectarse al proxy local."""
    if not uids:
        return "table inet topos {}\ndelete table inet topos\n"
    ids = ", ".join(str(u) for u in sorted(uids))
    return f"""table inet topos {{}}
delete table inet topos
table inet topos {{
    chain out {{
        type filter hook output priority 0; policy accept;
        meta skuid {{ {ids} }} ip daddr 127.0.0.1 tcp dport {port} accept
        meta skuid {{ {ids} }} counter reject
    }}
}}
"""


def agent_uids(store):
    import pwd
    uids = set()
    for name in store.state["enrolled"]:
        try:
            uids.add(pwd.getpwnam(name).pw_uid)
        except KeyError:
            continue
    return uids


def enforce(store, port=DEFAULT_PORT):
    import subprocess
    uids = agent_uids(store)
    r = subprocess.run(["nft", "-f", "-"], input=ruleset(uids, port), text=True,
                       capture_output=True)
    if r.returncode:
        raise OSError(errno.EPERM, t(f"nft falló: {r.stderr.strip()}", f"nft failed: {r.stderr.strip()}"))
    return uids
