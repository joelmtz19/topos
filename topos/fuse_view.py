"""Vista FUSE: el almacén montado como un sistema de archivos de lectura y escritura.

    /files/<n>                 contenido de cada vértice
    /relations/<etiqueta>/<n>  los archivos de cada relación
    /star/<n>/<etiqueta>/<m>   la estrella de n, relación por relación (sólo lectura)
    /betti  /holes  /perm      reportes generados al vuelo (sólo lectura)

Las operaciones de siempre se traducen al complejo:

    escribir /files/n          nuevo contenido para el vértice n
    crear /relations/L/n       crea n si no existe y lo pega en L como vértice
    ln /files/n relations/L/n  pega n en L (un archivo vive en muchas relaciones)
    rm /relations/L/n          lo saca de L; el archivo sigue en /files
    rm /files/n                borra el vértice y sus cocaras
    mkdir / rmdir relations/L  relación vacía / borra una relación vacía
    mv                         renombra vértices y relaciones, o mueve entre relaciones
    chmod                      fija en el haz los bits del usuario que lo corre

Renombrar encima de un vértice que ya existe le cambia el contenido y deja
intacto su lugar en el complejo. Así los editores que guardan escribiendo un
temporal y renombrándolo no le quitan las relaciones al archivo.

Los permisos que ve el kernel son secciones globales del haz: el modo de un
archivo sale de lo que el haz resuelve para el usuario que pregunta. Un bit
indeterminado o en conflicto se niega. Los usuarios que el haz nunca menciona
leen y escriben todo, porque no hay política que les aplique.
"""

import errno
import io
import os
import pwd
import stat
import time
from pathlib import Path
from contextlib import redirect_stdout

try:
    from fuse import FUSE, FuseOSError, Operations, fuse_get_context
except ImportError:  # Debian empaqueta fusepy con su propio nombre
    from fusepy import FUSE, FuseOSError, Operations, fuse_get_context

from .flow import Quota, Sessions, session_of
from .i18n import t
from .store import Store, StoreError

REPORTS = {"betti": ["betti"], "holes": ["holes"], "perm": ["perm", "show"]}


def _split_as(path):
    """'/as/bob/files/x' → ('bob', '/files/x'); cualquier otra ruta → (None, ruta)."""
    parts = path.split("/")
    if len(parts) >= 3 and parts[1] == "as" and parts[2]:
        inner = "/" + "/".join(p for p in parts[3:] if p)
        if inner == "/as" or inner.startswith("/as/"):
            raise FuseOSError(errno.ENOENT)      # no se anida: a nombre de uno a la vez
        return parts[2], inner
    return None, path
WRITE = os.O_WRONLY | os.O_RDWR


class ToposFS(Operations):
    def __init__(self, root):
        self.root = root
        self.t = time.time()
        self.handles = {}   # fh → [vértice, bytearray, sucio, sesión | None]
        self.next_fh = 1
        # Flujo de información: lo que cada sesión ha leído (sesión = uid + sesión de Linux,
        # así `cat secreto > publico` desde la misma terminal también cuenta). Vive en disco
        # para sobrevivir a un remontaje y para que el proxy de red lo consulte.
        # Information flow: what each session has read; on disk so it survives remounts
        # and the network proxy can read it.
        self.sessions = Sessions(Path(root) / ".topos")
        self.quota = Quota(Path(root) / ".topos")   # tope de extracción por agente y hora
        self._acting = None     # a nombre de quién va la operación en curso (/as/<quién>/…)

    def _store(self):
        # Se relee en cada llamada para que los cambios del CLI se vean al instante.
        return Store(self.root)

    def _caller(self):
        uid, gid, _ = fuse_get_context()
        return uid, gid

    def _session(self):
        uid, _, pid = fuse_get_context()
        return uid, session_of(pid)

    def _is_owner(self):
        return self._caller()[0] in (0, os.getuid())

    # -- a nombre de alguien / on behalf of someone ------------------------

    def __call__(self, op, *args):
        """FUSE llama todo por aquí. `/as/<quién>/…` es el mismo mundo, pero cada permiso
        es la intersección de quien llama y de <quién>: un chatbot que atiende a un
        cliente sólo ve lo que ese cliente podría ver.
        Every op comes through here. `/as/<who>/…` is the same world where every
        permission is the intersection of the caller's and <who>'s."""
        self._acting = None
        if op in ("link", "rename", "symlink") and len(args) >= 2:
            p1, a1 = _split_as(args[0])
            p2, a2 = _split_as(args[1])
            if p1 != p2:
                raise FuseOSError(errno.EXDEV)
            self._acting, args = p1, (a1, a2, *args[2:])
        elif args and isinstance(args[0], str) and args[0].startswith("/"):
            self._acting, inner = _split_as(args[0])
            args = (inner, *args[1:])
        if self._acting is not None and self._acting not in self._principals():
            raise FuseOSError(errno.ENOENT)
        try:
            return super().__call__(op, *args)
        finally:
            self._acting = None

    def _principals(self):
        return sorted(u for u in self._store().sheaf().users if not u.startswith("net/"))

    def _record_read(self, vertex):
        """El que abre `vertex` para leer carga su contenido y sus fuentes. Si su usuario
        tiene tope de archivos, abrir más de la cuenta en la hora se niega: leer cientos de
        registros es una extracción, no un uso normal. El tope va por agente (uid) y por hora,
        no por sesión, así que abrir una sesión nueva por archivo no lo reinicia."""
        if vertex is None or self._is_owner():
            return
        s = self._store()
        uid, sid = self._session()
        user = self._user()
        cap = s.limit(user)
        if cap is not None:
            allowed, seen = self.quota.allow(uid, vertex, cap)
            if not allowed:
                from . import agent
                agent.log({"t": time.time(), "agent": user, "via": "fuse", "tool": "read",
                           "args": {"file": vertex}, "status": "denied",
                           "result": t(f"tope de {cap} archivos/hora ({seen} ya): posible extracción",
                                       f"cap of {cap} files/hour ({seen} already): possible extraction")})
                raise FuseOSError(errno.EACCES)
        self.sessions.add(uid, sid, {vertex} | s.sources(vertex), opened=vertex)

    def _user(self):
        uid = self._caller()[0]
        try:
            return pwd.getpwuid(uid).pw_name
        except KeyError:
            return str(uid)

    def _report(self, name):
        from .cli import main
        buf = io.StringIO()
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            with redirect_stdout(buf):
                main(REPORTS[name])
        finally:
            os.chdir(cwd)
        return buf.getvalue().encode()

    def _commit(self, s, created=None, renamed=None):
        """Guarda, salvo que el cambio le dé a quien lo pide un bit que no tenía.

        Pegar un archivo en una relación extiende secciones del haz: un archivo
        sin política que se pega junto a otros que conceden algo, lo hereda. Así
        que nadie, salvo el dueño del mundo, puede cambiar la estructura de modo
        que sus propios permisos crezcan. El archivo que uno mismo acaba de crear
        no cuenta: ese sí es suyo.
        """
        if self._caller()[0] not in (0, os.getuid()):
            self._no_escalation(s, created, renamed or {})
        try:
            s.save()
        except StoreError as e:
            raise FuseOSError(errno.EINVAL) from e

    def _no_escalation(self, after, created, renamed):
        user = self._user()
        before = self._store()
        r0, r1 = before.sheaf(), after.sheaf()
        if user not in r0.users:
            return          # ya podía todo: no hay nada que ganar
        back = {new: old for old, new in renamed.items()}
        for v in after.vertices:
            if v == created:
                continue
            old = back.get(v, v)
            if old not in before.state["vertices"]:
                continue
            was, now = r0.mode(old, user), r1.mode(v, user)
            if any(c in "rwx" and w not in "rwx" for c, w in zip(now, was)):
                raise FuseOSError(errno.EACCES)

    # -- resolver rutas ----------------------------------------------------

    def _where(self, path):
        """Qué nombra una ruta, exista o no: ('files', n), ('rel', L), ('member', L, n)…"""
        parts = [p for p in path.split("/") if p]
        if not parts:
            return ("root",)
        head, rest = parts[0], parts[1:]
        if head in REPORTS and not rest:
            return ("report", head)
        if head == "as" and not rest:
            return ("as",)
        if head == "files" and len(rest) <= 1:
            return ("files", *rest)
        if head == "relations" and len(rest) <= 2:
            return ("relations",) if not rest else ("rel", rest[0]) if len(rest) == 1 \
                else ("member", *rest)
        if head == "star" and len(rest) <= 3:
            return ("star", *rest)
        return ("nowhere",)

    def _node(self, path):
        """('dir', [entradas]) o ('file', vértice | None, bytes)."""
        s = self._store()
        rels = s.relations
        w = self._where(path)
        kind, args = w[0], w[1:]
        if kind == "root":
            top = ["files", "relations", "star", *REPORTS]
            return "dir", top if self._acting else [*top, "as"]
        if kind == "as" and not self._acting:
            return "dir", self._principals()
        if kind == "report":
            return "file", None, self._report(args[0])
        if kind == "files":
            if not args:
                return "dir", s.vertices
            if args[0] in s.state["vertices"]:
                return "file", args[0], self._content(s, args[0])
        if kind == "relations":
            return "dir", sorted(rels)
        if kind == "rel" and args[0] in rels:
            return "dir", s.members(args[0])
        if kind == "member" and args[0] in rels and args[1] in s.members(args[0]):
            return "file", args[1], self._content(s, args[1])
        if kind == "star":
            if not args:
                return "dir", s.vertices
            v = args[0]
            if v in s.state["vertices"]:
                owners = sorted(label for label in rels if v in s.members(label))
                if len(args) == 1:
                    return "dir", owners
                if args[1] in owners:
                    members = s.members(args[1])
                    if len(args) == 2:
                        return "dir", members
                    if args[2] in members:
                        return "file", args[2], self._content(s, args[2])
        raise FuseOSError(errno.ENOENT)

    def _content(self, s, vertex):
        # Lo que alguien está escribiendo se ve antes de cerrar, como en ext4.
        for v, buf, dirty, _ in self.handles.values():
            if v == vertex and dirty:
                return bytes(buf)
        return s.cat(vertex)

    def _vertex(self, path):
        """El vértice que nombra una ruta de archivo, o un error si no es escribible."""
        node = self._node(path)
        if node[0] == "dir":
            raise FuseOSError(errno.EISDIR)
        if node[1] is None or self._where(path)[0] == "star":
            raise FuseOSError(errno.EROFS)
        return node[1]

    # -- permisos ----------------------------------------------------------

    def _mode(self, vertex):
        if vertex is None:
            return 0o444
        s = self._store()
        r = s.sheaf()
        # El dueño del mundo (quien monta) ve todo; cualquier otro que el haz no mencione
        # no ve nada. Nada de fail-open: en un montaje compartido, un usuario que nunca se
        # inscribió —o uno que se olvidó inscribir— no debe poder leerlo todo.
        # The world owner sees everything; anyone else the sheaf never mentions sees nothing.
        mode = 0o777 if self._is_owner() else self._mode_for(s, r, vertex, self._user())
        if getattr(self, "_acting", None) is not None:
            mode &= self._mode_for(s, r, vertex, self._acting)
        return mode

    @staticmethod
    def _mode_for(s, r, vertex, user):
        if user not in r.users:
            return 0            # default-deny: sin sección del haz, no hay acceso
        bits = r.mode(vertex, user)
        mode = sum(m for c, m in zip(bits, (0o400, 0o200, 0o100)) if c in "rwx")
        # Leer algo exige poder leer todo lo que fluyó hasta ahí: si la nómina llegó a un
        # resumen, quien no lee la nómina tampoco lee el resumen. Una lápida niega siempre.
        # Reading requires being able to read everything that flowed into it.
        if mode & 0o400 and any(src not in s.state["vertices"] or r.mode(src, user)[0] != "r"
                                for src in s.sources(vertex)):
            mode &= ~0o400
        return mode

    def _require(self, vertex, bit):
        if not self._mode(vertex) & bit:
            raise FuseOSError(errno.EACCES)

    # -- lectura -----------------------------------------------------------

    def _mtime(self, path, node):
        s = self._store()
        if node[0] == "file":
            return s.mtime(node[1], self.t) if node[1] else time.time()
        w = self._where(path)
        names = s.members(w[1]) if w[0] == "rel" else node[1] if w[0] == "files" else []
        return max((s.mtime(n, self.t) for n in names if n in s.state["vertices"]),
                   default=self.t)

    def getattr(self, path, fh=None):
        node = self._node(path)
        t = self._mtime(path, node)
        # El modo es la sección del haz para quien pregunta, así que el archivo
        # se le muestra como suyo: la columna de dueño de `ls -l` es la que aplica.
        uid, gid = self._caller()
        base = {"st_ctime": t, "st_mtime": t, "st_atime": t, "st_uid": uid, "st_gid": gid}
        if node[0] == "dir":
            writable = self._where(path)[0] in ("relations", "rel", "files")
            return {**base, "st_mode": stat.S_IFDIR | (0o755 if writable else 0o555),
                    "st_nlink": 2}
        mode = self._mode(node[1])
        if self._where(path)[0] == "star":
            mode &= 0o555
        return {**base, "st_mode": stat.S_IFREG | mode, "st_nlink": 1,
                "st_size": len(node[2])}

    def access(self, path, amode):
        node = self._node(path)
        if node[0] == "dir":
            if amode & os.W_OK and self._where(path)[0] not in ("relations", "rel", "files"):
                raise FuseOSError(errno.EROFS)
            return 0
        mode = self.getattr(path)["st_mode"]
        for want, bit in ((os.R_OK, 0o400), (os.W_OK, 0o200), (os.X_OK, 0o100)):
            if amode & want and not mode & bit:
                raise FuseOSError(errno.EACCES)
        return 0

    def readdir(self, path, fh):
        node = self._node(path)
        if node[0] != "dir":
            raise FuseOSError(errno.ENOTDIR)
        return [".", "..", *node[1]]

    def read(self, path, size, offset, fh):
        if fh in self.handles:
            return bytes(self.handles[fh][1][offset:offset + size])
        return self._node(path)[2][offset:offset + size]

    # -- abrir, escribir, cerrar ------------------------------------------

    def _open_handle(self, vertex, data, dirty=False):
        fh = self.next_fh
        self.next_fh += 1
        session = None if self._is_owner() else self._session()
        self.handles[fh] = [vertex, bytearray(data), dirty, session]
        return fh

    def open(self, path, flags):
        node = self._node(path)
        if node[0] == "dir":
            return 0
        if not flags & WRITE:
            if node[1] is not None:
                self._require(node[1], 0o400)
                self._record_read(node[1])
            return 0
        vertex = self._vertex(path)
        self._require(vertex, 0o200)
        if flags & os.O_RDWR:
            self._require(vertex, 0o400)
            self._record_read(vertex)
        data = b"" if flags & os.O_TRUNC else node[2]
        return self._open_handle(vertex, data, dirty=bool(flags & os.O_TRUNC))

    def create(self, path, mode, fi=None):
        w = self._where(path)
        if w[0] not in ("files", "member") or len(w) < 2:
            raise FuseOSError(errno.EACCES)
        s = self._store()
        name = w[-1]
        try:
            if w[0] == "member" and w[1] not in s.relations:
                raise FuseOSError(errno.ENOENT)
            if name in s.state["vertices"]:
                self._require(name, 0o200)
            else:
                s.add_bytes(name, b"")
                user = self._user()
                if user in s.sheaf().users:
                    # Quien crea el archivo es su primer dato local en el haz.
                    s.set_values(name, [f"+{user}:rw"])
            if w[0] == "member":
                s.glue([name], w[1])
        except StoreError as e:
            raise FuseOSError(errno.EINVAL) from e
        self._commit(s, created=name)
        return self._open_handle(name, b"", dirty=True)

    def write(self, path, data, offset, fh):
        h = self.handles.get(fh)
        if h is None:
            raise FuseOSError(errno.EBADF)
        buf = h[1]
        if offset > len(buf):
            buf.extend(b"\0" * (offset - len(buf)))
        buf[offset:offset + len(data)] = data
        h[2] = True
        return len(data)

    def truncate(self, path, length, fh=None):
        if fh in self.handles:
            h = self.handles[fh]
        else:
            vertex = self._vertex(path)
            self._require(vertex, 0o200)
            s = self._store()
            h = [vertex, bytearray(self._content(s, vertex)), True,
                 None if self._is_owner() else self._session()]
        h[1][length:] = b""
        h[1].extend(b"\0" * (length - len(h[1])))
        h[2] = True
        if fh not in self.handles:
            self._flush(h)

    def _flush(self, h):
        vertex, buf, dirty, session = h
        if not dirty:
            return
        s = self._store()
        if vertex in s.state["vertices"]:
            s.add_bytes(vertex, bytes(buf))
            # Todo lo que este agente (uid) leyó llega al archivo que escribe. Se marca por
            # uid, no por sesión: si no, bastaba leer el secreto en una terminal, sacarlo a
            # /tmp y volverlo a meter en otra sesión para lavar la marca.
            # Everything this agent (uid) has read flows into what it writes — keyed by uid,
            # not session, so laundering a secret through /tmp in a fresh session cannot strip
            # the label.
            if session is not None:
                s.taint(vertex, self.sessions.of_user(session[0]))
            self._commit(s)
        h[2] = False

    def flush(self, path, fh):
        if fh in self.handles:
            self._flush(self.handles[fh])

    def fsync(self, path, datasync, fh):
        self.flush(path, fh)

    def release(self, path, fh):
        h = self.handles.pop(fh, None)
        if h:
            self._flush(h)

    # -- estructura --------------------------------------------------------

    def unlink(self, path):
        w = self._where(path)
        vertex = self._vertex(path)
        self._require(vertex, 0o200)
        s = self._store()
        if w[0] == "files":
            s.remove_vertex(vertex)
        else:
            s.unglue(w[1], vertex)
        self._commit(s)

    def link(self, target, source):
        # FUSE llama link(ruta_nueva, ruta_existente).
        w = self._where(target)
        if w[0] != "member":
            raise FuseOSError(errno.EPERM)
        vertex = self._vertex(source)
        if w[2] != vertex:
            raise FuseOSError(errno.EPERM)   # en una relación el archivo conserva su nombre
        s = self._store()
        if w[1] not in s.relations:
            raise FuseOSError(errno.ENOENT)
        s.glue([vertex], w[1])
        self._commit(s)

    def mkdir(self, path, mode):
        w = self._where(path)
        if w[0] != "rel":
            raise FuseOSError(errno.EPERM)
        s = self._store()
        try:
            s.create_relation(w[1])
        except StoreError as e:
            raise FuseOSError(errno.EEXIST) from e
        self._commit(s)

    def rmdir(self, path):
        w = self._where(path)
        if w[0] != "rel":
            raise FuseOSError(errno.EPERM)
        s = self._store()
        if w[1] not in s.relations:
            raise FuseOSError(errno.ENOENT)
        if s.members(w[1]):
            raise FuseOSError(errno.ENOTEMPTY)
        s.drop(w[1])
        self._commit(s)

    def rename(self, old, new):
        a, b = self._where(old), self._where(new)
        s = self._store()
        renamed = {}
        try:
            if a[0] == "rel" and b[0] == "rel":
                s.rename_relation(a[1], b[1])
            elif a[0] in ("files", "member") and b[0] in ("files", "member") and len(b) > 1:
                vertex = self._vertex(old)
                self._require(vertex, 0o200)
                if a[0] == "member" and b[0] == "member" and a[1] != b[1]:
                    if b[1] not in s.relations:
                        raise FuseOSError(errno.ENOENT)
                    s.unglue(a[1], vertex)
                    s.glue([vertex], b[1])
                name = b[-1]
                if name != vertex:
                    if name in s.state["vertices"]:
                        self._require(name, 0o200)
                        s.add_bytes(name, s.cat(vertex))
                        s.taint(name, s.sources(vertex))   # el guardado atómico no lava marcas
                        s.remove_vertex(vertex)
                    else:
                        s.rename_vertex(vertex, name)
                        renamed[vertex] = name
            else:
                raise FuseOSError(errno.EXDEV)
        except StoreError as e:
            raise FuseOSError(errno.EINVAL) from e
        self._commit(s, renamed=renamed)

    def chmod(self, path, mode):
        vertex = self._vertex(path)
        user = self._user()
        s = self._store()
        if user not in s.sheaf().users:
            # Meter a alguien al haz le negaría todo lo demás; eso se hace con `topos perm`.
            raise FuseOSError(errno.EPERM)
        values = [("+" if mode & bit else "-") + f"{user}:{c}"
                  for c, bit in zip("rwx", (0o400, 0o200, 0o100))]
        s.set_values(vertex, values)
        self._commit(s)

    def chown(self, path, uid, gid):
        raise FuseOSError(errno.EPERM)

    def utimens(self, path, times=None):
        node = self._node(path)
        if node[0] == "file" and node[1] is not None and self._where(path)[0] != "star":
            s = self._store()
            s.touch(node[1], times[1] if times else None)
            self._commit(s)

    def statfs(self, path):
        s = self._store()
        return {"f_bsize": 4096, "f_frsize": 4096, "f_blocks": 1 << 20,
                "f_bfree": 1 << 19, "f_bavail": 1 << 19,
                "f_files": len(s.vertices) + (1 << 16), "f_ffree": 1 << 16,
                "f_namemax": 255}


def mount(store, mountpoint, foreground=True, readonly=False, shared=False):
    """shared: otros usuarios del sistema entran al montaje y el haz decide por
    cada uno (allow_other; si no montas como root, /etc/fuse.conf necesita
    user_allow_other)."""
    # El modo depende de quién pregunta; la caché del kernel es por inodo, no por
    # usuario, así que con ella bob vería los permisos que el haz le dio a alice.
    opts = {"attr_timeout": 0, "entry_timeout": 0}
    if shared:
        opts["allow_other"] = True
    FUSE(ToposFS(str(store.root)), mountpoint, foreground=foreground, ro=readonly,
         nothreads=True, **opts)
