from topos import memory


def line(inode, path, perms="rw-s", off="0"):
    return f"7f00-7f10 {perms} {off} 00:01 {inode} {path}"


SNAP = {
    "1": {"name": "a", "maps": [line(10, "/dev/shm/ab"), line(30, "/dev/shm/ca"),
                               "5500-5600 rw-p 0 00:00 0 [heap]"]},
    "2": {"name": "b", "maps": [line(10, "/dev/shm/ab"), line(20, "/dev/shm/bc")]},
    "3": {"name": "c", "maps": [line(20, "/dev/shm/bc"), line(30, "/dev/shm/ca"),
                               line(99, "/usr/lib/libc.so", "r-xp"),
                               line(98, "/usr/lib/libm.so", "r-xp")]},
}


def test_pairwise_sharing_makes_a_loop():
    procs, points = memory.build(SNAP, writable_only=True)
    assert len(points) == 3
    assert memory.nerve(procs, points).betti(1) == [1, 1]


def test_kolmogorov_quotient_merges_indistinguishable_points():
    procs, points = memory.build(SNAP)
    classes = memory.kolmogorov(points)
    assert len(points) == 6        # 3 shm, libc, libm y el heap de a
    # libc y libm sólo las ve c: ningún abierto las separa.
    assert sorted(classes[frozenset({"c[3]"})]) == ["/usr/lib/libc.so@0", "/usr/lib/libm.so@0"]
    assert len(classes) == 5


def test_parses_real_maps_format():
    m = memory.MAPS.match("7f1c2a000000-7f1c2a022000 r--p 00000000 08:01 1835041 /usr/lib/x.so")
    assert m and m[7] == "/usr/lib/x.so"
