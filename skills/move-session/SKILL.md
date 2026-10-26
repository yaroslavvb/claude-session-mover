---
name: move-session
description: "Move a Claude Code session from one of the user's Claude accounts to another with claude-session-mover (csm), keeping the whole conversation. Use when the user says: move this session to another account; move my <title> session to <account>; I'm out of quota, move it to <account>; this account is rate limited, switch accounts; which of my sessions are out of quota; list my sessions across accounts; move it to whichever account has quota left (csm move --to auto). Also when they name an account next to a session, or paste a claude.ai/code/session_… link and ask to run it as another account. Use it too to move a session BETWEEN MACHINES (move my session on the laptop to this machine, bring that desktop-app session over, continue this work on another computer) and to find a session anywhere by title or id, the desktop app's own sessions included (csm find, csm move --from-machine, --mirror-cwd). Use it for: stop the session you moved, close that moved window, clean up after the move; which permission mode is the moved session in; which live sessions are running weaker than this machine's default, is anything still stuck in auto, did my permission settings take, restart the idle ones in the wrong mode (csm modes); and which of my accounts are set up the same / do my accounts share settings, skills, plugins, memory (csm matrix)."
---

# Move a session to another account

`csm` (claude-session-mover) moves a Claude Code session to another of the user's own
accounts. It copies the transcript into the target account's config home and resumes it
there, with Remote Control on, so the conversation continues on that account's quota and
shows up in that account's Claude app. An account is a config home: `~/.claude` (named
`default`) or `~/.claude-<name>` (named `<name>`), or whatever `csm accounts` lists.

**A move is between two config homes, and by default both are on this machine.** Two
different flags involve a second machine, and mixing them up is the common mistake:

- **`csm --machine M …`** (or `csm --ssh HOST …`) runs this same command **on** that machine,
  where it again moves between two homes over there. Nothing crosses; the row numbers it
  prints are that machine's.
- **`csm move <id> --from-machine M`** brings a session **from** M **to here**: it is found
  over there in every config home, copied over ssh, and resumed here. `csm find --on M` is
  how you get the id.

Both global flags go **before** the subcommand: `csm --machine desktop list`, never
`csm list --machine desktop`.

```
csm accounts [--json]                         # the homes, who each is signed in as, live sessions, quota
csm list [--account NAME] [--all] [--json] [--limit N]
csm move SESSION --to ACCOUNT|auto [--stop-source] [--dry-run] [--permission-mode MODE]
                              [--name LABEL] [--no-remote-control] [--foreground] [--all]
                              [--from-machine M] [--mirror-cwd] [--copy-only]
                              [--from-account ACCOUNT]
csm stop SESSION [--dry-run]                  # end a session csm moved, free its window
csm find TEXT [--on M] [--all] [--json]       # where is that session, on any machine
csm modes [--account NAME] [--json] [--check] [--restart-idle [--apply]]
csm matrix [--check] [--json] [--cwd DIR] [--account NAME]
csm --machine M <command>                     # ...the same command, over there
csm --ssh HOST <command>                      # ...naming an ssh host instead of a machine
```

SESSION is a row number from the `csm list` you just ran, a session id or a 4+ character
prefix, a `claude.ai/code/session_…` link, or enough of the title to be unique. ACCOUNT is a
name, a handle, an email, or a unique prefix. **Never pass a bare number as an account**:
names only — a position in a list changes whenever an account is added.

`--limit N` is a hard cap when you type it — at most N rows, for a short table on a phone —
and the table says how many it left out. Left out, the default (20) never cuts a live session.

## Moving

1. **Run `csm list` first, always**, even when the user named the session. The row numbers
   `move` accepts come from that listing, and it shows `● live`, `← this session`,
   `⚠ OUT OF QUOTA (kind, resets HH:MM)` and `closed` (ended from the app).
2. **Show a short shortlist in your own words**: the session, its account, its age, and
   whether it is out of quota. The user may be on a phone.
3. **If which session they mean is not certain, ask one short question** naming the two or
   three candidates. Never move on a guess: a move starts a second process on a conversation.
4. **If they named no account, use `--to auto`** when a quota meter is configured: it picks
   the account here with the most weekly room among those with a fresh reading under both
   cutoffs, never the source, and prints which one and its numbers — pass that on. With no
   fresh reading it refuses rather than guess; then show `csm accounts` and ask. Without a
   meter, suggest an account that is not the source, is `ok` in `csm accounts`, and is not
   flagged out of quota.
5. **Run `csm move <row> --to <account> --stop-source`.** Use `--dry-run` first only when
   something looks off; a dry run prints `🛑 a real move would be REFUSED: …` when it would be,
   and prints the move note it would write.
6. **"Move THIS session"**: just do it. The tool recognises its own session and will not stop
   it (that would kill the turn reporting the move). Tell the user to close this one in the
   app so only the moved copy gets their next message. The copy ends at the last line already
   on disk, so this exchange is not in it.
7. **Read the plan the tool prints before answering.** Its `⚠` lines are the warnings below,
   measured for the source and target homes — pass on the ones that apply instead of
   guessing.
8. **Answer with one short block**: the account to open the app as, the session title, and the
   `https://claude.ai/code/session_…` link the tool printed. Hand over the **link, not the
   title**: with no custom title a session is named by its last prompt, so the name changes
   the moment the user types to the moved copy.
9. **Then offer `csm stop <id>`** when they are done with the moved copy. Every move leaves a
   `moved-<id8>` window, and while it exists moving that same session to that same account
   again is refused — so the cleanup is also what unblocks the next move.

**Move early, not at the limit.** Across two organizations the CLI drops the session's
preserved thinking, so the first turn after a move re-reads the whole conversation — on the
*target* account's quota. A long session moved at the very end of a quota window spends a
slice of the quota it was moved to find. The tool prints this cost block after every move,
and says `same organization: the session's preserved thinking is KEPT.` when the two
logins share one.

## Between machines: `--from-machine`

Run it on the machine the session is going **to**, with the id `csm find --on M` gave you:

```
csm find "<title words>" --on laptop                                  # which session, which account
csm move <id> --from-machine laptop --to work --mirror-cwd --dry-run  # read the plan and the note
csm move <id> --from-machine laptop --to work --mirror-cwd
```

- **The desktop app's sessions are reachable.** The app keeps them in the default home — which
  an accounts file often does not name — and their titles in its own index, which is in no
  transcript.
  `csm find` reads both, so a desktop session is found by its title or by its `local_` id.
- **The source is never stopped.** `--stop-source` is refused across machines: a process over
  there may be driving work this tool cannot see. The plan lists every process the source
  started that is still running, and leaves them alone. Tell the user not to type into the old
  copy, and to archive it in its app once its work is done.
- **The folder may exist only on the source machine.** `--mirror-cwd` copies the **code** to
  the same path here: git-tracked and untracked files, never the ignored ones, each under
  25 MB, with `.git`, so HEAD and the uncommitted edits match. Data stays where it was made.
  Without the flag a missing folder is a refusal, and a folder that already exists here is
  never written into. `--mirror-cwd` without `--from-machine` is refused.
- **A folder with the same meaning but a different spelling is translated** when the
  configuration says how (the machines file and the shared-directory names); otherwise the
  move is refused rather than resumed in the wrong place.
- **Desktop-app tools stay behind** (its side sessions and its own MCP tools), and so does
  anything the session started over there.
- Moving to the **same account** on another machine is allowed: it changes the machine, not
  the quota.

## The move note

**Every move appends one line to the copy** (never to the source, except where the two homes
share one `projects/` tree and the copy *is* the source). It is a hidden user message
(`isMeta`, the shape the CLI uses for its own reminders) chained to the last line of the
conversation, and it tells the resumed session what changed under it: when it moved, from
which account and machine to which, that the original still exists, that references to the
old account above it are stale, where auto-memory is read from, and — on a machine move —
that commands now run here, what the code mirror brought and what it left, what is still
running over there, and to name the machine before touching hardware.

It exists because a resumed session reads its transcript as its own past: every earlier turn
says it is running as one account, in one folder, on one machine, and after a move all three
can be false. Because it is in the transcript it survives a restart, a later move and a
compaction's re-read. `--dry-run` prints it and writes nothing.

## Permission mode

A move never weakens a session. Without a flag the tool resumes in the mode the session was
running in, raised to the target home's `permissions.defaultMode` only when the session
recorded nothing, `default` or `auto`; `plan` and `acceptEdits` are carried as they are,
because those are deliberate choices and a quota move is no reason to undo one. The plan line
`mode <M> (<why>)` names where the choice came from.

Pass `--permission-mode` to choose: `plan`, `default`, `acceptEdits`, `auto`, `dontAsk`,
`bypassPermissions` (`manual` is an alias of `default`). Only ask for `bypassPermissions`
when the user asked for it, and expect the warning below if the target has never accepted it.

After the move the tool reports the mode it **came up in**, or says the mode is
`the mode REQUESTED, not a measurement` and gives the `tmux capture-pane` command to check.
If it came up in a different mode, it says so with a 🛑 and the fix (`csm stop`, then move
again without touching the app's picker). Pass that on — do not claim a mode it did not
measure. Tell the user never to touch the mode picker on a session meant to run unattended:
a Remote Control session cannot be put back into bypass from there.

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
  account's connectors, and no terminal command can attach one. The tool names the connectors
  the conversation **has used** and, separately, the ones it only **mentions**: tell the user
  to enable the same set on the target account at claude.ai/customize/connectors, in a browser
  signed in as that account.
- **MCP sign-ins are per config home.** The tool names the MCP servers the conversation used;
  the fix is `claude mcp login <server>` once in the target home.
- **Plugins, skills, agents, commands and output styles come from the target home.** Enabled
  in a shared settings file is not installed. The conversation arrives intact; those tools do
  not, unless both homes point at one directory. `no INSTALLED plugins` means a session that
  was publishing or deploying loses those tools: say so before the link, and offer an account
  that has them.
- **Auto-memory is per home** unless both resolve to one store. csm never copies memory, in any
  configuration — a copy becomes a second set that drifts. The move note tells the resumed
  session which store it reads.
- **`⚠ <account> is near its limit`** is the meter (5-hour and weekly percent used);
  **`may be out of quota TOO`** is read off the target's own recent sessions, evidence rather
  than a reading. Say either one before the link and offer another account or `--to auto`.
- **`⚠ ONE TRANSCRIPT`**: the two homes' `projects/` are one directory, so the move copies
  nothing and only appends the move note — the moved session resumes the very file the source
  is using. If the source is
  RUNNING, two CLIs then append to one file and their lines interleave: pass `--stop-source`,
  or `csm stop <session>` right after the move. If the source IS the session running the move,
  it keeps writing to that file until it ends, so type to the moved window, not the old one.
  `csm list` flags the rows that are one shared transcript.
- **Bypass consent / "Enable Remote Control?"** never answered in the target home: the window
  may stop on that question.
- **`⚠ UNVERIFIED`**: the credential store could not be asked, so whether that login still
  works is unknown. The move goes ahead on the state file alone; say so. If the window
  connects and then every turn fails, that was why.
- **`csm: CSM_LOGIN_PROBE=…: the credential store was NOT asked`** (on stderr): the login check
  was **not** measured — that variable is the test suite's stand-in for the credential store, and
  something in the environment has it set. Say so, and have it unset before the move is trusted.
- **A transcript nothing has written to for a long time** may be older than the home's
  `cleanupPeriodDays` retention, which prunes transcripts. Mention it; nothing in csm deletes
  one.
- **`note: <account> has no way into this folder on <machine> yet`**: the moved session needs
  none, because csm starts it, but a *new* session the user opens here as that account does.
  Pass on the cure the note prints, if it prints one.

## Stopping a moved session

`csm stop SESSION` ends a session **csm moved** and removes the tmux window it opened. That
window is also what blocks moving the same session to the same account twice, so this is the
unblocker for `a window … already exists`.

- It stops nothing else: the authorisation is csm's own `moved-<id8>` window in the account's
  csm tmux session (`csm-<account>`, or whatever `CSM_TMUX_SESSION` spells it on this install —
  the move plan prints the name), plus, for a running session, a registry row naming that same
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
- A process is signalled only after its identity is proved — the registry's recorded start
  time must match `ps` byte for byte. A `ps` that could not answer is a refusal, not a pass:
  the source is still running, and nothing was proved. Offer to try again.

## "Is anything running in the wrong mode?" `csm modes`

The other half of the mode question: not "move this session" but **"is any live session on
this machine running weaker than this machine says it should?"**. Use it when the user asks
which sessions are stuck in `auto`, whether their permission settings took, or before and
after a restart.

```
csm modes                 # the table: what is weaker, and why
csm modes --json          # every live row, the counts, and coverage
csm modes --check         # ONE line. exit 0 ok · 1 a fault · 3 something could not be read
csm modes --restart-idle  # the plan for the idle ones (it signals nothing)
```

It is the complement of a settings check: a settings file can be right while a worker a
Remote Control server spawned sits in `auto`, because such a worker records the mode the
stored session record holds, not the one its server was started with. What it does that
`csm list` cannot: it reads **every** live registry row, including the ones `list` drops (a
server's pre-created session has a 0-byte transcript); when a transcript records no mode it
reads the mode off the process's own command line; and what it still could not read goes in
`coverage.unread` with a reason, and the exit code is **3** — unknown is never `ok`.

- A **fault** is only a Remote Control worker in a mode such a worker records by accident
  (nothing, `default`, `auto`) while this machine's default is stronger.
- `plan`, `acceptEdits` and anything started in a **terminal** are reported as **info**, never
  faults, and never restarted. An unfamiliar mode is **unknown** and is never judged.
- An `ok:` line that is not the whole truth says so: with a deliberately weaker session it
  reads `no Remote Control worker is weaker than <mode> by accident; N deliberately weaker
  session(s): …` and still exits 0.
- The scope is **this machine**. `csm --machine M modes` for another one.
- `--check` prints one line and nothing else, on either stream, so a scheduled check can match
  its prefix. Do not wrap it in anything that adds output.

🛑 **`--restart-idle --apply` is refused on purpose** while the mode a respawned worker comes
back in is unverified: the dry run prints which idle workers would be SIGTERMed and why each
other row is left alone (never a server, never a session that hosts itself, never this
session, never a busy one, never a pid whose start time does not prove it), and then stops.
**No environment variable can open that gate** — a constant in the file is the only switch, so
a stray variable in a scheduled pass can never stop the user's sessions. Offer the cures that
*are* measured instead: `csm move <id> --to <account> --permission-mode bypassPermissions`,
or ending the session in claude.ai and reopening it.

## "Where is that session?" `csm find`

```
csm find "refactor"             # every config home on this machine, the default one included
csm find 7f3a --on laptop       # ...on another machine, over ssh, read-only
csm find "refactor" --all       # not just the last 21 days
```

It matches an id or prefix (the CLI's uuid or the desktop app's `local_` id), a claude.ai
link, or title text, and it is the only way to see a **desktop-app** session, whose title is
in the app's own index and in no transcript. Two caveats to pass on:

- **The age column is the transcript file's last write, not the last turn.** A dead copy can
  read as minutes old.
- **A move is a copy, so a moved session shows up as two rows** — one per home. That is not a
  duplicate to clean up.

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
through the default `~/.claude` passes the check, with a note. `--cwd DIR` picks the project
the trust and memory rows are measured for, `--account NAME` limits the columns, `--json`
gives the whole table.

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
| `is on no machine` | that account's row names no machine, so it is not a target here: pick another, or the user fixes the accounts file |
| `named, never numbered` | use the account's name or handle |
| `row N is not in the last csm list` | run `csm list` again and use its numbers |
| `matches N sessions` | a move is a copy, so an id can be in two accounts: use the row number, or `--from-account <account>` to name the home to take it from |
| `ALREADY running session` | the target already runs that session: stop it there first, or pick a third account |
| `a window … already exists` | moved there before: `csm stop <session>`, or pick another account |
| `does not exist on <machine> any more` | the session's directory is gone: recreate it, or move another session |
| `pass --mirror-cwd` | the folder is not on this machine: add `--mirror-cwd`, or move a session whose folder is here |
| `a mirror never writes into an existing folder` | the folder is here already: drop `--mirror-cwd` to resume in it, or move that one aside first |
| `--stop-source never stops a process on another machine` | drop the flag; tell the user the original keeps running |
| `--to auto needs a quota meter` | none is configured where `CSM_METERS` points: name the account with `--to <account>` |
| `--to auto found no account … with a fresh quota reading` | every candidate is stale or over a cutoff: show `csm accounts` and ask which account to use |
| `is <owner>'s own session` | that session is the one conversation behind something that keeps answering (a bot, a bridge, a service): a second copy would talk to nobody. Tell that supervisor to change account; it uses `--copy-only` itself |
| `csm did not start <session>` | `stop` only ends csm's own windows, and the refusal lists the ones that do exist: close that session in the app or its own terminal |
| `that process is not the one in the window csm opened` | a `moved-…` window exists but the registry puts that pid elsewhere: stop it from the app |
| `is not a permission mode` | use one of the modes listed in the message |
| `is this machine; drop the flag` | `--machine` names another machine; without it the command already runs here |
| `is not a machine this tool knows` | use one of the names the refusal lists, or `--ssh HOST` for a host the configuration does not know |
| `--apply is refused` (on `modes --restart-idle`) | read the plan and use a move with `--permission-mode`, or end and reopen the session from claude.ai |

## Boundaries

- Run `move` on the machine the session is going to. `csm --machine M …` runs the whole
  command over there instead; `--from-machine M` is what brings a session here.
- Move only the session the user asked about, one per request unless they said otherwise.
- Never stop a process or close a window csm did not start. `--stop-source` and `csm stop` are
  the only stops, and `--stop-source` fires only after the moved session has connected. Never
  reach for a bare `tmux kill-window` or `kill <pid>` instead: csm proves the pid first.
- Never read, print or copy credentials, and never sign an account in on the user's behalf.
- `--copy-only` copies and writes the move note but starts nothing. It is for a program that
  resumes the copy under its own supervision — not for a move the user asked for.
- **To test a move, start a throwaway session yourself** rather than using one of theirs: run
  `claude -p` with `CLAUDE_CONFIG_DIR` pointed at a home, in a scrubbed environment and with
  `< /dev/null` (without it the CLI waits on stdin), then `csm stop` it afterwards and say
  which throwaways are theirs to archive.
