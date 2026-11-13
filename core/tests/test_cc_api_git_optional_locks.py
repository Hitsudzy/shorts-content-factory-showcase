"""CC-0119 (item 4): every git read the API starts runs with
GIT_OPTIONAL_LOCKS=0, so a status read beside a running batch never takes
`.git/index.lock` from under a stage commit. The variable comes from the
factory's one door, `shared/runlog/git_read.py` (CF-0717, `GIT_READ_ENV`):

* the API's own children - `versions.run_status` (`scripts/agents status`),
  `maintenance.run_archive` (the archive dry run) - get `factory.git_env()`;
* `channels._git` (the channel edits' git) hands it to `git_read.run`;
* the factory's functions that run git in this process (`agents_lock.status`,
  `is_working_factory`, `runlog._git`) run inside `factory.git_reads()`.

Stand-ins only: every child and every git call is replaced; nothing runs git
on a real repository."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _tmproot import tmp_root                     # noqa: E402

from api import channels, child, factory, maintenance, versions   # noqa: E402

KEY = "GIT_OPTIONAL_LOCKS"
TMP = tmp_root("cc-api-git-locks-test-")


class _Swap:
    """Replace `obj.name` for the block, put it back after."""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.saved = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.saved)


def test_the_value_is_the_factory_s():
    assert factory.git_read().GIT_READ_ENV == {KEY: "0"}
    env = factory.git_env({"PATH": "/bin", KEY: "1"})
    assert env[KEY] == "0" and env["PATH"] == "/bin"
    assert factory.git_env()[KEY] == "0"


def test_the_api_s_own_children_get_the_env():
    seen = []

    def fake_start(cmd, *, timeout, cwd=None, env=None):
        seen.append(env)
        return None
    with _Swap(child, "start", fake_start):
        versions.run_status(TMP)
        maintenance.run_archive(["true"])
    assert len(seen) == 2
    for env in seen:
        assert env is not None and env.get(KEY) == "0", env


def test_the_channel_git_goes_through_the_door_with_the_env():
    gr = factory.git_read()
    seen = []

    class CP:
        returncode, stdout, stderr = 0, "", ""

    def fake_run(args, **kw):
        seen.append((args, kw.get("env")))
        return CP()
    with _Swap(gr, "run", fake_run):
        channels._git(TMP, "status", "--porcelain")
    (args, env), = seen
    assert args[-2:] == ["status", "--porcelain"] and env[KEY] == "0", (args, env)


def test_the_factory_s_git_functions_run_inside_git_reads():
    was = os.environ.get(KEY)
    seen = {}
    rl, al = factory.runlog(), factory.agents_lock()

    def look(name, value):
        def f(*a, **kw):
            seen[name] = os.environ.get(KEY)
            return value
        return f
    with _Swap(rl, "_git", look("runlog._git", {"commit": "abc", "dirty": False})), \
            _Swap(al, "status", look("agents_lock.status", [])), \
            _Swap(al, "is_working_factory", look("is_working_factory", (True, ""))):
        factory.factory_version(TMP)
        factory.agent_pins(TMP)
        factory.forget_working_factory()
        factory.working_factory(TMP / "never-asked-before")
        factory.forget_working_factory()
    assert seen == {"runlog._git": "0", "agents_lock.status": "0",
                    "is_working_factory": "0"}, seen
    assert os.environ.get(KEY) == was, "put back after the read"


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
