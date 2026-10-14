---
name: move-session
description: "Move a Claude Code session from one of the user's Claude accounts to another with claude-session-mover (csm), keeping the whole conversation. Use when the user says: move this session to another account; move my <title> session to <account>; I'm out of quota, move it to <account>; this account is rate limited, switch accounts; which of my sessions are out of quota; list my sessions across accounts. Also use when they name an account next to a session, or paste a claude.ai/code/session_… link and ask to run it as another account."
---

# Move a session to another account

`csm` (claude-session-mover) moves a Claude Code session to another of the user's own accounts.
It copies the transcript into the target account's config home and resumes it there, with Remote
Control on, so the conversation continues on that account's quota and shows up in that
account's Claude app. An account is a config home: `~/.claude` (named `default`) or
`~/.claude-<name>` (named `<name>`), or whatever `csm accounts` lists.

```
csm accounts                                  # the accounts, and who each is signed in as
csm list [--account NAME] [--all] [--json]    # recent sessions, newest first
csm move SESSION --to ACCOUNT [--stop-source] [--dry-run]
```

SESSION is a row number from the `csm list` you just ran, a session id or a 4+ character
prefix, a `claude.ai/code/session_…` link, or enough of the title to be unique. ACCOUNT is a
name, an email, or a unique prefix. **Never pass a bare number as an account**: names only.

## What to do

1. **Run `csm list` first, always**, even when the user named the session. The row numbers
   `move` accepts come from that listing, and it shows which sessions are live, which one is
   this session (`← this session`) and which are `⚠ OUT OF QUOTA`.
2. **Show a short shortlist in your own words**: the session, its account, its age, and whether
   it is out of quota (and when that resets). The user may be on a phone.
3. **If which session they mean is not certain, ask one short question** naming the two or
   three candidates. Never move on a guess: a move starts a second process on a conversation.
4. **If they named no account, suggest one** that is not the source, is signed in (`csm
   accounts`), and is not flagged out of quota. Say which and why, then move.
5. **Run `csm move <row> --to <account> --stop-source`.** Use `--dry-run` first only when
   something looks off; a dry run prints `🛑 a real move would be REFUSED: …` when it would be.
6. **"Move THIS session"**: just do it. The tool recognises its own session and will not stop
   it (that would kill the turn reporting the move). Tell the user to close this one in the app
   so only the moved copy gets their next message. The copy ends at the last line already on
   disk, so this exchange is not in it.
7. **If the tool warns `may be out of quota TOO`**, say so before the link and offer another
   account.
8. **Answer with one short block**: the account to open the app as, the session title, and the
   `https://claude.ai/code/session_…` link the tool printed. Then the caveats below.

## Say every time

- **The thread in the app starts at the move.** The agent remembers the whole conversation, but
  the earlier turns are not re-rendered above the next message.
- **The old session is not deleted.** It stays in the source account; archive it in the app if
  wanted. `--stop-source` only stops its process.
- **The moved session is new in the target account**: new id, new link.

## Refusals and their fixes

| The tool says | Fix |
|---|---|
| `already in <account>` | pick a different account |
| `same login as` | that home is signed in to the same account: pick another |
| `holds no login` / `WRONG login` | the user signs that home in: `CLAUDE_CONFIG_DIR=<home> claude`, then `/login`. Never try this yourself |
| `named, never numbered` | use the account's name |
| `row N is not in the last csm list` | run `csm list` again and use its numbers |
| `matches N sessions` | a move is a copy, so an id can be in two accounts: use the row number |
| `ALREADY running session` | the target already runs that session: stop it there first, or pick a third account |
| `window … already exists` | moved there before: close that tmux window, or pick another account |
| `does not exist on <host> any more` | the session's directory is gone: recreate it, or move another session |

## Boundaries

- Run it on the machine where the session's transcripts are; `csm --ssh HOST …` reaches another one.
- Move only the session the user asked about, one per request unless they said otherwise.
- Never stop a process or close a window you did not start. `--stop-source` is the only stop,
  and it fires only after the moved session has connected.
- Never read, print or copy credentials, and never sign an account in on the user's behalf.
