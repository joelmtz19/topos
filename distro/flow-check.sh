#!/usr/bin/env bash
# La fuga con permisos legítimos, cerrada: un agente que SÍ puede leer finanzas y
# escribir en trabajo copia la nómina a trabajo; bob, que sólo lee trabajo, no la ve.
# The legitimate-permission leak, closed: an agent that CAN read finance and write
# work copies the payroll into work; bob, who only reads work, cannot see it.
#
#   docker run --rm -i --device /dev/fuse --cap-add SYS_ADMIN \
#     --security-opt apparmor:unconfined topos-os bash -l distro/flow-check.sh
set -u
fails=0
ok()   { printf '  ✓ %s\n' "$*"; }
bad()  { printf '  ✗ %s\n' "$*"; fails=$((fails + 1)); }
M=$HOME/mundo

d=$(mktemp -d)
printf 'Ana 38417\n' > "$d/payroll.md"
printf 'Monday: Ana sends the proposal.\n' > "$d/meeting.md"
printf -- '- (empty)\n' > "$d/todo.md"
topos add "$d"/*.md > /dev/null && rm -rf "$d"
topos glue payroll.md --as finance > /dev/null
topos glue meeting.md todo.md --as work > /dev/null
topos agent create agent-notes --grant finance:r work:rw
topos agent create bob --grant work:r

echo "== 1. shell: cat payroll > work/leak.md, as agent-notes (every step is allowed)"
sudo -n -u agent-notes bash -c "cat $M/files/payroll.md > $M/relations/work/leak.md" \
    && ok "agent-notes wrote the copy (reading finance and writing work are both allowed)" \
    || bad "agent-notes could not write the copy"
sudo -n -u bob cat "$M/relations/work/todo.md" > /dev/null \
    && ok "bob still reads the rest of work" || bad "bob lost access to work"
if sudo -n -u bob cat "$M/relations/work/leak.md" > /dev/null 2>&1; then
    bad "bob read the copied payroll"
else
    ok "bob cannot read the copy: the payroll's mark travelled with it"
fi

echo "== 2. MCP: agent-notes reads the payroll and writes a summary"
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"read","arguments":{"path":"files/payroll.md"}}}' \
  '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"write","arguments":{"path":"relations/work/summary.md","content":"Ana earns 38417\n"}}}' \
  | sudo -n -u agent-notes env TOPOS_LANG=en topos mcp --world "$M" > /tmp/mcp.out
grep -q '"id": 3' /tmp/mcp.out && grep -q 'wrote relations/work/summary.md' /tmp/mcp.out \
    && ok "agent-notes wrote summary.md through MCP" || bad "the MCP write failed"
if sudo -n -u bob cat "$M/relations/work/summary.md" > /dev/null 2>&1; then
    bad "bob read the summary"
else
    ok "bob cannot read the summary either"
fi
sudo -n -u agent-notes cat "$M/relations/work/summary.md" > /dev/null \
    && ok "agent-notes can (it reads the source)" || bad "agent-notes lost its own summary"

echo "== topos flow show"
topos flow show | sed 's/^/  /'

echo "== 3. the owner reviews and declassifies"
topos flow declassify summary.md | sed 's/^/  /'
sudo -n -u bob cat "$M/relations/work/summary.md" > /dev/null \
    && ok "after declassifying, bob reads it" || bad "bob still cannot read it"

echo
[ "$fails" -eq 0 ] && echo "listo / ok" || echo "$fails falla(s) / failure(s)"
exit "$fails"
