# topos

**Una capa de seguridad para agentes de IA, hecha de topología.** *(English: [README.md](README.md))*

Un agente de IA es tan seguro como lo que puede alcanzar. topos le da a un conjunto de agentes
que colaboran un mundo compartido donde **lo que cada uno puede leer, escribir y enviar lo hace
cumplir el kernel de Linux, no la voluntad del modelo de obedecer un prompt.** Los agentes
conservan todo su poder y siguen colaborando; una inyección de prompt simplemente no puede hacer
que uno filtre tu base de datos, te queme el presupuesto de la API o borre sus huellas.

Empezó como un "sistema operativo topológico" y la topología es de verdad —los archivos son
vértices de un complejo simplicial, los permisos un haz, los procesos caminos— pero lo que lo
hace útil es lo que esa estructura te da para la seguridad de los agentes.

## Contra qué protege

Cada agente corre como su propio usuario de Linux en un mundo montado con FUSE. Encima de eso:

- **Mínimo privilegio.** Un agente lee y escribe sólo lo que el **haz** de permisos le concede.
  Una relación (un grupo de archivos con nombre) puede obligar a sus archivos a coincidir; las
  políticas que se contradicen se reportan antes de que estorben (`topos perm check`), como una
  obstrucción en H¹.
- **Nada de auto-escalada.** Un agente no puede darse acceso pegando, renombrando ni con `chmod`:
  el kernel lo niega.
- **Flujo de información: las marcas viajan con los datos.** Todo lo que un agente leyó marca lo
  que luego escribe. Un archivo que hace a partir de tu nómina no lo puede leer alguien que no
  puede leer la nómina — ni copiándolo por el propio `/tmp` del agente y otra terminal.
- **Salida de red: el destino es un lector más.** Los agentes salen a internet sólo por un proxy,
  y sólo a hosts permitidos y autorizados a recibir lo que el agente leyó (`topos net`). Un
  firewall del kernel (nftables) bloquea todo lo demás.
- **Presupuestos.** Topes por agente y por hora de peticiones y bytes en el proxy: un chatbot
  abusado no te vacía la cuenta del modelo.
- **A nombre de quien pregunta.** Un bot de soporte que atiende a un cliente sólo ve la
  intersección de sus permisos y los del cliente (`--on-behalf-of`), y un tope por agente y hora
  de archivos distintos frena la extracción masiva.
- **Una bitácora a prueba de manipulación.** Cada acción se encadena por hash en un archivo que
  sólo el dueño del mundo escribe; los agentes no pueden borrarla, leerla ni firmarse como otro.
  `topos verify` detecta cualquier edición.

Cada una de estas está probada de punta a punta contra el kernel real en `distro/*-check.sh`, y
los ataques que confirmó un red team quedan como casos permanentes de regresión en
[`distro/redteam.sh`](distro/redteam.sh).

### Lo que *no* hace

topos limita el alcance del daño; no hace inmune al modelo a la inyección de prompt. Los datos
que el agente copia fuera de su mundo (a canales que topos no media) quedan fuera de alcance,
salvo la red, que el proxy sí media. La cadena de la bitácora es a prueba de manipulación contra
los agentes (que no tocan el archivo) y contra ediciones casuales; anclar la última entrada
contra un reescritor con acceso de dueño/root necesitaría un ancla externa (un registro remoto o
un TPM), que es trabajo futuro. El tope de extracción cuenta archivos, no filas: una tabla entera
en un archivo no queda acotada por él.

## Pruébalo en un minuto (Docker)

```
TOPOS_LANG=es docker compose up -d --build
docker compose exec topos bash -l
```

Se levantan dos servicios: `topos` (el sistema, con el mundo montado, el planificador, el demonio
de bitácora y el proxy de salida) y `ollama` (un modelo abierto, en tu GPU NVIDIA). El mundo, los
modelos y la bitácora viven en volúmenes. Adentro:

```
cd ~/mundo && cat huecos
topos pegar tesis.md datos.md figuras.md --como paper   # el prompt baja a β(…,0)
topos agente crear bot --concede trabajo:rw             # un agente: usuario de Linux sin nada
topos agente correr bot "resume relations/trabajo/reunion.md en pendientes.md"
topos agente bitacora                                   # qué hizo
topos verificar                                         # la bitácora está intacta
topos-demo-agents                                       # dos agentes en un mundo; una fuga negada
```

Para usar el Ollama de tu máquina: `TOPOS_OLLAMA=http://host.docker.internal:11434 docker compose up -d topos`.

## Agentes desde cualquier cliente MCP

`topos mcp` habla el Model Context Protocol por stdio, así que Claude, Cursor, Goose o cualquier
cliente MCP trabaja dentro de un mundo de topos. Córrelo como el usuario de Linux del agente y el
kernel hace cumplir el haz sin importar lo que pida el cliente:

```
sudo -u agent-x topos mcp --mundo ~/mundo --a-nombre-de cliente-ana
```

## La distro

`distro/build.sh` construye **topOS** (basada en Debian): un ISO arrancable (BIOS y UEFI, en vivo)
y un tar para `wsl --import`. Detalles en [`distro/LEEME.md`](distro/LEEME.md).

## Comandos

```
topos iniciar | agregar | importar | ls | cat | borrar
topos pegar A B C --como ETIQ | cortar | soltar | relaciones | estrella | enlace | betti | huecos
topos permisos gobernar | fijar | inscribir | limitar | ver | revisar | cohomologia
topos flujo ver | desclasificar        # qué datos llegaron a qué archivos
topos red permitir | confiar | presupuesto | consumo | ver | proxy | aplicar
topos verificar                        # la bitácora no fue manipulada
topos caminos | correr | planificador  # procesos como caminos; el planificador topológico
topos agente crear | correr | bitacora | evaluar
topos mcp | montar | memoria
```

Todo el sistema habla inglés por omisión; `TOPOS_LANG=es` lo pasa a español (los comandos en
inglés siguen funcionando).

## Pruebas

```
pip install -e ".[test]" && pytest              # en Windows corren las que no necesitan Linux
docker build -t topos . && docker run --rm topos python -m pytest -q     # la suite completa
```

CI corre la suite completa y el corpus del red team en cada push.

## Licencia

[Apache-2.0](LICENSE). Se agradecen contribuciones — ver [CONTRIBUTING.md](CONTRIBUTING.md);
reporta vulnerabilidades por [SECURITY.md](SECURITY.md).
