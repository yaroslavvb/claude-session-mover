# The fungibility matrix

**An account is a payment layer — a login and a quota. Everything that should follow you lives outside the
account's config home and is shared.**

That sentence is the whole design. If you run several Claude accounts on one machine, the parts of your setup that
make the machine *yours* — instructions, skills, plugins, hooks, memory, permission defaults — have no business
living inside any one account's config home. Put them in one place every home reads, and switching accounts stops
being a migration. What is left over after you do that is the short list of things that genuinely cannot be shared,
and this page is about telling the two apart.

A *config home* is the directory `CLAUDE_CONFIG_DIR` points at (`~/.claude` when it is unset). One home holds one
login, so one home is one account. Everything below is measured against Claude Code 2.1.300 on macOS; Linux
differences are called out where they exist.

Run `csm matrix` to see the state of your own machine. Every section below names the row that reports it.

## The matrix

Legend: ✅ fungible (shared, or `csm` carries it) · 🔧 fungible after a one-time setup · 🛑 not fungible — per
account, per config home or per machine by design · ⚠️ changes when a session moves (`csm` tells you).

| Layer | Lives in | Across accounts (one machine) | Across machines | What to do |
|---|---|---|---|---|
| [Conversation (transcript)](#conversation) | `<home>/projects/<folder>/<id>.jsonl` + optional `<id>/` | ✅ `csm` copies it | 🔧 copy by hand — `csm` moves within one machine | the folder name is derived from the absolute path; `claude --resume` also takes a file path |
| [Usage limits](#quota) | the account | 🛑 per account — the reason to move | ✅ one account, one quota, every machine | move the session; never pool credentials |
| [Login (OAuth credential)](#login) | macOS: Keychain item named from the literal `CLAUDE_CONFIG_DIR`; Linux: `<home>/.credentials.json` | 🛑 one login per config home | 🛑 sign in on each machine | renaming a home on macOS orphans its login |
| [**claude.ai connectors**](#connectors) (Gmail, Drive, Calendar, …) | your claude.ai account (server-side) | 🛑 **per account — no terminal can attach one** | ✅ follow the account to every machine | enable the same set on every account at `claude.ai/customize/connectors`; a moved session sees only the target account's connectors |
| [MCP server sign-ins (OAuth)](#mcp-signins) | inside the login credential | 🛑 per config home | 🛑 per machine | `claude mcp login <server>` once per home |
| [MCP server definitions](#mcp-definitions) | project `.mcp.json`, user scope in `.claude.json`, plugins | 🔧 project `.mcp.json` or a shared plugin; user-scope entries are per home | 🔧 same | prefer project or plugin scope |
| [Auto-memory](#memory) | `<home>/projects/<folder>/memory/` | 🔧 point every home at one store | 🔧 a synced store, if the project path matches | `csm` never copies memory (copies fork) |
| [settings.json](#settings) (permissions, hooks, env, enabled plugins) | `<home>/settings.json` | 🔧 symlink every home to one file | 🔧 sync it; absolute paths inside are per machine | holds no login, so it is the safe file to share |
| [CLAUDE.md, skills, agents, commands, output styles](#instructions) | `<home>/…` | 🔧 symlink into one shared dir | 🔧 dotfiles or a repo | project-level copies travel with the repo |
| [Plugins](#plugins) | enabled in `settings.json`, installed in `<home>/plugins/` | 🔧 symlink `plugins/` as well — enabled is not installed | 🔧 install on each machine | |
| [Scheduled tasks](#scheduled-tasks) | `<home>/scheduled-tasks/` | 🔧 shareable, but each run bills the home that runs it | 🛑 per machine | |
| [First-run and folder-trust answers](#first-run) | `<home>/.claude.json` | 🛑 per home — `csm` pre-answers them for the moved folder | 🛑 per machine | |
| [Bypass-mode consent](#bypass-consent) | `skipDangerousModePermissionPrompt` in `settings.json` | 🔧 comes with a shared `settings.json` | 🔧 same | |
| [Permission mode](#permission-mode) | settings `permissions.defaultMode` + the session's record | ✅ `csm` chooses it — never weaker | — | |
| [Model, title](#model-title) | the transcript | ✅ carried | — | a title can change with the next prompt; use the link |
| [Preserved thinking](#thinking) | bound to the organization that wrote it | ⚠️ dropped across organizations; the first turn re-reads on the target's quota | — | move early, not at the limit |
| [claude.ai session link](#session-link) | Remote Control | ⚠️ a new link, owned by the target account | — | the old link still opens the old copy |
| [Process environment](#process-env) | the launching process | 🛑 never inherited — `csm` scrubs `CLAUDE*` / `ANTHROPIC*` | — | |
| [Rewind history, task lists](#rewind) | `<home>/file-history/<id>/`, `<home>/tasks/<id>/` | ✅ `csm` copies the session's own, additively, when it is there | — | `csm move --dry-run` lists what it will copy |
| [Host tool logins](#host-logins) (git, cloud CLIs) | your OS user | ✅ shared by every account on the machine | 🛑 per machine | |

Three things worth saying once, because they frame everything else:

- **Sessions can only see and message sessions of their own account.** Cross-session messaging is scoped to the
  config home's live-session registry and the account behind it.
- **The official clients have no multi-email account switcher.** The browser profile is the switch. In the terminal,
  `CLAUDE_CONFIG_DIR` is the switch.
- **One login holds one organization.** That is why preserved thinking does not survive a move between two personal
  accounts (see [Preserved thinking](#thinking)).

---

<a id="conversation"></a>

## Conversation (transcript)

**Where it lives.** `<config home>/projects/<folder>/<session-id>.jsonl`, where the filename stem is the session id.
Beside it there may be a directory with the same name holding the session's side data — `subagents/agent-<id>.jsonl`,
`tool-results/`, `workflows/`, `custom-title.json`, `ccr-tip.json`. The directory is optional. The `<folder>` name is
the session's absolute working directory with **every** character outside `[A-Za-z0-9]` replaced by `-` — dots,
slashes and underscores included — truncated to 200 characters with a base-36 hash of the original appended when it
is longer. The project directory can also hold `memory/` and a `bridge-pointer.json`, and neither belongs to any one
session.

**Across accounts: ✅ with a copy.** The transcript is account-agnostic text; it is the home it sits in that decides
which account replays it. `--resume <id>` searches the current directory's project folder, then the sibling git
worktrees of the same repo, then every project folder in the home for `<id>.jsonl` (accepting the result only if
exactly one matches) — but it never looks in another config home. So moving a session means putting the file in the
target home. `--resume` also accepts a path to a `.jsonl` file directly, which is the simplest way to resume a
transcript that is not where the slug says it should be.

**Across machines: 🔧 by hand.** Nothing syncs transcripts. Copy the file, and expect the folder name to differ if
the project's absolute path differs. `CLAUDE_CODE_PROJECT_DIR_NAME` (`[A-Za-z0-9_-]{1,64}`, no Windows device names)
overrides the project directory name outright, which is the clean answer to "the same repo lives at a different path
on my other machine".

**What `csm` does.** Copies the `.jsonl` and its sibling `<id>/` directory into the target home, reusing the
**source's** folder name rather than recomputing a slug, and never moves, edits or deletes the source. Each move
leaves one copy per home.

**`csm matrix` row.** None — the matrix describes homes, not sessions. `csm list` shows the transcripts.

<a id="quota"></a>

## Usage limits

**Where they live.** On the account, server-side.

**Across accounts: 🛑 by design.** This is not a gap to close; it is the reason the tool exists. Pooling credentials
to share a quota is a bad trade — it splits attribution, puts logins in plaintext, and risks account standing.

**Across machines: ✅.** One account's quota looks the same from every machine it serves.

**What `csm` does.** Marks a session whose last turn hit a usage limit and moves it onto an account with headroom.
It recognises several error shapes (`usage_limit_reached`, `rate_limit_error`, `rate_limit_exceeded`), so a session
that stopped for quota is flagged rather than silently listed as idle.

**`csm matrix` row.** None — a quota is not readable offline. The `account` row tells you which account each home
spends.

<a id="login"></a>

## Login (OAuth credential)

**Where it lives.** On macOS, not in a file: a generic-password Keychain item whose **service** is
`Claude Code-credentials` when `CLAUDE_CONFIG_DIR` is unset, and `Claude Code-credentials-<8 hex>` otherwise, where
the 8 hex characters are the start of `sha256(NFC(<the literal CLAUDE_CONFIG_DIR string>))`. The item's **account**
attribute is `$USER`. On Linux and in containers there is no keychain and the login is a plaintext file at
`<config home>/.credentials.json`, mode 0600; Claude Code refuses to follow a symlink in its place.

**Across accounts: 🛑 one login per config home.** That is the definition of a home.

**Across machines: 🛑.** Sign in once per account per machine. The refresh window is set at login (on the order of
weeks) and ordinary renewals do not extend it, so "days left" counts down from the last interactive sign-in, not
from the last use.

**Traps worth knowing.** The hash is taken over the string exactly as you exported it, so a path and the same path
with a trailing slash are two different logins — and spelling the default home out as
`CLAUDE_CONFIG_DIR=$HOME/.claude` takes the hash branch and lands on a different, empty slot, which reads exactly
like "logged out" for a home that is signed in. Unset must mean unset. Renaming or moving a home on macOS does **not** carry its login; see
[docs/setup.md](setup.md#rename) for the copy-first order. On Linux the opposite is true: the login travels with the
directory.

**What `csm` does.** It checks, and never reads. The target check is tri-state: the state file's
`oauthAccount.emailAddress` **and** the credential's *existence*, tested with
`security find-generic-password -a "$USER" -s "<service>"` — exit code only, never `-w` or `-g`, under a timeout; on
Linux, the existence of `<home>/.credentials.json`, never its contents. Signed in → proceed. Credential gone →
refuse, with the fix. Could not look (a locked keychain, an ssh hop, a timeout) → proceed and warn UNVERIFIED.
Unreadable is never reported as signed out. No credential value is read, printed, logged or copied, ever.

**`csm matrix` rows.** `account` (the email from the state file) and `login`, whose cells are `ok` / `GONE` /
`signed out` / `? unverified`.

<a id="connectors"></a>

## claude.ai connectors

This is the one row of the matrix that cannot be made fungible from a terminal, on any machine, by any tool. It is
worth being exact about why.

**Where it lives.** On your claude.ai account, server-side. A connector is a property of the **account**, not of the
machine, the config home or the session. The CLI fetches the connector list from claude.ai **at startup**, for
whichever account the home is logged in as, re-fetches it when the account changes, and needs an MCP-connectors
scope on the login token to see it at all; without that scope it reports that connectors could not be loaded in this
session.

**Nothing local holds the grant.** The only on-disk traces are caches of names and ids:
`claudeAiMcpEverConnected` in `<home>/.claude.json` (a list of connector server ids this home has ever connected to),
`mcpNeedsAuthNoticed` in the same file, and `<home>/mcp-needs-auth-cache.json`, whose top-level keys are display
names of the form `claude.ai <ServiceName>`. All three are caches. Copying any of them into another home gives that
home's account nothing — it only makes the cache lie.

**The CLI refuses to let you write one by hand.** A server entry in an MCP config that declares
`type: "claudeai-proxy"` is rejected with the message that this type is only used by claude.ai connectors, and the
CLI points you at `claude.ai/customize/connectors` — or tells you to add an ordinary server with `type: "http"`
instead. `claude mcp login <name>` can **authenticate** a connector the account already has; it cannot attach one.
There is no `claude mcp` subcommand, and no flag anywhere, that connects a connector to an account.

**Therefore:**

- **Across accounts: 🛑 not fungible, no workaround.** A terminal cannot attach a connector to an account.
- **Across machines: ✅ for free.** The grant belongs to the account, so one consent covers every machine that
  account serves.
- **A moved session sees only the target account's connectors.** If the source account had Gmail and the target does
  not, the moved session loses that capability mid-task. This is the single largest remaining gap in treating
  accounts as interchangeable.

**How to make it fungible.** Only in a browser, and only by hand: open `claude.ai` → Settings → Connectors, signed
in as that account, and enable the same set. Do it once per account, each in its own browser profile — never chain
two accounts' sign-ins in one window. The nearest local substitute is `claude mcp add --transport http …`, which
gives you an ordinary MCP server: per home rather than per account, and invisible to cloud routines.

**What `csm` does.** It warns, before the move. It scans the session's transcript for tool names beginning
`mcp__claude_ai_` and lists the connectors the conversation has actually used, with the note that these belong to the
account and must be enabled on the target account at `claude.ai/customize/connectors`, because no terminal can
attach them. This is a warning, never a refusal: the move still works, and you are the one who knows whether the
rest of the conversation needs Gmail.

**`csm matrix` row.** `connectors`, and it always prints the same cell: *per account — granted at
`claude.ai/customize/connectors`, not readable offline*. The matrix is read-only, offline and prompt-free, and
nothing in a config home answers the question, so an honest row says so rather than guessing. It is also advisory:
`csm matrix --check` does not fail on it, because a red exit code for something no config home can fix would stay
red forever.

(If you want the real per-account list, it has to come from the CLI's own MCP listing run with that home's
`CLAUDE_CONFIG_DIR` — which is not a read: it rewrites that home's `.claude.json` and health-checks every configured
server over the network. That is why it is not part of `csm matrix`.)

<a id="mcp-signins"></a>

## MCP server sign-ins (OAuth)

**Where they live.** Not in a separate file. Under an `mcpOAuth` key **inside the same credential blob as the
claude.ai login** — the Keychain item on macOS, `.credentials.json` elsewhere — keyed per server, each holding an
access token, a refresh token and a client registration.

**Across accounts: 🛑 per config home.** There is no file to copy, and signing a second home into the same account
does not carry its MCP server logins over.

**Across machines: 🛑.** Same reason.

**How to make it fungible.** You cannot; you can only repeat it. Run `claude mcp login <server>` once per home, per
machine, and put it on your new-home checklist.

**What `csm` does.** Warns. It lists the `mcp__<server>__` servers the transcript has used and notes that MCP
sign-ins are per config home.

**`csm matrix` row.** `MCP sign-ins`, which always reads *per home — stored inside the login credential, not read*.
On macOS the map is inside the Keychain secret and reading it would mean reading the secret, which the tool never
does. (`MCP servers` is a different row — see below.)

<a id="mcp-definitions"></a>

## MCP server definitions

**Where they live.** Three scopes: a project's own `.mcp.json`; user scope in `<home>/.claude.json` under
`mcpServers`; per-project entries in `<home>/.claude.json` under `projects['<cwd>'].mcpServers`; and plugin scope,
inside each installed plugin's own `.mcp.json`.

**Across accounts: 🔧.** A project `.mcp.json` is read by every account that opens that folder, and a plugin's
servers come with the plugin — so both are shared the moment the plugin directory is. User-scope entries live in
`.claude.json`, which must stay per home, so those are not shared.

**Across machines: 🔧.** Same answer: project and plugin scope travel with the repo or the plugin; user scope does
not.

**How to make it fungible.** Prefer project scope or a plugin over user scope. Remember that the definition and the
sign-in are different things: sharing the definition does not share the OAuth token.

**What `csm` does.** Nothing to the definitions; it only warns about the sign-ins.

**`csm matrix` row.** `MCP servers`, listing the user-scope server **names** per home (names only — an MCP URL,
header or env value routinely carries a token, so none of those is printed or exported).

<a id="memory"></a>

## Auto-memory

**Where it lives.** By default `<config home>/projects/<folder>/memory/`, with `MEMORY.md` as the index. Two
settings relocate it, and they do **not** behave the same way:

- `autoMemoryDirectory` (a `settings.json` key) is used **verbatim** as the memory directory — nothing is
  appended, and a leading `~/` is expanded. It is the documented lever, and it **wins** over the variable below.
- `CLAUDE_CODE_REMOTE_MEMORY_DIR` (an environment variable) moves the **base**: memory becomes
  `$CLAUDE_CODE_REMOTE_MEMORY_DIR/projects/<folder>/memory/`, still one directory per project.

That difference decides which one you want. See [docs/setup.md](setup.md#memory) for the verification and the
recipe.

**Across accounts: 🔧 one line.** Point every home at one store and every account on the machine shares one memory
per project. Critically, relocating this way leaves the memory write auto-allow intact, so no permission rule is
needed — and none should be added.

**Across machines: 🔧, with one caveat.** Put the store in a synced or shared directory and spell that directory in
each machine's own literal absolute path. The caveat is that the per-project folder name is derived from the
project's **realpath**, so the same repo checked out under a different username or a different parent directory
produces a different folder even when the base is shared.

**Traps.** The environment variable is undocumented and is not interpolated: a `~/x` or `$HOME/x` value makes the CLI
create a directory literally named `~` in the working directory. Never point at a store with a *symlink* — a
symlinked memory or project directory breaks the write auto-allow, and the write is then denied in `default` and
`acceptEdits` mode. A running session keeps the environment it started with, so a cutover is only finished once
long-lived sessions restart. A **resumed** session writes the memory path carried in its own history, which after a
cutover is the old per-home path. And never add a `permissions.deny` or `permissions.ask` rule naming a memory path:
a blocking rule on a memory write makes the background memory agent refuse to run at all, which switches auto-memory
off entirely and silently — for every account at once, if the settings file is shared.

**What `csm` does.** It never copies `memory/`, in any configuration, because a copy is how two stores start to
fork. Instead it resolves each home's memory directory the way the CLI does — `env.CLAUDE_COWORK_MEMORY_PATH_OVERRIDE`
(verbatim), then `autoMemoryDirectory` (verbatim, `~/` expanded), then `env.CLAUDE_CODE_REMOTE_MEMORY_DIR` or the
config home plus `projects/<folder>/memory/` — and reports in the plan whether the two homes share a store or not.
A store that is configured but not created yet still counts as the store. If the two homes do not share one, the
plan says so: the moved session will not see the source home's notes for this project.

**`csm matrix` row.** `auto-memory`: shared store vs per home, with the resolved directory, for every home side by
side. The state to watch for is **mixed** — some homes pointing at the store and some not. It reads as "mostly
shared" while notes keep forking.

<a id="settings"></a>

## settings.json

**Where it lives.** `<config home>/settings.json`, with `<config home>/settings.local.json` merged over it. It
carries `permissions` (`defaultMode`, `disableAutoMode`, `allow`/`deny`/`ask`), `env`, `hooks`, `enabledPlugins`,
`extraKnownMarketplaces`, `skipDangerousModePermissionPrompt`, `theme`, `tui` and more. On 2.1.300 `theme` is a
settings key, not a `.claude.json` key — older documentation that places it in `.claude.json` is wrong.

**Across accounts: 🔧 the highest-value link there is.** It holds no login, which is exactly what makes it the safe
file to share. One file, one edit, every account.

**Across machines: 🔧.** Sync or copy it, but remember that any absolute path inside it — a memory store base, a hook
script — is machine-specific and has to be spelled per machine.

**Traps.** `settings.local.json` is merged **over** `settings.json`, so one home that has one while its siblings do
not runs with different settings even when `settings.json` is perfectly shared. That asymmetry is the most common
"but they're identical" false positive. Separately, a set of keys — including `enabledPlugins`,
`autoMemoryDirectory`, `allowedMcpServers`, `modelOverrides` and `disableAllHooks` — is stripped when the settings
come from the folder Claude Code was launched in rather than from your own settings, so put anything that must apply
to every account in each home's user settings (or the one shared file they link to).

**What `csm` does.** Reads the target home's effective settings to choose the permission mode, and never writes
them.

**`csm matrix` rows.** `settings.json` and `settings.local.json` (shared = same realpath as the other homes / own
file / missing), plus the derived rows `permissions mode`, `disableAutoMode` and `bypass consent`. "Same realpath"
is the only test that proves two accounts actually read one file; comparing contents would call two copies equal
right up until somebody edits one. `settings.local.json` is reported but never fails `--check`: one home having
one and another not is usually the design, not a drift. The derived rows are resolved the way the CLI resolves
them — **per key path**, first definition wins — so a `settings.local.json` holding only `permissions.allow` leaves
the shared `permissions.defaultMode` standing instead of erasing it.

<a id="instructions"></a>

## CLAUDE.md, skills, agents, commands, output styles

**Where they live.** `<home>/CLAUDE.md`, `<home>/skills/`, `<home>/agents/`, `<home>/commands/`,
`<home>/output-styles/`.

**Across accounts: 🔧 symlink each into one shared directory.** `agents/`, `commands/` and `output-styles/` are plain
files with no account scope — share them freely. `skills/` is shareable too, with one caveat: `skills/synced/` holds
skills synced from claude.ai, named `<skillUuid>_<accountUuid>`, so sharing the parent directory pools every
account's synced copies into one place. If that is unwanted, link the hand-written skill directories individually and
leave `skills/synced/` per home.

**Across machines: 🔧.** Keep them in dotfiles or a repo and install from there; project-level copies travel with the
repo they are in.

**What `csm` does.** Warns when the source home has skills, agents or commands the target home lacks (compared by
realpath, so two homes linked to one shared directory raise nothing). The moved session picks up whatever the target
home has.

**`csm matrix` rows.** `CLAUDE.md`, `skills`, `agents`, `commands`, `output-styles` — each per home: shared with
the others (same realpath), its own file, or missing. One realpath for every home reads as `shared` wherever that
path lives, including inside one of the config homes; that layout earns a note rather than a fault, because
renaming or deleting that home would dangle every link into it. A **DANGLING** symlink IS a fault, distinct from
"absent": it is what a home rename leaves behind, and it is silent — the CLI simply loads nothing.

<a id="plugins"></a>

## Plugins

**Where they live.** Two halves in two places: *enabled* is a flag in `settings.json` (`enabledPlugins`), *installed*
is a payload in `<home>/plugins/` — `installed_plugins.json`, `known_marketplaces.json` and `plugins/cache/<marketplace>/<plugin>/<version>/`.

**Across accounts: 🔧 symlink `plugins/` as well.** This is the trap the two halves create: a plugin enabled in a
shared `settings.json` is claimed by **every** home, while the install lives in one. The accounts that are supposed
to be interchangeable then silently lack its slash commands, skills and MCP servers. Symlinking `plugins/` makes one
`claude plugin install` serve every account on the machine. Caveat, as with skills: `plugins/synced/` holds
claude.ai-synced plugin state, which is account-scoped, so sharing the parent pools it.

**Across machines: 🔧 install once per machine.** Each home caches its own marketplace manifest, so without a shared
directory several versions can be live at once.

**What `csm` does.** Warns when the target home has plugins enabled but not installed.

**`csm matrix` rows.** `plugins` (shared / own / missing) and `plugins enabled`, which is the one
that catches the silent failure — a cell reads `–` when nothing is enabled-but-not-installed, and `N missing`
when something is. An **absent** plugin registry means nothing is installed — a fact the check must
fire on; an **unparseable** one means "I could not look", which is a different cell.

<a id="scheduled-tasks"></a>

## Scheduled tasks

**Where they live.** `<home>/scheduled-tasks/`.

**Across accounts: 🔧 shareable, but think first.** The files share fine. The consequence does not: a task runs on
whichever account's home it sits in, so sharing the directory changes who pays for every run. If exactly one account
is meant to run scheduled work, leave the directory per home — its absence elsewhere is the design, not drift.

**Across machines: 🛑.** A scheduled task runs where its scheduler runs.

**What `csm` does.** Nothing.

**`csm matrix` row.** `scheduled-tasks` (shared / own / missing), reported like the other shareable entries. Read a
divergence here as a question, not a fault.

<a id="first-run"></a>

## First-run and folder-trust answers

**Where they live.** `<home>/.claude.json` — the per-home state file. Note where that file is: with
`CLAUDE_CONFIG_DIR` set it lives **inside** the home; with it unset it is `~/.claude.json`, never inside the default
`~/.claude` directory. The two keys that block an unattended start are top-level `hasCompletedOnboarding` and
`projects['<absolute cwd>'].hasTrustDialogAccepted`.

**Across accounts: 🛑 per home, and per (home × directory) for trust.** A new home always re-asks. `.claude.json`
must never be shared: it carries the account identity (`oauthAccount`), user-scope MCP servers, per-project history
and the first-run gates all in one file, so sharing it crosses account identities.

**Across machines: 🛑.** The state file is per home, and a home copied to another machine also carries a stale
`machineID` and `remoteControlMachineId`.

**Why it matters more than it sounds.** The blocking dialogs — workspace trust ("Yes, I trust this folder" / "No,
exit", or "No, continue without these permissions" when MCP servers are in play), the bypass-mode disclaimer
("WARNING: Claude Code running in Bypass Permissions mode" → "Yes, I accept" / "No, exit") and the Remote Control
offer ("Enable Remote Control" / "Never mind") — are all built with the cancelling answer **listed first and holding
focus**, and with the option numbers hidden. A stray Enter declines. An unattended start in a cold home does not
fail loudly; it sits there, and from a phone it reads as "started and never connected".

**How to make it fungible.** You cannot share it, but you can pre-answer it: set
`projects['<absolute cwd>'].hasTrustDialogAccepted` and `hasCompletedOnboarding` in the new home's `.claude.json`,
and `skipDangerousModePermissionPrompt` in its settings. Merge the keys you need; never copy the file.

**What `csm` does.** Pre-answers these gates for the folder it is moving the session into, and — for a dialog that
still appears — answers by **reading the `❯` marker's own line** each poll: Down only while the marker is not on the
wanted option, Enter only when the marker's line names the wanted label and not the cancelling one, and no key at all
when the pane is ambiguous. Never a digit, never a canned keystroke sequence. It accepts the bypass warning only when
the move was deliberately asked to start in bypass mode.

**`csm matrix` rows.** `onboarding` and `folder trust`, both evaluated for `--cwd` (the current directory by
default), per home.

<a id="bypass-consent"></a>

## Bypass-mode consent

**Where it lives.** `skipDangerousModePermissionPrompt` in `settings.json`. The older `.claude.json` key
`bypassPermissionsModeAccepted` is still honoured on 2.1.300, but new homes should get the settings key.

**Across accounts: 🔧 free with a shared `settings.json`.** It is one of the better arguments for sharing that file.

**Across machines: 🔧 same.**

**Why it matters.** A home without it stops on a warning dialog whose first, focused option is "No, exit". An
unconsented `bypassPermissions` start is silently downgraded to `default`, and `--bg` with `bypassPermissions` (or
with auto mode) refuses outright until that home has accepted the disclaimer once, interactively.

**What `csm` does.** Answers the dialog only when the move deliberately starts the session in bypass mode.

**`csm matrix` row.** `bypass consent`, whose cells are `accepted` / `accepted(old)` / `will warn` /
`bypass OFF` / `?`.

<a id="permission-mode"></a>

## Permission mode

**Where it lives.** In two places that interact: `permissions.defaultMode` in the target home's effective settings,
and the mode recorded on the session itself. `permissions.disableAutoMode` is an enum with exactly one legal value,
the string `"disable"`; setting it removes `auto` from the modes a session can enter or return to, it is read once at
launch, and a managed-settings copy overrides everything below it.

**Across accounts: ✅ `csm` chooses it, and never weakens it.** Explicit `--permission-mode` wins (validated;
`manual` is an alias of `default`). Otherwise the target's effective `permissions.defaultMode` — `settings.json`
resolved through symlinks, with `settings.local.json` over it — replaces the transcript's mode only when the
transcript recorded nothing, `default` or `auto`. `plan` and `acceptEdits` are carried as they are; unknown modes are
left untouched. The plan line names which of those rules decided.

**A caveat that is easy to miss.** A session's mode is a property of the running process. If the source session was
in `auto` and the target home or machine disables auto mode, the moved session cannot come up in the same mode. And
`--permission-mode` is ignored when *attaching* to an existing session, and is not forwarded to a cloud one.

**What `csm` does.** Beyond choosing: after the session starts it reports the mode it **actually** came up in, read
from the session's own record or the footer, rather than repeating what was asked for. If it could not measure it,
it says "asked for X (not measured)" rather than claiming.

**`csm matrix` rows.** `permissions mode` and `disableAutoMode`, reported verbatim per home, never coerced to
a boolean.

<a id="model-title"></a>

## Model and title

**Where they live.** In the transcript. A custom title is `<id>/custom-title.json`.

**Across accounts: ✅ carried**, because the transcript is.

**Caveat.** A title is not stable: the next prompt can change it, and the listed title is unreliable as an identifier.
Use the session link or the id.

**What `csm` does.** Resolves the title by precedence — custom title, then the AI-generated title, then the last
prompt, then the first user message — and prints the new session link after the move.

<a id="thinking"></a>

## Preserved thinking

**Where it lives.** Server-side, bound to the organization that produced it.

**Across accounts: ⚠️ dropped between organizations.** Resume a transcript signed in to a different organization and
the CLI says so plainly: *"Claude can't use thinking from another organization … It isn't deleted: resume this
session signed in to that organization to use it again. Claude's next responses may be slower and use more tokens
because it has to reread this session and generate new thinking."* Nothing is lost and the move still works — but the
first turn on the new account re-reads the whole conversation, and that re-read is billed to the **target's** quota.

Two accounts in the same organization do not hit this. Two separate personal accounts always will.

**What this means in practice.** Move early, not at the limit. A move made when a session is small costs a small
re-read; a move made at the cap costs the largest re-read the session will ever have, on the account you were trying
to conserve.

**What `csm` does.** Says this in the plan and again in the success block, and — when both homes' state files are
readable — compares the two `oauthAccount.organizationUuid` values, so it can tell you "same organization: thinking
is kept" instead of warning for nothing.

<a id="session-link"></a>

## claude.ai session link

**Where it lives.** With Remote Control. A bridged session's transcript carries `bridge-session` lines holding a
`bridgeSessionId` (a `cse_…` id), and the web URL is the same id with the prefix swapped:
`cse_X` → `https://claude.ai/code/session_X`. The owner account and organization uuids are stamped per bridge
session.

**Across accounts: ⚠️ a new link.** The moved session connects as a new bridge session owned by the target account.
The old link still opens the old copy, on the old account.

**What the web view shows.** `noHistoryBackfill` is a real per-bridge-session flag that suppresses replaying the
local conversation up to the web client, and it is forced on when a session reattaches to a bridge session other
than the one it last recorded — which is exactly what a move is — though it was present on the bridge line appended
by 2.1.296 and **absent** from the lines appended by 2.1.300, so treat the flag, not the rendering, as the measured
part. The certain half: the local agent has the whole conversation, the moved session gets a new link owned by the
target account, and the app may show the conversation starting at the move. That looks like data loss and is not.
Take none of this as a promise about what the app renders; the local transcript is the thing that is certain.

**What `csm` does.** Prints the new link, because the listed title is unreliable.

<a id="process-env"></a>

## Process environment

**Where it lives.** In whatever process launched the CLI.

**Across accounts: 🛑 never inherited, deliberately.** A `CLAUDE_*` or `ANTHROPIC_*` variable left over from the
session you typed the command in is exactly how a move ends up pointing at the wrong home, the wrong memory store or
the wrong key.

**What `csm` does.** Drops **every** `CLAUDE*` and `ANTHROPIC*` variable — by family, not by a list of names — for
the child process and for every `tmux` call, then sets back only `CLAUDE_CONFIG_DIR` (and unsets it for the default
home, because an explicit `$HOME/.claude` is a different Keychain slot from unset).

<a id="rewind"></a>

## Rewind history, task lists

**Where it lives.** Outside `projects/`, in the config home itself, keyed by session id: `<home>/file-history/<id>/`
holds the per-session snapshots of files Claude edited, which back the rewind feature — verified on 2.1.300, where
every config home had it. `<home>/tasks/<id>/` is a path the CLI knows (its own read-allowlist names it), but on
2.1.300 a session's task **output** is written outside the config home, under a cache root keyed on the working
directory, so there is usually nothing there to carry. Older builds filed the same lists as
`<home>/todos/<id>-*.json`.

**Across accounts: ✅.** The directories are per home, so the data would be left behind if the transcript travelled
alone. `csm` copies whichever of them the session actually has into the target home, **additively and never
overwriting** — an existing file there is left as it is. `csm move --dry-run` lists exactly what will be copied, and
that output is the authoritative answer for your version.

**What is never copied, in any case:** `session-env/`, `shell-snapshots/`, `sessions/`, `jobs/`,
`bridge-pointer.json`, `.claude.json` and credentials. The first four are code-execution surfaces the CLI itself
denies writes to even under bypass; `sessions/` holds per-process secrets and pids that mean nothing in another home;
`bridge-pointer.json` points at a live pid and is stale the moment a session moves.

<a id="host-logins"></a>

## Host tool logins

**Where they live.** With your OS user: `git` credentials, `gh`, cloud CLIs, SSH keys.

**Across accounts: ✅ free.** Every config home on the machine runs as the same OS user, so every account's sessions
see the same host tooling. This is the one layer that is fungible without doing anything.

**Across machines: 🛑.** Per machine, like any other local credential.

**One related fact.** The machine's device keys live at `~/.claude/.device-keys.json` regardless of
`CLAUDE_CONFIG_DIR` — per machine, shared by every account on it, and stale if a config home is cloned onto a second
machine.

**`csm matrix` row.** None; the matrix describes config homes. `CLI version` is the other machine-level row, read
without running the binary where it can be (the launcher symlink names the version), so the matrix stays safe to
run from a hook or a scheduled check.

---

## How to read `csm matrix`

Rows are layers, columns are the config homes on this machine, plus a verdict column. Every cell is one of three
things, never two:

- **measured ok** — read, and it matches,
- **divergent** — read, and it does not,
- **unknown, with the reason** — could not be read.

**Unknown is never folded into ok.** A checker that quietly promotes "I could not look" to "fine" prints a green
summary over a machine it never read, and the summary line is never "all homes match" while a cell is unknown. The
same rule separates *absent* (a fact) from *unreadable* (not a fact): an absent plugin registry means nothing is
installed; an unparseable one means nothing at all.

```sh
csm matrix                      # the whole table for the current directory
csm matrix --cwd ~/code/app     # evaluate the first-run gates for that folder
csm matrix --account work,personal
csm matrix --json
csm matrix --check              # exit 1 when a shareable layer diverges or a login is gone
```

`--check` is about the homes. It does not go red for connectors, which no config home can fix.

To act on what it tells you, see [docs/setup.md](setup.md).
