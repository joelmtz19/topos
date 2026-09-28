"""topos: una capa topológica sobre Linux.

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
    topos perm show | check | cohomology
    topos paths PROGRAMA.txt           deadlocks y clases de dihomotopía
    topos run PROGRAMA.txt [--naive] [--runs N]   lo ejecuta con hilos reales
    topos sched serve | status | run NOMBRE PROGRAMA.txt
                                       el planificador para procesos independientes
    topos agent crear NOMBRE [--concede REL:rw]    un agente: usuario de Linux sin nada
    topos agent run NOMBRE "TAREA" [--recursos A B]   lo pone a trabajar (modelo en Ollama)
    topos agent bitacora               quién tocó qué
    topos mem [--writable] [--snapshot F] [--dump F]
    topos mount DIR [--readonly] [--shared]   monta el almacén como sistema de archivos (Linux)
"""

import argparse
import sys
from pathlib import Path

from . import memory, progress
from .complex import token
from .store import Store, StoreError


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
    p = argparse.ArgumentParser(prog="topos", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True, metavar="COMANDO")

    def cmd(name, fn, help=None):
        c = sub.add_parser(name, help=help)
        c.set_defaults(run=fn)
        return c

    cmd("init", cmd_init, "crea un almacén vacío")
    c = cmd("add", cmd_add, "agrega archivos")
    c.add_argument("files", nargs="+")
    c.add_argument("--name")
    c = cmd("import", cmd_import, "importa un árbol de carpetas")
    c.add_argument("dir")
    cmd("ls", cmd_ls, "lista vértices")
    c = cmd("cat", cmd_cat, "muestra un archivo")
    c.add_argument("name")
    c = cmd("rm", cmd_rm, "borra un vértice")
    c.add_argument("name")
    c = cmd("glue", cmd_glue, "pega un símplice")
    c.add_argument("names", nargs="+")
    c.add_argument("--as", dest="label")
    c = cmd("cut", cmd_cut, "quita un símplice y sus cocaras")
    c.add_argument("names", nargs="+")
    c = cmd("drop", cmd_drop, "borra una relación")
    c.add_argument("label")
    cmd("rels", cmd_rels, "lista relaciones")
    c = cmd("star", cmd_star, "estrella de un vértice")
    c.add_argument("name")
    c = cmd("link", cmd_link, "enlace de un vértice")
    c.add_argument("name")
    for name, fn in (("betti", cmd_betti), ("holes", cmd_holes)):
        c = cmd(name, fn, "números de Betti" if name == "betti" else "ciclos que no son borde")
        c.add_argument("--dim", type=int, default=1)

    c = cmd("perm", None, "haz de permisos")
    psub = c.add_subparsers(required=True, metavar="ACCIÓN")
    g = psub.add_parser("govern", help="la relación gobierna estos bits")
    g.add_argument("label")
    g.add_argument("bits", nargs="+")
    g.set_defaults(run=cmd_perm_govern)
    s = psub.add_parser("set", help="fija valores locales", prefix_chars="=")
    s.add_argument("target")
    s.add_argument("values", nargs="+")
    s.set_defaults(run=cmd_perm_set)
    e = psub.add_parser("enroll", help="mete a un usuario al haz sin darle nada")
    e.add_argument("user")
    e.set_defaults(run=cmd_perm_enroll)
    psub.add_parser("show", help="tabla de permisos efectivos").set_defaults(run=cmd_perm_show)
    psub.add_parser("check", help="obstrucciones al pegado").set_defaults(run=cmd_perm_check)
    psub.add_parser("cohomology", help="dimensiones de H⁰ y H¹").set_defaults(run=cmd_perm_coh)

    c = cmd("paths", cmd_paths, "procesos como caminos")
    c.add_argument("program")
    c.add_argument("--max-paths", type=int, default=200_000)
    c = cmd("run", cmd_run, "ejecuta un programa con el planificador topológico")
    c.add_argument("program")
    c.add_argument("--naive", action="store_true", help="semáforos reales, sin monitor")
    c.add_argument("--runs", type=int, default=1, help="repite y cuenta deadlocks")
    c.add_argument("--jitter", type=float, default=0.02, help="pausa aleatoria máxima por paso (s)")
    c.add_argument("--seed", type=int)
    c = cmd("sched", None, "planificador topológico entre procesos")
    ssub = c.add_subparsers(required=True, metavar="ACCIÓN")
    for name, fn, help in (("serve", cmd_sched_serve, "arranca el demonio"),
                           ("status", cmd_sched_status, "quién está dónde"),
                           ("run", cmd_sched_run, "corre un proceso de un programa")):
        x = ssub.add_parser(name, help=help)
        x.add_argument("--socket")
        x.set_defaults(run=fn)
        if name == "run":
            x.add_argument("name")
            x.add_argument("program")
    c = cmd("agent", None, "agentes con un modelo abierto, encerrados por el haz")
    asub = c.add_subparsers(required=True, metavar="ACCIÓN")
    x = asub.add_parser("crear", help="crea el usuario del agente y lo inscribe en el haz")
    x.add_argument("name")
    x.add_argument("--concede", nargs="*", default=[], metavar="REL:rwx",
                   help="relaciones que el agente puede usar")
    x.set_defaults(run=cmd_agent_create)
    x = asub.add_parser("run", help="pone al agente a trabajar en una tarea")
    x.add_argument("name")
    x.add_argument("task")
    x.add_argument("--recursos", nargs="*", default=None,
                   help="archivos que toma por el planificador; sólo escribe en ellos")
    x.add_argument("--mundo", help="raíz del mundo montado (por omisión ~/mundo)")
    x.add_argument("--modelo")
    x.add_argument("--ollama")
    x.add_argument("--socket")
    x.set_defaults(run=cmd_agent_run)
    x = asub.add_parser("evaluar", help="compara modelos con las mismas tareas")
    x.add_argument("--modelos", nargs="+", required=True)
    x.add_argument("--repeticiones", type=int, default=3)
    x.add_argument("--ollama")
    x.set_defaults(run=cmd_agent_eval)
    x = asub.add_parser("bitacora", help="las últimas acciones de los agentes")
    x.add_argument("-n", type=int, default=30)
    x.set_defaults(run=cmd_agent_log)
    c = cmd("mem", cmd_mem, "memoria como espacio topológico")
    c.add_argument("--writable", action="store_true", help="sólo memoria compartida escribible")
    c.add_argument("--snapshot", help="lee un snapshot JSON en vez de /proc")
    c.add_argument("--dump", help="guarda el snapshot de /proc en JSON")
    c = cmd("mount", cmd_mount, "monta la vista FUSE")
    c.add_argument("dir")
    c.add_argument("--background", action="store_true")
    c.add_argument("--readonly", action="store_true", help="monta sin escritura")
    c.add_argument("--shared", action="store_true",
                   help="deja entrar a otros usuarios; el haz decide por cada uno")
    return p


# -- almacén ----------------------------------------------------------------

def cmd_init(a):
    s = Store.init()
    print(f"almacén vacío en {s.meta}")


def cmd_add(a):
    s = Store.find()
    if a.name and len(a.files) > 1:
        raise StoreError("--name sólo tiene sentido con un archivo")
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
    print(f"{files} archivos; cada carpeta quedó como una relación")


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
        extra = f"  gobierna {' '.join(gov)}" if gov else ""
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


def cmd_betti(a):
    h = Store.find().homology(a.dim)
    for k, b in enumerate(h.betti):
        print(f"β{k} = {b}")
    print(f"χ (hasta dim {a.dim}) = {h.euler}   [calculado en el {h.space}]")


def cmd_holes(a):
    s = Store.find()
    h = s.homology(a.dim)
    names = {0: "componente(s)", 1: "ciclo(s)", 2: "cavidad(es)"}
    print(f"H0: {h.betti[0]} {names[0]}")
    for i, comp in enumerate(_components(s.complex()), 1):
        print(f"  {i}. {', '.join(sorted(comp))}")
    join = " ∩ ".join if h.space == "nervio" else token
    for k in range(1, a.dim + 1):
        reps = h.cycles.get(k, [])
        print(f"H{k}: {len(reps)} {names.get(k, 'clases')}")
        for i, cyc in enumerate(reps, 1):
            print(f"  {i}. " + "   ".join(join(x) for x in cyc))
    if h.space == "nervio":
        print("(los ciclos están expresados en el nervio: sus vértices son relaciones)")


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


# -- haz --------------------------------------------------------------------

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
    print(f"{a.user} está en el haz: sólo tendrá lo que se le conceda")


def cmd_perm_show(a):
    s = Store.find()
    r = s.sheaf()
    if not r.users:
        print("sin permisos declarados")
        return
    users = r.users
    width = max(len(v) for v in s.vertices)
    print(" " * width + "  " + "  ".join(f"{u:>6}" for u in users))
    for v in s.vertices:
        print(f"{v:<{width}}  " + "  ".join(f"{r.mode(v, u):>6}" for u in users))
    print("\nletra = concedido   - = negado   · = sin sección (se niega)   ! = conflicto")


def cmd_perm_check(a):
    r = Store.find().sheaf()
    if not r.conflicts:
        print("los datos locales se pegan en una sección global: sin obstrucciones")
        return
    print(f"{len(r.conflicts)} obstrucción(es) en H¹(K_b, A):")
    for c in r.conflicts:
        print("  " + c.describe())
    return 2


def cmd_perm_coh(a):
    r = Store.find().sheaf()
    print(f"dim H⁰ = {sum(r.h0.values())}   (grados de libertad de una política global)")
    print(f"dim H¹ = {sum(r.h1.values())}   (lazos de relaciones que gobiernan el mismo bit)")
    for b in r.bits:
        print(f"  {b:<14} H⁰={r.h0[b]}  H¹={r.h1[b]}")


# -- procesos y memoria -------------------------------------------------------

def cmd_paths(a):
    from .run import split_commands
    _, text = split_commands(Path(a.program).read_text(encoding="utf-8"))
    space = progress.ProgressSpace(progress.parse(text))
    reach, good, deadlocks = space.analyze()
    total = 1
    for n in space.lens:
        total *= n + 1
    print(f"espacio de estados: {total} puntos, {len(reach)} alcanzables, "
          f"{total - sum(space.allowed(s) for s in _grid(space.lens))} prohibidos")
    if deadlocks:
        print(f"\n{len(deadlocks)} deadlock(s):")
        for d in deadlocks:
            print(f"  {d}: {space.describe_state(d)}")
    unsafe = reach - good
    if unsafe:
        print(f"zona sin retorno: {_n(len(unsafe), 'estado')} que ya no llega(n) al final")
    if space.final not in reach:
        print("\nninguna ejecución termina")
        return 2
    classes = space.classes(a.max_paths)
    print(f"\n{sum(map(len, classes))} ejecuciones completas en {len(classes)} "
          "clase(s) de dihomotopía:")
    for i, cls in enumerate(classes, 1):
        schedule, sems = space.describe_path(cls[0])
        print(f"  {i}. {_n(len(cls), 'ejecución', 'ejecuciones')}, p. ej. {schedule}")
        if sems:
            print(f"     {sems}")
    return 2 if deadlocks else 0


def _n(k, one, many=None):
    return f"{k} {one if k == 1 else many or one + 's'}"


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
    mode = "ingenuo (semáforos reales)" if a.naive else "topológico (monitor sobre el espacio)"
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
        print(f"{mode}: {a.runs} corridas, {_n(stuck, 'deadlock')}"
              + (f", {waits} esperas impuestas por el monitor" if not a.naive else ""))
        for order, n in sorted(orders.items(), key=lambda x: -x[1]):
            print(f"  {n:>4}  {order or '(sin semáforos)'}")
        return 2 if stuck else 0
    r = runner.run(a.naive)
    for name, word, out in r.output:
        if out:
            print(f"[{name} {word}] {out}")
    if not r.finished:
        print(f"{mode}: {r.error or 'no terminó'}")
        print(f"  atorado en {r.state}: {space.describe_state(r.state)}")
        return 2
    schedule, order = space.describe_path(r.path)
    print(f"{mode}: terminó en {len(r.path)} pasos")
    print(f"  orden: {schedule}")
    if order:
        print(f"  semáforos: {order}")
    if r.waits:
        print(f"  el monitor hizo esperar {_n(r.waits, 'vez', 'veces')} "
              "para no entrar a la zona sin retorno")
    return 0


def _socket(a):
    from .sched import DEFAULT_SOCKET
    return a.socket or DEFAULT_SOCKET


def cmd_sched_serve(a):
    from .sched import serve
    path = _socket(a)
    print(f"planificador topológico escuchando en {path}", flush=True)
    serve(path)


def cmd_sched_status(a):
    from .sched import Client
    c = Client(_socket(a))
    st = c.call(op="status")
    c.close()
    if not st["procs"]:
        print("nadie conectado")
        return
    for p in st["procs"]:
        print(f"  {p['name']:<10} paso {p['pos']}/{p['len']}  siguiente: {p['next']}")
    print(st["describe"])


def cmd_sched_run(a):
    import subprocess
    from .run import split_commands
    from .sched import Client
    commands, text = split_commands(Path(a.program).read_text(encoding="utf-8"))
    prog = progress.parse(text)
    if a.name not in prog.names:
        raise ValueError(f"{a.program} no tiene un proceso {a.name!r}")
    steps = prog.ops[prog.names.index(a.name)]
    c = Client(_socket(a))
    try:
        me = c.call(op="join", name=a.name, plan=[w for _, _, w in steps],
                    capacity=prog.capacity)["name"]
        for kind, sem, word in steps:
            r = c.call(op="step")
            note = "  (esperó: el monitor lo apartó de la zona sin retorno)" if r["waited"] else ""
            print(f"[{me}] {word}{note}", flush=True)
            if kind == "op" and word in commands:
                if subprocess.run(commands[word], shell=True).returncode:
                    raise ValueError(f"`{commands[word]}` falló")
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
    s = Store.find()
    s.enroll(a.name)
    for spec in a.concede:
        rel, _, bits = spec.partition(":")
        s.set_values("@" + rel, [f"+{a.name}:{bits or 'r'}"])
    s.save()
    granted = ", ".join(a.concede) or "nada"
    print(f"{a.name}: usuario de Linux, inscrito en el haz; se le concede {granted}")


def cmd_agent_run(a):
    import os
    from . import agent
    mundo = os.path.abspath(os.path.expanduser(a.mundo or "~/mundo"))
    if _whoami() != a.name:
        # El modelo corre como el usuario del agente: lo que el haz le niega, el kernel se lo niega.
        argv = ["sudo", "-n", "-u", a.name, sys.executable, "-m", "topos", "agent", "run",
                a.name, a.task, "--mundo", mundo,
                "--modelo", a.modelo or agent.DEFAULT_MODEL,
                "--ollama", a.ollama or agent.DEFAULT_OLLAMA or agent.find_ollama()]
        if a.socket or os.environ.get("TOPOS_SCHED"):
            argv += ["--socket", a.socket or os.environ["TOPOS_SCHED"]]
        if a.recursos is not None:
            argv += ["--recursos", *a.recursos]
        sys.stdout.flush()
        os.execvp("sudo", argv)
    llm = agent.Ollama(a.modelo or agent.DEFAULT_MODEL, a.ollama)
    print(f"[{a.name}] {a.task}   (modelo {llm.model})", flush=True)
    summary = agent.run(a.name, a.task, mundo, llm, a.recursos, a.socket,
                        echo=lambda s: print(s, flush=True))
    print(f"[{a.name}] {summary}")


def cmd_agent_eval(a):
    from .agent_eval import evaluate, table
    results = evaluate(a.modelos, a.repeticiones, a.ollama,
                       echo=lambda s: print(s, flush=True))
    print()
    print(table(results))


def cmd_agent_log(a):
    import json
    import time
    from .agent import LOG
    try:
        lines = LOG.read_text(encoding="utf-8").splitlines()[-a.n:]
    except FileNotFoundError:
        print("la bitácora está vacía")
        return
    for line in lines:
        e = json.loads(line)
        when = time.strftime("%H:%M:%S", time.localtime(e["t"]))
        mark = {"ok": "✓", "negado": "✗", "error": "!"}.get(e["estado"], "?")
        args = e.get("args") or {}
        what = ", ".join(f"{k}={v}" for k, v in args.items() if k != "contenido")
        print(f"{when} {mark} {e['agente']:<16} {e['tool']}({what})"
              + (f"  {e['resultado']}" if e["estado"] != "ok" or e["tool"] == "fin" else ""))


def cmd_mem(a):
    import json
    snap = memory.load(a.snapshot) if a.snapshot else memory.snapshot()
    if a.dump:
        Path(a.dump).write_text(json.dumps(snap), encoding="utf-8")
        print(f"snapshot de {len(snap)} procesos en {a.dump}")
        return
    procs, points = memory.build(snap, a.writable)
    classes = memory.kolmogorov(points)
    print(f"{len(procs)} procesos, {len(points)} puntos de memoria, "
          f"{len(classes)} tras el cociente T0")
    h = memory.nerve(procs, points).homology(1)
    print(f"nervio: β0 = {h.betti[0]}, β1 = {h.betti[1]}   [calculado en el {h.space}]")
    if h.space == "primal":
        for i, cyc in enumerate(h.cycles.get(1, []), 1):
            print(f"  ciclo {i}: " + "  ".join(token(x) for x in cyc))
    pairs = memory.shared_pairs(points)
    if pairs:
        print("\npares que comparten más memoria:")
        for (p, q), n in pairs[:10]:
            print(f"  {n:>5}  {p} ↔ {q}")


def cmd_mount(a):
    from .fuse_view import mount
    mount(Store.find(), a.dir, foreground=not a.background, readonly=a.readonly,
          shared=a.shared)


if __name__ == "__main__":
    sys.exit(main())
