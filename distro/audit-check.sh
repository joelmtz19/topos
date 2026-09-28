#!/usr/bin/env bash
# F3, cerrado: el agente no puede borrar ni falsificar la bitácora.
# F3, closed: the agent cannot wipe or forge the audit log.
#
#   docker run --rm -i --device /dev/fuse --cap-add SYS_ADMIN \
#     --security-opt apparmor:unconfined topos-os bash -l distro/audit-check.sh
set -u
fails=0
ok()  { printf '  ✓ %s\n' "$*"; }
bad() { printf '  ✗ %s\n' "$*"; fails=$((fails + 1)); }
M=$HOME/mundo
AUDIT="$TOPOS_HOME/.topos/audit.jsonl"

d=$(mktemp -d); for f in payroll a b c; do printf 'secret\n' > "$d/$f.md"; done
topos add "$d"/*.md > /dev/null && rm -rf "$d"
topos glue payroll.md a.md b.md c.md --as finance > /dev/null
topos agent create agent-notes --grant finance:r > /dev/null

echo "== el agente actúa (por MCP): sus acciones quedan en la bitácora protegida"
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"read","arguments":{"path":"files/payroll.md"}}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"read","arguments":{"path":"files/a.md"}}}' \
  '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"read","arguments":{"path":"files/b.md"}}}' \
  | sudo -n -u agent-notes env TOPOS_LANG=en topos mcp --world "$M" >/dev/null
n=$(topos agent log -n 50 | grep -c agent-notes)
[ "$n" -ge 3 ] && ok "quedaron registradas las acciones de agent-notes ($n líneas)" || bad "no se registró"

echo "== el agente intenta borrar la bitácora"
if sudo -n -u agent-notes bash -c ": > '$AUDIT'" 2>/dev/null; then
    bad "el agente truncó la bitácora"
else
    ok "el agente no puede truncar la bitácora (.topos es 700, la lleva el dueño)"
fi
if sudo -n -u agent-notes cat "$AUDIT" >/dev/null 2>&1; then
    bad "el agente puede leer la bitácora de todos"
else
    ok "el agente ni siquiera puede leerla"
fi

echo "== el agente intenta firmarse como otro"
printf '{"agent":"otro-agente","tool":"read","status":"ok"}\n' | sudo -n -u agent-notes \
    python3 -c 'import socket,sys,os; s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM); s.connect(os.environ["TOPOS_AUDIT"]); s.sendall(sys.stdin.buffer.read()); s.close()' 2>/dev/null
sleep 0.3
if topos agent log -n 5 | grep -q "otro-agente"; then
    bad "el agente se firmó como otro-agente"
else
    ok "el demonio impuso el uid real: no pudo firmarse como otro"
fi

echo "== el dueño verifica la cadena"
topos verify | sed 's/^/  /'
topos verify >/dev/null && ok "la cadena está intacta" || bad "verify reportó manipulación"

echo "== si alguien edita una línea intermedia, verify lo detecta"
sudo sed -i '1s/read/HACK/' "$AUDIT" 2>/dev/null   # edita la 1ª entrada, que tiene sucesoras
if topos verify >/dev/null; then
    bad "verify no detectó la edición"
else
    ok "verify detecta la edición: la cadena se rompe en la siguiente línea"
fi

echo
[ "$fails" -eq 0 ] && echo "listo / ok" || echo "$fails falla(s) / failure(s)"
exit "$fails"
