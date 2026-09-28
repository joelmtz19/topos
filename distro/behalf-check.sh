#!/usr/bin/env bash
# Un chatbot de soporte que puede leer toda la base de clientes, atendiendo a ana
# por MCP: sólo ve lo que ana puede ver, y no puede vaciar la base en una conversación.
# A support chatbot that can read the whole customer base, serving ana over MCP.
#
#   docker run --rm -i --device /dev/fuse --cap-add SYS_ADMIN \
#     --security-opt apparmor:unconfined topos-os bash -l distro/behalf-check.sh
set -u
fails=0
ok()  { printf '  ✓ %s\n' "$*"; }
bad() { printf '  ✗ %s\n' "$*"; fails=$((fails + 1)); }
M=$HOME/mundo

d=$(mktemp -d)
for c in ana beto caro dani eli; do printf '{"name": "%s", "plan": "example"}\n' "$c" > "$d/$c.json"; done
printf 'How to reset your password: …\n' > "$d/faq.md"
topos add "$d"/* > /dev/null && rm -rf "$d"
topos glue ana.json beto.json caro.json dani.json eli.json --as customers > /dev/null
topos glue faq.md --as public > /dev/null
topos agent create support-bot --grant customers:r public:r
topos perm enroll ana > /dev/null
topos perm set @public +ana:r
topos perm set ana.json +ana:r
topos perm limit support-bot --files 3

mcp() {   # $1 = --on-behalf-of args; the rest are JSON-RPC calls, one per line
    local who=$1; shift
    { echo '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}'
      printf '%s\n' "$@"; } | sudo -n -u support-bot env TOPOS_LANG=en topos mcp --world "$M" $who
}
read_call() { printf '{"jsonrpc":"2.0","id":%s,"method":"tools/call","params":{"name":"read","arguments":{"path":"%s"}}}' "$1" "$2"; }

echo "== 1. on behalf of ana"
out=$(mcp "--on-behalf-of ana" "$(read_call 1 files/ana.json)" "$(read_call 2 files/beto.json)" \
      "$(read_call 3 relations/public/faq.md)")
grep -q '"id": 1.*\\"name\\": \\"ana\\"' <<<"$out" && ok "reads ana.json" || bad "could not read ana.json"
grep -q '"id": 2.*"isError": true' <<<"$out" && ok "beto.json denied: ana may not see it" || bad "beto.json leaked"
grep -q '"id": 3.*reset your password' <<<"$out" && ok "reads the public FAQ" || bad "could not read the FAQ"

echo "== 2. the model cannot step out of the view"
out=$(mcp "--on-behalf-of ana" "$(read_call 4 ../../files/beto.json)" "$(read_call 5 /home/topos/mundo/files/beto.json)")
grep -q '"id": 4.*"isError": true' <<<"$out" && ok "../ escape denied" || bad "../ escaped the view"
grep -q '"id": 5.*"isError": true' <<<"$out" && ok "absolute path stays inside the view (denied)" || bad "absolute path escaped"

echo "== 3. no bulk extraction: cap of 3 distinct files per conversation"
out=$(mcp "" "$(read_call 6 files/ana.json)" "$(read_call 7 files/beto.json)" "$(read_call 8 files/caro.json)" \
      "$(read_call 9 files/dani.json)")
grep -q '"id": 8.*"isError": false' <<<"$out" && ok "3 customers read" || bad "the first 3 failed"
grep -q '"id": 9.*"isError": true' <<<"$out" && ok "the 4th is denied: possible extraction" || bad "the 4th was read"
out=$(mcp "" "$(read_call 10 files/eli.json)")
grep -q '"id": 10.*"isError": false' <<<"$out" && ok "a new conversation starts fresh" || bad "new conversation blocked"

echo "== bitácora / log"
topos agent log -n 4 | sed 's/^/  /'
echo
[ "$fails" -eq 0 ] && echo "listo / ok" || echo "$fails falla(s) / failure(s)"
exit "$fails"
