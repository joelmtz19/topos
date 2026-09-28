# topos

**A security layer for AI agents, built out of topology.** *(Español: [README.es.md](README.es.md))*

An AI agent is only as safe as what it can reach. topos gives a set of collaborating agents a
shared world where **what each one can read, write, and send is enforced by the Linux kernel,
not by the model's willingness to obey a prompt.** Agents keep their full power and keep
working together; a prompt injection just can't make one leak your database, burn your API
budget, or cover its tracks.

It started as a "topological operating system" and the topology is real — files are vertices
in a simplicial complex, permissions are a sheaf, processes are paths — but what makes it
useful is what that structure buys you for agent security.

## What it protects against

Each agent runs as its own Linux user in a world mounted over FUSE. On top of that:

- **Least privilege.** An agent reads and writes only what the permission **sheaf** grants it.
  A relation (a named group of files) can force its files to agree on permissions; conflicting
  policies are reported before they bite (`topos perm check`) as an obstruction in H¹.
- **No self-escalation.** An agent can't grant itself access by gluing, renaming, or `chmod` —
  the kernel refuses.
- **Information flow: labels travel with the data.** Everything an agent has read taints what
  it later writes. A file it produces from your payroll can't be read by someone who can't read
  the payroll — even copied through the agent's own `/tmp` and a fresh shell.
- **Network egress: the destination is one more reader.** Agents reach the internet only through
  a proxy, and only to allowlisted hosts cleared to receive what the agent has read
  (`topos net`). A kernel firewall (nftables) blocks everything else.
- **Budgets.** Per-agent, per-hour request/byte limits at the proxy, so an abused chatbot can't
  drain your model account.
- **On behalf of the asker.** A support bot serving a customer only sees the intersection of its
  own and the customer's permissions (`--on-behalf-of`), and a per-agent hourly cap on distinct
  files stops bulk extraction.
- **A tamper-evident audit log.** Every action is hash-chained into a file only the world owner
  can write; agents can't wipe it, read it, or forge another's name. `topos verify` detects any
  edit.

Every one of these is proven end-to-end against the real kernel in `distro/*-check.sh`, and the
attacks a red team confirmed live on as permanent regression cases in
[`distro/redteam.sh`](distro/redteam.sh).

### What it does *not* do

topos limits the blast radius; it doesn't make the model immune to prompt injection. Data the
agent copies outside its world (into channels topos doesn't mediate) is out of scope, except the
network, which the proxy does mediate. The audit chain is tamper-evident against agents (who
can't touch the file at all) and against casual edits; anchoring the very latest entry against an
owner/root-level rewrite would need an external anchor (a remote log or TPM), which is future
work. The bulk-extraction cap counts files, not rows: a whole table in one file isn't bounded by
it.

## Try it in a minute (Docker)

```
docker compose up -d --build
docker compose exec topos bash -l
```

Two services come up: `topos` (the system, world mounted, scheduler, audit daemon, egress proxy)
and `ollama` (an open model, on your NVIDIA GPU). World, models, and log live in volumes. Inside:

```
cd ~/mundo && cat holes
topos glue thesis.md data.md figures.md --as paper     # the prompt drops to β(…,0)
topos agent create bot --grant work:rw                 # an agent: a Linux user with nothing
topos agent run bot "summarize relations/work/meeting.md into todo.md"
topos agent log                                        # what it did
topos verify                                           # the log is intact
topos-demo-agents                                      # two agents in one world; a leak denied
```

Use your host's Ollama instead of the container's: `TOPOS_OLLAMA=http://host.docker.internal:11434 docker compose up -d topos`.
Everything speaks English by default; `TOPOS_LANG=es` switches the whole system to Spanish.

## Agents from any MCP client

`topos mcp` speaks the Model Context Protocol over stdio, so Claude, Cursor, Goose, or any MCP
client works inside a topos world. Run it as the agent's Linux user and the kernel enforces the
sheaf no matter what the client asks:

```
sudo -u agent-x topos mcp --world ~/mundo --on-behalf-of customer-ana
```

## The distro

`distro/build.sh` builds **topOS** (Debian-based): a bootable ISO (BIOS and UEFI, live) and a tar
for `wsl --import`. Details in [`distro/LEEME.md`](distro/LEEME.md).

## Commands

```
topos init | add | import | ls | cat | rm
topos glue A B C --as LABEL | cut | drop | rels | star | link | betti | holes
topos perm govern | set | enroll | limit | show | check | cohomology
topos flow show | declassify           # which data reached which files
topos net allow | trust | budget | usage | show | proxy | enforce
topos verify                           # the audit log was not tampered with
topos paths | run | sched              # processes as paths; the topological scheduler
topos agent create | run | log | eval  # open-model agents, confined by the sheaf
topos mcp | mount | mem
```

Commands and messages have Spanish aliases (`pegar`, `huecos`, `agente crear`, …).

## Tests

```
pip install -e ".[test]" && pytest              # on Windows, the OS-independent tests run
docker build -t topos . && docker run --rm topos python -m pytest -q     # full suite
```

CI runs the full suite plus the red-team corpus on every push.

## License

[Apache-2.0](LICENSE). Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md); report
vulnerabilities via [SECURITY.md](SECURITY.md).
