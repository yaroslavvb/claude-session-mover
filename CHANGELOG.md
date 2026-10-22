# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every fact below was measured against Claude Code 2.1.296–2.1.300 on macOS. The on-disk
state it reads is undocumented and can change in any CLI release; the tests pin every shape
the tool depends on.

## [0.3.0] — 2026-10-22

Verified against Claude Code 2.1.308 on macOS.

### Added

- **`LESSONS.md`**, linked from the README: 36 rules for moving Claude Code sessions between
  accounts and machines, each with a one-line rule, the incident behind it, a command to check
  it and the version it was verified against, with fast-changing or undocumented facts marked
  **Beta**. New in it: `projects/<slug>/bridge-pointer.json` is per-account Remote Control
  state, so a `projects/` tree must not be shared between accounts on a machine that runs
  Remote Control servers; writes reopen the transcript by path and hold no descriptor;
  `cleanupPeriodDays` prunes, so pin it before linking anything; the Keychain slot formula and
  the inputs tools disagree on; `CLAUDE_SECURESTORAGE_CONFIG_DIR` (present in the binary,
  undocumented); an environment token outranks the config dir; `.claude.json` mixes identity
  with per-project trust; and a linked shared file can silently become a real one.
- A **Related tools** section in `LESSONS.md` (about 25 actively developed tools that move or
  share sessions or accounts) and a short one in the README, replacing "Prior art".
- `csm list` adds a line saying how many rows are one transcript several homes can see.

### Fixed

- **Safe on homes that share one `projects/` tree.** Where the source and target homes'
  `projects/` resolve to one directory:
  - a move copies nothing: no transcript copy, no `.csm-bak-…` backup, no sibling copy, not even
    a chmod. Before, the copy onto itself raised `shutil.SameFileError` half-way through the
    move;
  - side data that is one directory in both homes (a shared `file-history/`) is skipped;
    `tasks/` and `todos/` still travel when they are real per-home directories. The merge copy
    also refuses a copy onto itself for any caller;
  - `csm list` shows one row per transcript instead of one per home (collapsed by realpath, so
    two genuine copies after an ordinary move stay two rows), attributed to the home running it,
    else the home holding its `tasks/`/`todos/`. `csm move <id>` and `csm move "<title>"` no
    longer refuse an idle shared session as "several copies";
  - the live-twin refusal asks every home on the machine, the default home included even when an
    accounts file leaves it out, because the process holding a shared transcript can belong to a
    third account;
  - the plan warns that the moved session resumes the very file the source uses, and, if the
    source is running, that two CLIs would interleave in it, naming `--stop-source`.
  Homes with their own `projects/` behave exactly as before. 11 new tests (232 in all).

## [0.2.0] — 2026-10-19

### Added

- **The pane is captured before anything is signalled.** `csm stop` and `move --stop-source`
  write the source pane's whole scrollback to `captures/<date>/` under the state directory
  (0600 in a 0700 directory) and print the path, then prove the pid, then signal. A prompt the
  agent had typed and not yet sent exists only in the scrollback, and `kill-window` destroys
  the pane with the process. The capture can never fail the stop, and `--dry-run` writes
  nothing. New `CSM_CAPTURES` environment variable.
- **`docs/lessons.md`** gained the rules a week of moves measured: the three answers to "is
  this home signed in" (and why "I could not look" must stay its own answer), reading a
  confirmation dialog's option order off the build instead of answering by number, the
  per-session data that lives outside `projects/`, capture-before-signal, telling a moved
  agent that it moved, memory being portable when its work is not, the desktop app as a
  config home no account list mentions, and account isolation.
- **`csm stop SESSION [--dry-run]`** — end a session csm moved and remove the tmux window it
  opened. That window is also what blocks moving the same session to the same account twice,
  so this is the unblocker for `a window … already exists`. Its only authorisation is csm's
  own fingerprint: a `moved-<id8>` window in the `csm-<account>` tmux session, plus, for a
  running session, a registry row naming that same window. It refuses the session running the
  command, refuses anything csm did not start (and lists what it did), and never deletes a
  transcript.
- **`csm matrix`** — your own fungibility table: rows are the layers that decide whether your
  accounts are interchangeable (account, login, `settings.json`, `settings.local.json`,
  `CLAUDE.md`, skills, agents, commands, output styles, plugins, scheduled tasks,
  enabled-but-not-installed plugins, user-scope MCP server names, auto-memory, onboarding,
  folder trust, permission mode, `disableAutoMode`, bypass consent, CLI version, connectors,
  MCP sign-ins), columns are the config homes on this machine. Read-only, offline and
  prompt-free: it writes nothing into any config home (only a line in csm's own log), never
  runs `claude`, never reads a credential value and makes no network call — it does ask `git`
  for the project root, and on macOS asks the keychain whether an item exists. Flags:
  `--json`, `--cwd DIR`, `--account NAME` (repeatable or a comma list), `--check` (exit 1 on a
  divergent shareable layer or a login that is gone, never on an unknown). Sharing is judged
  by resolved path, not by equal bytes: ONE realpath for every home reads `shared` wherever
  that path lives — including inside one of the config homes, the layout you get by sharing
  through the default `~/.claude`, which earns a note rather than a divergence. A symlink to
  nowhere reads `DANGLING` rather than "absent".
- **Warnings before a move**, each measured for the source and target homes of that move,
  and none of them able to
  break a move: claude.ai connectors (named from the `mcp__claude_ai_*` tool names the
  conversation actually used) belong to the account and must be enabled on the target at
  claude.ai/customize/connectors; other MCP servers used, whose sign-ins are per config home;
  plugins installed in the source home but not the target; skills, agents, commands and output
  styles the target lacks (compared by resolved path); bypass consent not accepted; "Enable
  Remote Control?" never answered; auto-memory not shared between the two homes; and
  `CLAUDE_CODE_REMOTE_MEMORY_DIR` set only in the calling shell, which the moved session does
  not inherit.
- **A cost block after every move**: across organizations the CLI drops the session's
  preserved thinking and the first turn re-reads the whole conversation — on the target
  account's quota, so move early rather than at the limit; `same organization: the session's
  preserved thinking is KEPT.` when both homes record the same `organizationUuid`; the copied
  transcript still names the source account inside itself; the prompt cache starts cold.
- **"Came up as" reporting**: the mode the moved session actually came up in, read from what
  the resumed session appended past the copied byte count, else from the pane footer. When it
  differs from the mode asked for, the tool says so and how to fix it; when it cannot be
  measured it says `the mode REQUESTED, not a measurement` and gives the `tmux capture-pane`
  command to check by hand.
- **Per-session side data travels with the move**: `file-history/<id>/` (what `/rewind`
  restores from, verified present on 2.1.300), plus `tasks/<id>/` and older builds'
  `todos/<id>*.json` where a build keeps them in the config home — on 2.1.300 a session's task
  output lives outside the home, so usually there is nothing there to carry.
  Copied additively, never overwriting. Nothing else from the home moves —
  `sessions/`, `session-env/`, `shell-snapshots/`, `jobs/`, `bridge-pointer.json`,
  `.claude.json` and credentials stay where they are, pinned by a test.
- `--permission-mode manual` as an alias of `default`.
- `csm accounts` reports the login as `ok`, `CREDENTIAL GONE` or `ok (UNVERIFIED)`, and ends
  by pointing at `csm matrix`.
- `csm list` marks a session ended from the app (`code 4090`) as `closed`.
- Env knobs for tests and for locked-down machines: `CSM_LOGIN_PROBE`
  (`true|false|unknown|off`, forces the credential probe and announces itself on stderr and in
  the log on every run; an unknown value is refused) and `CSM_TMUX_SOCKET` (adds `-L <socket>`
  to every tmux call).
- `CHANGELOG.md`, `docs/fungibility-matrix.md`, `docs/setup.md` and `docs/lessons.md`.
- A **Prior art** section in the README: claude-swap, claude-rotate, claude-sesh-mover and
  claude-sync.

### Changed

- **The permission mode is chosen, not copied.** An explicit `--permission-mode` wins;
  otherwise the mode the session was running in is used, raised to the target home's
  `permissions.defaultMode` (`settings.local.json` over `settings.json`, read through
  symlinks) only when the session recorded nothing, `default` or `auto`. `plan` and
  `acceptEdits` are carried as they are, a mode the tool does not know is left alone, and a
  move never weakens a session. The plan names where the choice came from.
- `--permission-mode` is validated in the tool instead of by argparse, so `manual` is
  accepted and an invalid value is refused with the list of modes. Both still exit 2; the
  message text changed.
- **The environment scrub is by family.** Every `CLAUDE*` and `ANTHROPIC*` variable, plus
  `CLOUD_ML_REGION` and `AWS_BEARER_TOKEN_BEDROCK`, is removed from the moved session's
  environment, from every tmux call and from every `ps` call; only `CLAUDE_CONFIG_DIR` is set
  back (and unset for the default home). Your own non-Claude credentials — cloud CLI profiles
  and the like — deliberately survive.
- **Auto-memory is never copied, in any configuration.** The plan says which directory each
  home resolves to and why nothing travelled. A copied store is a second set of notes that
  then drifts, with nothing afterwards reporting the fork — including in the case that looks
  harmless, where neither home has a store and the target has no notes yet.
- **Auto-memory is resolved in the CLI's own order and shape:**
  `env.CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` (verbatim) → `autoMemoryDirectory` (verbatim, a
  leading `~/` expanded) → `env.CLAUDE_CODE_REMOTE_MEMORY_DIR` or the config home, plus
  `projects/<key>/memory/`. The documented setting wins over the environment variable, only
  the last rung appends a project key, and a store that does not exist yet is still a store.
- **A warm target home is no longer opened for writing.** The theme and onboarding keys are
  written only when `hasCompletedOnboarding` is not already true, no theme is invented for a
  home that has one, and the state-file backup is now `.claude.json.csm-bak-<epoch>`, so two
  moves keep two backups instead of overwriting one.
- **The claude.ai thread claim is softened.** The output no longer asserts that the app does
  not re-render earlier turns. It says the move makes a NEW claude.ai session owned by the
  target account, that the old link still opens the source copy, that the moved agent holds
  the whole conversation, and that the app may show the thread starting at the move.
- Quota detection widened to `usage_limit_reached`, `rate_limit_error` and
  `rate_limit_exceeded`, with the reset time also read from `quotaLimits.resetsAt`.
- The duplicate-window refusal now points at `csm stop`.
- Every tmux call — `send-keys` and `capture-pane` included — goes through one wrapper, so the
  env scrub, the socket override and the "tmux is not installed" refusal apply to all of them.
- `MOVED` and `STOPPED` log lines carry the mode asked for and the mode it came up in, and
  what was and was not stopped, with the reason. No scrubbed value ever reaches the log.
- The one-machine rule is spelled out in the top-level description, in `--ssh`'s help, in
  `move`'s description and in the success block: a move is between two config homes of ONE
  machine, and `--ssh` runs the same command over there rather than moving a session across.
- The module docstring and every `--help` text were rewritten as public documentation, and the
  skill in `skills/move-session/` now covers `stop`, `matrix`, the mode choice, the cost of a
  move and the new warnings.

### Fixed

- **First-run dialogs were answered by the option's number — which matches nothing, and could
  confirm "No, exit".** On a cold target home the CLI renders these dialogs with the indexes
  hidden, the cancelling option first and focused, so v0.1.0's "type the digit, then Enter"
  pressed a key the dialog ignored and then confirmed whatever was focused: the move could
  decline its own folder-trust prompt and the window would exit. The answerer now reads the
  `❯` focus marker from the top of the dialog downwards: it presses Down only while the marker
  is not on the wanted option, presses Enter only when the marker's own line names the wanted
  label and not the cancelling one, presses nothing at all when one joined line holds both,
  and gives up after a small key budget. Down is known to wrap, the first matching prompt wins
  (so a "Press Enter" left in the scrollback can no longer confirm a live dialog), and the
  bypass warning is answered only when the move deliberately starts in that mode. The test
  that pinned the old behaviour was removed.
- **A dialog whose body had scrolled off the pane was never answered.** The search started at
  the line the prompt matched on; in a short window the first match is the confirm label and
  the focused cancel sits on the line above it, so no marker was found and the move waited out
  the whole connect timeout. The block is now anchored at the EARLIEST of the prompt line and
  the two option lines — still never above the dialog, so a marker in the scrollback is still
  ignored.
- **Two more cold-home dialogs are recognised.** The managed-settings trust dialog
  (`Do you trust these settings?` / `Yes, I trust these settings` / `No, exit Claude Code`)
  matched no rule at all. And a home whose settings set `permissions.defaultMode` and leave
  `disableAutoMode` unset is offered `Make auto mode your default permission mode?` once — a
  dialog that is **not** cancel-first: `Yes, set auto mode …` is drawn first and focused.
  The answerer walks the marker onto `No, keep …`, because accepting would rewrite that
  home's default permission mode for every later session (measured on 2.1.301).
- **`default` does draw a footer**, `⏸ manual mode on` (2.1.301), and it is now in the
  literals the pane is read for. Without it the one downgrade the cost block exists to catch
  — bypass asked for, `default` delivered — was invisible.
- **A pid is no longer signalled on the strength of a registry row.** Before any SIGTERM
  (`--stop-source` and `stop`), the registry's `procStart` must equal
  `LC_ALL=C TZ=UTC ps -o lstart= -p <pid>` and argv[0] must be the CLI itself. A `ps` that
  cannot answer is now a refusal — "nothing was stopped and nothing was proved" — rather than
  an assumption, and "could not ask" is kept distinct from "answered nothing". A registry row
  with **no** recorded start time is a refusal too: there is no name-based fallback, because
  "argv[0] is the Claude Code CLI" does not say WHICH session, and on a machine running
  several of them pid reuse by another one would pass it. Registry files outlive their
  processes and pids are reused.
- **`ps` is asked in the C locale, the way the CLI writes the value.** `ps -o lstart=` prints
  month and weekday names in the caller's locale, so on a non-English shell the prover
  compared a localised string against the C-locale string in the registry, called it a pid
  reuse, and left the source running after `--stop-source` — two copies answering, which is
  what the flag exists to prevent. The test helper now mirrors the WRITER rather than the
  tool, so the suite can see this class of bug at all.
- **`claude` is matched as argv[0]**, by basename or by the versioned bundle path, not as a
  substring of the whole command line — any command with "claude" in its arguments used to
  qualify.
- **"Signed in" no longer means "the state file names someone".** The login check is now
  tri-state: the home's recorded email *and* the existence of its credential. A home whose
  credential was removed or expired is refused before anything is copied or written, instead
  of being set up and then failing at the first API call. A credential store that cannot be
  asked is reported as `UNVERIFIED` and the move proceeds — "I could not look" is never
  promoted to "you are signed out".
- **The Keychain account falls back to the OS user name when `$USER` is not exported** (a
  container, `env -i`, some CI runners), as the CLI does, instead of jumping to the
  `claude-code-user` sentinel. The sentinel named an account that does not exist, every probe
  came back `errSecItemNotFound`, and every home read as signed out — a hard refusal, in
  exactly the unattended context the tool is for.
- **A home signed in with a trailing slash is no longer reported as signed out.** The Keychain
  item is named from the literal `CLAUDE_CONFIG_DIR`, and every path csm holds has been
  through `expanduser`, which drops the slash. One extra probe covers that one spelling, says
  which spelling served and warns that the home's literal differs. One extra, and no more: a
  speculative probe is another chance to hang on a locked keychain over ssh.
- **`settings.local.json` no longer erases the keys it does not mention.** Both readers merged
  whole top-level objects, so the common shape — an accumulated `permissions.allow` in
  `settings.local.json` — wiped `permissions.defaultMode`, `permissions.disableAutoMode` and
  an `env` block coming from `settings.json`: `csm matrix` printed `–` for the mode rows of
  every home that had one and called the rows divergent. Settings are now layered the way the
  CLI resolves them, **per key path**.
- **A state file that is not valid UTF-8 no longer kills `csm matrix` with a traceback.**
  `read_text` raises `UnicodeDecodeError`, which is a `ValueError` and not an `OSError`, so it
  escaped every guard. A byte-corrupted `.claude.json`, `settings.json` or plugin registry now
  reads as `unreadable`, with the reason in the cell — in the function whose contract is
  "three outcomes, never two", and in the command advertised as safe to run from a hook.
- **The first-run write takes the CLI's own `.claude.json.lock`**, re-reads the file inside it
  and merges only the two keys csm owns, so a write the CLI made in between (its
  `lastSessionId`, its end-of-turn metrics) is no longer lost — and neither is the trust key
  csm just wrote, which used to leave the moved window stopping on the dialog the move had
  pre-answered. A lock that cannot be taken within `CSM_LOCK_WAIT` seconds is a warning, never
  a refusal: an unattended move must not die on another session's lock. An abandoned lock is
  broken by age.
- **A move into a home that already holds this session id in a DIFFERENT project folder is
  refused**, naming the other folder. `--resume <id>` scans the home and takes the hit only
  when exactly one file matches, so the second copy would make the resume ambiguous and the
  window would die after the state file had already been written.
- **`--dry-run` now prints what the move will cost** — the thinking that does not cross
  organizations, the cold prompt cache, the transcript still naming the source account. A dry
  run is the last moment "move early, not at the limit" can still be acted on. The measured
  half ("it came up in X") stays with the real move.
- **`csm list --limit` and `--json` have help text**, and `--limit` says what surprised people:
  it caps the ENDED rows only, so `--limit 1` on a machine with forty live sessions still
  prints forty-one. `csm accounts` now says that its `live N` counts running processes, which
  `csm list` can legitimately show fewer of.
- **`csm stop` resolves its argument from the windows csm opened** before falling back to a
  full scan of every transcript in every home, so the common case reads a handful of files.
  The refusal text still comes from the full scan, so there is one producer of it.
- **Doc anchors render on GitHub.** Every heading in `docs/` carried a Pandoc-style `{#id}`,
  which GFM prints literally while deriving a different slug — 117 of the 118 anchored links
  in the repo, the README's matrix table among them, jumped nowhere. The ids are now
  `<a id="…"></a>` lines above their headings and every link resolves as written.

### Security

- The credential is still never read, printed, copied or logged. The new existence check uses
  only the exit code of `security find-generic-password -a "$USER" -s "<service>"` on macOS
  (never `-w` or `-g`, under a timeout) and the existence of `<home>/.credentials.json`
  elsewhere, which is never opened. The Keychain service name is derived from the literal
  `CLAUDE_CONFIG_DIR` string, so renaming a home orphans its login.
- Scrubbing by family closes the environment leak under future variable names: a token
  variable added by a later CLI release is dropped without this tool having to learn its name,
  so it cannot outrank the target home's login in the moved session.
- `csm matrix` reports MCP servers by name only — an entry's url, headers and env routinely
  carry tokens — reads no credential value, makes no network call and writes nothing, so it is
  safe to run from a hook or a scheduled check.
- `csm stop` can only end what csm itself started, proves the pid before signalling it, never
  stops the session running the command, and never deletes a transcript. When it kills a
  window it says plainly that doing so SIGHUPs the pane's process tree.

## [0.1.0] — 2026-10-13

Initial public release.

### Added

- `csm accounts`, `csm list` and `csm move`: find Claude Code sessions across every config
  home on a machine, and move one into another account's home, keeping the conversation.
- Account discovery (`~/.claude` as `default`, each `~/.claude-<name>` as `<name>`) and an
  optional accounts file naming each home and the login it must hold.
- Session matching by row number, session id or prefix, `claude.ai/code/session_…` link or
  title; refusals instead of guesses on anything ambiguous.
- Preflight refusals before the first byte is written: same account, a target that is signed
  out or signed in to the same login, a vanished working directory, a destination copy that is
  already running, an existing tmux window.
- Resume with Remote Control in a detached tmux window (`--no-remote-control` and
  `--foreground` as alternatives), the target home's first-run and folder-trust answers
  pre-written additively and atomically with a backup, `--stop-source` only after the moved
  session has printed its claude.ai link, and `--dry-run` for the plan alone.
- `--ssh HOST` to run the same command on another machine.
- The `move-session` skill, for driving a move by voice or from a phone.
- Fixture-only tests (fake homes, fake `claude`, fake tmux; no network, no account) and CI on
  ubuntu and macOS × Python 3.9 and 3.12.

[0.3.0]: https://github.com/yaroslavvb/claude-session-mover/compare/484f855...main
[0.2.0]: https://github.com/yaroslavvb/claude-session-mover/compare/48dde4b...484f855
[0.1.0]: https://github.com/yaroslavvb/claude-session-mover/commit/48dde4b
