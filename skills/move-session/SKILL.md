---
name: move-session
description: "Move a Claude Code session from one of the user's Claude accounts to another with claude-session-mover (csm), keeping the whole conversation. Use when the user says: move this session to another account; move my <title> session to <account>; I'm out of quota, move it to <account>; this account is rate limited, switch accounts; which of my sessions are out of quota; list my sessions across accounts. Also when they name an account next to a session, or paste a claude.ai/code/session_… link and ask to run it as another account. Use it too for: stop the session you moved, close that moved window, clean up after the move; which permission mode is the moved session in; and which of my accounts are set up the same / do my accounts share settings, skills, plugins, memory (csm matrix)."
---

# Move a session to another account

`csm` (claude-session-mover) moves a Claude Code session to another of the user's own
accounts. It copies the transcript into the target account's config home and resumes it
there, with Remote Control on, so the conversation continues on that account's quota and
shows up in that account's Claude app. An account is a config home: `~/.claude` (named
`default`) or `~/.claude-<name>` (named `<name>`), or whatever `csm accounts` lists.

**A move is between two config homes on ONE machine.** `csm --ssh HOST …` runs the same
command over there; it never moves a session from this machine to that one.

```
csm accounts                                  # the homes, who each is signed in as, live sessions
csm list [--account NAME] [--all] [--json] [--limit N]
csm move SESSION --to ACCOUNT [--stop-source] [--dry-run] [--permission-mode MODE]
                              [--name LABEL] [--no-remote-control] [--foreground] [--all]
csm stop SESSION [--dry-run]                  # end a session csm moved, free its window
csm matrix [--check] [--json] [--cwd DIR] [--account NAME]
```

SESSION is a row number from the `csm list` you just ran, a session id or a 4+ character
prefix, a `claude.ai/code/session_…` link, or enough of the title to be unique. ACCOUNT is a
name, an email, or a unique prefix. **Never pass a bare number as an account**: names only.

## Moving

1. **Run `csm list` first, always**, even when the user named the session. The row numbers
   `move` accepts come from that listing, and it shows `● live`, `← this session`,
   `⚠ OUT OF QUOTA (kind, resets HH:MM)` and `closed` (ended from the app).
2. **Show a short shortlist in your own words**: the session, its account, its age, and
   whether it is out of quota. The user may be on a phone.
3. **If which session they mean is not certain, ask one short question** naming the two or
   three candidates. Never move on a guess: a move starts a second process on a conversation.
4. **If they named no account, suggest one** that is not the source, is `ok` in
   `csm accounts`, and is not flagged out of quota. Say which and why, then move.
5. **Run `csm move <row> --to <account> --stop-source`.** Use `--dry-run` first only when
   something looks off; a dry run prints `🛑 a real move would be REFUSED: …` when it would be.
6. **"Move THIS session"**: just do it. The tool recognises its own session and will not stop
   it (that would kill the turn reporting the move). Tell the user to close this one in the
   app so only the moved copy gets their next message. The copy ends at the last line already
   on disk, so this exchange is not in it.
7. **Read the plan the tool prints before answering.** Its `⚠` lines are the warnings below,
   measured for the source and target homes — pass on the ones that apply instead of
   guessing.
8. **Answer with one short block**: the account to open the app as, the session title, and the
   `https://claude.ai/code/session_…` link the tool printed. Then the caveats below.

**Move early, not at the limit.** Across two organizations the CLI drops the session's
preserved thinking, so the first turn after a move re-reads the whole conversation — on the
*target* account's quota. A long session moved at the very end of a quota window spends a
slice of the quota it was moved to find. The tool prints this cost block after every move,
and says `same organization: the session's preserved thinking is KEPT.` when the two
logins share one.

## Permission mode

A move never weakens a session. Without a flag the tool resumes in the mode the session was
running in, raised to the target home's `permissions.defaultMode` only when the session
recorded nothing, `default` or `auto`; `plan` and `acceptEdits` are carried as they are. The
plan line `mode <M> (<why>)` names where the choice came from.

Pass `--permission-mode` to choose: `plan`, `default`, `acceptEdits`, `auto`, `dontAsk`,
`bypassPermissions` (`manual` is an alias of `default`). Only ask for `bypassPermissions`
when the user asked for it, and expect the warning below if the target has never accepted it.

After the move the tool reports the mode it **came up in**, or says the mode is
`the mode REQUESTED, not a measurement` and gives the `tmux capture-pane` command to check.
If it came up in a different mode, it says so with a 🛑 and the fix (`csm stop`, then move
again without touching the app's picker). Pass that on — do not claim a mode it did not
measure.

## Say every time

- **A new session in the target account**: new id, new claude.ai link, owned by that account.
  The old link still opens the source copy. The moved agent has the whole conversation; the
  app may show the thread starting at the move.
- **The old session is not deleted.** It stays in the source account; archive it in the app if
  wanted. `--stop-source` only stops its process, and only after the move has connected — and
  it captures the source pane's scrollback to `<state dir>/captures/<date>/` (0600) first and
  prints the path. Tell the user where it went; it holds conversation text, so it stays on
  that machine.
- **The first turn is slower**: the prompt cache starts cold. Across organizations it is also
  the expensive one — preserved thinking does not cross, so the whole conversation is re-read on
  the new account's quota. Move early rather than at the limit.
- **The move carries the session's rewind history** (and its task list, where the build keeps
  one in the config home), not just the transcript, and nothing else from the home: no
  registry, no shell snapshots, no credentials. Skills, plugins and MCP servers come from the
  target home.
- **The copied transcript still names the source account inside itself**, so the moved session
  may describe itself as the old account until its context is rebuilt.

## Warnings to pass on when the plan prints them

- **claude.ai connectors belong to the account.** The moved session gets the *target*
  account's connectors, and no terminal command can attach one. If the conversation has used
  connectors, the tool names them: tell the user to enable the same set on the target account
  at claude.ai/customize/connectors, in a browser signed in as that account.
- **MCP sign-ins are per config home.** The tool names the MCP servers the conversation used;
  the fix is `claude mcp login <server>` once in the target home.
- **Plugins, skills, agents, commands and output styles come from the target home.** Enabled
  in a shared settings file is not installed. The conversation arrives intact; those tools do
  not, unless both homes point at one directory.
- **Auto-memory is per home** unless both resolve to one store. csm never copies memory, in any
  configuration — a copy becomes a second set that drifts.
- **Bypass consent / "Enable Remote Control?"** never answered in the target home: the window
  may stop on that question.
- **`⚠ UNVERIFIED`**: the credential store could not be asked, so whether that login still
  works is unknown. The move goes ahead; say so.
- **`may be out of quota TOO`**: say it before the link and offer another account.

## Stopping a moved session

`csm stop SESSION` ends a session **csm moved** and removes the tmux window it opened. That
window is also what blocks moving the same session to the same account twice, so this is the
unblocker for `a window … already exists`.

- It stops nothing else: the authorisation is csm's own `moved-<id8>` window in the
  `csm-<account>` tmux session, plus, for a running session, a registry row naming that same
  window. Anything else is refused, with the list of windows csm did open.
- It never stops the session running the command, and **never deletes a transcript**.
- **The pane's whole scrollback is captured first**, to `captures/<date>/` under the state
  directory (0600), and the path is printed — tell the user where it went. A prompt the agent
  had typed and not yet sent exists nowhere else, and killing the window destroys the pane with
  the process. The capture can never fail the stop. Those files hold conversation text: leave
  them on that machine, do not copy them into a synced or served folder.
- Killing the window SIGHUPs the pane's process tree, so a session whose pid could not be
  proved still ends with its window. The tool says which happened.
- `--dry-run` prints the plan and stops nothing.

## "Which of my accounts are set up the same?"

`csm matrix` prints the user's own fungibility table: rows are the layers that decide whether
accounts are interchangeable (account, login, settings.json, settings.local.json, CLAUDE.md,
skills, agents, commands, output styles, plugins, scheduled tasks,
enabled-but-not-installed plugins, MCP servers, auto-memory, onboarding, folder trust,
permission mode, disableAutoMode, bypass consent, CLI version, connectors, MCP sign-ins),
columns are the config homes on this machine.

It is read-only, offline and prompt-free: it writes nothing into any config home (only a line
in csm's own log), never runs `claude`, never reads a credential value, and makes no network
call. `--check` exits 1 when a shareable layer diverges or a login is gone (never on an
unknown). One realpath for every home counts as shared wherever that path lives, so sharing
through the default `~/.claude` passes the check, with a note. `--cwd DIR` picks the project the trust and memory rows are
measured for, `--account NAME` limits the columns, `--json` gives the whole table.

Use it when the user asks why a moved session lost a skill or a plugin, which homes share one
settings file, or whether their accounts are interchangeable. Read it out as the few rows that
differ — `?` means "could not look", which is not "no". `✅ shared / 🔧 one shared file or key
away / 🛑 per account by design` is the legend.

## Refusals and their fixes

| The tool says | Fix |
|---|---|
| `already in <account>` | pick a different account |
| `same login as` | that home is signed in to the same account: pick another |
| `holds no login` | the user signs that home in: `CLAUDE_CONFIG_DIR=<home> claude`, then `/login`. Never do this yourself |
| `credential is GONE` | the state file still names someone but the login is not there: the user signs in again |
| `WRONG login` | the accounts file expects another email there: the user signs it in again |
| `named, never numbered` | use the account's name |
| `row N is not in the last csm list` | run `csm list` again and use its numbers |
| `matches N sessions` | a move is a copy, so an id can be in two accounts: use the row number |
| `ALREADY running session` | the target already runs that session: stop it there first, or pick a third account |
| `a window … already exists` | moved there before: `csm stop <session>`, or pick another account |
| `does not exist on <host> any more` | the session's directory is gone: recreate it, or move another session |
| `is not a session csm moved` | `stop` only ends csm's own windows: close that one in the app or its own terminal |
| `is not a permission mode` | use one of the modes listed in the message |

## Boundaries

- Run it on the machine where the session's transcripts are; `csm --ssh HOST …` reaches
  another one.
- Move only the session the user asked about, one per request unless they said otherwise.
- Never stop a process or close a window csm did not start. `--stop-source` and `csm stop` are
  the only stops, and `--stop-source` fires only after the moved session has connected.
- Never read, print or copy credentials, and never sign an account in on the user's behalf.
