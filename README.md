# Claude Session Mover

[![tests](https://github.com/yaroslavvb/claude-session-mover/actions/workflows/test.yml/badge.svg)](https://github.com/yaroslavvb/claude-session-mover/actions/workflows/test.yml)

`csm` moves a running [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) session from one of your
own Claude accounts to another, keeping the whole conversation. One account hits its usage limit while another has
quota to spare; instead of starting the work over and losing the thread, you move the thread. `csm` copies the
session's transcript into the other account's config home, pre-answers that home's first-run dialogs, and resumes
it there under the other login. The agent remembers everything that was said, every turn from then on is spent on
the other account, and nothing is deleted from the old one. With `--from-machine` it does the same across two
machines: the session is found on the other one, copied over ssh, and resumed here. And when a session has
stopped answering altogether — a usage limit, a restart, a Remote Control disconnect — `csm revive` reads why out
of its own transcript and brings it back, from nothing but its claude.ai link
([below](#revive-a-dead-session)).

Behind the tool is one idea: **an account is a payment layer — a login and a quota. Everything that should follow
you lives outside the account's config home and is shared.** Instructions, skills, plugins, hooks, memory and
permission defaults have no business living inside any one account's home. Move them out and switching accounts
stops being a migration; what is left is a short list of things that genuinely cannot be shared, and that list is
worth knowing by heart. It is the matrix below — and `csm matrix` prints the same table measured against your own
machine.

## The fungibility matrix

A *config home* is the directory `CLAUDE_CONFIG_DIR` points at (`~/.claude` when it is unset). One home holds one
login, so one home is one account.

Legend: ✅ fungible (shared, or `csm` carries it) · 🔧 fungible after a one-time setup · 🛑 not fungible — per
account, per config home or per machine by design · ⚠️ changes when a session moves (`csm` tells you).

| Layer | Across accounts (one machine) | Across machines | Notes |
|---|---|---|---|
| [Conversation (transcript)](docs/fungibility-matrix.md#conversation) | ✅ `csm` copies it | ✅ `csm move --from-machine` copies it | `<home>/projects/<folder>/<id>.jsonl`; the folder name comes from the absolute path |
| [Usage limits](docs/fungibility-matrix.md#quota) | 🛑 per account — the reason to move | ✅ one account, one quota, every machine | move the session; never pool credentials |
| [Login (OAuth credential)](docs/fungibility-matrix.md#login) | 🛑 one login per config home | 🛑 sign in on each machine | macOS: a Keychain item named from the literal `CLAUDE_CONFIG_DIR`; Linux: `<home>/.credentials.json` |
| [**claude.ai connectors**](docs/fungibility-matrix.md#connectors) (Gmail, Drive, Calendar, …) | 🛑 **per account — no terminal can attach one** | ✅ follow the account to every machine | enable the same set on every account at `claude.ai/customize/connectors`; a moved session sees only the target account's |
| [MCP server sign-ins (OAuth)](docs/fungibility-matrix.md#mcp-signins) | 🛑 per config home | 🛑 per machine | they live inside the login credential: `claude mcp login <server>` once per home |
| [MCP server definitions](docs/fungibility-matrix.md#mcp-definitions) | 🔧 project `.mcp.json` or a shared plugin; user-scope entries are per home | 🔧 same | prefer project or plugin scope |
| [Auto-memory](docs/fungibility-matrix.md#memory) | 🔧 point every home at one store | 🔧 a synced store, if the project path matches | `csm` never copies memory — a copy is how stores fork |
| [settings.json](docs/fungibility-matrix.md#settings) (permissions, hooks, env, enabled plugins) | 🔧 symlink every home to one file | 🔧 sync it; absolute paths inside are per machine | holds no login, so it is the safe file to share |
| [CLAUDE.md, skills, agents, commands, output styles](docs/fungibility-matrix.md#instructions) | 🔧 symlink into one shared directory | 🔧 dotfiles or a repo | project-level copies travel with the repo |
| [Plugins](docs/fungibility-matrix.md#plugins) | 🔧 symlink `plugins/` as well — enabled is not installed | 🔧 install on each machine | enabled in `settings.json`, installed in `<home>/plugins/` |
| [Scheduled tasks](docs/fungibility-matrix.md#scheduled-tasks) | 🔧 shareable, but each run bills the home that runs it | 🛑 per machine | `<home>/scheduled-tasks/` |
| [First-run and folder-trust answers](docs/fungibility-matrix.md#first-run) | 🛑 per home — `csm` pre-answers them for the folder it moves into | 🛑 per machine | `<home>/.claude.json` |
| [Bypass-mode consent](docs/fungibility-matrix.md#bypass-consent) | 🔧 comes with a shared `settings.json` | 🔧 same | `skipDangerousModePermissionPrompt` |
| [Permission mode](docs/fungibility-matrix.md#permission-mode) | ✅ `csm` chooses it — never weaker | — | `permissions.defaultMode` plus the session's own record |
| [Model, title](docs/fungibility-matrix.md#model-title) | ✅ carried | — | a title can change with the next prompt; use the link |
| [Preserved thinking](docs/fungibility-matrix.md#thinking) | ⚠️ dropped across organizations; the first turn re-reads on the target's quota | — | move early, not at the limit |
| [claude.ai session link](docs/fungibility-matrix.md#session-link) | ⚠️ a new link, owned by the target account | — | the old link still opens the old copy |
| [Process environment](docs/fungibility-matrix.md#process-env) | 🛑 never inherited — `csm` scrubs `CLAUDE*` / `ANTHROPIC*` | — | only `CLAUDE_CONFIG_DIR` is set back |
| [Rewind history, task lists](docs/fungibility-matrix.md#rewind) | ✅ `csm` copies the session's own `file-history/`, and `tasks/` where a build keeps it in the home | — | additively, never overwriting; `csm move --dry-run` lists exactly what it will copy |
| [Host tool logins](docs/fungibility-matrix.md#host-logins) (git, cloud CLIs) | ✅ shared by every account on the machine | 🛑 per machine | every home runs as the same OS user |

Three things worth saying once, because they frame the rest:

- **claude.ai connectors belong to the account, and no terminal command on any machine can attach one.** This is
  the single layer that is never fungible from a shell. Enable the identical set on each account, in a browser
  signed in as that account, or a moved session quietly loses that capability mid-task.
- **Sessions can only see and message sessions of their own account**, and no official client shows accounts on
  different emails together. The browser profile is the switch in the app; `CLAUDE_CONFIG_DIR` is the switch in the
  terminal.
- **One login holds one organization**, which is why preserved thinking does not survive a move between two
  personal accounts.

The full reference, one section per layer with the exact paths and keys, is
[docs/fungibility-matrix.md](docs/fungibility-matrix.md). The recipe for making each layer fungible is
[docs/setup.md](docs/setup.md).

### Run `csm matrix` to see your own

`csm matrix` measures the same table against the config homes on your machine. It is read-only, offline and
prompt-free: it writes nothing into any config home (only a line in its own log), never runs `claude`, never
reads a credential value (only whether one exists) and makes no network call, so it is safe from a hook or a
scheduled check. It does ask `git` for the project root, and on macOS asks the keychain whether an item exists.

Here it runs against two homes that share a settings file and a `CLAUDE.md`, but not their skills or their
plugins. The real output ends with a legend, left out here because it repeats the two lists above and below:

```
$ csm matrix
fungibility matrix on thishost
  2 config homes · project ~/code/app

layer                 v   personal                    work
--------------------  --  --------------------------  --------------------------
account               🛑  you@example.com             you@work.example
login                 🛑  ok                          ok
settings.json         🔧  shared                      shared
settings.local.json   🔧  –                           –
CLAUDE.md             🔧  shared                      shared
skills                🔧  –                           link
agents                🔧  –                           –
commands              🔧  –                           –
output-styles         🔧  –                           –
plugins               🔧  own                         own
scheduled-tasks       🔧  –                           –
plugins enabled       🔧  1 missing                   2 ok
MCP servers           🔧  –                           –
auto-memory           🔧  store                       store
onboarding            🛑  done                        done
folder trust          🛑  trusted                     trusted
permissions mode      ✅  acceptEdits                 acceptEdits
disableAutoMode       🔧  –                           –
bypass consent        🔧  accepted                    accepted
CLI version           🛑  2.1.300 (~/.local/share/claude/versions/2.1.300)
connectors            🛑  per account — granted at claude.ai/customize/connectors, not readable
                          offline
MCP sign-ins          🛑  per home — stored inside the login credential, not read

  skills: work → ~/shared-claude/skills; absent in personal; point every home's skills at one copy
  plugins: personal → ~/.claude-personal/plugins; work → ~/.claude-work/plugins; point every home's
    plugins at one copy
  plugins enabled: personal enables but has not installed charts@market; install them once in that
    home, or link every home's plugins/ to one directory so one install serves them all
  auto-memory: every home reads ~/claude-memory/projects/<project>/memory
  connectors: No file in any config home records them, and no terminal command on any machine can
    attach one, so a moved session gets the TARGET account's connectors. Enable the same set on
    every account, in a browser signed in as that account.
  MCP sign-ins: They live under an `mcpOAuth` key inside the same blob as the login, so there is no
    file to copy: `claude mcp login <server>` once per config home.

  7 of 10 shareable layer(s) agree across 2 home(s) · 3 divergent
```

Cell vocabulary: `shared` = one realpath in every home · `shared(N)` = one realpath shared by N of the homes,
not all · `own` = its own copy · `(=)` = the same bytes in separate files · `link`, `→home` = a symlink ·
`DANGLING` = a symlink to nowhere (what renaming a home leaves behind) · `–` = absent · `?` = could not look.

One realpath for every home is `shared` wherever that path lives — including inside one of the config homes,
the layout you get by sharing through the default `~/.claude`. That earns a note (rename that home and every
link into it dangles), not a divergence.

Every cell is a measurement, never a guess. `?` is not the same as `no` and is never counted as a match, so
`--check` goes red on a layer that diverges or a login that is gone, and never on an unknown.

## Quick start

Requirements: Python 3.7 or newer (standard library only), Claude Code, and tmux for the default Remote Control
mode. macOS and Linux.

```sh
git clone https://github.com/yaroslavvb/claude-session-mover
cd claude-session-mover
./install.sh                  # links claude-session-mover and csm into ~/.local/bin
./install.sh --skill          # ...and the move-session skill into every account home (for phones)
./install.sh --no-short-name  # ...the long name only, when something else owns `csm` here
```

`--no-short-name` is for a machine where `csm` is already a wrapper of your own that sets this tool's environment
and `exec`s it — see [Running it from a wrapper](#wrapper). A link installed over it would hand you the bare tool
with none of its inputs.

Each account needs its own config home, signed in once:

```sh
CLAUDE_CONFIG_DIR=~/.claude-work claude      # then /login as that account
```

`~/.claude` is the account `default` (`CLAUDE_CONFIG_DIR` unset) and every `~/.claude-<name>` directory is the
account `<name>`. To name accounts yourself, or to say which login each home must hold, write an accounts file —
see [`csm accounts`](#csm-accounts) below.

```sh
csm accounts                        # the homes found here, and who each is signed in as
csm matrix                          # what they share, and what they cannot
csm list                            # recent sessions in every account, newest first
csm move 3 --to work --dry-run      # the plan, and any refusal; nothing changes
csm move 3 --to work                # row 3 of the last list -> the account "work"
csm revive https://claude.ai/code/session_01Ab... --dry-run   # it stopped: why, and what now
csm stop 3                          # end that moved session and free its window
csm modes --check                   # one line: is any live session weaker than this machine's default
csm find "refactor" --on laptop     # where is that session, on this machine or another
csm move 7f3a --from-machine laptop --to work   # ...bring it here
```

## Commands

Three global options sit in front of the subcommand:

| option | effect |
|---|---|
| `--version` | print the version |
| `--machine M` | run this same command **on** that machine, where `csm` is installed too, so it moves sessions between two homes **over there**. It brings nothing here — `move <id> --from-machine M` is the one that does. `M` is a name the accounts file's `machines` column uses |
| `--ssh HOST` | the same thing, naming an ssh host instead of a configured machine. Any host goes: unlike `--machine`, it is not checked against the machines the configuration knows |

Both run the remote command with `BatchMode` and a connect timeout, so an unattended call can never sit on a
password prompt, and the remote leg's exit code is logged as well as its dispatch.

### `csm accounts`

The config homes on this machine, and who is signed in. `--json` for the machine-readable form. When
`CSM_METERS` points at a quota meter, each account's 5-hour and weekly usage is a column too.

Accounts are discovered by default. To name them yourself, or to pin which login each must hold, write
`~/.config/claude-session-mover/accounts` (or point `CSM_ACCOUNTS` at a file); it then replaces discovery entirely.
`#` comments, one account per line, in either of two dialects — a line holding a TAB is a table row.

**Simple**, for one machine and a handful of homes:

```
# name      home               [expected email]
default     -                  you@example.com
work        ~/.claude-work     you@work.example
personal    ~/.claude-me
```

`-` (or `default`) is the default home, i.e. `CLAUDE_CONFIG_DIR` unset.

**Table**, when the same file is read on several machines or by other tools. The columns this tool reads are taken
by name from a commented header line when there is one, and otherwise by position: 1 name, 2 email, 3 home,
6 machines, 7 handle. Every other column is ignored by design, so the file may belong to another tool.

```
# name	email	home	x	x	machines	handle
work	you@work.example	~/.claude-work	-	-	laptop,desktop	wk
personal	you@example.com	~/.claude-me	-	-	laptop	me
```

| column | what |
|---|---|
| `machines` | which machines this account is on, matched against `CSM_MACHINE` (default: this machine's short hostname). A row that names no machine (`-` or empty) is refused as a move target. A file whose `machines` names this machine nowhere lists **every** account rather than none, so an unrecognised `CSM_MACHINE` cannot read as "nothing here" |
| `handle` | a short alias that resolves wherever the name does, and is what listings print. One lower-case token of `[a-z0-9-]`, not all digits, not starting with a hyphen, unique in the file |

🛑 `home` in a **table** may not be `-`, `default` or `~/.claude`. `-` means "the default home with
`CLAUDE_CONFIG_DIR` unset", and spelling the default home out is a third thing again — any non-empty value takes
the hashed-Keychain branch and lands on an empty slot that reads exactly like signed out. A table row that wants
the default home is a row that wants a home of its own. The simple dialect keeps `-`, where there is one home and
it is unambiguous.

With an expected email, a home signed in as anyone else is refused as a move target, because the move would spend
the wrong quota. A file that mixes the two dialects, a duplicate name or a duplicate handle is refused naming the
line.

### `csm list`

Recent sessions in every account, newest first, numbered so `move 3` means the row you just read.

| flag | effect |
|---|---|
| `--account NAME` | only this account |
| `--all` | up to 300 sessions (`CSM_ALL_LIMIT`) |
| `--limit N` | **at most N rows**, the N newest, live or not — for a shorter table than the default on a small screen. An explicit `--limit` is a hard cap: it outranks `--all`, and the table says how many rows it left out, because `move 3` is numbered against *that* table. Left out, the default is 20 (`CSM_LIMIT`) and never cuts a live session |
| `--json` | the machine-readable form |

Rows are marked `● live`, `  ended`, or `  closed` when the session was ended from the app. The session you are
typing in is marked `← this session`, and a session whose last turn hit a usage limit is marked
`⚠ OUT OF QUOTA (5h|week, resets HH:MM)` — a heuristic read off the transcript, not the meter. The account column
is the account's handle where the accounts file gives one, and its name otherwise.

### `csm move`

```sh
csm move SESSION --to ACCOUNT [flags]
```

`SESSION` can be a row number from the last `csm list`, a session id or a prefix of one (4 characters or more), a
`https://claude.ai/code/session_…` link, or a piece of the title. `--to` takes an account's name, its handle, its
email, or a unique prefix of any of those. Anything ambiguous is refused with the candidates listed, never guessed,
and so is a bare number unless an account is literally named that.

| flag | effect |
|---|---|
| `--to ACCOUNT` | the account to move it to (required). `--to auto` picks the account here with the most weekly room from the quota meter `CSM_METERS` names — never the source, never an account at or over a cutoff or whose reading is stale, and it prints which one it chose and its numbers. With no fresh reading it refuses rather than guess |
| `--dry-run` | print the plan, the move note and any refusal; copy, write and start nothing |
| `--stop-source` | stop the old process once the new one has printed its claude.ai link. Only in the default Remote Control mode, where that link is the proof it connected. The source pane's scrollback is captured to `<state dir>/captures/<date>/` first, and the path is printed |
| `--no-remote-control` | start a plain interactive session in tmux, without Remote Control |
| `--foreground` | resume in this terminal instead of tmux |
| `--permission-mode MODE` | the mode to resume in: `plan`, `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions` (`manual` is an alias of `default`) |
| `--name NAME` | the Remote Control name of the moved session |
| `--all` | search every session, not just the newest |
| `--from-machine M` | bring the session **from** that machine to this one: it is found there in every config home, the default one the desktop app uses included, copied over ssh, and resumed here. The source is **never** stopped — a process over there may be driving work this tool cannot see — and the plan lists what it started that is still running |
| `--mirror-cwd` | with `--from-machine`, when the session's folder is not on this machine: copy its **code** across first — git-tracked and untracked files, never the ignored ones, each under 25 MB, `.git` included. Data stays where it was made. A folder that already exists here is never written into |
| `--copy-only` | do every refusal, the first-run gates, the copy and the move note — and start nothing. For a program that resumes the copy itself, under its own supervision |
| `--from-account ACCOUNT` | take the copy in that account's home, when an earlier move left the same session id in more than one |

Without `--permission-mode`, the mode the session was running in is used, raised to the target home's
`permissions.defaultMode` when that is stronger **and** the session recorded nothing, `default` or `auto` — an
automatic choice never weakens a session, and the plan line names where the choice came from. An explicit
`--permission-mode` is obeyed as given, including a weaker one.

A successful move prints the account to open the app as, the new `https://claude.ai/code/session_…` link, the tmux
window it runs in, and what the move cost.

**Every move appends a move note to the copy**, and only to the copy — except under one shared `projects/` tree,
where the copy *is* the source and that one file is the only place the resumed session could read it: one hidden
line (`isMeta`, the shape the CLI uses for its own reminders) chained to the last line of the conversation by
`parentUuid`. A resumed session reads its transcript as
its own past, and after a move the account, the folder and the machine every earlier turn names can all be wrong —
measured: a session resumed on another machine went looking for a process it had started on the old one. The note
states what changed under it, what above it is now stale, where auto-memory is read from and, on a cross-machine
move, what stayed behind and what the code mirror brought. Because it is in the transcript it survives a restart, a
later move and a compaction's re-read. `--dry-run` prints it and writes nothing.

**Across machines** the session's folder is translated into this machine's spelling where the configuration says
how (`CSM_MACHINES`, `CSM_SYNC_DIRS`); otherwise a folder that is not here is a refusal rather than a resume in the
wrong place. The transcript and its sibling directory cross in one `tar` pipe over ssh into `CSM_IMPORTS`, which
stays as the record of what crossed, and from there the move is the ordinary one. Moving to the **same** account on
another machine is allowed: it changes the machine, not the quota.

**A session something else owns is refused.** Where `CSM_BOTS_DIR` names a supervisor that keeps one persistent
session (a bot, a chat bridge, a service), a plain `move` of that session would start a second copy nothing is
talking to while the supervisor kept answering on the old account. The refusal names the owner, and `--copy-only`
is the entry point such a supervisor uses to change account itself.

### `csm revive`

```sh
csm revive SESSION [flags]
```

Brings back a session that stopped — a usage limit, a restart, a Remote Control disconnect, a kill mid-turn. It
reads **why** it stopped out of the transcript, whether anything is still running it, how much quota its account
has and whether anything else owns it, and then takes the first row of its decide table that matches. The whole
narrative, the table in plain words and what it cannot do are in
[Revive a dead session](#revive-a-dead-session) below.

| flag | effect |
|---|---|
| `--dry-run` | print the plan — the row it would take, the note it would send, any refusal — and start, wake, move and write nothing |
| `--json` | the diagnosis record, the decision and the note, as JSON. The prose goes to stderr, so stdout stays parseable |
| `--to ACCOUNT` | move it to that account instead of reviving it where it is (`auto` for the one with the most weekly room). It is also the cure for a limit that is still in force |
| `--new-link` | a fresh copy on a new link: **fork** the dead session to a new session id and a new link, leaving its transcript byte-identical. It is the only way back for a Remote Control **server child**, which cannot be resumed onto its own link at all, and on a dead self-hosted or terminal session it forks instead of resuming in place (row 11). The old link, where there was one, still opens the old copy. On a row that forks nothing — live, a move, a refusal — the output says it was **not** carried out, and why |
| `--account NAME` | which home's copy to revive. Only needed when a move has left copies of one id in more than one home and none of them is running — revive refuses rather than choose, the same as `move` and `stop` |
| `--say TEXT` | one thing to pass on to the revived session, quoted verbatim and attributed to you. At most 400 characters, and it may not start with `!` or `/`, which the CLI would run as a command |
| `--permission-mode MODE` | the mode to come back in. Without it, the mode the session recorded, by the same rule as `move`. ⚠️ It is applied only on the rows that START a process (6, 7, 8, 10, 11); on a wake, on row 3, on row 9 and on a refusal nothing is started, so the mode line REPORTS what the session is already in (`unchanged: …`, `applied: false` in `--json`) and the flag is named as not carried out |
| `--unarchive` | resume a session that was archived or ended from the app, which unarchives it. Refused without this flag |
| `--name NAME` | the Remote Control name the revived session gets |
| `--from-machine M` | refused, and says so: every gate a revive turns on is a question about the machine the transcript is on. Run `csm --machine M revive <spec>` instead, which does the whole thing over there |

**Exit codes are the answer an unattended caller reads**: `0` the session took a turn (or there was nothing to
do, or the one thing to tap was printed), `1` something is **up** and nothing proved it read the note, `2`
nothing was started at all.

### `csm stop`

```sh
csm stop SESSION [--dry-run]
```

Ends a session **this tool moved** and removes the tmux window it opened: the cleanup, and the unblocker for moving
the same session to the same account again. It stops nothing else. The authorisation is `csm`'s own window
(`moved-<id8>` in `csm-<account>`) plus, for a running session, a live registry row naming that same window; the pid
is signalled only after its identity is proved. Killing the window SIGHUPs the pane's process tree, which the
output says plainly. The transcript is never deleted.

Before anything is signalled, the pane's whole scrollback is written to `<state dir>/captures/<date>/` (0600, in a
0700 directory) and the path is printed. A prompt the agent had typed and not yet sent exists nowhere else, and
`tmux kill-window` destroys the pane with the process. The capture can never fail the stop; `--dry-run` writes
nothing. `csm move --stop-source` captures the source pane the same way. Those files hold conversation text — they
are deliberately per-machine, under your state directory, and should not be synced or served.

### `csm find`

```sh
csm find "refactor"             # every config home on this machine, the default one included
csm find 7f3a --on laptop       # ...on another machine, over ssh, read-only
csm find "refactor" --all --json
```

Finds a session by id or prefix (the CLI's uuid, or the desktop app's `local_` id), by a `claude.ai` link, or by
title text, in **every** config home on a machine — including the default one, where the desktop app keeps its
sessions — and by the desktop app's own titles, which are in no transcript. The row it prints is what
`csm move <id> --from-machine M` takes. `--on M` runs the search over there by piping a small standard-library
helper to that machine's system python, so nothing has to be installed on it; `--all` widens the window from 21
days (`CSM_FIND_DAYS`) to everything.

Two things the table cannot tell you: the **age column is the transcript file's last write**, not the last turn, so
a dead copy can read as minutes old; and **a move is a copy**, so a session that has been moved shows up as two
rows, one per home.

**Exit codes:** `0` with rows, `1` when nothing matched — never "the search failed". A caller that wants rows
counts `--json` (which is `[]`, with the hint on stderr so stdout stays parseable). On no match it prints
**🛑 0 rows is not proof** that the session is gone: this searches transcript ids and titles, and a session that
has stopped has no registry row while a Remote Control session usually has no title either — so paste its
`claude.ai` link, which names the transcript by arithmetic. A config home it was not allowed to read is named as
unread rather than counted as empty.

### `csm modes`

```sh
csm modes                       # the table: which live sessions are weaker, and why
csm modes --account work
csm modes --json                # every live row, the verdicts, the counts, the coverage
csm modes --check               # ONE line. exit 0 ok, 1 a fault, 3 something could not be read
csm modes --restart-idle        # the plan for the idle ones; it signals nothing
```

Every live session in every config home here, the mode it is **really** in, and whether that is weaker than this
machine's `permissions.defaultMode`. It is the complement of a settings check: a settings file can be right while a
worker a Remote Control server spawned sits in `auto`, because such a worker records the mode the stored session
record holds, not the one its server was started with — so a session in the wrong mode is invisible to a check that
reads the file. Read-only, apart from `--restart-idle --apply`.

- It reads **every** live registry row, including the ones `csm list` drops: a server's pre-created session has a
  0-byte transcript.
- When a transcript records no mode it reads the mode off the process's own command line — a measurement, not a
  guess. What it still could not read goes in `coverage.unread` with a reason, and the exit code is **3**: unknown
  is never `ok`. That command line comes from one `ps` for the whole machine; `coverage.ps` in `--json` says
  whether it answered, because a `ps` that could not be asked is not a machine with nothing running on it.
- A **fault** is only a Remote Control worker in a mode such a worker records by accident (nothing, `default`,
  `auto`). `plan`, `acceptEdits` and anything started in a terminal are reported as **info** and never restarted;
  an unfamiliar mode is **unknown** and never judged.
- `--check` writes exactly one line to stdout and **nothing** to stderr, so a scheduled check can match its prefix
  (`ok:`, `FAULT:`, `INCOMPLETE:`) and agree with the exit code. Every diagnostic on that path goes to the log.
- `--restart-idle` prints which idle workers a restart would SIGTERM to bring them back in their server's mode, and
  why each other row is refused: never a server, never a session hosting itself, never this session, never a busy
  one, never a pid whose recorded start time does not prove it. 🛑 `--apply` is **gated**: while the mode a
  respawned worker comes back in is unverified it refuses and signals nothing (exit 2). **No environment variable
  can open that gate** — a constant in the file is the only switch, because a stray variable in a scheduled pass's
  environment must never be able to stop your sessions.

### `csm matrix`

```sh
csm matrix                      # the whole table for the current directory
csm matrix --cwd ~/code/app     # evaluate the first-run gates for that folder
csm matrix --account work,personal
csm matrix --json
csm matrix --check              # exit 1 when a shareable layer diverges or a login is gone
```

| flag | effect |
|---|---|
| `--json` | the whole table as JSON: homes, rows, cells, summary, exit |
| `--cwd DIR` | the project the first-run gates and the memory row are measured for (default: the current directory) |
| `--account NAME` | only these columns; repeatable, or one comma-separated list |
| `--check` | exit 1 when a shareable layer diverges or a login is gone. An unknown never fails it: a cell nobody could read is not a fault |

`--check` is about the homes. It does not go red for connectors, which no config home can fix, nor for a layer you
simply have not set up yet.

### Environment

Nothing about one setup is in the code: an accounts table, a machine's name, a quota meter, a room probe and the
rest are all knobs, with a documented default and a tool that works with none of them set.

**Accounts and machines**

| variable | effect |
|---|---|
| `CSM_ACCOUNTS` | the accounts file to read instead of `~/.config/claude-session-mover/accounts`. Setting it replaces discovery entirely |
| `CSM_MACHINE` | what this machine is called in the accounts file's `machines` column, and as a `--machine` target (default: the short hostname). An unrecognised value lists every account rather than none |
| `CSM_MACHINES` | per-machine path roots, as JSON: `{"<machine>": {"home": "<path>", "<label>": "<path>"}}`. Its keys join the accounts file's `machines` column as the names `--machine` accepts — when both are empty, any host goes; its absolute string values are what translate a folder from one machine's spelling to another's |
| `CSM_SYNC_DIRS` | home-relative directory names that are **the same synced folder on every machine**, comma-separated (`work,shared`). Such a directory is usually a symlink into a sync client's tree, which no named root above ever matches, so this is the rule that translates it |

**Quota**

| variable | effect |
|---|---|
| `CSM_METERS` | a quota meter, as JSON: `{"<account name or handle>": {"five_hour": <percent used>, "seven_day": <percent used>, "at": <epoch>}}`. Unset or unreadable means the meter is **unread**, never "free": `--to auto` then refuses, `csm accounts` prints no meter column, and the plan falls back to the transcript evidence |
| `CSM_METER_MAX_AGE` | how old a reading may be and still be a reading, in seconds (default 10800). Older is unread |
| `CSM_AUTO_MAX_5H`, `CSM_AUTO_MAX_7D` | `--to auto` skips an account at or over these percentages used, and the same two numbers make a *named* target "near its limit" in the plan (default 90, 95) |

**Another machine**

| variable | effect |
|---|---|
| `CSM_SSH_CMD` | how ssh is invoked (default `ssh -o BatchMode=yes -o ConnectTimeout=15`). The defaults matter: a plain `ssh` meeting a host it has no key for sits on a password prompt forever, and nothing times out the check that called it |
| `CSM_REMOTE_CMD` | how to invoke this tool **on** the other machine, `shlex.split` and then quoted token by token, so a multi-word command survives. A token may begin `~/` or `$HOME/`, which means the home of the machine it runs *on*. Unset, the remote's widened `PATH` is tried first and `$HOME/git/claude-session-mover/claude-session-mover` second |
| `CSM_REMOTE_PYTHON` | the interpreter the read-only `find` / `--from-machine` helper is piped to (default `/usr/bin/python3`). The helper is standard-library-only, so a machine with nothing installed still answers |
| `CSM_DESKTOP_INDEX` | the desktop app's session index, where a session it opened keeps its title (default `~/Library/Application Support/Claude/claude-code-sessions`). It is read from the environment of whichever machine the session is on |
| `CSM_IMPORTS` | where a copy from another machine is staged, and kept as the record of what crossed (default `<state dir>/imports`). 🛑 Never a `projects/` directory, and a value inside one is **refused**: a leftover staging file is deleted before the fetch, so a `projects/` here would delete that home's own transcript |
| `CSM_FIND_DAYS` | how far back `find` and `--from-machine` look without `--all`, in days (default 21) |
| `CSM_MIRROR_FILE_MAX`, `CSM_MIRROR_TOTAL_MAX` | `--mirror-cwd`'s per-file and total ceilings (default 25 MB, 2 GB). Code crosses, data does not |

**Notes the plan can make**

| variable | effect |
|---|---|
| `CSM_ROOM_CMD` | an optional probe for whether the **target** account can already be reached in this folder by whatever runs sessions here for it: a command template carrying `{handle}`, whose stdout is a table whose fourth field is a folder. Unset, no such note is made. A probe that exits non-zero says **nothing**: "could not look" is never a verdict |
| `CSM_ROOM_FIX` | the cure appended to that note, a template carrying `{handle}`, `{name}` and `{cwd}`. Unset, only the fact is printed — inventing a command is worse than naming none |
| `CSM_BOTS_DIR` | where a supervisor that owns a session keeps its state: one `<name>.json` per owner, each with a `session_id`. A plain `move` of a session named there is refused (default `<state dir>/owners`; absent means no session is owned) |
| `CSM_BOT_FIX` | the cure in that refusal, a template carrying `{owner}`, `{to}` and `{id}` |
| `CSM_RC_JOBS_DIR` | where a **scheduled-pass** supervisor records the session each of its passes runs as: one `<job>.session` file of `key=value` lines, whose last `uuid=` is the local session id. Such a pass has a revive of its own that puts it back on the same link, so `csm revive` refuses a session named there and says whose command it is. **Unset means nothing is owned this way**, because the default installation has no such program; a directory that cannot be read is a refusal, never a "no" |

**Reviving**

| variable | effect |
|---|---|
| `CSM_RELAY_MODEL` | the model the relay runs as (default `haiku`). It reads one instruction and makes one tool call, so the cheapest one is the right one — and it is a knob because the cost lands on whichever account's home the relay runs in |
| `CSM_RELAY_TIMEOUT_S` | how long the relay may take in all (default 120). Measured ~8 s per wake, so the bound is not for a slow relay but for a **held** one: a relay that stops to ask a person has to come back as "started, not proved" instead of hanging an unattended run |
| `CSM_RELAY_NAME` | the name the relay runs under, which is the sender the app shows beside the message, templated over `{machine}` (default `csm revive ({machine})`). Deliberately not a person's name and not the revived session's: the reader has to see at a glance that a tool sent it |
| `CSM_REVIVE_PROVE_S` | how long to wait for **proof** that the revived session read the note — its registry row going `busy`, or an `assistant` line past the offset taken before the relay (default 90). A bounded machine wait; passing it without proof is exit 1, never 0 |
| `CSM_REVIVE_TAIL` | how much of a transcript `revive` reads to say why a session stopped (default 1 MiB) — deliberately **not** the listing's `CSM_TAIL_BYTES`, whose 384 KiB window misses the limit lines of a long agentic session |
| `CSM_REVIVE_NOTE_MAX`, `CSM_REVIVE_SAY_MAX` | the revive note's budget in characters (default 1500; optional clauses are *dropped* to meet it, never sentences cut) and the longest `--say` (default 400; a longer one is refused rather than shortened, because it is quoted verbatim) |
| `CSM_REVIVE_LOG` | one JSON record per revive, 0600 (default `<state dir>/revive.jsonl`): what was decided, what ran, what was proved — and never the note, which is conversation text |
| `CSM_LSOF` | how `lsof` is invoked. Only `revive` asks it, and only for the one question that is in no process's argv: which folder a Remote Control server is serving |

**Listing, state and binaries**

| variable | effect |
|---|---|
| `CSM_LIMIT` | how many sessions `list` shows when nothing was asked for (default 20) |
| `CSM_ALL_LIMIT` | the ceiling `--all` has (default 300) |
| `CSM_ROW_TITLE` | how much of a title a listing row shows (default 44; `--json` keeps the whole thing) |
| `CSM_STATE_DIR` | the **state dir**: where the log and the `list` numbering are kept (default `$XDG_STATE_HOME/claude-session-mover`, falling back to `~/.local/state/claude-session-mover`) |
| `CSM_LOG` | the log file itself (default `<state dir>/log`) |
| `CSM_PICKS` | where `list` leaves its numbering, so `move 3` means the row you just read (default `<state dir>/picks.json`) |
| `CSM_CAPTURES` | where the pane captures `csm stop` and `csm move --stop-source` write are kept (default `<state dir>/captures`, 0700, each file 0600) |
| `CSM_SHARED_HOME` | the machine's shared settings home: the one `settings.json` several homes may symlink to, read **first** when asking what permission mode this machine asks for (default `~/.claude`). It is deliberately *not* where a home's memory store is read from — that is a question about one home, and the CLI answers it from that home's own settings |
| `CSM_KEEP_ENV` | `CLAUDE*` / `ANTHROPIC*` variable names the environment scrub keeps for the moved session, comma-separated. Empty by default; a name outside those two families is dropped rather than honoured, so this cannot become a general allowlist. What it is for is a tool *inside* the moved session that needs the same input this one had — most usefully the path of an accounts file |
| `CSM_CLAUDE` | the `claude` binary, when it is not on `PATH` |
| `CSM_TMUX` | the `tmux` binary, when it is not on `PATH` |
| `CSM_CONNECT_WAIT` | seconds to wait for the moved window's claude.ai link (default 150) |
| `CSM_LOCK_WAIT` | seconds to wait for the CLI's `.claude.json.lock` before writing anyway with a warning (default 2) |
| `CSM_TMUX_SESSION` | the tmux session a moved window is opened in, as a template over `{name}`, `{handle}` and `{label}` (default `csm-{name}`). Set it to `claude-{handle}` if you already keep a tmux session per account and want moved windows there. 🛑 `csm stop` finds a moved window only in the session the spelling in force names, so changing this while one is open hides it from `stop`: close those windows first, or name the spelling they were opened under. A template naming a field it does not know falls back to the default; `.` and `:` are replaced, because tmux reads them as window and pane, and a leading `-` is dropped, because the name is passed to `tmux -s` and `-t` |
| `CSM_TMUX_SOCKET` | add `-L <socket>` to every `tmux` call, to keep `csm`'s windows on a server of their own |
| `CSM_TMUX_TIMEOUT_S` | how long one `tmux` client may take to answer (default 20). `wait_window` checks its deadline only *between* captures, so one blocking tmux client would otherwise be an unbounded hang inside a bounded wait |
| `CSM_LOGIN_PROBE` | `true`, `false`, `unknown` or `off` — force the answer of the credential-existence check instead of asking the store, for a machine where asking it is not possible. It announces itself on stderr and in the log on every run |
| `CSM_BIN_DIR` | where `install.sh` links the command (default `~/.local/bin`) |

Four knobs are for the test suite and for a machine where the credential store cannot be asked: `CSM_LOGIN_PROBE`
and `CSM_TMUX_SOCKET` above, `CSM_NO_HOLD`, which the table leaves out because it drops the held-open window a
move's scrollback is read from, and `CSM_REMOTE_LOCAL` / `CSM_REMOTE_HOME`, which make "the other machine" this
process with `HOME` pointed at a fixture tree. Three of them — `CSM_LOGIN_PROBE`, `CSM_REMOTE_LOCAL`,
`CSM_REMOTE_HOME` — are dropped from a moved session's environment **by name**, although `CSM_*` is outside the
scrubbed families, so a stale export cannot follow a real move. The tuning internals (`CSM_HEAD_BYTES`,
`CSM_TAIL_BYTES`, `CSM_POLL`, `CSM_SETTLE`, `CSM_CANARY_CHUNK`) and the full list are in
[docs/design.md](docs/design.md#env).

<a id="wrapper"></a>

### Running it from a wrapper

A setup with more than a couple of accounts usually has inputs of its own: an accounts table some other script
already owns, a quota meter a scheduled job writes, a machine name that is not the hostname, a log everything else
writes to. None of that belongs in this tool, so the arrangement that keeps working is a small wrapper that sets
the `CSM_*` variables and `exec`s `claude-session-mover`. Nothing is parsed or reformatted on the way through, so
every output contract above stays the tool's own. Have the wrapper set each variable only when it is unset: that is
what lets a test, or you for one command, point a knob somewhere else.

Install with `./install.sh --no-short-name` on such a machine, so `~/.local/bin/csm` cannot shadow the wrapper, and
set `CSM_REMOTE_CMD` to the wrapper's own path: a `--machine M` leg then runs *that* machine's wrapper, with that
machine's table, meter and log, instead of a bare tool with no inputs. Spell that path `~/…`, not absolutely —
two machines rarely share a home directory, and a leading `~/` is the one part of this variable that the far
side's shell expands.

## What a move does

1. **Find.** Scan every account home's transcripts — a head and a tail of each file, never a full parse — and its
   live registry, `sessions/<pid>.json`. With `--from-machine`, the same scan runs on that machine instead, and the
   transcript is fetched into the staging directory first.
2. **Refuse early.** Every check runs before the first byte is written, and each refusal says what to do instead.
   Refused: a move to the same account, a target that holds no login or the same login, a target whose credential
   is gone, a working directory that no longer exists, a destination copy that is already running, and a window
   from an earlier move of the same session.
3. **Copy.** The transcript and its sibling directory go into the target home under the source's own project folder
   name, together with the session's own side data outside `projects/` — rewind history, and task lists where a
   build keeps them in the home — when it has any, additively and never overwriting. Memory is never copied, in
   any configuration. The move is refused if the target already holds this session id in a *different* project
   folder, because `--resume` then has two files to choose between.
4. **Pre-answer.** The target's workspace-trust dialog for that directory, and its onboarding, are answered in its
   state file: additively, atomically, with a backup, keeping the file's mode.
5. **Note.** The move note is appended to the copy: what changed under this session, and what above it is stale.
6. **Resume.** `claude --resume <id> --remote-control=<title> --permission-mode <mode> --model <model>` runs in a
   detached tmux window `moved-<id8>` of the tmux session `csm-<account>`, under the target's `CLAUDE_CONFIG_DIR`,
   in the session's recorded working directory, with a scrubbed environment.
7. **Prove.** Wait for the claude.ai link in the pane; only then, with `--stop-source`, stop the old process. A
   move that does not connect leaves the source running and keeps the window with its scrollback.

`--copy-only` stops after step 5 and starts nothing, for a program that resumes the copy itself.

Should a dialog still appear in the new window, it is answered by reading the focus marker (`❯`) one poll at a
time: Down only while the marker is not on the wanted option, Enter only when the marker's own line names that
option, and no key at all when the pane is ambiguous. Never a digit, never a canned sequence — a cold home's
dialogs put the cancelling answer first and focused, so a blind Enter declines.

**Homes that share one `projects/` tree.** If two homes' `projects/` resolve to the same directory (both symlinked
into one tree, say), `csm` compares by resolved path, not by spelling. `csm list` shows one row per transcript, not
one per home, and names the home running it. A move between two such homes copies nothing — the file the target
resumes is already the file the source uses — so there is no copy, no backup and no sibling copy, and side data
that is one directory in both homes is skipped too — only the move note is appended, to that one file. The
live-twin refusal asks every home on the machine (the default home first, because the desktop app registers its
sessions there and no accounts-file row names that home), because the process holding a shared transcript can
belong to a third account. Leaving the
source running then means two CLIs append to one file, so the plan says so and names `--stop-source`. Read
[LESSONS.md § D](LESSONS.md#d) before choosing this layout.

## What a move costs, and what it cannot carry

`csm move` prints the ones that apply before and after the move. In short:

- **Preserved thinking is dropped across organizations.** It is bound to the organization that wrote it, so the CLI
  discards it and the first turn **re-reads the whole session — on the new account's quota**. Move early, while
  there is quota to spare: a long session moved at the limit spends a slice of the quota it was moved to find. Two
  homes in the same organization keep it, and the tool says so when it can read both.
- **A new claude.ai link, owned by the target account.** The old link still opens the source account's copy. The
  moved agent has the whole conversation locally; the app may show the thread starting at the move.
- **Connectors and MCP sign-ins are the target's.** Connectors belong to the account and cannot be attached from
  any terminal; MCP OAuth tokens live inside the login credential, so they are per config home
  (`claude mcp login <server>`). `csm` lists the ones the session actually used, so you can see what it is about to
  lose.
- **Plugins, skills, agents and commands are the target home's**, even when one shared `settings.json` enables the
  same plugins everywhere — enabled is not installed. `csm` warns when the target lacks something the source had.
- **Memory is per home unless you shared it.** `csm` never copies a memory directory, in any configuration,
  because copying is how stores fork; it reports whether the two homes resolve to the same store.
- **The prompt cache starts cold**, so the first turn after a move is slower.
- **The copy ends at the last line on disk.** A reply still being written is not in it.
- **The transcript still names the source account inside itself** — paths and the recorded email from earlier turns
  — so the moved session will describe itself as the old account until its context is rebuilt.

## Revive a dead session

A move is for a session that is still running. `csm revive` is for the one that is **not**: the account hit its
usage limit and the turn died on a 429, the machine restarted under it, Remote Control disconnected, something
killed it mid-turn. Paste the claude.ai link — usually the only name you still have for it, because such a
session has no registry row and often no title — and it answers two questions in one go: *why did it stop*, and
*what brings it back*.

```sh
csm revive https://claude.ai/code/session_01Ab... --dry-run   # why it stopped, and what reviving it would do
csm revive https://claude.ai/code/session_01Ab...             # ...do it
csm revive 7f3a --to auto --say "skip the card run, just write the findings up"
csm revive 7f3a --new-link                                    # fork a dead session onto a new link, fresh copy
```

**When to use it, and when to just open the session and say *continue*.** If the session is a Remote Control one
whose folder still has a `claude remote-control` server running, opening its link in the app and typing
*continue* is the better answer: the server respawns the worker itself, and you keep the link, the title, the
account and the quota window. Nothing local can make that happen — the respawn is the server's decision, taken
when the session next gets activity — so `revive` detects exactly that case, prints the one thing to tap, and
starts nothing (row 9). Reach for `revive` instead when **nobody is at the keyboard**, when you **do not know why
it stopped**, when the account it was on **has no quota left** (`--to auto` moves it to the one that does), or
when the thing you actually need to know is whether its **last tool call ever ran**.

### What it decides, in order

The first row that matches wins — a session that is both out of quota and dead is answered about the quota,
because starting it would spend its first turn hitting the same wall.

| # | when | what it does |
|---|---|---|
| 1 | something else owns the session: a supervisor in `CSM_BOTS_DIR`, a scheduled pass in `CSM_RC_JOBS_DIR` | **refuses**, naming that owner's own revive command. A second copy would answer nobody while the owner kept answering |
| 2 | the transcript holds no conversation (0 bytes, or no main-chain line — a Remote Control server pre-creates such sessions) | **refuses**: there is nothing to continue |
| 3 | it is live and **busy** | **nothing to do** — it is working right now, and a message would join the turn it is in the middle of |
| 4 | it stopped on a usage limit that is **still in force**, and no `--to` | **refuses**, with the reset in local time and the cures: wait until then and run it again, or `--to auto` now. For a monthly-spend, credits or model limit it says that waiting does not clear it at all |
| 5 | it is live and **idle** (a lazy respawn, or you opened the link) | **wakes it**: nothing is started, the note is relayed in. ⚠️ A `--to`, a `--new-link` or a `--permission-mode` is *not* carried out here, and the output says so for each: a move or a fork copies a transcript and this one has a live writer, so stop it first, and a mode is applied to a process this row starts none of |
| 6 | `--to ACCOUNT` or `--to auto` | **moves it** — an ordinary `csm move`, with its copy, its own move note and its printed cost — and then relays the revive note into the copy |
| 7 | dead, a **self-hosted** Remote Control session (it wrote its own `bridge-session` line), same account, no `--new-link` | **resumes it in place, on the same claude.ai link**. Archived or ended from the app is refused unless `--unarchive` |
| 8 | dead, a **terminal** session, same account, no `--new-link` | **resumes it in place** — and it gets a **new** claude.ai link, which the output says loudly: it was never a Remote Control session, so that is new exposure, not a restoration |
| 9 | dead, a Remote Control **server child**, same account, no `--new-link` | **prints the one thing to tap** — open the link and say *continue* — plus whether that folder's server is up, and starts nothing and waits for nothing |
| 10 | dead, a server child, same account, `--new-link` | **forks it**: `--resume <old> --fork-session --session-id <new uuid4>`, so a new id, a new link, the same past. The old transcript is left byte-identical and the old link still opens the **old** copy — archive it and do not type there |
| 11 | dead, a **self-hosted** or **terminal** session, same account, `--new-link` | **forks it too**, by row 10's mechanics: `--new-link` asks for a fresh copy on a new link, whatever kind the dead session is. For a self-hosted one the link it had still opens the **old** copy; a terminal one never had a link, so the output warns about the old **copy** instead and names no link it cannot name |

Rows 7–11 are mutually exclusive by kind and by `--new-link`, so their order among themselves is not
what decides; everything that depends on the order is in rows 1–6. Row 11 is a row *number*, not a position in
the walk — it is reached from inside the same two branches as rows 7 and 8, and was added rather than renumbered
because the row number is in `--json`, in `revive.jsonl` and in every record already written.

Which kind of session it is, is **proved, never guessed**: a server child's local transcript id *is*
`uuid5` of its bridge session's API url, so the link, its registry row or an orphan `~/.claude/bridge-spawn/`
directory that derives to this transcript's name all prove it. The registry's `entrypoint` is deliberately not
used — it says how a process was started, and a fork or a resume rewrites it.

And when none of those four sources still exists — which is the ordinary state of a dead child named by its own
id or by part of its title: no registry row, no bridge line in its own file, and no `bridge-spawn` directory once
it exited cleanly — the id's **uuid version** settles it on its own. A child's id is a `uuid5`; every other
session gets a random `uuid4`. Such a session takes row 9 or, with `--new-link`, row 10, and the output asks for
the link rather than printing one it cannot name. It must never take row 8: that would start a second process on
the old local id, which a later lazy respawn of the old link shares.

The `action` string in `--json` and in `revive.jsonl` is one of `refuse`, `nothing`, `wake`, `move`, `resume`,
`resume-new-link` (row 8), `keep-link` (row 9) and `fork` (rows 10 and 11) — see the mapping in
[docs/design.md](docs/design.md#the-decide-table).

**A flag that was not carried out says so**, in the second line and in `--json`'s `decision.dropped`: `--to` on a
row that is not a move, `--say` on a row that sends no note, `--new-link` on a row that forks nothing, and
`--permission-mode` on a row that starts no process. And `--json`'s `mode` block carries **`applied`**: `true`
only on the rows that start a process (6, 7, 8, 10, 11), where the mode really is the one in that process's
command line. On every other row the block reports the mode the session is **already in**, measured from its own
command line and from the last `permissionMode` its transcript recorded, with `why` beginning `unchanged:`; when
the two measurements disagree the **stronger** one is reported, because a Remote Control worker records `auto`
while its server's argv says `bypassPermissions`, and a mode neither source names reads `unknown` — never
`default`.

### The three-line answer

Everything above the detail block is what gets read out on a phone: **what stopped it and when · what revive
would do · the one risk**.

```
REVIVE  the refactor sweep   (work, bf974a77)
  1 stopped Tue 27 Oct 17:46 (19h ago): it hit a session limit, which resets 18:30 — that reset has passed
  2 FORK it: a new session id, a new link, the same past
  3 risk: the OLD link still opens the OLD copy — two conversations with one history, so archive the old
          one and do not type there
```

(then the detail block — what it is and how that was proved, its state, the stop, lost work, the account and
its meter, whether a server is up in that folder, who else owns it, the link, the folder, the mode, the row it
took — and then the note itself.)

The risk line is worst-first and outranks the row's own mechanism: an unanswered tool call, an archive somebody
made on purpose, and the agents a frozen workflow run lost each change what you should do next. Why it stopped
is **parsed as JSON lines over the last 1 MiB** (`CSM_REVIVE_TAIL`), from the last real prompt forward, never
grepped — a text match on the tail says "out of quota" about any session that merely discussed one, and the
listing's 384 KiB window misses the limit lines of a long agentic session entirely.

### How the note gets in: one carrier, and it is a relay

Whatever row it takes, the session comes up (or is found) as an ordinary **idle** process with no prompt of its
own, and the note is then delivered to it by a headless Claude of its own:

```
claude -p --model haiku --permission-mode bypassPermissions --name "csm revive (<machine>)" \
       --output-format json "<call SendMessage once, to '<that session's name>', with this text verbatim>"
```

run under that session's own config home with the environment scrubbed, stdin closed, in a folder of csm's own
under the state dir, bounded by `CSM_RELAY_TIMEOUT_S`. Measured on CLI 2.1.312 (Wed 28 Oct 2026): ~5–8 s and
$0.002–0.006 per wake, and it lands recorded for what it is — `isMeta: true, turnOrigin: "peer", origin:
{kind: "peer", name: "csm revive (<machine>)", fromMode: "bypass", verifiedPeerPid, msg_id}` — with the app
showing it as a message from that sender. **Honest attribution is the whole reason for the detour.** A
positional prompt was measured to be recorded as *your own typing* (`origin: {kind: "human"},
promptSource: "typed"`) whatever its text says, so a sentence csm wrote would be indistinguishable, in your own
conversation's record, from one you typed. The alternative — a hidden `isMeta` line plus `--reply-on-resume` — is
honest and self-starting, but it writes into a transcript, and for a fork it would have to write into the *old*
one, where a later lazy respawn of the old link could pick it up as an interrupted turn: two actors on one
conversation. So **a revive writes into no transcript at all**, and the note opens with its own stamp,
`[claude-session-mover — written by the tool; the user did not type this]`.

**The proof is a turn, not a link.** The transcript's byte offset is taken *before* the relay; exit `0` needs
either the registry row going `busy` or an `assistant` line past that offset within `CSM_REVIVE_PROVE_S`. A relay
that reports success and delivers nothing is exit `1` — "it is up but idle: open `<link>` and say continue" —
because the proof is the session's own behaviour and not the relay's word for it.

### What it cannot do

- **It cannot make a server respawn a dead child.** Only server-side activity does that, so row 9 prints the tap
  instead of pretending. It does not then sit and poll for you to tap it: a tool that waits for a person is the
  one shape this tool never takes.
- **It cannot wake a session by writing to its own peer socket.** The protocol is readable and the frame works,
  but a hand-rolled frame from a plain script is **held** on a session that bypasses prompts — measured, the pane
  reads `Held peer message … The sender did not attest its permission mode and this session bypasses prompts`,
  which is a dialog waiting for a human. So the wake goes through Claude Code's own SendMessage tool, from the
  relay above, or not at all.
- **A server child cannot keep its link without its server.** `claude --resume <id>` of such a session never
  re-attaches that claude.ai session — it registers a new one — and `--resume=<url>` hydrates from the server and
  can *replace* the local transcript. That is why reviving a server child in the same account **forks** rather
  than reusing its id: a csm-started process on the old id plus a later lazy respawn of the old link is two
  writers on one conversation. A self-hosted `--remote-control=` session does re-attach, and for it the printed
  link is the proof — a *new* link means nothing re-attached, and the note is then not sent, because the sentence
  it carries would be false.
- **It cannot reach a machine that is off.** A transcript lives in a config home, which is per machine;
  `--from-machine` is refused for `revive`, because every gate it turns on — is anything still writing that
  transcript, is a server up in that folder, can that home still run it — is a question about the machine the
  session is *on*, and the answers are not transportable. `csm --machine M revive <spec>` runs the whole thing
  over there instead; with that machine down, nothing here can revive it.
- **It never waits out a limit, signals anything, or unarchives by accident.** A limit still in force is a
  refusal carrying the time, not a sleep; `revive` has no stop of any kind; and a session archived or ended from
  the app needs `--unarchive` said out loud.
- **It cannot tell you whether an interrupted tool call took effect.** It tells you that there is no recorded
  result, which is the honest answer, and the revived session is told the same thing.
- **It cannot choose between two copies of one id.** A move is a copy, so after any `csm move` the same id sits
  in two homes; with neither of them running, nothing says which one was being used, and `revive` refuses and
  names both — `move` and `stop` do the same. `--account NAME` is the answer.
- **It cannot address a session whose registry name is not unique.** SendMessage addresses a session *by* its
  name, so two proved live sessions of one name is a refusal before anything is sent, naming both. csm's own
  label carries the session's id8 so that the windows it starts cannot collide.
- **It does not keep the note out of every file on disk — only out of its own.** `revive.jsonl` and the log hold
  no note text, by design. But the relay is a `claude -p` run, and the CLI files that run's own transcript under
  the project folder of its cwd — inside the revived session's config home. csm runs the relay in a directory of
  its own so that transcript lands beside no session's, and keeps that folder out of every listing, but the note
  is in a file the CLI wrote, in that home.

## Safety

Every one of these is a rule in the code, and the tests pin them:

- **The source transcript is never edited or deleted.** A move is a copy and a resume.
- **Nothing is written before every refusal has been checked.** A move refused for a stale window, a vanished
  directory or a live twin leaves the target home exactly as it was.
- **A credential is never read, printed, copied or logged.** The login check asks only whether one *exists* — on
  macOS by the exit code of a Keychain lookup with no `-w` and no `-g`, elsewhere by the existence of the file. "I
  could not look" is a third answer, reported as unverified, never silently promoted to "signed in".
- **A process is signalled only after its identity is proved**: the registry's recorded start time must match
  `ps` byte for byte — asked in the C locale, the way the CLI writes it — and the executable must be the CLI.
  A `ps` that cannot answer, or a registry row with no recorded start time, is a refusal: nothing was stopped,
  and nothing was proved. There is no name-based fallback, because argv[0] does not say WHICH session.
- **It never stops the session running it.** Saying "move this session" from inside a session is the main use from
  a phone.
- **It never stops a process on another machine.** `--stop-source` is refused across machines: a process over
  there may be driving work this tool cannot see, so the plan lists what the source started and leaves it running.
- **A session another program owns is not moved, it is handed back.** Where `CSM_BOTS_DIR` names the supervisor of
  a session, a plain `move` is refused: a second copy would answer to nobody while the supervisor kept answering
  on the old account. A directory that cannot be read is a refusal too, never a "no".
- **`modes --restart-idle --apply` is gated by a constant in the file**, not by an environment variable, so no
  stray variable in a scheduled pass's environment can make it signal anything.
- **ssh is `BatchMode` with a connect timeout**, so an unattended call can never block on a password prompt.
- **`--to auto` refuses rather than guesses.** No meter or a reading older than the maximum age leaves an account
  *unread*, which is never *free*, and an account over a cutoff is passed over: a guess here is a move into a
  second exhausted account, which looks exactly like a success.
- **`csm stop` ends only a window `csm` itself opened**, named `moved-<id8>` in `csm-<account>`; everything else is
  refused with the list of windows that do qualify.
- **tmux targets are exact-matched** (`-t '=name'`), because tmux otherwise matches prefixes.
- **The child's environment is scrubbed of the whole `CLAUDE*` and `ANTHROPIC*` families** — by prefix, so a
  variable added in a future release is covered — and only `CLAUDE_CONFIG_DIR` is set back, plus whatever
  `CSM_KEEP_ENV` names by hand, which must itself be in those families. Your own non-Claude credentials in the
  environment are deliberately left alone.
- **The one file csm writes in a config home is written under the CLI's own lock.** `.claude.json` is re-read
  inside `.claude.json.lock`, only the trust and onboarding keys are merged in, the old file is kept as
  `.claude.json.csm-bak-<epoch>`, and a lock that cannot be taken is a warning rather than a failed move.
- **`--dry-run` on every command that writes**, and `csm matrix` writes nothing into any config home — only a
  line in its own log.

## Making your accounts fungible

The short version of [docs/setup.md](docs/setup.md):

1. **One config home per account**, mode 700, named after the account.
2. **Sign each in from that account's own browser profile** — never two sign-ins chained in one window — and verify
   the result by email, not by the folder's name.
3. **Pick one shared directory** and symlink the shareable entries of every home into it: `settings.json`,
   `CLAUDE.md`, `skills/`, `agents/`, `commands/`, `output-styles/` and, if you want one install to serve every
   account, `plugins/`. Leave the state behind: `.claude.json`, credentials, `projects/`, `sessions/`,
   `session-env/`, `shell-snapshots/`, `file-history/`.
4. **Point every home at one memory store**, so notes do not fork the day you add an account.
5. **Do the per-home chores once**: MCP sign-ins, folder trust, and connectors in the browser *per account*.
6. **Verify with `csm matrix --check`.**

Across machines, the shared directory travels in a repo or dotfiles; logins, plugins and scheduled tasks are per
machine; connectors are free, because they follow the account.

## Lessons

Nine of the rules that cost the most to learn. **[LESSONS.md](LESSONS.md)** has 45, each with a one-line rule,
the incident behind it, a command to check it, and the Claude Code version it was verified against, with the
fast-changing (Beta) facts marked. The longer narrative is in [docs/lessons.md](docs/lessons.md).

- **Do not share one `projects/` tree between accounts on a machine that runs Remote Control servers.**
  `projects/<slug>/bridge-pointer.json` is each server's per-account reattach state, and pin `cleanupPeriodDays`
  before linking anything, or one home's pruner deletes every account's history.
  ([more](LESSONS.md#d))

- **An account is a payment layer — a login and a quota. Everything that should follow you belongs outside the
  config home.** Anything you leave inside one will fork silently the day you add another account.
  ([more](docs/lessons.md#accounts))
- **`CLAUDE_CONFIG_DIR` is the only thing that selects an account, and the login — not the directory name — says
  which account that is.** A home named for one account can hold another's credential, and nothing in the
  interface says so. ([more](docs/lessons.md#accounts))
- **claude.ai connectors belong to the account, and no terminal can attach one.** Enable the identical set on every
  account in a browser, or a moved session loses a capability mid-task. ([more](docs/lessons.md#mcp))
- **Enabled is not installed: link `plugins/` as well.** A shared `settings.json` enables a plugin in every home;
  only the home that ran the install actually has it. ([more](docs/lessons.md#sharing))
- **Across organizations a move drops preserved thinking, so move early rather than at the limit.** The first turn
  after the move re-reads the session on the new account's quota. ([more](docs/lessons.md#moving))
- **A session mover must never copy memory, because copying is how stores fork.** Share the store instead, and
  spell it as one literal absolute path. ([more](docs/lessons.md#memory))
- **Renaming a config home on macOS orphans its login.** The Keychain service name is derived from the literal
  `CLAUDE_CONFIG_DIR` string, so copy the item first and prove the new home serves before deleting the old one.
  ([more](docs/lessons.md#credentials))
- **"Signed in" means a usable credential, and "could not read it" is a third answer, never "signed out".** A
  checker that folds unknown into ok prints a green summary over a machine it never read.
  ([more](docs/lessons.md#credentials))

## From a phone

`./install.sh --skill` links [`skills/move-session`](skills/move-session/SKILL.md) into each account home, because
each config home reads its own `skills/`. Then, from any session that still has quota — a Remote Control session on
that machine, for example — say *"I'm out of quota, move my refactor session to personal"*, or *"move this session
to work"*, or *"move it to whichever account has quota left"*, or *"bring my laptop's session over here"*, or
*"stop the session you moved"*. The agent lists the candidates, asks when it is ambiguous, moves the session, and
answers with the account and the new link.

It covers the dead ones too: *"my session died, bring it back"*, *"revive this link"*, *"the remote control
disconnected — restart it"*, *"it stopped on a limit, continue it on an account with room"*. Paste the claude.ai
link and the agent runs `csm revive` with it; the answer comes back as the three lines above, the link, and the
title you knew it by.

Re-run `./install.sh --skill` after an update. It repoints a link of its own, and **refuses a link that points
somewhere else**, printing `skipped <home>/skills/move-session: it links to …` — which is the case to watch for if
you already kept that skill somewhere of your own: those homes go on reading the old text until you repoint them
by hand, or point your own copy at this one. Read the lines it prints; a home it skipped is a home it did not
update.

## Compatibility

- **Python 3.7 or newer, standard library only.** No dependencies, one file.
- **macOS and Linux.** The only platform difference that matters is where the login lives: a Keychain item on
  macOS, `<home>/.credentials.json` elsewhere.
- **tmux** for the default Remote Control mode. `--foreground` resumes in the current terminal and needs no tmux.
- **ssh** for `--machine` / `--ssh`, and for `find --on` / `move --from-machine`, which also want a python on the
  far side — the system one is enough, because the helper they pipe over is standard-library-only.
- **Claude Code's on-disk state is undocumented** and can change in any release. Everything here was measured
  against CLI 2.1.296–2.1.300 (the shared-tree handling and LESSONS.md against 2.1.308; everything `csm revive`
  reads and does against 2.1.312); the tests pin every shape the tool depends on, so a format change fails loudly
  rather than quietly. Re-check anything load-bearing against the version you actually run.
- CI runs the suite on Ubuntu and macOS against Python 3.9 and 3.12, and on Ubuntu 22.04 against **3.7** — the
  floor this page promises, so it is measured and not merely claimed — with no tmux and no account.

## FAQ

**Can I attach my connectors to the other account?**
No. A claude.ai connector is granted to the *account*, server-side, and no terminal command on any machine can
attach one — the CLI refuses a hand-written entry and points at the browser, and `claude mcp login` can only
authenticate a connector the account already has. Enable the identical set on each account at
`claude.ai/customize/connectors`, signed in as that account. `csm move` lists the connectors the session was
actually using, so you know what the move would cost.

**Is my login copied?**
Never. `csm` does not read, print, copy or log a credential — it checks only that one exists, and on macOS it does
that by the exit code of a Keychain lookup that asks for no value. Each config home must be signed in once, by you.

**Can I move a session to another machine?**
Yes: `csm move <id> --from-machine M --to <account>`, run on the machine the session is going **to**. The session
is found over there in every config home, the transcript and its sibling directory cross in one `tar` pipe over
ssh, the folder is translated into this machine's spelling where the configuration says how, and the copy is
resumed here. `csm find --on M` is how you get the id, and the desktop app's own sessions are included. Two things
to know: **the source is never stopped** — a process over there may be driving work this tool cannot see, so the
plan lists what it started — and the session's **folder** must be here or be brought with `--mirror-cwd`, which
copies the code and leaves the data where it was made.

Do not confuse that with `--machine M` / `--ssh HOST`, which run the whole command *on* that machine, where it
again moves between two homes over there.

**Does it delete anything?**
No. The source transcript stays where it is, readable from the old account. `--stop-source` stops one proved
process; `csm stop` removes one window `csm` itself opened. Neither touches a transcript.

**What if the target account has never been used in this directory?**
That is the normal case and not a problem: `csm` pre-answers the target home's folder-trust and onboarding gates
for that directory before it starts anything. Those dialogs put the cancelling answer first and focused, so an
unattended start in a cold home would otherwise just sit there.

**The moved session says it is the old account.**
The copied transcript still contains the earlier turns' paths and recorded email, so the agent reads that about
itself until the context is rebuilt. It is spending the new account's quota regardless; the link and `csm list`
are the authority.

**Can the other account see my files?**
Every config home on the machine runs as the same OS user, so yes — the accounts differ in who pays, not in what
the machine can reach. Only move sessions between accounts you own.

## Tests

```sh
python3 tests/test_mover.py
```

706 tests, fixtures only: fake homes and transcripts, a fake `claude` that records its argv and environment, a fake
`tmux` that really runs the moved window's command on a private socket, a fake `ssh` that records the command line
it was handed, and — for `find --on` and `--from-machine` — "the other machine" played by this process with `HOME`
pointed at a fixture tree, so no test reaches a real host. No network, no account, no credential store, no real
tmux server and no real config home. They cover
both accounts-file dialects, both matching ladders, every refusal, the `--limit` cap, the environment scrub, the
dialog answerer's key-by-key walk, the process proof, the move note, `--to auto`'s meter arithmetic, folder
translation, the permission sweep's verdicts and its one parsed line, `stop`, and the matrix's cells and exit
codes. What a fixture cannot show — a real resume under another login — was measured instead, and written
down in [docs/design.md](docs/design.md).

## Related tools

Actively developed tools for neighbouring jobs (as of 22 Oct 2026; the full list of about 25, grouped, is in
[LESSONS.md § Related tools](LESSONS.md#related)):

- [claude-sesh-mover](https://github.com/Sertelegger/claude-sesh-mover) — a Claude Code plugin that exports, imports
  and migrates sessions between profiles, containers and machines.
- [hatswap](https://github.com/orvi2014/hatswap) — concurrent accounts, a live session move between them, folders
  pinned to accounts, and handoff to Codex.
- [claude-rotate](https://github.com/OpenGraphLabs/claude-rotate) — resumes the session on the next account when a
  usage limit hits.
- [AgEnD](https://github.com/songsid/agend) — a fleet daemon for several agent CLIs that can carry a conversation to
  another credential profile.
- [tokenmaxxing](https://github.com/anaclumos/tokenmaxxing) — one real `~/.claude`, only the credential store
  switching, via `CLAUDE_SECURESTORAGE_CONFIG_DIR`.
- [Orca](https://github.com/stablyai/orca) — a config dir per account with a shared layer of settings, skills and
  plugins.
- [agent-shim](https://github.com/exadev/agent-shim), [claude-profile-manager](https://github.com/jakubkontra/claude-profile-manager),
  [clausona](https://github.com/larcane97/clausona), [clauth](https://github.com/uwuclxdy/clauth) — per-account
  homes linked into one shared layer, each with a written list of what must stay per account.
- [claude-swap](https://github.com/realiti4/claude-swap) — swaps the login under one home, with rate-limit rotation.
- [claude-sync](https://github.com/tawanorg/claude-sync) — sync Claude Code sessions across devices, end-to-end
  encrypted.

`csm`'s own scope is narrower: one conversation, moved from one of your own config homes into another — on this
machine, or from another machine with `--from-machine` — onto another of your own logins.

## Notes

Not affiliated with, endorsed by, or supported by Anthropic. It reads and writes Claude Code's own undocumented
on-disk state, which can change in any release.

**Use it only with Claude accounts you own.** It never copies, shares or pools a credential, and it is not a way to
let several people share one subscription. Each account is signed in by you, once per config home, and a move
changes nothing about who pays for what — it changes which of *your* accounts a conversation continues on.

## Documentation

- [LESSONS.md](LESSONS.md) — rules for moving sessions between accounts and machines: rule, why, check, verified
  version, and stable or Beta, plus the related tools.
- [docs/fungibility-matrix.md](docs/fungibility-matrix.md) — the matrix in full, one section per layer: where it
  lives, the verdict on each axis, how to make it fungible, and which `csm matrix` row reports it.
- [docs/setup.md](docs/setup.md) — the recipe for making accounts fungible, on one machine and across machines.
- [docs/lessons.md](docs/lessons.md) — the generic lessons from running several accounts day to day.
- [docs/design.md](docs/design.md) — the design, the on-disk formats, the measurements and the safety rules.
- [CHANGELOG.md](CHANGELOG.md) — what changed in each release.

## License

MIT. See [LICENSE](LICENSE).
