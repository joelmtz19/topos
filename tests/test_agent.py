import json

import pytest

from topos import agent


class Scripted:
    """Un 'modelo' que pide herramientas según un guion y registra lo que le devuelven."""

    def __init__(self, calls):
        self.calls, self.seen = list(calls), []

    def chat(self, messages, tools):
        self.seen.append(messages[-1])
        if not self.calls:
            return {"role": "assistant", "content": "listo"}
        name, args = self.calls.pop(0)
        return {"role": "assistant", "content": "",
                "tool_calls": [{"function": {"name": name, "arguments": args}}]}


@pytest.fixture
def mundo(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "LOG", tmp_path / "bitacora.jsonl")
    root = tmp_path / "mundo"
    (root / "files").mkdir(parents=True)
    (root / "relations" / "trabajo").mkdir(parents=True)
    (root / "files" / "notas.md").write_text("reunión: mandar propuesta el lunes", encoding="utf-8")
    return root


def test_agent_reads_writes_and_finishes(mundo):
    llm = Scripted([("leer", {"ruta": "files/notas.md"}),
                    ("escribir", {"ruta": "relations/trabajo/resumen.md", "contenido": "- propuesta"}),
                    ("terminar", {"resumen": "resumí las notas"})])
    out = []
    assert agent.run("agente-x", "resume", mundo, llm, echo=out.append) == "resumí las notas"
    assert (mundo / "relations" / "trabajo" / "resumen.md").read_text() == "- propuesta"
    assert "mandar propuesta" in llm.seen[1]["content"]          # el resultado le llegó
    log = [json.loads(x) for x in agent.LOG.read_text().splitlines()]
    assert [e["tool"] for e in log] == ["leer", "escribir", "terminar", "fin"]


def test_paths_outside_the_world_are_denied(mundo):
    llm = Scripted([("leer", {"ruta": "../../etc/passwd"}), ("terminar", {"resumen": "no pude"})])
    out = []
    agent.run("agente-x", "curiosea", mundo, llm, echo=out.append)
    assert out[0].startswith("  ✗ leer") and "fuera del mundo" in out[0]


def test_writes_are_limited_to_reserved_resources(mundo):
    w = agent.World(mundo, {"resumen.md"})
    assert agent.run_tool(w, "escribir", {"ruta": "files/otro.md", "contenido": "x"})[0] == "negado"
    assert agent.run_tool(w, "escribir", {"ruta": "files/resumen.md", "contenido": "x"})[0] == "ok"


def test_bad_tool_calls_come_back_as_errors(mundo):
    w = agent.World(mundo)
    assert agent.run_tool(w, "borrar_todo", {})[0] == "error"
    assert agent.run_tool(w, "_path", {"rel": "x"})[0] == "error"
    assert agent.run_tool(w, "leer", {"ruta": "files/no-existe.md"})[0] == "error"


def test_small_model_quirks_are_absorbed(mundo):
    assert agent.normalize_args("relacionar", {"ruta": "files/nomina.md", "relacion": "t"}) == \
        {"archivo": "nomina.md", "relacion": "t"}
    assert agent.normalize_args("terminar", {"mensaje": "listo"}) == {"resumen": "listo"}
    assert agent.normalize_args("leer", {"cualquier_cosa": "files/a"}) == {"ruta": "files/a"}
    assert agent.strip_thinking("<think>mmm</think> hola") == "hola"


def test_anexar_keeps_what_was_there(mundo):
    w = agent.World(mundo)
    w.anexar("files/notas.md", "- nueva")
    assert (mundo / "files" / "notas.md").read_text(encoding="utf-8") == \
        "reunión: mandar propuesta el lunes\n- nueva\n"


def test_a_model_that_rambles_is_nudged_back_to_tools(mundo):
    class Rambler(Scripted):
        def chat(self, messages, tools):
            if len(self.seen) == 0:
                self.seen.append(messages[-1])
                return {"role": "assistant", "content": "Okay, let me think about this..."}
            return super().chat(messages, tools)
    llm = Rambler([("terminar", {"resumen": "hecho"})])
    assert agent.run("agente-x", "haz algo", mundo, llm, echo=lambda s: None) == "hecho"
