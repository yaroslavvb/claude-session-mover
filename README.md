# Claude Session Mover

Move a running [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) session to another of your own
Claude accounts, without losing the conversation.

One account hits its usage limit while your other accounts have quota left. Normally you would start the work again
in another account and lose the conversation. `csm` moves the conversation instead. It copies the session's transcript
into the other account's config home, pre-answers that home's first-run dialogs, and resumes the session there under
the other login. By default the moved session has Remote Control on, so it is reachable from claude.ai and the mobile
app. The agent remembers everything that was said, and every turn from then on is spent on the other account. Nothing
is deleted from the old one.

**Design notes:** [docs/design.md](docs/design.md) covers the mechanism, the on-disk formats it reads, the measured
facts it rests on, and every safety rule.

## Install

Requirements:

- Python 3.7 or newer (standard library only)
- Claude Code
- tmux, for the default Remote Control mode

macOS and Linux.

```sh
git clone https://github.com/yaroslavvb/claude-session-mover
cd claude-session-mover
./install.sh            # links claude-session-mover and csm into ~/.local/bin
./install.sh --skill    # ...and the move-session skill into every account home (for phones)
```

Each account needs its own config home: a directory that `CLAUDE_CONFIG_DIR` points at, signed in once.

```sh
CLAUDE_CONFIG_DIR=~/.claude-work claude      # then /login as your work account
```

`~/.claude` is the account `default` (`CLAUDE_CONFIG_DIR` unset), and each `~/.claude-<name>` is the account
`<name>`. To name accounts yourself, or to say which login each home must hold, write an accounts file. See
`csm accounts --help`.

## Use

```sh
csm accounts                        # the homes found here, who each is signed in as, live sessions
csm list                            # recent sessions in every account, newest first
csm list --account work --json
csm move 3 --to personal --dry-run  # the plan, and any refusal; nothing changes
csm move 3 --to personal            # row 3 of the last list -> the account "personal"
csm move 3 --to personal --stop-source
```

`list` marks running sessions `● live` and the session you are typing in `← this session`. A session whose last
turn hit a usage limit is marked `⚠ OUT OF QUOTA (5h|week, resets HH:MM)`.

`SESSION` in `move` can be:

- a row number from the last `csm list`
- a session id, or a prefix of one (4 or more characters)
- a `https://claude.ai/code/session_…` link
- a piece of the title

`--to` takes an account's name, its email, or a unique prefix of either. Anything ambiguous is refused, never
guessed, and so is a bare number (unless an account is literally named `2`).

| flag | effect |
|---|---|
| `--dry-run` | print the plan and any refusal; copy, write and start nothing |
| `--stop-source` | once the moved session has printed its claude.ai link, stop the old process |
| `--no-remote-control` | start a plain interactive session in tmux (`tmux attach -t '=csm-<account>'`) |
| `--foreground` | resume in this terminal instead of tmux |
| `--permission-mode M` | override the mode read from the transcript |
| `--name LABEL` | the Remote Control name of the moved session |
| `--ssh HOST` | run the same command on another machine where csm is installed |

A successful move prints the account to open the app as, and the new `https://claude.ai/code/session_…` link.

## How a move works

1. **Find.** Scan every account home's transcripts (a head and a tail of each file, never a full parse) and its live
   registry, `sessions/<pid>.json`.
2. **Refuse early.** Every check runs before the first byte is written, and each refusal says what to do instead.
   Refused are a move to the same account, a target that is signed out or signed in to the same login, a working
   directory that is gone, a destination copy that is running, and an existing window.
3. **Copy.** The transcript and its sibling directory go into the target home, under the source's own project
   folder name. The project's `memory/` goes too, if the target has none.
4. **Pre-answer.** The target's workspace-trust dialog for that directory and its onboarding are answered in its
   state file: additively, atomically, with a backup, keeping the file's mode.
5. **Resume.** `claude --resume <id> --remote-control=<title> --permission-mode <its mode> --model <its model>` runs
   in a detached tmux window `moved-<id8>` of session `csm-<account>`, under the target's `CLAUDE_CONFIG_DIR`. Its
   environment is scrubbed of the old session's variables and of any token that would outrank the target's login.
6. **Prove.** Wait for the claude.ai link in the pane, then, with `--stop-source`, stop the old process.

## Safety

- The source transcript is never edited or deleted. `--stop-source` stops one pid, the one in the registry, and only
  after the new session has printed its link and the pid is still a `claude` process.
- A move that does not connect leaves the source running.
- It never stops the session that is running it. Saying "move this session" from inside a session is the main use
  from a phone.
- It never reads, prints or copies a credential. Who is signed in is read from the home's state file.
- A dialog that still appears is answered by the option's number, never with arrow keys. The bypass-permissions
  warning is accepted only for a session that already ran in that mode.

## Limits

- **Same machine.** The move happens where the transcripts are; `--ssh` runs csm on another machine.
- **A new session in the app.** The moved session is owned by the target account, with a new id and link. The
  agent has the whole conversation, but the claude.ai thread starts at the move: earlier turns are not re-rendered.
- **The prompt cache starts cold**, so the first turn after a move costs more than a continuation would.
- **The last line on disk only.** A reply still being written is not in the copy.
- **"Signed in" is the last login the state file recorded**, not a live credential. A stale entry passes the check,
  and the move then fails to connect (safely: the source keeps running).
- **The quota flag is a heuristic** read off transcripts, not the meter.
- **Undocumented formats.** It reads Claude Code's internal on-disk state (measured on 2.1.296), which can change in
  any release. The tests pin every shape it depends on.

## From a phone

`./install.sh --skill` links [`skills/move-session`](skills/move-session/SKILL.md) into each account home, because each
config home reads its own `skills/`. Then, in any session that still has quota (a Remote Control session on that
machine, for example), say *"I'm out of quota, move my refactor session to personal"* or *"move this session to
work"*. The agent lists the candidates, asks if it is ambiguous, moves the session, and answers with the account and
the new link.

## Tests

```sh
python3 tests/test_mover.py
```

The tests use fixtures only: fake homes and transcripts, a fake `claude` that records its argv and environment, and a
fake `tmux` that really runs the moved window's command. They need no network and no account. They cover the
parsing, both matching ladders, every refusal, the hand-off and the keypresses. What fixtures cannot show, a real
resume under another login, was measured instead (see the design notes).

## License

MIT. See [LICENSE](LICENSE).
