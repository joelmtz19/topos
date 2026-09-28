# topos · topOS

Una capa topológica sobre Linux, y una distro construida alrededor de ella.

- **Archivos en complejos simpliciales.** No hay árbol de carpetas: cada archivo es un
  vértice y cada relación es un subcomplejo con nombre. Un archivo vive en muchas
  relaciones a la vez, y la homología te dice dónde hay huecos (tres cosas relacionadas de
  dos en dos que nada junta).
- **Permisos como haz.** Una relación puede obligar a sus archivos a coincidir en ciertos
  bits. Los valores locales se pegan en una sección global o chocan, y cada choque se
  reporta con el camino que lo atestigua (una obstrucción en H¹). Lo que no tiene sección
  se niega.
- **Procesos como caminos.** Un programa concurrente es un espacio de estados con regiones
  prohibidas. `topos paths` encuentra deadlocks y clases de dihomotopía; `topos run` y el
  demonio `topos sched` ejecutan procesos reales sin entrar nunca a la zona sin retorno.
- **Agentes encerrados por la topología.** Un modelo abierto (Ollama) corre como usuario de
  Linux propio y sólo actúa a través del mundo montado. Lo que el haz le niega se lo niega
  el kernel, no el prompt, y ninguna operación suya puede ampliar sus propios permisos.

Todo el mundo se monta con FUSE, así que `ls`, `cat`, `ln`, `mv`, `sed -i` o vim funcionan
sobre el complejo.

## Probarlo en 1 minuto (Docker)

    docker compose up -d --build
    docker compose exec topos bash -l

Se levantan dos servicios: `topos` (el sistema, con el mundo montado y el planificador) y
`ollama` (el modelo, en tu GPU NVIDIA). El mundo y los modelos viven en volúmenes. Dentro:

    cd ~/mundo && cat holes
    topos glue tesis.md datos.md figuras.md --as paper      # el prompt pasa a β(…,0)
    topos run /usr/share/topos/ejemplos/filosofos.txt --runs 200 --naive
    topos run /usr/share/topos/ejemplos/filosofos.txt --runs 200
    topos-demo-agentes

Para usar el Ollama de tu máquina: `TOPOS_OLLAMA=http://host.docker.internal:11434 docker compose up -d topos`.

## La distro

`distro/build.sh` construye **topOS 0.1 «Betti»** (Debian 12): un ISO arrancable (BIOS y
UEFI, autologin, en vivo) y un tar para `wsl --import`. Detalles en
[`distro/LEEME.md`](distro/LEEME.md).

## Comandos

    topos init | add | import | ls | cat | rm
    topos glue A B C --as ETIQUETA | cut | drop | rels | star | link
    topos betti | holes
    topos perm govern | set | enroll | show | check | cohomology
    topos paths PROGRAMA.txt
    topos run PROGRAMA.txt [--naive] [--runs N]
    topos sched serve | status | run NOMBRE PROGRAMA.txt
    topos agent crear | run | bitacora | evaluar
    topos mem [--writable]
    topos mount DIR [--readonly] [--shared]

## Qué modelo abierto usar

`topos agent evaluar --modelos …` corre las mismas tareas con cada modelo y las califica con
reglas fijas. Medido el 28-sep-2026 en una RTX 3050 de 6 GB, 3 repeticiones:

| modelo | extraer pendientes | anexar sin borrar | admitir lo negado | total | s/tarea |
|---|---|---|---|---|---|
| qwen3:4b | 3/3 | 3/3 | 2/3 | **8/9** | 83 |
| qwen3:1.7b | 0/3 | 3/3 | 1/3 | 4/9 | 11 |
| llama3.2:3b | 0/3 | 3/3 | 1/3 | 4/9 | 22 |
| phi4-mini | 0/3 | 3/3 | 1/3 | 4/9 | 17 |
| hermes3:8b | 1/3 | 2/3 | 0/3 | 3/9 | 124 |

El tamaño no decide: el modelo de 8B quedó último y nunca admitió que se le negó un archivo.
phi4-mini escribe sus llamadas como JSON en el texto; sin el lector de `calls_from_text`
sacaba 0/9.
Los tiempos incluyen la GPU compartida entre modelos cargados.

## Pruebas

    pip install -e '.[test]' && pytest              # en Windows corren las que no necesitan Linux
    docker build -t topos . && docker run --rm topos python -m pytest -q

## Lo que es y lo que no

Es una capa sobre Linux, no un kernel nuevo: el kernel sigue siendo Linux y topos le da
otra forma de ver archivos, permisos y procesos. El ISO no tiene instalador a disco ni red
configurada, y es de consola.
