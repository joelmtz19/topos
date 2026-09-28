#!/usr/bin/env bash
# La red dentro de topos, con internet de verdad y el candado del kernel puesto.
# The network inside topos, with the real internet and the kernel lock on.
#
#   docker run --rm -i --device /dev/fuse --cap-add SYS_ADMIN --cap-add NET_ADMIN --cap-add SYS_PTRACE \
#     --security-opt apparmor:unconfined topos-os bash -l distro/net-check.sh
set -u
fails=0
ok()  { printf '  ✓ %s\n' "$*"; }
bad() { printf '  ✗ %s\n' "$*"; fails=$((fails + 1)); }
M=$HOME/mundo
P=http://127.0.0.1:3128
AS="sudo -n -u agent-notes setsid -w"   # cada prueba, su propia sesión

d=$(mktemp -d)
printf 'Ana 38417\n' > "$d/payroll.md"
printf 'Monday: Ana sends the proposal.\n' > "$d/meeting.md"
topos add "$d"/*.md > /dev/null && rm -rf "$d"
topos glue payroll.md --as finance > /dev/null
topos glue meeting.md --as work > /dev/null
topos agent create agent-notes --grant finance:r work:r
topos net allow agent-notes example.com example.org
topos perm set @work +net/example.com:r +net/example.org:r     # trabajo puede ir a los dos
topos perm set @finance +net/example.com:r                      # la nómina, sólo a example.com
topos net show | sed 's/^/  /'

sudo -n env TOPOS_HOME="$TOPOS_HOME" topos net proxy > /tmp/proxy.log 2>&1 &
sleep 1
sudo -n env TOPOS_HOME="$TOPOS_HOME" topos net enforce | sed 's/^/  /'

code() { curl -s -o /dev/null --max-time 10 -w '%{http_code}/%{http_connect}' "$@"; }

echo "== 1. sin proxy, el kernel no deja salir al agente / no proxy: the kernel blocks the agent"
if $AS curl -s -o /dev/null --max-time 5 http://example.com; then
    bad "agent-notes reached example.com directly"
else
    ok "agent-notes cannot reach the internet directly"
fi
curl -s -o /dev/null --max-time 10 http://example.com && ok "the owner is not affected" || bad "the owner lost the network"

echo "== 2. por el proxy / through the proxy"
[ "$($AS bash -c "curl -s -o /dev/null --max-time 10 -w '%{http_code}' -x $P https://example.com")" = 200 ] \
    && ok "HTTPS to an allowed host (CONNECT): 200" || bad "HTTPS to example.com failed"
r=$($AS bash -c "curl -s -o /dev/null --max-time 10 -w '%{http_code}' -x $P http://example.net")
[ "$r" = 403 ] && ok "a host not on its list: 403" || bad "example.net answered $r"

echo "== 3. lo que la sesión leyó decide a dónde puede ir / what the session read decides"
r=$($AS bash -c "cat $M/files/meeting.md >/dev/null; curl -s -o /dev/null --max-time 10 -w '%{http_code}' -x $P http://example.org")
[ "$r" = 200 ] && ok "read work → example.org: 200" || bad "work → example.org gave $r"
r=$($AS bash -c "cat $M/files/payroll.md >/dev/null; curl -s -o /dev/null --max-time 10 -w '%{http_code}' -x $P http://example.org")
[ "$r" = 403 ] && ok "read payroll → example.org: 403 (the payroll may not go there)" \
    || bad "payroll → example.org gave $r"
r=$($AS bash -c "cat $M/files/payroll.md >/dev/null; curl -s -o /dev/null --max-time 10 -w '%{http_code}' -x $P http://example.com")
[ "$r" = 200 ] && ok "read payroll → example.com: 200 (cleared to receive it)" \
    || bad "payroll → example.com gave $r"

echo "== 4. presupuestos / budgets"
topos net budget agent-notes example.com --requests 1 | sed 's/^/  /'     # cuenta desde ahora
topos net budget agent-notes example.org --mb 0.0005 | sed 's/^/  /'      # 500 bytes; la página pesa más
r=$($AS bash -c "curl -s -o /dev/null --max-time 10 -w '%{http_code}' -x $P http://example.com")
[ "$r" = 200 ] && ok "1st capped request to example.com: 200" || bad "1st capped request gave $r"
r=$($AS bash -c "curl -s -o /dev/null --max-time 10 -w '%{http_code}' -x $P http://example.com")
[ "$r" = 429 ] && ok "2nd capped request to example.com: 429 (hourly cap)" || bad "2nd capped request gave $r"
got=$($AS bash -c "curl -s --max-time 10 -x $P http://example.org | wc -c")
[ "$got" -lt 1000 ] && ok "example.org cut mid-response after the byte cap ($got bytes arrived)" \
    || bad "example.org sent $got bytes past the cap"
r=$($AS bash -c "curl -s -o /dev/null --max-time 10 -w '%{http_code}' -x $P http://example.org")
[ "$r" = 429 ] && ok "next request to example.org: 429" || bad "next request to example.org gave $r"
sudo -n env TOPOS_HOME="$TOPOS_HOME" topos net usage | sed 's/^/  /'

echo "== bitácora / log"
topos agent log -n 8 | sed 's/^/  /'

echo
[ "$fails" -eq 0 ] && echo "listo / ok" || echo "$fails falla(s) / failure(s)"
exit "$fails"
