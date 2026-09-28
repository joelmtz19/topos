#!/usr/bin/env bash
# Corpus de ataque permanente / permanent attack corpus.
# Cada caso salió de un red team; aquí se queda para que el hueco no regrese.
# Each case came from a red team; it stays here so the hole cannot come back.
#
#   docker run --rm -i --device /dev/fuse --cap-add SYS_ADMIN \
#     --security-opt apparmor:unconfined topos-os bash -l distro/redteam.sh
set -u
fails=0
held() { printf '  ✓ %s\n' "$*"; }
brk()  { printf '  ✗ REGRESIÓN / REGRESSION: %s\n' "$*"; fails=$((fails + 1)); }
M=$HOME/mundo

d=$(mktemp -d)
printf 'PAYROLL-SECRET Ana 38417\n' > "$d/payroll.md"
printf 'Monday: Ana sends the proposal.\n' > "$d/meeting.md"
printf -- '- (empty)\n' > "$d/todo.md"
topos add "$d"/*.md > /dev/null 2>&1 && rm -rf "$d"
topos glue payroll.md --as finance > /dev/null
topos glue meeting.md todo.md --as work > /dev/null
topos agent create agent-notes --grant finance:r work:rw > /dev/null
topos agent create bob --grant work:r > /dev/null
A="sudo -n -u agent-notes"; B="sudo -n -u bob"

echo "== F1: lavar el secreto por /tmp y una sesión nueva (info-flow por uid)"
$A setsid -w bash -c "cat '$M/files/payroll.md' > /tmp/stash" 2>/dev/null
$A setsid -w bash -c "cat /tmp/stash > '$M/relations/work/leak.md'" 2>/dev/null
if $B grep -q PAYROLL-SECRET "$M/relations/work/leak.md" 2>/dev/null; then
    brk "F1 bob leyó la nómina lavada por /tmp"
else
    held "F1 la marca viaja por uid: bob no lee la copia lavada"
fi

echo "== F4: un usuario que nadie inscribió (default-deny)"
sudo -n useradd --system --no-create-home --shell /usr/sbin/nologin intruder 2>/dev/null
if sudo -n -u intruder grep -q PAYROLL-SECRET "$M/files/payroll.md" 2>/dev/null; then
    brk "F4 un uid no inscrito lee todo (fail-open)"
else
    held "F4 default-deny: un uid no inscrito no lee nada"
fi

echo "== Control: el dueño del mundo sí lee todo"
grep -q PAYROLL-SECRET "$M/files/payroll.md" && held "el dueño lee sus archivos" \
    || brk "el dueño perdió acceso a su propio mundo"

echo "== F5: reiniciar la sesión (setsid) no reinicia el tope de extracción"
topos agent create raton --grant finance:r work:r > /dev/null   # payroll, meeting, todo: 3 archivos
topos perm limit raton --files 2 > /dev/null
R="sudo -n -u raton"
$R setsid -w cat "$M/relations/finance/payroll.md" >/dev/null 2>&1     # 1, sesión nueva
$R setsid -w cat "$M/relations/work/meeting.md"    >/dev/null 2>&1     # 2, sesión nueva
$R setsid -w cat "$M/relations/work/todo.md"       >/dev/null 2>&1     # 3, sesión nueva → tope
if topos agent log -n 20 | grep -q "possible extraction\|posible extracción"; then
    held "F5 el tope por hora/uid frena la extracción aunque cambie de sesión"
else
    brk "F5 setsid reinició el tope de extracción"
fi

echo "== Control (.topos 700): el agente no lee el almacén del disco"
if $A cat "$TOPOS_HOME/.topos/state.json" >/dev/null 2>&1; then
    brk "el agente leyó .topos/state.json del disco"
else
    held ".topos sigue cerrado al agente"
fi

echo
[ "$fails" -eq 0 ] && echo "listo / ok" || echo "$fails regresión(es) / regression(s)"
exit "$fails"
