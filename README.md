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
of its own transcript and says what brings it back: a resume in place, a fork onto a new link, a move to an
account with room, or the one thing to tap when only that session's own server can reopen it. Usually from
nothing but its claude.ai link ([the walkthrough](#restart-a-session-that-died)).

## Start here

New here? This part is the whole tool in five minutes. `csm` is one command you type in a terminal, on the
machine the session lives on. It copies, resumes and reports; it never edits or deletes a conversation. (No
terminal to hand? Install it with `./install.sh --skill` and ask any session on that machine that still has
quota — [From a phone](#from-a-phone).) Four jobs:

| you want to | the command |
|---|---|
| **continue a session on another of your accounts**, because the one it is on is out of quota | `csm move <session> --to <account>` |
| **bring back a session that stopped** — a machine restart killed it, Remote Control disconnected, something killed it mid-turn, it hit a usage limit (add `--to <account>` while that limit is still in force) | `csm revive <session>` |
| **find a session** in any of your accounts, on this machine or another | `csm find "<id, link or words>"` |
| **see what you have** — the accounts here, and their recent sessions | `csm accounts`, `csm list` |

Three more for afterwards: `csm stop` ends a session csm started and frees its window, `csm modes` says
which live sessions run in a weaker permission mode than this machine asks for — a worker a Remote Control
server spawned can come up weaker than your `settings.json` says — and `csm matrix` prints what your accounts
share and what they cannot. [Commands](#commands) has all of them in full.

**`--dry-run` on `move`, `revive` and `stop` prints the whole plan and changes nothing**: it copies, starts,
wakes, moves and signals nothing, and writes nothing but one line in csm's own log. It is the right first
command for anything you have not done before.

### Install

```sh
git clone https://github.com/yaroslavvb/claude-session-mover
cd claude-session-mover
./install.sh                  # links claude-session-mover and csm into ~/.local/bin
```

Python 3.7 or newer, standard library only — nothing to install with pip. Plus Claude Code itself, and
tmux for the default Remote Control mode (`--foreground` needs none). macOS and Linux. The links go in
`~/.local/bin` (`CSM_BIN_DIR` changes that), and `install.sh` prints `note: … is not on your PATH` when it is
not on yours — read the lines it prints. The two install variants, `--skill` (which is what lets you drive
csm by talking to a session from a phone) and `--no-short-name`, are in [Quick start](#quick-start) below.

**What csm needs to know about your accounts.** One *config home* per account — a directory
`CLAUDE_CONFIG_DIR` points at, holding one login — each signed in once:

```sh
CLAUDE_CONFIG_DIR=~/.claude-work claude      # then /login as that account
```

`~/.claude` is the account `default` (`CLAUDE_CONFIG_DIR` unset) and every `~/.claude-<name>` directory
is the account `<name>`, so that one line is enough to have two accounts csm can move a session between.
To name the accounts yourself, to pin which login each home must hold, or to share one list across
machines, write an accounts file — [`csm accounts`](#csm-accounts) has both dialects and every column.
Then look; neither of these touches a session or a config home (`csm list` only leaves its row numbering
behind, in csm's own state directory):

```sh
csm accounts        # the homes found here, and the email each one is signed in as
csm list            # recent sessions in every account, newest first
```

### What do I give csm?

`csm move`, `csm revive` and `csm stop` each take one `SESSION` argument, and six different things are
accepted there. Behind those six ways of naming a session there are **two ids** — the claude.ai one (rows 1–2
below) and the local one (rows 3–4); a row number and title words are not ids at all — and which one you are
holding is the difference between "it just works" and "no session matches". (`csm find` takes the same things
except a row number — it is the command for when you have only words.)

**"Remote Control" decides a lot of what follows, so once:** it is how a session on this machine is driven
from the Claude app or a phone, and it makes three kinds of session that the rest of this page keeps apart:

- a **server child**: a `claude remote-control` server serves a folder and starts sessions in it. This is the
  kind you are most likely to be rescuing, and the only one csm cannot put back on its own link.
- a **self-hosted** session: one that asked for Remote Control itself (`claude --remote-control=<title>`), so
  it hosts its own link.
- a **terminal** session: a plain `claude` in a terminal. It has no claude.ai link at all until csm gives it one.

You do not have to work out which one you have, and you cannot tell from the app: `csm revive … --dry-run`
proves it, says so on its `what it is` line, and picks the answer from it.

| what you give it | what it looks like | where you find it | when to use it |
|---|---|---|---|
| **a claude.ai link** — the recommended one | `https://claude.ai/code/session_01PHXskvoLtckdvqFv3F8rei` | **in the app**, on a phone or a desktop: it is the address of that session's page, and in a browser it is what the address bar shows. **In a terminal**: a session that asked for Remote Control itself prints it in the session — the banner the `/remote-control` command leaves (`… is active · Continue here, on your phone, or at https…`) — while `csm list --json` carries each session's `url`, and `csm move` prints the new one when a move finishes | **whenever the session has stopped.** For a Remote Control session csm *computes* the transcript's file name from the link, so it resolves with nothing running: no process, no registry row, no network, no guessing |
| **the bare claude.ai id** | `session_01PHXskvoLtckdvqFv3F8rei`, or the same id as `cse_01PHXskvoLtckdvqFv3F8rei` | it is the last segment of that link. Remote Control writes the very same id with a `cse_` prefix instead — that spelling is what you see in a running session's registry row and in a server's own command line, so if you have the link you already have this id | exactly the same thing as the link — **one id, two prefixes**, and csm accepts either. Useful when you have the id but not the url |
| **the local session id** — Claude Code's own | `bf974a77-c0b0-5763-81be-f057a3dc7e57`, or just `bf974a77` | it *is* the transcript's file name: `<config home>/projects/<folder>/<id>.jsonl`. `csm list` and `csm find` print its first 8 characters; `--json` on either carries the whole id | when you got it from `csm list` or `csm find`. **A prefix of 4 characters or more is enough**, as long as it matches exactly one session; anything ambiguous is listed, never guessed |
| **a spacesheep session page link** | `https://spacesheep.dev/sessions/claude-code/bf974a77-c0b0-5763-81be-f057a3dc7e57` | the address of that page, if you publish sessions to spacesheep.dev | the uuid in such a link *is* the local session id, so it names the transcript directly, with no arithmetic and nothing running |
| **a row number** | `3` | the `#` column of **the last `csm list` you ran on this machine** | the shortest thing to type, right after a `csm list`. It is remembered per machine, so it means nothing after a `csm list` somewhere else |
| **words from the title** | `"refactor"` | the `title` column of `csm list` or `csm find`, matched case-insensitively anywhere in it | a session you can see in a listing. It is the one form that can quietly miss — see below |

**"Is it the session ID?"** — there are two, and csm accepts both wherever a `SESSION` is asked for. The
**claude.ai id** (`session_…` / `cse_…`) is the one in the link and in the app. The **local session id** is a
uuid, and it is the name of the transcript file on this machine — what `csm list` and `csm find` print. For a
session a Remote Control server started, the second is *computed* from the first, which is the whole reason a
link alone can find a session that nothing is running. So they are interchangeable for a session you can see
in a listing — but **for one that has stopped, reach for the link first**, and if it answers `no transcript
for that link here`, hand it the local id (or a 4-character prefix) instead. A terminal session has no link
at all: for that one the local id from `csm list` *is* the answer.

Three cautions, each measured rather than assumed:

- **A link is an exact question and gets an exact answer.** csm will never fall back from a link to matching
  part of an id or part of a title — that would hand you somebody else's session. If the link's transcript is
  not in a config home on this machine, it says so and names what it looked in.
- **The arithmetic holds for a session a Remote Control *server* started**, which is the kind you are most
  likely to be rescuing: its local id *is* a hash of its claude.ai session's own API address, so the link finds
  the transcript with nothing running — no process, no network, no registry row (the live `sessions/<pid>.json`
  file a running session keeps, and a stopped one has none). For a session that asked for Remote Control
  itself, or a terminal session that got a link later, csm matches the claude.ai id recorded inside the
  transcript instead; that works too, but only while the session is recent enough to be in the listing csm
  scans — while a link's arithmetic, and a local id typed in full, name the file however old it is. If a link
  comes back as `no transcript for that link here`, give the local session id or a 4-character prefix of it,
  and use `csm find` to get it.
- **A title can miss.** csm matches the title in the transcript — one you set, one the CLI generated, or the
  last prompt — which is often not the words the app shows you. Measured across the transcripts on one
  machine, CLI 2.1.312: 11% of the transcripts a Remote Control server started carry a generated title line,
  against 64% of the others, so for those csm is matching a prompt rather than a title, and a stopped Remote
  Control session is exactly the case where that bites. `csm find` also reads the desktop app's own titles,
  which are in no transcript and which `csm list` does not see. When a title finds nothing, use the link or
  the id.

### Restart a session that died

The case this part is written for: a session stopped answering — the machine restarted under it, Remote
Control disconnected, something killed it mid-turn, or its account hit a usage limit.

**In a hurry.** With the session's claude.ai link, copied out of the app:

```sh
csm revive <link> --dry-run     # why it stopped, and what reviving it would do — nothing changes
csm revive <link>               # ...do that
```

With no link — a plain `claude` in a terminal has none — name it from a listing instead:

```sh
csm list                        # or: csm find "<words from the title>"
csm revive bf974a77 --dry-run   # the 8-character id in the `session` column, or that row's number
```

Read **line 2** of the answer: it names what csm will do, and for one kind of session what it deliberately
will **not** do — a worker a Remote Control *server* started, which only that server can put back on its own
link. If the server is still up, the cure is to open the link and say *continue*; if it died with the machine,
`csm revive <link> --new-link` is the one command that brings the conversation back with nobody tapping
anything, onto a new link. The steps below are the same thing unhurried.

**0. Try the cheap thing first.** If it was a Remote Control session and a `claude remote-control` server is
still running in its folder, open its link in the app and type *continue*: the server respawns the worker
itself, and you keep the link, the title, the account and its quota window. Nothing local can make that
happen. If it was a plain terminal session, the by-hand equivalent is `claude --resume <id>` in its own
folder — which leaves it with no claude.ai link, where a revive gives it one.

Neither helps when that server is gone (it died with the machine), when the account is out of quota — the
next turn dies on the same wall — or when you do not know why it stopped. Reach for `csm revive` when nobody
is at the keyboard, when the account has to change, or when what you actually need to know is whether its
last tool call ever ran. 🛑 And never hand-resume a **server child**: `claude --resume` registers a *new*
claude.ai session for it instead of re-attaching the old one, and `--resume=<url>` can replace the local
transcript with the server's copy ([What it cannot do](#what-it-cannot-do)).

**1. Name the session.** The link is the one spec that always resolves for a session that is no longer
running: open it in the Claude app, or in a browser, and copy the address —
`https://claude.ai/code/session_…`. With no link, run `csm list` (or `csm find "<words>"`) and take the
8-character id in the `session` column, or that row's number; any of the six forms in the table above will do.

**2. Ask what happened, and change nothing.** Run it from anywhere on that machine — the folder it would
come back in is read out of the transcript, not out of your shell.

```sh
csm revive https://claude.ai/code/session_01PHXskvoLtckdvqFv3F8rei --dry-run
```

The answer opens with three lines, and they are the whole answer — everything after them is for checking the
reasoning. This session is a worker a Remote Control server started, and that server is still up:

```
REVIVE  the refactor sweep   (work, bf974a77)
  1 stopped Tue 27 Oct 17:46 (19h ago): it answered and stopped: the last line is a clean
    assistant turn
  2 nothing is started: open https://claude.ai/code/session_01PHXskvoLtckdvqFv3F8rei and say
    continue — its server respawns it on open
  3 risk: a server child cannot be resumed onto its own link; the cure that does not need you
    is `--new-link`, which forks
```

(then a detail block: what kind of session it is and how that was proved, whether anything is running it,
the account and its quota, whether a server is up in that folder, the link, the folder, the permission
mode, the row it took — and the note it would send.)

Line **1** is why it stopped, read out of the transcript: `it answered and stopped` (a clean last turn — the
ordinary shape of a session killed while idle), `it was cut off mid-turn: its last tool call (<tool>) has no
recorded result, so what that call did is UNKNOWN` (a kill in the middle of work — read this one carefully),
`it hit a <kind> limit, which resets <time>` (with ` — that reset has passed` on the end when it has, which
is why a limit in line 1 does not always decide line 2), `it was archived or ended from the app`, or
`its last turn ended on <error>, which is not a limit`.

Line **2** is what a real run would do — one sentence per case, from the decide table
([in full](#what-it-decides-in-order)) — and it tells you which command you actually want:

| line 2 says | what it means | what to do |
|---|---|---|
| `nothing is started: open <link> and say continue — its server respawns it on open` | it was a worker a `claude remote-control` **server** started, and such a session cannot be resumed onto its own link by anything local — only its server can bring it back, and only when the link is opened | open the link and say *continue* |
| `nothing is started: its server is down, so opening <link> will not bring it back …` | the same kind of session, but no server runs in its folder now (a machine restart kills the server too), so the tap cannot work until one does | `csm revive <link> --new-link` forks it onto a new link with the same past, and needs nobody. (When csm could not tell whether a server is up, the first line's advice ends `if one runs in its folder (its server could not be read here …)`.) |
| `resume it in place, on the same claude.ai link` | it asked for Remote Control itself, so resuming it re-attaches that same link | `csm revive <link>` |
| `resume it in place — it gets a NEW claude.ai link` | it was a plain `claude` in a terminal. It never had a link, so the one it comes back on is new exposure, not a restoration | `csm revive <id>`. To bring it back with no link at all, resume it by hand: `claude --resume <id>` in its folder |
| `FORK it: a new session id, a new link, the same past` (or `FORK it onto a NEW claude.ai link: …`) | you passed `--new-link`, or it is a server child, which has no other way back | that is the plan; afterwards leave the old copy alone (step 4) |
| `nothing to do yet: the limit it stopped on is still in force` | starting it now would spend its first turn hitting the same wall | wait until the reset it prints and run it again, or move it: step 5. A reset that has already passed is reported in line 1 and decides nothing |
| `wake it — relay this note to the session that is already running` | it is not dead after all: something respawned it, or you opened the link | `csm revive <link>` delivers the note to it; or simply type in the app |
| `nothing to do: it is working right now` | it is in the middle of a turn | nothing. A message now would join that turn |
| `nothing to do: it was archived or ended from the app` | somebody, or a sweep, closed it on purpose | `csm revive <link> --unarchive` if you do mean to reopen it, which unarchives it |
| `nothing to do: <owner> owns this session` | a supervisor, a bot or a scheduled pass keeps this session | that program's own command, which the refusal names |

Line **3** is the one risk, worst first, and it outranks the mechanism: an unanswered tool call, an archive
somebody made on purpose, or agents a frozen workflow run lost each change what you should do next.

**3. Do it.** The same command without `--dry-run`:

```sh
csm revive https://claude.ai/code/session_01PHXskvoLtckdvqFv3F8rei
```

The plan and the run take the same row, so what the dry run printed is what happens.

**4. Read what you get back, and mind the old link.** The revive note is never typed as you and never
written into a transcript: the session comes up idle, and the note is then delivered to it as a *peer*
message, from a sender named `csm revive (<machine>)`, saying what moved under it, asking it to carry on where
it stopped and to re-check anything time-sensitive first. `--say "<one line>"` adds a sentence of your own,
quoted verbatim and attributed to you — `--say "skip the card run, just write the findings up"` is how you
redirect it. (A `--to` revive is a move as well, and a move does append its own hidden note to the **copy**:
step 5.) Then:

- **Resumed in place** (`✅ revived, and it has taken a turn`): the `link` line is the same link you gave it,
  and a `window` line names the tmux window it runs in and prints the `csm stop …` that ends it. To look in:
  `tmux attach -t '=csm-<account>'` — that `window` line names the exact tmux session and window.
- **Resumed with a new link**: the output says so loudly —
  `⚠ new link    it was never a Remote Control session, so this link is new exposure, not a restoration`.
  Use the new one; nothing opens the way in it had before.
- **Forked** (`--new-link`, or a dead Remote Control server child): you get a **new** session id and a **new**
  link, with the whole past. A `new session` line carries that id, the `window` line prints
  `csm stop <the NEW id8>`, and the old way in is called out: `🛑 OLD LINK  <url> still opens the OLD copy,
  which is now a second conversation with the same past. Do not type there; archive it in the app.` Do exactly
  that (claude.ai in a browser archives it too): two conversations with one history is the one mess csm cannot
  untangle for you. A forked **terminal** session has no old link to archive — the output says so, and its old
  transcript simply sits on disk with nothing running it.
- **Nothing started** (the server-child case): it prints the link to open, whether that folder's server is up,
  and the two commands that follow — `csm revive <id>` once it is open, which relays the note into the session
  the server respawned (typing in the app does the rest), or `csm revive <id> --new-link` to fork.
- **`⚠ it is up, and NOT proved (exit 1)`**: something is running, but nothing proved it read the note. That
  line names the link to open and say *continue* on.

**Exit codes, for a script:** `0` it took a turn — or there was nothing to do, or the one thing to tap was
printed; `1` something is up and nothing proved it read the note; `2` a refusal, and nothing was started.

**5. If the account is out of quota, bring it back on another one.** Same command, plus where to put it:

```sh
csm revive <link> --to personal     # that account
csm revive <link> --to auto         # the account here with the most weekly room
```

This is an ordinary `csm move` with the revive note delivered afterwards, so it costs what a move costs
([What a move costs](#what-a-move-costs-and-what-it-cannot-carry)): a new link owned by the target account,
and across two organizations the first turn re-reads the whole conversation on the new account's quota.
`--to auto` needs a quota meter — `CSM_METERS`, which nothing in csm writes; a job of your own fills it — and
with none it refuses rather than guess and names the knob, so on a plain install name the account yourself.
`--to` is also the cure for a limit that is still in force.

**6. Clean up when you are done.** A revive that started a window leaves it running:

```sh
csm stop bf974a77            # ends it and frees the window (for a fork: the NEW id)
```

A revive opens its window under the same name a move does — `moved-<id8>` in the tmux session `csm-<account>`
— which is exactly what `csm stop` is authorised on, and the success output prints the command to use. It ends
only a session csm itself started, captures the pane's scrollback first, and never deletes a transcript: the
conversation stays where it is, and can be revived again.

### Move a session to another account

For a session that is **still running** and whose account is out of quota:

```sh
csm list                           # find it; note its row number
csm move 3 --to work --dry-run     # the plan, the cost, and any refusal
csm move 3 --to work               # do it
csm stop 3                         # later: end it and free its window — a row number means the
                                   #   last `csm list` on this machine, so its 8-character id is
                                   #   the safer argument once you have run another listing
```

It prints the account to open the app as, the **new** claude.ai link, the window it runs in and what the move
cost. The old link still opens the old account's copy; nothing is deleted. `--to auto` picks the account with
the most room when a quota meter is configured. The session is found on another machine instead with
`csm move <id> --from-machine laptop --to work` ([`csm move`](#csm-move) has every flag).

### Find a session

```sh
csm find "refactor"             # every config home on this machine, the desktop app's included
csm find 7f3a --on laptop       # ...on another machine, over ssh, read-only
```

It searches ids, links and titles in every account home. Two things it will tell you itself: the age column
is the transcript file's last write and not its last turn, and **0 rows is not proof the session is gone** —
a stopped session has no registry row and a Remote Control one usually has no title, so paste its link, which
names the transcript by arithmetic. A session that never had a link (a terminal one) has none to paste: widen
the window with `--all`, or read the file names in `<config home>/projects/<folder>/`, which *are* the local
session ids.

### What csm will not do

Each of these is a refusal with the cure in it, not a surprise:

- **It cannot make a Remote Control server respawn a dead child.** Only activity on that claude.ai session
  does it — opening the link — and that is the server's decision, so csm prints the one thing to tap and
  starts nothing. `--new-link` is the way back that needs nothing of yours.
- **It cannot wait out a usage limit.** A limit still in force is a refusal carrying the reset time and the
  two cures (wait, or `--to <account>`): `csm revive` never sleeps, and it signals nothing.
- **It cannot revive a session that is on another machine.** A transcript lives in a config home, and every
  gate a revive turns on is a question about the machine the session is on: run `csm --machine laptop revive
  <spec>` and the whole thing happens over there. (A *move* does cross machines: `--from-machine`.)
- **It cannot choose between two copies of one id.** A move is a copy, so after any move the same id sits in
  two homes; with neither running, it refuses and names both. `csm revive --account <name>` says which one;
  `csm move`'s spelling for it is `--from-account`, and `csm stop` needs neither — it looks only at the copy
  whose window csm itself opened.
- **It cannot tell you whether an interrupted tool call took effect** — only that there is no recorded result,
  which is also what it tells the revived session.
- **It cannot attach a claude.ai connector to another account.** No terminal command on any machine can; you
  enable the same set per account in a browser. A moved session sees the target account's connectors.
- **It never copies a login, and never copies memory.** It checks only that a credential exists, and sharing a
  memory store is a setup step ([Making your accounts fungible](#making-your-accounts-fungible)) — copying one
  is how stores fork.
- **A session another program owns is handed back, not moved**, and a session archived or ended from the app
  needs `--unarchive` said out loud.

### Where to read more

Everything below this part is reference. Where to go:

| if you want | read |
|---|---|
| every command and every flag | [Commands](#commands) |
| what a move does, step by step | [What a move does](#what-a-move-does) |
| what a move costs and what it cannot carry | [What a move costs, and what it cannot carry](#what-a-move-costs-and-what-it-cannot-carry) |
| the revive decide table in full, and how the note is delivered | [Revive a dead session](#revive-a-dead-session) |
| continuing stopped sessions with nobody at the keyboard | [Waking stopped sessions automatically](#waking-stopped-sessions-automatically) · `csm stalled` |
| what is shared between accounts, and what can never be | [The fungibility matrix](#the-fungibility-matrix) · `csm matrix` |
| how to make your accounts interchangeable | [Making your accounts fungible](#making-your-accounts-fungible) · [docs/setup.md](docs/setup.md) |
| every environment knob | [Environment](#environment) |
| the rules that cost the most to learn | [Lessons](#lessons) · [LESSONS.md](LESSONS.md) |
| driving csm by talking to a session from a phone | [From a phone](#from-a-phone) |
| the rules in the code that keep it safe | [Safety](#safety) |
| short answers to the usual questions | [FAQ](#faq) |
| running it from a wrapper of your own | [Running it from a wrapper](#wrapper) |

Behind the tool is one idea: **an account is a payment layer — a login and a quota. Everything that should follow
you lives outside the account's config home and is shared.** Instructions, skills, plugins, hooks, memory and
permission defaults have no business living inside any one account's home. Move them out and switching accounts
stops being a migration; what is left is a short list of things that genuinely cannot be shared, and that list is
worth knowing by heart. It is the matrix below — and `csm matrix` prints the same table measured against your own
machine.

## The fungibility matrix

Reference, and the part of it you have to know is in [What csm will not do](#what-csm-will-not-do) above — skip
this table on a first read and come back when you are setting a second account up.

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

The footer counts only the ten layers `--check` decides on — the seven shared entries (`settings.json`,
`CLAUDE.md`, `skills`, `agents`, `commands`, `output-styles`, `plugins`) plus `plugins enabled`,
`MCP servers` and `auto-memory` — and not every 🔧 row in the table: `login` is reported on its own, and
`settings.local.json` and `scheduled-tasks` never fail it, because having one and not the other is usually
the design.

Every cell is a measurement, never a guess. `?` is not the same as `no` and is never counted as a match, so
`--check` goes red on a layer that diverges or a login that is gone, and never on an unknown.

## Quick start

The install itself, and the account homes it needs, are in [Start here](#install) above. `./install.sh` takes
two variants:

```sh
./install.sh --skill          # ...and the move-session skill into every account home (for phones)
./install.sh --no-short-name  # ...the long name only, when something else owns `csm` here
```

`--no-short-name` is for a machine where `csm` is already a wrapper of your own that sets this tool's environment
and `exec`s it — see [Running it from a wrapper](#wrapper). A link installed over it would hand you the bare tool
with none of its inputs.

Every command, in the order you meet them:

```sh
csm accounts                        # the homes found here, and who each is signed in as
csm matrix                          # what they share, and what they cannot
csm list                            # recent sessions in every account, newest first
csm move 3 --to work --dry-run      # the plan, and any refusal; nothing changes
csm move 3 --to work                # row 3 of the last list -> the account "work"
csm revive https://claude.ai/code/session_01Ab... --dry-run   # it stopped: why, and what now
csm stalled                         # which stopped sessions are ready to continue, and why
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

`SESSION` is any of the six forms in [What do I give csm?](#what-do-i-give-csm) — one list for `move`, `revive` and
`stop`, which share the resolver (`find` takes the same ones bar a row number). `--to` takes an account's name, its
handle, its email, or a unique prefix of any of those. Anything ambiguous is refused with the candidates listed,
never guessed, and so is a bare number unless an account is literally named that.

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
| `--dry-run` | print the plan — the row it would take, the note it would send, any refusal — and start, wake, move and write nothing, bar the one line in csm's own log every command writes (`revive.jsonl` records real runs only) |
| `--json` | the diagnosis record, the decision and the note, as JSON. The prose goes to stderr, so stdout stays parseable |
| `--to ACCOUNT` | move it to that account instead of reviving it where it is (`auto` for the one with the most weekly room). It is also the cure for a limit that is still in force |
| `--new-link` | a fresh copy on a new link: **fork** the dead session to a new session id and a new link, leaving its transcript byte-identical. It is the only way back for a Remote Control **server child**, which cannot be resumed onto its own link at all, and on a dead self-hosted or terminal session it forks instead of resuming in place (row 11). The old link, where there was one, still opens the old copy. On a row that forks nothing — live, a move, a refusal — the output says it was **not** carried out, and why |
| `--account NAME` | which home's copy to revive. Only needed when a move has left copies of one id in more than one home and none of them is running — revive refuses rather than choose, as `move` and `stop` do. Their spellings differ: `move --from-account NAME`, and `stop` needs none, because it looks only at the copy whose window csm opened |
| `--say TEXT` | one thing to pass on to the revived session, quoted verbatim and attributed to you. At most 400 characters, and it may not start with `!` or `/`, which the CLI would run as a command |
| `--permission-mode MODE` | the mode to come back in. Without it, the mode the session recorded, by the same rule as `move`. ⚠️ It is applied only on the rows that START a process (6, 7, 8, 10, 11); on a wake, on row 3, on row 9 and on a refusal nothing is started, so the mode line REPORTS what the session is already in (`unchanged: …`, `applied: false` in `--json`) and the flag is named as not carried out |
| `--unarchive` | resume a session that was archived or ended from the app, which unarchives it. Refused without this flag |
| `--name NAME` | the Remote Control name the revived session gets |
| `--auto` | **unattended**: nobody typed this run and nobody is reading its output. The note says so instead of saying you asked for it, and no row ends in a sentence for a person to act on — a dead server child is **forked**, and `--json`'s result then names the **old** bridge id to archive. Every refusal and every exit code is unchanged. See [Waking stopped sessions automatically](#waking-stopped-sessions-automatically) |
| `--from-machine M` | refused, and says so: every gate a revive turns on is a question about the machine the transcript is on. Run `csm --machine M revive <spec>` instead, which does the whole thing over there |

There is no `--foreground` and no `--no-remote-control` here: whatever row it takes, a revive comes up as a
Remote Control session, which is what gives a terminal session a link it never had. To bring one back without
a link, resume it by hand — `claude --resume <id>` in its folder, which is the by-hand path for a terminal or
self-hosted session and comes back with no link at all. Never for a server child: see
[What it cannot do](#what-it-cannot-do).

**Exit codes are the answer an unattended caller reads**: `0` the session took a turn (or there was nothing to
do, or the one thing to tap was printed), `1` something is **up** and nothing proved it read the note, `2`
nothing was started at all — every refusal, and nothing started.

### `csm stalled`

```sh
csm stalled                         # the table: what stopped, what is ready, what was already done
csm stalled --since 96 --json       # ...the rows a scheduled caller reads
csm stalled --check                 # ...one line: exit 1 when a wake failed
```

Every session in every config home here whose transcript was written inside the window, why each stopped,
whether it is **due** for a wake, what `csm revive --auto` would do about it, and whether that has already been
done. **It acts on nothing**: no window, no relay, no signal, no write outside csm's own log. What acts is
`csm revive <session> --auto`, one session at a time, so the decide table's refusals are asked once per wake and
not once per sweep. The rules are in [Waking stopped sessions automatically](#waking-stopped-sessions-automatically).

| flag | effect |
|---|---|
| `--since HOURS` | how far back to look, by a transcript's own last write (default 48). A transcript older than that is not even scanned |
| `--json` | the whole sweep: the rows (**due first, then oldest stop first** — the order a caller wakes them in), `due` with its reason, `row`/`action`/`what` from the decide table, `handled`, and a `coverage` block naming everything that could not be read. This is the contract a scheduled caller reads |
| `--check` | one line and an exit code: `0` (`ok:`), `1` (`FAULT:` — a due session whose last wake failed) or `3` (`INCOMPLETE:` — nothing failed, but something could not be read). A session merely **being** due is not a fault: that is the normal state between two passes. Nothing else is written, on either stream, and **no credential store is asked** |

### `csm stop`

```sh
csm stop SESSION [--dry-run]
```

Ends a session **this tool started** — one it moved, and one `csm revive` resumed or forked, which opens its
window under the same name — and removes that tmux window: the cleanup, and the unblocker for moving
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
  one, never a pid whose recorded start time does not prove it. 🛑 It stays a plan today: `--apply`, the flag that
  would carry it out, is **gated shut** while the mode a respawned worker comes back in is unverified — it refuses
  and signals nothing (exit 2). **No environment variable can open that gate** — a constant in the file is the only
  switch, because a stray variable in a scheduled pass's environment must never be able to stop your sessions.

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
| `CSM_REVIVE_LOG` | one JSON record per revive, 0600 (default `<state dir>/revive.jsonl`): what was decided, what ran, what was proved, and the at-most-once key `stop_uuid` — and never the note, which is conversation text. `csm stalled` reads this file back to fill `handled`, so a pass that wakes sessions must point it somewhere that survives (not `/tmp`) |
| `CSM_LSOF` | how `lsof` is invoked. Only `revive` asks it, and only for the one question that is in no process's argv: which folder a Remote Control server is serving |

**Waking stopped sessions automatically** (`csm stalled`, `csm revive --auto`)

| variable | effect |
|---|---|
| `CSM_WAKE_MARGIN_S` | how long after a limit's own reset a wake may be sent (default 120). A wake sent early is **consumed**, not queued, so the margin is for the clock: the `resetsAt` a transcript recorded and this machine's clock are two readings |
| `CSM_WAKE_MAX_AGE_H` | how old a mid-turn kill may be and still be due (default 24). The case it covers is a restart under a working session, which is answered within the day or not at all; an older one is still listed, with its age as the reason it is not due |
| `CSM_STALLED_SINCE_H` | how far back `csm stalled` looks, by a transcript's own last write, in hours (default 48). `--since` overrides it |
| `CSM_STALLED_PREFILTER` | the cheap prefilter's window (default 64 KiB) — deliberately far smaller than `CSM_REVIVE_TAIL`, because the question asked of every transcript is whether the **last** thing that happened there is a stop a wake covers, and that line is at the end of the file. A window that held no main-chain line is *inconclusive*, not empty, so a smaller value costs reads and never a missed session |

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

**When to use it, and when to just open the session and say *continue*.** The short version is
[step 0](#restart-a-session-that-died) of the walkthrough; the mechanism is this. A respawn is the server's own
decision, taken when the session next gets activity, so nothing local can make it happen: `revive` detects
exactly that case, prints the one thing to tap, and starts nothing (row 9). Reach for `revive` instead when
**nobody is at the keyboard**, when you **do not know why it stopped**, when the account it was on **has no
quota left** (`--to auto` moves it to the one that does), or when the thing you actually need to know is
whether its **last tool call ever ran**.

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
would do · the one risk**. Here for `csm revive <link> --new-link --dry-run` on a dead server child whose
limit has since reset — so row 4 does not fire, and line 1 says as much:

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
conversation. So **the revive note goes into no transcript at all** (a `--to` revive is also a `csm move`, and a
move appends its own `isMeta` move note to the copy it made), and the note opens with its own stamp,
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
  names both — `move` and `stop` refuse there too. `revive --account NAME` is the answer; `move`'s spelling is
  `--from-account NAME`, and `stop` considers only the copy whose window csm opened.
- **It cannot address a session whose registry name is not unique.** SendMessage addresses a session *by* its
  name, so two proved live sessions of one name is a refusal before anything is sent, naming both. csm's own
  label carries the session's id8 so that the windows it starts cannot collide.
- **It does not keep the note out of every file on disk — only out of its own.** `revive.jsonl` and the log hold
  no note text, by design. But the relay is a `claude -p` run, and the CLI files that run's own transcript under
  the project folder of its cwd — inside the revived session's config home. csm runs the relay in a directory of
  its own so that transcript lands beside no session's, and keeps that folder out of every listing, but the note
  is in a file the CLI wrote, in that home.

## Waking stopped sessions automatically

`csm revive <id>` is one session, named by a person. Two more pieces make the same thing run with nobody at the
keyboard: **`csm stalled`**, which says which sessions are ready, and **`csm revive <id> --auto`**, which
continues one of them honestly. Neither is a loop, and this tool does not install one: a scheduled pass of your
own runs `csm stalled --json`, takes the due rows, and runs one `csm revive --auto` per row.

```sh
csm stalled --json                              # which sessions are ready, and what each needs
csm revive <id> --auto                          # continue one, as an unattended caller
csm stalled --check                             # as a health check: exit 1 when a wake failed
```

### What is due, and what is not

**Due is exactly two stops**, read out of the transcript itself:

| it stopped on | due when |
|---|---|
| a **usage limit** of a class a reset clears — `session`, `weekly` | that limit's own `resetsAt` plus `CSM_WAKE_MARGIN_S` (120 s) has passed |
| being **killed while working** — an unanswered tool call or prompt | its process is gone *and* the stop is newer than `CSM_WAKE_MAX_AGE_H` (24 h). This is the machine-restart case |

A `monthly-spend`, `credits` or `model` limit is **never** due: waiting does not clear it, and a session woken
into one spends its first turn hitting the same wall. Nor is a limit whose class its own words did not name —
an unread class is not a clearable one. A clean finish is not due either (it answered, and there is nothing to
continue), and nor is an API error, which time does not fix.

**And five things are never due, whatever their stop**: a session that is **working** right now (a message would
join the turn it is in the middle of); one a **bot** owns (a relay into a bot's session surfaces as a message in
the channel that bot answers); one a **scheduled pass** owns that is not live and idle (its own supervisor puts
that one back); one with **no conversation** in it (a Remote Control server pre-creates those by the hundred);
and one **archived or ended from the app**, which was somebody's decision and not a failure to repair. Every row
`csm stalled` prints carries its reason in `why`, so "not due" is never a silence.

### What each state gets

Whatever the state, the action is a single `csm revive <id> --auto`, which takes the same decide table as any
other revive:

| the session is | `--auto` does |
|---|---|
| **live and idle** — a lazy respawn, or a pass parked on a limit | **wakes it** (row 5): the note is relayed in, nothing is started, the link is unchanged |
| **dead**, self-hosted or terminal | **resumes it in place** (rows 7 and 8), then relays the note. A terminal session gets a new link and is told so |
| **dead**, a Remote Control **server child** | **forks it** (row 10) — see the next section |
| out of quota with the limit **still in force** | **refused** (row 4), with the reset time. A wake sent early is *consumed*, not queued |
| owned by a bot, or by a dead scheduled pass | **refused** (row 1), naming that owner's own command |

An **`CSM_RC_JOBS_DIR`-owned session that is live and idle may be woken**, and that is the one narrowing of the
owner refusal. A wake starts nothing — it relays a message into the process that is already running — so there is
no second copy of the pass to make, which is the whole thing that refusal guards. A **dead** pass is still its
supervisor's, because reviving that one does start a process. A **bot** is refused whatever its state.

### A server child is forked, and the old session must be archived

A dead server child has no unattended way back onto its own link: only its own server respawns it, and only on
activity that cannot be given from here. So `--auto` takes the fork row instead of printing row 9's tap — and a
fork leaves **two conversations with one history**. The only thing that stops the old link respawning a second
actor is **archiving that old claude.ai session**, which csm deliberately cannot do: it reads no credential, and
archiving is an authenticated call to claude.ai. So it reports the id instead, in `--json`'s `result`:

```json
{ "new_id": "9c1f…", "old_bridge_id": "01PHXsk…", "old_url": "https://claude.ai/code/session_01PHXsk…",
  "archive_old": true }
```

`old_bridge_id` is the bare id; the API spells it `cse_<id>`. **A caller that forks and does not archive has made
two actors with one past**, and should say so loudly rather than quietly: that is worse than not waking the
session at all.

### At most once per stop

The key is **`(local id, stop event uuid)`** — the uuid of the transcript line the stop was read from. Every
record in `CSM_REVIVE_LOG` carries it as `stop_uuid`, and `csm stalled` reads the log back to fill `handled`.
The id alone could only answer "was this session ever revived"; a session that stopped, was woken, worked for an
hour and stopped again is a **new** stop and is due again, which is exactly what a key per stop gets you.

A stop counts as handled only on a record with **exit 0**. A non-zero exit is a wake that was *attempted and
failed* — nothing was delivered, the session is still sitting there — so the row stays **due**, the attempt is
counted in `handled.failed`, and `csm stalled --check` turns that into its one `FAULT:` line. Being due is not a
fault; a wake that failed is. Where a stop line carries no uuid (an older build's transcript, or a verdict read
off the file's mtime because no line carried a stamp), the readers fall back to `(local id, transcript size)`
rather than matching on the id alone.

### Running it as a scheduled pass

The shape that works, and the two things to get right:

- **Cap what one pass may do.** Take the due rows in the order `--json` gives them (due first, oldest stop
  first) and wake a handful per run, not all of them: a sweep that wakes thirty sessions at once spends thirty
  first turns on one account's quota.
- **Hold a lock, and let the run finish inside the interval.** One `csm revive` is bounded by its own waits
  (`CSM_CONNECT_WAIT`, `CSM_RELAY_TIMEOUT_S`, `CSM_REVIVE_PROVE_S`) and can take minutes; two passes overlapping
  would each diagnose the same dead transcript. `revive` holds its own per-session claim, but the pass should
  hold one of its own so the next tick skips rather than piles up.

`csm stalled --check` is the health check to put beside it: `ok:` while nothing has failed, `FAULT:` for a due
session whose last wake failed, `INCOMPLETE:` when something could not be read. It never asks a credential
store, prints exactly one line on stdout and nothing on stderr, so a scheduled reader can match the prefix.
⚠️ Because it asks no credential store, its **count** of due sessions can be one or two higher than `--json`'s:
a home whose login is gone is a refusal `--json` sees and `--check` does not, so a session there reads as due in
the one-line form and *not* due in the document the caller acts on. The count in that line is a reading, not a
work queue; `--json` is the queue. It never turns that into a fault.

## Safety

Every one of these is a rule in the code, and the tests pin them:

- **The source transcript is never edited or deleted.** A move is a copy and a resume. (One layout is the
  exception, and says so where it is described: two homes whose `projects/` resolve to **one** tree, where the
  copy *is* the source, and the move note is appended to that one file because it is the only place the resumed
  session could read it.)
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
  on the old account. A directory that cannot be read is a refusal too, never a "no". A `CSM_RC_JOBS_DIR`-owned
  session has one narrow exception, and only for a **wake**: one that is live and idle may be sent the note,
  because a relay starts no second copy of the pass. A dead one, and a bot in any state, stay refused.
- **A stopped session is never woken before its limit resets, and never twice for one stop.** The reset plus
  `CSM_WAKE_MARGIN_S` is the gate on the first, and the at-most-once key `(local id, stop event uuid)` in
  `CSM_REVIVE_LOG` is the gate on the second. A wake sent early is consumed, not queued.
- **`csm stalled` acts on nothing.** It is a read: no window, no relay, no signal, no write outside csm's own log.
  Every wake goes through `csm revive --auto`, one session at a time, so each one meets the whole decide table.
- **An unattended revive never claims you asked for it.** `--auto` replaces the note's request sentence with the
  fact — nobody has sent a message since the stop, and this installation continues stopped sessions
  automatically — because the receiving session decides what to do next on the strength of that sentence.
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

🛑 This needs one session on that machine that is still alive and still has quota, because that is what you are
typing into. When a restart killed everything there, nothing on a phone can start the first one: run csm on that
machine itself, or from another machine's terminal with `csm --machine <name> revive <link>`.

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
  rather than quietly. Re-check anything load-bearing against the version you actually run — `claude --version`
  says which that is, and `csm matrix` prints it per machine.
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

**Can I revive a session that died before I installed csm?**
Yes. Everything `revive` reads is already on disk — the transcript in its config home, and the live registry if
anything is still running — so when the session stopped relative to the install makes no difference. What it
cannot read is a session whose transcript was pruned (`cleanupPeriodDays`) or that lives on another machine.

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

745 tests, fixtures only: fake homes and transcripts, a fake `claude` that records its argv and environment, a fake
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
