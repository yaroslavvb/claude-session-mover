# Lessons from running several Claude accounts

These lessons come from running several Claude Code accounts — several config homes — across more than one machine
for day-to-day work, and from reading the CLI's own behaviour on versions 2.1.29x–2.1.300 on macOS and Linux. They
are written for anyone who keeps more than one account and wants a session, a setting or a note to be usable from
any of them. Every technical detail here was measured on those builds: Claude Code moves fast, keys get renamed and
dialogs get re-drawn, so re-check anything load-bearing against the version you actually run. Where a lesson is
something `csm` already does for you, it says so in a few words.

Most of this ground is also covered in [LESSONS.md](../LESSONS.md), as one-line rules — each with the incident
behind it, a command to check it, and the Claude Code version it was verified against. Those go up to 2.1.308,
newer than this page, so where the two differ, trust that one.

Contents: [Accounts and identity](#accounts) · [Credentials and signing in](#credentials) ·
[Sharing configuration](#sharing) · [Memory](#memory) · [Moving a session](#moving) ·
[Permission modes](#modes) · [Remote Control](#remote-control) · [Connectors and MCP](#mcp) ·
[Running many homes](#many-homes)

<a id="accounts"></a>

## Accounts and identity

**An account is a payment layer — a login and a quota. Everything that should follow you belongs outside the config
home.**
A config home owns the login, the transcripts written under it and its own first-run answers. Settings,
instructions, skills, plugins and memory do not have to live there, and anything that does will fork silently the
day you add another account. Decide, layer by layer, whether a thing is a payment detail or something that should
follow you, and move the second kind into one shared place every home links to.

**`CLAUDE_CONFIG_DIR` is the only thing that selects an account, and the login — not the directory name — says which
account that is.**
Window titles, service labels and log file names are decoration; a process started without the variable takes the
machine's default home and whatever login it holds. Spell the variable in every launcher, scheduler and wrapper, and
make a bare run with no account named fail loudly instead of quietly spending the wrong quota. A home named for one
account can hold another's credential, and nothing in the interface says so.

**One login holds one organization; a second organization on the same address is, in practice, a second account.**
The organization is chosen in the browser at sign-in time, and quota, policy and preserved thinking all follow it.
There is no in-place switch, so give each organization its own config home and record which one each home was signed
into.

**No client shows accounts on different emails together, and a session can only see sessions on its own account.**
The built-in switcher covers an individual and a team on the same email; past that, the browser profile is the
switch. If you want one view, build it locally by reading every config home on the machine — that is what
`csm list` and `csm accounts` do — and never design an agent workflow that assumes one account's session can
enumerate or message another's.

**Answer a usage limit by moving one conversation, not by pooling logins.**
A proxy that fans several accounts behind one endpoint becomes a second credential store outside the designed one,
splits usage attribution, and carries real account-standing risk; moving a single session achieves the same
continuation with none of that. For the same reason, keep scheduled, unattended work on a different account from the
one you use by hand, so one limit cannot stop both at once.

<a id="credentials"></a>

## Credentials and signing in

**Know where the login actually lives: outside the config home on macOS, inside it elsewhere.**
On macOS it is a Keychain generic-password item whose service name is `Claude Code-credentials` when
`CLAUDE_CONFIG_DIR` is unset and `Claude Code-credentials-<8 hex>` otherwise, the hex being the first 8 characters of
a SHA-256 over the literal, NFC-normalized value of the variable — so a trailing slash is a different login. On Linux and in containers it is `<home>/.credentials.json`, mode 0600. So copying a home
copies the login on one platform and not on the other, and any migration script has to branch on that. One corollary:
never write the default home's own path into the variable — any non-empty value takes the hashed branch and lands on
a different, empty slot, which reads exactly like being signed out.

**Renaming or moving a config home on macOS orphans its login: copy the Keychain item first, prove the new home
serves, delete the old item last.**
Every file survives the rename and the home still reports signed out, which costs one interactive browser sign-in per
account per machine. Copy the item to the service name the new path hashes to, keep a dated backup, confirm the new
home works with one small live call, and only then remove the old item.

**A sign-in link authorizes whichever account the browser is already signed into — one profile per account, never
chained.**
The email typed at the terminal is only a hint, and nothing verifies it afterwards, so completing a second account's
sign-in in the same browser window puts the first account's token into the second account's home, where every
liveness check still reads green. Use a browser profile signed in as exactly that account, and read the account back
out of the home immediately afterwards.

**"Signed in" means a usable credential, and "could not read it" is a third answer, never "signed out".**
The home's JSON state file keeps naming the last account it saw long after the credential is gone, so a file-only
check blesses a home that cannot authenticate at all. Check that the credential exists — on macOS
`security find-generic-password -a "$USER" -s "<service>"`, exit code only, never `-w`, which prints the secret —
and report an unreadable store as unknown, with the reason. (`csm` does exactly this before a move, and says `UNVERIFIED` rather
than guessing.)

**An idle home's access token is expired; what carries the login is the refresh token, and that lapses too.**
A check that validates the access token will condemn a perfectly good home, and one that only compares files will
bless a dead one — the honest proof is one small live call. Logins also expire after weeks of no use with nothing
announcing it: the servers just stop, so track renewals on a schedule instead of discovering them.

**"Signed in" has three answers, and the third one must not be promoted to either of the others.**
A home can be signed in, signed out, or unreadable — and that last answer is a real one, not a technicality. The
state file records the last login the CLI *saw*, so a home whose credential has been removed still names an account
in the file and passes every file-based check; a check that reads the file alone reports "ok" for a home that cannot
make a single API call. Ask the credential store. But over an ssh hop, on a locked keychain, and anywhere the
process may not read the store, the honest answer is "I could not look" — report that as its own state, because
reading it as "signed out" is how a tool tells you to re-authenticate accounts that are perfectly fine. Refuse on a
credential that is *absent*; warn, and proceed, on one that could not be *read*.

**Read a confirmation dialog's option order off the build in front of you, and never answer one by number.**
A tool that pre-answers the CLI's first-run gates is typing into a dialog whose option order, default focus and key
handling belong to that release: which option is first, which is pre-selected, and whether the arrow keys wrap are
all free to change, and a dialog may draw no numbers at all. Measured on two consecutive builds, the destructive
option was the first and focused one. So read the rendered prompt, match the option by its *text*, and send the
keystrokes that move to it — never a digit, and never a bare Enter on a dialog you have not read.

<a id="sharing"></a>

## Sharing configuration between homes

**`settings.json` is the file you can share; `.claude.json` is not.**
`settings.json` holds permissions, hooks, `env`, enabled plugins and theme, and holds no login, so every home can be
a symlink to one copy. `.claude.json` holds the account record and the per-directory trust answers, which are
precisely the things that must stay per home. Put anything meant for every account in the user-level settings of each
home, not in a project folder — a set of keys, `enabledPlugins` and `autoMemoryDirectory` among them, is stripped
when settings come from the folder the CLI was launched in.

**Share the parts of a home that are configuration, and leave the parts that are state.**
Link `CLAUDE.md`, `skills/`, `agents/`, `commands/`, `output-styles/` and `plugins/` to one shared directory; leave
`projects/`, `sessions/`, `file-history/`, `history.jsonl` and the credential alone. `scheduled-tasks/` can be shared
too, but each task runs — and bills — on whichever home holds it. Claude Code also treats `jobs/`, `daemon.json`,
`shell-snapshots/` and `session-env/` as code-execution surfaces and refuses writes to them even in a permissive
mode, so do not sync, link or shadow those.

**One shared settings file spreads one bad write to every account at once.**
Sharing is what makes accounts interchangeable, and it is also a single point of failure: one truncating write leaves
every account on the machine running with no hooks and no permission rules, silently. Validate the file after any
programmatic edit, keep dated backups, and treat edits to it as privileged.

**Enabled is not installed: link `plugins/` as well.**
Enablement lives in `settings.json`, which sharing makes identical everywhere, but the payload lives in each home's
`plugins/` directory — and an enabled-but-missing plugin is skipped without a word, so its skills and commands simply
do not exist for that account. Install once per machine, point every home's `plugins/` at that install, and compare
the two lists in a check. (`csm` warns when the target home has plugins enabled but not installed, and when the
source home has skills, agents or commands the target lacks.)

**Pre-answer a new home's first-run gates, or something will sit at a dialog nobody can see.**
Onboarding, workspace trust (recorded per home *and* per directory) and the bypass-mode disclaimer are all per config
home, and each draws its cancelling option first and focused — a stray Enter declines and exits. Write
`hasCompletedOnboarding` and `projects[<dir>].hasTrustDialogAccepted` into `.claude.json`, and
`skipDangerousModePermissionPrompt` into `settings.json`, rather than scripting keystrokes. (`csm` pre-answers the
gates for the folder it moves into, and when a dialog still appears it reads the focus marker off the live screen
instead of sending a canned key sequence.)

**A running session keeps the environment and settings it started with.**
Editing a shared settings file or an environment variable changes what the *next* process reads; long-lived sessions,
editors and supervisors keep their old values until they restart. A configuration cutover is finished by restarting
what is still running, not by saving the file.

<a id="memory"></a>

## Memory

**Auto-memory is written inside the active config home by default, so it forks the day you add an account.**
Point every home at one store instead, and know what each lever does. The documented `autoMemoryDirectory` setting
names the memory directory itself (it accepts a `~/` prefix), so every project ends up in one folder behind one
index — fine for a small setup, a problem once a busy project fills it. The `CLAUDE_CODE_REMOTE_MEMORY_DIR`
environment variable, set in the shared settings' `env` block, relocates the root instead and keeps the per-project
layout at `<store>/projects/<project folder>/memory/`.

**The environment variable takes a literal absolute path, and the project folder is derived from the working
directory.**
The variable is not shell-expanded, so a `~` or a `$HOME` inside it silently points nowhere useful. And because the
per-project folder name comes from the project's absolute path, the same project checked out at a different path on
another machine gets a different folder inside the same store — plan on a real directory per spelling, reconciled
deliberately, rather than expecting one folder to appear everywhere.

**Do not share a directory the CLI writes to by symlinking it.**
The write-approval check fans out over every spelling a symlink produces and wants all of them allowed, so a
symlinked memory or state directory can be refused in the stricter modes, after stalling an unattended session at a
prompt first. Share *read* configuration with symlinks; relocate *written* directories with the setting or the
environment variable, which the checker treats as a root of its own, and keep real directories underneath.

**Never write a permissions `deny` or `ask` rule that names a memory path.**
Such a rule switches auto-memory off everywhere that settings file reaches, and it does so silently — nothing reports
that notes have stopped being written. If a path must be protected, use a hook that redirects the write and says so.

**A session mover must never copy memory, because copying is how stores fork.**
With one shared store the moved session loads the same memory it already had and the mover copies nothing. (`csm`
resolves both homes' memory directories, says in the plan whether they are the same store, and warns you when the
moved session will not see the notes it had.)

<a id="moving"></a>

## Moving a session

**A move is a transcript copy plus a resume in the other home — nothing is deleted.**
A session is one JSONL file at `<home>/projects/<project folder>/<session id>.jsonl`, with an optional sibling
directory of the same name holding subagent logs, tool results and a custom title. Copy both into the other home
under the same project folder and resume there. The source file stays, so after a move the conversation exists in
both homes: count rows, not conversations, when you audit what a move left behind.

**`--resume` never looks in another config home, and the project folder name is not worth recomputing.**
Inside one home a resume will search every project folder for the id, and it also accepts a path to a transcript file
directly; across homes it finds nothing until the file is copied in. Read the source's own folder name off disk
rather than deriving it: the name is the absolute path with every character outside `[A-Za-z0-9]` replaced by `-`,
truncated past 200 characters with a hash appended, and it can be overridden outright by an environment variable.

**Across organizations a move drops preserved thinking, so move early rather than at the limit.**
Claude Code binds preserved thinking to the organization that produced it; resumed under a different one, it says so
and re-reads the conversation to generate new thinking — on the new account's quota. Nothing is lost, but the first
turn after a move is the most expensive one, and the bigger the session the more it costs. Accounts inside the same
organization do not pay this.

**A moved session gets a new session link owned by the new account, and the web view may start at the move.**
The local agent still has the whole conversation and its memory; what changes is what the web and mobile clients
show, which can begin its scrollback where the move happened. Say this out loud to whoever is using the tool: it
looks like data loss and is not. The old link still opens the old copy, on the old account.

**A moved transcript still names the account it came from, so never trust a session's self-description.**
Every earlier turn that mentioned the account and email is still in the file, and the agent will happily repeat it.
Identify the running account from the config home, the process environment and the credential instead. Titles are as
unreliable: with no explicit title, a session's title is its last prompt, so use the printed link.

**Transcripts are pinned to the machine they were born on.**
Memory can live on a shared store and follow you everywhere; transcripts do not sync. A cross-machine move means
copying the file to the other machine, pre-answering that machine's per-home gates, and making sure that machine
actually serves the working directory — the list of folders an account has registered is per account and per machine.
Be explicit about which of the two your tooling does: `csm` moves the conversation — between accounts on a machine,
and between machines with `--from-machine`, which brings the transcript and, with `--mirror-cwd`, the code. Never the
data, the devices or the jobs: those stay where they were made, and the moved session is told so.

**Scrub the environment of any process you start for another account.**
Claude Code exports a family of `CLAUDE*` variables, at least one of which carries a token, so a child inherited from
your session can act as — and bill to — the parent account even when the config directory points elsewhere. Drop
every `CLAUDE*` and `ANTHROPIC*` variable and set back only `CLAUDE_CONFIG_DIR`, and unset them in test harnesses
too, or the tests end up measuring their caller.

**Prove a process before you signal it, and never stop the session you are running in.**
Live processes register at `<home>/sessions/<pid>.json`; match the recorded start time against the live process table
byte for byte before any terminate, because a pid is reused and a name match is not proof. If the proof cannot be
made, stop nothing and say so. (`csm stop` ends only a session `csm` itself moved, and refuses everything else.)

**A session's data is not all in `projects/`: carry its file history and task list too.**
The CLI keeps per-session state *outside* the project folder, keyed by the session id — `file-history/<id>/`, which
is what an in-session rewind restores from, and, depending on the build, `tasks/<id>/` or `todos/<id>*.json` (newer
builds write task output outside the config home instead, so check before promising it). A resume looks for
them under the home it resumes *in*, so a move that copies only the transcript arrives with every word of the
conversation and no rewind history at all, and nothing says so. Copy them **additively**: the destination home may
hold its own history for that id — someone moved the session back once — and an overwriting copy destroys it. What
must *not* travel is anything describing a *process* or offering code execution: the live-session registry, captured
shell environments, shell snapshots, background-job state, pointers to a running pid, the home's own state file, and
every credential.

**Capture the pane before you end anything.**
Everything else a session owns is on disk and survives a signal. The pane does not: a prompt the agent had composed
and not yet sent exists only in the terminal's scrollback, and killing the window destroys the pane along with the
process. Measured the hard way: in one real setup a single `kill-session` on a hand-made tmux session ended every
live session in it, and the unsent drafts survived only because the panes had been captured by hand first. So the
order is capture, prove, signal; the capture is wrapped so it can never fail the stop, and the file is written 0600
on the machine that wrote it, because it holds conversation text.

**Tell the moved agent that it moved — in the session log, not in your reply.**
A resumed session reads its own transcript and believes it. Left alone it will assume the account it started on, the
machine it started on, and whatever its earlier turns said about its environment; it will also be told by the CLI
that its background jobs "didn't finish", when in fact they are still running somewhere it can no longer see. Append
one hidden, metadata-flagged line to the copy, chained to the last message, naming what changed: the account, the
machine, that its own earlier self-references are now stale, where its memory lives, and what stayed behind. Because
it is in the log, it survives a restart and a later move — which a message to the user does not.

**Memory can follow a session to another machine; its work often cannot.**
A shared memory store makes notes portable, which makes it easy to believe the session is portable. It is not: the
processes it started, the data they wrote, the devices it had paired, and the working directory itself all stay on
the machine it ran on. Mirroring the working directory moves the *code*, not the data beside it — so decide, and say
in the plan, what is being left behind. And a mirrored repository must still be able to push: if the source cloned
over ssh and the receiving machine has no key for the host, rewrite the remote to https in the *mirror's* own config,
never in the original.

<a id="modes"></a>

## Permission modes

**Permission mode is a per-machine setting, not a per-account one.**
`permissions.defaultMode` lives in `settings.json`, which a shared-settings layout makes identical for every account
on the machine, and a per-invocation override cannot loosen it because the merge keeps the stricter value. Decide the
mode per machine and write down the trade you accepted.

**When a session moves, never weaken its permission mode — and never silently widen it either.**
A transcript may record no mode at all, or one a hosted client recorded by accident; raising those to the target
home's configured default is right. But a deliberately restrictive mode such as `plan` or `acceptEdits` came from a
human gesture and must be carried through untouched. (`csm` applies exactly this rule and names, in the plan, where
the chosen mode came from.)

**Leaving the most permissive mode is one-way for that process.**
Once the mode has changed and the process was not started with the matching flag, the permissive mode stops being
offered and there is no way back short of restarting or moving the session. Do not touch the mode picker on a session
that is meant to run unattended.

**A session's mode can come from somewhere other than the flag you passed.**
A hosted session can restore the mode stored on its record, overriding the launcher's `--permission-mode`;
`permissions.disableAutoMode` — whose only legal value is the string `"disable"` — removes `auto` from the modes a
session may enter, is read once at launch, and a managed copy of settings beats everything under it; and an
unconsented `bypassPermissions` is quietly downgraded to `default`. A session also records no mode of its own until
its first prompt, so right after a resume the only honest report is "asked for X, not measured".

**Even a permissive mode routes some shell shapes to a human, and no instructions file changes that.**
Scripts passed inline to an interpreter, loops sitting next to another `-c`-style flag, unguarded deletion targets,
and reads or writes of the CLI's own configuration paths can still prompt — with nothing timing them out, so an
unattended run can wait for hours. Write scripts to a file and run the file, keep deletion targets literal, and if
you want a rule enforced, ship it as a hook that refuses the bad shape and hands back the rewrite; an instructions
file shapes what the agent chooses, not what the harness asks about.

<a id="remote-control"></a>

## Remote Control

**One Remote Control server per folder per device, and stop it with a signal it can handle.**
The claim is held server-side, so a hard-killed server never deregisters: its replacement is refused with increasing
backoff until the lease lapses, and meanwhile the dead entry stays in the session picker, offering sessions that
simply hang.

**Whatever launches Claude Code for you decides the account.**
A supervisor, scheduler or background service starts sessions as the config home in its own environment, not as
whoever asked for the session — and where the variable is unset it lands on the login-less default home and fails
outright. Pin the config directory in the service definition and verify it by reading the running process's
environment rather than the file, which can be rewritten under you.

**A desktop app is a config home your account list does not mention.**
The desktop client runs the same CLI against the default config directory, so its conversations are ordinary
transcripts in a home that a per-account inventory — built from the homes you named — leaves out entirely. Its
titles live in the app's own index rather than in the transcripts, so a search by title that reads only transcripts
misses them. Enumerate the default home too, read both places for a title, and prove which account a home holds
from its credential, never from the directory's name.

**A session can only see, and only message, sessions on its own account.**
Every listing and every session-to-session message is scoped to one account's home and one account's API identity.
So an agent cannot tell another account's session that it fixed the bug that session was stuck on, and a sweep run
from one account cannot see what the others are doing. Anything that must cross accounts crosses through the
filesystem or through a human — plan for that rather than discovering it mid-task.

<a id="mcp"></a>

## Connectors and MCP

**claude.ai connectors belong to the account, and no terminal can attach one.**
The CLI fetches the connector list at startup for whichever account the home is logged into; nothing on disk holds
the grant, the local traces are caches that are useless if copied, and a hand-written proxy entry is refused with a
pointer to `claude.ai/customize/connectors`. Grant the same connectors to every account you intend to be
interchangeable — a moved session sees only the target account's set. (`csm` lists the connectors a transcript has
been using and warns you before the move.)

**MCP server sign-ins live inside the login credential, so they are per config home.**
Signing a home into an account does not carry that account's MCP authorizations: each home needs
`claude mcp login <server>` once, and a server entry in a config file is not proof of a usable token — verify by
listing the server's tools. Prefer a project `.mcp.json` or a plugin for the server *definitions*, so they travel
instead of being retyped per home.

**`claude mcp list` is a write and a network call, not a read.**
It rewrites the home's state file and health-checks every configured server, so it has no place in a read-only audit
or a frequent status check. Cache the result, show its age, and make it something a check does only when asked.

<a id="many-homes"></a>

## Running many homes

**Name accounts after something that cannot be reassigned; never number them.**
Numbers leave gaps when an account is added or removed, and a reassigned number re-points every document, log line
and script written before the change. Derive the name from the login itself and derive the home, window and log names
from that, and have a tool handed an ambiguous name print the candidates instead of guessing.

**Make anything that can change several homes dry-run by default, and give every inspecting tool a read-only mode.**
A tool whose default mode prepares or repairs will prepare or repair — running one "just to look" at a machine can
overwrite the very settings file you were inspecting. Print the plan, name what will be touched, and require a flag
to act. (`csm move --dry-run` prints the plan and every refusal, and `csm matrix` only reads.)

**Address terminal-multiplexer targets by exact match.**
tmux resolves a target name by prefix, so as soon as names share a prefix a command can attach to or kill the wrong
one — including a command you wrote into a runbook for someone else to paste. Use the `-t '=name'` form everywhere,
in printed commands too.

**Run one parity check across every home, make it exit non-zero, and let "unknown" be a verdict of its own.**
Divergence stays invisible until a session on one account behaves differently from the same session on another, so
compare the shared symlinks, enabled-versus-installed plugins, user-scope MCP servers, the memory location, the trust
and onboarding flags, the permission mode and the CLI version. A cell that could not be read is neither healthy nor
broken: print its age and the reason, because stale-green is the characteristic failure of a matrix of homes and it
is what makes people re-authenticate accounts that were fine all along. (`csm matrix` prints this for the homes on
the machine, and `csm matrix --check` exits 1 when a shareable layer has diverged or a login is gone.)

**Before renaming a config home, inventory everything that reads its path; afterwards, list the homes again.**
Supervisors, service definitions, shells, editors and live sessions all hold the old path, and a CLI killed mid-write
re-creates the directory it started with *after* the move looks finished. Finish a rename by grepping for the old
name rather than by listing directories, and merge any stray home back in before deleting it.

**Check the live state before building on documentation, including this page.**
Facts about an undocumented on-disk format are true of the version they were measured on; keys, dialog wording and
option order all change between releases. Pin version-sensitive behaviour to the version it was proven on, re-test it
after an upgrade, and re-verify every document that describes something you just changed.
