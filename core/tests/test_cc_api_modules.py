#!/usr/bin/env python3
"""CC-0039: the factory's modules the API loads by path (`api/factory.py`
`_mod`) are loaded once, under a lock, and handed out only fully executed.

Found by CC-0007's live check: on a freshly started API two parallel
`GET /api/channels/<a>` and `/<b>` answered 500 - `module 'validate_inserts'
has no attribute 'channel_config_errors'`: the second request took the module
the first was still executing (FastAPI runs the sync routes in a threadpool).

What is pinned:

* a slow stand-in module (it sleeps before it defines its name), loaded by
  many threads at once on a cold cache: every thread gets the one finished
  module, it is executed once;
* the real app on a cold cache (the modules `_mod` loads and runlog's
  neighbours taken out of the cache and of `sys.modules`): many threads asking for two channels at once all get
  200 - and the modules they used are freshly loaded ones, so the cold path
  really ran;
* a plain `import` of the module running in another thread (a factory module
  does `import runlog` while a route reaches `_mod("runlog")`) is waited for,
  not taken half-done;
* the same for runlog's own loader of its neighbours (`runlog.sibling`, a copy
  of runlog.py in a temp dir with slow stand-in neighbours) - the second race
  the cold app hit once `_mod` was fixed (`module 'sampler' has no attribute
  'MAX_HOURS'`);
* an exec that fails leaves nothing half-loaded: the name is in neither the
  cache nor `sys.modules` (or what was there before is back), the error goes
  up, and once the file is fixed the next call loads it.

Stand-ins only: a temp code tree for the stand-in modules, the temp factory of
`test_cc_api_channels.py` for the app; the live checkout's channels are never
read.
"""
import re
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from _tmproot import tmp_root                        # noqa: E402
from api import factory                              # noqa: E402
import test_cc_api_channels as tc                    # noqa: E402

TMP = tmp_root("cc-api-modules-test-")
N = 12

# the names `_mod` loads - read from the module itself, so a new one is covered
LOADED = sorted(set(re.findall(r'_mod\("(\w+)"', Path(factory.__file__).read_text())))
# and the modules runlog loads beside itself (`runlog.sibling`) - a fresh API
# has none of them either
SIBLINGS = sorted(set(re.findall(r'sibling\("(\w+)"\)',
                                 (ROOT / "shared/runlog/runlog.py").read_text())))


class _Cold:
    """Take the named modules out of `_mod`'s cache and `sys.modules`; put the
    originals back afterwards (other tests hold them)."""

    def __init__(self, names):
        self.names = names

    def __enter__(self):
        self.saved = {n: (factory._MODS.pop(n, None), sys.modules.pop(n, None))
                      for n in self.names}
        return self

    def __exit__(self, *exc):
        for n, (cached, mod) in self.saved.items():
            factory._MODS.pop(n, None)
            sys.modules.pop(n, None)
            if cached is not None:
                factory._MODS[n] = cached
            if mod is not None:
                sys.modules[n] = mod
        return False


class _Code:
    """Point `_mod` at a temp code tree."""

    def __init__(self, tree):
        self.tree = tree

    def __enter__(self):
        self.saved = factory.CODE
        factory.CODE = self.tree
        return self

    def __exit__(self, *exc):
        factory.CODE = self.saved
        return False


_K = [0]


def code_tree(files):
    _K[0] += 1
    tree = TMP / f"code-{_K[0]}"
    for rel, text in files.items():
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_text(text, encoding="utf-8")
    return tree


def _together(fn, n=N):
    """Run fn() in n threads released at once; (results, errors)."""
    gate = threading.Barrier(n)
    results, errors = [None] * n, []

    def run(i):
        try:
            gate.wait()
            results[i] = fn(i)
        except BaseException as e:                       # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads), "a thread hung"
    return results, errors


def test_the_names_loaded_by_path_are_known():
    assert {"validate_inserts", "run_plan", "channel_ids", "runlog"} <= set(LOADED), LOADED
    assert "sampler" in SIBLINGS, SIBLINGS


def test_a_slow_module_on_a_cold_cache_is_handed_out_only_finished():
    name = "cc0039_slow"
    tree = code_tree({"slow/slow.py": (
        "import time\n"
        "import builtins\n"
        "builtins.cc0039_execs = getattr(builtins, 'cc0039_execs', 0) + 1\n"
        "time.sleep(0.3)\n"
        "def finished():\n"
        "    return 'yes'\n")})
    import builtins
    builtins.cc0039_execs = 0
    with _Code(tree), _Cold([name]):
        results, errors = _together(lambda i: factory._mod(name, "slow/slow.py").finished())
        assert not errors, [repr(e) for e in errors]
        assert results == ["yes"] * N, results
        assert builtins.cc0039_execs == 1, builtins.cc0039_execs
        assert factory._MODS[name] is sys.modules[name]
    del builtins.cc0039_execs


SLOW = ("import time\n"
        "time.sleep(0.3)\n"
        "def finished():\n"
        "    return 'yes'\n")


def _plain_import_meets(get, name, tree):
    """A plain `import <name>` (from `tree` on sys.path) is running in one
    thread while the others ask `get()` for it: what they got."""
    started = threading.Event()

    def plain():
        sys.path.insert(0, str(tree))
        try:
            started.set()
            return __import__(name).finished()
        finally:
            sys.path.remove(str(tree))

    def ask(i):
        if i == 0:
            return plain()
        started.wait(5)
        for _ in range(200):                 # until the plain import is under way
            if name in sys.modules:
                break
            threading.Event().wait(0.005)
        return get().finished()

    return _together(ask, n=4)


def test_a_plain_import_in_progress_is_waited_for():
    name = "cc0039_plain"
    tree = code_tree({f"{name}.py": SLOW})
    with _Code(tree), _Cold([name]):
        results, errors = _plain_import_meets(lambda: factory._mod(name, f"{name}.py"), name, tree)
        assert not errors, [repr(e) for e in errors]
        assert results == ["yes"] * 4, results


def _runlog_copy():
    """runlog.py copied into a temp dir, loaded by path: its `sibling` then
    looks beside the copy, where the test puts a slow stand-in."""
    tree = code_tree({"runlog_copy.py": (ROOT / "shared/runlog/runlog.py").read_text(),
                      "cc0039_sib.py": SLOW, "cc0039_sib2.py": SLOW})
    import importlib.util
    spec = importlib.util.spec_from_file_location("cc0039_runlog", tree / "runlog_copy.py")
    rl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rl)
    return rl, tree


def test_runlog_sibling_hands_out_only_finished_modules():
    rl, tree = _runlog_copy()
    with _Cold(["cc0039_sib", "cc0039_sib2"]):
        results, errors = _together(lambda i: rl.sibling("cc0039_sib").finished())
        assert not errors, [repr(e) for e in errors]
        assert results == ["yes"] * N, results
        results, errors = _plain_import_meets(lambda: rl.sibling("cc0039_sib2"), "cc0039_sib2",
                                              tree)
        assert not errors, [repr(e) for e in errors]
        assert results == ["yes"] * 4, results


def test_the_app_on_a_cold_cache_answers_parallel_first_requests():
    root = tc.factory_tree()
    app_client = tc.client(root)
    for _ in range(3):
        with _Cold(LOADED + SIBLINGS) as cold:
            def ask(i):
                cid = ("reel", "demo")[i % 2]
                return app_client.get(f"/api/channels/{cid}").status_code
            # one TestClient per thread would also do; a shared one is what a
            # browser's parallel fetches look like to the threadpool
            results, errors = _together(ask)
            assert not errors, [repr(e) for e in errors]
            assert results == [200] * N, results
            fresh = [n for n in ("validate_inserts", "run_plan", "channel_ids")
                     if factory._MODS.get(n) is not None
                     and factory._MODS[n] is not cold.saved[n][0]]
            assert fresh == ["validate_inserts", "run_plan", "channel_ids"], fresh
            assert hasattr(factory._MODS["validate_inserts"], "channel_config_errors")


def test_a_failing_exec_leaves_nothing_half_loaded():
    name = "cc0039_broken"
    tree = code_tree({"broken.py": "HALF = 1\nraise RuntimeError('broken on purpose')\n"})
    with _Code(tree), _Cold([name]):
        for _ in range(2):                       # every call tries afresh, none sticks
            try:
                factory._mod(name, "broken.py")
            except RuntimeError as e:
                assert "broken on purpose" in str(e)
            else:
                raise AssertionError("the error did not go up")
            assert name not in sys.modules and name not in factory._MODS
        # in parallel too: every thread sees the error, none a half module
        results, errors = _together(lambda i: factory._mod(name, "broken.py"))
        assert len(errors) == N and all(isinstance(e, RuntimeError) for e in errors), errors
        assert name not in sys.modules and name not in factory._MODS
        (tree / "broken.py").write_text("HALF = 1\nWHOLE = 2\n", encoding="utf-8")
        m = factory._mod(name, "broken.py")
        assert m.WHOLE == 2 and factory._MODS[name] is m is sys.modules[name]


def test_a_failing_exec_puts_back_what_was_there():
    name = "cc0039_other"
    tree = code_tree({"other.py": "raise ValueError('no')\n"})
    stand = type(sys)("cc0039_other")           # a module of that name from elsewhere
    stand.__file__ = str(TMP / "elsewhere.py")
    with _Code(tree), _Cold([name]):
        sys.modules[name] = stand
        try:
            factory._mod(name, "other.py")
        except ValueError:
            pass
        else:
            raise AssertionError("the error did not go up")
        assert sys.modules[name] is stand and name not in factory._MODS


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
