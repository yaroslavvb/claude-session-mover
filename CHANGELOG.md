# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Every fact below was measured against Claude Code 2.1.296–2.1.300 on macOS. The on-disk
state it reads is undocumented and can change in any CLI release; the tests pin every shape
the tool depends on.

## [0.6.4] — 2026-10-29

- **A one-shot `claude -p` run is never due.** The first real dry run of a watchdog over `csm stalled` found
  exactly one due session, and it was a script's `claude -p` research helper killed mid-run; reviving it would
  have opened an interactive session on a new claude.ai link for a task whose caller had already given up on it.
  `revive_stop` now records the `entrypoint` of the last main-chain line it read, and `stalled_due` declines a
  terminal-kind session whose last writer was print mode (`sdk-cli`). A Remote Control server child also runs in
  print mode, but it is told apart by its id, never by this field; and a one-shot run later resumed by hand
  reads `cli` and is due again. `csm revive <id>` by hand still revives one.

## [0.6.3] — 2026-10-29

What an adversarial review of 0.6.2 found the same day, by running both readers over every
transcript in the config homes on one machine (1,958 files): the new unanswered-prompt verdict
fired on 132 of them, and in every one of those the session had answered everything anybody
asked it. 764 tests (761 + 3).

### Fixed

- **A compaction summary is not a prompt, and reading it as one called idle sessions dead
  mid-work.** The CLI compacts a session that is SITTING IDLE to keep its prompt cache warm, and
  says so itself in the `informational` line it writes right after: *"Compacted while idle, before
  the prompt cache expired · turn off with `"idleCompaction": false`"*. What that leaves at the end
  of the file is a `system` line of subtype `compact_boundary`, a `user` line carrying
  `isCompactSummary: true` (and `isVisibleInTranscriptOnly: true`) whose text is the summary, and a
  run of `attachment` lines — and NO assistant line, because the session was idle. 0.6.2's window
  opened at that summary, found nothing after it, and reported `mid-turn`: *"killed before it said
  anything"*, about a session that was idle precisely because it had finished. Measured over all
  1,958 transcripts in the config homes on this machine: 132 end in that shape, nine of them inside
  `CSM_WAKE_MAX_AGE_H`, and for a dead Remote Control child the action an unattended caller takes
  on that verdict is a FORK plus archiving the claude.ai link the session already had.
  - `isCompactSummary` now joins `isMeta` and `tool_result` in the lines a window may not open at:
    the line is `type: "user"` and nobody sent it. The window then opens at the real prompt before
    the compaction, whose answer is in the same window, and all 132 read `finished`. The 40
    genuinely unanswered prompts in that corpus — eight of them carrying the CLI's own
    `interruptedByShutdown` — are untouched, and no other verdict moves: `usage-limit` 39,
    `api-error` 22, `finished` 1,589, `empty` 132, `mid-turn` (unanswered tool call) 4, all
    identical before and after.
  - 🛑 AND IT IS FIXED AT THE WINDOW, NOT IN THE VERDICT. A session parked on a usage limit is
    idle, so it is a candidate for idle compaction too — and a window opening at the summary holds
    neither the limit line nor the prompt it belongs to. Such a session read `mid-turn` rather than
    `usage-limit`, which `stalled_due` calls due NOW instead of at the reset: pinned by a test,
    because waking inside the window spends the session's first turn on a second 429.

## [0.6.2] — 2026-10-29

What a live end-to-end run of the waker on throwaway sessions found (CLI 2.1.312, the same day):
the sweep covered only half of "killed while working". 761 tests (753 + 8).

### Fixed

- **An unanswered PROMPT is a mid-turn kill, like an unanswered tool call.** `revive_stop` read
  `mid-turn` only from an assistant line whose `tool_use` no later `tool_result` answers — so the
  shape a kill in the first seconds of a turn leaves read `unknown`: not due under any wake rule,
  and carrying `uuid: ""`, so an at-most-once key could not have named that stop even if it had
  been. Measured on a throwaway session SIGKILLed 1.5 s after Enter: the file ends on the user's
  own line plus the `attachment` line 2.1.312 writes after it (`attachment.type:
  "total_tokens_reminder"`, type `attachment` — a main-chain type that carries no `message`), and
  there is no assistant line at all. A real prompt (not `isMeta`, not a `tool_result`) with no
  main-chain assistant line after it is now `mid-turn`, with **that prompt line's uuid as the stop
  event** and its timestamp as the stop. This is the machine-restart case for a session that was
  between turns, which is most of what a Wednesday 02:30 restart leaves behind.
  - `stop.tool` is what tells the two shapes apart, and the sentences that named a tool no longer
    invent one: the risk line becomes *it was killed before it answered its last prompt, so nothing
    on disk says whether it had started acting on it*, and the revive note says *it was killed
    before it answered that prompt at all* instead of naming "a tool" at an unrecorded time.
  - ⚠️ A LIVE session that is thinking leaves exactly the same bytes on disk, so nothing about
    liveness moved: `stalled_due` still refuses every `mid-turn` stop whose process is not gone
    (and every row whose `ps` could not be asked, 0.6.1), and `archived` still outranks the new
    verdict — a prompt typed into a session somebody then closed from the app was a decision.
  - The verdict needs a prompt IN the window: a bounded tail holding only tool results reports
    `unknown` as before, rather than calling a turn it never saw cut off. And any assistant line
    blocks it, the `<synthetic>` "No response requested." line included (L47) — reading its absence
    as "nothing was written" would call a stop mid-turn on the strength of a line in the file.
  - LESSONS **L56**; README *What is due, and what is not*.

## [0.6.1] — 2026-10-29

What a review of 0.6.0's sweep found the same day, before the loop was anybody's: six fixes, all
in `csm stalled` and the fork row. The theme is that a reading nobody could take must never read
as a verdict, and that one stop event is one wake however many copies of the transcript exist.
753 tests (745 + 8).

### Fixed

- **A session whose `ps` could not be asked is no longer called due.** `revive_state` can only
  call a session live by PROVING its registry row, and that proof needs `ps`; with `ps` blind
  every live session read `dead`, and a live-BUSY session's transcript ends in an unanswered
  `tool_use` — exactly the `mid-turn` shape the sweep calls due. So an unattended caller would
  resume a session that was running, which `revive_start` itself refuses ("two CLIs appending to
  one transcript cannot be untangled"). `stalled_report` already put such a row in
  `coverage.unread`; `stalled_due` now refuses it too, with that reason, so the row stays listed
  and out of a watchdog's hands. `ps_table`'s own promise — "`None` is never nothing is running"
  — is what this keeps.
- **One stop event is one wake, across copies of the transcript.** A fork copies the file, so
  the same stop line and the same uuid end a second session: csm's own fork row makes one, and
  so does `claude --resume X --fork-session` or `/fork` on a parked session. `revive_handled`
  filtered the log by local id first, so the parent's exit-0 record could not cover the copy,
  both rows read DUE for one stop event, and a pass that wakes everything due woke both — two
  actors continuing one history. The at-most-once key is now the stop event itself when the
  line carries a uuid (the id + size triple remains the no-uuid fallback), the record names the
  copy it matched (`handled.copy_of`), and `csm stalled` refuses to call two rows that share a
  stop uuid due in ONE sweep — keeping the older file, since a copy is written after what it
  copied.
- **The machine is read once a sweep, not once a session.** `ps_table`'s contract is "one call,
  not one per session", and running the whole `diagnose` per candidate broke it: `revive_state`
  and `server_in_folder` each ask `ps`, `revive_account` asks the credential store,
  `server_in_folder` asks `lsof` whenever a Remote Control server is up. Measured on the
  suite's own fixtures: six parked sessions in one home cost 12 machine-wide `ps -Ao` runs and
  6 credential probes in one sweep, now 1 and 1. `read_only_memo` is opened by `stalled_report`
  and by nothing else — `revive_recheck` still asks `ps` afresh in the last second before it
  starts a window, because there the answer's age is the whole question.
- **`result.forked` says whether a second claude.ai session exists.** The fork row makes the new
  session, its link and its transcript BEFORE the relay, so an ambiguous registry name, a relay
  that errors or a turn that never appears all return exit 1 with the fork already made — and a
  caller reading the exit code alone takes that for "nothing happened", skips archiving the old
  session and forks again on its next pass. The key is `False` from the start and set exactly
  where the second session comes into being.
- **The due sentence ages the reset, not the wake margin.** `ready` is the instant a wake becomes
  permitted (`resets_at` + `CSM_WAKE_MARGIN_S`), and `human_age` floors — so a two-hour wait read
  as "1h ago" in the one sentence a person reads.
- **`csm revive` and `csm stalled` now give one answer about a limit whose class was never
  named.** `clears_with_time` is `None`, not `False`, when the stop line's own words matched no
  class, and row 4 keyed on `is False` — so the same build told the reader to wait for the reset
  while `stalled` said waiting does not clear a limit whose class its own words did not name.

## [0.6.0] — 2026-10-29

Continuing a stopped session **without anybody asking**. 0.5.0 could revive one session a person
named; this release adds the two pieces an unattended loop needs — `csm stalled`, which says which
sessions are ready, and `csm revive --auto`, which continues one honestly — plus the at-most-once
key that stops the same stop being acted on twice. Measured against Claude Code **2.1.312** on
macOS.

708 tests became **745**, on Python 3.12 and on the 3.7 floor the README promises. `move`, `stop`,
`list`, `modes`, `matrix` and `find` are untouched; `revive` without `--auto` takes the same row,
sends the same note and exits the same way as in 0.5.0.

### Added

- **`csm stalled [--since HOURS] [--json] [--check]`** — every session in every config home here
  whose transcript was written inside the window (default 48 h), why each stopped, whether it is
  **due** for a wake, what `csm revive --auto` would do about it, and whether that has already been
  done. Read-only: it starts nothing, messages nothing, signals nothing and writes nothing outside
  csm's own log. What acts is `csm revive <id> --auto`, one session at a time, so every refusal in
  the decide table is asked once per wake and not once per sweep.
  - **DUE is exactly two stops.** A usage limit of a class a reset clears (`session`, `weekly`)
    whose reset plus `CSM_WAKE_MARGIN_S` has passed; or a session killed while it was working (an
    unanswered tool call or prompt) whose process is gone, inside `CSM_WAKE_MAX_AGE_H`. A clean
    finish is not due — it answered — and neither is an API error, which waiting does not fix. A
    `monthly-spend`, `credits` or `model` limit is **never** due, and nor is a limit whose class its
    own words did not name: an unread class is not a clearable one.
  - **Five things are never due, whatever their stop**: a session that is working right now, one a
    bot owns, one a scheduled pass owns that is not live and idle, one with no conversation in it
    (a Remote Control server pre-creates those), and one archived or ended from the app — which was
    somebody's decision and not a failure to repair. Every row carries the reason in `why`.
  - **A cheap prefilter, and it is `revive_stop` on a smaller window.** The question asked of every
    transcript is whether the *last* thing that happened there is a stop a wake covers, and that
    line is at the end of the file. So the last `CSM_STALLED_PREFILTER` (64 KiB) is parsed first and
    the full 1 MiB diagnosis runs only for candidates. It is over-inclusive on purpose: a window
    that held no main-chain line is *inconclusive*, not empty, so a narrow window can cost a second
    read and never a missed session. Running the same parser is what keeps the prefilter and the
    diagnosis from drifting apart.
  - **`--json` is the contract** a scheduled caller reads: the rows (due first, then **oldest stop
    first** — the order a caller wakes them in), `due` with its reason, `row`/`action`/`what` from
    the decide table, `handled`, and a `coverage` block naming everything that could not be read.
  - **`--check`** prints one line and exits `0` (`ok:`), `1` (`FAULT:`) or `3` (`INCOMPLETE:`), the
    same contract as `modes --check`. **A due session is not a fault** — being due is the normal
    state between one pass and the next. The fault is a wake that was *tried and failed* for that
    same stop, which nothing else in the loop reports. On that path the credential probe is never
    asked at all: it prints a line of its own whenever `CSM_LOGIN_PROBE` is set, and on macOS it can
    raise a Keychain dialog, which is the one shape an unattended run may never produce. ⚠️ The
    consequence, documented rather than hidden: its *count* of due sessions can run one or two above
    `--json`'s, because a home whose login is gone is a refusal `--json` sees and `--check` does not.
    The queue is `--json`; that line is a reading, and it never turns the difference into a fault.
  - A refusal from one session's diagnosis (an unreadable `CSM_RC_JOBS_DIR`, say, which
    `rc_job_owner` dies on rather than answer "nobody owns it") drops **that row** into `coverage`
    and carries on: in `revive` it is right to abort, because it is about to act, and here it would
    abandon a whole-machine read over one directory and leave `--check` with an exit code outside
    its own contract.
- **`csm revive --auto`** — unattended mode. It changes two things and not one gate:
  - **The note's attribution.** The default sentence says the user asked for this revive, which is
    false of a run a scheduled pass made, and the receiving session is about to decide what to do
    next on the strength of it. `--auto` says instead: *"The user has not sent a message since it
    stopped; this installation continues stopped sessions automatically."* A `--say` is still quoted
    verbatim beside it — the text came from somebody, the run did not.
  - **A dead Remote Control server child is FORKED** (row 10, as if `--new-link`) rather than
    answered with row 9's printed tap: only its own server respawns it, and only on activity that
    cannot be given from here, so the fork is the only action that exists. `--json`'s `result` then
    names `old_bridge_id`, `old_url` and `archive_old`, because the one thing that stops the old
    link respawning a second actor with the same history is **archiving that old claude.ai
    session** — which csm deliberately cannot do, since it reads no credential.
  - Every refusal is untouched: a bot, a dead scheduled pass, a limit still in force (a wake sent
    early is *consumed*, not queued — LESSONS L40), an empty transcript, a home that holds no login.
    The exit codes are unchanged. `--json` reports the mode as `unattended` — not under `auto`,
    which has meant `--to auto`'s own note since 0.3.0.
- **The at-most-once key `(local id, stop event uuid)`.** `revive_stop` now reports the `uuid` of
  the transcript line its verdict was read from, and every record in `CSM_REVIVE_LOG` carries it as
  `stop_uuid`. The id alone can only answer "was this session ever revived"; a session that stopped,
  was woken, worked for an hour and stopped again is a **new** stop and is due again. `csm stalled`
  reads the log back and treats a stop as handled only on a record with **exit 0** — a non-zero exit
  is a wake that was attempted and failed, so the row stays due and the attempt is counted. Where a
  stop line carries no uuid (an older build's transcript, or a verdict read off the file's mtime),
  the readers fall back to 0.5.0's own `(local id, transcript size)` rather than matching on the id.
- **Knobs**: `CSM_WAKE_MARGIN_S` (120), `CSM_WAKE_MAX_AGE_H` (24), `CSM_STALLED_SINCE_H` (48),
  `CSM_STALLED_PREFILTER` (64 KiB). All documented in the README's Environment table.

### Changed

- **The owner refusal is narrowed, and only for a wake.** An `CSM_RC_JOBS_DIR`-owned session that is
  **live and idle** may now be woken: row 5 starts nothing — it relays a message into the process
  that is already running — so there is no second copy of the pass to make, which is the whole thing
  that refusal guards. A **dead** pass is still its supervisor's, because reviving that one does
  start a process. A **bot** is refused whatever its state: a relay into a bot's session surfaces as
  a message in the channel that bot answers. Row 5's sentence names the pass when there is one.
  - *Why it mattered*: a scheduled-pass supervisor revives a session that **died** and does not
    handle a usage limit, so a parked pass was the one class of session nothing ever continued.
- **`revive_home_gate`** is the home-usable gate lifted out of `revive_plan` into a function of its
  own, so the sweep and the run cannot disagree about whether a row would be refused. Zero
  behaviour change for `revive`. `diagnose(..., probe=False)` and `revive_account(..., probe=False)`
  leave the credential store unasked, for `--check`; `usable` is then `None` ("not asked"), which is
  never read as "cannot run it".
- `revive_fork` reports `old_bridge_id` / `old_url` / `archive_old` on **every** fork, not only an
  `--auto` one: it is a fact about the action, and the old link is left behind either way.

## [0.5.0] — 2026-10-28

`csm revive`: resolution that reaches a session nothing is running, a stop reason that is right
for all of them, the diagnosis those two make possible, and now **the actions** — wake it,
resume it in place, fork it onto a new link, move it to another account, or print the one thing
to tap. Everything here is measured against Claude Code **2.1.312** on macOS (Wed 28 Oct 2026)
— a newer version than the 2.1.296–2.1.300 the rest of this file was written against.

466 tests became **706**, on Python 3.12 and on the 3.7 floor the README promises. Nothing about
`move`, `stop`, `list`, `modes`, `matrix` or `find` changed behaviour except where this file says
so: `check_target`'s split is byte-for-byte identical for a move, and `find`'s exit code is the one
deliberate change to an existing contract.

### Added

- **`csm revive SESSION` acts.** It takes the first row of the decide table that matches, and
  whatever that row is, the session comes up (or is found) as an ordinary **idle** process with
  no prompt of its own and the note is then **relayed** to it. Exit `0` means it took a turn
  (or that there was nothing to do, or that the one thing to tap was printed), `1` that
  something is up and nothing proved it read the note, `2` that nothing was started at all.
  - **Row 5, wake**: it is up and idle, so nothing is started — the note is relayed into it.
  - **Rows 7 and 8, resume in place**: `claude --resume <id> --remote-control=<label>` in
    `moved-<id8>`, in the session's own home. For a self-hosted session the **link is the
    proof**: it re-attaches its own claude.ai session, so a NEW link means nothing re-attached
    and the note is *not* sent, because the sentence it carries ("the link you had still opens
    this conversation") would be false. A terminal session gets a new link and is told so.
  - **Row 6, move**: `do_move` unchanged — its copy, its own `isMeta` move note into the copy,
    its window, its link, its printed cost — and then the revive note relayed into the copy.
  - **Row 9, keep-link**: a dead server child cannot be resumed onto its own link, so the one
    tap is printed (open the link; its server respawns the child, idle) and **nothing is
    started and nothing is waited for**.
  - **Row 10, fork** (`--new-link`): `--resume <old> --fork-session --session-id <new uuid4>`,
    in `moved-<new8>`. csm chooses the id, which is what makes the window name, `preflight`
    and `csm stop`'s authorisation work on a forked session at all; bare `--fork-session`
    mints an id csm never learns. The old transcript is left byte-identical, and the old link
    is reported loudly: it still opens the OLD copy.
- **The relay, and it is the only carrier.** `claude -p --model <CSM_RELAY_MODEL, haiku>
  --permission-mode bypassPermissions --name "csm revive (<machine>)" --output-format json`,
  run under the target session's own config home with the environment scrubbed, stdin closed,
  in a folder of csm's own under the state dir, bounded by `CSM_RELAY_TIMEOUT_S` — instructed
  to call its SendMessage tool **once**, to that session's registry `name`, with the note
  verbatim between two marker lines.
  - 🛑 **Nothing is ever written into a transcript by a revive, and no positional prompt is
    ever passed.** Measured in a spike (2.1.312, Wed 28 Oct 2026): a positional prompt is
    recorded as the user's own typing (`origin: {kind: "human"}, promptSource: "typed"`)
    whatever its text says, while a relayed message is recorded for what it is —
    `isMeta: true, turnOrigin: "peer", origin: {kind: "peer", name: "csm revive (<machine>)",
    fromMode: "bypass", verifiedPeerPid, msg_id}` — and the app shows it as a message from
    that sender. The `isMeta`-line-plus-`--reply-on-resume` alternative was measured too and
    rejected: it writes into a transcript, and for a fork it would have to write into the
    *old* one, where a later lazy respawn of the old link could pick it up as an interrupted
    turn. (A hand-rolled frame to the session's own peer socket is *held* for a person on a
    bypassPermissions session, so the relay goes through Claude Code's own tool or not at all.)
  - **The proof is a turn, never a link**: the registry row going `busy`, or an `assistant`
    line past the byte offset taken *before* the relay (`continued_past`, written in
    `appended_mode`'s shape), within `CSM_REVIVE_PROVE_S`. A relay that reports success and
    sends nothing is exit 1, because the proof is the session's own behaviour and not the
    relay's word for it.
- **At most one revive of one session at a time**, held from the diagnosis to the start:
  `state_lock`'s own lock-directory shape (including its 120 s stale break, so a killed revive
  does not wedge the session), keyed on the local id. And because a lazy respawn has the *same*
  local id before and after, the liveness check is **re-run in the last second before anything
  starts**: every home's registry and the machine-wide `ps` sweep, through `revive_state`, so a
  child that appeared while csm was deciding is a refusal rather than a second writer.
- **`<STATE_DIR>/revive.jsonl`** (0600), one JSON record per revive, plus one `CSM_LOG` line:
  the at-most-once triple (local id, bridge id, transcript size at diagnosis), the row, the
  action, what was started, what was proved and the exit code. 🛑 Never the note — that is
  conversation text, and this file is a record of what ran.
- **Knobs**: `CSM_RELAY_MODEL` (`haiku`), `CSM_RELAY_TIMEOUT_S` (120 s), `CSM_RELAY_NAME`
  (`csm revive ({machine})`), `CSM_REVIVE_PROVE_S` (90 s), `CSM_REVIVE_LOG`.
- **The external-imports dialog** — "Allow external CLAUDE.md file imports?" — is in `PROMPTS`,
  answered with its focused default, **No**. Measured out of the 2.1.312 bundle:
  `confirmLabel: "Yes, allow external imports", cancelLabel: "No, disable external imports",
  hideIndexes: true, cancelFirst`, and answering it writes
  `hasClaudeMdExternalIncludesApproved` into that home's state file for the project, for good.
  Approving a CLAUDE.md to import files from outside its own working directory is consent only
  the person can give, so csm declines — and it answers at all only because the dialog *blocks*
  an interactive start, which would otherwise make a revive that did nothing. ⚠️ The revived
  session therefore comes up without those imports, which matters in a folder whose doctrine
  lives in an imported file.
- **Optional plan keys** `session_id`, `fork_session` and `revive_of`, with the plan `version`
  left at **1**: `run_window` reads every field but `kind` and `local_id` with `.get`, so a
  reflexive bump would refuse a plan already on disk from a move that is still starting. A
  `--session-id` is emitted only beside `--fork-session` and only for a whole uuid, because the
  CLI refuses the pair otherwise.

- **`csm revive SESSION --dry-run`: the diagnosis, the plan and the note.** One record about
  one session, printed as a three-line answer (what stopped it and when · what revive would do
  · the one risk), then the detail, then the row of the decide table it would take and the note
  it would send. `--json` carries the record, the decision and the note. It is read-only and
  offline: it starts nothing, signals nothing and writes nothing — and it is built by the same
  function the real run uses, so what the plan says is what the run carries out.
  - **What kind of session it is, proved rather than guessed.** A Remote Control *server
    child*'s local id *is* `uuid5` of its bridge session's api url, so a bare bridge id from
    the link, from its registry row or from an orphan `~/.claude/bridge-spawn/cse_X-*`
    directory that derives to this transcript's name is proof — and such a session cannot be
    resumed onto its own link, which is why reviving it in the same account has to fork. A
    *self-hosted* session wrote a `bridge-session` line or a `bridge_status` url into its own
    transcript and does re-attach. 🛑 The registry's `entrypoint` is never used for this: it
    says how the process was started (`sdk-cli` means `--print`) and a fork or a resume
    rewrites it.
  - **Why it stopped, parsed as JSON lines over at least 1 MiB, from the last real prompt
    forward.** `usage-limit` (with the *class* from the limit's own words — session, weekly,
    monthly-spend, credits, model — because waiting only clears the first two; the window from
    `rateLimitType`; the reset; and whether it is still in force), `api-error`, `mid-turn` (the
    last main-chain assistant line holds a `tool_use` no later `tool_result` answers),
    `archived` (a `code 4090` system line *after* the last `bridge_status`), `finished`,
    `empty`, `unknown`. A limit with a clean answer after it is history, not the stop.
    - The window is `CSM_REVIVE_TAIL`, 1 MiB by default, and **not** the listing's 384 KiB: on
      the incident this was written for, `usage_limit_reached` and `quotaLimits` are in the
      last 512 KiB of a 2.6 MB transcript and *not* in the last 384 KiB, so the listing's
      window reports a clean finish for a session sitting on a wall. And it is parsed, never
      grepped: a text match on the tail says "out of quota" about any session that merely
      discussed one.
  - **What the run lost**, from `workflows/wf_*.json` in the session's sibling directory: the
    agents whose own `state` is `error`, counted and named. 🛑 Never the file's top-level
    `status`, which reads `completed` on the incident where five agents died on a limit.
  - Plus: whether anything is still running it (a registry row proved by `procStart`, and a
    machine-wide `ps` sweep for a claude process whose argv names `cse_<bare>` or
    `--resume <id>` — a registry file survives the SIGKILL of its own process), whether the
    session's own home can still run it, its account's meter, whether a `claude remote-control`
    **server** is up in that folder (the one thing that decides whether opening the link brings
    a server child back by itself), and whether anything else owns it.
- **The revive note**, delivered as the revived session's next user turn. It opens with the
  stamp — `[claude-session-mover — written by the tool; the user did not type this]` — because
  it renders in the app as a message, and a message in your conversation that you did not type
  has to say so in its first line. Then: when and why it stopped, what changed while it was
  stopped (a reset that passed, a machine that restarted *after* the stop), how it was brought
  back, the account and the memory store, the agents that died with it — and, only for a
  `mid-turn` stop, that its last tool call has no recorded result and may have fully applied,
  partly applied or not run. Then one request, attributed: `--say TEXT` quoted verbatim as
  `He said: "…"`, or the plain fact that csm was asked to revive it. Bounded at ~1,500
  characters by *dropping* optional clauses, never by cutting a sentence; a `--say` over 400
  characters is refused rather than shortened.
  - 🛑 A `--say` (or a built note) whose first non-space character is `!` or `/` is refused:
    the CLI runs a delivered prompt starting with either as a command (2.1.312's own
    `prompt_undelivered` says so), so it would either execute something nobody asked for or
    vanish.
- **`CSM_RC_JOBS_DIR`**: where a scheduled-pass supervisor records the session each pass runs
  as (`<job>.session` files whose last `uuid=` line is the local id). A session named there is
  revived by its own supervisor, onto the same link, so `revive` refuses it and says whose
  command it is — the same doctrine as `CSM_BOTS_DIR`, including that a directory which cannot
  be *read* is a refusal and not a "no". Unset means no such program.
- **`CSM_LSOF`**: how `lsof` is invoked. Only `revive` asks it, and only for the one question
  that is nowhere in a process's argv — which folder a Remote Control server is serving.

- **A claude.ai link now finds its transcript with nothing running.** A Remote Control
  session's local id is not random: the CLI derives it from the bridge session's own API url,
  `uuid5(3ab19d7e-9f35-45c2-926e-75e271cc60b3, "https://api.anthropic.com/v1/code/sessions/
  cse_<bare>")`. So `derive_local_id` computes the transcript's **name** from the link alone —
  no process, no registry row, no network. Before this, a link resolved only through a live
  registry row or a transcript's own `bridge-session` line, and a Remote-Control server child
  writes neither: every dead phone session was unreachable by the only name anybody has for
  it. Verified on 37/37 live registry rows carrying both ids, and 0/37 against any other name
  form; two pairs are pinned in the tests as constants rather than recomputed, so the test
  cannot agree with the tool by construction.
  - It accepts a claude.ai link, a bare `session_X` or `cse_X`, any url carrying such a
    segment (by the CLI's own rule: split on `/?#`, first segment that is *entirely* such an
    id), and a **spacesheep session page**, `…spacesheep.dev/sessions/claude-code/<uuid>`,
    whose uuid *is* the local id.
  - It is applied at the **spec layer**, above `pick`'s ladder, in `move`, `stop` and (through
    the remote helper, which runs for a local `find` too) `find`. That is what lets a derived
    id be **pinned** into the listing: only a whole id survives the age cap, and the session
    reached by its link is typically the oldest file in the home — it stopped days ago, which
    is why anyone is looking for it.
  - 🛑 **A link never falls through to a weaker rung.** Its rungs are exact: the derived
    transcript, then a row whose claude.ai id is that one. A link that derives to nothing here
    is refused, naming the file it wanted, and is never handed to the id-prefix or title
    rungs. The title rung is the sharp edge — a session whose first prompt *pasted* the link
    has the link in its title, so "find me this link" would have answered with the session
    that merely talks about the one you asked for. (A spacesheep link reached that rung for
    real: `URL_RE` does not match it at all.)
  - A **version canary** checks that the namespace constant really is in the CLI bundle this
    machine runs, and says `derivation unverified for CLI <v>` in the plan when it is not —
    never a silent pass. The needle is the constant, not a function name: the construction
    around it is byte-identical in 2.1.310/311/312 while every minified identifier in it
    changes. The bundle is ~290 MB, so the verdict is cached in the state dir against the
    bundle's path, size and mtime and the scan runs **once per CLI version** (0.22 s, 69 MB
    peak RSS, in `CSM_CANARY_CHUNK`-sized reads with a needle-sized overlap).
- **A third source for a session's claude.ai id:** a `{"type": "system", "subtype":
  "bridge_status", "url": …}` line, which a `--remote-control=` session writes every time
  `/remote-control` reports in. An explicit `bridge-session` line still wins; this one is read
  because the two sit in different places in the file — `bridge-session` is written once near
  the start and falls into the unread middle of a long transcript, while `bridge_status` is in
  the tail. (97 of the 1,935 transcripts in the config homes here carry one.)
- **The remote helper answers about links and about server children.** `find` runs the same
  derivation (so a dead link resolves on another machine too, and above the age cutoff, where
  it has to be to matter), and reads `<home>/sessions/*.json` for a live child's
  `bridgeSessionId` — the only place a running server child's two ids sit together, which the
  helper never read before, so `find` failed for *live* children as well.

### Fixed

The first eleven entries are the review of this release's own commits, applied before it shipped.
Each one has a test that fails without the fix.

- **The note now reaches a session resumed over a stale registry row.** Right after a resume there
  can be two registry files for one id: a stale one whose pid was reused, and the new process's.
  `live_rows` keeps whichever sorts last by file name, which compares pids as text, so the stale row
  could mask the real one. The relay then found no name and sent nothing (exit 1, "not proved").
  Seen once on a CI runner, depending on which pid it handed out. `live_name` now reads every row
  for the id and takes the proved one; a test swaps the two rows' roles so either order is covered.
- **The suite no longer depends on the machine it runs on** (tests and CI only; the tool is
  unchanged). The fake tmux keyed a pane file by window name, so a window reopened under the same
  name shared a file with the old window's still-running process, whose exit trailer could land
  over the new link; it now keys panes by window id and SIGHUPs a killed window's process group, as
  the real tmux does. That was the flake behind `Stop.test_a_second_move_is_accepted_again_once_the_window_is_gone`,
  which failed CI on 0.4.0. Three revive tests had assumed this machine's `ps` and temp-path
  lengths. CI's Python 3.9 cell moved to ubuntu-24.04, because ubuntu-latest (26.04) no longer
  serves 3.9. And the stand-in for a running session is now a copy of `/bin/sh` run as
  `claude -c 'sleep 120; exit 0'`, not a `claude` symlink to `/bin/sleep`: on Ubuntu 26.04
  `sleep` is a multicall binary (Rust coreutils) that dispatches on its name, so the symlink exited
  at once and 56 tests failed there.
- **Line 2 for a dead server child no longer contradicts itself.** With no server in its folder it
  read "open the link and say continue — its server respawns it on open (and its server is down)";
  three fresh readers of the README each took it as a contradiction. Each server state now gets one
  sentence: up, "open it and say continue"; down, "its server is down, so opening it will not bring
  it back … `--new-link` forks it onto a new link now"; unread, the first advice with "if one runs
  in its folder". A pure test feeds all three states to `revive_decide`.

- 🛑 **A dead server child named by its id or by part of its title was classified `terminal`
  and RESUMED IN PLACE on its own local id** — the two-writer start LESSONS.md L39 forbids,
  reachable by the ordinary spec a person types (`csm list` prints the id8 and the title, and
  `csm revive --help` invites both). `revive_kind` could prove `server-child` only from one of
  four sources, and a dead child that exited cleanly has none of them: no registry row, no
  bridge id in its own transcript, and no `bridge-spawn` directory. It fell through to
  `terminal`, which is decide row 8 — `claude --resume <old id>` with **no** `--fork-session` —
  while a later lazy respawn of the old link has that same local id. `--new-link` could not
  rescue it, because the flag is read only inside the `server-child` branches, so row 8 matched
  first and the flag was silently ignored while `--json` reported `"action": "new-link"`. The
  id's own uuid **version** settles it with nothing left to read: a child's id is `uuid5`, every
  other session's is a random `uuid4`. Of the 861 version-5 transcripts in the config homes on
  this machine, 2 name their bridge session in their own file and 19 have a live row or a
  directory — **840 were in the state that mis-classified**. Such a session now takes row 9, or
  row 10 with `--new-link`, and asks for the link rather than printing one it cannot name.
- 🛑 **`revive` silently picked the wrong copy when one id sat in two homes**, where `move` and
  `stop` both refuse. `revive_resolve`'s soft pass answers `None` both for "nothing matched" and
  for "several matched, and `one_of` would refuse", and the rung below it — which exists for a
  transcript every listing *drops* — answered for both by taking the first home in `accts` order.
  A move is a copy, so two dead copies of one id is the ordinary state after any `csm move`: a
  3-day-old snapshot was resumed over a 1-minute-old one, published on a new claude.ai link,
  charged to the wrong account's quota, and told "You are still `<the other email>`". Only "no
  listing row for this id anywhere" now reaches that rung, it asks every home rather than the
  first, and **`--account NAME`** is the cure both refusals name.
- **`preflight`'s live-twin check refused every in-place revive over a stale registry row.**
  `revive_state` refuses to trust a row whose pid it cannot prove and reads it as DEAD, keeping
  the reason; `preflight` read the same row straight out of `live_rows` with no proof. For a
  *move* that branch is rare, because the destination usually does not exist; for a revive in
  place the destination **is** the session's own transcript, so it ran on every run against the
  session's own dead row. The dry run said "row 7, resume it in place" and the real run exited 2
  with "`<account>` is ALREADY running session `<id>`", whose two cures are both impossible —
  and it is the machine-restart case the feature was built for, where the surviving rows name low
  pid numbers that are very likely in use again. The row is now proved by
  `still_the_same_process`, exactly as `live_name` does, and only where the destination is the
  session's own file, so `move` keeps its conservative behaviour byte for byte.
- **`Path.glob` swallowed the PermissionError, so `revive <link>` and `find <link>` answered "no
  transcript for that link here" about a home they could not read.** Both link rungs globbed, and
  `Path.glob` does not raise on a directory it may not open — it yields nothing — so the
  `except OSError` around it was dead code and a locked-out home came back as a home that does
  not hold the file. That is the worst answer this feature can give: the person is told the
  session they are rescuing is not on this machine. The scan is now `os.listdir` plus a stat per
  folder (the shape `preflight`, `live_rows`, `owner_of` and `rc_job_owner` were already
  rewritten to, measured on 3.7.9 and 3.13), unreadable folders are carried on the spec, and
  every sentence that claimed absence names them instead.
- **A `<synthetic>` "No response requested." line counted as the session answering, masking both
  a usage-limit stop and a mid-turn kill as `finished`.** The CLI writes that line — no error
  keys, model `<synthetic>` — precisely when an injected `isMeta` prompt produced **nothing**, so
  the one line that records a non-answer was being read as the answer. A waited-out limit lost
  its `class`, `window` and `resets_at` and the note then said the session "had answered and was
  sitting idle"; a session killed mid-`Edit` read as finished too, which dropped the one sentence
  M4 makes mandatory — its last tool call has no recorded result. 23 such lines in 20 of the
  1,943 transcripts here, all with that exact text. Both readers now ask one question
  (`answered_here`), which also fixes the other half: an `isApiErrorMessage` line whose `error` is
  not `rate_limit` still set `scan_transcript`'s marker, so `csm list` said `out_of_quota: false`
  about a session `csm revive` called `usage-limit`.
- **The widened quota detection was not applied to `REMOTE_HELPER.scan`**, so `csm find` still
  reported no quota for 10 of the 44 measured stop lines — and its `elif not err` branch actively
  *cleared* a quota found on an earlier line. `cmd_find` promises the opposite ("one reading rule,
  so a row found here and a row found there are the same row") and runs the helper locally too, so
  three readers disagreed about one file. The helper now tests both shapes, and only a line that is
  really an answer clears a quota.
- **Nothing checked that the registry `name` the relay addresses is unique**, and csm made the
  collisions itself. SendMessage addresses a session *by* its name; `live_rows` is keyed by local
  id, and `rc_name` was `rc_label(<title>, "revived by csm")` truncated to 56 characters, so two
  revives of one session — or two sessions whose titles start alike — registered under one
  identical name. The note could then land in a conversation nobody named while `prove_turn`
  watched the intended session and reported "it is up but idle" with no hint of the misdelivery.
  The proved live rows of that home are now counted before anything is sent, more than one is a
  refusal naming both, and csm's own label carries the session's id8.
- **The at-most-once claim did not hold for the length of a revive.** `state_lock` breaks a lock
  directory older than 120 s by its `mkdir` mtime and nothing refreshed it, while a revive holds
  its claim across four bounded waits — a window connecting (150 s), its registry row appearing
  (150 s), the relay (120 s), the turn (90 s), and for a fork the new transcript (150 s) — so from
  t=120 s a concurrent `csm revive <same id>` broke a claim that was very much alive, on every
  run. The waits now re-stamp every lock this process holds (`touch_locks`), and the revive claim
  has its own bound, `REVIVE_CLAIM_STALE_S`; the `.claude.json` lock keeps the 120 s it was
  written for.
- **`relay_dir`'s docstring was wrong about where the relay's own transcript goes**, which made a
  real fact look handled. The cwd moves the project-folder **slug**, not the home: the relay files
  `<the session's home>/projects/<slug of the relay dir>/<its id>.jsonl`, with the note inside it.
  So every revive left a session in `csm list`, in `csm find` and in revive's own resolution whose
  title was the relay instruction — and one of those is revivable. That slug is now skipped by
  `transcripts_by_id` and by the spec layer's scan, the docstring says what the 0700 mode really
  protects (the cwd, not the transcript), and README, design.md and LESSONS.md (L48) say that the
  note does reach disk in that home, so "no note in any file csm keeps" is not read as more than
  it claims.
- **`revive_state`'s `ps` sweep matched too much, twice, and each one became a hard refusal.** The
  bridge-id arm was a plain substring, so any process running as `claude` whose command line
  merely *mentioned* the id read as "something is running this session NOW" — the remote helper's
  `detail()` has always required the id to follow a flag, and the test that pins it calls the other
  shape a decoy. And `own` matched `--resume <old id>`, which a session **forked** from that id
  carries for its whole life, so a second `csm revive <old> --new-link` was refused with "two CLIs
  appending to one transcript" — which `revive_fork`'s own measured fact contradicts: a fork writes
  only `<new>.jsonl` and leaves the file it read byte-identical.
- **`tmux()` was the only subprocess call in the engine with no timeout**, and every revive wait is
  a loop around it: `wait_window` checks its deadline only *between* captures, so one blocking tmux
  client — a wedged server, a socket that accepts and never answers — hung the whole command past
  `CONNECT_WAIT_S` with no bound at all, which is the one shape the no-blocking-wait rule forbids,
  inside the command that promises bounded machine waits. `CSM_TMUX_TIMEOUT_S` (default 20) now
  bounds it, and a timeout is a failed capture, which every caller already handles.
- **`scan_transcript` missed roughly a quarter of real usage-limit stops, and read them as a
  clean finish.** Detection was `apiError in QUOTA_ERRORS`, but of 44 assistant quota-stop
  lines in the config homes on this machine **10 carry no `apiError` key at all** — only
  `isApiErrorMessage: true`, `error: "rate_limit"`, `apiErrorStatus: 429` and a top-level
  `quotaLimits` ({`status`, `resetsAt`, `rateLimitType`}). Those fell into the clean-line
  branch, so `csm list` said the session had finished and `out_of_quota` was false. Worse, the
  same branch set the "the session answered again" marker, so a *genuine* limit earlier in the
  tail was read as waited out. Both shapes are now read, and `kind` — the word that says
  whether waiting clears the stop at all — falls back to `quotaLimits.rateLimitType`.
- **The remote helper could not identify the process owning a Remote Control session, and it
  failed in the dangerous direction: "nothing is running there".** A server child's argv is
  `--print --sdk-url …/cse_X --session-id cse_X --resume=<that url>` and names the local uuid
  nowhere, while `detail` matched on the local uuid alone. `--stop-source`'s cross-machine
  refusal and the move note's "still running on `<origin>`" clause both key on that answer, so
  a `--from-machine` move of a session that was very much alive reported the other machine
  idle. `detail` now takes the bare bridge id as an optional third word (older callers still
  work) and matches it after `--resume`, `--session-id` or `--sdk-url`.

#### Fixed after the live test

Two bugs the first end-to-end run of `csm revive` against real sessions found, both reproduced live
on CLI **2.1.312** (Wed 28 Oct 2026). Each has a test that fails without the fix.

- 🛑 **A wake REPORTED a permission mode it had not applied, in the unsafe direction.** Every row
  with a note resolved `resolve_mode`, row 5 included — and row 5 starts no process at all: it
  relays a note to a session that is already running. Live: a session running
  `--permission-mode bypassPermissions`, woken with `--permission-mode plan`, was reported as
  `mode plan (from --permission-mode)` while it went on running in bypass, and `--json` carried
  `{"mode": "plan", "why": "from --permission-mode"}` — telling an unattended caller that a
  session had been put into the safest mode when it was in the least safe one. A mode is now
  resolved only on the rows that START a process (`REVIVE_ROWS_THAT_START` — 6, 7, 8, 10, 11),
  and rows 3, 5, 9 and every refusal REPORT what the session is already in instead
  (`unchanged_mode`): the proved pid's own `--permission-mode`, off the same `ps` sweep
  `csm modes` reads (`revive_state.mode_launched`, new), and the last `permissionMode` its
  transcript recorded, each named in a `why` that opens `unchanged:`. When the two disagree the
  **stronger** one is reported, because a Remote Control worker records `auto` while its server's
  argv says `bypassPermissions`; an unknown mode is carried through untouched; and when neither
  source says anything the line reads `unknown`, never `default`. `--json`'s `mode` block gained
  **`applied`**, false on every row that starts nothing, and a `--permission-mode` typed at such a
  row is reported as not carried out by the existing `dropped()` convention. A typo in the flag is
  now also refused on every row (`check_mode`), as `--say`'s own check already was: it used to
  reach a wake in silence.
- 🛑 **`--new-link` was silently dropped on every row but 9 and 10.** The flag was read only at
  that one split, and `dropped()` named only `--to` and `--say`, on rows 3 and 9. Live:
  `csm revive <dead self-hosted session> --new-link --dry-run` took row 7 — "resume it in place,
  on the same claude.ai link" — with no mention of the flag anywhere in the plan or in `--json`.
  On a dead **self-hosted** or **terminal** session `--new-link` now takes the fork action as
  **row 11**: row 10's mechanics unchanged (`--resume <old> --fork-session --session-id <new
  uuid4>`, the window `moved-<new8>`, the old file left byte-identical, the loud warning
  afterwards), named honestly in the plan, in `--json` and in `revive.jsonl`. A terminal session
  never had a claude.ai link, so its fork's note and its warning talk about the old **copy** and
  invent no link. On every other row — the live rows 3 and 5, the move, and every refusal — the
  flag is reported as NOT carried out with the reason. `dropped()` is now called for **every**
  row rather than two, covers `--new-link` and `--permission-mode` as well as `--to` and `--say`,
  and what it returns is carried as `decision.dropped` so an unattended caller reads it as data.

### Changed

- **`check_target` is split**, with zero behaviour change for `move`: the five refusals about
  one config home (on no machine, no such home, holds no login, holds the wrong login, the
  credential is gone) are now `check_home_usable`, and `check_target` keeps its two about two
  *accounts* (source == target, the same login in another home) in front of them. `revive`
  resumes a session in the home it is already in for three of its actions, so those two would
  refuse exactly the thing it is for. The refusal **order** is preserved too — a home holding
  the wrong login is still reported as the wrong login, not as the same login.
- **`--to auto` always says which account it picked**, and now carries that sentence in
  `AUTO_NOTE` as well as printing it, so a caller whose one stream is a contract (`revive
  --json`, whose stdout must parse) can place it itself instead of finding it in the middle of
  its own output.
- **`csm find` exits 1 when nothing matched** (it used to exit 0 whatever it found, which
  reads as "asked and answered" to anything checking a status — and the answer it gives most
  often about a session somebody has lost is the empty one). The exit code was verified unused
  first: nothing in the wrapper installation that drives csm from scheduled passes
  runs `find` at all, let alone branches on its status. A caller that wants rows still reads
  `--json` and counts them; 1 means "nothing matched", never "the search failed", and with
  `--json` the hint goes to stderr so stdout stays parseable.
- **"No session matches" now says that 0 rows is not proof** and names the one spec that
  always works. What `find` searches is ids and titles, and the session being looked for is
  the one that stopped: it has no registry row, and a Remote Control session is the kind least
  likely to have a title at all (11% of v5 transcripts here carry an `ai-title`, against 64%
  of v4 ones). The hint names the derived transcript when a link was given, and asks for the
  link when one was not.
- **Row 8's `action` is `resume-new-link`, not `new-link`.** The `action` strings are a public
  vocabulary — `--json` carries them and so does every line of `revive.jsonl`, which README
  documents as the machine-readable record — and the one value a reader would guess was actively
  wrong: a caller filtering `action == "new-link"` got row 8, a terminal session resumed in
  place, and never row 10, which is what the `--new-link` **flag** does and is recorded as
  `fork`. The whole vocabulary (`refuse`, `nothing`, `wake`, `move`, `resume`,
  `resume-new-link`, `keep-link`, `fork`) is now in the decide tables in docs/design.md,
  README and SKILL.md.
- **Rows 3 and 9 say what they did not carry out.** `--say` is rendered only for the rows that
  deliver a note, so on rows 3 and 9 it was never delivered *and* never mentioned, and a `--to`
  typed at a live-busy session was dropped in silence — row 5 already said so out loud for the
  same reason. `--say`'s own length and leading-`!`/`/` checks have moved out of `revive_note`
  into the plan, so `csm revive X --say "/compact now"` against a limit now reports the prefix
  instead of exiting on the limit with the bad flag unexamined.
- **Row 5 checks that the CLI is on PATH before it claims it will relay anything**, rather than
  discovering it inside `relay_note` and reporting "the note was NOT delivered". It is the part
  of the brief's `preflight(..., copy_only=True)` for the no-window rows that is actually
  applicable; the rest is not, and docs/design.md records that deviation and why.
- **`--version` says 0.5.0**, and `revive --help`'s `--dry-run` line no longer calls itself "the
  only mode that answers today" — it was written while only the diagnosis existed, and a flag's
  own help saying the command does nothing is the one doc nobody re-reads.

### Documentation

- README: a **Revive a dead session** section beside the move narrative — when to use it and when
  opening the link and saying *continue* is the better answer, the decide table in plain words, the
  relay and why the detour is what keeps the attribution honest, the three-line answer as it
  prints, and what it cannot do (make a server respawn a dead child; wake a session by a
  hand-rolled socket frame, which is *held*; keep a server child's link without its server; reach
  a machine that is off). A `csm revive` entry in the command reference with its flags and its
  three exit codes, the new knobs in the Environment tables (`CSM_RELAY_MODEL`,
  `CSM_RELAY_TIMEOUT_S`, `CSM_RELAY_NAME`, `CSM_REVIVE_PROVE_S`, `CSM_REVIVE_TAIL`,
  `CSM_REVIVE_NOTE_MAX`, `CSM_REVIVE_SAY_MAX`, `CSM_REVIVE_LOG`, `CSM_LSOF`, `CSM_RC_JOBS_DIR`),
  the revive phrasings in *From a phone*, and the test count and version stamps brought up to date.
- The `move-session` skill: revive triggers in its description (revive, restore, bring it back, the
  session died, remote control disconnected or offline, it stopped on a limit, continue my dead
  session, a pasted link with nothing answering), a **Revive a session that died** section — the
  dry run first, the decide table, row 9's one tap and the `--new-link` alternative, what to answer
  in three lines plus the link and the title they knew it by, 🛑 that 0 rows is never "no such
  session", and what to say every time about a relayed note, `--to`, a mid-turn stop and lost
  agents — twelve new rows in *Refusals and their fixes*, and two revive boundaries. Two
  phrases of the description paid for the new triggers (`the desktop app's own sessions
  included`, `which live sessions are running weaker than this machine's default`), because the
  harness shows a skill's description to about 1,500 characters when it decides whether to load
  it, and a trigger past the cut is a trigger that never fires. Both are still in the body, and
  the phrases either side of them trigger the same two questions.
- `LESSONS.md`: **L37–L45** in a new section G — the nine lessons this build was bought with, each
  with its measured evidence and the date: the link→transcript arithmetic, a respawned child being
  idle, forking rather than reusing a server child's id, never waking before the reset, a
  hand-rolled peer frame being held where Claude Code's own SendMessage is delivered, a positional
  prompt being recorded as the user's own typing, `--print` workers never auto-resuming at a limit,
  the external-imports dialog blocking an unattended start, and a quota stop that carries no
  `apiError`.
- `docs/design.md`: a **Revive** section (what it reads, the decide table, the one carrier, the
  proof, at-most-once, and the limits), **ten** new rows in the measured-facts table — each stamped
  2.1.312, each with its own re-verification recipe — and the revive knobs in the knob table.
- From the review of this release: `LESSONS.md` gains **L46–L50** (a version-5 id is a server child
  and that survives every file being gone; a `<synthetic>` "No response requested." line is the
  record of a NON-answer; a relay's own transcript lands in the target's home and the cwd moves only
  the slug; a registry `name` is not unique and SendMessage addresses a session by it; a lock whose
  mtime is never touched is breakable in the middle of the work it protects). `docs/design.md` gains
  the row→`action` mapping, the version-5 rung, the one-copy-or-a-refusal rule, where the relay's
  transcript really goes, the name-uniqueness rule, the claim's own stale bound, and — recorded
  rather than hidden — **the one deviation from the implementation brief**: `--from-machine` is
  refused for `revive` rather than built, and `preflight(..., copy_only=True)` for the no-window
  rows is not implementable as written (on row 5 its live-twin check would refuse a session that is
  deliberately alive, which is that row's own condition), so only the part that applies is built.
  README and SKILL.md gain `csm find`'s exit codes, `--account`, and the two refusals to pass on
  as they are written.
- README: a **Start here** part at the top, written for somebody who has never seen this tool and
  meant to be read in five minutes — the four jobs in a table, the one-command install and the one
  config home per account it needs, and three things the page had nowhere before. **What do I give
  csm?** sets every form of session reference side by side, because "is it the session ID?" has two
  answers: the claude.ai link (the one that always works on a stopped session, since the transcript's
  name is computed from it — for a server child by arithmetic, for the rest from the id its own
  transcript records), the bare `session_…` / `cse_…` id that is the same id with the prefix swapped,
  Claude Code's own local id (a uuid, the transcript's file name, which is what `csm list` and
  `csm find` print, 4 characters of it being enough while unique), a spacesheep session page whose
  uuid *is* that local id, a row number from the last `csm list` on this machine, and title words —
  each with an example, where to find it in the app, in a browser and in a terminal, and when to
  prefer it, plus the measured reason a title misses (11% of the sessions a Remote Control server
  started carry a generated title against 64% of the others). **Restart a session that died** is the
  recipe, in order: the app first and when that is the better answer, the `--dry-run`, how to read its
  three lines, what each phrase line 2 can hold means for the command you should then type, what you
  get back and what to do with the old link, `--to` when the account is out of quota, and `csm stop`.
  Then short **Move** and **Find** recipes, **What csm will not do**, and a **Where to read more**
  table into the reference sections. Every command, output phrase and refusal in it was checked
  against the code — `revive --help`, `revive_decide`'s rows, `render_revive`, `revive_act`,
  `pick` / `pick_resolved`, `derive_local_id`, `auto_target` — and the three-line example is a real
  run of the fixtures, not an illustration. Nothing below moved or was renamed: every section and
  anchor is as it was, *Quick start* keeps its heading and its command list with the install block it
  now duplicated trimmed to the two variants, and the fungibility matrix says up front that it is
  reference and can be skipped on a first read.

## [0.4.0] — 2026-10-25

**One engine.** This release merges in a private fork that had been used daily for two weeks and
had grown the features this repository lacked: a permission sweep, a session search, moves between
machines, a quota-driven target and a note that tells the moved session what changed under it.
Everything that was specific to one person's machines left the code on the way over and became a
documented knob, so the merged tool still runs with nothing configured — and the two places where
the fork was *less* careful were not adopted: it copied a project's `memory/` when the target home
had none (this one never copies memory, in any configuration, because that is how stores fork),
and it fell back to an argv name test when a pid's recorded start time was missing (this one
refuses: a name does not say *which* session). A setup with inputs of its own now supplies them
from a wrapper that sets the `CSM_*` variables and `exec`s the tool, instead of carrying a second
copy of the tool.

232 tests became **466**, and CI gained an Ubuntu 22.04 × Python 3.7 cell, so the floor the README
promises is measured rather than claimed, and Python 3.14 cells: from 3.14 pathlib's `exists()` and
`is_file()` answer False on a permission error instead of raising, which made the two refusals
that guard an unreadable project folder pass silently. They now ask `os.stat` directly.

### Added

- **`CSM_TMUX_SESSION`: the tmux session a moved window is opened in**, as a template over
  `{name}`, `{handle}` and `{label}`, still defaulting to `csm-{name}`. For an install that
  already keeps a tmux session per account, `claude-{handle}` puts a moved window in the session
  you already attach to. It is also what makes that choice reversible: `csm stop` looks for a
  `moved-<id8>` window only in the session the spelling in force names, so a window opened under
  one spelling is invisible to `stop` under another — the knob is how you hand the old spelling
  back instead of being told csm has moved nothing here. A template naming a field it does not
  know falls back to the default rather than refusing, and the result is sanitised whatever it
  said: tmux reads `.` and `:` as window and pane, and a leading `-` would reach `tmux -s` as a
  flag.

- **`csm modes`: the permission sweep.** Every live session in every config home here, the mode it
  is *really* in, and whether that is weaker than this machine's `permissions.defaultMode`. It is
  the complement of a settings check: a worker a Remote Control server spawned records the mode
  the stored session record holds, not the one its server was launched with, so a settings file
  can read correct while live sessions sit in `auto` — and nothing looked. It reads every live
  registry row, including the ones `csm list` drops (a server's pre-created session has a 0-byte
  transcript), and where a transcript records no mode it reads the mode off the process's own
  command line. `fault` is only a Remote Control worker in a mode such a worker records by
  accident; `plan`, `acceptEdits` and terminal sessions are `info` and never restarted; what could
  not be read is `unknown`, never `ok`.
  - `--check` prints **one line on stdout and nothing on stderr**, with the exit code agreeing
    with the prefix (`ok:` 0, `FAULT:` 1, `INCOMPLETE:` 3), so a scheduled check can match it.
    Every diagnostic on that path goes to the log, and the credential probe does not run there.
  - `--restart-idle` prints which idle workers a restart would `SIGTERM`, and why each other row
    is refused. `--apply` is **gated and refuses**: the respawn is measured, the mode a respawned
    worker comes back in is not. No environment variable can open the gate — a constant in the
    file is the only switch, because a stray variable in a scheduled pass's environment must never
    be able to stop a session.
- **`csm find TEXT [--on M]`.** Finds a session by id or prefix, claude.ai link or title text in
  *every* config home on a machine — the default one included, where the **desktop app** keeps its
  sessions, with its titles read from the app's own index, which no transcript holds. `--on M`
  runs the search over there by piping a self-contained, standard-library-only, 3.6-safe helper to
  that machine's system python, so nothing has to be installed on the far side; it is read-only
  and run with `-I`. The table labels what it cannot know: the age is the transcript *file's* last
  write, not the last turn, and a moved session shows as two rows, because a move is a copy.
- **Moves between machines: `move <id> --from-machine M`**, with `--mirror-cwd`. The session is
  found over there, the transcript and its sibling directory cross in one `tar` pipe over ssh into
  a staging directory that stays as the record of what crossed, and the copy is resumed here. The
  **source is never stopped** — a process over there may be driving work this tool cannot see —
  and the plan lists what it started that is still running, so `--stop-source` is refused across
  machines. `--mirror-cwd` brings the session's **code** when its folder is only on the other
  machine (git-tracked and untracked, never ignored, 25 MB a file, 2 GB in all, `.git` included);
  data stays where it was made, a folder that already exists here is never written into, and a
  mirror whose remote cannot be pushed over ssh from here gets an https rewrite in its *own*
  `.git/config`.
- **Folder translation between machines** (`CSM_MACHINES`, `CSM_SYNC_DIRS`): named roots present
  on both machines first, longest prefix first, then the home-relative directories that are one
  synced folder everywhere — the rule a sync root needs, because such a directory is usually a
  symlink into the sync client's tree and the transcript records the symlink spelling — then home
  to home. A folder no rule reaches and that is not here is a refusal, not a guess.
- **The move note.** Every move appends one hidden `isMeta` line to the copy, chained by
  `parentUuid`, saying when the session moved, from which account and machine to which, that the
  original still exists, what above it is now stale, where auto-memory is read from, and — across
  machines — that commands now run here, what the mirror brought, what stayed behind and what is
  still running there. A resumed session reads its transcript as its own past: measured, one
  resumed on another machine went looking for a process it had started on the old one, and the
  CLI's own banner told it that background tasks "didn't finish" when they were in fact still
  running over there. `--dry-run` prints it.
- **`move --to auto`**, and a quota meter. `CSM_METERS` names a JSON file of percentages used per
  account, written by whatever tool you like; `auto` takes the account here with the most weekly
  room among those with a *fresh* reading under both cutoffs (`CSM_AUTO_MAX_5H` 90 %,
  `CSM_AUTO_MAX_7D` 95 %) and a usable login, never the source, and prints which one it chose and
  its numbers. With no meter it **refuses**: unread is never room, and a guess here is a move into
  a second exhausted account, which looks exactly like a success. `csm accounts` gains a meter
  column, and a *named* target at or over a cutoff gets a `near its limit` warning with the
  numbers.
- **`--machine M` as the configured spelling of `--ssh HOST`.** `--machine` is checked against the
  machines the configuration knows, refuses this machine ("drop the flag") and names the
  alternatives; `--ssh` still takes any host. Both strip the flag by name and never by value, run
  ssh with `BatchMode` and a connect timeout so an unattended call cannot sit on a password
  prompt, log the remote leg's **exit code** as well as its dispatch, and obey `CSM_REMOTE_CMD` —
  which is how a machine with a wrapper of its own says where its command is, so a remote leg gets
  *that* machine's environment. A remote listing ends by saying whose rows they are.
- **The accounts file reads a tab-separated table**, as a second dialect chosen per line, with the
  columns taken by name from a commented header and otherwise by position (1 name, 2 email, 3
  home, 6 machines, 7 handle) and every other column ignored — so a table some other tool already
  owns can be read where it is, instead of being copied into a second table that goes stale the
  day an account is added. With it:
  - **handles**: a short alias that resolves wherever a name does and is what every listing
    prints, with its shape enforced where it is read (one lower-case `[a-z0-9-]` token, never all
    digits, never leading-hyphen) because `resolve` has an exact rung for it;
  - **`machines`** (against `CSM_MACHINE`, the short hostname by default): a row for another
    machine is not listed, and a row naming *no* machine is listed but refused as a target, so the
    refusal can name it. A file whose `machines` column names this machine nowhere lists every
    account rather than none;
  - 🛑 **`home` may not be `-`, `default` or `~/.claude` in a table**: those are three different
    things, and any non-empty spelling of the default home takes the hashed-Keychain branch onto
    an empty slot that reads exactly like signed out. The simple dialect keeps `-`.
  - A file that mixes the dialects, repeats a name or repeats a handle is refused naming the line.
- **`move --copy-only`**: every refusal, the first-run gates, the copy and the move note — and
  nothing started, for a program that resumes the copy under its own supervision. And **`move
  --from-account A`**, for the case a move creates: after one move the same id is in two homes,
  and `pick` correctly refuses to guess which.
- **A session another program owns is refused**, before the target is even resolved. Where
  `CSM_BOTS_DIR` holds a supervisor's `<name>.json` naming a `session_id`, a plain move would
  start a second copy nothing is talking to while the supervisor kept answering on the old
  account; the refusal names the owner, and `--copy-only` is how that supervisor changes account
  itself. A directory that cannot be *read* is a refusal too, never a "no".
- **Two more notes in the plan**: a **room** note (only with `CSM_ROOM_CMD`) saying whatever runs
  sessions here for the target account has no way into this folder yet — silent when the probe
  exits non-zero, because "could not look" is never a verdict — and a **retention** note when the
  transcript's own file is older than the home's `cleanupPeriodDays`, which prunes.
- **`CSM_KEEP_ENV`**: `CLAUDE*` / `ANTHROPIC*` names the environment scrub puts back for the moved
  session, for a tool *inside* it that needs the same input this one had. Empty by default, and a
  name outside those two families is dropped rather than honoured, so it cannot become a general
  allowlist.
- **`install.sh --no-short-name`**: link the long name only, for a machine where `csm` is already
  a wrapper of your own. Without it the link shadows that wrapper and hands you the tool with none
  of its inputs.

### Changed

- 🛑 **`--limit N` is a hard cap.** It was advertised and inert: live rows were exempt from it, so
  on a machine where every Remote Control worker is a live session `--limit 6` printed 45 rows. It
  now means **at most N rows**, the N newest, live or not, and it outranks `--all` and a session
  pinned by its full id, because `csm move 3` is numbered against the table that was printed. The
  table says how many rows it left out. The default is unchanged at 20 (`CSM_LIMIT`, with
  `CSM_ALL_LIMIT` for `--all`) and still never cuts a live session — "move my *running* session"
  is the common ask, and that session can be the oldest file in the home.
- **The account column in `csm list` and in every message is the handle** where the accounts file
  gives one, and the name otherwise. Its width is measured from the rows, so short handles no
  longer leave the header a column to the right of what is under it.
- **The connector note distinguishes "has used" from "mentions".** A `mcp__…` name is also carried
  by a deferred-tool metadata block, with no call having been made, so a single regex over the
  transcript claimed calls that never happened. The used bucket is matched only where
  `"type":"tool_use"` and the name sit on one JSON line.
- **The live-twin sweep is per home, by resolved `projects/` path.** It used to run only when the
  source and target shared one tree, which is false by construction for a `--from-machine` move —
  the move most likely to overwrite a transcript a live process on a *third* home is writing.
  Measured before the fix: the move completed and copied over that home's transcript. The default
  home is asked first, because the desktop app registers its sessions there and no accounts-file
  row names it.
- **The ambiguous-id guard compares paths by `stat`, not by spelling.** With a shared `projects/`
  tree `normpath` could call one file two paths and manufacture a refusal.
- **This machine's `permissions.defaultMode` is read from `CSM_SHARED_HOME` first** (default
  `~/.claude`), so one shared `settings.json` answers for every account at once, and then from
  each account home, so a home whose symlink has been replaced still reports its own drift. It is
  deliberately *not* where a home's memory store is read from: that is a question about one home,
  which the CLI answers from that home's own settings.
- **The three test-only `CSM_*` switches are dropped from a moved session's environment by name**
  (`CSM_LOGIN_PROBE`, `CSM_REMOTE_LOCAL`, `CSM_REMOTE_HOME`), although `CSM_*` is outside the
  scrubbed families: a stale export inside a window nobody is watching would force a safety
  check's answer, or make "the other machine" that process.
- **The plan's target line uses `→`**, not `->`, which is what a caller parsing the dry run reads.

### Fixed

- **An ssh that never connected read as an answer.** `--machine` / `--ssh` hinted at exit 126 and
  127 but said nothing at **255**, ssh's own "could not connect" — so a machine that was asleep,
  or one reachable only through a VPN that was down, printed ssh's words (`Connection closed by
  UNKNOWN port 65535`) and stopped, which reads exactly like a machine with nothing to list. It now
  names 255 as usually the transport's and not the far side's, says the lines above it are ssh's,
  and gives `ssh <host> true` as the one line that tells which. It claims neither, because a remote
  command may return 255 itself. Both transport hints now say `csm:` like every other line this
  tool addresses to a person; the 126/127 one had said `claude-session-mover:`, so one stderr could
  carry two spellings of the tool's name and read as a third program talking.

- **A home that could not be read was listed as empty.** `pathlib`'s `glob` swallows a
  `PermissionError` from its own directory scan and yields nothing, so an `except OSError` around
  a glob is dead code; the registry read uses `os.listdir`, which raises and is therefore
  *reported* — while a home with no `sessions/` directory stays a quiet zero, because reporting
  that as unread would make every `modes --check` on the machine a permanent `INCOMPLETE:`.
- **A move's own refusals could be blinded the same way, and then opened.** Three of `preflight`'s
  inputs answered "nothing there" for "I was not allowed to look". The live-twin check read an
  unreadable `sessions/` as *no process is running this*, which is the quietest possible path to
  the one outcome that check exists to prevent — two CLIs appending to one transcript. The
  ambiguous-id guard globbed the target's project folders, so a second copy of the id sitting in a
  folder this process may not read was invisible (and the `except OSError` written around the glob
  was dead code); it uses `os.listdir` and a stat per folder now, which also stops treating the
  transcript's own name as a glob pattern. And `Path.exists()` on the destination raised straight
  out of `preflight` — a traceback from the one function whose whole contract is to answer in
  sentences. All three are blockers now, named and reported together like every other refusal, on
  the same doctrine as `login_usable` and the registry read: *could not look* is never a verdict.
  Every guard still asks `preflight`; the plan builder's own stats, which only choose what to
  print about a move that is already refused, answer `False` instead of raising, so `--dry-run`
  prints "a real move would be REFUSED" where it used to print a stack.
- **`__run` deleted the file it was pointed at and started what that file named.** The plan is a
  hand-off read once, so `__run` unlinks it and then execs the program its JSON holds — and
  `make_plan` has stamped `kind` and `version` on every plan since 0.1.0 with nothing ever reading
  them. Pointed by hand or by a typo at some other JSON file, it removed that file and tried to
  start whatever its `claude` key happened to say, in whatever `cwd` it happened to name. The file
  is identified first; nothing is deleted and nothing is started otherwise.
- **A machine with no `permissions.defaultMode` printed a malformed verdict.** `modes --check`
  interpolated the empty reading straight into three of its four lines, so the first thing a fresh
  install saw was `ok: every live session is at  or stronger` — a hole where the mode belongs, in
  the one line this tool promises to keep stable, claiming sessions are at or stronger than a
  baseline that is not there. All four lines now use the `(no defaultMode on this machine)` the
  `INCOMPLETE:` line already carried, which is also the reading `csm modes`' own table has always
  shown as `(none named)`. A machine that names a default — every machine that has been set up,
  and the only case a scheduled caller sees — is unchanged byte for byte.
- **A `ps` that would not answer was read as an empty machine.** The sweep asks `ps` once for the
  whole machine, and `subprocess.run` without `check` raises for nothing — so a `ps` that rejects
  that argument spelling exits non-zero with an empty stdout, and returning a table with no rows
  in it says every process on the machine is gone. The sweep then explained an unread session with
  "pid N is not in `ps` output", a claim about a question it never got to ask, in the one
  `INCOMPLETE:` line a scheduled caller prints. A non-zero exit is "could not be asked" now, which
  is how the per-pid prover beside it has always read the same thing. Whether that one prover
  answered is also carried out of the sweep, as `coverage.ps` in `--json`: every `coverage.unread`
  reason turns on it, and a reader diagnosing an `INCOMPLETE:` otherwise cannot tell a quiet
  machine from a blinded one.
- **`csm modes --apply` on its own** printed the read-only table and exited 0 instead of refusing
  its one destructive flag.
- **`--mirror-cwd` raised an `OSError` mid-move** where no rule mapped the folder and its parent
  here was not writable — the case that section's own comment warns about. It is a one-line
  refusal now.
- **An `effort` value from a plan file is validated** before it is passed to the CLI.
- **A home-relative `CSM_REMOTE_CMD` could not name the other machine's home.** Every token is
  quoted, and `shlex.quote` has to quote both `~/…` and `$HOME/…`, so a wrapper's own path
  reached the far side as a filename whose first component was literally `~` and exited 127 —
  while an absolute path is no answer either, because two machines rarely share a home. A
  leading `~/` or `$HOME/` is now the one part of that variable the remote shell expands.
- **A folder that is not a git tree got `<project>` for its memory store.** The slug is the
  realpath of the worktree root, and returning nothing without one was meant as honesty — but
  the caller then wrote a literal `<project>` into the move note, a path no directory matches,
  handed to a session the same note tells to write its notes nowhere else. Such a folder is
  keyed on the realpath of the folder itself, which is what the store on disk shows.
- **Every log line names the machine the rest of the output does.** It carried the hostname,
  which is often a third name again (a collision suffix, a domain), so a `grep <machine>` over
  the log was incomplete. With nothing configured it still *is* the hostname.
- **`csm matrix` headed its columns with the account's name, not its handle.** It was the one
  command the handle never reached. A matrix column is about ten characters wide — it is one
  column per home — so the heading is truncated, and a layout whose account names share a
  prefix (one login per project, one per client) produced several columns headed with the same
  truncated string and nothing to say which was which: measured on a six-home machine, four of
  the six headings read alike. The notes under the table named the homes the same way, so a
  divergence was reported about a name that was nowhere in the table above it, and the heading
  named the hostname while every other heading names the configured machine. The identity the
  table compares homes by is still the name — a handle that happened to equal another
  account's name must not make one home read as another — and `--json` keeps its `name` field,
  which a cell's `home` names, and gains `handle` beside it as `accounts --json` has. The same
  sweep reached the one ambiguity list that still named accounts by key while the listing it is
  read beside named them by handle.
- **An empty `machines` cell at the END of a table row read as "the column is not there".** The
  two are opposites: an empty cell says this account is on no machine, which is a refusal as a
  move target, while an absent column says the file never said, and then every row is a target.
  Trailing tabs were stripped with the trailing spaces, so the guard opened on exactly the row
  the file had ruled out. A tab is column structure, not whitespace.
- **A numeric knob that is not a number no longer takes the tool down.** All fifteen are read at
  import time, so a `ValueError` there is a traceback *before* `main` has run — on every
  subcommand, `modes --check` included, whose whole promise is one line on stdout and nothing on
  stderr. A scheduled caller then reports a fault in the machine's permission modes when what
  happened is that somebody typed `CSM_LIMIT=lots` in a shell profile. This release added nine
  such knobs, several of them the kind a person really does export, so the reach was new even
  though the shape was not. Each one falls back to its documented default and says so in the log,
  which is the rule the rest of the file already follows for a value it cannot use.
- **`CSM_IMPORTS` is refused inside a config home's `projects/`.** A cross-machine copy is staged
  there, and a leftover staging file is deleted before the fetch so that "the copy did not
  arrive" can be told from "a file was already there" — the one delete in this tool, and it is
  aimed by a knob. Pointed at a `projects/` tree, the first `--from-machine` move of a session
  that home already had would have deleted that home's transcript, which is the one thing this
  tool promises never to do. The knob's own note said never anybody's `projects/`; now something
  holds it to that, by resolved path, before a byte is fetched.

### Documentation

- README: `csm find` and `csm modes` sections; `--to auto`, `--from-machine`, `--mirror-cwd`,
  `--copy-only` and `--from-account` in the `move` table; both accounts-file dialects; **every**
  `CSM_*` knob in the Environment section, grouped, with the test-only ones named; a *Running it
  from a wrapper* note; and the FAQ's "can I move a session to another machine" answer rewritten,
  since the answer is now yes.
- `docs/design.md`: new sections for `--to auto`, the move note, an owned session, between
  machines (including the translation rules and the remote helper) and the permission sweep; the
  accounts section covers both dialects, handles and `machines`; the knob table is complete; the
  step-by-step gains the note and `--copy-only`.
- `docs/setup.md`: the two translation knobs beside the path-mismatch problem, and the skill in
  the per-home checklist, with `--no-short-name`.
- `LESSONS.md`, `docs/lessons.md` and `docs/fungibility-matrix.md`: the statements that a move
  never crosses machines are corrected — with what still does not cross (the data, the devices,
  the jobs) named.
- The `move-session` skill is **one** skill again, merged from both copies: the command map
  checked against `--help`, `modes`, `find`, between-machines moves, `--to auto`, `--limit`, the
  move note, the warnings to pass on, and a refusal table with the fix for each. Nothing in it
  names a particular account, machine or path.

## [0.3.1] — 2026-10-25

Nothing about moving a session changed. CI, the installer and the documentation.

### Fixed

- **The ubuntu CI cells were red for a test, not for the tool.** `csm matrix`'s advice column
  wraps at 100 columns, and two matrix tests matched that prose against the wrapped
  output; on a runner whose `TMPDIR` is a long real path rather than a short symlink, the extra
  path width pushed `point every home's settings.json at one copy` across a line break. The two
  tests now match against the unwrapped text (`" ".join(out.split())`), so what is pinned is the
  advice, not how wide a path prints. The matrix itself was always right. Reproduce the old
  failure on macOS with `TMPDIR=$(cd /some/real/directory && pwd -P) python3 tests/test_mover.py`.
  Still 232 tests.
- **`install.sh` is executable** (it was committed `100644`, so the README's own `./install.sh`
  failed for anyone who cloned the repo), and it now **rejects an unknown option** instead of
  silently installing the command only: the check runs before the first link, `-h`/`--help`
  prints the usage, and anything but `--skill` exits 2.

### Documentation

- README: a CI badge under the title; the Lessons section says "Nine" of the rules, which is how
  many bullets it has; the Environment table gains `CSM_LOG` and `CSM_PICKS`, with one line under
  it naming the test and locked-down-machine knobs (`CSM_LOGIN_PROBE`, `CSM_TMUX_SOCKET`,
  `CSM_NO_HOLD`) and the tuning internals, and pointing at
  [docs/design.md](docs/design.md#env) for the full list.
- `docs/setup.md`: the `projects/` row of "Never link or share these" now states the two costs of
  linking it anyway — on a machine that runs Remote Control servers the accounts' servers
  overwrite one `projects/<slug>/bridge-pointer.json`, and any home still on the default
  `cleanupPeriodDays` prunes every account's history — with the mitigation for each.
- `docs/lessons.md`: links back to `LESSONS.md`, and says that where the two differ `LESSONS.md`
  is the newer measurement (2.1.308, against this page's 2.1.29x–2.1.300).
- The `move-session` skill passes on the `⚠ ONE TRANSCRIPT` warning 0.3.0 added.

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

[0.6.1]: https://github.com/yaroslavvb/claude-session-mover/compare/v0.6.0...v0.6.1
[0.6.0]: https://github.com/yaroslavvb/claude-session-mover/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/yaroslavvb/claude-session-mover/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/yaroslavvb/claude-session-mover/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/yaroslavvb/claude-session-mover/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/yaroslavvb/claude-session-mover/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/yaroslavvb/claude-session-mover/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/yaroslavvb/claude-session-mover/releases/tag/v0.1.0
