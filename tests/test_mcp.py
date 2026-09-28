"""El servidor MCP hablado por JSON-RPC, sin montar nada.
The MCP server spoken to over JSON-RPC, with nothing mounted."""

import io
import json

import pytest

from topos import agent, mcp


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr(agent, "LOG", tmp_path / "log.jsonl")
    root = tmp_path / "world"
    (root / "files").mkdir(parents=True)
    (root / "relations" / "work").mkdir(parents=True)
    (root / "star" / "notes.md" / "work").mkdir(parents=True)
    (root / "star" / "notes.md" / "work" / "notes.md").write_text("x", encoding="utf-8")
    (root / "star" / "notes.md" / "work" / "todo.md").write_text("x", encoding="utf-8")
    (root / "files" / "notes.md").write_text("mandar propuesta", encoding="utf-8")
    (root / "holes").write_text("H1: 1 ciclo(s)\n", encoding="utf-8")
    return root


def talk(world, *messages, **kw):
    out = io.StringIO()
    lines = "\n".join(m if isinstance(m, str) else json.dumps(m) for m in messages) + "\n"
    mcp.serve(world, stdin=io.StringIO(lines), stdout=out, **kw)
    return [json.loads(x) for x in out.getvalue().splitlines()]


def call(i, name, **args):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call",
            "params": {"name": name, "arguments": args}}


def test_handshake_and_tool_list(world):
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "prueba", "version": "0"}}}
    r = talk(world, init, {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert len(r) == 2                                   # la notificación no lleva respuesta
    assert r[0]["result"]["protocolVersion"] == "2025-06-18"
    assert r[0]["result"]["serverInfo"]["name"] == "topos"
    names = {x["name"] for x in r[1]["result"]["tools"]}
    assert {"read", "write", "relate", "holes", "star", "betti"} <= names
    assert "finish" not in names


def test_unknown_protocol_version_gets_ours(world):
    r = talk(world, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {"protocolVersion": "1999-01-01"}})
    assert r[0]["result"]["protocolVersion"] == mcp.PROTOCOL_VERSIONS[0]


def test_tools_read_write_and_see_the_shape(world):
    r = talk(world, call(1, "read", path="files/notes.md"),
             call(2, "write", path="relations/work/summary.md", content="- propuesta"),
             call(3, "holes"), call(4, "star", file="notes.md"))
    assert r[0]["result"] == {"content": [{"type": "text", "text": "mandar propuesta"}], "isError": False}
    assert (world / "relations" / "work" / "summary.md").read_text() == "- propuesta"
    assert "H1: 1" in r[2]["result"]["content"][0]["text"]
    assert r[3]["result"]["content"][0]["text"] == "work: notes.md, todo.md"


def test_denials_come_back_as_tool_errors_and_are_logged(world):
    r = talk(world, call(1, "read", path="../../etc/passwd"))
    assert r[0]["result"]["isError"] is True
    log = [json.loads(x) for x in agent.LOG.read_text(encoding="utf-8").splitlines()]
    assert log[0]["via"] == "mcp" and log[0]["status"] == "denied"


def test_read_only_server_has_no_write_tools(world):
    r = talk(world, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
             call(2, "write", path="files/x.md", content="x"), readonly=True)
    names = {x["name"] for x in r[0]["result"]["tools"]}
    assert not names & {"write", "append", "relate"}
    assert r[1]["result"]["isError"] is True
    assert not (world / "files" / "x.md").exists()


def test_protocol_errors(world):
    r = talk(world, "{esto no es json", {"jsonrpc": "2.0", "id": 7, "method": "no/existe"},
             [{"jsonrpc": "2.0", "id": 8, "method": "ping"}, {"jsonrpc": "2.0", "id": 9, "method": "ping"}])
    assert r[0]["error"]["code"] == -32700
    assert r[1]["error"]["code"] == -32601
    assert [x["id"] for x in r[2]] == [8, 9]
