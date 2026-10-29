---
name: move-session
description: "Move a Claude Code session from one of the user's Claude accounts to another with claude-session-mover (csm), keeping the whole conversation. Use when the user says: move this session to another account; move my <title> session to <account>; I'm out of quota, move it to <account>; this account is rate limited, switch accounts; which of my sessions are out of quota; list my sessions across accounts; move it to whichever account has quota left (csm move --to auto). Also when they name an account next to a session, or paste a claude.ai/code/session_… link and ask to run it as another account. Use it too when a session has DIED (csm revive): revive it, restore it, bring it back, continue my dead session, my session died, the remote control disconnected or is offline, it stopped on a limit — a pasted link with nothing answering is a revive, not a move. Use it to SWEEP for them (csm stalled): what's stalled, what's parked, which sessions are stuck or out of quota, which stopped overnight, is anything waiting to be continued, wake everything that's ready, continue them all, did the wake run, is the watchdog running, why wasn't my session woken. Use it too to move a session BETWEEN MACHINES (move my session on the laptop to this machine, bring that desktop-app session over, continue this work on another computer) and to find a session anywhere by title or id (csm find, csm move --from-machine, --mirror-cwd). Use it for: stop the session you moved, close that moved window, clean up after the move; which permission mode is the moved session in, is anything still stuck in auto, did my permission settings take, restart the idle ones in the wrong mode (csm modes); and which of my accounts are set up the same / do my accounts share settings, skills, plugins, memory (csm matrix)."
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
csm revive SESSION [--dry-run] [--json] [--to ACCOUNT|auto] [--new-link] [--say TEXT]
                              [--permission-mode MODE] [--unarchive] [--name LABEL]
                              [--account NAME] [--auto]
csm stalled [--since HOURS] [--json] [--check] # which stopped sessions are ready to continue
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

## Revive a session that died

`csm revive SESSION` is for a session that has **stopped answering**: it hit a usage limit, the machine restarted
under it, Remote Control disconnected, something killed it mid-turn. A move needs a live session; this does not.

```
csm revive <link or title> --dry-run     # why it stopped, and what reviving it would do
csm revive <link or title>               # ...do it
csm revive <link> --to auto              # ...on the account with the most room, when its own has none
csm revive <link> --new-link             # ...fork a dead session onto a new link: a fresh copy, same past
```

1. **Ask for the claude.ai link, and prefer it over every other spec.** A session that stopped has no live row,
   and a Remote Control session usually has no title either — its transcript is named by a uuid that appears in
   nothing the user would type. The link alone finds the file, with nothing running.
2. 🛑 **"No session matches" is never "there is no such session."** `csm find` and `csm list` search ids and
   titles, so 0 rows about a dead session means the search could not see it, not that it is gone. Ask for the
   link and run `csm revive <link>` — never tell the user their session does not exist.
3. **Run `csm revive <spec> --dry-run` first**, unless the case is obvious (the user pasted a link and said "bring
   it back", and the plan has no refusal in it). The dry run starts nothing, prints the row it would take, the note
   it would send, and `🛑 a real revive would be REFUSED: …` when it would be. Read it before answering.
4. **Then run it for real** and read the exit code: `0` it took a turn (or there was nothing to do, or the one
   thing to tap was printed), `1` it is **up** and nothing proved it read the note, `2` nothing was started.
5. **Answer in three lines, then the link, then the title they knew it by.** The tool's own first three lines are
   exactly that answer — what stopped it and when · what was done · the one risk — so pass them on in your own
   words, add the `https://claude.ai/code/session_…` link to open, and name the old title, because a revived
   session is found in the app by the name they remember. On exit 1, say plainly that it is up and nothing
   proved it read the note, and give them the one sentence to type: open the link and say *continue*.

**What it decides** (first match wins, so a session that is both dead and out of quota is answered about the
quota):

| # | when | what it does |
|---|---|---|
| 1 | another program owns the session (a bot, or a scheduled pass) | refuses, naming that owner's own revive command |
| 2 | the transcript holds no conversation | refuses: there is nothing to continue |
| 3 | it is live and busy | nothing to do — it is working right now |
| 4 | the limit it stopped on is still in force, and no `--to` | refuses, with the reset time and the cures: wait, or `--to auto` now |
| 5 | it is live and idle | wakes it: the note is relayed in, nothing is started. A `--to`, a `--new-link` or a `--permission-mode` is **not** carried out — it is still running, so stop it first, and this row starts no process to put in a mode |
| 6 | `--to ACCOUNT` or `--to auto` | moves it (an ordinary move, with its cost), then relays the note into the copy |
| 7 | dead, a self-hosted Remote Control session, no `--new-link` | resumes it in place, on the **same** link. Archived needs `--unarchive` |
| 8 | dead, a terminal session, no `--new-link` | resumes it in place — it gets a **new** link, which is new exposure, not a restoration |
| 9 | dead, a Remote Control **server child**, no `--new-link` and no `--auto` | prints the one thing to tap and starts nothing. With `--auto` it takes row 10 instead, because nobody is reading it |
| 10 | dead, a server child, `--new-link` | forks it: new id, new link, same past; the old link still opens the old copy |
| 11 | dead, a self-hosted or terminal session, `--new-link` | forks it the same way: `--new-link` means a fresh copy on a new link whatever kind it is. A self-hosted session's old link still opens the old copy; a terminal one never had a link, so the warning is about the old **copy** |

The `action` in `--json` names the row: `refuse`, `nothing`, `wake`, `move`, `resume`, `resume-new-link` (8),
`keep-link` (9), `fork` (10 and 11). ⚠️ `resume-new-link` is row 8, a resume in place; the `--new-link` FLAG takes
row 10 or 11, which record `fork`.

**Read `decision.dropped` and `mode.applied` before you say what happened.** A flag that was not carried out is
named there and in the second line — `--to` on a row that is not a move, `--say` on a row that sends no note,
`--new-link` on a row that forks nothing, `--permission-mode` on a row that starts no process — so pass that on
instead of reporting the flag as honoured. `mode.applied: false` means the `mode` shown is the one the session is
**already** running in (measured from its own command line and its transcript, `why` beginning `unchanged:`), not
one csm set: never tell the user their session was put into a mode on a wake, on row 3, on row 9 or on a refusal.

**A dead server child often cannot name its own link, and that is still row 9.** When nothing records which
claude.ai session it was — no registry row, no bridge line in its file, no `bridge-spawn` directory — csm proves
the kind from the id's uuid version alone and asks for the link instead of printing one. Pass that on as it is
written: *paste its claude.ai link*, or `--new-link` to fork it, which needs no link at all. Never offer to
"resume it in place": that would put a second process on an id a later respawn of the old link shares.

**Two refusals to pass on as they are.** When one id sits in two homes and neither is running, revive refuses and
names both — the cure is `--account <handle>`, and it is the same refusal `move` and `stop` give. When two live
sessions in one home carry the same registry name, revive refuses before sending anything, because SendMessage
addresses a session by its name — the cure is `--name <label>` on the revive, or stopping the other.

**Row 9 is the one that needs the user, and it is usually the cheapest answer.** Nothing local can make a Remote
Control server respawn its child — the server does that when the session next gets activity. So tell them: *open
this link and say "continue"*; the server brings the worker back, and they keep the link, the title, the
account and the quota window. Then either they type *continue* themselves, or — once the link is open — run
`csm revive <spec>` again and it takes row 5 and wakes it with the note for them. The zero-tap alternative is
`csm revive <spec> --new-link`, which **forks**: a new id and a new link, the same past, and the old link still
opens the OLD copy. Say that out loud when you use it, and tell them to archive the old one and not to type there.

**Say every time, for a revive**

- **The note is relayed, not typed.** The session is brought up idle and a small headless Claude of csm's own
  sends the note with its SendMessage tool, so the app shows it as a message from **"csm revive (<machine>)"**,
  recorded as a peer message. Nothing is ever written into a transcript, and nothing is typed as if they had typed
  it. `--say TEXT` is the only way to put their own words in, quoted verbatim and attributed to them — at most 400
  characters, and it may not begin `!` or `/`.
- **`--to` makes it a move**, so it costs what a move costs: a new link, the target account's connectors and
  plugins, and across organizations a first turn that re-reads the whole conversation on the new account's quota.
- **A mid-turn stop is the risky one.** When the tool reports that the last tool call has no recorded result, pass
  that on in those words: it may have fully applied, partly applied or not run, and the revived session is told
  the same thing. The other mid-turn wording — *the last prompt has no answer of any kind after it* — is a kill a
  few seconds earlier: there is no call to check, and nothing it may have begun is on disk. Say that instead of
  inventing a tool; the user's own last message is the work.
- **Lost agents.** When the diagnosis names errored agents of a workflow run, say how many and which — that work
  is outstanding whatever the run's own status file claims.
- **It waits for nothing and signals nothing.** A limit still in force is a refusal carrying the local reset time,
  not a wait; `revive` has no stop of any kind; and `--unarchive` is the only way a session that was archived or
  ended from the app is reopened.

## "What's stalled?" and waking them: `csm stalled`, `csm revive --auto`

`csm stalled` is the sweep: every session in every account home here whose transcript was written in the last
48 h, why each stopped, whether it is **due** to be continued, what `csm revive --auto` would do about it, and
whether that has already been done. Reach for it when the user asks what is stalled or parked, which sessions are
stuck or out of quota, which stopped overnight, whether anything is waiting, or whether the thing that wakes them
is working. **It acts on nothing** — no window, no message, no signal.

```
csm stalled                              # the table, with a reason for every row
csm stalled --json                       # the rows, `due` with its reason, and `handled`
csm stalled --check                      # one line: ok: / FAULT: / INCOMPLETE:, exit 0/1/3
csm revive <id> --auto                   # continue ONE of them, as an unattended caller
```

1. **Run `csm stalled` and read the rows out, not the count.** Each row says what stopped it, whether it is due
   and **why or why not** — "waiting does not clear a monthly-spend limit", "daily owns it and it is dead", "it is
   working right now". That sentence is the answer; a bare "3 sessions are stalled" is not.
2. **Due means exactly two things.** A usage limit of a class a reset clears (`session`, `weekly`) whose reset
   plus a margin has passed; or a session killed while working whose process is gone, within 24 h. A
   monthly-spend, credits or model limit is **never** due — waiting does not clear it, so say so and offer
   `csm revive <id> --to auto`, which is the cure. A clean finish is not due either: it answered.
3. **Wake them one at a time, with `csm revive <id> --auto`**, oldest stop first, which is the order `--json`
   gives. Never loop over every due row at once: a sweep that wakes a dozen sessions spends a dozen first turns
   on one account's quota. Say how many you woke and how many you left.
4. **`--auto` changes the note's attribution**, which matters when the user asks what their session was told: it
   says nobody has sent a message since it stopped and that this installation continues stopped sessions
   automatically — **not** that the user asked. `--say TEXT` is still quoted verbatim beside it, when they do
   have something to pass on.
5. 🛑 **`--auto` FORKS a dead Remote Control server child**, where a plain revive would print "open the link and
   say continue" (row 9). There is no unattended way back onto such a session's own link. The fork leaves **two
   conversations with one history**, so `--json`'s `result.old_bridge_id` names the old claude.ai session, which
   has to be **archived** — csm cannot do that itself. Tell the user plainly when this happens: the old link
   still opens the old copy, archive it, do not type there.
   ⚠️ **And read `result.forked`, not the exit code.** The fork is made before the note is relayed, so a relay or
   proof failure comes back as exit 1 with the fork already there: `forked: true` beside `"exit": 1` still means a
   second session exists, still has to be archived, and must **not** be forked again.
6. **`handled` is per STOP, not per session — and the stop, not the id, is the key.** A stop already revived (a
   record with exit 0) is not due again; a session that stopped, was woken and stopped **again** is a new stop and
   is due. Because a fork copies the transcript, the same stop line can end two sessions, and a record for either
   covers both (`handled.copy_of` names which) — otherwise one stop event would be woken once per copy. A row
   whose `handled.failed` is non-zero is a wake that was tried and **failed** — that is what `--check` reports as
   `FAULT:`, and it is worth raising on its own, because the next pass will just try again.
7. **`csm stalled --check` answers "is the waking working?"** `ok:` while nothing has failed, `FAULT:` for a due
   session whose last wake failed, `INCOMPLETE:` when something could not be read. ⚠️ A session merely **being**
   due is not a fault: that is the normal state between two passes, so do not report `ok: 2 session(s) due` as a
   problem.
8. **A row that says "`ps` could not be asked" is a reading nobody could take, not a verdict.** Such a row is
   never due, because with `ps` blind a *running* session reads dead and resuming it would put two CLIs on one
   transcript. Report it as unread — it is in `coverage.unread` too — and look at the session yourself rather
   than waking it.

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
- **Exit 0 with rows, exit 1 when nothing matched.** Exit 1 is never "the search failed": it
  is "nothing matched", and **0 rows is not proof** the session is gone. Never say "no such
  session" on it — ask for the `claude.ai` link, which names the transcript by arithmetic
  with nothing running. A caller that wants rows counts `--json`.

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
| `no transcript for that link here` (`revive`, `move`, `find`) | that link's transcript is in no config home on this machine. It may be on another: `csm find <link> --on <machine>`, then `csm --machine <machine> revive <link>`. 🛑 A link is never matched by part of an id or by a title, because that would answer with somebody else's session — so do not retry it as a title search |
| `has no main-chain line in its transcript` | that id is a session a Remote Control server pre-created and nobody ever used: there is nothing to continue. Ask which session they mean, and for its link |
| `is still inside the <kind> limit it stopped on` | wait until the reset time in the message and run `csm revive` again, or `csm revive <spec> --to auto` now to continue it on an account with room. For a monthly-spend, credits or model limit, waiting does **not** clear it: only `--to`, or lifting the cap |
| `was archived or ended from the app` | somebody closed that session on purpose, or the 7-day sweep did. Ask before reopening it; `--unarchive` resumes it, which unarchives it |
| `is <owner>'s own session` (on `revive`) | run the command the refusal names: that supervisor has a revive of its own, which puts its session back on the same link. Never revive someone else's session yourself |
| `something is running session … NOW` | a server respawned its child while csm was deciding, and nothing was started. Run `csm revive <spec>` again: an idle session is woken, not resumed |
| `is no longer running: its registry row could not be proved` | it went away between the diagnosis and the wake, and nothing was sent. Run `csm revive <spec>` again — a dead session is resumed or forked, not woken |
| `another revive of session … is in flight` | one revive of one session at a time. Wait for the other one; a stale lock clears itself after 120 s |
| `--say is N characters and the limit is 400` | pass less: it is quoted verbatim into the user's own session, so it is refused rather than shortened |
| `--say` starts with `!` or `/` | reword it — a delivered message beginning with either is run as a command, and a leading space does not help (the CLI strips it) |
| `--from-machine is not built for revive` | run the whole thing over there: `csm --machine <machine> revive <spec>` (add `--dry-run` first). Every gate a revive turns on is a question about the machine the transcript is on |
| `revive has no action for a <kind> session in the same account` | name where to put it: `csm revive <spec> --to <account>` |
| `is this machine; drop the flag` | `--machine` names another machine; without it the command already runs here |
| `is not a machine this tool knows` | use one of the names the refusal lists, or `--ssh HOST` for a host the configuration does not know |
| `--apply is refused` (on `modes --restart-idle`) | read the plan and use a move with `--permission-mode`, or end and reopen the session from claude.ai |

## Boundaries

- Run `move` on the machine the session is going to. `csm --machine M …` runs the whole
  command over there instead; `--from-machine M` is what brings a session here.
- Move only the session the user asked about, one per request unless they said otherwise. The same for a revive:
  one session per request, and never revive a session the user did not name — a revived session starts spending
  quota and may act on work they have moved on from. `csm stalled` names them all, which is a reading and not a
  mandate: when they ask you to wake "everything that's ready", wake a handful and say what you left.
- `--auto` is for a run with **nobody watching**. Typing it yourself while they are reading your answer puts a
  sentence in their session that says nobody asked — so use it only when they want the unattended behaviour
  (a scheduled pass, or forking a dead server child without being asked for the tap).
- `revive` never stops, signals or archives anything, and never writes into a transcript. If something has to be
  ended, that is `csm stop` on a window csm opened, and it is a separate request.
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
