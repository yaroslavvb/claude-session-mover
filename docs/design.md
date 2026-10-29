# Claude Session Mover: design and implementation

Version 0.6.2 · code **[github.com/yaroslavvb/claude-session-mover](https://github.com/yaroslavvb/claude-session-mover)**
(MIT, one Python file, standard library only).

Everything here is Claude Code's own **undocumented on-disk state**. It has already changed inside one minor
series, so every claim below is stamped with the CLI release it was measured on — 2.1.296 to 2.1.300, on macOS,
and 2.1.312 for everything [`revive`](#revive) reads and does — and the ones that matter most come with a recipe
for re-measuring them on your own build ([Measured facts](#measured)).

One of your Claude accounts hits its usage limit while your other accounts have quota left. The usual answer is
to start the work again in another account and lose the conversation. Claude Session Mover moves the conversation
instead: it copies the session's transcript into the other account's config home and resumes it there. The agent
still knows everything that was said, and every turn from then on spends the new account's quota. Nothing is
deleted from the old account.

🛑 **A move is between two config homes, and by default both are on THIS machine.** A transcript lives under
`<home>/projects/`, which is per machine, and `--resume` looks only inside the home it is running under. Two
different flags involve a second machine, and mixing them up is the common mistake:

- **`--machine M`** (or `--ssh HOST`) runs the same command *on* that machine, where it again moves between two
  homes there. Nothing crosses, and the row numbers it prints are that machine's.
- **`move <id> --from-machine M`** brings a session *from* M *to here*: it is found over there in every config
  home, fetched over ssh, staged, and resumed in a home on this machine ([below](#between-machines)). The source
  is never stopped, and `--mirror-cwd` brings its code when the folder is not here.

<a id="contents"></a>

## Contents

- [Quick start](#quick-start)
- [The idea in one picture](#picture)
- [What a move does, step by step](#steps)
- [Accounts: discovered, named, never numbered](#accounts)
- [Picking a session](#picking)
- [`--to auto`: the account with the most room](#auto)
- [The move note: telling the session it moved](#note)
- [A session another program owns](#owned)
- [Between machines: `find`, `--from-machine`, `--mirror-cwd`](#between-machines)
- [`csm modes`: the permission sweep](#modes)
- [Choosing the permission mode](#mode)
- [Answering a dialog nobody is there to answer](#dialogs)
- [Proving a process before signalling it](#proof)
- [Is this home really signed in?](#login)
- [What the target home cannot do: the notes](#notes)
- [Auto-memory is never copied](#memory)
- [What a move costs](#cost)
- [Revive: bringing back a session that stopped](#revive)
- [`csm stalled`: the unattended sweep](#stalled)
- [`csm stop`: ending what csm started](#stop)
- [`csm matrix`: measuring your own setup](#matrix)
- [What is on disk: the formats it reads](#formats)
- [Measured facts, and how to re-measure them](#measured)
- [Safety rules](#safety)
- [Limits](#limits)
- [Environment knobs](#env)
- [From a phone](#phone)
- [Why move rather than pool](#why-move)
- [Lessons carried into 0.2.0](#lessons)
- [Repository and tests](#layout)

<a id="quick-start"></a>

## Quick start

```
git clone https://github.com/yaroslavvb/claude-session-mover
cd claude-session-mover && ./install.sh          # links claude-session-mover and csm into ~/.local/bin

csm accounts                                      # the config homes found here, and who is signed in
csm matrix                                        # what those homes share, and what is per account
csm list                                          # recent sessions across every account, newest first
csm move 3 --to work --dry-run                    # print the plan and any refusal, change nothing
csm move 3 --to work --stop-source                # move row 3 to the account named "work"
csm move 3 --to auto                              # ...or to whichever account has the most room left
csm revive <claude.ai link> --dry-run             # it stopped answering: why, and what would bring it back
csm revive <claude.ai link>                       # ...wake it, resume it, fork it, or move it
csm stop 3                                        # end a session csm moved, and free its window
csm modes --check                                 # one line: is any live session weaker than the default
csm find "refactor" --on laptop                   # where is that session, here or on another machine
csm move 7f3a --from-machine laptop --to work     # bring it here, onto that account
```

Requirements: Python 3.7 or newer, Claude Code, and tmux for the default Remote Control mode.

Each account needs its own config home: a directory you point `CLAUDE_CONFIG_DIR` at and sign in once
(`CLAUDE_CONFIG_DIR=~/.claude-work claude`, then `/login`). Making several homes behave like one setup is
[docs/setup.md](setup.md); what can and cannot be shared at all is [docs/fungibility-matrix.md](fungibility-matrix.md).

<a id="picture"></a>

## The idea in one picture

```
 account A (out of quota)                           account B (has quota)
 ~/.claude-a/                                       ~/.claude-b/
   projects/<folder>/<id>.jsonl   ── copy ──────▶     projects/<folder>/<id>.jsonl
   projects/<folder>/<id>/        ── copy ──────▶     projects/<folder>/<id>/
   file-history/<id>/  (+ tasks/)  ─ copy ──▶     file-history/<id>/  (+ tasks/)
   .claude.json   (untouched)                         .claude.json  + trust <cwd>, onboarding done
   sessions/<pid>.json → live pid                     ▲
                                                      │ tmux window "moved-<id8>" in session "csm-b":
                                                      │ CLAUDE_CONFIG_DIR=~/.claude-b
                                                      │ claude --resume <id> --remote-control=<title>
                                                      │        --permission-mode <the mode csm CHOSE>
                                                      ▼
                                       a NEW claude.ai session owned by account B:
                                       https://claude.ai/code/session_…
```

A Claude Code session on disk is one append-only JSONL file plus an optional sibling directory. The account is
not part of what makes it resumable; it is whichever login the process runs under. So a move is a copy and a
resume, and everything else in the tool makes that copy safe and the resume unattended.

<a id="steps"></a>

## What a move does, step by step

1. **Find the session.** Scan every account home's `projects/*/*.jsonl` and the live registry `sessions/<pid>.json`.
   Each file costs two seeks: a 96 KB head and a 384 KB tail, never a full parse. Pick the one you named
   ([ladder below](#picking)). With `--from-machine M` the same scan runs on that machine instead, over ssh,
   and the transcript is fetched into the staging directory first ([below](#between-machines)).
2. **Choose the permission mode** ([below](#mode)) — it is chosen, not copied — and compute the target notes
   ([below](#notes)) against that mode.
3. **Refuse early.** Every check runs before the first byte is written, and each refusal names what to do
   instead. It refuses:
   - the same account as the source;
   - a target with no login, the wrong login (an accounts-file `expected email` that does not match), the same
     login as the source, or a login whose credential is **gone** ([below](#login));
   - a working directory that no longer exists, or a `claude` that is not on `PATH`;
   - a destination transcript that is live in the target;
   - the same session id already sitting in a DIFFERENT project folder of the target home. The CLI's resume
     resolution looks in the cwd's own folder, then sibling worktrees, then scans every folder for
     `<id>.jsonl` and takes the hit **only when exactly one file matches** — so a copy left behind by an
     earlier move out of a third account would make `--resume` ambiguous, and the window would die after the
     state file had already been written;
   - **either of the two questions above being unanswerable.** A `sessions/` directory or a project folder
     this process may not read makes "is something running the destination" and "is there a second copy of
     this id" unknown, not *no* — and both are read through calls that raise rather than shrug (`os.listdir`
     and a stat per folder, never `pathlib`'s `glob`, whose scan swallows a `PermissionError` and yields
     nothing). Each is its own refusal, naming the directory, because what cannot be ruled out is two CLIs
     appending to one transcript. Same rule as the login check: *could not look* is never a verdict;
   - an existing `moved-<id8>` window — with `csm stop <session>` named as the fix;
   - a target account whose accounts-file row names **no machine**: it is listed so the refusal can name it,
     rather than answering "no such account" about a row the file plainly holds;
   - a session another program **owns** ([below](#owned)), before the target is even resolved;
   - and, across machines: `--stop-source` (never a process over there), `--mirror-cwd` without
     `--from-machine`, a folder that is neither here nor mirrorable, and a mirror onto a folder that already
     exists here.

   Under `--dry-run` these are printed as "a real move would be REFUSED", not raised.
4. **Copy.** The transcript goes to `<target home>/projects/<the source's own folder name>/`, with:
   - its sibling `<id>/` directory (subagent transcripts, tool results, workflows);
   - the session's own side data outside `projects/` — `file-history/<id>/` (what `/rewind` restores from),
     plus `tasks/<id>/` and the older `todos/<id>*.json` where a build keeps them — copied **additively, never
     overwriting**;
   - never the project's `memory/`, in any configuration ([below](#memory)).

   A quiet file already at the destination is backed up to `<name>.csm-bak-<epoch>` first. The source is never
   edited or deleted. Nothing else travels: `sessions/`, `session-env/`, `shell-snapshots/`, `jobs/`,
   `bridge-pointer.json`, `.claude.json` and every credential stay where they are.
5. **Pre-answer the first-run dialogs** in the target's state file, under the CLI's own `.claude.json.lock`,
   additively, atomically, with a backup (`.claude.json.csm-bak-<epoch>`) and the file's own mode. The file is
   re-read **inside** the lock and only the two keys csm owns are merged in, because the target home is not idle
   just because this session is not in it: the CLI writes that file at startup and at the end of every turn, and
   a read-modify-replace that ignores the lock loses whichever write lands second — either the CLI's update, or
   the trust key csm just wrote, in which case the moved window stops on the dialog the move pre-answered. A lock
   that cannot be taken within `CSM_LOCK_WAIT` seconds is a printed warning, never a refusal (an unattended move
   must not die on another session's lock), and a lock older than two minutes is treated as abandoned. The keys:
   - the workspace-trust dialog for that directory (`projects[<cwd>].hasTrustDialogAccepted`);
   - onboarding (`hasCompletedOnboarding`, plus a `theme` if none is set).

   A home that has never run interactively in that directory stops on both, and in a detached window nobody is
   there to answer. ⚠️ A home that has **already** answered both for that directory produces an empty to-do list
   and its state file is not opened for writing at all: a warm home is left exactly as it was, and no preference
   is invented for it. (On 2.1.300 `theme` is a *settings.json* key — the state-file key is vestigial, and
   `hasCompletedOnboarding` is the one that suppresses the picker.)
6. **Append the move note** to the copy — one hidden `isMeta` line, chained by `parentUuid` to the last real
   line of the conversation, saying what changed under this session and what above it is now stale
   ([below](#note)). It is written to the copy only, and under one shared `projects/` tree, where the copy IS the
   source, to that one file. `--dry-run` prints it; `--copy-only` stops here.
7. **Launch under the target login.** A detached tmux window `moved-<first 8 of id>` in session `csm-<account>`
   runs the tool's own `__run <plan.json>`. That sets the target's `CLAUDE_CONFIG_DIR`, or *unsets* it for the
   default home, scrubs the environment ([below](#safety)), restores `PATH`, and runs:
   ```
   claude --remote-control=<title, moved from A> --permission-mode <the chosen mode>
          --model <its model> --resume <id>
   ```
   in the session's recorded working directory. The hand-off goes through a file because a tmux window starts
   with the tmux *server's* environment, whatever that was when the server started. The interpreter and the
   script are spelled absolutely; the plan file is mode 0600 and is deleted by `__run` as it reads it.
8. **Wait for proof.** The tool watches the pane (`capture-pane -p -J`, so a wrapped link is whole) for
   `https://claude.ai/code/session_…`, up to 150 s, polling every 3 s. A dialog on the screen is answered by
   reading its focus marker ([below](#dialogs)), at most one key per poll. The wait ends early when the window
   prints `__run`'s exit banner, so a refused model or a dead login fails in a second with the reason in the pane.
9. **Report what actually happened.** The success block prints the new claude.ai link, the mode the session
   **came up in** versus the mode that was asked for ([below](#mode)), what the move cost ([below](#cost)), and
   any target note that still applies.
10. **Optionally stop the source** (`--stop-source`). Only after the link has appeared, only once the pid has been
   **proved** to be the same process the registry wrote down ([below](#proof)), and never when the source is the
   session running the tool. A move that did not connect leaves the source running: two copies is bad, nothing
   running is worse.

Three other modes:

- `--no-remote-control` starts the window as a plain interactive session to `tmux attach` to; the proof is that
  it is still running after a few seconds. `--stop-source` is refused here — without the link there is no proof.
- `--copy-only` does every refusal, the first-run gates, the copy and the note, and starts **nothing**: for a
  program that resumes the copy itself, under its own supervision. `--stop-source`, `--foreground` and
  `--no-remote-control` are refused with it, because there is no window to prove and nothing to stop.
- `--foreground` skips tmux and replaces the tool with the resumed session in your terminal. It is refused inside
  Claude Code, where there is no terminal to give it.

Exit codes: `0` done, `1` it started but did not connect (or a window could not be removed), `2` a refusal.

<a id="accounts"></a>

## Accounts: discovered, named, never numbered

An **account** here is a config home: the directory Claude Code keeps its login state, settings and transcripts in.

- **Discovery.** `~/.claude` is the account `default`, every `~/.claude-<name>` directory is the account
  `<name>`, and the home in `$CLAUDE_CONFIG_DIR` is added if it is elsewhere.
- **An accounts file** (`~/.config/claude-session-mover/accounts`, or `$CSM_ACCOUNTS`) replaces discovery
  entirely, in either of two dialects, chosen per line. **Simple**: `name  home  [expected-email]`,
  whitespace-separated, with `-` for the default home. **Table**: tab-separated, with the columns taken by name
  from a commented header line when there is one and otherwise by position — 1 name, 2 email, 3 home,
  6 machines, 7 handle — so a file some other tool already owns can be read where it is, extra columns and all,
  instead of being copied into a second table that goes stale the day an account is added. A file that mixes the
  dialects, or repeats a name or a handle, is refused naming the line. With an expected email, a home signed in as
  anyone else is refused, because the move would spend the wrong quota.
- **`handle`** is a short alias that resolves wherever the name does, and is what every listing and message
  prints. Its shape is enforced where it is read, not assumed — one lower-case `[a-z0-9-]` token, never all
  digits, never leading-hyphen — because `resolve` has an exact rung for it: an all-digit handle would make
  `--to 2` resolve to an account while a bare number is otherwise refused, and a leading hyphen reads as a flag.
  A row whose handle breaks the shape is dropped with a line in the log, never on stderr.
- **`machines`** says which machines an account is on, matched against `CSM_MACHINE` (the short hostname by
  default). A row for another machine is not listed here; a row that names **no** machine is listed but refused as
  a target, so the refusal can name it rather than answer "no such account" about a row the file plainly holds.
  ⚠️ A file whose `machines` column names this machine nowhere lists **every** account rather than none: an
  unrecognised machine name must not read as "nothing is here", which is what makes a hostname an acceptable
  default at all.
- 🛑 **`home` in a table may not be `-`, `default` or `~/.claude`.** Those are three different things — see the
  default home below — and in a table, where the same file is read on several machines, a row that wants the
  default home is a row that wants a home of its own. The simple dialect keeps `-`, where there is one home and it
  is unambiguous.
- **Who is signed in** is read from the home's state file, `oauthAccount.emailAddress`, and then checked against
  the *existence* of its credential ([below](#login)). The tool never reads, prints, logs or copies a credential
  value. Two homes signed in to the same login and organisation are the same account for quota purposes, so a
  move between them is refused.
- **The default home is special.** With `CLAUDE_CONFIG_DIR` unset, the CLI keeps its state file at
  `~/.claude.json` (outside the directory) and uses the bare `Claude Code-credentials` Keychain item. Setting
  `CLAUDE_CONFIG_DIR=~/.claude` is not the same account: the state file moves inside the directory and the
  Keychain item becomes `Claude Code-credentials-<8 hex>`, which is empty, so it reads as signed out. A move into
  `default` therefore **unsets** the variable rather than spelling the path.
- **Naming ladder** for `--to`, first unique match wins: exact name, exact email, exact handle, unique prefix of a
  name or handle, unique substring of a name, handle or email. Anything ambiguous is refused with the candidates
  listed. **A bare number is refused** unless it is literally an account's name: a position in a list changes
  whenever an account is added or removed, so it cannot be trusted to mean the same account twice.

<a id="picking"></a>

## Picking a session

`SESSION` is tried against these, first unique win, and more than one match is listed, never guessed:

1. a row number from the last `csm list` on this machine (saved, so `move 3` means the row you just read; an
   all-digit argument is always a row number);
2. an exact local session id, then a unique prefix of one (4+ characters);
3. a `claude.ai/code/session_…` link, or a bare `cse_…` / `session_…` id;
4. a unique, case-insensitive piece of the title.

**A move is a copy, so after one move the same id exists in two accounts**, with the same title. When an id or
title matches several rows, the single live one wins; two live copies, or none, is a refusal that lists the row
numbers. `csm stop` narrows the same ladder to the rows that have a window csm opened before falling back to the
full list, so after a move `csm stop <id>` means the copy csm started, not the original.

Titles come from the transcript in this order: `custom-title` (a name you gave it), `ai-title`, `last-prompt`,
then the first real user message. With no custom title the name can therefore change a turn later — hand over the
**link**, not the title.

**How long the listing is.** The default is 20 rows, and the default never cuts a live session: "move my *running*
session" is the common ask, and that session can be the oldest file in the home. `--all` raises the ceiling to 300.
An explicit **`--limit N` is a hard cap** instead — at most N rows, the N newest, live or not — and it outranks
both `--all` and a session pinned by its full id, because `move 3` is numbered against the table that was printed:
a cap that quietly kept extra rows would renumber the thing the next command names. The table says how many rows it
left out. Why it exists at all: a machine running many Remote Control workers has that many live sessions, and an
uncapped listing is pages long on a phone — which the default already handles, so `--limit` is only for "shorter
than that".

<a id="auto"></a>

## `--to auto`: the account with the most room

`--to auto` reads a **meter** — a JSON file written by whatever tool you point `CSM_METERS` at, one entry per
account name or handle with `five_hour` and `seven_day` as percent *used* and `at` as the time of the reading
(through the same epoch normaliser as everything else, so milliseconds survive). Nothing here asks the network.

Among the accounts this machine has, `auto` takes those with a **fresh** reading (under `CSM_METER_MAX_AGE`, three
hours by default) under both cutoffs (`CSM_AUTO_MAX_5H` 90 %, `CSM_AUTO_MAX_7D` 95 %) and a usable login, and picks
the lowest weekly percentage; the 5-hour percentage and then the file's own order break a tie. It prints the
account it chose and its numbers, because a silent choice cannot be checked.

🛑 **Unread is never room.** No meter, a reading carrying an `error`, percentages that are not numbers, a reading
older than the maximum age: each of those leaves the account *unread*, which is not *free*, so `auto` passes over
it rather than hoping. (An account at or over a cutoff is the other case — read, and too busy.) With no meter at
all `auto` refuses, naming the knob and `--to <account>`: a guess here is a move into a second exhausted account,
which looks exactly like a success, because the window connects and prints a link and only then does every turn
fail.

🛑 **The source account is identified field-wise — name, then login, then label — never by name alone.** A
`--from-machine` source is a *synthesised* account whose name is `<machine>:<config home>` by construction, so it
can never equal a target's name; comparing names therefore matched nothing on a cross-machine move, and `auto`
could hand the session straight back to the account it was already running as. An empty string never matches, so
two rows that both record no email are not thereby the same account.

A **named** target gets the same two cutoffs as a warning rather than a choice: when the meter is configured, fresh
and at or over one of them, the plan says `⚠ <account> is near its limit: …` with the numbers. Otherwise it falls
back to the older evidence — a usage limit still in force in the target's own recent transcripts. A reading is a
*reading*, a transcript is *evidence*, and a stale reading is neither; all of it is a warning, never a refusal.

<a id="note"></a>

## The move note: telling the session it moved

A resumed session reads its transcript as **its own past**. Every earlier turn says it is running as one account,
in one folder, on one machine, and after a move all three can be false — measured on the first cross-machine move:
the session resumed here and went looking for a process it had started on the other machine, and the CLI's own
resume banner told it that seven background tasks "didn't finish", when in fact they were still running over there.

So every move appends **one line to the copy** (and only to the copy — except under one shared `projects/` tree,
where the copy *is* the source and that one file is the only place the resumed session could read it). It is a
hidden user message: `"isMeta": true`, wrapped in `<system-reminder>`, chained by `parentUuid` to the last real
line of the conversation, which is how the CLI writes its own caveats. It states:

- when the session moved, from which account and machine to which, and that the original still exists;
- that references above it to the old account are stale, and that an account change across organizations dropped
  the earlier thinking;
- where auto-memory for this project is read from, when a store can be resolved — the store's own announcement is
  made when a session *starts*, so a resumed session never sees it;
- on a cross-machine move: that commands now run here, that the other machine's devices, files and jobs are
  reached over ssh, what the code mirror brought and what it left, what the source started that is still running,
  and that the desktop app's own tools stayed behind.

It ends by asking the session to name the machine before touching hardware, and it says nothing else about what to
do: a system reminder is read as an instruction from the user, and nobody asked for one. Because it is in the
transcript it survives a restart, a later move and a compaction's re-read. `--dry-run` prints it and writes nothing.

<a id="owned"></a>

## A session another program owns

Some sessions are a **front door, not a conversation**: one persistent session with something in front of it that
keeps answering on its own — a chat bridge, a bot, a service. Moving one the ordinary way starts a second copy in a
`moved-…` window that nothing is talking to, while the thing holding the channel keeps answering on the **old**
account. The move reports success and changes nothing that was asked for.

So a plain `move` of such a session is refused before the target is even resolved. `CSM_BOTS_DIR` is a directory of
`<name>.json` files, each carrying the `session_id` it owns; the refusal names the owner, and the way through is
for that supervisor to change account itself — it stops its session, calls `move … --copy-only`, and resumes the
copy under its own supervision. With no such directory nothing is owned, and an installation without a supervisor
never meets this at all.

🛑 **A directory that cannot be read is a refusal, not a "no".** Answering "nobody owns it" there would open the
guard silently and start exactly the second copy this check exists to prevent — the worst outcome, reached by the
quietest path. (One unreadable *file* inside it is skipped instead: a half-written state file is not a claim.) It
is read with `os.listdir` for the same reason the permission sweep is: `pathlib`'s `glob` swallows a
`PermissionError` from its own scan and yields nothing, so an `except OSError` around a glob is dead code.

<a id="between-machines"></a>

## Between machines: `find`, `--from-machine`, `--mirror-cwd`

**Finding.** `csm find TEXT [--on M]` searches **every** `~/.claude*` home on a machine, the default one included —
which is where the desktop app keeps its sessions, and which an accounts file often does not name — and the desktop
app's own session index (`CSM_DESKTOP_INDEX`), where the title of such a session lives; the transcript has none.
With `--on M` the search runs over there by piping a self-contained, standard-library-only helper to its system python
(`CSM_REMOTE_PYTHON`), so **nothing has to be installed on the far side** and nothing of this file crosses. The
helper is annotation-free and f-string-free on purpose: it can land on any machine's `/usr/bin/python3`. It is
read-only, it is run with `-I` so no module beside it can be imported, and it reads `CSM_DESKTOP_INDEX` from *its
own* environment, because that path is that machine's spelling and an override set here would be wrong there.

Two honest labels on the result: the **age is the transcript file's last write**, not the last turn, so a dead copy
can read as minutes old; and a move is a copy, so **a moved session is two rows**, one per home.

**Bringing one here.** `move <id> --from-machine M` fetches the transcript and its sibling directory in one `tar`
pipe over ssh into `CSM_IMPORTS` — never into anybody's `projects/`, because a stray `<id>.jsonl` there is exactly
what makes `--resume <id>` ambiguous, and because a leftover staging file is deleted before the fetch, so a
`projects/` there would make that the one delete this tool promises not to make; a value resolving inside one is
refused — and the staged copy stays as the record of what crossed. From there the move
is the ordinary one. The source account is synthesised from what the helper read over there, so the plan can name
it; its `home` is a path on the *other* machine and is never read as a local one. Moving to the **same** account on
another machine is a real move: it changes the machine, not the quota.

🛑 **The source is never stopped.** `--stop-source` is refused across machines: a process over there may be driving
work this tool cannot see — a build, a device, a job whose grandchild is loading that machine's cores. The plan
lists every process the source started that is still running, and leaves them alone.

**Folder translation.** The same project usually has a different absolute path on each machine. `CSM_MACHINES` is a
JSON file of per-machine roots (`{"<machine>": {"home": "…", "<label>": "…"}}`; only absolute string values are
roots, so anything else in the file is ignored and a file some other tool owns can be read as it is), and the rules
are tried in this order: each root label present on **both** machines, longest origin prefix first; then each name
in `CSM_SYNC_DIRS`, mapping `<origin home>/<name>` to the **realpath** of `<here home>/<name>`; then origin home to
this home. The named roots come first because one of them is usually a sync client's real path, which `home` would
otherwise capture through its symlink spelling. The sync rule exists because a transcript records the symlink
spelling that no named root ever matches. The origin's home is read from `CSM_MACHINES`, or, for a machine it does
not name, from everything before `/.claude` in the transcript's own path over there.

A translation that would return the path unchanged counts as *no rule* — which matters where two machines spell
`$HOME` identically: the folder is then simply looked for here, and `preflight`'s "that directory does not exist
any more" refusal is what catches an absent one, rather than a silent resume in the wrong place.

**`--mirror-cwd`** copies the session's **code** when the folder is not here: git-tracked and untracked files, never
the ignored ones, each under `CSM_MIRROR_FILE_MAX` (25 MB) except under `.git/`, and the whole mirror under
`CSM_MIRROR_TOTAL_MAX` (2 GB) or it is refused. `.git` comes too, so HEAD and the uncommitted edits match. Data
stays where it was made: a recording, a model or a database belongs on the machine that made it. A folder that
already exists here is never written into, and `--mirror-cwd` without `--from-machine` is refused. One asymmetry is
handled rather than inherited: a clone made where an ssh key exists carries a `git@github.com:` remote, and a
machine whose git talks to GitHub over https cannot push it. When the mirror's remote is that spelling **and** this
machine's `ssh -T git@github.com` does not authenticate, the mirror alone gets `url.https://github.com/.insteadOf
git@github.com:` in its **own** `.git/config` — the remote URL still reads the same, and no other repository on
either machine is touched.

<a id="modes"></a>

## `csm modes`: the permission sweep

The complement of a settings check. A settings file can be correct while a live session runs weaker than it says,
because a worker a Remote Control server spawned records **the mode the stored session record holds**, not the one
its server was launched with — the same mechanism as [choosing the permission mode](#mode), seen from the other
end. A check that reads the file reports green over a machine full of sessions in `auto`.

`csm modes` lists every live session in every config home here with the mode it is really in, and judges it against
this machine's `permissions.defaultMode` — read from `CSM_SHARED_HOME` first, so one shared `settings.json` answers
for every account at once, and then from each account home, so a home whose symlink has been replaced still reports
its own drift.

| verdict | what it is |
|---|---|
| `fault` | a Remote Control **worker** in a mode such a worker records by accident — nothing, `default`, `auto` — while the machine's default is stronger |
| `info` | weaker on purpose: `plan`, `acceptEdits`, or any session started in a terminal. Never restarted |
| `unknown` | a mode nothing could measure, or one the tool does not know. Never `ok` |
| `ok` | at the machine's default or stronger |

It reads **every** live registry row, including the ones `csm list` drops — a server's pre-created session has a
0-byte transcript — and where a transcript records no mode it reads the mode off the process's own command line,
which is a measurement rather than a guess. What it still could not read goes in `coverage.unread` with a reason.
That command line comes from one `ps` for the whole machine, so `coverage.ps` says whether that one prover answered
at all: every `unread` reason turns on it, and a non-zero `ps` is "could not be asked", never "nothing is running".

**`--check` is a contract**, because scheduled checks match it by prefix: exactly **one line on stdout and nothing
on stderr**, and the exit code agrees with the prefix — `ok:` 0, `FAULT:` 1, `INCOMPLETE:` 3 (nothing was found
weaker, but something could not be read). Every diagnostic on that path goes to the log instead, the credential
probe is not run there, and an `ok:` line that is not the whole truth says so: with a deliberately weaker session
it reads `no Remote Control worker is weaker than <mode> by accident; N deliberately weaker session(s): …`.

⚠️ Two measured traps live in the reading itself. `pathlib`'s `glob` **swallows** a `PermissionError` from its own
directory scan and yields nothing, so an `except OSError` around a glob is dead code and a locked-out home reads as
an empty one; the sweep uses `os.listdir`, which raises and is therefore reported. And the other half of that:
a home with no `sessions/` directory must stay a quiet **zero**, not an unread home, or one quiet home turns every
`--check` on the machine into a permanent `INCOMPLETE:` — which a scheduled check reads as a fault about the
machine.

🛑 **`--restart-idle --apply` is gated.** The dry run prints which idle workers a restart would `SIGTERM` to bring
them back in their server's mode, and why each other row is refused: never a server, never a session that hosts
itself, never the session running the command, never a busy one, never a pid whose recorded start time does not
prove it. `--apply` then refuses and signals nothing, because only half of what it needs is measured: a claude.ai
session whose local worker is gone **is** respawned on the next message, but the **mode** it comes back in is not
established, and a respawn that lands in `default` leaves an unattended session asking and waiting forever.
**There is no environment variable that opens the gate** — a constant in the file is the only switch, so a stray
variable in a scheduled pass's environment can never make this stop your sessions. The experiment that would settle
it is written out beside that constant.

<a id="mode"></a>

## Choosing the permission mode

v0.1.0 copied the mode out of the transcript. That is wrong for exactly the sessions people move.

A worker spawned by a Remote Control server records **the mode the claude.ai session record holds**, not the mode
its server was launched with: a session that had been running unattended can record `auto`. Pass that through and
the move hands back a weaker session than the one that was running — and a Remote Control session cannot be put
back into `bypassPermissions` from the picker afterwards. So the mode is **chosen** (`resolve_mode`):

1. an explicit `--permission-mode` wins, after validation. The modes, weakest to strongest, are
   `plan, default, acceptEdits, auto, dontAsk, bypassPermissions`; `manual` is the settings schema's own alias
   for `default`. An unknown value is a refusal that names them (exit 2).
2. else, the **target home's** `permissions.defaultMode` wins **only** when it is stronger *and* the transcript
   recorded nothing, `default` or `auto` — the modes a session records by accident. The setting is read from the
   target's `settings.json` with `settings.local.json` over it, through symlinks, so homes that share one settings
   file all answer the same.
3. else the recorded mode, even when the settings are stronger: `plan` and `acceptEdits` are deliberate
   constraints (shift+tab, or a flag) and a quota move must not hand back a session that may now write and run
   anything unasked.
4. else the settings' mode, else `default`.

A move **never weakens** a session, and a mode this tool has never heard of is carried through untouched rather
than ranked as "weakest" — a CLI that gains a mode must not be downgraded by a tool one release behind. The plan
line names the mode *and where it came from*.

**Then it checks.** `came_up_as` reports what the moved session actually came up in, from two sources, the
stronger first:

- the `permissionMode` the resumed session appended to the transcript **past the byte count the copy ended at** —
  the copy already contains every mode the source ever recorded, so only bytes written after the copy say
  anything. The CLI writes that line with the first prompt, so right after a move there is usually nothing yet;
- else the window's own footer literal (`⏵⏵ bypass permissions on`, `accept edits on`, `plan mode on`,
  `auto mode on`, and `⏸ manual mode on` — the footer's name for `default`, measured on 2.1.301. There is no
  footer for `dontAsk`, so a pane showing none of these says nothing about the mode). The `default` literal
  matters: without it, the one downgrade this block exists to catch — bypass asked for, `default` delivered —
  is invisible in the pane.

If the two differ, the success block says so loudly, with the reason (claude.ai restores a mode it holds on the
session's record over the flag) and the fix (`csm stop`, move again, leave the picker alone). If neither source
answered, it says `the mode REQUESTED, not a measurement` and prints the `capture-pane` command to check by hand.
Both the asked-for and the came-up-in mode go into the log line.

⚠️ Two related CLI behaviours, measured on 2.1.300: `permissions.disableAutoMode` (an enum whose only legal value
is `"disable"`) removes `auto` from the modes a session can enter, so a session that was in `auto` cannot come up
in `auto` on a home that disables it; and a `bypassPermissions` start in a home that has not accepted the bypass
disclaimer is silently downgraded to `default`, which is why that consent gets its own target note.

<a id="dialogs"></a>

## Answering a dialog nobody is there to answer

The state-file pre-answers make trust and onboarding unreachable in the normal case. The keystroke answerer is the
belt and braces — and in v0.1.0 it was dangerous.

**Measured on 2.1.299 and 2.1.300** — a pane read with `capture-pane -p -J`, and the dialog's own construction
in the bundle, which the 2.1.296 bundle shares: the trust, bypass and Remote Control dialogs are built
`hideIndexes: true, cancelFirst: true, focus: "cancel"`. The cancelling option is drawn **first**, holds the
focus, and **no option numbers appear at all**. Verbatim from a pane:

```
Quick safety check: Is this a project you created or one you trust?
❯ No, exit
  Yes, I trust this folder
Enter to confirm · Esc to cancel
```

So v0.1.0's rule — "answer by the option's number, and if it is still there press Enter" — typed a stray
character that matched nothing and then **confirmed "No, exit"**, killing the window it was asked to rescue.

The rule now (`prompt_answer`, a pure function, so it is tested without a terminal):

- **the first matching prompt wins and returns.** It never falls through to a later pattern: an old
  "Press Enter to continue" still in the scrollback would otherwise send an Enter onto a live dialog's focused
  cancel;
- the **bypass** warning is answered only when the move is deliberately starting the session in
  `bypassPermissions`;
- a screen that is not a choice (theme picker, "Press Enter to continue") gets one Enter;
- otherwise the pane is read **from the top of the dialog downwards** — the earliest of the prompt line and the
  two option lines, because a short window (or output pushed above it) scrolls the question off and leaves the
  focused option ABOVE the first line that matched, while the `❯` glyph is also the ordinary input line's, so a
  marker above the whole dialog must still not be read as its focus — and the decision comes from **the marker's
  own line**: the wanted label on it → `Enter`; **both** labels on it → **no key at all**; otherwise → `Down`.
- `Down` **wraps** in a two-option list, so "press Down until the marker is where I want it" terminates for a list
  of any length and a repeat can never land on the cancel. No canned key sequence is ever safe.
- at most `MAX_PROMPT_KEYS` (6) keys per prompt, one per poll; after that the dialog is left on the screen for a
  person and the give-up is logged.

The "both labels on one line" case is real: `capture-pane -J` joins wrapped lines, and `-J` is mandatory (without
it a wrapped claude.ai link reads as a shorter, wrong id). **The one safe way to be wrong is to leave the dialog
up.**

Labels, with the version each was measured on. **Read the "drawn first" column**: the last row is not
cancel-first, which is the whole reason the answerer walks the marker instead of trusting a shape.

| Dialog | Wanted | The other option | Drawn first, focused | Measured on |
|---|---|---|---|---|
| workspace trust | `Yes, I trust this folder` | `No, exit`, or `No, continue without these permissions` | the cancel | 2.1.300 |
| workspace trust, managed settings (`Do you trust these settings?`) | `Yes, I trust these settings` | `No, exit Claude Code` | the cancel | 2.1.300 |
| bypass mode (`WARNING: Claude Code running in Bypass Permissions mode`) | `Yes, I accept` | `No, exit` | the cancel | 2.1.300 |
| auto-mode offer (`Make auto mode your default permission mode?`) | `No, keep <mode>` | `Yes, set auto mode as my default permission mode` | **the accepting answer** | 2.1.301 |
| Remote Control (`Enable Remote Control?`) | `Enable Remote Control` | `Never mind` | the cancel | 2.1.300 |

The auto-mode offer is made once per home, to a home whose settings set `permissions.defaultMode` and leave
`disableAutoMode` unset — the layout [§4 of the setup page](setup.md#layout) leads to. Accepting it would rewrite
that home's default permission mode for every later session, so it is declined, by walking the marker onto the
`No, keep …` line. A "press Enter on a cold dialog" shortcut would accept it; that is the shortcut this design
refuses to take.

⚠️ The Remote Control dialog could not be reached in the test harness (a home authenticated by a dummy API key
goes straight to the prompt), and in practice the home's `remoteDialogSeen` flag records that it has been
answered. It is handled by the same marker rule, never by a blind Enter. v0.1.0's claim that it prints
`Choose [1/2] (default: 1)` is unverified and has been removed.

<a id="proof"></a>

## Proving a process before signalling it

A registry file outlives its process, and pids are reused, so "the file says pid 4242" is not evidence. v0.1.0
tested whether the string `claude` appeared anywhere in `ps -o command=`, which also matches an editor open on a
file under a `.claude` directory.

`still_the_same_process` now requires:

- **pid plus start time.** The live registry row carries `procStart`, which equals
  `LC_ALL=C TZ=UTC ps -o lstart= -p <pid>` (compared whitespace-normalised, because `ps` pads single-digit days).
  In one real setup this matched for every live registry row on the machine. A mismatch is "the pid has been
  reused", with both times printed. **The locale is part of the question**: `ps -o lstart=` prints month and
  weekday names in the caller's locale, and the CLI writes the value under `LC_ALL=C`, so a prover that
  inherited the user's locale would compare `jeu. 15 oct. …` against `Thu Oct 15 …`, call it a pid reuse, and
  leave the source running after `--stop-source` — two copies answering. The test helper spells the WRITER's
  command, not the tool's, so the suite can see that class of bug at all.
- **argv[0], not a substring**: the basename must be `claude`, or the path must contain the versioned-bundle
  segment `/.local/share/claude/versions/` (a Remote-Control-spawned worker runs as that binary). This is an
  EXTRA condition on top of the start time, never a substitute for it: a registry row with no recorded
  `procStart` is refused outright, because "argv[0] is the Claude Code CLI" does not say WHICH session, and on
  a machine running several of them pid reuse by another one would pass that test.
- **"could not ask" is a refusal, not a pass.** `_ps` deliberately distinguishes `None` (ps could not be asked —
  a timeout on a loaded machine) from `""` (ps answered nothing). An unprovable identity refuses with
  *nothing was stopped and nothing was proved*, never with "the pid was reused". Conflating the two makes a
  blinded prover look like agreement, and every guard built on it quietly stops guarding.

This gates both `--stop-source` and `csm stop`. Only `SIGTERM`, only the one pid the registry gave, never a
pattern, never a process tree.

<a id="login"></a>

## Is this home really signed in?

The state file is **not** the login. `oauthAccount.emailAddress` is the last login the CLI saw there, so a home
whose credential was removed or expired still names someone: it passes every file check, gets its dialogs
pre-answered and its transcript written, and then fails at the first API call — the one outcome a preflight
exists to prevent.

So the check is one primitive with three answers (`credential_present`, wrapped by `login_usable`), shared by
the views — `csm accounts`, `csm matrix` — and by the move's refusal, so what you are shown and what you are
refused on can never disagree:

| Answer | What it means | What the move does |
|---|---|---|
| signed in | the state file names a login **and** its credential exists | proceed |
| credential **gone** | the state file names a login, the store says that item does not exist | refuse, with the sign-in gesture for that home |
| **could not look** | the store could not be asked | proceed, and print `⚠ UNVERIFIED` |

Existence only, never a value:

- **macOS**: the *exit code* of `security find-generic-password -a "$USER" -s "<service>"` — no `-w`, no `-g`
  (both print the secret) — under a 10 s timeout, because an item whose ACL does not cover `/usr/bin/security`
  raises a dialog that would block an unattended run. Exit `44` (`errSecItemNotFound`) is a real "signed out";
  every other non-zero answer (a locked keychain, no access, ssh with no login keychain) is **unknown**.
  The service name is `Claude Code-credentials` for the default home, else `Claude Code-credentials-` plus the
  first 8 hex of `sha256(NFC(the literal CLAUDE_CONFIG_DIR string))` — no realpath, no `~` expansion, no
  trailing-slash trimming, so `~/.claude-work` and `~/.claude-work/` are two different logins and renaming a home
  orphans its login until that item is copied across. Every path csm holds has been through `expanduser`, which
  drops a trailing slash, so when the probe answers `44` it is retried **once** with the slash spelling; if that
  item exists the home is signed in, and the output says which spelling served and that the home's literal
  `CLAUDE_CONFIG_DIR` differs from the path csm uses. One extra probe, and no more — realpath and other
  speculative spellings are not tried, because each `security` call is another chance to block on a locked
  keychain over ssh.
  The item's **account** field is `$USER`, and when that is not exported (a container, `env -i`, some CI
  runners) the OS user name from the password database, as the CLI does — not the `claude-code-user` sentinel,
  which names an account that does not exist and would make every home read as signed out at once.
- **elsewhere**: whether `<home>/.credentials.json` exists. It is never opened.

🛑 Unreadable is never promoted to "signed out". Reading "I could not look" as "you are logged out" is how a check
tells people to sign in to accounts that are perfectly fine.

`CSM_LOGIN_PROBE=true|false|unknown|off` forces the answer for tests. While it is set it announces itself on
stderr **and in the log on every run**: a stale export must never switch a safety check off in silence. An
unknown value is refused.

<a id="notes"></a>

## What the target home cannot do: the notes

Warnings, never refusals, computed at every move and keyed on the mode the move will actually pass (keyed on the
transcript's mode, the bypass note would go missing on exactly the moves that need it). Each one is wrapped so a
failing probe can never break a move, and they are printed again under the pane lines when a move does not
connect — they are the likeliest reason a window stopped.

| Note | Why it exists |
|---|---|
| **bypass consent** | the move starts in `bypassPermissions` and the target's settings do not set `skipDangerousModePermissionPrompt`: the window may stop on the warning (and on 2.1.300 an unconsented bypass start is silently downgraded) |
| **Remote Control dialog** | the target's `remoteDialogSeen` is not `true` |
| **plugins** | the source home has plugins installed and the target has none: *enabled in a shared settings file is not installed* — the tree is per home |
| **skills / agents / commands / output-styles** | the source has them and the target does not, compared by **realpath** so homes linked to one shared directory say nothing |
| **connectors** (always printed) | claude.ai connectors belong to the **account**, server-side, and no terminal can attach one: the moved session gets the target's. The names are read from `mcp__claude_ai_<Connector>__…` in the transcript, in **two buckets**: the ones the conversation *has used* — matched only where `"type":"tool_use"` and the name sit on one JSON line — and the ones it merely *mentions*, because a deferred-tool metadata block carries the same name without any call having been made. The sentence says which it is, so it cannot claim a call that did not happen |
| **retention** | the transcript's own file has not been written to for at least the home's `cleanupPeriodDays` (absent means the CLI's own default of 30; `0` switches the sweep off), so the home that keeps it may prune it. Read only to warn — nothing here deletes a transcript |
| **room** (only with `CSM_ROOM_CMD`) | whatever runs sessions here for the *target* account has no way into this folder yet: the moved session needs none, because this tool starts it, but a new session started here as that account does. A probe that exits non-zero says nothing at all |
| **other MCP servers** | the servers the conversation used, with the reminder that MCP sign-ins live inside the credential blob and are per config home (`claude mcp login <server>`, once in the target) |
| **memory** | the two homes resolve auto-memory to different directories and the project has notes ([below](#memory)) |
| **memory in this shell only** | `CLAUDE_CODE_REMOTE_MEMORY_DIR` is set in your shell but not in the target home's settings: the moved session does not inherit it (every `CLAUDE*` variable is scrubbed) |

A separate warning says the **target may be out of quota too**. When a meter is configured and its reading is fresh
and at or over a cutoff, that reading is what the warning names ([above](#auto)); otherwise it is read off the
target's own recent sessions, when a limit it hit is still in force — evidence rather than a reading. Either way a
warning, never a refusal, because moving into a second exhausted account otherwise looks like a success: the window
connects and prints a link, and then every turn is refused.

<a id="memory"></a>

## Auto-memory is never copied

Auto-memory is the one piece of state where copying is worse than not carrying it: two copies fork and then
drift, and nothing afterwards reports the fork. The tool resolves each home's memory directory and **reports**
rather than copies — in every configuration, including the one that looks harmless (neither home has a store
and the target has no notes), because that is exactly the case that creates the second store.

Resolution, in order (`memory_store`), read from the home's own settings so a symlinked `settings.json` is
followed. The order and the **shape** are both the CLI's, measured on 2.1.300, and the shape differs between
the rungs — the first two name the memory directory itself, the third names a base under which it is keyed per
project:

1. `env.CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` — the memory directory, used **verbatim**: nothing is appended and
   nothing is expanded.
2. `autoMemoryDirectory` in settings — also **verbatim**, and the one rung that expands a leading `~/`. It is
   the documented lever, and it **wins over** the environment variable below.
3. `env.CLAUDE_CODE_REMOTE_MEMORY_DIR`, else the config home — a base, under which memory lives at
   `<base>/projects/<key>/memory/`. The variable is undocumented and the CLI uses its value **literally**, so a
   value starting with `~` or `$HOME`, or a relative one, is a mistake and is ignored here too. The two
   project keys are not the same key: with the variable set the CLI keys on the **realpath of the project's git
   worktree root** with every non-alphanumeric character turned into `-`, while the config home keys on the
   transcript's own project-folder name — a session launched through a symlink is filed under the symlink's
   spelling. When the worktree cannot be resolved the tool prints `<project>` rather than name a directory that
   would send you to the wrong notes.

A store that is configured but does not exist yet is still the store: requiring the directory to exist reads a
fresh store as "no store", and then everything said about memory is about a path the CLI will never open.

No `memory/` ever travels. The step line says why, and the target note says what the moved session will read
instead.

<a id="cost"></a>

## What a move costs

Printed in the plan — **including under `--dry-run`**, which is the last moment "move early, not at the limit"
can still be acted on — and again after a successful move, where the measured "it came up in X" lines join it:

- **Preserved thinking is bound to the organization that wrote it.** Across organizations the CLI drops it and
  the first turn **re-reads the whole session to regenerate it — on the target account's quota**, on top of a
  cold prompt cache. On a long session that re-read is a real slice of the very quota the move went looking for,
  so **move early**, while there is quota to spare, not after the refusal. When both homes' state files name the
  same `organizationUuid`, the block says instead: *same organization: the session's preserved thinking is KEPT.*
- **A new claude.ai session**, with a new id and link, owned by the target account. The old link keeps pointing
  at the source account's copy. The local agent has the whole conversation; the app may show the thread starting
  at the move. (The CLI has a `noHistoryBackfill` flag, forced on when a session reattaches to a bridge session
  other than the one it recorded. It was present on the bridge line appended by 2.1.296 and absent from the lines
  appended by 2.1.300, so this doc states the new-session fact and asserts nothing about re-rendering.)
- **The copied transcript still names the source account inside itself** — paths and the recorded email from
  earlier turns — so the moved agent describes itself as the old account until its context is rebuilt. Harmless,
  but it surprises people.
- **Connectors, MCP sign-ins, plugins, skills come from the target home** ([notes](#notes)).
- **The last line on disk only.** A reply still being written is not in the copy, and when you move the session
  you are talking in, the message asking for the move does not travel.

<a id="revive"></a>

## Revive: bringing back a session that stopped

Everything above is about a session that is still running. `csm revive SESSION` is about one that is **not** — a
usage limit, a restart, a Remote Control disconnect, a kill mid-turn — and it was built against one measured
incident: a Remote Control session whose turn died on a 429 at 17:46 local time on 27 Oct 2026 and sat dead for
17 hours, one of a run of such stops that cost tens of hours of agent wall-clock in five weeks. Everything in
this section was measured on **CLI 2.1.312**, Wed 28 Oct 2026.

**It starts from the link, because that is all there is.** A Remote Control session spawned by the bridge writes no
`bridge-session` line into its own transcript, so before this release a link resolved only through a live registry
row — which a dead session does not have. The transcript's name is *computable* instead:
`uuid5(3ab19d7e-9f35-45c2-926e-75e271cc60b3, "https://api.anthropic.com/v1/code/sessions/cse_<bare>")`, verified on
37/37 live pairs. `derive_local_id` does that at the **spec layer**, above `pick`'s ladder, which is also what pins
the derived id past the listing's age cap — the session anybody is looking for stopped days ago. 🛑 A link gets
exact rungs only (the derived transcript, then a row whose claude.ai id is that one) and is refused rather than
handed to the id-prefix or title rungs: a session whose first prompt *pasted* the link has the link in its title.

**The diagnosis is one record, and it is proved rather than guessed.**

| field | what it answers, and from what |
|---|---|
| `kind` | `server-child` (its local id *is* `uuid5` of a bridge id — from the link, the registry, or an orphan `~/.claude/bridge-spawn/cse_X-*` directory that derives to this transcript; **or, with none of those left, from the id's own uuid version** — see below), `self-hosted` (a `bridge-session` line or a `bridge_status` url it wrote itself), `terminal`, `desktop`. 🛑 Never the registry's `entrypoint`: that says how the process was started, and a fork or a resume rewrites it |
| `state` | `live-busy` / `live-idle` (a registry row whose pid is proved by `procStart`) or `dead`, plus a machine-wide `ps` sweep for an argv naming `cse_<bare>` or the local id — a registry file survives the `SIGKILL` of its own process |
| `stop` | `usage-limit` (class, window, `resetsAt`, still in force?), `api-error`, `mid-turn` (the last main-chain assistant line holds a `tool_use` no later `tool_result` answers — **or**, 0.6.2, the last real prompt has no main-chain assistant line after it at all: killed before it said anything, and `tool` is then empty), `archived` (a `code 4090` line after the last `bridge_status`), `finished`, `empty`, `unknown` — parsed as JSON lines over `CSM_REVIVE_TAIL` (1 MiB), from the last real prompt forward. It also carries `uuid`, the uuid of the line the verdict was read from: the **stop event's own name**, and half the at-most-once key of an unattended wake |
| `lost_work` | the agents whose own `state` is `error` in the sibling directory's `workflows/wf_*.json`. 🛑 Never the file's top-level `status`, which reads `completed` on the incident where five agents died on the limit |
| `account` | whether the session's own home can still run it, plus the meter — and the 5-hour instant comes from the transcript, never from the meter's seven-day `resets_at` |
| `server` | whether a `claude remote-control` server is up with that folder as its cwd (`ps` plus `lsof -a -d cwd`), which is the one thing that decides whether opening the link brings a server child back by itself |
| `owner` | a supervisor in `CSM_BOTS_DIR`, or a scheduled pass in `CSM_RC_JOBS_DIR` whose `<job>.session` file names this id |

**The decide table is data** (`REVIVE_ROWS`), walked in order, first match wins — so a session that is both dead
and out of quota is answered about the quota, because starting it would spend its first turn on the same wall.
Rows 1, 2 and 4 refuse (exit 2); row 3 has nothing to do; rows 5–8, 10 and 11 act; row 9 prints one sentence.
The plan a `--dry-run` prints and the thing a real run carries out come from **one function**, so a plan that said
row 7 cannot be followed by a run that takes row 10.

| # | condition | action |
|---|---|---|
| 1 | a bot owns it, or a scheduled pass owns it and it is not live-idle | refuse, naming that owner's own command. ⚠️ An `CSM_RC_JOBS_DIR`-owned session that is **live and idle** falls through to row 5: a wake relays a message into the process already running and starts no second copy of the pass, which is the whole thing this refusal guards. A bot is refused whatever its state |
| 2 | `stop == empty` | refuse: nothing to continue |
| 3 | `live-busy` | nothing to do |
| 4 | a usage limit still in force, no `--to` | refuse, with the reset and the cures |
| 5 | `live-idle` | wake it — relay the note, start nothing |
| 6 | `--to ACCOUNT\|auto` | `do_move` unchanged, then relay the note into the copy |
| 7 | dead, `self-hosted`, no `--new-link` | resume in place on the same link (archived refuses without `--unarchive`) |
| 8 | dead, `terminal`, no `--new-link` | resume in place; it gets a new link, and is told so |
| 9 | dead, `server-child`, no `--new-link` and no `--auto` | print the one tap; start nothing, wait for nothing. With `--auto` it takes row 10 instead: row 9's whole result is a sentence for a person, and nobody is reading it |
| 10 | dead, `server-child`, `--new-link` | fork: `--resume <old> --fork-session --session-id <new uuid4>` |
| 11 | dead, `self-hosted` or `terminal`, `--new-link` | fork, by row 10's mechanics: `--new-link` is a fresh copy on a new link whatever the kind |

⚠️ **Row 11 is a row NUMBER, not a position in the walk.** It is reached from inside the `self-hosted` and
`terminal` branches, beside rows 7 and 8, and the three are mutually exclusive by kind and by `--new-link` — as
rows 9 and 10 already are. Everything that depends on the ORDER is in rows 1–6. It was added rather than
renumbered because the row number is carried by `--json`, by every line of `revive.jsonl` and by the README, and
renumbering would silently re-label every record already written.

<a id="the-decide-table"></a>
The `action` string each row records is part of the interface: `--json` carries it and so does every line of
`revive.jsonl`.

| row | 1, 2, 4 | 3 | 5 | 6 | 7 | 8 | 9 | 10, 11 |
|---|---|---|---|---|---|---|---|---|
| `action` | `refuse` | `nothing` | `wake` | `move` | `resume` | `resume-new-link` | `keep-link` | `fork` |
| exit | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

⚠️ Row 8's action was `new-link` before 0.5.0's review fixes and is `resume-new-link` now. The old spelling read
like the `--new-link` FLAG, and the flag takes row **10** or **11**, which record `fork` — so a caller filtering
`action == "new-link"` matched a resume in place and never a fork.

**A FLAG THAT WAS NOT CARRIED OUT SAYS SO**, and on every row. `dropped(row)` is called by `take` for all of them,
refusals included, and what it returns is both appended to the second line and carried as `decision.dropped`:
`--to` where the row is not a move, `--say` where the row sends no note, `--new-link` where the row forks nothing
(with the reason: a live writer on rows 3 and 5, a move's own new link on row 6, "nothing is started on this row"
otherwise), and `--permission-mode` where the row starts no process.

**The mode is RESOLVED only where it is APPLIED.** `REVIVE_ROWS_THAT_START` is `(6, 7, 8, 10, 11)`; on those rows
`resolve_mode` picks the mode the window is started in and `--json`'s `mode.applied` is `true`. Every other row
— 3, 5, 9 and every refusal — starts no process, so `unchanged_mode` REPORTS the mode the session is already in
instead: `revive_state`'s `mode_launched` (the proved pid's own `--permission-mode`, off the same `ps` sweep
`csm modes` reads) and the last `permissionMode` its transcript recorded, each named in `why`, which opens
`unchanged:`. When they disagree the stronger is reported — a Remote Control worker records `auto` while its
server's argv says `bypassPermissions` — an unknown mode is carried through untouched, and when neither source
says anything the line reads `unknown`, never `default`. 🛑 Measured live on CLI 2.1.312, Wed 28 Oct 2026: a
session running `--permission-mode bypassPermissions`, woken with `--permission-mode plan`, was reported as
`mode plan (from --permission-mode)` while it kept running in bypass — the unsafe direction, and the reason
`unchanged_mode` and `mode.applied` exist.

**A `server-child` whose link nothing records is still row 9.** The four sources of a bare bridge id above are all
things that can be gone: a dead child has no registry row, writes no bridge id into its own transcript (2 of the
861 version-5 transcripts in the config homes here carry one), and its `~/.claude/bridge-spawn/cse_X-*` directory
is deleted on a handled exit — a server shutdown or a graceful restart. 840 of those 861 therefore had no source
at all, and a session named by its own id or by part of its title brings none. The id's **uuid version** is the one
fact that survives: `derive_local_id` mints a child's id as `uuid5`, every other session gets a random `uuid4`, so
version 5 *is* the proof. `kind` is then `server-child` with an empty `bridge_id`, and the row says "paste the
link, or `--new-link`" rather than printing a link it cannot name. 🛑 What this is for is that the alternative is
row 8 — `--resume <old id>` with **no** `--fork-session` — a second process on the local id a later lazy respawn
of the old link shares (LESSONS.md L39).

**One copy, or a refusal.** A move is a copy, so after any `csm move` one id sits in two homes. `revive_resolve`'s
soft pass answers `None` both for "nothing matched" and for "several matched, and `one_of` would refuse", and only
the first may fall through to `revive_row` — the rung that exists for a transcript every listing *drops*. Fall
through on the second and revive acts on whichever home came first in `accts` order: a stale snapshot, the wrong
account's quota, and a note reading "You are still <the other email>". `revive_row` itself asks every home too,
and `--account NAME` is the cure the refusal names.

**One carrier, and it is a relay.** Whatever the row, the session comes up (or is found) as an ordinary idle
process with **no positional prompt**, and the note is then delivered by a headless Claude of its own:
`claude -p --model <CSM_RELAY_MODEL> --permission-mode bypassPermissions --name "csm revive (<machine>)"
--output-format json "<call SendMessage once, verbatim, between these markers>"`, run under that session's own
config home with the environment scrubbed, stdin closed (`subprocess.DEVNULL`, so fd 0 really is `/dev/null`), in
a folder of csm's own under the state dir, bounded by `CSM_RELAY_TIMEOUT_S`. It lands recorded for what it is — `isMeta: true, turnOrigin: "peer", origin: {kind:
"peer", name: …, fromMode: "bypass", verifiedPeerPid, msg_id}` — and the app shows it as a message from that
sender. The two alternatives were measured and are worse: a positional prompt is recorded as the user's own
typing, and an `isMeta` line plus `--reply-on-resume` writes into a transcript — for a fork, into the *old* one,
where a later lazy respawn of the old link could pick it up as an interrupted turn. So **a revive writes into no
transcript at all**; the cross-account move still appends its own move note to the copy, as it always has.

**Where the relay's own transcript goes, and the name it addresses.** The cwd moves the project-folder **slug**,
not the home: the relay's transcript lands at `<its home>/projects/<slug of STATE_DIR/relay>/<its id>.jsonl`, in
the revived session's own config home, written by the CLI. So the note does reach disk, in that home — csm's rule
is that *no file csm keeps* holds it (`revive.jsonl`, the log, the record in `--json`'s `result`), never that the
note is unwritten anywhere. That slug is kept out of `transcripts_by_id`, or every revive would leave a session in
`csm list`, in `csm find` and in revive's own resolution whose title is the relay instruction.

And the relay addresses the session by the `name` in its registry row, because that is what SendMessage takes — so
that name has to be unique among the **proved** live rows of that home, or the note could land in an unrelated
conversation while `prove_turn` watches the intended one and reports "up but idle". More than one is a refusal
before anything is sent, naming both; and csm's own label carries the session's id8 (`rc_label(<title>, "revived
by csm <id8>")`) so the windows it starts cannot collide with each other — `rc_label` truncates to 56 characters,
which two revives of one session used to collide inside.

**The proof is a turn, not a link.** The transcript's byte offset is taken before the relay; exit 0 needs the
registry row going `busy` or an `assistant` line past that offset within `CSM_REVIVE_PROVE_S`. A relay that
reports success and delivers nothing is exit 1, printing the one sentence to type. For a row-7 resume the **link**
is a second proof: a self-hosted session re-attaches its own claude.ai session, so a *new* link means nothing
re-attached and the note is not sent, because the sentence it carries would be false.

**At most once, and the gate is re-run in the last second.** `state_lock`'s lock-directory shape keyed on the
local id is held from the diagnosis to the start — with the stale break set to `REVIVE_CLAIM_STALE_S` and not the
120 s the `.claude.json` lock keeps. That lock is held for a read-modify-replace; this claim is held across four
bounded waits (a window connecting, its registry row appearing, the relay, the turn, and for a fork the new
transcript) that sum to as much as 660 s, so at 120 s a second `csm revive` of the same session broke a live claim
from t=120 s on every run. The waits re-stamp the directory as they poll (`touch_locks`), so a killed revive still
clears itself. The claim is held and because a lazy respawn has the
*same* local id before and after, every home's registry and the machine-wide `ps` sweep are re-read immediately
before anything starts: a child that appeared while csm was deciding is a refusal, not a second writer. Each
revive appends a JSON record to `CSM_REVIVE_LOG` (0600) carrying the at-most-once triple — local id, bridge id,
transcript size at diagnosis — the row, the action, what was started, what was proved and the exit code. Never
the note: that is conversation text. Since 0.6.0 it also carries `stop_uuid`, the at-most-once key of an
unattended wake, which `csm stalled` reads back (below).

**What it will not do.** It cannot make a server respawn a dead child (row 9 prints the tap, and does not poll for
a person). It will not wake a session by writing to its peer socket, because a hand-rolled frame is *held* for a
human on a session that bypasses prompts. It will not reuse a server child's id in its own home. It will not reach
a machine that is off: `--from-machine` is refused for `revive`, because every gate it turns on is a question
about the machine the transcript is on, and `csm --machine M revive <spec>` runs the whole thing over there
instead. It will not choose between two copies of one id, or address a registry name that is not unique. And it
signals nothing, ever.

🛑 **One deviation from the implementation brief, recorded rather than hidden.** The brief's M5 lists
`--from-machine M` for `revive` (fetch as `move` does, then rows 6–10 here) and `preflight(..., copy_only=True)`
for the no-window rows. Neither is built. `--from-machine` is *refused* instead, for the reason above, and the
`copy_only` preflight is not implementable as written: run on row 5, its live-twin check would refuse a session
that is deliberately alive, which is that row's own condition. What is left of it and does apply is built — row 5
checks that the CLI is on PATH before it claims it will relay anything, and the folder and twin gates still run on
every row that starts a window.

<a id="stalled"></a>

## `csm stalled`: the unattended sweep

0.5.0 could revive one session a person named. 0.6.0 adds the two pieces an unattended loop needs, and
deliberately not the loop: **`csm stalled`** says which sessions are ready, **`csm revive <id> --auto`** continues
one of them, and a scheduled pass of your own joins them. The acting stays one session per command on purpose —
that way every row of the decide table, and every refusal in it, is asked once per wake rather than once per
sweep.

**Due is a property of the stop, and there are two of them.** A usage limit of a class a *reset* clears
(`session`, `weekly`) once `resetsAt + CSM_WAKE_MARGIN_S` has passed; and a `mid-turn` stop whose process is gone,
inside `CSM_WAKE_MAX_AGE_H`. `monthly-spend`, `credits` and `model` never clear by waiting, and a class whose own
words nothing matched is not on the positive list either — an unread class is not a clearable one. A `finished`
stop is not due (it answered), nor is `api-error` (time does not fix it). And six states are never due whatever
the stop: `live-busy`, bot-owned, owned by a scheduled pass that is not live-idle, **unmeasured**, `empty`, and
archived. Every row carries its reason in `why`, so "not due" is never a silence.

🛑 **And `mid-turn` has two shapes since 0.6.2.** The second is a real prompt with no main-chain assistant line
after it — the file a kill in the first seconds of a turn leaves, measured on 2.1.312 as the user's line plus the
`total_tokens_reminder` attachment and nothing else. Before 0.6.2 that read `unknown`: not due, and carrying no
`uuid`, so the at-most-once key had no name for the stop. The prompt line itself is the stop event. ⚠️ A live
session that is thinking leaves the same bytes, which is why the refusal below matters more, not less.

🛑 **Unmeasured is the sixth, and it was added in 0.6.1.** A session is only called live by proving its registry
row, and that proof needs `ps`; `ps_table` answers `None` when `ps` could not be *asked*, and `None` is never
"nothing is running". With `ps` blind every live session reads `dead` — and a live session that is BUSY ends its
transcript on an unanswered `tool_use`, which is exactly the `mid-turn` shape above, so the sweep called a
running session due and a watchdog would have resumed it. `stalled_report` already put the row in
`coverage.unread`; `stalled_due` now refuses it with that same sentence. The conditions correlate, which is why
it matters: the sweep is heaviest, and the machine busiest, right after the restart this feature exists for.

**The prefilter is `revive_stop` on a smaller window.** A `diagnose` is a 1 MiB parse plus a machine-wide `ps`,
and a home holds thousands of transcripts. So the last `CSM_STALLED_PREFILTER` (64 KiB) is parsed first, and only
the three verdicts a small window cannot be trusted to rule out — `usage-limit`, `mid-turn`, `unknown` — reach the
full diagnosis. 🛑 The line that says what stopped a session is at the **end** of its file (a session that stopped
wrote nothing after the stop); the 1 MiB window exists to find the last real *prompt*, which only matters once
something is going to act. 🛑 And an empty **window** is not an empty **file**: when the window held no main-chain
line and the file is larger than the window, the verdict is *inconclusive* and the file is read properly. Running
the same parser rather than a second "does this look like a limit" test is what keeps the two from drifting —
a text match on a tail is the thing `revive_stop` exists not to be.

**At most once per stop, keyed on the stop and not on the session.** `revive_stop` reports the `uuid` of the line
its verdict was read from; `revive_record` writes it as `stop_uuid`; `revive_handled` reads the log's tail back and
matches on **`stop_uuid` alone** (0.6.1 — see below). A session that stopped, was woken, worked for an hour and stopped again has a new
uuid and is due again — which is the whole point, because a key per *session* would wake it once and never more,
and no key at all would relay the same note twelve times an hour. Handled means a record with **exit 0**: a
non-zero exit is a wake that was attempted and failed, so the row stays due and the attempt is counted
(`handled.failed`), which is what `--check` reports as its one `FAULT:`. Where a stop line carries no `uuid`, the
fallback is 0.5.0's own `(local id, transcript size)` — never the id alone.

🛑 **And the uuid is not narrowed by the local id, because a fork copies the transcript** (0.6.1). `--fork-session`
writes a new file holding every line of the old one, uuids included, and leaves what it read byte-identical — so
the stop line that made the parent due ends the copy too, under a second local id. Matching `(local id, uuid)`
meant the parent's exit-0 record could not cover the copy: both rows read due for ONE stop event and a pass that
wakes everything due woke both, which is two actors continuing one history. It needs no csm bug to reach — a
person running `claude --resume X --fork-session`, or `/fork`, on a parked session leaves exactly that pair. So a
record matches on the stop event, `handled.copy_of` names the session it was matched from, and `stalled_report`
refuses to call two rows sharing a `stop.uuid` due in one sweep, keeping the older file.

**And the machine is read once a sweep** (`read_only_memo`, 0.6.1). This is the one caller that runs the whole
`diagnose` over every session in every home, and the probes inside it answer about the machine, the home and the
folder rather than about the session: `revive_state` and `server_in_folder` each take a machine-wide `ps`,
`revive_account` asks the credential store, `server_in_folder` asks `lsof`. Measured on the suite's own fixtures:
six parked sessions in one home cost 12 `ps -Ao` runs and 6 credential probes in one sweep, now 1 and 1. The memo
is opened by `stalled_report` and by nothing else — `revive_recheck` asks `ps` afresh in the last second before it
starts a window, because there the answer's *age* is the whole question.

**`--auto` changes two things and no gate.** The note's *attribution*, because nobody typed the run and the
receiving session decides what to do next on the strength of that sentence; and row 9, which becomes row 10's
fork, because a dead server child has no unattended way back onto its own link. A fork leaves two conversations
with one history, so `--json`'s `result` names `forked` / `old_bridge_id` / `old_url` / `archive_old`: the old
claude.ai session has to be archived, and csm cannot do that itself — it reads no credential, and archiving is an
authenticated call. Every refusal, the limit still in force above all, is untouched.

🛑 **`forked` is its own key because the exit code cannot carry it** (0.6.1). `revive_fork` creates the new
session, its link and its transcript *before* the relay, so a registry name that turned ambiguous, a relay that
errored or a turn that never appeared all return **exit 1 with the fork already made** — and a caller reading the
exit code alone takes that for "nothing happened", skips the archive in exactly the cases where the old link is
live beside a new one, and forks again on its next pass. `forked` is `False` in `revive_act`'s `out` from the
start and set at the one line where the second session comes into being; a fork that printed no link leaves it
`False`, because nothing new came into being there.

**`--check` is `modes --check`'s contract, with one difference worth naming: being due is not a fault.** It is the
normal state between one pass and the next. The fault is a wake that was tried and failed for the same stop, which
nothing else in the loop reports — the next pass just finds the row due and tries again. `INCOMPLETE:` covers what
could not be read, the revive log included: a log nobody can read is not an empty one, because the sweep then
cannot tell a stop it has acted on from one it has not. On that path the credential probe is never asked at all
(`diagnose(..., probe=False)`): it prints a line of its own whenever `CSM_LOGIN_PROBE` is set, and on macOS it can
raise a Keychain dialog — the one shape an unattended run may never produce.

<a id="stop"></a>

## `csm stop`: ending what csm started

v0.1.0 created a `moved-<id8>` window on every move, refused the next move of the same session into the same
account while that window existed, and offered no way to clean it up. `csm stop SESSION [--dry-run]` is that way.

🛑 **The only authorisation is csm's own fingerprint**: a window named `moved-<id8>` in the tmux session
`csm-<account>` of the account the row belongs to (or whatever `CSM_TMUX_SESSION` spells it, [below](#env)) —
and, for a live row, a registry `tmux` field naming **that same window id**, so a moved window plus an unrelated
reused pid cannot add up to a signal for someone else's process. Anything else is refused, with the `moved-…` windows that do exist listed. It never stops the session
running the command, and **it never deletes a transcript**.

The candidate set comes from the windows csm opened, whose names carry the 8-character id prefixes, so the usual
case reads a handful of transcripts instead of every transcript in every home. The full scan still runs when
that narrowed list does not resolve the argument — only so the refusal text has one producer.

Then, in order: the pane is captured, the pid is proved ([above](#proof)) and `SIGTERM`ed; the window is killed
(`tmux kill-window -t '=csm-<account>:=moved-<id8>'`). When the pid could not be tied to the window or could not
be proved, no process is signalled — and the plan says plainly that killing the window destroys its pane and
`SIGHUP`s the process tree in it, so that process ends with the window anyway. The log line records both halves:
window removed or not, pid signalled or not and why.

<a id="matrix"></a>

## `csm matrix`: measuring your own setup

`csm matrix` prints your own fungibility matrix: rows are the layers that decide whether your accounts are
interchangeable, columns are the config homes on this machine, plus a verdict column
(✅ shared or carried · 🔧 one shared file or key away · 🛑 per account, per config home or per machine by
design). The layer-by-layer
story is [docs/fungibility-matrix.md](fungibility-matrix.md); the setup it checks for is [docs/setup.md](setup.md).

Design rules worth knowing:

- **Read-only, offline, prompt-free.** It never runs `claude` (the CLI version comes off the launcher symlink's
  `versions/<version>` segment — `claude --version` on a cold home can print a banner and start an update check),
  never reads a credential value and makes no network call. It writes nothing into any config home — a test pins
  that by comparing every home byte for byte before and after — and the only thing it does write is a line in
  csm's own log. Two child processes do run: `git rev-parse --show-toplevel` for the project root, and, on macOS,
  `security find-generic-password` to ask whether an item exists.
- **Unknown is not ok.** `read_json3` answers `absent | unreadable | unparseable | ok`, so an *absent* plugin
  registry is a measurement ("nothing installed") while an unparseable one is `?`. Cell states are
  `ok / diff / cold / unknown / info`, an unknown is never counted as a match, and the summary never claims
  agreement over a machine it could not read.
- **Shared means the same realpath**, never the same bytes, and **wherever that realpath lives**: two unlinked
  identical copies read `own(=)`, a partial group reads `shared(2)`, a symlink to nowhere reads `DANGLING` — its
  own state, never "absent", because that is what renaming a home leaves behind and the CLI loads it in silence.
  One realpath for every home is `shared` even when that path is inside one of the config homes, which is the
  layout you get by sharing through the default `~/.claude`: calling that a divergence contradicts the legend,
  makes `--check` impossible to get green on the recommended setup, and flips the verdict with `--account`. It
  earns a NOTE instead (rename or delete that home and every link into it dangles), and `→<home>` is still how a
  cell reads when the homes do not agree.
- **Cold is not a fault.** The first-run gates, and an auto-memory store nobody has configured yet, are "needs
  your hands". `--check` exits 1 only on a divergent shareable layer or a login that is **gone** — never on an
  unknown, and never on `settings.local.json` or `scheduled-tasks`, where asymmetry is usually the design. A
  check that fails on "you have not set this up yet" stays red forever and gets ignored.
- **It has to print anywhere.** Widths are counted in printed columns (emoji are two wide), the table is laid out
  for 100 columns, span rows wrap instead of truncating, and the glyphs degrade to same-width ASCII stand-ins
  when stdout cannot encode them, so a C-locale CI does not die of `UnicodeEncodeError`.

Flags: `--json` (homes, rows, cells, summary, exit), `--cwd DIR` (which project the first-run gates and the
memory row are measured for), `--account NAME` (repeatable or comma-separated), `--check`.

<a id="formats"></a>

## What is on disk: the formats it reads

All of this is Claude Code's own undocumented on-disk state, as written by 2.1.296–2.1.300.

| What | Where | Used for |
|---|---|---|
| Transcript | `<home>/projects/<folder>/<id>.jsonl` | the session itself; copied |
| Sibling dir | `<home>/projects/<folder>/<id>/` | subagent transcripts, tool results, workflows; copied |
| Rewind history | `<home>/file-history/<id>/` | what `/rewind` restores from; copied additively |
| Task list | `<home>/tasks/<id>/` (older builds: `<home>/todos/<id>*.json`) | copied additively **when it is there**. On 2.1.300 a session's task output is written outside the config home, under a cache root keyed on the working directory, so usually there is nothing to copy |
| Live registry | `<home>/sessions/<pid>.json`: `pid`, `procStart`, `sessionId`, `cwd`, `bridgeSessionId`, `tmux`, `name`, `status`, `entrypoint` | which sessions are running; the only map from a phone session to its transcript; `procStart` is the pid's identity |
| State file | `<home>/.claude.json`, or `~/.claude.json` for the default home: `oauthAccount` (`emailAddress`, `organizationUuid`), `projects[<cwd>].hasTrustDialogAccepted`, `hasCompletedOnboarding`, `remoteDialogSeen` | who is signed in; the first-run gates |
| Settings | `<home>/settings.json`, with `<home>/settings.local.json` over it: `permissions.defaultMode`, `permissions.disableAutoMode`, `skipDangerousModePermissionPrompt`, `env`, `enabledPlugins`, `autoMemoryDirectory`, `theme` | the mode chooser, the bypass note, the memory store |

Transcript lines it reads, by `type`:

- **Title.** `custom-title` (`customTitle`), then `ai-title` (`aiTitle`), then `last-prompt` (`lastPrompt`), then
  the first real user message.
- **Link.** `bridge-session` (`bridgeSessionId: cse_X`, the last one wins): the claude.ai link is
  `https://claude.ai/code/session_X`.
- **Permission mode.** `permission-mode` lines (`permissionMode`) *and* the `permissionMode` field on user prompt
  lines; in file order the later wins. This is an **input to the chooser**, never evidence of how the session was
  behaving ([above](#mode)).
- **Model and quota.** From `assistant` lines: `message.model` from the last **clean** line. An `apiError` of
  `usage_limit_reached`, `rate_limit_error` or `rate_limit_exceeded` is the out-of-quota flag, with the reset
  time from `apiErrorParams.rate_limit_info.{rateLimitType, resetsAt}` or, on builds that write it there,
  `quotaLimits.resetsAt`. A session is flagged only when its last limit is still in force or is the last
  assistant line in the file.
- **Ended from the app.** A `system` line carrying `code 4090` marks the session "closed" rather than "ended":
  resuming it is rarely what anyone wants.
- **MCP use.** Tool names matching `mcp__<server>__`, from the head and tail windows; a server named
  `claude_ai_<Connector>` is a claude.ai connector ([notes](#notes)).

A session is running when its registry file names a pid that answers `kill -0`. Dead processes leave their files
behind, so a file alone means nothing.

<a id="measured"></a>

## Measured facts, and how to re-measure them

| Fact | Measured on | How to re-verify |
|---|---|---|
| A copied transcript resumes under another login: `claude --resume <same id>` with another home's `CLAUDE_CONFIG_DIR` connects as that account and registers a new claude.ai session it owns. `--fork-session` is not needed, and a stale `bridge-session` line is harmless — a new one is appended and the last wins | 2.1.296, end to end on two real accounts | move a one-turn session with `--no-remote-control` and ask the moved agent about its own first turn |
| `--resume <id>` searches, in order: the cwd's own project folder, the repo's sibling git worktrees, then every project folder in the home — accepting a scan hit only if exactly one file matches. It never looks in another config home. It also accepts a transcript **path** | 2.1.300 (resolution chain in the bundle), 2.1.296 (on disk: found under the right folder, a symlinked path's folder, an unrelated folder, and while recording a different cwd; an id that exists nowhere answered `No conversation found`) | resume a copied transcript from a home it was never created in |
| The project folder name is the launch path with **every** character outside `[A-Za-z0-9]` turned into `-` (dots, slashes and underscores included); past 200 characters the CLI truncates and appends a hash of its own | 2.1.300 (binary), 2.1.296 (on disk, throwaway home and real login) | start a session in a directory with a space and an underscore in its name |
| The folder and the recorded `cwd` can disagree: a session started through a symlinked path is filed under the symlink's spelling while it records the resolved path, so the mover never recomputes the folder — it reuses the source's own folder name | 2.1.296, seen on real transcripts in one multi-account setup | compare each transcript's first-line `cwd` with its folder name |
| The cold-home trust, bypass and Remote Control dialogs are `hideIndexes, cancelFirst, focus:"cancel"` — cancel drawn first, focused, no numbers. **Not every dialog is**: the auto-mode offer below draws its accepting answer first and focused, which is why the answerer reads the marker instead of assuming a shape | 2.1.299 and 2.1.300 for the three (a pane, plus the construction in the bundle — which the 2.1.296 bundle shares, so a v0.1.0 write-up claiming the trust dialog listed "Yes" first was simply wrong); 2.1.301 for the auto-mode offer | the recipe below |
| A fourth cold-home gate: **"Make auto mode your default permission mode?"**, offered once per home to a home whose settings set `permissions.defaultMode` and leave `disableAutoMode` unset. Its options are `Yes, set auto mode as my default permission mode` (first AND focused) and `No, keep <current mode>`; accepting it rewrites that home's default for every later session, so the answerer walks the marker to the `No` | 2.1.301 (live, in an isolated home; the construction in the bundle) | start a cold home whose settings name a `defaultMode` |
| Bypass consent is `skipDangerousModePermissionPrompt` in **settings.json** (the legacy `.claude.json` key `bypassPermissionsModeAccepted` is still read); an unconsented `bypassPermissions` start is silently downgraded to `default` | 2.1.300 | start a cold home with `--permission-mode bypassPermissions` |
| `theme` is a **settings.json** key, not a `.claude.json` key; `hasCompletedOnboarding` is what suppresses the picker | 2.1.300 (it is declared in the settings schema, and no config home checked carried it in the state file) | `grep theme <home>/settings.json <home>/.claude.json` |
| On macOS the login is a Keychain generic-password item named from the **literal** `CLAUDE_CONFIG_DIR` string (sha256, first 8 hex); elsewhere it is `<home>/.credentials.json`, mode 0600, and a symlink in its place is refused. MCP OAuth tokens live under an `mcpOAuth` key **inside the same blob** | 2.1.300 | hash the literal path and list the item by service name — existence only |
| The live registry's `procStart` equals `LC_ALL=C TZ=UTC ps -o lstart= -p <pid>` — the CLI forces both variables, and `ps -o lstart=` really is locale-sensitive (`Thu Oct 15 …` under C, `jeu. 15 oct. …` under a French locale) | 2.1.300, every live row on one machine; the locale sensitivity measured on macOS | compare the two for any running session, then again with `LC_ALL` set to a non-English locale |
| Preserved thinking is bound to the organization that wrote it: resumed under another organization the CLI drops it, says so, and re-reads the session to regenerate it | 2.1.300 (the message and its organization-uuid gate in the bundle) | move a session with thinking between two organizations |
| `noHistoryBackfill` is a real per-bridge-session flag, forced on when a session reattaches to a bridge session other than the one it recorded | present on the bridge line appended by 2.1.296, **absent** from the lines appended by 2.1.300 | read the `bridge-session` lines appended after a move |
| An error line names its model `<synthetic>`, and `claude --model '<synthetic>'` refuses to start — so a model is taken only from a clean assistant line that looks like a model id | 2.1.296 | the out-of-quota line at the end of any limited session |
| A desktop-app transcript records its mode on every prompt line, not in a `permission-mode` line, and a first prompt with a pasted screenshot can be bigger than the 96 KB head — hence the backwards read when head and tail have neither | 2.1.296 | a session started from the desktop app |
| Per-session data outside `projects/`, keyed by session id: `file-history/<id>/` is real and populated. `<home>/tasks/` is a path the CLI knows (its read-allowlist names it), but a session's task OUTPUT is written outside the config home, under a cache root keyed on the working directory — so `tasks/<id>/` is carried opportunistically and is usually absent. Older builds wrote `todos/<id>-*.json` | 2.1.300 (the bundle's path builders and read-allowlist; on disk, per-session `file-history/<uuid>/` directories, no `todos/` and no `tasks/`) | `ls <home>/file-history \| head` after using `/rewind`; `ls <home>/tasks` for the other half |
| `jobs/`, `daemon.json`, `shell-snapshots/` and `session-env/` are treated as code-execution surfaces that even a bypassing session may not write — another reason nothing but the session's own data travels | 2.1.300 | the reserved-name set in the bundle |
| A Remote Control session's local transcript id is `uuid5(3ab19d7e-9f35-45c2-926e-75e271cc60b3, "https://api.anthropic.com/v1/code/sessions/cse_<bare>")`, and claude.ai's `session_<bare>` is the bridge's `cse_<bare>` with the prefix swapped. A server-spawned child's transcript carries **no** bridge id of its own | 2.1.312 on 37/37 live registry rows across six homes (0/37 for any other name form); the namespace constant is byte-identical in 2.1.310, .311 and .312 | compare `sessionId` against `bridgeSessionId` in `<home>/sessions/*.json`: `python3 -c 'import uuid,sys;print(uuid.uuid5(uuid.UUID("3ab19d7e-9f35-45c2-926e-75e271cc60b3"),"https://api.anthropic.com/v1/code/sessions/"+sys.argv[1]))' cse_<bare>` |
| A killed server child leaves an orphan `~/.claude/bridge-spawn/cse_<bare>-<6 chars>/` directory — the bridge removes it only on a handled exit — and that root is hardcoded to `~/.claude` for **every** account. It is a pid-free death index | 2.1.312, 40/40 such directories deriving to exactly one transcript each | `ls ~/.claude/bridge-spawn` and derive each name with the one-liner above |
| A respawned server child comes back **idle**: it re-sends nothing and writes nothing until a message arrives, and the session-start attachments arrive with the first turn *after* the wake | 2.1.312, on the incident transcript: no entry at all between the 429 at 00:46:14Z and the peer prompt at 18:03:30Z, whose attachments are stamped 170 ms later | open a dead Remote Control session in the app and watch `wc -l` on its transcript |
| `claude --resume <uuid>` of a server child does **not** re-attach its claude.ai session (ingress url null) — it registers a new one; `--resume <path.jsonl>` silently mints a fresh id; `--resume=<https url>` hydrates from the server and **replaces** the local transcript, declining only to replace a non-empty local file with an empty server set. A self-hosted `--remote-control=` session resumed with `--resume <id> --remote-control=<name>` does re-attach the same session | 2.1.312 (`Hydrated N entries from remote` and `hydrate_skip_zero_content_replace` in the bundle; the resume behaviour on disk, and the re-attach measured on 2.1.285/286 for a scheduled pass) | resume a throwaway of each kind and compare the link it prints with the one it had |
| `--resume <old> --fork-session --session-id <new uuid4> --remote-control=<label>` writes exactly `<new>.jsonl`, leaves the old transcript byte-identical, and prints a link. A **positional prompt** on such a start is recorded as the user's own typing: `origin: {kind: "human"}, promptSource: "typed", turnOrigin: "human"`, whatever its text says | 2.1.312, on a throwaway in an isolated home | `shasum` the old file before and after; `jq -c 'select(.type=="user")\|{promptSource,turnOrigin,origin}' <new>.jsonl \| tail -1` |
| A message sent by Claude Code's own `SendMessage`, from a headless `claude -p … --permission-mode bypassPermissions --name <sender>` helper, is **delivered** to an idle bypass session and recorded as `isMeta: true, turnOrigin: "peer", origin: {kind: "peer", name, fromMode: "bypass", verifiedPeerPid, msg_id}` — ~5–8 s, $0.002–0.006, and `SendMessage` is available without `--allowedTools`. A **hand-rolled** frame to the same session's `messagingSocketPath` is *held*: `Held peer message … The sender did not attest its permission mode and this session bypasses prompts` | 2.1.312, both on throwaway sessions in an isolated home | send one word each way to a throwaway and read its pane |
| A usage-limit stop is `isApiErrorMessage: true` with `error: "rate_limit"` — and **`apiError` is optional**: 10 of 44 real stop lines carry only `apiErrorStatus: 429` and a top-level `quotaLimits` ({`status`, `resetsAt`, `rateLimitType`}). A wake delivered before `resetsAt` is consumed and lost | 2.1.312; the 44 lines are every quota stop in the config homes on this machine, and the lost wake is the incident's own 17:46 PDT turn, 45 min inside the window | `grep -h '"isApiErrorMessage":true' <home>/projects/*/*.jsonl \| jq -c '{apiError,error,q:(.message.quotaLimits//.quotaLimits)}' \| sort \| uniq -c` |
| The CLI's own quota auto-resume is gated on `isInteractive() && !bg && !remote`, plus the `tengu_marble_heron` server flag and the `autoContinueAtUsageLimit` setting (both on by default) — so a `--print` worker, which is what a Remote Control server spawns, is never eligible. It is also an in-process wait, cancelled by `process_exit`: *"Automatic continue cancelled · Claude Code exited during the wait, so the task will not resume on its own when the usage limit resets"* (beside `background_handoff`, `relaunch`, `desktop_handoff`, `cloud_handoff`) | 2.1.312 (the gate and the five cancellation reasons in the bundle); never observed firing in any transcript in this multi-account setup | `strings <the CLI binary> \| grep -c 'Automatic continue cancelled'`, and search your own transcripts for the CLI's "usage limit has reset" continuation text |
| A fifth cold-home gate: **"Allow external CLAUDE.md file imports?"** — `confirmLabel: "Yes, allow external imports", cancelLabel: "No, disable external imports", hideIndexes: true, cancelFirst`. It **blocks** an interactive start until answered, and accepting it writes `hasClaudeMdExternalIncludesApproved` into that home's project state permanently, so the answerer walks the marker to the **No** | 2.1.312 (the construction in the bundle; live in a cold home, in a folder whose `CLAUDE.md` has an `@` import) | the dialog recipe below, in a folder whose `CLAUDE.md` imports a file from outside it |

**Re-verifying the dialog shapes safely.** Never against a live tmux server or a real config home:

```
d=$(mktemp -d); mkdir -p "$d/home" "$d/proj"              # a throwaway home and an untrusted cwd
tmux -L csm-probe -f /dev/null new-session -d -c "$d/proj" \
  "CLAUDE_CONFIG_DIR=$d/home ANTHROPIC_API_KEY=sk-not-a-real-key claude"
sleep 5; tmux -L csm-probe capture-pane -p -J            # read the dialog exactly as the tool does
tmux -L csm-probe kill-server
```

`-L csm-probe` is a **private** tmux server, so nothing here can touch your own windows; `-f /dev/null` ignores
your tmux config; the dummy key keeps the probe away from any account. The same `-L` override is available to the
test suite as `CSM_TMUX_SOCKET`.

**Re-verifying the environment families** against a CLI build:

```
strings <the CLI binary> | grep -oE '\b(CLAUDE|ANTHROPIC)[A-Z0-9_]*' | sort -u | wc -l
```

It runs to hundreds of `CLAUDE*` names and dozens of `ANTHROPIC*` ones, which is why the scrub is by family.

<a id="safety"></a>

## Safety rules

- **Nothing is written before every refusal has been checked.** A refused move leaves the target home untouched,
  and a dry run reports what a real move would refuse.
- **The source is never edited or deleted.** `--stop-source` sends `SIGTERM` to the one pid in the registry,
  after [proving](#proof) it is still that process, and only once the moved window has printed its link.
- **It never stops itself.** "Move this session" is the main use from a phone: the agent inside the session runs
  the tool on its own session. The tool recognises itself by `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PID` and its
  process ancestry, marks that row `← this session`, and leaves it running — stopping it would kill the turn
  that is about to say where the move went. `csm stop` refuses it too.
- **Two writers on one transcript is unrecoverable**, so a destination that is live in the target account is
  refused, and a quiet one is backed up before it is overwritten.
- **The environment is scrubbed by FAMILY, not by name** — for the moved session, for every tmux call (so a tmux
  *server* the tool has to start is born clean and hands that environment to every window anyone opens in it
  later), and for every `ps` call. Everything starting `CLAUDE` or `ANTHROPIC` goes, plus the two provider
  variables that carry neither prefix (`CLOUD_ML_REGION`, `AWS_BEARER_TOKEN_BEDROCK`). Only `CLAUDE_CONFIG_DIR`
  (unset for the default home) and `PATH` are set back, from the plan. The allowlist (`KEEP_EXACT`) is empty and
  is the only way to add anything.

  A list of **names** cannot be closed under names that do not exist yet, and each name a list misses is a real
  outcome: a credential (`CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, the OAuth
  refresh token) **outranks the target home's own login**, so the session moves and the quota does not, and the
  move reports success; a provider switch (`ANTHROPIC_BASE_URL`, `CLAUDE_CODE_USE_BEDROCK`,
  `CLAUDE_CODE_USE_VERTEX`) sends the window somewhere that spends neither account's subscription; identity
  variables break self-detection; preference variables leak the mover's own settings into someone else's session.

  ⚠️ It is two families plus two names, **not** a general cleanout: `AWS_PROFILE`,
  `GOOGLE_APPLICATION_CREDENTIALS` and the rest of your own auth survive on purpose, because that is how your
  work inside the moved session keeps working.
- **Dialogs are answered by reading the focus marker**, one key at a time, and an ambiguous screen gets no key at
  all ([above](#dialogs)). The bypass warning is answered only when the move deliberately starts the session in
  bypass mode.
- **Credentials are probed for existence only** — never read, printed, logged or copied — under a timeout, so no
  keychain dialog can block an unattended run.
- **tmux targets are exact** (`-t '=csm-work:=moved-1a2b3c4d'`): tmux matches prefixes otherwise. Window listings
  are read as `#{window_id} #{window_name}` and split on the first space, because a window name can contain
  spaces. Every tmux call goes through one wrapper, which is the only place the scrub, the socket override and
  the "tmux is not installed" refusal live — a call that goes around it would quietly opt out of all three.
- **The moved window outlives its process** and prints `=== claude exited rc=N`, so a failure keeps its evidence.
  `csm stop` is how it is cleaned up.

<a id="limits"></a>

## Limits

- **The move happens where the session is being resumed.** `--machine M` / `--ssh HOST` run the same command on
  another machine that has the tool installed and move between *that* machine's homes; `--from-machine M` brings a
  session here, and needs only ssh and a python over there ([above](#between-machines)). A plain non-login
  `ssh host cmd` gets a minimal `PATH`, so the remote interpreter and the tool are spelled absolutely, and
  `CSM_REMOTE_CMD` is how a machine with a wrapper of its own says where its command is — spelled `~/…`, because
  the far side's home is rarely this one's and that prefix is the only part of it the remote shell expands.
- **A folder nobody can map does not move.** Across machines, a working directory that no translation rule reaches
  and that does not exist here is a refusal, not a guess; `--mirror-cwd` is the way to bring the code.
- **A new session in the app**, with a new id and link, owned by the target account. The old link keeps pointing
  at the old copy.
- **The prompt cache starts cold**, and across organizations the preserved thinking is dropped and re-generated
  on the target's quota ([above](#cost)).
- **The last line on disk only.** A reply still being written is not in the copy.
- **A running process can rewrite the state file.** If something in the target home rewrites `.claude.json` right
  after the pre-answers, a dialog can come back; the marker-reading answerer is the fallback.
- **The quota flag is a heuristic** read off transcripts, not the meter.
- **`revive` is local to the machine the transcript is on.** `--from-machine` is refused for it, because every gate
  it turns on — is anything still writing that file, is a server up in that folder, can that home still run it — is
  a question about *that* machine; `csm --machine M revive <spec>` runs the whole thing over there instead
  ([above](#revive)). It also cannot make a server respawn a dead child, cannot wake a session except through
  Claude Code's own `SendMessage`, and never reuses a server child's session id.
- **`csm accounts` and `csm matrix` can be slow with many homes on a locked macOS keychain**: the credential
  probe is capped at 10 s per home before it falls back to "unverified".
- **Undocumented formats.** Everything above is Claude Code's internal state and can change in any release; the
  tests pin the shapes the tool depends on, and the recipes above re-measure the rest.

<a id="env"></a>

## Environment knobs

Nothing about one installation is in the code. Everything that differs between setups — the accounts table, this
machine's name, a quota meter, the path roots of other machines, a room probe, a supervisor's state directory — is a
knob with a documented default, and the tool works with none of them set. That is also what lets a wrapper supply
one setup's inputs and `exec` the tool ([README](../README.md#wrapper)); a knob already set is never overridden, so
a test or a one-off can point any of them somewhere else.

| Variable | What |
|---|---|
| `CSM_ACCOUNTS` | the accounts file (default `~/.config/claude-session-mover/accounts`). Setting it replaces discovery entirely |
| `CSM_MACHINE` | this machine's name in the accounts file's `machines` column, and as a `--machine` target (default: the short hostname) |
| `CSM_MACHINES` | per-machine path roots, as JSON: `{"<machine>": {"home": "<path>", "<label>": "<path>"}}`. Its keys join the accounts file's `machines` column as the names `--machine` accepts; its absolute string values translate a folder between machines |
| `CSM_SYNC_DIRS` | home-relative directory names that are the same synced folder on every machine, comma-separated. The rule a symlinked sync root needs |
| `CSM_METERS` | the quota meter (default `~/.config/claude-session-mover/meters.json`). Unset or unreadable means **unread**, never free |
| `CSM_METER_MAX_AGE` | how old a reading may be and still be a reading, in seconds (default 10800) |
| `CSM_AUTO_MAX_5H`, `CSM_AUTO_MAX_7D` | the percentages used at which `--to auto` skips an account and a named target is called near its limit (default 90, 95) |
| `CSM_SSH_CMD` | how ssh is invoked (default `ssh -o BatchMode=yes -o ConnectTimeout=15`: an unattended call must never sit on a password prompt) |
| `CSM_REMOTE_CMD` | how to invoke this tool on another machine, `shlex.split` then quoted token by token, except a leading `~/` or `$HOME/`, which is the home of the machine it runs on. Unset, the remote's widened `PATH` first and `$HOME/git/claude-session-mover/claude-session-mover` second |
| `CSM_REMOTE_PYTHON` | the interpreter the read-only helper is piped to (default `/usr/bin/python3`) |
| `CSM_DESKTOP_INDEX` | the desktop app's session index, read from the environment of whichever machine the session is on (default `~/Library/Application Support/Claude/claude-code-sessions`) |
| `CSM_IMPORTS` | where a cross-machine copy is staged and kept as the record of what crossed (default `<state dir>/imports`); never a `projects/` directory, and a value resolving inside one is refused before anything is fetched |
| `CSM_FIND_DAYS` | how far back `find` and `--from-machine` look without `--all`, in days (default 21) |
| `CSM_MIRROR_FILE_MAX`, `CSM_MIRROR_TOTAL_MAX` | `--mirror-cwd`'s per-file and total ceilings (default 25 MB, 2 GB) |
| `CSM_ROOM_CMD`, `CSM_ROOM_FIX` | an optional probe for whether the target account can already be reached in this folder, and the cure sentence for its note. Unset, no note is made; a probe that exits non-zero says nothing |
| `CSM_BOTS_DIR`, `CSM_BOT_FIX` | where a supervisor that owns a session keeps its `<name>.json` state (default `<state dir>/owners`), and the cure in the refusal that names it |
| `CSM_RC_JOBS_DIR` | where a **scheduled-pass** supervisor records the session each pass runs as: one `<job>.session` file of `key=value` lines whose last `uuid=` is the local id. `revive` refuses a session named there and says whose command it is. **Unset** means no such program, which is the default; unreadable is a refusal, never a "no" |
| `CSM_RELAY_MODEL`, `CSM_RELAY_TIMEOUT_S`, `CSM_RELAY_NAME` | the relay that carries the revive note: the model it runs as (default `haiku` — one instruction, one tool call, and the cost lands on the home it runs in), how long it may take in all (default 120 s, a bound for a *held* relay rather than a slow one), and the sender the app shows, templated over `{machine}` (default `csm revive ({machine})`) |
| `CSM_REVIVE_PROVE_S` | how long to wait for proof that the revived session read the note — its registry row going `busy`, or an `assistant` line past the offset taken before the relay (default 90). Passing it without proof is exit 1, never 0 |
| `CSM_REVIVE_TAIL` | how much of a transcript `revive` reads to say why a session stopped (default 1 MiB), deliberately not `CSM_TAIL_BYTES`: on the incident transcript the limit lines are in the last 512 KiB and *not* in the last 384 KiB |
| `CSM_REVIVE_NOTE_MAX`, `CSM_REVIVE_SAY_MAX` | the note's character budget (default 1500; optional clauses are dropped in a documented order, never sentences cut) and the longest `--say` (default 400; longer is refused, because it is quoted verbatim) |
| `CSM_REVIVE_LOG` | one JSON record per revive, 0600 (default `<state dir>/revive.jsonl`): the at-most-once triple, the row, the action, what was proved, the exit code — and never the note , plus `stop_uuid`, the key `csm stalled` reads back to fill `handled`. A pass that wakes sessions must point this somewhere that survives a restart |
| `CSM_WAKE_MARGIN_S`, `CSM_WAKE_MAX_AGE_H` | when a stopped session is **due**: how long after a limit's own reset a wake may be sent (default 120 s — a wake sent early is *consumed*, not queued), and how old a mid-turn kill may be and still be woken without anybody asking (default 24 h) |
| `CSM_STALLED_SINCE_H`, `CSM_STALLED_PREFILTER` | the sweep's window by a transcript's own mtime (default 48 h, `--since` overrides it), and the cheap prefilter's byte window (default 64 KiB), deliberately far smaller than `CSM_REVIVE_TAIL`: the line that says what stopped a session is at the END of its file |
| `CSM_LSOF` | how `lsof` is invoked. Only `revive` asks it, for the one question that is in no argv: which folder a Remote Control server is serving |
| `CSM_CANARY_CHUNK` | the read size of the once-per-CLI-version scan that checks the uuid5 namespace constant is really in the installed bundle (~290 MB, 0.22 s, read in chunks with a needle-sized overlap; the verdict is cached in the state dir against the bundle's path, size and mtime) |
| `CSM_LIMIT`, `CSM_ALL_LIMIT`, `CSM_ROW_TITLE` | the default row count (20), the `--all` ceiling (300), and the title width in a row (44) |
| `CSM_SHARED_HOME` | the machine's shared settings home, read first when asking what permission mode this machine asks for (default `~/.claude`). Deliberately *not* where a home's memory store is read from |
| `CSM_KEEP_ENV` | `CLAUDE*` / `ANTHROPIC*` names the scrub keeps for the moved session, comma-separated. Empty by default; a name outside those families is dropped rather than honoured |
| `CSM_STATE_DIR`, `CSM_LOG`, `CSM_PICKS` | where the log and the saved `list` numbering live (`$XDG_STATE_HOME` is honoured) |
| `CSM_CAPTURES` | where the pre-signal pane captures are written; default `<state dir>/captures` (0700, each file 0600) |
| `CSM_LOCK_WAIT` | how many seconds to wait for the CLI's `.claude.json.lock` before writing anyway with a warning (default 2) |
| `CSM_TMUX_TIMEOUT_S` | how long one `tmux` client may take to answer (default 20). Every other subprocess call in the engine carried a timeout and `tmux()` did not, while `wait_window` — the loop every move and every revive waits in — checks its deadline only *between* captures |
| `CSM_CLAUDE`, `CSM_TMUX` | the `claude` / `tmux` binaries to use |
| `CSM_TMUX_SESSION` | the tmux session a moved window is opened in, templated over `{name}`, `{handle}`, `{label}` (default `csm-{name}`); `claude-{handle}` puts it in a per-account session you already keep. `stop` looks only in the session the spelling in force names, so a window open under another spelling is invisible to it until that spelling is given back. An unknown field falls back to the default, and the result is sanitised because tmux reads `.` and `:` as window and pane |
| `CSM_HEAD_BYTES`, `CSM_TAIL_BYTES` | how much of a transcript is read per row |
| `CSM_CONNECT_WAIT`, `CSM_POLL`, `CSM_SETTLE` | how long a move waits for the link, the poll interval, how long a non-Remote-Control window must stay up |
| `CSM_BIN_DIR` | where `install.sh` links the command (default `~/.local/bin`) |
| `CSM_TMUX_SOCKET` | **tests**: `tmux -L <socket>` on every call, so the suite drives a private tmux server and a `stop` test can never kill your own windows |
| `CSM_LOGIN_PROBE` | **tests**: forces the credential-existence answer (`true`/`false`/`unknown`/`off`), announcing itself on stderr and in the log on every run |
| `CSM_NO_HOLD` | **tests**: the moved window exits instead of being held open for its scrollback |
| `CSM_REMOTE_LOCAL`, `CSM_REMOTE_HOME` | **tests**: "the other machine" is this process, with `HOME` pointed at a fixture tree, so no test touches ssh |

🛑 `CSM_LOGIN_PROBE`, `CSM_REMOTE_LOCAL` and `CSM_REMOTE_HOME` are dropped from a moved session's environment **by
name**, although `CSM_*` is outside the scrubbed families: a stale export of one of them inside a window nobody is
watching would force a safety check's answer, or make "the other machine" that process. `CSM_TMUX_SOCKET` is not
one of them — the suite needs it to reach the window it just opened.

<a id="phone"></a>

## From a phone

The repo ships a Claude Code skill, `move-session`. `./install.sh --skill` links it into every account home,
since each config home reads its own `skills/`. Then, in any session that still has quota, you say *"move my
refactor session to work"* or *"I'm out of quota, move this session to personal"*. The agent lists the
candidates, asks one question if it is ambiguous, runs the move, and answers with the account to open the app as
and the new `claude.ai/code/session_…` link — and later, *"stop the session you moved"*.

<a id="why-move"></a>

## Why move rather than pool

The other way to use several subscriptions is a proxy in front of them that rotates logins by remaining quota. A
pool answers as whichever login it picked, so nothing downstream can say which account paid for a turn, and it
cannot move a conversation that is already running. A pool on an unattended machine is also a terms-of-service
risk. The mover does something narrower: it hands a conversation to another of **your own** logins, and that
login does its own talking, on its own token, in its own app. One session, one account, in the log.

<a id="lessons"></a>

## Lessons carried into 0.2.0

The mover was first built for one person's multi-account setup and reviewed in use. Each finding became a rule:

| Finding | Rule now |
|---|---|
| a fallback answered the trust dialog by the option's number, then pressed Enter — the dialogs draw no numbers and focus the **cancel** option, so the fallback confirmed "No, exit" | answer by reading the `❯` marker; `Enter` only on the wanted label; nothing at all when a joined line holds both ([above](#dialogs)) |
| the transcript's mode was passed straight to `--permission-mode`, which hands back `auto` for a session that had been running unattended | the mode is **chosen**, never weakened, and the result is verified against what the session came up in |
| `--stop-source` checked `"claude" in ps -o command=`, which matches an editor open on a config file | prove the pid: `procStart` against `LC_ALL=C TZ=UTC ps -o lstart=`, and argv[0] as an extra condition, or refuse |
| a scrub list of variable names missed the API base URL, the provider switches and the OAuth refresh token | scrub the whole `CLAUDE*`/`ANTHROPIC*` families, put back `CLAUDE_CONFIG_DIR` and `PATH` only |
| a home whose credential had been removed still read as "signed in", so the move connected to nothing | tri-state login: signed in / gone (refuse) / could not look (warn `UNVERIFIED`) |
| every move left a `moved-…` window, and the next move of the same session was refused with no way out | `csm stop`, on csm's own fingerprint only |
| the quota flag knew one API error name of three | all three, plus the `quotaLimits` reset fallback and the "ended from the app" state |
| the moved window started with the whole conversation but no rewind history or task list | the session's side data travels too, additively |
| a move into a warm home rewrote its state file and invented a theme for it | a home that has answered both gates is not opened for writing; the backup carries an epoch, so two moves keep two backups |
| `--stop-source` fired before the connect check, so a failed move left nothing running | stop only after the link has appeared |
| a copied id matched in two accounts, and the first match was a stale copy | the live copy wins; otherwise list and ask |
| the trust pre-answer and the copy ran before the last refusal | `preflight` first: nothing is written before every check passes |
| the out-of-quota line's `<synthetic>` model was passed to `--model` | a model only from a clean line, shaped like a model id |
| a desktop session moved as `default`: its mode was beyond the head window | modes from prompt lines too, then a backwards read |
| `--stop-source` from inside the session killed the turn reporting the move | recognise self, never stop it |
| `--remote-control=` names built from titles carried `/`, `:` and `@` | a cleaned label with the provenance kept whole |
| the folder name was recomputed from the cwd with a `/`-and-`.` rule | reuse the source's folder name |
| numbered accounts swapped numbers once | accounts are named, never numbered |

More of them, grouped and generalised: [docs/lessons.md](lessons.md).

<a id="layout"></a>

## Repository and tests

| Path | What |
|---|---|
| `claude-session-mover` | the tool: one Python file, standard library only |
| `install.sh` | links `claude-session-mover` and `csm` into `~/.local/bin`; `--skill` links the skill into every account home; `--no-short-name` leaves `csm` alone, for a machine where that name is already a wrapper of your own |
| `skills/move-session/SKILL.md` | the Claude Code skill for the phone flow |
| `tests/test_mover.py` | the suite: fixtures only |
| [`README.md`](../README.md) | what it does, the matrix, the commands |
| [`CHANGELOG.md`](../CHANGELOG.md) | what changed, release by release |
| [`docs/fungibility-matrix.md`](fungibility-matrix.md) | every layer: where it lives, what is shareable, how |
| [`docs/setup.md`](setup.md) | making several accounts behave like one setup |
| [`docs/lessons.md`](lessons.md) | the generic lessons behind the rules |
| `docs/design.md` | this page |

The tests — 745 of them — run the real script against fake homes and transcripts, a fake `claude` that records its
argv and environment, and a fake `tmux` that really runs the moved window's command, alongside in-process unit
tests of the pure parts (the dialog answerer, the mode chooser, the memory resolver, the meter arithmetic, folder
translation, the matrix cells). Anything that would reach another machine runs against `CSM_REMOTE_LOCAL`, with
"over there" played by this process and a fixture `HOME`, so no test touches ssh. They need no network, no account,
no credential store and no real tmux server, and they pass on Python 3.7, 3.9, 3.12 and 3.13; CI runs them on Linux
and macOS, with one Ubuntu 22.04 cell on 3.7 so the floor this page promises is measured.

State lives in `~/.local/state/claude-session-mover/` (`$XDG_STATE_HOME` is honoured): `log`, one line per list,
move, stop, refusal and window start — asked-for and came-up-in modes included, and never a scrubbed value — and
`picks.json`, the numbering of the last `list`.

---

**Why it matters:** hitting a usage limit stops costing the conversation. The whole exchange moves to an account
with quota in under a minute, from a phone, with nobody at the keyboard — and the tool says plainly what the
move could not carry with it.
