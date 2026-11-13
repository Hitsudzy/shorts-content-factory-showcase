"""CF-0620: `PRICES_FILE` of `shot_usability.py`, `screen_recording.py` and
`sharpness.py` is the price table of the factory this checkout belongs to,
not the home checkout's.

The default was `Path.home() / "shorts-content-factory" / "shared" /
"gate-prices.json"`: code and tests of a version worktree
(`.worktrees/release-<v>/agents/footage-indexer`) priced shots by the live
factory's table instead of their own (found by the CF-0612 audit hook). It is
now `_fi_paths.prices_file()`: FACTORY_ROOT when it holds a table, else the
root this checkout lives in - and outside any tree the root its place implies.
Video-editor's `shot_score` loads these modules by path with the indexer's
scripts/ not on sys.path, so the modules reach `_fi_paths` by path too; that
load is checked here as a child process with nothing of the indexer on
sys.path.

Every layout is a temp tree with copies of the modules, so the answer is
checked against a root that is certainly not the home checkout.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _fi_paths  # noqa: E402

MODULES = ("shot_usability", "screen_recording", "sharpness")
COPIED = MODULES + ("_fi_paths",)

# A by-path load, the way video-editor's shot_score.sharpness_module() does it:
# no indexer directory on sys.path, the module's own siblings handed over only
# for shot_usability (shot_score._load_indexer_module).
PROBE = r"""
import importlib.util, sys
from pathlib import Path
scripts = Path(sys.argv[1])
assert str(scripts) not in sys.path
def load(name):
    spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
deps = {n: load(n) for n in ("screen_recording", "sharpness")}
for n, m in deps.items():
    print(n, m.PRICES_FILE)
sys.modules.update(deps)
print("shot_usability", load("shot_usability").PRICES_FILE)
"""


def _env(root=None):
    env = {k: v for k, v in os.environ.items() if k not in ("FACTORY_ROOT", "PYTHONPATH")}
    if root is not None:
        env["FACTORY_ROOT"] = str(root)
    return env


def _factory(tmp, name="factory", table=True, marker=True):
    """`<tmp>/<name>` holding the agent's scripts at
    `agents/footage-indexer/scripts/`, the runlog marker and a price table."""
    root = Path(tmp) / name
    scripts = root / "agents" / "footage-indexer" / "scripts"
    scripts.mkdir(parents=True)
    for n in COPIED:
        shutil.copy(SCRIPTS / f"{n}.py", scripts / f"{n}.py")
    if marker:
        (root / "shared" / "runlog").mkdir(parents=True)
        (root / "shared" / "runlog" / "runlog.py").write_text("")
    if table:
        (root / "shared").mkdir(exist_ok=True)
        (root / "shared" / "gate-prices.json").write_text('{"rules": {}}')
    return root, scripts


def _probe(scripts, env, cwd):
    out = subprocess.run([sys.executable, "-c", PROBE, str(scripts)], capture_output=True,
                         text=True, env=env, cwd=cwd, timeout=60)
    assert out.returncode == 0, out.stderr
    return dict(line.split(" ", 1) for line in out.stdout.splitlines())


def test_this_checkout_prices_by_its_own_root():
    """In this process, imported the usual way: the table of the factory this
    checkout lives in - `<root>/shared/gate-prices.json`, three parents above
    scripts/ - unless FACTORY_ROOT names one with a table."""
    import screen_recording
    import sharpness
    import shot_usability
    expected = _fi_paths.prices_file()
    own = SCRIPTS.resolve().parents[2] / "shared" / "gate-prices.json"
    if not os.environ.get("FACTORY_ROOT"):
        assert expected == own, (expected, own)
    for mod in (shot_usability, screen_recording, sharpness):
        assert mod.PRICES_FILE == expected, (mod.__name__, mod.PRICES_FILE, expected)


def test_a_worktree_loaded_by_path_reads_its_own_table():
    """A checkout in another factory tree (a version worktree), its modules
    loaded by path from a process that has none of them on sys.path: every
    PRICES_FILE is that tree's table."""
    with tempfile.TemporaryDirectory(prefix="cf0620-") as tmp:
        root, scripts = _factory(tmp)
        got = _probe(scripts, _env(), tmp)
        want = str((root / "shared" / "gate-prices.json").resolve())
        assert set(got) == set(MODULES), got
        assert all(v == want for v in got.values()), (got, want)


def test_factory_root_with_a_table_wins_one_without_does_not_hide_ours():
    with tempfile.TemporaryDirectory(prefix="cf0620-") as tmp:
        root, scripts = _factory(tmp)
        other, _ = _factory(tmp, "other")
        got = _probe(scripts, _env(other), tmp)
        want = str((other / "shared" / "gate-prices.json").resolve())
        assert all(v == want for v in got.values()), (got, want)

        bare = Path(tmp) / "bare"
        (bare / "channels").mkdir(parents=True)
        got = _probe(scripts, _env(bare), tmp)
        want = str((root / "shared" / "gate-prices.json").resolve())
        assert all(v == want for v in got.values()), (got, want)


def test_outside_any_tree_the_place_implies_the_root():
    """No marker above, no FACTORY_ROOT: the modules still load, and the table
    is the one `<root>/agents/footage-indexer/scripts/` implies - not a home
    path."""
    with tempfile.TemporaryDirectory(prefix="cf0620-") as tmp:
        root, scripts = _factory(tmp, marker=False, table=False)
        got = _probe(scripts, _env(), tmp)
        want = str((root / "shared" / "gate-prices.json").resolve())
        assert all(v == want for v in got.values()), (got, want)


def test_the_pool_follows_factory_root_strictly():
    """`_fi_paths.pool_dir()`: FACTORY_ROOT's pool even when it has none -
    never a fall-through to the live one."""
    with tempfile.TemporaryDirectory(prefix="cf0620-") as tmp:
        bare = Path(tmp) / "bare"
        bare.mkdir()
        code = "import _fi_paths; print(_fi_paths.pool_dir())"
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             env=_env(bare), cwd=str(SCRIPTS), timeout=60)
        assert out.stdout.strip() == str((bare / "shared" / "footage").resolve()), out


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:  # a crash is a failure, not a skip
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
