# Changelog

All notable changes. Versions follow [semantic versioning](https://semver.org/); `opsboard update` installs the newest tagged version.

## Unreleased

### Added
- **Fix run progress:** a fix tab on the request page with the steps of the run, the threads it handled and a live feed of Claude's messages, commands and edits; earlier runs can be picked. Background runs, the running badge and run notifications open it. Skills can name their steps with optional `OPS_STEP` lines (`docs/fix-skill.md`).
- Request *Overview* sidebar like GitLab's: assignees, reviewers with their review state, labels, milestone, tasks, time tracking and participants, with avatars.
- Request page header and tabs like GitLab: *Overview* (description rendered with marked + DOMPurify, Mermaid diagrams, pipeline, approvals, threads, reviewers, labels), *Commits*, *Pipelines* / *Checks* and *Changes*. The libraries are vendored; Mermaid loads only when a description has a diagram.
- Request page changes look like GitLab's: a file tree with search and list / tree views, syntax colouring (highlight.js, vendored), *Viewed* per file, copy path, file mode changes, expand / collapse all, and a toggle for the threads column.
- A notification for every new review thread on your open requests; it opens the request page at that thread.
- Request page threads look like GitLab's: who started it on which line and when, resolved ones folded into *N replies · Last reply by …*; a counter with ↑ ↓ steps through the unresolved ones. Plain comments are left out.
- **Merge / pull request page:** a title opens the request inside Opsboard — the diff file by file, and the threads on the right with their replies; resolved threads are folded. Markers link diff lines and threads both ways.
- A short system sound with each notification (a different one when a run failed or stopped); *Settings → Claude → Sound when a fix finishes*, on by default.
- *Settings → Claude → Claude usage in the sidebar* (on by default). Off: the sidebar shows CPU, RAM and swap, and Overview leaves out the machine tiles.
- **Notifications:** a bell next to the logo counts finished fix runs (pushed, committed, stopped, failed); click an entry to jump to its merge request on Overview, which lights up once. Optional browser alerts, and a system notification (macOS Notification Center, `notify-send` on Linux) when no dashboard tab is showing them.
- *Settings → Claude → Live Claude usage* (on by default; switching it takes effect at once): plan limits every minute with Claude Code's own sign-in, falling back to the cache when it is missing, expired or rejected. Off: no limits at all — the sidebar shows CPU, RAM and swap, and Overview leaves out the machine tiles.
- README section *Claude usage* with setup and troubleshooting; the sidebar tells you to run `/usage` when there is nothing saved yet.
- Agents cannot switch *Live Claude usage* on through `opsboard config` (`--source agent` is refused); the setup prompt tells Claude never to read Claude Code's sign-in.

### Fixed
- Agents started by a Claude Code *Workflow* show up under their session (running, completed or failed, with the workflow phase); they were missing because they live in `subagents/workflows/`.
- A fix run stays *running* until its Claude process exits; a run with background jobs was marked done after its first turn, so only one of several runs showed as in progress.

### Changed
- Overview starts with the machine; task attention stays on the Tasks page. Expired limits are no longer shown as current.

## 0.10.0 — 2026-10-15

First public release.

### What it does
- **Sessions:** every running Claude Code session with its agents, background jobs, skills, MCP servers, containers, databases and worktrees, and your messages with how long each answer took.
- **Claude usage** in the sidebar: session (5 h), weekly and per-model limits with reset times and the account they belong to, read from Claude Code's own cache — no token.
- **Tasks:** Jira tasks (or just the task keys in your titles) joined with your merge / pull requests: status columns, kanban, review threads, conflicts, colour marks, minimize.
- **Merge / pull requests** from GitLab or GitHub, like the host's own list: labels, pipeline or checks, reviewers, approvals, threads.
- **Fix skills:** ⋯ → Run fix starts a Claude Code skill of your choice in the background, following a documented contract (`docs/fix-skill.md`, `examples/fix-skill/`). `opsboard review` gives skills one CLI for GitLab and GitHub that refuses requests you did not open; `opsboard skill check` checks a skill against the contract.
- **Docker, Postgres, Worktrees, Processes, machine metrics** and **Notes** (a checklist with live Jira status).
- **Project profiles** (`generic`, `odoo-docker-env`), a team file `.claude/opsboard.profile.json` in the project repository and a personal `profile.local.json`.
- English, Uzbek and Russian interface; light and dark themes; keyboard shortcuts; a sidebar that shrinks to icons and becomes a menu on phones.
- **Set up with Claude:** a prompt that lets Claude Code fill the settings through the CLI.

### Security
- Listens on `127.0.0.1` only, accepts only `localhost` Host headers (blocks DNS rebinding) and needs the page's own token for every change.
- Tokens live in the macOS Keychain or the Linux Secret Service; `config.json` only when neither exists. Redacted from everything the page shows.

### Upgrading from the internal "Claude Ops" builds
- The history was squashed for the public release, so `git pull` no longer works: re-clone (`git clone https://github.com/Javohir-dev/opsboard.git`), copy your `config.json`, `notes.json`, `marks.json` and `profile.local.json` into the new folder, then run `./install.sh`. The command is now `opsboard`; `ops-dash` stays as an alias.
- Tokens move to the Keychain entry `opsboard` automatically; autostart entries are renamed the next time you run `opsboard autostart on`.
- The bundled `mr-fix` skill is gone; `opsboard update` removes a leftover `~/.claude/skills/mr-fix` link. Pick your own in *Settings → Claude → Fix skill*.
- Reload open dashboard tabs once.
