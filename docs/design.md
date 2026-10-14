# Claude Session Mover: design and implementation

Tue 13 Oct 2026 (week 42) · version 0.1.0 · code **[github.com/yaroslavvb/claude-session-mover](https://github.com/yaroslavvb/claude-session-mover)**
(MIT, one Python file, standard library only) · live copy of this page
[spacesheep.dev/@yaroslavvb/claude-session-mover-design](https://spacesheep.dev/@yaroslavvb/claude-session-mover-design).
Measurements are from Claude Code 2.1.296 on macOS.

One of your Claude accounts hits its usage limit while your other accounts have quota left. The usual answer is to
start the work again in another account, and lose the conversation. Claude Session Mover moves the conversation
instead: it copies the session's transcript into the other account's config home and resumes it there. The agent
still knows everything that was said, and every turn from then on spends the new account's quota. Nothing is
deleted from the old account.

## Contents {#contents}

- [Quick start](#quick-start)
- [The idea in one picture](#picture)
- [What a move does, step by step](#steps)
- [Accounts: discovered, named, never numbered](#accounts)
- [Picking a session](#picking)
- [What is on disk: the formats it reads](#formats)
- [Measured facts the design rests on](#measured)
- [Safety rules](#safety)
- [Limits](#limits)
- [From a phone](#phone)
- [Why move rather than pool](#why-move)
- [Lessons from the first version](#lessons)
- [Repository and tests](#layout)

## Quick start {#quick-start}

```
git clone https://github.com/yaroslavvb/claude-session-mover
cd claude-session-mover && ./install.sh          # links claude-session-mover and csm into ~/.local/bin

csm accounts                                      # the config homes found here, and who is signed in
csm list                                          # recent sessions across every account, newest first
csm move 3 --to work --dry-run                    # print the plan and any refusal, change nothing
csm move 3 --to work --stop-source                # move row 3 to the account named "work"
```

Requirements:

- Python 3.7 or newer
- Claude Code
- tmux, for the default Remote Control mode

Each account needs its own config home: a directory you point `CLAUDE_CONFIG_DIR` at and sign in once
(`CLAUDE_CONFIG_DIR=~/.claude-work claude`, then `/login`).

## The idea in one picture {#picture}

```
 account A (out of quota)                           account B (has quota)
 ~/.claude-a/                                       ~/.claude-b/
   projects/<folder>/<id>.jsonl   ── copy ──────▶     projects/<folder>/<id>.jsonl
   projects/<folder>/<id>/        ── copy ──────▶     projects/<folder>/<id>/
   .claude.json   (untouched)                         .claude.json  + trust <cwd>, onboarding done
   sessions/<pid>.json → live pid                     ▲
                                                      │ tmux window "moved-<id8>" in session "csm-b":
                                                      │ CLAUDE_CONFIG_DIR=~/.claude-b
                                                      │ claude --resume <id> --remote-control=<title>
                                                      ▼
                                       a NEW claude.ai session owned by account B:
                                       https://claude.ai/code/session_…
```

A Claude Code session on disk is one append-only JSONL file plus an optional sibling directory. The account is not
part of what makes it resumable. It is whichever login the process runs under. So a move is a copy and a resume;
everything else in the tool makes that copy safe and the resume unattended.

## What a move does, step by step {#steps}

1. **Find the session.** Scan every account home's `projects/*/*.jsonl` and the live registry `sessions/<pid>.json`.
   Each file costs two seeks: a 96 KB head and a 384 KB tail, never a full parse. Pick the one you named
   ([ladder below](#picking)).
2. **Refuse early.** Every check runs before the first byte is written, and each refusal names what to do instead.
   It refuses:
   - the same account as the source;
   - a target with no login, the wrong login, or the same login as the source;
   - a working directory that no longer exists;
   - a destination transcript that is live in the target;
   - an existing `moved-<id>` window.
3. **Copy.** The transcript goes to `<target home>/projects/<the source's own folder name>/`, with its sibling
   `<id>/` directory (subagents, tool results), and the project's `memory/` if the target has none. A quiet file
   already at the destination is backed up first. The source is never edited or deleted.
4. **Pre-answer the first-run dialogs** in the target's state file, additively, atomically, with a backup and the
   file's own mode:
   - the workspace-trust dialog for that directory (`projects[<cwd>].hasTrustDialogAccepted`);
   - onboarding (`hasCompletedOnboarding`, plus a `theme` if none is set).

   A home that has never run interactively in that directory stops on both, and in a detached window nobody is there
   to answer.
5. **Launch under the target login.** A detached tmux window `moved-<first 8 of id>` in session `csm-<account>` runs
   the tool's own `__run <plan.json>`. That sets the target's `CLAUDE_CONFIG_DIR`, or *unsets* it for the default
   home. It scrubs the environment ([below](#safety)), restores `PATH`, and runs:
   ```
   claude --remote-control=<title, moved from A> --permission-mode <the session's own mode>
          --model <its model> --resume <id>
   ```
   in the session's recorded working directory. The hand-off goes through a file because a tmux window starts with the
   tmux *server's* environment, whatever that was when it started. The interpreter and the script are spelled
   absolutely.
6. **Wait for proof.** The tool watches the pane (`capture-pane -J`, so a wrapped link is whole) for
   `https://claude.ai/code/session_…`, up to 150 s. It answers a stray first-run prompt by its option number, and stops
   waiting as soon as the window prints its exit banner.
7. **Optionally stop the source** (`--stop-source`). This happens only after the link has appeared, only if the
   registry's pid is still a `claude` process, and never when the source is the session running the tool.

Two more modes:

- `--no-remote-control` starts the window as a plain interactive session to `tmux attach` to; the proof is that it is
  still running after a few seconds.
- `--foreground` skips tmux and replaces the tool with the resumed session in your terminal. It is refused inside
  Claude Code, where there is no terminal to give it.

## Accounts: discovered, named, never numbered {#accounts}

An **account** here is a config home: the directory Claude Code keeps its login state, settings and transcripts in.

- **Discovery.** `~/.claude` is the account `default`, every `~/.claude-<name>` directory is the account `<name>`,
  and the home in `$CLAUDE_CONFIG_DIR` is added if it is elsewhere.
- **An accounts file** (`~/.config/claude-session-mover/accounts`, or `$CSM_ACCOUNTS`) replaces discovery entirely.
  It holds one `name  home  [expected-email]` per line, with `-` for the default home. With an expected email, a home
  signed in as anyone else is refused, because the move would spend the wrong quota.
- **Who is signed in** is read from the home's state file, `oauthAccount.emailAddress`. The tool never reads or
  copies a credential, and so never raises the macOS Keychain dialog that blocks unattended runs. Two homes signed in
  to the same login and organisation are the same account for quota purposes, so a move between them is refused.
- **The default home is special.** With `CLAUDE_CONFIG_DIR` unset, the CLI keeps its state file at `~/.claude.json`
  (outside the directory) and uses the bare `Claude Code-credentials` Keychain item. Setting
  `CLAUDE_CONFIG_DIR=~/.claude` is not the same account. The state file moves inside the directory, and the Keychain
  item becomes `Claude Code-credentials-<first 8 hex of sha256(path)>`, which is empty, so it reads as signed out.
  A move into `default` therefore **unsets** the variable rather than spelling the path.
- **Naming ladder** for `--to`, first unique match wins:
  1. exact name;
  2. exact email;
  3. unique prefix;
  4. unique substring.

  Anything ambiguous is refused with the candidates listed. **A bare number is refused** unless it is literally an
  account's name. A position in a list changes whenever an account is added or removed, so it cannot be trusted to
  mean the same account twice.

## Picking a session {#picking}

`SESSION` is tried against these, first unique win, and more than one match is listed, never guessed:

1. a row number from the last `csm list` on this machine (saved, so `move 3` means the row you just read; an
   all-digit argument is always a row number);
2. an exact local session id, then a unique prefix of one (4+ characters);
3. a `claude.ai/code/session_…` link, or a bare `cse_…` / `session_…` id;
4. a unique, case-insensitive piece of the title.

**A move is a copy, so after one move the same id exists in two accounts**, with the same title. When an id or title
matches several rows, the single live one wins; two live copies, or none, is a refusal that lists the row numbers.

## What is on disk: the formats it reads {#formats}

All of this is Claude Code's own undocumented on-disk state, read the way the CLI writes it in 2.1.x.

| What | Where | Used for |
|---|---|---|
| Transcript | `<home>/projects/<folder>/<id>.jsonl` | the session itself; copied |
| Sibling dir | `<home>/projects/<folder>/<id>/` | subagent transcripts, tool results; copied |
| Live registry | `<home>/sessions/<pid>.json`: `pid`, `sessionId`, `cwd`, `bridgeSessionId`, `tmux`, `name`, `status`, `entrypoint` | which sessions are running; the only map from a phone session to its transcript |
| State file | `<home>/.claude.json`, or `~/.claude.json` for the default home: `oauthAccount`, `projects[cwd]`, `hasCompletedOnboarding`, `theme` | who is signed in; the first-run dialogs |

Transcript lines it reads, by `type`:

- **Title.** `custom-title` (`customTitle`, a name you gave it), then `ai-title` (`aiTitle`), then `last-prompt`
  (`lastPrompt`), then the first real user message, in that order.
- **Link.** `bridge-session` (`bridgeSessionId: cse_X`, the last one wins): the claude.ai link is
  `https://claude.ai/code/session_X`.
- **Permission mode.** `permission-mode` lines (`permissionMode`), and the `permissionMode` field on user prompt lines.
  The later one wins.
- **Model and quota.** From `assistant` lines: `message.model` from the last clean line. An `apiError` of
  `usage_limit_reached`, with `apiErrorParams.rate_limit_info.{rateLimitType, resetsAt}`, is the out-of-quota flag.

A session is running when its registry file names a pid that answers `kill -0`. Dead processes leave their files
behind, so a file alone means nothing.

## Measured facts the design rests on {#measured}

- **A copied transcript resumes under another login.** `claude --resume <same id>` with another home's
  `CLAUDE_CONFIG_DIR` connects as that account and registers a new claude.ai session that account owns. The moved
  agent answered a question about its own first turn correctly. `--fork-session` is not needed, and the stale
  `bridge-session` line can stay: a new one is appended and the last one wins.
- **This tool, end to end, on a real pair of accounts (13 Oct 2026).** A one-turn session was moved with
  `--no-remote-control`. The window came up on the target's subscription, showed the earlier exchange, and kept the
  session's permission mode. Its process had the target's `CLAUDE_CONFIG_DIR` and none of the moving session's
  variables. The transcript landed under the source's folder name.
- **`--resume <id>` finds the file in any project folder of the home**, and it looks before it checks the login. With
  a dummy key, the transcript was found every time:
  - under the right folder;
  - under the folder of a symlinked path;
  - under an unrelated folder;
  - while recording a different cwd.

  An id that exists nowhere answered `No conversation found`.
- **The folder name is the launch path with every non-alphanumeric character turned into `-`**: `proj dir_x` became
  `proj-dir-x`, both in a throwaway home and under a real login. A rule that replaces only `/` and `.` is wrong for
  paths with spaces or underscores.
- **The folder and the recorded `cwd` can disagree.** A session started through a symlinked path can be filed under
  the symlink's spelling while it records the resolved path. In one real setup, 56 of 835 transcripts were like that.
  So the mover never recomputes the folder: it reuses the source's own folder name, and launches in the recorded `cwd`.
- **Two first-run dialogs stop a resumed session in a cold home**: workspace trust, then onboarding (theme picker and
  security notice). Both were hit on the first real move, and the tool pre-answers both.
  - **The trust dialog lists "Yes, I trust this folder" first.** A fallback that presses Down and Enter would choose
    "No", so stray prompts are answered by the option's number. A second sighting one poll later gets Enter, and a
    third gets nothing.
  - **"Enable Remote Control? (y/n)"** prints `Choose [1/2] (default: 1)`, so Enter accepts it.
  - **The bypass-permissions warning** offers "Yes, I accept" and "No, exit".
- **An error line names its model `<synthetic>`**, and the out-of-quota line is that kind of line, at the end of
  exactly the session you want to move. `claude --model '<synthetic>'` refuses to start. So a model is taken only from
  a clean assistant line, and only if it looks like a model id.
- **A desktop-app transcript records its permission mode on every prompt line, not in a `permission-mode` line.** A
  first prompt with a pasted screenshot can be bigger than the 96 KB head. If the tail has no mode either, the file is
  read backwards for the last one. A session that silently resumed in `default` mode would stop for a click on every
  tool call.
- **The new claude.ai thread starts at the move.** The resumed session carries `noHistoryBackfill`. The agent has the
  whole conversation, but the app does not re-render the earlier turns above your next message.

## Safety rules {#safety}

- **Nothing is written before every refusal has been checked.** A refused move leaves the target home untouched, and
  a dry run reports what a real move would refuse.
- **The source is never edited or deleted.** `--stop-source` sends SIGTERM to the one pid in the registry, after
  checking it is still a `claude` process (a registry file can outlive its process, and the pid can be reused). It
  does so only once the moved window has printed its link. A move that did not connect leaves the source running:
  two copies is bad, nothing running is worse.
- **It never stops itself.** "Move this session" is the main use from a phone: the agent inside the session runs the
  tool on its own session. The tool recognises itself by `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PID` and its process
  ancestry, marks that row `← this session`, and leaves it running. Stopping it would kill the turn that is about to
  tell you where the move went.
- **Two writers on one transcript is unrecoverable**, so a destination that is live in the target account is refused,
  and a quiet one is backed up before it is overwritten.
- **The environment is scrubbed**, for the moved session and for any tmux server the tool starts. Two kinds of
  variable go:
  - Variables that describe the session running the tool: `CLAUDECODE`, `CLAUDE_PID`, `CLAUDE_CODE_SESSION_*`,
    `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_BRIDGE_*`, `CLAUDE_CODE_MESSAGING_*` and their kin. Inherited, they make the
    new process believe it is nested in, or bridged through, the old one.
  - Tokens that outrank a home's own login: `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`.
    With one of those left in, the session would move but the quota would not.
- **Prompts are answered by number, and the dangerous one only when it was already accepted.** The bypass-permissions
  warning is accepted only for a session that was already running in that mode in the source account.
  `--permission-mode` overrides the mode.
- **tmux targets are exact** (`-t '=csm-work:=moved-1a2b3c4d'`): tmux matches prefixes otherwise. Window listings are
  split by line, because a window name can contain spaces.
- **The moved window outlives its process** and prints `=== claude exited rc=N`, so a failure keeps its evidence.
- **Credentials are never read, printed or copied.**

## Limits {#limits}

- **Same machine.** The move happens where the transcripts live; `--ssh HOST` runs the same command on another
  machine that has the tool installed.
- **A new session in the app**, with a new id and link, owned by the target account. The old link keeps pointing at
  the old copy.
- **The prompt cache starts cold**, so the first turn after a move is slower and costs more than a continuation.
- **The last line on disk only.** A reply still being written is not in the copy. When you move the session you are
  talking in, the message asking for the move does not travel.
- **"Signed in" is the last login the state file recorded, not a live credential.** A home whose credential was removed
  or has expired still reads as signed in, and the move then fails to connect (safely: the source keeps running).
- **A running process can rewrite the state file.** If something in the target home rewrites `.claude.json` right
  after the pre-answers, a dialog can come back; the number-keyed answer is the fallback.
- **The quota flag is a heuristic** read off transcripts, not the meter.
- **Undocumented formats.** Everything above is Claude Code's internal state and can change in any release; the tests
  pin the shapes the tool depends on.

## From a phone {#phone}

The repo ships a Claude Code skill, `move-session`. `./install.sh --skill` links it into every account home, since
each config home reads its own `skills/`. Then, in any session that still has quota (a Remote Control session on the
machine, for example), you say *"move my refactor session to work"* or *"I'm out of quota, move this session to
personal"*. The agent lists the candidates, asks one question if it is ambiguous, runs the move, and answers with the
account to open the app as and the new `claude.ai/code/session_…` link.

## Why move rather than pool {#why-move}

The other way to use several subscriptions is a proxy in front of them that rotates logins by remaining quota. A pool
answers as whichever login it picked, so nothing downstream can say which account paid for a turn, and it cannot move
a conversation that is already running. A pool on an unattended machine is also a terms-of-service risk. The mover
does something narrower: it hands a conversation to another of your own logins, and that login does its own talking,
on its own token, in its own app. One session, one account, in the log.

## Lessons from the first version {#lessons}

The mover was first built for one person's multi-account setup and reviewed in use. Each finding became a rule here:

| Finding | Rule now |
|---|---|
| `--stop-source` fired before the connect check, so a failed move left nothing running | stop only after the link has appeared |
| a copied id matched in two accounts, and the first match was a stale copy | the live copy wins; otherwise list and ask |
| the trust pre-answer and the copy ran before the last refusal | `preflight` first: nothing is written before every check passes |
| the out-of-quota line's `<synthetic>` model was passed to `--model` | a model only from a clean line, shaped like a model id |
| a desktop session moved as `default`: its mode was beyond the head window | modes from prompt lines too, then a backwards read |
| `--stop-source` from inside the session killed the turn reporting the move | recognise self, never stop it |
| `--remote-control=` names built from titles carried `/`, `:` and `@` | a cleaned label with the provenance kept whole |
| the folder name was recomputed from the cwd with a `/`-and-`.` rule | reuse the source's folder name |
| a fallback answered the trust dialog with Down and Enter | answer by the option's number |
| numbered accounts swapped numbers once | accounts are named, never numbered |

## Repository and tests {#layout}

| Path | What |
|---|---|
| `claude-session-mover` | the tool: one Python file, standard library only |
| `install.sh` | links `claude-session-mover` and `csm` into `~/.local/bin`; `--skill` links the skill into every account home |
| `skills/move-session/SKILL.md` | the Claude Code skill for the phone flow |
| `tests/test_mover.py` | 49 tests, fixtures only |
| `docs/design.md` | this page |

The tests run the real script against fake homes and transcripts, a fake `claude` that records its argv and
environment, and a fake `tmux` that really runs the moved window's command. They need no network and no account.
They pass on Python 3.7, 3.9 and 3.12 on macOS, and CI runs them on Linux and macOS.

State lives in `~/.local/state/claude-session-mover/` (`$XDG_STATE_HOME` is honoured): `log`, one line per list,
move, refusal and window start; `picks.json`, the numbering of the last `list`.

---

**Why it matters:** hitting a usage limit stops costing the conversation. The work keeps its memory and moves to an
account with quota in under a minute, from a phone, with nobody at the keyboard.
