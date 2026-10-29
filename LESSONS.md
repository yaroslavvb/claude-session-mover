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
[E. Checks](#e) · [F. How to work on this](#f) ·
[G. Reviving a session that died](#g) · [Related tools](#related)

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

<a id="g"></a>

## G. Reviving a session that died

Measured on macOS, CLI **2.1.312**, Wed 28 Oct 2026, against the incident that prompted them: a
Remote Control session whose turn died on a usage limit at 17:46 local time and sat dead for 17
hours. Every one of these is **Beta**: it is behaviour and layout nobody documents.

### L37 · A Remote Control session's transcript name is arithmetic on its link

- **Rule.** Do not look a Remote Control session up — compute it.
  `uuid5(3ab19d7e-9f35-45c2-926e-75e271cc60b3, "https://api.anthropic.com/v1/code/sessions/cse_<bare>")`
  is the local transcript's id, and claude.ai's `session_<bare>` is the bridge's `cse_<bare>` with
  the prefix swapped.
- **Why.** A server-spawned child writes no `bridge-session` line into its own transcript, so a
  session that has stopped can be resolved only through a live registry row — which a dead session
  does not have. Every dead phone session was unreachable by the one name anybody still had for it:
  its link. Verified on **37/37** live registry rows carrying both ids, across six account homes,
  and 0/37 against any other name form; the namespace constant is byte-identical in 2.1.310, .311
  and .312. A spacesheep session page's uuid *is* the local id too.
- **Check.** `csm revive <link> --dry-run`, or recompute it from a live row:
  `python3 -c 'import uuid,sys;print(uuid.uuid5(uuid.UUID("3ab19d7e-9f35-45c2-926e-75e271cc60b3"),"https://api.anthropic.com/v1/code/sessions/"+sys.argv[1]))' cse_<bare>`
  against the `sessionId` in `<home>/sessions/*.json`. Re-check after every CLI upgrade: `csm` keeps
  a canary that greps the constant out of the installed bundle and says `derivation unverified for
  CLI <v>` when it is gone.
- **Verified.** 2.1.310–2.1.312. **Beta.**

### L38 · A respawned server child comes back idle and says nothing

- **Rule.** Bringing the *process* back is not bringing the *session* back. Whoever revives a
  session has to supply the next message.
- **Why.** The bridge respawns a child lazily, when the server has work for that session (the app
  opening it, a message, a trigger firing), and the respawned child re-sends nothing and writes
  nothing. Measured on the incident transcript: between the 429 at 00:46:14Z and the peer message at
  18:03:30Z there is **no entry at all** for the 17:56Z respawn — only three untimestamped
  bookkeeping entries — and the session-start attachments (`instructions`, `date changed`,
  `skill_listing`) arrive with the first turn *after* the wake, 170 ms after the prompt.
- **Check.** Open a dead Remote Control session in the app, then `wc -l` its transcript before and
  after: the line count does not move until something is typed.
- **Verified.** 2.1.312. **Beta.**

### L39 · Reviving a server child in its own home must FORK, never reuse its id

- **Rule.** Resume a server-spawned session with `--fork-session` and an id you chose yourself; never
  start a second process on the old local id, and never `--resume=<url>`.
- **Why.** Three measurements meet here. `claude --resume <uuid>` of such a session does **not**
  re-attach its claude.ai session (its ingress url is null) — it registers a *new* link. A lazy
  respawn of the old link can arrive at any time afterwards, and it has the **same local id**, so
  two CLIs would append to one transcript — the unrecoverable state of **L08**.
  And `--resume=<https url>` hydrates from the server and **replaces** the local transcript
  (`Hydrated N entries from remote`; it declines only to replace a non-empty local file with an
  empty server set, `hydrate_skip_zero_content_replace`). A fork leaves the old file byte-identical
  and gives the new conversation a writer of its own — at the price of a new link, which still has
  to be said out loud, because the old link goes on opening the old copy. A self-hosted
  `--remote-control=` session is the exception: it does re-attach, and needs no fork.
- **Check.** Fork a throwaway: `claude --resume <old> --fork-session --session-id <new uuid4>
  --remote-control=<label>`, then `shasum` the old transcript before and after and confirm only
  `<new>.jsonl` was written.
- **Verified.** 2.1.312. **Beta.**

### L40 · Never wake a session before its limit resets — the wake is consumed and lost

- **Rule.** Read `quotaLimits.resetsAt` off the stop line and refuse to deliver anything before it.
  A pending wake is not queued behind a limit; it is spent on it.
- **Why.** The incident's own heartbeat fired 45 minutes **inside** the five-hour window: the prompt
  is at 2026-10-28T00:46:13.673Z (17:46 PDT, `isMeta: true`) and the next line is another 429 at
  00:46:14.230Z. One turn, one more rate-limit line, and nothing re-fired after the 18:30 reset — the
  session then sat dead until morning. Classes matter as much as the clock: a session or weekly limit
  clears at the reset, while monthly-spend, credits and model limits do not clear by waiting at all.
- **Check.** `csm revive <spec> --dry-run` prints `resets <time>` and refuses while it is in force;
  the raw fact is the last `quotaLimits` object in the transcript's tail.
- **Verified.** 2.1.312. **Beta.**

### L41 · A hand-rolled peer frame is held for a human; the CLI's own SendMessage is delivered

- **Rule.** Wake a live session through Claude Code's own `SendMessage` tool, run from a headless
  `claude -p` helper under that session's config home — never by writing frames to its peer socket
  from a script.
- **Why.** The socket protocol is readable (`sessions/<pid>.json` → `messagingSocketPath`, token in
  `sessions/<pid>.<sha256(socketPath)>.key`, then `{"type":"auth",…}` and a `{"type":"user",…}`
  frame) and the frame does arrive — and is then **held**, with a dialog: `Held peer message … The
  sender did not attest its permission mode and this session bypasses prompts. Review it below, or
  set "crossSessionInbound" to "accept".` A tool that produces a dialog nobody is there to answer
  has not woken anything. The relay path was measured instead: `claude -p --model haiku
  --permission-mode bypassPermissions --name "csm revive (<machine>)" --output-format json
  "<send this verbatim>"` with `< /dev/null`, delivered to an idle bypass session in ~5–8 s for
  $0.002–0.006, recorded honestly on the receiver (`isMeta: true, turnOrigin: "peer", origin:
  {kind: "peer", name: …, fromMode: "bypass", verifiedPeerPid, msg_id}`) and shown in the app as a
  message from that sender. `SendMessage` was found without any `--allowedTools`.
- **Check.** Send a one-word message to a throwaway session both ways and read the receiving pane:
  the script's frame waits on a dialog, the relay's lands as a peer message.
- **Verified.** 2.1.312. **Beta.**

### L42 · A positional prompt is recorded as the user's own typing

- **Rule.** Never hand a resumed session a positional prompt that a tool wrote. Deliver it as a peer
  message instead, and stamp it.
- **Why.** Whatever the text says about itself, the line written for a positional prompt carries
  `origin: {kind: "human"}, promptSource: "typed", turnOrigin: "human"` — so a sentence a tool
  composed is indistinguishable, in the conversation's own record, from one the user typed. That
  record is what the session reads back after a compaction, and what the person reads when they ask
  what they said. (The honest in-transcript alternative, an `isMeta` line plus `--reply-on-resume`,
  works and self-starts — but it writes into a transcript, and for a fork it would have to be written
  into the **old** one, where a later respawn of the old link can pick it up as an interrupted turn:
  two actors on one conversation. Never pass `--reply-on-resume` together with a positional prompt
  either — the prompt wins, typed as human.)
- **Check.** Resume a throwaway with a positional prompt and read the last user line of its
  transcript: `jq -c 'select(.type=="user")|{promptSource,turnOrigin,origin}' <file> | tail -1`.
- **Verified.** 2.1.312. **Beta.**

### L43 · The CLI's own quota auto-resume never covers a worker, and dies with the process

- **Rule.** Do not count on Claude Code continuing itself after a limit resets. Build the revive.
- **Why.** 2.1.312 does have a quota auto-resume, gated on `isInteractive() && !bg && !remote` plus
  the `tengu_marble_heron` server flag and the `autoContinueAtUsageLimit` setting (both on by
  default). A Remote Control **server child runs `--print`**, so it is never eligible — and it was
  never observed firing in this multi-account setup at all (0 transcripts). It is also an in-process wait, and
  the bundle spells out what ends it: `process_exit: "Automatic continue cancelled · Claude Code
  exited during the wait, so the task will not resume on its own when the usage limit resets"`,
  beside `background_handoff`, `relaunch`, `desktop_handoff` and `cloud_handoff`. A session killed by
  a restart — the common case — has no waiting process left to continue it.
- **Check.** `strings <the CLI binary> | grep -c 'Automatic continue cancelled'`, and look for the
  CLI's own "usage limit has reset" continuation text in your transcripts: in the setup this was
  written against there is none.
- **Verified.** 2.1.312. **Beta.**

### L44 · The external-imports dialog blocks an unattended start

- **Rule.** A cold-start gate list that misses one dialog is a start that hangs. Add *"Allow external
  CLAUDE.md file imports?"* to the answerer, and answer it with its focused default, **No**.
- **Why.** Measured out of the 2.1.312 bundle: `confirmLabel: "Yes, allow external imports",
  cancelLabel: "No, disable external imports", hideIndexes: true, cancelFirst` — the same shape as
  the trust and bypass gates, and like them it **blocks** the session until it is answered, which
  makes a revive that started a window and did nothing. Answering yes writes
  `hasClaudeMdExternalIncludesApproved` into that home's project state for good, which is consent
  only the person can give — so the right answer is No, and the consequence (a session that comes up
  without those imports) belongs in the output, not in a silent default. It matters most in exactly
  the folders worth reviving: the ones whose doctrine lives in an imported file.
- **Check.** Start a cold home in a folder whose `CLAUDE.md` has an `@~/…` import line, on a private
  tmux socket, and read the pane.
- **Verified.** 2.1.312. **Beta.**

### L45 · A usage-limit stop does not always carry `apiError`

- **Rule.** Detect a quota stop by the whole shape — `isApiErrorMessage: true` with
  `error: "rate_limit"` or a top-level `quotaLimits` — and never by `apiError` alone. Take the kind
  from `quotaLimits.rateLimitType` when `apiError` is absent.
- **Why.** Of 44 real assistant quota-stop lines in the config homes on this machine, **10 carry no
  `apiError` key at all**: only `isApiErrorMessage: true`, `error: "rate_limit"`,
  `apiErrorStatus: 429` and `quotaLimits` ({`status`, `resetsAt`, `rateLimitType`}). A reader keyed on
  `apiError` put those in the clean-line branch, so a session sitting on a wall was reported as
  *finished* — and, worse, the same branch marked "the session answered again", which read a genuine
  earlier limit as waited out. Read the tail as JSON lines, too, and not with a text grep: a match on
  the text says "out of quota" about any session that merely discussed one.
- **Check.**
  `grep -h '"isApiErrorMessage":true' <home>/projects/*/*.jsonl | jq -c 'select(.message.content|tostring|test("limit"))|{apiError,error,q:(.message.quotaLimits//.quotaLimits)}' | sort | uniq -c`
- **Verified.** 2.1.312. **Beta.**

### L46 · A version-5 session id is a server child; that survives every file being gone

- **Rule.** Read the kind of a Remote Control session from the uuid **version** of its local id when
  nothing else can say. A child's id is `uuid5(<bridge namespace>, <its api url>)` (L37) and every
  other session gets a random `uuid4`, so version 5 is proof on its own — and a tool that must never
  resume a child in place (L39) needs that proof precisely when nothing is left to look at.
- **Why.** The bare bridge id is written down in exactly four places, and a dead child named by its
  own id or by part of its title has none of them: no live registry row, no `bridge-session` line in
  its own transcript (L37), and no `~/.claude/bridge-spawn/cse_X-*` directory once it exited cleanly —
  the bridge deletes that on a *handled* exit, which a server shutdown or a graceful restart is. Of
  861 version-5 transcripts in the config homes on this machine, **2** name their bridge session in
  their own file and **19** have a directory or a live row: 840 could be classified only by the id.
  Reading those as plain terminal sessions is how an in-place `--resume <old id>` — L39's forbidden
  two-writer start — gets reached by the ordinary spec a person types.
- **Check.** `uuid5` the derivation for a link you have, then
  `python3 -c 'import uuid,sys; print(uuid.UUID(sys.argv[1]).version)' <local id>`; compare against
  how many of your own v5 transcripts carry a `bridge-session` line.
- **Verified.** 2.1.312, Wed 28 Oct 2026, 861 v5 transcripts on one machine. **Beta.**

### L47 · A `<synthetic>` "No response requested." line is the record of a NON-answer

- **Rule.** A clean assistant line counts as "the session answered again" only when its `model` looks
  like a model. A line whose model is `<synthetic>` is not an answer, and neither is one carrying
  `isApiErrorMessage` with an `error` that is not `rate_limit`.
- **Why.** The CLI writes a non-error assistant line reading **"No response requested."**, model
  `<synthetic>`, precisely when an injected `isMeta` prompt ("Continue from where you left off.")
  produced nothing — so the one line that records a non-answer wears a clean line's clothes. Counting
  it masks a usage-limit stop as `finished` (losing the class, the window and the reset) and a kill
  mid-tool-call as `finished` too, which drops the one sentence a revived session must be told: its
  last tool call has no recorded result. Measured: 23 such lines in 20 of the 1,943 transcripts in the
  config homes here, every one with that exact text.
- **Check.**
  `grep -h '"model":"<synthetic>"' <home>/projects/*/*.jsonl | jq -c 'select(.apiError==null and .isApiErrorMessage==null)|.message.content[0].text' | sort | uniq -c`
- **Verified.** 2.1.312, Wed 28 Oct 2026. **Beta.**

### L48 · A relay's own transcript lands in the TARGET's home; the cwd moves only the slug

- **Rule.** Running the note-carrying `claude -p` relay in a directory of your own does not keep its
  transcript out of the session's config home — it only changes which project folder inside that home
  the file lands in. Say so out loud wherever "the note is in no file we keep" is claimed, and keep
  that project slug out of every listing.
- **Why.** `cwd` decides the project-folder **slug** and nothing else, so the relay files
  `<CLAUDE_CONFIG_DIR>/projects/<slug of the relay dir>/<its own id>.jsonl` — with the note verbatim
  inside it, written by the CLI with the CLI's own permissions. Two consequences follow: the rule that
  no *tool-kept* file holds the note is not a claim that the note is unwritten; and every run leaves a
  session whose title is the relay instruction in any listing that scans `projects/*/*.jsonl`, which
  a session mover will then happily offer to move or revive. A 0700 mode on the relay's cwd protects
  the cwd, not the transcript.
- **Check.** `claude -p --output-format json "…"` in a scratch directory, then
  `ls -lt "$CLAUDE_CONFIG_DIR/projects/"` — the newest folder is that directory's slug, and it holds a
  transcript named by the `session_id` in the result document.
- **Verified.** 2.1.312, Wed 28 Oct 2026 (the spike's own result document names its `session_id`).
  **Beta.**

### L49 · A registry `name` is not unique, and SendMessage addresses a session by it

- **Rule.** Before messaging a session by the `name` in its registry row, count the **proved** live
  rows in that home carrying that name. Not exactly one is a refusal with nothing sent. And never
  build a name from a title alone: put the session's id8 in it.
- **Why.** The registry is keyed by local id, not by name, so two live rows can carry one name; the
  tool addressing them cannot tell which answers. A note then lands in a conversation nobody named,
  while the prover watches the intended session and reports "it is up but idle" — a misdelivery with
  no signal at all. And a name built as `<sanitised title> + <fixed tail>`, truncated to a fixed
  width, makes the collision by construction: two revives of one session, or two sessions whose
  titles start alike, register under one identical name.
- **Check.** `jq -r .name <home>/sessions/*.json | sort | uniq -d`
- **Verified.** 2.1.312, Wed 28 Oct 2026 (observed in fixtures with two live rows of one name; the
  collision by construction read off the label builder). **Beta.**

### L50 · A lock whose mtime is never touched is breakable in the middle of the work it protects

- **Rule.** A stale-break bound belongs to the HOLDER, not to the lock type: set it from the sum of
  the waits that lock is held across, and re-stamp the directory inside each polling wait.
- **Why.** A lock-directory's age is read from its `mkdir` mtime, so a claim held across several
  bounded waits looks abandoned from the moment the first bound passes — and the holder is then not
  "finished", it is in the middle of the one operation the claim exists to serialise. A 120 s bound
  written for a read-modify-replace of one JSON file, reused for a claim held across a window
  connecting (150 s), its registry row appearing (150 s), a relay (120 s) and a turn (90 s), was
  breakable on **every** run from t=120 s.
- **Check.** Sum the knobs the claim is held across and compare with the break; then
  `stat -f %m <lock dir>` during a long run and watch whether it moves.
- **Verified.** Read off the engine's own knob definitions, Wed 28 Oct 2026. **Beta.**

### L51 · An unattended wake needs a key per STOP, not per session

- **Rule.** Record what was woken under `(local session id, the uuid of the transcript line the
  stop was read from)`, and treat a stop as handled only on a record whose exit code was `0`.
- **Why.** Both halves are failures that look like success. Key it on the **session id** and a
  session is woken once and never again — the ordinary life of a long-running session is to stop,
  continue, work for an hour and stop again, and that second stop is a different event that needs a
  different answer. Leave the key out altogether and a pass that runs every five minutes relays the
  same note into the same session twelve times an hour, each one a turn spent on the account's
  quota. And counting a record with a **non-zero** exit as handled retires a session nothing ever
  delivered a note to: exit 1 means something is up and unproved, exit 2 means nothing was started
  at all, and in both cases the session is still sitting there. A line's `uuid` is written once and
  never rewritten, which is what makes it a name for one stop; when a line carries none, the
  transcript's **size** is the next best thing, because anything written since makes it a different
  file state.
- **Check.** Wake a throwaway session, then run the sweep twice: the row must read handled the
  first time and stay handled. Then let it stop again and confirm the new stop's uuid differs from
  the recorded one and the row is due once more.
  ```sh
  csm stalled --json | jq '.rows[] | {short, due, why, handled}'
  jq -r '[.local_id[0:8], .stop_uuid, .exit] | @tsv' < ~/.local/state/claude-session-mover/revive.jsonl
  ```
- **Verified.** 2.1.312; the `uuid` field on every main-chain line is of the transcript format, not
  of this tool. **Beta.**

### L52 · A dead server child cannot be woken unattended: fork it, and archive the old session

- **Rule.** With nobody at the keyboard, a dead Remote Control **server child** is forked onto a new
  id and a new link — and the old claude.ai session is archived in the same breath, by whatever
  holds the credential.
- **Why.** Only the child's own server respawns it, lazily, when that claude.ai session next gets
  **server-side activity** — opening the link in the app does it, and nothing local can. So the
  answer that works for a person ("open this and say *continue*") has no unattended equivalent at
  all, and a tool that printed it and exited `0` would be reporting work it did not do. The fork is
  the only action that exists, and it is not free: it leaves two conversations with one history, and
  the **old link still respawns the old one** on the next tap. Two actors with the same past, each
  believing it is the session, is a worse outcome than a session that was never continued — so the
  fork is only safe when the old session is archived, and the tool that forks must hand the old
  bridge id to whoever can do that (`POST /v1/code/sessions/<cse_id>/archive`, with that account's
  own token). Reviving such a child onto its *own* id instead is L39's two-writers failure.
- **Check.** Fork a throwaway child, then open the old link and watch a second worker register:
  `csm list` shows two live sessions whose transcripts share every line up to the fork.
- **Verified.** 2.1.312. **Beta.**

### L53 · A note a tool sent unasked must not say the user asked for it

- **Rule.** When a scheduled pass continues a session, the note says that nobody has sent a message
  since it stopped and that the installation continues stopped sessions automatically — not that
  the user asked for this.
- **Why.** The receiving session decides what to do next on the strength of that sentence, and
  "they asked me to continue" and "nothing has been asked and a timer fired" license different
  next steps: the first reads as a go-ahead for whatever was in flight, the second as a reason to
  re-check before touching anything. It is the same failure as L42 one layer up — there the CLI
  recorded a tool's prompt as the user's own typing, here the *text* would claim an instruction
  nobody gave. Words the user really did type are still quoted verbatim, beside the fact that the
  run was not theirs.
- **Check.** Run the unattended revive of a throwaway session and read the message in the app: it
  must carry the tool's stamp, the sender name, and no claim that anybody asked for it.
- **Verified.** Read off this tool's own note builder, Thu 29 Oct 2026. **Stable** (it is a rule
  about what to write, not a measurement of the CLI).

### L54 · A fork copies the transcript, so one stop event lives under two session ids

- **Rule.** Match an unattended wake's at-most-once record on the **stop event uuid alone** when the
  stop line carries one — never on `(session id, uuid)` — and refuse to call two rows that share a
  stop uuid due in one sweep.
- **Why.** `--fork-session` writes a NEW transcript holding every line of the old one, uuids
  included, and leaves the file it read byte-identical. So the stop line that made the parent due
  ends the copy too, under a second local id. Filter the log by id first and the parent's exit-0
  record cannot cover the copy: both rows read **due** for one stop event, and a pass that wakes
  everything due wakes both — two actors continuing one history, which is the single outcome the
  key exists to prevent. It needs no bug to reach: a person running `claude --resume X
  --fork-session`, or `/fork`, on a parked session leaves exactly this pair. A uuid names one
  transcript line that was written once, so it is already the right key; narrowing it with the id
  is what breaks it. Keep the `(id, size)` triple only for a stop line that carries no uuid.
- **Check.** Fork a parked throwaway session, then `csm stalled --json | jq '[.rows[] |
  {short, due, stop: .stop.uuid, handled: .handled.copy_of}]'`: at most one row sharing a
  `stop.uuid` may read due, and a record for either must mark both handled.
- **Verified.** 2.1.312, Thu 29 Oct 2026 (the fork's copied uuids read off the written transcript;
  the two-due-rows state reproduced in fixtures). **Beta.**

### L55 · A fork that came up is done, whatever the exit code says

- **Rule.** A caller decides whether to archive, and whether to try again, on **what the document
  says was created** — not on the process's exit code. Publish that as its own key (`result.forked`)
  rather than leaving it to be inferred.
- **Why.** The fork row creates the new session, its link and its transcript *before* it relays the
  note, so every failure after that point — an ambiguous registry name, a relay that errors, a turn
  that never appears — returns a non-zero exit with the fork already made. An exit code is one
  number for "nothing happened" and "something happened and could not be proved", and a caller that
  reads it as the first skips the archive in precisely the cases where the old link is live beside
  a new one, and leaves the row due so its next pass forks again: three conversations with one past
  and no archive, each failure buying another. The same holds one level down for a timeout: a caller
  that SIGKILLs the tool at a cap below the tool's own ceiling destroys the record that would have
  said what was done, so an unknown outcome must be treated as **done**, never as pending.
- **Check.** `csm revive <dead server child> --auto --json` with the relay made to fail: `result`
  must carry `forked: true`, `new_id`, `old_bridge_id` and `archive_old` beside `"exit": 1`.
- **Verified.** Read off this tool's own fork row, Thu 29 Oct 2026, and reproduced in the fleet
  caller's fixtures. **Stable** (it is a rule about what a result must state).

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
