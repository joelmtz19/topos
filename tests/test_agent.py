import json

import pytest

from topos import agent


class Scripted:
    """A 'model' that calls tools from a script and records what it gets back."""

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
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "LOG", tmp_path / "log.jsonl")
    root = tmp_path / "world"
    (root / "files").mkdir(parents=True)
    (root / "relations" / "work").mkdir(parents=True)
    (root / "files" / "notes.md").write_text("reunión: mandar propuesta el lunes", encoding="utf-8")
    return root


def test_agent_reads_writes_and_finishes(world):
    llm = Scripted([("read", {"path": "files/notes.md"}),
                    ("write", {"path": "relations/work/summary.md", "content": "- propuesta"}),
                    ("finish", {"summary": "resumí las notas"})])
    out = []
    assert agent.run("agent-x", "resume", world, llm, echo=out.append) == "resumí las notas"
    assert (world / "relations" / "work" / "summary.md").read_text() == "- propuesta"
    assert "mandar propuesta" in llm.seen[1]["content"]          # the result reached the model
    log = [json.loads(x) for x in agent.LOG.read_text(encoding="utf-8").splitlines()]
    assert [e["tool"] for e in log] == ["read", "write", "finish", "end"]
    assert all(e["status"] == "ok" for e in log)


def test_spanish_tool_and_argument_names_still_work(world):
    llm = Scripted([("leer", {"ruta": "files/notes.md"}),
                    ("anexar", {"ruta": "files/notes.md", "texto": "- nueva"}),
                    ("terminar", {"resumen": "hecho"})])
    assert agent.run("agent-x", "haz algo", world, llm, echo=lambda s: None) == "hecho"
    assert (world / "files" / "notes.md").read_text(encoding="utf-8").endswith("- nueva\n")


def test_paths_outside_the_world_are_denied(world):
    llm = Scripted([("read", {"path": "../../etc/passwd"}), ("finish", {"summary": "no pude"})])
    out = []
    agent.run("agent-x", "curiosea", world, llm, echo=out.append)
    assert out[0].startswith("  ✗ read")


def test_writes_are_limited_to_reserved_resources(world):
    w = agent.World(world, {"summary.md"})
    assert agent.run_tool(w, "write", {"path": "files/other.md", "content": "x"})[0] == "denied"
    assert agent.run_tool(w, "write", {"path": "files/summary.md", "content": "x"})[0] == "ok"


def test_bad_tool_calls_come_back_as_errors(world):
    w = agent.World(world)
    assert agent.run_tool(w, "delete_everything", {})[0] == "error"
    assert agent.run_tool(w, "_path", {"rel": "x"})[0] == "error"
    assert agent.run_tool(w, "finish", {})[0] == "error"          # finish is not a world method
    assert agent.run_tool(w, "read", {"path": "files/missing.md"})[0] == "error"


def test_small_model_quirks_are_absorbed(world):
    assert agent.normalize_args("relate", {"ruta": "files/payroll.md", "relacion": "t"}) == \
        {"file": "payroll.md", "relation": "t"}
    assert agent.normalize_args("finish", {"mensaje": "listo"}) == {"summary": "listo"}
    assert agent.normalize_args("read", {"whatever": "files/a"}) == {"path": "files/a"}
    assert agent.strip_thinking("<think>mmm</think> hola") == "hola"


def test_append_keeps_what_was_there(world):
    w = agent.World(world)
    w.append("files/notes.md", "- nueva")
    assert (world / "files" / "notes.md").read_text(encoding="utf-8") == \
        "reunión: mandar propuesta el lunes\n- nueva\n"


def test_a_model_that_rambles_is_nudged_back_to_tools(world):
    class Rambler(Scripted):
        def chat(self, messages, tools):
            if len(self.seen) == 0:
                self.seen.append(messages[-1])
                return {"role": "assistant", "content": "Okay, let me think about this..."}
            return super().chat(messages, tools)
    llm = Rambler([("finish", {"summary": "hecho"})])
    assert agent.run("agent-x", "haz algo", world, llm, echo=lambda s: None) == "hecho"


def test_tool_calls_written_as_text_are_recovered():
    text = 'Uso la herramienta:\n```json\n{"type": "function", "function": {"name": "leer", ' \
           '"parameters": {"ruta": "files/a.md"}}}\n```\ny {"name": "no_existe", "arguments": {}}'
    assert agent.calls_from_text(text) == \
        [{"function": {"name": "read", "arguments": {"ruta": "files/a.md"}}}]
    assert agent.calls_from_text("sin llamadas {roto") == []
