# Claude Session Mover

[![tests](https://github.com/yaroslavvb/claude-session-mover/actions/workflows/test.yml/badge.svg)](https://github.com/yaroslavvb/claude-session-mover/actions/workflows/test.yml)

`csm` moves a running [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) session from one of your
own Claude accounts to another, keeping the whole conversation. One account hits its usage limit while another has
quota to spare; instead of starting the work over and losing the thread, you move the thread. `csm` copies the
session's transcript into the other account's config home, pre-answers that home's first-run dialogs, and resumes
it there under the other login. The agent remembers everything that was said, every turn from then on is spent on
the other account, and nothing is deleted from the old one.

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
| [Conversation (transcript)](docs/fungibility-matrix.md#conversation) | ✅ `csm` copies it | 🔧 copy by hand | `<home>/projects/<folder>/<id>.jsonl`; the folder name comes from the absolute path |
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
./install.sh            # links claude-session-mover and csm into ~/.local/bin
./install.sh --skill    # ...and the move-session skill into every account home (for phones)
```

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
csm stop 3                          # end that moved session and free its window
```

## Commands

Two global options sit in front of the subcommand:

| option | effect |
|---|---|
| `--version` | print the version |
| `--ssh HOST` | run this same command **on** that machine, where `csm` is installed too. A move is always between two config homes of one machine, so this moves sessions over there, never from here to there |

### `csm accounts`

The config homes on this machine, and who is signed in. `--json` for the machine-readable form.

Accounts are discovered by default. To name them yourself, or to pin which login each must hold, write
`~/.config/claude-session-mover/accounts` (or point `CSM_ACCOUNTS` at a file); it then replaces discovery entirely.

```
# name      home               [expected email]
default     -                  you@example.com
work        ~/.claude-work     you@work.example
personal    ~/.claude-me
```

`-` is the default home. With an expected email, a home signed in as anyone else is refused as a move target,
because the move would spend the wrong quota.

### `csm list`

Recent sessions in every account, newest first, numbered so `move 3` means the row you just read.

| flag | effect |
|---|---|
| `--account NAME` | only this account |
| `--all` | up to 300 sessions |
| `--limit N` | how many sessions to list (default 20). It caps the **ended** ones only: every live session is listed whatever the limit, so a small number can still print a long table |
| `--json` | the machine-readable form |

Rows are marked `● live`, `  ended`, or `  closed` when the session was ended from the app. The session you are
typing in is marked `← this session`, and a session whose last turn hit a usage limit is marked
`⚠ OUT OF QUOTA (5h|week, resets HH:MM)` — a heuristic read off the transcript, not the meter.

### `csm move`

```sh
csm move SESSION --to ACCOUNT [flags]
```

`SESSION` can be a row number from the last `csm list`, a session id or a prefix of one (4 characters or more), a
`https://claude.ai/code/session_…` link, or a piece of the title. `--to` takes an account's name, its email, or a
unique prefix of either. Anything ambiguous is refused with the candidates listed, never guessed, and so is a bare
number unless an account is literally named that.

| flag | effect |
|---|---|
| `--to ACCOUNT` | the account to move it to (required) |
| `--dry-run` | print the plan and any refusal; copy, write and start nothing |
| `--stop-source` | stop the old process once the new one has printed its claude.ai link. Only in the default Remote Control mode, where that link is the proof it connected. The source pane's scrollback is captured to `<state dir>/captures/<date>/` first, and the path is printed |
| `--no-remote-control` | start a plain interactive session in tmux, without Remote Control |
| `--foreground` | resume in this terminal instead of tmux |
| `--permission-mode MODE` | the mode to resume in: `plan`, `default`, `acceptEdits`, `auto`, `dontAsk`, `bypassPermissions` (`manual` is an alias of `default`) |
| `--name NAME` | the Remote Control name of the moved session |
| `--all` | search every session, not just the newest |

Without `--permission-mode`, the mode the session was running in is used, raised to the target home's
`permissions.defaultMode` when that is stronger **and** the session recorded nothing, `default` or `auto` — an
automatic choice never weakens a session, and the plan line names where the choice came from. An explicit
`--permission-mode` is obeyed as given, including a weaker one.

A successful move prints the account to open the app as, the new `https://claude.ai/code/session_…` link, the tmux
window it runs in, and what the move cost.

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

| variable | effect |
|---|---|
| `CSM_ACCOUNTS` | the accounts file to read instead of `~/.config/claude-session-mover/accounts` |
| `CSM_CLAUDE` | the `claude` binary, when it is not on `PATH` |
| `CSM_TMUX` | the `tmux` binary, when it is not on `PATH` |
| `CSM_STATE_DIR` | the **state dir**: where the log and the `list` numbering are kept (default `$XDG_STATE_HOME/claude-session-mover`, falling back to `~/.local/state/claude-session-mover`) |
| `CSM_LOG` | the log file itself (default `<state dir>/log`) |
| `CSM_PICKS` | where `list` leaves its numbering, so `move 3` means the row you just read (default `<state dir>/picks.json`) |
| `CSM_CAPTURES` | where the pane captures `csm stop` and `csm move --stop-source` write are kept (default `<state dir>/captures`, 0700, each file 0600) |
| `CSM_CONNECT_WAIT` | seconds to wait for the moved window's claude.ai link (default 150) |
| `CSM_LOCK_WAIT` | seconds to wait for the CLI's `.claude.json.lock` before writing anyway with a warning (default 2) |
| `CSM_LOGIN_PROBE` | `true`, `false`, `unknown` or `off` — force the answer of the credential-existence check instead of asking the store, for a machine where asking it is not possible. It announces itself on stderr and in the log on every run |
| `CSM_TMUX_SOCKET` | add `-L <socket>` to every `tmux` call, to keep `csm`'s windows on a server of their own |
| `CSM_BIN_DIR` | where `install.sh` links the command (default `~/.local/bin`) |

Three knobs are for the test suite and for a machine where the credential store cannot be asked:
`CSM_LOGIN_PROBE` and `CSM_TMUX_SOCKET` above, and `CSM_NO_HOLD`, which the table leaves out because it drops the
held-open window a move's scrollback is read from. The tuning internals (`CSM_HEAD_BYTES`, `CSM_TAIL_BYTES`,
`CSM_POLL`, `CSM_SETTLE`) and the full list are in [docs/design.md](docs/design.md#env).

## What a move does

1. **Find.** Scan every account home's transcripts — a head and a tail of each file, never a full parse — and its
   live registry, `sessions/<pid>.json`.
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
5. **Resume.** `claude --resume <id> --remote-control=<title> --permission-mode <mode> --model <model>` runs in a
   detached tmux window `moved-<id8>` of the tmux session `csm-<account>`, under the target's `CLAUDE_CONFIG_DIR`,
   in the session's recorded working directory, with a scrubbed environment.
6. **Prove.** Wait for the claude.ai link in the pane; only then, with `--stop-source`, stop the old process. A
   move that does not connect leaves the source running and keeps the window with its scrollback.

Should a dialog still appear in the new window, it is answered by reading the focus marker (`❯`) one poll at a
time: Down only while the marker is not on the wanted option, Enter only when the marker's own line names that
option, and no key at all when the pane is ambiguous. Never a digit, never a canned sequence — a cold home's
dialogs put the cancelling answer first and focused, so a blind Enter declines.

**Homes that share one `projects/` tree.** If two homes' `projects/` resolve to the same directory (both symlinked
into one tree, say), `csm` compares by resolved path, not by spelling. `csm list` shows one row per transcript, not
one per home, and names the home running it. A move between two such homes copies nothing — the file the target
resumes is already the file the source uses — so there is no copy, no backup and no sibling copy, and side data
that is one directory in both homes is skipped too. The live-twin refusal asks every home on the machine (the
default home included), because the process holding a shared transcript can belong to a third account. Leaving the
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
- **`csm stop` ends only a window `csm` itself opened**, named `moved-<id8>` in `csm-<account>`; everything else is
  refused with the list of windows that do qualify.
- **tmux targets are exact-matched** (`-t '=name'`), because tmux otherwise matches prefixes.
- **The child's environment is scrubbed of the whole `CLAUDE*` and `ANTHROPIC*` families** — by prefix, so a
  variable added in a future release is covered — and only `CLAUDE_CONFIG_DIR` is set back. Your own non-Claude
  credentials in the environment are deliberately left alone.
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

Nine of the rules that cost the most to learn. **[LESSONS.md](LESSONS.md)** has 36, each with a one-line rule,
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
to work"*, or *"stop the session you moved"*. The agent lists the candidates, asks when it is ambiguous, moves the
session, and answers with the account and the new link.

## Compatibility

- **Python 3.7 or newer, standard library only.** No dependencies, one file.
- **macOS and Linux.** The only platform difference that matters is where the login lives: a Keychain item on
  macOS, `<home>/.credentials.json` elsewhere.
- **tmux** for the default Remote Control mode. `--foreground` resumes in the current terminal and needs no tmux.
- **Claude Code's on-disk state is undocumented** and can change in any release. Everything here was measured
  against CLI 2.1.296–2.1.300 (the shared-tree handling and LESSONS.md against 2.1.308); the tests pin every shape the tool depends on, so a format change fails loudly
  rather than quietly. Re-check anything load-bearing against the version you actually run.
- CI runs the suite on Ubuntu and macOS against Python 3.9 and 3.12, with no tmux and no account.

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
Not with `csm`. A transcript lives under a config home, config homes are per machine, and `--resume` only looks
inside the home it is running under. `--ssh HOST` runs `csm` *on* that machine, so it moves sessions between two
homes over there. To carry a conversation to another machine by hand, copy the `.jsonl` (and its sibling
directory) into a home there and resume it: `claude --resume` also accepts a path to a `.jsonl` file, which is the
simplest answer when the project sits at a different absolute path and so gets a different folder name.

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

Fixtures only: fake homes and transcripts, a fake `claude` that records its argv and environment, and a fake `tmux`
that really runs the moved window's command on a private socket. No network, no account, no credential store, no
real tmux server and no real config home. They cover the parsing, both matching ladders, every refusal, the
environment scrub, the dialog answerer's key-by-key walk, the process proof, `stop`, and the matrix's cells and
exit codes. What a fixture cannot show — a real resume under another login — was measured instead, and written
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

`csm`'s own scope is narrower: one conversation, moved between two config homes on one machine, onto another of
your own logins.

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
