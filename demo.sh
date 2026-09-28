#!/usr/bin/env bash
# Recorrido completo dentro de Linux: almacén, haz, caminos, memoria y FUSE.
set -u
say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

cd /tmp && rm -rf demo && mkdir demo && cd demo
for n in tesis datos figuras notas presupuesto; do echo "contenido de $n" > "$n.md"; done
topos init
topos add *.md > /dev/null
topos glue tesis.md datos.md --as investigacion
topos glue datos.md figuras.md --as analisis
topos glue figuras.md tesis.md --as articulo
topos glue notas.md presupuesto.md --as admin

say "Homología: un hueco entre investigación, análisis y artículo"
topos holes
say "Tapamos el hueco con un triángulo"
topos glue tesis.md datos.md figuras.md --as paper
topos betti

say "Haz de permisos (root lee sólo lo que el haz le concede)"
topos perm govern investigacion root:r
topos perm set tesis.md +root:r
topos perm govern admin root:rw
topos perm set @admin +root:r -root:w
topos perm set notas.md -root:r
topos perm show
topos perm check

say "Procesos como caminos"
topos paths /opt/topos/ejemplos/cena.txt

say "Planificador topológico: hilos reales que rodean la zona sin retorno"
topos paths /opt/topos/ejemplos/filosofos.txt | head -4
topos run /opt/topos/ejemplos/filosofos.txt
topos run /opt/topos/ejemplos/filosofos.txt --runs 200 --jitter 0.005 --naive
topos run /opt/topos/ejemplos/filosofos.txt --runs 200 --jitter 0.005

say "Memoria como espacio topológico (IPC real: rw-s)"
python - <<'PY' &
import mmap, os, time
# Tres procesos, cada par comparte un segmento distinto: un ciclo sin triple.
segs = {}
for name in ("ab", "bc", "ca"):
    fd = os.open(f"/dev/shm/topos-{name}", os.O_CREAT | os.O_RDWR); os.ftruncate(fd, 4096)
    segs[name] = fd
def hold(names):
    maps = [mmap.mmap(segs[n], 4096) for n in names]
    time.sleep(8)
for names in (("ab", "ca"), ("ab", "bc"), ("bc", "ca")):
    if os.fork() == 0:
        hold(names); os._exit(0)
time.sleep(9)
PY
sleep 2
topos mem --writable
wait

say "Montaje FUSE"
mkdir -p /mnt/topos
topos mount /mnt/topos --background
sleep 1
ls /mnt/topos /mnt/topos/relations /mnt/topos/star/datos.md
ls -l /mnt/topos/files
cat /mnt/topos/files/tesis.md
cat /mnt/topos/files/notas.md || echo "(negado por el haz, como debe)"
cat /mnt/topos/holes

say "Escribir a través del montaje con herramientas de siempre"
M=/mnt/topos
topos perm set tesis.md +root:w   # el haz concede escribir tesis.md y nada más
echo "capítulo 1 reescrito" > $M/files/tesis.md && cat $M/files/tesis.md
( echo "algo" > $M/files/presupuesto.md ) 2>/dev/null || echo "(escribir presupuesto.md: negado, el haz no le da w a root)"
mkdir $M/relations/entrega
ln $M/files/tesis.md $M/relations/entrega/tesis.md
cp /etc/hostname $M/relations/entrega/portada.txt
ls $M/relations/entrega
mv $M/relations/entrega/portada.txt $M/relations/admin/portada.txt
sed -i 's/reescrito/pulido/' $M/relations/entrega/tesis.md   # temporal + rename
cat $M/files/tesis.md
topos rels
rm $M/relations/entrega/tesis.md && rmdir $M/relations/entrega
ls $M/files
fusermount -u /mnt/topos

say "Varios usuarios en el mismo montaje: el haz decide por cada uno"
cd /tmp && rm -rf equipo && mkdir equipo && cd equipo
echo "plan v1" > plan.md; echo "minuta" > minuta.md; echo "querido diario" > diario.md
topos init > /dev/null && topos add *.md > /dev/null
topos glue plan.md minuta.md --as equipo > /dev/null
topos perm govern equipo alice:rw bob:rw
topos perm set @equipo +alice:rw +bob:r -bob:w
topos perm set diario.md +alice:rw
mkdir -p /mnt/equipo && topos mount /mnt/equipo --background --shared && sleep 1
E=/mnt/equipo/files
as() { local u=$1; shift; printf '%-6s$ %s
' "$u" "$*"; runuser -u "$u" -- sh -c "$*" 2>&1 | sed 's/^/        /'; }
as alice "ls -l $E"
as bob   "ls -l $E"
as alice "echo 'plan v2' >> $E/plan.md && cat $E/plan.md"
as bob   "cat $E/plan.md; echo 'plan de bob' > $E/plan.md"
as bob   "cat $E/diario.md"
as carol "cat $E/diario.md   # carol no aparece en el haz: ninguna política le aplica"
as alice "touch -d '2026-01-01 12:00' $E/minuta.md && ls -l --time-style=+%F $E/minuta.md"
fusermount -u /mnt/equipo

say "Pruebas"
cd /opt/topos && python -m pytest -q
