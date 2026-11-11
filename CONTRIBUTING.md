# Contributing to Agent Vault

Thanks for helping. Bug reports, ideas, documentation fixes and code are all welcome.

## Before you start

- **Bugs:** open an issue with the command you ran, what you expected, what happened, your operating system and your Python version. Remove personal paths and memory content first.
- **Features:** open an issue to discuss the idea before writing a large change, so we can agree on the approach.
- **Security problems:** do not open an issue. Follow [SECURITY.md](SECURITY.md).

## Development setup

You need Python 3.11 or newer and Git. There are no dependencies to install.

```bash
git clone https://github.com/AlexMakesC0de/agent-vault.git
cd agent-vault
python -m unittest discover -s scripts/tests -q
```

Use `python3` on macOS and Linux. The suite takes a few minutes on Windows and under a minute elsewhere. CI runs it on Windows (Python 3.11 and 3.13), macOS and Linux for every pull request.

Your own installed copy in `~/.config/agent-memory` is never touched by the tests. To try a change for real, run `install` from your clone and check it with `router.py doctor`.

## Rules every change follows

- **Standard library only.** No third-party packages, at runtime or in tests.
- **Windows, macOS and Linux.** Use `pathlib`, write files as UTF-8, and test paths with spaces and non-ASCII characters where it matters.
- **Never lose memory.** Setup, install and migration preserve existing files and settings. When a change could overwrite or reset memory, refuse with a clear message instead.
- **Real files in tests.** Tests use real temporary homes, repositories and profiles, and run the real commands. Do not mock the filesystem or Git.
- **Synthetic fixtures only.** Never put real memories, names, company details or machine paths in tests, docs or screenshots. Use invented data such as `ExampleApp` and `sam@example.com`.
- **No forged trust.** Do not mark client hooks as trusted or change permissions on the user's behalf.
- **Docs follow code.** If a change alters behaviour, a limit or a command, update the README and the files in `docs/` in the same pull request.

Before changing a script, read it and [docs/architecture.md](docs/architecture.md).

## Pull requests

1. Branch from `main` with a `feat/`, `fix/` or `docs/` prefix.
2. Keep each pull request to one change, with tests that fail without it.
3. Use short commit subjects with a type prefix: `feat:`, `fix:`, `docs:`, `test:` or `chore:`.
4. Run the full suite locally, then describe in the pull request what changed, why, and how you verified it.

## Updating the README screenshots

The screenshots use invented data only. Rebuild the page with:

```bash
python docs/assets/make-demo.py demo.html
```

Open `demo.html` in a browser at 1280 pixels wide and save light and dark captures as `docs/assets/viewer-light.png` and `docs/assets/viewer-dark.png`.

## Translations

`README.md` is the source of truth. Translated READMEs (`README.zh-CN.md`, `README.es.md`, `README.ja.md`, `README.ko.md`, `README.pt-BR.md`, `README.de.md`) may lag behind it. Corrections and new languages are welcome; keep commands, paths and code blocks exactly as in the English version.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
