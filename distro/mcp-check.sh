#!/usr/bin/env bash
# Un cliente MCP real (el SDK oficial de Python) contra `topos mcp` corriendo
# como el usuario del agente, sobre un mundo montado: el kernel hace cumplir el haz.
# A real MCP client (the official Python SDK) against `topos mcp` running as the
# agent's user over a mounted world: the kernel enforces the sheaf.
#
#   docker run --rm -i --device /dev/fuse --cap-add SYS_ADMIN \
#     --security-opt apparmor:unconfined -e TOPOS_LANG=en topos-os bash -l distro/mcp-check.sh
set -u
sudo apt-get update -qq >/dev/null && sudo apt-get install -y -qq python3-venv >/dev/null
python3 -m venv /tmp/cliente && /tmp/cliente/bin/pip install -q mcp >/dev/null

d=$(mktemp -d)
printf 'Monday: Ana sends the proposal on Wednesday.\n' > "$d/meeting.md"
printf -- '- (empty)\n' > "$d/todo.md"
printf 'Ana 38417\n' > "$d/payroll.md"
topos add "$d"/*.md > /dev/null && rm -rf "$d"
topos glue meeting.md todo.md --as work > /dev/null
topos glue payroll.md --as finance > /dev/null
topos agent create agent-notes --grant work:rw

/tmp/cliente/bin/python - <<'PY'
import asyncio, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = StdioServerParameters(command="sudo", args=[
    "-n", "-u", "agent-notes", "env", "TOPOS_LANG=en",
    "topos", "mcp", "--world", "/home/topos/mundo"])

CHECKS = [
    ("read", {"path": "relations/work/meeting.md"}, False, "Ana sends"),
    ("read", {"path": "files/payroll.md"}, True, "denied"),
    ("relate", {"file": "payroll.md", "relation": "work"}, True, ""),
    ("write", {"path": "relations/work/summary.md", "content": "- Ana: proposal (Wednesday)\n"}, False, "wrote"),
    ("holes", {}, False, "H1"),
    ("star", {"file": "meeting.md"}, False, "work:"),
]

def g(obj, *names):
    """El SDK cambió de camelCase a snake_case; aceptamos los dos."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    raise AttributeError(names)

async def main():
    fails = 0
    async with stdio_client(SERVER) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            info = g(init, "server_info", "serverInfo")
            print(f"server {info.name} {info.version}, protocol {g(init, 'protocol_version', 'protocolVersion')}")
            tools = sorted(x.name for x in (await s.list_tools()).tools)
            print("tools:", ", ".join(tools))
            for name, args, want_error, needle in CHECKS:
                res = await s.call_tool(name, args)
                text = res.content[0].text if res.content else ""
                is_error = bool(g(res, "is_error", "isError"))
                ok = is_error == want_error and needle in text
                fails += not ok
                print(f"  {'✓' if ok else '✗'} {name}({', '.join(f'{k}={v!r}' for k, v in args.items() if k != 'content')})"
                      f"  isError={is_error}  {text.splitlines()[0][:70] if text else ''}")
    sys.exit(fails)

asyncio.run(main())
PY
rc=$?
echo "== bitácora / log"
topos agent log -n 10
echo; [ "$rc" -eq 0 ] && echo "listo / ok" || echo "$rc falla(s) / failure(s)"
exit "$rc"
