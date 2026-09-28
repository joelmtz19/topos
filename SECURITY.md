# Security Policy

topos is a security layer for AI agents. Finding a way to defeat one of its controls is exactly
the kind of report we want.

## Reporting a vulnerability

Please report privately — use GitHub's **"Report a vulnerability"** (Security → Advisories) on
this repository rather than opening a public issue, so it can be fixed before it's public.

Include the claim you broke (from the README's list), the root cause if you found it, and an
exact reproduction. Proofs that run against the container (like `distro/*-check.sh`) are ideal.

## Scope and threat model

The world owner (the human running the mount) is trusted. Each agent is an unprivileged Linux
user confined by the sheaf, FUSE, nftables, and the egress proxy. In scope: any way an agent
reads, writes, or sends something the policy forbids; grants itself access; launders tainted data
past the flow control (file or network); exceeds its budget or extraction cap; or wipes or forges
the audit log.

Known limitations are listed under **"What it does not do"** in the [README](README.md#what-it-does-not-do)
— reports about those are still welcome, especially concrete ways to close them.

## Confirmed findings become regression tests

Every vulnerability we confirm is added as a permanent case in
[`distro/redteam.sh`](distro/redteam.sh), which CI runs on every change, so a fix can't silently
regress.
