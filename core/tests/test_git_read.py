#!/usr/bin/env python3
"""CF-0717: the factory's git reads run with GIT_OPTIONAL_LOCKS=0, through one door.

`git status` refreshes a stale `.git/index` and writes it back under
`.git/index.lock` - an "optional lock". Beside a batch, a stage commit or the
command center that is a race for the lock, and the writer that loses fails.
`shared/runlog/git_read.py` is the door every git child of the root code goes
through: a read gets GIT_OPTIONAL_LOCKS=0 on top of the caller's env, a write
(commit, add, mv, ...) the caller's env untouched.

What is fixed here:
- the helper sets the variable and keeps everything else of the caller's env;
  a write is left alone; reads and writes are told apart past `-C <dir>`;
- on a real temp repo with a stale index, `git status` through the helper - and
  through the factory's own readers (`runlog._git`, `runlog._git_out`,
  `agents_lock._git`, `git_commit.git`) - leaves `.git/index` byte for byte and
  its mtime as they were, while a plain `git status` does rewrite it (the trap
  is real);
- the guard: no root code starts `["git", ...]` itself past the helper, except
  the short list of writers below (each entry still has to be there).

Temp repos only, no network, no live data; a second or two.
"""
import ast
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))     # first: `runlog` is the module, not the folder

from _tmproot import tmp_root   # noqa: E402

import git_read      # noqa: E402
import git_commit    # noqa: E402
import agents_lock   # noqa: E402

TMP = tmp_root("git-read-test-")
os.environ["FACTORY_ROOT"] = str(TMP / "factory")          # runlog never looks at the repo's root
(TMP / "factory").mkdir()
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
import runlog        # noqa: E402

KEY = "GIT_OPTIONAL_LOCKS"


def _plain_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, LC_ALL="C")
    return env


def _git(repo, *args):
    cp = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                         *args], capture_output=True, text=True, env=_plain_env(), timeout=30)
    assert cp.returncode == 0, cp.stderr
    return cp


_n = [0]


def stale_repo():
    """A repo with one commit whose tracked files' stat changed since the index
    was written (content the same): the next `git status` wants to refresh it."""
    _n[0] += 1
    repo = TMP / f"repo{_n[0]}"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for name in ("a.txt", "b.txt"):
        (repo / name).write_text(name + "\n")
    _git(repo, "add", "a.txt", "b.txt")
    _git(repo, "commit", "-q", "-m", "one")
    old = time.time() - 100
    for name in ("a.txt", "b.txt"):
        os.utime(repo / name, (old, old))
    old_idx = time.time() - 200
    os.utime(repo / ".git" / "index", (old_idx, old_idx))
    return repo


def index_state(repo):
    p = repo / ".git" / "index"
    return p.read_bytes(), p.stat().st_mtime_ns


class Env:
    """os.environ with KEY set to `value` (None - unset) for the block."""

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        self.was = os.environ.get(KEY)
        if self.value is None:
            os.environ.pop(KEY, None)
        else:
            os.environ[KEY] = self.value

    def __exit__(self, *exc):
        if self.was is None:
            os.environ.pop(KEY, None)
        else:
            os.environ[KEY] = self.was


# ------------------------------------------------------------------ the helper
def test_read_env_sets_the_variable_and_keeps_the_callers_env():
    caller = {"PATH": "/x", "LC_ALL": "C", "GIT_TERMINAL_PROMPT": "0", KEY: "1"}
    env = git_read.read_env(caller)
    assert env[KEY] == "0"
    assert {k: v for k, v in env.items() if k != KEY} == \
        {k: v for k, v in caller.items() if k != KEY}
    assert caller[KEY] == "1", "the caller's dict is not changed"
    with Env(None):
        env = git_read.read_env()
        assert env[KEY] == "0" and env.get("PATH") == os.environ.get("PATH")
        assert KEY not in os.environ, "os.environ itself is not touched"


def test_reads_and_writes_are_told_apart():
    reads = [["status", "--porcelain"], ["-C", "/x", "rev-parse", "HEAD"],
             ["-C", "/x", "-c", "a=b", "log", "-1"], ["--no-pager", "diff"],
             ["-C", "/x", "ls-files", "-z"], ["worktree", "list", "--porcelain"],
             ["symbolic-ref", "--short", "-q", "HEAD"], ["check-ignore", "--stdin"],
             ["show", "HEAD:x"], ["for-each-ref"], ["merge-base", "a", "b"],
             ["config", "--get", "x.y"], ["branch", "--show-current"]]
    writes = [["commit", "-m", "x"], ["-C", "/x", "add", "--", "a"], ["mv", "a", "b"],
              ["worktree", "add", "/y", "v1"], ["checkout", "v1"], ["tag", "v1"],
              ["symbolic-ref", "HEAD", "refs/heads/x"], ["config", "x.y", "1"],
              ["reset", "-q", "--", "a"], ["rm", "a"], ["push"], ["fetch", "--tags"],
              ["branch", "x"], [], ["-C", "/x"]]
    for a in reads:
        assert git_read.is_read(a), a
        assert git_read.env_for(a, {"A": "1"}) == {"A": "1", KEY: "0"}, a
    for a in writes:
        assert not git_read.is_read(a), a
        mine = {"A": "1"}
        assert git_read.env_for(a, mine) is mine, a              # the caller's env, untouched
        assert git_read.env_for(a) is None, a                    # None: the child inherits


def test_run_hands_git_the_env_and_the_rest_as_given():
    seen = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    subprocess.run = spy
    try:
        git_read.run(["-C", "/x", "status"], env={"A": "1"}, timeout=7, capture_output=True)
        git_read.run(["-C", "/x", "commit", "-m", "m"], env={"A": "1"}, timeout=7)
        git_read.run(("rev-parse", "HEAD"), cwd="/y", timeout=3)
        try:
            git_read.run(["status"])
        except TypeError:
            pass
        else:
            raise AssertionError("a git child without a ceiling (CF-0229) is refused")
    finally:
        subprocess.run = real
    (c1, k1), (c2, k2), (c3, k3) = seen
    assert c1 == ["git", "-C", "/x", "status"] and k1["env"] == {"A": "1", KEY: "0"}
    assert k1["timeout"] == 7 and k1["capture_output"] is True
    assert c2[:4] == ["git", "-C", "/x", "commit"] and k2["env"] == {"A": "1"}
    assert c3 == ["git", "rev-parse", "HEAD"] and k3["cwd"] == "/y"
    assert k3["env"][KEY] == "0" and k3["env"].get("PATH") == os.environ.get("PATH")


# ------------------------------------------------------------------ a real index
def test_status_through_the_helper_leaves_the_index_alone():
    repo = stale_repo()
    before = index_state(repo)
    with Env(None):
        cp = git_read.run(["-C", str(repo), "status", "--porcelain"], capture_output=True,
                          text=True, env=_plain_env(), timeout=30)
    assert cp.returncode == 0 and cp.stdout == "", cp.stdout + cp.stderr
    assert index_state(repo) == before, "git status through the helper rewrote .git/index"
    # the trap is real: the same read without the helper writes the index back
    cp = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True,
                        text=True, env=_plain_env(), timeout=30)
    assert cp.returncode == 0
    assert index_state(repo) != before, "a plain git status should refresh a stale index"


def test_the_factory_readers_leave_the_index_alone():
    with Env(None):
        for name, read in (
                ("runlog._git", lambda r: runlog._git(r)),
                ("runlog._git_out", lambda r: runlog._git_out(r, "status", "--porcelain")),
                ("agents_lock._git", lambda r: agents_lock._git(r, "status", "--porcelain")),
                ("agents_lock.dirty", lambda r: agents_lock.dirty(r)),
                ("git_commit.git", lambda r: git_commit.git(r, "status", "--porcelain"))):
            repo = stale_repo()
            before = index_state(repo)
            read(repo)
            assert index_state(repo) == before, f"{name} rewrote .git/index"
            assert KEY not in os.environ, name


# ------------------------------------------------------------------ the guard
#: Code dirs of the root repository (the agents with a repo of their own are
#: theirs; frontend/ is the center's).
CODE_DIRS = ("shared", "scripts", "api", "agents/analyst", "agents/publisher",
             "inserts", "patterns", "rotation", "pipeline", "publish", "analytics",
             "notify", "channels")
SKIP_PARTS = {"tests", ".venv", "__pycache__", "node_modules", ".git"}
HELPER = "shared/runlog/git_read.py"
#: Writers that start git themselves - a subcommand that does not read the
#: repository. Each entry must still be found (a stale one is a failure).
ALLOWED_WRITERS = {
    ("shared/runlog/publish_layout.py", "mv"): "`git mv` of a tracked publish note",
    ("api/channels.py", "merge-file"): "`git merge-file -p` on temp files, no repository",
}
_SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output"}


def _code_files():
    for d in CODE_DIRS:
        base = ROOT / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or SKIP_PARTS & set(p.relative_to(ROOT).parts):
                continue
            if p.suffix == ".py":
                yield p
            elif not p.suffix and d == "scripts":
                try:
                    first = p.read_text(encoding="utf-8").splitlines()[:1]
                except (OSError, UnicodeDecodeError):
                    continue
                if first and "python" in first[0]:
                    yield p


def _is_subprocess_call(func):
    if isinstance(func, ast.Attribute) and func.attr in _SUBPROCESS_CALLS:
        return isinstance(func.value, ast.Name) and func.value.id == "subprocess"
    return isinstance(func, ast.Name) and func.id in _SUBPROCESS_CALLS - {"run"}


def git_starts(source):
    """[(line, subcommand or None, why)] of the git children `source` starts
    itself: a subprocess call whose argv is a literal list/tuple opening with
    "git" (subcommand None - not a literal, e.g. `*args`), or a "git ..." string."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and _is_subprocess_call(node.func) and node.args):
            continue
        a0 = node.args[0]
        if isinstance(a0, (ast.List, ast.Tuple)) and a0.elts:
            e0 = a0.elts[0]
            if isinstance(e0, ast.Constant) and e0.value == "git":
                words = []
                for e in a0.elts[1:]:
                    if isinstance(e, ast.Constant) and isinstance(e.value, str):
                        words.append(e.value)
                    else:
                        words.append(None)                     # a value or *args
                sub = _literal_subcommand(words)
                found.append((node.lineno, sub, "argv"))
        elif isinstance(a0, ast.Constant) and isinstance(a0.value, str) \
                and a0.value.strip().startswith("git "):
            found.append((node.lineno, None, "shell string"))
        elif isinstance(a0, ast.JoinedStr) and a0.values and \
                isinstance(a0.values[0], ast.Constant) and \
                str(a0.values[0].value).strip().startswith("git "):
            found.append((node.lineno, None, "shell string"))
    return found


def _literal_subcommand(words):
    i = 0
    while i < len(words):
        w = words[i]
        if w is None:
            return None
        if w in git_read._GLOBAL_WITH_VALUE:
            i += 2
            continue
        if w.startswith("-"):
            i += 1
            continue
        return w
    return None


def test_the_guard_sees_a_direct_read():
    src = ('import subprocess\n'
           'subprocess.run(["git", "status", "--porcelain"])\n'
           'subprocess.run(["git", "-C", str(d), *args], timeout=5)\n'
           'subprocess.check_output(("git", "-C", d, "rev-parse", "HEAD"))\n'
           'subprocess.run("git status", shell=True)\n'
           'subprocess.run(["git", "-C", d, "mv", a, b])\n'
           'subprocess.run(["python3", "git"])\n')
    got = [(line, sub) for line, sub, _ in git_starts(src)]
    assert got == [(2, "status"), (3, None), (4, "rev-parse"), (5, None), (6, "mv")], got


def test_no_root_code_starts_a_git_read_past_the_helper():
    bad, met = [], set()
    files = list(_code_files())
    assert len(files) > 50, f"the guard sees too few files ({len(files)}) - CODE_DIRS moved?"
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if rel == HELPER:
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "git" not in src:
            continue
        for line, sub, why in git_starts(src):
            if sub is not None and not git_read.is_read([sub]) and (rel, sub) in ALLOWED_WRITERS:
                met.add((rel, sub))
                continue
            bad.append(f"{rel}:{line}: git {sub or '<not a literal>'} ({why}) - "
                       f"start it through shared/runlog/git_read.py (`git_read.run`)")
    assert not bad, "git started past the helper (CF-0717):\n" + "\n".join(bad)
    stale = set(ALLOWED_WRITERS) - met
    assert not stale, f"allow-list entries no longer met - drop them: {sorted(stale)}"


def test_the_center_reuses_the_helper():
    """api/factory.git_env and api/channels go through the same door."""
    src = (ROOT / "api" / "factory.py").read_text(encoding="utf-8")
    assert '_mod("git_read", "shared/runlog/git_read.py")' in src
    assert "GIT_READ_ENV = {" not in src, "the center keeps no second copy of the variable"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
