# Claude Session Mover: design and implementation

Version 0.3.1 · code **[github.com/yaroslavvb/claude-session-mover](https://github.com/yaroslavvb/claude-session-mover)**
(MIT, one Python file, standard library only).

Everything here is Claude Code's own **undocumented on-disk state**. It has already changed inside one minor
series, so every claim below is stamped with the CLI release it was measured on — 2.1.296 to 2.1.300, on macOS —
and the ones that matter most come with a recipe for re-measuring them on your own build
([Measured facts](#measured)).

One of your Claude accounts hits its usage limit while your other accounts have quota left. The usual answer is
to start the work again in another account and lose the conversation. Claude Session Mover moves the conversation
instead: it copies the session's transcript into the other account's config home and resumes it there. The agent
still knows everything that was said, and every turn from then on spends the new account's quota. Nothing is
deleted from the old account.

🛑 **A move is between two config homes on ONE machine.** A transcript lives under `<home>/projects/`, which is
per machine, and `--resume` looks only inside the home it is running under. `--ssh HOST` runs the same command
*on* that machine, where it again moves between two homes there.

<a id="contents"></a>

## Contents

- [Quick start](#quick-start)
- [The idea in one picture](#picture)
- [What a move does, step by step](#steps)
- [Accounts: discovered, named, never numbered](#accounts)
- [Picking a session](#picking)
- [Choosing the permission mode](#mode)
- [Answering a dialog nobody is there to answer](#dialogs)
- [Proving a process before signalling it](#proof)
- [Is this home really signed in?](#login)
- [What the target home cannot do: the notes](#notes)
- [Auto-memory is never copied](#memory)
- [What a move costs](#cost)
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
csm stop 3                                        # end a session csm moved, and free its window
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
   ([ladder below](#picking)).
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
   - an existing `moved-<id8>` window — with `csm stop <session>` named as the fix.

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
6. **Launch under the target login.** A detached tmux window `moved-<first 8 of id>` in session `csm-<account>`
   runs the tool's own `__run <plan.json>`. That sets the target's `CLAUDE_CONFIG_DIR`, or *unsets* it for the
   default home, scrubs the environment ([below](#safety)), restores `PATH`, and runs:
   ```
   claude --remote-control=<title, moved from A> --permission-mode <the chosen mode>
          --model <its model> --resume <id>
   ```
   in the session's recorded working directory. The hand-off goes through a file because a tmux window starts
   with the tmux *server's* environment, whatever that was when the server started. The interpreter and the
   script are spelled absolutely; the plan file is mode 0600 and is deleted by `__run` as it reads it.
7. **Wait for proof.** The tool watches the pane (`capture-pane -p -J`, so a wrapped link is whole) for
   `https://claude.ai/code/session_…`, up to 150 s, polling every 3 s. A dialog on the screen is answered by
   reading its focus marker ([below](#dialogs)), at most one key per poll. The wait ends early when the window
   prints `__run`'s exit banner, so a refused model or a dead login fails in a second with the reason in the pane.
8. **Report what actually happened.** The success block prints the new claude.ai link, the mode the session
   **came up in** versus the mode that was asked for ([below](#mode)), what the move cost ([below](#cost)), and
   any target note that still applies.
9. **Optionally stop the source** (`--stop-source`). Only after the link has appeared, only once the pid has been
   **proved** to be the same process the registry wrote down ([below](#proof)), and never when the source is the
   session running the tool. A move that did not connect leaves the source running: two copies is bad, nothing
   running is worse.

Two other modes:

- `--no-remote-control` starts the window as a plain interactive session to `tmux attach` to; the proof is that
  it is still running after a few seconds. `--stop-source` is refused here — without the link there is no proof.
- `--foreground` skips tmux and replaces the tool with the resumed session in your terminal. It is refused inside
  Claude Code, where there is no terminal to give it.

Exit codes: `0` done, `1` it started but did not connect (or a window could not be removed), `2` a refusal.

<a id="accounts"></a>

## Accounts: discovered, named, never numbered

An **account** here is a config home: the directory Claude Code keeps its login state, settings and transcripts in.

- **Discovery.** `~/.claude` is the account `default`, every `~/.claude-<name>` directory is the account
  `<name>`, and the home in `$CLAUDE_CONFIG_DIR` is added if it is elsewhere.
- **An accounts file** (`~/.config/claude-session-mover/accounts`, or `$CSM_ACCOUNTS`) replaces discovery
  entirely. It holds one `name  home  [expected-email]` per line, with `-` for the default home. With an expected
  email, a home signed in as anyone else is refused, because the move would spend the wrong quota.
- **Who is signed in** is read from the home's state file, `oauthAccount.emailAddress`, and then checked against
  the *existence* of its credential ([below](#login)). The tool never reads, prints, logs or copies a credential
  value. Two homes signed in to the same login and organisation are the same account for quota purposes, so a
  move between them is refused.
- **The default home is special.** With `CLAUDE_CONFIG_DIR` unset, the CLI keeps its state file at
  `~/.claude.json` (outside the directory) and uses the bare `Claude Code-credentials` Keychain item. Setting
  `CLAUDE_CONFIG_DIR=~/.claude` is not the same account: the state file moves inside the directory and the
  Keychain item becomes `Claude Code-credentials-<8 hex>`, which is empty, so it reads as signed out. A move into
  `default` therefore **unsets** the variable rather than spelling the path.
- **Naming ladder** for `--to`, first unique match wins: exact name, exact email, unique prefix, unique
  substring. Anything ambiguous is refused with the candidates listed. **A bare number is refused** unless it is
  literally an account's name: a position in a list changes whenever an account is added or removed, so it cannot
  be trusted to mean the same account twice.

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
| **connectors** (always printed) | claude.ai connectors belong to the **account**, server-side, and no terminal can attach one: the moved session gets the target's. The names the conversation actually used are listed, read from `mcp__claude_ai_<Connector>__…` tool names in the transcript |
| **other MCP servers** | the servers the conversation used, with the reminder that MCP sign-ins live inside the credential blob and are per config home (`claude mcp login <server>`, once in the target) |
| **memory** | the two homes resolve auto-memory to different directories and the project has notes ([below](#memory)) |
| **memory in this shell only** | `CLAUDE_CODE_REMOTE_MEMORY_DIR` is set in your shell but not in the target home's settings: the moved session does not inherit it (every `CLAUDE*` variable is scrubbed) |

A separate warning says the **target may be out of quota too**, read off the target's own recent sessions when a
limit it hit is still in force. Evidence, not the meter — and a warning, because moving into a second exhausted
account otherwise looks like a success: the window connects and prints a link, and then every turn is refused.

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

<a id="stop"></a>

## `csm stop`: ending what csm started

v0.1.0 created a `moved-<id8>` window on every move, refused the next move of the same session into the same
account while that window existed, and offered no way to clean it up. `csm stop SESSION [--dry-run]` is that way.

🛑 **The only authorisation is csm's own fingerprint**: a window named `moved-<id8>` in the tmux session
`csm-<account>` of the account the row belongs to — and, for a live row, a registry `tmux` field naming **that
same window id**, so a moved window plus an unrelated reused pid cannot add up to a signal for someone else's
process. Anything else is refused, with the `moved-…` windows that do exist listed. It never stops the session
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
| Per-session data outside `projects/`, keyed by session id: `file-history/<id>/` is real and populated. `<home>/tasks/` is a path the CLI knows (its read-allowlist names it), but a session's task OUTPUT is written outside the config home, under a cache root keyed on the working directory — so `tasks/<id>/` is carried opportunistically and is usually absent. Older builds wrote `todos/<id>-*.json` | 2.1.300 (the bundle's path builders and read-allowlist; on disk, per-session `file-history/<uuid>/` directories, no `todos/` and no `tasks/`) | `ls <home>/file-history | head` after using `/rewind`; `ls <home>/tasks` for the other half |
| `jobs/`, `daemon.json`, `shell-snapshots/` and `session-env/` are treated as code-execution surfaces that even a bypassing session may not write — another reason nothing but the session's own data travels | 2.1.300 | the reserved-name set in the bundle |

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

- **Same machine.** The move happens where the transcripts live; `--ssh HOST` runs the same command on another
  machine that has the tool installed, and moves between *that* machine's homes. (A plain non-login `ssh host cmd`
  gets a minimal `PATH`, so the remote interpreter and the tool are spelled absolutely.)
- **A new session in the app**, with a new id and link, owned by the target account. The old link keeps pointing
  at the old copy.
- **The prompt cache starts cold**, and across organizations the preserved thinking is dropped and re-generated
  on the target's quota ([above](#cost)).
- **The last line on disk only.** A reply still being written is not in the copy.
- **A running process can rewrite the state file.** If something in the target home rewrites `.claude.json` right
  after the pre-answers, a dialog can come back; the marker-reading answerer is the fallback.
- **The quota flag is a heuristic** read off transcripts, not the meter.
- **`csm accounts` and `csm matrix` can be slow with many homes on a locked macOS keychain**: the credential
  probe is capped at 10 s per home before it falls back to "unverified".
- **Undocumented formats.** Everything above is Claude Code's internal state and can change in any release; the
  tests pin the shapes the tool depends on, and the recipes above re-measure the rest.

<a id="env"></a>

## Environment knobs

| Variable | What |
|---|---|
| `CSM_ACCOUNTS` | the accounts file (default `~/.config/claude-session-mover/accounts`) |
| `CSM_STATE_DIR`, `CSM_LOG`, `CSM_PICKS` | where the log and the saved `list` numbering live (`$XDG_STATE_HOME` is honoured) |
| `CSM_CAPTURES` | where the pre-signal pane captures are written; default `<state dir>/captures` (0700, each file 0600) |
| `CSM_LOCK_WAIT` | how many seconds to wait for the CLI's `.claude.json.lock` before writing anyway with a warning (default 2) |
| `CSM_CLAUDE`, `CSM_TMUX` | the `claude` / `tmux` binaries to use |
| `CSM_HEAD_BYTES`, `CSM_TAIL_BYTES` | how much of a transcript is read per row |
| `CSM_CONNECT_WAIT`, `CSM_POLL`, `CSM_SETTLE` | how long a move waits for the link, the poll interval, how long a non-Remote-Control window must stay up |
| `CSM_TMUX_SOCKET` | **tests**: `tmux -L <socket>` on every call, so the suite drives a private tmux server and a `stop` test can never kill your own windows |
| `CSM_LOGIN_PROBE` | **tests**: forces the credential-existence answer (`true`/`false`/`unknown`/`off`), announcing itself on stderr and in the log on every run |
| `CSM_NO_HOLD` | **tests**: the moved window exits instead of being held open for its scrollback |

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
| `install.sh` | links `claude-session-mover` and `csm` into `~/.local/bin`; `--skill` links the skill into every account home |
| `skills/move-session/SKILL.md` | the Claude Code skill for the phone flow |
| `tests/test_mover.py` | the suite: fixtures only |
| [`README.md`](../README.md) | what it does, the matrix, the commands |
| [`CHANGELOG.md`](../CHANGELOG.md) | what changed, release by release |
| [`docs/fungibility-matrix.md`](fungibility-matrix.md) | every layer: where it lives, what is shareable, how |
| [`docs/setup.md`](setup.md) | making several accounts behave like one setup |
| [`docs/lessons.md`](lessons.md) | the generic lessons behind the rules |
| `docs/design.md` | this page |

The tests run the real script against fake homes and transcripts, a fake `claude` that records its argv and
environment, and a fake `tmux` that really runs the moved window's command, alongside in-process unit tests of
the pure parts (the dialog answerer, the mode chooser, the memory resolver, the matrix cells). They need no
network, no account, no credential store and no real tmux server, and they pass on Python 3.7, 3.9 and 3.12; CI
runs them on Linux and macOS.

State lives in `~/.local/state/claude-session-mover/` (`$XDG_STATE_HOME` is honoured): `log`, one line per list,
move, stop, refusal and window start — asked-for and came-up-in modes included, and never a scrubbed value — and
`picks.json`, the numbering of the last `list`.

---

**Why it matters:** hitting a usage limit stops costing the conversation. The whole exchange moves to an account
with quota in under a minute, from a phone, with nobody at the keyboard — and the tool says plainly what the
move could not carry with it.
