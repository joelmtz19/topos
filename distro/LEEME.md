# topOS 0.1 «Betti»

Debian 12 con topos como forma de ver el sistema. Al entrar, cada usuario tiene su
mundo montado en `~/mundo`, el prompt muestra los números de Betti del mundo
(`β(3,1)`) y se recalcula cuando cambia, y el planificador topológico corre en
`/tmp/topos-sched.sock` para que cualquier proceso se coordine con él.

## Construir

    distro/build.sh          # deja distro/out/topOS.iso y distro/out/topOS-wsl.tar

Todo se arma dentro de Docker, sin privilegios.

## Usarla

**En WSL (Windows):**

    wsl --import topOS C:\Users\joelm\WSL\topOS distro\out\topOS-wsl.tar --version 2
    wsl -d topOS

Para quitarla: `wsl --unregister topOS`.

**En una máquina virtual:** arranca `topOS.iso` como CD (VirtualBox, Hyper-V
generación 1 o 2, QEMU). Entra sola como `topos`.

**En una USB:** graba `topOS.iso` con Rufus (modo imagen DD) o con
`dd if=topOS.iso of=/dev/sdX bs=4M`. Arranca en BIOS y en UEFI. Es un sistema
en vivo: lo que hagas se pierde al apagar.

Usuario `topos`, contraseña `topos`, con sudo sin contraseña. root también
tiene contraseña `topos`.

## Qué probar

    cd ~/mundo && cat holes                  # el hueco entre tesis, datos y figuras
    topos glue tesis.md datos.md figuras.md --as paper   # lo tapas: el prompt pasa a β(…,0)
    topos run /usr/share/topos/ejemplos/filosofos.txt --runs 200 --naive
    topos run /usr/share/topos/ejemplos/filosofos.txt --runs 200
    topos sched run Ana /usr/share/topos/ejemplos/filosofos.txt   # en tres terminales,
    topos sched run Beto …    topos sched run Caro …               # uno por filósofo
    toposfetch

## Probar el arranque sin pantalla

    docker build -f distro/Dockerfile.qemu -t topos-qemu distro
    docker run --rm -v "$PWD/distro/out:/t/out" -v "$PWD/distro/boot-test.py:/t/boot-test.py" \
        topos-qemu python3 boot-test.py out/topOS.iso

Arranca el ISO en QEMU por consola serial, espera el prompt, corre comandos y
apaga. Sin KVM (Docker Desktop no lo expone) emula por software y tarda varios
minutos.

## Lo que todavía no tiene

- Instalador a disco: sólo corre en vivo o en WSL.
- Red en el ISO: el kernel la trae, pero no hay un cliente DHCP configurado.
- Escritorio gráfico: es de consola.
