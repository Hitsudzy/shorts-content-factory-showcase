#!/usr/bin/env python3
"""CF-0107, Compliance Checker part: `check_contribution.py` writes `start`
and `done`/`failed` events to the batch's RUN_EVENTS.jsonl through the
root's shared/runlog library (found by the `scripts/_runlog.py` shim), and
with no batch to write to nothing is written and the script behaves exactly
as before. The check is pure Python over stance.json - no binary, no model -
so there are no `child` events to look for; the script event is the record.

Everything runs offline on synthetic Content Researcher JSON. Seconds.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SCRIPTS = REPO / "scripts"
SCRIPT = SCRIPTS / "check_contribution.py"
sys.path.insert(0, str(SCRIPTS))

from _tmproot import tmp_root  # noqa: E402  CF-0489: removed at exit
TMP = tmp_root("cc-runlog-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")   # never touch ~/.shorts-content-factory
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import _runlog  # noqa: E402

PY = sys.executable
CHANNEL = "example-film"

# A script carrying a real production fact (CF-0187): concrete - a name and a
# number - absent from the story it is added to, and sourced to a link that is
# not the story's own. Passes -> exit 0.
_BEAT = ("Kaufman shot the kitchen argument forty-one times before he kept "
         "a take.")
PASSING = {"channel": CHANNEL, "scripts": [{
    "script_id": "s-pass",
    "hook": "The trailer promised a slow-burn thriller.",
    "commentary": f"The trailer promised a slow burn. {_BEAT} That is the "
                  f"scene the whole picture turns on.",
    "payoff": "Slow burn, forty-one times over.",
    "production_fact": {
        "text": "Kaufman shot the kitchen argument forty-one times before he "
                "kept a take.",
        "beat_text": _BEAT,
        "source_url": "https://example.org/kaufman/production#filming",
        "on_screen": "41 takes of the kitchen argument",
    },
}]}

# The same script with the fact replaced by a general phrase of the kind the
# stance names ("the shoot was difficult") -> fact_not_concrete -> block ->
# exit 1.
BLOCKING = {"channel": CHANNEL, "scripts": [{
    "script_id": "s-block",
    "hook": "The trailer promised a slow-burn thriller.",
    "commentary": "The trailer promised a slow burn. The shoot was difficult. "
                  "That is the scene the whole picture turns on.",
    "payoff": "Slow burn, and a hard one.",
    "production_fact": {
        "text": "The shoot was difficult and the cast found it demanding.",
        "beat_text": "The shoot was difficult.",
        "source_url": "https://example.org/kaufman/production#filming",
        "on_screen": None,
    },
}]}


def _events(batch):
    path = batch / "RUN_EVENTS.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _fresh_batch(name, payload):
    b = TMP / name
    b.mkdir(parents=True, exist_ok=True)
    cr = b / "03-content-researcher.json"
    cr.write_text(json.dumps(payload))
    return b, cr


def _run(args, batch=None, cwd=None):
    """check_contribution.py as the skill runs it: a fresh interpreter,
    RUNLOG_BATCH in the environment (or not)."""
    env = {k: v for k, v in os.environ.items() if k not in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    if batch is not None:
        env["RUNLOG_BATCH"] = str(batch)
    return subprocess.run([PY, str(SCRIPT), *args], env=env, cwd=cwd,
                          capture_output=True, text=True, timeout=60)


# --------------------------------------------------------------------------
# the shim
# --------------------------------------------------------------------------

def test_shim_resolves_the_root_from_inside_this_checkout():
    """The ancestor walk finds shared/runlog/runlog.py whether this repo is the
    normal agents/compliance-checker checkout or a worktree under .claude/worktrees/."""
    root = _runlog.factory_root()
    assert (root / "shared" / "runlog" / "runlog.py").is_file(), root
    assert (root / "README.md").is_file() and (root / "channels").is_dir(), \
        f"{root} is not the factory root"
    assert REPO.resolve().is_relative_to(root), (REPO, root)
    assert Path(_runlog.runlog.__file__).resolve() == (root / "shared" / "runlog" / "runlog.py").resolve()
    assert hasattr(_runlog.runlog, "script") and hasattr(_runlog.runlog, "child")


def test_shim_honours_factory_root_and_survives_a_missing_root():
    code = "import _runlog, sys; print(_runlog.factory_root()); print(type(_runlog.runlog).__name__)"
    env = dict(os.environ, FACTORY_ROOT=str(_runlog.factory_root()), PYTHONPATH=str(SCRIPTS))
    cp = subprocess.run([PY, "-c", code], env=env, capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0, cp.stderr
    lines = cp.stdout.split()
    assert lines[0] == str(_runlog.factory_root()) and lines[1] == "module", cp.stdout

    # A copy of scripts/ outside the factory: the stand-in, one warning, no crash.
    orphan = TMP / "orphan"
    orphan.mkdir(exist_ok=True)
    (orphan / "_runlog.py").write_bytes((SCRIPTS / "_runlog.py").read_bytes())
    env = {k: v for k, v in os.environ.items() if k != "FACTORY_ROOT"}
    env["PYTHONPATH"] = str(orphan)
    cp = subprocess.run([PY, "-c", code.replace("print(_runlog.factory_root()); ", "")],
                        env=env, cwd=str(orphan), capture_output=True, text=True, timeout=30)
    assert cp.returncode == 0 and cp.stdout.strip() == "_Silent", (cp.stdout, cp.stderr)
    assert "factory root not found" in cp.stderr


# --------------------------------------------------------------------------
# events with a batch
# --------------------------------------------------------------------------

def test_passing_run_writes_start_and_done_with_stage_step_params():
    batch, cr = _fresh_batch("pass", PASSING)
    cp = _run([str(cr), CHANNEL], batch=batch)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "s-pass: pass" in cp.stdout and "1 script(s), 0 blocked" in cp.stdout, cp.stdout
    assert "[runlog]" not in cp.stderr, cp.stderr

    events = _events(batch)
    assert [(e["kind"], e["status"]) for e in events] == [("script", "start"), ("script", "done")], events
    start, done = events
    assert start["id"] == done["id"] and start["pid"] == done["pid"] != os.getpid()
    for e in events:
        assert e["stage"] == "compliance-checker" and e["step"] == "check-contribution", e
        assert e["name"] == "check_contribution.py", e
        assert e["ts"].endswith("Z")
        assert e["params"] == {"args": [str(cr), CHANNEL]}, e["params"]
    assert start["duration_s"] is None and isinstance(done["duration_s"], (int, float))
    assert done.get("error") in (None, ""), done
    assert not [e for e in events if e["kind"] == "child"], "no binary, no model: no child events"


def test_blocked_run_exits_1_and_is_recorded_as_failed():
    batch, cr = _fresh_batch("block", BLOCKING)
    cp = _run([str(cr)], batch=batch)            # channel taken from the file
    assert cp.returncode == 1, (cp.returncode, cp.stdout, cp.stderr)
    assert "s-block: block" in cp.stdout and "1 blocked" in cp.stdout, cp.stdout
    events = _events(batch)
    assert [e["status"] for e in events] == ["start", "failed"], events
    assert events[1]["error"] == "SystemExit: 1", events[1]
    assert events[0]["params"] == {"args": [str(cr)]}, events[0]["params"]
    assert events[0]["step"] == events[1]["step"] == "check-contribution"


def test_usage_error_exits_2_and_is_recorded_as_failed():
    batch, _ = _fresh_batch("usage", PASSING)
    cp = _run([], batch=batch)
    assert cp.returncode == 2, (cp.returncode, cp.stderr)
    assert "usage:" in cp.stdout
    events = _events(batch)
    assert [e["status"] for e in events] == ["start", "failed"], events
    assert events[1]["error"] == "SystemExit: 2" and events[0]["params"] is None, events


def test_two_runs_in_one_batch_append_in_order():
    """The skill runs the script once per pass; a second run appends after the
    first rather than truncating the file or sharing an id."""
    batch, cr = _fresh_batch("twice", PASSING)
    assert _run([str(cr)], batch=batch).returncode == 0
    assert _run([str(cr)], batch=batch).returncode == 0
    events = _events(batch)
    assert [e["status"] for e in events] == ["start", "done", "start", "done"], events
    assert events[0]["id"] == events[1]["id"] != events[2]["id"] == events[3]["id"]
    assert events[0]["ts"] <= events[2]["ts"]


# --------------------------------------------------------------------------
# no batch: nothing written, same behaviour
# --------------------------------------------------------------------------

def test_without_a_batch_nothing_is_written_and_the_output_is_the_same():
    batch, cr = _fresh_batch("compare", PASSING)
    ref = _run([str(cr), CHANNEL], batch=batch)
    assert ref.returncode == 0 and _events(batch)

    # The input file lives outside any batch dir and cwd is nowhere in
    # particular, so the library's own lookup finds nothing either.
    nowhere = TMP / "nowhere" / "deeper"
    nowhere.mkdir(parents=True, exist_ok=True)
    loose = TMP / "nowhere" / "cr.json"
    loose.write_text(json.dumps(PASSING))
    cp = _run([str(loose), CHANNEL], batch=None, cwd=str(nowhere))
    assert cp.returncode == 0, cp.stderr
    assert cp.stdout == ref.stdout, (cp.stdout, ref.stdout)
    assert "no batch dir" in cp.stderr, cp.stderr                # says so, does not raise
    stray = (list((TMP / "nowhere").rglob("RUN_EVENTS.jsonl")) + list(REPO.glob("RUN_EVENTS.jsonl"))
             + list(SCRIPTS.glob("RUN_EVENTS.jsonl")) + list(HERE.glob("RUN_EVENTS.jsonl")))
    assert not stray, stray

    # Blocking is still exit 1 without a batch - accounting changes nothing.
    loose_b = TMP / "nowhere" / "cr-block.json"
    loose_b.write_text(json.dumps(BLOCKING))
    cp = _run([str(loose_b)], batch=None, cwd=str(nowhere))
    assert cp.returncode == 1 and "s-block: block" in cp.stdout, (cp.returncode, cp.stdout)
    assert "RUNLOG_BATCH" not in os.environ and "RUNLOG_PARENT" not in os.environ


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
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
