#!/usr/bin/env python3
"""CF-0478: the sieve-flag answerer of a run, `scripts/sieve_answer_claude.py`,
on a stub in place of `claude` - no test here calls a model.

Pinned: the call is the checked one-off's (`-p --model <model>`, Read/Write,
the answers', questions' and sheet's folders added, acceptEdits) and its
prompt names `screen_recording`; the log lands beside the answers; answers
that do not cover the questions fail the source; a console claude with no
session exits with `NOT_LOGGED_IN` and asks the journal of questions exactly
one question however many sources fail on it (CF-0652), the next call claude
answers resolves it, a root without the journal is a log line and not a
failure; the ceiling kills claude's whole
process group; and, end to end, the command the channel config will carry
(`{python} {scripts}/sieve_answer_claude.py ...`) marks a batch source through
`backfill_sieve_flags.backfill_batch`, while a logged-out claude leaves the
source out with a record and the sieve's summary line says why.

The journal and the notification bus are a temp directory of each test
(`NEEDS_YOU_DIR`, `NOTIFY_STATE_DIR`, `NOTIFY_BACKENDS=log` - no Telegram, no
network); the in-process tests hand the journal a stub notifier.

No pytest dependency - plain asserts, run directly.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import backfill_sieve_flags as bf        # noqa: E402
import sieve_answer_claude as sac        # noqa: E402
import source_sieve as sv                # noqa: E402
from test_backfill_sieve_flags import (  # noqa: E402
    batch_report, fake_sheet, pool)

ANSWERER = SCRIPTS / "sieve_answer_claude.py"
MODE_ENV = "STUB_CLAUDE_MODE"
# CF-0649: the "hang" mode's timings. Under load (15-20) starting the stub's
# Python, importing, spawning the grandchild and writing its pid costs seconds;
# a 2 s ceiling killed the stub before child.pid existed. The ceiling is now
# wide enough for that, and the elapsed bound stays below HANG_SECONDS, so an
# answerer that does not kill the group (and waits the hang out) is still red.
HANG_CEILING_SECONDS = 15
HANG_SECONDS = 180
HANG_ELAPSED_BOUND_SECONDS = 90
GONE_WAIT_SECONDS = 15   # a killed grandchild may take a moment to exit
ARGV_ENV = "STUB_CLAUDE_ARGV"

# The stub: reads the answers path and the shots out of the prompt and the
# questions file, the way the real model is told to, and behaves per mode.
STUB = r'''#!{python}
import json, os, re, subprocess, sys, time
argv = sys.argv[1:]
rec = os.environ.get("{argv_env}")
if rec:
    open(rec, "w").write(json.dumps(argv))
mode = os.environ.get("{mode_env}", "ok")
prompt = argv[-1]
qpath = re.search(r"questions file (\S+) ", prompt).group(1)
apath = re.search(r"JSON file (\S+) in the form", prompt).group(1)
q = json.load(open(qpath))
if mode == "logged_out":
    print("OAuth token has expired. Please run /login")
    sys.exit(1)
if mode == "boom":
    print("something else broke")
    sys.exit(2)
if mode == "hang":
    child = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep({hang})"])
    pid_file = os.environ["STUB_CHILD_PID"]
    open(pid_file + ".tmp", "w").write(str(child.pid))
    os.replace(pid_file + ".tmp", pid_file)
    time.sleep({hang})
shots = q["shots"] if mode != "partial" else q["shots"][:1]
json.dump({{"video_id": q["video_id"], "answers": [
    {{"index": s["index"], "burned_text": False, "on_topic": True,
      "screen_recording": False}} for s in shots]}}, open(apath, "w"))
print("done")
'''


def stub(tmp):
    p = Path(tmp) / "claude"
    p.write_text(STUB.format(python=sys.executable, argv_env=ARGV_ENV,
                             mode_env=MODE_ENV, hang=HANG_SECONDS))
    p.chmod(0o755)
    return p


def questions(tmp, vid="vid1", n=3, both=True):
    d = Path(tmp) / "out"
    d.mkdir(exist_ok=True)
    q = {"video_id": vid, "both_flags_required": both,
         "shots": [{"index": i} for i in range(n)]}
    path = d / f"{vid}{bf.QUESTIONS_SUFFIX}"
    path.write_text(json.dumps(q))
    return path, d / f"{vid}.sheet.jpg", d / f"{vid}{bf.ANSWERS_SUFFIX}"


def journal_env(tmp):
    """The journal of questions and the bus, inside the test's temp dir."""
    return {"NEEDS_YOU_DIR": str(Path(tmp) / "needs-you"),
            "NOTIFY_STATE_DIR": str(Path(tmp) / "notify"),
            "NOTIFY_BACKENDS": "log"}


@contextmanager
def isolated(tmp):
    """os.environ with journal_env(tmp) - for the answerer the indexer runs
    through the shell (it inherits this process's environment)."""
    new = journal_env(tmp)
    old = {k: os.environ.get(k) for k in new}
    os.environ.update(new)
    try:
        yield
    finally:
        for k, v in old.items():
            os.environ.pop(k, None) if v is None else os.environ.update({k: v})


def asked(tmp, status="all"):
    """The answerer's questions in the test's journal."""
    mod, why = sac.needs_you_module()
    assert mod is not None, why
    return [q for q in mod.questions(status=status,
                                     directory=Path(tmp) / "needs-you")
            if q["key"] == sac.NEEDS_YOU_KEY]


def run(tmp, mode, extra=(), vid="vid1"):
    qp, sheet, ans = questions(tmp, vid=vid)
    env = dict(os.environ, **journal_env(tmp), **{MODE_ENV: mode,
                              ARGV_ENV: str(Path(tmp) / "argv.json"),
                              "STUB_CHILD_PID": str(Path(tmp) / "child.pid")})
    r = subprocess.run(
        [sys.executable, str(ANSWERER), "--questions", str(qp), "--sheet",
         str(sheet), "--answers", str(ans), "--video-id", vid, "--claude",
         str(stub(tmp)), *extra],
        env=env, capture_output=True, text=True,
        timeout=HANG_SECONDS - 30)
    return r, ans


def test_the_call_is_the_checked_one_and_the_answers_land_with_a_log():
    with tempfile.TemporaryDirectory() as tmp:
        r, ans = run(tmp, "ok", extra=("--model", "haiku"))
        assert r.returncode == sac.EXIT_OK, r.stderr
        doc = json.loads(ans.read_text())
        assert [a["index"] for a in doc["answers"]] == [0, 1, 2]
        log = ans.parent / f"vid1{sac.LOG_SUFFIX}"
        assert log.exists() and "done" in log.read_text()
        argv = json.loads((Path(tmp) / "argv.json").read_text())
        assert argv[:3] == ["-p", "--model", "haiku"], argv
        assert argv[argv.index("--allowedTools") + 1:][:2] == ["Read", "Write"]
        assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
        assert str(ans.parent) in argv
        assert "screen_recording" in argv[-1] and "vid1" in argv[-1]


def test_answers_that_miss_a_shot_fail_the_source():
    with tempfile.TemporaryDirectory() as tmp:
        r, _ = run(tmp, "partial")
        assert r.returncode == sac.EXIT_BAD_ANSWERS, (r.returncode, r.stderr)
        assert "2 listed shot(s) unanswered" in r.stderr


def test_not_logged_in_is_one_question_and_a_working_answer_resolves_it():
    with tempfile.TemporaryDirectory() as tmp:
        for vid in ("vid1", "vid2"):
            r, _ = run(tmp, "logged_out", vid=vid)
            assert r.returncode == sac.EXIT_NOT_LOGGED_IN, r.stderr
            assert sac.NOT_LOGGED_IN in r.stderr.strip().splitlines()[-1]
        qs = asked(tmp)
        assert len(qs) == 1 and qs[0]["status"] == "open", qs
        q, = qs
        assert q["source"] == sac.NEEDS_YOU_SOURCE
        assert "/login" in q["text"] and "vid" not in q["text"], q["text"]
        # one source after another does not reword it: one `add`, no `text` op
        ops = (Path(tmp) / "needs-you" / "questions.jsonl").read_text()
        assert len(ops.splitlines()) == 1, ops
        # the bus was told once (the log backend - nothing leaves the machine)
        sent = (Path(tmp) / "notify").glob("*.jsonl")
        rows = [ln for f in sent for ln in f.read_text().splitlines()
                if f"needs-you:{q['id']}" in ln]
        assert len(rows) == 1, rows
        r, _ = run(tmp, "ok")
        assert r.returncode == 0, r.stderr
        q, = asked(tmp)
        assert q["status"] == "resolved" and q["resolved_by"] == \
            sac.NEEDS_YOU_SOURCE, q
        # the next logout asks anew
        r, _ = run(tmp, "logged_out")
        assert [q["status"] for q in asked(tmp)] == ["resolved", "open"]


def test_another_failure_is_not_a_login_question():
    with tempfile.TemporaryDirectory() as tmp:
        r, _ = run(tmp, "boom")
        assert r.returncode == sac.EXIT_CLAUDE_FAILED, r.stderr
        assert asked(tmp) == []


def test_answers_claude_wrote_short_still_resolve_the_login():
    """Exit 0 means claude had a session: the question goes even when the
    answers fail the source for another reason."""
    with tempfile.TemporaryDirectory() as tmp:
        run(tmp, "logged_out")
        r, _ = run(tmp, "partial")
        assert r.returncode == sac.EXIT_BAD_ANSWERS, r.stderr
        assert [q["status"] for q in asked(tmp)] == ["resolved"]


def test_remind_and_clear_in_process_with_a_stub_notifier():
    mod, why = sac.needs_you_module()
    assert mod is not None, why
    with tempfile.TemporaryDirectory() as tmp:
        told = []
        kw = {"directory": tmp, "notifier": told.append}
        q1 = sac.remind(module=mod, **kw)
        q2 = sac.remind(module=mod, **kw)
        assert q1["id"] == q2["id"] and len(told) == 1, told
        done = sac.clear_reminder("v9", module=mod, directory=tmp)
        assert [q["id"] for q in done] == [q1["id"]]
        assert done[0]["note"] == "claude answered v9"
        assert sac.clear_reminder("v9", module=mod, directory=tmp) == []


def test_a_root_without_the_journal_is_a_log_line_not_a_failure():
    with tempfile.TemporaryDirectory() as tmp:
        mod, why = sac.needs_you_module(roots=[tmp])
        assert mod is None and "needs_you.py" in why, why
        log = Path(tmp) / "a.log"
        real = sac.needs_you_module
        sac.needs_you_module = lambda roots=None: (None, why)
        try:
            assert sac.remind(log) is None
            assert sac.clear_reminder("v", log) == []
        finally:
            sac.needs_you_module = real
        text = log.read_text()
        assert "the login question was not asked" in text and why in text
        assert "not resolved" not in text   # a working answer stays silent


def test_the_answerer_names_no_vault_note():
    """CF-0652: the old note is gone from the answerer - path, env and flag."""
    text = ANSWERER.read_text(encoding="utf-8")
    for word in ("Notebook", "NEEDS-YOU.md", "SIEVE_ANSWERER_NEEDS_YOU",
                 "--needs-you"):
        assert word not in text, word


def test_the_ceiling_kills_the_whole_process_group():
    with tempfile.TemporaryDirectory() as tmp:
        t0 = time.monotonic()
        r, _ = run(tmp, "hang",
                   extra=("--timeout", str(HANG_CEILING_SECONDS)))
        elapsed = time.monotonic() - t0
        assert r.returncode == sac.EXIT_TIMEOUT, r.stderr
        assert elapsed < HANG_ELAPSED_BOUND_SECONDS, elapsed
        pid_file = Path(tmp) / "child.pid"
        assert pid_file.exists(), (
            f"the stub never spawned its grandchild within the "
            f"{HANG_CEILING_SECONDS}s ceiling - the machine is too loaded "
            f"for this test, not a verdict on the ceiling")
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + GONE_WAIT_SECONDS
        while True:
            alive = _alive(pid)
            if not alive or time.monotonic() > deadline:
                break
            time.sleep(0.2)
        assert not alive, f"grandchild {pid} outlived the ceiling"


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie reparented to init is gone for our purposes
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                        capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


# The command the channel config will carry - see the report of CF-0478.
CONFIG_CMD = ("{python} {scripts}/sieve_answer_claude.py --questions "
              "{questions} --sheet {sheet} --answers {answers} --video-id "
              "{video_id}")


def test_the_config_command_marks_a_batch_source_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        cmd = CONFIG_CMD + f" --claude {stub(tmp)}"
        old = os.environ.get(MODE_ENV)
        os.environ[MODE_ENV] = "ok"
        try:
            with isolated(tmp):
                block = bf.backfill_batch(
                    batch_report(), Path(tmp) / "out", footage, pipeline,
                    answer_cmd=cmd, make_sheet=fake_sheet(footage, pipeline))
        finally:
            os.environ.pop(MODE_ENV) if old is None else os.environ.update(
                {MODE_ENV: old})
        assert block["answered"] == ["old"], block
        data = json.loads((footage / "old.shots.json").read_text())
        assert all(s["burned_text"] is False and s["on_topic"] is True
                   for s in data["shots"])
        line = sv.answers_summary_line(
            block, answerer={"command": cmd, "from": sv.ANSWER_FROM_CONFIG})
        assert "1 of 1 source(s) marked" in line, line
        assert "answerer `sieve_answer_claude.py` from " in line, line
        assert sv.ANSWER_FROM_CONFIG in line and "not logged in" not in line
        assert asked(tmp) == []


def test_a_logged_out_claude_takes_the_source_out_and_the_line_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        footage, pipeline = pool(tmp)
        cmd = CONFIG_CMD + f" --claude {stub(tmp)}"
        old = os.environ.get(MODE_ENV)
        os.environ[MODE_ENV] = "logged_out"
        try:
            with isolated(tmp):
                block = bf.backfill_batch(
                    batch_report(), Path(tmp) / "out", footage, pipeline,
                    answer_cmd=cmd, make_sheet=fake_sheet(footage, pipeline))
        finally:
            os.environ.pop(MODE_ENV) if old is None else os.environ.update(
                {MODE_ENV: old})
        rec, = block["sources"]
        assert rec["ok"] is False and sac.NOT_LOGGED_IN in rec["error"], rec
        assert sv.not_logged_in(block) == ["old"]
        line = sv.answers_summary_line(
            block, answerer={"command": cmd, "from": sv.ANSWER_FROM_CONFIG},
            taken=["old"])
        assert "0 of 1 source(s) marked" in line, line
        assert "console claude is not logged in" in line, line
        assert "journal of questions asks for a login" in line, line
        assert [q["status"] for q in asked(tmp)] == ["open"]


def test_placeholders_python_and_scripts_are_this_checkout():
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "said.txt"
        cmd = (f"{sys.executable} -c 'import sys; open(sys.argv[3], \"w\")"
               f".write(sys.argv[1] + \"|\" + sys.argv[2]); "
               f"open(sys.argv[4], \"w\").write(\"x\")' {{python}} {{scripts}} "
               f"{out} {{answers}}")
        bf.answer_by_cmd(cmd, {"video_id": "v", "sheet": None},
                         Path(tmp) / "v.answers.json")
        py, scripts = out.read_text().split("|")
        assert py == sys.executable and Path(scripts) == SCRIPTS


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
