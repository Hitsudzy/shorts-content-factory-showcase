#!/usr/bin/env python3
"""CF-0706: the root's licence rule is never handed out half-loaded.

Production batch example-science/2026-10-12T2001Z: the footage-indexer stage's
ingest died with `AttributeError: module 'footage_licence_for_footage_indexer'
has no attribute 'licence_of'`. The ingest walks topics in a thread pool and
each walk asks `source_rights.refusal` -> `licence_rule()` about its first
candidate at the same moment. `licence_rule()` checked `sys.modules` without a
lock and put the new module there *before* executing it, so a second thread
found the half-executed module (its `__file__` already the right path) and
called `licence_of` on it before the first thread had defined it.

Pinned here on a temp root (no network, no live root, no channel file):

  - many threads asking `refusal` / `licence_rule` at once on a rule that is
    slow to execute all get a whole module (this failed before the fix);
  - a module left in `sys.modules` without `licence_of` (half-executed, or an
    old copy) is not handed out - it is loaded again;
  - a rule that raises half-way, or that has no `licence_of`, gives None (the
    NC / ND / non-free floor still decides) and leaves nothing behind.

No pytest dependency - plain asserts, run directly.
"""
import os
import sys
import tempfile
import threading
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import source_rights as sr          # noqa: E402
from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("cf0706-")
THREADS = 12

# A stand-in of the root's shared/footage_licence.py: slow to execute (the
# window the production threads fell into), then the real function's shape.
SLOW_RULE = '''
import time
time.sleep({delay})
OWN_GRAPHIC = "own_graphic"


def licence_of(short_name, licences, non_free=False):
    name = (short_name or "").lower()
    for lic in licences.get("accepted") or []:
        if any(m in name for m in lic.get("matches") or []):
            return {{"id": lic["id"], "accepted": True, "reason": None}}
    return {{"id": None, "accepted": False, "reason": "not on the accepted list"}}
'''

ORIGINS = {"licences": {"accepted": [{"id": "cc_by", "matches": ["cc by"]}],
                        "refused": []}}
CANDIDATE = {"licence": {"short_name": "Some Licence 1.0", "id": None,
                         "judged": False}}


def make_root(body):
    root = Path(tempfile.mkdtemp(dir=TMP))
    (root / "shared").mkdir()
    (root / "shared" / "footage_licence.py").write_text(body, encoding="utf-8")
    return root


class on_root:
    """FACTORY_ROOT -> `root`, with the rule unloaded before and after."""

    def __init__(self, root):
        self.root = root

    def _forget(self):
        sys.modules.pop(sr.MODULE_NAME, None)
        forget = getattr(sr, "_forget_loaded", None)
        if forget:
            forget()

    def __enter__(self):
        self.saved = os.environ.get("FACTORY_ROOT")
        os.environ["FACTORY_ROOT"] = str(self.root)
        self._forget()
        return self

    def __exit__(self, *exc):
        self._forget()
        if self.saved is None:
            os.environ.pop("FACTORY_ROOT", None)
        else:
            os.environ["FACTORY_ROOT"] = self.saved


def run_threads(fn):
    """`fn` in THREADS threads released together -> [(result, exc)]."""
    gate = threading.Barrier(THREADS)
    out = [None] * THREADS

    def one(i):
        gate.wait()
        try:
            out[i] = (fn(), None)
        except Exception as exc:        # noqa: BLE001 - the assertion reads it
            out[i] = (None, exc)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return out


def test_concurrent_refusals_all_read_a_whole_rule():
    with on_root(make_root(SLOW_RULE.format(delay=0.3))):
        out = run_threads(lambda: sr.refusal("v1", CANDIDATE, ORIGINS))
    errors = [repr(e) for _, e in out if e is not None]
    assert not errors, errors
    for why, _ in out:
        assert why and "not one this channel takes" in why, why


def test_concurrent_loads_hand_out_one_whole_module():
    with on_root(make_root(SLOW_RULE.format(delay=0.3))):
        # whole at the moment it is handed out, not only after the joins
        out = run_threads(lambda: (lambda m: (m, callable(getattr(m, "licence_of", None))))(
            sr.licence_rule()))
    assert all(e is None for _, e in out), out
    assert all(whole for (_, whole), _ in out), out
    mods = [m for (m, _), _ in out]
    assert len({id(m) for m in mods}) == 1, "the rule was loaded more than once"


def test_a_half_module_in_sys_modules_is_loaded_again():
    root = make_root(SLOW_RULE.format(delay=0))
    with on_root(root):
        half = types.ModuleType(sr.MODULE_NAME)
        half.__file__ = str(root / "shared" / "footage_licence.py")   # the right path, no body
        sys.modules[sr.MODULE_NAME] = half
        mod = sr.licence_rule()
        assert mod is not half and callable(getattr(mod, "licence_of", None)), mod
        why = sr.refusal("v1", CANDIDATE, ORIGINS)
        assert why and "not one this channel takes" in why, why


def test_a_rule_without_licence_of_gives_none_and_the_floor():
    old = "OWN_GRAPHIC = 'own_graphic'\n"           # an old copy: no licence_of
    with on_root(make_root(old)):
        assert sr.licence_rule() is None
        assert sr.MODULE_NAME not in sys.modules
        assert sr.refusal("v1", CANDIDATE, ORIGINS) is None     # not refused: the floor
        nc = {"licence": {"short_name": "CC BY-NC 4.0", "judged": False}}
        assert "NC / ND" in sr.refusal("v2", nc, ORIGINS)


def test_a_rule_that_raises_half_way_leaves_nothing_behind():
    broken = "def licence_of(*a, **k):\n    return {}\nraise RuntimeError('half way')\n"
    with on_root(make_root(broken)):
        out = run_threads(sr.licence_rule)
        assert all(m is None and e is None for m, e in out), out
        assert sr.MODULE_NAME not in sys.modules


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")
             and callable(v) and v.__module__ == __name__]
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
