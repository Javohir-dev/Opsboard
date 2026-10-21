# Opsboard

A local dashboard for developers who work with [Claude Code](https://claude.com/claude-code): your sessions and agents, your merge / pull requests and tasks, Docker, Postgres and the machine — in one browser tab.

![Overview](docs/screenshots/overview.png)

One browser tab shows:

- **Sessions** — every running Claude Code session: what it is doing right now, its agents (running / done / failed), background jobs, the skills, MCP servers, containers, databases and worktrees it uses, and your message history with how long each answer took.
- **Tasks** — your Jira tasks (or just the task keys in your titles) joined with your merge / pull requests: status columns, open review threads, merge conflicts, which Claude session works on which task, colour marks, and a one-click background fix run with your own skill.
- **Merge / pull requests** — GitLab or GitHub, as in their own list: Open / Merged / Closed tabs, labels, pipeline or checks, reviewers, approvals and review threads.
- **Docker / Postgres / Worktrees** — running containers, database connections and slow queries, worktrees with uncommitted changes, and leftovers whose worktree is gone.
- **Claude usage** — your plan limits (session, weekly, per model) with reset times and the account they belong to, in the sidebar. See [Claude usage](#claude-usage).
- **Machine** — CPU, RAM, swap, GPU, disk, network and power.
- **Notes** — a personal checklist (ToDo / Warning / Done, nesting, dividers) with live Jira status next to every task key.

It runs on your machine only (`127.0.0.1`), needs nothing but Python 3, and sends your tokens only to your own code host and Jira. Interface in English, Uzbek and Russian.

> Screenshots show the built-in demo (`OPS_DEMO=1`, see *Development*) — no real data.

**Supported:** macOS and Linux. Windows is not supported.

---

## 1. Requirements

| Needed | Why |
|---|---|
| macOS or Linux | |
| Python 3.8+ | runs the dashboard (standard library only — no `pip install`) |
| git | install and update |
| GitLab token (`read_api`) **or** GitHub token | merge / pull requests, review threads, conflicts, pipelines |
| Jira API token *(optional)* | your tasks; without Jira, tasks come from the keys in your merge / pull request titles |
| Docker *(optional)* | Docker and Postgres pages |
| Claude Code CLI *(optional)* | background fix runs |

## 2. Install

```bash
git clone https://github.com/Javohir-dev/opsboard.git ~/.opsboard
cd ~/.opsboard && git checkout -q "$(git describe --tags --abbrev=0)"   # the latest release
./install.sh
```

`install.sh` checks Python, puts an `opsboard` command into `~/.local/bin` and opens the dashboard at <http://127.0.0.1:8095/>.

If it prints a `PATH` hint, add that line to `~/.zshrc` (or `~/.bashrc`) and open a new terminal.

## 3. First run — Settings

The first time, only **Settings** is open. Every other page unlocks when the fields marked with a red **\*** are valid.

1. **Project folder \*** — click the field and pick the checkout you work in. From it the dashboard detects the code host and project, worktrees, the project profile and the Postgres container.
2. **Code host** — GitLab or GitHub, detected from the git remote.
   - **GitLab:** *Preferences* → *Access tokens* → scope **`read_api`** (**`api`** if your fix skill replies to threads) → paste → **Test & save**.
   - **GitHub:** *Settings* → *Developer settings* → *Fine-grained tokens*, for the repository: **Pull requests**, **Contents** and **Checks** read (**Pull requests: write** if your fix skill replies) → paste → **Test & save**.
3. **Tasks → Tracker** — *Jira* (site, email and an API token from <https://id.atlassian.com/manage-profile/security/api-tokens>) or *None*.
4. Check the **Status** cards at the top. Each card is clickable and jumps to the setting to fix; **Re-detect** runs detection again.

**Set up with Claude** (on the Settings page) gives you a prompt to paste into Claude Code in your project folder: Claude runs `opsboard detect`, fills what it can find with `opsboard config set … --source agent`, tells you which tokens to store yourself with `opsboard secret set …` (it never asks for them in the chat) and can draft a fix skill for your project.

The interface is in English, Uzbek or Russian — *Settings → You → Language* (default: the browser's language). Translations live in `static/i18n/`.

Each value shows where it came from — *set by you*, *detected*, or *please check* (low confidence; press **Confirm** if it is right). Your own values always win over detected ones; **Reset** goes back to the detected value.

![Settings](docs/screenshots/settings.png)

## 4. Daily use

```bash
opsboard            # start (if needed) and open the browser
opsboard status     # is it running, on which port
opsboard restart    # after changing the port or updating by hand
opsboard down       # stop
opsboard update     # install the newest release (a development checkout on a branch: git pull) + restart
opsboard version    # the installed version
opsboard autostart on|off   # start at login (launchd on macOS, systemd --user on Linux)
opsboard doctor     # check every connection from the terminal
```

### Keyboard shortcuts

Press **`?`** anywhere for the list. Defaults (press `g`, then the letter):

| Page | Keys | Page | Keys |
|---|---|---|---|
| Overview | `g o` | Worktrees | `g w` |
| Sessions | `g s` | Processes | `g r` |
| Docker | `g d` | Notes | `g n` |
| Postgres | `g p` | Settings | `g ,` |
| Tasks | `g t` | Merge requests | `g m` |

Change them in *Settings → Keyboard shortcuts*: click a field and press the keys (`alt+1`, `cmd+shift+k`, `t`…). Plain keys are ignored while you type; shortcuts with `alt` / `ctrl` / `cmd` work everywhere.

### Claude usage

The sidebar shows the same numbers as Claude Code's *Account & Usage*: session (5 h), weekly and per-model limits, when each resets, and which account (email, organization, plan) they belong to. It needs a Claude subscription (Pro, Max, Team, Enterprise); with an API key there are no plan limits and the block stays hidden.

Turn it off in *Settings → Claude → Live Claude usage*: then there are no limits at all — the sidebar shows CPU, RAM and swap instead, and Overview leaves out the machine tiles.

**Live — every minute (on by default).** Opsboard asks Anthropic for your limits once a minute with Claude Code's own sign-in, the way Claude Code itself does. A green **LIVE** tag appears next to *Claude usage*.

- **macOS:** the sign-in is in the Keychain item *Claude Code-credentials*. The first time, macOS asks whether `security` may read it — choose **Always Allow**. (Plain *Allow* works too, but macOS asks again each time Claude Code renews its sign-in.)
- **Linux:** it is read from `~/.claude/.credentials.json`; nothing to confirm.
- Opsboard keeps the sign-in in memory only, sends it nowhere but `api.anthropic.com`, never writes or shows it, and never renews it — when it expires, open Claude Code once and live numbers come back.
- If anything goes wrong (expired sign-in, rejected, offline, rate-limited) the sidebar falls back to the saved numbers and says why under *Live usage:*.
- This uses the same endpoint as Claude Code's *Account & Usage*; it is not a documented public API and may change.

If the live request fails, the sidebar shows what Claude Code last saved in `~/.claude.json` (run `/usage` in Claude Code to refresh it): *updated 3h ago* when it is older than a few minutes, *Reset — open /usage to refresh* for a limit whose reset time has passed.

### Sessions page

Every live Claude Code session as a card: what it is doing now, its agents, the containers, databases and skills it uses. **Details** opens the session — agents, background jobs, your messages and how long each answer took.

![Sessions](docs/screenshots/sessions.png)

### Tasks page

![Tasks](docs/screenshots/tasks.png)

- **Update** (or the ↻ icon on Overview) reloads Jira and the code host now; otherwise they refresh every 5 minutes (*Settings → Advanced*).
- **List / Kanban** switch in the toolbar; status cards on top hide or show columns.
- **⋯** on a task: colour marks (Stopped, High, Watch, Ready, Note, Waiting on others, Paused), **Minimize** in *Needs attention*, and **Run fix**.

![Kanban](docs/screenshots/tasks-kanban.png)

### Merge / pull requests page

![Pull requests](docs/screenshots/mrs.png)

Your open requests also appear on Overview, under *Tasks · needs attention*. The page lists your merge / pull requests in the configured project, like the host's own list: **Open / Merged / Closed / All** tabs with counts, search, and sort by created or updated date. Each row shows the labels in the host's colours, pipeline / checks status, reviewers, **Approved**, resolved review threads (`2 of 3`), merge conflicts and the linked Jira task with its status. **⋯** on a row: colour marks, **Minimize** (one-line row, ↔ expands it) and **Run fix** for open requests.

### A merge / pull request

Click a title to open it here instead of on GitLab / GitHub. The header reads like GitLab's (*Open · you requested to merge `branch` into `target`*, with copy buttons) and has the same tabs: **Overview** — the description rendered like on the host (tables, `<details>`, Mermaid diagrams), the pipeline, approvals, threads and conflicts, reviewers and labels; **Commits**; **Pipelines** (*Checks* on GitHub); and **Changes**: the changes like the host's *Changes* tab — a file tree with search on the left, syntax-coloured diffs, *Viewed* per file (remembered in your browser), copy path, expand / collapse all — and on the right every review thread like GitLab shows it — unresolved ones open on top, resolved ones folded into *N replies · Last reply by …* with who resolved them and when. The counter above them jumps between the unresolved threads (↑ ↓) and ⋮ expands or folds them all. A marker in the diff shows where a thread sits; click it, or the `file:line` on a thread, to jump between them. **Open in GitLab** and **Run fix** are at the top; the page reloads from the host every two minutes or with ↻.

### Notes page

A checklist for your own notes, saved as you type. It opens even before Settings are complete.

![Notes](docs/screenshots/notes.png)

| Key | Does |
|---|---|
| Enter | new line (splits at the cursor) |
| Tab / Shift+Tab | indent / outdent |
| ⌘Enter (Ctrl+Enter) | toggle **Done** |
| Backspace at the start | outdent, then join with the line above |
| Alt+↑ / Alt+↓ | move the line |
| `---` + Enter | divider |

- New lines start as **ToDo**; an empty line is removed when you leave it.
- Click the chip left of the text to pick a tag: **ToDo**, **Warning**, **Done** (crosses the line out) or **None**.
- Task keys such as `SHOP-142` become links with their current Jira status.
- **Import from Notion:** in Notion select the list → *Copy* (or *Copy as Markdown*) → paste into any line. `- [ ]` / `- [x]` items, nesting and `[ToDo]` / `[done]` / `[⚠️]` prefixes are kept.
- **⋯** at the end of a line → **Show history** (created date and time, every tag change such as *ToDo → Done*, and every text change with the old and new text) or **Delete**.
- Deleted lines go to **Deleted (N)** in the toolbar, keep their history and can be **Restored**.
- **Date filter**: Today, Yesterday, Last 7 / 30 days or a custom range, by the date a line was *created* or last *changed*.
- Overview lists your **ToDo** lines at the bottom (*Notes · to do*) and you can edit them right there — text and tag; **show all** lists every line.
- Done items are hidden unless **show done** is on. Notes are stored in `notes.json` and never committed.
- Edits from two open tabs are merged, not overwritten. Every save keeps the previous version in `notes-history/` (last 50) — copy one back over `notes.json` to restore.

### Postgres page

Connections per database and which container they come from, queries running now, transactions left open, and databases whose worktree is gone.

![Postgres](docs/screenshots/postgres.png)

### Worktrees page

Every worktree with its uncommitted files, last commit, server container, databases and the Claude sessions using it. **Clean up** deletes one worktree and everything that belongs to it — the folder, its local branch, its server container and its databases (with their files). It first shows exactly what will go, and warns about anything you would lose: uncommitted changes, commits that are not pushed anywhere, a merge request that is still open, a Claude session still working there. With a warning the button reads **Yes, clean up anyway** and forces it.

Only worktrees in the list can be removed — never the main checkout — and only the containers and databases whose names the profile derives from that worktree (`{project}-qa-{slug}`, `wt_{slug}_qa`…). A profile can name its own command for this (`worktrees.remove`); `odoo-docker-env` uses `invoke remove-worktree -n {name}` (with `--force` when forced), which also removes Odoo filestores.

### Fix skill: fixing review threads in the background

![Run fix](docs/screenshots/fix.png)

**⋯ → Run fix** on one of your open merge / pull requests starts a Claude Code skill of your choice in the background (*Settings → Claude → Fix skill*). Opsboard does not ship one: write your own for your stack, following **[the fix-skill contract](docs/fix-skill.md)** — how it is called, the safety rules, push permission, what "skip tests" means, and the `OPS_RESULT` line it reports back. [`examples/fix-skill/SKILL.md`](examples/fix-skill/SKILL.md) is a starting point.

The dialog turns into a call like `/<skill> 7264 push skip-tests`:

| Switch | Word |
|---|---|
| Review threads | — (off: `conflict-only`) |
| Merge conflict | the target branch is always merged first |
| Skip tests | `skip-tests` |
| Push, reply and resolve | `push` |

Follow it under **Background runs** on Overview or Tasks, or on the request page's fix tab: the steps (*Merge target → Threads → Fix → Checks → Commit → Push & reply*) with how long each took, which threads were replied to or resolved during the run, and a live feed of what Claude says, runs and edits (click a command to see it in full). **Stop** kills it. Turn the action off in *Settings → Claude → Background runs*.

When a run finishes, the **bell** next to the logo (top right on a phone) shows a red count and the tab title gets `(1)`. Click it to see what the run did — pushed, committed, stopped or failed, with the commit, threads and checks — and click an entry to jump to its merge / pull request on Overview, which lights up once so it is easy to spot (the run, if the request is no longer open). Runs you stop yourself are not announced. A **new review thread** on one of your open requests is announced too (not your own); opening it jumps to the thread on the request page. Each notification plays a short system sound (Glass, or Basso when the run failed or stopped; on Linux the freedesktop sounds through `paplay`/`pw-play`) — *Settings → Claude → Sound when a fix finishes*, with a *Play it* button to try it.

Desktop alerts: in the bell panel press **Turn on** once and allow notifications in the browser; the alert opens the dashboard when clicked. With no dashboard tab showing alerts (closed, or alerts not allowed), Opsboard posts a system notification itself — Notification Center on macOS, `notify-send` on Linux.

Skills talk to GitLab through `opsboard review`, so they need no token or API code of their own, and it refuses to touch merge requests you did not open:

```bash
opsboard review whoami             # host user, git author, reply language, project folder
opsboard review mine [--conflicts] # your open merge requests
opsboard review info 7264          # branches, sha, conflicts
opsboard review threads 7264       # open review threads as JSON
opsboard review reply 7264 <thread> reply.md --resolve
opsboard review describe 7264 description.md
opsboard review upload test-log.txt
```

`opsboard skill check <name>` checks a skill against the contract.

### Telegram

Opsboard can also live in a Telegram bot. It runs inside Opsboard — it starts and stops with it and needs no public address (it asks Telegram for messages itself).

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`) and paste its token in *Settings → Telegram* (kept in the Keychain / Secret Service).
2. Press **Open @yourbot in Telegram** and **Start**: a one-time code links your Telegram account. The bot ignores everyone else and every group.
3. **New thread notifications:** a message when someone opens a review thread on one of your open requests.

Commands: `/mrs` (open requests), `/mr 7376`, `/sessions` (Claude sessions that are working and how many agents each runs), `/usage` (Claude plan limits with bars and reset times — live when *Live Claude usage* is on, otherwise Claude Code's cache with its age), `/info` (which accounts it is linked to — Telegram, GitLab / GitHub, Jira, Claude — this Mac, the Opsboard version and the bot's settings; never tokens).

**Claude chat** (*Settings → Telegram → Claude chat*, off by default): any other message goes to Claude Code on your Mac, in your project folder, and the answer comes back. It is one Claude Code session that stays open between messages (closed after 3 idle hours or when Opsboard stops): messages you send while it works queue up, and when it comes back on its own — a background job finished, another session answered — that arrives as a new message. `/new` starts a fresh conversation; `/cancel` stops the current answer. *What Claude may do* picks the permission mode — *Read and answer only* by default.

### Project profiles

Everything specific to how a project is laid out lives in a profile, chosen in *Settings → Workspace → Project profile* (detected automatically):

| Profile | For |
|---|---|
| `generic` | any git project: worktrees from `git worktree list`, Jira statuses grouped by their category |
| `odoo-docker-env` | Odoo projects in the camptocamp docker-env layout: worktrees of `src/local`, a QA container and databases per worktree (`<project>-qa-<worktree>`, `wt_<worktree>_qa`), Russian Jira status names, module names from MR titles |

Additions for a whole team — task areas and their names, keywords, plan sections, extra status names — go into **`.claude/opsboard.profile.json` in the project repository**, so everyone who clones the project gets them. Your own, on top of that, go into `profile.local.json` next to `config.json` (never committed). Order: built-in profile → project file → your local file. The built-in profiles are in `profiles/` (send a pull request to add one).

## 5. Where things are stored

Everything lives in the checkout folder (`opsboard home` prints it; `~/.opsboard` if you followed step 2) and is ignored by git:

| File | Contents |
|---|---|
| `config.json` | your settings (`chmod 600`); tokens too, but only when no Keychain / Secret Service is available |
| `.page-token` | the token the page sends with every change |
| `marks.json` | colour marks on tasks |
| `profile.local.json` | your additions to the project profile |
| `notes.json`, `notes-history/` | your notes and their last 50 versions (`chmod 600`) |
| `runs/`, `runs.json` | background fix runs and their logs |
| `notifications.json` | the bell's notifications (last 100) |
| `threads-seen.json` | review threads already announced |
| `mr-modules.json`, `key-aliases.json` | caches |
| `server.log`, `opsboard.log` | start-up output; server log (rotated at 1 MB, 3 kept) |

Order of precedence: environment variable (`OPS_*`) → *set by you* → *set by Claude* → *detected* → default.

Settings from the terminal:

```bash
opsboard config get                       # everything (tokens masked)
opsboard config set db.container my-db-1  # your own value
opsboard config unset db.container        # back to the detected value
opsboard secret set gitlab.token          # asks for the token without echoing it
opsboard detect                           # what would be detected (add --apply to save)
```

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| `opsboard: command not found` | add `~/.local/bin` to `PATH` (step 2) |
| Page does not open | `opsboard status`; see `server.log` in `opsboard home` |
| Port 8095 is busy | *Settings → Advanced → Port*, then `opsboard restart` |
| Pages stay locked | open Settings — the red box lists what is missing or rejected |
| "token was rejected" | the token expired or lacks `read_api` — create a new one and **Test & save** |
| Postgres card is red | *Settings → Workspace → Postgres container*, or **Re-detect** with Docker running |
| Linux: no folder dialog | install `zenity` (or `kdialog`), or use **type path** |
| Docker card says not running | macOS: **Start Docker**; Linux: `sudo systemctl start docker` |
| No *Claude usage* in the sidebar | run `/usage` in Claude Code once; with an API key (no subscription) there are no plan limits to show |
| Claude usage says *updated 18h ago* or *Reset — open /usage* | run `/usage` in Claude Code, or turn on *Live Claude usage* |
| *Live usage: … not allowed* | macOS denied Keychain access: turn the switch off and on, then choose **Always Allow** in the dialog |
| *Live usage: … sign-in has expired* | open Claude Code once (it renews its own sign-in); Opsboard never renews it |
| macOS keeps asking for the Keychain | you chose *Allow* instead of *Always Allow* — choose **Always Allow** once |

## 7. Uninstall

```bash
opsboard down
rm ~/.local/bin/opsboard
rm -rf "$(opsboard home)"      # also deletes your settings
security delete-generic-password -s opsboard -a gitlab.token   # macOS: tokens live in the Keychain (repeat for jira.token, github.token)
```

## Development

```bash
OPS_DEMO=1 OPS_DATA_DIR=$(mktemp -d) python3 server.py --port 8094   # demo data, never your own
```

```bash
opsboard test          # unit and HTTP tests (Python standard library only)
opsboard test --e2e    # plus a Playwright smoke test of every page (needs Node 20+)
uvx ruff check . && uvx ruff format --check .
```

Layout:

| Path | What |
|---|---|
| `server.py` | HTTP server, security checks, `/api/*` |
| `core.py` | paths, shared state, collector loop, logging |
| `sessions.py` | Claude Code sessions, agents and background jobs from the transcripts |
| `system.py` | machine, Docker, Postgres, worktrees |
| `tasks.py` | Jira and GitLab |
| `runs.py`, `notes.py`, `review.py` | background fix runs; notes and colour marks; `opsboard review` |
| `config.py`, `secretstore.py`, `detect.py`, `machine.py` | settings, Keychain / Secret Service, auto-detection, OS helpers |
| `index.html`, `static/` | the page: `style.css`, one script per page in `static/js/`, [morphdom](https://github.com/patrick-steele-idem/morphdom) (MIT) in `static/vendor/` |

The page re-renders every 2 seconds by patching the DOM (morphdom), so what you are typing, a focused field and an open dropdown are left alone.

Tests never touch your own data: they run a separate server with `OPS_DATA_DIR` pointing to a temporary folder and keep tokens in a plain file there (`OPS_SECRET_STORE=file`). CI (`.github/workflows/ci.yml`) runs the same on Linux and macOS, Python 3.8 and 3.12.

## Security

- The server listens on `127.0.0.1` only. It answers only requests addressed to `127.0.0.1:<port>` or `localhost:<port>` (this blocks DNS-rebinding attacks), and every change must carry the page's own token (`.page-token`, `600`), so other web pages cannot act on it.
- Tokens are kept in the **macOS Keychain** or the Linux **Secret Service** (libsecret, via `secret-tool`); only when neither is available do they fall back to `config.json` (`600`). Tokens already in `config.json` move to the Keychain on the next start. They are shown in the browser only as `••••1A3F` and redacted from everything the dashboard displays — including text you pasted into Claude.
- The dashboard only reads GitLab and Jira. Writing happens only in a background fix run that you start yourself, through `opsboard review`, and only on your own merge requests.

## License

[MIT](LICENSE). See [CHANGELOG.md](CHANGELOG.md) for what changed in each version.
