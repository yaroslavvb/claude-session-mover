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
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent / "claude-session-mover"
PY = sys.executable
LINK = "https://claude.ai/code/session_01MovedFakeSession42"

FAKE_CLAUDE = r'''#!@PY@
import json, os, sys, time
log = os.environ.get("FAKE_CLAUDE_LOG")
if log:
    with open(log, "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "env": dict(os.environ)}) + "\n")
append = os.environ.get("FAKE_CLAUDE_APPEND_MODE")
if append:
    sid = sys.argv[sys.argv.index("--resume") + 1]
    for folder in os.scandir(os.environ["FAKE_CLAUDE_PROJECTS"]):
        p = os.path.join(folder.path, sid + ".jsonl")
        if os.path.exists(p):
            with open(p, "a") as f:
                f.write(json.dumps({"type": "permission-mode", "permissionMode": append}) + "\n")
footer = os.environ.get("FAKE_CLAUDE_FOOTER")
if footer:                      # printed BEFORE the link: the link ends the tool's wait
    print(footer, flush=True)
if any(a.startswith("--remote-control") for a in sys.argv) and not os.environ.get("FAKE_CLAUDE_NOURL"):
    print("Remote Control active: @LINK@", flush=True)
print("fake claude running", flush=True)
time.sleep(float(os.environ.get("FAKE_CLAUDE_SLEEP") or 1.0))
sys.exit(int(os.environ.get("FAKE_CLAUDE_RC") or 0))
'''

FAKE_TMUX = r'''#!@PY@
"""A tmux stand-in: sessions and windows live in a JSON file; a new window's command REALLY
runs (in the background, output to a pane file); capture-pane prints that file, or the next
scripted screen when FAKE_TMUX_SCRIPT holds some. Windows carry ids (@1, @2, ...) as the
real one does, and kill-window removes them: both are what `csm stop` depends on."""
import json, os, subprocess, sys
st_path = os.environ["FAKE_TMUX_STATE"]
calls = os.environ["FAKE_TMUX_CALLS"]
args = sys.argv[1:]
with open(calls, "a") as f:
    f.write(json.dumps(args) + "\n")
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
    pane = os.path.join(os.path.dirname(st_path), "pane-%s-%s.txt" % (sess, win))
    st["sessions"].setdefault(sess, {})[win] = {"pane": pane, "id": "@%d" % st["next"]}
    st["next"] += 1
    save()
    out = open(pane, "w")
    subprocess.Popen(["/bin/sh", "-c", shell_cmd], cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, start_new_session=True)
    sys.exit(0)
if cmd == "kill-window":
    sess, win = target()
    if win not in st["sessions"].get(sess, {}):
        sys.exit(1)
    del st["sessions"][sess][win]
    save()
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
        self.tmux_env = root / "tmux-env.jsonl"
        for name, body in (("claude", FAKE_CLAUDE), ("tmux", FAKE_TMUX)):
            p = self.bin / name
            p.write_text(body.replace("@PY@", PY).replace("@LINK@", LINK))
            p.chmod(0o755)
        # 🛑 A stand-in for a running session has to be a real executable NAMED claude:
        # the pid guard reads argv[0]'s basename, and a `#!` script's ps line names the
        # interpreter instead. A symlink to /bin/sleep behaves the same on macOS and Linux.
        self.procbin = root / "procbin"
        self.procbin.mkdir()
        os.symlink("/bin/sleep", str(self.procbin / "claude"))
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

    def spawn(self, name="claude"):
        """A real process standing for a running session, running an executable named
        `claude` (or `sleep`, for the negative case)."""
        exe = str(self.procbin / "claude") if name == "claude" else "/bin/sleep"
        p = subprocess.Popen([exe, "120"])
        self.procs.append(p)
        return p

    def live(self, home, sid, pid, cwd=None, bridge=None, status="idle", tmux="",
             proc_start=None):
        (home / "sessions").mkdir(exist_ok=True)
        row = {"pid": pid, "sessionId": sid, "cwd": cwd or str(self.work),
               "bridgeSessionId": bridge or "", "status": status, "entrypoint": "sdk-cli",
               "name": "rc-name", "tmux": tmux}
        if proc_start is None:
            proc_start = ps_start(pid)       # read with the tool's own command, never hardcoded
        if proc_start:
            row["procStart"] = proc_start
        (home / "sessions" / f"{pid}.json").write_text(json.dumps(row))

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
        # one round trip proves the CLI is wired to the resolver; the ladder itself is
        # pinned in-process, because six more subprocess launches buy nothing
        self.assertIn("->  personal", self.ok(self.dry("pers")))
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
        # module-level env reads happen at import: point them at the tempdir afterwards
        self.mod.HOME = self.root / "home"
        self.mod.LOG = self.root / "log"
        self.mod.STATE_DIR = self.root / "state"
        self.mod.PICKS = self.root / "picks.json"
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
            os.symlink("/bin/sleep", str(pb / "claude"))
        p = subprocess.Popen([str(pb / "claude"), "120"])
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
        self.assertEqual(self.mod.memory_slug(str(self.root / "work")), "")  # no repo: ""

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

    def test_the_help_says_a_move_never_crosses_machines(self):
        import argparse
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            with self.assertRaises(SystemExit):
                self.mod.main(["--help"])
        self.assertIn("ONE machine", out.getvalue())
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

    def test_the_one_machine_limit_is_in_the_help(self):
        out = self.ok(self.w.run("--help"))
        self.assertIn("ONE machine", out)


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
        self.refused(self.w.run("stop", SID_B), "not a session csm moved",
                     "moved-11111111")

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
        self.refused(self.w.run("stop", SID_A), "not a session csm moved",
                     "csm has moved nothing here")


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
        self.assertIn("fungibility matrix on", out)
        for col in ("work", "personal"):
            self.assertIn(col, out)
        for layer in ("account", "login", "settings.json", "CLAUDE.md", "skills",
                      "plugins enabled", "MCP servers", "auto-memory", "onboarding",
                      "folder trust", "permissions mode", "disableAutoMode",
                      "bypass consent", "CLI version", "connectors", "MCP sign-ins"):
            self.assertIn(layer, out)
        self.assertIn("point every home's settings.json at one copy", out)
        self.assertIn("shareable layer(s) agree across 2 home(s)", out)
        # the legend explains every verdict the table used
        self.assertIn("one shared file or key away", out)
        self.assertIn("could not look", out)

    def test_connectors_and_mcp_signins_are_stated_whatever_is_measured(self):
        out = self.table()
        # a span row wraps instead of being truncated: these are the rows people quote
        self.assertIn("claude.ai/customize/connectors, not readable", out)
        self.assertIn("offline", out.split("claude.ai/customize/connectors")[1])
        self.assertIn("per home — stored inside the login credential, not read", out)

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
        out = self.ok(self.w.run("move", SID_A, "--to", "work"))
        self.assertIn(LINK, out)
        self.assertEqual(self.t.read_bytes(), self.before)
        self.assertEqual(list(self.central.rglob("*.csm-bak-*")), [])
        self.assertEqual(len(list(self.central.rglob(SID_A + ".jsonl"))), 1)
        call = self.w.claude_calls()[0]
        self.assertEqual(call["argv"][-2:], ["--resume", SID_A])
        self.assertEqual(call["env"]["CLAUDE_CONFIG_DIR"], str(self.work))

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
