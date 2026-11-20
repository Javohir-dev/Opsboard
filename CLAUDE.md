# CLAUDE.md — read before changing anything here

This folder is both the Opsboard source **and the user's live install**. The files next
to the code (`config.json`, `notes.json`, `notes-history/`, `marks.json`,
`claude-logins/`, `backups/`, `runs*`, `telegram-*.json`) are real user data, and
Opsboard also writes outside it: `~/.claude/settings.json`, `~/.claude.json`, and the
macOS Keychain. Test mistakes here have wiped the user's settings, notes, Claude sign-ins,
Telegram link and keyboard shortcuts three times (2026-10-15, 2026-11-10, 2026-11-20).
Each time the user had to sign in and set things up again by hand. **No change is
worth risking that.**

## Hard rules

1. **Run tests only with `bin/opsboard test`** (`--e2e` for the browser suite). It runs
   them with a throwaway `HOME` and data dir. Never `python3 -m unittest …`, `pytest`,
   or a single test module by hand. `discover -s tests` without `-t .` skips
   `tests/__init__.py` and runs against the real data. A user-level Claude Code hook
   (`~/.claude/hooks/opsboard-guard.py`) blocks those forms. Do not work around it.
2. **Never test against the running server** (`127.0.0.1:8095`). For UI checks start a
   second server on another port with its own data:
   `OPS_DATA_DIR=<scratch> OPS_SECRET_STORE=file OPS_CLAUDE_SETTINGS=<scratch>/s.json OPS_CLAUDE_JSON=<scratch>/c.json OPS_CLAUDE_CREDENTIALS=<scratch>/cred.json python3 server.py --port 8197`,
   or mock the API with `page.route`. Read-only looks at :8095 (GET, screenshots) are fine.
   Never click anything there that changes state.
3. **Never delete, move or overwrite user state** (the files above, `~/.claude/settings.json`,
   `~/.claude.json`, Keychain items) with shell commands or scripts. If something looks
   wrong, ask the user first.
4. **Never write the Keychain or Claude Code's sign-in yourself.** Only Opsboard code may,
   and only on the user's own click.
5. **Never spend a Claude limit reset.** Only the user's confirmed click may.
6. Any new code that writes user state must call `safety.allow_write(path)` (or
   `safety.allow_keychain()`) and `safety.backup(path, kind)` first, like `config.save`,
   `claudeaccounts.switch` and `claudelogins.forget` do. Under a test run they refuse
   real paths.

## Safety net (do not remove)

- `core.py` / `config.py` exit if `unittest` is loaded without `OPS_DATA_DIR`.
- `safety.py` refuses real-path and Keychain writes during tests and keeps up to 200
  copies per kind in `backups/<kind>/` before every change (config, claude-settings,
  claude-logins, marks, notes).
- Undo: `bin/opsboard backups [kind]`, then `bin/opsboard restore <name>`. The replaced
  version is backed up as well.

## Before you finish

- `bin/opsboard test` is green.
- `bin/opsboard doctor` shows the same as before your change.
- `git status` shows only source files. `config.json`, backups and tokens are never
  committed.
