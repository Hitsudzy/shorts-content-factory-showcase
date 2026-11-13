#!/usr/bin/env python3
"""CF-0675: a verdict from the command center is a commit - or waits in the queue
while a batch is going.

`publish/acceptance-log.json` is tracked: a verdict written and not committed
leaves the root dirty (and `batch-start` wants it clean), and one committed under
an open batch moves the root's HEAD under the batch. Pinned here, on temp git
repositories only (the real checkout is never written, no network, no live
batch - open batches are stand-in rows of `runlog.open_batches`):

* no batch going: one verdict, one commit `Приёмка: <slug> <вердикт> (<by>)` of
  the record and of nothing else - a staged file elsewhere stays out of it;
* a batch going: the verdict lands in `publish/acceptance-pending.jsonl`, the
  record and HEAD do not move, the tree stays clean for `batch-start`;
* the batch done: `commit_pending` applies the whole queue as one commit, and the
  schedule's tick does it (`batch_schedule._acceptance_flush`); so does the next
  verdict given with no batch going, before its own commit;
* the same video twice in the queue: the last verdict wins, the commit message
  says so;
* readers (`entries` from a file, `state`) see the queued verdict at once,
  `pending: true`; a writer's rows (`entries(log=doc)`) never carry it, and
  `write_log` never writes one;
* a refused verdict is refused at once under a batch too, and a commit git does
  not make leaves the record as it was.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(ROOT / "shared"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("acceptance-commit-test-")
os.environ.setdefault("RUNLOG_STATE_DIR", str(TMP / "state"))
os.environ["RUNLOG_POOL"] = str(TMP / "no-pool")       # never the live pipeline/

import acceptance    # noqa: E402
import batch_schedule   # noqa: E402
import runlog        # noqa: E402

CHANNEL = "testchan"
BATCH = "2026-10-10T0900Z"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
_n = [0]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def factory():
    """A fresh root repo: the record committed, the repo's own .gitignore lines
    for the queue, a batch directory with a stand-in open run."""
    _n[0] += 1
    d = TMP / f"root{_n[0]}"
    (d / "publish").mkdir(parents=True)
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@example.invalid")
    git(d, "config", "user.name", "test")
    git(d, "config", "core.hooksPath", str(d / ".git" / "hooks"))   # no global hook (push)
    ignore = [l for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
              if "acceptance-pending" in l]
    assert ignore, "the repo's .gitignore names the queue"
    (d / ".gitignore").write_text("\n".join(ignore) + "\n", encoding="utf-8")
    acceptance.write_log([], path=d / "publish" / "acceptance-log.json")
    (d / "code.py").write_text("x = 1\n", encoding="utf-8")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "init")
    return d


def log_of(d):
    return d / "publish" / "acceptance-log.json"


def batch_open(d):
    return [(d / "pipeline" / CHANNEL / BATCH, NOW, True)]


def say(d, slug, verdict="accepted", by="центр", open_rows=(), **kw):
    if verdict == "rejected":
        kw.setdefault("reason", "кадры не про тему")
        kw.setdefault("reason_code", "off_topic")
    return acceptance.record_and_commit(
        CHANNEL, BATCH, slug, verdict, f"{slug} - {verdict}", by=by, root=d,
        open_rows=list(open_rows), topic_id="t-" + slug, batch_dir=TMP / "no-batch", **kw)


def commits(d):
    return int(git(d, "rev-list", "--count", "HEAD"))


def clean(d):
    return git(d, "status", "--porcelain", "--untracked-files=all") == ""


def test_a_verdict_with_no_batch_going_is_one_commit_of_the_record_only():
    d = factory()
    (d / "code.py").write_text("x = 2\n", encoding="utf-8")
    git(d, "add", "code.py")                       # staged by someone else: stays out
    res = say(d, "harbourlights")
    assert res["committed"] and not res["pending"] and res["flushed"] is None
    assert res["commit"] == git(d, "rev-parse", "HEAD")
    assert git(d, "log", "-1", "--format=%s") == "Приёмка: harbourlights принят (центр)"
    assert git(d, "show", "--name-only", "--format=", "HEAD") == "publish/acceptance-log.json"
    assert git(d, "diff", "--cached", "--name-only") == "code.py"
    rows = acceptance.entries(path=log_of(d))
    assert [r["slug"] for r in rows] == ["harbourlights"] and not rows[0].get("pending")
    assert "Acceptance: testchan/2026-10-10T0900Z/harbourlights" in git(d, "log", "-1", "--format=%B")


def test_under_an_open_batch_the_verdict_is_queued_and_the_tree_stays_clean():
    d = factory()
    before, head = log_of(d).read_bytes(), git(d, "rev-parse", "HEAD")
    res = say(d, "harbourlights", open_rows=batch_open(d))
    assert res["pending"] and not res["committed"] and res["commit"] is None
    assert res["batches"][0]["dir"].endswith(BATCH)
    assert res["row"]["pending"] is True
    assert log_of(d).read_bytes() == before and git(d, "rev-parse", "HEAD") == head
    q = d / "publish" / "acceptance-pending.jsonl"
    assert Path(res["queue"]).resolve() == q.resolve() and len(acceptance.read_pending(q)) == 1
    assert clean(d), git(d, "status", "--porcelain", "--untracked-files=all")
    st = runlog.repo_state(runlog.ROOT_REPO, d)    # what batch-start reads of the root
    assert st["dirty"] == [] and st["branch"] == "main"


def test_a_refused_verdict_is_refused_at_once_under_a_batch_too():
    d = factory()
    try:
        acceptance.record_and_commit(CHANNEL, BATCH, "harbourlights", "accepted", "yes, 1 and 3",
                                     by="центр", root=d, open_rows=batch_open(d),
                                     topic_id="t", batch_dir=TMP / "no-batch")
    except acceptance.AcceptanceError as e:
        assert "does not name this video" in str(e)
    else:
        raise AssertionError("an answer that does not name the video was queued")
    assert not (d / "publish" / "acceptance-pending.jsonl").exists()


def test_readers_see_the_queued_verdict_pending_and_writers_never_write_it():
    d = factory()
    say(d, "delver", "rejected")                               # on the record
    say(d, "harbourlights", open_rows=batch_open(d))                # queued
    say(d, "delver", "accepted", open_rows=batch_open(d), amend="передумал: delver да")
    rows = {r["slug"]: r for r in acceptance.entries(path=log_of(d))}
    assert rows["harbourlights"]["pending"] is True and rows["harbourlights"]["queued_by"] == "центр"
    assert rows["delver"]["pending"] is True and rows["delver"]["verdict"] == "accepted"
    assert rows["delver"]["history"][0]["verdict"] == "rejected"
    assert rows["delver"]["on_record"]["verdict"] == "rejected"
    assert rows["harbourlights"]["on_record"] is None
    st = acceptance.state(CHANNEL, BATCH, "harbourlights", path=log_of(d),
                          holds_path=TMP / "no-holds.json")
    assert st["recorded"] and st["accepted"] and st["pending"] and st["queued_at"]
    own = acceptance.entries(log=acceptance.read_log(log_of(d)))
    assert [(r["slug"], r["verdict"]) for r in own] == [("delver", "rejected")]
    assert all(not r.get("pending")
               for r in acceptance.entries(path=log_of(d), pending=False))
    out = TMP / f"written{_n[0]}.json"
    acceptance.write_log(acceptance.entries(path=log_of(d)), path=out)
    written = acceptance.entries(path=out, pending=False)
    assert [(r["slug"], r["verdict"]) for r in written] == [("delver", "rejected")]


def test_after_the_batch_the_queue_is_one_commit_and_the_last_verdict_wins():
    d = factory()
    say(d, "harbourlights", open_rows=batch_open(d), by="центр")
    say(d, "delver", "rejected", open_rows=batch_open(d), by="центр")
    say(d, "harbourlights", "rejected", open_rows=batch_open(d), by="терминал")
    n = commits(d)
    held = acceptance.commit_pending(d, open_rows=batch_open(d))
    assert not held["committed"] and "идёт батч" in held["why"] and held["left"] == 3
    assert commits(d) == n
    res = acceptance.commit_pending(d, by="расписание", open_rows=[])
    assert res["committed"] and commits(d) == n + 1 and res["left"] == 0
    assert sorted(res["applied"]) == [f"{CHANNEL}/{BATCH}/delver", f"{CHANNEL}/{BATCH}/harbourlights"]
    msg = git(d, "log", "-1", "--format=%B")
    assert msg.startswith("Приёмка: 2 вердикта из очереди после батча (терминал, центр)")
    assert "Конфликт: testchan/2026-10-10T0900Z/harbourlights" in msg
    assert "последний побеждает: отклонён" in msg
    assert res["conflicts"][0]["won"] == "rejected"
    assert git(d, "show", "--name-only", "--format=", "HEAD") == "publish/acceptance-log.json"
    rows = {r["slug"]: r for r in acceptance.entries(path=log_of(d))}
    assert rows["harbourlights"]["verdict"] == "rejected" and not rows["harbourlights"].get("pending")
    assert not (d / "publish" / "acceptance-pending.jsonl").exists() and clean(d)
    again = acceptance.commit_pending(d, open_rows=[])
    assert not again["committed"] and again["why"] == "очередь приёмки пуста"


def test_the_next_verdict_with_no_batch_commits_the_queue_first():
    d = factory()
    say(d, "harbourlights", open_rows=batch_open(d))
    n = commits(d)
    res = say(d, "delver", "rejected")
    assert res["flushed"]["committed"] and res["committed"] and commits(d) == n + 2
    subjects = git(d, "log", "-2", "--format=%s").splitlines()
    assert subjects == ["Приёмка: delver отклонён (центр)", "Приёмка: harbourlights принят (центр)"]
    assert clean(d)


def test_the_schedule_tick_commits_the_queue_once_no_batch_is_going():
    d = factory()
    assert batch_schedule._acceptance_flush(d, NOW, open_rows=[]) == ""   # no queue
    say(d, "harbourlights", open_rows=batch_open(d))
    n = commits(d)
    assert batch_schedule._acceptance_flush(d, NOW, open_rows=batch_open(d)) == ""
    assert commits(d) == n
    line = batch_schedule._acceptance_flush(d, NOW, open_rows=[])
    assert line.startswith("приёмка: 1 из очереди закоммичено ") and commits(d) == n + 1
    assert git(d, "log", "-1", "--format=%s") == "Приёмка: harbourlights принят (центр)"


def test_a_commit_git_refuses_leaves_the_record_as_it_was():
    d = factory()
    hook = d / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)
    before, n = log_of(d).read_bytes(), commits(d)
    try:
        say(d, "harbourlights")
    except acceptance.AcceptanceError as e:
        assert "not committed" in str(e)
    else:
        raise AssertionError("a refused commit was reported as made")
    assert log_of(d).read_bytes() == before and commits(d) == n and clean(d)


def test_the_cli_records_and_commits_and_commits_the_queue():
    d = factory()
    env = dict(os.environ, RUNLOG_POOL=str(TMP / "no-pool"))
    base = [sys.executable, str(ROOT / "shared" / "runlog" / "acceptance.py"),
            "--root", str(d), "--log", str(log_of(d))]
    cp = subprocess.run(base + ["--record", f"{CHANNEL}/{BATCH}/harbourlights", "--verdict",
                                "accepted", "--answer", "harbourlights да", "--topic", "t-l",
                                "--batch-dir", str(TMP / "no-batch"), "--write", "--commit",
                                "--by", "оператор"], capture_output=True, text=True, env=env)
    assert cp.returncode == 0, cp.stderr
    assert git(d, "log", "-1", "--format=%s") == "Приёмка: harbourlights принят (оператор)"
    cp = subprocess.run(base + ["--commit-pending", "--json"], capture_output=True, text=True,
                        env=env)
    assert cp.returncode == 0, cp.stderr
    assert json.loads(cp.stdout)["why"] == "очередь приёмки пуста"


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
