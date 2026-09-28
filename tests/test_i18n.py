from pathlib import Path

import pytest

from topos import agent, i18n
from topos.cli import main
from topos.progress import ProgressSpace, parse

EJ = Path(__file__).parent.parent / "ejemplos"


@pytest.mark.parametrize("env, expected", [
    ({"TOPOS_LANG": "en"}, "en"),
    ({"TOPOS_LANG": "es"}, "es"),
    ({"TOPOS_LANG": "", "LANG": "es_MX.UTF-8"}, "es"),
    ({"TOPOS_LANG": "", "LC_ALL": "", "LC_MESSAGES": "", "LANG": "de_DE.UTF-8"}, "en"),
])
def test_language_comes_from_the_environment(monkeypatch, env, expected):
    for k in ("TOPOS_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert i18n.lang() == expected


def test_the_same_command_speaks_both_languages(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOPOS_HOME", raising=False)
    monkeypatch.setenv("TOPOS_LANG", "en")
    assert main(["init"]) == 0
    assert "empty store" in capsys.readouterr().out
    monkeypatch.setenv("TOPOS_LANG", "es")
    assert main(["holes"]) == 0
    assert "componente(s)" in capsys.readouterr().out


def test_spanish_command_aliases(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TOPOS_HOME", raising=False)
    for n in "abc":
        (tmp_path / n).write_text(n)
    main(["iniciar"])
    main(["agregar", "a", "b", "c"])
    main(["pegar", "a", "b", "--como", "p"])
    main(["pegar", "b", "c", "--as", "q"])
    main(["pegar", "a", "c", "--as", "r"])
    capsys.readouterr()
    main(["huecos"])
    assert "H1: 1" in capsys.readouterr().out


def test_deadlock_description_in_english(monkeypatch):
    monkeypatch.setenv("TOPOS_LANG", "en")
    space = ProgressSpace(parse((EJ / "cena.txt").read_text(encoding="utf-8")))
    assert "A holds disco and waits for P(impresora)" in space.describe_state((1, 1))


def test_agent_prompt_and_tools_follow_the_language(monkeypatch):
    monkeypatch.setenv("TOPOS_LANG", "en")
    read = next(d for n, d, _ in agent.tools() if n == "read")
    assert read.startswith("Read a file")
    monkeypatch.setenv("TOPOS_LANG", "es")
    read = next(d for n, d, _ in agent.tools() if n == "read")
    assert read.startswith("Lee un archivo")
