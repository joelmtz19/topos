from pathlib import Path

from topos.cli import main
from topos.progress import parse
from topos.run import Runner, split_commands

EJ = Path(__file__).parent.parent / "ejemplos"


def runner(name, **kw):
    commands, text = split_commands((EJ / name).read_text(encoding="utf-8"))
    return Runner(parse(text), commands, **kw)


def test_monitor_never_deadlocks_where_naive_does():
    r = runner("filosofos.txt", jitter=0.005, seed=1)
    guided = [r.run() for _ in range(30)]
    assert all(g.finished for g in guided)
    assert sum(g.waits for g in guided) > 0
    space = r.space
    for g in guided:
        assert all(s in r.good for s in _states(space, g.path))


def test_naive_mode_detects_a_real_deadlock():
    # Sin jitter entre el primer P y el segundo, con pausa antes: casi siempre se atora.
    r = runner("cena.txt", jitter=0.05, seed=7, patience=0.1)
    results = [r.run(naive=True) for _ in range(8)]
    stuck = [x for x in results if not x.finished]
    assert stuck and all(x.error == "deadlock" for x in stuck)
    assert all(x.state == (1, 1) for x in stuck)


def test_commands_run_and_are_reported(capsys):
    assert main(["run", str(EJ / "filosofos.txt"), "--seed", "2"]) == 0
    out = capsys.readouterr().out
    assert "Ana come con t1 y t2" in out and "Caro come con t3 y t1" in out


def test_paths_ignores_do_lines(capsys):
    assert main(["paths", str(EJ / "filosofos.txt")]) == 2
    assert "deadlock" in capsys.readouterr().out


def _states(space, path):
    s = space.origin
    yield s
    for i in path:
        s = space.step(s, i)
        yield s
