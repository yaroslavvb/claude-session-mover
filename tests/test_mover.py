#!/usr/bin/env python3
"""Tests for claude-session-mover: fixtures only. No network, no real account, no real tmux.

    python3 tests/test_mover.py          # or: python3 -m unittest discover -s tests

Every test builds a throwaway world and runs the REAL script as a subprocess, so what is
tested is the command a person types:

    <tmp>/home/.claude/ , <tmp>/home/.claude.json       the default account
    <tmp>/home/.claude-<name>/.claude.json              oauthAccount = the login it holds
    <tmp>/home/.claude-<name>/projects/<folder>/<id>.jsonl
    <tmp>/home/.claude-<name>/sessions/<pid>.json       a live registry row (a real pid)
    <tmp>/bin/claude                                    records argv + env, prints a link
    <tmp>/bin/tmux                                      a fake that RUNS the window command

What fixtures cannot show is whether a copied transcript really resumes under another
login; that was measured instead (docs/design.md, "Measured facts"). These tests guard the
parsing, the matching ladders, every refusal, and the hand-off to the moved window.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "claude-session-mover"
PY = sys.executable
LINK = "https://claude.ai/code/session_01MovedFakeSession42"

FAKE_CLAUDE = r'''#!@PY@
"""A `claude` stand-in: it records every call, and simulates three things HONESTLY — the
three the tool now measures itself against.

  * A RELAY (`-p … "<instruction>"`). It reads the target name and the note out of the
    instruction the way the relay's own Claude would, finds that session's transcript through
    its home's registry, and appends the two lines a delivered peer message really leaves: an
    `isMeta` user line with `turnOrigin: "peer"` and `origin: {kind: "peer", …}` (the shape
    measured in the spike, CLI 2.1.312, Wed 28 Oct 2026), and the assistant line of the turn
    it starts. Then it prints an `--output-format json` result document.
    🛑 WHAT IT DOES NOT SIMULATE IS THE MODEL: it never answers the note, it delivers it.
    `FAKE_RELAY_MODE` picks which honest outcome to simulate — `send` (delivered, a turn
    follows), `busy` (delivered, the row goes busy and no line is written yet), `quiet` (it
    claims success and sends nothing: the case that proves the PROOF is independent of the
    relay's own word), `error`, `crash`, `held` (it never returns).
  * A FORK (`--fork-session --session-id <new>`): it writes `<new>.jsonl` beside the old
    transcript with each line's `sessionId` rewritten, and leaves the old file
    byte-identical — which is what was measured.
  * A session REGISTERING itself (`FAKE_CLAUDE_REGISTER`): `<home>/sessions/<pid>.json`, with
    the `name` its `--remote-control=` label gave it, which is the only way SendMessage can
    address it. 🛑 The pid in that row is a REAL child process named `claude`, never this
    script's own: `still_the_same_process` proves a row by `ps -o lstart=` plus argv[0], and a
    `#!` script's `ps` line names the interpreter — so a row naming this pid could never be
    proved and every wait on one would time out for the wrong reason. The child is killed and
    the row removed when this exits, as a real session's row goes when it ends.
"""
import json, os, re, subprocess, sys, time

ARGV = sys.argv[1:]


def home():
    return os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(os.environ["HOME"], ".claude")


def opt(flag):
    for i, a in enumerate(ARGV):
        if a == flag and i + 1 < len(ARGV):
            return ARGV[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return None


def rows():
    d = os.path.join(home(), "sessions")
    out = []
    for n in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if n.endswith(".json"):
            try:
                out.append((os.path.join(d, n), json.load(open(os.path.join(d, n)))))
            except Exception:
                pass
    return out


def transcript(sid):
    proj = os.path.join(home(), "projects")
    for f in sorted(os.listdir(proj)) if os.path.isdir(proj) else []:
        p = os.path.join(proj, f, sid + ".jsonl")
        if os.path.exists(p):
            return p
    return None


def jwrite(path, d):
    with open(path, "a") as f:
        f.write(json.dumps(d) + "\n")


def _is_devnull():
    """Is fd 0 really /dev/null? — which is what `stdin=subprocess.DEVNULL` makes it.

    🛑 THE ONE THING HERE THAT DEPENDS ON CSM'S CHOICE rather than on the test runner's
    stdin. Compared by (st_dev, st_rdev, st_mode) because /dev/null has no inode number a
    test may rely on.
    """
    try:
        a, b = os.fstat(0), os.stat(os.devnull)
    except OSError:
        return False
    return (a.st_dev, a.st_rdev, a.st_mode) == (b.st_dev, b.st_rdev, b.st_mode)


log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"argv": ARGV, "cwd": os.getcwd(), "env": dict(os.environ)}) + "\n")

# ------------------------------------------------------------------------------- the relay
if "-p" in ARGV:
    instr = ARGV[-1]
    m = re.search(r"named '([^']*)'", instr)
    target = m.group(1) if m else ""
    lines = instr.splitlines()
    marks = [i for i, l in enumerate(lines) if l.startswith("-----")]
    note = "\n".join(lines[marks[0] + 1:marks[1]]) if len(marks) >= 2 else ""
    mode = os.environ.get("FAKE_RELAY_MODE") or "send"
    sid, rowpath, row, seen = "", "", {}, 0
    for p, r in rows():
        if r.get("name") == target:
            seen += 1
            if not sid:
                sid, rowpath, row = r.get("sessionId") or "", p, r
    if os.environ.get("FAKE_RELAY_LOG"):
        jwrite(os.environ["FAKE_RELAY_LOG"],
               {"target": target, "note": note, "sid": sid, "named": seen, "mode": mode,
                "argv": ARGV,
                "cwd": os.getcwd(), "sender": opt("--name") or "",
                "config_dir": os.environ.get("CLAUDE_CONFIG_DIR", ""),
                # 🛑 `isatty` CANNOT MEASURE CSM'S CHOICE HERE. `World.run` passes no
                # `stdin=`, so csm inherits the test runner's stdin, and under
                # `python tests/test_mover.py` — or any redirected run, which is how the
                # suites are run — that is already not a tty: the child reads False whether
                # or not csm closed stdin, and the assertion could not fail. What DOES
                # depend on csm's choice is the identity of fd 0: `subprocess.DEVNULL` makes
                # it /dev/null, and an inherited stdin is anything else.
                "stdin_tty": sys.stdin.isatty(),
                "stdin_devnull": _is_devnull()})
    if mode == "held":
        time.sleep(float(os.environ.get("FAKE_RELAY_HOLD") or 600))
    if mode == "crash":
        sys.stderr.write("fake relay: SendMessage is not a tool here\n")
        sys.exit(9)
    if mode == "error":
        print(json.dumps({"type": "result", "subtype": "error_during_execution",
                          "is_error": True, "num_turns": 1,
                          "result": "SendMessage was not available to me"}))
        sys.exit(int(os.environ.get("FAKE_RELAY_RC") or 0))
    msg = "msg_01FakeRelay%d" % os.getpid()
    if mode in ("send", "busy") and rowpath:
        row["status"] = "busy"
        json.dump(row, open(rowpath, "w"))
    t = transcript(sid) if (mode == "send" and sid) else None
    if t:
        now = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + ".000Z"
        jwrite(t, {"type": "user", "isMeta": True, "turnOrigin": "peer",
                   "isSidechain": False, "sessionId": sid, "cwd": row.get("cwd") or "",
                   "uuid": "peer-%d" % os.getpid(), "timestamp": now,
                   "origin": {"kind": "peer", "name": opt("--name") or "",
                              "fromMode": "bypass", "msg_id": msg,
                              "verifiedPeerPid": os.getpid()},
                   "message": {"role": "user", "content":
                               "Another Claude session sent a message: "
                               "<cross-session-message from-name=\"%s\">%s"
                               "</cross-session-message>" % (opt("--name") or "", note)}})
        jwrite(t, {"type": "assistant", "isSidechain": False, "sessionId": sid,
                   "cwd": row.get("cwd") or "", "uuid": "ans-%d" % os.getpid(),
                   "parentUuid": "peer-%d" % os.getpid(), "timestamp": now,
                   "message": {"role": "assistant", "model": "claude-sonnet-4-5",
                               "content": [{"type": "text",
                                            "text": "picking it up where it stopped"}]}})
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
                      "num_turns": 3, "duration_ms": 6415, "total_cost_usd": 0.00186224,
                      "session_id": "relay-%d" % os.getpid(),
                      "result": "I sent it to `%s` once, verbatim, and the send succeeded "
                                "(%s)." % (target, msg)}))
    sys.exit(int(os.environ.get("FAKE_RELAY_RC") or 0))

# -------------------------------------------------------------------------------- the fork
new_id = opt("--session-id")
if "--fork-session" in ARGV and new_id and not os.environ.get("FAKE_CLAUDE_NOFORK"):
    src = transcript(opt("--resume") or "")
    if src:
        with open(os.path.join(os.path.dirname(src), new_id + ".jsonl"), "w") as out:
            for ln in open(src):
                ln = ln.strip()
                if not ln.startswith("{"):
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(d, dict) and d.get("sessionId"):
                    d["sessionId"] = new_id
                out.write(json.dumps(d) + "\n")

# ------------------------------------------------------------------- registering a session
child = regpath = None
if os.environ.get("FAKE_CLAUDE_REGISTER"):
    d = os.path.join(home(), "sessions")
    os.makedirs(d, exist_ok=True)
    name = ([a.split("=", 1)[1] for a in ARGV if a.startswith("--remote-control=")] or [""])[0]
    child = subprocess.Popen([os.environ["FAKE_CLAUDE_PROCBIN"], "-c", "sleep 120; exit 0"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env = dict(os.environ)
    env["LC_ALL"], env["TZ"] = "C", "UTC"
    env.pop("LC_TIME", None)
    env.pop("LANG", None)
    start = subprocess.run(["ps", "-o", "lstart=", "-p", str(child.pid)],
                           capture_output=True, text=True, env=env).stdout.strip()
    regpath = os.path.join(d, "%d.json" % child.pid)
    json.dump({"pid": child.pid, "sessionId": new_id or opt("--resume") or "",
               "cwd": os.getcwd(), "name": name, "status": "idle", "entrypoint": "cli",
               "procStart": start, "bridgeSessionId": "", "tmux": ""},
              open(regpath, "w"))

append = os.environ.get("FAKE_CLAUDE_APPEND_MODE")
if append:
    sid = ARGV[ARGV.index("--resume") + 1]
    for folder in os.scandir(os.environ["FAKE_CLAUDE_PROJECTS"]):
        p = os.path.join(folder.path, sid + ".jsonl")
        if os.path.exists(p):
            with open(p, "a") as f:
                f.write(json.dumps({"type": "permission-mode", "permissionMode": append}) + "\n")
footer = os.environ.get("FAKE_CLAUDE_FOOTER")
if footer:                      # printed BEFORE the link: the link ends the tool's wait
    print(footer, flush=True)
if any(a.startswith("--remote-control") for a in ARGV) and not os.environ.get("FAKE_CLAUDE_NOURL"):
    # 🛑 A knob, because a resume IN PLACE is proved by the link being the OLD one: the real
    # CLI re-attaches a self-hosted session to its own claude.ai session and mints a new link
    # for anything else, and both outcomes have to be testable.
    print("Remote Control active: %s"
          % (os.environ.get("FAKE_CLAUDE_LINK") or "@LINK@"), flush=True)
print("fake claude running", flush=True)
time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP") or 1.0))
if child is not None:
    try:
        child.kill()
        child.wait()
        os.unlink(regpath)
    except Exception:
        pass
sys.exit(int(os.environ.get("FAKE_CLAUDE_RC") or 0))
'''

#: An `ssh` stand-in: records its whole argv and exits with whatever is asked for. The tool
#: composes one remote shell line, so what it would really have run is argv[-1].
FAKE_SSH = r'''#!@PY@
import json, os, sys
with open(os.environ["FAKE_SSH_LOG"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\n")
sys.stdout.write(os.environ.get("FAKE_SSH_STDOUT") or "")
sys.exit(int(os.environ.get("FAKE_SSH_RC") or 0))
'''

#: An `lsof -a -d cwd -F pn -p <comma list>` stand-in, in the machine-readable form csm
#: asks for: it answers from a JSON map of `{"<pid>": "<cwd>"}` and exits with whatever is
#: asked for. 🛑 A fixture world has no `claude remote-control` SERVER in it — the question
#: "is a server up in this folder" is about the machine's own process table — so the suite
#: answers it here rather than letting a test read the machine, where the answer changes
#: between runs and between machines.
FAKE_LSOF = r'''#!@PY@
import json, os, shutil, sys
# 🛑 THE OTHER RACE FIXTURE (`FAKE_TMUX_ARM_FROM` is the first). This one fires INSIDE the
# diagnosis: `diagnose` reads whether anything is running the session before it asks whether a
# server is up in its folder, and that question is the `lsof`. So a file copied into place
# here lands between those two reads — which is the pane of time a wake is about, the session
# having been proved alive a moment before the note is sent to it.
_arm = os.environ.get("FAKE_LSOF_ARM_FROM")
if _arm and os.path.exists(_arm):
    shutil.copyfile(_arm, os.environ["FAKE_LSOF_ARM_TO"])
    os.unlink(_arm)
rc = int(os.environ.get("FAKE_LSOF_RC") or 0)
path = os.environ.get("FAKE_LSOF_MAP") or ""
m = {}
if path and os.path.exists(path):
    m = json.load(open(path))
want = sys.argv[sys.argv.index("-p") + 1].split(",") if "-p" in sys.argv else []
for pid in want:
    if pid in m:
        print("p%s" % pid)
        print("fcwd")
        print("n%s" % m[pid])
sys.exit(rc)
'''

FAKE_TMUX = r'''#!@PY@
"""A tmux stand-in: sessions and windows live in a JSON file; a new window's command REALLY
runs (in the background, output to a pane file); capture-pane prints that file, or the next
scripted screen when FAKE_TMUX_SCRIPT holds some. Windows carry ids (@1, @2, ...) as the
real one does, and kill-window removes them: both are what `csm stop` depends on."""
import json, os, shutil, signal, subprocess, sys
st_path = os.environ["FAKE_TMUX_STATE"]
calls = os.environ["FAKE_TMUX_CALLS"]
args = sys.argv[1:]
with open(calls, "a") as f:
    f.write(json.dumps(args) + "\n")
# 🛑 A RACE FIXTURE, and the only way to write one. `FAKE_TMUX_ARM_FROM`/`_TO` copies one
# file into place the FIRST time tmux is called, which in a real `csm revive` is inside
# `preflight` — after the diagnosis has read every registry and before the start gate re-reads
# them. That is exactly when a Remote Control server's LAZY respawn appears: the app opens the
# link while csm is deciding, and a live registry row the diagnosis could not have seen is
# suddenly there. Nothing else in this suite can make something appear between two reads.
_arm = os.environ.get("FAKE_TMUX_ARM_FROM")
if _arm and os.path.exists(_arm):
    shutil.copyfile(_arm, os.environ["FAKE_TMUX_ARM_TO"])
    os.unlink(_arm)
env_log = os.environ.get("FAKE_TMUX_ENV")
if env_log:
    with open(env_log, "a") as f:
        f.write(json.dumps(dict(os.environ)) + "\n")
if args[:1] == ["-L"]:
    args = args[2:]                      # the private socket a test suite asks for
try:
    st = json.load(open(st_path))
except (OSError, ValueError):
    st = {"sessions": {}, "next": 1}
st.setdefault("next", 1)
for _s, _wins in st["sessions"].items():         # a test may write a bare pane path
    for _w, _v in list(_wins.items()):
        if not isinstance(_v, dict):
            _wins[_w] = {"pane": _v, "id": "@%d" % st["next"]}
            st["next"] += 1
def save():
    json.dump(st, open(st_path, "w"))
def opt(flag):
    return args[args.index(flag) + 1] if flag in args else None
def target():
    t = opt("-t") or ""
    if not t.startswith("="):
        sys.stderr.write("fake tmux: inexact target " + t + "\n")
        sys.exit(3)
    sess, _, win = t[1:].partition(":")
    return sess, win.lstrip("=")
cmd = args[0]
if cmd == "has-session":
    sys.exit(0 if target()[0] in st["sessions"] else 1)
if cmd == "list-windows":
    s = target()[0]
    if s not in st["sessions"]:
        sys.exit(1)
    fmt = opt("-F") or "#{window_name}"
    for name, w in st["sessions"][s].items():
        print(fmt.replace("#{window_id}", w["id"]).replace("#{window_name}", name))
    sys.exit(0)
if cmd in ("new-session", "new-window"):
    sess = opt("-s") if cmd == "new-session" else target()[0]
    win, cwd, shell_cmd = opt("-n"), opt("-c"), args[-1]
    wid = "@%d" % st["next"]
    # 🛑 One pane file per window ID, not per window NAME. A window opened again under the
    # same name (a second move after `csm stop`) used to share its file with the first
    # window's process, which could still write its "=== claude exited" trailer over the
    # new link: `Stop.test_a_second_move_is_accepted_again_once_the_window_is_gone` failed
    # that way on GitHub's runners (Sun 25 Oct and Wed 28 Oct 2026).
    pane = os.path.join(os.path.dirname(st_path), "pane-%s-%s-%s.txt" % (sess, win, wid[1:]))
    st["sessions"].setdefault(sess, {})[win] = {"pane": pane, "id": wid}
    st["next"] += 1
    out = open(pane, "w")
    p = subprocess.Popen(["/bin/sh", "-c", shell_cmd], cwd=cwd, stdout=out,
                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    st["sessions"][sess][win]["pgid"] = p.pid
    save()
    sys.exit(0)
if cmd == "kill-window":
    sess, win = target()
    if win not in st["sessions"].get(sess, {}):
        sys.exit(1)
    gone = st["sessions"][sess].pop(win)
    save()
    # What the real tmux does to a pane's processes when its window is destroyed: SIGHUP.
    if isinstance(gone, dict) and gone.get("pgid"):
        try:
            os.killpg(gone["pgid"], signal.SIGHUP)
        except OSError:
            pass
    sys.exit(0)
if cmd == "capture-pane":
    sess, win = target()
    if win not in st["sessions"].get(sess, {}):
        sys.exit(1)
    script = os.environ.get("FAKE_TMUX_SCRIPT")
    if script and os.path.exists(script):
        screens = json.load(open(script))
        if screens:
            print(screens.pop(0))
            json.dump(screens, open(script, "w"))
            sys.exit(0)
    print(open(st["sessions"][sess][win]["pane"]).read())
    sys.exit(0)
if cmd == "send-keys":
    target()
    sys.exit(0)
sys.exit(0)
'''


def load_tool():
    """Import the tool as a module, for the pure functions.

    🛑 The module must be in `sys.modules` BEFORE it is executed: `Session` is a dataclass
    under `from __future__ import annotations`, and dataclass resolves its annotations
    through `sys.modules[cls.__module__]`.
    """
    loader = importlib.machinery.SourceFileLoader("csm_mod", str(TOOL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["csm_mod"] = mod
    loader.exec_module(mod)
    return mod


def jl(*rows) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def ps_start(pid: int) -> str:
    """`LC_ALL=C TZ=UTC ps -o lstart= -p <pid>` — exactly as the CLI WRITES it.

    🛑 This mirrors the WRITER, not the tool. A helper that copies whatever the tool does
    agrees with the tool by construction, so it can never catch the tool asking `ps` a
    different question from the one that produced the registry value — which is how the
    missing `LC_ALL=C` survived: `ps -o lstart=` prints month and weekday names in the
    caller's locale.

    ⚠️ Never hardcode a date: macOS (BSD) and Linux (procps-ng) format and pad this
    differently, which is why the tool compares it whitespace-normalised.
    """
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env["TZ"] = "UTC"
    env.pop("LC_TIME", None)
    env.pop("LANG", None)
    try:
        r = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True,
                           text=True, timeout=10, env=env)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def a_foreign_locale() -> str:
    """An installed non-C locale whose `ps -o lstart=` differs from the C one, or `""`."""
    probe = os.getpid()
    base = ps_start(probe)
    if not base:
        return ""
    for loc in ("fr_FR.UTF-8", "de_DE.UTF-8", "es_ES.UTF-8", "ja_JP.UTF-8", "C.UTF-8"):
        env = dict(os.environ)
        env["LC_ALL"] = loc
        env["TZ"] = "UTC"
        try:
            r = subprocess.run(["ps", "-o", "lstart=", "-p", str(probe)],
                               capture_output=True, text=True, timeout=10, env=env)
        except (OSError, subprocess.SubprocessError):
            continue
        if r.returncode == 0 and (r.stdout or "").strip() != base:
            return loc
    return ""


def user(text, cwd, sid, perm=None, sidechain=False, uuid=None, parent=None):
    """⚠️ `uuid` is OPTIONAL and off by default, which is deliberate: most tests do not
    care, and a transcript the CLI wrote always has one. Pass it where the CHAIN matters —
    the move note hangs off the last main-chain line that carries a uuid, and a fixture
    with none proves nothing about where the note lands."""
    d = {"type": "user", "cwd": cwd, "sessionId": sid, "isSidechain": sidechain,
         "message": {"role": "user", "content": text}}
    if perm:
        d["permissionMode"] = perm
    if uuid:
        d["uuid"], d["parentUuid"] = uuid, parent
    return d


def assistant(text, cwd, sid, model="claude-sonnet-4-5", error=None, resets=None,
              kind="five_hour", uuid=None, parent=None, tools=(), shape="apiError",
              synthetic=False, api_error_only=None):
    """`tools` are MCP tool names, written as real `tool_use` blocks: a name in a block of
    this shape is a CALL, which is what tells `mcp_used` from `mcp_servers`.

    🛑 `shape` IS WHICH OF THE TWO MEASURED QUOTA-STOP SHAPES `error` is written as, and
    the default is the one with an `apiError` so every older test is byte-for-byte what it
    was. Measured on CLI 2.1.312, Wed 28 Oct 2026: of 44 assistant quota-stop lines in the
    config homes on this machine, 34 carry `apiError` + `apiErrorParams.rate_limit_info`
    and 10 carry no `apiError` key at all — only `isApiErrorMessage: true`,
    `error: "rate_limit"`, `apiErrorStatus: 429` and a top-level `quotaLimits`
    ({status: "rejected", resetsAt: <unix s>, rateLimitType: "five_hour"|"seven_day", …}).
    `shape="rate_limit"` writes that second one.

    🛑 `synthetic=True` IS THE LINE THAT RECORDS A NON-ANSWER: no error keys at all, model
    `<synthetic>`, text "No response requested." — what the CLI writes when an injected
    `isMeta` prompt produced NOTHING. Measured here Wed 28 Oct 2026 on CLI 2.1.312: 23 such
    lines in 20 of the 1,943 transcripts in the config homes on this machine, every one with
    that exact text. It wears a clean line's clothes, and both readers of a transcript used
    to count it as the session answering again.
    🛑 `api_error_only="<kind>"` is the OTHER member of the no-`apiError` family: an error
    that is not a limit (`api_error_overloaded`, 529), carrying `isApiErrorMessage` and no
    `apiError` key. "An error that is not a limit is not the session answering again", which
    the clean branch's comment said while the code counted it.
    """
    d = {"type": "assistant", "cwd": cwd, "sessionId": sid, "isSidechain": False,
         "message": {"role": "assistant", "model": model,
                     "content": [{"type": "text", "text": text}]
                     + [{"type": "tool_use", "name": t, "id": "tu_%d" % i, "input": {}}
                        for i, t in enumerate(tools)]}}
    if uuid:
        d["uuid"], d["parentUuid"] = uuid, parent
    if synthetic:
        d["message"]["model"] = "<synthetic>"
    if api_error_only:
        d["isApiErrorMessage"] = True
        d["error"] = api_error_only
        d["apiErrorStatus"] = 529
        d["message"]["model"] = "<synthetic>"
    if error:
        d["message"]["model"] = "<synthetic>"
        if shape == "apiError":
            d["apiError"] = error
            d["apiErrorParams"] = {"rate_limit_info": {"rateLimitType": kind,
                                                       "resetsAt": resets}}
        else:
            d["isApiErrorMessage"] = True
            d["error"] = "rate_limit"
            d["apiErrorStatus"] = 429
            d["quotaLimits"] = {"status": "rejected", "resetsAt": resets,
                                "rateLimitType": kind, "overageStatus": "rejected",
                                "isUsingOverage": False}
    return d


class World:
    def __init__(self, root: Path):
        self.root = root
        self.home = root / "home"
        self.home.mkdir()
        self.bin = root / "bin"
        self.bin.mkdir()
        self.work = root / "work"
        self.work.mkdir()
        self.state = root / "state"
        self.claude_log = root / "claude.jsonl"
        self.tmux_calls = root / "tmux-calls.jsonl"
        self.tmux_state = root / "tmux-state.json"
        self.tmux_env = root / "tmux-env.jsonl"
        self.ssh_log = root / "ssh-calls.jsonl"
        self.lsof_map = root / "lsof-map.json"
        #: What the relay was asked to deliver, to whom, and from which config home: one
        #: line per `claude -p` the tool ran. It is the only place the note's text can be
        #: compared with what the tool said it would send.
        self.relay_log = root / "relay.jsonl"
        #: 🛑 WHAT fd 0 IS WHEN csm RUNS, and deliberately neither the test runner's own stdin
        #: nor /dev/null. csm must CLOSE stdin for the `claude -p` relay it starts (a `-p` run
        #: with a terminal on stdin waits for input that never comes), and the only way a test
        #: can tell that apart from "it passed on whatever it was handed" is for what it was
        #: handed to be something else. An empty regular file reads EOF at once, is never a
        #: tty, and is not /dev/null — so the fake claude's `_is_devnull()` measures csm's own
        #: choice rather than how this suite happened to be invoked (under `python
        #: tests/test_mover.py` with output redirected, which is how the README says to run it,
        #: the runner's stdin is already not a tty and may already be /dev/null).
        self.stdin_file = root / "parent-stdin"
        self.stdin_file.write_text("")
        for name, body in (("claude", FAKE_CLAUDE), ("tmux", FAKE_TMUX),
                           ("fake-ssh", FAKE_SSH), ("fake-lsof", FAKE_LSOF)):
            p = self.bin / name
            p.write_text(body.replace("@PY@", PY).replace("@LINK@", LINK))
            p.chmod(0o755)
        # 🛑 A stand-in for a running session has to be a real executable NAMED claude:
        # the pid guard reads argv[0]'s basename, and a `#!` script's ps line names the
        # interpreter instead. A symlink to /bin/sleep behaves the same on macOS and Linux.
        self.procbin = root / "procbin"
        self.procbin.mkdir()
        # 🛑 A COPY OF /bin/sh, NOT A SYMLINK TO /bin/sleep (Wed 28 Oct 2026). On Ubuntu 26.04
        # `sleep` is a multicall binary (Rust coreutils) that dispatches on the name it was run
        # by, so a `claude` symlink to it exited 1 at once: 56 tests failed on GitHub's
        # ubuntu-latest. A shell run as `claude -c 'sleep 120; exit 0'` keeps its own argv[0]
        # whatever the coreutils are — the shape `spawn(argv_tail=…)` and `server()` use.
        shutil.copy("/bin/sh", str(self.procbin / "claude"))
        self.procs = []

    # --- homes ------------------------------------------------------------
    def account(self, name, email=None, org="org-1", default=False, mode=0o600, **extra):
        h = self.home / ".claude" if default else self.home / f".claude-{name}"
        (h / "projects").mkdir(parents=True, exist_ok=True)
        state = self.home / ".claude.json" if default else h / ".claude.json"
        d = dict(extra)
        if email:
            d["oauthAccount"] = {"emailAddress": email, "organizationUuid": org}
        state.write_text(json.dumps(d))
        state.chmod(mode)
        return h

    def table(self, *rows, **kw):
        """A TAB-separated accounts table, the dialect a table another tool keeps is in.

        Each row is `(name, email, home, machines, handle)`. Columns 4, 5 and 8 are filled
        with `-` so the POSITIONS the readers hard-code (3 home, 6 machines, 7 handle) are
        the ones exercised, and `header=False` drops the commented header line so the
        positional fallback is exercised too.
        """
        lines = []
        if kw.get("header", True):
            lines.append("# " + "\t".join(kw.get("names") or (
                "name", "email", "home", "tmux", "tmux_other", "machines", "handle",
                "roles")))
        for name, email, home, machines, handle in rows:
            lines.append("\t".join([name, email, str(home), "-", "-", machines, handle,
                                    "-"]))
        p = self.root / "accounts.tsv"
        p.write_text("\n".join(lines) + "\n")
        return p

    def meters(self, **readings):
        """`name_or_handle=(five_hour %, seven_day %, age in seconds)` -> the meter file."""
        now = time.time()
        p = self.root / "meters.json"
        p.write_text(json.dumps({
            k: {"at": now - age, "five_hour": fh, "seven_day": sd, "error": "",
                "resets_at": ""} for k, (fh, sd, age) in readings.items()}))
        return p

    def session(self, home, sid, cwd=None, lines=None, folder=None, mtime=None, sibling=False):
        cwd = cwd or str(self.work)
        folder = folder or "-" + "".join(c if c.isalnum() else "-" for c in cwd).lstrip("-")
        d = home / "projects" / folder
        d.mkdir(parents=True, exist_ok=True)
        t = d / f"{sid}.jsonl"
        t.write_text(jl(*(lines if lines is not None else [
            user("fix the parser", cwd, sid, perm="acceptEdits"),
            assistant("done", cwd, sid)])))
        if sibling:
            (d / sid / "subagents").mkdir(parents=True)
            (d / sid / "subagents" / "agent-1.jsonl").write_text("{}\n")
        if mtime:
            os.utime(str(t), (mtime, mtime))
        return t

    def spawn(self, name="claude", argv_tail=()):
        """A real process standing for a running session, running an executable named
        `claude` (or `sleep`, for the negative case).

        With `argv_tail` the executable is a COPY of /bin/sh instead, run as
        `claude -c 'sleep N; exit 0' <tail>`, so a test can put flags like
        `--permission-mode bypassPermissions` on a live process's real command line — which
        is where `modes` reads a launch mode from. ⚠️ `sleep N; exit 0`, not `sleep N`: a
        shell given ONE simple command execs it and loses its own argv, so the flags this
        was spawned for would vanish from `ps`.
        """
        if argv_tail:
            d = self.root / ("shbin%d" % len(self.procs))
            d.mkdir(exist_ok=True)
            exe = d / name
            shutil.copy("/bin/sh", str(exe))
            cmd = [str(exe), "-c", "sleep 120; exit 0"] + list(argv_tail)
        else:
            if name == "claude":
                cmd = [str(self.procbin / "claude"), "-c", "sleep 120; exit 0"]
            else:
                cmd = ["/bin/sleep", "120"]
        p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def server(self, name="myproject"):
        """A real process whose `ps` line reads `…/claude remote-control --name <name>` —
        the shape `RC_SERVER_RE` recognises as a Remote Control SERVER.

        🛑 `spawn(argv_tail=…)` cannot make this one: its `claude -c 'sleep …' <tail>` puts
        the shell's own flag between argv[0] and the subcommand, and the real server's argv
        has the word right after the binary. So the subcommand here is a real script file
        of that name, run with the directory as the cwd. ⚠️ `sleep 120` + `exit 0` for the
        same reason as `spawn`: a shell handed one simple command execs it and loses its
        argv.
        """
        d = self.root / ("srvbin%d" % len(self.procs))
        d.mkdir(exist_ok=True)
        shutil.copy("/bin/sh", str(d / "claude"))
        (d / "remote-control").write_text("sleep 120\nexit 0\n")
        p = subprocess.Popen([str(d / "claude"), "remote-control", "--name", name],
                             cwd=str(d), stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def live(self, home, sid, pid, cwd=None, bridge=None, status="idle", tmux="",
             proc_start=None, entrypoint="sdk-cli", name="rc-name", path=None):
        """A live registry row. `name` is what SendMessage addresses the session BY, so a
        test about waking one either names it or proves what happens when it has no name;
        `path` writes the row somewhere else, for a row that is to appear LATER."""
        (home / "sessions").mkdir(exist_ok=True)
        row = {"pid": pid, "sessionId": sid, "cwd": cwd or str(self.work),
               "bridgeSessionId": bridge or "", "status": status, "entrypoint": entrypoint,
               "name": name, "tmux": tmux}
        if proc_start is None:
            proc_start = ps_start(pid)       # read with the tool's own command, never hardcoded
        if proc_start:
            row["procStart"] = proc_start
        (path or (home / "sessions" / f"{pid}.json")).write_text(json.dumps(row))
        return row

    # --- running ----------------------------------------------------------
    def env(self, **extra):
        e = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
             "CSM_STATE_DIR": str(self.state), "CSM_CLAUDE": str(self.bin / "claude"),
             "CSM_TMUX": str(self.bin / "tmux"), "CSM_POLL": "0.05",
             # ⚠️ A ceiling, not a duration: the fake claude either prints the link or
             # exits, and `wait_window` ends on either, so no test ever waits this out.
             # It was 6s, which a loaded CI runner can miss — a flake that looks exactly
             # like the bug the test is for.
             "CSM_CONNECT_WAIT": "30", "CSM_SETTLE": "0.3", "CSM_NO_HOLD": "1",
             # 🛑 No test ever asks a real credential store: the probe is forced, and the
             # tool says so on stderr every time it is.
             "CSM_LOGIN_PROBE": "true",
             # 🛑 And no test asks the real `lsof` either: a fixture world holds no Remote
             # Control server, so the folder question is answered by the stand-in.
             "CSM_LSOF": str(self.bin / "fake-lsof"), "FAKE_LSOF_MAP": str(self.lsof_map),
             "FAKE_CLAUDE_LOG": str(self.claude_log), "FAKE_TMUX_CALLS": str(self.tmux_calls),
             "FAKE_TMUX_STATE": str(self.tmux_state), "LC_ALL": "C.UTF-8",
             # The relay, and the proof after it: bounds small enough that a test which is
             # MEANT to time out does so in a second, and large enough that one which is not
             # never does. Neither is ever waited out by a passing test — the fake relay
             # either delivers or says it could not.
             "CSM_RELAY_TIMEOUT_S": "30", "CSM_REVIVE_PROVE_S": "8",
             "FAKE_RELAY_LOG": str(self.relay_log),
             # 🛑 The executable a registered session's pid really runs: argv[0]'s basename
             # has to be `claude` for `still_the_same_process` to prove the row at all.
             "FAKE_CLAUDE_PROCBIN": str(self.procbin / "claude")}
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def run(self, *args, **env):
        with open(str(self.stdin_file)) as fd0:          # see `stdin_file`'s 🛑
            return subprocess.run([PY, str(TOOL), *args], capture_output=True, text=True,
                                  env=self.env(**env), timeout=60, stdin=fd0)

    def claude_calls(self, wait=3.0):
        deadline = time.time() + wait
        while time.time() < deadline:
            if self.claude_log.exists() and self.claude_log.read_text().strip():
                break
            time.sleep(0.05)
        if not self.claude_log.exists():
            return []
        return [json.loads(x) for x in self.claude_log.read_text().splitlines() if x.strip()]

    def tmux_log(self):
        if not self.tmux_calls.exists():
            return []
        return [json.loads(x) for x in self.tmux_calls.read_text().splitlines() if x.strip()]

    def relay_calls(self):
        """One entry per `claude -p` relay the tool ran: target, note, sender, config home."""
        if not self.relay_log.exists():
            return []
        return [json.loads(x) for x in self.relay_log.read_text().splitlines() if x.strip()]

    def windows(self):
        """`{tmux session: [window names]}` as the fake tmux holds them right now."""
        try:
            st = json.loads(self.tmux_state.read_text())
        except (OSError, ValueError):
            return {}
        return {s: sorted(w) for s, w in (st.get("sessions") or {}).items()}

    def close(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()


SID_A = "11111111-aaaa-4aaa-8aaa-111111111111"
SID_B = "22222222-bbbb-4bbb-8bbb-222222222222"
SID_C = "33333333-cccc-4ccc-8ccc-333333333333"

#: 🛑 TWO MEASURED PAIRS, NOT TWO INVENTED ONES. A Remote Control session's local id is
#: `uuid5(3ab19d7e-9f35-45c2-926e-75e271cc60b3, "https://api.anthropic.com/v1/code/
#: sessions/cse_<bare>")`, and these two pairs were read off this machine (CLI 2.1.312,
#: Wed 28 Oct 2026, 37/37 live registry rows carrying both ids). They are written out
#: rather than computed here on purpose: a fixture that derives the id with the same
#: arithmetic as the tool agrees with the tool by construction and could never catch the
#: namespace, the name form or the prefix rule changing. ⚠️ If one of these ever fails,
#: the CLI changed: re-measure against a live registry row, do not edit the constant.
LINK_BARE = "01PHXskvoLtckdvqFv3F8rei"
LINK_SID = "bf974a77-c0b0-5763-81be-f057a3dc7e57"
LINK_BARE2 = "01PHXskvDdMLxdjXDuoZkBpF"
LINK_SID2 = "38ffa06c-4d9a-5981-96b0-a3447ac0c094"

#: ⚠️ COMPUTED, NOT MEASURED, and used only where a server child has to read as DEAD. The
#: two pairs above are REAL sessions on the machine this was written on, and `revive`'s
#: machine-wide `ps` sweep correctly finds them — so a test that needs a dead server child
#: (the fork) has to name a bridge session nothing is running. This pair is the same
#: arithmetic applied to an id no session ever had, so it proves the ROW and never the
#: derivation: that is what `DeriveId`, `Picking` and `ReviveDryRun` use the measured pairs
#: for. Recomputed with: uuid5(UUID("3ab19d7e-9f35-45c2-926e-75e271cc60b3"),
#: "https://api.anthropic.com/v1/code/sessions/cse_" + FORK_BARE).
FORK_BARE = "01PHXcsmForkFixture0001"
FORK_SID = "d77f5fa0-58ab-546f-aa71-01acb730df58"


def link_of(bare):
    return "https://claude.ai/code/session_" + bare


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.w = World(Path(self._tmp.name))
        self.work = self.w.account("work", "me@work.example")
        self.personal = self.w.account("personal", "me@home.example", org="org-2")

    def tearDown(self):
        self.w.close()
        self._tmp.cleanup()

    def ok(self, r):
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def refused(self, r, *needles):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        for n in needles:
            self.assertIn(n, r.stderr)
        return r.stderr

    def listing(self, *extra):
        return json.loads(self.ok(self.w.run("list", "--json", *extra)))


# ------------------------------------------------------------------------------ accounts

class Accounts(Base):
    def test_discovers_default_and_dash_homes(self):
        self.w.account("default", "me@default.example", default=True)
        rows = json.loads(self.ok(self.w.run("accounts", "--json")))
        by = {r["name"]: r for r in rows}
        self.assertEqual(set(by), {"default", "work", "personal"})
        self.assertTrue(by["default"]["default"])
        # the default home's login lives in ~/.claude.json, OUTSIDE ~/.claude
        self.assertEqual(by["default"]["email"], "me@default.example")
        self.assertEqual(by["work"]["state"], "ok")

    def test_signed_out_home_is_shown(self):
        self.w.account("spare")
        by = {r["name"]: r for r in json.loads(self.ok(self.w.run("accounts", "--json")))}
        self.assertEqual(by["spare"]["state"], "signed out")

    def test_accounts_file_replaces_discovery_and_checks_the_login(self):
        cfg = self.w.root / "accounts"
        cfg.write_text("# name home email\njob ~/.claude-work me@other.example\n"
                       "me  ~/.claude-personal\n")
        by = {r["name"]: r for r in json.loads(
            self.ok(self.w.run("accounts", "--json", CSM_ACCOUNTS=cfg)))}
        self.assertEqual(set(by), {"job", "me"})
        self.assertTrue(by["job"]["state"].startswith("WRONG LOGIN"))

    def test_accounts_file_errors_are_refusals(self):
        cfg = self.w.root / "accounts"
        cfg.write_text("job ~/.claude-work\njob ~/.claude-personal\n")
        self.refused(self.w.run("accounts", CSM_ACCOUNTS=cfg), "used twice")


class AccountsTable(Base):
    """The TAB-separated dialect: columns by header name or by position, handles, the
    `machines` column, and the refusals that keep a table row from naming a home that is
    nobody's."""

    def setUp(self):
        super().setUp()
        self.spare = self.w.account("spare", "me@spare.example", org="org-3")

    def rows(self, tsv, machine="laptop", *extra):
        return {r["name"]: r for r in json.loads(self.ok(self.w.run(
            "accounts", "--json", *extra, CSM_ACCOUNTS=tsv, CSM_MACHINE=machine)))}

    def two_rows(self, **kw):
        return self.w.table(("job", "me@work.example", self.work, "laptop,desktop", "wk"),
                            ("me", "me@home.example", self.personal, "laptop", "mine"),
                            **kw)

    def test_a_table_names_the_homes_and_carries_the_handles(self):
        by = self.rows(self.two_rows())
        self.assertEqual(set(by), {"job", "me"})
        self.assertEqual(by["job"]["handle"], "wk")
        self.assertEqual(by["job"]["home"], str(self.work))
        self.assertEqual(by["job"]["email"], "me@work.example")
        self.assertEqual(by["job"]["machines"], ["laptop", "desktop"])
        # discovery is replaced entirely, so a home the table leaves out is not an account
        self.assertNotIn("spare", by)

    def test_columns_are_read_by_header_name_when_the_header_moves_them(self):
        # The point of reading the header first: a table that re-orders or inserts a column
        # is survived by NAME. Here `home` and `email` are swapped and a column is added.
        p = self.w.root / "accounts.tsv"
        p.write_text("# key\thome\tnote\temail\tmachines\thandle\n"
                     + "\t".join(["job", str(self.work), "x", "me@work.example", "laptop",
                                  "wk"]) + "\n")
        by = self.rows(p)
        self.assertEqual(by["job"]["home"], str(self.work))
        self.assertEqual(by["job"]["email"], "me@work.example")
        self.assertEqual(by["job"]["handle"], "wk")

    def test_a_header_calling_the_first_column_n_is_still_read(self):
        by = self.rows(self.two_rows(names=("n", "email", "home", "a", "b", "machines",
                                            "handle", "roles")))
        self.assertEqual(set(by), {"job", "me"})
        self.assertEqual(by["me"]["handle"], "mine")

    def test_with_no_header_the_documented_positions_are_used(self):
        by = self.rows(self.two_rows(header=False))
        self.assertEqual(set(by), {"job", "me"})
        self.assertEqual(by["job"]["home"], str(self.work))
        self.assertEqual(by["job"]["handle"], "wk")

    def test_an_empty_machines_cell_at_the_END_of_a_row_still_says_no_machine(self):
        """🛑 A TAB IS NOT TRAILING WHITESPACE, and the two answers are opposites.

        `machines` empty means "on no machine", which `check_target` refuses as a move
        target; the column being ABSENT means the file never said, and then every row is a
        target. A plain `rstrip()` of the line turns the first into the second whenever the
        empty cell is the last one on the row — so the guard opened on exactly the row the
        file had ruled out.
        """
        head = "# name\temail\thome\tx\tx\tmachines\thandle\n"
        src = "\t".join(["me", "me@home.example", str(self.personal), "-", "-",
                         "laptop", "mine"]) + "\n"
        p = self.w.root / "accounts.tsv"
        # the LAST two cells of the `job` row are empty, and the row ends there
        p.write_text(head + src
                     + "\t".join(["job", "me@work.example", str(self.work), "-", "-"])
                     + "\t\t\n")
        by = self.rows(p)
        self.assertEqual(by["job"]["machines"], [])        # said, and said "none"
        self.assertEqual(by["job"]["handle"], "")
        cwd = str(self.w.work)
        self.w.session(self.personal, SID_A, lines=[user("go", cwd, SID_A),
                                                    assistant("ok", cwd, SID_A)])
        self.refused(self.w.run("move", SID_A, "--to", "job", "--dry-run",
                                CSM_ACCOUNTS=p, CSM_MACHINE="laptop"),
                     "is on no machine")
        # and a NARROW table, which really has not said, keeps every row a target
        q = self.w.root / "narrow.tsv"
        q.write_text("# name\temail\thome\n"
                     "me\tme@home.example\t%s\njob\tme@work.example\t%s\n"
                     % (self.personal, self.work))
        self.assertIsNone(self.rows(q)["job"]["machines"])
        self.ok(self.w.run("move", SID_A, "--to", "job", "--dry-run",
                           CSM_ACCOUNTS=q, CSM_MACHINE="laptop"))

    def test_a_file_mixing_the_two_dialects_is_refused_naming_the_line(self):
        p = self.w.root / "accounts.tsv"
        p.write_text("job\tme@work.example\t%s\t-\t-\tlaptop\twk\t-\n"
                     "me ~/.claude-personal\n" % self.work)
        self.refused(self.w.run("accounts", CSM_ACCOUNTS=p, CSM_MACHINE="laptop"),
                     ":2:", "one dialect")

    def test_two_rows_with_one_name_are_refused(self):
        p = self.w.table(("job", "me@work.example", self.work, "laptop", "wk"),
                         ("job", "me@home.example", self.personal, "laptop", "mine"))
        self.refused(self.w.run("accounts", CSM_ACCOUNTS=p, CSM_MACHINE="laptop"),
                     "used twice")

    def test_two_rows_with_one_handle_are_refused(self):
        # 🛑 Not "the first one wins": `--to wk` would then answer with whichever came
        # first and never ask which was meant, and the listing would print two cells
        # nobody can tell apart.
        p = self.w.table(("job", "me@work.example", self.work, "laptop", "wk"),
                         ("me", "me@home.example", self.personal, "laptop", "wk"))
        self.refused(self.w.run("accounts", CSM_ACCOUNTS=p, CSM_MACHINE="laptop"),
                     "handle 'wk' is used twice")

    def test_a_handle_of_the_wrong_shape_drops_its_row_and_says_nothing_on_stderr(self):
        # The one row-level fault that is not a refusal: the file may be shared with other
        # tools, and one unusable alias is not a reason to refuse every command. It is said
        # in the log, where a shape complaint belongs — never on a stream a caller parses.
        p = self.w.table(("job", "me@work.example", self.work, "laptop", "Work Account"),
                         ("me", "me@home.example", self.personal, "laptop", "mine"))
        self.w.session(self.personal, SID_B)
        r = self.w.run("list", "--json", CSM_ACCOUNTS=p, CSM_MACHINE="laptop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        self.assertEqual([x["handle"] for x in json.loads(r.stdout)], ["mine"])
        self.assertNotIn("job", self.rows(p))
        self.assertIn("Work Account", (self.w.state / "log").read_text())

    def test_an_all_digit_handle_is_one_of_those(self):
        # It would make `--to 2` resolve to an account, while a bare number is refused
        # everywhere else precisely because a position is not a name.
        p = self.w.table(("job", "me@work.example", self.work, "laptop", "2"),
                         ("me", "me@home.example", self.personal, "laptop", "mine"))
        self.assertEqual(set(self.rows(p)), {"me"})

    def test_a_row_this_machine_is_not_named_in_is_not_an_account_here(self):
        p = self.w.table(("job", "me@work.example", self.work, "desktop", "wk"),
                         ("me", "me@home.example", self.personal, "laptop", "mine"))
        self.assertEqual(set(self.rows(p, "laptop")), {"me"})
        self.assertEqual(set(self.rows(p, "desktop")), {"job"})

    def test_a_narrow_table_has_not_said_which_machines_so_every_row_is_here(self):
        # 🛑 Absent is not "none". A table of name/email/home has said nothing about
        # machines, and reading that as "on no machine" would refuse every move target.
        p = self.w.root / "accounts.tsv"
        p.write_text("# name\temail\thome\n"
                     "job\tme@work.example\t%s\n"
                     "me\tme@home.example\t%s\n" % (self.work, self.personal))
        by = self.rows(p, "a-name-nobody-wrote")
        self.assertEqual(set(by), {"job", "me"})
        self.assertIsNone(by["job"]["machines"])
        self.w.session(self.work, SID_A)
        self.assertIn("→  me", self.ok(self.w.run(
            "move", SID_A, "--to", "me", "--dry-run", CSM_ACCOUNTS=p,
            CSM_MACHINE="a-name-nobody-wrote")))

    def test_a_machine_the_table_does_not_name_lists_everything(self):
        # 🛑 Filtering to nothing reads exactly like "there are no sessions anywhere",
        # which is the one answer that is never useful.
        self.assertEqual(set(self.rows(self.two_rows(), "a-name-nobody-wrote")),
                         {"job", "me"})

    def test_a_row_on_no_machine_is_refused_as_a_move_target(self):
        p = self.w.table(("job", "me@work.example", self.work, "laptop", "wk"),
                         ("me", "me@home.example", self.personal, "-", "mine"))
        self.assertIn("me", self.rows(p))                  # visible in the view...
        self.w.session(self.work, SID_A)
        self.refused(self.w.run("move", SID_A, "--to", "mine", "--dry-run",
                                CSM_ACCOUNTS=p, CSM_MACHINE="laptop"),
                     "mine is on no machine")              # ...and never a destination

    def test_the_default_home_may_not_be_spelled_in_a_table(self):
        for home in ("-", "default", "~/.claude", str(self.w.home / ".claude")):
            p = self.w.table(("job", "me@work.example", home, "laptop", "wk"))
            self.refused(self.w.run("accounts", CSM_ACCOUNTS=p, CSM_MACHINE="laptop"),
                         "names no home of its own", home)

    def test_the_simple_dialect_still_takes_a_dash_for_the_default_home(self):
        self.w.account("default", "me@default.example", default=True)
        cfg = self.w.root / "accounts"
        cfg.write_text("home -\nwork ~/.claude-work\n")
        by = {r["name"]: r for r in json.loads(self.ok(self.w.run(
            "accounts", "--json", CSM_ACCOUNTS=cfg)))}
        self.assertTrue(by["home"]["default"])
        self.assertEqual(by["home"]["email"], "me@default.example")
        self.assertIsNone(by["home"]["machines"])          # the file did not say

    def test_a_handle_resolves_wherever_a_name_does(self):
        p = self.two_rows()
        self.w.session(self.work, SID_A)
        out = self.ok(self.w.run("move", SID_A, "--to", "mine", "--dry-run",
                                 CSM_ACCOUNTS=p, CSM_MACHINE="laptop"))
        self.assertIn("→  mine", out)
        # and the handle is what the table and the footer print, not the name
        out = self.ok(self.w.run("list", CSM_ACCOUNTS=p, CSM_MACHINE="laptop"))
        self.assertIn("account", out.splitlines()[0])
        self.assertIn(" wk ", out)
        self.assertIn("accounts: wk, mine", out)

    def test_a_handle_also_works_as_a_prefix_and_a_substring(self):
        p = self.two_rows()
        self.w.session(self.work, SID_A)
        for spec in ("mine", "MINE", "min", "ine", "me@home.example", "me"):
            self.assertIn("→  mine", self.ok(self.w.run(
                "move", SID_A, "--to", spec, "--dry-run",
                CSM_ACCOUNTS=p, CSM_MACHINE="laptop")), spec)

    def test_the_header_lines_up_with_the_rows_under_it(self):
        # 🛑 `account` is seven characters and a handle is often fewer, so a column sized
        # by the handles alone pushed every header but `#` one place right of its own
        # column. A table whose header sits over the wrong column is how somebody reads an
        # age as a state — and the account cell is what gets typed back at `--to`.
        p = self.two_rows()
        self.w.session(self.work, SID_A,
                       lines=[user("ALPHATITLE", str(self.w.work), SID_A)])
        out = self.ok(self.w.run("list", CSM_ACCOUNTS=p, CSM_MACHINE="laptop"))
        head, row = out.splitlines()[0], out.splitlines()[1]
        self.assertIn("wk", row)
        self.assertEqual(head.index("title"), row.index("ALPHATITLE"))
        self.assertTrue(head.index("account") == row.index("wk"), head + "\n" + row)

    def test_accounts_shows_the_meter_only_when_one_is_configured(self):
        p = self.two_rows()
        out = self.ok(self.w.run("accounts", CSM_ACCOUNTS=p, CSM_MACHINE="laptop"))
        self.assertNotIn("quota unread here", out)
        m = self.w.meters(wk=(12, 34, 60))
        out = self.ok(self.w.run("accounts", CSM_ACCOUNTS=p, CSM_MACHINE="laptop",
                                 CSM_METERS=m))
        self.assertIn("5 h 12% · week 34% used", out)
        self.assertIn("quota unread here", out)            # the row with no reading
        by = {r["name"]: r for r in json.loads(self.ok(self.w.run(
            "accounts", "--json", CSM_ACCOUNTS=p, CSM_MACHINE="laptop", CSM_METERS=m)))}
        self.assertAlmostEqual(by["job"]["meter"]["seven_day"], 34.0)
        self.assertIsNone(by["me"]["meter"])

    def test_an_errored_or_non_numeric_meter_row_is_unread_not_zero(self):
        p = self.two_rows()
        m = self.w.root / "meters.json"
        m.write_text(json.dumps({
            "wk": {"at": time.time(), "five_hour": 1, "seven_day": 2, "error": "timeout"},
            "mine": {"at": time.time(), "five_hour": "0", "seven_day": 0}}))
        out = self.ok(self.w.run("accounts", CSM_ACCOUNTS=p, CSM_MACHINE="laptop",
                                 CSM_METERS=m))
        self.assertEqual(out.count("quota unread here"), 2)

    def test_a_meter_timestamp_in_milliseconds_is_not_read_as_1970(self):
        p = self.two_rows()
        m = self.w.root / "meters.json"
        m.write_text(json.dumps({"wk": {"at": time.time() * 1000, "five_hour": 5,
                                        "seven_day": 6}}))
        out = self.ok(self.w.run("accounts", CSM_ACCOUNTS=p, CSM_MACHINE="laptop",
                                 CSM_METERS=m))
        self.assertIn("5 h 5% · week 6% used", out)
        self.assertNotIn("STALE", out)


class RemoteDispatch(Base):
    """`--machine M` / `--ssh HOST`: one dispatcher, two spellings. No real ssh is run — the
    ssh invocation itself is a knob, so the test points it at a recorder."""

    def setUp(self):
        super().setUp()
        self.tsv = self.w.table(
            ("job", "me@work.example", self.work, "laptop,desktop", "wk"),
            ("me", "me@home.example", self.personal, "laptop", "mine"))

    def ssh_run(self, *args, **env):
        e = {"CSM_SSH_CMD": str(self.w.bin / "fake-ssh"),
             "FAKE_SSH_LOG": str(self.w.ssh_log),
             "CSM_ACCOUNTS": str(self.tsv), "CSM_MACHINE": "laptop"}
        e.update({k: str(v) for k, v in env.items()})
        return self.w.run(*args, **e)

    def sent(self):
        return [json.loads(x) for x in self.w.ssh_log.read_text().splitlines() if x.strip()]

    def test_this_machine_is_a_refusal_and_not_a_traceback(self):
        # 🛑 The dispatch happens inside the Refusal handler, so this comes out as one line
        # and exit 2. Outside it, the `die()` would escape as a traceback.
        r = self.ssh_run("--machine", "laptop", "list")
        self.refused(r, "is this machine", "drop the flag")
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(self.w.ssh_log.exists())

    def test_a_machine_the_table_does_not_know_is_refused_naming_the_ones_it_does(self):
        self.refused(self.ssh_run("--machine", "mars", "list"),
                     "not a machine this tool knows", "desktop", "laptop")

    def test_with_nothing_to_check_against_any_name_goes(self):
        # 🛑 `--machine` is the spelling that IS checked, so it is the one this has to be
        # proved on: with no accounts file and no machines file there is nothing to check
        # against, and an unknown name is then not evidence of a mistake. Discovery is the
        # whole public default, and it must not need a table to reach another machine.
        for flag in ("--machine", "--ssh"):
            if self.w.ssh_log.exists():
                self.w.ssh_log.unlink()
            r = self.w.run(flag, "anything", "accounts",
                           CSM_SSH_CMD=str(self.w.bin / "fake-ssh"),
                           FAKE_SSH_LOG=str(self.w.ssh_log))
            self.assertEqual(r.returncode, 0, flag + ": " + r.stderr)
            self.assertEqual(self.sent()[0][0], "anything")

    def test_the_two_spellings_send_the_same_command(self):
        self.assertEqual(self.ok(self.ssh_run("--machine", "desktop", "accounts")), "")
        self.ok(self.ssh_run("--ssh", "desktop", "accounts"))
        a, b = self.sent()
        self.assertEqual(a, b)
        self.assertEqual(a[0], "desktop")
        self.assertTrue(a[-1].endswith("accounts"), a[-1])

    def test_both_at_once_is_refused(self):
        r = self.ssh_run("--machine", "desktop", "--ssh", "desktop", "list")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("two spellings of one thing", r.stderr)

    def test_the_flag_is_stripped_by_name_never_by_value(self):
        # 🛑 `desktop` is also the title being matched here. Filtering the forwarded argv by
        # VALUE would eat it and move a different session on the far side.
        self.ok(self.ssh_run("--machine", "desktop", "move", "desktop", "--to", "wk",
                         "--dry-run"))
        line = self.sent()[0][-1]
        self.assertIn("move desktop --to wk --dry-run", line)
        self.assertNotIn("--machine", line)

    def test_the_equals_spelling_is_stripped_too(self):
        self.ok(self.ssh_run("--machine=desktop", "accounts"))
        self.assertNotIn("--machine", self.sent()[0][-1])

    def test_a_multi_word_remote_command_reaches_the_far_side_intact(self):
        self.ok(self.ssh_run("--machine", "desktop", "list",
                         CSM_REMOTE_CMD="/opt/bin/env -i /opt/bin/csm"))
        line = self.sent()[0][-1]
        self.assertIn("/opt/bin/env -i /opt/bin/csm list", line)

    def test_a_home_relative_remote_command_names_the_far_sides_home(self):
        # 🛑 Two machines rarely share a home directory, so an absolute path is no answer
        # and this is the only way to say "your copy, not mine". `shlex.quote` has to quote
        # both spellings, which is why the prefix needs its own rule: quoted, `~/bin/csm`
        # is a path whose first component is literally `~`, and the far side exits 127.
        for spelling in ("~/wrap/csm", "$HOME/wrap/csm"):
            if self.w.ssh_log.exists():
                self.w.ssh_log.unlink()
            self.ok(self.ssh_run("--machine", "desktop", "list",
                                 CSM_REMOTE_CMD=spelling))
            line = self.sent()[0][-1]
            self.assertIn('"$HOME"/wrap/csm list', line, spelling)
            # and nothing of the word reached the shell as a quoted literal tilde
            self.assertNotIn("'~", line)
            self.assertNotIn("'$HOME", line)

    def test_a_remote_command_is_still_quoted_everywhere_but_that_prefix(self):
        # Only the leading home is unquoted. The rest of a word with a space in it, and a
        # `$` anywhere but that prefix, stay one quoted word the remote shell never expands.
        self.ok(self.ssh_run("--machine", "desktop", "accounts",
                             CSM_REMOTE_CMD="'~/my wrap/csm' --env='$NOPE'"))
        line = self.sent()[0][-1]
        self.assertIn('"$HOME"/\'my wrap/csm\' \'--env=$NOPE\' accounts', line)

    def test_without_one_the_remote_path_is_tried_before_a_clone_beside_it(self):
        self.ok(self.ssh_run("--machine", "desktop", "accounts"))
        line = self.sent()[0][-1]
        # The ORDER is the claim: the installed command is looked for first and the clone
        # is only the fallback, so a machine that has both runs the installed one.
        self.assertIn("command -v", line)
        self.assertLess(line.index("command -v"),
                        line.index("$HOME/git/claude-session-mover/claude-session-mover"),
                        line)

    def test_an_ssh_host_is_never_checked_against_the_machines_the_table_knows(self):
        # 🛑 `--ssh HOST` names an SSH HOST: an alias out of ssh_config, a bastion, a
        # hostname that is in no accounts file by design. Checking it against the table
        # would break the one spelling that has always meant "that host", and would make
        # the `--machine` refusal's own advice ("name a host with --ssh") dead advice.
        self.ok(self.ssh_run("--ssh", "a-bastion-in-no-table", "accounts"))
        self.assertEqual(self.sent()[0][0], "a-bastion-in-no-table")
        self.refused(self.ssh_run("--machine", "a-bastion-in-no-table", "accounts"),
                     "not a machine this tool knows")
        # and the remote-list gesture echoes the flag that was typed, because `--machine`
        # would refuse a host the table does not name
        out = self.ok(self.ssh_run("--ssh", "a-bastion-in-no-table", "list",
                                   FAKE_SSH_STDOUT="  1  wk  something\n"))
        self.assertIn("csm --ssh a-bastion-in-no-table move <#> --to <account>", out)

    def test_a_machine_named_only_by_a_row_that_is_elsewhere_is_still_known(self):
        # 🛑 The known set is the WHOLE `machines` column, not the rows that survive the
        # here-filter. One account per machine is exactly the layout the column is for, and
        # reading the filtered list refused a machine the table named while telling you to
        # fix a column that was right.
        tsv = self.w.table(("job", "me@work.example", self.work, "laptop", "wk"),
                           ("me", "me@home.example", self.personal, "desktop", "mine"))
        self.ok(self.w.run("--machine", "desktop", "accounts",
                           CSM_SSH_CMD=str(self.w.bin / "fake-ssh"),
                           FAKE_SSH_LOG=str(self.w.ssh_log),
                           CSM_ACCOUNTS=tsv, CSM_MACHINE="laptop"))
        self.assertEqual(self.sent()[0][0], "desktop")

    def test_batchmode_is_the_default_ssh(self):
        mod = load_tool()
        self.addCleanup(sys.modules.pop, "csm_mod", None)
        self.assertIn("BatchMode=yes", mod.SSH_CMD)
        self.assertIn("ConnectTimeout", mod.SSH_CMD)

    def test_both_the_dispatch_and_its_exit_code_are_logged(self):
        # A DISPATCH IS NOT AN OUTCOME: the first line is the only record if the ssh never
        # returns, the second says how it ended. Without both, a remote leg cannot be read
        # back out of the log at all.
        r = self.ssh_run("--machine", "desktop", "list", FAKE_SSH_RC="3")
        self.assertEqual(r.returncode, 3)
        log = (self.w.state / "log").read_text()
        self.assertIn("ssh desktop:", log)
        self.assertIn("ssh desktop: exit 3", log)

    def test_every_log_line_names_the_machine_the_rest_of_the_output_does(self):
        # One machine, one spelling. The log is the only durable record of a dispatch, and a
        # hostname there beside `on laptop` everywhere else makes `grep laptop` over it
        # incomplete — the hostname is often a third name again (a collision suffix, a
        # domain). With nothing configured, `machine()` IS the hostname, so nothing is lost.
        self.ok(self.ssh_run("--machine", "desktop", "list"))
        for line in (self.w.state / "log").read_text().splitlines():
            if line.strip():
                self.assertIn("[laptop:", line, line)

    def test_a_remote_list_says_whose_row_numbers_those_are(self):
        out = self.ok(self.ssh_run("--machine", "desktop", "list",
                               FAKE_SSH_STDOUT="  1  wk  something\n"))
        self.assertIn("something", out)
        self.assertIn("row numbers there are not row numbers here", out)
        self.assertIn("csm --machine desktop move <#> --to <account>", out)

    def test_a_remote_list_in_json_gets_no_footer_and_a_failed_one_gets_none_either(self):
        out = self.ok(self.ssh_run("--machine", "desktop", "list", "--json",
                               FAKE_SSH_STDOUT="[]\n"))
        self.assertEqual(out, "[]\n")
        r = self.ssh_run("--machine", "desktop", "list", FAKE_SSH_RC="1")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("row numbers there", r.stdout)

    def test_the_126_127_hint_names_the_installer_and_the_knob(self):
        r = self.ssh_run("--machine", "desktop", "list", FAKE_SSH_RC="127")
        self.assertEqual(r.returncode, 127)
        self.assertIn("install.sh", r.stderr)
        self.assertIn("CSM_REMOTE_CMD", r.stderr)

    def test_a_transport_hint_calls_the_tool_what_every_other_line_calls_it(self):
        # one name per tool: a refusal says `csm:`, so a hint printed under ssh's own
        # output must not say `claude-session-mover:` and read as a third program
        for rc in ("127", "255"):
            r = self.ssh_run("--machine", "desktop", "list", FAKE_SSH_RC=rc)
            said = [ln for ln in r.stderr.splitlines() if ln.startswith(("csm:", "claude-"))]
            self.assertTrue(said, rc + ": " + r.stderr)
            for ln in said:
                self.assertTrue(ln.startswith("csm:"), ln)

    def test_an_ssh_that_never_connected_says_so_instead_of_leaving_sshs_words(self):
        """🛑 255 is ssh's own 'could not connect', and what ssh prints on the way there
        reads like an answer about sessions ('Connection closed by UNKNOWN port 65535').
        Without this line the reader cannot tell a machine that is asleep from a machine
        with nothing to list."""
        r = self.ssh_run("--machine", "desktop", "list", FAKE_SSH_RC="255")
        self.assertEqual(r.returncode, 255)
        self.assertIn("255", r.stderr)
        self.assertIn("could not connect", r.stderr)
        self.assertIn("ssh desktop true", r.stderr)
        # and it does not claim to know: the remote command may also return 255
        self.assertIn("usually", r.stderr)

    def test_an_ordinary_remote_failure_gets_no_transport_hint(self):
        # rc 1 is the far side answering, so neither hint may fire
        r = self.ssh_run("--machine", "desktop", "list", FAKE_SSH_RC="1")
        self.assertEqual(r.returncode, 1)
        self.assertNotIn("could not connect", r.stderr)
        self.assertNotIn("install.sh", r.stderr)


class Resolve(Base):
    def setUp(self):
        super().setUp()
        self.w.session(self.work, SID_A)

    def dry(self, to):
        return self.w.run("move", SID_A, "--to", to, "--dry-run")

    def test_name_email_prefix_substring(self):
        # one round trip proves the CLI is wired to the resolver; the ladder itself is
        # pinned in-process, because six more subprocess launches buy nothing
        self.assertIn("→  personal", self.ok(self.dry("pers")))
        mod = load_tool()
        self.addCleanup(sys.modules.pop, "csm_mod", None)
        accts = [mod.Account("work", self.work, expect=""),
                 mod.Account("personal", self.personal, expect="")]
        for spec in ("personal", "PERSONAL", "me@home.example", "pers", "erso",
                     "home.example"):
            self.assertEqual(mod.resolve(spec, accts).name, "personal", spec)

    def test_ambiguous_is_refused_with_candidates(self):
        self.w.account("personal2", "me2@home.example", org="org-3")
        self.refused(self.dry("pers"), "matches 2 accounts", "personal", "personal2")

    def test_a_bare_number_is_refused(self):
        self.refused(self.dry("2"), "named, never numbered")

    def test_a_number_that_is_literally_a_name_works(self):
        self.w.account("2", "me3@else.example", org="org-9")
        self.assertIn("→  2 ", self.ok(self.dry("2")))

    def test_unknown(self):
        self.refused(self.dry("nobody"), "is no account here")


# ---------------------------------------------------------------------------- listing

class Listing(Base):
    def test_title_order_custom_then_ai_then_last_prompt_then_first(self):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[
            user("first words", cwd, SID_A), assistant("ok", cwd, SID_A),
            {"type": "ai-title", "aiTitle": "AI title", "sessionId": SID_A},
            {"type": "custom-title", "customTitle": "My name for it", "sessionId": SID_A}])
        self.w.session(self.work, SID_B, lines=[
            user("first words", cwd, SID_B), assistant("ok", cwd, SID_B),
            {"type": "ai-title", "aiTitle": "AI title", "sessionId": SID_B},
            {"type": "last-prompt", "lastPrompt": "later prompt", "sessionId": SID_B}])
        self.w.session(self.work, SID_C, lines=[
            user("<command-name>/clear</command-name>", cwd, SID_C),
            user("the real first prompt", cwd, SID_C), assistant("ok", cwd, SID_C)])
        t = {r["local_id"]: r["title"] for r in self.listing()}
        self.assertEqual(t[SID_A], "My name for it")
        self.assertEqual(t[SID_B], "AI title")
        self.assertEqual(t[SID_C], "the real first prompt")

    def one_old_live_and_two_new(self):
        now = time.time()
        self.w.session(self.work, SID_A, mtime=now - 9000)          # old, but live
        self.w.session(self.personal, SID_B, mtime=now - 10)
        self.w.session(self.personal, SID_C, mtime=now - 100)
        self.w.live(self.work, SID_A, self.w.spawn().pid)

    def test_newest_first_and_the_DEFAULT_limit_never_cuts_a_live_session(self):
        # The default is the path where no number was typed, and there the old rule stands:
        # the session somebody means to move is running, and it may be the oldest file here.
        # `CSM_LIMIT` IS the default, so setting it is still the default path.
        self.one_old_live_and_two_new()
        rows = json.loads(self.ok(self.w.run("list", "--json", CSM_LIMIT="2")))
        self.assertEqual([r["local_id"] for r in rows], [SID_B, SID_A])
        self.assertTrue(rows[1]["live"])   # the oldest file here, and still listed
        rows = self.listing()
        self.assertEqual([r["local_id"] for r in rows], [SID_B, SID_C, SID_A])

    def test_an_explicit_limit_is_a_hard_cap_even_over_a_live_session(self):
        # Where every Remote Control worker registers as live, the exemption above swallows
        # the whole list: `--limit 1` printed every row, and the flag was advertised and
        # inert. An explicit number is at most N rows, the newest, live or not.
        self.one_old_live_and_two_new()
        self.assertEqual([r["local_id"] for r in self.listing("--limit", "1")], [SID_B])
        self.assertEqual([r["local_id"] for r in self.listing("--limit", "2")],
                         [SID_B, SID_C])
        self.assertEqual(len(self.listing("--limit", "99")), 3)      # min(N, rows), never N

    def test_an_explicit_limit_beats_all_and_the_table_says_what_it_left_out(self):
        self.one_old_live_and_two_new()
        self.assertEqual(len(self.listing("--all", "--limit", "2")), 2)
        out = self.ok(self.w.run("list", "--limit", "2"))
        self.assertIn("the newest 2 of at least 3 on this machine", out)
        self.assertIn("csm list --all", out)
        # ⚠️ The regression an argparse default of DEFAULT_LIMIT would have shipped: every
        # run would look explicit, so `--all` here would cap at 20 and claim "of at least".
        # (A listing that really is capped — more rows than the ceiling — says so under
        # `--all` too, which is why this world has three sessions and not three hundred.)
        self.assertNotIn("of at least", self.ok(self.w.run("list", "--all")))
        self.assertNotIn("of at least", self.ok(self.w.run("list")))

    def test_with_no_accounts_file_the_handle_is_the_name(self):
        # Discovery gives no handles, so every listing and every `--to` keeps working with
        # the names — the public audience's experience is unchanged by the column existing.
        self.w.session(self.work, SID_A)
        self.assertEqual(self.listing()[0]["handle"], "work")
        out = self.ok(self.w.run("list"))
        self.assertIn("accounts: personal, work", out)

    def test_all_limit_and_the_title_width_are_knobs(self):
        now = time.time()
        for i, sid in enumerate((SID_A, SID_B, SID_C)):
            self.w.session(self.work, sid, mtime=now - i,
                           lines=[user("a very long first prompt indeed, longer than any "
                                       "column could be", str(self.w.work), sid)])
        self.assertEqual(len(json.loads(self.ok(self.w.run(
            "list", "--all", "--json", CSM_ALL_LIMIT="2")))), 2)
        wide = self.ok(self.w.run("list", CSM_ROW_TITLE="60"))
        narrow = self.ok(self.w.run("list", CSM_ROW_TITLE="20"))
        self.assertGreater(max(len(x) for x in wide.splitlines()),
                           max(len(x) for x in narrow.splitlines()))

    def test_a_dead_registry_file_is_not_live(self):
        self.w.session(self.work, SID_A)
        p = self.w.spawn()
        self.w.live(self.work, SID_A, p.pid)
        p.kill()
        p.wait()
        self.assertFalse(self.listing()[0]["live"])

    def test_quota_flag_in_force_and_waited_out(self):
        cwd = str(self.w.work)
        future_ms = int((time.time() + 3600) * 1000)
        past_s = int(time.time() - 3600)
        self.w.session(self.work, SID_A, lines=[
            user("go", cwd, SID_A), assistant("working", cwd, SID_A),
            assistant("limit", cwd, SID_A, error="usage_limit_reached", resets=future_ms)])
        self.w.session(self.work, SID_B, lines=[
            user("go", cwd, SID_B),
            assistant("limit", cwd, SID_B, error="usage_limit_reached", resets=past_s),
            user("again", cwd, SID_B), assistant("fine now", cwd, SID_B)])
        by = {r["local_id"]: r for r in self.listing()}
        self.assertTrue(by[SID_A]["out_of_quota"])
        self.assertEqual(by[SID_A]["quota"]["kind"], "five_hour")
        self.assertAlmostEqual(by[SID_A]["quota"]["resets_at"], future_ms / 1000, delta=1)
        self.assertFalse(by[SID_B]["out_of_quota"])
        self.assertIn("OUT OF QUOTA", self.ok(self.w.run("list")))

    def test_model_is_never_synthetic(self):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[
            user("go", cwd, SID_A), assistant("ok", cwd, SID_A, model="claude-opus-4-1"),
            assistant("limit", cwd, SID_A, error="usage_limit_reached",
                      resets=int(time.time() + 600))])
        self.assertEqual(self.listing()[0]["model"], "claude-opus-4-1")

    def test_permission_mode_from_prompt_lines_and_read_backwards(self):
        cwd = str(self.w.work)
        big = "x" * 4000
        lines = [user("go", cwd, SID_A, perm="default"),
                 {"type": "permission-mode", "permissionMode": "plan", "sessionId": SID_A},
                 user("second", cwd, SID_A, perm="bypassPermissions")]
        lines += [assistant(big, cwd, SID_A) for _ in range(12)]     # ~48 KB after the prompt
        self.w.session(self.work, SID_A, lines=lines)
        rows = json.loads(self.ok(self.w.run("list", "--json", CSM_HEAD_BYTES=1024,
                                             CSM_TAIL_BYTES=8192)))
        self.assertEqual(rows[0]["permission_mode"], "bypassPermissions")

    def test_claude_ai_link_from_the_bridge_line(self):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[
            user("go", cwd, SID_A), assistant("ok", cwd, SID_A),
            {"type": "bridge-session", "bridgeSessionId": "cse_01OldLinkAbcdef", "sessionId": SID_A},
            {"type": "bridge-session", "bridgeSessionId": "cse_01NewLinkAbcdef", "sessionId": SID_A}])
        self.assertEqual(self.listing()[0]["url"], "https://claude.ai/code/session_01NewLinkAbcdef")

    def test_this_session_is_marked(self):
        self.w.session(self.work, SID_A)
        out = self.ok(self.w.run("list", CLAUDE_CODE_SESSION_ID=SID_A))
        self.assertIn("← this session", out)


# ------------------------------------------------------------------------- picking

class Picking(Base):
    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        now = time.time()
        self.w.session(self.work, SID_A, mtime=now - 30, lines=[
            user("refactor the parser", cwd, SID_A), assistant("ok", cwd, SID_A),
            {"type": "bridge-session", "bridgeSessionId": "cse_01PickMeByLink99", "sessionId": SID_A}])
        self.w.session(self.personal, SID_B, mtime=now - 20, lines=[
            user("write the docs", cwd, SID_B), assistant("ok", cwd, SID_B)])
        self.w.session(self.personal, SID_C, mtime=now - 10, lines=[
            user("write the tests", cwd, SID_C), assistant("ok", cwd, SID_C)])

    def plan_for(self, spec):
        out = self.ok(self.w.run("move", spec, "--to", "work" if spec != "refactor" else "personal",
                                 "--dry-run"))
        return out.splitlines()[0]

    def plan_to(self, spec, to):
        """…when the row the spec names is itself in `work`, which `plan_for` moves TO."""
        return self.ok(self.w.run("move", spec, "--to", to, "--dry-run"))

    def test_row_number_from_the_last_list(self):
        self.ok(self.w.run("list"))
        self.assertIn("write the tests", self.plan_for("1"))
        self.assertIn("write the docs", self.plan_for("2"))

    def test_row_number_without_a_list_is_refused(self):
        self.refused(self.w.run("move", "1", "--to", "work", "--dry-run"), "not in the last")

    def test_an_all_digit_spec_is_a_row_number_not_an_id_prefix(self):
        self.refused(self.w.run("move", SID_B[:6], "--to", "work", "--dry-run"),
                     "not in the last")

    def test_id_prefix_link_and_title(self):
        self.assertIn("write the docs", self.plan_for(SID_B[:11]))
        r = self.w.run("move", "https://claude.ai/code/session_01PickMeByLink99", "--to",
                       "personal", "--dry-run")
        self.assertIn("refactor the parser", self.ok(r).splitlines()[0])
        self.assertIn("refactor the parser", self.plan_for("refactor"))

    def test_ambiguous_title_is_refused(self):
        self.refused(self.w.run("move", "write the", "--to", "work", "--dry-run"),
                     "matches 2 sessions")

    def test_after_a_move_the_live_copy_wins(self):
        # the same id in two homes, as a move leaves it; only the copy in `work` is running
        self.w.session(self.personal, SID_A, lines=[
            user("refactor the parser", str(self.w.work), SID_A)])
        self.w.live(self.work, SID_A, self.w.spawn().pid)
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run"))
        self.assertIn("work (me@work.example)  →  personal", out)

    def test_two_quiet_copies_are_refused(self):
        self.w.session(self.personal, SID_A, lines=[
            user("refactor the parser", str(self.w.work), SID_A)])
        self.refused(self.w.run("move", SID_A, "--to", "work", "--dry-run"),
                     "a move is a copy")

    # --- a link, resolved by arithmetic -----------------------------------
    def dead_server_child(self, home=None):
        """A session as a dead Remote Control child leaves it: a transcript whose NAME is
        the only thing tying it to its claude.ai link — no `bridge-session` line in it, and
        no registry row, because the process is gone."""
        cwd = str(self.w.work)
        return self.w.session(home or self.work, LINK_SID, mtime=time.time() - 40 * 86400,
                              lines=[user("the one that died", cwd, LINK_SID),
                                     assistant("working on it", cwd, LINK_SID)])

    def test_a_dead_server_child_is_found_by_its_link_with_nothing_running(self):
        self.dead_server_child()
        out = self.ok(self.w.run("move", link_of(LINK_BARE), "--to", "personal",
                                 "--dry-run"))
        self.assertIn("the one that died", out.splitlines()[0])
        self.assertIn(LINK_SID, out)
        self.assertIn("resolved from the link", out)
        # and a bare bridge id, which is what the app copies, is the same question
        self.assertIn("the one that died", self.plan_to("cse_" + LINK_BARE, "personal"))

    def test_a_spacesheep_session_link_finds_the_same_transcript(self):
        self.dead_server_child()
        out = self.ok(self.w.run(
            "move", "https://spacesheep.dev/sessions/claude-code/" + LINK_SID,
            "--to", "personal", "--dry-run"))
        self.assertIn("the one that died", out.splitlines()[0])
        self.assertIn("resolved from the link", out)

    def test_a_link_with_no_transcript_here_is_refused_and_names_the_file_it_wanted(self):
        r = self.w.run("move", link_of(LINK_BARE), "--to", "personal", "--dry-run")
        self.refused(r, "no transcript for that link here", LINK_SID,
                     "session_" + LINK_BARE, "work", "personal")

    def test_a_link_NEVER_matches_by_title_even_when_a_session_quotes_it(self):
        """🛑 The sharp edge of falling through. A session whose own first prompt pasted the
        link has the link IN ITS TITLE, so the title rung would answer "found it" with the
        session that merely talks about the one you asked for — and then move that.

        A spacesheep link is the form that really reached that rung: `URL_RE` does not
        match it at all, so before the spec layer the ladder fell straight past the id
        rungs to the title.
        """
        cwd = str(self.w.work)
        sheep = "https://spacesheep.dev/sessions/claude-code/" + LINK_SID
        decoy = "44444444-dddd-4ddd-8ddd-444444444444"
        self.w.session(self.personal, decoy, lines=[
            user("read " + sheep + " and tell me what it says", cwd, decoy)])
        r = self.w.run("move", sheep, "--to", "work", "--dry-run")
        self.refused(r, "no transcript for that link here", LINK_SID)
        self.assertNotIn("read http", r.stdout + r.stderr)
        # the same for the claude.ai spelling
        link = link_of(LINK_BARE2)
        self.w.session(self.personal, "55555555-eeee-4eee-8eee-555555555555", lines=[
            user("look at " + link, cwd, "55555555-eeee-4eee-8eee-555555555555")])
        self.refused(self.w.run("move", link, "--to", "work", "--dry-run"),
                     "no transcript for that link here", LINK_SID2)

    def test_a_link_still_resolves_through_a_bridge_session_line(self):
        """The old rung, unchanged: a self-hosted session whose transcript names its link,
        and whose derived id is not a file here."""
        self.assertIn("refactor the parser",
                      self.plan_to("https://claude.ai/code/session_01PickMeByLink99",
                                   "personal"))

    def test_a_link_resolves_through_a_live_registry_row_too(self):
        cwd = str(self.w.work)
        sid = "66666666-ffff-4fff-8fff-666666666666"
        self.w.session(self.personal, sid, lines=[user("the live one", cwd, sid)])
        self.w.live(self.personal, sid, self.w.spawn().pid, bridge="cse_" + LINK_BARE2)
        self.assertIn("the live one", self.plan_for(link_of(LINK_BARE2)))

    def test_stop_takes_a_link_too_and_says_csm_did_not_start_it(self):
        """`stop`'s own authorisation is unchanged — but it has to get as far as checking
        it, which before the spec layer a link to a dead child never did."""
        self.dead_server_child()
        self.refused(self.w.run("stop", link_of(LINK_BARE)), "csm did not start",
                     LINK_SID[:8])


# ------------------------------------------------------------------------- refusals

class Refusals(Base):
    def setUp(self):
        super().setUp()
        self.t = self.w.session(self.work, SID_A)

    def move(self, *extra, **env):
        return self.w.run("move", SID_A, *extra, **env)

    def test_same_account(self):
        self.refused(self.move("--to", "work"), "already in work")

    def test_same_login_in_another_home(self):
        self.w.account("twin", "me@work.example")
        self.refused(self.move("--to", "twin"), "same login")

    def test_same_email_in_another_organisation_is_allowed(self):
        self.w.account("team", "me@work.example", org="org-team")
        self.ok(self.move("--to", "team", "--dry-run"))

    def test_signed_out_target(self):
        self.w.account("spare")
        self.refused(self.move("--to", "spare"), "holds no login", "/login")

    def test_wrong_login_against_the_accounts_file(self):
        cfg = self.w.root / "accounts"
        cfg.write_text("work ~/.claude-work\npersonal ~/.claude-personal someone@else.example\n")
        self.refused(self.move("--to", "personal", CSM_ACCOUNTS=cfg), "WRONG login")

    def test_missing_working_directory(self):
        self.w.session(self.work, SID_B, cwd=str(self.w.root / "gone"))
        self.refused(self.w.run("move", SID_B, "--to", "personal"), "does not exist")

    def row_of(self, account, sid):
        rows = self.listing()
        return str([r["pos"] for r in rows if r["account"] == account and r["local_id"] == sid][0])

    def test_live_twin_at_the_destination(self):
        # moved there earlier and still running there: copying over it would make two writers
        self.w.session(self.personal, SID_A)
        self.w.live(self.personal, SID_A, self.w.spawn().pid)
        row = self.row_of("work", SID_A)
        r = self.w.run("move", row, "--to", "personal", "--dry-run")
        # the dry run reports it instead of raising, and the real move refuses it
        self.assertIn("a real move would be REFUSED", self.ok(r))
        self.refused(self.w.run("move", row, "--to", "personal"), "ALREADY running")

    def test_a_registry_that_cannot_be_read_is_not_proof_that_nothing_runs_there(self):
        """🛑 The twin check's input may not be allowed to fail open.

        `dest` already exists, so the one question left is whether a process is writing
        it — and the answer comes from `<home>/sessions/`. A directory this process cannot
        read used to come back empty, which reads exactly like "nothing is running here":
        the quietest possible path to the one outcome the check exists to prevent, two CLIs
        appending to one transcript. "Could not look" is never a verdict.
        """
        self.w.session(self.personal, SID_A)                 # the file a move would land on
        d = self.personal / "sessions"
        d.mkdir(exist_ok=True)
        row = self.row_of("work", SID_A)
        os.chmod(str(d), 0o000)
        # ⚠️ Restored HERE, not with addCleanup: cleanups run after tearDown, and tearDown
        # is what deletes the fixture tree — which it cannot, through a 000 directory.
        try:
            if os.access(str(d), os.R_OK):
                self.skipTest("this filesystem or user ignores a 000 directory")
            dry = self.w.run("move", row, "--to", "personal", "--dry-run")
            real = self.w.run("move", row, "--to", "personal")
        finally:
            os.chmod(str(d), 0o700)
        self.assertIn("a real move would be REFUSED", self.ok(dry))
        self.refused(real, "cannot be read", "would not open",
                     "refused rather than guessed")
        self.assertEqual(self.w.claude_calls(wait=0.2), [], "nothing was started")

    def test_window_already_there(self):
        self.w.tmux_state.write_text(json.dumps(
            {"sessions": {"csm-personal": {"moved-11111111": "/dev/null"}}}))
        self.refused(self.move("--to", "personal"), "already exists")

    def test_the_same_id_already_in_another_project_folder_of_the_target(self):
        # 🛑 `--resume <id>` scans the home and takes the hit only when EXACTLY ONE file
        # matches, so a copy left in another folder by an earlier move makes the resume
        # ambiguous — and the window would die after the state file was already written.
        self.w.session(self.personal, SID_A, folder="-some-other-spelling")
        row = self.row_of("work", SID_A)
        out = self.ok(self.w.run("move", row, "--to", "personal", "--dry-run"))
        self.assertIn("a real move would be REFUSED", out)
        self.assertIn("another project folder", out)
        self.refused(self.w.run("move", row, "--to", "personal"),
                     "another project folder", "exactly ONE file")

    def test_a_project_folder_that_cannot_be_read_does_not_answer_for_the_whole_home(self):
        """🛑 The same hole as the registry's, in the guard right below it.

        `Path.glob` swallows the PermissionError its own scan raises and yields nothing, so
        `tgt.projects.glob("*/<id>.jsonl")` answered "no other copy" about a home it had
        not finished reading — and the `except OSError` written around it was dead code.
        The copy here is in a folder this process may not read, which is precisely the one
        the guard must not miss.
        """
        self.w.session(self.personal, SID_A, folder="-some-other-spelling")
        row = self.row_of("work", SID_A)
        locked = self.personal / "projects" / "-some-other-spelling"
        os.chmod(str(locked), 0o000)
        try:
            if os.access(str(locked / (SID_A + ".jsonl")), os.F_OK):
                self.skipTest("this filesystem or user ignores a 000 directory")
            dry = self.w.run("move", row, "--to", "personal", "--dry-run")
            real = self.w.run("move", row, "--to", "personal")
        finally:
            os.chmod(str(locked), 0o700)
        self.assertIn("a real move would be REFUSED", self.ok(dry))
        self.refused(real, "cannot tell whether", "would not open",
                     "refused rather than guessed")
        self.assertEqual(self.w.claude_calls(wait=0.2), [], "nothing was started")

    def test_a_destination_folder_that_cannot_be_statted_is_a_sentence_not_a_traceback(self):
        """`Path.exists()` only swallows ENOENT/ENOTDIR/EBADF/ELOOP, so a target project
        folder this process may not read raised straight out of `preflight` — a function
        whose whole contract is to answer in sentences. The answer it could not get is
        "would this overwrite something", which is a blocker."""
        self.w.session(self.personal, SID_A)                 # same folder, so dest is here
        row = self.row_of("work", SID_A)
        locked = Path(os.path.dirname(str(
            self.personal / "projects" / slug_of(str(self.w.work)))))
        folder = self.personal / "projects" / slug_of(str(self.w.work))
        self.assertTrue(folder.is_dir(), folder)
        os.chmod(str(folder), 0o000)
        try:
            if os.access(str(folder / (SID_A + ".jsonl")), os.F_OK):
                self.skipTest("this filesystem or user ignores a 000 directory")
            real = self.w.run("move", row, "--to", "personal")
            dry = self.w.run("move", row, "--to", "personal", "--dry-run")
        finally:
            os.chmod(str(folder), 0o700)
        err = self.refused(real, "cannot tell whether")
        self.assertNotIn("Traceback", err)
        # 🛑 And the DRY RUN answers in the plan, not with a stack: the plan builder makes
        # the same stats for its prose, and `--dry-run`'s whole answer is what it prints.
        self.assertEqual(dry.returncode, 0, dry.stdout + dry.stderr)
        self.assertIn("a real move would be REFUSED", dry.stdout)
        self.assertNotIn("Traceback", dry.stderr)
        self.assertEqual(self.w.claude_calls(wait=0.2), [], "nothing was started")
        self.assertTrue(locked.is_dir())

    def test_stop_source_needs_remote_control(self):
        self.refused(self.move("--to", "personal", "--stop-source", "--no-remote-control"),
                     "needs the default Remote Control mode")

    def test_foreground_inside_claude_code_is_refused(self):
        self.refused(self.move("--to", "personal", "--foreground", CLAUDECODE="1"),
                     "inside Claude Code")

    def test_a_refusal_writes_nothing(self):
        before = sorted(str(p) for p in self.personal.rglob("*"))
        state_before = (self.personal / ".claude.json").read_text()
        self.w.account("twin", "me@work.example")
        self.w.tmux_state.write_text(json.dumps(
            {"sessions": {"csm-personal": {"moved-11111111": "/dev/null"}}}))
        self.refused(self.move("--to", "personal"))
        self.assertEqual(sorted(str(p) for p in self.personal.rglob("*")), before)
        self.assertEqual((self.personal / ".claude.json").read_text(), state_before)

    def test_dry_run_changes_nothing(self):
        before = sorted(str(p) for p in self.personal.rglob("*"))
        out = self.ok(self.move("--to", "personal", "--dry-run"))
        self.assertIn("dry run: nothing was copied", out)
        self.assertIn("pre-answer", out)
        self.assertEqual(sorted(str(p) for p in self.personal.rglob("*")), before)
        self.assertFalse(any(c[0].startswith("new-") for c in self.w.tmux_log()))

    def test_the_dry_run_says_what_the_move_will_cost(self):
        # 🛑 a dry run is the last moment "move early, not at the limit" can be acted on.
        out = self.ok(self.move("--to", "personal", "--dry-run"))
        self.assertIn("what this move costs", out)
        self.assertIn("preserved thinking", out)
        self.assertIn("prompt cache starts cold", out)
        # the MEASURED half belongs to a real move only: nothing has come up yet
        self.assertNotIn("came up in", out)
        self.assertNotIn("not a measurement", out)

    def test_the_dry_run_says_thinking_is_kept_inside_one_organization(self):
        self.w.account("team", "me@team.example", org="org-1")      # same org as work
        out = self.ok(self.move("--to", "team", "--dry-run"))
        self.assertIn("same organization", out)
        self.assertNotIn("RE-READS the whole session", out)


# ------------------------------------------------------------------------------ moves

class Moves(Base):
    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.src = self.w.session(self.work, SID_A, folder="-the-launch-spelling", sibling=True, lines=[
            user("refactor the parser", cwd, SID_A, perm="bypassPermissions"),
            assistant("on it", cwd, SID_A, model="claude-opus-4-1"),
            {"type": "ai-title", "aiTitle": "Refactor: https://example.com/a/b", "sessionId": SID_A},
            assistant("limit", cwd, SID_A, error="usage_limit_reached",
                      resets=int(time.time() + 3600))])
        mem = self.src.parent / "memory"
        mem.mkdir()
        (mem / "MEMORY.md").write_text("- a note\n")
        (self.personal / ".claude.json").chmod(0o640)

    def test_remote_move_end_to_end(self):
        src_proc = self.w.spawn()
        self.w.live(self.work, SID_A, src_proc.pid)
        r = self.w.run("move", SID_A, "--to", "personal",
                       CLAUDECODE="1", CLAUDE_CODE_SESSION_ID="99999999-not-this-one",
                       CLAUDE_CODE_OAUTH_TOKEN="tok", ANTHROPIC_API_KEY="key",
                       CLAUDE_CODE_BRIDGE_OWNER_ACCOUNT_UUID="x", CLAUDE_CONFIG_DIR=str(self.work))
        out = self.ok(r)
        self.assertIn(LINK, out)
        self.assertIn("me@home.example", out)
        # the copy: same folder name as the source, sibling dir and memory with it
        dest = self.personal / "projects" / "-the-launch-spelling" / f"{SID_A}.jsonl"
        self.assertEqual(dest.read_bytes(), self.src.read_bytes())
        self.assertTrue((dest.parent / SID_A / "subagents" / "agent-1.jsonl").exists())
        self.assertFalse((dest.parent / "memory").exists(), "memory is never copied")
        self.assertTrue(self.src.exists(), "the source must never be deleted")
        # the first-run gates, additively, keeping the file's mode, with a backup
        st = json.loads((self.personal / ".claude.json").read_text())
        self.assertTrue(st["projects"][str(self.w.work)]["hasTrustDialogAccepted"])
        self.assertTrue(st["hasCompletedOnboarding"])
        self.assertEqual(st["oauthAccount"]["emailAddress"], "me@home.example")
        self.assertEqual(stat.S_IMODE((self.personal / ".claude.json").stat().st_mode), 0o640)
        self.assertEqual(len(list(self.personal.glob(".claude.json.csm-bak-*"))), 1)
        # what the moved window ran, and with which environment
        call = self.w.claude_calls()[0]
        argv, env = call["argv"], call["env"]
        self.assertEqual(argv[-2:], ["--resume", SID_A])
        self.assertIn("--permission-mode", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-4-1")
        rc = [a for a in argv if a.startswith("--remote-control=")][0]
        self.assertNotIn("/", rc)
        self.assertTrue(rc.endswith("moved from work"), rc)
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.personal))
        for gone in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_OAUTH_TOKEN",
                     "ANTHROPIC_API_KEY", "CLAUDE_CODE_BRIDGE_OWNER_ACCOUNT_UUID"):
            self.assertNotIn(gone, env)
        self.assertEqual(os.path.realpath(call["cwd"]), os.path.realpath(str(self.w.work)))
        # tmux: a new session named for the account, a window named for the session, exact targets
        calls = self.w.tmux_log()
        new = [c for c in calls if c[0] in ("new-session", "new-window")][0]
        self.assertEqual(new[new.index("-s") + 1], "csm-personal")
        self.assertEqual(new[new.index("-n") + 1], "moved-11111111")
        for c in calls:
            if "-t" in c:
                self.assertTrue(c[c.index("-t") + 1].startswith("="), c)
        # without --stop-source the source keeps running
        self.assertIsNone(src_proc.poll())

    def test_stop_source_after_the_link(self):
        src_proc = self.w.spawn()
        self.w.live(self.work, SID_A, src_proc.pid)
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--stop-source"))
        self.assertIn("stopped the source process", out)
        src_proc.wait(timeout=10)
        self.assertEqual(src_proc.returncode, -signal.SIGTERM)

    def test_a_failed_move_leaves_the_source_running(self):
        src_proc = self.w.spawn()
        self.w.live(self.work, SID_A, src_proc.pid)
        r = self.w.run("move", SID_A, "--to", "personal", "--stop-source",
                       FAKE_CLAUDE_NOURL="1", FAKE_CLAUDE_RC="1", FAKE_CLAUDE_SLEEP="0")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("LEFT RUNNING", r.stdout)
        self.assertIn("claude exited rc=1", r.stdout)
        time.sleep(0.3)
        self.assertIsNone(src_proc.poll())

    def test_never_stops_itself(self):
        src_proc = self.w.spawn()
        self.w.live(self.work, SID_A, src_proc.pid)
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--stop-source",
                                 CLAUDE_CODE_SESSION_ID=SID_A))
        self.assertIn("RUNNING on purpose", out)
        self.assertIsNone(src_proc.poll())

    def test_never_stops_a_pid_that_is_no_longer_claude(self):
        other = self.w.spawn("sleep")
        self.w.live(self.work, SID_A, other.pid, proc_start=ps_start(other.pid))
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--stop-source"))
        self.assertIn("not running the Claude Code CLI", out)
        self.assertIsNone(other.poll())

    def test_a_registry_row_with_no_start_time_is_never_signalled(self):
        # an older CLI's row: unprovable, so it is a refusal and not a name check
        other = self.w.spawn("sleep")
        self.w.live(self.work, SID_A, other.pid, proc_start="")
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--stop-source"))
        self.assertIn("recorded no start time", out)
        self.assertIn("nothing was proved", out)
        self.assertIsNone(other.poll())

    def test_never_stops_a_pid_whose_start_time_disagrees(self):
        # the registry file outlived its process and the pid was reused
        proc = self.w.spawn()
        self.w.live(self.work, SID_A, proc.pid, proc_start="Mon Jan  1 00:00:00 2001")
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--stop-source"))
        self.assertIn("has been reused", out)
        self.assertIsNone(proc.poll())

    def test_move_into_the_default_home_unsets_the_variable(self):
        default = self.w.account("default", "me@default.example", default=True)
        self.ok(self.w.run("move", SID_A, "--to", "default", CLAUDE_CONFIG_DIR=str(self.work)))
        env = self.w.claude_calls()[0]["env"]
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        self.assertTrue((default / "projects" / "-the-launch-spelling" / f"{SID_A}.jsonl").exists())
        st = json.loads((self.w.home / ".claude.json").read_text())   # outside ~/.claude
        self.assertTrue(st["projects"][str(self.w.work)]["hasTrustDialogAccepted"])
        self.assertFalse((default / ".claude.json").exists())

    def test_quiet_destination_is_backed_up_first(self):
        old = self.w.session(self.personal, SID_A, folder="-the-launch-spelling",
                             mtime=time.time() - 5000,
                             lines=[user("an older copy", str(self.w.work), SID_A)])
        rows = json.loads(self.ok(self.w.run("list", "--json")))
        row = [r["pos"] for r in rows if r["account"] == "work" and r["local_id"] == SID_A][0]
        self.ok(self.w.run("move", str(row), "--to", "personal"))
        baks = list(old.parent.glob(f"{SID_A}.jsonl.csm-bak-*"))
        self.assertEqual(len(baks), 1)
        self.assertIn("an older copy", baks[0].read_text())

    def test_the_trust_dialog_is_walked_to_yes_one_key_per_poll(self):
        # 🛑 The dialog as the CLI really draws it: cancel FIRST, focused, and no numbers.
        script = self.w.root / "screens.json"
        script.write_text(json.dumps([
            "Accessing workspace:\n\n Quick safety check: Is this a project you created or one "
            "you trust?\n\n ❯ No, exit\n   Yes, I trust this folder\n",
            "Accessing workspace:\n\n Is this a project you created or one you trust?\n\n"
            "   No, exit\n ❯ Yes, I trust this folder\n"]))
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", FAKE_TMUX_SCRIPT=script))
        self.assertIn(LINK, out)
        keys = [c[-1] for c in self.w.tmux_log() if c[0] == "send-keys"]
        self.assertEqual(keys, ["Down", "Enter"])

    def test_bypass_warning_is_only_accepted_for_a_bypass_session(self):
        script = self.w.root / "screens.json"
        warning = ("WARNING: Claude Code running in Bypass Permissions mode\n"
                   " ❯ No, exit\n   Yes, I accept\n")
        accepted = ("WARNING: Claude Code running in Bypass Permissions mode\n"
                    "   No, exit\n ❯ Yes, I accept\n")
        script.write_text(json.dumps([warning, accepted]))
        self.ok(self.w.run("move", SID_A, "--to", "personal", FAKE_TMUX_SCRIPT=script))
        keys = [c[-1] for c in self.w.tmux_log() if c[0] == "send-keys"]
        self.assertEqual(keys, ["Down", "Enter"])
        # the same screen for a session that did NOT run in bypass mode: no key at all
        cwd = str(self.w.work)
        self.w.session(self.work, SID_B, lines=[
            user("careful work", cwd, SID_B, perm="acceptEdits"), assistant("ok", cwd, SID_B)])
        self.w.tmux_calls.unlink()
        script.write_text(json.dumps([warning, warning]))
        self.ok(self.w.run("move", SID_B, "--to", "personal", FAKE_TMUX_SCRIPT=script))
        self.assertEqual([c for c in self.w.tmux_log() if c[0] == "send-keys"], [])

    def test_no_remote_control_mode(self):
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--no-remote-control",
                                 FAKE_CLAUDE_SLEEP="3"))
        self.assertIn("tmux attach", out)
        argv = self.w.claude_calls()[0]["argv"]
        self.assertFalse(any(a.startswith("--remote-control") for a in argv))

    def test_foreground_execs_claude_here(self):
        r = self.w.run("move", SID_A, "--to", "personal", "--foreground", FAKE_CLAUDE_SLEEP="0")
        self.assertIn("fake claude running", self.ok(r))
        call = self.w.claude_calls()[0]
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], str(self.personal))
        self.assertFalse(any(a.startswith("--remote-control") for a in call["argv"]))
        self.assertEqual(self.w.tmux_log(), [])

    def test_target_out_of_quota_too_is_a_warning(self):
        cwd = str(self.w.work)
        self.w.session(self.personal, SID_B, lines=[
            user("x", cwd, SID_B),
            assistant("limit", cwd, SID_B, error="usage_limit_reached",
                      resets=int(time.time() + 1800), kind="seven_day")])
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run"))
        self.assertIn("may be out of quota TOO", out)


# ------------------------------------------------------------------- another machine

def slug_of(cwd: str) -> str:
    """The project folder name the CLI gives a directory: every non-alphanumeric -> `-`."""
    return re.sub(r"[^A-Za-z0-9]", "-", cwd)


DESK_SID = "90c2bd49-0000-4000-8000-000000000000"


class CrossMachine(Base):
    """🛑 `find` and `--from-machine`, against a fixture "other machine".

    `CSM_REMOTE_LOCAL=1` makes the other machine THIS process, with `HOME` pointed at
    `<tmp>/remote`, so the real `REMOTE_HELPER` runs (as `python3 -I -`, exactly the way ssh
    runs it) and the real tar pipe runs — with no ssh, no second machine and no network.
    The fixture is shaped like the session the feature exists for: a DESKTOP-APP session in
    the DEFAULT home, its title only in the app's own index, out of quota, and its working
    directory absent on this machine.
    """

    def setUp(self):
        super().setUp()
        self.remote = self.w.root / "remote"
        self.gone = str(self.w.root / "only-over-there" / "firmware")
        home = self.remote / ".claude"
        d = home / "projects" / slug_of(self.gone)
        d.mkdir(parents=True)
        (d / (DESK_SID + ".jsonl")).write_text(jl(
            user("deploy to the handset", self.gone, DESK_SID, perm="bypassPermissions"),
            assistant("on it", self.gone, DESK_SID, model="claude-opus-4-1"),
            {"type": "ai-title", "aiTitle": "Handset deploy", "sessionId": DESK_SID}))
        # a sibling directory, and a subagent transcript that must never be a row of its own
        (d / DESK_SID / "subagents").mkdir(parents=True)
        (d / DESK_SID / "subagents" / "agent-1.jsonl").write_text('{"isSidechain": true}\n')
        (self.remote / ".claude.json").write_text(json.dumps(
            {"oauthAccount": {"emailAddress": "you@desk.example",
                              "organizationUuid": "org-desk"}}))
        idx = (self.remote / "Library" / "Application Support" / "Claude"
               / "claude-code-sessions" / "acct" / "org")
        idx.mkdir(parents=True)
        (idx / ("local_" + DESK_SID + ".json")).write_text(json.dumps({
            "sessionId": "local_" + DESK_SID, "cliSessionId": DESK_SID, "cwd": self.gone,
            "title": "Finish the handset deploy and verify it",
            "permissionMode": "bypassPermissions", "effort": "xhigh",
            "error": "You've hit your session limit · resets 12:20pm",
            "bridgeSessionIds": ["session_01QVqhJ3dyik6cTyZ3yMANoy"]}))
        self.imports = self.w.root / "imports"
        self.renv = {"CSM_REMOTE_LOCAL": "1", "CSM_REMOTE_HOME": str(self.remote),
                     "CSM_IMPORTS": str(self.imports), "CSM_MACHINE": "here"}

    def csm(self, *args, **env):
        e = dict(self.renv)
        e.update({k: str(v) for k, v in env.items()})
        return self.w.run(*args, **e)

    def rows(self, *args):
        return json.loads(self.ok(self.csm("find", *(args + ("--json",)))))

    # --- find -------------------------------------------------------------
    def test_find_sees_a_desktop_session_in_the_default_home_by_the_apps_own_title(self):
        # The title is ONLY in the desktop index; the transcript's own is "Handset deploy".
        out = self.ok(self.csm("find", "finish the handset", "--on", "desktop"))
        self.assertIn("Finish the handset deploy", out)
        self.assertIn("[desktop app]", out)
        self.assertIn("OUT OF QUOTA", out)
        self.assertIn("you@desk.example", out)
        self.assertIn("--from-machine desktop", out)

    def test_find_matches_the_cli_id_the_desktop_id_and_the_link(self):
        for spec in ("90c2bd", "local_90c2bd",
                     "https://claude.ai/code/session_01QVqhJ3dyik6cTyZ3yMANoy"):
            self.assertEqual([x["id"] for x in self.rows(spec, "--on", "desktop")],
                             [DESK_SID], spec)
        # and the subagent's own transcript is never a row
        self.assertEqual([x["id"] for x in self.rows("", "--on", "desktop")], [DESK_SID])

    def test_find_says_what_the_age_is_and_that_a_move_is_a_copy(self):
        out = self.ok(self.csm("find", "handset", "--on", "desktop"))
        self.assertIn("transcript file's last write", out)
        self.assertIn("one moved session is two rows", out)

    def test_nothing_matching_exits_1_and_says_0_rows_is_not_proof(self):
        """🛑 It used to exit 0 whatever it found, which reads as "asked and answered".

        The exit code was verified unused before it was changed: nothing under
        the wrapper — the one installation that drives csm from scheduled passes — runs
        `find` at all. A caller wanting rows counts `--json`, never the status.
        """
        r = self.csm("find", "no-such-session", "--on", "desktop")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no session on desktop matches", r.stdout)
        self.assertIn("0 rows is not proof", r.stdout)
        self.assertIn("Paste its claude.ai link", r.stdout)
        self.assertIn("--all", r.stdout)
        self.assertNotIn("--from-machine", r.stdout)

    def test_a_link_that_matches_nothing_says_which_FILE_it_wanted(self):
        r = self.csm("find", link_of(LINK_BARE), "--on", "desktop")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(LINK_SID, r.stdout)
        self.assertIn("session_" + LINK_BARE, r.stdout)
        self.assertNotIn("Paste its claude.ai link", r.stdout, "it already is one")

    def test_a_json_find_with_no_rows_keeps_stdout_pure_json_and_exits_1(self):
        r = self.csm("find", "no-such-session", "--on", "desktop", "--json")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(json.loads(r.stdout), [])
        self.assertIn("0 rows is not proof", r.stderr)

    # --- a link, resolved by arithmetic, over there ------------------------
    def dead_child_over_there(self, sid=LINK_SID, folder=None, lines=None):
        """A session as a dead Remote Control child leaves it on the other machine: the
        transcript's NAME is the only thing tying it to its claude.ai link."""
        cwd = str(self.w.work)
        d = self.remote / ".claude-work2" / "projects" / (folder or slug_of(cwd))
        d.mkdir(parents=True, exist_ok=True)
        (d / (sid + ".jsonl")).write_text(jl(*(lines or [
            user("the one that died over there", cwd, sid),
            assistant("working on it", cwd, sid)])))
        (self.remote / ".claude-work2" / ".claude.json").write_text(json.dumps(
            {"oauthAccount": {"emailAddress": "you@two.example",
                              "organizationUuid": "org-two"}}))
        return d / (sid + ".jsonl")

    def test_find_resolves_a_dead_link_over_there_by_deriving_the_transcript_name(self):
        t = self.dead_child_over_there()
        os.utime(str(t), (time.time() - 90 * 86400,) * 2)    # past the 21-day window too
        rows = self.rows(link_of(LINK_BARE), "--on", "desktop")
        self.assertEqual([x["id"] for x in rows], [LINK_SID])
        self.assertEqual(rows[0]["hit"], "url")
        self.assertEqual(rows[0]["email"], "you@two.example")

    def test_a_spacesheep_session_link_resolves_over_there_as_well(self):
        self.dead_child_over_there()
        rows = self.rows("https://spacesheep.dev/sessions/claude-code/" + LINK_SID,
                         "--on", "desktop")
        self.assertEqual([x["id"] for x in rows], [LINK_SID])

    def test_find_resolves_a_LIVE_childs_link_through_the_registry_over_there(self):
        """A running server child's transcript carries no bridge id at all, so before this
        the helper could not match its link either — `find` failed for live sessions too."""
        sid = "77777777-aaaa-4aaa-8aaa-777777777777"
        self.dead_child_over_there(sid=sid, lines=[
            user("the live child", str(self.w.work), sid)])
        sess = self.remote / ".claude-work2" / "sessions"
        sess.mkdir(exist_ok=True)
        (sess / "4242.json").write_text(json.dumps(
            {"pid": 4242, "sessionId": sid, "cwd": str(self.w.work),
             "bridgeSessionId": "cse_" + LINK_BARE2, "status": "idle",
             "entrypoint": "sdk-cli"}))
        rows = self.rows(link_of(LINK_BARE2), "--on", "desktop")
        self.assertEqual([x["id"] for x in rows], [sid])
        self.assertEqual(rows[0]["bridge"], LINK_BARE2)

    def test_find_resolves_a_link_through_a_bridge_status_url_over_there(self):
        sid = "88888888-bbbb-4bbb-8bbb-888888888888"
        self.dead_child_over_there(sid=sid, lines=[
            user("the self-hosted one", str(self.w.work), sid),
            {"type": "system", "subtype": "bridge_status", "sessionId": sid,
             "content": "/remote-control is active · Continue here, on your phone",
             "url": link_of(LINK_BARE2)}])
        rows = self.rows(link_of(LINK_BARE2), "--on", "desktop")
        self.assertEqual([x["id"] for x in rows], [sid])
        self.assertEqual(rows[0]["bridge"], LINK_BARE2)

    def test_find_with_no_on_reads_this_machines_own_homes(self):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[user("local work here", cwd, SID_A)])
        env = dict(self.renv)
        env.pop("CSM_REMOTE_LOCAL")           # really local: no fixture tree in the way
        env.pop("CSM_REMOTE_HOME")
        out = self.ok(self.w.run("find", "local work", **env))
        self.assertIn(SID_A[:8], out)
        self.assertIn("local work here", out)
        self.assertNotIn("--from-machine", out, "nothing to bring: it is already here")

    def test_on_this_machine_is_the_same_as_no_on(self):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[user("right here", cwd, SID_A)])
        env = dict(self.renv)
        env.pop("CSM_REMOTE_LOCAL")
        env.pop("CSM_REMOTE_HOME")
        out = self.ok(self.w.run("find", "right here", "--on", "here", **env))
        self.assertIn(SID_A[:8], out)
        self.assertNotIn("--from-machine", out)

    def test_find_on_a_machine_the_table_does_not_know_is_refused(self):
        tsv = self.w.table(("job", "me@work.example", self.work, "here,desktop", "wk"))
        self.refused(self.w.run("find", "x", "--on", "mars", CSM_ACCOUNTS=str(tsv),
                                CSM_MACHINE="here"),
                     "not a machine this tool knows", "desktop")

    # --- the refusals -----------------------------------------------------
    def test_a_missing_folder_is_refused_and_names_mirror_cwd(self):
        r = self.csm("move", "90c2bd", "--from-machine", "desktop", "--to", "personal")
        self.refused(r, "does not exist on here", "pass --mirror-cwd")
        self.assertFalse(self.imports.exists(), "nothing is staged on a refusal")

    def test_two_machines_that_spell_home_alike_still_refuse_a_folder_that_is_not_here(self):
        """⚠️ When the two machines spell home identically, home-to-home is an IDENTITY:
        a folder translates to itself whether or not it exists here, so nothing in the
        translation can tell the two cases apart. `preflight`'s missing-folder refusal is
        the only thing between that and a resume in a directory that is not there."""
        absent = str(self.w.home / "went-away")
        d = self.remote / ".claude" / "projects" / slug_of(absent)
        d.mkdir(parents=True)
        (d / (SID_B + ".jsonl")).write_text(jl(user("still going", absent, SID_B)))
        mj = self.w.root / "same-home.json"
        mj.write_text(json.dumps({"desktop": {"home": str(self.w.home)},
                                  "here": {"home": str(self.w.home)}}))
        r = self.csm("move", SID_B[:8], "--from-machine", "desktop", "--to", "personal",
                     CSM_MACHINES=str(mj))
        self.refused(r, absent, "does not exist on here", "pass --mirror-cwd")
        self.assertFalse(self.imports.exists())

    def test_mirror_cwd_without_from_machine_is_refused(self):
        self.refused(self.csm("move", SID_A, "--to", "personal", "--mirror-cwd"),
                     "--mirror-cwd goes with --from-machine")

    def test_from_machine_naming_this_machine_is_refused(self):
        self.refused(self.csm("move", "90c2bd", "--from-machine", "here", "--to", "personal"),
                     "is this machine", "drop the flag")

    def test_staging_inside_a_config_homes_projects_is_refused_before_anything_is_fetched(self):
        """🛑 The one delete in this tool is aimed by a knob, so the knob is checked.

        A leftover staging file is removed before the fetch, so that "the copy did not
        arrive" can be told from "a file was already there". `CSM_IMPORTS` pointed inside a
        `projects/` tree would make that delete a transcript of that account's — the one
        thing this tool promises never to do — and the file's own note said "never
        anybody's `projects/`" with nothing holding it to that.
        """
        victim = self.personal / "projects" / slug_of(str(self.w.work))
        victim.mkdir(parents=True, exist_ok=True)
        keep = victim / (DESK_SID + ".jsonl")
        keep.write_text(jl(user("a transcript of its own", str(self.w.work), DESK_SID)))
        r = self.csm("move", DESK_SID, "--from-machine", "desktop", "--to", "personal",
                     "--dry-run", CSM_IMPORTS=str(victim))
        self.refused(r, "CSM_IMPORTS", "projects/", "outside every config home")
        self.assertIn("a transcript of its own", keep.read_text())
        # and a staging directory of its own is fine
        self.ok(self.csm("move", DESK_SID, "--from-machine", "desktop", "--to", "personal",
                         "--dry-run", "--mirror-cwd"))

    def test_an_unknown_machine_is_refused_naming_the_ones_it_knows(self):
        tsv = self.w.table(("job", "me@work.example", self.work, "here,desktop", "wk"))
        self.refused(self.w.run("move", "90c2bd", "--from-machine", "mars", "--to",
                                "personal", CSM_ACCOUNTS=str(tsv), CSM_MACHINE="here"),
                     "not a machine this tool knows", "desktop")

    def test_stop_source_is_refused_across_machines(self):
        os.makedirs(self.gone)
        out = self.ok(self.csm("move", "90c2bd", "--from-machine", "desktop", "--to",
                               "personal", "--stop-source", "--dry-run"))
        self.assertIn("never stops a process on another machine", out)
        r = self.csm("move", "90c2bd", "--from-machine", "desktop", "--to", "personal",
                     "--stop-source")
        self.refused(r, "never stops a process on another machine")

    def test_auto_never_hands_a_session_back_to_the_account_it_already_runs_as(self):
        """🛑 The whole reason `auto_target` compares FIELDS and not names.

        A `--from-machine` source is a SYNTHESISED account whose name is
        `<machine>:<home>` by construction, so that it can never equal a target's — moving
        the same account to another machine is a real move. Comparing names therefore
        matches nothing here, and `auto` would hand the session straight back to the
        account it is already running as, on a machine where it has no more quota than it
        had. The login is what identifies it, and this is the only shape that proves it:
        the same-machine case passes on the name alone.
        """
        os.makedirs(self.gone)
        twin = self.w.account("twin", "you@desk.example", org="org-desk")
        tbl = self.w.table(
            ("work", "me@work.example", self.work, "here", "wk"),
            ("personal", "me@home.example", self.personal, "here", "pers"),
            ("twin", "you@desk.example", twin, "here", "tw"))
        # the account signed in as the SOURCE's own login has by far the most room, so
        # nothing but the identity check can keep `auto` off it
        m = self.w.meters(tw=(0, 1, 60), pers=(0, 50, 60), wk=(0, 70, 60))
        out = self.ok(self.csm("move", "90c2bd", "--from-machine", "desktop", "--to",
                               "auto", "--dry-run", CSM_ACCOUNTS=str(tbl),
                               CSM_METERS=str(m)))
        self.assertIn("--to auto: pers", out)
        self.assertNotIn("--to auto: tw", out)
        self.assertIn("→  pers (me@home.example)", out)

    def test_a_mirror_onto_a_folder_that_is_already_here_is_refused(self):
        os.makedirs(self.gone)
        out = self.ok(self.csm("move", "90c2bd", "--from-machine", "desktop", "--to",
                               "personal", "--mirror-cwd", "--dry-run"))
        self.assertIn("never writes into an existing folder", out)

    def test_a_third_home_that_shares_the_targets_tree_is_asked_before_the_copy(self):
        """🛑 `dest` can be held by a home that is neither the source nor the target.

        Where several homes' `projects/` are ONE directory the transcript exists once on
        the machine, so the process writing `dest` need not be in the target home's own
        registry. The sweep that asks every such home used to be gated on whether the
        SOURCE and the target file it in one directory — which, for a `--from-machine`
        move, is false by construction (the source's tree is the staging area), so the
        sweep never ran on the move most likely to land on a transcript a local process
        is writing.
        """
        os.makedirs(self.gone)
        third = self.w.account("elsewhere", "me@other.example", org="org-3")
        shutil.rmtree(str(third / "projects"))
        os.symlink(str(self.personal / "projects"), str(third / "projects"))
        # what an earlier move left in the shared tree, and the pid writing it now
        d = self.personal / "projects" / slug_of(self.gone)
        d.mkdir(parents=True, exist_ok=True)
        (d / (DESK_SID + ".jsonl")).write_text(jl(user("deploy", self.gone, DESK_SID)))
        self.w.live(third, DESK_SID, self.w.spawn().pid, cwd=self.gone)
        r = self.csm("move", "90c2bd", "--from-machine", "desktop", "--to", "personal")
        self.refused(r, "ALREADY running", "elsewhere")
        self.assertFalse(self.imports.exists(), "nothing is staged on a refusal")

    def test_a_home_with_its_own_tree_running_the_same_id_is_not_that_transcripts_writer(self):
        """The other half of the same rule: a home whose `projects/` is its OWN directory
        holds its own copy of the id, which is a different file — not a second writer of
        `dest`, and not a refusal."""
        os.makedirs(self.gone)
        third = self.w.account("elsewhere", "me@other.example", org="org-3")
        d = self.personal / "projects" / slug_of(self.gone)
        d.mkdir(parents=True, exist_ok=True)
        (d / (DESK_SID + ".jsonl")).write_text(jl(user("deploy", self.gone, DESK_SID)))
        self.w.session(third, DESK_SID, cwd=self.gone, folder=slug_of(self.gone))
        self.w.live(third, DESK_SID, self.w.spawn().pid, cwd=self.gone)
        out = self.ok(self.csm("move", "90c2bd", "--from-machine", "desktop", "--to",
                               "personal", "--dry-run"))
        self.assertNotIn("ALREADY running", out)

    def test_a_mirror_that_cannot_make_the_folder_here_is_refused_in_one_line(self):
        """🛑 A folder the two machines spell differently and NO rule maps is left as the
        origin's own absolute path, and its parent here can be a directory this user may
        not write — another account's home, a system root. That is a sentence to print,
        not an OSError to raise through the middle of a move."""
        remote_real = Path(os.path.realpath(str(self.remote)))
        here_real = Path(os.path.realpath(str(self.w.home)))
        src = remote_real / "locked" / "sub" / "repo"
        src.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(src)], check=True)
        d = self.remote / ".claude" / "projects" / slug_of(str(src))
        d.mkdir(parents=True)
        (d / (SID_C + ".jsonl")).write_text(jl(user("build it", str(src), SID_C)))
        locked = here_real / "locked"
        locked.mkdir()
        mj = self.w.root / "machines.json"
        mj.write_text(json.dumps({"desktop": {"home": str(remote_real)},
                                  "here": {"home": str(here_real)}}))
        os.chmod(str(locked), 0o500)                 # traversable, not writable
        try:
            r = self.csm("move", SID_C[:8], "--from-machine", "desktop", "--to",
                         "personal", "--mirror-cwd", CSM_MACHINES=str(mj))
        finally:
            # ⚠️ Put it back HERE, not in a cleanup: cleanups run after `tearDown`, which
            # has already deleted the tree the directory was in.
            os.chmod(str(locked), 0o700)
        self.refused(r, "--mirror-cwd cannot create", "Clone the repository here")
        self.assertEqual(self.w.claude_calls(wait=0.2), [], "nothing was started")

    def test_two_matches_are_refused_naming_the_ids(self):
        other = "7777aaaa-0000-4000-8000-000000000000"
        d = self.remote / ".claude" / "projects" / slug_of(self.gone)
        (d / (other + ".jsonl")).write_text(jl(
            user("deploy to the handset too", self.gone, other),
            {"type": "ai-title", "aiTitle": "Handset deploy, again"}))
        r = self.csm("move", "handset", "--from-machine", "desktop", "--to", "personal")
        self.refused(r, "sessions on desktop match", DESK_SID[:8], other[:8])

    # --- the plan ---------------------------------------------------------
    def test_the_dry_run_shows_the_fetch_the_effort_and_what_stayed_behind(self):
        os.makedirs(self.gone)                      # as if the folder were already here
        out = self.ok(self.csm("move", "90c2bd", "--from-machine", "desktop", "--to",
                               "personal", "--dry-run"))
        self.assertIn("FROM THE MACHINE desktop", out)
        self.assertIn("fetch 90c2bd49", out)
        self.assertIn("and 90c2bd49-0000-4000-8000-000000000000/ (1 files", out,
                      "the sibling directory crosses with it")
        self.assertIn("--effort xhigh", out)
        self.assertIn("[desktop app session local_90c2bd49", out)
        self.assertIn("a separate working tree", out)
        self.assertIn("out of quota", out)
        self.assertFalse(self.imports.exists(), "a dry run fetches nothing")

    def test_the_same_account_on_another_machine_is_a_move_not_a_refusal(self):
        os.makedirs(self.gone)
        # the target home holds the login the fixture session is signed in as
        (self.personal / ".claude.json").write_text(json.dumps(
            {"oauthAccount": {"emailAddress": "you@desk.example",
                              "organizationUuid": "org-desk"}}))
        out = self.ok(self.csm("move", "90c2bd", "--from-machine", "desktop", "--to",
                               "personal", "--dry-run"))
        self.assertIn("on the same account (you@desk.example)", out)
        self.assertIn("changes the machine, not the quota", out)

    def test_a_synced_folder_is_named_as_the_same_folder(self):
        sync = self.w.home / "shared" / "proj"
        sync.mkdir(parents=True)
        d = self.remote / ".claude" / "projects" / slug_of(str(sync))
        d.mkdir(parents=True)
        (d / (SID_B + ".jsonl")).write_text(jl(user("in the synced tree", str(sync), SID_B)))
        out = self.ok(self.csm("move", SID_B[:8], "--from-machine", "desktop", "--to",
                               "personal", "--dry-run", CSM_SYNC_DIRS="shared"))
        self.assertIn("the same synced folder as on desktop", out)

    # --- the real thing ---------------------------------------------------
    def test_a_cross_machine_move_stages_the_transcript_and_resumes_it_here(self):
        os.makedirs(self.gone)
        out = self.ok(self.csm("move", "90c2bd", "--from-machine", "desktop", "--to",
                               "personal"))
        self.assertIn(LINK, out)
        self.assertIn("the original is NOT stopped", out)
        self.assertIn("still open in the DESKTOP APP there", out)
        # staged, under the machine it came from, and KEPT as the record of what crossed
        staged = self.imports / "desktop" / slug_of(self.gone) / (DESK_SID + ".jsonl")
        self.assertTrue(staged.is_file(), sorted(str(p) for p in self.imports.rglob("*")))
        self.assertTrue((staged.parent / DESK_SID / "subagents" / "agent-1.jsonl").is_file(),
                        "the sibling directory crosses with it")
        self.assertFalse(any(p.name.startswith("._") for p in staged.parent.iterdir()),
                         "no AppleDouble files from tar")
        # and filed into the target home from there
        dest = self.personal / "projects" / slug_of(self.gone) / (DESK_SID + ".jsonl")
        self.assertEqual(dest.read_bytes(), staged.read_bytes())
        # the source on the other machine is untouched
        there = (self.remote / ".claude" / "projects" / slug_of(self.gone)
                 / (DESK_SID + ".jsonl"))
        self.assertTrue(there.is_file())
        argv = self.w.claude_calls()[0]["argv"]
        self.assertEqual(argv[-2:], ["--resume", DESK_SID])
        self.assertEqual(argv[argv.index("--effort") + 1], "xhigh")
        # 🛑 The Remote Control label keeps the TITLE: the provenance half is the source's
        # short label, not its `<machine>:<config home>` name, which left eight characters
        # of title.
        rc = [a for a in argv if a.startswith("--remote-control=")][0]
        self.assertIn("Finish the handset", rc, rc)
        self.assertTrue(rc.endswith("moved from you desk.example desktop"), rc)

    def test_a_mirror_brings_the_code_across_and_the_move_resumes_in_it(self):
        # ⚠️ Realpaths throughout: `git rev-parse --show-toplevel` resolves symlinks, and a
        # temporary directory on macOS is reached through one, so a fixture that mixed the
        # two spellings would measure the symlink and not the rule.
        remote_real = Path(os.path.realpath(str(self.remote)))
        here_real = Path(os.path.realpath(str(self.w.home)))
        src = remote_real / "tree"            # the folder as the other machine spells it
        src.mkdir()
        g = ["git", "-C", str(src), "-c", "user.email=t@t", "-c", "user.name=t"]
        env = dict(os.environ)
        env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_CONFIG_NOSYSTEM": "1"})
        subprocess.run(g + ["init", "-q"], check=True, env=env)
        (src / ".gitignore").write_text("*.rec\n")
        (src / "code.py").write_text("print(1)\n")
        subprocess.run(g + ["add", "-A"], check=True, env=env)
        subprocess.run(g + ["commit", "-qm", "one"], check=True, env=env)
        (src / "frames.rec").write_bytes(b"\0" * 4096)
        # a session in THAT folder, which does not exist here under its own spelling
        d = self.remote / ".claude" / "projects" / slug_of(str(src))
        d.mkdir(parents=True)
        (d / (SID_C + ".jsonl")).write_text(jl(user("build it", str(src), SID_C)))
        mj = self.w.root / "machines.json"
        mj.write_text(json.dumps({"desktop": {"home": str(remote_real)},
                                  "here": {"home": str(here_real)}}))
        out = self.ok(self.csm("move", SID_C[:8], "--from-machine", "desktop", "--to",
                               "personal", "--mirror-cwd", CSM_MACHINES=str(mj)))
        # this machine's OWN spelling of the folder, which is what the plan must promise:
        # the step used to print the origin's path as the destination.
        here = self.w.home / "tree"
        self.assertIn("is %s here" % here, out)
        self.assertIn("mirror the code into %s on here" % here, out)
        self.assertEqual((here / "code.py").read_text(), "print(1)\n")
        self.assertFalse((here / "frames.rec").exists(), "an ignored file never crosses")
        self.assertTrue((here / ".git").is_dir())
        self.assertEqual(os.path.realpath(self.w.claude_calls()[0]["cwd"]),
                         os.path.realpath(str(here)))


class RemoteHelper(unittest.TestCase):
    """The helper's `detail` and `mirror` modes, run the way ssh runs them (`python3 -I -`)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        # 🛑 A UNIT TEST MAY NOT READ THE MACHINE'S OWN GIT CONFIG. A global
        # `url.https://github.com/.insteadOf git@github.com:` — a reasonable thing to have
        # — rewrites every fixture remote on the way out, so a remote added as
        # `git@github.com:…` reads back as `https://…`, which is not the shape
        # `github_https_fallback` is about: the test would then measure the machine instead
        # of the code. Git reads the global and system files for every command, so both are
        # pinned away here; the one `git commit` below passes user.name/email with `-c`.
        for var, val in (("GIT_CONFIG_GLOBAL", os.devnull),
                         ("GIT_CONFIG_SYSTEM", os.devnull),
                         ("GIT_CONFIG_NOSYSTEM", "1")):
            was = os.environ.get(var)
            os.environ[var] = val
            self.addCleanup(lambda v=var, o=was:
                            os.environ.__setitem__(v, o) if o is not None
                            else os.environ.pop(v, None))
        self.mod = load_tool()
        self.mod.LOG = self.dir / "log"
        self.addCleanup(sys.modules.pop, "csm_mod", None)

    def helper(self, *args, **kw):
        # ⚠️ `home` replaces HOME for this run: the helper discovers config homes under `~`
        # (`.claude` and `.claude-*` with a `projects/`), so a test about what it READS has
        # to own that directory rather than the machine's.
        env = dict(os.environ)
        if kw.get("home"):
            env["HOME"] = str(kw["home"])
        r = subprocess.run([PY] + list(kw.get("flags", ("-I", "-"))) + [str(a) for a in args],
                           input=self.mod.REMOTE_HELPER, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=120,
                           cwd=kw.get("cwd"), env=env)
        if kw.get("raw"):
            return r
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_fixture_is_deaf_to_the_machines_own_git_config(self):
        """The guard for the setUp above: an ambient `url.…insteadOf` must not reach here."""
        repo = self.dir / "iso"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "git@github.com:someone/x.git"], check=True)
        url = subprocess.run(["git", "-C", str(repo), "remote", "get-url", "origin"],
                             stdout=subprocess.PIPE, universal_newlines=True).stdout.strip()
        self.assertEqual(url, "git@github.com:someone/x.git",
                         "a url.insteadOf from the machine's git config is leaking into the "
                         "fixture — isolate it in setUp, do not relax the assertion")

    def test_a_stray_module_in_the_working_directory_cannot_shadow_the_standard_library(self):
        """🛑 Over ssh the working directory is the remote account's HOME, and `python3 -`
        puts it on `sys.path`: a scratch `re.py` there is imported instead of the standard
        library's. Measured: it broke every mode of the helper with an AttributeError.
        `-I` is what keeps that out, and this is the test that says so."""
        (self.dir / "re.py").write_text("raise SystemExit('the stray file ran')\n")
        (self.dir / "json.py").write_text("raise SystemExit('the stray file ran')\n")
        bad = self.helper("detail", str(self.dir / "x.jsonl"), "no-such-id",
                          flags=("-",), cwd=str(self.dir), raw=True)
        self.assertNotEqual(bad.returncode, 0, "the stray file should have broken this")
        got = self.helper("detail", str(self.dir / "x.jsonl"), "no-such-id",
                          cwd=str(self.dir))
        self.assertEqual(got["owners"], [])

    def test_the_owner_is_matched_by_its_resume_flag_and_its_children_are_listed(self):
        sid = "4b4b4b4b-0000-4000-8000-000000000000"
        owner = subprocess.Popen(
            [PY, "-c", "import subprocess,time; subprocess.Popen(['sleep','40']); "
                       "time.sleep(40)", "--resume=" + sid])
        # a DECOY: a side session's argv names the id inside a path, never after --resume
        decoy = subprocess.Popen([PY, "-c", "import time; time.sleep(40)",
                                  "/x/side-notes/local_" + sid])
        for p in (owner, decoy):
            self.addCleanup(p.wait)        # cleanups run last in first out: kill, then wait
            self.addCleanup(p.kill)
        time.sleep(1.0)
        t = self.dir / (sid + ".jsonl")
        t.write_text('{"type":"user"}\n{"name":"mcp__ccd_session__start_session"}\n')
        det = self.helper("detail", str(t), sid)
        self.assertEqual([o["pid"] for o in det["owners"]], [owner.pid])
        left = [p for p in det["left"] if p["cmd"].startswith("sleep 40")]
        self.assertTrue(left, det)
        self.assertEqual(det["app_tools"], 1)
        # 🛑 The grandchild is killed BY THE PID `detail` just reported, never by matching
        # its command line: `pkill -f '^sleep 40$'` reaches outside the fixture and would
        # end an unrelated `sleep 40` belonging to whoever is running the suite.
        for p in left:
            try:
                os.kill(p["pid"], signal.SIGKILL)
            except OSError:
                pass

    def test_a_server_childs_owner_is_found_by_its_cse_id_and_not_by_the_local_uuid(self):
        """🛑 IT FAILED IN THE DANGEROUS DIRECTION: "nothing is running there".

        A Remote Control server's child runs `--print --sdk-url …/cse_X --session-id cse_X
        --resume=<that url>` and names the local uuid NOWHERE (measured on CLI 2.1.312,
        Wed 28 Oct 2026). `detail` matched on the local uuid alone, so it reported no owner
        — and that is what `--stop-source`'s cross-machine refusal and the move note's
        "still running on <origin>" clause both read, so a `--from-machine` move of a
        session that was very much alive said the other machine was idle.
        """
        # 🛑 A MADE-UP BRIDGE ID, NOT ONE OF THE MEASURED PAIRS, and this test is the
        # reason the rule exists: `detail` sweeps the WHOLE machine's `ps`, and the two
        # measured ids in `LINK_BARE`/`LINK_BARE2` were read off this machine's own live
        # registry — so the first draft of this test matched a real Remote Control worker
        # (pid 91121) beside its fixture and the assertion failed. A fixture that names a
        # real session reaches outside itself; `detail` only reads, but the next sweep that
        # acts on an owner would not.
        bare = "01FixtureOnlyNeverReal00"
        sid = "4b4b4b4b-1111-5111-8111-111111111111"
        url = "https://api.anthropic.com/v1/code/sessions/cse_" + bare
        worker = subprocess.Popen([PY, "-c", "import time; time.sleep(40)", "--print",
                                   "--sdk-url", url, "--session-id", "cse_" + bare,
                                   "--resume=" + url])
        # a DECOY: the bridge id in a path, not after a flag that means "this is my session"
        decoy = subprocess.Popen([PY, "-c", "import time; time.sleep(40)",
                                  "/x/logs/cse_" + bare + ".log"])
        for p in (worker, decoy):
            self.addCleanup(p.wait)        # cleanups run last in first out: kill, then wait
            self.addCleanup(p.kill)
        time.sleep(1.0)
        t = self.dir / (sid + ".jsonl")
        t.write_text('{"type":"user"}\n')
        det = self.helper("detail", str(t), sid, bare)
        self.assertEqual([o["pid"] for o in det["owners"]], [worker.pid])
        # ...and without the bridge id it is still blind, which is what the third word fixes
        self.assertEqual(self.helper("detail", str(t), sid)["owners"], [])
        # a bridge id that is not this one must not match either
        self.assertEqual(
            self.helper("detail", str(t), sid, "01SomeOtherFixtureId000")["owners"], [])

    def test_the_helpers_find_reads_BOTH_quota_shapes_like_the_engine(self):
        """🛑 ONE READING RULE, which is `cmd_find`'s own promise: "it does it through the
        same helper whether the machine is this one or another, so a row found here and a row
        found there are the same row." M2's widened detection landed in `scan_transcript` and
        in `revive_stop` and not in the helper's `scan`, whose `elif not err` branch actively
        CLEARED a quota found on an earlier line — so `csm find` reported no quota for the 10
        of 44 measured stop lines that carry no `apiError`, while `csm list` reported one and
        `csm revive` said `usage-limit`. This class never exercised `scan` at all.
        """
        home = self.dir / "h1"
        for shape, sid in (("apiError", SID_A), ("rate_limit", SID_B)):
            d = home / ".claude" / "projects" / "-work"
            d.mkdir(parents=True, exist_ok=True)
            (d / (sid + ".jsonl")).write_text(jl(
                user("go", "/work", sid),
                assistant("You've hit your weekly limit · resets 10pm", "/work", sid,
                          error="usage_limit_reached", resets=time.time() + 3600,
                          shape=shape)))
        for shape, sid in (("apiError", SID_A), ("rate_limit", SID_B)):
            got = self.helper("find", sid, 21, home=home)
            rows = [r for r in (got.get("candidates") or []) if r.get("id") == sid]
            self.assertEqual(len(rows), 1, (shape, got))
            self.assertTrue(rows[0].get("quota"),
                            "%s: the helper must see this stop too" % shape)
            self.assertIn("weekly limit", rows[0]["quota"], shape)

    def test_the_helper_does_not_let_a_non_answer_clear_a_quota_it_found(self):
        """And the clearing branch has the same two exceptions the engine's does: an error
        that is not a limit, and a `<synthetic>` "No response requested." line."""
        home = self.dir / "h2"
        d = home / ".claude" / "projects" / "-work"
        d.mkdir(parents=True)
        (d / (SID_C + ".jsonl")).write_text(jl(
            user("go", "/work", SID_C),
            assistant("You've hit your weekly limit · resets 10pm", "/work", SID_C,
                      error="usage_limit_reached", resets=time.time() + 3600,
                      shape="rate_limit"),
            assistant("No response requested.", "/work", SID_C, synthetic=True)))
        got = self.helper("find", SID_C, 21, home=home)
        rows = [r for r in (got.get("candidates") or []) if r.get("id") == SID_C]
        self.assertEqual(len(rows), 1, got)
        self.assertTrue(rows[0].get("quota"), got)

    def test_the_mirror_copies_code_and_leaves_the_ignored_and_the_big_files(self):
        repo = self.dir / "repo"
        repo.mkdir()
        g = ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t"]
        subprocess.run(g + ["init", "-q"], check=True)
        (repo / ".gitignore").write_text("*.rec\n")
        (repo / "code.py").write_text("print(1)\n")
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["commit", "-qm", "one"], check=True)
        (repo / "code.py").write_text("print(2)\n")              # an uncommitted edit
        (repo / "new.py").write_text("x = 1\n")                  # untracked, small
        (repo / "frames.rec").write_bytes(b"\0" * 5000)          # ignored
        (repo / "big.bin").write_bytes(b"\0" * 5000)             # untracked, too big
        plan = self.helper("mirror", str(repo), 1000)
        files = set(plan["files"])
        self.assertTrue({"code.py", "new.py", ".gitignore", ".git/HEAD"} <= files, files)
        self.assertNotIn("frames.rec", files)
        self.assertEqual([x[0] for x in plan["skipped"]], ["big.bin"])
        self.assertEqual(plan["dirty"], 3)                       # code.py, new.py, big.bin
        dest = self.dir / "mirror"
        os.environ["CSM_REMOTE_LOCAL"] = "1"
        self.addCleanup(os.environ.pop, "CSM_REMOTE_LOCAL", None)
        self.mod.tar_across("desktop", str(repo), plan["files"], dest)
        self.assertEqual((dest / "code.py").read_text(), "print(2)\n")
        self.assertFalse((dest / "frames.rec").exists())
        self.assertFalse(any(p.name.startswith("._") for p in dest.iterdir()))
        st = subprocess.run(["git", "-C", str(dest), "status", "--porcelain"],
                            stdout=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(st.returncode, 0)
        self.assertIn(" M code.py", st.stdout)

    def test_a_folder_that_is_not_a_git_tree_cannot_be_mirrored(self):
        plain = self.dir / "plain"
        plain.mkdir()
        self.assertEqual(self.helper("mirror", str(plain), 1000).get("git"), False)

    def test_a_mirror_with_an_ssh_remote_pushes_over_https_when_ssh_is_refused(self):
        repo = self.dir / "r"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin",
                        "git@github.com:someone/firmware.git"], check=True)
        self.mod._github_ssh_ok = lambda: True
        self.assertFalse(self.mod.github_https_fallback(str(repo)), "ssh works: untouched")
        self.mod._github_ssh_ok = lambda: False
        self.assertTrue(self.mod.github_https_fallback(str(repo)))
        got = subprocess.run(["git", "-C", str(repo), "config", "--local", "--get",
                              "url.https://github.com/.insteadOf"], stdout=subprocess.PIPE,
                             universal_newlines=True).stdout.strip()
        self.assertEqual(got, "git@github.com:")
        other = self.dir / "o"
        subprocess.run(["git", "init", "-q", str(other)], check=True)
        subprocess.run(["git", "-C", str(other), "remote", "add", "origin",
                        "https://github.com/x/y.git"], check=True)
        self.assertFalse(self.mod.github_https_fallback(str(other)),
                         "already https: untouched")

    def test_the_helper_is_sent_to_the_remote_python_through_the_ssh_knob(self):
        """What a REAL `--on` leg sends: the ssh invocation is the knob, so this records it
        instead of running ssh — and what it records is the whole remote shell word."""
        log = self.dir / "ssh.jsonl"
        rec = self.dir / "fake-ssh"
        rec.write_text("#!" + PY + "\nimport json, os, sys\n"
                       "open(os.environ['L'], 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
                       'sys.stdout.write(\'{"candidates": []}\\n\')\n')
        rec.chmod(0o755)
        self.mod.SSH_CMD = str(rec)
        self.mod.REMOTE_PYTHON = "/usr/bin/python3"
        os.environ["L"] = str(log)
        self.addCleanup(os.environ.pop, "L", None)
        self.assertEqual(self.mod.find_rows("desktop", "x", False), [])
        sent = json.loads(log.read_text().splitlines()[-1])
        self.assertEqual(sent[0], "desktop")
        self.assertIn("/usr/bin/python3 -I - find x", sent[-1])


class TranslateCwd(unittest.TestCase):
    """One project, a different absolute path on each machine: a different user name makes
    `~/code/p` a different path, and a sync client's own root differs per machine too."""

    def setUp(self):
        self.mod = load_tool()
        self.addCleanup(sys.modules.pop, "csm_mod", None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        # This machine: `~/shared` is a SYMLINK into the sync client's own tree, which is
        # exactly the case no named root can match.
        self.here_home = self.root / "one"
        (self.here_home / "Cloud" / "shared").mkdir(parents=True)
        os.symlink(str(self.here_home / "Cloud" / "shared"), str(self.here_home / "shared"))
        self.real_sync = os.path.realpath(str(self.here_home / "shared"))
        self.mj = self.root / "machines.json"
        self.mj.write_text(json.dumps({
            "laptop": {"home": str(self.here_home), "sync": self.real_sync},
            "desktop": {"home": "/home/two", "sync": "/home/two/Storage/shared"},
            "twin": {"home": str(self.here_home), "sync": self.real_sync},
            # not roots: a null, a nested object and a relative value are all ignored
            "lab": {"home": "/home/lab", "sync": None, "overlay": {"a": 1},
                    "base": "relative/path"},
        }))
        self.mod.MACHINES_FILE = self.mj
        self.mod.SYNC_DIRS = ("shared",)
        self.mod.HOME = self.here_home

    def t(self, origin, cwd, path=""):
        return self.mod.translate_cwd(origin, cwd, path, here_name="laptop",
                                      here_home=str(self.here_home))

    def test_the_other_machines_sync_root_is_this_machines(self):
        self.assertEqual(self.t("desktop", "/home/two/Storage/shared/proj"),
                         self.real_sync + "/proj")

    def test_an_ordinary_home_relative_folder_maps_home_to_home(self):
        self.assertEqual(self.t("desktop", "/home/two/code/app"),
                         str(self.here_home) + "/code/app")

    def test_the_symlink_spelling_of_a_synced_directory_maps_through_the_sync_rule(self):
        """🛑 The rule that named roots alone cannot do. The other machine's transcript
        records `<home>/shared/...`, its symlink spelling: no named root matches it, and
        `home` to `home` would answer with this machine's symlink instead of the folder the
        sync client really keeps."""
        self.assertEqual(self.t("desktop", "/home/two/shared/proj"),
                         self.real_sync + "/proj")

    def test_the_sync_rule_is_tried_before_home_to_home(self):
        # with no sync directory configured, the same path falls through to home -> home
        self.mod.SYNC_DIRS = ()
        self.assertEqual(self.t("desktop", "/home/two/shared/proj"),
                         str(self.here_home) + "/shared/proj")

    def test_two_machines_that_spell_a_folder_the_same_way_need_no_translation(self):
        self.assertEqual(self.t("twin", str(self.here_home) + "/code/app"), "")

    def test_a_folder_outside_every_root_is_left_alone(self):
        self.assertEqual(self.t("desktop", "/opt/data/run1"), "")

    def test_a_label_only_one_machine_has_is_no_rule(self):
        # `lab` has no usable `sync`, so only its home can map
        self.assertEqual(self.t("lab", "/home/lab/sync/x"), str(self.here_home) + "/sync/x")

    def test_a_machine_the_file_does_not_name_takes_its_home_from_the_transcript_path(self):
        self.assertEqual(
            self.t("newbox", "/home/other/code/p",
                   "/home/other/.claude-work/projects/-home-other-code-p/a.jsonl"),
            str(self.here_home) + "/code/p")

    def test_with_no_machines_file_at_all_only_home_to_home_applies(self):
        self.mod.MACHINES_FILE = self.root / "nope.json"
        self.assertEqual(self.t("desktop", "/home/two/code/app", ""), "")
        self.assertEqual(
            self.t("desktop", "/home/two/code/app", "/home/two/.claude/projects/x/a.jsonl"),
            str(self.here_home) + "/code/app")

    def test_an_unparseable_machines_file_is_not_a_crash(self):
        self.mj.write_text("{ not json")
        self.assertEqual(self.t("desktop", "/home/two/code/app"), "")

    def test_an_empty_cwd_translates_to_nothing(self):
        self.assertEqual(self.t("desktop", ""), "")

    def test_in_sync_dir_knows_the_synced_tree_through_the_symlink(self):
        self.assertTrue(self.mod.in_sync_dir(str(self.here_home / "shared" / "p")))
        self.assertTrue(self.mod.in_sync_dir(self.real_sync))
        self.assertFalse(self.mod.in_sync_dir(str(self.here_home / "code")))
        self.mod.SYNC_DIRS = ()
        self.assertFalse(self.mod.in_sync_dir(str(self.here_home / "shared" / "p")),
                         "with nothing configured, no folder is the same folder anywhere")

    def test_machine_roots_reads_only_absolute_string_values(self):
        got = self.mod.machine_roots("lab")
        self.assertEqual(got, {"home": "/home/lab"})

    def test_a_machine_with_no_entry_and_no_guess_has_no_roots(self):
        self.assertEqual(self.mod.machine_roots("newbox"), {})


class OriginAccount(unittest.TestCase):
    """The synthesised source of a cross-machine move."""

    def setUp(self):
        self.mod = load_tool()
        self.addCleanup(sys.modules.pop, "csm_mod", None)

    def test_the_name_carries_the_machine_so_it_can_never_equal_a_target(self):
        a = self.mod.origin_account("desktop", {"home": "/home/two/.claude-work",
                                                "email": "you@work.example",
                                                "org": "org-1"})
        self.assertEqual(a.name, "desktop:.claude-work")
        self.assertEqual(a.email, "you@work.example")
        self.assertEqual(a.org, "org-1")
        self.assertEqual(a.machines, ("desktop",))
        self.assertIn("@desktop", a.label)

    def test_a_known_login_lends_its_label_to_the_remote_row(self):
        accts = [self.mod.Account("work", Path("/x"), handle="wk",
                                  _oauth={"emailAddress": "you@work.example"})]
        a = self.mod.origin_account("desktop", {"home": "/home/two/.claude-work",
                                                "email": "you@work.example"}, accts)
        self.assertEqual(a.label, "wk@desktop")

    def test_a_home_with_no_login_recorded_there_is_not_invented(self):
        a = self.mod.origin_account("desktop", {"home": "/home/two/.claude"})
        self.assertEqual(a.email, "")
        self.assertEqual(a.label, ".claude@desktop")


class RunWindow(Base):
    # ⚠️ `kind` and `version` are what `make_plan` stamps on every plan it writes, so a
    # fixture without them is a file the tool would never produce — and since `__run` now
    # identifies a plan before deleting it, it is also not one it would accept.
    PLAN = {"kind": "csm-run", "version": 1, "config_dir": None, "local_id": SID_A,
            "rc_name": None, "perm": "plan", "model": "", "path": "", "title": "t",
            "from": "a", "to": "b", "window": "moved-x", "session": "csm-b"}

    def test_plan_is_read_once_and_the_window_reports_the_exit(self):
        plan = self.w.root / "plan.json"
        plan.write_text(json.dumps(dict(
            self.PLAN, cwd=str(self.w.work), claude=str(self.w.bin / "claude"))))
        r = subprocess.run([PY, str(TOOL), "__run", str(plan)], capture_output=True, text=True,
                           env=self.w.env(FAKE_CLAUDE_SLEEP="0", FAKE_CLAUDE_RC="3",
                                          CLAUDE_CONFIG_DIR="/should/be/unset"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("=== claude exited rc=3", r.stdout)
        self.assertFalse(plan.exists())
        call = self.w.claude_calls()[0]
        self.assertNotIn("CLAUDE_CONFIG_DIR", call["env"])
        self.assertEqual(call["argv"], ["--permission-mode", "plan", "--resume", SID_A])

    def test_the_plan_format_version_stays_1(self):
        """🛑 `make_plan`'s own 🛑 — "`version` STAYS 1, so an older csm can read a newer
        plan" — with nothing that could notice a reflexive bump. `run_window` checks only
        `kind` and `local_id`, and `RunWindow.PLAN` is an INPUT fixture rather than an
        expectation, so the number was asserted nowhere at all. The hand-off is written by
        one csm and read by another, which is the whole reason the field exists.
        """
        mod = load_tool()
        self.addCleanup(sys.modules.pop, "csm_mod", None)
        acct = mod.Account(name="work", home=self.w.work)
        s = mod.Session(account=acct, local_id=SID_A, transcript=self.w.work / "t.jsonl",
                        mtime=0.0, cwd=str(self.w.work))
        plan = mod.make_plan(s, acct, "label", "default")
        self.assertEqual(plan["version"], 1)
        self.assertEqual(plan["kind"], "csm-run")
        self.assertEqual(self.PLAN["version"], plan["version"],
                         "the fixture and what the tool writes are one format")

    def test_a_file_that_is_not_a_plan_is_neither_deleted_nor_run(self):
        """🛑 `__run`'s next two steps are "unlink this path" and "exec what this JSON
        names". `make_plan` has always stamped `kind`, and nothing read it — so pointed by
        hand or by a typo at another JSON file, `__run` deleted it and then tried to start
        whatever its `claude` key said, in whatever `cwd` it named."""
        other = self.w.root / "not-a-plan.json"
        other.write_text(json.dumps(
            {"claude": str(self.w.bin / "claude"), "cwd": str(self.w.work),
             "local_id": SID_A, "perm": "plan"}))
        r = subprocess.run([PY, str(TOOL), "__run", str(other)], capture_output=True,
                           text=True, env=self.w.env(FAKE_CLAUDE_SLEEP="0"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("is not a csm run plan", r.stderr)
        self.assertTrue(other.exists(), "it deleted a file that was not its hand-off")
        self.assertEqual(self.w.claude_calls(wait=0.2), [], "nothing was started")


# ------------------------------------------------------------------ in-process fixtures

class InProc(unittest.TestCase):
    """The tool imported as a module, for the pure functions: a few milliseconds each.

    Everything that can be a pure-function test is one — the subprocess tests above are
    the slow part of this suite, and there are a lot of rules to pin.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.mod = load_tool()
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(sys.modules.pop, "csm_mod", None)
        # 🛑 EVERY module-level path, not just the obvious three. These are read at IMPORT,
        # from the real environment, so one left alone is a test reading — or writing —
        # the machine's own state: the pane captures, the accounts table, the quota meter,
        # the owner directory, the machine's shared settings home. A test that reads a
        # real file passes here and means nothing anywhere else, and the one that WRITES
        # one is worse. A test that wants any of these points it at its own fixture.
        self.mod.HOME = self.root / "home"
        self.mod.LOG = self.root / "log"
        self.mod.STATE_DIR = self.root / "state"
        self.mod.PICKS = self.root / "picks.json"
        self.mod.CAPTURES = self.root / "captures"
        self.mod.IMPORTS = self.root / "imports"
        self.mod.SHARED_HOME = self.root / "home" / ".claude"
        self.mod.ACCOUNTS_FILE = self.root / "accounts"
        self.mod.MACHINES_FILE = self.root / "machines.json"
        self.mod.METERS_FILE = self.root / "meters.json"
        self.mod.BOTS_DIR = self.root / "owners"
        self.mod.LOGIN_PROBE = "true"
        self.procs = []
        self.addCleanup(self.kill_all)

    def kill_all(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()

    def account(self, name, email="me@work.example", org="org-1", settings=None, **state):
        home = self.root / "home" / (".claude-" + name)
        (home / "projects").mkdir(parents=True, exist_ok=True)
        d = dict(state)
        if email:
            d["oauthAccount"] = {"emailAddress": email, "organizationUuid": org}
        (home / ".claude.json").write_text(json.dumps(d))
        if settings is not None:
            (home / "settings.json").write_text(json.dumps(settings))
        return self.mod.Account(name, home)

    def session(self, acct, sid=SID_A, perm="", lines=None, folder="-work", cwd=None):
        cwd = cwd or str(self.root / "work")
        os.makedirs(cwd, exist_ok=True)
        d = acct.home / "projects" / folder
        d.mkdir(parents=True, exist_ok=True)
        t = d / (sid + ".jsonl")
        t.write_text(jl(*(lines if lines is not None else [user("go", cwd, sid)])))
        return self.mod.Session(account=acct, local_id=sid, transcript=t,
                                mtime=t.stat().st_mtime, cwd=cwd, perm=perm, title="t")

    def claude_proc(self):
        """A real process whose argv[0] basename is `claude`."""
        pb = self.root / "procbin"
        if not pb.exists():
            pb.mkdir()
            shutil.copy("/bin/sh", str(pb / "claude"))   # see World's procbin
        p = subprocess.Popen([str(pb / "claude"), "-c", "sleep 120; exit 0"])
        self.procs.append(p)
        return p


# ----------------------------------------------------------------- answering the dialogs
# The screens below are the shapes the CLI really draws (measured on 2.1.300): the
# cancelling option FIRST, focused, and no option numbers anywhere.

TRUST = ("Accessing workspace: /tmp/x\n\n Quick safety check\n\n Is this a project you "
         "created or one you trust?\n\n ❯ No, exit\n   Yes, I trust this folder\n")
TRUST_ON_YES = ("Is this a project you created or one you trust?\n\n   No, exit\n"
                " ❯ Yes, I trust this folder\n")
BYPASS = ("WARNING: Claude Code running in Bypass Permissions mode\n\n ❯ No, exit\n"
          "   Yes, I accept\n")
BYPASS_ON_YES = ("WARNING: Claude Code running in Bypass Permissions mode\n\n   No, exit\n"
                 " ❯ Yes, I accept\n")
REMOTE = ("Enable Remote Control?\n Opens a secure connection to claude.ai.\n\n"
          " ❯ Never mind\n   Enable Remote Control\n")
# A home governed by managed settings asks the trust question with other words.
TRUST_SETTINGS = ("Do you trust these settings?\n\n ❯ No, exit Claude Code\n"
                  "   Yes, I trust these settings\n")
# ⚠️ NOT cancel-first: the accepting answer is drawn first AND focused, and accepting it
# rewrites the home's default permission mode for every later session.
AUTO_MODE = ("Make auto mode your default permission mode?\n\n"
             " ❯ Yes, set auto mode as my default permission mode\n"
             "   No, keep bypass permissions\n")
AUTO_MODE_ON_NO = ("Make auto mode your default permission mode?\n\n"
                   "   Yes, set auto mode as my default permission mode\n"
                   " ❯ No, keep bypass permissions\n")
#: 🛑 THE LABELS ARE THE CLI'S OWN, read out of the 2.1.312 bundle on Wed 28 Oct 2026:
#: `confirmLabel: "Yes, allow external imports", cancelLabel: "No, disable external
#: imports", hideIndexes: true, cancelFirst` — so the cancelling answer is drawn first and
#: holds the focus, as the trust dialog's does.
IMPORTS = ("Allow external CLAUDE.md file imports?\n\n This project's CLAUDE.md or "
           ".claude/rules imports files outside the current working directory. Never allow "
           "this for third-party repositories.\n\n External imports:\n   ../shared.md\n\n"
           " ❯ No, disable external imports\n   Yes, allow external imports\n")
IMPORTS_ON_YES = ("Allow external CLAUDE.md file imports?\n\n"
                  "   No, disable external imports\n ❯ Yes, allow external imports\n")


class PromptAnswering(InProc):
    def answer(self, pane, mode="default", tries=None):
        return self.mod.prompt_answer(pane, mode, tries if tries is not None else {})

    def test_the_measured_trust_dialog_gets_down_then_enter(self):
        self.assertEqual(self.answer(TRUST), ("trust", "Down"))
        self.assertEqual(self.answer(TRUST_ON_YES), ("trust", "Enter"))

    def test_enter_is_never_sent_while_the_marker_sits_on_no(self):
        # the invariant, for every marker position: Enter only on the wanted line. Down
        # WRAPS in a two-option list, so walking the marker always terminates.
        for pane in (TRUST, BYPASS, REMOTE):
            name, key = self.answer(pane, mode="bypassPermissions")
            self.assertEqual(key, "Down", pane)

    def test_a_line_holding_both_options_is_answered_with_nothing(self):
        # `capture-pane -J` joins wrapped lines, so one row can carry both labels. An
        # answer here would be a coin toss, and one of the two faces kills the window.
        joined = ("Is this a project you created or one you trust?\n"
                  " ❯ No, exit   Yes, I trust this folder\n")
        self.assertEqual(self.answer(joined), ("trust", ""))

    def test_the_bypass_warning_is_only_answered_for_a_bypass_move(self):
        self.assertEqual(self.answer(BYPASS, mode="bypassPermissions"), ("bypass", "Down"))
        self.assertEqual(self.answer(BYPASS_ON_YES, mode="bypassPermissions"),
                         ("bypass", "Enter"))
        self.assertEqual(self.answer(BYPASS_ON_YES, mode="acceptEdits"), ("bypass", ""))

    def test_a_scrollback_prompt_cannot_answer_a_live_dialog(self):
        # an old "Press Enter to continue" above a live bypass warning must not be matched
        # after it: the first matching prompt RETURNS, it never falls through
        pane = "Press Enter to continue\n\n" + BYPASS_ON_YES
        self.assertEqual(self.answer(pane, mode="acceptEdits"), ("bypass", ""))

    def test_the_remote_control_question_is_not_mistaken_for_its_option(self):
        self.assertEqual(self.answer(REMOTE), ("remote-control", "Down"))
        moved = ("Enable Remote Control?\n\n   Never mind\n ❯ Enable Remote Control\n")
        self.assertEqual(self.answer(moved), ("remote-control", "Enter"))

    def test_the_screens_that_are_not_choices_get_one_enter(self):
        self.assertEqual(self.answer("Choose the text style that looks best"),
                         ("theme", "Enter"))
        self.assertEqual(self.answer("Press Enter to continue"), ("continue", "Enter"))

    def test_a_marker_in_the_scrollback_above_the_dialog_is_ignored(self):
        # ❯ is also the ordinary input line's glyph
        pane = "❯ some earlier prompt I typed\n\n" + TRUST
        self.assertEqual(self.answer(pane), ("trust", "Down"))
        pane = "❯ some earlier prompt I typed\n\n" + TRUST_ON_YES
        self.assertEqual(self.answer(pane), ("trust", "Enter"))

    def test_a_select_with_no_visible_marker_is_left_alone(self):
        pane = "Is this a project you created?\n\n   No, exit\n   Yes, I trust this folder\n"
        self.assertEqual(self.answer(pane), ("trust", ""))

    def test_the_wanted_option_not_on_screen_yet_is_no_answer(self):
        pane = "Is this a project you created or one you trust?\n\n ❯ No, exit\n"
        self.assertEqual(self.answer(pane), ("trust", ""))

    def test_one_prompt_has_a_bounded_budget_of_keys(self):
        tries = {}
        for _ in range(self.mod.MAX_PROMPT_KEYS):
            name, key = self.answer(TRUST, tries=tries)
            self.assertEqual(key, "Down")
            tries[name] = tries.get(name, 0) + 1
        self.assertEqual(self.answer(TRUST, tries=tries), ("trust", ""))

    def test_ordinary_output_is_not_a_prompt(self):
        self.assertEqual(self.answer("> rebuilding the index...\n✻ Thinking\n"), ("", ""))

    def test_a_dialog_whose_body_scrolled_off_is_still_answered(self):
        # 🛑 a short window, or extra output above it, pushes the question off the top.
        # The first regex hit is then the CONFIRM label, and the focused cancel sits on
        # the line ABOVE it — so anchoring the search at the match alone finds no marker
        # and the answerer sits there for the whole connect wait.
        pane = " ❯ No, exit\n   Yes, I trust this folder\n"
        self.assertEqual(self.answer(pane), ("trust", "Down"))
        pane = "   No, exit\n ❯ Yes, I trust this folder\n"
        self.assertEqual(self.answer(pane), ("trust", "Enter"))

    def test_a_marker_above_the_whole_dialog_is_still_ignored(self):
        # the anchor moves up to the dialog's own first line, never above it
        pane = "❯ an earlier prompt I typed\n\n   No, exit\n   Yes, I trust this folder\n"
        self.assertEqual(self.answer(pane), ("trust", ""))

    def test_the_managed_settings_trust_dialog_is_recognised(self):
        self.assertEqual(self.answer(TRUST_SETTINGS), ("trust-settings", "Down"))
        moved = ("Do you trust these settings?\n\n   No, exit Claude Code\n"
                 " ❯ Yes, I trust these settings\n")
        self.assertEqual(self.answer(moved), ("trust-settings", "Enter"))

    def test_the_auto_mode_offer_is_declined_not_accepted(self):
        # 🛑 this one is NOT cancel-first, so a canned "press Enter" would accept it and
        # weaken the home's default mode for good. The marker walk declines it instead.
        self.assertEqual(self.answer(AUTO_MODE, mode="bypassPermissions"),
                         ("auto-mode-default", "Down"))
        self.assertEqual(self.answer(AUTO_MODE_ON_NO, mode="bypassPermissions"),
                         ("auto-mode-default", "Enter"))

    def test_the_auto_mode_offer_never_gets_enter_on_the_yes_line(self):
        for pane in (AUTO_MODE, TRUST_SETTINGS):
            name, key = self.answer(pane, mode="bypassPermissions")
            self.assertEqual(key, "Down", pane)

    def test_the_external_imports_dialog_is_declined_which_is_its_focused_default(self):
        """🛑 A CHOICE, NOT A SHRUG. Answering this dialog writes
        `hasClaudeMdExternalIncludesApproved` into that home's state file for the project,
        for good — and approving a CLAUDE.md to import files from outside its own working
        directory is consent only he can give ("Never allow this for third-party
        repositories", the dialog's own words). It is answered at all because it BLOCKS an
        interactive start, which would otherwise make a revive that did nothing."""
        self.assertEqual(self.answer(IMPORTS), ("external-imports", "Enter"))
        self.assertEqual(self.answer(IMPORTS_ON_YES), ("external-imports", "Down"))

    def test_the_external_imports_dialog_is_read_off_the_marker_like_the_rest(self):
        """⚠️ `capture-pane -J` can join both labels onto one row, and the one safe way to
        be wrong is to send nothing at all."""
        joined = ("Allow external CLAUDE.md file imports?\n\n"
                  " ❯ No, disable external imports   Yes, allow external imports\n")
        self.assertEqual(self.answer(joined), ("external-imports", ""))


# ------------------------------------------------------------------------ permission mode

class PermissionMode(InProc):
    def test_the_order_is_a_strength_order(self):
        self.assertEqual(self.mod.MODE_ORDER[0], "plan")
        self.assertEqual(self.mod.MODE_ORDER[-1], "bypassPermissions")
        self.assertEqual(self.mod.canon_mode("manual"), "default")
        self.assertEqual(self.mod.mode_rank("manual"), self.mod.mode_rank("default"))
        self.assertEqual(self.mod.mode_rank("somethingNew"), -1)
        self.assertEqual(self.mod.RAISE_FROM, ("", "default", "auto"))

    def resolve(self, recorded, default_mode=None, asked=None, local=None):
        settings = None if default_mode is None else {"permissions": {"defaultMode": default_mode}}
        tgt = self.account("work", settings=settings)
        if local:
            (tgt.home / "settings.local.json").write_text(
                json.dumps({"permissions": {"defaultMode": local}}))
        src = self.account("personal", email="me@home.example", org="org-2")
        return self.mod.resolve_mode(self.session(src, perm=recorded), tgt, asked)

    def test_an_accidental_mode_is_raised_to_the_targets_default(self):
        mode, why = self.resolve("auto", "bypassPermissions")
        self.assertEqual(mode, "bypassPermissions")
        self.assertIn("settings.json", why)
        self.assertIn("weaker", why)
        self.assertIn("--permission-mode auto", why)      # how to keep the recorded one

    def test_an_empty_recorded_mode_is_raised_too(self):
        self.assertEqual(self.resolve("", "acceptEdits")[0], "acceptEdits")

    def test_plan_and_acceptedits_are_deliberate_and_never_raised(self):
        for deliberate in ("plan", "acceptEdits"):
            mode, why = self.resolve(deliberate, "bypassPermissions")
            self.assertEqual(mode, deliberate)
            self.assertIn("--permission-mode bypassPermissions", why)

    def test_a_stronger_recorded_mode_is_never_weakened(self):
        self.assertEqual(self.resolve("bypassPermissions", "plan")[0], "bypassPermissions")

    def test_an_unknown_recorded_mode_is_passed_through_untouched(self):
        self.assertEqual(self.resolve("someFutureMode", "bypassPermissions")[0],
                         "someFutureMode")

    def test_the_flag_wins_and_manual_is_an_alias(self):
        self.assertEqual(self.resolve("plan", "bypassPermissions", asked="dontAsk"),
                         ("dontAsk", "from --permission-mode"))
        self.assertEqual(self.resolve("plan", None, asked="manual")[0], "default")

    def test_an_unknown_mode_is_refused_with_the_list(self):
        with self.assertRaises(self.mod.Refusal) as e:
            self.resolve("plan", None, asked="nonsense")
        self.assertIn("bypassPermissions", str(e.exception))
        self.assertIn("manual", str(e.exception))

    def test_with_nothing_anywhere_it_is_default(self):
        mode, why = self.resolve("", None)
        self.assertEqual(mode, "default")
        self.assertIn("no settings", why)

    def test_settings_local_wins_and_a_symlinked_settings_file_is_followed(self):
        shared = self.root / "shared-settings.json"
        shared.write_text(json.dumps({"permissions": {"defaultMode": "dontAsk"}}))
        tgt = self.account("work", settings={})
        (tgt.home / "settings.json").unlink()
        os.symlink(str(shared), str(tgt.home / "settings.json"))
        self.assertEqual(self.mod.settings_mode(tgt)[0], "dontAsk")
        self.assertEqual(self.resolve("auto", "plan", local="bypassPermissions")[0],
                         "bypassPermissions")

    def test_the_footer_and_the_appended_line_are_read(self):
        self.assertEqual(self.mod.pane_mode("...\n⏵⏵ bypass permissions on"),
                         "bypassPermissions")
        self.assertEqual(self.mod.pane_mode("⏵⏵ plan mode on\nlater: ⏵⏵ auto mode on"),
                         "auto")
        self.assertEqual(self.mod.pane_mode("nothing here"), "")
        t = self.root / "copy.jsonl"
        t.write_text(jl({"type": "user", "permissionMode": "plan"}))
        after = t.stat().st_size
        self.assertEqual(self.mod.appended_mode(t, after), "")      # nothing appended yet
        with t.open("a") as f:
            f.write(json.dumps({"type": "permission-mode",
                                "permissionMode": "acceptEdits"}) + "\n")
        self.assertEqual(self.mod.appended_mode(t, after), "acceptEdits")
        # the transcript outranks the footer, which is only a render
        self.assertEqual(self.mod.came_up_as("⏵⏵ auto mode on", t, after),
                         ("acceptEdits", "from the transcript"))
        self.assertEqual(self.mod.came_up_as("⏵⏵ auto mode on", t, t.stat().st_size),
                         ("auto", "from the window footer"))
        self.assertEqual(self.mod.came_up_as("", t, t.stat().st_size), ("", ""))

    def test_the_footer_for_default_is_manual_mode_on(self):
        # 🛑 measured on 2.1.301: `default` DOES draw a footer, under the name the UI
        # uses. Without this literal the one downgrade the cost block exists to catch —
        # bypass was asked for and the session came up in default — is invisible.
        self.assertEqual(self.mod.pane_mode("...\n⏸ manual mode on"), "default")
        t = self.root / "copy.jsonl"
        t.write_text(jl({"type": "user"}))
        came, how = self.mod.came_up_as("⏸ manual mode on", t, t.stat().st_size)
        self.assertEqual((came, how), ("default", "from the window footer"))
        self.assertNotEqual(came, "bypassPermissions")


# ------------------------------------------------------------------------- the pid guard

class PidGuard(InProc):
    def test_what_counts_as_a_claude_executable(self):
        ok = self.mod.is_claude_exe
        self.assertTrue(ok("/usr/local/bin/claude --resume x"))
        self.assertTrue(ok("/home/you/.local/share/claude/versions/2.1.300 --remote-control"))
        self.assertFalse(ok("vim /home/you/.claude/settings.json"))
        self.assertFalse(ok("tail -f claude.log"))
        self.assertFalse(ok("/tmp/claude-scratch/python3 -c pass"))
        self.assertFalse(ok(""))

    def test_a_matching_procstart_lets_the_stop_through(self):
        p = self.claude_proc()
        s = self.session(self.account("work"))
        s.pid, s.proc_start = p.pid, ps_start(p.pid)
        ok, why = self.mod.still_the_same_process(s)
        self.assertTrue(ok, why)

    def test_a_disagreeing_procstart_means_the_pid_was_reused(self):
        p = self.claude_proc()
        s = self.session(self.account("work"))
        s.pid, s.proc_start = p.pid, "Mon Jan  1 00:00:00 2001"
        ok, why = self.mod.still_the_same_process(s)
        self.assertFalse(ok)
        self.assertIn("reused", why)

    def test_a_blinded_ps_is_not_agreement(self):
        p = self.claude_proc()
        s = self.session(self.account("work"))
        s.pid, s.proc_start = p.pid, ps_start(p.pid)
        self.mod._ps = lambda *a, **k: None         # ps could not be asked at all
        ok, why = self.mod.still_the_same_process(s)
        self.assertFalse(ok)
        self.assertIn("nothing was proved", why)

    def test_a_ps_that_answers_nothing_is_not_agreement_either(self):
        p = self.claude_proc()
        s = self.session(self.account("work"))
        s.pid, s.proc_start = p.pid, ps_start(p.pid)
        self.mod._ps = lambda *a, **k: ""
        self.assertFalse(self.mod.still_the_same_process(s)[0])

    def test_without_a_procstart_there_is_no_fallback_at_all(self):
        # 🛑 argv[0] is not proof of WHICH session. On a machine running several copies
        # of the CLI, pid reuse by another one passes a name check — so a row with no
        # recorded start time is a refusal, even when the pid IS the Claude Code CLI.
        p = self.claude_proc()
        s = self.session(self.account("work"))
        s.pid = p.pid
        ok, why = self.mod.still_the_same_process(s)
        self.assertFalse(ok)
        self.assertIn("recorded no start time", why)
        self.assertIn("nothing was proved", why)

    def test_the_executable_is_still_checked_on_top_of_the_start_time(self):
        other = subprocess.Popen(["/bin/sleep", "120"])
        self.procs.append(other)
        s = self.session(self.account("other", email="x@y.example"), sid=SID_B)
        s.pid, s.proc_start = other.pid, ps_start(other.pid)
        ok, why = self.mod.still_the_same_process(s)
        self.assertFalse(ok)
        self.assertIn("not running the Claude Code CLI", why)

    def test_no_procstart_and_a_blinded_ps_is_a_refusal_too(self):
        p = self.claude_proc()
        s = self.session(self.account("work"))
        s.pid = p.pid
        self.mod._ps = lambda *a, **k: None
        self.assertFalse(self.mod.still_the_same_process(s)[0])

    @unittest.skipUnless(a_foreign_locale(), "no non-C locale with a different ps format")
    def test_a_foreign_shell_locale_is_not_a_pid_reuse(self):
        # 🛑 the registry value is written under LC_ALL=C; a prover that inherits the
        # user's locale compares 'jeu. 15 oct. …' against 'Thu Oct 15 …' and reports a
        # reuse that did not happen — leaving two copies of the session answering.
        loc = a_foreign_locale()
        p = self.claude_proc()
        s = self.session(self.account("work"))
        s.pid, s.proc_start = p.pid, ps_start(p.pid)
        old = os.environ.get("LC_ALL")
        os.environ["LC_ALL"] = loc
        try:
            ok, why = self.mod.still_the_same_process(s)
        finally:
            if old is None:
                os.environ.pop("LC_ALL", None)
            else:
                os.environ["LC_ALL"] = old
        self.assertTrue(ok, why)

    def test_a_registry_file_that_outlived_its_process_says_so(self):
        p = self.claude_proc()
        pid = p.pid
        p.kill()
        p.wait()
        s = self.session(self.account("work"))
        s.pid = pid
        ok, why = self.mod.still_the_same_process(s)
        self.assertFalse(ok)
        self.assertIn("already exited", why)


# -------------------------------------------------------------------- the first-run gates

class FirstRunWrites(InProc):
    def state(self, acct):
        return json.loads(acct.state_file.read_text())

    def test_a_warm_home_with_the_cwd_already_trusted_is_not_touched(self):
        cwd = str(self.root / "work")
        tgt = self.account("work", hasCompletedOnboarding=True,
                           projects={cwd: {"hasTrustDialogAccepted": True}})
        before = tgt.state_file.read_bytes(), tgt.state_file.stat().st_mtime
        self.assertEqual(self.mod.clear_first_run(tgt, cwd, apply=True), [])
        self.assertEqual(tgt.state_file.read_bytes(), before[0])
        self.assertEqual(tgt.state_file.stat().st_mtime, before[1])
        self.assertEqual(list(tgt.home.glob(".claude.json.csm-bak-*")), [])

    def test_a_warm_home_with_a_new_cwd_gets_the_trust_flag_and_no_theme(self):
        cwd = str(self.root / "work")
        tgt = self.account("work", hasCompletedOnboarding=True)
        todo = self.mod.clear_first_run(tgt, cwd, apply=True)
        self.assertEqual(todo, ["trust " + cwd])
        d = self.state(tgt)
        self.assertTrue(d["projects"][cwd]["hasTrustDialogAccepted"])
        self.assertNotIn("theme", d)        # a preference the CLI never set there
        self.assertEqual(len(list(tgt.home.glob(".claude.json.csm-bak-*"))), 1)

    def test_a_cold_home_gets_all_three_and_an_epoch_stamped_backup(self):
        cwd = str(self.root / "work")
        tgt = self.account("work")
        todo = self.mod.clear_first_run(tgt, cwd, apply=True)
        self.assertEqual(len(todo), 3)
        d = self.state(tgt)
        self.assertTrue(d["hasCompletedOnboarding"])
        self.assertEqual(d["theme"], "dark")
        self.assertEqual(len(list(tgt.home.glob(".claude.json.csm-bak-*"))), 1)

    def test_an_existing_theme_is_never_overwritten(self):
        tgt = self.account("work", theme="light")
        self.mod.clear_first_run(tgt, str(self.root / "work"), apply=True)
        self.assertEqual(self.state(tgt)["theme"], "light")

    def test_two_moves_keep_two_backups(self):
        tgt = self.account("work")
        self.mod.clear_first_run(tgt, str(self.root / "a"), apply=True)
        time.sleep(1.05)                 # the stamp is whole seconds
        self.mod.clear_first_run(tgt, str(self.root / "b"), apply=True)
        self.assertEqual(len(list(tgt.home.glob(".claude.json.csm-bak-*"))), 2)

    def test_the_clis_own_lock_is_taken_and_released(self):
        cwd = str(self.root / "work")
        tgt = self.account("work")
        lock = tgt.state_file.with_name(tgt.state_file.name + ".lock")
        seen = []
        real = self.mod.read_json
        self.mod.read_json = lambda p: seen.append(lock.is_dir()) or real(p)
        self.addCleanup(setattr, self.mod, "read_json", real)
        self.mod.clear_first_run(tgt, cwd, apply=True)
        # the first read builds the plan, the second happens INSIDE the lock
        self.assertEqual(seen[-1], True, seen)
        self.assertFalse(lock.exists(), "the lock is released in a finally")

    def test_a_write_the_cli_made_in_between_is_not_lost(self):
        # 🛑 a read-modify-replace that writes back the object it read at plan time
        # discards whatever the CLI wrote since. Only the two keys csm owns are merged.
        cwd = str(self.root / "work")
        tgt = self.account("work", hasCompletedOnboarding=True)
        real = self.mod.read_json
        state = {"n": 0}

        def read(p):
            d = real(p)
            state["n"] += 1
            if state["n"] == 1 and isinstance(d, dict):
                d2 = dict(d)
                d2["lastSessionId"] = "written-by-the-cli"
                p.write_text(json.dumps(d2))        # the CLI writes between the two reads
            return d
        self.mod.read_json = read
        self.addCleanup(setattr, self.mod, "read_json", real)
        self.mod.clear_first_run(tgt, cwd, apply=True)
        d = self.state(tgt)
        self.assertEqual(d["lastSessionId"], "written-by-the-cli")
        self.assertTrue(d["projects"][cwd]["hasTrustDialogAccepted"])

    def test_a_lock_that_cannot_be_taken_warns_and_moves_on(self):
        # ⚠️ never a refusal: a 05:30 unattended move must not die on another session's
        # lock. It says so on stderr and writes anyway.
        import contextlib
        import io
        cwd = str(self.root / "work")
        tgt = self.account("work")
        lock = tgt.state_file.with_name(tgt.state_file.name + ".lock")
        lock.mkdir()
        self.addCleanup(lambda: lock.is_dir() and os.rmdir(str(lock)))
        self.mod.STATE_LOCK_WAIT_S = 0.05
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            todo = self.mod.clear_first_run(tgt, cwd, apply=True)
        self.assertTrue(todo)
        self.assertIn("could not take", err.getvalue())
        self.assertTrue(self.state(tgt)["projects"][cwd]["hasTrustDialogAccepted"])
        self.assertTrue(lock.is_dir(), "someone else's lock is never removed")

    def test_an_abandoned_lock_is_broken_after_its_stale_age(self):
        cwd = str(self.root / "work")
        tgt = self.account("work")
        lock = tgt.state_file.with_name(tgt.state_file.name + ".lock")
        lock.mkdir()
        old = time.time() - (self.mod.STATE_LOCK_STALE_S + 60)
        os.utime(str(lock), (old, old))
        self.mod.clear_first_run(tgt, cwd, apply=True)
        self.assertFalse(lock.exists())
        self.assertTrue(self.state(tgt)["projects"][cwd]["hasTrustDialogAccepted"])


# ------------------------------------------------------------------- the memory store

class MemoryStore(InProc):
    def test_the_env_key_is_read_from_the_homes_settings(self):
        store = self.root / "store"
        store.mkdir()
        acct = self.account("work", settings={
            "env": {self.mod.MEMORY_DIR_ENV: str(store)}})
        self.assertEqual(self.mod.memory_store(acct),
                         (str(store), "settings env.%s" % self.mod.MEMORY_DIR_ENV, True))
        self.assertEqual(self.mod.MEMORY_DIR_ENV, "CLAUDE_CODE_REMOTE_MEMORY_DIR")

    def test_a_relative_or_tilde_value_is_no_store(self):
        # 🛑 the CLI uses the value LITERALLY: `~` and `$HOME` are never expanded for it
        for bad in ("~/store", "store", "$HOME/store"):
            acct = self.account("w" + str(abs(hash(bad)) % 99),
                                settings={"env": {self.mod.MEMORY_DIR_ENV: bad}})
            self.assertEqual(self.mod.memory_store(acct), ("", "", True), bad)

    def test_a_store_that_does_not_exist_yet_is_still_the_store(self):
        # 🛑 a configured store the CLI will create on its first note is a store: reading
        # it as "no store" describes a directory the CLI never opens, and (before the
        # memory/ copy was removed) was the state in which notes got forked.
        nope = self.root / "nope"
        acct = self.account("work", settings={"env": {self.mod.MEMORY_DIR_ENV: str(nope)}})
        self.assertEqual(self.mod.memory_store(acct),
                         (str(nope), "settings env.%s" % self.mod.MEMORY_DIR_ENV, True))

    def test_a_broken_settings_file_is_no_store_and_no_crash(self):
        acct = self.account("work")
        (acct.home / "settings.json").write_text("{not json")
        self.assertEqual(self.mod.memory_store(acct), ("", "", True))

    def test_the_documented_setting_is_read_too(self):
        store = self.root / "auto"
        store.mkdir()
        acct = self.account("work", settings={"autoMemoryDirectory": str(store)})
        base, how, keyed = self.mod.memory_store(acct)
        self.assertEqual(base, str(store))
        self.assertIn("autoMemoryDirectory", how)
        self.assertFalse(keyed)                   # used verbatim: nothing is appended
        self.assertEqual(self.mod.memory_dir(acct, "-work", str(self.root))[0], str(store))

    def test_the_documented_setting_wins_over_the_environment_variable(self):
        # 🛑 the binary's order: COWORK override → autoMemoryDirectory → the env var.
        auto, env = self.root / "auto", self.root / "env"
        auto.mkdir()
        env.mkdir()
        acct = self.account("work", settings={
            "autoMemoryDirectory": str(auto),
            "env": {self.mod.MEMORY_DIR_ENV: str(env)}})
        self.assertEqual(self.mod.memory_store(acct)[0], str(auto))
        over = self.root / "over"
        acct2 = self.account("two", email="me@two.example", settings={
            "autoMemoryDirectory": str(auto),
            "env": {self.mod.MEMORY_OVERRIDE_ENV: str(over),
                    self.mod.MEMORY_DIR_ENV: str(env)}})
        self.assertEqual(self.mod.memory_store(acct2),
                         (str(over), "settings env.%s" % self.mod.MEMORY_OVERRIDE_ENV,
                          False))

    def test_the_env_var_is_the_only_project_keyed_store(self):
        env = self.root / "env"
        env.mkdir()
        acct = self.account("work", settings={"env": {self.mod.MEMORY_DIR_ENV: str(env)}})
        where, _how = self.mod.memory_dir(acct, "-work", str(self.root / "work"))
        self.assertTrue(where.startswith(str(env) + os.sep + "projects" + os.sep))
        self.assertTrue(where.endswith(os.sep + "memory"))

    def test_a_tilde_in_the_documented_setting_is_expanded(self):
        acct = self.account("work", settings={"autoMemoryDirectory": "~/shared-memory"})
        base, _how, keyed = self.mod.memory_store(acct)
        self.assertEqual(base, os.path.expanduser("~/shared-memory"))
        self.assertFalse(keyed)

    @unittest.skipUnless(shutil.which("git"), "git not installed")
    def test_the_store_slug_is_the_realpath_of_the_git_root(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], capture_output=True)
        link = self.root / "link"
        os.symlink(str(repo), str(link))
        slug = self.mod.memory_slug(str(link))
        self.assertTrue(slug)
        self.assertEqual(slug, self.mod.memory_slug(str(repo)))
        self.assertNotIn("/", slug)

    def test_a_folder_that_is_no_git_tree_is_keyed_on_its_own_path(self):
        # 🛑 It has a store all the same, under the slug of its own realpath. Returning ""
        # here put a literal `<project>` in the move note — a path nothing matches, handed
        # to a session the same note tells to write its notes nowhere else.
        plain = self.root / "work"
        slug = self.mod.memory_slug(str(plain))
        self.assertEqual(slug, re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(str(plain))))
        self.assertNotIn("/", slug)
        self.assertEqual(self.mod.memory_slug(""), "")   # nothing to key on at all

    def notes(self, src, tgt):
        mem = src.transcript.parent / "memory"
        mem.mkdir(exist_ok=True)
        (mem / "MEMORY.md").write_text("- a note\n")
        return mem

    def test_memory_is_never_copied_even_when_neither_home_has_a_store(self):
        # 🛑 the one case that looks harmless is the case that CREATES the second store.
        # README, the matrix page, the lessons page and the skill all promise this, and
        # the code used to do the opposite here.
        src_a = self.account("work")
        tgt = self.account("personal", email="me@home.example", org="org-2")
        s = self.session(src_a)
        self.notes(s, tgt)
        dest, steps = self.mod.copy_in(s, tgt, apply=True)
        self.assertFalse((dest.parent / "memory").exists())
        self.assertIn("copy NO memory/", " ".join(steps))
        self.assertTrue(dest.exists())                               # transcript travels
        self.assertTrue((s.transcript.parent / "memory").exists())   # source untouched

    def test_a_target_that_has_its_own_notes_keeps_them(self):
        src_a = self.account("work")
        tgt = self.account("personal", email="me@home.example", org="org-2")
        s = self.session(src_a)
        self.notes(s, tgt)
        own = tgt.home / "projects" / "-work" / "memory"
        own.mkdir(parents=True)
        (own / "MEMORY.md").write_text("- the target's own note\n")
        self.mod.copy_in(s, tgt, apply=True)
        self.assertIn("the target's own", (own / "MEMORY.md").read_text())

    def test_a_store_means_no_memory_is_copied_at_all(self):
        store = self.root / "store"
        store.mkdir()
        src_a = self.account("work")
        tgt = self.account("personal", email="me@home.example", org="org-2",
                           settings={"env": {self.mod.MEMORY_DIR_ENV: str(store)}})
        s = self.session(src_a)
        self.notes(s, tgt)
        dest, steps = self.mod.copy_in(s, tgt, apply=True)
        self.assertFalse((dest.parent / "memory").exists())
        self.assertIn("copy NO memory/", " ".join(steps))
        self.assertTrue(dest.exists())                      # the transcript still travels
        self.assertTrue((s.transcript.parent / "memory").exists())   # source untouched

    def test_the_notes_say_whether_memory_is_shared(self):
        store = self.root / "store"
        store.mkdir()
        shared = {"env": {self.mod.MEMORY_DIR_ENV: str(store)}}
        src_a = self.account("work", settings=shared)
        tgt = self.account("personal", email="me@home.example", org="org-2", settings=shared)
        s = self.session(src_a)
        self.notes(s, tgt)
        memory_notes = [n for n in self.mod.target_notes(s, tgt, "default")
                        if "auto-memory" in n]
        self.assertEqual(memory_notes, [])                  # the same store: nothing to say
        apart = self.account("apart", email="me@else.example", org="org-3")
        note = [n for n in self.mod.target_notes(s, apart, "default")
                if "auto-memory is per account" in n]
        self.assertTrue(note)
        self.assertIn("1 note file(s)", note[0])

    def test_a_source_with_no_notes_says_nothing_about_memory(self):
        src_a = self.account("work")
        tgt = self.account("personal", email="me@home.example", org="org-2")
        s = self.session(src_a)
        self.assertEqual([n for n in self.mod.target_notes(s, tgt, "default")
                          if "auto-memory" in n], [])


# ------------------------------------------------------------- resolving the settings

class SettingsResolution(InProc):
    """🛑 The CLI resolves each setting by its own KEY PATH across the sources. A reader
    that layers whole top-level objects loses every sibling key — and the common shape
    (an accumulated `permissions.allow` in settings.local.json) then erases the permission
    mode, disableAutoMode and the memory store that the home really reads."""

    def home_with(self, name, base, local=None):
        acct = self.account(name, settings=base)
        if local is not None:
            (acct.home / "settings.local.json").write_text(json.dumps(local))
        return acct

    def test_an_allow_list_overlay_does_not_erase_the_permission_mode(self):
        acct = self.home_with("work",
                              {"permissions": {"defaultMode": "bypassPermissions",
                                               "disableAutoMode": "disable"}},
                              {"permissions": {"allow": ["Bash(ls:*)"]}})
        s = self.mod.effective_settings(acct.home)
        self.assertEqual(s["permissions"]["defaultMode"], "bypassPermissions")
        self.assertEqual(s["permissions"]["disableAutoMode"], "disable")
        self.assertEqual(s["permissions"]["allow"], ["Bash(ls:*)"])
        self.assertEqual(self.mod.settings3(acct.home)[0]["permissions"]["defaultMode"],
                         "bypassPermissions")

    def test_the_matrix_rows_read_the_same_value_the_move_does(self):
        acct = self.home_with("work",
                              {"permissions": {"defaultMode": "bypassPermissions",
                                               "disableAutoMode": "disable"}},
                              {"permissions": {"allow": ["Bash(ls:*)"]}})
        rows = {r.layer: r for r in self.mod.row_modes([acct])}
        self.assertEqual(rows["permissions mode"].cells[0].text, "bypassPermissions")
        self.assertEqual(rows["disableAutoMode"].cells[0].text, "disable")
        # and the move's own reader agrees, so the table cannot contradict the refusal
        self.assertEqual(self.mod.settings_mode(acct)[0], "bypassPermissions")

    def test_two_homes_reading_one_shared_file_are_not_a_divergence(self):
        a = self.home_with("one", {"permissions": {"defaultMode": "bypassPermissions"}},
                           {"permissions": {"allow": ["Bash(ls:*)"]}})
        b = self.home_with("two", {"permissions": {"defaultMode": "bypassPermissions"}})
        rows = {r.layer: r for r in self.mod.row_modes([a, b])}
        self.assertEqual([c.text for c in rows["permissions mode"].cells],
                         ["bypassPermissions", "bypassPermissions"])
        self.assertEqual(rows["permissions mode"].state, "ok")

    def test_the_overlay_still_wins_on_a_key_it_does_define(self):
        acct = self.home_with("work", {"permissions": {"defaultMode": "plan"}},
                              {"permissions": {"defaultMode": "acceptEdits"}})
        self.assertEqual(
            self.mod.effective_settings(acct.home)["permissions"]["defaultMode"],
            "acceptEdits")

    def test_an_env_block_in_both_files_keeps_both_keys(self):
        store = self.root / "store"
        store.mkdir()
        acct = self.home_with("work", {"env": {self.mod.MEMORY_DIR_ENV: str(store)}},
                              {"env": {"SOMETHING_ELSE": "1"}})
        self.assertEqual(self.mod.memory_store(acct)[0], str(store))

    def test_a_non_utf8_state_file_is_unreadable_not_a_traceback(self):
        # 🛑 read_text raises UnicodeDecodeError, which is a ValueError and not an
        # OSError, so it escaped every guard and killed the whole matrix.
        p = self.root / "broken.json"
        p.write_bytes(b'{"a": "\xff\xfe"}')
        self.assertEqual(self.mod.read_json3(p), (None, "unreadable"))
        self.assertIsNone(self.mod.read_json(p))

    def test_the_matrix_prints_a_reason_instead_of_dying_on_one(self):
        acct = self.account("work")
        acct.state_file.write_bytes(b'{"oauthAccount": {"emailAddress": "\xff"}}')
        (acct.home / "settings.json").write_bytes(b"{\xff}")
        cwd = str(self.root / "work")
        os.makedirs(cwd, exist_ok=True)
        rows = {r.layer: r for r in self.mod.matrix_rows([acct], cwd)}
        for layer in ("account", "folder trust", "onboarding", "permissions mode"):
            self.assertEqual(rows[layer].cells[0].state, "unknown", layer)
            self.assertTrue(rows[layer].note, layer)

    def test_an_accounts_file_that_is_not_text_is_refused_not_raised_raw(self):
        p = self.root / "accounts"
        p.write_bytes(b"work \xff/home\n")
        with self.assertRaises(self.mod.Refusal):
            self.mod.parse_accounts_file(p)


# ------------------------------------------------------------------- the side data

class OtherHomes(InProc):
    """Which homes the live-twin check asks, and the one case a cross-machine move changes."""

    def test_a_cross_machine_source_home_is_not_excluded_from_the_twin_check(self):
        """🛑 Two machines often spell one config home identically (the same user name).
        For a `--from-machine` move `s.account.home` is a path over THERE, so excluding
        this machine's home of the same name would drop a real local home from the check
        and let a move land on a transcript a local process is writing."""
        a = self.account("work")
        b = self.account("personal", email="me@home.example")
        s = self.session(a)
        self.assertNotIn("work", [x.name for x in self.mod.other_homes(s, b, [a, b])],
                         "on one machine the source is the source, and not a third home")
        s.origin = "desktop"
        self.assertIn("work", [x.name for x in self.mod.other_homes(s, b, [a, b])])

    def test_the_target_is_always_excluded(self):
        a = self.account("work")
        b = self.account("personal", email="me@home.example")
        s = self.session(a)
        s.origin = "desktop"
        self.assertNotIn("personal", [x.name for x in self.mod.other_homes(s, b, [a, b])])


class SideData(InProc):
    def test_the_sessions_own_side_data_travels_additively(self):
        src_a = self.account("work")
        tgt = self.account("personal", email="me@home.example", org="org-2")
        s = self.session(src_a)
        (src_a.home / "file-history" / SID_A).mkdir(parents=True)
        (src_a.home / "file-history" / SID_A / "abc@v1").write_text("one")
        (src_a.home / "tasks" / SID_A).mkdir(parents=True)
        (src_a.home / "tasks" / SID_A / "t1.json").write_text("{}")
        mine = tgt.home / "file-history" / SID_A
        mine.mkdir(parents=True)
        (mine / "abc@v1").write_text("the target's own, newer")
        self.mod.copy_in(s, tgt, apply=True)
        self.assertEqual((mine / "abc@v1").read_text(), "the target's own, newer")
        self.assertTrue((tgt.home / "tasks" / SID_A / "t1.json").exists())

    def test_side_data_never_crosses_machines(self):
        """🛑 For a `--from-machine` move the source home is a path on the OTHER machine,
        and two machines often spell one home identically. Reading it here would pick up
        THIS machine's `file-history/<id>/` — an earlier local copy's rewind history — and
        file it under the moved session as if it were its own."""
        src_a = self.account("work")
        tgt = self.account("personal", email="me@home.example", org="org-2")
        s = self.session(src_a)
        (src_a.home / "file-history" / SID_A).mkdir(parents=True)
        (src_a.home / "file-history" / SID_A / "abc@v1").write_text("one")
        self.assertTrue(self.mod.side_data(s, tgt), "on one machine it travels")
        s.origin = "desktop"
        self.assertEqual(self.mod.side_data(s, tgt), [])
        self.mod.copy_in(s, tgt, apply=True)
        self.assertFalse((tgt.home / "file-history" / SID_A).exists())

    def test_nothing_else_from_the_home_is_ever_carried(self):
        src_a = self.account("work")
        tgt = self.account("personal", email="me@home.example", org="org-2")
        s = self.session(src_a)
        for name in ("sessions", "session-env", "shell-snapshots", "jobs"):
            (src_a.home / name).mkdir(parents=True, exist_ok=True)
            (src_a.home / name / (SID_A + ".json")).write_text("{}")
        self.mod.copy_in(s, tgt, apply=True)
        for name in ("sessions", "session-env", "shell-snapshots", "jobs"):
            self.assertFalse((tgt.home / name / (SID_A + ".json")).exists(), name)


# ----------------------------------------------------------------- the environment scrub

DIRTY = {
    "CLAUDECODE": "1", "CLAUDE_PID": "4242", "CLAUDE_CODE_SESSION_ID": "s",
    "CLAUDE_CODE_OAUTH_TOKEN": "tok", "CLAUDE_CODE_OAUTH_REFRESH_TOKEN": "tok",
    "ANTHROPIC_API_KEY": "key", "ANTHROPIC_AUTH_TOKEN": "key",
    "ANTHROPIC_BASE_URL": "https://elsewhere.example", "CLAUDE_CODE_USE_BEDROCK": "1",
    "CLAUDE_CODE_USE_VERTEX": "1", "ANTHROPIC_MODEL": "something",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "1", "CLOUD_ML_REGION": "r",
    "AWS_BEARER_TOKEN_BEDROCK": "b", "CLAUDE_A_NAME_NOBODY_HAS_INVENTED_YET": "x",
    "ANTHROPIC_SOMETHING_NEW": "x",
}
MINE = {"AWS_PROFILE": "work", "GOOGLE_APPLICATION_CREDENTIALS": "/tmp/gcp.json",
        "PATH": "/usr/bin", "CSM_POLL": "0.05"}


class Scrub(InProc):
    def test_both_families_go_including_names_nobody_has_invented_yet(self):
        env = dict(DIRTY)
        env.update(MINE)
        out = self.mod.scrubbed_env(env)
        for gone in DIRTY:
            self.assertNotIn(gone, out, gone)
        # ⚠️ it is two families plus two names, not a general cleanout: your own auth
        # survives, because that is what your work inside the session uses
        for kept in MINE:
            self.assertEqual(out[kept], MINE[kept])
        self.assertEqual(self.mod.SCRUB_PREFIXES, ("CLAUDE", "ANTHROPIC"))

    def test_csm_keep_env_puts_back_exactly_what_it_names_and_nothing_else(self):
        env = dict(DIRTY)
        env["CLAUDE_SESSION_TOOL_ACCOUNTS"] = "/etc/accounts"
        self.mod.KEEP_EXACT = frozenset({"CLAUDE_SESSION_TOOL_ACCOUNTS"})
        out = self.mod.scrubbed_env(env)
        self.assertEqual(out["CLAUDE_SESSION_TOOL_ACCOUNTS"], "/etc/accounts")
        for gone in DIRTY:
            self.assertNotIn(gone, out, gone)

    def test_a_name_outside_the_two_families_is_not_a_keep_list_entry(self):
        # 🛑 The knob is a put-back inside the scrub, not a general allowlist: a name the
        # scrub never touches has no business being named here, and honouring it would turn
        # one env var into a way to re-open the families it is carved out of.
        import subprocess as sp
        r = sp.run([PY, "-I", "-c", "import os, importlib.machinery as m, importlib.util as u;"
                    "import sys;l=m.SourceFileLoader('csm_x', %r);"
                    "s=u.spec_from_loader('csm_x', l);"
                    "mod=u.module_from_spec(s);sys.modules['csm_x']=mod;"
                    "l.exec_module(mod);"
                    "print(sorted(mod.KEEP_EXACT))" % str(TOOL)],
                   capture_output=True, text=True,
                   env=dict(os.environ, CSM_KEEP_ENV="AWS_PROFILE,CLAUDE_X,PATH"))
        self.assertEqual(r.stdout.strip(), "['CLAUDE_X']", r.stdout + r.stderr)

    def test_the_test_only_knobs_never_follow_a_move(self):
        # A stale export of one of these inside a moved window would force a credential
        # probe's answer, or make "the other machine" this very process.
        out = self.mod.scrubbed_env({"CSM_LOGIN_PROBE": "true", "CSM_REMOTE_LOCAL": "1",
                                     "CSM_REMOTE_HOME": "/x", "CSM_TMUX_SOCKET": "sock",
                                     "CSM_POLL": "0.05"})
        self.assertEqual(sorted(out), ["CSM_POLL", "CSM_TMUX_SOCKET"])


# --------------------------------------------------------------------- the login probe

class LoginProbe(InProc):
    def test_the_keychain_slot_is_hashed_from_the_literal_string(self):
        import hashlib
        home = self.root / "home" / ".claude-work"
        acct = self.mod.Account("work", home)
        want = hashlib.sha256(str(home).encode()).hexdigest()[:8]
        self.assertEqual(acct.credential_service, "Claude Code-credentials-" + want)
        # 🛑 the hash is over the literal string, never a realpath: the SAME directory
        # reached by another spelling is a different login, which is why renaming or
        # moving a home orphans it until the Keychain item is copied across
        link = self.root / "home" / "link-to-work"
        home.mkdir(parents=True, exist_ok=True)
        os.symlink(str(home), str(link))
        self.assertNotEqual(self.mod.Account("w2", link).credential_service,
                            acct.credential_service)
        # the unset default home has the bare name
        self.assertEqual(self.mod.Account("d", home, default=True).credential_service,
                         "Claude Code-credentials")

    def test_the_three_states(self):
        import contextlib
        import io
        acct = self.account("work")
        for forced, want in (("true", (True, "")), ("false", False), ("unknown", True)):
            self.mod.LOGIN_PROBE = forced
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                ok, sentence = self.mod.login_usable(acct)
            self.assertIn("CSM_LOGIN_PROBE", err.getvalue())   # it announces itself, always
            if forced == "true":
                self.assertEqual((ok, sentence), (True, ""))
            elif forced == "false":
                self.assertFalse(ok)
                self.assertIn("credential is GONE", sentence)
            else:
                self.assertTrue(ok)
                self.assertIn("UNVERIFIED", sentence)

    def test_an_unknown_probe_value_is_refused_rather_than_guessed(self):
        self.mod.LOGIN_PROBE = "maybe-ish"
        with self.assertRaises(self.mod.Refusal):
            self.mod.credential_present(self.account("work"))

    def test_a_home_that_names_nobody_is_refused_before_the_store_is_asked(self):
        acct = self.account("work", email=None)
        ok, sentence = self.mod.login_usable(acct)
        self.assertFalse(ok)
        self.assertIn("/login", sentence)

    def set_user(self, value):
        """Set (or unset, with None) `$USER` for this test only."""
        old = os.environ.get("USER")

        def restore():
            if old is None:
                os.environ.pop("USER", None)
            else:
                os.environ["USER"] = old
        self.addCleanup(restore)
        if value is None:
            os.environ.pop("USER", None)
        else:
            os.environ["USER"] = value

    def fake_security(self, answer):
        """Stand in for `security find-generic-password`; `answer(argv) -> exit code`."""
        import types
        plat = sys.platform
        asked = []

        class R(object):
            def __init__(self, rc):
                self.returncode = rc

        real = self.mod.subprocess
        self.mod.subprocess = types.SimpleNamespace(
            run=lambda argv, **k: asked.append(argv) or R(answer(argv)),
            SubprocessError=real.SubprocessError, DEVNULL=real.DEVNULL)
        self.addCleanup(setattr, self.mod, "subprocess", real)
        self.addCleanup(setattr, self.mod.sys, "platform", plat)
        self.mod.sys.platform = "darwin"
        self.mod.LOGIN_PROBE = ""
        return asked

    def test_the_keychain_account_falls_back_to_the_os_user_not_the_sentinel(self):
        # 🛑 USER is not exported in a container, under `env -i`, or on some CI runners.
        # Reaching for the sentinel there asks about an account that does not exist, the
        # probe answers errSecItemNotFound, and EVERY home reads as signed out — a hard
        # refusal in exactly the unattended context the tool is meant for.
        import pwd as _pwd
        self.set_user(None)
        self.assertEqual(self.mod.keychain_user(), _pwd.getpwuid(os.getuid()).pw_name)
        for odd in ("a name with spaces", "no/slashes"):
            self.set_user(odd)
            self.assertEqual(self.mod.keychain_user(), "claude-code-user", odd)
        self.set_user("someone")
        self.assertEqual(self.mod.keychain_user(), "someone")

    def test_the_trailing_slash_spelling_of_a_home_is_tried_once(self):
        # 🛑 the item is named from the LITERAL CLAUDE_CONFIG_DIR, and expanduser drops a
        # trailing slash — so a home signed in with one would read as signed out and the
        # move would refuse a target that works. One extra probe, and no more.
        home = self.root / "home" / ".claude-work"
        acct = self.mod.Account("work", home)
        got = self.mod.credential_services(acct)
        self.assertEqual([s for _l, s in got],
                         [self.mod.keychain_service_for(str(home)),
                          self.mod.keychain_service_for(str(home) + os.sep)])
        self.assertEqual(got[0][0], "")
        self.assertEqual(got[1][0], str(home) + os.sep)
        self.assertEqual(len(got), 2)                 # nothing speculative is added
        # the default home has one name and no variants: CLAUDE_CONFIG_DIR is unset
        self.assertEqual(self.mod.credential_services(
            self.mod.Account("d", home, default=True)),
            [("", "Claude Code-credentials")])

    def test_a_home_signed_in_under_the_other_spelling_reads_as_signed_in(self):
        import contextlib
        import io
        home = self.root / "home" / ".claude-work"
        acct = self.mod.Account("work", home)
        slashed = self.mod.keychain_service_for(str(home) + os.sep)
        asked = self.fake_security(lambda argv: 0 if slashed in argv else 44)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertIs(self.mod.credential_present(acct), True)
        self.assertEqual(len(asked), 2)               # the plain spelling, then the slash
        self.assertIn("literal CLAUDE_CONFIG_DIR", err.getvalue())

    def test_both_spellings_missing_is_still_a_definite_signed_out(self):
        acct = self.mod.Account("work", self.root / "home" / ".claude-work")
        self.fake_security(lambda argv: 44)
        self.assertIs(self.mod.credential_present(acct), False)

    def test_a_locked_keychain_stops_the_probe_at_unknown(self):
        acct = self.mod.Account("work", self.root / "home" / ".claude-work")
        asked = self.fake_security(lambda argv: 36)   # the keychain is locked
        self.assertIsNone(self.mod.credential_present(acct))
        self.assertEqual(len(asked), 1)   # unknown stops it: no second call to hang on


# ------------------------------------------------------------------------- soft picking

class OnOtherMachines(InProc):
    def test_the_ssh_flag_forwards_the_rest_of_the_command_unchanged(self):
        import types
        seen = []

        class FakeRun:
            returncode = 0

        real = self.mod.subprocess
        # rebind the NAME inside the tool's module, never a shared module's attribute
        self.mod.subprocess = types.SimpleNamespace(
            run=lambda argv, *a, **k: seen.append(argv) or FakeRun(),
            CompletedProcess=real.CompletedProcess, SubprocessError=real.SubprocessError,
            DEVNULL=real.DEVNULL, PIPE=real.PIPE, STDOUT=real.STDOUT, Popen=real.Popen)
        self.addCleanup(setattr, self.mod, "subprocess", real)
        self.mod.over_ssh("host", ["--ssh", "host", "move", "host", "--to", "work"])
        self.mod.over_ssh("host", ["--ssh=host", "move", "host", "--to", "work"])
        for argv in seen:
            # the flag goes by POSITION: a session spec that happens to equal the host
            # name must survive
            self.assertTrue(argv[-1].endswith("move host --to work"), argv)
            self.assertNotIn("--ssh", argv[-1])

    def test_the_help_distinguishes_the_two_ways_a_second_machine_is_involved(self):
        """🛑 The two are confusable and the help has to separate them: `--machine M` runs
        the command OVER THERE and brings nothing here, while `move --from-machine M`
        brings a session here. The help used to say a move never crosses machines at all,
        which `--from-machine` made untrue."""
        import argparse
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit):
                self.mod.main(["--help"])
        txt = out.getvalue()
        self.assertIn("Both homes are on this machine", txt)
        self.assertIn("--from-machine", txt)
        self.assertIn("It brings nothing here", txt)
        self.assertIsInstance(argparse.ArgumentParser(), argparse.ArgumentParser)


class BridgeLine(InProc):
    def test_the_shape_of_an_appended_bridge_session_line_is_pinned(self):
        # 🛑 the KEYS, not a claim about what the app renders: a move makes a new claude.ai
        # session, and what the web client shows above your next message is its business
        acct = self.account("work")
        line = {"type": "bridge-session", "sessionId": SID_A,
                "bridgeSessionId": "cse_01NewLink0123456", "lastSequenceNum": 3,
                "ownerAccountUuid": "acc-uuid", "ownerOrganizationUuid": "org-uuid"}
        s = self.session(acct, lines=[user("go", str(self.root / "work"), SID_A), line])
        info = self.mod.scan_transcript(s.transcript)
        self.assertEqual(info["bridge_id"], "01NewLink0123456")

    #: The measured shape of a `/remote-control is active` line (CLI 2.1.312, Wed 28 Oct
    #: 2026: 97 of the 1,935 transcripts in the config homes here carry one). `content` and
    #: `url` both name the session; only `url` is machine-readable.
    STATUS = {"type": "system", "subtype": "bridge_status", "sessionId": SID_A,
              "isMeta": False, "isSidechain": False, "userType": "external",
              "entrypoint": "cli", "version": "2.1.312",
              "content": "/remote-control is active · Continue here, on your phone, or at "
                         "https://claude.ai/code/session_01StatusLink0001",
              "url": "https://claude.ai/code/session_01StatusLink0001"}

    def test_a_bridge_status_url_is_a_bridge_id_source_too(self):
        """🛑 The third place a transcript names its claude.ai session.

        Without this, a self-hosted session whose one `bridge-session` line fell into the
        unread middle of a long transcript had no claude.ai id at all — so its own link
        could not find it, which is the whole point of resolving a link.
        """
        acct = self.account("work")
        s = self.session(acct, lines=[user("go", str(self.root / "work"), SID_A),
                                      self.STATUS])
        self.assertEqual(self.mod.scan_transcript(s.transcript)["bridge_id"],
                         "01StatusLink0001")

    def test_an_explicit_bridge_session_line_wins_over_a_status_url(self):
        """They name the same session; the line the CLI writes on purpose is the answer."""
        acct = self.account("work")
        line = {"type": "bridge-session", "sessionId": SID_A,
                "bridgeSessionId": "cse_01TheRealOne001"}
        s = self.session(acct, lines=[user("go", str(self.root / "work"), SID_A),
                                      self.STATUS, line])
        self.assertEqual(self.mod.scan_transcript(s.transcript)["bridge_id"],
                         "01TheRealOne001")

    def test_a_status_line_without_a_url_says_nothing(self):
        acct = self.account("work")
        bad = dict(self.STATUS)
        bad.pop("url")
        s = self.session(acct, lines=[user("go", str(self.root / "work"), SID_A), bad,
                                      {"type": "system", "subtype": "other",
                                       "url": "https://claude.ai/code/session_01Nope00001"}])
        self.assertEqual(self.mod.scan_transcript(s.transcript)["bridge_id"], "")


class DeriveId(InProc):
    """🛑 A LINK NAMES ITS TRANSCRIPT BY ARITHMETIC, and these are the measured pairs.

    This is the one fact the whole dead-session lookup rests on: with no process, no
    registry row and no network, `uuid5(BRIDGE_NS, <the bridge session's api url>)` is the
    name of the file on disk. See `LINK_BARE` above for why the pairs are written out.
    """

    PAIRS = ((LINK_BARE, LINK_SID), (LINK_BARE2, LINK_SID2))

    def test_the_two_measured_pairs_derive_from_every_spelling(self):
        for bare, want in self.PAIRS:
            for form in ("cse_" + bare, "session_" + bare, link_of(bare),
                         link_of(bare) + "?tab=files", link_of(bare) + "#top",
                         "https://api.anthropic.com/v1/code/sessions/cse_" + bare,
                         "  " + link_of(bare) + "  "):
                self.assertEqual(self.mod.derive_local_id(form), want, form)
                self.assertEqual(self.mod.bare_bridge_id(form), bare, form)

    def test_a_derived_id_is_always_a_version_5_uuid(self):
        """So it can never collide with a terminal session, which gets a random v4 id."""
        for bare, want in self.PAIRS:
            self.assertEqual(uuid.UUID(self.mod.derive_local_id("cse_" + bare)).version, 5)
            self.assertEqual(uuid.UUID(want).version, 5)

    def test_a_spacesheep_session_page_is_the_local_id_itself(self):
        # measured Wed 28 Oct 2026: sessionpipe's claude-code session id IS the local id
        self.assertEqual(
            self.mod.derive_local_id(
                "https://spacesheep.dev/sessions/claude-code/" + LINK_SID.upper()),
            LINK_SID)
        self.assertEqual(self.mod.bare_bridge_id(
            "https://spacesheep.dev/sessions/claude-code/" + LINK_SID), "")

    def test_nothing_that_is_not_a_link_derives_anything(self):
        for spec in ("", "   ", "refactor the parser", "3", SID_A, SID_A[:8],
                     "https://claude.ai/code/", "https://claude.ai/code/sessions",
                     "cse-" + LINK_BARE, "session" + LINK_BARE,
                     "https://spacesheep.dev/sessions/claude-code/not-a-uuid"):
            self.assertEqual(self.mod.derive_local_id(spec), "", repr(spec))

    def test_the_segment_must_be_the_WHOLE_segment(self):
        """⚠️ Stricter than `URL_RE` on purpose: this output is a filename."""
        self.assertEqual(self.mod.bare_bridge_id("x-session_" + LINK_BARE), "")
        self.assertEqual(self.mod.bare_bridge_id("session_" + LINK_BARE + ".jsonl"), "")
        self.assertEqual(self.mod.bare_bridge_id("/a/b/session_" + LINK_BARE + "/c"),
                         LINK_BARE)

    # --- the spec layer ---------------------------------------------------
    def test_a_whole_local_id_is_pinned_and_is_not_a_link(self):
        sp = self.mod.resolve_spec(SID_A.upper(), [])
        self.assertEqual(sp.pin, SID_A)
        self.assertFalse(sp.link)
        self.assertEqual(self.mod.spec_notes(sp), [])

    def test_a_spec_that_is_not_a_link_pays_nothing_for_any_of_this(self):
        """🛑 The canary is only asked about a spec that was DERIVED. An ordinary `csm move
        3` must not read a 290 MB bundle, glob for a file it did not compute, or leave a
        cache behind — the resolution path is on every subcommand."""
        a = self.account("work")
        self.bundle(b"a build with no such namespace in it")
        for spec in ("3", "refactor", SID_A, SID_A[:8], ""):
            sp = self.mod.resolve_spec(spec, [a])
            self.assertEqual(sp.canary, {}, spec)
            self.assertFalse(sp.link, spec)
        self.assertFalse(list(self.mod.STATE_DIR.glob("canary-*")),
                         "nothing was derived, so nothing should have been checked")

    def test_a_link_whose_transcript_is_here_pins_the_derived_id(self):
        a = self.account("work")
        self.session(a, sid=LINK_SID)
        sp = self.mod.resolve_spec(link_of(LINK_BARE), [a])
        self.assertTrue(sp.link)
        self.assertEqual((sp.bare, sp.derived, sp.pin), (LINK_BARE, LINK_SID, LINK_SID))
        self.assertEqual(sp.homes, ["work"])
        self.assertIn("resolved from the link", " ".join(self.mod.spec_notes(sp)))

    def test_a_link_whose_transcript_is_not_here_pins_nothing_but_stays_a_link(self):
        a = self.account("work")
        self.session(a, sid=SID_A)
        sp = self.mod.resolve_spec(link_of(LINK_BARE), [a])
        self.assertTrue(sp.link)
        self.assertEqual(sp.derived, LINK_SID)
        self.assertEqual(sp.pin, "")
        self.assertEqual((sp.homes, sp.searched), ([], ["work"]))

    def test_a_home_whose_projects_cannot_be_read_does_not_answer_for_the_others(self):
        a = self.account("locked")
        b = self.account("work", email="me@home.example")
        self.session(b, sid=LINK_SID)
        (a.home / "projects").chmod(0o000)
        self.addCleanup(lambda: (a.home / "projects").chmod(0o700))
        sp = self.mod.resolve_spec(link_of(LINK_BARE), [a, b])
        self.assertEqual(sp.homes, ["work"])

    # --- the version canary -----------------------------------------------
    def bundle(self, body, version="9.9.9"):
        """A stand-in CLI bundle at the path `cli_version` reads a version out of."""
        p = self.root / "versions" / version
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        p.chmod(0o755)
        os.environ["CSM_CLAUDE"] = str(p)
        self.addCleanup(os.environ.pop, "CSM_CLAUDE", None)
        return p

    def test_the_canary_finds_the_constant_across_a_chunk_boundary(self):
        """⚠️ The needle sits at an offset the chunking cannot land on, so the overlap —
        not luck — is what finds it."""
        needle = self.mod.BRIDGE_NS.encode()
        self.bundle(b"a" * 60 + needle + b"b" * 500)
        self.mod.CANARY_CHUNK = 1          # floored at 2x the needle inside `canary`
        c = self.mod.canary()
        self.assertIs(c["ok"], True)
        self.assertEqual(c["version"], "9.9.9")
        self.assertIn("1 occurrence", c["why"])

    def test_the_verdict_is_cached_per_version_and_0600(self):
        p = self.bundle(b"x" * 100 + self.mod.BRIDGE_NS.encode())
        self.assertIs(self.mod.canary()["ok"], True)
        cache = self.mod.canary_path("9.9.9")
        self.assertTrue(cache.exists())
        self.assertEqual(stat.S_IMODE(cache.stat().st_mode), 0o600)
        # 🛑 THE CACHE IS WHAT ANSWERS THE SECOND TIME, and this is how that is proved:
        # the bundle becomes unreadable, so a rescan could only say "could not look", while
        # the cached verdict (keyed on path, size and mtime, all still readable) stands.
        p.chmod(0o000)
        self.addCleanup(p.chmod, 0o755)
        self.assertIs(self.mod.canary()["ok"], True)

    def test_an_upgrade_invalidates_the_cache(self):
        p = self.bundle(b"x" * 100 + self.mod.BRIDGE_NS.encode())
        self.assertIs(self.mod.canary()["ok"], True)
        p.write_bytes(b"a new build that does not derive ids this way")
        os.utime(str(p), (time.time() + 5, time.time() + 5))
        c = self.mod.canary()
        self.assertIs(c["ok"], False)
        self.assertIn("is NOT in", c["why"])

    def test_a_bundle_nothing_can_read_is_unknown_and_never_a_pass(self):
        p = self.bundle(b"x" * 100 + self.mod.BRIDGE_NS.encode())
        p.chmod(0o000)
        self.addCleanup(p.chmod, 0o755)
        c = self.mod.canary()
        self.assertIsNone(c["ok"], "could not look is not ok")
        self.assertIn("could not be read", c["why"])

    def test_no_claude_at_all_is_unknown_and_says_where_it_looked(self):
        os.environ["CSM_CLAUDE"] = str(self.root / "nope" / "claude")
        self.addCleanup(os.environ.pop, "CSM_CLAUDE", None)
        c = self.mod.canary()
        self.assertIsNone(c["ok"])
        self.assertTrue(c["why"], c)

    def test_an_unverified_derivation_is_said_out_loud(self):
        a = self.account("work")
        self.session(a, sid=LINK_SID)
        self.bundle(b"a build with no such namespace in it")
        sp = self.mod.resolve_spec(link_of(LINK_BARE), [a])
        notes = " ".join(self.mod.spec_notes(sp))
        self.assertIn("derivation unverified for CLI 9.9.9", notes)
        self.assertIn("resolved from the link", notes, "and it still resolves")


class SoftPick(InProc):
    def rows(self):
        a = self.account("work")
        b = self.account("personal", email="me@home.example", org="org-2")
        return [self.session(a, SID_A), self.session(b, SID_A)]

    def test_soft_returns_none_where_the_hard_one_refuses(self):
        rows = self.rows()
        self.assertIsNone(self.mod.pick(SID_A, rows, soft=True))
        with self.assertRaises(self.mod.Refusal) as e:
            self.mod.pick(SID_A, rows)
        self.assertIn("a move is a copy", str(e.exception))
        self.assertIsNone(self.mod.pick("nothing like it", rows, soft=True))
        self.assertIs(self.mod.pick(SID_A, rows[:1], soft=True), rows[0])


# -------------------------------------------------------------- what the transcript says

class TranscriptFacts(Base):
    def test_every_quota_error_name_is_recognised(self):
        cwd = str(self.w.work)
        future = int((time.time() + 3600) * 1000)
        for i, name in enumerate(("usage_limit_reached", "rate_limit_error",
                                  "rate_limit_exceeded")):
            sid = "%08d-aaaa-4aaa-8aaa-111111111111" % i
            self.w.session(self.work, sid, lines=[
                user("go", cwd, sid),
                assistant("limit", cwd, sid, error=name, resets=future)])
        rows = {r["local_id"]: r for r in self.listing()}
        self.assertTrue(all(r["out_of_quota"] for r in rows.values()), rows)

    def test_a_reset_recorded_under_quota_limits_is_read(self):
        cwd = str(self.w.work)
        future = int((time.time() + 3600) * 1000)
        line = assistant("limit", cwd, SID_A, error="rate_limit_error", resets=None)
        line["apiErrorParams"] = {"rate_limit_info": {"rateLimitType": "seven_day"},
                                  "quotaLimits": {"resetsAt": future}}
        self.w.session(self.work, SID_A, lines=[user("go", cwd, SID_A), line])
        row = self.listing()[0]
        self.assertTrue(row["out_of_quota"])
        self.assertAlmostEqual(row["quota"]["resets_at"], future / 1000, delta=1)

    def test_a_session_ended_from_the_app_is_closed_not_ended(self):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[
            user("go", cwd, SID_A), assistant("ok", cwd, SID_A),
            {"type": "system", "sessionId": SID_A,
             "message": {"role": "system", "content": "Remote session ended (code 4090)"}}])
        self.assertTrue(self.listing()[0]["ended_remotely"])
        self.assertIn("closed", self.ok(self.w.run("list")))

    def test_the_mcp_servers_and_connectors_a_session_used_are_listed(self):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[
            user("go", cwd, SID_A),
            {"type": "assistant", "cwd": cwd, "sessionId": SID_A, "isSidechain": False,
             "message": {"role": "assistant", "model": "claude-sonnet-4-5", "content": [
                 {"type": "tool_use", "name": "mcp__claude_ai_Gmail__search", "input": {}},
                 {"type": "tool_use", "name": "mcp__local_notes__add", "input": {}}]}}])
        self.assertEqual(self.listing()[0]["mcp_servers"],
                         ["claude_ai_Gmail", "local_notes"])


class QuotaShapes(InProc):
    """🛑 TWO SHAPES OF ONE STOP, and the second read as a clean finish.

    Measured on this machine, CLI 2.1.312, Wed 28 Oct 2026: of 44 assistant quota-stop
    lines in the config homes here, 34 carry an `apiError` and 10 carry none at all — only
    `isApiErrorMessage: true`, `error: "rate_limit"`, `apiErrorStatus: 429` and a top-level
    `quotaLimits` ({status: "rejected", resetsAt, rateLimitType}). Those landed in the
    clean-assistant-line branch, so csm reported the session as FINISHED and `quota` stayed
    empty — on roughly a quarter of the real stops on this machine. Every answer that keys
    on "why did it stop" is wrong for those, which is why both shapes are pinned here and
    not merely one.
    """

    def quota_of(self, *lines):
        a = self.account("work")
        s = self.session(a, lines=list(lines))
        return self.mod.scan_transcript(s.transcript)

    def stop(self, shape, resets=None, kind="five_hour", text="You've hit your limit"):
        cwd = str(self.root / "work")
        return assistant(text, cwd, SID_A, error="usage_limit_reached", resets=resets,
                         kind=kind, shape=shape)

    def go(self):
        return user("go", str(self.root / "work"), SID_A)

    def clean(self, text="answering again"):
        return assistant(text, str(self.root / "work"), SID_A)

    def test_both_shapes_are_read_as_a_quota_stop(self):
        future = time.time() + 3600
        for shape in ("apiError", "rate_limit"):
            q = self.quota_of(self.go(), self.stop(shape, resets=future))["quota"]
            self.assertTrue(q, shape)
            self.assertEqual(q["kind"], "five_hour", shape)
            self.assertAlmostEqual(q["resets_at"], future, delta=1, msg=shape)
            self.assertIn("hit your limit", q["message"], shape)

    def test_the_no_apiError_shape_names_its_own_error(self):
        q = self.quota_of(self.go(), self.stop("rate_limit", resets=time.time() + 60))
        self.assertEqual(q["quota"]["error"], "rate_limit")
        self.assertEqual(
            self.quota_of(self.go(), self.stop("apiError", resets=time.time() + 60))
            ["quota"]["error"], "usage_limit_reached")

    def test_the_window_falls_back_to_quotaLimits_rateLimitType(self):
        """The word a caller keys on to say whether WAITING clears the stop at all: a
        five-hour or weekly limit resets, a monthly spend cap does not."""
        for kind in ("five_hour", "seven_day"):
            q = self.quota_of(self.go(), self.stop("rate_limit", resets=time.time() + 60,
                                                   kind=kind))
            self.assertEqual(q["quota"]["kind"], kind)

    def test_a_reset_in_unix_SECONDS_is_read_as_well_as_milliseconds(self):
        # the measured no-apiError lines carry plain unix seconds (1789362000)
        secs = int(time.time() + 7200)
        q = self.quota_of(self.go(), self.stop("rate_limit", resets=secs))
        self.assertAlmostEqual(q["quota"]["resets_at"], secs, delta=1)
        q = self.quota_of(self.go(), self.stop("rate_limit", resets=secs * 1000))
        self.assertAlmostEqual(q["quota"]["resets_at"], secs, delta=1)

    def test_a_stop_line_is_not_a_clean_assistant_line_in_either_shape(self):
        """🛑 The second half of the bug, and the subtler one. A stop line that fell into
        the clean branch also set `assistant_idx`, which is what the in-force heuristic
        compares against — so a GENUINE limit earlier in the tail was read as waited out
        because the limit line after it counted as the session answering again.
        """
        past = time.time() - 7200
        for shape in ("apiError", "rate_limit"):
            q = self.quota_of(self.go(), self.stop(shape, resets=past))["quota"]
            self.assertTrue(q, "%s: the last line is the stop, so it is still waiting"
                            % shape)
        # two stops in a row: the second must not cancel the first either
        q = self.quota_of(self.go(), self.stop("apiError", resets=past),
                          self.stop("rate_limit", resets=past))["quota"]
        self.assertTrue(q)

    def test_a_limit_that_was_waited_out_is_still_not_flagged(self):
        """The existing heuristic, unchanged: a transcript records every limit it ever hit."""
        for shape in ("apiError", "rate_limit"):
            info = self.quota_of(self.go(), self.stop(shape, resets=time.time() - 7200),
                                 self.clean())
            self.assertEqual(info["quota"], {}, shape)
            self.assertEqual(info["model"], "claude-sonnet-4-5", shape)

    def test_an_ordinary_assistant_line_is_still_clean(self):
        info = self.quota_of(self.go(), self.clean())
        self.assertEqual(info["quota"], {})
        self.assertEqual(info["model"], "claude-sonnet-4-5")

    def test_error_alone_is_not_this_line(self):
        """⚠️ BOTH KEYS, TOGETHER. `isApiErrorMessage` without `error: "rate_limit"`, or the
        word on its own, is some other line — and reading either as a quota stop would put
        "out of quota" on sessions that are not."""
        cwd = str(self.root / "work")
        just_flag = assistant("something failed", cwd, SID_A)
        just_flag["isApiErrorMessage"] = True
        just_word = assistant("something failed", cwd, SID_A)
        just_word["error"] = "rate_limit"
        for line in (just_flag, just_word):
            self.assertEqual(self.quota_of(self.go(), line)["quota"], {})

    def test_a_sidechain_stop_is_not_the_session_stopping(self):
        line = self.stop("rate_limit", resets=time.time() + 60)
        line["isSidechain"] = True
        self.assertEqual(self.quota_of(self.go(), self.clean(), line)["quota"], {})


# -------------------------------------------------------------- what revive reads and says

#: The measured shape of a `/remote-control is active` line and of the disconnect the CLI
#: writes when a session is archived or ended from the app. ⚠️ The ORDER of the two in the
#: file is the whole test: `code 4090` BEFORE the last status line is an older disconnect
#: the session recovered from, and only one after it means the session is closed now.
STATUS_LINE = {"type": "system", "subtype": "bridge_status", "isSidechain": False,
               "content": "/remote-control is active · Continue here, on your phone",
               "url": "https://claude.ai/code/session_01StatusLink0001"}
ENDED_LINE = {"type": "system", "subtype": "informational", "isSidechain": False,
              "content": "Remote Control disconnected (code 4090)"}
BRIDGE_LINE = {"type": "bridge-session", "bridgeSessionId": "cse_01SelfHosted00001"}


def tool_call(cwd, sid, name="Edit", tid="tu_1", uuid="a9", parent="u1", stamp=None):
    """An assistant line whose one content block is a `tool_use`: a turn in flight."""
    d = assistant("let me edit that", cwd, sid, uuid=uuid, parent=parent)
    d["message"]["content"] = [{"type": "tool_use", "name": name, "id": tid, "input": {}}]
    if stamp:
        d["timestamp"] = stamp
    return d


def tool_answer(cwd, sid, tid="tu_1", uuid="u9", parent="a9"):
    """The `user` line that answers it. No answer for a `tool_use` id = killed mid-turn."""
    d = user("", cwd, sid, uuid=uuid, parent=parent)
    d["message"]["content"] = [{"type": "tool_result", "tool_use_id": tid,
                                "content": "ok"}]
    return d


def tokens_reminder(cwd, sid, uuid="t9", parent="u1"):
    """The line 2.1.312 writes straight after a user's prompt, so a transcript killed one
    second into the turn does NOT end on the prompt itself.

    🛑 THE MEASURED SHAPE (the config homes on this machine, Thu 29 Oct 2026, week 44):
    `type: "attachment"` — a `MAIN_TYPES` member, so it makes the window non-empty — with
    `attachment.type: "total_tokens_reminder"`, a `renderedRole` of `system`, its own uuid,
    and NO `message` key at all. It is neither the prompt nor an answer to it, which is
    exactly why the reader has to look past the last line to tell the two apart.
    """
    return {"type": "attachment", "cwd": cwd, "sessionId": sid, "isSidechain": False,
            "attachment": {"type": "total_tokens_reminder",
                           "text": "<total_tokens>15000000 tokens left</total_tokens>"},
            "rendered": [{"content": "<system-reminder>\n<total_tokens>15000000 tokens "
                                     "left</total_tokens>\n</system-reminder>"}],
            "renderedRole": "system", "userType": "external", "entrypoint": "cli",
            "uuid": uuid, "parentUuid": parent}


def idle_compaction(cwd, sid, uuid="c9", parent="a1"):
    """WHAT THE CLI LEAVES AT THE END OF A SESSION IT COMPACTED WHILE IT WAS IDLE.

    🛑 THE MEASURED SHAPE (the config homes on this machine, Thu 29 Oct 2026, week 44: 132
    of 1,958 transcripts end in it). The CLI compacts an IDLE session to keep its prompt
    cache warm and says so itself in the `informational` line it writes after — "Compacted
    while idle, before the prompt cache expired" — so the file ends on a `compact_boundary`
    system line, a `user` line carrying `isCompactSummary: true` and
    `isVisibleInTranscriptOnly: true` whose text is the summary, and a run of `attachment`
    lines. There is no assistant line after it, because the session was idle: it had already
    answered everything anybody asked. Returned as the whole run of lines, in order.
    """
    summary = user("This session is being continued from a previous conversation that ran "
                   "out of context. The summary below covers the earlier portion.",
                   cwd, sid, uuid=uuid, parent=parent)
    summary["isCompactSummary"] = True
    summary["isVisibleInTranscriptOnly"] = True
    summary["turnPosition"] = {"promptIndex": 1, "turnIndex": 1}
    def att(kind, u):
        return {"type": "attachment", "cwd": cwd, "sessionId": sid, "isSidechain": False,
                "attachment": {"type": kind}, "renderedRole": "system",
                "uuid": u, "parentUuid": uuid}
    return [{"type": "system", "subtype": "compact_boundary", "isSidechain": False,
             "isMeta": False, "cwd": cwd, "sessionId": sid, "uuid": "sysc", "parentUuid": parent,
             "message": {"role": "system", "content": ""},
             "compactMetadata": {"trigger": "auto", "preTokens": 170000}},
            summary,
            att("compact_file_reference", "at1"), att("environment", "at2"),
            att("skill_listing", "at3"),
            {"type": "system", "subtype": "informational", "isSidechain": False,
             "isMeta": False, "cwd": cwd, "sessionId": sid, "uuid": "sysi",
             "parentUuid": uuid, "content": "Compacted while idle, before the prompt cache "
                                            "expired · turn off with \"idleCompaction\": false"}]


class ReviveDiagnose(InProc):
    """🛑 WHY IT STOPPED, WHAT IT IS, AND WHETHER IT RUNS — the three answers every revive
    action is chosen from, so every one of them is pinned here rather than inferred.

    The stop is read as JSON lines from the last real prompt forward, which is the measured
    fix for two ways of being wrong: a text match on the tail says "out of quota" about any
    session that merely discussed one, and a byte window of a listing's size misses the
    limit lines of the incident this was written for by ~120 KiB.
    """

    def setUp(self):
        super().setUp()
        self.mod.MACHINE = "here"
        self.mod.SHARED_HOME = self.root / "home" / ".claude"
        self.mod.RC_JOBS_DIR = None
        # 🛑 Never the machine's own `lsof`: a fixture world holds no Remote Control server,
        # and the question is about the process table this test does not own.
        self.mod.LSOF_BIN = str(self.root / "no-such-lsof")
        self.a = self.account("work")
        self.cwd = str(self.root / "work")
        os.makedirs(self.cwd, exist_ok=True)

    def test_the_proved_row_is_found_whichever_of_two_rows_for_the_id_sorts_last(self):
        """🛑 `live_name` reads EVERY registry row for the id. Two rows for one id is the
        state right after a resume: a stale file whose pid was reused, and the new process.
        Which one `live_rows` kept depended on the pids compared as text, so on one CI
        runner the stale row masked the real one and the note went to nobody (Wed 28 Oct
        2026). The roles are swapped halfway, so either file sorting last is covered."""
        reg = self.a.home / "sessions"
        reg.mkdir(exist_ok=True)
        one, two = self.claude_proc(), self.claude_proc()
        t = self.sess(self.go(), self.clean())

        def rows(real, stale):
            (reg / ("%d.json" % real.pid)).write_text(json.dumps(
                {"pid": real.pid, "sessionId": SID_A, "name": "the-real-one",
                 "procStart": ps_start(real.pid)}))
            (reg / ("%d.json" % stale.pid)).write_text(json.dumps(
                {"pid": stale.pid, "sessionId": SID_A, "name": "a-stale-row",
                 "procStart": "Mon Jan  1 00:00:00 2024"}))
            return self.mod.live_name(self.a, SID_A, t.transcript).get("name")

        self.assertEqual(rows(one, two), "the-real-one")
        self.assertEqual(rows(two, one), "the-real-one")

    # --- fixtures ---------------------------------------------------------
    def sess(self, *lines, **kw):
        return self.session(self.a, lines=list(lines) or None, **kw)

    def go(self, text="run the campaign"):
        return user(text, self.cwd, SID_A, uuid="u1")

    def clean(self, text="done", uuid="a1", parent="u1"):
        return assistant(text, self.cwd, SID_A, uuid=uuid, parent=parent)

    def limit(self, resets=None, shape="apiError", kind="five_hour",
              text="You've hit your session limit · resets 6:30pm (America/Los_Angeles)"):
        return assistant(text, self.cwd, SID_A, error="usage_limit_reached", resets=resets,
                         kind=kind, shape=shape, uuid="a2", parent="a1")

    def stop_of(self, *lines, **kw):
        return self.mod.revive_stop(self.sess(*lines, **kw).transcript)

    def claude_with(self, *tail):
        """A real process whose argv[0] basename is `claude` and whose argv carries `tail`.

        ⚠️ `sleep N; exit 0`, not `sleep N`: a shell handed ONE simple command execs it and
        loses its own argv, so the flags this exists for would vanish from `ps`.
        """
        d = self.root / ("shbin%d" % len(self.procs))
        d.mkdir(exist_ok=True)
        exe = d / "claude"
        shutil.copy("/bin/sh", str(exe))
        p = subprocess.Popen([str(exe), "-c", "sleep 120; exit 0"] + list(tail),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(p)
        return p

    def fake_lsof(self, mapping, rc=0):
        p = self.root / "lsof"
        p.write_text(FAKE_LSOF.replace("@PY@", PY))
        p.chmod(0o755)
        mp = self.root / "lsof-map.json"
        mp.write_text(json.dumps({str(k): v for k, v in mapping.items()}))
        os.environ["FAKE_LSOF_MAP"], os.environ["FAKE_LSOF_RC"] = str(mp), str(rc)
        self.addCleanup(os.environ.pop, "FAKE_LSOF_MAP", None)
        self.addCleanup(os.environ.pop, "FAKE_LSOF_RC", None)
        self.mod.LSOF_BIN = str(p)

    # --- the stop ---------------------------------------------------------
    def test_a_usage_limit_in_force_names_its_class_its_window_and_its_reset(self):
        future = time.time() + 3600
        st = self.stop_of(self.go(), self.clean(), self.limit(resets=future))
        self.assertEqual(st["stop"], "usage-limit")
        self.assertEqual((st["class"], st["window"]), ("session", "five_hour"))
        self.assertTrue(st["in_force"])
        self.assertIs(st["clears_with_time"], True)
        self.assertAlmostEqual(st["resets_at"], future, delta=1)
        self.assertIn("session limit", st["why"])

    def test_the_same_stop_with_the_reset_passed_is_no_longer_in_force(self):
        st = self.stop_of(self.go(), self.limit(resets=time.time() - 7200))
        self.assertEqual(st["stop"], "usage-limit")
        self.assertFalse(st["in_force"])
        self.assertIn("that reset has passed", st["why"])

    def test_the_no_apiError_shape_is_read_as_the_same_stop(self):
        """M2's second shape, and a quarter of the real stops on this machine."""
        st = self.stop_of(self.go(), self.limit(resets=time.time() + 60, shape="rate_limit",
                                                kind="seven_day",
                                                text="You've hit your weekly limit"))
        self.assertEqual((st["stop"], st["kind"]), ("usage-limit", "rate_limit"))
        self.assertEqual((st["class"], st["window"]), ("weekly", "seven_day"))

    def test_the_class_says_whether_waiting_is_the_cure_at_all(self):
        """🛑 The whole reason the class is read: a session or weekly limit lifts at its
        reset, and a spend cap, a credit balance or a model limit does not — so "wait until
        6:30" is advice that costs the wait and then another failed turn."""
        cases = {"You've hit your monthly spend limit · raise it at claude.ai":
                 ("monthly-spend", False),
                 "You've hit your weekly limit · resets 10pm": ("weekly", True),
                 "You've hit your session limit · resets 6:30pm": ("session", True),
                 "You're out of usage credits. Run /usage-credits": ("credits", False),
                 "You've reached your Fable limit. Switch to another model":
                 ("model", False)}
        for text, (klass, clears) in cases.items():
            self.assertEqual(self.mod.limit_class(text), (klass, clears), text)
            st = self.stop_of(self.go(), self.limit(resets=time.time() - 60, text=text))
            self.assertEqual((st["class"], st["clears_with_time"]), (klass, clears), text)

    def test_a_limit_the_turn_recovered_from_is_not_why_it_stopped(self):
        """2.1.312 auto-continues at a usage limit when the session is interactive, so a
        limit with a clean answer after it is history, not the stop."""
        st = self.stop_of(self.go(), self.limit(resets=time.time() - 7200),
                          self.clean("answering again", uuid="a3", parent="a2"))
        self.assertEqual(st["stop"], "finished")

    def test_an_error_that_is_not_a_limit_is_its_own_class(self):
        line = assistant("overloaded", self.cwd, SID_A, uuid="a2", parent="a1")
        line["apiError"] = "overloaded_error"
        st = self.stop_of(self.go(), line)
        self.assertEqual((st["stop"], st["kind"]), ("api-error", "overloaded_error"))
        self.assertIn("not a limit", st["why"])

    def nores(self, uuid="a9", parent="a2"):
        """The `isMeta` prompt and the `<synthetic>` line that records it getting nothing —
        the real pair, in the real order (`assistant`'s own 🛑 has the measurement)."""
        meta = user("Continue from where you left off.", self.cwd, SID_A, uuid="u9",
                    parent=parent)
        meta["isMeta"] = True
        return [meta, assistant("No response requested.", self.cwd, SID_A, synthetic=True,
                                uuid=uuid, parent="u9")]

    def test_a_no_response_requested_line_does_not_wait_out_a_limit(self):
        """🛑 THE ONE LINE THAT RECORDS A NON-ANSWER, counted as the answer.

        `revive_stop`'s clean-line branch exists because 2.1.312 auto-continues at a limit
        and answers anyway — but a `<synthetic>` "No response requested." line is the CLI
        recording that an injected prompt produced NOTHING. Counting it read a waited-out
        limit as `finished`, losing `class`, `window` and `resets_at`, and the note then told
        the revived session it "had answered and was sitting idle".
        """
        past = time.time() - 3600
        st = self.stop_of(self.go(), self.limit(resets=past), *self.nores())
        self.assertEqual(st["stop"], "usage-limit")
        self.assertEqual(st["class"], "session")
        self.assertEqual(st["window"], "five_hour")
        self.assertAlmostEqual(st["resets_at"], past, delta=1)
        self.assertIn("that reset has passed", st["why"])
        # a line that IS the session answering still ends the limit, as before
        self.assertEqual(self.stop_of(self.go(), self.limit(resets=past),
                                      self.clean("answering again", uuid="a3",
                                                 parent="a2"))["stop"], "finished")

    def test_a_no_response_requested_line_does_not_hide_a_mid_turn_kill(self):
        """And `pending` is taken from the last assistant line, so the same line stole the
        tool name out of the one sentence M4 makes mandatory."""
        st = self.stop_of(self.go(),
                          tool_call(self.cwd, SID_A, name="Bash",
                                    stamp="2026-10-28T09:33:07.000Z"),
                          *self.nores(parent="a9"))
        self.assertEqual((st["stop"], st["tool"]), ("mid-turn", "Bash"))
        self.assertIn("UNKNOWN", st["why"])

    def test_an_isApiErrorMessage_that_is_not_a_limit_is_not_an_answer_either(self):
        """The other half of the no-`apiError` family. `scan_transcript` read it as the
        session answering again — the branch's own comment says the opposite — so `csm list`
        said `out_of_quota: false` about a session `csm revive` called `usage-limit`."""
        past = time.time() - 3600
        over = assistant("overloaded", self.cwd, SID_A, uuid="a3", parent="a2",
                         api_error_only="api_error_overloaded")
        t = self.sess(self.go(), self.limit(resets=past, shape="rate_limit"), over)
        self.assertEqual(self.mod.revive_stop(t.transcript)["stop"], "usage-limit")
        self.assertTrue(self.mod.scan_transcript(t.transcript)["quota"],
                        "the two readers must agree about one file")
        # and the listing's own reader agrees about the synthetic line too
        t2 = self.sess(self.go(), self.limit(resets=past, shape="rate_limit"),
                       *self.nores())
        self.assertTrue(self.mod.scan_transcript(t2.transcript)["quota"])

    def test_a_mid_turn_kill_names_the_tool_whose_result_never_came(self):
        """🛑 The one stop where "do not repeat work that is already done" is dangerous
        advice: the tool call may have fully applied, partly applied or not run."""
        st = self.stop_of(self.go(), tool_call(self.cwd, SID_A, name="Edit",
                                               stamp="2026-10-28T09:33:07.000Z"))
        self.assertEqual((st["stop"], st["tool"]), ("mid-turn", "Edit"))
        self.assertIn("UNKNOWN", st["why"])
        self.assertTrue(st["tool_at"] > 0)

    def test_an_answered_tool_call_is_not_mid_turn(self):
        st = self.stop_of(self.go(), tool_call(self.cwd, SID_A),
                          tool_answer(self.cwd, SID_A),
                          self.clean("and here is the answer", uuid="a8", parent="u9"))
        self.assertEqual(st["stop"], "finished")

    def test_archived_is_a_4090_AFTER_the_last_remote_control_report(self):
        st = self.stop_of(self.go(), self.clean(), STATUS_LINE, ENDED_LINE)
        self.assertEqual(st["stop"], "archived")
        self.assertIs(st["archived"], True)
        # the other order is a disconnect it recovered from, and says nothing
        st = self.stop_of(self.go(), self.clean(), ENDED_LINE, STATUS_LINE)
        self.assertEqual(st["stop"], "finished")
        self.assertIs(st["archived"], False)

    def test_a_clean_last_line_is_a_finish(self):
        st = self.stop_of(self.go(), self.clean())
        self.assertEqual(st["stop"], "finished")
        self.assertIn("answered and stopped", st["why"])

    def test_a_zero_byte_and_a_title_only_transcript_are_both_empty(self):
        t = self.sess(self.go()).transcript
        t.write_text("")
        self.assertEqual(self.mod.revive_stop(t)["stop"], "empty")
        t.write_text(jl({"type": "custom-title", "customTitle": "t"}))
        st = self.mod.revive_stop(t)
        self.assertEqual(st["stop"], "empty")
        self.assertIn("nothing to continue", st["why"])

    def stamped_go(self, stamp="2026-10-29T01:12:03.000Z"):
        """The last real prompt, with a timestamp: for this stop the PROMPT is the event."""
        d = self.go()
        d["timestamp"] = stamp
        return d

    def test_an_unanswered_PROMPT_is_a_mid_turn_kill_and_names_itself(self):
        """🛑 THE SHAPE A KILL IN THE FIRST SECONDS OF A TURN LEAVES (Thu 29 Oct 2026, wk 44).

        Measured that day on a throwaway session SIGKILLed 1.5 s after Enter, CLI 2.1.312:
        the file ends on the user's line plus the `total_tokens_reminder` attachment, and
        there is no assistant line after it at all. Only an unanswered `tool_use` counted as
        `mid-turn` until then, so this read `unknown` with `uuid: ""` — a stop no wake rule
        covered and no at-most-once key could name, in the one case (a machine restart under
        a session between turns) the unattended wake exists for.
        """
        go = self.stamped_go()
        st = self.stop_of(go, tokens_reminder(self.cwd, SID_A))
        self.assertEqual(st["stop"], "mid-turn")
        self.assertIn("the last prompt has no answer of any kind", st["why"])
        self.assertIn("killed before it said anything", st["why"])
        # 🛑 THE PROMPT LINE IS THE STOP EVENT: its uuid is the at-most-once key, and its
        # stamp is when the work stopped — not the file's mtime, which a later touch moves.
        self.assertEqual(st["uuid"], "u1")
        self.assertEqual(st["at"], self.mod._stamp(go))
        self.assertTrue(st["from_prompt"])
        # ⚠️ AND NO TOOL, which is what tells the two mid-turn shapes apart downstream:
        # there is no call whose result might be missing, because nothing ran.
        self.assertEqual((st["tool"], st["tool_at"]), ("", 0.0))

    def test_the_prompt_alone_is_the_same_verdict_as_the_prompt_and_its_attachment(self):
        """The attachment is 2.1.312's; a build that writes none, or a kill between the two
        writes, leaves the prompt as the whole file — one stop, read the same way."""
        for tail in ([], [tokens_reminder(self.cwd, SID_A)]):
            st = self.stop_of(self.stamped_go(), *tail)
            self.assertEqual((st["stop"], st["uuid"]), ("mid-turn", "u1"), tail)

    def test_a_tail_with_no_prompt_in_it_reports_no_stop_of_its_own(self):
        """🛑 `from_prompt` IS THE GUARD. A window that holds tool results and nothing else
        never saw the prompt it belongs to, so it must not report that prompt's turn as cut
        off: `revive_stop` reads a bounded tail, and the one honest answer there is
        `unknown` (which the sweep's prefilter treats as "read this file properly")."""
        st = self.stop_of(tool_answer(self.cwd, SID_A))
        self.assertEqual((st["stop"], st["from_prompt"]), ("unknown", False))

    def test_a_line_the_session_wrote_ITSELF_is_never_an_unanswered_prompt(self):
        """🛑 ANY assistant line blocks this verdict, including the one that records a
        NON-answer. `<synthetic>` "No response requested." is not the session answering —
        `answered_here` refuses to count it — but it IS a line written after the prompt, so
        reading its absence as "nothing was written" would call a stop mid-turn on the
        strength of a line that is right there in the file."""
        st = self.stop_of(self.stamped_go(),
                          assistant("No response requested.", self.cwd, SID_A,
                                    synthetic=True, uuid="a9", parent="u1"))
        self.assertEqual(st["stop"], "unknown")
        # and a real answer is a finish, exactly as before
        self.assertEqual(self.stop_of(self.stamped_go(), self.clean())["stop"], "finished")

    def test_an_archive_outranks_an_unanswered_prompt(self):
        """A prompt typed into a session somebody then closed from the app was a DECISION,
        not a failure to repair — and `stalled_due` refuses every archived row anyway."""
        st = self.stop_of(self.stamped_go(), STATUS_LINE, ENDED_LINE)
        self.assertEqual(st["stop"], "archived")
        self.assertIs(st["archived"], True)

    def test_a_subagents_turn_is_not_an_answer_to_his_prompt(self):
        """`isSidechain` lines are skipped everywhere else in this reader for the same
        reason: a subagent's turn is not the session's own."""
        side = assistant("working on it", self.cwd, SID_A, uuid="s1", parent="u1")
        side["isSidechain"] = True
        st = self.stop_of(self.stamped_go(), side)
        self.assertEqual((st["stop"], st["uuid"]), ("mid-turn", "u1"))

    def test_a_session_COMPACTED_WHILE_IDLE_answered_everything_and_is_not_mid_turn(self):
        """🛑 THE SHAPE THAT MADE THE UNANSWERED-PROMPT VERDICT CALL IDLE SESSIONS DEAD
        MID-WORK (fixed Thu 29 Oct 2026, week 44, the day the verdict was added).

        The CLI compacts a session that is SITTING IDLE to keep its prompt cache warm, and
        the file then ends on the `compact_boundary` system line, the `isCompactSummary`
        user line and a run of attachments, with NO assistant line after it — because the
        session was idle, having answered everything. Measured over all 1,958 transcripts in
        the config homes on this machine that day: 132 end in that shape, and every one of
        them read `mid-turn`, "killed before it said anything", about a session that had
        finished. For a dead Remote Control child that verdict is DUE, and the action is a
        FORK plus archiving the claude.ai link it already had.

        The summary is not a prompt, so the window skips it exactly as it skips `isMeta`,
        and the real prompt's answer is right there: `finished`.
        """
        st = self.stop_of(self.stamped_go(), self.clean(), *idle_compaction(self.cwd, SID_A))
        self.assertEqual(st["stop"], "finished")
        self.assertEqual(st["uuid"], "a1", "the answer it gave is the event, not the summary")

    def test_a_compaction_summary_never_opens_the_window_over_the_limit_it_followed(self):
        """🛑 AND THAT IS WHY THE FIX IS AT THE WINDOW, NOT IN THE VERDICT. A session parked
        on a usage limit is idle, so it is a candidate for idle compaction too — and a window
        that opened at the summary would hold neither the limit line nor the prompt it
        belongs to. The stop would read `mid-turn` instead of `usage-limit`, which
        `stalled_due` calls due NOW rather than at the reset: the one thing the brief's first
        safety rule forbids (`Never wake before the reset`)."""
        resets = time.time() + 3600
        st = self.stop_of(self.stamped_go(), self.limit(resets=resets),
                          *idle_compaction(self.cwd, SID_A, parent="a2"))
        self.assertEqual(st["stop"], "usage-limit")
        self.assertIs(st["in_force"], True)
        self.assertAlmostEqual(st["resets_at"], resets, places=0)

    def test_a_compaction_the_session_then_ANSWERED_is_still_a_finish(self):
        """The ordinary compaction: it happens mid-turn, the session keeps going and answers.
        Skipping the summary must not lose that answer — the window opens at the prompt
        before the compaction and the answer after it is in the same window."""
        st = self.stop_of(self.stamped_go(), *idle_compaction(self.cwd, SID_A))
        self.assertEqual(st["stop"], "mid-turn", "nothing answered that prompt, before or after")
        st2 = self.stop_of(self.stamped_go(), *idle_compaction(self.cwd, SID_A),
                           self.clean(uuid="a7", parent="c9"))
        self.assertEqual((st2["stop"], st2["uuid"]), ("finished", "a7"))

    def test_the_window_opens_at_the_last_REAL_prompt(self):
        """A `tool_result` and an `isMeta` line are both `type: "user"` and neither is a
        prompt: a window that started at one of them would begin in the middle of the turn
        it is trying to explain, and a limit from the turn BEFORE the last prompt was
        waited out."""
        meta = user("<system-reminder>a note</system-reminder>", self.cwd, SID_A,
                    uuid="um", parent="a2")
        meta["isMeta"] = True
        st = self.stop_of(self.go(), self.limit(resets=time.time() - 7200), meta,
                          tool_answer(self.cwd, SID_A, uuid="ur", parent="um"))
        self.assertTrue(st["from_prompt"])
        self.assertEqual(st["stop"], "usage-limit", "neither line opened a new window")
        later = user("now do the next thing", self.cwd, SID_A, uuid="u2", parent="a2")
        st = self.stop_of(self.go(), self.limit(resets=time.time() - 7200), later,
                          self.clean("on it", uuid="a4", parent="u2"))
        self.assertEqual(st["stop"], "finished", "the limit is before the last prompt")

    def test_revive_reads_further_back_than_a_listing_row_does(self):
        """🛑 THE MEASURED FACT this window exists for. On the incident transcript
        (CLI 2.1.312, Wed 28 Oct 2026) `usage_limit_reached` and `quotaLimits` are in the
        last 512 KiB and NOT in the last 384 KiB, so `scan_transcript`'s window reports a
        clean finish for a session that is sitting on a wall.
        """
        pad = dict(assistant("x" * 2000, self.cwd, SID_A))
        pad["isSidechain"] = True            # a subagent's own lines: not the conversation
        lines = [self.go(), self.limit(resets=time.time() + 3600)] + [pad] * 260
        s = self.sess(*lines)
        self.assertGreater(s.transcript.stat().st_size, 512 * 1024)
        self.mod.TAIL_BYTES = 384 * 1024
        self.assertEqual(self.mod.scan_transcript(s.transcript)["quota"], {},
                         "the listing window is too narrow to see it, which is the bug")
        st = self.mod.revive_stop(s.transcript)
        self.assertEqual(st["stop"], "usage-limit")
        self.assertGreater(st["read_bytes"], 512 * 1024)

    def test_the_window_is_a_knob_and_the_record_says_what_it_read(self):
        """`--json` carries `read_bytes`, so a diagnosis made here and one made over ssh
        (whose helper reads its own window) can be told apart rather than compared."""
        s = self.sess(self.go(), self.clean())
        st = self.mod.revive_stop(s.transcript, tail=64)
        self.assertLessEqual(st["read_bytes"], 64)
        self.assertEqual(self.mod.revive_stop(s.transcript)["read_bytes"],
                         s.transcript.stat().st_size)

    # --- what kind of session -------------------------------------------
    def test_a_server_child_is_proved_by_the_derivation_and_never_by_entrypoint(self):
        """🛑 `entrypoint` looks like the answer and is not: it says HOW the process was
        started (`sdk-cli` is `--print`) and a fork or a resume rewrites it. The local id
        being uuid5 of the bridge session's api url cannot be rewritten."""
        s = self.session(self.a, sid=LINK_SID, lines=[user("go", self.cwd, LINK_SID)])
        k = self.mod.revive_kind(s, LINK_BARE)
        self.assertEqual((k["kind"], k["bridge_id"], k["from"]),
                         ("server-child", LINK_BARE, "the link"))
        self.assertIn("uuid5", k["why"])
        s.entrypoint = "cli"                 # the registry disagreeing changes nothing
        self.assertEqual(self.mod.revive_kind(s, LINK_BARE)["kind"], "server-child")
        # and a v4 session whose registry row says `sdk-cli` is NOT one
        t = self.session(self.a, sid=SID_A)
        t.entrypoint = "sdk-cli"
        self.assertEqual(self.mod.revive_kind(t)["kind"], "terminal")

    def test_a_server_childs_own_registry_row_proves_it_too(self):
        s = self.session(self.a, sid=LINK_SID, lines=[user("go", self.cwd, LINK_SID)])
        s.bridge_id = LINK_BARE
        self.assertEqual(self.mod.revive_kind(s)["from"], "its registry row")

    def test_an_orphan_bridge_spawn_directory_proves_it_with_nothing_running(self):
        """The pid-free death index: the bridge deletes that directory only on a handled
        exit, so a killed child leaves one naming the claude.ai session of a transcript
        that names none itself."""
        d = self.mod.SHARED_HOME / "bridge-spawn" / ("cse_" + LINK_BARE + "-mZBVxD")
        d.mkdir(parents=True)
        (d / "append-system-prompt.txt").write_text("x")
        s = self.session(self.a, sid=LINK_SID, lines=[user("go", self.cwd, LINK_SID)])
        k = self.mod.revive_kind(s)
        self.assertEqual((k["kind"], k["from"]),
                         ("server-child", "an orphan bridge-spawn dir"))
        self.assertEqual(self.mod.bridge_spawn_bare(SID_A), "", "another id, no claim")

    def test_a_session_that_asked_for_remote_control_itself_is_self_hosted(self):
        s = self.session(self.a, lines=[self.go(), BRIDGE_LINE])
        k = self.mod.revive_kind(s)
        self.assertEqual((k["kind"], k["bridge_id"]),
                         ("self-hosted", "01SelfHosted00001"))
        self.assertIn("re-attaches", k["why"])
        s2 = self.session(self.a, sid=SID_B, lines=[user("go", self.cwd, SID_B),
                                                    STATUS_LINE])
        self.assertEqual(self.mod.revive_kind(s2)["kind"], "self-hosted")

    def test_with_no_claude_ai_session_anywhere_it_is_a_terminal_session(self):
        k = self.mod.revive_kind(self.session(self.a))
        self.assertEqual((k["kind"], k["bridge_id"]), ("terminal", ""))

    def test_a_version_5_id_is_a_server_child_even_with_no_source_of_its_link(self):
        """🛑 THE ONE CASE THAT USED TO READ AS `terminal`, and `terminal` is decide row 8 —
        `--resume <old id>` with no `--fork-session`, a second process on the old local id.

        A DEAD server child named by its own id or by part of its title has none of the four
        sources `revive_kind` can prove a bridge id from: no registry row, no bridge line in
        its own transcript (measured: 2 of 861 v5 transcripts here carry one), and no
        `bridge-spawn` dir once it exited cleanly. The id's own uuid VERSION needs none of
        them.
        """
        s = self.session(self.a, sid=FORK_SID, lines=[user("go", self.cwd, FORK_SID)])
        k = self.mod.revive_kind(s)
        self.assertEqual(k["kind"], "server-child")
        self.assertEqual(k["bridge_id"], "", "nothing here proved WHICH session")
        self.assertIn("version-5", k["why"])
        self.assertIn("link is unknown", k["why"])
        # and it is the VERSION that does it, not the absence of evidence: a v4 id with the
        # same empty surroundings is still a terminal session
        self.assertEqual(self.mod.revive_kind(self.session(self.a, sid=SID_A))["kind"],
                         "terminal")
        self.assertEqual(self.mod.uuid_version(FORK_SID), 5)
        self.assertEqual(self.mod.uuid_version(SID_A), 4)
        self.assertIsNone(self.mod.uuid_version("not-a-uuid"))

    def test_a_version_5_id_with_a_source_still_names_its_link(self):
        """The new rung is a FALL-THROUGH, below every source: when one of them answers, the
        bridge id and the `from` are still that source's, so the link is still printed."""
        s = self.session(self.a, sid=LINK_SID, lines=[user("go", self.cwd, LINK_SID)])
        k = self.mod.revive_kind(s, LINK_BARE)
        self.assertEqual((k["kind"], k["bridge_id"], k["from"]),
                         ("server-child", LINK_BARE, "the link"))

    def test_the_desktop_apps_own_session_is_told_apart(self):
        s = self.session(self.a)
        s.desktop = {"sessionId": "local_1", "title": "from the app"}
        self.assertEqual(self.mod.revive_kind(s)["kind"], "desktop")

    # --- is it running --------------------------------------------------
    def test_no_registry_row_reads_as_dead_and_says_why(self):
        st = self.mod.revive_state(self.session(self.a))
        self.assertEqual(st["state"], "dead")
        self.assertIn("no config home here has a registry row", st["why"])
        self.assertTrue(st["ps_asked"], "ps was asked, and answered")

    def test_a_proved_pid_is_live_and_busy_or_idle_by_its_own_row(self):
        p = self.claude_proc()
        s = self.session(self.a)
        s.pid, s.proc_start = p.pid, ps_start(p.pid)
        s.status = "idle"
        self.assertEqual(self.mod.revive_state(s)["state"], "live-idle")
        s.status = "busy"
        got = self.mod.revive_state(s)
        self.assertEqual(got["state"], "live-busy")
        self.assertIs(got["proved"], True)

    def test_an_unprovable_row_reads_as_DEAD_and_keeps_the_reason(self):
        """🛑 The dangerous direction is the other one. A registry file outlives its
        process and pids are reused, so an unproved row must never read as alive — a revive
        that believes a dead session is working does nothing at all."""
        p = self.claude_proc()
        s = self.session(self.a)
        s.pid, s.status = p.pid, "idle"
        s.proc_start = "Thu Jan  1 00:00:00 2026"
        st = self.mod.revive_state(s)
        self.assertEqual(st["state"], "dead")
        self.assertIs(st["proved"], False)
        self.assertIn("has been reused", st["why"])

    def test_the_machine_wide_sweep_finds_a_child_by_its_cse_id(self):
        """A server child's argv carries `cse_<bare>` and never the local uuid, and its
        registry file can be missing or stale — measured: a row survives a SIGKILL until
        some live session sweeps the directory."""
        p = self.claude_with("--session-id", "cse_" + LINK_BARE)
        s = self.session(self.a, sid=LINK_SID, lines=[user("go", self.cwd, LINK_SID)])
        s.bridge_id = LINK_BARE
        st = self.mod.revive_state(s)
        self.assertEqual(st["state"], "dead", "no registry row: nothing proves it")
        self.assertIn(p.pid, [r["pid"] for r in st["ps"]])
        self.assertIn("name it", st["why"])

    def test_the_sweep_uses_the_bridge_id_the_LINK_proved(self):
        """⚠️ For a dead server child the bare id is in no file csm read — it comes from
        the link. Sweeping for `s.bridge_id` alone would look for a name nothing carries,
        in exactly the case the sweep exists for."""
        p = self.claude_with("--session-id", "cse_" + LINK_BARE)
        s = self.session(self.a, sid=LINK_SID, lines=[user("go", self.cwd, LINK_SID)])
        self.assertEqual(s.bridge_id, "")
        self.assertEqual(self.mod.revive_state(s)["ps"], [])
        self.assertIn(p.pid, [r["pid"]
                              for r in self.mod.revive_state(s, LINK_BARE)["ps"]])
        sp = self.mod.resolve_spec(link_of(LINK_BARE), [self.a])
        rec = self.mod.diagnose(s, [self.a], sp)
        self.assertIn(p.pid, [r["pid"] for r in rec["state"]["ps"]])

    def test_the_sweep_also_matches_a_resume_of_the_local_id(self):
        p = self.claude_with("--resume=" + SID_A)
        st = self.mod.revive_state(self.session(self.a))
        self.assertIn(p.pid, [r["pid"] for r in st["ps"]])

    def test_a_bridge_id_only_MENTIONED_is_a_decoy_and_not_a_running_session(self):
        """🛑 AFTER A FLAG, NOT ANYWHERE IN THE LINE. This arm was a plain substring, so any
        process running as `claude` whose argv merely mentioned the id read as "something is
        running this session NOW" — which `revive_start` turns into a hard refusal. The remote
        helper's `detail()` has required the flag from the start, and the test that pins it
        (`RemoteHelper`) calls the other shape a decoy; this is the same rule on this side.
        """
        # ⚠️ FORK_BARE, never LINK_BARE: the measured pair names a REAL session on the machine
        # this was written on, and the sweep reads the real process table — so a test about
        # what the sweep does NOT match has to name a bridge session nothing ever ran.
        decoy = self.claude_with("/logs/cse_" + FORK_BARE + "/notes.txt")
        s = self.session(self.a, sid=FORK_SID, lines=[user("go", self.cwd, FORK_SID)])
        self.assertEqual(self.mod.revive_state(s, FORK_BARE)["ps"], [],
                         "a mention is not a flag")
        del decoy
        for flag in ("--session-id", "--resume", "--sdk-url"):
            p = self.claude_with(flag,
                                 "https://api.anthropic.com/v1/code/sessions/cse_"
                                 + FORK_BARE)
            self.assertIn(p.pid, [r["pid"]
                                  for r in self.mod.revive_state(s, FORK_BARE)["ps"]], flag)

    def test_a_FORK_reading_this_transcript_is_not_a_second_writer_of_it(self):
        """🛑 `revive_fork`'s own measured fact: a fork writes exactly `<new>.jsonl` and leaves
        the transcript it read byte-identical (2.1.312, Wed 28 Oct 2026). But `--resume <old
        id>` stays in that window's argv for its whole life, so `own` matched it and a second
        `csm revive <old> --new-link` was refused with "two CLIs appending to one transcript
        cannot be untangled" — about a process that never writes this file at all.
        """
        new = "9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f"
        fork = self.claude_with("--fork-session", "--session-id", new, "--resume", SID_A)
        s = self.session(self.a)
        self.assertEqual(self.mod.revive_state(s)["ps"], [], "a fork READ it, it never wrote")
        del fork
        # and a plain resume of the same id still is a writer, which is what the sweep is for
        p = self.claude_with("--resume", SID_A)
        self.assertIn(p.pid, [r["pid"] for r in self.mod.revive_state(s)["ps"]])

    # --- the work it lost ------------------------------------------------
    def wf(self, s, name="wf_d4fd7f6a-04f.json", body=None):
        d = s.sibling / "workflows"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(body if isinstance(body, str) else json.dumps(body))
        return d / name

    def test_the_errored_agents_are_counted_and_the_top_level_status_is_not_read(self):
        """🛑 Measured on the incident (753,955 B, Wed 28 Oct 2026): five agents carry
        `state: "error"` with "You've hit your session limit", and the file's own
        `status` reads `completed`. Whoever reinstates the top level reports the run as
        finished at exactly the moment it should report the opposite."""
        s = self.session(self.a)
        self.wf(s, body={"status": "completed", "workflowProgress": [
            {"index": 0, "title": "phase 1", "type": "phase"},
            {"state": "error", "label": "a2-e73-camera"},
            {"state": "error", "label": "verify:a3-e71-leak"},
            {"state": "completed", "label": "a1-fine"}]})
        got = self.mod.revive_lost_work(s)
        self.assertEqual(got["errors"], 2)
        self.assertEqual(got["labels"], ["a2-e73-camera", "verify:a3-e71-leak"])
        self.assertEqual(got["files"], ["wf_d4fd7f6a-04f.json"])

    def test_no_sibling_directory_is_no_lost_work_and_no_crash(self):
        self.assertEqual(self.mod.revive_lost_work(self.session(self.a))["errors"], 0)

    def test_a_workflow_file_that_will_not_parse_is_unread_and_not_a_zero(self):
        s = self.session(self.a)
        self.wf(s, name="wf_half.json", body="{ not json")
        got = self.mod.revive_lost_work(s)
        self.assertEqual((got["errors"], got["unread"]), (0, ["wf_half.json"]))

    # --- the account, the server, the owner ------------------------------
    def test_the_account_verdict_is_check_home_usable_caught_not_raised(self):
        s = self.session(self.a)
        got = self.mod.revive_account(s, [self.a])
        self.assertIs(got["usable"], True)
        self.assertEqual(got["meter"], "unread")
        self.assertIn("unread", got["meter_text"])
        gone = self.account("signedout", email=None)
        s2 = self.session(gone, sid=SID_B)
        got = self.mod.revive_account(s2, [gone])
        self.assertIs(got["usable"], False)
        self.assertIn("holds no login", got["why"])

    def test_a_stale_reading_is_stale_and_the_seven_day_reset_is_kept_apart(self):
        """🛑 The 5-hour instant NEVER comes from the meter: the `resets_at` a reading
        carries is the SEVEN-DAY window's, and reading it as "when the limit lifts" is
        wrong by hours. The transcript's own `quotaLimits.resetsAt` is the 5-hour one."""
        self.mod.METERS_FILE.write_text(json.dumps(
            {"work": {"at": time.time() - 9 * 3600, "five_hour": 3.0, "seven_day": 44.0,
                      "resets_at": "2026-11-01T00:00:00Z", "error": ""}}))
        got = self.mod.revive_account(self.session(self.a), [self.a])
        self.assertEqual(got["meter"], "stale")
        self.assertEqual(got["seven_day_resets_at"], "2026-11-01T00:00:00Z")
        self.assertEqual((got["five_hour"], got["seven_day"]), (3.0, 44.0))

    def fake_ps(self, table):
        """🛑 The server question is about the MACHINE's process table, which no fixture
        owns: this box runs 28 real `claude remote-control` servers right now, so a test
        reading the real one asserts about whatever happens to be up. The table is faked
        here and nowhere else — the argv sweep in `revive_state` is tested against the real
        `ps` and real processes, which is where that matters."""
        self.mod.ps_table = lambda: table

    def test_a_server_in_this_folder_is_found_and_one_elsewhere_is_not(self):
        exe = str(self.root / "procbin" / "claude")
        self.fake_ps({4242: exe + " remote-control --name myproject --spawn=same-dir"})
        self.fake_lsof({4242: self.cwd})
        got = self.mod.server_in_folder(self.cwd)
        self.assertIs(got["up"], True)
        self.assertEqual(got["pids"], [4242])
        self.assertIn("myproject", got["names"])
        self.fake_lsof({4242: str(self.root / "elsewhere")})
        got = self.mod.server_in_folder(self.cwd)
        self.assertIs(got["up"], False)
        self.assertIn("none of them in this folder", got["why"])

    def test_a_session_that_merely_carries_the_FLAG_is_not_a_server(self):
        """`--remote-control=<name>` is a SESSION asking for Remote Control; the server is
        the bare subcommand. Counting the flag would report a server in every folder a
        moved window is open in."""
        exe = str(self.root / "procbin" / "claude")
        self.fake_ps({4242: exe + " --remote-control=Sleep --permission-mode bypass"})
        self.fake_lsof({4242: self.cwd})
        got = self.mod.server_in_folder(self.cwd)
        self.assertIs(got["up"], False)
        self.assertIn("at all", got["why"])

    def test_nothing_but_the_claude_cli_counts(self):
        """`RC_SERVER_RE` finds the words anywhere on the line, so argv[0] is checked on
        top of it: otherwise `vim /x/claude remote-control` is a server."""
        self.fake_ps({4242: "vim /x/claude remote-control --name room"})
        self.fake_lsof({4242: self.cwd})
        self.assertTrue(self.mod.RC_SERVER_RE.search("vim /x/claude remote-control"))
        self.assertIs(self.mod.server_in_folder(self.cwd)["up"], False)

    def test_an_lsof_that_cannot_be_asked_is_unread_and_never_a_no(self):
        """The doctrine of the whole file: "could not look" is not a verdict. Here it
        decides whether anybody is told that opening the link brings the session back."""
        exe = str(self.root / "procbin" / "claude")
        self.fake_ps({4242: exe + " remote-control --name myproject"})
        self.fake_lsof({}, rc=9)
        got = self.mod.server_in_folder(self.cwd)
        self.assertIsNone(got["up"])
        self.assertIn("could not be asked", got["why"])
        # and a candidate that named no folder leaves the question open too
        self.fake_lsof({})
        got = self.mod.server_in_folder(self.cwd)
        self.assertIsNone(got["up"])
        self.assertIn("named no folder", got["why"])

    def test_a_ps_that_cannot_be_asked_is_unread_too(self):
        self.mod.ps_table = lambda: None
        got = self.mod.server_in_folder(self.cwd)
        self.assertIsNone(got["up"])
        self.assertIn("ps could not be asked", got["why"])

    def test_a_session_with_no_folder_is_not_a_server_question(self):
        self.assertIn("records no folder", self.mod.server_in_folder("")["why"])

    def test_a_scheduled_pass_owns_its_own_session_and_says_whose_command_it_is(self):
        d = self.root / "rc-jobs"
        d.mkdir()
        (d / "daily-maintenance.session").write_text(
            "uuid=%s\nstarted=1793194502\nname=Daily maintenance\n" % SID_A)
        (d / "other.session").write_text("uuid=%s\n" % SID_B)
        self.mod.RC_JOBS_DIR = d
        got = self.mod.revive_owner(SID_A)
        self.assertEqual((got["owner"], got["kind"]), ("daily-maintenance", "rc_job"))
        self.assertIn("--revive", got["fix"])
        self.assertEqual(self.mod.revive_owner(SID_C)["owner"], "")

    def test_the_last_uuid_line_wins_because_that_file_is_appended_to(self):
        d = self.root / "rc-jobs"
        d.mkdir()
        (d / "pass.session").write_text("uuid=%s\nuuid=%s\n" % (SID_B, SID_A))
        self.mod.RC_JOBS_DIR = d
        self.assertEqual(self.mod.rc_job_owner(SID_A), "pass")
        self.assertEqual(self.mod.rc_job_owner(SID_B), "",
                         "the earlier run's id is not what the pass is on now")

    def test_an_rc_jobs_directory_that_cannot_be_READ_is_a_refusal_not_a_no(self):
        d = self.root / "rc-jobs"
        d.mkdir()
        (d / "pass.session").write_text("uuid=%s\n" % SID_A)
        d.chmod(0o000)
        self.addCleanup(d.chmod, 0o700)
        self.mod.RC_JOBS_DIR = d
        if os.geteuid() == 0:
            self.skipTest("root reads an unreadable directory")
        with self.assertRaises(self.mod.Refusal) as e:
            self.mod.rc_job_owner(SID_A)
        self.assertIn("could not read", str(e.exception))

    def test_the_knob_unset_means_no_such_supervisor_at_all(self):
        self.mod.RC_JOBS_DIR = None
        self.assertEqual(self.mod.rc_job_owner(SID_A), "")

    # --- the whole record ------------------------------------------------
    def test_one_record_carries_every_answer_the_decide_table_reads(self):
        s = self.session(self.a, sid=LINK_SID,
                         lines=[user("go", self.cwd, LINK_SID, uuid="u1"),
                                assistant("ok", self.cwd, LINK_SID, uuid="a1",
                                          parent="u1")])
        sp = self.mod.resolve_spec(link_of(LINK_BARE), [self.a])
        rec = self.mod.diagnose(s, [self.a], sp)
        for key in ("session", "kind", "state", "stop", "lost_work", "account", "server",
                    "owner", "spec"):
            self.assertIn(key, rec, key)
        self.assertEqual(rec["session"]["url"], link_of(LINK_BARE))
        self.assertEqual(rec["kind"]["kind"], "server-child")
        self.assertEqual(rec["state"]["state"], "dead")
        self.assertEqual(rec["stop"]["stop"], "finished")
        self.assertEqual(rec["machine"], "here")
        json.dumps(rec, default=str)         # the --json path must not choke on it


class ReviveNoteText(InProc):
    """WHAT THE REVIVED SESSION IS TOLD. Pure text, so every clause can be pinned.

    🛑 It arrives as that session's next USER turn — it renders in the app as a message —
    so the stamp is not decoration: a message in his conversation that he did not type has
    to say so in its first line, and `--say` is the only sentence that may be attributed to
    him. `move_note`'s rule holds here too: facts, no advice, nothing it cannot show.

    ⚠️ It builds its own fixtures rather than inheriting `ReviveDiagnose`'s: a test class
    that subclasses another one silently RE-RUNS all of its tests, which makes every count
    read here and in CI a lie about how much was checked.
    """

    STOP = {"stop": "usage-limit", "class": "session", "window": "five_hour",
            "resets_at": 0.0, "in_force": False, "age": "17h", "at": 0.0,
            "clears_with_time": True, "tool": "", "tool_at": 0.0}

    def setUp(self):
        super().setUp()
        self.mod.MACHINE = "here"
        self.a = self.account("work", email="me@work.example")
        self.tgt = self.account("personal", email="you@home.example", org="org-2")
        self.s = self.session(self.a)

    def rec(self, **over):
        stop = dict(self.STOP)
        stop["at"] = time.time() - 17 * 3600
        stop.update(over.pop("stop", {}))
        out = {"session": {"short": self.s.short, "title": "t", "url": ""},
               "stop": stop, "lost_work": {"errors": 0, "labels": []}}
        out.update(over)
        return out

    def note(self, action="resume", **kw):
        rec = kw.pop("rec", None) or self.rec(**kw.pop("over", {}))
        kw.setdefault("when", "Wed 28 Oct 2026 13:30 PDT")
        kw.setdefault("boot", 0.0)
        return self.mod.revive_note(self.s, rec, action, **kw)

    def test_the_stamp_opens_it_and_the_request_and_the_closing_end_it(self):
        n = self.note()
        self.assertTrue(n.startswith("[claude-session-mover — written by the tool; the "
                                     "user did not type this] "), n[:120])
        self.assertIn("Revived at Wed 28 Oct 2026 13:30 PDT on `here`", n)
        self.assertIn("This session stopped at", n)
        self.assertIn("He asked csm to revive this session and continue where it stopped.",
                      n)
        self.assertTrue(n.endswith("Re-check anything time-sensitive (running jobs, locks, "
                                   "claims, hardware state) before acting on it; do not "
                                   "repeat work that is already done."), n[-200:])

    def test_a_mid_turn_stop_says_the_tool_result_is_missing_and_nothing_else_does(self):
        """🛑 The sentence exists for exactly one class. After a limit the turn
        demonstrably did not run; after a SIGKILL mid-`Edit` the call may have fully
        applied, partly applied or not run, and "do not repeat work" is the worst possible
        reading of that."""
        n = self.note(over={"stop": {"stop": "mid-turn", "tool": "Edit",
                                     "tool_at": time.time() - 3600}})
        self.assertIn("Its last tool call (Edit,", n)
        self.assertIn("has no recorded result: check whether it took effect before "
                      "repeating it.", n)
        self.assertNotIn("no recorded result", self.note())

    def test_a_mid_turn_stop_with_no_tool_says_nothing_about_a_call(self):
        """🛑 THE SECOND MID-TURN SHAPE (Thu 29 Oct 2026, week 44): killed before it answered
        the prompt at all, so `tool` is empty. The sentence above would have named "a tool"
        and a time nothing recorded — a claim about a call the file does not hold, in the one
        message he reads."""
        n = self.note(over={"stop": {"stop": "mid-turn", "tool": "", "tool_at": 0.0}})
        self.assertIn("It was killed before it answered that prompt at all", n)
        self.assertIn("read the folder before repeating anything.", n)
        self.assertNotIn("tool call", n)

    def test_say_is_quoted_verbatim_and_attributed_to_him(self):
        n = self.note(say="  drop the camera half and finish the power model  ")
        self.assertIn('He said: "drop the camera half and finish the power model"', n)
        self.assertNotIn("He asked csm to revive", n)

    def test_a_say_that_the_cli_would_run_as_a_command_is_refused(self):
        """2.1.312's own `prompt_undelivered`: "a prompt starting with ! or / would run as
        a command there"."""
        for bad in ("/compact", "  /clear", "!rm -rf build", " ! ls"):
            with self.assertRaises(self.mod.Refusal) as e:
                self.note(say=bad)
            self.assertIn("runs a leading", str(e.exception))
            self.assertIn("--say starts with `%s`" % bad.strip()[0], str(e.exception))

    def test_a_say_over_the_bound_is_refused_and_never_shortened(self):
        with self.assertRaises(self.mod.Refusal) as e:
            self.note(say="x" * (self.mod.REVIVE_SAY_MAX + 1))
        self.assertIn("quoted verbatim", str(e.exception))
        self.assertIn(str(self.mod.REVIVE_SAY_MAX), str(e.exception))

    def test_a_fork_says_loudly_that_the_old_link_opens_the_old_copy(self):
        """🛑 AND ONLY WHERE THERE IS AN OLD LINK. `--new-link` forks a dead TERMINAL
        session too (row 11), and that session never had a claude.ai link — so the sentence
        that is right for a server child would be false in its note.
        """
        n = self.note("fork", new_id=SID_B,
                      over={"session": {"short": self.s.short, "title": "t",
                                        "url": link_of(LINK_BARE)}})
        self.assertIn("csm FORKED it: this copy is %s, forked from %s"
                      % (SID_B[:8], self.s.short), n)
        self.assertIn("The old link still opens the OLD copy", n)
        self.assertIn("do not type there, and archive it", n)
        # the same action on a session with no link of its own (`rec`'s own `url` is ""):
        # the old COPY, and not one word about a link that never existed
        n = self.note("fork", new_id=SID_B)
        self.assertIn("csm FORKED it: this copy is %s" % SID_B[:8], n)
        self.assertIn("had no claude.ai link of its own", n)
        self.assertNotIn("The old link still opens", n)

    def test_a_wake_says_nothing_was_restarted(self):
        n = self.note("wake")
        self.assertIn("still running and idle", n)
        self.assertIn("the claude.ai link is unchanged", n)

    def test_a_resume_in_place_and_a_new_link_resume_are_told_apart(self):
        self.assertIn("the link you had still opens this conversation", self.note("resume"))
        n = self.note("resume-new-link")
        self.assertIn("NEW claude.ai link", n)
        self.assertIn("nothing opens the old one", n)

    def test_a_move_names_both_accounts_and_a_same_account_revive_does_not(self):
        n = self.note("move", tgt=self.tgt)
        self.assertIn("csm moved it from me@work.example to you@home.example", n)
        self.assertIn("You now run as you@home.example", n)
        self.assertIn("are stale", n)
        same = self.note("resume")
        self.assertIn("You are still me@work.example on `here`", same)
        self.assertNotIn("are stale", same)

    def test_a_restart_after_the_stop_is_said_and_one_before_it_is_not(self):
        """The difference between "pick up where you left off" and "work out what
        happened": a session whose stop is older than the boot was killed by the restart."""
        stopped = time.time() - 17 * 3600
        n = self.note(over={"stop": {"at": stopped}}, boot=stopped + 600)
        self.assertIn("this machine restarted at", n)
        self.assertIn("killed by the restart and not by anything it did", n)
        self.assertNotIn("this machine restarted",
                         self.note(over={"stop": {"at": stopped}}, boot=stopped - 600))

    def test_a_reset_that_has_passed_is_said_and_a_future_one_is_not(self):
        past = time.time() - 600
        n = self.note(over={"stop": {"resets_at": past}})
        self.assertIn("Since then:", n)
        self.assertIn("that limit's reset passed at", n)
        self.assertIn("which reset at", n)
        ahead = self.note(over={"stop": {"resets_at": time.time() + 600,
                                         "in_force": True}})
        self.assertNotIn("Since then:", ahead)
        self.assertIn("which lifts at", ahead)

    def test_the_agents_that_died_with_it_are_counted_and_named(self):
        n = self.note(over={"lost_work": {"errors": 5, "labels": ["a2-e73", "verify:a3"]}})
        self.assertIn("5 agent(s) of a workflow run died with it (a2-e73, verify:a3)", n)
        self.assertIn("whatever the run's own status file says", n)

    def test_the_memory_store_is_named_because_a_resume_never_hears_it(self):
        store = self.root / "shared-memory"
        store.mkdir()
        tgt = self.account("personal2", email="you@home.example",
                           settings={"env": {self.mod.MEMORY_DIR_ENV: str(store)}})
        n = self.note("move", tgt=tgt)
        self.assertIn("Auto memory for this project is read from %s" % store, n)
        self.assertNotIn("Auto memory", self.note("resume"))

    def test_the_budget_is_met_by_dropping_optional_clauses_in_order(self):
        """🛑 A budget, not a truncation: the stamp, the stop, the mid-turn warning, the
        request and the closing sentence are never dropped, and no sentence is ever cut in
        half."""
        store = self.root / "shared-memory"
        store.mkdir()
        tgt = self.account("personal3", email="you@home.example",
                           settings={"env": {self.mod.MEMORY_DIR_ENV: str(store)}})
        over = {"lost_work": {"errors": 9, "labels": ["label-%d" % i for i in range(6)]},
                "stop": {"resets_at": time.time() - 600}}
        long_say = "please " + "x" * 380
        self.mod.REVIVE_NOTE_MAX = 10 ** 6   # with room, every clause is there
        full = self.mod.revive_note(self.s, self.rec(**over), "move", tgt=tgt, say=long_say,
                                    when="Wed 11:00", boot=0.0)
        self.assertIn("Auto memory", full)
        self.assertIn("9 agent(s)", full)
        self.assertIn("Since then:", full)
        # 🛑 One character short of the whole note, so exactly the first clause in the drop
        # order has to go. Set from the note's own length because that length includes this
        # run's temporary paths: GitHub's `/tmp/tmpXXXX` is short enough that the default
        # budget fitted every clause, and the test failed there while passing on a Mac with
        # a long TMPDIR (Wed 28 Oct 2026).
        self.mod.REVIVE_NOTE_MAX = len(full) - 1
        n = self.mod.revive_note(self.s, self.rec(**over), "move", tgt=tgt, say=long_say,
                                 when="Wed 11:00", boot=0.0)
        self.assertLessEqual(len(n), self.mod.REVIVE_NOTE_MAX)
        self.assertNotIn("Auto memory", n, "the first clause in the drop order")
        self.assertIn(long_say, n, "his own words are never shortened")
        self.assertIn("csm moved it from", n)
        self.assertIn("Re-check anything time-sensitive", n)


class ReviveDryRun(Base):
    """`csm revive <spec> --dry-run`, end to end, once per row of the decide table.

    🛑 EVERY ROW, BECAUSE THE ROW IS THE WHOLE ANSWER. The order is the contract — first
    match wins — so a session that is both out of quota and dead is answered about the
    quota, and a session something else owns is answered about its owner before anything
    is read about quota at all. Each test here is the command a person types.
    """

    def setUp(self):
        super().setUp()
        self.cwd = str(self.w.work)

    # --- fixtures ---------------------------------------------------------
    def go(self, sid=SID_A):
        return user("run the campaign", self.cwd, sid, uuid="u1")

    def clean(self, sid=SID_A):
        return assistant("done", self.cwd, sid, uuid="a1", parent="u1")

    def limit(self, resets, sid=SID_A, text="You've hit your session limit · resets 6:30pm"):
        return assistant(text, self.cwd, sid, error="usage_limit_reached", resets=resets,
                         shape="rate_limit", uuid="a2", parent="a1")

    def revive(self, spec, *extra, **env):
        return self.w.run("revive", spec, "--dry-run", *extra, **env)

    def rec(self, spec, *extra, **env):
        out = self.ok(self.revive(spec, "--json", *extra, **env))
        return json.loads(out)

    def row_of(self, spec, *extra, **env):
        return self.rec(spec, *extra, **env)["decision"]

    def dead(self, sid=SID_A, lines=None):
        return self.w.session(self.work, sid, cwd=self.cwd,
                              lines=lines if lines is not None
                              else [self.go(sid), self.clean(sid)])

    def live(self, sid=SID_A, status="idle", lines=None, mode=""):
        """A transcript plus a live, provable registry row.

        `mode` puts a real `--permission-mode` on that process's own command line — which is
        where the mode a RUNNING session is in is measured from (`launch_mode`, the same
        reading `csm modes` takes), and what a row that starts nothing has to report.
        """
        self.dead(sid, lines)
        p = (self.w.spawn(argv_tail=("--resume", sid, "--permission-mode", mode))
             if mode else self.w.spawn())
        self.w.live(self.work, sid, p.pid, cwd=self.cwd, status=status)
        return p

    # --- the gate ---------------------------------------------------------
    def test_the_plan_and_the_real_run_take_the_same_row(self):
        """🛑 ONE PRODUCER. The gate that used to refuse a run without `--dry-run` is gone
        (the actions are built), so the thing worth pinning is that what the dry run prints
        is what the run carries out: a plan that said row 9 cannot be followed by a run that
        takes row 10. Row 9 is the one that starts nothing, so it is the one to ask here."""
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        planned = self.row_of(link_of(LINK_BARE))
        self.assertEqual(planned["row"], 9)
        r = self.w.run("revive", link_of(LINK_BARE), "--json")
        self.ok(r)
        got = json.loads(r.stdout)
        self.assertIs(got["dry_run"], False)
        self.assertEqual(got["decision"]["row"], planned["row"])
        self.assertEqual(got["result"]["action"], "keep-link")
        self.assertEqual(self.w.claude_calls(wait=0.4), [], "row 9 starts nothing")

    def test_from_machine_says_where_the_diagnosis_has_to_be_made(self):
        self.dead()
        self.refused(self.revive(SID_A, "--from-machine", "desktop"),
                     "--from-machine is not built for revive",
                     "csm --machine desktop revive <spec>")

    def test_a_dry_run_writes_nothing_and_starts_nothing(self):
        t = self.dead()
        before = t.read_text()
        self.ok(self.revive(SID_A))
        self.assertEqual(t.read_text(), before)
        self.assertEqual(self.w.claude_calls(wait=0.4), [])
        self.assertEqual(self.w.tmux_log(), [])

    def test_the_answer_opens_with_three_lines_and_then_the_detail(self):
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        out = self.ok(self.revive(SID_A))
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("REVIVE  run the campaign"), lines[0])
        self.assertTrue(lines[1].startswith("  1 stopped "), lines[1])
        self.assertTrue(lines[2].startswith("  2 "), lines[2])
        self.assertTrue(lines[3].startswith("  3 risk: "), lines[3])
        self.assertIn("what it is   self-hosted", out)
        self.assertIn("decide       row 7", out)
        self.assertIn("the revive note (delivered as its next user turn):", out)
        self.assertIn("(dry run: nothing was started, woken, moved, signalled or written)",
                      out)

    # --- row by row -------------------------------------------------------
    def test_row_1_a_bot_owns_it(self):
        self.dead()
        d = self.w.root / "owners"
        d.mkdir()
        (d / "chatbot.json").write_text(json.dumps({"session_id": SID_A}))
        dec = self.row_of(SID_A, CSM_BOTS_DIR=str(d))
        self.assertEqual((dec["row"], dec["action"], dec["exit"]), (1, "refuse", 2))
        self.assertIn("chatbot", dec["refusal"])
        self.assertFalse(dec["note"], "nothing is told anything")

    def test_row_1_a_scheduled_pass_owns_it_and_has_its_own_revive(self):
        self.dead()
        d = self.w.root / "rc-jobs"
        d.mkdir()
        (d / "daily-maintenance.session").write_text("uuid=%s\nperm=bypassPermissions\n"
                                                     % SID_A)
        out = self.ok(self.revive(SID_A, CSM_RC_JOBS_DIR=str(d)))
        self.assertIn("row 1", out)
        self.assertIn("rc_job daily-maintenance --revive", out)

    def test_row_2_nothing_to_continue(self):
        """A server pre-creates sessions: such a transcript has a derivable name, a link
        and no turn of its own — 132 of them in the config homes here, Wed 28 Oct 2026."""
        self.dead(lines=[{"type": "custom-title", "customTitle": "pre-created"}])
        dec = self.row_of(SID_A)
        self.assertEqual((dec["row"], dec["action"]), (2, "refuse"))
        self.assertIn("nothing to continue", dec["refusal"])

    def test_row_2_reaches_a_transcript_no_listing_carries(self):
        """🛑 "there is nothing to continue" is an ANSWER about a 0-byte pre-created
        session; "no transcript for that link here" would be false about a file on disk."""
        t = self.w.session(self.work, LINK_SID, cwd=self.cwd, lines=[])
        t.write_text("")
        self.assertEqual([r["local_id"] for r in self.listing()], [],
                         "no listing carries it, which is right for `list`")
        dec = self.row_of(link_of(LINK_BARE))
        self.assertEqual(dec["row"], 2)
        self.assertIn("0 bytes", dec["refusal"])

    def test_row_3_it_is_working(self):
        self.live(status="busy")
        dec = self.row_of(SID_A)
        self.assertEqual((dec["row"], dec["action"], dec["exit"]), (3, "nothing", 0))
        self.assertIn("working right now", dec["what"])
        self.assertFalse(dec["note"])

    def test_row_4_the_limit_is_still_in_force(self):
        self.dead(lines=[self.go(), self.clean(), self.limit(time.time() + 3600)])
        out = self.ok(self.revive(SID_A))
        self.assertIn("row 4", out)
        self.assertIn("still inside the session limit", out)
        self.assertIn("wait until", out)
        self.assertIn("--to auto", out)
        self.assertNotIn("the revive note", out)

    def test_row_4_says_when_waiting_is_not_the_cure(self):
        self.dead(lines=[self.go(), self.clean(),
                         self.limit(time.time() + 3600,
                                    text="You've hit your monthly spend limit · raise it "
                                         "at claude.ai/settings/usage")])
        out = self.ok(self.revive(SID_A))
        self.assertIn("waiting does NOT clear a monthly-spend limit", out)
        self.assertNotIn("wait until", out)

    def test_row_4_is_outranked_by_an_owner_and_by_an_empty_transcript(self):
        """The order of the table, proved where two rows both match."""
        self.dead(lines=[self.go(), self.clean(), self.limit(time.time() + 3600)])
        d = self.w.root / "owners"
        d.mkdir()
        (d / "bot.json").write_text(json.dumps({"session_id": SID_A}))
        self.assertEqual(self.row_of(SID_A, CSM_BOTS_DIR=str(d))["row"], 1)

    def test_row_5_a_live_idle_session_is_woken(self):
        self.live(status="idle")
        dec = self.row_of(SID_A)
        self.assertEqual((dec["row"], dec["action"], dec["exit"]), (5, "wake", 0))
        self.assertTrue(dec["note"])
        self.assertIn("PEER message", dec["risk"])

    def test_row_5_is_outranked_by_a_limit_still_in_force(self):
        """A wake inside the limit is consumed and lost — measured on the 17:46 heartbeat."""
        self.live(status="idle",
                  lines=[self.go(), self.clean(), self.limit(time.time() + 3600)])
        self.assertEqual(self.row_of(SID_A)["row"], 4)

    def test_row_6_to_another_account(self):
        self.dead()
        dec = self.row_of(SID_A, "--to", "personal")
        self.assertEqual((dec["row"], dec["action"]), (6, "move"))
        self.assertIn("personal", dec["what"])
        self.assertIn("RE-READS", dec["risk"])
        self.assertIn("csm moved it from me@work.example to me@home.example",
                      self.rec(SID_A, "--to", "personal")["note"])
        # a revive to another account IS a move, so it costs what a move costs
        out = self.ok(self.revive(SID_A, "--to", "personal"))
        self.assertIn("what this move costs", out)
        self.assertIn("RE-READS the whole", out)

    def test_row_6_is_how_a_limit_in_force_is_cured(self):
        self.dead(lines=[self.go(), self.clean(), self.limit(time.time() + 3600)])
        self.assertEqual(self.row_of(SID_A)["row"], 4)
        self.assertEqual(self.row_of(SID_A, "--to", "personal")["row"], 6)

    def test_row_7_a_self_hosted_session_resumes_in_place(self):
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        dec = self.row_of(SID_A)
        self.assertEqual((dec["row"], dec["action"]), (7, "resume"))
        self.assertIn("same claude.ai link", dec["what"])
        self.assertIn("the link you had still opens this conversation",
                      self.rec(SID_A)["note"])

    def test_row_7_refuses_an_archived_session_unless_told_to_unarchive(self):
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE, STATUS_LINE, ENDED_LINE])
        dec = self.row_of(SID_A)
        self.assertEqual((dec["row"], dec["action"], dec["exit"]), (7, "refuse", 2))
        self.assertIn("archived", dec["refusal"])
        self.assertIn("--unarchive", dec["refusal"])
        dec = self.row_of(SID_A, "--unarchive")
        self.assertEqual((dec["row"], dec["action"]), (7, "resume"))

    def test_row_8_a_terminal_session_resumes_and_gets_a_new_link(self):
        self.dead()
        dec = self.row_of(SID_A)
        self.assertEqual((dec["row"], dec["action"]), (8, "resume-new-link"))
        self.assertIn("NEW claude.ai link", dec["what"])
        self.assertIn("exposure", dec["risk"])

    def test_row_9_a_server_child_keeps_its_link_and_starts_nothing(self):
        """🛑 `--resume <uuid>` cannot re-attach a server child's claude.ai session: it
        registers a NEW link. So the cheap answer is one tap — the server respawns the
        child when the link is opened — and nothing is started or waited for here."""
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        dec = self.row_of(link_of(LINK_BARE))
        self.assertEqual((dec["row"], dec["action"], dec["exit"]), (9, "keep-link", 0))
        # 🛑 NOT "say continue": whether that advice is given depends on whether a server
        # runs in the folder, which this end-to-end run reads off the REAL machine's `ps`
        # (a CI runner has none, a Remote Control Mac has dozens). Each server state's
        # wording is pinned by the pure test below; this one pins the row.
        self.assertIn("nothing is started", dec["what"])
        self.assertIn(link_of(LINK_BARE), dec["what"])
        self.assertIn("--new-link", dec["risk"])
        self.assertFalse(dec["note"], "nothing is started, so nothing is told anything")
        out = self.ok(self.revive(link_of(LINK_BARE)))
        self.assertIn(link_of(LINK_BARE), out)

    def test_a_dead_server_child_named_by_its_ID_is_never_resumed_in_place(self):
        """🛑 THE TWO-WRITER OUTCOME L39 AND F5 FORBID, reachable by the ordinary spec.

        `csm list` prints the 8-character id and the title and `csm revive --help` invites
        both, and a DEAD server child named that way has no source of its bridge id at all:
        no registry row, no bridge line in its own transcript, no `bridge-spawn` dir. It
        therefore read as `terminal`, which is row 8 — `--resume <old id>` with no
        `--fork-session`, a second process on the old local id, while a later lazy respawn of
        the old link has that same id. `--new-link` could not rescue it either: the flag is
        read only inside the `server-child` branches, so row 8 matched first.
        """
        self.w.session(self.work, FORK_SID, cwd=self.cwd,
                       lines=[self.go(FORK_SID), self.clean(FORK_SID)])
        for spec in (FORK_SID, FORK_SID[:8], "campaign"):
            dec = self.row_of(spec)
            self.assertEqual((dec["row"], dec["action"]), (9, "keep-link"), spec)
            self.assertFalse(dec["note"], spec)
        # the link it cannot name is ASKED FOR, never invented
        out = self.ok(self.revive(FORK_SID))
        self.assertIn("paste the link (`csm revive <link>`)", out)
        self.assertIn("version-5 uuid", out)
        self.assertNotIn("https://claude.ai/code/session_", out)
        # and `--new-link` now reaches row 10, which forks without needing the link
        dec = self.row_of(FORK_SID, "--new-link")
        self.assertEqual((dec["row"], dec["action"]), (10, "fork"))

    def test_row_9_says_whether_the_server_that_would_respawn_it_is_up(self):
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        p = self.w.server("myproject")
        self.w.lsof_map.write_text(json.dumps({str(p.pid): self.cwd}))
        out = self.ok(self.revive(link_of(LINK_BARE)))
        self.assertIn("a server is up in this folder: pid %d (myproject)" % p.pid, out)
        self.assertNotIn("its server is down", out)
        self.assertNotIn("its server is unread", out)
        self.assertNotIn("could not be read here", out)

    def test_row_9_says_one_coherent_thing_for_each_server_state(self):
        """Opening the link respawns the child only while a server runs in its folder, and
        a restart kills that server too. Line 2 once read "open it and say continue — its
        server respawns it on open (and its server is down)", which three fresh readers of
        the README each took as a contradiction (Wed 28 Oct 2026). Pure, on a real record
        with only `server` changed, because whether a server is up here depends on the
        machine the suite runs on (its real `claude remote-control` processes are in `ps`)."""
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        record = self.rec(link_of(LINK_BARE))["record"]
        mod = load_tool()
        args = types.SimpleNamespace(to="", say="", permission_mode="", new_link=False,
                                     unarchive=False)

        def line2(up):
            dec = mod.revive_decide(dict(record, server={"up": up}), args)
            self.assertEqual(dec["row"], 9)
            return dec["what"]

        up = line2(True)
        self.assertIn("say continue — its server respawns it on open", up)
        self.assertNotIn("down", up)
        down = line2(False)
        self.assertIn("its server is down, so opening", down)
        self.assertIn("`--new-link` forks it onto a new link now", down)
        self.assertNotIn("say continue", down)
        self.assertNotIn("respawns it on open", down)
        unread = line2(None)
        self.assertIn("its server could not be read here", unread)
        self.assertIn("`--new-link` forks it", unread)

    def test_row_10_a_server_child_forks_onto_a_new_link(self):
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        dec = self.row_of(link_of(LINK_BARE), "--new-link")
        self.assertEqual((dec["row"], dec["action"]), (10, "fork"))
        self.assertIn("OLD link still opens the OLD copy", dec["risk"])
        note = self.rec(link_of(LINK_BARE), "--new-link")["note"]
        self.assertIn("csm FORKED it", note)
        self.assertIn("The old link still opens the OLD copy", note)
        self.assertIn("csm FORKED it", self.ok(self.revive(link_of(LINK_BARE),
                                                           "--new-link")))

    def test_row_11_new_link_FORKS_a_dead_self_hosted_session(self):
        """🛑 MEASURED LIVE ON CLI 2.1.312, Wed 28 Oct 2026: `csm revive <dead self-hosted
        session> --new-link --dry-run` took row 7 — "resume it in place, on the same
        claude.ai link" — with no mention of the flag at all, because `new_link` was read
        only at the row-9/row-10 split. `--new-link` means a fresh copy on a new link.
        """
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        self.assertEqual(self.row_of(SID_A)["row"], 7, "without the flag it resumes")
        dec = self.row_of(SID_A, "--new-link")
        self.assertEqual((dec["row"], dec["action"], dec["exit"]), (11, "fork", 0))
        self.assertIn("FORK it onto a NEW claude.ai link", dec["what"])
        self.assertIn("still opens the OLD copy", dec["risk"])
        self.assertEqual(dec["dropped"], "", "the flag IS carried out here")
        self.assertTrue(dec["note"])
        note = self.rec(SID_A, "--new-link")["note"]
        self.assertIn("csm FORKED it", note)
        self.assertIn("The old link still opens the OLD copy", note)
        out = self.ok(self.revive(SID_A, "--new-link"))
        self.assertIn("decide       row 11 — fork", out)

    def test_row_11_forks_a_dead_terminal_session_and_invents_no_old_link(self):
        """A terminal session never had a claude.ai link, so the sentence a server child's
        fork needs — "the old link still opens the OLD copy" — would be false in its note."""
        self.dead()
        self.assertEqual(self.row_of(SID_A)["row"], 8, "without the flag it resumes")
        dec = self.row_of(SID_A, "--new-link")
        self.assertEqual((dec["row"], dec["action"]), (11, "fork"))
        self.assertIn("left byte-identical", dec["what"])
        self.assertIn("SECOND conversation", dec["risk"])
        note = self.rec(SID_A, "--new-link")["note"]
        self.assertIn("csm FORKED it", note)
        self.assertIn("had no claude.ai link of its own", note)
        self.assertNotIn("The old link still opens", note)

    def test_new_link_on_a_row_that_forks_nothing_says_it_was_NOT_carried_out(self):
        """🛑 A FLAG THAT WAS NOT CARRIED OUT SAYS SO — on the live rows and on a refusal,
        not only on the two rows `dropped` used to be called for."""
        self.live(status="idle")                                       # row 5
        dec = self.row_of(SID_A, "--new-link")
        self.assertEqual(dec["row"], 5)
        self.assertIn("NOT carry out --new-link", dec["dropped"])
        self.assertIn("live writer", dec["dropped"])
        self.assertIn("NOT carry out --new-link", dec["what"])
        self.live(sid=SID_B, status="busy")                            # row 3
        dec = self.row_of(SID_B, "--new-link")
        self.assertEqual(dec["row"], 3)
        self.assertIn("NOT carry out --new-link", dec["what"])
        # and a refusal: a transcript with no conversation in it
        self.dead(sid=SID_C, lines=[{"type": "custom-title", "customTitle": "pre-made"}])
        dec = self.row_of(SID_C, "--new-link")
        self.assertEqual((dec["row"], dec["action"]), (2, "refuse"))
        self.assertIn("NOT carry out --new-link: nothing is started on this row",
                      dec["what"])

    # --- the mode a row that starts nothing LEAVES ALONE -------------------
    def test_row_5_reports_the_mode_the_wake_LEAVES_ALONE_not_the_one_asked_for(self):
        """🛑 MEASURED LIVE ON CLI 2.1.312, Wed 28 Oct 2026: a session running
        `--permission-mode bypassPermissions`, woken with `--permission-mode plan`, was
        reported as `mode plan (from --permission-mode)` while it went on running in bypass
        — the UNSAFE direction. A wake starts no process, so no mode is applied to anything.
        """
        self.live(status="idle", mode="bypassPermissions",
                  lines=[user("run the campaign", self.cwd, SID_A, perm="auto", uuid="u1"),
                         self.clean()])
        got = self.rec(SID_A, "--permission-mode", "plan")
        self.assertEqual(got["decision"]["row"], 5)
        self.assertEqual(got["record"]["state"]["mode_launched"], "bypassPermissions")
        # the mode REPORTED is the one it is in, and the weaker recorded `auto` — what a
        # Remote Control worker records by accident — does not outrank the argv
        self.assertEqual(got["mode"]["mode"], "bypassPermissions")
        self.assertIs(got["mode"]["applied"], False)
        self.assertIn("unchanged: a wake starts nothing", got["mode"]["why"])
        self.assertIn("its command line says --permission-mode bypassPermissions",
                      got["mode"]["why"])
        self.assertIn("its transcript last recorded auto", got["mode"]["why"])
        self.assertNotIn("from --permission-mode", json.dumps(got["mode"]))
        # and the flag is reported as NOT carried out, in the sentence a person reads
        self.assertIn("NOT put it in plan", got["decision"]["what"])
        out = self.ok(self.revive(SID_A, "--permission-mode", "plan"))
        self.assertIn("mode         bypassPermissions (unchanged: a wake starts nothing",
                      out)
        self.assertNotIn("mode         plan", out)

    def test_a_mode_nothing_could_measure_is_unknown_and_never_a_guess(self):
        """Row 9 starts nothing either, and a dead session has no command line to read: so
        the line says `unknown` with the reason, and never `default`."""
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        got = self.rec(link_of(LINK_BARE), "--permission-mode", "bypassPermissions")
        self.assertEqual(got["decision"]["row"], 9)
        self.assertEqual(got["mode"]["mode"], "")
        self.assertIs(got["mode"]["applied"], False)
        self.assertIn("nothing here records what mode it is in", got["mode"]["why"])
        self.assertIn("NOT put it in bypassPermissions", got["decision"]["what"])
        out = self.ok(self.revive(link_of(LINK_BARE), "--permission-mode",
                                  "bypassPermissions"))
        self.assertIn("mode         unknown (unchanged: this row starts nothing", out)

    def test_the_mode_IS_the_one_asked_for_on_a_row_that_starts_a_process(self):
        """The other half of the same contract: where csm really starts the session, the
        mode is the one it will be started in and `applied` says so."""
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        got = self.rec(SID_A, "--permission-mode", "plan")
        self.assertEqual(got["decision"]["row"], 7)
        self.assertEqual((got["mode"]["mode"], got["mode"]["why"]),
                         ("plan", "from --permission-mode"))
        self.assertIs(got["mode"]["applied"], True)
        self.assertEqual(got["decision"]["dropped"], "")

    def test_a_permission_mode_typo_is_refused_on_a_row_that_starts_nothing_too(self):
        """A flag is either wrong or it is not; which row the session happens to take is not
        what decides (`check_say`'s own rule, now `--permission-mode`'s as well)."""
        self.live(status="busy")
        self.refused(self.revive(SID_A, "--permission-mode", "sideways"),
                     "sideways", "not a permission mode")

    # --- the flags --------------------------------------------------------
    def test_the_say_text_is_quoted_into_the_note_and_a_command_is_refused(self):
        self.dead()
        got = self.rec(SID_A, "--say", "finish the power model")
        self.assertIn('He said: "finish the power model".', got["note"])
        # The printed block wraps at the page width, and WHERE depends on how long this run's
        # temporary paths are (they are in the note before his words; a short TMPDIR, or
        # macOS turning /tmp into /private/tmp, moves the break). So the whitespace is folded
        # before matching, and the whole quotation is matched.
        out = self.ok(self.revive(SID_A, "--say", "finish the power model"))
        self.assertIn('He said: "finish the power model".', " ".join(out.split()))
        self.refused(self.revive(SID_A, "--say", "/compact"), "runs a leading")

    def test_an_unknown_permission_mode_is_refused_in_the_dry_run(self):
        self.dead()
        self.refused(self.revive(SID_A, "--permission-mode", "sideways"),
                     "sideways", "not a permission mode")
        self.assertIn("mode         bypassPermissions",
                      self.ok(self.revive(SID_A, "--permission-mode",
                                          "bypassPermissions")))

    def test_the_name_flag_is_the_remote_control_label_it_would_use(self):
        self.dead()
        self.assertIn("--name       My revived pass",
                      self.ok(self.revive(SID_A, "--name", "My revived pass")))

    def test_the_risk_line_is_the_worst_fact_and_not_always_the_rows_own(self):
        """An unanswered tool call outranks the mechanism: it changes what the reader
        should DO next, which is what the third line is for."""
        self.dead(lines=[self.go(), tool_call(self.cwd, SID_A, name="Bash")])
        out = self.ok(self.revive(SID_A))
        self.assertIn("3 risk: its last tool call (Bash) has no recorded result", out)
        self.assertIn("neither assumption is safe", out)

    def test_the_other_mid_turn_shape_names_no_tool_it_cannot_see(self):
        """🛑 A MID-TURN STOP WITH NO TOOL IS A KILL BEFORE THE FIRST WORD (Thu 29 Oct 2026).
        The sentence used to say "its last tool call (a tool) has no recorded result" for it,
        which invents a call the transcript does not hold — and the risk is the opposite one:
        not whether a call took effect, but that nothing says how far it got."""
        self.dead(lines=[self.go(), tokens_reminder(self.cwd, SID_A)])
        out = self.ok(self.revive(SID_A))
        self.assertIn("3 risk: it was killed before it answered its last prompt", out)
        self.assertNotIn("(a tool)", out)

    def test_the_lost_agents_reach_the_three_line_answer(self):
        t = self.dead()
        d = t.parent / SID_A / "workflows"
        d.mkdir(parents=True)
        (d / "wf_abc.json").write_text(json.dumps({
            "status": "completed",
            "workflowProgress": [{"state": "error", "label": "a2-e73-camera"},
                                 {"state": "error", "label": "verify:a3"}]}))
        out = self.ok(self.revive(SID_A))
        self.assertIn("3 risk: 2 agent(s) of a workflow run died with it", out)
        self.assertIn("lost work    2 errored agent(s) in wf_abc.json", out)

    def test_the_json_carries_the_record_the_decision_and_the_note(self):
        self.dead()
        got = self.rec(SID_A)
        self.assertIs(got["dry_run"], True)
        self.assertEqual(sorted(got["record"]), [
            "account", "at", "kind", "lost_work", "machine", "owner", "server", "session",
            "spec", "state", "stop", "version"])
        self.assertEqual(got["decision"]["row"], 8)
        self.assertIn("claude-session-mover —", got["note"])
        self.assertEqual(got["record"]["session"]["local_id"], SID_A)

    def test_the_auto_choice_is_said_outside_the_json_so_stdout_stays_json(self):
        """🛑 `--json`'s stdout is a contract. `--to auto` announces its pick — a choice
        this tool made for you is never silent — so on that path it is carried IN the
        document instead of printed into the middle of it."""
        self.dead()
        meters = self.w.meters(personal=(5.0, 10.0, 60))
        got = self.rec(SID_A, "--to", "auto", CSM_METERS=str(meters))
        self.assertEqual(got["decision"]["row"], 6)
        self.assertIn("--to auto: personal", got["auto"])
        out = self.ok(self.revive(SID_A, "--to", "auto", CSM_METERS=str(meters)))
        self.assertIn("--to auto: personal", out)

    def test_a_link_that_names_no_transcript_here_is_refused_not_diagnosed(self):
        self.dead()
        self.refused(self.revive(link_of(LINK_BARE2)), "no transcript for that link here",
                     LINK_SID2)

    def test_a_home_that_could_not_be_READ_is_never_reported_as_not_holding_the_link(self):
        """🛑 "COULD NOT LOOK" IS NEVER A VERDICT — the doctrine this file states five times
        and rewrote `preflight`, `live_rows`, `owner_of` and `rc_job_owner` for, missed at
        the spec layer. Both link rungs used `Path.glob`, which swallows the PermissionError
        its own scan raises and yields nothing, so a locked-out home came back as "this home
        does not hold it" and the person was told the session they are rescuing is not on
        this machine.
        """
        t = self.w.session(self.personal, FORK_SID, cwd=self.cwd,
                           lines=[self.go(FORK_SID), self.clean(FORK_SID)])
        link = link_of(FORK_BARE)
        self.assertIn("resolved from the link", self.ok(self.revive(link)))
        for locked in (t.parent, self.personal / "projects"):
            mode = locked.stat().st_mode
            locked.chmod(0o000)
            try:
                err = self.refused(self.revive(link))
            finally:
                locked.chmod(mode)
            self.assertIn("could not finish looking", err)
            self.assertIn("PermissionError", err)
            self.assertNotIn("no transcript for that link here", err)
            self.assertNotIn("belong to a session this machine never ran", err)

    def test_one_id_in_two_homes_is_refused_and_never_silently_picked(self):
        """🛑 `move` AND `stop` BOTH REFUSE HERE, and revive did not. `revive_resolve`'s soft
        pass answers None for two different reasons — nothing matched, or several copies did
        — and the rung below it, which exists for a transcript every listing DROPS, answered
        for both by taking the first home in order. So revive acted on a stale snapshot, on
        the wrong account's quota, and wrote "You are still <wrong email>" into the note.
        """
        old = time.time() - 3 * 86400
        self.w.session(self.personal, SID_A, cwd=self.cwd,
                       lines=[self.go()], mtime=old)
        self.w.session(self.work, SID_A, cwd=self.cwd,
                       lines=[self.go(), self.clean()])
        err = self.refused(self.revive(SID_A))
        self.assertIn("matches 2 sessions", err)
        self.assertIn("work", err)
        self.assertIn("personal", err)
        # and `--account` is the cure the refusal can offer
        dec = self.row_of(SID_A, "--account", "work")
        self.assertEqual(dec["row"], 8)
        got = self.rec(SID_A, "--account", "personal")
        self.assertEqual(got["record"]["session"]["account"], "personal")

    def test_one_id_in_two_homes_is_refused_even_when_no_listing_carries_it(self):
        """The rung below the listing has to hold the same rule: a 0-byte pre-created
        transcript is dropped by `sessions_for` in BOTH homes, so `revive_row` is what
        answers, and it compared mtimes only WITHIN one home."""
        for home in (self.work, self.personal):
            self.w.session(home, LINK_SID, cwd=self.cwd, lines=[])
        err = self.refused(self.revive(link_of(LINK_BARE)))
        self.assertIn("2 account homes here hold a copy", err)
        self.assertIn("--account <handle>", err)
        dec = self.row_of(link_of(LINK_BARE), "--account", "personal")
        self.assertEqual(dec["row"], 2, "an empty transcript: nothing to continue")

    def test_the_move_gate_is_in_the_plan_and_not_left_for_the_real_run(self):
        """`--to` the account it is already in is the easiest flag to type by accident,
        and `check_target` is what says so — so the dry run says it too."""
        self.dead()
        dec = self.row_of(SID_A, "--to", "work")
        self.assertEqual((dec["row"], dec["action"], dec["exit"]), (6, "refuse", 2))
        self.assertIn("already in work", dec["refusal"])
        self.assertFalse(dec["note"])

    def test_a_home_that_cannot_run_it_is_a_refusal_on_every_row_that_starts_something(self):
        """🛑 A home whose login is gone takes a session up and then fails at its first
        token refresh, which looks exactly like a successful revive."""
        spare = self.w.account("spare")              # no login at all
        self.w.session(spare, SID_B, cwd=self.cwd,
                       lines=[self.go(SID_B), self.clean(SID_B)])
        dec = self.row_of(SID_B)
        self.assertEqual((dec["row"], dec["action"], dec["exit"]), (8, "refuse", 2))
        self.assertIn("holds no login", dec["refusal"])
        self.assertFalse(dec["note"], "nothing is started, so nothing is told anything")
        out = self.ok(self.revive(SID_B))
        self.assertIn("🛑 this home cannot run it", out)


class HomeUsable(InProc):
    """`check_target` split into "is this a legal move" and "can this home run a session".

    🛑 ZERO BEHAVIOUR CHANGE FOR `move`, which is why this class exists beside
    `Refusals(Base)` rather than instead of it: the five one-home refusals have to come out
    of `check_home_usable` word for word, in the same ORDER, with `check_target`'s two
    two-account ones still in front of them. `revive` resumes a session in the home it is
    already in for three of its actions, so those two would refuse exactly the thing it is
    for.
    """

    def setUp(self):
        super().setUp()
        self.mod.MACHINE = "here"
        self.src = self.account("work", email="me@work.example")

    def tgt(self, name="personal", **kw):
        kw.setdefault("email", "you@home.example")
        kw.setdefault("org", "org-2")
        return self.account(name, **kw)

    def home_why(self, tgt, accts=None):
        with self.assertRaises(self.mod.Refusal) as e:
            self.mod.check_home_usable(tgt, accts or [self.src, tgt])
        return str(e.exception)

    def target_why(self, tgt, accts=None):
        s = self.session(self.src)
        with self.assertRaises(self.mod.Refusal) as e:
            self.mod.check_target(s, tgt, accts or [self.src, tgt])
        return str(e.exception)

    def test_a_usable_home_passes_both_and_returns_the_credential_sentence(self):
        tgt = self.tgt()
        s = self.session(self.src)
        self.assertEqual(self.mod.check_home_usable(tgt, [self.src, tgt]),
                         self.mod.check_target(s, tgt, [self.src, tgt]))

    def test_the_five_one_home_refusals_are_the_same_sentence_from_either_door(self):
        for make, needle in (
                (lambda: self.tgt("gone", email=None), "holds no login"),
                (lambda: self.tgt("spare", email="someone@else.example"), None)):
            tgt = make()
            if needle:
                self.assertIn(needle, self.home_why(tgt))
                self.assertEqual(self.home_why(tgt), self.target_why(tgt))
        # a home that is not there at all
        tgt = self.tgt("missing")
        shutil.rmtree(str(tgt.home))
        self.assertIn("does not exist", self.home_why(tgt))
        self.assertEqual(self.home_why(tgt), self.target_why(tgt))

    def test_the_expected_login_check_is_the_same_too(self):
        self.mod.ACCOUNTS_FILE.write_text(
            "work %s\npersonal %s someone@else.example\n"
            % (self.src.home, self.root / "home" / ".claude-personal"))
        accts = self.mod.load_accounts()
        tgt = [a for a in accts if a.name == "personal"][0]
        self.tgt()                           # the home holds you@home.example
        self.assertIn("WRONG login", self.home_why(tgt, accts))
        self.assertEqual(self.home_why(tgt, accts), self.target_why(tgt, accts))

    def test_an_account_on_no_machine_is_refused_by_the_home_door_too(self):
        tgt = self.tgt()
        tgt.machines = frozenset()
        self.assertIn("is on no machine", self.home_why(tgt))

    def test_only_check_target_refuses_the_two_ACCOUNT_facts(self):
        """🛑 The point of the split. Revive resumes a session in its own home — the same
        account, the same login — and both of these would refuse that."""
        s = self.session(self.src)
        with self.assertRaises(self.mod.Refusal) as e:
            self.mod.check_target(s, self.src, [self.src])
        self.assertIn("already in work", str(e.exception))
        twin = self.account("twin", email="me@work.example")
        with self.assertRaises(self.mod.Refusal) as e:
            self.mod.check_target(s, twin, [self.src, twin])
        self.assertIn("same login", str(e.exception))
        # the same two homes, asked the one-home question: both usable
        self.assertEqual(self.mod.check_home_usable(self.src, [self.src]), "")
        self.assertEqual(self.mod.check_home_usable(twin, [self.src, twin]), "")

    def test_the_order_of_the_refusals_is_kept_where_two_of_them_both_match(self):
        """⚠️ A home holding the WRONG login must be reported as the wrong login, not as
        the same login — a reader given the other sentence goes and fixes the wrong thing.
        That is what `before_login` in `check_home_usable` is for."""
        self.mod.ACCOUNTS_FILE.write_text(
            "work %s\ntwin %s someone@else.example\n"
            % (self.src.home, self.root / "home" / ".claude-twin"))
        self.account("twin", email="me@work.example")     # the SOURCE's own login
        accts = self.mod.load_accounts()
        twin = [a for a in accts if a.name == "twin"][0]
        self.assertIn("WRONG login", self.target_why(twin, accts))

    def test_the_credential_probe_is_last_and_says_the_same_thing_either_way(self):
        """🛑 The state file is not the credential, and this check stays LAST — it is the
        one that costs a Keychain question, and everything cheaper has already refused."""
        self.mod.LOGIN_PROBE = "false"
        tgt = self.tgt()
        why = self.home_why(tgt)
        self.assertIn("its credential is GONE", why)
        self.assertEqual(why, self.target_why(tgt))


# ------------------------------------------------------------- the revive, carried out

class ReviveRun(Base):
    """Shared fixtures for `csm revive` WITHOUT `--dry-run`: it really starts, relays, proves.

    🛑 FIXTURES ONLY, as everywhere in this file. The `claude` is the stand-in at the top of
    this file, the `tmux` is the stand-in at the top of this file, and the only real processes
    are the `/bin/sleep`s that stand for a running session's pid. Nothing talks to claude.ai,
    no real config home is read, nothing is signalled and no real session is ever messaged.
    """

    def setUp(self):
        super().setUp()
        self.cwd = str(self.w.work)

    # --- what the transcript says -----------------------------------------
    def go(self, sid=SID_A):
        return user("run the campaign", self.cwd, sid, uuid="u1")

    def clean(self, sid=SID_A):
        return assistant("done", self.cwd, sid, uuid="a1", parent="u1")

    def limit(self, resets, sid=SID_A, text="You've hit your session limit · resets 6:30pm",
              uuid="a2", parent="a1"):
        """⚠️ `uuid` IS THE STOP EVENT'S OWN NAME, and it is a parameter because the
        at-most-once key of an unattended wake is `(local id, that uuid)`: a test about a
        session that stops TWICE has to be able to give the second stop a name of its own."""
        return assistant(text, self.cwd, sid, error="usage_limit_reached", resets=resets,
                         shape="rate_limit", uuid=uuid, parent=parent)

    def dead(self, sid=SID_A, lines=None, home=None):
        return self.w.session(home if home is not None else self.work, sid, cwd=self.cwd,
                              lines=lines if lines is not None
                              else [self.go(sid), self.clean(sid)])

    def alive(self, sid=SID_A, status="idle", lines=None, name="rc-name", mode=""):
        """A session with a transcript AND a live, provable registry row.

        `mode` puts a real `--permission-mode` on that process's own command line, which is
        the only measurement of the mode a running session is in.
        """
        t = self.dead(sid, lines)
        p = (self.w.spawn(argv_tail=("--resume", sid, "--permission-mode", mode))
             if mode else self.w.spawn())
        self.w.live(self.work, sid, p.pid, cwd=self.cwd, status=status, name=name)
        return t, p

    # --- the command ------------------------------------------------------
    def revive(self, spec, *extra, **env):
        # The window's own claude registers a row and then stays up long enough for the
        # relay and the proof; no passing test ever waits this out.
        env.setdefault("FAKE_CLAUDE_REGISTER", "1")
        env.setdefault("FAKE_CLAUDE_SLEEP", "15")
        return self.w.run("revive", spec, *extra, **env)

    def rec(self, spec, *extra, **env):
        r = self.revive(spec, "--json", *extra, **env)
        return json.loads(r.stdout), r

    def lines_of(self, t):
        return [json.loads(x) for x in t.read_text().splitlines() if x.strip()]

    def assertNothingStarted(self, r):
        self.assertEqual(self.w.claude_calls(wait=0.4), [], r.stdout + r.stderr)
        self.assertEqual([c for c in self.w.tmux_log()
                          if c[:1] in (["new-window"], ["new-session"])], [])


class ReviveWake(ReviveRun):
    """Row 5: it is UP and idle, so nothing is started — the note is relayed into it.

    🛑 THE RELAY IS THE ONLY CARRIER, measured in the spike (CLI 2.1.312, Wed 28 Oct 2026): a
    headless `claude -p` under the session's own home, calling its SendMessage tool once, so
    the note lands recorded as a PEER message and not as the user's own typing.
    """

    def test_an_idle_session_is_woken_and_the_turn_is_proved(self):
        t, _p = self.alive()
        before = t.stat().st_size
        out = self.ok(self.revive(SID_A))
        self.assertIn("✅ revived, and it has taken a turn", out)
        self.assertIn("it answered: an assistant line appeared past", out)
        # nothing was STARTED: a wake opens no window at all
        self.assertEqual([c for c in self.w.tmux_log()
                          if c[:1] in (["new-window"], ["new-session"])], [])
        # the relay really delivered, and the session really answered
        got = self.w.relay_calls()
        self.assertEqual(len(got), 1, got)
        self.assertEqual(got[0]["target"], "rc-name")
        kinds = [(d.get("type"), d.get("turnOrigin")) for d in self.lines_of(t)]
        self.assertIn(("user", "peer"), kinds)
        self.assertEqual(kinds[-1][0], "assistant")
        self.assertGreater(t.stat().st_size, before)

    def test_a_real_wake_reports_the_mode_it_is_RUNNING_in_and_applies_none(self):
        """🛑 MEASURED LIVE ON CLI 2.1.312, Wed 28 Oct 2026: a session running
        `--permission-mode bypassPermissions`, woken with `--permission-mode plan`, was
        reported as `mode plan (from --permission-mode)` while it kept running in bypass.
        A wake starts no process, so the only honest line is what it is already in — and the
        flag that was not carried out says so.
        """
        self.alive(mode="bypassPermissions")
        got, r = self.rec(SID_A, "--permission-mode", "plan")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(got["decision"]["row"], 5)
        self.assertEqual(got["mode"]["mode"], "bypassPermissions")
        self.assertIs(got["mode"]["applied"], False)
        self.assertIn("unchanged: a wake starts nothing", got["mode"]["why"])
        self.assertIn("NOT put it in plan", got["decision"]["what"])
        # nothing was started at all, so no process got any `--permission-mode` but the
        # relay's own measured one
        self.assertEqual([c for c in self.w.claude_calls() if "--resume" in c["argv"]], [])
        relay = [c for c in self.w.claude_calls() if "-p" in c["argv"]][0]["argv"]
        self.assertEqual(relay[relay.index("--permission-mode") + 1], "bypassPermissions")
        self.assertIn("mode         bypassPermissions (unchanged: a wake starts nothing",
                      r.stderr)

    def test_the_relay_is_the_measured_command_line_in_the_sessions_own_home(self):
        self.alive()
        self.ok(self.revive(SID_A))
        call = [c for c in self.w.claude_calls() if "-p" in c["argv"]][0]
        argv = call["argv"]
        self.assertEqual(argv[0], "-p")
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertTrue(argv[argv.index("--name") + 1].startswith("csm revive ("),
                        argv[argv.index("--name") + 1])
        # 🛑 under the TARGET's home, and in a folder of csm's own: a `-p` run files a
        # transcript of its own under the project folder of its cwd.
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], str(self.work))
        self.assertEqual(os.path.realpath(call["cwd"]),
                         os.path.realpath(str(self.w.state / "relay")))
        # 🛑 `stdin_tty` CANNOT FAIL IN AN AUTOMATED RUN (the fake's own note says why), so
        # what is asserted is the identity of fd 0: `stdin=subprocess.DEVNULL` makes it
        # /dev/null, and an inherited stdin — the thing his 13 Oct 2026 rule forbids a `-p`
        # run to have — is anything else. Removing that one keyword now fails this test.
        self.assertTrue(self.w.relay_calls()[0]["stdin_devnull"],
                        "stdin must be /dev/null, not inherited")
        self.assertFalse(self.w.relay_calls()[0]["stdin_tty"])

    def test_the_relays_environment_is_scrubbed_like_every_other_child(self):
        self.alive()
        self.ok(self.revive(SID_A, CLAUDECODE="1", CLAUDE_CODE_OAUTH_TOKEN="tok",
                            ANTHROPIC_API_KEY="key", CLAUDE_CODE_SESSION_ID="9" * 8))
        env = [c for c in self.w.claude_calls() if "-p" in c["argv"]][0]["env"]
        for gone in ("CLAUDECODE", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                     "CLAUDE_CODE_SESSION_ID"):
            self.assertNotIn(gone, env)

    def test_the_note_is_relayed_verbatim_and_between_the_markers(self):
        """The note the run REPORTS and the note the relay was handed are one string.

        ⚠️ Against the run's own document, not against a `--dry-run` a second earlier: the
        note stamps when the session stopped and how long ago, so two runs a second apart
        word that clause differently — which is the note being honest, not a drift.
        """
        self.alive()
        got, _r = self.rec(SID_A)
        self.assertEqual(self.w.relay_calls()[0]["note"], got["note"])
        self.assertIn("written by the tool; the user did not type this", got["note"])
        # ⚠️ `named` is the fixture counting rows on disk, with no proof of any of them — it
        # was never a guarantee csm provided. What csm provides is the refusal pinned by
        # `test_a_name_that_names_two_live_sessions_is_refused_before_anything_is_sent`.
        self.assertEqual(self.w.relay_calls()[0]["named"], 1)

    def test_the_registry_going_busy_is_proof_on_its_own(self):
        """A short answer can be over before any poll sees `busy`, and a long one may not
        have written its line yet — so either proof counts."""
        t, _p = self.alive()
        before = t.read_bytes()
        out = self.ok(self.revive(SID_A, FAKE_RELAY_MODE="busy"))
        self.assertIn("its registry row went busy", out)
        self.assertEqual(t.read_bytes(), before, "nothing was written to the transcript")

    def test_a_relay_that_claims_success_and_sends_nothing_is_NOT_proof(self):
        """🛑 The proof is the session's own behaviour, never the relay's word for it."""
        t, _p = self.alive()
        before = t.read_bytes()
        r = self.revive(SID_A, FAKE_RELAY_MODE="quiet", CSM_REVIVE_PROVE_S="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("it is up, and NOT proved (exit 1)", r.stdout)
        self.assertIn("nothing within 1s", r.stdout)
        self.assertIn("it is up but idle: open", r.stdout)
        self.assertEqual(t.read_bytes(), before)

    def test_a_failed_relay_is_started_not_proved_and_says_what_to_tap(self):
        self.alive()
        r = self.revive(SID_A, FAKE_RELAY_MODE="error")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("NOT delivered", r.stdout)
        self.assertIn("SendMessage was not available", r.stdout)
        self.assertIn("it is up but idle: open", r.stdout)

    def test_a_relay_that_crashes_is_a_measurement_and_not_a_traceback(self):
        self.alive()
        r = self.revive(SID_A, FAKE_RELAY_MODE="crash")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no JSON result", r.stdout)
        self.assertIn("SendMessage is not a tool here", r.stdout)

    def test_a_held_relay_times_out_instead_of_waiting_for_a_person(self):
        """🛑 His rule of 13 Oct 2026: nothing an agent runs may wait for a person. A `-p`
        run in a home whose default mode is not bypassPermissions was never measured, so a
        relay that does not come back is bounded and reported."""
        self.alive()
        start = time.time()
        r = self.revive(SID_A, FAKE_RELAY_MODE="held", FAKE_RELAY_HOLD="20",
                        CSM_RELAY_TIMEOUT_S="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("did not finish within", r.stdout)
        self.assertIn("HELD for a person", r.stdout)
        self.assertLess(time.time() - start, 40, "it waited the hold out")

    def test_a_live_row_with_no_name_cannot_be_addressed_and_says_so(self):
        self.alive(name="")
        r = self.revive(SID_A)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("carries no `name`", r.stdout)
        self.assertEqual(self.w.relay_calls(), [], "nothing was sent to nobody")

    def test_a_session_that_stops_between_the_diagnosis_and_the_wake_is_refused(self):
        """🛑 "It is up but idle" would be false about a session that has ended, and nothing
        was sent anywhere — so this is a refusal, and the next run resumes or forks it."""
        _t, p = self.alive()
        self.w.server()                  # so the diagnosis really asks lsof, on any machine
        # the row is proved by the diagnosis and gone a moment later: `FAKE_LSOF_ARM_FROM`
        # lands between those two reads
        gone = self.w.root / "it-ended.json"
        gone.write_text("{}")
        r = self.revive(SID_A, FAKE_LSOF_ARM_FROM=str(gone),
                        FAKE_LSOF_ARM_TO=str(self.work / "sessions" / ("%d.json" % p.pid)))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("is no longer running", r.stderr)
        self.assertEqual(self.w.relay_calls(), [])
        # ⚠️ and a refusal raised mid-action is still recorded: the record is how an
        # unattended caller finds out which gate stopped it
        rows = [json.loads(x) for x in
                (self.w.state / "revive.jsonl").read_text().splitlines() if x.strip()]
        self.assertEqual((rows[0]["row"], rows[0]["exit"]), (5, 2))
        self.assertIs(rows[0]["started"], False)

    def test_a_row_that_cannot_be_PROVED_in_that_last_second_sends_nothing(self):
        """🛑 `live_name`'s own 🛑, which the suite measured nothing of: "a registry file
        outlives its process, so an unproved row is no row at all here — messaging the name
        of a dead row would send the note to whatever answers to it next."

        The adjacent test arms the row to VANISH, so `live_rows` returns nothing and
        `live_name` is `{}` either way. This arms the row that is still ON DISK and no longer
        provable, which is the shape the brief names: rows survive a SIGKILL until a live
        session sweeps them. With the gate removed the whole suite passes; with this, it does
        not.
        """
        _t, p = self.alive()
        self.w.server()                  # so the diagnosis really asks lsof, on any machine
        row = self.work / "sessions" / ("%d.json" % p.pid)
        stale = self.w.root / "stale.json"
        d = json.loads(row.read_text())
        d["procStart"] = "Mon Jan  1 00:00:00 2024"     # same pid, a different process
        stale.write_text(json.dumps(d))
        r = self.revive(SID_A, FAKE_LSOF_ARM_FROM=str(stale), FAKE_LSOF_ARM_TO=str(row))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("could not be proved in the second before the note was sent",
                      r.stderr)
        self.assertEqual(self.w.relay_calls(), [], "nothing was sent to a dead row's name")

    def test_a_name_that_names_two_live_sessions_is_refused_before_anything_is_sent(self):
        """🛑 SendMessage ADDRESSES A SESSION BY ITS NAME, and nothing checked that the name
        was unique. `relay_note` refuses only an EMPTY name, so the note could land in an
        unrelated live session's conversation — a message in his conversation that he did not
        type, in the wrong conversation — while `prove_turn` watches the INTENDED session and
        reports "it is up but idle" with no hint of the misdelivery.

        The suite's fake relay already MEASURED this (`named`), and two tests asserted
        `named == 1` as though it were a guarantee csm provided; it was a property of the
        fixture.
        """
        self.alive()                                      # SID_A, name "rc-name"
        _t2, p2 = self.alive(sid=SID_B)                   # unrelated, same name
        r = self.revive(SID_A)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("is not unique in work", r.stderr)
        self.assertIn(SID_B[:8], r.stderr)
        self.assertIn("--name", r.stderr)
        self.assertEqual(self.w.relay_calls(), [], "nothing was sent to an ambiguous name")
        # 🛑 AND THE SECOND ROW IS PROVED, not counted: the same row with no recorded start
        # time cannot be proved, so it is a stale row and not a second answerer — and the
        # wake goes through exactly as it did before.
        # ⚠️ The fixture's own `named` still reads 2 — it counts rows on disk, with no proof
        # of any of them — which is exactly why `named == 1` elsewhere was never a guarantee
        # csm provided. What csm provides is this: the row it cannot prove is not a twin.
        self.w.live(self.work, SID_B, p2.pid, cwd=self.cwd, proc_start="")
        out = self.ok(self.revive(SID_A))
        self.assertIn("✅ revived", out)
        self.assertEqual(self.w.relay_calls()[0]["target"], "rc-name")

    def test_every_revive_leaves_one_record_and_it_holds_no_note_text(self):
        """🛑 `revive.jsonl` is a record of what ran: the at-most-once triple (the local id,
        the bridge id and the transcript's size at diagnosis), the row, the action and the
        exit. Never the note, which is conversation text."""
        self.alive()
        self.ok(self.revive(SID_A))
        p = self.w.state / "revive.jsonl"
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        rows = [json.loads(x) for x in p.read_text().splitlines() if x.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["local_id"], rows[0]["row"], rows[0]["action"],
                          rows[0]["exit"]), (SID_A, 5, "wake", 0))
        self.assertIsInstance(rows[0]["bytes"], int)
        self.assertNotIn("written by the tool", p.read_text())

    def test_the_json_run_keeps_stdout_pure_and_carries_what_happened(self):
        self.alive()
        got, r = self.rec(SID_A)
        self.assertIs(got["dry_run"], False)
        self.assertEqual(got["exit"], 0)
        self.assertEqual(got["result"]["action"], "wake")
        self.assertIs(got["result"]["proved"], True)
        self.assertIs(got["result"]["relay"]["ok"], True)
        self.assertTrue(got["result"]["relay"]["msg_id"].startswith("msg_"),
                        got["result"]["relay"])
        self.assertIn("REVIVE  run the campaign", r.stderr)      # the prose, out of the way
        self.assertNotIn("REVIVE  run the campaign", r.stdout)

    def test_the_relays_own_argv_in_the_record_does_not_carry_the_note(self):
        """The note is conversation text; the command line is in the log and the record."""
        self.alive()
        got, _r = self.rec(SID_A)
        joined = " ".join(got["result"]["relay"]["argv"])
        self.assertIn("<the instruction and the note>", joined)
        self.assertNotIn("written by the tool", joined)


class ReviveResumeInPlace(ReviveRun):
    """Rows 7 and 8: start it again in its own home, in `moved-<id8>`, and relay the note.

    🛑 ROW 7'S PROOF IS THE LINK ITSELF. A self-hosted session re-attaches its own claude.ai
    session, so the link the window prints must be the one it had; a new link means nothing
    re-attached, and the note csm was about to send ("the link you had still opens this
    conversation") would be false — so it is not sent.
    """

    SELF_HOSTED = link_of("01SelfHosted00001")

    def self_hosted(self, sid=SID_A):
        return self.dead(sid, lines=[self.go(sid), self.clean(sid), BRIDGE_LINE])

    def test_a_self_hosted_session_resumes_onto_its_own_link_and_is_proved(self):
        t = self.self_hosted()
        out = self.ok(self.revive(SID_A, FAKE_CLAUDE_LINK=self.SELF_HOSTED))
        self.assertIn("✅ revived, and it has taken a turn", out)
        self.assertIn(self.SELF_HOSTED, out)
        self.assertEqual(self.w.windows().get("csm-work"), ["moved-11111111"])
        start = [c for c in self.w.claude_calls() if "--resume" in c["argv"]][0]
        argv = start["argv"]
        self.assertEqual(argv[-2:], ["--resume", SID_A])
        self.assertNotIn("--fork-session", argv)
        self.assertNotIn("--session-id", argv)
        self.assertTrue(any(a.startswith("--remote-control=") for a in argv), argv)
        self.assertEqual(start["env"]["CLAUDE_CONFIG_DIR"], str(self.work))
        # and the note arrived, as a peer message, in the session's own transcript
        self.assertEqual(self.w.relay_calls()[0]["sid"], SID_A)
        self.assertIn("the link you had still opens this conversation",
                      self.w.relay_calls()[0]["note"])
        self.assertIn(("user", "peer"),
                      [(d.get("type"), d.get("turnOrigin")) for d in self.lines_of(t)])

    def test_a_NEW_link_on_a_resume_in_place_is_not_called_a_revive(self):
        """The fake prints the default link, which is not the one this session had — exactly
        what a resume that failed to re-attach looks like."""
        self.self_hosted()
        r = self.revive(SID_A)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("came up on a NEW link", r.stdout)
        self.assertIn(self.SELF_HOSTED, r.stdout)
        self.assertEqual(self.w.relay_calls(), [], "the note would have been false")
        self.assertIn("--new-link` forks deliberately", r.stdout)

    def test_a_terminal_session_resumes_and_says_the_link_is_new_exposure(self):
        self.dead()
        out = self.ok(self.revive(SID_A))
        self.assertIn("resume it in place — it gets a NEW claude.ai link", out)
        self.assertIn("new exposure", out)
        self.assertIn("✅ revived", out)
        self.assertIn("it was not a Remote Control session before",
                      self.w.relay_calls()[0]["note"])

    def test_a_window_that_prints_no_link_is_started_not_proved_and_sends_nothing(self):
        self.self_hosted()
        r = self.revive(SID_A, FAKE_CLAUDE_NOURL="1", FAKE_CLAUDE_SLEEP="0.3")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("printed no claude.ai link", r.stdout)
        self.assertIn("the note was NOT sent", r.stdout)
        self.assertEqual(self.w.relay_calls(), [])

    def test_csm_stop_ends_the_window_a_resume_opened(self):
        self.self_hosted()
        self.ok(self.revive(SID_A, FAKE_CLAUDE_LINK=self.SELF_HOSTED))
        # ⚠️ the whole id, because an all-digit spec is a row number from `csm list`
        out = self.ok(self.w.run("stop", SID_A))
        self.assertIn("The window is gone", out)
        self.assertEqual(self.w.windows().get("csm-work", []), [])

    def test_the_mode_asked_for_reaches_the_window(self):
        self.self_hosted()
        out = self.ok(self.revive(SID_A, "--permission-mode", "bypassPermissions",
                                  FAKE_CLAUDE_LINK=self.SELF_HOSTED))
        self.assertIn("mode         bypassPermissions", out)
        argv = [c for c in self.w.claude_calls() if "--resume" in c["argv"]][0]["argv"]
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")


class ReviveFork(ReviveRun):
    """Row 10: a Remote Control server child, onto a NEW session id and a new link.

    🛑 CSM CHOOSES THE ID (`--session-id <new uuid4>` beside `--fork-session`), because every
    id-keyed part of this tool — the window name, `preflight`, `csm stop`'s authorisation —
    needs an id csm knew before anything started. Bare `--fork-session` mints one it never
    learns.
    """

    def child(self):
        return self.w.session(self.work, FORK_SID, cwd=self.cwd,
                              lines=[self.go(FORK_SID), self.clean(FORK_SID)])

    def forked(self, *extra, **env):
        got, r = self.rec(link_of(FORK_BARE), "--new-link", *extra, **env)
        return got["result"], r

    def test_a_fork_writes_a_new_id_and_leaves_the_old_file_byte_identical(self):
        old = self.child()
        before = old.read_bytes()
        res, r = self.forked()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new = res["new_id"]
        self.assertTrue(re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
                                 r"[0-9a-f]{4}-[0-9a-f]{12}$", new), new)
        self.assertNotEqual(new, FORK_SID)
        self.assertEqual(old.read_bytes(), before, "the old transcript must not be touched")
        self.assertTrue(Path(res["fork_file"]).is_file(), res)
        self.assertEqual(Path(res["fork_file"]).name, new + ".jsonl")
        # the window, and the command line, are named for the NEW id
        self.assertEqual(self.w.windows().get("csm-work"), ["moved-" + new[:8]])
        argv = [c for c in self.w.claude_calls() if "--resume" in c["argv"]][0]["argv"]
        self.assertIn("--fork-session", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], new)
        self.assertEqual(argv[-2:], ["--resume", FORK_SID])

    def test_the_note_names_the_fork_and_warns_loudly_about_the_old_link(self):
        self.child()
        res, r = self.forked()
        note = self.w.relay_calls()[0]["note"]
        self.assertIn("csm FORKED it: this copy is %s" % res["new_id"][:8], note)
        self.assertIn("The old link still opens the OLD copy", note)
        self.assertIn("🛑 OLD LINK", r.stderr)
        self.assertIn(link_of(FORK_BARE), r.stderr)
        self.assertIn("is untouched", r.stderr)

    def test_the_relayed_turn_lands_in_the_FORKS_transcript(self):
        old = self.child()
        res, _r = self.forked()
        fork = Path(res["fork_file"])
        self.assertIn(("user", "peer"),
                      [(d.get("type"), d.get("turnOrigin")) for d in self.lines_of(fork)])
        self.assertNotIn("peer", old.read_text())
        self.assertEqual(self.w.relay_calls()[0]["sid"], res["new_id"])
        self.assertIs(res["proved"], True)

    def test_the_record_of_a_FORK_holds_no_note_text(self):
        """🛑 THE ONE PATH WHERE THE `note` FILTER IS NOT A NO-OP, and the only test of that
        filter ran on the other one. A wake's result dict has no `note` key at all, so
        `revive_record`'s `if k != "note"` had nothing to drop and the assertion could not
        fail; `revive_fork` is the one action that sets `out["note"]`, because the note is
        rebuilt to name the fork's own new id.
        """
        self.child()
        got, _r = self.rec(link_of(FORK_BARE), "--new-link")
        self.assertIn("written by the tool", got["note"],
                      "`--json` DOES report the note that was sent")
        self.assertNotIn("note", got["result"], "but not under `result`")
        rows = [json.loads(x) for x in
                (self.w.state / "revive.jsonl").read_text().splitlines() if x.strip()]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("note", rows[0])
        self.assertNotIn("written by the tool", json.dumps(rows[0]))
        self.assertNotIn("written by the tool",
                         (self.w.state / "revive.jsonl").read_text())
        # and the same holds of the log line beside it
        self.assertNotIn("written by the tool", (self.w.state / "log").read_text())

    def test_stop_ends_a_forked_window_by_its_NEW_id(self):
        """🛑 This is what `--session-id` buys: `csm stop` can only end a window it can name
        and a session it can find, and both key on the id csm chose."""
        self.child()
        res, _r = self.forked()
        out = self.ok(self.w.run("stop", res["new_id"]))
        self.assertIn("The window is gone", out)
        self.assertEqual(self.w.windows().get("csm-work", []), [])

    def test_a_link_without_the_new_transcript_is_not_a_fork_and_sends_nothing(self):
        """🛑 A LINK IS NOT A FORK. If `<new>.jsonl` never appeared, whatever is in that
        window is writing something else, and the note must not be sent to it."""
        self.child()
        got, r = self.rec(link_of(FORK_BARE), "--new-link", FAKE_CLAUDE_NOFORK="1",
                          CSM_CONNECT_WAIT="2")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("wrote no transcript for", got["result"]["why"])
        self.assertEqual(self.w.relay_calls(), [])

    def test_without_new_link_the_same_session_keeps_its_link_and_starts_nothing(self):
        self.child()
        r = self.w.run("revive", link_of(FORK_BARE))
        self.ok(r)
        self.assertIn("keep-link", r.stdout)
        self.assertNothingStarted(r)


class ReviveForkOnNewLink(ReviveRun):
    """Row 11: `--new-link` on a dead session that is NOT a server child — a fresh copy.

    🛑 MEASURED LIVE ON CLI 2.1.312, Wed 28 Oct 2026: `csm revive <dead self-hosted session>
    --new-link --dry-run` took row 7 — "resume it in place, on the same claude.ai link" —
    and said nothing about the flag, because `new_link` was read only at the row-9/row-10
    split and `dropped` named only `--to` and `--say`. The mechanics are row 10's, because
    they are one function: `--fork-session` with an id csm chose, a window named for the new
    id, the old file left byte-identical, and the loud warning afterwards.
    """

    def test_new_link_forks_a_dead_self_hosted_session_onto_a_new_id(self):
        old = self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        before = old.read_bytes()
        got, r = self.rec(SID_A, "--new-link")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        res, new = got["result"], got["result"]["new_id"]
        self.assertEqual((got["decision"]["row"], got["decision"]["action"]),
                         (11, "fork"))
        self.assertNotEqual(new, SID_A)
        self.assertEqual(old.read_bytes(), before, "the old transcript is never touched")
        self.assertEqual(Path(res["fork_file"]).name, new + ".jsonl")
        self.assertEqual(self.w.windows().get("csm-work"), ["moved-" + new[:8]])
        argv = [c for c in self.w.claude_calls() if "--resume" in c["argv"]][0]["argv"]
        self.assertIn("--fork-session", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], new)
        self.assertEqual(argv[-2:], ["--resume", SID_A])
        # the note and the warning both name the link it had, which still opens the old copy
        self.assertIn("The old link still opens the OLD copy",
                      self.w.relay_calls()[0]["note"])
        self.assertIn("🛑 OLD LINK", r.stderr)
        self.assertIn("https://claude.ai/code/session_01SelfHosted00001", r.stderr)

    def test_a_forked_terminal_session_warns_about_the_old_COPY_and_names_no_link(self):
        """A terminal session never had a claude.ai link: the old-link sentence would be
        false, and inventing one is what row 9 refuses to do."""
        old = self.dead()
        before = old.read_bytes()
        got, r = self.rec(SID_A, "--new-link")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(got["decision"]["row"], 11)
        self.assertEqual(old.read_bytes(), before)
        self.assertIn("🛑 OLD COPY", r.stderr)
        self.assertNotIn("🛑 OLD LINK", r.stderr)
        note = self.w.relay_calls()[0]["note"]
        self.assertIn("had no claude.ai link of its own", note)
        self.assertNotIn("The old link still opens", note)

    def test_the_mode_asked_for_reaches_a_forked_window(self):
        """Row 11 starts a process, so `--permission-mode` IS applied here — the other half
        of the wake's contract."""
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        got, r = self.rec(SID_A, "--new-link", "--permission-mode", "acceptEdits")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIs(got["mode"]["applied"], True)
        self.assertEqual(got["mode"]["mode"], "acceptEdits")
        argv = [c for c in self.w.claude_calls() if "--resume" in c["argv"]][0]["argv"]
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "acceptEdits")

    def test_stop_ends_the_window_by_the_forks_new_id(self):
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        got, _r = self.rec(SID_A, "--new-link")
        out = self.ok(self.w.run("stop", got["result"]["new_id"]))
        self.assertIn("The window is gone", out)
        self.assertEqual(self.w.windows().get("csm-work", []), [])


class ReviveMove(ReviveRun):
    """Row 6: `--to` another account — `do_move` unchanged, then the relay into the copy."""

    def test_a_dead_session_moves_and_the_note_is_relayed_into_the_copy(self):
        src = self.dead()
        before = src.read_bytes()
        out = self.ok(self.revive(SID_A, "--to", "personal"))
        self.assertIn("✅ moved. It runs as personal", out)
        self.assertIn("✅ revived, and it has taken a turn", out)
        dest = self.personal / "projects" / src.parent.name / (SID_A + ".jsonl")
        self.assertTrue(dest.is_file())
        self.assertEqual(src.read_bytes(), before, "the source is never written to")
        # the move's own isMeta note is in the COPY, and the revive's note came by relay
        kinds = [(d.get("type"), d.get("isMeta"), d.get("turnOrigin"))
                 for d in self.lines_of(dest)]
        self.assertIn(("user", True, None), kinds)        # the move note
        self.assertIn(("user", True, "peer"), kinds)      # the relayed revive note
        got = self.w.relay_calls()
        self.assertEqual(len(got), 1, got)
        self.assertEqual(got[0]["config_dir"], str(self.personal))
        self.assertIn("csm moved it from me@work.example to me@home.example", got[0]["note"])

    def test_the_relay_comes_AFTER_the_move_and_not_instead_of_it(self):
        self.dead()
        self.ok(self.revive(SID_A, "--to", "personal"))
        kinds = ["relay" if "-p" in c["argv"] else "start" for c in self.w.claude_calls()]
        self.assertEqual(kinds, ["start", "relay"], kinds)

    def test_a_move_that_does_not_connect_relays_nothing(self):
        self.dead()
        r = self.revive(SID_A, "--to", "personal", FAKE_CLAUDE_NOURL="1",
                        FAKE_CLAUDE_RC="1", FAKE_CLAUDE_SLEEP="0.2")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("the move did not connect", r.stdout)
        self.assertEqual(self.w.relay_calls(), [])

    def test_to_auto_announces_its_pick_and_moves_there(self):
        self.dead()
        meters = self.w.meters(personal=(5.0, 10.0, 60))
        out = self.ok(self.revive(SID_A, "--to", "auto", CSM_METERS=str(meters)))
        self.assertIn("--to auto: personal", out)
        self.assertIn("✅ revived", out)

    def test_a_live_idle_session_is_woken_and_NOT_moved(self):
        """⚠️ A `--to` typed at a session that is still running is not carried out: a move
        copies a transcript and this one has a live writer."""
        self.alive()
        out = self.ok(self.revive(SID_A, "--to", "personal"))
        self.assertIn("NOT move it to personal", out)
        self.assertFalse((self.personal / "projects").exists() and
                         list((self.personal / "projects").glob("*/*.jsonl")))


class ReviveKeepLink(ReviveRun):
    """Row 9: a dead server child in the same account — print the one tap, start NOTHING.

    🛑 AND WAIT FOR NOTHING. Only he can open the link, and the server respawns the child
    when it is opened; a tool that polled here for a person to tap something would be the one
    shape his 13 Oct 2026 rule forbids inside an agent's own session.
    """

    def test_it_prints_the_one_tap_and_starts_nothing(self):
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        r = self.w.run("revive", link_of(LINK_BARE))
        out = self.ok(r)
        self.assertIn("open          " + link_of(LINK_BARE), out)
        self.assertIn("and say continue", out)
        self.assertIn("then          `csm revive bf974a77`", out)
        self.assertIn("--new-link", out)
        self.assertNothingStarted(r)
        self.assertEqual(self.w.relay_calls(), [])

    def test_it_says_whether_the_server_that_would_respawn_it_is_up(self):
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        p = self.w.server("myproject")
        self.w.lsof_map.write_text(json.dumps({str(p.pid): self.cwd}))
        out = self.ok(self.w.run("revive", link_of(LINK_BARE)))
        self.assertIn("server        a server is up in this folder: pid %d (myproject)"
                      % p.pid, out)

    def test_the_record_says_nothing_was_started(self):
        self.w.session(self.work, LINK_SID, cwd=self.cwd,
                       lines=[self.go(LINK_SID), self.clean(LINK_SID)])
        self.ok(self.w.run("revive", link_of(LINK_BARE)))
        rows = [json.loads(x) for x in
                (self.w.state / "revive.jsonl").read_text().splitlines() if x.strip()]
        self.assertEqual((rows[0]["row"], rows[0]["action"], rows[0]["exit"]),
                         (9, "keep-link", 0))
        self.assertIs(rows[0]["started"], False)


class ReviveRefusals(ReviveRun):
    """Every refusal, and each one writes nothing and starts nothing.

    🛑 ONE `csm: <msg>` LINE ON STDERR AND EXIT 2 — cures included, because a reader who only
    ever sees stderr (a hook, a scheduled pass, a phone notification) must be told what to do
    and not only what is wrong.
    """

    def refuse(self, spec, *extra, **env):
        """The refusal sentence, having checked that it is ONE line and that nothing ran.

        ⚠️ `CSM_LOGIN_PROBE` announces itself on stderr on every run it is set — which is
        every run in this suite — so the refusal is the one `csm:` line that is not that.
        """
        r = self.revive(spec, *extra, **env)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        said = [x for x in r.stderr.splitlines()
                if x.startswith("csm: ") and "CSM_LOGIN_PROBE" not in x]
        self.assertEqual(len(said), 1, r.stderr)
        self.assertNothingStarted(r)
        self.assertEqual(self.w.relay_calls(), [])
        return said[0]

    def test_a_bot_owns_it(self):
        self.dead()
        d = self.w.root / "owners"
        d.mkdir()
        (d / "chatbot.json").write_text(json.dumps({"session_id": SID_A}))
        self.assertIn("chatbot", self.refuse(SID_A, CSM_BOTS_DIR=str(d)))

    def test_a_scheduled_pass_owns_it_and_has_its_own_revive(self):
        self.dead()
        d = self.w.root / "rc-jobs"
        d.mkdir()
        (d / "daily.session").write_text("uuid=%s\n" % SID_A)
        self.assertIn("rc_job daily --revive", self.refuse(SID_A, CSM_RC_JOBS_DIR=str(d)))

    def test_an_empty_transcript_has_nothing_to_continue(self):
        t = self.dead(lines=[])
        t.write_text("")
        self.assertIn("nothing to continue", self.refuse(SID_A))

    def test_a_limit_still_in_force_is_refused_with_its_reset_and_its_cures(self):
        self.dead(lines=[self.go(), self.clean(), self.limit(time.time() + 3600)])
        why = self.refuse(SID_A)
        self.assertIn("still inside the session limit", why)
        self.assertIn("wait until", why)
        self.assertIn("--to auto", why)

    def test_a_monthly_spend_limit_says_waiting_is_not_the_cure(self):
        self.dead(lines=[self.go(), self.clean(),
                         self.limit(time.time() + 3600,
                                    text="You've hit your monthly spend limit · raise it "
                                         "at claude.ai/settings/usage")])
        why = self.refuse(SID_A)
        self.assertIn("waiting does NOT clear a monthly-spend limit", why)
        self.assertNotIn("wait until", why)

    def test_an_archived_session_is_refused_until_unarchive_is_passed(self):
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE, STATUS_LINE, ENDED_LINE])
        self.assertIn("--unarchive", self.refuse(SID_A))
        # the link it has to come back on is the one the plan names, not one guessed here
        url = json.loads(self.ok(self.w.run("revive", SID_A, "--dry-run", "--json",
                                            "--unarchive")))["record"]["session"]["url"]
        out = self.ok(self.revive(SID_A, "--unarchive", FAKE_CLAUDE_LINK=url))
        self.assertIn("✅ revived", out)

    def test_a_stale_registry_row_is_never_read_as_a_live_twin_of_itself(self):
        """🛑 THE REFUSAL THAT CONTRADICTED THE DIAGNOSIS ONE SCREEN ABOVE IT.

        `revive_state` refuses to trust a row whose pid it cannot prove and reads it as DEAD,
        keeping the reason. `preflight`'s live-twin check read the same row straight out of
        `live_rows` with no proof — and for an in-place revive `dest_of(s, s.account)` IS the
        session's own transcript, so `dest_there` is always true and that check runs on every
        single run. The dry run said "row 7, resume it in place" and the real run exited 2
        with "<account> is ALREADY running session <id>", whose two cures are both impossible
        (there is nothing to stop; a third account is not what was asked). It is the
        machine-restart case the whole feature was built for: the rows that survive a restart
        name low pid numbers that are very likely in use again.
        """
        self.unprovable_row_still_resumes("Mon Jan  1 00:00:00 2024")

    def test_a_row_with_no_recorded_start_time_is_not_a_live_twin_either(self):
        """The second route to the same refusal, and it needs no pid reuse at all: a row the
        CLI wrote without a `procStart` can never be proved (`still_the_same_process` has no
        name-based fallback on purpose)."""
        self.unprovable_row_still_resumes("")

    def unprovable_row_still_resumes(self, proc_start):
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        p = self.w.spawn()                       # a real, live pid the row names
        self.w.live(self.work, SID_A, p.pid, cwd=self.cwd, proc_start=proc_start)
        got = json.loads(self.ok(self.w.run("revive", SID_A, "--dry-run", "--json")))
        self.assertEqual(got["record"]["state"]["state"], "dead")
        self.assertEqual(got["decision"]["row"], 7)
        url = got["record"]["session"]["url"]
        out = self.ok(self.revive(SID_A, FAKE_CLAUDE_LINK=url))
        self.assertNotIn("ALREADY running", out)
        self.assertIn("✅ revived", out)

    def test_a_home_whose_login_is_gone_starts_nothing(self):
        """🛑 Such a home takes the session up and then fails at its first token refresh,
        which looks exactly like a successful revive."""
        spare = self.w.account("spare")
        self.dead(SID_B, home=spare)
        self.assertIn("holds no login", self.refuse(SID_B))

    def test_the_target_of_a_to_is_gated_before_anything_is_copied(self):
        self.dead()
        self.assertIn("already in work", self.refuse(SID_A, "--to", "work"))

    def test_a_busy_session_is_left_alone_and_nothing_is_sent(self):
        """Not a refusal — exit 0, because there is nothing to do: a message sent now would
        join the turn it is in the middle of."""
        self.alive(status="busy")
        r = self.revive(SID_A)
        out = self.ok(r)
        self.assertIn("nothing to do: it is working right now", out)
        self.assertNothingStarted(r)
        self.assertEqual(self.w.relay_calls(), [])

    def test_a_lazy_respawn_between_the_diagnosis_and_the_start_is_refused(self):
        """🛑 THE LAST GATE. A Remote Control server respawns its child LAZILY, on
        server-side activity — so the app opening the link while csm is deciding leaves a
        brand-new process writing the very transcript csm is about to resume. The row that
        appears here is armed to land inside `preflight`, i.e. after the diagnosis has read
        every registry and before the start gate re-reads them."""
        self.dead(lines=[self.go(), self.clean(), BRIDGE_LINE])
        p = self.w.spawn()
        later = self.w.root / "respawn.json"
        self.w.live(self.work, SID_A, p.pid, cwd=self.cwd, path=later)
        (self.work / "sessions").mkdir(exist_ok=True)
        why = self.refuse(SID_A, FAKE_TMUX_ARM_FROM=str(later),
                          FAKE_TMUX_ARM_TO=str(self.work / "sessions" / ("%d.json" % p.pid)))
        self.assertIn("something is running session 11111111 NOW", why)
        self.assertIn("respawns its child LAZILY", why)
        # ⚠️ and it is `revive_recheck` that caught it, NOT `preflight`: the row appears on
        # the first tmux call, which is inside preflight and after its own registry read —
        # so this gate is load-bearing and not a second copy of one that already exists
        self.assertNotIn("ALREADY running", why)
        # a refusal raised mid-action is still recorded, and says nothing was started
        rows = [json.loads(x) for x in
                (self.w.state / "revive.jsonl").read_text().splitlines() if x.strip()]
        self.assertEqual((rows[0]["row"], rows[0]["action"], rows[0]["exit"]),
                         (7, "resume", 2))
        self.assertIs(rows[0]["started"], False)

    def test_a_refusal_writes_nothing_at_all(self):
        t = self.dead(lines=[self.go(), self.clean(), self.limit(time.time() + 3600)])
        before = t.read_bytes()
        self.refuse(SID_A)
        self.assertEqual(t.read_bytes(), before)
        self.assertEqual(self.w.windows(), {})

    def test_a_json_refusal_is_still_one_line_on_stderr_and_exit_2(self):
        self.dead(lines=[self.go(), self.clean(), self.limit(time.time() + 3600)])
        r = self.revive(SID_A, "--json")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        got = json.loads(r.stdout)                       # stdout stays one document
        self.assertEqual(got["decision"]["row"], 4)
        self.assertEqual(got["exit"], 2)
        said = [x for x in r.stderr.splitlines()
                if x.startswith("csm: ") and "CSM_LOGIN_PROBE" not in x]
        self.assertEqual(len(said), 1, r.stderr)
        self.assertIn("still inside the session limit", said[0])

    def test_from_machine_is_refused_and_names_the_route_that_does_work(self):
        """🛑 Every gate a revive turns on — is anything still writing that transcript, is a
        server up in that folder, can that home still run it — is a question about the
        machine the session is ON, and the answers are not transportable. So the refusal
        points at running the whole command there, which `--machine` already does."""
        self.dead()
        why = self.refuse(SID_A, "--from-machine", "desktop")
        self.assertIn("--from-machine is not built for revive", why)
        self.assertIn("csm --machine desktop revive <spec>", why)


class ReviveLock(ReviveRun):
    """At most ONE revive of one session at a time, held from the diagnosis to the start.

    🛑 Two revives, each deciding on a dead transcript and each starting a window, is the one
    outcome this command could produce that nothing else guards: `preflight`'s live-twin check
    only ever sees a process that has already registered. The claim is `state_lock`'s own
    lock-directory shape, keyed on the local id — with its OWN stale break, and not the 120 s
    the `.claude.json` lock keeps: this claim is held across four bounded waits that add up to
    more than 120 s, so the short bound made it breakable from t=120 s on every run. The waits
    re-stamp it as they poll, so a revive that was killed still does not wedge the session.
    """

    def claim(self, sid=SID_A):
        return self.w.state / ("revive-%s.lock" % sid)

    def test_a_second_revive_while_the_first_holds_the_claim_is_refused(self):
        t = self.dead()
        before = t.read_bytes()
        self.claim().mkdir(parents=True)
        r = self.revive(SID_A)
        self.refused(r, "another revive of session 11111111 is in flight")
        self.assertEqual(t.read_bytes(), before)
        self.assertEqual(self.w.claude_calls(wait=0.4), [])
        # 🛑 THE BOUND IT NAMES IS THE SUM OF THE WAITS IT IS HELD ACROSS, not the 120 s of the
        # lock `state_lock` was written for: a window connecting, its registry row appearing,
        # the relay and the turn, plus one spare connect. Here those are the suite's own small
        # knobs (CSM_CONNECT_WAIT=30, CSM_RELAY_TIMEOUT_S=30, CSM_REVIVE_PROVE_S=8), so the
        # arithmetic is asserted rather than a number copied out of the engine.
        want = 3 * 30 + 30 + 8 + 30
        self.assertIn("clears itself after %ds" % want, r.stderr)
        self.assertGreater(want, 120, "the whole point: longer than the .claude.json lock's")

    def test_a_long_wait_keeps_the_claim_fresh_so_a_second_revive_cannot_break_it(self):
        """🛑 The other half: the bound is read off the directory's MTIME, which `os.mkdir`
        stamps once. A claim held across a wait that outlasts the bound is a directory that
        looks abandoned while the thing it protects is running, so each polling wait re-stamps
        every lock this process holds."""
        mod = load_tool()
        self.addCleanup(sys.modules.pop, "csm_mod", None)
        mod.STATE_DIR = self.w.state
        self.w.state.mkdir(parents=True, exist_ok=True)
        p = self.w.state / "claim"
        with mod.state_lock(p, stale=5.0) as lk:
            self.assertTrue(lk.held)
            lock = Path(str(p) + ".lock")
            old = time.time() - 600
            os.utime(str(lock), (old, old))
            self.assertLess(lock.stat().st_mtime, time.time() - 60)
            mod.touch_locks()
            self.assertGreater(lock.stat().st_mtime, time.time() - 5,
                               "a held claim must be re-stamped, not left at its mkdir time")
            # a second attempt on a fresh claim finds it held, where the aged one was broken
            with mod.state_lock(p, stale=5.0) as second:
                self.assertFalse(second.held)
        self.assertEqual(mod.HELD_LOCKS, [], "and it is forgotten when released")

    def test_a_stale_claim_is_broken_and_the_revive_runs(self):
        self.alive()
        self.claim().mkdir(parents=True)
        os.utime(str(self.claim()), (time.time() - 600, time.time() - 600))
        self.assertIn("✅ revived", self.ok(self.revive(SID_A)))

    def test_the_claim_is_released_when_the_revive_ends(self):
        self.alive()
        self.ok(self.revive(SID_A))
        self.assertFalse(self.claim().exists(), "the lock directory outlived its revive")
        # and a second revive gets as far as deciding — it reads the session as BUSY now,
        # because the first one really did start a turn, which is the point
        r = self.revive(SID_A)
        self.ok(r)
        self.assertNotIn("in flight", r.stderr)
        self.assertIn("it is working right now", r.stdout)

    def test_a_dry_run_takes_no_claim_and_is_not_blocked_by_one(self):
        """A dry run reads: it has nothing to be at most once about."""
        self.dead()
        self.claim().mkdir(parents=True)
        out = self.ok(self.w.run("revive", SID_A, "--dry-run"))
        self.assertIn("(dry run: nothing was started", out)

    def test_the_claim_is_keyed_on_the_session_so_another_one_is_free(self):
        # 🛑 two names, because SendMessage addresses a session BY its name — and as of 0.5.0's
        # review fixes two proved live rows of one name is a REFUSAL of the tool's own, pinned
        # by `ReviveWake.test_a_name_that_names_two_live_sessions_is_refused_…`. It was not an
        # ambiguity of the fixture.
        self.alive(SID_A, name="first-session")
        self.alive(SID_B, name="second-session")
        self.claim(SID_B).mkdir(parents=True)
        out = self.ok(self.revive(SID_A))
        self.assertIn("✅ revived", out)
        self.assertEqual([c["target"] for c in self.w.relay_calls()], ["first-session"])


class RevivePlumbing(InProc):
    """The pure parts of the actions: the plan's new keys, the relay's words, the proof."""

    def plan(self, **kw):
        a = self.account("work")
        s = self.session(a)
        return self.mod.make_plan(s, a, "a label", "default", **kw)

    def test_the_plan_version_stays_1_and_the_new_keys_are_optional(self):
        """🛑 A reflexive bump would refuse a plan already on disk from a move that is still
        starting, and `run_window` reads every field but `kind` and `local_id` with `.get`."""
        p = self.plan()
        self.assertEqual((p["kind"], p["version"]), ("csm-run", 1))
        self.assertEqual((p["session_id"], p["fork_session"], p["revive_of"]),
                         ("", False, ""))
        self.assertEqual(p["window"], "moved-" + SID_A[:8])

    def test_every_tmux_call_carries_a_timeout_and_one_is_a_failed_capture(self):
        """🛑 `tmux()` WAS THE ONLY SUBPROCESS CALL IN THE ENGINE WITHOUT A TIMEOUT, and every
        revive wait is a loop around it: `wait_window` checks its deadline only BETWEEN
        `capture-pane` calls, so one tmux client that blocks — a wedged server, a socket that
        accepts and never answers — hung the whole command past `CONNECT_WAIT_S` with no bound
        at all. That is the one shape the no-blocking-wait rule forbids, inside the command that
        promises bounded machine waits.
        """
        seen = {}

        def blocked(argv, **kw):
            seen.update(kw)
            raise subprocess.TimeoutExpired(argv, kw.get("timeout") or 0)

        self.mod.tmux_bin = lambda: "/usr/bin/true"
        real, self.mod.subprocess.run = self.mod.subprocess.run, blocked
        self.addCleanup(setattr, self.mod.subprocess, "run", real)
        r = self.mod.tmux("capture-pane", "-p", check=False)
        self.assertTrue(seen.get("timeout"), "no timeout was passed to subprocess.run")
        self.assertEqual(seen["timeout"], self.mod.TMUX_TIMEOUT_S)
        # a timeout is a FAILED capture, which every caller already handles — so
        # `wait_window` sees rc != 0 and ends on its own deadline instead of hanging
        self.assertEqual(r.returncode, 127)
        self.assertIn("did not answer", r.stderr)
        with self.assertRaises(self.mod.Refusal) as caught:
            self.mod.tmux("capture-pane", "-p", check=True)
        self.assertIn("may be wedged", str(caught.exception))

    def test_a_fork_plan_emits_both_flags_and_names_the_window_for_the_new_id(self):
        new = "9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f"
        p = self.plan(session_id=new, fork_session=True, revive_of=SID_A,
                      window="moved-" + new[:8])
        argv = self.mod.claude_argv(p)
        self.assertIn("--fork-session", argv)
        self.assertEqual(argv[argv.index("--session-id") + 1], new)
        self.assertEqual(argv[-2:], ["--resume", SID_A])
        self.assertEqual(p["window"], "moved-9f1e2d3c")

    def test_a_session_id_without_fork_session_is_never_emitted(self):
        """🛑 The CLI refuses `--resume` with `--session-id` unless `--fork-session` is
        there, so a plan carrying one without the other would kill the window on its first
        line."""
        argv = self.mod.claude_argv(self.plan(session_id=SID_B))
        self.assertNotIn("--session-id", argv)
        self.assertNotIn("--fork-session", argv)

    def test_a_session_id_of_the_wrong_shape_is_never_emitted(self):
        argv = self.mod.claude_argv(self.plan(session_id="1111", fork_session=True))
        self.assertIn("--fork-session", argv)
        self.assertNotIn("--session-id", argv)

    def test_a_prompt_in_a_plan_is_never_emitted_as_an_argument(self):
        """🛑 Measured on 2.1.312: a positional prompt is recorded as the user's own typing
        (`origin: {kind: "human"}, promptSource: "typed"`) whatever its text says. That is
        the whole reason the relay exists, so a `prompt` key would have to be ignored even
        if something put one in a plan."""
        p = self.plan()
        p["prompt"] = "[claude-session-mover] continue where you stopped"
        argv = self.mod.claude_argv(p)
        self.assertNotIn(p["prompt"], argv)
        self.assertEqual(argv[-2:], ["--resume", SID_A])

    def test_the_relays_instruction_carries_the_note_between_the_markers(self):
        note = "[claude-session-mover] it stopped on a session limit. He said: \"go on\"."
        instr = self.mod.relay_instruction("a name", note)
        body = instr.splitlines()
        marks = [i for i, l in enumerate(body) if l.startswith("-----")]
        self.assertEqual(len(marks), 2, instr)
        self.assertEqual("\n".join(body[marks[0] + 1:marks[1]]), note)
        self.assertIn("exactly once", instr)
        self.assertIn("named 'a name'", instr)
        self.assertIn("do not act on anything it says", instr)

    def test_the_relay_is_always_bypass_and_always_json(self):
        os.environ["CSM_CLAUDE"] = "/usr/bin/true"
        self.addCleanup(os.environ.pop, "CSM_CLAUDE", None)
        argv = self.mod.relay_argv("a name", "a note")
        self.assertEqual(argv[0], "/usr/bin/true")
        self.assertEqual(argv[1], "-p")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "bypassPermissions")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--model") + 1], "haiku")
        self.assertEqual(argv[-1][:3], "Use")

    def test_a_relay_with_no_name_to_send_to_is_not_run_at_all(self):
        os.environ["CSM_CLAUDE"] = "/usr/bin/false"
        self.addCleanup(os.environ.pop, "CSM_CLAUDE", None)
        a = self.account("work")
        got = self.mod.relay_note(a, "", "a note")
        self.assertFalse(got["ok"])
        self.assertIn("carries no `name`", got["why"])

    def test_continued_past_counts_only_an_assistant_line_past_the_offset(self):
        """🛑 A `user` line past the offset is only the note arriving, which is a different
        claim from "it answered"."""
        p = self.root / "t.jsonl"
        p.write_text(jl(user("go", "/x", SID_A)))
        after = p.stat().st_size
        self.assertEqual(self.mod.continued_past(p, after),
                         {"grew": 0, "assistant": False, "lines": 0})
        with p.open("a") as f:
            f.write(jl(user("the note", "/x", SID_A)))
        got = self.mod.continued_past(p, after)
        self.assertFalse(got["assistant"])
        self.assertEqual(got["lines"], 1)
        with p.open("a") as f:
            f.write(jl(assistant("on it", "/x", SID_A)))
        self.assertTrue(self.mod.continued_past(p, after)["assistant"])

    def test_continued_past_ignores_a_sidechain_answer(self):
        """A subagent's line is not the session itself taking a turn."""
        p = self.root / "t.jsonl"
        p.write_text(jl(user("go", "/x", SID_A)))
        after = p.stat().st_size
        sub = dict(assistant("sub", "/x", SID_A), isSidechain=True)
        with p.open("a") as f:
            f.write(jl(sub))
        got = self.mod.continued_past(p, after)
        self.assertFalse(got["assistant"])
        self.assertEqual(got["lines"], 1)

    def test_an_unreadable_transcript_is_not_a_continuation(self):
        self.assertEqual(self.mod.continued_past(self.root / "nope.jsonl", 0),
                         {"grew": 0, "assistant": False, "lines": 0})

    def test_a_refusal_sentence_carries_its_cures(self):
        got = self.mod.revive_refusal({"refusal": "it is still inside the limit",
                                       "cures": ["wait until 6:30pm", "or `--to auto` now"]})
        self.assertEqual(got, "it is still inside the limit. wait until 6:30pm; "
                              "or `--to auto` now")
        self.assertEqual(self.mod.revive_refusal({"refusal": "no"}), "no")

    def test_the_relay_folder_is_csms_own_and_is_0700(self):
        d = self.mod.relay_dir()
        self.assertEqual(d.parent, self.mod.STATE_DIR)
        self.assertEqual(stat.S_IMODE(d.stat().st_mode), 0o700)

    def test_the_relay_name_survives_a_broken_template(self):
        self.mod.RELAY_NAME = "csm revive ({nope})"
        self.assertTrue(self.mod.relay_name().startswith("csm revive ("))
        self.mod.RELAY_NAME = "   "
        self.assertEqual(self.mod.relay_name(), "csm revive")


# ------------------------------------------------------------------- the unattended revive

class ReviveAuto(ReviveRun):
    """`csm revive --auto`: the same decide table, run for a caller nobody is watching.

    🛑 `--auto` CHANGES TWO THINGS AND NOT ONE GATE. The note's ATTRIBUTION, because nobody
    typed this run and the receiving session is about to act on the strength of that sentence;
    and the row a dead Remote Control server child takes, because row 9's whole result is a
    sentence for a person to act on and there is no unattended way back onto such a session's
    own link. Every refusal — a bot, a dead scheduled pass, a limit still in force, a home
    that holds no login — is untouched, and so are the exit codes.
    """

    def child(self):
        """A dead Remote Control server child: a transcript named by uuid5 of a bridge id."""
        return self.w.session(self.work, FORK_SID, cwd=self.cwd,
                              lines=[self.go(FORK_SID), self.clean(FORK_SID)])

    def jobs(self, sid=SID_A, job="daily"):
        d = self.w.root / "rc-jobs"
        d.mkdir(exist_ok=True)
        (d / ("%s.session" % job)).write_text("uuid=%s\n" % sid)
        return str(d)

    def test_the_note_says_nobody_has_sent_a_message_and_never_that_he_asked(self):
        self.alive()
        got, r = self.rec(SID_A, "--auto")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("The user has not sent a message since it stopped; this installation "
                      "continues stopped sessions automatically.", got["note"])
        self.assertNotIn("He asked csm to revive", got["note"])
        self.assertIs(got["unattended"], True)
        # and it is the note that was really handed to the relay, not a second rendering
        self.assertEqual(self.w.relay_calls()[0]["note"], got["note"])

    def test_a_say_is_still_quoted_verbatim_beside_the_unattended_sentence(self):
        """The text came from somebody; the RUN did not, and the note says both."""
        self.alive()
        got, _r = self.rec(SID_A, "--auto", "--say", "skip the card run")
        self.assertIn('He said: "skip the card run". The user has not sent a message',
                      got["note"])

    def test_without_auto_the_note_still_says_he_asked_for_it(self):
        self.alive()
        got, _r = self.rec(SID_A)
        self.assertIn("He asked csm to revive this session", got["note"])
        self.assertNotIn("this installation continues stopped sessions", got["note"])
        self.assertIs(got["unattended"], False)

    def test_auto_forks_a_dead_server_child_and_names_the_OLD_bridge_id(self):
        """🛑 THE ID THE CALLER HAS TO ARCHIVE. A fork leaves two conversations with one
        history, and the only thing that stops the old link respawning a second actor is
        archiving that old claude.ai session — which csm deliberately cannot do (it reads no
        credential). So the id is reported rather than described.
        """
        self.child()
        got, r = self.rec(link_of(FORK_BARE), "--auto")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((got["decision"]["row"], got["decision"]["action"]), (10, "fork"))
        self.assertIn("--auto: a server child has no unattended way back onto its own link",
                      got["decision"]["what"])
        res = got["result"]
        self.assertEqual(res["old_bridge_id"], FORK_BARE)
        self.assertEqual(res["old_url"], link_of(FORK_BARE))
        self.assertIs(res["archive_old"], True)
        self.assertTrue(res["new_id"] and res["new_id"] != FORK_SID, res)
        # 🛑 and no sentence for a person to act on came out of it: row 9's own result
        self.assertNotIn("and say continue", r.stdout + r.stderr)

    def test_the_same_child_without_auto_is_row_9_and_starts_nothing(self):
        """The pair is the point: `--auto` is what turns the printed tap into the fork."""
        self.child()
        got, r = self.rec(link_of(FORK_BARE))
        self.assertEqual((got["decision"]["row"], got["decision"]["action"]),
                         (9, "keep-link"))
        self.assertIs(got["unattended"], False)
        self.assertIn("and say continue", r.stderr)
        self.assertNothingStarted(r)

    def test_a_limit_still_in_force_is_refused_under_auto_too(self):
        """🛑 A wake sent early is CONSUMED, not queued (LESSONS L40), and `--auto` is the
        one caller that would never see the refusal — so nothing about row 4 moves."""
        self.dead(lines=[self.go(), self.clean(), self.limit(time.time() + 3600)])
        r = self.revive(SID_A, "--auto")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("still inside the session limit", r.stderr)
        self.assertEqual(self.w.relay_calls(), [])
        self.assertNothingStarted(r)

    def test_a_scheduled_pass_that_is_live_and_idle_is_woken(self):
        """🛑 THE NARROWING, and the whole reason for it: a wake starts nothing, so there is
        no second copy of the pass to make — and a pass parked on a usage limit was the one
        class of session nothing ever continued, because its supervisor revives a session that
        DIED and does not handle a limit."""
        self.alive(lines=[self.go(), self.clean(), self.limit(time.time() - 3600)])
        got, r = self.rec(SID_A, "--auto", CSM_RC_JOBS_DIR=self.jobs())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(got["decision"]["row"], 5)
        self.assertIn("the scheduled pass `daily`", got["decision"]["what"])
        self.assertIn("starts no second copy of the pass", got["decision"]["what"])
        self.assertEqual(got["record"]["owner"]["kind"], "rc_job")
        self.assertEqual(len(self.w.relay_calls()), 1, self.w.relay_calls())
        # nothing was STARTED: a wake opens no window, which is what makes it safe here
        self.assertEqual([c for c in self.w.tmux_log()
                          if c[:1] in (["new-window"], ["new-session"])], [])

    def test_a_scheduled_pass_that_is_DEAD_stays_its_own_supervisors(self):
        self.dead()
        r = self.revive(SID_A, "--auto", CSM_RC_JOBS_DIR=self.jobs())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("rc_job daily --revive", r.stderr)
        self.assertNothingStarted(r)
        self.assertEqual(self.w.relay_calls(), [])

    def test_a_bot_is_refused_even_when_it_is_live_and_idle(self):
        """🛑 A relay into a bot's session surfaces as a message in the channel that bot
        answers, which is not csm's to write in — so the bot refusal is not narrowed."""
        self.alive()
        d = self.w.root / "owners"
        d.mkdir()
        (d / "chatbot.json").write_text(json.dumps({"session_id": SID_A}))
        r = self.revive(SID_A, "--auto", CSM_BOTS_DIR=str(d))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("chatbot", r.stderr)
        self.assertEqual(self.w.relay_calls(), [])

    def test_the_record_carries_the_stop_events_own_uuid(self):
        """🛑 THE AT-MOST-ONCE KEY, written where `csm stalled` reads it back."""
        self.alive(lines=[self.go(), self.clean(), self.limit(time.time() - 3600)])
        self.ok(self.revive(SID_A, "--auto"))
        rows = [json.loads(x) for x in
                (self.w.state / "revive.jsonl").read_text().splitlines() if x.strip()]
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["stop_uuid"], "a2")
        self.assertEqual((rows[0]["row"], rows[0]["exit"]), (5, 0))
        self.assertNotIn("not sent a message since", json.dumps(rows[0]))


# ------------------------------------------------------------------------- csm stalled

class Stalled(ReviveRun):
    """`csm stalled`: every session that stopped, and which of them is ready to continue.

    🛑 FIXTURES ONLY, AND THE COMMAND ITSELF ACTS ON NOTHING. Each test asserts the verdict in
    the row AND that no window, no relay, no signal and no transcript write came out of the
    sweep: what acts is `csm revive <id> --auto`, one session at a time.
    """

    def sweep(self, *extra, **env):
        return self.w.run("stalled", *extra, **env)

    def doc(self, *extra, **env):
        r = self.sweep("--json", *extra, **env)
        return json.loads(self.ok(r)), r

    def row(self, sid=SID_A, *extra, **env):
        got, r = self.doc(*extra, **env)
        hits = [x for x in got["rows"] if x["local_id"] == sid]
        self.assertEqual(len(hits), 1, got["rows"])
        return hits[0], got, r

    def logged(self, sid, stop_uuid, exit=0, **extra):
        """One record in the revive log, in `revive_record`'s own shape."""
        p = self.w.state / "revive.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        d = {"at": time.time() - 60, "machine": "here", "local_id": sid, "bridge_id": "",
             "bytes": None, "stop_uuid": stop_uuid, "account": "work", "row": 5,
             "action": "wake", "exit": exit}
        d.update(extra)
        with p.open("a") as f:
            f.write(json.dumps(d) + "\n")
        return p

    def parked(self, resets, sid=SID_A, at=None, **kw):
        """A dead session parked on a usage limit.

        ⚠️ `at` stamps the limit LINE, which is WHEN IT STOPPED — not `resets`, which is when
        its limit lifts. The two are different facts and only one of them orders the table.
        Without a stamp `revive_stop` falls back to the transcript's own mtime, and two
        fixtures written in the same millisecond then have no order at all.
        """
        line = self.limit(resets, sid, **kw)
        if at:
            line["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at))
        return self.dead(sid, lines=[self.go(sid), self.clean(sid), line])

    # --- what is due ------------------------------------------------------
    def test_a_usage_limit_that_has_not_reset_yet_is_not_due(self):
        self.parked(time.time() + 3600)
        r, _got, run = self.row()
        self.assertFalse(r["due"], r["why"])
        self.assertIn("its session limit resets", r["why"])
        self.assertIn("a wake waits 120s past that", r["why"])
        self.assertNothingStarted(run)

    def test_a_usage_limit_past_its_reset_and_the_margin_is_due(self):
        self.parked(time.time() - 3600)
        r, got, _run = self.row()
        self.assertTrue(r["due"], r["why"])
        self.assertIn("its session limit reset at", r["why"])
        self.assertEqual(r["stop"]["stop"], "usage-limit")
        self.assertEqual(r["stop"]["class"], "session")
        self.assertEqual(got["due"], 1)

    def test_a_reset_inside_the_margin_is_not_due_yet(self):
        """🛑 THE MARGIN IS THE WHOLE OF "never before the reset": the `resetsAt` the
        transcript recorded and this machine's clock are two readings."""
        self.parked(time.time() - 10)
        r, _got, _run = self.row()
        self.assertFalse(r["due"], r["why"])
        self.assertIn("a wake waits 120s past that", r["why"])

    def test_a_monthly_spend_limit_is_never_due_however_long_it_waits(self):
        self.parked(time.time() - 86400,
                    text="You've hit your monthly spend limit · raise it at "
                         "claude.ai/settings/usage")
        r, _got, _run = self.row()
        self.assertFalse(r["due"], r["why"])
        self.assertIn("waiting does not clear a monthly-spend limit", r["why"])

    def test_a_dead_session_killed_mid_turn_is_due_and_a_busy_one_never_is(self):
        self.dead(lines=[self.go(), tool_call(self.cwd, SID_A)])
        self.alive(SID_B, status="busy",
                   lines=[self.go(SID_B), tool_call(self.cwd, SID_B)])
        got, _r = self.doc()
        by_id = dict((x["local_id"], x) for x in got["rows"])
        self.assertTrue(by_id[SID_A]["due"], by_id[SID_A]["why"])
        self.assertEqual(by_id[SID_A]["stop"]["stop"], "mid-turn")
        self.assertIn("killed mid-turn", by_id[SID_A]["why"])
        self.assertFalse(by_id[SID_B]["due"], by_id[SID_B]["why"])
        self.assertEqual(by_id[SID_B]["why"], "it is working right now")

    def test_a_session_killed_right_after_Enter_is_due_and_a_busy_one_never_is(self):
        """🛑 THE WEDNESDAY-RESTART CASE THE SWEEP USED TO MISS (Thu 29 Oct 2026, week 44).

        A session killed between turns has written the prompt and nothing of its own after
        it — measured on 2.1.312, 1.5 s after Enter: the user line plus the
        `total_tokens_reminder` attachment. That read `unknown`, so the row was not due and
        carried no stop uuid to key a wake on; the brief's own due rule says "an unanswered
        tool call, or an unanswered user prompt".

        🛑 AND THE LIVE SESSION BESIDE IT IS THE REASON THE RULE IS NARROW: a session that is
        THINKING leaves the same shape on disk, so what keeps it out is `revive_state`'s
        answer and never the transcript's.
        """
        self.dead(lines=[self.go(), tokens_reminder(self.cwd, SID_A)])
        self.alive(SID_B, status="busy",
                   lines=[self.go(SID_B), tokens_reminder(self.cwd, SID_B)])
        got, _r = self.doc()
        by_id = dict((x["local_id"], x) for x in got["rows"])
        self.assertTrue(by_id[SID_A]["due"], by_id[SID_A]["why"])
        self.assertEqual(by_id[SID_A]["stop"]["stop"], "mid-turn")
        self.assertEqual(by_id[SID_A]["stop"]["uuid"], "u1")
        self.assertIn("killed mid-turn", by_id[SID_A]["why"])
        self.assertFalse(by_id[SID_B]["due"], by_id[SID_B]["why"])
        self.assertEqual(by_id[SID_B]["why"], "it is working right now")

    def test_a_mid_turn_kill_older_than_the_cap_is_listed_and_not_due(self):
        t = self.dead(lines=[self.go(), tool_call(self.cwd, SID_A)])
        old = time.time() - 50 * 3600
        os.utime(str(t), (old, old))
        r, _got, _run = self.row(CSM_STALLED_SINCE_H="96")
        self.assertFalse(r["due"], r["why"])
        self.assertIn("past the 24h an automatic wake covers", r["why"])

    def test_a_clean_finish_and_an_api_error_are_not_even_candidates(self):
        """🛑 NEITHER IS WAITING FOR ANYTHING. A clean finish answered and stopped, and an
        error that is not a limit is not cured by time — so both are ruled out by the cheap
        prefilter and never cost a `diagnose`."""
        self.dead()                                      # answered, and sitting idle
        self.dead(SID_B, lines=[self.go(SID_B),
                                assistant("", self.cwd, SID_B, uuid="a2", parent="u1",
                                          api_error_only="api_error_overloaded")])
        got, _r = self.doc()
        self.assertEqual(got["rows"], [])
        self.assertEqual((got["scanned"], got["candidates"]), (2, 0))

    def test_a_session_archived_after_its_limit_is_never_due(self):
        """🛑 THE ARCHIVE GUARD, on the one shape that reaches it: a session that hit a limit
        and was then archived or ended from the app is still read as `usage-limit` (the limit
        is why it stopped), so it IS a candidate — and archiving it was somebody's decision,
        not a failure to repair."""
        self.parked(time.time() - 3600)
        t = self.work / "projects"
        tr = sorted(t.glob("*/%s.jsonl" % SID_A))[0]
        with tr.open("a") as f:
            f.write(jl(BRIDGE_LINE, STATUS_LINE, ENDED_LINE))
        r, _got, _run = self.row()
        self.assertEqual(r["stop"]["stop"], "usage-limit")
        self.assertIs(r["stop"]["archived"], True)
        self.assertFalse(r["due"], r["why"])
        self.assertIn("archived or ended from the app", r["why"])

    def test_a_bot_owned_session_is_never_due(self):
        self.parked(time.time() - 3600)
        d = self.w.root / "owners"
        d.mkdir()
        (d / "chatbot.json").write_text(json.dumps({"session_id": SID_A}))
        r, _got, _run = self.row(CSM_BOTS_DIR=str(d))
        self.assertFalse(r["due"], r["why"])
        self.assertIn("chatbot owns it", r["why"])
        self.assertIn("surfaces in the channel it answers", r["why"])

    def test_a_scheduled_pass_is_due_while_it_is_idle_and_not_once_it_is_dead(self):
        self.parked(time.time() - 3600, SID_A)                      # dead: its own to revive
        self.alive(SID_B, lines=[self.go(SID_B), self.clean(SID_B),
                                 self.limit(time.time() - 3600, SID_B)])
        d = self.w.root / "rc-jobs"
        d.mkdir()
        (d / "daily.session").write_text("uuid=%s\n" % SID_A)
        (d / "hourly.session").write_text("uuid=%s\n" % SID_B)
        got, _r = self.doc(CSM_RC_JOBS_DIR=str(d))
        by_id = dict((x["local_id"], x) for x in got["rows"])
        self.assertFalse(by_id[SID_A]["due"], by_id[SID_A]["why"])
        self.assertIn("daily owns it and it is dead", by_id[SID_A]["why"])
        self.assertTrue(by_id[SID_B]["due"], by_id[SID_B]["why"])
        self.assertEqual(by_id[SID_B]["action"], "wake")

    # --- at most once -----------------------------------------------------
    def test_a_handled_stop_is_not_due_again_but_a_NEW_stop_on_it_is(self):
        """🛑 THE AT-MOST-ONCE KEY IS `(local id, stop event uuid)`. The id alone can only
        say "this session was revived once", and a session that was woken, worked for an hour
        and stopped again is a different stop — due again, or nothing ever continues it twice.
        """
        t = self.parked(time.time() - 3600)
        self.logged(SID_A, "a2", exit=0)
        r, _got, _run = self.row()
        self.assertFalse(r["due"], r["why"])
        self.assertIn("already revived for this stop", r["why"])
        self.assertEqual(r["handled"]["attempts"], 1)
        self.assertIs(r["handled"]["done"], True)
        self.assertIn("stop event a2", r["handled"]["compared"])
        # it ran again, and stopped again: a new stop event, with a uuid of its own
        with t.open("a") as f:
            f.write(jl(assistant("on it", self.cwd, SID_A, uuid="a3", parent="a2"),
                       self.limit(time.time() - 600, uuid="a4", parent="a3")))
        again, _got2, _run2 = self.row()
        self.assertTrue(again["due"], again["why"])
        self.assertEqual(again["stop"]["uuid"], "a4")
        self.assertIs(again["handled"]["done"], False)
        self.assertEqual(again["handled"]["attempts"], 0)

    def test_a_record_for_another_stop_event_never_marks_this_one_handled(self):
        """⚠️ THE OTHER SESSION'S STOP NEEDS A UUID OF ITS OWN here, and that is the fixture
        catching up with reality (Thu 29 Oct 2026): a uuid names ONE transcript line, so two
        unrelated sessions never share one, and the only way they do is that one is a COPY of
        the other — which is the case `revive_handled` now matches on purpose, because a fork
        copies the transcript and both copies would otherwise be woken for one stop. This test
        keeps the claim it was written for: a wake of a DIFFERENT conversation is not this
        one's."""
        self.parked(time.time() - 3600)
        self.logged(SID_B, "someone-elses-stop", exit=0)
        r, _got, _run = self.row()
        self.assertTrue(r["due"], r["why"])
        self.assertEqual(r["handled"]["attempts"], 0)
        self.assertEqual(r["handled"]["copy_of"], "")

    def test_a_failed_wake_leaves_the_row_due_and_counts_the_attempt(self):
        """🛑 `done` IS EXIT 0, NOT "A RECORD EXISTS". A non-zero exit means nothing was
        delivered: the session is still sitting there and has to stay due."""
        self.parked(time.time() - 3600)
        self.logged(SID_A, "a2", exit=2)
        r, got, _run = self.row()
        self.assertTrue(r["due"], r["why"])
        self.assertEqual((r["handled"]["failed"], r["handled"]["last_exit"]), (1, 2))
        self.assertIn("FAILED", r["handled"]["why"])
        self.assertEqual(got["failed"], 1)

    # --- the cheap prefilter ----------------------------------------------
    def test_the_prefilter_skips_a_clean_finish_and_an_empty_transcript(self):
        """🛑 THE COST CONTROL: a `diagnose` is a 1 MiB parse plus a machine-wide `ps`, and a
        Remote Control server pre-creates 0-byte sessions by the hundred."""
        self.dead()                                      # a clean finish
        empty = self.dead(SID_B, lines=[])
        empty.write_text("")                             # a pre-created session
        self.parked(time.time() - 3600, SID_C)
        got, _r = self.doc()
        self.assertEqual([x["local_id"] for x in got["rows"]], [SID_C])
        self.assertEqual(got["scanned"], 3)
        self.assertEqual(got["candidates"], 1)

    def test_a_transcript_outside_the_window_is_not_even_scanned(self):
        t = self.parked(time.time() - 3600)
        old = time.time() - 72 * 3600
        os.utime(str(t), (old, old))
        got, _r = self.doc()
        self.assertEqual(got["rows"], [])
        self.assertEqual(got["scanned"], 0)
        # ...and it is there when the window is widened to reach it
        wide, _r2 = self.doc("--since", "96")
        self.assertEqual([x["local_id"] for x in wide["rows"]], [SID_A])
        self.assertEqual(wide["since_h"], 96.0)

    def test_a_narrow_window_that_rules_nothing_out_is_still_diagnosed(self):
        """🛑 AN EMPTY WINDOW IS NOT AN EMPTY FILE. With the prefilter's window set below the
        padding below, its last bytes hold no main-chain line at all — which says nothing
        about the stop, so the file is read properly rather than skipped."""
        t = self.parked(time.time() - 3600)
        with t.open("a") as f:
            f.write(jl(*[{"type": "progress", "isSidechain": False, "pad": "x" * 200}
                         for _ in range(40)]))
        r, got, _run = self.row(CSM_STALLED_PREFILTER="2048")
        self.assertTrue(r["due"], r["why"])
        self.assertIn("rules nothing out", r["prefilter"])
        self.assertEqual(got["candidates"], 1)

    # --- the sweep acts on nothing ----------------------------------------
    def test_the_sweep_starts_nothing_relays_nothing_and_writes_no_transcript(self):
        t = self.parked(time.time() - 3600)
        before = t.read_bytes()
        r = self.sweep()
        self.ok(r)
        self.assertNothingStarted(r)
        self.assertEqual(self.w.relay_calls(), [])
        self.assertEqual(t.read_bytes(), before)
        self.assertEqual(self.w.windows(), {})

    def test_the_rows_are_due_first_and_then_oldest_stop_first(self):
        """The order `--json` carries IS the order the caller wakes them in, so the row that
        has been waiting longest goes first — a newer stop would otherwise keep jumping it."""
        now = time.time()
        self.parked(now - 7200, SID_A, at=now - 7200, uuid="aa")     # due, stopped 2h ago
        self.parked(now - 600, SID_B, at=now - 600, uuid="bb")       # due, stopped 10m ago
        self.parked(now + 3600, SID_C, at=now - 60, uuid="cc")       # not due: still in force
        got, _r = self.doc()
        self.assertEqual([x["local_id"] for x in got["rows"]], [SID_A, SID_B, SID_C])
        self.assertEqual([x["due"] for x in got["rows"]], [True, True, False])

    def test_the_action_reported_is_the_one_revive_auto_really_takes(self):
        """🛑 THE SWEEP AND THE RUN MAY NEVER DISAGREE: a dead server child is `fork` here,
        because `--auto` is the command this table is read for — row 9's printed tap is not."""
        self.w.session(self.work, FORK_SID, cwd=self.cwd,
                       lines=[self.go(FORK_SID), tool_call(self.cwd, FORK_SID)])
        r, _got, _run = self.row(FORK_SID)
        self.assertTrue(r["due"], r["why"])
        self.assertEqual((r["kind"], r["row"], r["action"]), ("server-child", 10, "fork"))

    def test_a_home_that_cannot_run_it_is_reported_and_never_called_due(self):
        """A home whose login is gone takes a session up and then fails at its first token
        refresh, which looks exactly like a successful revive — so revive refuses it, and a
        row this sweep called due would send a watchdog at it every five minutes."""
        spare = self.w.account("spare")
        self.dead(SID_B, lines=[self.go(SID_B), self.clean(SID_B),
                                self.limit(time.time() - 3600, SID_B)], home=spare)
        r, _got, _run = self.row(SID_B)
        self.assertFalse(r["due"], r["why"])
        self.assertIn("revive would refuse it", r["why"])
        self.assertIn("holds no login", r["why"])

    # --- the table and the check line -------------------------------------
    def test_the_table_names_what_revive_auto_would_do_and_how_to_do_it(self):
        self.parked(time.time() - 3600)
        out = self.ok(self.sweep())
        self.assertIn("csm stalled —", out)
        self.assertIn("DUE 1", out)
        self.assertIn("revive --auto would: row 8", out)
        self.assertIn("csm revive <session> --auto", out)
        self.assertIn("ok: 1 session(s) due for a wake and none has failed", out)

    def test_check_is_one_quiet_line_and_asks_no_credential_store(self):
        """🛑 THE CONTRACT: one line on stdout, NOTHING on stderr. `CSM_LOGIN_PROBE` is set on
        every run in this suite and announces itself on stderr whenever it is asked — so an
        empty stderr is the proof that this path never asks it."""
        self.parked(time.time() - 3600)
        r = self.sweep("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stderr, "", r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
        self.assertTrue(r.stdout.startswith("ok: 1 session(s) due for a wake"), r.stdout)

    def test_check_FAULTS_only_once_a_wake_for_that_stop_has_failed(self):
        """🛑 BEING DUE IS NOT A FAULT — it is the normal state between two passes. The fault
        is a wake that was tried and failed, which nothing else in the loop reports."""
        self.parked(time.time() - 3600)
        ok = self.sweep("--check")
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)
        self.logged(SID_A, "a2", exit=1)
        bad = self.sweep("--check")
        self.assertEqual(bad.returncode, 1, bad.stdout + bad.stderr)
        self.assertTrue(bad.stdout.startswith("FAULT: 1 due session(s) whose last wake "
                                              "FAILED"), bad.stdout)
        self.assertIn("1 attempt(s), last exit 1", bad.stdout)
        self.assertEqual(bad.stderr, "", bad.stderr)

    def test_a_revive_log_that_cannot_be_read_is_INCOMPLETE_and_not_a_quiet_ok(self):
        """🛑 A LOG NOBODY CAN READ IS NOT AN EMPTY ONE: the sweep then cannot tell a stop it
        has already acted on from one it has not, which is how a session is woken twice. (A
        MISSING log is the state of every fresh install and is not a problem at all.)"""
        self.parked(time.time() - 3600)
        blocked = self.w.root / "revive-log-is-a-directory"
        blocked.mkdir()
        r = self.sweep("--check", CSM_REVIVE_LOG=str(blocked))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("INCOMPLETE: no due session has a failed wake"),
                        r.stdout)
        self.assertIn("could not be read", r.stdout)
        self.assertEqual(r.stderr, "", r.stderr)

    def test_a_quiet_machine_says_so_and_exits_0(self):
        self.dead()
        r = self.sweep("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("ok: nothing is due for a wake"), r.stdout)

    def test_an_owner_directory_that_cannot_be_read_is_INCOMPLETE_not_an_exit_2(self):
        """🛑 ONE SESSION'S REFUSAL IS NOT THE WHOLE SWEEP'S. `rc_job_owner` dies on a jobs
        directory it cannot read, because answering "nobody owns it" there is how a second
        copy of a scheduled pass gets started — right for `revive`, which is about to act,
        and wrong for a whole-machine read, which would abort over one directory and leave
        `--check` with an exit code outside its 0/1/3 contract."""
        self.parked(time.time() - 3600)
        blocked = self.w.root / "rc-jobs-is-a-file"
        blocked.write_text("not a directory")
        got, _r = self.doc(CSM_RC_JOBS_DIR=str(blocked))
        self.assertEqual(got["rows"], [])
        self.assertEqual(len(got["coverage"]["unread"]), 1, got["coverage"])
        self.assertIn("not a directory", got["coverage"]["unread"][0]["reason"])
        r = self.sweep("--check", CSM_RC_JOBS_DIR=str(blocked))
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("INCOMPLETE:"), r.stdout)
        self.assertEqual(r.stderr, "", r.stderr)

    def test_a_home_whose_projects_cannot_be_LISTED_is_reported_not_skipped(self):
        """🛑 A HOME THAT CANNOT BE LISTED IS NOT AN EMPTY ONE. `transcripts_by_id` catches
        the OSError and answers `{}`, which reads downstream exactly like "this home runs
        nothing" — the one answer that is never true. So the sweep asks the directory itself
        and the failure reaches the coverage channel and the `INCOMPLETE:` line."""
        self.parked(time.time() - 3600)
        shutil.rmtree(str(self.personal / "projects"))
        (self.personal / "projects").write_text("not a directory at all")
        got, _r = self.doc()
        self.assertEqual([u["name"] for u in got["coverage"]["unread"]], ["personal"])
        self.assertIn("could not be read", got["coverage"]["unread"][0]["reason"])
        self.assertEqual([x["local_id"] for x in got["rows"]], [SID_A])
        r = self.sweep("--check")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("1 not read (personal:", r.stdout)

    def test_a_session_whose_ps_could_not_be_asked_is_listed_and_never_due(self):
        """🛑 AN UNMEASURED STATE IS NOT A DEAD ONE (Thu 29 Oct 2026, week 44).

        `revive_state` can only call a session live by PROVING its registry row, and that
        proof needs `ps`; `ps_table`'s own promise is that `None` is never "nothing is
        running". So with `ps` blind every live session reads `dead` — and a live session
        that is BUSY ends its transcript on an unanswered tool_use, which is exactly the
        `mid-turn` shape this sweep calls due. The row stays listed with its reason, because
        resuming it would put two CLIs on one transcript, which `revive_start` itself refuses.
        """
        self.dead(lines=[self.go(), tool_call(self.cwd, SID_A)])
        ps = self.w.bin / "ps"                          # the fixture bin is FIRST on PATH
        ps.write_text("#!/bin/sh\necho 'ps: illegal option' >&2\nexit 1\n")
        ps.chmod(0o755)
        r, got, run = self.row()
        self.assertFalse(r["due"], r["why"])
        self.assertIn("`ps` could not be asked", r["why"])
        self.assertNothingStarted(run)
        self.assertIn("could not be asked", got["coverage"]["unread"][0]["reason"])
        # ...and the one line a scheduled caller reads says so too, rather than "nothing due".
        c = self.sweep("--check")
        self.assertEqual(c.returncode, 3, c.stdout + c.stderr)
        self.assertTrue(c.stdout.startswith("INCOMPLETE:"), c.stdout)

    # --- one stop event, however many copies of it there are --------------
    def forked_pair(self, stop_uuid="stop1", resets=None):
        """A parked session and the COPY a fork leaves: the same stop line, two local ids.

        ⚠️ THE MTIMES ARE SET, because which row is kept is "the older file" — a fork's copy
        is written after the conversation it copied — and two fixtures written in the same
        millisecond have no order at all.
        """
        now = time.time()
        resets = now - 7200 if resets is None else resets
        parent = self.dead(SID_A, lines=[self.go(SID_A), self.clean(SID_A),
                                         self.limit(resets, SID_A, uuid=stop_uuid)])
        copy = self.dead(SID_B, lines=[self.go(SID_B), self.clean(SID_B),
                                       self.limit(resets, SID_B, uuid=stop_uuid)])
        os.utime(str(parent), (now - 600, now - 600))
        os.utime(str(copy), (now - 60, now - 60))
        return parent, copy

    def test_one_stop_event_is_due_once_however_many_copies_of_it_exist(self):
        """🛑 A FORK COPIES THE TRANSCRIPT, so one stop line ends two sessions.

        The same uuid under a second local id is what `csm revive --new-link` leaves behind —
        and what `claude --resume X --fork-session` or `/fork` on a parked session leaves
        behind with no csm involved at all. Both rows used to read DUE for ONE stop event and
        an unattended pass woke both: two actors continuing one history, which is the thing
        the at-most-once key exists to prevent.
        """
        self.forked_pair()
        got, _r = self.doc()
        due = [x for x in got["rows"] if x["due"]]
        self.assertEqual([x["local_id"] for x in due], [SID_A],
                         [(x["local_id"], x["due"], x["why"]) for x in got["rows"]])
        held = [x for x in got["rows"] if not x["due"]][0]
        self.assertEqual(held["local_id"], SID_B)
        self.assertIn("same stop event", held["why"])
        self.assertIn("two actors", held["why"])
        self.assertEqual(got["due"], 1)

    def test_a_wake_recorded_for_one_copy_covers_the_other(self):
        """The at-most-once key is `(stop event)`, not `(local id, stop event)`: the parent's
        exit-0 record has to cover the copy, or the copy is woken on the next pass."""
        self.forked_pair()
        self.logged(SID_A, "stop1", exit=0)
        got, _r = self.doc()
        self.assertEqual([x["due"] for x in got["rows"]], [False, False],
                         [(x["local_id"], x["why"]) for x in got["rows"]])
        copy = [x for x in got["rows"] if x["local_id"] == SID_B][0]
        self.assertIn("already revived for this stop", copy["why"])
        self.assertIn("shares this stop line", copy["why"])
        self.assertEqual(copy["handled"]["copy_of"], SID_A)
        c = self.sweep("--check")
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)

    def test_a_NEW_stop_in_the_copy_is_its_own_question(self):
        """The uuid is matched, not the id — so a copy that stopped again on a line of its
        own is due again, exactly as the parent would be."""
        self.forked_pair()
        self.logged(SID_A, "stop1", exit=0)
        self.dead(SID_C, lines=[self.go(SID_C), self.clean(SID_C),
                                self.limit(time.time() - 7200, SID_C, uuid="stop2")])
        got, _r = self.doc()
        by = dict((x["local_id"], x) for x in got["rows"])
        self.assertTrue(by[SID_C]["due"], by[SID_C]["why"])

    # --- the machine is read once a sweep, not once a session -------------
    def test_the_machine_is_read_once_a_sweep_and_not_once_a_session(self):
        """🛑 `ps_table`'S OWN PROMISE IS "ONE CALL, NOT ONE PER SESSION", and the sweep broke
        it: `diagnose` asks `ps` in `revive_state` and again in `server_in_folder`, and asks
        the credential store in `revive_account`, once per candidate. Measured here Thu 29 Oct
        2026 against the engine before the fix: these six parked fixture sessions in one home
        cost 12 machine-wide `ps -Ao` runs and 6 credential probes in ONE sweep, against 1 and
        1 after — at ~101 ms per `ps` on this Mac, and growing with the number of parked
        sessions, i.e. exactly when this loop matters most.
        """
        counter = self.w.root / "ps-calls"
        real = shutil.which("ps") or "/bin/ps"
        ps = self.w.bin / "ps"
        ps.write_text('#!/bin/sh\necho "$@" >> "%s"\nexec %s "$@"\n' % (counter, real))
        ps.chmod(0o755)
        now = time.time()
        for n, sid in enumerate((SID_A, SID_B, SID_C, LINK_SID, LINK_SID2, FORK_SID)):
            self.dead(sid, lines=[self.go(sid), self.clean(sid),
                                  self.limit(now - 3600, sid, uuid="u-%d" % n)])
        got, r = self.doc()
        self.assertEqual(got["candidates"], 6, got["rows"])
        # ⚠️ ONLY THE MACHINE-WIDE ONES. `self_session` walks its own parents with
        # `ps -o ppid= -p <pid>`, which is one ladder per RUN and not one per session.
        wide = [x for x in counter.read_text().splitlines() if "-Ao" in x]
        self.assertLessEqual(len(wide), 2,
                             "the whole machine was read %d times for 6 sessions" % len(wide))
        # ⚠️ `CSM_LOGIN_PROBE` announces itself on stderr every time it is asked, which is how
        # the per-session probe was found: the answer is a property of the HOME, and each
        # `security` call is another chance to block on a locked keychain nobody can unlock.
        probes = [x for x in r.stderr.splitlines() if "CSM_LOGIN_PROBE" in x]
        self.assertEqual(len(probes), 1, probes)

    def test_revive_itself_still_asks_ps_afresh(self):
        """🛑 AND THE MEMO IS THE SWEEP'S ALONE. `revive_recheck` asks `ps` again in the last
        second before it starts a window, because a Remote Control server respawns its child
        lazily and one can appear between the diagnosis and the start. A cached reading there
        would hand it an answer from minutes ago."""
        counter = self.w.root / "ps-calls"
        real = shutil.which("ps") or "/bin/ps"
        ps = self.w.bin / "ps"
        ps.write_text('#!/bin/sh\necho "$@" >> "%s"\nexec %s "$@"\n' % (counter, real))
        ps.chmod(0o755)
        self.parked(time.time() - 3600)
        r = self.revive(SID_A, "--json", "--auto")
        self.assertIn(r.returncode, (0, 1), r.stdout + r.stderr)
        wide = [x for x in counter.read_text().splitlines() if "-Ao" in x]
        self.assertGreaterEqual(len(wide), 2,
                                "revive read the machine %d time(s): the diagnosis and the "
                                "re-check are two readings" % len(wide))

    # --- what the two commands say about one session ----------------------
    def test_the_due_sentence_ages_the_reset_and_not_the_wake_margin(self):
        """`ready` is the instant a wake becomes PERMITTED (reset + 120 s), not the instant
        the limit lifted, and `human_age` floors — so measuring from it reported a two-hour
        wait as "1h ago" in the sentence a person reads."""
        now = time.time()
        self.parked(now - 7200, at=now - 7200)
        r, _got, _run = self.row()
        self.assertTrue(r["due"], r["why"])
        self.assertIn("2h ago", r["why"])

    def test_a_limit_whose_class_was_never_named_gets_one_answer_from_both(self):
        """🛑 THE SWEEP AND THE RUN MAY NEVER DISAGREE, and `clears_with_time` is `None` —
        not `False` — for a limit line whose own words matched no class csm knows. `stalled`
        calls that "waiting does not clear a limit whose class its own words did not name";
        row 4 keyed on `is False` and so told the reader of the same build to wait for the
        reset instead."""
        self.parked(time.time() + 3600, text="Something about usage went wrong")
        r, _got, _run = self.row()
        self.assertFalse(r["due"], r["why"])
        self.assertIn("whose class its own words did not name", r["why"])
        self.assertEqual(r["row"], 4)
        out = self.ok(self.w.run("revive", SID_A, "--dry-run"))
        self.assertIn("waiting may not clear it at all", out)
        self.assertNotIn("wait until", out)


# -------------------------------------------------------- what the move says it will cost

class MoveNotes(Base):
    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[
            user("refactor the parser", cwd, SID_A, perm="acceptEdits"),
            assistant("on it", cwd, SID_A)])

    def dry(self, *extra, **env):
        return self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run",
                                  *extra, **env))

    def test_the_plan_names_the_mode_and_where_it_came_from(self):
        out = self.dry()
        self.assertIn("mode acceptEdits", out)
        (self.personal / "settings.json").write_text(json.dumps(
            {"permissions": {"defaultMode": "bypassPermissions"}}))
        out = self.dry()
        self.assertIn("mode acceptEdits", out)          # deliberate: never raised
        self.assertIn("--permission-mode bypassPermissions", out)

    def test_an_accidental_mode_is_raised_and_the_bypass_note_follows_it(self):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_B, lines=[user("go", cwd, SID_B, perm="auto")])
        (self.personal / "settings.json").write_text(json.dumps(
            {"permissions": {"defaultMode": "bypassPermissions"}}))
        out = self.ok(self.w.run("move", SID_B, "--to", "personal", "--dry-run"))
        self.assertIn("mode bypassPermissions", out)
        # the warning keys on the mode that will be USED, or it would go missing exactly
        # where it is needed
        self.assertIn("skipDangerousModePermissionPrompt", out)
        (self.personal / "settings.json").write_text(json.dumps(
            {"permissions": {"defaultMode": "bypassPermissions"},
             "skipDangerousModePermissionPrompt": True}))
        self.assertNotIn("skipDangerousModePermissionPrompt",
                         self.ok(self.w.run("move", SID_B, "--to", "personal", "--dry-run")))

    def test_the_connectors_line_is_always_in_the_plan(self):
        out = self.dry()
        self.assertIn("claude.ai connectors", out)
        self.assertIn("no terminal can attach one", out)

    def test_a_home_that_never_saw_the_remote_control_dialog_is_warned_about(self):
        self.assertIn("Enable Remote Control", self.dry())
        d = json.loads((self.personal / ".claude.json").read_text())
        d["remoteDialogSeen"] = True
        (self.personal / ".claude.json").write_text(json.dumps(d))
        self.assertNotIn("never answered", self.dry())

    def test_a_target_with_no_installed_plugins_is_warned_about(self):
        self.assertNotIn("INSTALLED plugins", self.dry())
        (self.work / "plugins").mkdir()
        (self.work / "plugins" / "installed_plugins.json").write_text("{}")
        self.assertIn("no INSTALLED plugins", self.dry())
        (self.personal / "plugins").mkdir()
        (self.personal / "plugins" / "installed_plugins.json").write_text("{}")
        self.assertNotIn("no INSTALLED plugins", self.dry())

    def test_skills_the_target_home_lacks_are_named_unless_the_dirs_are_shared(self):
        (self.work / "skills" / "a-skill").mkdir(parents=True)
        self.assertIn("has no skills of its own", self.dry())
        # the usual fix: both homes linked to one directory — then nothing is lost
        shared = self.w.root / "shared-skills"
        shared.mkdir()
        (shared / "a-skill").mkdir()
        for home in (self.work, self.personal):
            if (home / "skills").is_dir() and not (home / "skills").is_symlink():
                shutil.rmtree(str(home / "skills"))
            os.symlink(str(shared), str(home / "skills"))
        self.assertNotIn("has no skills", self.dry())

    def test_a_target_whose_credential_is_gone_is_refused_before_anything_is_written(self):
        before = sorted(str(p) for p in self.personal.rglob("*"))
        self.refused(self.w.run("move", SID_A, "--to", "personal",
                                CSM_LOGIN_PROBE="false"), "credential is GONE", "/login")
        self.assertEqual(sorted(str(p) for p in self.personal.rglob("*")), before)

    def test_an_unreadable_credential_store_warns_and_still_moves(self):
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run",
                                 CSM_LOGIN_PROBE="unknown"))
        self.assertIn("UNVERIFIED", out)

    def test_the_accounts_view_shows_the_same_three_states(self):
        self.assertIn("ok", self.ok(self.w.run("accounts")))
        self.assertIn("CREDENTIAL GONE", self.ok(self.w.run("accounts",
                                                            CSM_LOGIN_PROBE="false")))
        self.assertIn("UNVERIFIED", self.ok(self.w.run("accounts",
                                                       CSM_LOGIN_PROBE="unknown")))

    def test_the_one_machine_default_and_its_one_exception_are_in_the_help(self):
        out = self.ok(self.w.run("--help"))
        self.assertIn("Both homes are on this machine", out)
        self.assertIn("`move --from-machine M` brings the session over", out)


class MoveCost(Base):
    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.src = self.w.session(self.work, SID_A, lines=[
            user("refactor the parser", cwd, SID_A, perm="acceptEdits"),
            assistant("on it", cwd, SID_A)])

    def test_the_success_block_says_what_the_move_cost(self):
        out = self.ok(self.w.run("move", SID_A, "--to", "personal"))
        self.assertIn("what this move costs", out)
        self.assertIn("RE-READS", out)                 # thinking dropped across orgs
        self.assertIn("Move early", out)
        self.assertIn("names the source account", out)
        # 🛑 the over-claim v0.1.0 made about the app's scrollback is gone
        self.assertNotIn("does not re-render", out)
        self.assertIn("NEW claude.ai session", out)

    def test_two_accounts_in_one_organization_keep_their_thinking(self):
        self.w.account("team", "me@team.example", org="org-1")   # same org as `work`
        out = self.ok(self.w.run("move", SID_A, "--to", "team"))
        self.assertIn("same organization", out)

    def test_an_unmeasurable_mode_is_reported_as_the_one_requested(self):
        out = self.ok(self.w.run("move", SID_A, "--to", "personal"))
        self.assertIn("not a measurement", out)        # nothing appended, no footer
        self.assertIn("capture-pane", out)

    def test_a_session_that_comes_up_in_another_mode_is_reported_not_assumed(self):
        # the resumed session records its own mode past the end of the copy
        out = self.ok(self.w.run("move", SID_A, "--to", "personal",
                                 FAKE_CLAUDE_APPEND_MODE="auto",
                                 FAKE_CLAUDE_PROJECTS=str(self.personal / "projects")))
        self.assertIn("it came up in auto", out)
        self.assertIn("from the transcript", out)
        self.assertIn("csm stop", out)

    def test_the_window_footer_is_read_when_the_transcript_says_nothing(self):
        out = self.ok(self.w.run("move", SID_A, "--to", "personal",
                                 FAKE_CLAUDE_FOOTER="⏵⏵ bypass permissions on"))
        self.assertIn("it came up in bypassPermissions", out)
        self.assertIn("from the window footer", out)

    def test_the_log_records_both_modes_and_no_secrets(self):
        self.ok(self.w.run("move", SID_A, "--to", "personal", **DIRTY))
        text = (self.w.state / "log").read_text()
        self.assertIn("asked acceptEdits", text)
        self.assertIn("came up", text)
        for value in set(DIRTY.values()):
            if len(value) > 3:
                self.assertNotIn(value, text, value)

    def test_every_tmux_call_runs_with_the_scrubbed_environment(self):
        env_log = self.w.root / "tmux-env.jsonl"
        self.ok(self.w.run("move", SID_A, "--to", "personal", FAKE_TMUX_ENV=env_log,
                           CSM_TMUX_SOCKET="csm-test-socket", **DIRTY))
        rows = [json.loads(x) for x in env_log.read_text().splitlines() if x.strip()]
        self.assertTrue(rows)
        for env in rows:
            leaked = [k for k in env if k.startswith(("CLAUDE", "ANTHROPIC"))]
            self.assertEqual(leaked, [], leaked)
        # and the private socket reaches every call, so a test server is really private
        for call in self.w.tmux_log():
            self.assertEqual(call[:2], ["-L", "csm-test-socket"], call)

    def test_the_moved_session_keeps_your_own_credentials_for_other_tools(self):
        self.ok(self.w.run("move", SID_A, "--to", "personal", AWS_PROFILE="work",
                           GOOGLE_APPLICATION_CREDENTIALS="/tmp/gcp.json", **DIRTY))
        env = self.w.claude_calls()[0]["env"]
        self.assertEqual(env["AWS_PROFILE"], "work")
        self.assertEqual(env["GOOGLE_APPLICATION_CREDENTIALS"], "/tmp/gcp.json")
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.personal))
        for gone in DIRTY:
            self.assertNotIn(gone, env, gone)

    def test_the_session_s_side_data_arrives_with_it(self):
        (self.work / "file-history" / SID_A).mkdir(parents=True)
        (self.work / "file-history" / SID_A / "abc@v1").write_text("a backup")
        self.ok(self.w.run("move", SID_A, "--to", "personal"))
        self.assertTrue((self.personal / "file-history" / SID_A / "abc@v1").exists())


# ---------------------------------------------------------------------------- csm stop

class Stop(Base):
    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[
            user("refactor the parser", cwd, SID_A), assistant("ok", cwd, SID_A)])

    def move(self, *extra, **env):
        return self.ok(self.w.run("move", SID_A, "--to", "personal", *extra, **env))

    def windows(self):
        st = json.loads(self.w.tmux_state.read_text())
        return {s: sorted(w) for s, w in st["sessions"].items()}

    def test_it_removes_the_window_csm_opened_and_keeps_the_transcript(self):
        self.move()
        self.assertEqual(self.windows(), {"csm-personal": ["moved-11111111"]})
        # after a move the id sits in BOTH homes: the copy with a moved- window is the one
        # `stop` means, so this is not refused as ambiguous
        self.assertEqual(len([r for r in self.listing() if r["local_id"] == SID_A]), 2)
        out = self.ok(self.w.run("stop", SID_A))
        self.assertIn("✅ stopped", out)
        self.assertEqual(self.windows(), {"csm-personal": []})
        self.assertTrue((self.personal / "projects").exists())
        dest = list((self.personal / "projects").rglob(f"{SID_A}.jsonl"))
        self.assertEqual(len(dest), 1)              # never deleted
        self.assertIn("STOPPED", (self.w.state / "log").read_text())

    def test_a_second_move_is_accepted_again_once_the_window_is_gone(self):
        self.move()
        # after a move the id sits in both homes, so the source copy is named by its row
        rows = self.listing()
        row = str([r["pos"] for r in rows
                   if r["account"] == "work" and r["local_id"] == SID_A][0])
        self.refused(self.w.run("move", row, "--to", "personal"), "already exists",
                     "csm stop")
        self.ok(self.w.run("stop", SID_A))
        self.ok(self.w.run("move", row, "--to", "personal"))

    def test_it_refuses_a_session_it_did_not_start_and_names_what_it_did(self):
        self.move()
        cwd = str(self.w.work)
        self.w.session(self.personal, SID_B, lines=[user("mine", cwd, SID_B)])
        self.refused(self.w.run("stop", SID_B), "csm did not start",
                     "csm only ends what it started", "moved-11111111")

    def test_a_dry_run_stops_nothing(self):
        self.move()
        out = self.ok(self.w.run("stop", SID_A, "--dry-run"))
        self.assertIn("kill-window -t '=csm-personal:=moved-11111111'", out)
        self.assertIn("dry run", out)
        self.assertEqual(self.windows(), {"csm-personal": ["moved-11111111"]})

    def test_a_live_process_in_that_window_is_signalled(self):
        self.move()
        proc = self.w.spawn()
        wid = json.loads(self.w.tmux_state.read_text())["sessions"]["csm-personal"][
            "moved-11111111"]["id"]
        self.w.live(self.personal, SID_A, proc.pid, tmux=f"csm-personal:{wid}.%1")
        out = self.ok(self.w.run("stop", SID_A))
        self.assertIn("SIGTERM pid %d" % proc.pid, out)
        proc.wait(timeout=10)
        self.assertEqual(proc.returncode, -signal.SIGTERM)

    def test_a_pid_sitting_in_another_window_is_left_alone(self):
        self.move()
        proc = self.w.spawn()
        self.w.live(self.personal, SID_A, proc.pid, tmux="csm-personal:@99.%1")
        self.refused(self.w.run("stop", SID_A), "not the one in the window csm opened")
        self.assertIsNone(proc.poll())
        self.assertEqual(self.windows(), {"csm-personal": ["moved-11111111"]})

    def test_a_pid_that_cannot_be_tied_to_the_window_is_not_signalled(self):
        # a live row with no tmux field: a `moved-` window plus a pid is not the same as
        # a pid IN that window
        self.move()
        proc = self.w.spawn()
        self.w.live(self.personal, SID_A, proc.pid)
        out = self.ok(self.w.run("stop", SID_A))
        self.assertIn("cannot be tied to the window", out)
        self.assertEqual(self.windows(), {"csm-personal": []})
        self.assertIsNone(proc.poll())

    def test_an_unprovable_pid_is_not_signalled_but_the_window_still_goes(self):
        self.move()
        proc = self.w.spawn()
        wid = json.loads(self.w.tmux_state.read_text())["sessions"]["csm-personal"][
            "moved-11111111"]["id"]
        self.w.live(self.personal, SID_A, proc.pid, tmux=f"csm-personal:{wid}.%1",
                    proc_start="Mon Jan  1 00:00:00 2001")
        out = self.ok(self.w.run("stop", SID_A))
        self.assertIn("signal no process", out)
        self.assertIn("SIGHUPs the process tree", out)
        self.assertEqual(self.windows(), {"csm-personal": []})
        self.assertIsNone(proc.poll())              # the fake tmux kills no real process

    def test_it_refuses_to_stop_the_session_running_it(self):
        self.move()
        self.refused(self.w.run("stop", SID_A, CLAUDE_CODE_SESSION_ID=SID_A),
                     "from another session")

    def test_with_no_tmux_session_at_all_it_refuses_rather_than_fails(self):
        self.refused(self.w.run("stop", SID_A), "csm did not start",
                     "csm has moved nothing here")

    # --- CSM_TMUX_SESSION: a tmux session per account that is already yours -------

    def test_the_window_goes_in_the_tmux_session_the_template_names(self):
        tsv = self.w.table(("work", "me@work.example", self.work, "laptop", "w"),
                           ("personal", "me@home.example", self.personal, "laptop", "p"))
        env = {"CSM_TMUX_SESSION": "mine-{handle}", "CSM_ACCOUNTS": str(tsv),
               "CSM_MACHINE": "laptop"}
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", **env))
        self.assertIn("mine-p:moved-11111111", out)
        self.assertEqual(self.windows(), {"mine-p": ["moved-11111111"]})

    def test_a_window_moved_under_one_template_is_still_stopped_under_it(self):
        """🛑 The reason the knob exists. `stop`'s whole candidate set is the `moved-`
        windows of each account's tmux session, so a session already moved is only
        reachable while that session is spelled the way the move spelled it."""
        env = {"CSM_TMUX_SESSION": "mine-{name}"}
        self.ok(self.w.run("move", SID_A, "--to", "personal", **env))
        self.assertEqual(self.windows(), {"mine-personal": ["moved-11111111"]})
        # The DEFAULT spelling cannot see it. It refuses — here as "which copy did you
        # mean", because without the `moved-` window to point at the copy the id sits in
        # two homes — and nothing is signalled or closed either way.
        r = self.w.run("stop", SID_A)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.windows(), {"mine-personal": ["moved-11111111"]})
        # and named by its row, so is the copy, it is the window that cannot be found
        row = str([x["pos"] for x in json.loads(self.ok(self.w.run("list", "--json")))
                   if x["account"] == "personal" and x["local_id"] == SID_A][0])
        self.refused(self.w.run("stop", row), "csm has moved nothing here")
        self.assertEqual(self.windows(), {"mine-personal": ["moved-11111111"]})
        # the spelling it was opened under does
        out = self.ok(self.w.run("stop", SID_A, **env))
        self.assertIn("✅ stopped", out)
        self.assertEqual(self.windows(), {"mine-personal": []})

    def test_a_template_naming_nothing_it_knows_falls_back_instead_of_failing(self):
        # a bad knob must not take `move` down: the default spelling is used
        out = self.ok(self.w.run("move", SID_A, "--to", "personal",
                                 CSM_TMUX_SESSION="broken-{nosuchfield}"))
        self.assertIn("csm-personal:moved-11111111", out)
        self.assertEqual(self.windows(), {"csm-personal": ["moved-11111111"]})

    def test_a_template_may_not_smuggle_a_dot_or_a_colon_into_a_session_name(self):
        # tmux reads `a:b.c` as session:window.pane, so the name is sanitised whatever
        # the template said
        self.ok(self.w.run("move", SID_A, "--to", "personal",
                           CSM_TMUX_SESSION="a.b:c-{name}"))
        self.assertEqual(self.windows(), {"a-b-c-personal": ["moved-11111111"]})

    def test_a_name_that_would_read_as_a_flag_is_not_passed_to_tmux_as_one(self):
        # the name goes to `tmux -s` and `-t`, so a leading hyphen is dropped rather than
        # handed to tmux as an option
        self.ok(self.w.run("move", SID_A, "--to", "personal",
                           CSM_TMUX_SESSION=".x-{name}"))
        self.assertEqual(self.windows(), {"x-personal": ["moved-11111111"]})

    def test_a_template_that_sanitises_away_to_nothing_falls_back(self):
        self.ok(self.w.run("move", SID_A, "--to", "personal", CSM_TMUX_SESSION=":::"))
        self.assertEqual(self.windows(), {"csm-personal": ["moved-11111111"]})


# -------------------------------------------------------------------------- csm modes

class Modes(Base):
    """`csm modes` — which LIVE sessions run weaker than this machine's defaultMode.

    Why the subcommand exists: a settings check reads the FILE, and the file can be right on
    every machine while a live Remote Control worker sits in `auto`, because such a worker
    records the mode the stored session record holds rather than the one its server was
    started with. The exit contract is the one scheduled callers read: 0 `ok:`, 1 `FAULT:`,
    3 `INCOMPLETE:` — unknown is never ok.
    """

    def setUp(self):
        super().setUp()
        # An accounts file, so discovery never turns the SHARED settings home below into a
        # third account, and so the rows print handles the way a configured install does.
        self.third = self.w.account("elsewhere", "me@other.example")
        self.tsv = self.w.table(("work", "me@work.example", self.work, "laptop", "w"),
                                ("personal", "me@home.example", self.personal, "laptop", "p"),
                                ("elsewhere", "me@other.example", self.third, "desktop", "e"))
        self.shared = self.w.home / ".claude"
        self.shared.mkdir(exist_ok=True)
        self.default_mode("bypassPermissions")

    def default_mode(self, mode):
        f = self.shared / "settings.json"
        f.write_text(json.dumps({"permissions": {"defaultMode": mode} if mode
                                 else {}}))

    def csm(self, *args, **env):
        """⚠️ NOT called `run`: a method of that name shadows `TestCase.run` and the
        fixture is never built at all."""
        e = {"CSM_ACCOUNTS": str(self.tsv), "CSM_MACHINE": "laptop"}
        e.update(env)
        return self.w.run(*args, **e)

    def listing(self, *extra):
        return json.loads(self.ok(self.csm("list", "--json", *extra)))

    def worker(self, sid, perm, home=None, title=None, status="idle", entrypoint="sdk-cli",
               pid=None, proc_start=None, empty=False, argv_tail=()):
        """One live session: a transcript (or an empty one) plus a live registry row."""
        home = self.work if home is None else home
        cwd = str(self.w.work)
        if empty:
            self.w.session(home, sid, lines=[])
        else:
            self.w.session(home, sid, lines=[
                user(title or "Phone work", cwd, sid, perm=perm or None),
                assistant("ok", cwd, sid)])
        p = self.w.spawn(argv_tail=argv_tail) if pid is None else None
        pid = p.pid if p is not None else pid
        self.w.live(home, sid, pid, status=status, entrypoint=entrypoint,
                    proc_start=proc_start)
        return pid

    def report(self, *args):
        r = self.csm("modes", "--json", *args)
        self.assertIn(r.returncode, (0, 1, 3), r.stdout + r.stderr)
        return json.loads(r.stdout)

    # --- the verdicts ----------------------------------------------------

    def test_a_remote_control_worker_in_auto_is_a_fault_and_check_exits_1(self):
        self.worker(SID_A, "auto", title="Stuck in auto")
        rep = self.report()
        self.assertEqual(rep["faults"], 1)
        self.assertEqual(rep["default_mode"], "bypassPermissions")
        row = rep["rows"][0]
        self.assertEqual((row["mode"], row["verdict"], row["mode_source"]),
                         ("auto", "fault", "its transcript"))
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("FAULT: "), r.stdout)
        self.assertIn("auto", r.stdout)
        self.assertIn("w 11111111 (auto)", r.stdout)       # the HANDLE, not the name

    def test_everything_at_the_machines_mode_reads_ok_and_exits_0(self):
        self.worker(SID_A, "bypassPermissions")
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("ok: "), r.stdout)
        self.assertEqual(self.report()["faults"], 0)

    def test_plan_and_accept_edits_are_deliberate_and_never_faults(self):
        self.worker(SID_A, "plan")
        self.worker(SID_B, "acceptEdits")
        rep = self.report()
        self.assertEqual((rep["faults"], rep["deliberate"]), (0, 2))
        self.assertEqual(self.csm("modes", "--check").returncode, 0)

    def test_a_terminal_session_is_reported_but_is_not_a_fault(self):
        # entrypoint `cli` = somebody started it themselves; its mode is their own choice.
        self.worker(SID_A, "default", entrypoint="cli")
        rep = self.report()
        self.assertEqual((rep["faults"], rep["deliberate"]), (0, 1))
        self.assertIn("not spawned by a Remote Control server", rep["rows"][0]["why"])

    def test_no_defaultMode_on_this_machine_is_INCOMPLETE_not_ok(self):
        self.default_mode(None)
        self.worker(SID_A, "auto")
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("INCOMPLETE: "), r.stdout)
        self.assertIn("(no defaultMode on this machine)", r.stdout)
        self.assertEqual(self.report()["unknown"], 1)

    def test_a_quiet_machine_with_no_defaultMode_still_reads_as_a_sentence(self):
        """🛑 The other side of the one above, and the FIRST thing a fresh install prints.
        With nothing live there is nothing to judge, so this is the `ok:` path — and that
        path used to interpolate an empty `default_mode` raw, giving `ok: every live
        session is at  or stronger`: a malformed sentence, with a double space where the
        mode should be, in the one line this tool promises to keep stable, claiming
        sessions are at or stronger than a baseline that is not there. `render_modes` has
        always said `(none named)` for the same reading.
        """
        self.default_mode(None)
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("ok: "), r.stdout)
        self.assertIn("(no defaultMode on this machine)", r.stdout)
        self.assertNotIn("is at  or stronger", r.stdout)
        self.assertNotIn("  ", r.stdout.strip())      # no hole where a value belongs
        self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
        self.assertEqual(r.stderr, "")

    def test_a_machine_that_names_a_default_is_unchanged_byte_for_byte(self):
        """The fallback above may not cost a byte on the path a scheduled caller reads: it
        is a prefix-matched contract, and every machine that has been set up names a mode.
        """
        self.worker(SID_A, "bypassPermissions")
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith(
            "ok: every live session is at bypassPermissions or stronger — "), r.stdout)
        self.assertNotIn("no defaultMode", r.stdout)

    def test_an_unknown_mode_is_never_judged_and_never_ok(self):
        self.worker(SID_A, "telepathy")
        rep = self.report()
        self.assertEqual((rep["faults"], rep["unknown"]), (0, 1))
        self.assertIn("not a mode this tool knows", rep["rows"][0]["why"])
        self.assertEqual(self.csm("modes", "--check").returncode, 3)

    def test_a_live_session_list_drops_is_still_counted_here(self):
        """🛑 The hole this subcommand was written around: a server's pre-created session
        has a 0-byte transcript, which `list`'s subagent rule skips. `modes` reads every
        live registry row and puts what it could not measure in `coverage.unread`."""
        pid = self.worker(SID_A, "", empty=True)
        self.assertEqual(self.listing(), [])                 # list cannot see it
        rep = self.report()
        self.assertEqual(rep["live"], 1)
        self.assertEqual(len(rep["coverage"]["unread"]), 1)
        u = rep["coverage"]["unread"][0]
        self.assertIn("pid %d" % pid, u["name"])
        self.assertIn("0 bytes", u["reason"])
        self.assertIsNotNone(u["age_s"])
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith("INCOMPLETE: "), r.stdout)

    def test_the_launch_mode_is_read_off_the_live_command_line(self):
        """A session with nothing recorded is not unknown if its own argv says the mode."""
        self.worker(SID_A, "", empty=True,
                    argv_tail=("--permission-mode", "bypassPermissions"))
        rep = self.report()
        row = rep["rows"][0]
        self.assertEqual((row["mode"], row["mode_source"], row["verdict"]),
                         ("bypassPermissions", "its own command line", "ok"))
        self.assertEqual(rep["coverage"]["unread"], [])
        self.assertEqual(self.csm("modes", "--check").returncode, 0)

    def test_coverage_names_the_homes_read_and_the_ones_with_none(self):
        self.worker(SID_A, "bypassPermissions")
        shutil.rmtree(str(self.personal))
        cov = self.report()["coverage"]
        self.assertIn("w", cov["read"])
        self.assertIn("p", cov["absent"])     # no home here: nothing of theirs runs here
        self.assertNotIn("e", cov["read"] + cov["absent"])   # on another machine
        self.assertEqual(cov["unread"], [])

    def test_a_row_the_table_puts_on_no_machine_is_not_swept(self):
        """`machines` = `-` means "on no machine": there is nothing there to measure. It is
        not the same as a table that never named machines at all, which sweeps every row."""
        nowhere = self.w.account("nowhere", "me@nowhere.example")
        self.tsv = self.w.table(
            ("work", "me@work.example", self.work, "laptop", "w"),
            ("nowhere", "me@nowhere.example", nowhere, "-", "n"))
        self.worker(SID_A, "bypassPermissions")
        cov = self.report()["coverage"]
        self.assertEqual(cov["read"], ["w"])
        self.assertNotIn("n", cov["read"] + cov["absent"])

    def test_a_registry_file_that_will_not_parse_is_unread_not_absent(self):
        """🛑 An unreadable registry row beside a LIVE pid used to read downstream exactly
        like "this home runs nothing" — the one answer that is never true."""
        p = self.w.spawn()
        (self.work / "sessions").mkdir(exist_ok=True)
        (self.work / "sessions" / ("%d.json" % p.pid)).write_text("{not json")
        rep = self.report()
        self.assertEqual(rep["live"], 0)
        self.assertEqual(len(rep["coverage"]["unread"]), 1)
        u = rep["coverage"]["unread"][0]
        self.assertIn("could not be read as JSON", u["reason"])
        self.assertIn("pid %d" % p.pid, u["reason"])
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith("INCOMPLETE: "), r.stdout)

    def test_a_home_with_no_sessions_directory_at_all_is_a_quiet_zero_not_unread(self):
        """🛑 The other half of the one above, and the half a scheduled caller feels. The
        CLI creates `sessions/` the first time a session runs in a home, so its ABSENCE is
        a measurement — nothing has ever run there. Calling that "unread" would turn every
        machine with a quiet home into a permanent INCOMPLETE, and a daily check reads a
        permanent INCOMPLETE as a broken sweep.
        """
        self.worker(SID_A, "bypassPermissions")          # work gets a sessions/ dir
        self.assertFalse((self.personal / "sessions").exists())
        rep = self.report()
        self.assertEqual(rep["coverage"]["unread"], [])
        self.assertIn("p", rep["coverage"]["read"])
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("ok: "), r.stdout)

    def test_a_registry_directory_that_will_not_open_is_unread_not_quiet(self):
        """🛑 `modes --check` must say INCOMPLETE about a home it could not look into. The
        bare `except OSError` under it returned `{}`, which reads downstream exactly like
        "this home runs nothing" — so a locked-out home used to pass as ok."""
        self.worker(SID_A, "bypassPermissions")
        d = self.personal / "sessions"
        d.mkdir(exist_ok=True)
        os.chmod(str(d), 0o000)
        # ⚠️ Restored in the test body, not with addCleanup: cleanups run AFTER tearDown,
        # and tearDown is what deletes the fixture tree — which it cannot, through a 000
        # directory.
        try:
            if os.access(str(d), os.R_OK):
                self.skipTest("this filesystem or user ignores a 000 directory")
            rep = self.report()
            r = self.csm("modes", "--check")
        finally:
            os.chmod(str(d), 0o700)
        unread = rep["coverage"]["unread"]
        self.assertEqual(len(unread), 1, unread)
        self.assertEqual(unread[0]["name"], "p")
        self.assertIn("would not open", unread[0]["reason"])
        self.assertIn("nothing says what is running", unread[0]["reason"])
        self.assertIsNone(unread[0]["age_s"])
        self.assertIn("p", rep["coverage"]["read"])     # read in part, not absent
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("INCOMPLETE: "), r.stdout)
        self.assertEqual(r.stderr, "")

    def test_a_ps_that_will_not_answer_is_unread_not_an_empty_machine(self):
        """🛑 The third shape of the same mistake, in the sweep's OTHER prover. `ps_table`
        asks `ps` once for the whole machine, and `subprocess.run` without `check` raises
        for nothing — so a `ps` that rejects the argument spelling (a different `ps` than
        the one this was measured against, a container's cut-down one) exits non-zero with
        an empty stdout. Returning `{}` for that says every pid on the machine is gone, and
        the sweep then explains an unread row with "pid N is not in `ps` output" — a claim
        about a question it never got to ask, printed in the one `INCOMPLETE:` line a
        scheduled caller reads.
        """
        self.worker(SID_A, None, empty=True)            # mode readable only from argv
        ps = self.w.bin / "ps"                          # the fixture bin is FIRST on PATH
        ps.write_text("#!/bin/sh\necho 'ps: illegal option' >&2\nexit 1\n")
        ps.chmod(0o755)
        rep = self.report()
        self.assertIs(rep["coverage"]["ps"], False,
                      "coverage claimed ps was read when it exited non-zero")
        unread = rep["coverage"]["unread"]
        self.assertEqual(len(unread), 1, unread)
        self.assertIn("could not be asked", unread[0]["reason"])
        self.assertNotIn("not in `ps` output", unread[0]["reason"])
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("INCOMPLETE: "), r.stdout)
        self.assertIn("could not be asked", r.stdout)
        # the parsed contract survives a blinded prover: one line, and nothing on stderr
        self.assertEqual(len(r.stdout.strip().splitlines()), 1, r.stdout)
        self.assertEqual(r.stderr, "")

    def test_the_account_filter_narrows_the_sweep(self):
        self.worker(SID_A, "auto", home=self.work)
        self.worker(SID_B, "auto", home=self.personal)
        self.assertEqual(self.report()["faults"], 2)
        rep = self.report("--account", "p")
        self.assertEqual(rep["faults"], 1)
        self.assertEqual(rep["coverage"]["read"], ["p"])

    def test_an_unknown_account_is_one_refusal_and_not_a_traceback(self):
        self.refused(self.csm("modes", "--account", "nope"), "is no account here")

    # --- the one parsed line ---------------------------------------------

    def test_the_ok_line_names_a_deliberate_session_instead_of_claiming_bypass(self):
        """🛑 `ok:` may not say "every live session is at bypassPermissions or stronger"
        while a session sits in `plan`. It is not a fault — somebody chose it — but the one
        line a scheduled pass prints has to agree with the table above it."""
        self.worker(SID_A, "plan", title="Planning")
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("ok: "), r.stdout)
        self.assertNotIn("every live session is at bypassPermissions or stronger", r.stdout)
        self.assertIn("1 deliberately weaker session(s)", r.stdout)
        self.assertIn("(plan)", r.stdout)

    def test_a_machine_with_nothing_running_reads_cleanly(self):
        """A quiet machine once answered `0 live session(s) on laptop, ; 2 home(s) read` —
        the dangling comma of an empty count list. It is a normal state."""
        r = self.csm("modes", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("0 live session(s) on laptop;", r.stdout)
        self.assertNotIn(", ;", r.stdout)
        self.assertIn("live sessions: 0\n", self.ok(self.csm("modes")))

    def test_check_writes_one_line_to_stdout_and_nothing_at_all_to_stderr(self):
        """🛑 THE CONTRACT. A scheduled caller captures stdout AND stderr together, deletes
        the newlines, truncates and matches the prefix — so one stray byte on either stream
        turns a reading of the machine into a fault report about the tool. This runs with
        the credential probe forced (which announces itself on stderr on every run that
        touches it) and with a table row that is dropped (which is logged, never printed).
        """
        self.worker(SID_A, "bypassPermissions")
        bad = self.w.table(("work", "me@work.example", self.work, "laptop", "w"),
                           ("personal", "me@home.example", self.personal, "laptop", "-BAD"))
        r = self.csm("modes", "--check", CSM_ACCOUNTS=str(bad))
        self.assertEqual(r.stderr, "", "stderr must be EMPTY: %r" % r.stderr)
        self.assertEqual(len(r.stdout.rstrip("\n").split("\n")), 1, r.stdout)
        self.assertTrue(r.stdout.endswith("\n"))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_a_numeric_knob_that_is_not_a_number_does_not_take_the_check_down(self):
        """🛑 NOT A TRACEBACK, because of where these are read.

        Every numeric knob is read at IMPORT time, so a `ValueError` there lands before
        `main` has run — on every subcommand, `modes --check` included, whose whole promise
        is one line on stdout and nothing on stderr. A scheduled caller then reports a
        fault in the machine's permission modes when what happened is that somebody typed
        `CSM_LIMIT=lots` in a shell profile. The knob falls back to its default and the log
        says so, which is the rule the rest of the file follows for a value it cannot use.
        """
        self.worker(SID_A, "bypassPermissions")
        log = self.w.root / "knoblog"
        r = self.csm("modes", "--check", CSM_LIMIT="lots", CSM_METER_MAX_AGE="soon",
                     CSM_LOG=str(log))
        self.assertEqual(r.stderr, "", "stderr must be EMPTY: %r" % r.stderr)
        self.assertEqual(len(r.stdout.rstrip("\n").split("\n")), 1, r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertTrue(r.stdout.startswith("ok: "), r.stdout)
        said = log.read_text()
        self.assertIn("CSM_LIMIT='lots' is not a number: using 20", said)
        self.assertIn("CSM_METER_MAX_AGE='soon' is not a number", said)
        # and the default really is what took effect
        self.assertIn("(default 20", self.ok(self.csm("list", "--help", CSM_LIMIT="lots")))

    def test_the_check_line_survives_being_flattened_the_way_a_caller_flattens_it(self):
        """What the callers actually do: `2>&1 | tr -d '\\n' | cut -c1-220`, then match the
        prefix. The flattened line still has to start with the verdict."""
        self.worker(SID_A, "auto")
        r = self.csm("modes", "--check")
        flat = (r.stdout + r.stderr).replace("\n", "")[:220]
        self.assertTrue(flat.startswith("FAULT: "), flat)
        self.assertEqual(r.returncode, 1)

    def test_check_in_json_carries_the_line_and_its_exit_code(self):
        self.worker(SID_A, "auto")
        r = self.csm("modes", "--check", "--json")
        self.assertEqual(r.returncode, 1, r.stderr)
        d = json.loads(r.stdout)
        self.assertTrue(d["check"]["line"].startswith("FAULT: "))
        self.assertEqual(d["check"]["exit"], 1)

    # --- the restart plan ------------------------------------------------

    def test_restart_idle_plans_the_idle_workers_and_apply_is_refused(self):
        """🛑 `--apply` stays shut while `RESPAWN_VERIFIED` is False: the respawn itself is
        measured, the MODE a respawned worker comes back in is not."""
        pid = self.worker(SID_A, "auto")
        r = self.csm("modes", "--restart-idle")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("SIGTERM  pid %d" % pid, r.stdout)
        self.assertIn("--apply is REFUSED", r.stdout)
        self.assertIn("dry run — nothing was signalled", r.stdout)
        a = self.csm("modes", "--restart-idle", "--apply")
        self.assertEqual(a.returncode, 2, a.stdout + a.stderr)
        self.assertIn("refused", a.stderr)
        self.assertIn("would be SIGTERMed", a.stdout)       # the plan is still printed
        os.kill(pid, 0)                     # still there: nothing was signalled

    def test_restart_idle_refuses_a_busy_row_a_reused_pid_and_a_pid_that_is_not_claude(self):
        busy = self.worker(SID_A, "auto", status="busy")
        other = self.w.spawn()
        self.worker(SID_B, "auto", home=self.personal, pid=other.pid,
                    proc_start="Mon Jan  1 00:00:00 2001")
        notclaude = self.w.spawn("sleep")
        self.worker(SID_C, "auto", home=self.third, pid=notclaude.pid,
                    proc_start=ps_start(notclaude.pid))
        self.tsv = self.w.table(
            ("work", "me@work.example", self.work, "laptop", "w"),
            ("personal", "me@home.example", self.personal, "laptop", "p"),
            ("elsewhere", "me@other.example", self.third, "laptop", "e"))
        r = self.csm("modes", "--restart-idle")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("  SIGTERM  pid", r.stdout)
        self.assertIn("0 idle Remote Control worker(s) would be SIGTERMed", r.stdout)
        self.assertIn("3 fault row(s) refused", r.stdout)
        self.assertIn("not idle", r.stdout)
        self.assertIn("has been reused", r.stdout)
        self.assertIn("not running the Claude Code CLI", r.stdout)
        for p in (busy, other.pid, notclaude.pid):
            os.kill(p, 0)

    def test_a_registry_row_with_no_start_time_is_refused_and_never_name_matched(self):
        """🛑 There is NO name-based fallback. Accepting "argv[0] is the Claude Code CLI" as
        proof when a row recorded no start time is exactly what pid reuse passes on a machine
        running dozens of them."""
        p = self.w.spawn()
        self.worker(SID_A, "auto", pid=p.pid, proc_start="")
        r = self.csm("modes", "--restart-idle")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 idle Remote Control worker(s) would be SIGTERMed", r.stdout)
        self.assertIn("recorded no start time", r.stdout)
        os.kill(p.pid, 0)

    def test_the_restart_plan_in_json_says_it_applied_nothing(self):
        pid = self.worker(SID_A, "auto")
        r = self.csm("modes", "--restart-idle", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)["restart"]
        self.assertEqual((res["applied"], res["stopped"], res["respawn_verified"]),
                         (False, [], False))
        self.assertEqual(len(res["would_stop"]), 1)
        os.kill(pid, 0)                     # still there: a plan signals nothing

    def test_this_session_is_never_a_candidate_however_wrong_its_mode(self):
        pid = self.worker(SID_A, "auto")
        r = self.csm("modes", "--restart-idle", CLAUDE_CODE_SESSION_ID=SID_A)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 idle Remote Control worker(s) would be SIGTERMed", r.stdout)
        self.assertIn("it is THIS session", r.stdout)
        os.kill(pid, 0)

    def test_the_table_header_lines_up_with_the_rows_under_it(self):
        self.worker(SID_A, "auto", title="Phone work")
        out = self.ok(self.csm("modes"))
        head = next(l for l in out.splitlines() if l.lstrip().startswith("#  "))
        row = next(l for l in out.splitlines() if " FAULT" in l)
        for word in ("mode", "state", "age", "session"):
            self.assertIn(word, head)
        self.assertEqual(head.index("mode"), row.index("auto"),
                         "the `mode` header is not over its column:\n%s\n%s" % (head, row))
        self.assertEqual(head.index("session"), row.index(SID_A[:8]),
                         "the `session` header is not over its column:\n%s\n%s"
                         % (head, row))

    def test_apply_on_its_own_is_refused_and_prints_no_reading_at_all(self):
        """🛑 `--apply` is the only destructive switch here, and on its own it is a refusal,
        not a flag quietly dropped: `csm modes --apply` used to print the read-only table
        and exit 0 — a reading of the machine that looks exactly like a report of work
        done."""
        pid = self.worker(SID_A, "auto")
        r = self.csm("modes", "--apply")
        self.refused(r, "--apply does nothing on its own", "--restart-idle")
        self.assertEqual(r.stdout, "", "a refusal may not also print a reading")
        os.kill(pid, 0)

    def test_the_advice_names_the_session_id_and_not_a_row_number(self):
        """🛑 These row numbers are this sweep's; `csm move 3` resolves against whatever
        `csm list` last wrote. An id means the same thing in both."""
        self.worker(SID_A, "auto")
        out = self.ok(self.csm("modes", "--restart-idle"))
        self.assertIn("csm move %s --to <account>" % SID_A[:8], out)
        self.assertIn("not a row number", out)


class RestartApplyGate(InProc):
    """`modes --restart-idle --apply`: the SIGTERM half, which the gate keeps shut today.

    🛑 Why these run IN PROCESS and flip the constant themselves: `RESPAWN_VERIFIED` is
    False in the shipped file and there is deliberately no environment variable that can
    turn it on — a stray export in a scheduled pass must never be able to stop a session. So
    the CLI path is pinned above (nothing signalled, exit 2), and the behaviour AFTER the one
    experiment in `RESPAWN_VERIFIED`'s note is pinned here, against this suite's own
    throwaway processes.
    """

    def setUp(self):
        super().setUp()
        self.mod.RESPAWN_VERIFIED = True                 # the experiment, pretended done
        self.mod.CAPTURES = self.root / "captures"

    def row(self, pid, **extra):
        r = {"pos": 1, "verdict": "fault", "handle": "w", "account": "work",
             "home": str(self.root / "home" / ".claude-work"), "local_id": SID_A,
             "short": SID_A[:8], "pid": pid, "proc_start": ps_start(pid), "mode": "auto",
             "status": "idle", "entrypoint": "sdk-cli", "is_self": False,
             "is_server": False, "hosts_itself": False, "tmux": "", "transcript": "",
             "mtime": 0.0, "title": "Stuck in auto", "age": "3h"}
        r.update(extra)
        return r

    def gone(self, pid, seconds=5.0):
        """The signal this suite's own child died of, or None if it is still running.

        ⚠️ Not `os.kill(pid, 0)`: this process is the child's parent and does not reap it,
        so a SIGTERMed child is a ZOMBIE and `kill(pid, 0)` still succeeds. `wait()` is what
        tells the two apart, and its return code names the signal (−15 = SIGTERM).
        """
        kid = next((k for k in self.procs if k.pid == pid), None)
        self.assertIsNotNone(kid, "pid %d is not one of this test's children" % pid)
        try:
            return kid.wait(timeout=seconds)
        except subprocess.TimeoutExpired:
            return None

    def test_a_proven_idle_worker_is_signalled_and_reported(self):
        pid = self.claude_proc().pid
        done, failed = self.mod.apply_restart([self.row(pid)])
        self.assertEqual(([r["pid"] for r in done], failed), ([pid], []))
        self.assertEqual(self.gone(pid), -15, "pid %d was not SIGTERMed" % pid)
        self.assertIn("SIGTERM pid %d" % pid, self.mod.LOG.read_text())

    def test_the_refusals_are_read_again_between_the_plan_and_the_kill(self):
        """A plan is not a licence: a row that turned busy, or is a server, or is this
        session, is left alone even though it reached `apply_restart`."""
        cases = [("status", "busy", "not idle"),
                 ("is_self", True, "THIS session"),
                 ("is_server", True, "SERVER"),
                 ("hosts_itself", True, "hosts its own"),
                 ("entrypoint", "cli", "not sdk-cli"),
                 ("verdict", "info", "not fault")]
        for field, value, words in cases:
            with self.subTest(field=field):
                pid = self.claude_proc().pid
                done, failed = self.mod.apply_restart([self.row(pid, **{field: value})])
                self.assertEqual(done, [])
                self.assertEqual(len(failed), 1)
                self.assertIn(words, failed[0][1])
                self.assertIn("left alone at the last gate", failed[0][1])
                os.kill(pid, 0)                                   # untouched

    def test_a_pid_whose_start_time_does_not_match_is_never_signalled(self):
        pid = self.claude_proc().pid
        done, failed = self.mod.apply_restart(
            [self.row(pid, proc_start="Mon Jan  1 00:00:00 2001")])
        self.assertEqual(done, [])
        self.assertIn("has been reused", failed[0][1])
        os.kill(pid, 0)

    def test_a_pid_that_is_not_a_claude_is_never_signalled(self):
        """`is_claude_exe` stays an EXTRA condition on top of the start time. The row here
        carries a real `procStart`, so the start time MATCHES and the only thing left to
        refuse on is what the pid is running."""
        p = subprocess.Popen(["/bin/sleep", "120"])
        self.procs.append(p)
        done, failed = self.mod.apply_restart([self.row(p.pid)])
        self.assertEqual(done, [])
        self.assertIn("not running the Claude Code CLI", failed[0][1])
        os.kill(p.pid, 0)

    def test_a_row_with_no_recorded_start_time_is_refused_and_not_name_matched(self):
        """🛑 No name-based fallback. The process IS a `claude`, and it is still refused,
        because nothing says WHICH session that pid is."""
        pid = self.claude_proc().pid
        done, failed = self.mod.apply_restart([self.row(pid, proc_start="")])
        self.assertEqual(done, [])
        self.assertIn("recorded no start time", failed[0][1])
        os.kill(pid, 0)

    def test_one_bad_row_does_not_stop_the_good_one_and_the_render_says_both(self):
        good, busy = self.claude_proc().pid, self.claude_proc().pid
        done, failed = self.mod.apply_restart(
            [self.row(good), self.row(busy, pos=2, status="busy", short="bb000000")])
        self.assertEqual([r["pid"] for r in done], [good])
        self.assertEqual(len(failed), 1)
        self.assertEqual(self.gone(good), -15)
        os.kill(busy, 0)
        text = self.mod.render_restart({"machine": "laptop", "at": "2026-10-15T16:00:00"},
                                       [], [], done, failed, applied=True)
        self.assertIn("STOPPED  pid %d" % good, text)
        self.assertIn("1 signalled, 1 left alone", text)
        self.assertNotIn("dry run", text)

    def test_a_capture_that_answers_nothing_never_blocks_the_signal(self):
        pid = self.claude_proc().pid
        # No tmux pane on the row: the capture answers "" and the stop goes ahead anyway.
        done, failed = self.mod.apply_restart([self.row(pid)])
        self.assertEqual(([r["pid"] for r in done], failed), ([pid], []))
        self.assertEqual(done[0]["pane_kept"], "")
        self.assertEqual(self.gone(pid), -15)

    def test_the_pane_is_captured_while_the_worker_is_still_running(self):
        """🛑 CAPTURE FIRST, PROVE, THEN SIGNAL. A pane is the one thing a SIGTERM destroys
        that is nowhere else on disk, so the read has to happen while the worker is still
        up — which is what the fake tmux here measures, rather than the capture merely
        having happened at some point."""
        pid = self.claude_proc().pid
        kid = next(k for k in self.procs if k.pid == pid)
        alive_when_read = []

        def fake_tmux(*a, **kw):
            alive_when_read.append(kid.poll() is None)
            return types.SimpleNamespace(returncode=0, stdout="> a draft nobody sent\n",
                                         stderr="")

        self.mod.tmux = fake_tmux
        done, failed = self.mod.apply_restart([self.row(pid, tmux="csm-work:@3.%7")])
        self.assertEqual(([r["pid"] for r in done], failed), ([pid], []))
        self.assertEqual(alive_when_read, [True],
                         "the pane was read after the SIGTERM, not before it")
        kept = Path(done[0]["pane_kept"])
        self.assertTrue(kept.is_file(), "nothing was parked: %r" % done[0]["pane_kept"])
        body = kept.read_text()
        self.assertIn("a draft nobody sent", body)
        self.assertIn("modes --restart-idle", body)      # why it was parked
        self.assertEqual(self.gone(pid), -15)


class ModeSweepUnits(InProc):
    """The sweep's pure pieces: the launch-mode reader, the judge and the check line."""

    def test_the_launch_mode_is_read_in_both_spellings_and_canonicalised(self):
        self.assertEqual(self.mod.launch_mode("claude --permission-mode auto"), "auto")
        self.assertEqual(self.mod.launch_mode("claude --permission-mode=acceptEdits"),
                         "acceptEdits")
        self.assertEqual(self.mod.launch_mode("claude --permission-mode manual"), "default")
        self.assertEqual(self.mod.launch_mode("claude --resume x"), "")
        self.assertEqual(self.mod.launch_mode(None), "")

    def test_a_server_and_a_self_hosting_session_are_told_apart(self):
        server = "/x/claude remote-control --name room"
        itself = "/x/claude --resume abc --remote-control=moved-abc"
        self.assertTrue(self.mod.RC_SERVER_RE.search(server))
        self.assertFalse(self.mod.RC_SERVER_RE.search(itself))
        self.assertTrue(self.mod.RC_REPL_RE.search(itself))
        # 🛑 Anchored to argv[0]: a binary whose name merely ENDS in the word is not it.
        self.assertFalse(self.mod.RC_SERVER_RE.search("/x/myclaude remote-control"))

    def base_row(self, **extra):
        r = {"mode": "auto", "entrypoint": "sdk-cli"}
        r.update(extra)
        return r

    def test_an_unmeasurable_mode_is_unknown_and_never_ok(self):
        v, why = self.mod.judge_mode(self.base_row(mode=""), "bypassPermissions")
        self.assertEqual(v, "unknown")
        self.assertIn("nothing could say", why)

    def test_a_stronger_mode_than_the_default_is_ok(self):
        v, _ = self.mod.judge_mode(self.base_row(mode="bypassPermissions"), "acceptEdits")
        self.assertEqual(v, "ok")

    def test_a_mode_the_tool_does_not_know_is_unknown_not_weakest(self):
        v, _ = self.mod.judge_mode(self.base_row(mode="telepathy"), "bypassPermissions")
        self.assertEqual(v, "unknown")

    def test_the_counts_tail_has_no_dangling_comma_when_nothing_runs(self):
        rep = {"coverage": {"unread": [], "read": ["w", "p"]}, "live": 0, "mode_counts": {},
               "faults": 0, "unknown": 0, "deliberate": 0, "machine": "laptop",
               "default_mode": "bypassPermissions", "rows": []}
        line, code = self.mod.modes_check_line(rep)
        self.assertEqual(code, 0)
        self.assertIn("0 live session(s) on laptop;", line)
        self.assertNotIn(", ;", line)

    def test_a_fault_outranks_an_incomplete_read(self):
        rep = {"coverage": {"unread": [{"name": "w:pid 1", "reason": "no transcript"}],
                            "read": ["w"]},
               "live": 2, "mode_counts": {"auto": 1}, "faults": 1, "unknown": 1,
               "deliberate": 0, "machine": "laptop", "default_mode": "bypassPermissions",
               "rows": [{"verdict": "fault", "handle": "w", "short": "aaaaaaaa",
                         "mode": "auto"}]}
        line, code = self.mod.modes_check_line(rep)
        self.assertEqual(code, 1)
        self.assertTrue(line.startswith("FAULT: "))
        self.assertIn("1 not measured (w:pid 1: no transcript)", line)

    def test_more_than_four_deliberate_sessions_are_counted_not_listed(self):
        rows = [{"verdict": "info", "handle": "w", "short": "s%d" % i, "mode": "plan"}
                for i in range(6)]
        rep = {"coverage": {"unread": [], "read": ["w"]}, "live": 6,
               "mode_counts": {"plan": 6}, "faults": 0, "unknown": 0, "deliberate": 6,
               "machine": "laptop", "default_mode": "bypassPermissions", "rows": rows}
        line, code = self.mod.modes_check_line(rep)
        self.assertEqual(code, 0)
        self.assertIn("+2 more", line)

    def test_the_shared_settings_home_decides_the_machines_mode_before_an_account_home(self):
        shared = self.root / "shared"
        shared.mkdir()
        (shared / "settings.json").write_text(
            json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
        self.mod.SHARED_HOME = shared
        a = self.account("work", settings={"permissions": {"defaultMode": "plan"}})
        mode, where = self.mod.machine_default_mode([a])
        self.assertEqual(mode, "bypassPermissions")
        self.assertIn("shared", where)

    def test_with_no_shared_settings_an_account_home_answers(self):
        self.mod.SHARED_HOME = self.root / "no-such-home"
        a = self.account("work", settings={"permissions": {"defaultMode": "acceptEdits"}})
        mode, where = self.mod.machine_default_mode([a])
        self.assertEqual(mode, "acceptEdits")
        self.assertIn(".claude-work", where)

    def test_a_row_session_is_built_from_the_row_and_never_resolved_again(self):
        """What `apply_restart` proves a pid with must not depend on the accounts file:
        the table may have been edited between the plan and the kill."""
        s = self.mod.row_session({"account": "work", "handle": "w", "pid": 42,
                                  "proc_start": "x", "local_id": SID_A, "home": "/nope"})
        self.assertEqual((s.pid, s.proc_start, s.account.name, s.account.label),
                         (42, "x", "work", "w"))
        self.assertEqual(s.short, SID_A[:8])

    def test_a_transcript_that_cannot_be_stat_d_is_not_an_empty_one(self):
        """🛑 The sweep's "0 bytes" clause asks `file_size(...) == 0`, so `None` may not
        pass for empty — and the read may never RAISE, because on the `--check` path a
        traceback is one stray byte on stderr and every scheduled reader of that one line
        turns that into a FAULT about the machine. A transcript deleted between the listing
        and this read is exactly that race.
        """
        empty = self.root / "empty.jsonl"
        empty.write_text("")
        self.assertEqual(self.mod.file_size(empty), 0)
        gone = self.root / "no-such-transcript.jsonl"
        self.assertIsNone(self.mod.file_size(gone))
        self.assertNotEqual(self.mod.file_size(gone), 0)
        locked = self.root / "locked"
        locked.mkdir()
        os.chmod(str(locked), 0o000)
        try:
            if os.access(str(locked / "x.jsonl"), os.F_OK):
                self.skipTest("this filesystem or user ignores a 000 directory")
            self.assertIsNone(self.mod.file_size(locked / "x.jsonl"))
        finally:
            os.chmod(str(locked), 0o700)

    def test_the_settings_local_layer_is_read_for_the_machines_mode_too(self):
        self.mod.SHARED_HOME = self.root / "no-such-home"
        a = self.account("work", settings={"permissions": {"defaultMode": "plan"}})
        (a.home / "settings.local.json").write_text(
            json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
        mode, _ = self.mod.machine_default_mode([a])
        self.assertEqual(mode, "bypassPermissions")


# --------------------------------------------------------------------------- csm matrix

class MatrixRows(InProc):
    """Every row of the matrix, in process: each of these builds config homes in a
    tempdir and reads them, with no subprocess at all. The command around them — the
    table, --json, --check, --account — is the subprocess class below.

    🛑 No test here asks a real credential store: the tri-state probe is stubbed, which
    is also how the three answers are driven. The probe itself is pinned by `LoginProbe`.
    """

    def setUp(self):
        super().setUp()
        self.cwd = str(self.root / "work")
        os.makedirs(self.cwd, exist_ok=True)
        self.shared = self.root / "shared"
        self.shared.mkdir()
        self.cred = {}
        self.mod.credential_present = lambda a: self.cred.get(a.name, True)

    def homes(self, *names):
        return [self.account(n, email="%s@example.com" % n) for n in names]

    def rows(self, accts):
        return dict((r.layer, r) for r in self.mod.matrix_rows(accts, self.cwd))

    @staticmethod
    def cells(row, accts):
        return dict((a.name, (c.text, c.state)) for a, c in zip(accts, row.cells))

    def link(self, accts, name, body="x\n", dir_=False):
        """One real entry in a shared directory, linked into each home."""
        src = self.shared / name
        if dir_:
            src.mkdir()
        else:
            src.write_text(body)
        for a in accts:
            os.symlink(str(src), str(a.home / name))
        return src

    # --- what "shared" means ---------------------------------------------------

    def test_one_file_linked_into_every_home_is_what_reads_as_shared(self):
        accts = self.homes("one", "two")
        self.link(accts, "settings.json", '{"permissions": {"defaultMode": "plan"}}')
        by = self.rows(accts)
        self.assertEqual(self.cells(by["settings.json"], accts),
                         {"one": ("shared", "ok"), "two": ("shared", "ok")})
        # and the value behind that one file is read through the link, for every home
        self.assertEqual(self.cells(by["permissions mode"], accts),
                         {"one": ("plan", "ok"), "two": ("plan", "ok")})

    def test_two_copies_with_the_same_bytes_are_still_two_files(self):
        accts = self.homes("one", "two")
        for a in accts:
            (a.home / "settings.json").write_text('{"a": 1}')
        row = self.rows(accts)["settings.json"]
        self.assertEqual(self.cells(row, accts), {"one": ("own(=)", "diff"),
                                                  "two": ("own(=)", "diff")})
        self.assertIn("point every home's settings.json at one copy", row.note)
        self.assertTrue(row.counts)

    def test_a_symlink_to_nowhere_is_its_own_state_never_absent(self):
        # what renaming a config home leaves behind: the CLI then loads nothing, silently
        accts = self.homes("one", "two")
        os.symlink(str(self.root / "gone" / "CLAUDE.md"), str(accts[0].home / "CLAUDE.md"))
        row = self.rows(accts)["CLAUDE.md"]
        self.assertEqual(self.cells(row, accts), {"one": ("DANGLING", "diff"),
                                                  "two": ("–", "diff")})
        self.assertIn("a symlink to nowhere in one", row.note)

    def test_one_realpath_inside_another_home_is_shared_with_a_warning(self):
        # 🛑 one realpath for every home IS shared, wherever that path lives. The
        # commonest working layout puts the shared copy in the default home and links the
        # others at it; calling that a divergence contradicts the legend and makes
        # `--check` impossible to get green. Where it lives earns a note, not a fault.
        accts = self.homes("one", "two")
        (accts[0].home / "skills").mkdir()
        os.symlink(str(accts[0].home / "skills"), str(accts[1].home / "skills"))
        row = self.rows(accts)["skills"]
        self.assertEqual(self.cells(row, accts), {"one": ("shared", "ok"),
                                                  "two": ("shared", "ok")})
        self.assertEqual(row.state, "ok")
        self.assertIn("inside one's own home", row.note)
        self.assertIn("dangles", row.note)

    def test_that_layout_does_not_fail_the_check(self):
        accts = self.homes("one", "two")
        for name in ("settings.json", "CLAUDE.md"):
            (accts[0].home / name).write_text("{}" if name.endswith(".json") else "hi")
            os.symlink(str(accts[0].home / name), str(accts[1].home / name))
        rows = self.mod.matrix_rows(accts, str(self.root))
        failed = [r.layer for r in rows if r.counts and r.state == "diff"]
        self.assertNotIn("settings.json", failed)
        self.assertNotIn("CLAUDE.md", failed)

    def test_a_dangling_link_is_still_a_divergence(self):
        accts = self.homes("one", "two")
        os.symlink(str(self.root / "gone"), str(accts[1].home / "skills"))
        row = self.rows(accts)["skills"]
        self.assertEqual(self.cells(row, accts)["two"], ("DANGLING", "diff"))
        self.assertEqual(row.state, "diff")

    def test_a_group_of_homes_sharing_one_copy_is_not_called_shared(self):
        accts = self.homes("one", "two", "three")
        self.link(accts[:2], "CLAUDE.md")
        row = self.rows(accts)["CLAUDE.md"]
        self.assertEqual(self.cells(row, accts), {"one": ("shared(2)", "diff"),
                                                  "two": ("shared(2)", "diff"),
                                                  "three": ("–", "diff")})

    def test_an_entry_no_home_has_is_consistent_not_divergent(self):
        accts = self.homes("one", "two")
        by = self.rows(accts)
        for layer in ("agents", "commands", "output-styles", "scheduled-tasks"):
            self.assertEqual(self.cells(by[layer], accts),
                             {"one": ("–", "ok"), "two": ("–", "ok")}, layer)

    def test_one_home_has_nothing_to_compare_itself_with(self):
        accts = self.homes("one")
        (accts[0].home / "settings.json").write_text("{}")
        self.assertEqual(self.cells(self.rows(accts)["settings.json"], accts),
                         {"one": ("own", "ok")})

    # --- plugins ---------------------------------------------------------------

    def test_a_plugin_enabled_for_every_home_and_installed_in_one(self):
        accts = self.homes("one", "two")
        self.link(accts, "settings.json",
                  json.dumps({"enabledPlugins": {"notes@m": True, "off@m": False}}))
        (accts[0].home / "plugins").mkdir()
        (accts[0].home / "plugins" / "installed_plugins.json").write_text(
            json.dumps({"plugins": {"notes@m": [{"version": "1.0.0"}]}}))
        row = self.rows(accts)["plugins enabled"]
        self.assertEqual(self.cells(row, accts), {"one": ("1 ok", "ok"),
                                                  "two": ("1 missing", "diff")})
        self.assertIn("two enables but has not installed notes@m", row.note)
        self.assertTrue(row.counts)

    def test_an_absent_registry_is_a_measurement_and_a_broken_one_is_not(self):
        accts = self.homes("one", "two")
        self.link(accts, "settings.json",
                  json.dumps({"enabledPlugins": {"notes@m": True}}))
        (accts[0].home / "plugins").mkdir()
        (accts[0].home / "plugins" / "installed_plugins.json").write_text("{not json")
        row = self.rows(accts)["plugins enabled"]
        self.assertEqual(self.cells(row, accts)["one"], ("?", "unknown"))
        # an ABSENT registry means nothing is installed — a fact the row must fire on
        self.assertEqual(self.cells(row, accts)["two"], ("1 missing", "diff"))
        # and the unknown's reason survives on a row that also diverges
        self.assertIn("unparseable", row.note)

    # --- memory ----------------------------------------------------------------

    def test_memory_per_home_needs_your_hands_but_is_not_a_failure(self):
        accts = self.homes("one", "two")
        row = self.rows(accts)["auto-memory"]
        self.assertEqual(self.cells(row, accts), {"one": ("own home", "cold"),
                                                  "two": ("own home", "cold")})
        self.assertIn("CLAUDE_CODE_REMOTE_MEMORY_DIR", row.note)
        self.assertEqual(row.state, "cold")        # cold is never a --check failure

    def test_one_env_key_in_a_shared_settings_file_makes_one_store(self):
        accts = self.homes("one", "two")
        store = self.root / "memory-store"
        store.mkdir()
        self.link(accts, "settings.json",
                  json.dumps({"env": {"CLAUDE_CODE_REMOTE_MEMORY_DIR": str(store)}}))
        row = self.rows(accts)["auto-memory"]
        self.assertEqual(self.cells(row, accts), {"one": ("store", "ok"),
                                                  "two": ("store", "ok")})
        self.assertIn("every home reads", row.note)

    def test_a_half_finished_cutover_reads_as_MIXED(self):
        accts = self.homes("one", "two")
        store = self.root / "memory-store"
        store.mkdir()
        (accts[0].home / "settings.json").write_text(
            json.dumps({"env": {"CLAUDE_CODE_REMOTE_MEMORY_DIR": str(store)}}))
        row = self.rows(accts)["auto-memory"]
        self.assertEqual(self.cells(row, accts), {"one": ("store", "diff"),
                                                  "two": ("own home", "diff")})
        self.assertIn("MIXED", row.note)
        self.assertTrue(row.counts)

    def test_two_homes_pointing_at_two_stores_are_not_sharing_one(self):
        accts = self.homes("one", "two")
        for a, name in zip(accts, ("store-a", "store-b")):
            store = self.root / name
            store.mkdir()
            (a.home / "settings.json").write_text(
                json.dumps({"env": {"CLAUDE_CODE_REMOTE_MEMORY_DIR": str(store)}}))
        row = self.rows(accts)["auto-memory"]
        self.assertEqual(self.cells(row, accts), {"one": ("store", "diff"),
                                                  "two": ("store", "diff")})
        self.assertIn("store-a", row.note)
        self.assertIn("store-b", row.note)

    def test_a_memory_key_that_is_not_an_absolute_path_is_not_a_store(self):
        accts = self.homes("one")
        (accts[0].home / "settings.json").write_text(
            json.dumps({"env": {"CLAUDE_CODE_REMOTE_MEMORY_DIR": "~/store"}}))
        self.assertEqual(self.cells(self.rows(accts)["auto-memory"], accts)["one"][0],
                         "own home")

    # --- the first-run gates ---------------------------------------------------

    def test_a_cold_home_is_named_for_the_directory_asked_about(self):
        accts = self.homes("one", "two")
        by = self.rows(accts)
        self.assertEqual(self.cells(by["folder trust"], accts)["one"],
                         ("will ask", "cold"))
        self.assertEqual(self.cells(by["onboarding"], accts)["one"], ("will ask", "cold"))
        self.assertIn("csm move", by["folder trust"].note)
        self.assertFalse(by["folder trust"].counts)

    def test_the_gates_are_per_home_and_per_directory(self):
        one = self.account("one", hasCompletedOnboarding=True,
                           projects={self.cwd: {"hasTrustDialogAccepted": True}})
        two = self.account("two")
        accts = [one, two]
        by = self.rows(accts)
        self.assertEqual(self.cells(by["folder trust"], accts)["one"], ("trusted", "ok"))
        self.assertEqual(self.cells(by["onboarding"], accts)["one"], ("done", "ok"))
        self.assertEqual(self.cells(by["folder trust"], accts)["two"],
                         ("will ask", "cold"))
        # another directory is another key, in the same home
        other = dict((r.layer, r) for r in self.mod.matrix_rows(accts, str(self.root)))
        self.assertEqual(self.cells(other["folder trust"], accts)["one"],
                         ("will ask", "cold"))

    def test_bypass_consent_is_read_from_the_settings_and_the_old_state_key(self):
        one = self.account("one", settings={"skipDangerousModePermissionPrompt": True})
        two = self.account("two", bypassPermissionsModeAccepted=True)
        three = self.account("three")
        accts = [one, two, three]
        self.assertEqual(self.cells(self.rows(accts)["bypass consent"], accts),
                         {"one": ("accepted", "ok"), "two": ("accepted(old)", "ok"),
                          "three": ("will warn", "cold")})

    def test_the_mode_keys_are_reported_verbatim(self):
        one = self.account("one", settings={"permissions": {
            "defaultMode": "acceptEdits", "disableAutoMode": "disable"}})
        two = self.account("two", settings={"permissions": {"defaultMode": "plan"}})
        accts = [one, two]
        by = self.rows(accts)
        self.assertEqual(self.cells(by["permissions mode"], accts),
                         {"one": ("acceptEdits", "diff"), "two": ("plan", "diff")})
        self.assertEqual(self.cells(by["disableAutoMode"], accts),
                         {"one": ("disable", "diff"), "two": ("–", "diff")})
        # an ABSENT defaultMode is `default`, so those two must not read as a divergence
        three = self.account("three", settings={"permissions": {"defaultMode": "default"}})
        four = self.account("four", settings={})
        self.assertEqual(self.rows([three, four])["permissions mode"].state, "ok")

    # --- the login -------------------------------------------------------------

    def test_a_credential_that_is_gone_is_a_failure_with_the_way_back(self):
        accts = self.homes("one", "two")
        self.cred["two"] = False
        row = self.rows(accts)["login"]
        self.assertEqual(self.cells(row, accts), {"one": ("ok", "ok"),
                                                  "two": ("GONE", "diff")})
        self.assertIn("/login", row.note)
        self.assertTrue(row.counts)

    def test_could_not_look_is_unknown_never_signed_out(self):
        accts = self.homes("one")
        self.cred["one"] = None
        row = self.rows(accts)["login"]
        self.assertEqual(self.cells(row, accts)["one"], ("? unverified", "unknown"))
        self.assertIn("not the same as signed out", row.note)
        self.assertEqual(row.state, "unknown")

    def test_a_home_that_names_nobody_is_cold_not_mistaken_for_signed_out(self):
        accts = [self.account("one", email=None)]
        by = self.rows(accts)
        self.assertEqual(self.cells(by["login"], accts)["one"], ("signed out", "cold"))
        self.assertEqual(self.cells(by["account"], accts)["one"], ("–", "cold"))

    def test_a_home_signed_in_as_someone_else_than_the_accounts_file_expects(self):
        a = self.account("one", email="someone@example.com")
        a.expect = "wanted@example.com"
        row = self.rows([a])["account"]
        self.assertEqual(self.cells(row, [a])["one"][1], "diff")
        self.assertIn("would spend the wrong quota", row.note)

    # --- reading, honestly -----------------------------------------------------

    def test_an_unparseable_settings_file_makes_its_rows_unknown_not_empty(self):
        accts = self.homes("one", "two")
        (accts[0].home / "settings.json").write_text("{nope")
        by = self.rows(accts)
        for layer in ("plugins enabled", "permissions mode", "disableAutoMode",
                      "bypass consent"):
            self.assertEqual(self.cells(by[layer], accts)["one"][1], "unknown", layer)
            self.assertIn("unparseable", by[layer].note, layer)

    def test_an_unparseable_state_file_makes_its_rows_unknown_not_empty(self):
        accts = self.homes("one", "two")
        accts[0].state_file.write_text("{nope")
        accts[0]._oauth = None
        by = self.rows(accts)
        for layer in ("account", "MCP servers", "onboarding", "folder trust"):
            self.assertEqual(self.cells(by[layer], accts)["one"][1], "unknown", layer)

    def test_user_scope_mcp_servers_are_listed_by_name_and_nothing_else(self):
        one = self.account("one", mcpServers={
            "linear": {"type": "http", "url": "https://example.test/t0ps3cret"}})
        two = self.account("two")
        accts = [one, two]
        row = self.rows(accts)["MCP servers"]
        self.assertEqual(self.cells(row, accts), {"one": ("linear", "diff"),
                                                  "two": ("–", "diff")})
        out = self.mod.render_matrix(list(self.rows(accts).values()), accts, self.cwd,
                                     {"homes": 2, "shareable": 10, "agree": 8,
                                      "divergent": 1, "unknown": 0, "cold": 3,
                                      "failed": []})
        for leak in ("t0ps3cret", "example.test"):
            self.assertNotIn(leak, out)

    def test_the_summary_never_folds_an_unknown_into_a_match(self):
        accts = self.homes("one", "two")
        (accts[0].home / "settings.json").write_text("{nope")
        rows = self.mod.matrix_rows(accts, self.cwd)
        sumy = self.mod.matrix_summary(rows, accts)
        self.assertGreaterEqual(sumy["unknown"], 1)
        self.assertLess(sumy["agree"], sumy["shareable"])


class MatrixUnits(InProc):
    """The matrix's readers and its renderer."""

    def test_json_is_read_three_ways_so_absent_is_never_unreadable(self):
        p = self.root / "x.json"
        self.assertEqual(self.mod.read_json3(p), (None, "absent"))
        p.write_text("{oops")
        self.assertEqual(self.mod.read_json3(p), (None, "unparseable"))
        p.write_text('{"a": 1}')
        self.assertEqual(self.mod.read_json3(p), ({"a": 1}, "ok"))
        d = self.root / "adir"
        d.mkdir()
        self.assertEqual(self.mod.read_json3(d)[1], "unreadable")

    def test_an_entry_is_judged_by_its_realpath_and_a_dead_link_is_not_absent(self):
        real = self.root / "real.md"
        real.write_text("hello\n")
        here = self.root / "here.md"
        os.symlink(str(real), str(here))
        e = self.mod.entry_at(here)
        self.assertEqual((e.kind, e.link, e.real),
                         ("file", True, os.path.realpath(str(real))))
        self.assertTrue(e.digest)
        dead = self.root / "dead.md"
        os.symlink(str(self.root / "nowhere.md"), str(dead))
        self.assertEqual(self.mod.entry_at(dead).kind, "dangling")
        self.assertEqual(self.mod.entry_at(self.root / "nothing.md").kind, "absent")

    def test_the_cli_version_comes_off_the_launcher_symlink(self):
        bundle = self.root / ".local" / "share" / "claude" / "versions" / "2.1.300"
        bundle.mkdir(parents=True)
        (bundle / "claude").write_text("#!/bin/sh\n")
        launcher = self.root / "claude"
        os.symlink(str(bundle / "claude"), str(launcher))
        self.mod.claude_bin = lambda: str(launcher)
        self.assertEqual(self.mod.cli_version()[0], "2.1.300")
        self.mod.claude_bin = lambda: ""
        self.assertEqual(self.mod.cli_version()[0], "")
        self.assertIn("no `claude` on PATH", self.mod.cli_version()[1])

    def test_project_folder_turns_every_other_character_into_a_dash(self):
        self.assertEqual(self.mod.project_folder("/a/b_c.d"), "-a-b-c-d")
        # past 200 characters the CLI appends a hash of its own: say nothing rather than
        # name a directory that is not the one it would use
        self.assertEqual(self.mod.project_folder("/" + "x" * 400), "")

    def test_the_glyphs_degrade_to_stand_ins_of_the_same_width(self):
        line = "%s one %s two %s three – … →" % (self.mod.V_SHARED, self.mod.V_SETUP,
                                                 self.mod.V_PER)

        class Ascii:
            encoding = "ascii"

        real, sys.stdout = sys.stdout, Ascii()
        try:
            out = self.mod.printable(line)
        finally:
            sys.stdout = real
        self.assertEqual(self.mod.dwidth(out), self.mod.dwidth(line))
        self.assertEqual(out, out.encode("ascii", "strict").decode())

    def test_the_table_fits_the_width_it_is_laid_out_for(self):
        self.mod.credential_present = lambda a: True     # no store is asked, even a fake
        accts = [self.account("one"), self.account("two"), self.account("three")]
        cwd = str(self.root / "work")
        os.makedirs(cwd, exist_ok=True)
        rows = self.mod.matrix_rows(accts, cwd)
        out = self.mod.render_matrix(rows, accts, cwd,
                                     self.mod.matrix_summary(rows, accts))
        for line in out.splitlines():
            if len(line.split()) < 2:
                continue        # one unbreakable token (an absolute path) on its own line
            self.assertLessEqual(self.mod.dwidth(line), self.mod.MATRIX_WIDTH, line)
        self.assertIn("fungibility matrix on", out)
        for name in ("layer", "one", "two", "three"):
            self.assertIn(name, out.splitlines()[3])


class MatrixCommand(Base):
    """The command around the rows: the table, --json, --check, --account.

    🛑 One of these pins what the whole command promises — that it is read-only, offline
    and prompt-free: the config homes are compared byte for byte before and after, and
    neither the fake `claude` nor the fake tmux may be called at all.
    """

    def matrix(self, *extra, **env):
        return self.w.run("matrix", "--cwd", str(self.w.work), *extra, **env)

    def table(self, *extra, **env):
        return self.ok(self.matrix(*extra, **env))

    def test_the_table_names_every_home_every_layer_and_what_to_do(self):
        (self.work / "settings.json").write_text('{"a": 1}')
        out = self.table()
        # the advice column wraps, so prose is matched against the unwrapped text: how
        # wide a path prints (a symlinked TMPDIR vs a real one) is not what is pinned
        flat = " ".join(out.split())
        self.assertIn("fungibility matrix on", out)
        for col in ("work", "personal"):
            self.assertIn(col, out)
        for layer in ("account", "login", "settings.json", "CLAUDE.md", "skills",
                      "plugins enabled", "MCP servers", "auto-memory", "onboarding",
                      "folder trust", "permissions mode", "disableAutoMode",
                      "bypass consent", "CLI version", "connectors", "MCP sign-ins"):
            self.assertIn(layer, out)
        self.assertIn("point every home's settings.json at one copy", flat)
        self.assertIn("shareable layer(s) agree across 2 home(s)", flat)
        # the legend explains every verdict the table used
        self.assertIn("one shared file or key away", flat)
        self.assertIn("could not look", flat)

    def test_connectors_and_mcp_signins_are_stated_whatever_is_measured(self):
        out = self.table()
        # a span row wraps instead of being truncated: these are the rows people quote
        flat = " ".join(out.split())
        self.assertIn("claude.ai/customize/connectors, not readable", flat)
        self.assertIn("offline", flat.split("claude.ai/customize/connectors")[1])
        self.assertIn("per home — stored inside the login credential, not read", flat)

    def test_the_json_carries_the_homes_the_rows_the_cells_and_the_exit(self):
        d = json.loads(self.table("--json"))
        self.assertEqual(d["tool"], "claude-session-mover")
        self.assertEqual(sorted(h["name"] for h in d["homes"]), ["personal", "work"])
        layers = [r["layer"] for r in d["rows"]]
        self.assertIn("auto-memory", layers)
        for row in d["rows"]:
            self.assertIn(row["state"], ("ok", "diff", "cold", "unknown", "info"))
            for c in row["cells"]:
                self.assertIn(c["state"], ("ok", "diff", "cold", "unknown", "info"))
                self.assertIn(c["home"], ("work", "personal", "*"))
        self.assertEqual(set(d["summary"]), {"homes", "shareable", "agree", "divergent",
                                             "unknown", "cold", "failed"})
        self.assertEqual(d["exit"], 0)

    def test_check_passes_a_machine_whose_shared_layers_agree(self):
        # nothing configured, nothing divergent: the cold rows (memory, the gates) are
        # "needs your hands", and a check that failed on them would stay red forever
        r = self.matrix("--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("needing your hands", r.stdout)

    def test_check_fails_on_a_divergent_layer_and_on_a_login_that_is_gone(self):
        (self.work / "CLAUDE.md").write_text("# mine\n")
        r = self.matrix("--check")
        self.assertEqual(r.returncode, 1, r.stdout)
        d = json.loads(self.matrix("--json", "--check").stdout)
        self.assertEqual(d["exit"], 1)
        self.assertEqual(d["summary"]["failed"], ["CLAUDE.md"])
        r = self.matrix("--check", CSM_LOGIN_PROBE="false")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("login", json.loads(
            self.matrix("--json", "--check", CSM_LOGIN_PROBE="false").stdout
        )["summary"]["failed"])

    def test_an_unknown_never_fails_the_check_and_is_never_a_match(self):
        out = self.table(CSM_LOGIN_PROBE="unknown")
        self.assertIn("could not be read", out)
        self.assertEqual(self.matrix("--check", CSM_LOGIN_PROBE="unknown").returncode, 0)

    def test_account_limits_the_columns_and_one_home_says_so(self):
        out = self.table("--account", "work")
        self.assertIn("nothing to compare it with", out)
        self.assertNotIn("personal", out)
        d = json.loads(self.table("--account", "work,personal", "--json"))
        self.assertEqual(sorted(h["name"] for h in d["homes"]), ["personal", "work"])
        d = json.loads(self.table("--account", "work", "--account", "work", "--json"))
        self.assertEqual(len(d["homes"]), 1)            # named twice is still one column
        self.refused(self.matrix("--account", "nope"), "is no account here")

    def test_it_writes_nothing_and_runs_neither_claude_nor_tmux(self):
        (self.work / "plugins").mkdir()
        (self.personal / "settings.json").write_text('{"a": 1}')
        before = self.snapshot()
        self.table()
        self.table("--json")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.w.claude_calls(wait=0.2), [])
        self.assertEqual(self.w.tmux_log(), [])

    def test_accounts_points_at_it(self):
        self.assertIn("csm matrix", self.ok(self.w.run("accounts")))

    def test_the_columns_and_the_notes_name_the_homes_the_way_the_rest_does(self):
        """🛑 THE HANDLE, like every other command, and for a reason the names make plain.

        A matrix column is about ten characters wide — the table is one column per home —
        so the heading is truncated, and a layout whose account names share a prefix (one
        login per project, one per client) produced several columns headed with the same
        truncated string, with nothing to tell a reader which column was which account.
        Measured on a real six-home machine: four of the six headings read alike. The
        notes under the table have to agree with the headings, or a divergence is reported
        about a name that is nowhere in the table above it.
        """
        p = self.w.table(("acme-production-eu", "me@work.example", self.work,
                          "laptop", "prod"),
                         ("acme-production-us", "me@home.example", self.personal,
                          "laptop", "us"))
        # a divergence, so the note that lists the homes by name is printed too
        (self.work / "CLAUDE.md").write_text("# mine\n")
        (self.personal / "CLAUDE.md").write_text("# theirs\n")
        out = self.table(CSM_ACCOUNTS=p, CSM_MACHINE="laptop")
        head = [ln for ln in out.splitlines() if ln.startswith("layer")][0]
        self.assertIn("prod", head)
        self.assertIn("us", head)
        # and not the truncation that made two columns read alike
        self.assertNotIn("acme-produ", out)
        flat = " ".join(out.split())
        self.assertIn("prod → ", flat)
        self.assertIn("us → ", flat)
        # the heading names the machine this tool is configured as, not the hostname
        self.assertIn("fungibility matrix on laptop", out)
        # --json keeps `name` (a cell's `home` field is that name) and gains `handle`
        d = json.loads(self.table("--json", CSM_ACCOUNTS=p, CSM_MACHINE="laptop"))
        self.assertEqual(sorted((h["name"], h["handle"]) for h in d["homes"]),
                         [("acme-production-eu", "prod"), ("acme-production-us", "us")])
        for row in d["rows"]:
            for c in row["cells"]:
                self.assertIn(c["home"], ("acme-production-eu", "acme-production-us", "*"))

    def snapshot(self):
        """Every config home, byte for byte. (Only the homes: an interpreter is free to
        drop its own caches elsewhere under HOME, and that is not the tool writing.)"""
        out = {}
        for home in sorted(self.w.home.glob(".claude*")):
            for p in [home] + sorted(home.rglob("*")):
                st = p.lstat()
                out[str(p)] = (st.st_mode, st.st_size, st.st_mtime)
        return out



class CaptureBeforeSignal(InProc):
    """🛑 CAPTURE FIRST, PROVE, THEN SIGNAL. Everything else a session owns is on disk and
    survives a SIGTERM; a prompt the agent typed and never sent lives only in the pane, and
    `kill-window` destroys the pane with the process."""

    def setUp(self):
        super().setUp()
        self.mod.CAPTURES = self.root / "captures"
        self.s = self.session(self.account("work"))

    def fake_tmux(self, code, out):
        self.mod.tmux = lambda *a, **kw: types.SimpleNamespace(
            returncode=code, stdout=out, stderr="")

    def test_the_scrollback_lands_in_a_dated_0600_file_naming_the_pane(self):
        self.fake_tmux(0, "> a draft nobody sent\n")
        p = Path(self.mod.capture_pane(self.s, "csm-work:@3.%7", "stop"))
        self.assertTrue(p.is_file())
        self.assertEqual(p.parent.name, time.strftime("%Y-%m-%d"))
        self.assertEqual(oct(p.stat().st_mode & 0o777), "0o600")
        self.assertEqual(oct(p.parent.stat().st_mode & 0o777), "0o700")
        body = p.read_text()
        self.assertIn("a draft nobody sent", body)
        self.assertIn("csm-work:@3.%7", body)
        self.assertIn(self.s.local_id, body)

    def test_no_pane_means_nothing_to_capture_and_no_directory_is_made(self):
        self.fake_tmux(0, "x")
        self.assertEqual(self.mod.capture_pane(self.s, "", "stop"), "")
        self.assertFalse((self.root / "captures").exists())

    def test_a_refusing_tmux_or_an_empty_pane_can_never_fail_the_stop(self):
        self.fake_tmux(1, "")
        self.assertEqual(self.mod.capture_pane(self.s, "x:@1.%1", "stop"), "")
        self.fake_tmux(0, "  \n ")
        self.assertEqual(self.mod.capture_pane(self.s, "x:@1.%1", "stop"), "")

    def test_a_capture_that_raises_is_swallowed_so_the_stop_still_happens(self):
        def boom(*a, **kw):
            raise OSError("no tmux on this box")
        self.mod.tmux = boom
        self.assertEqual(self.mod.capture_pane(self.s, "x:@1.%1", "--stop-source"), "")

    def test_it_reads_the_whole_scrollback_not_just_the_visible_pane(self):
        seen = []
        self.mod.tmux = lambda *a, **kw: (seen.append(a), types.SimpleNamespace(
            returncode=0, stdout="x\n", stderr=""))[1]
        self.mod.capture_pane(self.s, "x:@1.%1", "stop")
        self.assertEqual(seen[0], ("capture-pane", "-p", "-S", "-", "-t", "x:@1.%1"))


# --------------------------------------------------------------- one shared projects/ tree
# Two or more homes whose projects/ (and file-history/) are symlinks into ONE directory. The
# layout is a choice some people make to share history between accounts; LESSONS.md says
# what it costs. These pin that csm sees ONE file there, copies nothing onto itself, and asks
# every home, not just the target, who is running it.

def link_into(central: Path, home: Path, name: str = "projects") -> None:
    central.mkdir(parents=True, exist_ok=True)
    d = home / name
    if d.is_dir() and not d.is_symlink():
        for p in d.iterdir():
            shutil.move(str(p), str(central / p.name))
        d.rmdir()
    os.symlink(str(central), str(d))


class SharedTree(Base):
    def setUp(self):
        super().setUp()
        self.third = self.w.account("third", "me@third.example", org="org-3")
        self.central = self.w.root / "central" / "projects"
        for h in (self.work, self.personal, self.third):
            link_into(self.central, h)
        self.t = self.w.session(self.work, SID_A)
        self.before = self.t.read_bytes()

    def test_one_transcript_is_one_row_not_one_per_account(self):
        rows = self.listing()
        self.assertEqual([r["local_id"] for r in rows], [SID_A])
        out = self.ok(self.w.run("list"))
        self.assertIn("one shared tree", out)

    # An idle shared row is filed under the first home in account order: here `personal`.

    def test_moving_by_id_is_not_refused_as_several_copies(self):
        out = self.ok(self.w.run("move", SID_A, "--to", "work", "--dry-run"))
        self.assertIn("copy NOTHING", out)
        self.assertIn("ONE TRANSCRIPT", out)
        self.assertNotIn("REFUSED", out)

    def test_a_real_move_copies_nothing_and_leaves_no_backup(self):
        # ⚠️ The bytes are unchanged because the COPY step writes nothing here — this
        # fixture's lines carry no `uuid`, so the move note has no chain to hang on
        # either. The note's own behaviour on a shared tree is the next test.
        out = self.ok(self.w.run("move", SID_A, "--to", "work"))
        self.assertIn(LINK, out)
        self.assertEqual(self.t.read_bytes(), self.before)
        self.assertEqual(list(self.central.rglob("*.csm-bak-*")), [])
        self.assertEqual(len(list(self.central.rglob(SID_A + ".jsonl"))), 1)
        call = self.w.claude_calls()[0]
        self.assertEqual(call["argv"][-2:], ["--resume", SID_A])
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], str(self.work))

    def test_the_move_note_is_appended_to_the_one_shared_file(self):
        """🛑 There is no second file to put it in, and that is the right answer.

        The note is what the resumed session reads; under one tree the file it resumes IS
        the source's file, so the note goes there or nowhere. It does mean a source still
        running can see it — the plan and `target_notes` both say the two share a file,
        and `--stop-source` is what stops them interleaving.
        """
        cwd = str(self.w.work)
        t = self.w.session(self.work, SID_B, lines=[
            user("go", cwd, SID_B, uuid="u1"),
            assistant("ok", cwd, SID_B, uuid="a1", parent="u1")])
        before = len(t.read_text().splitlines())
        out = self.ok(self.w.run("move", SID_B, "--to", "work"))
        self.assertIn("the move note is appended to it", out)
        rows = [json.loads(x) for x in t.read_text().splitlines() if x.strip()]
        notes = [r for r in rows if r.get("isMeta")]
        self.assertEqual(len(notes), 1)
        self.assertEqual(rows.index(notes[0]), before)
        self.assertEqual(len(list(self.central.rglob(SID_B + ".jsonl"))), 1)
        self.assertEqual(list(self.central.rglob("*.csm-bak-*")), [])

    def test_the_row_names_the_account_that_is_running_it(self):
        self.w.live(self.personal, SID_A, self.w.spawn().pid)
        rows = self.listing()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["account"], "personal")
        self.assertTrue(rows[0]["live"])

    def test_a_running_source_is_warned_about_not_refused(self):
        self.w.live(self.personal, SID_A, self.w.spawn().pid)
        # The row is personal's (it runs there), so personal's process is the SOURCE, not a
        # twin: moving a live session is the whole point. It is warned, with the flag.
        out = self.ok(self.w.run("move", SID_A, "--to", "third", "--dry-run"))
        self.assertIn("The source is RUNNING", out)
        self.assertIn("--stop-source", out)

    def test_the_default_home_is_asked_too(self):
        default = self.w.account("default", "me@default.example", default=True)
        link_into(self.central, default)
        self.w.live(default, SID_A, self.w.spawn().pid)
        cfg = self.w.root / "accounts"            # an accounts file that omits the default
        cfg.write_text("work ~/.claude-work\npersonal ~/.claude-personal\n")
        rows = json.loads(self.ok(self.w.run("list", "--json", CSM_ACCOUNTS=cfg)))
        src = rows[0]["account"]
        tgt = "personal" if src == "work" else "work"
        self.refused(self.w.run("move", SID_A, "--to", tgt, CSM_ACCOUNTS=cfg),
                     "default is ALREADY running")


class SharedTreeUnits(InProc):
    def test_same_path_sees_through_a_link_and_answers_for_a_missing_end(self):
        real = self.root / "real" / "x"
        real.mkdir(parents=True)
        os.symlink(str(self.root / "real"), str(self.root / "alias"))
        self.assertTrue(self.mod.same_path(real, self.root / "alias" / "x"))
        self.assertTrue(self.mod.same_path(self.root / "real" / "nope",
                                           self.root / "alias" / "nope"))
        self.assertFalse(self.mod.same_path(real, self.root / "real" / "y"))

    def test_unshared_homes_keep_two_rows_for_two_real_copies(self):
        a, b = self.account("work"), self.account("personal", email="me@home.example")
        s1, s2 = self.session(a), self.session(b)
        self.assertEqual(len(self.mod.dedupe_shared([s1, s2])), 2)
        self.assertEqual(self.mod.SHARED, [])

    def test_a_shared_file_history_is_not_carried_but_tasks_are(self):
        a, b = self.account("work"), self.account("personal", email="me@home.example")
        central = self.root / "central-fh"
        link_into(central, a.home, "file-history")
        link_into(central, b.home, "file-history")
        s = self.session(a)
        (central / SID_A).mkdir()
        (central / SID_A / "f@v1").write_text("one")
        (a.home / "tasks" / SID_A).mkdir(parents=True)
        (a.home / "tasks" / SID_A / "t.json").write_text("{}")
        pairs = self.mod.side_data(s, b)
        self.assertEqual([p.parent.name for p, _ in pairs], ["tasks"])
        self.mod.copy_in(s, b, apply=True)
        self.assertEqual((central / SID_A / "f@v1").read_text(), "one")
        self.assertTrue((b.home / "tasks" / SID_A / "t.json").exists())

    def test_copy_tree_onto_itself_is_a_no_op(self):
        d = self.root / "d"
        d.mkdir()
        (d / "f").write_text("keep")
        os.symlink(str(d), str(self.root / "e"))
        self.mod.copy_tree(d, self.root / "e")          # must not raise SameFileError
        self.assertEqual((d / "f").read_text(), "keep")

    def test_copy_in_onto_one_tree_touches_nothing(self):
        a, b = self.account("work"), self.account("personal", email="me@home.example")
        central = self.root / "central"
        link_into(central, a.home)
        link_into(central, b.home)
        s = self.session(a)
        (s.sibling / "subagents").mkdir(parents=True)
        os.chmod(str(s.transcript), 0o644)
        before = s.transcript.read_bytes()
        dest, steps = self.mod.copy_in(s, b, apply=True)
        self.assertTrue(self.mod.same_path(dest, s.transcript))
        self.assertIn("copy NOTHING", steps[0])
        self.assertEqual(s.transcript.read_bytes(), before)
        self.assertEqual(oct(s.transcript.stat().st_mode & 0o777), "0o644", "not even a chmod")
        self.assertEqual(list(central.rglob("*.csm-bak-*")), [])


# ------------------------------------------------------------------------ the quota meter

class Meters(Base):
    """`--to auto`, the near-limit warning on a NAMED target, and what "unread" means.

    🛑 The whole point of the feature is that a reading is a reading. A stale one is
    neither room nor a limit, a missing file is not zero per cent, and `auto` with nothing
    to read refuses instead of picking the first home it finds — because a move into a
    second exhausted account looks exactly like a success.
    """

    def setUp(self):
        super().setUp()
        self.spare = self.w.account("spare", "me@spare.example", org="org-3")
        self.other = self.w.account("other", "me@other.example", org="org-4")
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[user("go", cwd, SID_A),
                                                assistant("ok", cwd, SID_A)])
        self.tbl = self.w.table(
            ("work", "me@work.example", self.work, "here", "wk"),
            ("personal", "me@home.example", self.personal, "here", "pers"),
            ("spare", "me@spare.example", self.spare, "here", "sp"),
            ("other", "me@other.example", self.other, "here", "oth"))

    def go(self, *extra, **readings):
        e = {"CSM_ACCOUNTS": str(self.tbl), "CSM_MACHINE": "here"}
        if readings:
            e["CSM_METERS"] = str(self.w.meters(**readings))
        return self.w.run("move", SID_A, *extra, **e)

    def test_auto_picks_the_account_with_the_most_weekly_room(self):
        out = self.ok(self.go("--to", "auto", "--dry-run",
                              pers=(10, 80, 60), sp=(5, 20, 60), oth=(0, 50, 60)))
        self.assertIn("--to auto: sp", out)
        # 🛑 The arrow too: a supervisor reads the chosen account off this line BY the
        # arrow (`→\s+(\S+)\s+\(`), so an ASCII `->` here is a caller that stops working.
        self.assertIn("→  sp (me@spare.example)", out)

    def test_auto_skips_a_near_limit_and_a_stale_reading(self):
        # pers is over the 5-hour cutoff, sp's reading is hours old: neither is room.
        out = self.ok(self.go("--to", "auto", "--dry-run",
                              pers=(95, 10, 60), sp=(0, 1, 5 * 3600), oth=(0, 60, 60)))
        self.assertIn("--to auto: oth", out)

    def test_auto_never_picks_the_account_the_session_is_already_on(self):
        out = self.ok(self.go("--to", "auto", "--dry-run",
                              wk=(0, 0, 60), pers=(0, 40, 60)))
        self.assertIn("--to auto: pers", out)

    def test_auto_with_no_fresh_reading_refuses_and_says_how_to_name_one(self):
        self.refused(self.go("--to", "auto", "--dry-run", pers=(0, 1, 9 * 3600)),
                     "found no account", "--to <account>")

    def test_auto_with_no_meter_at_all_refuses_and_names_the_knob(self):
        self.refused(self.go("--to", "auto", "--dry-run"),
                     "--to auto needs a quota meter", "CSM_METERS", "--to <account>")

    def test_a_named_target_near_its_limit_is_warned_about_not_refused(self):
        out = self.ok(self.go("--to", "pers", "--dry-run", pers=(40, 97, 60)))
        self.assertIn("near its limit", out)
        self.assertIn("week 97%", out)
        self.assertIn("--to auto", out)

    def test_a_stale_reading_never_warns_and_never_counts_as_room(self):
        out = self.ok(self.go("--to", "pers", "--dry-run", pers=(40, 99, 4 * 3600)))
        self.assertNotIn("near its limit", out)

    def test_the_meter_comes_first_and_the_transcript_is_the_fallback(self):
        # The target has a live limit in its own transcript AND a fresh meter over the
        # cutoff: the READING is what is printed, and the evidence is the second path.
        cwd = str(self.w.work)
        self.w.session(self.personal, SID_B, lines=[
            user("x", cwd, SID_B), {"type": "ai-title", "aiTitle": "Theirs",
                                    "sessionId": SID_B},
            assistant("limit", cwd, SID_B, error="usage_limit_reached",
                      resets=int(time.time() + 7200))])
        meter = self.ok(self.go("--to", "pers", "--dry-run", pers=(99, 99, 60)))
        self.assertIn("near its limit", meter)
        self.assertNotIn("may be out of quota TOO", meter)
        evidence = self.ok(self.go("--to", "pers", "--dry-run"))
        self.assertIn("may out of quota TOO".replace("may out", "may be out"), evidence)
        self.assertIn("Theirs", evidence)

    def test_a_target_whose_limit_already_expired_is_not_warned_about(self):
        cwd = str(self.w.work)
        self.w.session(self.personal, SID_B, lines=[
            user("x", cwd, SID_B),
            assistant("limit", cwd, SID_B, error="usage_limit_reached",
                      resets=int(time.time() - 7200))])
        self.assertNotIn("out of quota TOO", self.ok(self.go("--to", "pers", "--dry-run")))

    def test_a_mid_turn_source_says_the_copy_stops_short_of_its_answer(self):
        """The other half of the same question: is the SOURCE fit to be copied now?

        A session mid-turn has not written its current answer yet, so the copy ends just
        before it. Said and not refused, because "move my running session" is the ask
        the tool exists for — but said, because otherwise the newest answer is quietly
        missing from the window that comes up.
        """
        self.w.live(self.work, SID_A, self.w.spawn().pid, status="busy")
        out = self.ok(self.go("--to", "pers", "--dry-run"))
        self.assertIn("the source is mid-turn", out)
        self.assertIn("not on disk yet", out)

    def test_an_idle_source_is_not_called_mid_turn(self):
        self.w.live(self.work, SID_A, self.w.spawn().pid, status="idle")
        self.assertNotIn("mid-turn", self.ok(self.go("--to", "pers", "--dry-run")))


# ------------------------------------------------------------------------- the move note

class MoveNoteText(InProc):
    """What the resumed session is TOLD. Pure text, so every clause can be pinned."""

    def setUp(self):
        super().setUp()
        self.mod.MACHINE = "here"
        self.tgt = self.account("personal", email="you@home.example")

    def note(self, **kw):
        """A note over a fresh source session, with `kw` set on it first.

        ⚠️ No `mirror=` here on purpose: `Session` is a plain dataclass, so a stray
        keyword would be `setattr`'d onto it and silently ignored by `move_note`, and the
        test that passed it would assert nothing. The mirror clause's test calls
        `move_note` directly, with the plan it means.
        """
        src = kw.pop("account", None) or self.account("work", email="me@work.example")
        s = self.session(src)
        for k, v in kw.items():
            assert hasattr(s, k), k        # a typo is not a silently skipped clause
            setattr(s, k, v)
        return self.mod.move_note(s, self.tgt, when="Thu 11:00")

    def test_an_account_move_says_so_and_names_no_machine_to_reach(self):
        n = self.note()
        self.assertIn("on the machine `here`", n)
        self.assertIn("from the account me@work.example to you@home.example", n)
        self.assertIn("This is a COPY", n)
        self.assertIn("are stale", n)
        self.assertNotIn("ssh ", n)
        self.assertTrue(n.startswith("<system-reminder>")
                        and n.endswith("</system-reminder>"))

    def test_the_same_login_on_another_machine_is_not_described_as_an_account_change(self):
        src = self.account("work", email="you@home.example")
        s = self.session(src)
        s.origin = "desktop"
        n = self.mod.move_note(s, self.tgt, when="Thu 11:00")
        self.assertIn("on the same account", n)
        self.assertNotIn("are stale", n)
        self.assertIn("from the machine `desktop` to the machine `here`", n)

    def test_a_store_is_named_and_no_store_says_nothing_about_memory(self):
        store = self.root / "shared-memory"
        store.mkdir()
        quiet = self.mod.move_note(self.session(self.account("work")), self.tgt,
                                   when="Thu 11:00")
        self.assertNotIn("Auto memory", quiet)
        tgt = self.account("personal2", email="you@home.example",
                           settings={"env": {self.mod.MEMORY_DIR_ENV: str(store)}})
        loud = self.mod.move_note(self.session(self.account("work")), tgt, when="Thu 11:00")
        self.assertIn("Auto memory for this project is read from %s" % store, loud)
        self.assertIn("Do not write a memory under", loud)

    def test_a_machine_move_names_what_stayed_and_how_to_reach_it(self):
        s = self.session(self.account("work", email="me@work.example"))
        s.origin = "desktop"
        s.desktop = {"effort": "xhigh"}
        s.detail = {"left": [{"pid": 7, "etime": "01:00", "cmd": "python campaign.py"}],
                    "app_tools": 3, "origin_cwd": "/elsewhere/work"}
        mirror = {"files": ["a"], "skipped": [], "bytes": 10,
                  "all_bytes": 10 + 20 * 2 ** 30, "head": "822eede", "branch": "main",
                  "dirty": 16, "top": s.cwd}
        n = self.mod.move_note(s, self.tgt, mirror=mirror, when="Thu 11:00")
        for want in ("from the machine `desktop` to the machine `here`", "ssh desktop",
                     "CODE-ONLY MIRROR", "822eede", "20.0 GB",
                     "pid 7 `python campaign.py`", "didn't finish", "mcp__ccd_",
                     "say which machine it belongs on", "On `desktop` this folder is",
                     "desktop-app session"):
            self.assertIn(want, n)

    def test_a_synced_folder_and_a_separate_tree_are_told_apart(self):
        s = self.session(self.account("work"))
        s.origin = "desktop"
        self.assertIn("own copy of that folder",
                      self.mod.move_note(s, self.tgt, when="Thu 11:00"))
        self.mod.SYNC_DIRS = ("work",)
        self.mod.HOME = self.root
        self.assertIn("inside a synced directory",
                      self.mod.move_note(s, self.tgt, when="Thu 11:00"))

    def test_the_note_is_a_hidden_line_chained_to_the_last_main_message(self):
        t = self.root / (SID_A + ".jsonl")
        t.write_text(jl(
            {"type": "user", "uuid": "u1", "parentUuid": None, "isSidechain": False,
             "version": "2.1.295", "gitBranch": "main"},
            {"type": "assistant", "uuid": "a1", "parentUuid": "u1", "isSidechain": False,
             "version": "2.1.295", "gitBranch": "main"},
            {"type": "assistant", "uuid": "side", "parentUuid": "x", "isSidechain": True},
            {"type": "custom-title", "customTitle": "t"}))
        s = self.session(self.account("work"))
        new = self.mod.append_move_note(t, s, "<system-reminder>hi</system-reminder>")
        last = json.loads(t.read_text().splitlines()[-1])
        self.assertEqual(last["uuid"], new)
        self.assertEqual(last["parentUuid"], "a1", "a sidechain line is not a parent")
        self.assertIs(last["isMeta"], True)
        self.assertEqual(last["type"], "user")
        self.assertEqual(last["sessionId"], SID_A)
        self.assertEqual(last["version"], "2.1.295")
        self.assertEqual(last["gitBranch"], "main")
        self.assertEqual(last["message"],
                         {"role": "user", "content": "<system-reminder>hi</system-reminder>"})

    def test_a_copy_with_no_conversation_gets_no_note_and_is_not_touched(self):
        t = self.root / "empty.jsonl"
        t.write_text('{"type":"custom-title","customTitle":"t"}\n')
        s = self.session(self.account("work"))
        self.assertEqual(self.mod.append_move_note(t, s, "x"), "")
        self.assertEqual(len(t.read_text().splitlines()), 1)

    def test_a_line_with_no_uuid_is_never_the_parent(self):
        t = self.root / "nouuid.jsonl"
        t.write_text(jl({"type": "user", "isSidechain": False},
                        {"type": "user", "uuid": "u9", "isSidechain": False}))
        s = self.session(self.account("work"))
        self.mod.append_move_note(t, s, "x")
        self.assertEqual(json.loads(t.read_text().splitlines()[-1])["parentUuid"], "u9")


class MoveNoteInPlan(Base):
    """The note reaches the plan, and the COPY — and a dry run writes nothing."""

    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.src = self.w.session(self.work, SID_A, lines=[
            user("refactor the parser", cwd, SID_A, uuid="u1"),
            assistant("ok", cwd, SID_A, uuid="a1", parent="u1")])

    def test_the_dry_run_prints_the_note_and_writes_nothing(self):
        before = self.src.read_text()
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run"))
        self.assertIn("the move note:", out)
        self.assertIn("move record, written by the tool", out)
        self.assertIn("append the MOVE NOTE to the copy", out)
        self.assertEqual(self.src.read_text(), before)
        self.assertEqual(list((self.personal / "projects").rglob("*.jsonl")), [])

    def test_a_real_move_appends_it_to_the_copy_and_not_to_the_source(self):
        before = self.src.read_text()
        out = self.ok(self.w.run("move", SID_A, "--to", "personal"))
        self.assertIn("move note", out)
        self.assertEqual(self.src.read_text(), before, "the source is never written to")
        dest = next((self.personal / "projects").rglob(SID_A + ".jsonl"))
        rows = [json.loads(x) for x in dest.read_text().splitlines() if x.strip()]
        notes = [r for r in rows if r.get("isMeta")]
        self.assertEqual(len(notes), 1, "exactly one note, never two")
        self.assertEqual(notes[0]["type"], "user")
        self.assertIn("move record", notes[0]["message"]["content"])
        self.assertIn("from the account me@work.example", notes[0]["message"]["content"])
        # 🛑 It is the newest line of the CONVERSATION as copied: the resumed session's
        # own lines come after it, which is what makes it the last thing read before the
        # next prompt rather than a line buried in the middle of the history.
        copied = len([x for x in before.splitlines() if x.strip()])
        self.assertEqual(rows.index(notes[0]), copied)

    def test_a_transcript_with_no_chain_says_the_note_was_not_written(self):
        # 🛑 The step line above promises the note. A transcript whose conversation lines
        # carry no `uuid` has nothing to chain one to, and nothing is written — so the
        # move has to SAY so, or the promise is quietly broken.
        cwd = str(self.w.work)
        self.w.session(self.work, SID_C, lines=[user("no chain here", cwd, SID_C)])
        out = self.ok(self.w.run("move", SID_C, "--to", "personal"))
        self.assertIn("move note    NOT written", out)
        dest = next((self.personal / "projects").rglob(SID_C + ".jsonl"))
        self.assertEqual([r for r in (json.loads(x) for x in
                                      dest.read_text().splitlines() if x.strip())
                          if r.get("isMeta")], [])


# --------------------------------------------------------------------------- the room note

class RoomNote(InProc):
    """Whether the TARGET account already has a way into this folder here.

    🛑 The guard under test is the one that costs nothing to get wrong and everything to
    get wrong quietly: a probe that FAILED prints an empty table, and reading that as "no
    way in" states something nobody measured.
    """

    def setUp(self):
        super().setUp()
        self.mod.MACHINE = "here"
        self.cwd = str(self.root / "work")
        os.makedirs(self.cwd, exist_ok=True)
        self.tgt = self.account("personal", email="you@home.example")
        self.tgt.handle = "pers"

    def probe(self, body, fix=""):
        d = self.root / "bin"
        d.mkdir(exist_ok=True)
        f = d / "rooms"
        f.write_text(body)
        f.chmod(0o755)
        self.mod.ROOM_CMD = str(f) + " --account {handle}"
        self.mod.ROOM_FIX = fix
        return f

    def note(self):
        s = self.session(self.account("work"), cwd=self.cwd)
        return self.mod.room_note(s, self.tgt)

    def test_with_no_probe_configured_there_is_no_note_at_all(self):
        self.mod.ROOM_CMD = ""
        self.assertEqual(self.note(), "")

    def test_a_probe_that_failed_says_nothing_about_rooms(self):
        self.probe("#!/bin/sh\necho 'no server reachable' >&2\nexit 2\n")
        self.assertEqual(self.note(), "")

    def test_a_probe_that_answered_an_empty_table_does_report_the_gap(self):
        # The positive control for the guard above: the same empty stdout, exit 0.
        self.probe("#!/bin/sh\necho header\necho ----\nexit 0\n")
        n = self.note()
        self.assertIn("has no way into this folder on here", n)
        self.assertIn("pers", n)

    def test_a_row_naming_this_folder_is_nothing_to_report(self):
        self.probe("#!/bin/sh\necho header\necho ----\necho \'a b c %s\'\n" % self.cwd)
        self.assertEqual(self.note(), "")

    def test_the_handle_reaches_the_probe_and_the_cure_is_the_knob(self):
        f = self.probe("#!/bin/sh\necho \"$2\" > %s/seen\necho h\necho -\n"
                       % self.root, fix="run: rooms add {name} for {handle} in {cwd}")
        n = self.note()
        self.assertEqual((self.root / "seen").read_text().strip(), "pers")
        self.assertIn("run: rooms add work for pers in " + self.cwd, n)
        self.assertTrue(f.exists())

    def test_a_probe_that_cannot_be_run_is_not_a_crash(self):
        self.mod.ROOM_CMD = str(self.root / "nope") + " {handle}"
        self.mod.ROOM_FIX = ""
        self.assertEqual(self.note(), "")

    def test_an_unparseable_probe_command_is_not_a_crash(self):
        self.mod.ROOM_CMD = "rooms --account '{handle}"
        self.assertEqual(self.note(), "")

    def test_a_session_with_no_folder_has_no_room_question(self):
        self.probe("#!/bin/sh\necho h\necho -\n")
        s = self.session(self.account("work"), cwd=self.cwd)
        s.cwd = ""
        self.assertEqual(self.mod.room_note(s, self.tgt), "")


# ------------------------------------------------------------- what the plan may claim

class ConnectorNote(Base):
    """A name is not a call: `has used` and `mentions` are two different claims."""

    def plan(self, lines):
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=lines)
        return self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run"))

    def test_a_called_connector_is_reported_as_used(self):
        cwd = str(self.w.work)
        out = self.plan([user("go", cwd, SID_A),
                         assistant("ok", cwd, SID_A,
                                   tools=["mcp__claude_ai_Gmail__search"])])
        self.assertIn("this conversation has used: Gmail", out)
        self.assertNotIn("mentions the connector", out)

    def test_a_connector_only_named_in_a_tool_definition_is_a_mention(self):
        """🛑 The measured false positive, in the two shapes it really takes.

        A transcript carries `"name": "mcp__…"` in places that are not calls: a system
        line listing deferred tools, and — the one that matters, because it is INSIDE
        `message.content` where the calls are — a content block that names a tool without
        being a `tool_use`. Both must read as a mention; only the second one can be got
        wrong by the narrow scan, so both are in this fixture.
        """
        cwd = str(self.w.work)
        out = self.plan([
            user("go", cwd, SID_A),
            {"type": "system", "cwd": cwd, "sessionId": SID_A,
             "surfacedDefinitions": [{"name": "mcp__claude_ai_Gmail__search",
                                      "description": "search mail"}]},
            {"type": "assistant", "cwd": cwd, "sessionId": SID_A, "isSidechain": False,
             "message": {"role": "assistant", "model": "claude-sonnet-4-5", "content": [
                 {"type": "tool_search_result", "name": "mcp__claude_ai_Gmail__search",
                  "description": "search mail"},
                 {"type": "text", "text": "I could use mcp__claude_ai_Gmail__search"}]}},
            assistant("ok", cwd, SID_A)])
        self.assertIn("mentions the connector(s) Gmail, without calling one", out)
        self.assertNotIn("has used", out)

    def test_an_mcp_server_that_was_called_names_the_sign_in_gesture(self):
        cwd = str(self.w.work)
        out = self.plan([user("go", cwd, SID_A),
                         assistant("ok", cwd, SID_A, tools=["mcp__linear__issues"])])
        self.assertIn("has also used the MCP server(s) linear", out)
        self.assertIn("claude mcp login", out)

    def test_the_connector_sentence_is_in_the_plan_even_with_no_mcp_at_all(self):
        cwd = str(self.w.work)
        out = self.plan([user("go", cwd, SID_A), assistant("ok", cwd, SID_A)])
        self.assertIn("connectors belong to the ACCOUNT", out)
        self.assertNotIn("has used", out)
        self.assertNotIn("mentions the connector", out)


class RetentionNote(Base):
    """`cleanupPeriodDays`: the target home may sweep the copy away before it is opened."""

    def session_aged(self, days):
        cwd = str(self.w.work)
        t = self.w.session(self.work, SID_A, lines=[user("go", cwd, SID_A),
                                                    assistant("ok", cwd, SID_A)])
        when = time.time() - days * 86400
        os.utime(str(t), (when, when))
        return t

    def plan(self, days_old, settings=None):
        self.session_aged(days_old)
        if settings is not None:
            (self.personal / "settings.json").write_text(json.dumps(settings))
        return self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run"))

    def test_a_fresh_session_is_never_warned_about(self):
        self.assertNotIn("keeps transcripts for", self.plan(1))

    def test_past_the_clis_own_default_it_is_warned_about(self):
        out = self.plan(40)
        self.assertIn("keeps transcripts for 30 day(s)", out)
        self.assertIn("neither settings file names the key", out)

    def test_the_homes_own_period_is_what_counts(self):
        out = self.plan(10, {"cleanupPeriodDays": 7})
        self.assertIn("keeps transcripts for 7 day(s)", out)
        self.assertIn("settings.json / settings.local.json in that home", out)

    def test_a_long_period_in_that_home_means_no_warning(self):
        self.assertNotIn("keeps transcripts for", self.plan(40, {"cleanupPeriodDays": 99999}))

    def test_zero_switches_the_sweep_off_and_so_the_warning_too(self):
        self.assertNotIn("keeps transcripts for", self.plan(400, {"cleanupPeriodDays": 0}))


# ----------------------------------------------------------- a session somebody else owns

class OwnedSession(Base):
    """A session that is a front door is handed to its supervisor, never moved by hand."""

    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[user("go", cwd, SID_A, uuid="u1"),
                                                assistant("ok", cwd, SID_A, uuid="a1",
                                                          parent="u1")])
        self.owners = self.w.root / "owners"
        self.owners.mkdir()

    def own(self, name, sid):
        (self.owners / (name + ".json")).write_text(json.dumps({"session_id": sid}))

    def env(self, **extra):
        e = {"CSM_BOTS_DIR": str(self.owners)}
        e.update(extra)
        return e

    def test_with_no_owner_directory_nothing_is_owned(self):
        self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run",
                           CSM_BOTS_DIR=str(self.w.root / "nowhere")))

    def test_a_plain_move_of_an_owned_session_is_refused_and_names_the_way(self):
        self.own("front-door", SID_A)
        self.refused(self.w.run("move", SID_A, "--to", "personal", "--dry-run",
                                **self.env()),
                     "is front-door's own session", "SECOND copy", "--copy-only")

    def test_the_cure_sentence_is_a_knob(self):
        self.own("front-door", SID_A)
        self.refused(self.w.run("move", SID_A, "--to", "personal", "--dry-run",
                                **self.env(CSM_BOT_FIX="say: owners switch {owner} {to}")),
                     "say: owners switch front-door personal")

    def test_another_sessions_owner_does_not_claim_this_one(self):
        self.own("front-door", SID_B)
        self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run", **self.env()))

    def test_one_unreadable_state_file_is_skipped_not_a_claim(self):
        (self.owners / "broken.json").write_text("{not json")
        self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run", **self.env()))

    def test_a_directory_that_cannot_be_READ_is_a_refusal_and_not_a_no(self):
        """🛑 The quietest path to the worst outcome.

        `Path.glob` swallows a PermissionError from its own scan and yields nothing, so an
        unreadable owner directory would read as "nobody owns this" — and the guard would
        open silently on exactly the session it exists to protect. `os.listdir` raises,
        and the refusal says what could not be read.
        """
        self.own("front-door", SID_A)
        os.chmod(str(self.owners), 0o000)
        try:
            self.refused(self.w.run("move", SID_A, "--to", "personal", "--dry-run",
                                    **self.env()),
                         "could not read", "owns this session", "CSM_BOTS_DIR")
        finally:
            # before tearDown, which has to be able to remove the tree
            os.chmod(str(self.owners), 0o755)

    def test_a_file_where_the_directory_should_be_says_so(self):
        f = self.w.root / "not-a-dir"
        f.write_text("x")
        self.refused(self.w.run("move", SID_A, "--to", "personal", "--dry-run",
                                CSM_BOTS_DIR=str(f)), "not a directory")

    def test_copy_only_does_the_whole_copy_and_starts_nothing(self):
        self.own("front-door", SID_A)
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--copy-only",
                                 **self.env()))
        self.assertIn("start NOTHING (--copy-only)", out)
        self.assertIn("Nothing was started", out)
        # 🛑 the way back in is a plain resume, never a `--remote-control=` name: a copy
        # the caller starts is not a window csm opened, and `csm stop` would refuse it
        self.assertIn("--resume " + SID_A, out)
        self.assertNotIn("--remote-control", out)
        # 🛑 AND IT IS RUNNABLE AS PRINTED. The line is read by somebody about to paste
        # it, so the home is absolute (no `~`, which an env assignment in front of a
        # command does not expand on every shell) and there is no prose in the middle.
        line = [x for x in out.splitlines() if "--resume " + SID_A in x][0]
        gesture = line.split(": ", 1)[1]
        self.assertTrue(gesture.startswith("CLAUDE_CONFIG_DIR=" + str(self.personal)),
                        gesture)
        self.assertNotIn("~", gesture)
        self.assertNotIn(",", gesture)
        dest = next((self.personal / "projects").rglob(SID_A + ".jsonl"))
        rows = [json.loads(x) for x in dest.read_text().splitlines() if x.strip()]
        self.assertEqual(len([r for r in rows if r.get("isMeta")]), 1,
                         "the move note is part of a copy-only move")
        self.assertEqual(self.w.claude_calls(wait=0.5), [], "claude is never started")
        st = json.loads(self.w.tmux_state.read_text()) if self.w.tmux_state.exists() else {}
        self.assertEqual({s: w for s, w in (st.get("sessions") or {}).items() if w}, {},
                         "and no window is opened")

    def test_copy_only_still_does_every_refusal(self):
        self.refused(self.w.run("move", SID_A, "--to", "work", "--copy-only",
                                **self.env()), "already in work")

    def test_copy_only_refuses_the_flags_that_mean_a_window(self):
        self.refused(self.w.run("move", SID_A, "--to", "personal", "--copy-only",
                                "--stop-source", **self.env()), "stops nothing either")
        self.refused(self.w.run("move", SID_A, "--to", "personal", "--copy-only",
                                "--foreground", **self.env()), "no terminal to choose")

    def test_an_old_moved_window_is_no_obstacle_to_a_copy_only_move(self):
        self.ok(self.w.run("move", SID_A, "--to", "personal"))
        # --from-account picks the source copy out of the two the first move left
        self.refused(self.w.run("move", SID_A, "--to", "personal",
                                "--from-account", "work"), "already exists")
        # the window is still there, and copy-only neither needs nor minds it
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--copy-only",
                                 "--from-account", "work"))
        self.assertIn("Nothing was started", out)


class FullIdPin(Base):
    """A session named by its WHOLE id is found however old its file is.

    🛑 `move` looks at the newest `max(CSM_LIMIT, 60)` transcripts per home, which is a
    fortnight or less on a busy machine — and the session somebody names by its full id is
    typically one that has been idle for longer than that. So a whole id is PINNED into
    the candidate list. A prefix is not: only a whole id names one file for certain.
    """

    #: One more than the floor `move` uses, so the ancient row really is out of the window.
    NEWER = 62

    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, lines=[user("ancient", cwd, SID_A)],
                       mtime=time.time() - 60 * 86400)
        self.w.session(self.work, LINK_SID, mtime=time.time() - 60 * 86400,
                       lines=[user("ancient link", cwd, LINK_SID)])
        for n in range(self.NEWER):
            sid = "%08d-dddd-4ddd-8ddd-dddddddddddd" % n
            self.w.session(self.work, sid, lines=[user("newer %d" % n, cwd, sid)])

    def test_a_whole_id_past_the_window_is_still_moved(self):
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--dry-run"))
        self.assertIn(SID_A, out)
        self.assertIn("ancient", out)

    def test_a_link_past_the_window_is_pinned_by_the_id_it_derives(self):
        """🛑 The pin is the whole reason the derivation runs at the SPEC layer and not
        inside `pick`: only a WHOLE id survives the listing's age cap, and a link is not
        one until it has been derived. A session reached by its link is typically the
        oldest file in the home — it stopped days ago, which is why anyone is looking.
        """
        out = self.ok(self.w.run("move", link_of(LINK_BARE), "--to", "personal",
                                 "--dry-run"))
        self.assertIn(LINK_SID, out)
        self.assertIn("ancient link", out)
        self.assertIn("resolved from the link", out)

    def test_a_prefix_of_that_id_is_deliberately_not_pinned(self):
        # ⚠️ not `SID_A[:8]`: an all-digit spec is a ROW NUMBER, a different refusal.
        self.refused(self.w.run("move", SID_A[:13], "--to", "personal", "--dry-run"),
                     "11111111-aaaa")

    def test_the_explicit_limit_still_outranks_a_pin_in_a_listing(self):
        rows = json.loads(self.ok(self.w.run("list", "--json", "--limit", "2")))
        self.assertEqual(len(rows), 2)


class PinUnit(InProc):
    def test_a_pin_joins_the_live_rows_and_a_cap_still_wins(self):
        a = self.account("work")
        cwd = str(self.root / "work")
        os.makedirs(cwd, exist_ok=True)
        old = "aaaaaaaa-0000-4000-8000-000000000000"
        self.session(a, sid=old, cwd=cwd)
        t = a.home / "projects" / "-work" / (old + ".jsonl")
        os.utime(str(t), (time.time() - 90 * 86400,) * 2)
        for n in range(5):
            sid = "%08d-bbbb-4bbb-8bbb-bbbbbbbbbbbb" % n
            self.session(a, sid=sid, cwd=cwd)
        self.assertNotIn(old, [x.local_id for x in self.mod.all_sessions([a], 2)])
        self.assertIn(old, [x.local_id for x in self.mod.all_sessions([a], 2, pin=old)])
        # the hard cap is the number that was typed, pin or no pin
        self.assertEqual(len(self.mod.all_sessions([a], 2, hard=True, pin=old)), 2)


class DefaultHomeFirst(InProc):
    """🛑 The twin check asks the DEFAULT home first.

    It is the home no accounts file has to name, and the one a desktop app or a bare
    `claude` registers its sessions in — so a session the app is holding open looks quiet
    from every account that IS named. Asked last, the refusal would name whichever other
    home it reached first and send somebody to stop the wrong process.
    """

    def test_the_default_home_is_the_first_home_asked(self):
        d = self.root / "home" / ".claude"
        (d / "projects").mkdir(parents=True)
        a, b = self.account("work"), self.account("personal", email="me@home.example")
        c = self.account("third", email="me@third.example")
        s = self.session(a)
        names = [x.name for x in self.mod.other_homes(s, b, [c, a])]
        self.assertEqual(names[0], "default")
        self.assertIn("third", names)
        self.assertNotIn("work", names, "the source is not a third home")
        self.assertNotIn("personal", names, "nor is the target")

    def test_when_the_accounts_file_names_that_home_its_own_row_goes_first(self):
        # The refusal has to call the home what the reader calls it, so a named row wins
        # over the unnamed stand-in — while still being asked first.
        d = self.root / "home" / ".claude"
        (d / "projects").mkdir(parents=True)
        app = self.mod.Account("app", d, default=True)
        a, b = self.account("work"), self.account("personal", email="me@home.example")
        s = self.session(a)
        names = [x.name for x in self.mod.other_homes(s, b, [a, app])]
        self.assertEqual(names, ["app"])
        self.assertNotIn("default", names)

    def test_a_home_that_is_not_there_is_not_a_home(self):
        a, b = self.account("work"), self.account("personal", email="me@home.example")
        s = self.session(a)
        # no ~/.claude on this fixture machine at all
        self.assertEqual(self.mod.other_homes(s, b, [a, b]), [])


class AmbiguousIdGuard(Base):
    """The same id in two project folders of one home makes `--resume <id>` ambiguous."""

    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.w.session(self.work, SID_A, folder="-launch-spelling",
                       lines=[user("go", cwd, SID_A)])

    def test_a_second_copy_in_another_folder_of_the_target_is_refused(self):
        self.w.session(self.personal, SID_A, folder="-somewhere-else",
                       lines=[user("older", str(self.w.work), SID_A)])
        self.refused(self.w.run("move", SID_A, "--to", "personal", "--from-account",
                                "work"),
                     "another project folder", "exactly ONE file")

    def test_one_file_reached_by_two_spellings_is_not_two_copies(self):
        """🛑 The guard asks `same_path`, not a string comparison.

        With one shared `projects/` tree the destination is reachable under several
        spellings, and comparing normalised strings calls one file two files —
        manufacturing a refusal about the very file the move is allowed to write.
        """
        central = self.w.root / "central" / "projects"
        link_into(central, self.work)
        link_into(central, self.personal)
        # a second path to the same folder, which a string comparison would read as a twin
        os.symlink(str(central / "-launch-spelling"), str(central / "-same-by-link"))
        # an idle shared row is filed under the first home in account order (personal),
        # so `--to work` is the direction that has somewhere to go
        out = self.ok(self.w.run("move", SID_A, "--to", "work", "--dry-run"))
        self.assertNotIn("another project folder", out)
        self.assertIn("copy NOTHING", out)


class MemoryIsNeverCopied(Base):
    """🛑 §4.16: the project's `memory/` is not copied in ANY store configuration.

    The one case that looks harmless — neither home has a store and the target has no
    notes yet — is the case that CREATES the second store, and nothing afterwards reports
    the fork. The plan says where the moved session will read instead, so the choice is
    the user's and explicit.
    """

    def setUp(self):
        super().setUp()
        cwd = str(self.w.work)
        self.src = self.w.session(self.work, SID_A, lines=[
            user("go", cwd, SID_A, uuid="u1")])
        mem = self.src.parent / "memory"
        mem.mkdir()
        (mem / "MEMORY.md").write_text("- a note\n")

    def moved_memory(self):
        dest = next((self.personal / "projects").rglob(SID_A + ".jsonl"))
        return sorted(p.name for p in (dest.parent / "memory").glob("*")) \
            if (dest.parent / "memory").is_dir() else None

    def test_no_store_anywhere_and_a_target_with_no_notes(self):
        out = self.ok(self.w.run("move", SID_A, "--to", "personal"))
        self.assertIn("copy NO memory/", out)
        self.assertIsNone(self.moved_memory())

    def test_a_target_that_has_its_own_notes_keeps_exactly_those(self):
        folder = self.src.parent.name
        tm = self.personal / "projects" / folder / "memory"
        tm.mkdir(parents=True)
        (tm / "THEIRS.md").write_text("- theirs\n")
        self.ok(self.w.run("move", SID_A, "--to", "personal"))
        self.assertEqual(self.moved_memory(), ["THEIRS.md"])

    def test_with_a_store_configured_in_the_target_nothing_is_copied_either(self):
        store = self.w.root / "store"
        store.mkdir()
        (self.personal / "settings.json").write_text(json.dumps(
            {"env": {"CLAUDE_CODE_REMOTE_MEMORY_DIR": str(store)}}))
        out = self.ok(self.w.run("move", SID_A, "--to", "personal"))
        self.assertIn("reads auto-memory from", out)
        self.assertIsNone(self.moved_memory())
        self.assertEqual(list(store.rglob("MEMORY.md")), [])

    def test_the_source_keeps_its_own_notes_whatever_happens(self):
        self.ok(self.w.run("move", SID_A, "--to", "personal"))
        self.assertEqual((self.src.parent / "memory" / "MEMORY.md").read_text(),
                         "- a note\n")


class MillisecondTimes(InProc):
    """`epoch_s` normalises milliseconds, so a limit waited out stays waited out."""

    def test_a_millisecond_resets_at_in_the_past_does_not_flag_a_quota(self):
        cwd = str(self.root / "work")
        os.makedirs(cwd, exist_ok=True)
        past_ms = int((time.time() - 30 * 86400) * 1000)
        t = self.root / "u1.jsonl"
        t.write_text(jl(user("p", cwd, SID_A),
                        assistant("limit", cwd, SID_A, error="usage_limit_reached",
                                  resets=past_ms),
                        # a clean assistant line AFTER it: only `resets_at` could flag it
                        assistant("and on we go", cwd, SID_A)))
        self.assertEqual(self.mod.scan_transcript(t)["quota"], {})

    def test_the_same_reset_in_the_future_does_flag_it(self):
        cwd = str(self.root / "work")
        os.makedirs(cwd, exist_ok=True)
        soon_ms = int((time.time() + 3600) * 1000)
        t = self.root / "u2.jsonl"
        t.write_text(jl(user("p", cwd, SID_A),
                        assistant("limit", cwd, SID_A, error="usage_limit_reached",
                                  resets=soon_ms),
                        assistant("and on we go", cwd, SID_A)))
        q = self.mod.scan_transcript(t)["quota"]
        self.assertAlmostEqual(q["resets_at"], soon_ms / 1000.0, places=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
