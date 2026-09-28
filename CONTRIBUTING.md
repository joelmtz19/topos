# Contributing to topos

Thanks for your interest. topos is a security tool, so the bar for changes is "prove it, don't
just claim it."

## Ground rules

- **Every security-relevant change ships with a proof.** Unit tests for the logic, and an
  end-to-end check against the real kernel in `distro/*-check.sh` when it touches the sheaf, the
  mount, the network, or the audit log.
- **Red-team your own change.** Try to break it before sending it. Anything a red team confirms
  becomes a permanent case in [`distro/redteam.sh`](distro/redteam.sh) so it can't regress.
- **Bilingual.** User-facing strings are written as `t("español", "english")` (see
  `topos/i18n.py`) — both versions, side by side. No separate catalogs.
- **Stdlib only** in the core (`topos/`), except the optional `fusepy` for the mount. The point
  is that it audits easily and installs anywhere.
- **Be honest about limits.** If a change closes a hole under some assumptions, say which. The
  README's "What it does not do" section is load-bearing.

## Running the tests

```
pip install -e ".[test]" && pytest                      # OS-independent (also on Windows)
docker build -t topos . && docker run --rm topos python -m pytest -q     # full suite (Linux)
docker build -f distro/Dockerfile --target base -t topos-os .
docker run --rm --device /dev/fuse --cap-add SYS_ADMIN --security-opt apparmor:unconfined \
    -v "$PWD/distro/redteam.sh:/tmp/redteam.sh:ro" topos-os bash -lic 'bash /tmp/redteam.sh'
```

CI runs all of this on every push and pull request.

## Pull requests

1. Branch, make the change with its tests, and get the full suite + `redteam.sh` green.
2. Describe *what threat the change addresses* and *how you verified it*, not just the diff.
3. Commits: a descriptive subject and a body that explains the why.

## Reporting security issues

Please don't open a public issue for a vulnerability. See [SECURITY.md](SECURITY.md).
