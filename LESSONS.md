# Lessons for moving Claude Code sessions between accounts and machines

These are the rules that a month of moving sessions between several Claude accounts, on several
machines, taught the hard way. Each one has a one-line **rule**, **why** (the incident that taught
it), a **check** you can run, and the Claude Code version it was **verified** against.

Two kinds of fact are mixed here, and they age differently:

- **Stable** facts are slow-changing *and* written down somewhere (Anthropic's docs, or several
  independent tools that had to implement them). Re-check them once in a while.
- **Beta** facts are fast-changing *or* undocumented: on-disk layout, dialog order, environment
  variables with no documentation entry. Re-check every one of them after each Claude Code upgrade.
  `grep -n 'Beta' LESSONS.md` is your re-check list.

The checks read state and never print a secret: no `security … -w`, no `cat` of a credential
file. The commands assume macOS or Linux, `jq`, and homes named `~/.claude` (the default) and
`~/.claude-<name>`; adjust the paths to your layout. The longer narrative behind many of these is
in [docs/lessons.md](docs/lessons.md).

Contents: [A. What a move is](#a) · [B. Doing the move safely](#b) ·
[C. Credentials and identity](#c) · [D. Sharing one home between accounts](#d) ·
[E. Checks](#e) · [F. How to work on this](#f) · [Related tools](#related)

<a id="a"></a>

## A. What a move is

### L01 · A transcript is account-neutral; the home decides the account

- **Rule.** A session is `<home>/projects/<folder>/<id>.jsonl` plus a sibling `<id>/` directory.
  Copy both into another config home and `claude --resume <id>` there continues the same
  conversation as that home's login.
- **Why.** Measured end to end on throwaway sessions: the copy resumed with the whole
  conversation, connected as the target account, and spent the target's quota. Nothing in the
  transcript says which login wrote it.
- **Check.** On a throwaway session: ask it for a codeword, move it, then ask the moved session
  for the codeword.
  ```sh
  ls ~/.claude-a/projects/*/<id>.jsonl
  CLAUDE_CONFIG_DIR=~/.claude-b claude --resume <id>     # after the copy
  ```
- **Verified.** 2.1.296 (measured), re-run on 2.1.300. **Stable** mechanism; the file layout is
  **Beta**.

### L02 · Move the work, not the credential

- **Rule.** Answer a usage limit by moving one conversation to another of your logins. Never swap
  a credential under running sessions, and never pool logins behind a proxy.
- **Why.** One account's weekly cap stopped every job that ran on it for about 40 hours while two
  other accounts had most of their week left. Pooling hides which account paid, cannot move a
  running conversation, and Remote Control and claude.ai connectors need the real login anyway.
  An in-place swap gives one global login and changes live sessions on their next API call.
- **Check.** Before moving, read the target's own meters (`/usage` in a session on that home).
  The 5-hour window and the week are separate: an account with week to spare can still be capped
  for the next few hours.
- **Verified.** 2.1.296–2.1.308. **Stable.**

### L03 · Move early: across organizations the thinking is dropped and the session is re-read

- **Rule.** Move while the source still has quota, not at the limit, and expect the first turn
  after a move to cost a full re-read on the target.
- **Why.** Preserved thinking is bound to the organization that produced it. Across organizations
  the CLI drops it, and the first turn re-reads the whole conversation (a 44 MB transcript, once)
  on the target account's quota. The prompt cache starts cold either way.
- **Check.** Same organization or not:
  ```sh
  for h in ~/.claude-a ~/.claude-b; do jq -r '.oauthAccount.organizationUuid // "none"' "$h/.claude.json"; done
  ```
- **Verified.** 2.1.296–2.1.300. **Beta** (server behaviour, undocumented).

### L04 · A moved session gets a new claude.ai link

- **Rule.** Resuming under another home registers a new claude.ai session owned by the target
  account. The old link still opens the source's copy. Hand the user the new link.
- **Why.** A move that ended without printing the new `https://claude.ai/code/session_…` link
  left the phone with nowhere to go. The app may also show the thread starting at the move,
  although the agent holds the whole conversation.
- **Check.** The moved window prints `https://claude.ai/code/session_…`; `csm move` waits for it
  and refuses to stop the source until it appears.
- **Verified.** 2.1.296–2.1.308. **Beta.**

### L05 · A session's data is not all in `projects/`

- **Rule.** Carry the session's side data too: `file-history/<id>/` (what `/rewind` restores
  from), `tasks/<id>/`, and on older builds `todos/<id>*.json`. Copy it additively, never
  overwriting what the target already has.
- **Why.** Fourteen moves made before this rule each arrived with the whole conversation and
  without its rewind history. Nothing reported it.
- **Check.**
  ```sh
  ls -d ~/.claude-a/file-history/<id> ~/.claude-a/tasks/<id> 2>/dev/null
  ```
- **Verified.** 2.1.300 (`file-history/<id>/` present). **Beta.** `csm` carries these.

### L06 · What a move never carries

- **Rule.** Leave the login, `.claude.json`, `sessions/`, `session-env/`, `shell-snapshots/`,
  `jobs/` and `bridge-pointer.json` where they are, and never copy auto-memory (share the store
  instead; a copy is how one store becomes two that drift).
- **Why.** These describe a process, a machine or an account, not a conversation. Pasted images
  (`uploads/`) also stay behind. Connectors belong to the account and MCP sign-ins to the home
  (L16), so the moved session has the target's.
- **Check.** After a move, the target's `sessions/` holds only rows the target's own processes
  wrote: `ls ~/.claude-b/sessions/`.
- **Verified.** 2.1.300. **Beta.** `csm` pins this list in a test.

<a id="b"></a>

## B. Doing the move safely

### L07 · Check every refusal before writing a byte

- **Rule.** Run all the refusals first (no recorded cwd, a vanished cwd, the same id running in
  the target, a second copy of the id elsewhere in the target, a window that already exists),
  then write.
- **Why.** A move refused half-way had already written the target's state file and left a copy
  behind, which then made the next attempt ambiguous.
- **Check.** `csm move <id> --to <name> --dry-run` prints every refusal a real move would hit.
- **Verified.** 2.1.296–2.1.308. **Stable** (your own code).

### L08 · Two writers on one transcript is unrecoverable

- **Rule.** Refuse a move into a home where the same session is running, and never leave the
  source running into the same file.
- **Why.** Two CLIs appending to one `.jsonl` interleave their lines, and the resulting chain of
  `parentUuid`s cannot be untangled. Move A to B and later B back to A, and the "destination" is
  the original file, possibly still open in a process.
- **Check.** Who is running a session (the registry is per home, so ask every home):
  ```sh
  grep -l '"sessionId": *"<id>"' ~/.claude*/sessions/*.json
  ```
- **Verified.** 2.1.300–2.1.308. **Beta.**

### L09 · `--resume <id>` finds an id only when exactly one file matches

- **Rule.** Never leave two copies of one id in different project folders of the same home.
  Reuse the source's folder name instead of recomputing it from the cwd.
- **Why.** The CLI looks in the cwd's folder, then sibling worktrees, then every folder, and takes
  the hit only when exactly one file matches. The folder is named after the path the session was
  *launched* from, while the transcript records the *resolved* cwd, so a session started through
  a symlink lives under a name no slug rule derives (56 transcripts in one case).
- **Check.**
  ```sh
  ls ~/.claude-b/projects/*/<id>.jsonl | wc -l     # must be 0 or 1
  ```
- **Verified.** 2.1.296–2.1.300. **Beta.**

### L10 · Pre-answer a cold home's first-run gates, and never answer a dialog by number

- **Rule.** On a home that has never opened this folder, pre-set workspace trust for that path
  and onboarding in its state file, additively and with a backup. If you must drive a dialog,
  read the focused option off the screen and walk to the one you want.
- **Why.** A resumed session in a detached window sat at a trust dialog nobody could see. The
  dialogs draw no option numbers, put the cancelling option first and focus it ("No, exit"), so
  "type 2, Enter" matched nothing, and Enter alone would have exited. One dialog ("Make auto mode
  your default?") puts the accepting answer first instead.
- **Check.**
  ```sh
  jq --arg p "$PWD" '.projects[$p].hasTrustDialogAccepted, .hasCompletedOnboarding' ~/.claude-b/.claude.json
  ```
- **Verified.** 2.1.296–2.1.300. **Beta** (dialog wording and order change between builds).

### L11 · Scrub the environment; an env token outranks the config dir

- **Rule.** Start the moved session with every `CLAUDE*` and `ANTHROPIC*` variable removed (plus
  `CLOUD_ML_REGION` and `AWS_BEARER_TOKEN_BEDROCK`), then set only `CLAUDE_CONFIG_DIR`. Check
  shared `settings.json` `env` blocks for credentials too.
- **Why.** `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN` and the
  Bedrock/Vertex/Foundry switches outrank every home's own login. A process started from inside a
  session also inherits about twenty `CLAUDE_CODE_*` variables naming the *parent* session. One
  credential line in a `settings.json` that several homes share outranks all of their logins at
  once.
- **Check.** Both must print nothing:
  ```sh
  env | grep -E '^(ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN|CLAUDE_CODE_OAUTH_TOKEN|CLAUDE_CODE_USE_(BEDROCK|VERTEX|FOUNDRY))='
  jq -r '.env // {} | keys[]' ~/.claude*/settings.json 2>/dev/null | grep -E 'API_KEY|AUTH_TOKEN|OAUTH_TOKEN'
  ```
- **Verified.** 2.1.300–2.1.308. **Stable** (the precedence is documented); the inherited
  variable names are **Beta**.

### L12 · A permission mode belongs to a process

- **Rule.** Choose the moved session's mode explicitly, never weaken it, never silently widen a
  mode the user picked (`plan`, `acceptEdits`), and report the mode it actually came up in.
- **Why.** claude.ai's stored mode for a session can override the `--permission-mode` flag a
  Remote Control server passes, so sessions came up in `auto` eighteen hours after the setting
  changed, and one moved session came up in `default`, where every tool call would have waited.
  A settings edit is not a cutover; a restart or a move is.
- **Check.** The mode the resumed session wrote after the copy, or its pane footer:
  ```sh
  tail -c 65536 ~/.claude-b/projects/<folder>/<id>.jsonl | grep -o '"permissionMode":"[A-Za-z]*"' | tail -1
  ```
- **Verified.** 2.1.296–2.1.300. **Beta** (permission modes are one of the fastest-changing
  surfaces).

### L13 · Capture the pane before you end anything; prove the pid before you signal it

- **Rule.** Save the source pane's whole scrollback before stopping it, signal a process only
  after its pid *and* start time match the registry, and never stop the session running the move.
- **Why.** A prompt typed and not yet sent exists only in the scrollback; killing a tmux session
  once ended six sessions, and two unsent drafts survived only because someone had captured the
  panes. A pid from a stale registry row can belong to another process by now.
- **Check.**
  ```sh
  tmux capture-pane -p -S - -t '=<session>:<window>' > before-stop.txt
  ps -o lstart= -p <pid>     # compare with the registry's procStart
  ```
- **Verified.** 2.1.300. **Stable** (tmux and ps); the registry fields are **Beta**.

### L14 · Tell the moved session that it moved

- **Rule.** Put the move in the conversation itself: the first prompt after a move (or a hidden
  line appended to the transcript) should name both accounts, both machines if they differ, and
  what stayed behind.
- **Why.** A resume does not fire the session-start hook, so nothing else reaches the agent. A
  session moved to another machine assumed its old machine and account, and that its background
  jobs had died; they were still running at the origin. The copied transcript also names the
  source account inside itself, so never trust a moved session's description of its own account.
- **Check.** Ask the moved session which account and machine it is on, and compare with
  `jq -r .oauthAccount.emailAddress ~/.claude-b/.claude.json` and `hostname`.
- **Verified.** 2.1.300. **Beta.** `csm` appends exactly such a line to the copy on every move —
  one hidden `isMeta` line, chained by `parentUuid` — so it survives a restart, a later move and a
  compaction's re-read, which a first prompt does not.

### L15 · Memory can follow a session to another machine; its work often cannot

- **Rule.** Before moving a session between machines, list what is bound to the origin: running
  processes, paired devices, data outside the repo, an uncommitted working tree. Never stop the
  source of a cross-machine move.
- **Why.** The first machine-to-machine move took about 90 seconds and left six processes, a
  paired device and 20 GB of data behind. `csm` carries the conversation — between homes on a
  machine, and between machines with `--from-machine`, which never stops the source and lists
  what it left running. `--ssh HOST` is the other thing: it runs the move *on* that host.
- **Check.** `pgrep -P <source pid>` and `git -C <cwd> status --short` on the origin.
- **Verified.** 2.1.300. **Stable.**

<a id="c"></a>

## C. Credentials and identity

### L16 · An account is its token, not the file that names it

- **Rule.** Decide whether a home is signed in from its credential, and give "could not read it"
  its own answer, never "signed out" or "ok". `oauthAccount` in `.claude.json` is a first look
  only.
- **Why.** A state file kept naming an account hours after its credential was removed, so
  file-based checks read "ok" for homes that could not log in. Over plain ssh a Mac's Keychain
  cannot be read at all. A cached `oauthAccount` that is absent heals itself; one that is present
  and wrong never does.
- **Check.** Existence only, never the value (macOS; on Linux, `test -s <home>/.credentials.json`):
  ```sh
  security find-generic-password -s "Claude Code-credentials-<hash>" -a "$USER" >/dev/null 2>&1 && echo present || echo "absent or unreadable"
  ```
- **Verified.** 2.1.296–2.1.308. **Stable** rule; the store's name is **Beta** (L17).

### L17 · The macOS Keychain slot is named from a hash of the literal config-dir string

- **Rule.** Treat the slot name as `Claude Code-credentials-` + the first 8 hex digits of
  sha256 over the NFC form of the `CLAUDE_CONFIG_DIR` string, and the bare `Claude
  Code-credentials` when it is unset. So never rename or move a home on macOS without copying its
  slot first: copy, keep a dated rollback, verify the new home serves one tiny request, then
  delete.
- **Why.** A plain `mv` of a home signs it out. Doing the copy first moved sixteen homes for zero
  sign-ins, and caught a slot holding two items where a bare lookup returned the wrong one.
  The inputs are disputed: independent tools hash the literal string, the canonicalized path, the
  raw string without normalization, or the resolved absolute path. They agree for a plain
  `~/.claude-x`, and diverge for a trailing slash, a home behind a symlink or a decomposed
  character. Spelling the default home out (`CLAUDE_CONFIG_DIR=~/.claude`) selects a different
  slot than leaving the variable unset, and reads as signed out.
- **Check.** Compute the name and look it up by account:
  ```sh
  printf %s "$CLAUDE_CONFIG_DIR" | python3 -c 'import sys,hashlib,unicodedata;print("Claude Code-credentials-"+hashlib.sha256(unicodedata.normalize("NFC",sys.stdin.read()).encode()).hexdigest()[:8])'
  ```
  After an upgrade, also check whether the service name gained a suffix: one tool reports a
  build-time suffix that is empty on the stable channel only.
- **Verified.** 2.1.296–2.1.308. **Beta.** Anthropic documents the per-dir keying; the exact
  formula is not documented.

### L18 · `CLAUDE_SECURESTORAGE_CONFIG_DIR` exists and is undocumented

- **Rule.** Know that the credential store can be chosen apart from the config dir, and do not
  build on it without a canary. When it is set, the credential (and the Keychain suffix) follow
  it first, then `CLAUDE_CONFIG_DIR`, then `~/.claude`; the empty string means the default slot.
- **Why.** It is the one lever that would let several accounts share one config home with only
  the credential switching. It is present in the 2.1.308 binary, at least one public tool
  switches accounts with it and more than a dozen read it, yet it has no changelog entry and no
  row in the environment-variable reference. A policy-level guard upstream refuses it from a
  user-tier setter, so it has to be set in the launcher's process environment.
- **Check.**
  ```sh
  strings "$(python3 -c 'import os,shutil;print(os.path.realpath(shutil.which("claude")))')" | grep -c CLAUDE_SECURESTORAGE_CONFIG_DIR
  ```
- **Verified.** Present in 2.1.308; never exercised here. **Beta.**

### L19 · `.claude.json` mixes identity with per-project trust

- **Rule.** Never share or copy a whole `.claude.json` between homes. Edit only the keys you mean
  (per-project trust, onboarding), atomically, with a backup, and keep the file's mode.
- **Why.** One file holds three concerns: `oauthAccount` and account-derived caches; per-home
  machine ids; and the `projects` map with per-project trust, allowed tools and MCP servers. The
  part worth sharing is trapped with the identity. When several sessions share one home, the
  cached account is rewritten by whichever refreshed last, so `/status` can name another
  session's account. Claude Code rewrites the file constantly, so a comment or a hand-added key
  there does not survive.
- **Check.**
  ```sh
  jq '{account: .oauthAccount.emailAddress, org: .oauthAccount.organizationUuid, projects: (.projects // {} | length)}' ~/.claude-b/.claude.json
  ```
- **Verified.** 2.1.300–2.1.308. **Beta.**

### L20 · One sign-in per browser profile

- **Rule.** Open each sign-in link in a browser signed in as that account, never chain two
  sign-ins in one browser window, and read the account back afterwards.
- **Why.** A login authorizes whatever account the browser holds, not the email the CLI hinted.
  Two sign-ins chained in one browser put one account's token into another's home, and that
  home's sessions spent the wrong quota for a day.
- **Check.** After signing in: `jq -r .oauthAccount.emailAddress <home>/.claude.json`, and confirm
  with `/status` in a session on that home.
- **Verified.** 2.1.296–2.1.308. **Stable.**

### L21 · Keep the default home free of a login you did not mean

- **Rule.** If you use named homes, make sure the default `~/.claude` holds no credential, no
  bare Keychain slot and no `oauthAccount`, so a bare `claude` fails loudly instead of spending an
  unknown account.
- **Why.** A desktop app relaunched at login wrote its account and a bare slot back into the
  default home twice in six days. A leftover credentials file in the default home also makes other
  windows read "Not logged in" after a `/login` that succeeded (an upstream fix says so).
- **Check.** All three should print nothing:
  ```sh
  ls ~/.claude/.credentials.json 2>/dev/null
  security find-generic-password -s "Claude Code-credentials" -a "$USER" >/dev/null 2>&1 && echo bare slot present
  jq -r '.oauthAccount.emailAddress // empty' ~/.claude.json
  ```
- **Verified.** 2.1.300–2.1.308. **Stable** rule; the writers are **Beta**.

### L22 · MCP grants ride the credential; connectors belong to the account

- **Rule.** Expect a moved session to have the target home's MCP sign-ins and the target
  account's claude.ai connectors, not the source's. Enable the same connectors on every account
  in a browser before you need to move.
- **Why.** MCP OAuth tokens are stored inside the same credential blob as the login, so each home
  signs in to each server on its own (36 "Authorize" clicks to give one plugin's grant to 35
  homes). No terminal can attach a claude.ai connector, so a moved session that reads mail
  through a connector loses it mid-task.
- **Check.** Before moving, list the connectors the session used:
  ```sh
  grep -o '"mcp__claude_ai_[A-Za-z0-9_]*' ~/.claude-a/projects/<folder>/<id>.jsonl | sort -u
  ```
- **Verified.** 2.1.300–2.1.308. **Beta.**

### L23 · Never write to the vendor's credential store

- **Rule.** Read a credential's existence; never refresh, rewrite or duplicate a token behind the
  CLI's back. To make an idle home refresh, start the CLI in that home.
- **Why.** Refresh tokens rotate. When one grant lives in two places, side A refreshes, the server
  revokes the old access token, side B fails, force-refreshes with the superseded token, and the
  CLI clears the login. Several tools in this space refuse to refresh for exactly this reason.
- **Check.** Find anything in your own scripts that reads or writes a secret:
  ```sh
  grep -rnE 'find-generic-password.* -w|add-generic-password|delete-generic-password|\.credentials\.json' <your scripts>
  ```
- **Verified.** 2.1.300–2.1.308. **Stable.**

<a id="d"></a>

## D. Sharing one home between accounts

Some people make accounts interchangeable by linking each account home's `projects/` (and
`file-history/`) into one shared tree, so every account sees every transcript and a "move" is just a
resume under the other login. `csm` handles that layout (one row per file, no copy onto itself, a
live-twin check across every home), but the layout has costs that are easy to miss.

### L24 · `projects/<slug>/bridge-pointer.json` is per-account Remote Control state

- **Rule.** Do not share a `projects/` tree between accounts on a machine that runs Remote Control
  servers. If you share one anyway, exclude `bridge-pointer.json` by name.
- **Why.** Each Remote Control server writes `projects/<project key>/bridge-pointer.json`: its
  environment id, the pid and start time of the writer, and the session ids it reattaches after a
  restart. Several servers for one project (one per account) each write their own; with one
  shared folder they overwrite one file, and after a restart a server reads another account's
  environment and loses its own sessions' reattach. A dry run of a merge found these on every
  machine running servers and none on the one machine that ran none. Whether the pointer is only a
  cache (the transcript also records the bridge join) or the only copy is disputed between tools.
- **Check.**
  ```sh
  find ~/.claude*/projects -maxdepth 2 -name bridge-pointer.json
  ```
- **Verified.** 2.1.308. **Beta.**

### L25 · Writes reopen the transcript by path; no file descriptor is held

- **Rule.** You can swap a project folder for a link under a live session without splitting its
  log, but do it when nothing is writing, and re-compare the files right before the swap.
- **Why.** No running `claude` process held a transcript open (20 samples over 43 processes):
  each write reopens the file by path. The risk is the merge itself: a live transcript that is
  momentarily a byte prefix of a stopped twin can be discarded, losing every line written after
  the comparison.
- **Check.**
  ```sh
  lsof -c claude 2>/dev/null | grep '\.jsonl$'     # expect nothing
  ```
- **Verified.** 2.1.308. **Beta.**

### L26 · `cleanupPeriodDays` prunes; pin it before linking anything

- **Rule.** Set `cleanupPeriodDays` high in every home that can reach a shared tree *before* you
  link it, and never park files you want to keep under a name inside the tree the pruner sweeps.
- **Why.** The startup pruner deletes transcripts older than the retention period (30 days by
  default). With one shared `projects/`, any home still on the default prunes every account's
  history, and the product's own `*.superseded-*` / `*.orphaned-*` spellings sit inside that
  sweep, so they are a hand-off, not an archive. `claude purge` under a shared tree deletes every
  account's transcripts for a project.
- **Check.**
  ```sh
  for h in ~/.claude ~/.claude-*; do printf '%s ' "$h"; jq -r '.cleanupPeriodDays // "default (30)"' "$h/settings.json" 2>/dev/null || echo "no settings.json"; done
  ```
- **Verified.** 2.1.300–2.1.308. **Stable** (documented setting).

### L27 · A symlink is not a redirect

- **Rule.** Redirect state with the environment key the product gives you
  (`CLAUDE_CODE_REMOTE_MEMORY_DIR` or `autoMemoryDirectory` for memory), symlink configuration
  files only, and resume a session in a linked tree by id, not through the picker.
- **Why.** A symlinked memory directory made every write ask for permission and stalled an
  unattended session for minutes, because the write auto-allow does not follow the link. The
  session picker has regressed through symlinked `projects/` entries more than once; resume by id
  kept working.
- **Check.** Throwaway session in a linked home: have it write a memory note and confirm no
  permission prompt appears; then `claude --resume <id>` from a second home finds it.
- **Verified.** 2.1.296–2.1.308. **Beta.**

### L28 · A linked shared file can silently become a real file

- **Rule.** Check every shared path with `lstat`, not "does it exist", and treat a regular file
  where a link belongs as a fault: move it aside, never delete it. Refuse to start a home whose
  credential entry is a symlink.
- **Why.** Atomic writes replace a symlink with a real file. The home keeps working; it just stops
  being the shared copy, and an existence check passes.
- **Check.**
  ```sh
  for h in ~/.claude-*; do for f in settings.json CLAUDE.md skills plugins; do [ -e "$h/$f" ] && [ ! -L "$h/$f" ] && echo "$h/$f is real, not a link"; done; done
  ```
- **Verified.** 2.1.300–2.1.308. **Beta.**

### L29 · Share by a written list; an unclassified entry stays private and is reported

- **Rule.** Decide per entry whether it is shared, and keep that decision in one manifest. A new
  top-level entry nobody has classified stays private and is reported, never linked by default.
- **Why.** When another CLI's update added about ten new per-account entries, a skip-list tool
  linked every one into every profile, and one profile then talked to another's daemon and
  quota. Claude Code adds and renames home entries often; an unknown one is the signal.
- **Check.**
  ```sh
  diff <(ls -A ~/.claude-a) <(ls -A ~/.claude-b)     # bash or zsh
  ```
- **Verified.** 2.1.308. **Stable** rule; the entry list is **Beta**.

### L30 · A shared directory is a shared namespace

- **Rule.** Expect other programs to write into anything you centralize, mark what you own, and
  stop a writer rather than parking its files.
- **Why.** In ten days three unrelated programs wrote into Claude's config: a desktop app put a
  login into the default home; another app re-created 22 skills every 60 seconds in a skills
  directory every account reads; a package manager overwrote a patched build. Every account
  sharing that directory got the injected skills.
- **Check.** Re-read a parked directory an hour later: `ls -lt ~/.claude/skills | head`.
- **Verified.** 2.1.300–2.1.308. **Beta.**

<a id="e"></a>

## E. Checks

### L31 · Unread is never green

- **Rule.** Give every check three outcomes, `ok` (looked everywhere), `FAULT` and `INCOMPLETE`,
  and never print `ok` over something you could not read.
- **Why.** A parity check printed "ok: 15 of 35 homes match" and exited 0 with most machines never
  read. A probe that timed out was once counted as four faults nobody had measured. `csm` reports
  a login as `ok`, `CREDENTIAL GONE` or `ok (UNVERIFIED)` for the same reason.
- **Check.** `csm matrix --check; echo $?` exits 1 only on a measured divergence, never on an
  unknown.
- **Verified.** 2.1.300–2.1.308. **Stable.**

### L32 · Prove a move by its delivery, not by its files

- **Rule.** A move is done when the moved session answers about its own first turn under the
  target login, not when the files land or the process starts.
- **Why.** Versions, configs and liveness flags have all read green over something that delivered
  nothing.
- **Check.** In the moved session: "What was the first thing I asked you in this session?" and
  `/status` for the account.
- **Verified.** 2.1.296–2.1.308. **Stable.**

### L33 · Version-stamp every claim about the binary

- **Rule.** Write the Claude Code version next to every on-disk fact you rely on, and re-check the
  Beta ones after each upgrade.
- **Why.** About fifty releases ship in two months. Docs that kept version-stamped claims stayed
  usable; one tool still documents a credential layout that was right in August and wrong two
  months later. The container (the config home and its layout) changes rarely; skills, plugins,
  hooks and permission modes change weekly.
- **Check.** `claude --version`, then `grep -n 'Beta' LESSONS.md`.
- **Verified.** 2.1.308. **Stable.**

<a id="f"></a>

## F. How to work on this

### L34 · Learn every kind of per-home state once, in one home

- **Rule.** Before making several accounts interchangeable, list every kind of state one home
  holds (first-run gates, MCP grants, plugins, connectors, memory, the default home) in one home,
  and write it down before touching the second.
- **Why.** The same question was asked seven times in six days, each kind found by failing in
  production on every home. `csm matrix` is that list for your own machine.
- **Check.** `csm matrix`.
- **Verified.** 2.1.300–2.1.308. **Stable.**

### L35 · Never drive a change from the home you are changing

- **Rule.** Run a home move, a retire or a merge from a session in a home the plan leaves alone,
  and stop self-healing supervisors before the first step.
- **Why.** A restructure run from a Remote Control session on the very home it had to retire left
  one account unmovable for two days. Old supervisors re-created deleted state within the hour.
- **Check.** `echo "$CLAUDE_CONFIG_DIR"` in the driving session is not one of the homes in the plan.
- **Verified.** 2.1.296–2.1.308. **Stable.**

### L36 · A third party's implementation is the stability test

- **Rule.** Treat a Claude Code primitive as stable when tools outside Anthropic implement it
  generically, and as Beta when they special-case it.
- **Why.** What has converged across tools: the env-selected config home, `SKILL.md` at a slug
  path, the `mcpServers` object, JSONL transcripts, resume by id. What each special-cases: where
  the login lives, credential-store mechanics, the state file, transcript layout, hook event names.
- **Check.** Before relying on a new primitive, search a few of the [related tools](#related) for
  it.
- **Verified.** 2.1.308. **Stable.**

<a id="related"></a>

## Related tools

Actively developed tools that move or share sessions or accounts, as of 22 Oct 2026. One line each,
from each project's own description or a read of its source; check the project before relying on
it.

**Moving or syncing sessions**

- [claude-sesh-mover](https://github.com/Sertelegger/claude-sesh-mover) — a Claude Code plugin that
  exports, imports and migrates sessions between profiles, containers and machines; refuses a
  running session.
- [hatswap](https://github.com/orvi2014/hatswap) — claims concurrent accounts, a live session move
  between them, folders pinned to accounts, and handoff to Codex.
- [claude-rotate](https://github.com/OpenGraphLabs/claude-rotate) — resumes a session on the next
  account when a usage limit hits, from a StopFailure hook.
- [cux](https://github.com/inulute/cux) — swaps the credential under one home on a cap and resumes
  the same conversation, driven by hooks.
- [claude-migrate](https://github.com/onlyilkr/claude-migrate) — moves desktop-app Code sessions to
  another account on the same Mac, dry-run first and undoable.
- [claude-transplant](https://github.com/vitaliyhayda/claude-transplant) — moves desktop-app history
  to the account in use after a switch.
- [remote-sessions](https://github.com/antoniolg/remote-sessions) — resumes any local conversation
  with Remote Control and returns its claude.ai link.
- [codex-claude-transfer](https://github.com/ahmojo/codex-claude-transfer) — moves Codex and Claude
  Code sessions between machines as a signed, encrypted bundle with cwd remapping.
- [claude-nomad](https://github.com/funkadelic/claude-nomad) — syncs a Claude Code setup and session
  history through a private git repo, rewriting machine-specific paths; never syncs credentials.
- [claude-sync](https://github.com/tawanorg/claude-sync) — encrypted session sync between your own
  devices.
- [ccsync](https://github.com/trananhhh/ccsync) — cross-machine sync of the Claude Code tree; its
  default ignore list excludes `bridge-pointer.json`.

**Accounts, homes and switching**

- [tokenmaxxing](https://github.com/anaclumos/tokenmaxxing) — a `claude` shim that keeps one real
  `~/.claude` and switches only the credential store, via `CLAUDE_SECURESTORAGE_CONFIG_DIR`.
- [Orca](https://github.com/stablyai/orca) — runs agent CLIs on your own subscriptions; a config dir
  per account with shared settings, instructions, skills and plugins, one active account at a time.
- [agent-shim](https://github.com/exadev/agent-shim) — a per-account link farm into one real
  `~/.claude`, with every home entry classified; refuses to launch on an ambient credential.
- [claude-profile-manager](https://github.com/jakubkontra/claude-profile-manager) — a generated
  `claude-<name>` wrapper per account, sharing commands, skills, agents, plugins and `projects/`.
- [clausona](https://github.com/larcane97/clausona) — profile manager for Claude Code and Codex
  through a shell hook, with documented lists of what must stay per account.
- [clauth](https://github.com/uwuclxdy/clauth) — account manager and usage monitor offering both an
  in-place swap and a config dir per session; documents the pruner hazard of a shared `projects/`.
- [AgEnD](https://github.com/songsid/agend) — a chat-driven daemon for several agent CLIs that can
  carry a conversation to another credential profile; sharing is an allow-list.
- [sideby](https://github.com/adonis0123/sideby) — account manager for several CLIs with declared
  share modes and dated decision records; never reads a credential.
- [claude-swap](https://github.com/realiti4/claude-swap) — swaps the login under one home, with
  rate-limit rotation and per-terminal concurrency.
- [ccswap](https://github.com/errhythm/ccswap) — several Claude and Codex logins side by side, with
  per-account history unless shared on request.
- [coding_agent_account_manager](https://github.com/dicklesworthstone/coding_agent_account_manager)
  — fast OAuth switching across several agent CLIs, in vault, isolated and shallow-home modes.
- [planhop](https://github.com/bendechrai/planhop) — runs Claude Code on whichever subscription's
  quota resets soonest, sharing everything but the login, `projects/` included.

**Remote Control and indexing**

- [claude-rc-keeper](https://github.com/PythonNut/claude-rc-keeper) — keeps several Remote Control
  hosts alive across reboots for one account; reads and writes `bridge-pointer.json`.
- [clauster](https://github.com/schubydoo/clauster) — spawns, rediscovers and prunes Remote Control
  bridges per project.
- [command-center](https://github.com/austinginder/command-center) — indexes several CLIs'
  transcript stores, `~/.claude-*` homes included, with a resume command per session that sets the
  matching `CLAUDE_CONFIG_DIR`.
- [sessionwiki](https://github.com/youdie006/sessionwiki) — one local full-text index over sessions
  from many tools, archived before the tool prunes them.
