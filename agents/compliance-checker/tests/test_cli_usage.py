#!/usr/bin/env python3
"""CF-0777: every command line the skill names answers `--help` with its usage
and exit 0, and refuses an option it does not know with a usage error (exit 2)
- never a traceback, never a file named `--help`.

The crash this pins: the stage operator of `example-tech/2026-10-16T0839Z`
asked `check_contribution.py --help` how it is called, and the script opened
`--help` as the batch file (`FileNotFoundError: [Errno 2] No such file or
directory: '--help'`, a `failed` event at 2026-10-16T17:10:59Z). The call
forms the skill uses - `<file>`, `<file> <channel>`, `... --dry-run`,
`publication_hold.py --sign ... --note N` - keep working.

Offline: synthetic batch files under a temp root, no RUNLOG_BATCH unless a
test sets one to its own temp batch. Seconds.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cc-cli-usage-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

from _cli import screen  # noqa: E402
from test_runlog_events import BLOCKING, CHANNEL, PASSING  # noqa: E402

PY = sys.executable

# Every script the skill tells the stage operator to run (SKILL.md), plus the
# retired blooper_relaxation.py, which is still a command line in the repo.
SCRIPT_NAMES = ("check_contribution.py", "rights_holder_info.py", "cut_shortlist.py",
                "publication_hold.py", "check_claims_gate.py", "blooper_relaxation.py",
                "merge_verdicts.py", "sensitivity_scenes.py",
                "judge_below_shortlist.py")    # CF-0882: run by the root's refill round


def _run(name, *args, batch=None):
    env = {k: v for k, v in os.environ.items() if k not in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    if batch is not None:
        env["RUNLOG_BATCH"] = str(batch)
    return subprocess.run([PY, str(SCRIPTS / name), *args], env=env, cwd=str(TMP),
                          capture_output=True, text=True, timeout=60)


def _batch(name, payload):
    b = TMP / name
    b.mkdir(parents=True, exist_ok=True)
    cr = b / "03-content-researcher.json"
    cr.write_text(json.dumps(payload))
    return b, cr


def _no_traceback(cp):
    assert "Traceback" not in cp.stderr and "Error:" not in cp.stderr.replace(
        "error: unrecognized", ""), cp.stderr


# --------------------------------------------------------------------------
# --help / -h
# --------------------------------------------------------------------------

def test_every_script_answers_help_with_its_usage_and_exit_0():
    for name in SCRIPT_NAMES:
        for flag in ("--help", "-h"):
            cp = _run(name, flag)
            assert cp.returncode == 0, (name, flag, cp.returncode, cp.stdout, cp.stderr)
            assert "usage:" in cp.stdout and name in cp.stdout, (name, flag, cp.stdout)
            _no_traceback(cp)


def test_help_beside_a_real_file_reads_and_writes_nothing():
    _, cr = _batch("help-beside", BLOCKING)
    before = cr.read_bytes()
    for name in ("check_contribution.py", "rights_holder_info.py",
                 "publication_hold.py", "cut_shortlist.py", "blooper_relaxation.py"):
        cp = _run(name, str(cr), str(cr), "--help")
        assert cp.returncode == 0, (name, cp.returncode, cp.stdout, cp.stderr)
        assert "usage:" in cp.stdout, (name, cp.stdout)
        assert "blocked" not in cp.stdout and "row(s)" not in cp.stdout, (name, cp.stdout)
        assert cr.read_bytes() == before, name


def test_the_crash_itself_help_is_a_done_event_not_a_failed_one():
    """The 17:10:59Z call, as it was made: RUNLOG_BATCH set, `--help` alone."""
    batch, _ = _batch("help-runlog", PASSING)
    cp = _run("check_contribution.py", "--help", batch=batch)
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "FileNotFoundError" not in cp.stderr, cp.stderr
    events = [json.loads(line) for line in
              (batch / "RUN_EVENTS.jsonl").read_text().splitlines() if line.strip()]
    assert [e["status"] for e in events] == ["start", "done"], events
    assert all(e.get("error") in (None, "") for e in events), events


# --------------------------------------------------------------------------
# an unknown option
# --------------------------------------------------------------------------

def test_every_script_refuses_an_unknown_option_with_a_usage_error():
    _, cr = _batch("unknown", PASSING)
    before = cr.read_bytes()
    for name in SCRIPT_NAMES:
        for args in (("--bogus",), (str(cr), "--bogus"), (str(cr), CHANNEL, "-x")):
            cp = _run(name, *args)
            assert cp.returncode == 2, (name, args, cp.returncode, cp.stdout, cp.stderr)
            # argparse (check_claims_gate.py) words a lone `--bogus` as a
            # missing argument; either way it is a usage error on stderr.
            assert "usage:" in cp.stderr and "error:" in cp.stderr, (name, args, cp.stderr)
            if name != "check_claims_gate.py" or len(args) > 1:
                assert "unrecognized" in cp.stderr, (name, args, cp.stderr)
            assert "Traceback" not in cp.stderr, (name, args, cp.stderr)
        assert cr.read_bytes() == before, name


def test_check_contribution_names_the_bad_option_and_a_missing_file_is_not_a_traceback():
    cp = _run("check_contribution.py", "--verbose")
    assert cp.returncode == 2 and "'--verbose'" in cp.stderr, (cp.returncode, cp.stderr)
    cp = _run("check_contribution.py", str(TMP / "no-such-03.json"))
    assert cp.returncode == 2, (cp.returncode, cp.stdout, cp.stderr)
    assert "cannot read the batch" in cp.stdout and "Traceback" not in cp.stderr, cp


# --------------------------------------------------------------------------
# the call forms that were already in use
# --------------------------------------------------------------------------

def test_check_contribution_call_forms_still_work():
    _, ok = _batch("form-pass", PASSING)
    _, bad = _batch("form-block", BLOCKING)
    cp = _run("check_contribution.py", str(ok))                 # SKILL.md, the runner
    assert cp.returncode == 0 and "s-pass: pass" in cp.stdout, (cp.stdout, cp.stderr)
    cp = _run("check_contribution.py", str(ok), CHANNEL)        # with the channel
    assert cp.returncode == 0 and "1 script(s), 0 blocked" in cp.stdout, (cp.stdout, cp.stderr)
    cp = _run("check_contribution.py", str(bad))                # a block is exit 1
    assert cp.returncode == 1 and "s-block: block" in cp.stdout, (cp.stdout, cp.stderr)
    cp = _run("check_contribution.py")                           # no file: usage, 2
    assert cp.returncode == 2 and "usage:" in cp.stdout, (cp.stdout, cp.stderr)


def test_publication_hold_option_values_are_not_taken_for_options():
    """`--note` / `--user` / `--date` / `--via` / `--root` take the next
    argument as their value, whatever it starts with."""
    flags = ("--dry-run", "--check", "--sign", "--resolve-rights-only", "--list")
    valued = ("--root", "--date", "--user", "--note", "--via")
    argv = ["--sign", "ch/b/t", "--user", "K", "--note", "-- signed, see -h",
            "--via", "cli", "--date", "2026-10-16", "--root", "-tmp", "--dry-run"]
    assert screen(argv, "usage: publication_hold.py ...", flags=flags, valued=valued) is None
    cp = _run("publication_hold.py", "--sign", "ch/b/t", "--user", "K", "--note",
              "-not an option", "--root", str(TMP / "ledger-root"), "--dry-run")
    assert cp.returncode != 2 and "unrecognized" not in cp.stderr, (cp.returncode, cp.stdout,
                                                                       cp.stderr)
    assert not (TMP / "ledger-root" / "publish").exists()


def test_screen_passes_positionals_known_flags_and_a_lone_dash():
    assert screen(["a.json", "example-tech", "--dry-run"], "usage: x.py",
                  flags=("--dry-run",)) is None
    assert screen(["-"], "usage: x.py") is None
    assert screen([], "usage: x.py") is None


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
