"""La decisión de red y la identificación del que llama, sin red de verdad.
The network decision and caller identification, without a real network."""

import pytest

from topos import net
from topos.store import Store


@pytest.fixture
def s(tmp_path):
    s = Store.init(tmp_path)
    for n in ("payroll", "meeting"):
        s.add_bytes(n, n.encode())
    s.glue(["payroll"], "finance")
    s.glue(["meeting"], "work")
    s.enroll("agent")
    s.set_values("@finance", ["+agent:r", "+net/bank.example:r"])
    s.set_values("@work", ["+agent:rw", "+net/bank.example:r", "+net/docs.example:r"])
    s.net_allow("agent", ["bank.example", "docs.example", "*.github.com"])
    return s


def test_hosts_and_wildcards():
    assert net.host_matches("api.github.com", "*.github.com")
    assert net.host_matches("github.com", "*.github.com")
    assert not net.host_matches("evilgithub.com", "*.github.com")
    assert net.host_matches("Bank.Example.", "bank.example")


def test_only_allowlisted_hosts(s):
    assert net.decide(s, "agent", set(), "docs.example")[0]
    assert net.decide(s, "agent", set(), "api.github.com")[0]
    ok, why = net.decide(s, "agent", set(), "attacker.example")
    assert not ok and "attacker.example" in why


def test_what_was_read_decides_where_it_may_go(s):
    assert net.decide(s, "agent", {"meeting"}, "docs.example")[0]          # trabajo → docs, sí
    ok, why = net.decide(s, "agent", {"meeting", "payroll"}, "docs.example")
    assert not ok and "payroll" in why                                     # la nómina no va a docs
    assert net.decide(s, "agent", {"meeting", "payroll"}, "bank.example")[0]   # al banco, sí
    assert not net.decide(s, "agent", {"/borrado"}, "bank.example")[0]     # lápida: nunca sale


def test_trusted_destination_receives_anything(s):
    s.net_allow("agent", ["ollama"])
    assert not net.decide(s, "agent", {"payroll"}, "ollama")[0]
    s.net_trust("ollama")
    assert net.decide(s, "agent", {"payroll"}, "ollama")[0]


def test_users_without_policy_are_not_restricted(s):
    assert net.decide(s, "someone-else", {"payroll"}, "anywhere.example")[0]


def test_invalid_hosts_are_rejected(s):
    from topos.store import StoreError
    for bad in ("", "a/b", "user@host", "host:80", "*."):
        with pytest.raises(StoreError):
            s.net_allow("agent", [bad])


def test_the_caller_is_found_in_proc_net_tcp(tmp_path):
    (tmp_path / "net").mkdir()
    local = net._hex_addr("127.0.0.1", 40000)
    assert local == "0100007F:9C40"
    (tmp_path / "net" / "tcp").write_text(
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        f"   0: {local} 0100007F:0C38 01 00000000:00000000 00:00000000 00000000  1001        0 55555 1\n")
    assert net.peer_socket("127.0.0.1", 40000, proc=tmp_path) == (1001, 55555)
    assert net.peer_socket("127.0.0.1", 40001, proc=tmp_path) == (None, None)


def test_ruleset_locks_agents_to_the_proxy():
    rules = net.ruleset({1001, 1002}, 3128)
    assert "meta skuid { 1001, 1002 } ip daddr 127.0.0.1 tcp dport 3128 accept" in rules
    assert "meta skuid { 1001, 1002 } counter reject" in rules
