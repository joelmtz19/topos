#!/usr/bin/env python3
"""Arranca topOS.iso en QEMU por consola serial, entra y prueba el sistema.

    python3 boot-test.py topOS.iso
Sale con 0 si el sistema arrancó, hizo login solo y los comandos corrieron.
"""

import os
import queue
import re
import subprocess
import sys
import threading
import time

ANSI = re.compile(rb"\x1b\[[0-9;?]*[a-zA-Z]")
COMMANDS = [
    "cat /etc/os-release | head -1",
    "cat ~/mundo/holes",
    "echo hola > ~/mundo/files/prueba.md && topos glue prueba.md tesis.md --as test && topos betti",
    "topos run /usr/share/topos/ejemplos/filosofos.txt --runs 50 --jitter 0.005",
    "echo FIN-DE-PRUEBA",
]


def main(iso):
    accel = ["-accel", "kvm"] if os.path.exists("/dev/kvm") else ["-accel", "tcg"]
    qemu = subprocess.Popen(
        ["qemu-system-x86_64", *accel, "-m", "1536", "-smp", "2", "-cdrom", iso,
         "-boot", "d", "-nographic", "-no-reboot"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = queue.Queue()
    threading.Thread(target=lambda: [out.put(b) for b in iter(lambda: qemu.stdout.read1(4096), b"")],
                     daemon=True).start()
    seen = b""

    def expect(pattern, timeout):
        nonlocal seen
        end = time.time() + timeout
        while time.time() < end:
            try:
                chunk = out.get(timeout=1)
            except queue.Empty:
                continue
            clean = ANSI.sub(b"", chunk).replace(b"\r", b"")
            sys.stdout.write(clean.decode("utf-8", "replace"))
            sys.stdout.flush()
            seen += clean
            if re.search(pattern, seen):
                seen = b""
                return True
        return False

    def send(line):
        qemu.stdin.write(line.encode() + b"\n")
        qemu.stdin.flush()

    t0 = time.time()
    ok = expect(rb"topos@topOS:[^\n]*\$ $", 900)
    print(f"\n[boot-test] prompt {'alcanzado' if ok else 'NUNCA llegó'} en {time.time() - t0:.0f} s")
    if ok:
        send(" && ".join(f"({c})" for c in COMMANDS))
        ok = expect(rb"\nFIN-DE-PRUEBA", 300)
        send("sudo poweroff")
        expect(rb"reboot: Power down|$^", 60)
    qemu.kill()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
