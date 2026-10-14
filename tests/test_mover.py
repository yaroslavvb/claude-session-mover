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

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "claude-session-mover"
PY = sys.executable
LINK = "https://claude.ai/code/session_01MovedFakeSession42"

FAKE_CLAUDE = r'''#!{py}
import json, os, sys, time
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ)}}) + "\n")
if any(a.startswith("--remote-control") for a in sys.argv) and not os.environ.get("FAKE_CLAUDE_NOURL"):
    print("Remote Control active: {link}", flush=True)
print("fake claude running", flush=True)
time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP") or 1.0))
sys.exit(int(os.environ.get("FAKE_CLAUDE_RC") or 0))
'''

FAKE_TMUX = r'''#!{py}
"""A tmux stand-in: sessions and windows live in a JSON file; a new window's command REALLY
runs (in the background, output to a pane file); capture-pane prints that file, or the next
scripted screen when FAKE_TMUX_SCRIPT holds some."""
import json, os, subprocess, sys
st_path = os.environ["FAKE_TMUX_STATE"]
calls = os.environ["FAKE_TMUX_CALLS"]
args = sys.argv[1:]
with open(calls, "a") as f:
    f.write(json.dumps(args) + "\n")
try:
    st = json.load(open(st_path))
except (OSError, ValueError):
    st = {{"sessions": {{}}}}
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
    print("\n".join(st["sessions"][s]))
    sys.exit(0)
if cmd in ("new-session", "new-window"):
    sess = opt("-s") if cmd == "new-session" else target()[0]
    win, cwd, shell_cmd = opt("-n"), opt("-c"), args[-1]
    pane = os.path.join(os.path.dirname(st_path), "pane-%s-%s.txt" % (sess, win))
    st["sessions"].setdefault(sess, {{}})[win] = pane
    save()
    out = open(pane, "w")
    subprocess.Popen(["/bin/sh", "-c", shell_cmd], cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    sys.exit(0)
if cmd == "capture-pane":
    sess, win = target()
    if win not in st["sessions"].get(sess, {{}}):
        sys.exit(1)
    script = os.environ.get("FAKE_TMUX_SCRIPT")
    if script and os.path.exists(script):
        screens = json.load(open(script))
        if screens:
            print(screens.pop(0))
            json.dump(screens, open(script, "w"))
            sys.exit(0)
    print(open(st["sessions"][sess][win]).read())
    sys.exit(0)
if cmd == "send-keys":
    target()
    sys.exit(0)
sys.exit(0)
'''


def jl(*rows) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def user(text, cwd, sid, perm=None, sidechain=False):
    d = {"type": "user", "cwd": cwd, "sessionId": sid, "isSidechain": sidechain,
         "message": {"role": "user", "content": text}}
    if perm:
        d["permissionMode"] = perm
    return d


def assistant(text, cwd, sid, model="claude-sonnet-4-5", error=None, resets=None, kind="five_hour"):
    d = {"type": "assistant", "cwd": cwd, "sessionId": sid, "isSidechain": False,
         "message": {"role": "assistant", "model": model,
                     "content": [{"type": "text", "text": text}]}}
    if error:
        d["apiError"] = error
        d["message"]["model"] = "<synthetic>"
        d["apiErrorParams"] = {"rate_limit_info": {"rateLimitType": kind, "resetsAt": resets}}
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
        for name, body in (("claude", FAKE_CLAUDE), ("tmux", FAKE_TMUX)):
            p = self.bin / name
            p.write_text(body.format(py=PY, link=LINK))
            p.chmod(0o755)
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

    def spawn(self, tag="claude-fake-source"):
        """A real process to stand for a running session; its command line says `claude`."""
        p = subprocess.Popen([PY, "-c", "import time; time.sleep(120)", tag])
        self.procs.append(p)
        return p

    def live(self, home, sid, pid, cwd=None, bridge=None, status="idle"):
        (home / "sessions").mkdir(exist_ok=True)
        (home / "sessions" / f"{pid}.json").write_text(json.dumps({
            "pid": pid, "sessionId": sid, "cwd": cwd or str(self.work),
            "bridgeSessionId": bridge or "", "status": status, "entrypoint": "sdk-cli",
            "name": "rc-name", "tmux": ""}))

    # --- running ----------------------------------------------------------
    def env(self, **extra):
        e = {"HOME": str(self.home), "PATH": f"{self.bin}:/usr/bin:/bin:/usr/sbin:/sbin",
             "CSM_STATE_DIR": str(self.state), "CSM_CLAUDE": str(self.bin / "claude"),
             "CSM_TMUX": str(self.bin / "tmux"), "CSM_POLL": "0.05",
             "CSM_CONNECT_WAIT": "6", "CSM_SETTLE": "0.3", "CSM_NO_HOLD": "1",
             "FAKE_CLAUDE_LOG": str(self.claude_log), "FAKE_TMUX_CALLS": str(self.tmux_calls),
             "FAKE_TMUX_STATE": str(self.tmux_state), "LC_ALL": "C.UTF-8"}
        e.update({k: str(v) for k, v in extra.items()})
        return e

    def run(self, *args, **env):
        return subprocess.run([PY, str(TOOL), *args], capture_output=True, text=True,
                              env=self.env(**env), timeout=60)

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

    def close(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()


SID_A = "11111111-aaaa-4aaa-8aaa-111111111111"
SID_B = "22222222-bbbb-4bbb-8bbb-222222222222"
SID_C = "33333333-cccc-4ccc-8ccc-333333333333"


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


class Resolve(Base):
    def setUp(self):
        super().setUp()
        self.w.session(self.work, SID_A)

    def dry(self, to):
        return self.w.run("move", SID_A, "--to", to, "--dry-run")

    def test_name_email_prefix_substring(self):
        for spec in ("personal", "PERSONAL", "me@home.example", "pers", "erso", "home.example"):
            out = self.ok(self.dry(spec))
            self.assertIn("->  personal", out, spec)

    def test_ambiguous_is_refused_with_candidates(self):
        self.w.account("personal2", "me2@home.example", org="org-3")
        self.refused(self.dry("pers"), "matches 2 accounts", "personal", "personal2")

    def test_a_bare_number_is_refused(self):
        self.refused(self.dry("2"), "named, never numbered")

    def test_a_number_that_is_literally_a_name_works(self):
        self.w.account("2", "me3@else.example", org="org-9")
        self.assertIn("->  2 ", self.ok(self.dry("2")))

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

    def test_newest_first_and_a_live_session_is_never_cut(self):
        now = time.time()
        self.w.session(self.work, SID_A, mtime=now - 9000)          # old, but live
        self.w.session(self.personal, SID_B, mtime=now - 10)
        self.w.session(self.personal, SID_C, mtime=now - 100)
        self.w.live(self.work, SID_A, self.w.spawn().pid)
        rows = self.listing("--limit", "1")
        self.assertEqual([r["local_id"] for r in rows], [SID_A])
        rows = self.listing("--limit", "3")
        self.assertEqual([r["local_id"] for r in rows], [SID_B, SID_C, SID_A])
        self.assertTrue(rows[2]["live"])

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
        self.assertIn("work (me@work.example)  ->  personal", out)

    def test_two_quiet_copies_are_refused(self):
        self.w.session(self.personal, SID_A, lines=[
            user("refactor the parser", str(self.w.work), SID_A)])
        self.refused(self.w.run("move", SID_A, "--to", "work", "--dry-run"),
                     "a move is a copy")


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

    def test_window_already_there(self):
        self.w.tmux_state.write_text(json.dumps(
            {"sessions": {"csm-personal": {"moved-11111111": "/dev/null"}}}))
        self.refused(self.move("--to", "personal"), "already exists")

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
        self.assertTrue((dest.parent / "memory" / "MEMORY.md").exists())
        self.assertTrue(self.src.exists(), "the source must never be deleted")
        # the first-run gates, additively, keeping the file's mode, with a backup
        st = json.loads((self.personal / ".claude.json").read_text())
        self.assertTrue(st["projects"][str(self.w.work)]["hasTrustDialogAccepted"])
        self.assertTrue(st["hasCompletedOnboarding"])
        self.assertEqual(st["oauthAccount"]["emailAddress"], "me@home.example")
        self.assertEqual(stat.S_IMODE((self.personal / ".claude.json").stat().st_mode), 0o640)
        self.assertTrue((self.personal / ".claude.json.csm-bak").exists())
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
        other = subprocess.Popen(["sleep", "60"])
        self.w.procs.append(other)
        self.w.live(self.work, SID_A, other.pid)
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", "--stop-source"))
        self.assertIn("no longer a claude process", out)
        self.assertIsNone(other.poll())

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

    def test_prompt_is_answered_by_its_number(self):
        script = self.w.root / "screens.json"
        script.write_text(json.dumps([
            "Accessing workspace:\n\n Quick safety check: Is this a project you created or one "
            "you trust?\n\n ❯ 1. Yes, I trust this folder\n   2. No, exit\n",
            "Accessing workspace:\n ❯ 1. Yes, I trust this folder\n   2. No, exit\n"]))
        out = self.ok(self.w.run("move", SID_A, "--to", "personal", FAKE_TMUX_SCRIPT=script))
        self.assertIn(LINK, out)
        keys = [c[-1] for c in self.w.tmux_log() if c[0] == "send-keys"]
        self.assertEqual(keys[0], "1")
        self.assertNotIn("Down", keys)

    def test_bypass_warning_is_only_accepted_for_a_bypass_session(self):
        script = self.w.root / "screens.json"
        warning = ("WARNING: Claude Code running in Bypass Permissions mode\n"
                   " ❯ 1. No, exit\n   2. Yes, I accept\n")
        script.write_text(json.dumps([warning]))
        self.ok(self.w.run("move", SID_A, "--to", "personal", FAKE_TMUX_SCRIPT=script))
        keys = [c[-1] for c in self.w.tmux_log() if c[0] == "send-keys"]
        self.assertEqual(keys, ["2"])
        # the same screen for a session that did NOT run in bypass mode: no key at all
        cwd = str(self.w.work)
        self.w.session(self.work, SID_B, lines=[
            user("careful work", cwd, SID_B, perm="acceptEdits"), assistant("ok", cwd, SID_B)])
        self.w.tmux_calls.unlink()
        script.write_text(json.dumps([warning]))
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


class RunWindow(Base):
    def test_plan_is_read_once_and_the_window_reports_the_exit(self):
        plan = self.w.root / "plan.json"
        plan.write_text(json.dumps({
            "cwd": str(self.w.work), "config_dir": None, "local_id": SID_A, "rc_name": None,
            "perm": "plan", "model": "", "claude": str(self.w.bin / "claude"), "path": "",
            "title": "t", "from": "a", "to": "b", "window": "moved-x", "session": "csm-b"}))
        r = subprocess.run([PY, str(TOOL), "__run", str(plan)], capture_output=True, text=True,
                           env=self.w.env(FAKE_CLAUDE_SLEEP="0", FAKE_CLAUDE_RC="3",
                                          CLAUDE_CONFIG_DIR="/should/be/unset"))
        self.assertEqual(r.returncode, 3)
        self.assertIn("=== claude exited rc=3", r.stdout)
        self.assertFalse(plan.exists())
        call = self.w.claude_calls()[0]
        self.assertNotIn("CLAUDE_CONFIG_DIR", call["env"])
        self.assertEqual(call["argv"], ["--permission-mode", "plan", "--resume", SID_A])


if __name__ == "__main__":
    unittest.main(verbosity=2)
