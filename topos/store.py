"""El almacén: archivos como vértices, relaciones como subcomplejos.

En lugar de un árbol de carpetas, cada archivo es un vértice y cada relación
es un subcomplejo con nombre (una lista de símplices). Un archivo puede vivir
en muchas relaciones a la vez y las relaciones se pueden traslapar, que es
justo lo que un árbol no permite.

Todo vive en `.topos/` junto al directorio de trabajo, como `.git/`:
    objects/<sha256>   contenidos, direccionados por hash
    state.json         vértices, relaciones y el haz de permisos
"""

import hashlib
import json
import os
import time
from pathlib import Path

from . import sheaf
from .complex import Complex, simplex, token
from .i18n import t

META = ".topos"
FORBIDDEN = set("/+@\\")


class StoreError(Exception):
    pass


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.meta = self.root / META
        self.state = json.loads((self.meta / "state.json").read_text(encoding="utf-8"))
        self.state.setdefault("mtimes", {})   # almacenes viejos no las tenían
        self.state.setdefault("enrolled", [])

    @classmethod
    def init(cls, root="."):
        meta = Path(root) / META
        if meta.exists():
            raise StoreError(t(f"ya hay un almacén en {meta}", f"there is already a store at {meta}"))
        (meta / "objects").mkdir(parents=True)
        empty = {"vertices": {}, "relations": {}, "govern": {}, "values": {}, "mtimes": {}}
        (meta / "state.json").write_text(json.dumps(empty, indent=2), encoding="utf-8")
        return cls(root)

    @classmethod
    def find(cls, start=None):
        env = os.environ.get("TOPOS_HOME")
        if env:
            return cls(env)
        here = Path(start or os.getcwd()).resolve()
        for d in (here, *here.parents):
            if (d / META / "state.json").exists():
                return cls(d)
        raise StoreError(t("no hay almacén aquí; corre `topos init`", "no store here; run `topos init`"))

    def save(self):
        tmp = self.meta / "state.json.tmp"
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.meta / "state.json")

    # -- vértices ----------------------------------------------------------

    @property
    def vertices(self):
        return sorted(self.state["vertices"])

    def add_bytes(self, name, data):
        if not name or FORBIDDEN & set(name):
            raise StoreError(t(f"nombre inválido {name!r}: no uses / + @ \\",
                                f"invalid name {name!r}: do not use / + @ \\"))
        digest = hashlib.sha256(data).hexdigest()
        obj = self.meta / "objects" / digest
        if not obj.exists():
            obj.write_bytes(data)
        self.state["vertices"][name] = digest
        self.state["mtimes"][name] = time.time()
        return name

    def add_file(self, path, name=None):
        path = Path(path)
        return self.add_bytes(name or path.name, path.read_bytes())

    def cat(self, name):
        self._need(name)
        return (self.meta / "objects" / self.state["vertices"][name]).read_bytes()

    def remove_vertex(self, name):
        self._need(name)
        self.cut([name])
        del self.state["vertices"][name]
        self.state["values"].pop(name, None)
        self.state["mtimes"].pop(name, None)

    def rename_vertex(self, old, new):
        """Renombra un vértice sin tocar su contenido, sus relaciones ni su haz."""
        self._need(old)
        if new == old:
            return
        if not new or FORBIDDEN & set(new):
            raise StoreError(t(f"nombre inválido {new!r}: no uses / + @ \\",
                                f"invalid name {new!r}: do not use / + @ \\"))
        if new in self.state["vertices"]:
            self.remove_vertex(new)
        self.state["vertices"][new] = self.state["vertices"].pop(old)
        if old in self.state["mtimes"]:
            self.state["mtimes"][new] = self.state["mtimes"].pop(old)
        for label, ss in self.state["relations"].items():
            self.state["relations"][label] = [
                list(simplex(new if v == old else v for v in s)) for s in ss]
        if old in self.state["values"]:
            self.state["values"][new] = self.state["values"].pop(old)

    def mtime(self, name, default=0.0):
        return self.state["mtimes"].get(name, default)

    def touch(self, name, when=None):
        self._need(name)
        self.state["mtimes"][name] = time.time() if when is None else when

    def _need(self, *names):
        missing = [n for n in names if n not in self.state["vertices"]]
        if missing:
            raise StoreError(t("no existe: ", "does not exist: ") + ", ".join(missing))

    # -- relaciones --------------------------------------------------------

    @property
    def relations(self):
        return {label: [tuple(s) for s in ss] for label, ss in self.state["relations"].items()}

    def glue(self, names, label=None):
        """Pega un símplice con los archivos dados dentro de la relación `label`."""
        s = simplex(names)
        self._need(*s)
        rels = self.state["relations"]
        if label is None:
            n = 1
            while f"r{n}" in rels:
                n += 1
            label = f"r{n}"
        if FORBIDDEN & set(label):
            raise StoreError(t(f"etiqueta inválida {label!r}", f"invalid label {label!r}"))
        cx = Complex(rels.get(label, []))
        cx.add(s)
        rels[label] = [list(g) for g in cx.generators]
        return label

    def cut(self, names):
        """Quita el símplice y sus cocaras de todas las relaciones."""
        s = simplex(names)
        for label, ss in list(self.state["relations"].items()):
            cx = Complex(ss)
            if s not in cx:
                continue
            before = {tuple(g) for g in ss}
            cx.remove(s)
            # Las caras sueltas que deja el corte se van; los vértices que ya
            # estaban sueltos (miembros de una carpeta) se quedan.
            gens = [list(g) for g in cx.generators if len(g) > 1 or g in before]
            if gens:
                self.state["relations"][label] = gens
            else:
                self._drop_relation(label)

    def create_relation(self, label):
        """Una relación vacía, como una carpeta recién hecha."""
        if not label or FORBIDDEN & set(label):
            raise StoreError(t(f"etiqueta inválida {label!r}", f"invalid label {label!r}"))
        if label in self.state["relations"]:
            raise StoreError(t(f"ya existe la relación {label!r}", f"relation {label!r} already exists"))
        self.state["relations"][label] = []

    def rename_relation(self, old, new):
        if old not in self.state["relations"]:
            raise StoreError(t(f"no existe la relación {old!r}", f"no relation {old!r}"))
        if not new or FORBIDDEN & set(new):
            raise StoreError(t(f"etiqueta inválida {new!r}", f"invalid label {new!r}"))
        if new in self.state["relations"]:
            raise StoreError(t(f"ya existe la relación {new!r}", f"relation {new!r} already exists"))
        rels = self.state["relations"]
        rels[new] = rels.pop(old)
        if old in self.state["govern"]:
            self.state["govern"][new] = self.state["govern"].pop(old)
        if "@" + old in self.state["values"]:
            self.state["values"]["@" + new] = self.state["values"].pop("@" + old)

    def unglue(self, label, name):
        """Saca un vértice de una sola relación; el resto del complejo no se toca."""
        if label not in self.state["relations"]:
            raise StoreError(t(f"no existe la relación {label!r}", f"no relation {label!r}"))
        cx = Complex(self.state["relations"][label])
        cx.remove((name,))
        self.state["relations"][label] = [list(g) for g in cx.generators]

    def drop(self, label):
        if label not in self.state["relations"]:
            raise StoreError(t(f"no existe la relación {label!r}", f"no relation {label!r}"))
        self._drop_relation(label)

    def _drop_relation(self, label):
        del self.state["relations"][label]
        self.state["govern"].pop(label, None)
        self.state["values"].pop("@" + label, None)

    def members(self, label):
        return sorted({v for s in self.relations.get(label, []) for v in s})

    def complex(self):
        return Complex([(v,) for v in self.vertices]
                       + [s for ss in self.relations.values() for s in ss])

    def label_of(self, gen):
        """Nombre de un generador para mostrar: las relaciones que lo contienen."""
        owners = [label for label, ss in self.relations.items()
                  if any(set(gen) <= set(s) for s in ss)]
        return "/".join(owners) if owners else token(gen)

    def homology(self, maxdim=1):
        return self.complex().homology(maxdim, namer=self.label_of)

    # -- haz de permisos ---------------------------------------------------

    def govern(self, label, specs):
        if label not in self.state["relations"]:
            raise StoreError(t(f"no existe la relación {label!r}", f"no relation {label!r}"))
        bits = set(self.state["govern"].get(label, []))
        for spec in specs:
            bits.update(sheaf.expand(spec))
        self.state["govern"][label] = sorted(bits)

    def set_values(self, target, specs):
        if target.startswith("@"):
            if target[1:] not in self.state["relations"]:
                raise StoreError(t(f"no existe la relación {target[1:]!r}", f"no relation {target[1:]!r}"))
        else:
            self._need(target)
        current = self.state["values"].setdefault(target, {})
        current.update(sheaf.parse_values(specs))

    def sheaf(self):
        return sheaf.analyze(self.vertices, self.relations,
                             self.state["govern"], self.state["values"],
                             self.state["enrolled"])

    def enroll(self, user):
        """Mete a un usuario al haz sin darle nada: lo que no se le conceda, se le niega."""
        if not user or ":" in user or FORBIDDEN & set(user):
            raise StoreError(t(f"usuario inválido {user!r}", f"invalid user {user!r}"))
        if user not in self.state["enrolled"]:
            self.state["enrolled"].append(user)
