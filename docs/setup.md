# Making accounts fungible

The goal: your Claude accounts differ only in who pays. Same instructions, same skills, same plugins, same hooks,
same memory, same permission defaults — so moving a session between them is a billing change, not a migration.

This page is the recipe. [docs/fungibility-matrix.md](fungibility-matrix.md) is the reference for *why* each layer
behaves the way it does, and for the handful of layers that cannot be made fungible at all.

Everything here was measured against Claude Code 2.1.300 on macOS. Linux differences are called out. Placeholders
throughout: two accounts called **work** and **personal**, with homes `~/.claude-work` and `~/.claude-personal`, and
an email `you@example.com`.

- [1. One config home per account](#homes)
- [2. Sign in — one browser profile per account](#signin)
- [3. Pick a shared directory](#shared-dir)
- [4. Link the shared entries](#layout)
- [5. Shared memory](#memory)
- [6. The per-home checklist](#checklist)
- [7. Across machines](#machines)
- [8. Renaming a home on macOS](#rename)
- [9. Verify](#verify)

---

<a id="homes"></a>

## 1. One config home per account

A *config home* is the directory `CLAUDE_CONFIG_DIR` points at. It holds one login, so one home is one account.

```sh
mkdir -p ~/.claude-work ~/.claude-personal
chmod 700 ~/.claude-work ~/.claude-personal
```

Mode 700 matters: on Linux the login is a plaintext file inside the home.

`csm` discovers homes by name — the default `~/.claude` plus each `~/.claude-<name>` — so `~/.claude-work` is the
account `work`. Name them after the account, never after a number: numbers leave gaps when you add or drop an
account, and nothing downstream can tell you which gap meant what.

Make the choice of account explicit everywhere. A bare `claude` with no `CLAUDE_CONFIG_DIR` runs on the default
home, which is the easiest way to spend the wrong quota without noticing. A shell function per account is enough:

```sh
claude_work()     { CLAUDE_CONFIG_DIR=~/.claude-work     command claude "$@"; }
claude_personal() { CLAUDE_CONFIG_DIR=~/.claude-personal command claude "$@"; }
```

<a id="signin"></a>

## 2. Sign in — one browser profile per account

```sh
CLAUDE_CONFIG_DIR=~/.claude-work claude      # then /login
```

Two rules, and the second one costs real money when it is broken:

1. **One browser profile per account.** The `/login` flow authorises whichever account the browser is currently
   signed in to.
2. **Never chain two sign-ins in one window.** Signing a second home in right after a first, in the same browser,
   silently puts the **first** account's identity into the second home. Both homes then spend one account's quota,
   and nothing says so — it can run for days before anyone notices. Use a separate browser profile per account, or
   sign fully out between logins.

**Prove the account from the home, not from the folder name.** A directory called `~/.claude-work` proves nothing.

```sh
csm accounts        # each home, the email it is signed in as, and its live sessions
```

or read the state file directly:

```sh
python3 -c 'import json,os,sys; p=os.path.expanduser("~/.claude-work/.claude.json"); print(json.load(open(p))["oauthAccount"]["emailAddress"])'
```

Note what that file is and is not. `oauthAccount.emailAddress` records the **last login the CLI saw**, not a live
one: a home can keep naming `you@example.com` for hours after its credential is gone. Pair the name with a check
that a credential actually exists — which is exactly what `csm matrix`'s `login` row does, and it does it without
reading the secret.

Where the state file lives is worth knowing too: with `CLAUDE_CONFIG_DIR` set, `.claude.json` is **inside** the
home; with it unset it is `~/.claude.json`, never inside `~/.claude`.

<a id="shared-dir"></a>

## 3. Pick a shared directory

One real directory holds the things every account should agree on; every home holds a **symlink** to it. Symlinks,
not copies: "same realpath" is a question you can answer in one line, "same content for now" is not.

**Option A — use the default `~/.claude` as the shared directory (recommended).** It already exists, it is where
you probably already keep your `CLAUDE.md` and skills, and keeping it **login-free** means a bare `claude` fails
loudly instead of quietly running as whoever signed in there last. `csm matrix` reports these layers as `shared`
and `--check` passes, with one note: the shared copy lives inside a config home, so renaming or deleting that home
dangles every link into it.

**Option B — a separate directory, e.g. `~/.config/claude-shared`.** Pick this if the default home is itself an
account you use (for instance, a desktop client is signed in there), or if you would rather the shared copy did
not depend on a config home surviving. The cost is one more path to remember, and one
trap: **do not name it `~/.claude-shared`**. Tools that discover accounts by the `~/.claude-<name>` pattern —
`csm accounts` among them — would adopt it as an account. Keep the shared directory outside that pattern, and keep
it outside every config home.

The rest of this page writes `~/.claude` for the shared directory. Substitute your own if you chose Option B.

The trade-off in one line: Option A costs you the ability to give the default home different settings from everyone
else; Option B costs you a little more path discipline. Both give the same answer to "do these accounts read one
file".

<a id="layout"></a>

## 4. Link the shared entries

A home may already have a real `settings.json` with your own rules and hooks, or a populated `plugins/`. The loop
below **moves** anything it finds out of the way first, to `<entry>.before-sharing`, and says so — it never deletes
a real file. Re-running it is safe: only a symlink it made before is removed.

```sh
SHARED=~/.claude
for home in ~/.claude-work ~/.claude-personal; do
  for entry in settings.json CLAUDE.md skills agents commands output-styles plugins; do
    [ -e "$SHARED/$entry" ] || continue
    if [ -e "${home:?}/$entry" ] && [ ! -L "${home:?}/$entry" ]; then
      mv "${home:?}/$entry" "${home:?}/$entry.before-sharing"   # never deleted
      echo "kept ${home}/$entry.before-sharing"
    else
      rm -f "${home:?}/$entry"                                  # an old symlink only
    fi
    ln -s "$SHARED/$entry" "$home/$entry"
  done
done
```

Read the `kept …` lines afterwards and merge anything you still want into the shared copy — a home's own
`settings.json` often holds permission rules nobody remembers adding.

**Link these:**

| Entry | Why |
|---|---|
| `settings.json` | The highest-value link by far: permissions (`defaultMode`, `disableAutoMode`), `env`, `hooks`, `enabledPlugins`, `skipDangerousModePermissionPrompt`, theme. One file, one edit, every account. It holds no login, which is what makes it safe to share. |
| `CLAUDE.md` | User-level instructions. |
| `plugins/` | One `claude plugin install` then serves every account. Without this, a plugin enabled in the shared `settings.json` is claimed by every home and installed in only some — and its commands, skills and MCP servers are silently missing in the rest. |
| `skills/` | User-level skills. |
| `agents/`, `commands/`, `output-styles/` | Plain files, no account scope. Share freely. |
| `settings.local.json` | Share it, or make sure **no** home has one. It is merged *over* `settings.json`, so one home that has one runs with different settings even when `settings.json` is perfectly shared. That asymmetry is the most common "but they're identical" false positive. |
| `scheduled-tasks/` | Shareable as files — but a task runs on whichever account's home it sits in, so sharing changes who pays. If exactly one account is meant to run scheduled work, leave this per home. |

Two caveats on the shared directories: `skills/synced/` holds skills synced from claude.ai, named
`<skillUuid>_<accountUuid>`, and `plugins/synced/` holds synced plugin state the same way. Both are account-scoped,
so sharing the parent pools every account's copies into one place. If that is unwanted, link the individual
hand-written skill directories instead of the whole `skills/`.

If your hooks are scripts, prefer keeping them in a repo and pointing the shared `settings.json` at that absolute
path, rather than linking a `hooks/` directory into each home.

**Never link or share these:**

| Entry | Why |
|---|---|
| `.claude.json` | The state file. It carries the account identity (`oauthAccount`), the per-directory first-run gates, bypass consent, user-scope MCP servers and per-project history in one file. Sharing it crosses account identities. Merge the keys you need; never copy the file. |
| `.credentials.json` (Linux) | The login itself. |
| `projects/` | Transcripts, and per-home memory when no shared store is configured. Memory is shared through a setting, not by linking this directory — a symlinked memory or project directory breaks the write auto-allow. If you link it anyway, two costs bite: on a machine that runs Remote Control servers the accounts' servers overwrite one `projects/<slug>/bridge-pointer.json`, so after a restart one reads another account's environment and loses its own sessions' reattach (exclude that file by name), and any home still on the default `cleanupPeriodDays` prunes every account's history (pin it high in every home before linking) — see [LESSONS.md § D](../LESSONS.md#d). |
| `sessions/` | The live per-pid registry, plus per-process secrets. |
| `shell-snapshots/`, `session-env/`, `jobs/`, `daemon.json` | Code-execution surfaces the CLI refuses writes to even under bypass. |
| `file-history/`, `tasks/`, `todos/`, `history.jsonl`, `statsig/`, `telemetry/`, `state/`, `cache/`, `backups/`, `uploads/`, `downloads/`, `ide/`, `debug/` | Per-home runtime state, keyed by session id. Sharing these makes two accounts' concurrent sessions clobber each other. |
| Anything whose name contains an account uuid | By definition not shared. |

One more thing that is per machine rather than per home: `~/.claude/.device-keys.json` is used regardless of
`CLAUDE_CONFIG_DIR`. Don't clone it to another machine.

<a id="memory"></a>

## 5. Shared memory

Auto-memory defaults to `<config home>/projects/<folder>/memory/`, with `MEMORY.md` as the index — so by default
each account has its own notes for the same project. Two settings relocate it, and **they do not behave the same
way**. The difference decides which one you want, so it is worth stating what was actually verified.

### What the binary does (verified, Claude Code 2.1.300)

Read read-only out of the installed binary. The resolver takes the first of these that produces a usable path:

1. `CLAUDE_COWORK_MEMORY_PATH_OVERRIDE` (environment) — used **verbatim**, with no `~` expansion.
2. **`autoMemoryDirectory`** (a settings key) — used **verbatim**. `~/` *is* expanded here. **Nothing is appended:
   no `projects/`, no project folder, no `memory/`.**
3. Otherwise: `<base>/projects/<folder>/memory/`, where `<base>` is **`CLAUDE_CODE_REMOTE_MEMORY_DIR`** when that
   environment variable is set and the config home when it is not.

So the two levers differ in kind:

| | `CLAUDE_CODE_REMOTE_MEMORY_DIR` | `autoMemoryDirectory` |
|---|---|---|
| Kind | environment variable (undocumented) | settings key (in the settings schema) |
| What it sets | the **base**; one directory per project underneath it | the memory directory **itself**, verbatim |
| `~/` expanded | **no** | yes |
| Value validated | no — taken raw from the environment | yes: must be absolute after expansion, at least 3 characters, no NUL, not a bare drive root. An invalid value is **ignored silently** and resolution falls through to the default |
| Precedence | lower | higher — it wins over the environment variable |

**The consequence to plan around:** because `autoMemoryDirectory` is used verbatim, putting it in a user-level
`settings.json` that every home shares gives **every project on the machine one memory directory**. All projects'
notes mix, and `MEMORY.md` becomes a single index for everything. That is almost never what anyone wants, and it is
easy to do by accident when you are trying to share memory across accounts.

Where `autoMemoryDirectory` may come from, first source that defines it winning: policy settings, flag settings,
then — only in a trusted folder — `.claude/settings.local.json` and `.claude/settings.json`, then the user's own
`settings.json`. The key's own schema description says a value set in a **checked-in** project `.claude/settings.json`
is ignored for security, and the workspace-trust dialog warns when a folder declares it ("This folder changes where
automatic memory is written (autoMemoryDirectory), declared in …"). Treat the checked-in route as unreliable. The
key is also on the list of settings stripped when settings come from the folder Claude Code was launched in.

### The recommendation

**To share one memory store across accounts (and across machines), keeping one directory per project: set
`CLAUDE_CODE_REMOTE_MEMORY_DIR` in the `env` block of the `settings.json` every home links to.**

```jsonc
{
  "env": {
    "CLAUDE_CODE_REMOTE_MEMORY_DIR": "/absolute/path/to/claude-memory"
  },
  "autoDreamEnabled": false
}
```

That single key gives every account on the machine one memory directory per project, and — this is the part that
matters — it leaves the memory write auto-allow intact, so **no permission rule is needed and none should be
added**.

`autoDreamEnabled: false` is a judgement call worth making in a shared store: background consolidation is the only
writer that prunes and rewrites *other* notes, and across accounts that means one account's consolidation is free to
rewrite another's.

**To relocate one project's memory** — into the repo's own folder, say — set `autoMemoryDirectory` in **that repo's
`.claude/settings.local.json`** (local settings; not checked in, honoured once the folder is trusted, and scoped to
that project):

```jsonc
// <repo>/.claude/settings.local.json
{ "autoMemoryDirectory": "~/notes/this-project-memory" }
```

Use that route deliberately, per project. Do not put the key in a shared user-level `settings.json`.

### Choosing the store base

- Absolute, and outside every config home.
- **Never named `~/.claude-<anything>`.** It will contain a `projects/` directory, so any tool that scans for config
  homes — `csm accounts` included — would adopt it as an account.
- For several machines, a path inside a synced folder, with each machine spelling **its own literal absolute
  realpath**.

### Moving an existing corpus in

1. **Inventory first, write nothing.** List `<home>/projects/<folder>/memory/*.md` for every home, with sizes and
   mtimes. Expect the corpus to have already forked: the same note in several homes with different content, and
   notes that exist in exactly one home, are the normal starting state.
2. **Copy, never move.** Keep the per-home corpora live through the cutover so there is always a way back. Removing
   them is a separate, later, explicitly confirmed step.
3. **Conflicts:** prefer the newest copy, and keep the loser in a `_superseded/` directory that is a **sibling** of
   `projects/` — the CLI only loads under `projects/`, so siblings are invisible to it. When two copies have no
   timestamps and near-identical mtimes, stop and ask rather than guess; guessing loses a note.
4. **Treat `MEMORY.md` specially.** It is a curated index and the CLI truncates it silently past roughly 200 lines
   or 25,000 characters. Rebuild it from the richest copy plus one line per newcomer, staying under that cap. Never
   merge it as if it were an ordinary file.
5. **Record a cutover timestamp** (a file in the store, as a sibling of `projects/`) so "written after the cutover"
   has a meaning.
6. **Restart sessions.** A running process keeps the environment it started with.
7. **Sweep strays.** Anything that appears under `<home>/projects/*/memory/` after the cutover gets copied into the
   store. Never delete the source.

### Caveats

- **The environment variable is undocumented.** No doc page, no changelog entry. A future release could stop
  honouring it and re-fork the corpus silently. Re-check after a CLI upgrade: open a session and ask it for the
  absolute path of its persistent memory directory. Three outcomes, and only the first two are evidence — a path
  under the store (good), a path somewhere else (regression), or no answer at all (a refusal, a timeout, an auth
  wall: **not** evidence, and it must not switch anything off).
- **The value is not interpolated.** A `~/x` or `$HOME/x` value makes the CLI create a directory literally named `~`
  in the working directory, silently. Absolute realpath, always.
- **Never point at the store with a symlink.** A symlinked memory directory — or a symlinked project directory —
  breaks the write auto-allow, and the write is then denied in `default` and `acceptEdits` mode. Use the setting.
- **Never add a `permissions.deny` or `permissions.ask` rule naming a memory path.** A blocking rule on a memory
  write makes the background memory agent refuse to run at all, which switches auto-memory off entirely and
  silently — for every account at once, if the settings file is shared. No `allow` rule is needed either; the write
  auto-allows when the path is the session's own memory directory.
- **The project folder name is path-derived**, from the realpath of the project root. The same repo checked out
  under a different username or a different parent directory gets a different folder, even with a shared base. See
  [§7](#machines).
- **A running session keeps the environment it started with.** Expect the cutover to be mixed until every long-lived
  session has restarted.
- **A resumed session writes the memory path carried in its own history** — after a cutover, the old per-home path.
  That is what the stray sweep is for.
- **No `.git` inside a synced folder.** Two machines committing at once is how a repository gets corrupted. Keep the
  history outside the synced store and point git at it with `--git-dir` / `--work-tree`, and let one machine commit.
- **A home whose `settings.json` is a real file rather than the shared link never receives the key** and keeps its
  own memory. That can be a legitimate exemption — name it and say so, rather than treating it as drift.
- **Cloud-sync side effects.** "Conflicted copy" files will appear and need resolving, and a placeholder file that
  is synced but not downloaded on this machine blocks on a download when read.

<a id="checklist"></a>

## 6. The per-home checklist

Do these once per home, per machine. Nothing here can be shared; it is the irreducible cost of an extra account.

- [ ] **Create the home**, mode 700, named after the account.
- [ ] **Sign in** (`CLAUDE_CONFIG_DIR=<home> claude`, then `/login`) in that account's **own browser profile**, and
      verify the resulting identity by email — never two sign-ins chained in one window. See [§2](#signin).
- [ ] **MCP sign-ins:** `claude mcp login <server>` once per home. MCP OAuth tokens live under an `mcpOAuth` key
      *inside the same credential blob as the login*, so there is no file to copy and signing two homes into the
      same account does not carry them over.
- [ ] **Connectors, in the browser, per account:** `claude.ai` → Settings → Connectors, signed in as that account.
      Enable the identical set on every account. **No terminal command on any machine can attach a connector** — the
      CLI refuses a hand-written `claudeai-proxy` entry and points you at that page, and `claude mcp login` can only
      authenticate a connector the account already has. A session moved to an account without the connector loses
      that capability mid-task. This is the one layer that is never fungible from a terminal; see
      [the matrix](fungibility-matrix.md#connectors).
- [ ] **Link the shared entries** ([§4](#layout)), including `plugins/` if you want one install to serve everyone.
- [ ] **Link the `move-session` skill into the home**, so a session in it can be told "move this to the other
      account" from a phone: `./install.sh --skill` does every home at once, and re-running it after an update
      repoints the links it made itself. Each config home reads its own `skills/`, so a shared `settings.json` does
      not cover this. 🛑 A `skills/move-session` that already links somewhere else is **skipped, not replaced** —
      the line says where it points — so a home you wired by hand keeps reading that copy until you repoint it or
      point it at this one. On a machine where `csm` is already a wrapper of your own that supplies this tool's
      environment, install with `./install.sh --skill --no-short-name`, or the link would shadow that wrapper.
- [ ] **Plugins:** if `plugins/` is *not* linked, install them in this home too, and check for version drift.
- [ ] **First-run gates:** a new home has answered neither the onboarding flow nor the folder-trust dialog, and both
      put the cancelling option first and focused, so an unattended start just sits there. Either run the home once
      interactively in the folder you care about, or pre-answer:
      `projects['<absolute cwd>'].hasTrustDialogAccepted` and `hasCompletedOnboarding` in the home's `.claude.json`,
      and `skipDangerousModePermissionPrompt` in its settings. **`csm` pre-answers these for the folder it moves a
      session into**, so a cold target home is not a reason a move fails.
- [ ] **Verify:** `csm matrix --check`.

<a id="machines"></a>

## 7. Across machines

What crosses, what does not:

| | How |
|---|---|
| The shared directory's contents | Keep `CLAUDE.md`, `skills/`, `agents/`, `commands/`, `output-styles/` and `settings.json` in a repo or dotfiles and install from there. |
| Absolute paths inside `settings.json` | Per machine. A memory store base and a hook script path have to be spelled with each machine's own realpath. |
| Logins | Per machine. Sign in once per account per machine; the refresh window is set at login (on the order of weeks) and ordinary renewals do not extend it. |
| Plugins | Install once per machine. |
| Memory | A store inside a synced folder, each machine spelling its own literal absolute path. |
| Scheduled tasks | Per machine — a task runs where its scheduler runs. |
| Transcripts | Not synced. `csm` moves one between accounts on a machine, and between machines with `csm move <id> --from-machine M` — found over there, copied over ssh, the folder translated into this machine's spelling, and resumed here. |
| Connectors | Free: a connector belongs to the account, so one consent covers every machine that account serves. |

**The path-mismatch problem.** Both the memory folder and the transcript folder are named from the project's
absolute path, with every character outside `[A-Za-z0-9]` replaced by `-`. A repo at `/Users/you/code/app` on one
machine and `/home/you/src/app` on another therefore gets two different folders even when the store is shared. Two
ways out:

- `CLAUDE_CODE_PROJECT_DIR_NAME` overrides the project directory name outright (`[A-Za-z0-9_-]{1,64}`, no Windows
  device names) — the clean answer when you control both machines.
- Otherwise keep one **real** directory per spelling, holding the same notes, and converge them with a copy-based
  sync. Do **not** symlink one folder to another: a symlinked memory directory breaks the write auto-allow.

The same mismatch decides whether `csm move <id> --from-machine M` can resume a session here at all, because the
*working directory* recorded in its transcript is the other machine's spelling. Two knobs say how to translate it:
`CSM_MACHINES`, a JSON file of each machine's path roots (`{"laptop": {"home": "/Users/you", "shared":
"/Users/you/Sync"}, …}`), matched by label across machines; and `CSM_SYNC_DIRS`, the home-relative names that are
*the same synced folder everywhere* — the rule a sync root needs, because such a folder is usually a symlink into
the sync client's own tree and the transcript records the symlink spelling. With neither set, a folder is only ever
translated home-to-home, and one that is not here is a refusal rather than a guess; `--mirror-cwd` is how the code
comes along when the folder is genuinely per machine.

<a id="rename"></a>

## 8. Renaming a home on macOS

On macOS the login is not a file. It is a generic-password Keychain item whose **service name is derived from the
literal `CLAUDE_CONFIG_DIR` string**:

- `CLAUDE_CONFIG_DIR` unset → service `Claude Code-credentials`
- `CLAUDE_CONFIG_DIR` set → service `Claude Code-credentials-` + the first 8 hex characters of
  `sha256(NFC(<the literal string>))`

The item's *account* attribute is `$USER`. **So renaming or moving a config home silently orphans its login.** The
directory keeps working; the account inside it is simply gone.

Compute the service name for a home, and test whether a login exists, without ever touching the secret:

```sh
home=/Users/you/.claude-work       # exactly the string you will export
svc="Claude Code-credentials-$(printf %s "$home" | python3 -c 'import hashlib,sys,unicodedata; print(hashlib.sha256(unicodedata.normalize("NFC", sys.stdin.read()).encode()).hexdigest()[:8])')"
security find-generic-password -a "$USER" -s "$svc" >/dev/null 2>&1 && echo present || echo "absent or unreadable"
```

**Never use `-w` (or `-g`) to test existence.** Without them, `find-generic-password` answers the only question you
have — is there an item — with exit 0 for present and exit 44 (`errSecItemNotFound`) for absent, and raises no
approval dialog. With them it returns the secret, and an item whose ACL does not list `/usr/bin/security` raises a
GUI dialog that can block an unattended run for a quarter of an hour.

Three more things that bite:

- **The hash is over the string exactly as spelled.** `/Users/you/.claude-work` and `/Users/you/.claude-work/` are
  two different logins, and the shell expands `~` before the CLI ever sees the value.
- **Unset must mean unset.** Spelling the default home out as `CLAUDE_CONFIG_DIR=$HOME/.claude` takes the hash
  branch and lands on a different, empty slot — which reads exactly like "logged out" for a home that is signed in.
  Drop the variable (`env -u CLAUDE_CONFIG_DIR`) rather than setting it to the default path.
- **The login Keychain cannot be read from a plain ssh session at all.** It answers "User interaction is not
  allowed" (exit 36) even when that Mac's GUI session is logged in. Over ssh, login state is **unknown**, never
  "signed out".

**The safe way to rename.** `security` has no rename, and copying a slot means handling the token. Unless you are
moving many homes at once, the cheapest correct answer is to not copy it:

1. Rename the directory.
2. Start the renamed home and run `/login` again, in that account's own browser profile.
3. Confirm the home names the expected account, then park (do not immediately delete) the old slot.

If you do copy the slot instead, the order is what keeps you safe: **copy → park the old one → re-derive the hash
and confirm it matches the new path → prove the new home actually serves → only then delete the old slot.** Never
delete the old slot before the new home has authenticated something.

On **Linux** none of this applies: the login is `<home>/.credentials.json` and travels with the directory. One
Linux-only trap: a CLI process killed mid-flight can re-create its *old* home path after the move, leaving a second,
partly-populated home behind. Re-list the homes after a rename, merge anything the stray gained (transcript lines in
particular), and list again.

<a id="verify"></a>

## 9. Verify

```sh
csm matrix
csm matrix --check      # exit 1 when a shareable layer diverges or a login is gone
```

`csm matrix` is read-only, offline and prompt-free: it reads no credential value, runs no network call, and starts
no session. Rows are layers, columns are the homes on this machine. Read it with one rule in mind: every cell is
**measured ok**, **divergent**, or **unknown with a reason**, and *unknown is never ok*. A summary that says "all
homes match" while a cell is unknown is a summary of a machine that was never read.

What to look for after following this page:

- `settings.json`, `settings.local.json`, `CLAUDE.md`, `skills`, `agents`, `commands`, `output-styles`, `plugins`
  — **shared**, meaning the same realpath in every home. That is the verdict wherever the one real copy lives,
  Option A included: a shared copy inside the default home reads as `shared`, with a note saying that renaming or
  deleting that home would dangle every link into it. A **DANGLING** symlink is the real failure, and it is what a
  rename leaves behind: silent, and invisible to any check that compares contents.
- `plugins enabled` — `–` in every column. This is the row that catches a plugin enabled for everybody and
  installed for some; a cell reading `N missing` names the count.
- `auto-memory` — the same resolved store for every home. Watch for **mixed**: some homes on the store and some not
  reads as "mostly shared" while notes keep forking.
- `login` — present for every home you use; `account` — the email you expect.
- `onboarding` and `folder trust` — cleared for the folders you work in, or accept that `csm` will answer them.
- `connectors` — always advisory, and always the same cell: *per account — granted at
  `claude.ai/customize/connectors`, not readable offline*. `--check` does not go red on it, because no config home
  can fix it. Checking that your accounts have the same connectors is a browser task, once per account.

The end-to-end proof, for memory, is the only one that really settles it: write a note in a session on one account
in a project, start a session on the other account in the same project, and confirm it reads the note — then the
reverse.
