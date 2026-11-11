# Security

Agent Vault runs locally. It needs no server, API key or network access, and it never sends memory anywhere. The security-relevant surface is what it writes: client hook settings, agent instruction files, the install folder, and the memory files themselves.

## Reporting a vulnerability

Report it privately through this repository's **Security** tab ("Report a vulnerability"). Do not open a public issue for a vulnerability.

Include the affected command, your operating system and Python version, and the steps that reproduce it.

## Scope

In scope:

- A hook, install or migration path that overwrites, deletes or corrupts memory, history or unrelated settings.
- Memory or knowledge from one project vault reaching another project's context.
- A command the tools generate that runs something other than the installed tools.

Out of scope: what an agent chooses to do with memory it was given. Memory is context, not authorization, and the tools say so in every context they emit.
