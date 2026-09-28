"""topos: una capa topológica sobre Linux / a topological layer over Linux."""

import argparse
import sys
from pathlib import Path

from . import memory, progress
from .complex import token
from .i18n import plural, t
from .store import Store, StoreError

USAGE_ES = """topos: una capa topológica sobre Linux.

    topos init                         crea .topos/ aquí
    topos add ARCHIVO... [--name N]    agrega archivos como vértices
    topos import DIR                   importa un árbol: cada carpeta es una relación
    topos ls | cat N | rm N
    topos glue A B C [--as ETIQUETA]   pega el símplice {A,B,C} en una relación
    topos cut A B                      quita el símplice {A,B} y sus cocaras
    topos drop ETIQUETA | rels
    topos star N | link N
    topos betti [--dim K] | holes [--dim K]
    topos perm govern ETIQ alice:rw    la relación obliga a sus archivos a coincidir
    topos perm set N|@ETIQ +alice:rw -bob:x
    topos perm enroll USUARIO          lo mete al haz sin darle nada
    topos perm show | check | cohomology
    topos flow show | declassify N     qué datos llegaron a qué archivos
    topos net allow AGENTE HOST… | trust HOST | show | proxy | enforce
                                       red: el destino es un lector más
    topos paths PROGRAMA.txt           deadlocks y clases de dihomotopía
    topos run PROGRAMA.txt [--naive] [--runs N]   lo ejecuta con hilos reales
    topos sched serve | status | run NOMBRE PROGRAMA.txt
                                       el planificador para procesos independientes
    topos agent create NOMBRE [--grant REL:rw]     un agente: usuario de Linux sin nada
    topos agent run NOMBRE "TAREA" [--resources A B]   lo pone a trabajar (Ollama)
    topos agent log | eval --models M…
    topos mcp [--world DIR] [--read-only]  servidor MCP para cualquier agente
    topos mem [--writable] [--snapshot F] [--dump F]
    topos mount DIR [--readonly] [--shared]   monta el almacén (Linux)

Los comandos tienen alias en español (pegar, huecos, caminos, agente crear…).
El idioma sale de TOPOS_LANG o del sistema: TOPOS_LANG=en para inglés.
"""

USAGE_EN = """topos: a topological layer over Linux.

    topos init                         create .topos/ here
    topos add FILE... [--name N]       add files as vertices
    topos import DIR                   import a tree: every folder becomes a relation
    topos ls | cat N | rm N
    topos glue A B C [--as LABEL]      glue the simplex {A,B,C} into a relation
    topos cut A B                      remove the simplex {A,B} and its cofaces
    topos drop LABEL | rels
    topos star N | link N
    topos betti [--dim K] | holes [--dim K]
    topos perm govern LABEL alice:rw   the relation forces its files to agree
    topos perm set N|@LABEL +alice:rw -bob:x
    topos perm enroll USER             put a user in the sheaf with nothing granted
    topos perm show | check | cohomology
    topos flow show | declassify N     which data reached which files
    topos net allow AGENT HOST… | trust HOST | show | proxy | enforce
                                       network: the destination is one more reader
    topos paths PROGRAM.txt            deadlocks and dihomotopy classes
    topos run PROGRAM.txt [--naive] [--runs N]    run it with real threads
    topos sched serve | status | run NAME PROGRAM.txt
                                       the scheduler for independent processes
    topos agent create NAME [--grant REL:rw]      an agent: a Linux user with nothing
    topos agent run NAME "TASK" [--resources A B]   put it to work (Ollama)
    topos agent log | eval --models M…
    topos mcp [--world DIR] [--read-only]  MCP server for any agent
    topos mem [--writable] [--snapshot F] [--dump F]
    topos mount DIR [--readonly] [--shared]   mount the store (Linux)

The language comes from TOPOS_LANG or the system: TOPOS_LANG=es for Spanish.
"""


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        return args.run(args) or 0
    except (StoreError, ValueError, OSError, progress.TooManyPaths) as e:
        print(f"topos: {e}", file=sys.stderr)
        return 1


def parser():
    p = argparse.ArgumentParser(prog="topos", description=t(USAGE_ES, USAGE_EN),
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True, metavar=t("COMANDO", "COMMAND"))

    def cmd(name, fn, help=None, es=None):
        c = sub.add_parser(name, help=help, aliases=[es] if es else [])
        c.set_defaults(run=fn)
        return c

    cmd("init", cmd_init, t("crea un almacén vacío", "create an empty store"), "iniciar")
    c = cmd("add", cmd_add, t("agrega archivos", "add files"), "agregar")
    c.add_argument("files", nargs="+")
    c.add_argument("--name", "--nombre", dest="name")
    c = cmd("import", cmd_import, t("importa un árbol de carpetas", "import a folder tree"), "importar")
    c.add_argument("dir")
    cmd("ls", cmd_ls, t("lista vértices", "list vertices"))
    c = cmd("cat", cmd_cat, t("muestra un archivo", "print a file"))
    c.add_argument("name")
    c = cmd("rm", cmd_rm, t("borra un vértice", "remove a vertex"), "borrar")
    c.add_argument("name")
    c = cmd("glue", cmd_glue, t("pega un símplice", "glue a simplex"), "pegar")
    c.add_argument("names", nargs="+")
    c.add_argument("--as", "--como", dest="label")
    c = cmd("cut", cmd_cut, t("quita un símplice y sus cocaras", "remove a simplex and its cofaces"),
            "cortar")
    c.add_argument("names", nargs="+")
    c = cmd("drop", cmd_drop, t("borra una relación", "delete a relation"), "soltar")
    c.add_argument("label")
    cmd("rels", cmd_rels, t("lista relaciones", "list relations"), "relaciones")
    c = cmd("star", cmd_star, t("estrella de un vértice", "star of a vertex"), "estrella")
    c.add_argument("name")
    c = cmd("link", cmd_link, t("enlace de un vértice", "link of a vertex"), "enlace")
    c.add_argument("name")
    c = cmd("betti", cmd_betti, t("números de Betti", "Betti numbers"))
    c.add_argument("--dim", type=int, default=1)
    c = cmd("holes", cmd_holes, t("ciclos que no son borde", "cycles that are not boundaries"), "huecos")
    c.add_argument("--dim", type=int, default=1)

    c = cmd("perm", None, t("haz de permisos", "permission sheaf"), "permisos")
    psub = c.add_subparsers(required=True, metavar=t("ACCIÓN", "ACTION"))

    def action(parent, name, fn, help, es=None, **kw):
        x = parent.add_parser(name, help=help, aliases=[es] if es else [], **kw)
        x.set_defaults(run=fn)
        return x

    g = action(psub, "govern", cmd_perm_govern,
               t("la relación gobierna estos bits", "the relation governs these bits"), "gobernar")
    g.add_argument("label")
    g.add_argument("bits", nargs="+")
    s = action(psub, "set", cmd_perm_set, t("fija valores locales", "set local values"), "fijar",
               prefix_chars="=")
    s.add_argument("target")
    s.add_argument("values", nargs="+")
    e = action(psub, "enroll", cmd_perm_enroll,
               t("mete a un usuario al haz sin darle nada", "put a user in the sheaf with nothing"),
               "inscribir")
    e.add_argument("user")
    action(psub, "show", cmd_perm_show, t("tabla de permisos efectivos", "effective permission table"),
           "ver")
    action(psub, "check", cmd_perm_check, t("obstrucciones al pegado", "gluing obstructions"), "revisar")
    action(psub, "cohomology", cmd_perm_coh, t("dimensiones de H⁰ y H¹", "dimensions of H⁰ and H¹"),
           "cohomologia")

    c = cmd("flow", None, t("flujo de información: qué datos llegaron a qué archivos",
                            "information flow: which data reached which files"), "flujo")
    fsub = c.add_subparsers(required=True, metavar=t("ACCIÓN", "ACTION"))
    action(fsub, "show", cmd_flow_show, t("archivos marcados, sus fuentes y quién los lee",
                                          "marked files, their sources and who can read them"), "ver")
    x = action(fsub, "declassify", cmd_flow_declassify,
               t("quita las marcas de un archivo (sólo el dueño)", "clear a file's marks (owner only)"),
               "desclasificar")
    x.add_argument("name")

    c = cmd("net", None, t("red: a dónde puede hablar cada agente y qué datos pueden salir",
                           "network: where each agent may talk and which data may leave"), "red")
    nsub = c.add_subparsers(required=True, metavar=t("ACCIÓN", "ACTION"))
    x = action(nsub, "allow", cmd_net_allow, t("hosts a los que un agente puede conectarse",
                                              "hosts an agent may connect to"), "permitir")
    x.add_argument("user")
    x.add_argument("hosts", nargs="+")
    x = action(nsub, "revoke", cmd_net_revoke, t("quita hosts a un agente", "remove hosts from an agent"),
               "quitar")
    x.add_argument("user")
    x.add_argument("hosts", nargs="+")
    x = action(nsub, "trust", cmd_net_trust, t("destino de confianza: recibe cualquier dato",
                                              "trusted destination: may receive any data"), "confiar")
    x.add_argument("host")
    action(nsub, "show", cmd_net_show, t("la política de red", "the network policy"), "ver")
    x = action(nsub, "check", cmd_net_check, t("¿puede este agente mandar lo que leyó a este host?",
                                              "may this agent send what it read to this host?"), "probar")
    x.add_argument("user")
    x.add_argument("host")
    for name, fn, help, es in (
            ("proxy", cmd_net_proxy, t("arranca el proxy (como root)", "start the proxy (as root)"), None),
            ("enforce", cmd_net_enforce, t("candado del kernel: los agentes sólo salen por el proxy",
                                           "kernel lock: agents only get out through the proxy"), "aplicar")):
        x = action(nsub, name, fn, help, es)
        x.add_argument("--port", "--puerto", dest="port", type=int, default=3128)

    c = cmd("paths", cmd_paths, t("procesos como caminos", "processes as paths"), "caminos")
    c.add_argument("program")
    c.add_argument("--max-paths", type=int, default=200_000)
    c = cmd("run", cmd_run, t("ejecuta un programa con el planificador topológico",
                              "run a program under the topological scheduler"), "correr")
    c.add_argument("program")
    c.add_argument("--naive", "--ingenuo", dest="naive", action="store_true",
                   help=t("semáforos reales, sin monitor", "real semaphores, no monitor"))
    c.add_argument("--runs", "--corridas", dest="runs", type=int, default=1,
                   help=t("repite y cuenta deadlocks", "repeat and count deadlocks"))
    c.add_argument("--jitter", type=float, default=0.02,
                   help=t("pausa aleatoria máxima por paso (s)", "max random pause per step (s)"))
    c.add_argument("--seed", "--semilla", dest="seed", type=int)

    c = cmd("sched", None, t("planificador topológico entre procesos",
                             "topological scheduler across processes"), "planificador")
    ssub = c.add_subparsers(required=True, metavar=t("ACCIÓN", "ACTION"))
    for name, fn, help, es in (
            ("serve", cmd_sched_serve, t("arranca el demonio", "start the daemon"), "servir"),
            ("status", cmd_sched_status, t("quién está dónde", "who is where"), "estado"),
            ("run", cmd_sched_run, t("corre un proceso de un programa", "run one process of a program"),
             "correr")):
        x = action(ssub, name, fn, help, es)
        x.add_argument("--socket")
        if name == "run":
            x.add_argument("name")
            x.add_argument("program")

    c = cmd("agent", None, t("agentes con un modelo abierto, encerrados por el haz",
                             "open-model agents, confined by the sheaf"), "agente")
    asub = c.add_subparsers(required=True, metavar=t("ACCIÓN", "ACTION"))
    x = action(asub, "create", cmd_agent_create,
               t("crea el usuario del agente y lo inscribe en el haz",
                 "create the agent's user and enroll it in the sheaf"), "crear")
    x.add_argument("name")
    x.add_argument("--grant", "--concede", dest="grant", nargs="*", default=[], metavar="REL:rwx",
                   help=t("relaciones que el agente puede usar", "relations the agent may use"))
    x = action(asub, "run", cmd_agent_run, t("pone al agente a trabajar en una tarea",
                                             "put the agent to work on a task"), "correr")
    x.add_argument("name")
    x.add_argument("task")
    x.add_argument("--resources", "--recursos", dest="resources", nargs="*", default=None,
                   help=t("archivos que toma por el planificador; sólo escribe en ellos",
                          "files taken through the scheduler; it may only write those"))
    x.add_argument("--world", "--mundo", dest="world",
                   help=t("raíz del mundo montado (por omisión ~/mundo)",
                          "root of the mounted world (default ~/mundo)"))
    x.add_argument("--model", "--modelo", dest="model")
    x.add_argument("--ollama")
    x.add_argument("--socket")
    x = action(asub, "eval", cmd_agent_eval, t("compara modelos con las mismas tareas",
                                              "compare models on the same tasks"), "evaluar")
    x.add_argument("--models", "--modelos", dest="models", nargs="+", required=True)
    x.add_argument("--repeats", "--repeticiones", dest="repeats", type=int, default=3)
    x.add_argument("--ollama")
    x = action(asub, "log", cmd_agent_log, t("las últimas acciones de los agentes",
                                            "the agents' latest actions"), "bitacora")
    x.add_argument("-n", type=int, default=30)

    c = cmd("mcp", cmd_mcp, t("servidor MCP: cualquier agente trabaja dentro del mundo",
                              "MCP server: any agent works inside the world"))
    c.add_argument("--world", "--mundo", dest="world",
                   help=t("raíz del mundo montado (por omisión ~/mundo)",
                          "root of the mounted world (default ~/mundo)"))
    c.add_argument("--read-only", "--solo-lectura", dest="readonly", action="store_true",
                   help=t("sin herramientas de escritura", "no writing tools"))
    c.add_argument("--resources", "--recursos", dest="resources", nargs="*", default=None,
                   help=t("sólo puede escribir estos archivos", "may only write these files"))
    c = cmd("mem", cmd_mem, t("memoria como espacio topológico", "memory as a topological space"),
            "memoria")
    c.add_argument("--writable", "--escribible", dest="writable", action="store_true",
                   help=t("sólo memoria compartida escribible", "only writable shared memory"))
    c.add_argument("--snapshot", help=t("lee un snapshot JSON en vez de /proc",
                                        "read a JSON snapshot instead of /proc"))
    c.add_argument("--dump", help=t("guarda el snapshot de /proc en JSON", "save the /proc snapshot as JSON"))
    c = cmd("mount", cmd_mount, t("monta la vista FUSE", "mount the FUSE view"), "montar")
    c.add_argument("dir")
    c.add_argument("--background", "--fondo", dest="background", action="store_true")
    c.add_argument("--readonly", "--solo-lectura", dest="readonly", action="store_true",
                   help=t("monta sin escritura", "mount without writes"))
    c.add_argument("--shared", "--compartido", dest="shared", action="store_true",
                   help=t("deja entrar a otros usuarios; el haz decide por cada uno",
                          "let other users in; the sheaf decides for each one"))
    return p


# -- almacén / store --------------------------------------------------------

def cmd_init(a):
    s = Store.init()
    print(t(f"almacén vacío en {s.meta}", f"empty store at {s.meta}"))


def cmd_add(a):
    s = Store.find()
    if a.name and len(a.files) > 1:
        raise StoreError(t("--name sólo tiene sentido con un archivo", "--name only makes sense with one file"))
    for f in a.files:
        print(s.add_file(f, a.name))
    s.save()


def cmd_import(a):
    s = Store.find()
    root = Path(a.dir)
    files = 0
    for d in sorted([root, *[p for p in root.rglob("*") if p.is_dir()]]):
        names = []
        for f in sorted(p for p in d.iterdir() if p.is_file()):
            rel = f.relative_to(root).as_posix().replace("/", "∕")
            names.append(s.add_bytes(rel, f.read_bytes()))
        files += len(names)
        if names:
            label = d.relative_to(root).as_posix().replace("/", "∕") or root.resolve().name
            s.glue(names, label)
    s.save()
    print(t(f"{files} archivos; cada carpeta quedó como una relación",
            f"{files} files; every folder became a relation"))


def cmd_ls(a):
    s = Store.find()
    for v in s.vertices:
        rels = [label for label in s.relations if v in s.members(label)]
        print(f"{v}  {' '.join(rels)}".rstrip())


def cmd_cat(a):
    sys.stdout.buffer.write(Store.find().cat(a.name))


def cmd_rm(a):
    s = Store.find()
    s.remove_vertex(a.name)
    s.save()


def cmd_glue(a):
    s = Store.find()
    label = s.glue(a.names, a.label)
    s.save()
    print(f"{token(sorted(set(a.names)))} ∈ {label}")


def cmd_cut(a):
    s = Store.find()
    s.cut(a.names)
    s.save()


def cmd_drop(a):
    s = Store.find()
    s.drop(a.label)
    s.save()


def cmd_rels(a):
    s = Store.find()
    for label, ss in s.relations.items():
        gov = s.state["govern"].get(label)
        extra = f"  {t('gobierna', 'governs')} {' '.join(gov)}" if gov else ""
        print(f"{label}: {'  '.join(token(x) for x in ss)}{extra}")


def cmd_star(a):
    s = Store.find()
    s._need(a.name)
    for g in s.complex().star(a.name):
        print(f"{token(g)}  ({s.label_of(g)})")


def cmd_link(a):
    s = Store.find()
    s._need(a.name)
    for g in s.complex().link(a.name).generators:
        print(token(g))


def _space(h):
    return t("el nervio", "the nerve") if h.space == "nervio" else t("el primal", "the primal complex")


def cmd_betti(a):
    h = Store.find().homology(a.dim)
    for k, b in enumerate(h.betti):
        print(f"β{k} = {b}")
    print(t(f"χ (hasta dim {a.dim}) = {h.euler}   [calculado en {_space(h)}]",
            f"χ (up to dim {a.dim}) = {h.euler}   [computed on {_space(h)}]"))


def cmd_holes(a):
    s = Store.find()
    h = s.homology(a.dim)
    names = {0: t("componente(s)", "component(s)"), 1: t("ciclo(s)", "cycle(s)"),
             2: t("cavidad(es)", "cavity(ies)")}
    print(f"H0: {h.betti[0]} {names[0]}")
    for i, comp in enumerate(_components(s.complex()), 1):
        print(f"  {i}. {', '.join(sorted(comp))}")
    join = " ∩ ".join if h.space == "nervio" else token
    for k in range(1, a.dim + 1):
        reps = h.cycles.get(k, [])
        print(f"H{k}: {len(reps)} {names.get(k, t('clases', 'classes'))}")
        for i, cyc in enumerate(reps, 1):
            print(f"  {i}. " + "   ".join(join(x) for x in cyc))
    if h.space == "nervio":
        print(t("(los ciclos están expresados en el nervio: sus vértices son relaciones)",
                "(cycles are written on the nerve: its vertices are relations)"))


def _components(cx):
    parent = {v: v for v in cx.vertices}

    def find(v):
        while parent[v] != v:
            parent[v] = parent[parent[v]]
            v = parent[v]
        return v

    for g in cx.generators:
        for w in g[1:]:
            parent[find(w)] = find(g[0])
    groups = {}
    for v in parent:
        groups.setdefault(find(v), set()).add(v)
    return sorted(groups.values(), key=min)


# -- haz / sheaf ------------------------------------------------------------

def cmd_perm_govern(a):
    s = Store.find()
    s.govern(a.label, a.bits)
    s.save()


def cmd_perm_set(a):
    s = Store.find()
    s.set_values(a.target, a.values)
    s.save()


def cmd_perm_enroll(a):
    s = Store.find()
    s.enroll(a.user)
    s.save()
    print(t(f"{a.user} está en el haz: sólo tendrá lo que se le conceda",
            f"{a.user} is in the sheaf: it only gets what is granted"))


def cmd_perm_show(a):
    s = Store.find()
    r = s.sheaf()
    if not r.users:
        print(t("sin permisos declarados", "no permissions declared"))
        return
    users = r.users
    width = max(len(v) for v in s.vertices)
    print(" " * width + "  " + "  ".join(f"{u:>6}" for u in users))
    for v in s.vertices:
        print(f"{v:<{width}}  " + "  ".join(f"{r.mode(v, u):>6}" for u in users))
    print("\n" + t("letra = concedido   - = negado   · = sin sección (se niega)   ! = conflicto",
                   "letter = granted   - = denied   · = no section (denied)   ! = conflict"))


def cmd_perm_check(a):
    r = Store.find().sheaf()
    if not r.conflicts:
        print(t("los datos locales se pegan en una sección global: sin obstrucciones",
                "the local data glue into a global section: no obstructions"))
        return
    print(t(f"{len(r.conflicts)} obstrucción(es) en H¹(K_b, A):",
            f"{len(r.conflicts)} obstruction(s) in H¹(K_b, A):"))
    for c in r.conflicts:
        print("  " + c.describe())
    return 2


def cmd_perm_coh(a):
    r = Store.find().sheaf()
    print(t(f"dim H⁰ = {sum(r.h0.values())}   (grados de libertad de una política global)",
            f"dim H⁰ = {sum(r.h0.values())}   (degrees of freedom of a global policy)"))
    print(t(f"dim H¹ = {sum(r.h1.values())}   (lazos de relaciones que gobiernan el mismo bit)",
            f"dim H¹ = {sum(r.h1.values())}   (loops of relations governing the same bit)"))
    for b in r.bits:
        print(f"  {b:<14} H⁰={r.h0[b]}  H¹={r.h1[b]}")


# -- flujo de información / information flow --------------------------------

def cmd_flow_show(a):
    from .store import TOMBSTONE
    s = Store.find()
    marked = {v: s.sources(v) for v in s.vertices if s.sources(v)}
    if not marked:
        print(t("ningún archivo está marcado: no ha fluido nada restringido",
                "no file is marked: nothing restricted has flowed"))
        return
    r = s.sheaf()
    for v, srcs in marked.items():
        shown = ", ".join(t(f"{x[1:]} (borrado)", f"{x[1:]} (deleted)") if x.startswith(TOMBSTONE) else x
                          for x in sorted(srcs))
        print(f"{v} ← {shown}")
        if r.users:
            readers = [u for u in r.users
                       if r.mode(v, u)[0] == "r"
                       and all(x in s.state["vertices"] and r.mode(x, u)[0] == "r" for x in srcs)]
            print(t(f"    lo pueden leer: {', '.join(readers) or 'nadie del haz'}",
                    f"    readable by: {', '.join(readers) or 'nobody in the sheaf'}"))


def cmd_flow_declassify(a):
    s = Store.find()
    before = s.sources(a.name)
    s.declassify(a.name)
    s.save()
    print(t(f"{a.name}: sin marcas (antes: {', '.join(sorted(before)) or 'ninguna'})",
            f"{a.name}: no marks (before: {', '.join(sorted(before)) or 'none'})"))


# -- red / network ------------------------------------------------------------

def cmd_net_allow(a):
    s = Store.find()
    s.net_allow(a.user, a.hosts)
    s.save()
    print(t(f"{a.user} puede conectarse a: {', '.join(s.net['allow'][a.user])}",
            f"{a.user} may connect to: {', '.join(s.net['allow'][a.user])}"))


def cmd_net_revoke(a):
    s = Store.find()
    s.net_revoke(a.user, a.hosts)
    s.save()


def cmd_net_trust(a):
    s = Store.find()
    s.net_trust(a.host)
    s.save()
    print(t(f"{a.host} es de confianza: puede recibir cualquier dato",
            f"{a.host} is trusted: it may receive any data"))


def cmd_net_show(a):
    s = Store.find()
    net = s.net
    if not net["allow"] and not net["trusted"]:
        print(t("sin política de red: los agentes inscritos no pueden conectarse a nada",
                "no network policy: enrolled agents cannot connect anywhere"))
    for user, hosts in sorted(net["allow"].items()):
        print(f"{user}: {', '.join(hosts) or '—'}")
    if net["trusted"]:
        print(t("de confianza: ", "trusted: ") + ", ".join(net["trusted"]))
    r = s.sheaf()
    readers = sorted(u for u in r.users if u.startswith("net/"))
    for principal in readers:
        files = [v for v in s.vertices if r.mode(v, principal)[0] == "r"]
        print(t(f"{principal[4:]} puede recibir: {', '.join(files) or 'nada'}",
                f"{principal[4:]} may receive: {', '.join(files) or 'nothing'}"))


def cmd_net_check(a):
    import pwd
    from .flow import Sessions
    from .net import decide
    s = Store.find()
    read = Sessions(s.meta).of_user(pwd.getpwnam(a.user).pw_uid)
    ok, why = decide(s, a.user, read, a.host)
    print(("✓ " if ok else "✗ ") + why)
    return 0 if ok else 2


def cmd_net_proxy(a):
    from .net import serve
    s = Store.find()
    print(t(f"proxy de topos en 127.0.0.1:{a.port}", f"topos proxy on 127.0.0.1:{a.port}"), flush=True)
    serve(str(s.root), a.port)


def cmd_net_enforce(a):
    from .net import enforce
    uids = enforce(Store.find(), a.port)
    print(t(f"candado aplicado: {len(uids)} agente(s) sólo salen por 127.0.0.1:{a.port}",
            f"lock applied: {len(uids)} agent(s) only get out through 127.0.0.1:{a.port}"))


# -- procesos y memoria / processes and memory ------------------------------

def cmd_paths(a):
    from .run import split_commands
    _, text = split_commands(Path(a.program).read_text(encoding="utf-8"))
    space = progress.ProgressSpace(progress.parse(text))
    reach, good, deadlocks = space.analyze()
    total = 1
    for n in space.lens:
        total *= n + 1
    forbidden = total - sum(space.allowed(s) for s in _grid(space.lens))
    print(t(f"espacio de estados: {total} puntos, {len(reach)} alcanzables, {forbidden} prohibidos",
            f"state space: {total} points, {len(reach)} reachable, {forbidden} forbidden"))
    if deadlocks:
        print(f"\n{len(deadlocks)} deadlock(s):")
        for d in deadlocks:
            print(f"  {d}: {space.describe_state(d)}")
    unsafe = reach - good
    if unsafe:
        print(t(f"zona sin retorno: {plural(len(unsafe), 'estado', 'state')} que ya no llega(n) al final",
                f"point of no return: {plural(len(unsafe), 'estado', 'state')} that can no longer finish"))
    if space.final not in reach:
        print("\n" + t("ninguna ejecución termina", "no execution finishes"))
        return 2
    classes = space.classes(a.max_paths)
    print("\n" + t(f"{sum(map(len, classes))} ejecuciones completas en {len(classes)} clase(s) de dihomotopía:",
                   f"{sum(map(len, classes))} complete executions in {len(classes)} dihomotopy class(es):"))
    for i, cls in enumerate(classes, 1):
        schedule, sems = space.describe_path(cls[0])
        n = plural(len(cls), "ejecución", "execution", "ejecuciones")
        print(f"  {i}. {n}, {t('p. ej.', 'e.g.')} {schedule}")
        if sems:
            print(f"     {sems}")
    return 2 if deadlocks else 0


def _grid(lens):
    if not lens:
        yield ()
        return
    for rest in _grid(lens[1:]):
        for k in range(lens[0] + 1):
            yield (k,) + rest


def cmd_run(a):
    from .run import Runner, split_commands
    commands, text = split_commands(Path(a.program).read_text(encoding="utf-8"))
    runner = Runner(progress.parse(text), commands, a.jitter, a.seed)
    space = runner.space
    mode = (t("ingenuo (semáforos reales)", "naive (real semaphores)") if a.naive
            else t("topológico (monitor sobre el espacio)", "topological (monitor over the space)"))
    if a.runs > 1:
        stuck, waits, orders = 0, 0, {}
        for _ in range(a.runs):
            r = runner.run(a.naive)
            if r.error and r.error != "deadlock":
                raise ValueError(r.error)
            stuck += not r.finished
            waits += r.waits
            if r.finished:
                order = space.describe_path(r.path)[1]
                orders[order] = orders.get(order, 0) + 1
        extra = "" if a.naive else t(f", {waits} esperas impuestas por el monitor",
                                     f", {waits} waits imposed by the monitor")
        print(t(f"{mode}: {a.runs} corridas, {plural(stuck, 'deadlock', 'deadlock')}{extra}",
                f"{mode}: {a.runs} runs, {plural(stuck, 'deadlock', 'deadlock')}{extra}"))
        for order, n in sorted(orders.items(), key=lambda x: -x[1]):
            print(f"  {n:>4}  {order or t('(sin semáforos)', '(no semaphores)')}")
        return 2 if stuck else 0
    r = runner.run(a.naive)
    for name, word, out in r.output:
        if out:
            print(f"[{name} {word}] {out}")
    if not r.finished:
        print(f"{mode}: {r.error or t('no terminó', 'did not finish')}")
        print(t(f"  atorado en {r.state}: {space.describe_state(r.state)}",
                f"  stuck at {r.state}: {space.describe_state(r.state)}"))
        return 2
    schedule, order = space.describe_path(r.path)
    print(t(f"{mode}: terminó en {len(r.path)} pasos", f"{mode}: finished in {len(r.path)} steps"))
    print(f"  {t('orden', 'order')}: {schedule}")
    if order:
        print(f"  {t('semáforos', 'semaphores')}: {order}")
    if r.waits:
        print(t(f"  el monitor hizo esperar {plural(r.waits, 'vez', 'time', 'veces')} "
                "para no entrar a la zona sin retorno",
                f"  the monitor made threads wait {plural(r.waits, 'vez', 'time', 'veces')} "
                "to stay out of the point of no return"))
    return 0


def _socket(a):
    from .sched import DEFAULT_SOCKET
    return a.socket or DEFAULT_SOCKET


def cmd_sched_serve(a):
    from .sched import serve
    path = _socket(a)
    print(t(f"planificador topológico escuchando en {path}", f"topological scheduler listening on {path}"),
          flush=True)
    serve(path)


def cmd_sched_status(a):
    from .sched import Client
    c = Client(_socket(a))
    st = c.call(op="status")
    c.close()
    if not st["procs"]:
        print(t("nadie conectado", "nobody connected"))
        return
    for p in st["procs"]:
        print(t(f"  {p['name']:<10} paso {p['pos']}/{p['len']}  siguiente: {p['next']}",
                f"  {p['name']:<10} step {p['pos']}/{p['len']}  next: {p['next']}"))
    print(st["describe"])


def cmd_sched_run(a):
    import subprocess
    from .run import split_commands
    from .sched import Client
    commands, text = split_commands(Path(a.program).read_text(encoding="utf-8"))
    prog = progress.parse(text)
    if a.name not in prog.names:
        raise ValueError(t(f"{a.program} no tiene un proceso {a.name!r}",
                           f"{a.program} has no process {a.name!r}"))
    steps = prog.ops[prog.names.index(a.name)]
    c = Client(_socket(a))
    try:
        me = c.call(op="join", name=a.name, plan=[w for _, _, w in steps],
                    capacity=prog.capacity)["name"]
        for kind, sem, word in steps:
            r = c.call(op="step")
            note = t("  (esperó: el monitor lo apartó de la zona sin retorno)",
                     "  (waited: the monitor kept it out of the point of no return)") if r["waited"] else ""
            print(f"[{me}] {word}{note}", flush=True)
            if kind == "op" and word in commands:
                if subprocess.run(commands[word], shell=True).returncode:
                    raise ValueError(t(f"`{commands[word]}` falló", f"`{commands[word]}` failed"))
    finally:
        c.close()


def _whoami():
    import getpass
    return getpass.getuser()


def cmd_agent_create(a):
    import subprocess
    if subprocess.run(["id", a.name], capture_output=True).returncode:
        subprocess.run(["sudo", "-n", "useradd", "--system", "--no-create-home",
                        "--shell", "/usr/sbin/nologin", a.name], check=True)
    import os
    from urllib.parse import urlparse
    s = Store.find()
    s.enroll(a.name)
    for spec in a.grant:
        rel, _, bits = spec.partition(":")
        s.set_values("@" + rel, [f"+{a.name}:{bits or 'r'}"])
    proxy = os.environ.get("TOPOS_PROXY")
    model_host = urlparse(os.environ.get("TOPOS_OLLAMA", "")).hostname
    if proxy and model_host:
        # Con candado de red, el agente sólo sale por el proxy; el modelo tiene que ver
        # los datos para trabajar, así que su host se permite y es de confianza.
        s.net_allow(a.name, [model_host])
        s.net_trust(model_host)
    s.save()
    granted = ", ".join(a.grant) or t("nada", "nothing")
    print(t(f"{a.name}: usuario de Linux, inscrito en el haz; se le concede {granted}",
            f"{a.name}: Linux user, enrolled in the sheaf; granted {granted}"))
    if proxy:
        r = subprocess.run(["sudo", "-n", "env", f"TOPOS_HOME={s.root}", "topos", "net", "enforce"],
                           capture_output=True, text=True)
        print(r.stdout.strip() or t("  (no se pudo aplicar el candado de red: ¿falta NET_ADMIN?)",
                                    "  (could not apply the network lock: missing NET_ADMIN?)"))


def cmd_agent_run(a):
    import os
    from . import agent
    world = os.path.abspath(os.path.expanduser(a.world or "~/mundo"))
    if _whoami() != a.name:
        # El modelo corre como el usuario del agente: lo que el haz le niega, el kernel se lo niega.
        # The model runs as the agent's user: what the sheaf denies, the kernel denies.
        proxy = os.environ.get("TOPOS_PROXY")
        via = [f"{k}={proxy}" for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")] \
            if proxy else []
        argv = ["sudo", "-n", "-u", a.name, "env", f"TOPOS_LANG={t('es', 'en')}", *via,
                sys.executable, "-m", "topos", "agent", "run", a.name, a.task, "--world", world,
                "--model", a.model or agent.DEFAULT_MODEL,
                "--ollama", a.ollama or agent.DEFAULT_OLLAMA or agent.find_ollama()]
        if a.socket or os.environ.get("TOPOS_SCHED"):
            argv += ["--socket", a.socket or os.environ["TOPOS_SCHED"]]
        if a.resources is not None:
            argv += ["--resources", *a.resources]
        sys.stdout.flush()
        os.execvp("sudo", argv)
    llm = agent.Ollama(a.model or agent.DEFAULT_MODEL, a.ollama)
    print(f"[{a.name}] {a.task}   ({t('modelo', 'model')} {llm.model})", flush=True)
    summary = agent.run(a.name, a.task, world, llm, a.resources, a.socket,
                        echo=lambda s: print(s, flush=True))
    print(f"[{a.name}] {summary}")


def cmd_agent_eval(a):
    from .agent_eval import evaluate, table
    results = evaluate(a.models, a.repeats, a.ollama, echo=lambda s: print(s, flush=True))
    print()
    print(table(results))


def cmd_agent_log(a):
    import json
    import time
    from .agent import LOG
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()[-a.n:]
    except FileNotFoundError:
        print(t("la bitácora está vacía", "the log is empty"))
        return
    for line in lines:
        e = json.loads(line)
        when = time.strftime("%H:%M:%S", time.localtime(e["t"]))
        status = e.get("status", e.get("estado"))
        mark = {"ok": "✓", "denied": "✗", "negado": "✗", "error": "!"}.get(status, "?")
        args = e.get("args") or {}
        what = ", ".join(f"{k}={v}" for k, v in args.items() if k not in ("content", "contenido"))
        tool = e["tool"]
        result = e.get("result", e.get("resultado", ""))
        print(f"{when} {mark} {e.get('agent', e.get('agente')):<16} {tool}({what})"
              + (f"  {result}" if status != "ok" or tool in ("end", "fin") else ""))


def cmd_mcp(a):
    import os
    from .mcp import serve
    world = os.path.abspath(os.path.expanduser(a.world or "~/mundo"))
    serve(world, readonly=a.readonly, resources=a.resources)


def cmd_mem(a):
    import json
    snap = memory.load(a.snapshot) if a.snapshot else memory.snapshot()
    if a.dump:
        Path(a.dump).write_text(json.dumps(snap), encoding="utf-8")
        print(t(f"snapshot de {len(snap)} procesos en {a.dump}", f"snapshot of {len(snap)} processes in {a.dump}"))
        return
    procs, points = memory.build(snap, a.writable)
    classes = memory.kolmogorov(points)
    print(t(f"{len(procs)} procesos, {len(points)} puntos de memoria, {len(classes)} tras el cociente T0",
            f"{len(procs)} processes, {len(points)} memory points, {len(classes)} after the T0 quotient"))
    h = memory.nerve(procs, points).homology(1)
    print(t(f"nervio: β0 = {h.betti[0]}, β1 = {h.betti[1]}   [calculado en {_space(h)}]",
            f"nerve: β0 = {h.betti[0]}, β1 = {h.betti[1]}   [computed on {_space(h)}]"))
    if h.space == "primal":
        for i, cyc in enumerate(h.cycles.get(1, []), 1):
            print(f"  {t('ciclo', 'cycle')} {i}: " + "  ".join(token(x) for x in cyc))
    pairs = memory.shared_pairs(points)
    if pairs:
        print("\n" + t("pares que comparten más memoria:", "pairs sharing the most memory:"))
        for (p, q), n in pairs[:10]:
            print(f"  {n:>5}  {p} ↔ {q}")


def cmd_mount(a):
    from .fuse_view import mount
    mount(Store.find(), a.dir, foreground=not a.background, readonly=a.readonly,
          shared=a.shared)


if __name__ == "__main__":
    sys.exit(main())
