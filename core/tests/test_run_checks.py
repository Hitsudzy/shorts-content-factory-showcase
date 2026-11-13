#!/usr/bin/env python3
"""CF-0203: the mechanical decisions the operator used to make by reading, as
commands of the run plan (`shared/run_checks.py`).

* `reserve_refill` (N > 0 refusals not refilled yet and M > 0 reserve left)
  over synthetic `03` / `01b` / `02` in a temporary batch - CF-0645: a slot
  the first round answered is not counted again in the late round;
* `captions-stale` / `captions-remeasure` over a stand-in `caption_cache.py`
  and `remeasure_captions.py` in a temporary indexer checkout - the stale list
  is taken by the command, not copied from a printed line; CF-0819: the
  remeasure is bounded, and past its ceiling or on a failure the stale crops
  are set aside (exit 6, ok for the plan with a note) - never exit 5;
* the plan names them: every named condition of `run_plan.CONDITIONS` has an
  evaluation, and ExampleFilm's pool-maintenance check and its handler call
  `run_checks.py`, the handler as a machine step.
"""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "shared"))
from _tmproot import tmp_root  # noqa: E402
import run_checks  # noqa: E402
import run_plan  # noqa: E402

TMP = tmp_root("run-checks-test-")
SCRIPT = ROOT / "shared" / "run_checks.py"
_N = [0]


def batch(skipped, remaining=None, index_batch=None, reserve02=None, scripts=None):
    _N[0] += 1
    b = TMP / "pipeline" / "example-film" / f"2026-10-0{_N[0] % 9 + 1}T00{_N[0]:02d}Z"
    b.mkdir(parents=True)
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"scripts": scripts or [], "skipped": [{"topic_id": t, "reason_code": "pool_too_thin"}
                                               for t in skipped]}))
    idx = {"batch": index_batch or str(b)}
    if remaining is not None:
        idx["reserve_substitution"] = {"remaining": remaining}
    (b / "01b-footage-index.json").write_text(json.dumps(idx))
    if reserve02 is not None:
        (b / "02-compliance-checker.json").write_text(json.dumps({"reserve": reserve02}))
    return b


def cli(*args):
    cp = subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                        capture_output=True, text=True, timeout=120)
    return cp.returncode, cp.stdout + cp.stderr


def test_reserve_refill_holds_when_refused_and_reserve_left():
    b = batch(["t1", "t2"], remaining=["r1"])
    holds, why = run_checks.reserve_refill(b)
    assert holds and "N=2" in why and "M=1" in why, why
    code, out = cli("reserve-refill", b)
    assert code == 0 and out.startswith("reserve_refill: yes"), out


def test_reserve_refill_not_without_refusals_or_reserve():
    assert not run_checks.reserve_refill(batch([], remaining=["r1"]))[0]
    assert not run_checks.reserve_refill(batch(["t1"], remaining=[]))[0]
    code, out = cli("reserve-refill", batch(["t1"], remaining=[]))
    assert code == 1 and "M=0" in out, out


def test_reserve_refill_reads_the_shelf_when_the_loop_never_ran():
    # no reserve_substitution block: 02 -> reserve[] minus what is indexed
    assert run_checks.reserve_refill(batch(["t1"], reserve02=["r1"]))[0]


def test_a_rerun_with_its_parents_index_refills_nothing():
    b = batch(["t1"], remaining=["r1"], index_batch="pipeline/example-film/PARENT")
    holds, why = run_checks.reserve_refill(b)
    assert not holds and "M=0" in why, why


def test_reserve_refill_without_03_is_no():
    b = TMP / "empty-batch"
    b.mkdir()
    assert run_checks.reserve_refill(b) == (False, "no 03-content-researcher.json: N unknown, "
                                                   "nothing to refill")


def test_reserve_refill_counts_only_the_slots_not_answered_yet():
    """CF-0645: the late round. `2026-10-08T1824Z` lost 001/004 to
    `plan_unassembled` after the supplement; asked there, the check sees two
    open slots. Once the indexer's `--reserve-for` answered them (a substitute
    or `reserve_exhausted`), the same refusals are not N again - a third ask
    over the same `03` is a no."""
    b = batch(["t1", "t4"], remaining=["r7", "r8", "r9"])
    holds, why = run_checks.reserve_refill(b)
    assert holds and why.startswith("N=2 refused, M=3"), why
    idx = json.loads((b / "01b-footage-index.json").read_text())
    idx["reserve_substitution"].update(
        substitutions=[{"replaced": "t1", "topic_id": "r7", "at": "researcher_refusal",
                        "outcome": "sources"}],
        unmatched=[{"replaced": "t4", "topic_id": None, "at": "researcher_refusal",
                    "reason_code": "reserve_exhausted"}],
        remaining=["r9"])
    (b / "01b-footage-index.json").write_text(json.dumps(idx))
    holds, why = run_checks.reserve_refill(b)
    assert not holds and why.startswith("N=0 refused (+2 already refilled), M=1"), why
    # The substitute itself refused in the round that brought it: its slot is open.
    cr = json.loads((b / "03-content-researcher.json").read_text())
    cr["skipped"].append({"topic_id": "r7", "reason_code": "plan_unassembled"})
    (b / "03-content-researcher.json").write_text(json.dumps(cr))
    holds, why = run_checks.reserve_refill(b)
    assert holds and why.startswith("N=1 refused (+2 already refilled), M=1"), why


def test_every_named_condition_has_an_evaluation():
    assert set(run_checks.CHECKS) == set(run_plan.CONDITIONS)


CACHE = '''
import json
from pathlib import Path
VALUE_KEY = "crop_bottom_cached"
SET_ASIDE_KEY = "crop_bottom_set_aside"
def _stale(s):
    return VALUE_KEY in s and s.get("stale")
def survey(paths):
    out = {}
    for p in paths:
        d = json.loads(Path(p).read_text())
        bad = [(s["index"], "old") for s in d["shots"] if _stale(s)]
        if bad:
            out[str(p)] = bad
    return out
def complaint(stale):
    return "caption-band cache is stale:\\n  remeasure_captions.py " + " ".join(sorted(stale))
def set_aside(path, dry_run=False):
    d = json.loads(Path(path).read_text())
    n = 0
    for s in d["shots"]:
        if _stale(s):
            s[SET_ASIDE_KEY] = {"value": s.pop(VALUE_KEY), "measured_by": "old"}
            del s["stale"]
            n += 1
    if n and not dry_run:
        Path(path).write_text(json.dumps(d))
    return n
def set_aside_warning(n, k):
    return f"WARNING caption-band cache: {n} stale crop(s) in {k} index(es) set aside"
'''
# CF-0819: the old pin - no set_aside.
OLD_CACHE = CACHE.split("def set_aside(")[0].replace("SET_ASIDE_KEY", "_OLD")
# A remeasure that records its argv and re-measures every stale shot it is given.
REMEASURE = '''
import sys, json
from pathlib import Path
Path(__file__).with_name("remeasured.json").write_text(json.dumps(sys.argv[1:]))
for p in [a for a in sys.argv[1:] if a.endswith(".shots.json")]:
    d = json.loads(Path(p).read_text())
    for s in d["shots"]:
        s.pop("stale", None)
    Path(p).write_text(json.dumps(d))
'''
# CF-0819: Tech 2026-10-20T0831Z - a remeasure that does not end in time.
HANGS = "import time\ntime.sleep(120)\n"
CRASHES = "import sys\nsys.exit(3)\n"


def indexer(remeasure=REMEASURE, cache=CACHE):
    d = TMP / f"fi{_N[0]}"
    _N[0] += 1
    (d / "scripts").mkdir(parents=True)
    (d / "scripts" / "caption_cache.py").write_text(cache)
    (d / "scripts" / "remeasure_captions.py").write_text(remeasure)
    pool = d / "pool"
    pool.mkdir()
    (pool / "a.shots.json").write_text(json.dumps(
        {"shots": [{"index": 1, "stale": True, "crop_bottom_cached": 900},
                   {"index": 2, "stale": True, "crop_bottom_cached": 880},
                   {"index": 3, "crop_bottom_cached": 870}]}))
    (pool / "b.shots.json").write_text(json.dumps({"shots": [{"index": 1, "crop_bottom_cached": 900}]}))
    return d, pool


def _load_cache(d):
    """The stand-in caption_cache of one temporary indexer, loaded under its own
    name - `caption_cache` in sys.modules is whichever checkout came first."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"cc_{d.name}", d / "scripts" / "caption_cache.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_captions_stale_is_an_exit_code():
    d, pool = indexer()
    code, out = cli("captions-stale", "--indexer-dir", d, pool / "a.shots.json", pool / "b.shots.json")
    assert code == 1 and "a.shots.json" in out and "b.shots.json" not in out, out
    code, out = cli("captions-stale", "--indexer-dir", d, pool / "b.shots.json")
    assert code == 0 and "current" in out, out


def test_captions_remeasure_takes_the_stale_list_itself():
    d, pool = indexer()
    code, out = cli("captions-remeasure", "--indexer-dir", d, pool / "a.shots.json",
                    pool / "b.shots.json")
    assert code == 0, out
    got = json.loads((d / "scripts" / "remeasured.json").read_text())
    # only the stale index, and never a bulk remeasure (CF-0819): stale shots
    # only, inside the budget, the rest set aside
    assert got == [str(pool / "a.shots.json"), "--stale-only", "--budget-seconds",
                   str(run_checks.REMEASURE_BUDGET), "--set-aside-rest"], got
    d2, pool2 = indexer()
    code, out = cli("captions-remeasure", "--indexer-dir", d2, pool2 / "b.shots.json")
    assert code == 0 and not (d2 / "scripts" / "remeasured.json").exists()


def test_the_remeasure_is_bounded_well_under_the_old_two_hours():
    assert run_checks.REMEASURE_BUDGET <= 300
    assert run_checks.REMEASURE_BUDGET < run_checks.REMEASURE_TIMEOUT <= 600


def test_a_remeasure_past_its_ceiling_sets_the_stale_aside_and_the_batch_goes_on():
    """CF-0819, Tech 2026-10-20T0831Z: the remeasure ran past its ceiling,
    run_checks exited 5 and the batch lost every topic. Now the child is
    stopped, what is still stale is set aside (not erased, not measured), the
    exit says so (6, ok for the plan) and the rerun of captions-stale is 0."""
    d, pool = indexer(remeasure=HANGS)
    cc = _load_cache(d)
    stale = cc.survey([pool / "a.shots.json", pool / "b.shots.json"])
    t0 = __import__("time").monotonic()
    code = run_checks.captions_remeasure(cc, d, stale, budget=1, timeout=1)
    assert __import__("time").monotonic() - t0 < 60
    assert code == run_checks.SET_ASIDE_EXIT == 6, code
    shots = json.loads((pool / "a.shots.json").read_text())["shots"]
    assert [s.get("crop_bottom_set_aside", {}).get("value") for s in shots] == [900, 880, None]
    assert shots[2]["crop_bottom_cached"] == 870               # a current crop is not touched
    code, out = cli("captions-stale", "--indexer-dir", d, pool / "a.shots.json", pool / "b.shots.json")
    assert code == 0 and "current" in out, out


def test_a_remeasure_that_fails_sets_the_stale_aside_loudly():
    d, pool = indexer(remeasure=CRASHES)
    code, out = cli("captions-remeasure", "--indexer-dir", d, pool / "a.shots.json")
    assert code == 6, out
    assert "exited 3" in out and "WARNING caption-band cache: 2 stale crop(s) in 1 index(es)" in out, out
    code, out = cli("captions-stale", "--indexer-dir", d, pool / "a.shots.json")
    assert code == 0, out


def test_a_dry_run_sets_nothing_aside():
    d, pool = indexer(remeasure=CRASHES)
    before = (pool / "a.shots.json").read_text()
    code, out = cli("captions-remeasure", "--indexer-dir", d, "--dry-run", pool / "a.shots.json")
    assert (pool / "a.shots.json").read_text() == before, out


def test_an_indexer_pinned_before_cf0819_is_a_clear_refusal():
    d, pool = indexer(cache=OLD_CACHE)
    code, out = cli("captions-remeasure", "--indexer-dir", d, pool / "a.shots.json")
    assert code == 2 and "predates CF-0819" in out and "Traceback" not in out, out
    assert not (d / "scripts" / "remeasured.json").exists()


def test_the_example_film_plan_calls_them():
    plan = run_plan.load("example-film", ROOT)
    by = {s["id"]: s for s in plan["stages"]}
    first = by["pool-maintenance"]["steps"][0]
    assert first["argv"][1:3] == ["{root}/shared/run_checks.py", "captions-stale"]
    assert first["on_exit"]["1"] == {**first["on_exit"]["1"], "run": "pool-remeasure-captions",
                                     "then": "rerun"}
    h = by["pool-remeasure-captions"]
    assert h["kind"] == "machine" and h["steps"][0]["argv"][2] == "captions-remeasure"
    assert {"check": "reserve_refill"} in by["footage-indexer-reserve"]["when"]


def test_every_plan_takes_a_set_aside_as_ok_with_a_note():
    """CF-0819: exit 6 of captions-remeasure (stale crops set aside) closes the
    handler, and its note lands in pool-maintenance's stage-done."""
    for ch in ("example-film", "example-tech", "example-science"):
        by = {s["id"]: s for s in run_plan.load(ch, ROOT)["stages"]}
        step = by["pool-remeasure-captions"]["steps"][0]
        assert step["argv"][2] == "captions-remeasure", ch
        assert set(step["ok_exit"]) == {0, run_checks.SET_ASIDE_EXIT}, ch
        assert "set aside" in step["note_on_exit"][str(run_checks.SET_ASIDE_EXIT)], ch


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
