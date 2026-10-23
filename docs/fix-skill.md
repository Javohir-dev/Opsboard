# Writing a fix skill

A **fix skill** is a Claude Code skill that takes one of your open merge / pull requests, fixes what reviewers asked for and resolves merge conflicts. Opsboard does not ship one, because what "fixed" means depends on your stack: which tests to run, how to lint, which files need special care in a conflict. You write it once for your project; the dashboard runs it in the background from **⋯ → Run fix**.

This page is the contract between the dashboard and your skill. [`examples/fix-skill/SKILL.md`](../examples/fix-skill/SKILL.md) follows it and is the quickest way to start.

## 1. Where the skill lives

A folder with a `SKILL.md`, in either place:

- `<project>/.claude/skills/<name>/` — shared with everyone who works in the project (commit it), or
- `~/.claude/skills/<name>/` — only for you.

Then choose it in *Settings → Claude → Fix skill*. `opsboard skill check <name>` checks it against this page.

## 2. How it is called

```
/<name> <number> [push] [skip-tests] [conflict-only]
```

| Word | Meaning | Your skill must |
|---|---|---|
| *(none)* | fix the open review threads and merge the target branch | commit, **not push**, put the thread replies into the final report |
| `push` | the user allowed publishing | push the source branch, reply to each thread and resolve it, update the description if needed |
| `skip-tests` | the user wants it fast | skip the test suite, but still run the **quick checks** (§5) |
| `conflict-only` | only the merge | merge the target branch and resolve conflicts; leave the review threads alone |

Words can come in any order. Anything else in the arguments is not from the dashboard — treat it as a request from the user.

The dashboard also sets these environment variables (a person calling the skill by hand will not have them, so fall back to `opsboard review info <number>`):

| Variable | Value |
|---|---|
| `OPS_REVIEW_HOST` | `gitlab` or `github` |
| `OPS_PROJECT` | `group/project` or `owner/repo` |
| `OPS_NUMBER` | the merge / pull request number |
| `OPS_URL` | its web address |
| `OPS_SOURCE`, `OPS_TARGET` | source and target branch |
| `OPS_PUSH` | `1` when `push` was given |
| `OPS_REPLY_LANGUAGE` | `thread` (answer in the reviewer's language), `en`, `ru` or `uz` |
| `OPS_PROJECT_ROOT` | the project folder; the run starts here |

## 3. Talking to GitLab or GitHub

Use `opsboard review` instead of calling the API yourself. It uses the token from the dashboard's settings, works the same on GitLab and GitHub, and **refuses to touch a merge / pull request the user neither opened nor is assigned to**.

```bash
opsboard review whoami                 # user, git author, reply language, project folder
opsboard review info <n>               # source, target, sha, conflicts, description
opsboard review threads <n> [--all]    # open review threads: id, author, bot, where, url, body, replies
opsboard review reply <n> <thread> <file> [--resolve]
opsboard review resolve <n> <thread>
opsboard review describe <n> <file>    # replaces the description, keeps the old one in <file>.bak
opsboard review upload <file>          # GitLab only: prints a markdown link to the uploaded file
opsboard review mine [--conflicts]     # your open merge / pull requests
```

Every command prints JSON and exits non-zero on failure (2: refused or not configured, 3: the host could not be reached).

## 4. Safety rules (not optional)

1. **Only the user's own merge / pull request.** `opsboard review` enforces it; do not work around it.
2. **Never `git push --force`**, never push to a branch other than the source branch.
3. **Never reply or resolve before the fix is pushed** — a thread marked "fixed" must point at a pushed commit.
4. **Do not touch the main checkout.** Work in a git worktree of the source branch (create one if needed).
5. **Stop on uncommitted changes** in that worktree — they belong to someone else's work. Report and exit.
6. **Without `push`, nothing leaves the machine:** no push, no reply, no resolve, no description update.
7. If a permission prompt is denied, **do not retry another way.** Commit what you have, report the command that was blocked.

## 5. Tests and quick checks

Without `skip-tests`, run the tests that cover what you changed (the narrowest set that proves the fix), and add a regression test when you fix logic.

With `skip-tests`, still run the **quick checks** — they must be fast (seconds) and deterministic. Typical choices:

| Stack | Quick checks |
|---|---|
| Python | `python -m py_compile` on changed files, `ruff check` |
| JavaScript / TypeScript | `tsc --noEmit`, `eslint` on changed files |
| Go | `go build ./... && go vet ./...` |
| XML / JSON / YAML | parse every changed file |

Write the exact commands into your skill so every run checks the same things. If a check fails, fix and re-run; after three failed attempts, stop and report.

## 6. Push permission

The dashboard starts the run with `claude -p … --permission-mode <Settings → Claude → Permission mode>`. In the default `auto` mode, Claude Code asks a classifier before risky commands, and pushing to a shared repository may be blocked. To let your skill push without a prompt, allow exactly what it needs in `~/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": [
      "Bash(git push origin *)",
      "Bash(opsboard review *)"
    ],
    "deny": [
      "Bash(git push --force*)",
      "Bash(git push -f*)"
    ]
  }
}
```

Keep `--force` in `deny`. If you would rather confirm each push yourself, leave `push` off in the dialog: the run commits and gives you the push command and the replies.

## 7. Reporting back

Finish with the normal human-readable report, then **one line** for the dashboard:

```
OPS_RESULT {"status":"pushed","commit":"a1b2c3d","threads":{"resolved":3,"open":0},"checks":"tests 42/42","note":""}
```

| Field | Values |
|---|---|
| `status` | `pushed`, `committed` (done, not pushed) or `stopped` (could not finish) |
| `commit` | the short sha of the last commit, if any |
| `threads` | how many threads you resolved and how many stay open |
| `checks` | what you ran, briefly: `tests 42/42`, `quick checks ok` |
| `note` | why it stopped, or anything the user must do |

The **Background runs** card shows this line; without it, the card shows the last lines of the report.

### Progress (optional)

The request page's fix tab shows six steps — *Merge target, Threads, Fix, Checks, Commit, Push & reply* — guessed from the commands the skill runs (`git merge`, test commands, file edits, `git commit`, `git push`, replies). To name them exactly, print a line on its own when a step starts or ends:

```
OPS_STEP {"step":"checks","status":"running","note":"tests 12/40"}
OPS_STEP {"step":"checks","status":"done","note":"tests 40/40"}
```

`step` is one of `merge`, `threads`, `fix`, `checks`, `commit`, `push`; `status` is `running`, `done`, `skipped` or `failed`; `note` is shown under the step. These lines are hidden from the live feed.

## 8. Replies on threads

Short, in `OPS_REPLY_LANGUAGE`: what changed, the commit, how it was checked. No apologies or filler. When you disagree with a reviewer, say why with evidence (file and line, a test, a measurement) and still resolve the thread if your process allows it.

```
Fixed in a1b2c3d: the total is now recomputed on write() too, covered by test_total_on_write.
```

## Checklist

- [ ] `SKILL.md` with `name` and a `description` that says when to use it
- [ ] understands `push`, `skip-tests`, `conflict-only`
- [ ] uses `opsboard review` for the host
- [ ] works in a worktree, stops on uncommitted changes
- [ ] never force-pushes; replies only after pushing
- [ ] quick checks written as exact commands
- [ ] ends with an `OPS_RESULT` line

`opsboard skill check <name>` reads your `SKILL.md`: the first five points are required, the rest are recommendations (it only understands English wording).
