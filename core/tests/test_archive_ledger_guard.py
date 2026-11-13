#!/usr/bin/env python3
"""CF-0056: the archive job asks the ledger before it destroys a batch.

Since CF-0358 (the user's decision of 2026-10-04) the job is step (c) of the
monthly archive, `scripts/monthly_archive.py` (the retired
`scripts/archive_old_batches.sh` moved batches with `mv`): batches older than
30 days go into one zip per month on Archive and leave the local disk whole
- no second local copy, old batches are consumable - and
05-video-editor.json is the only thing the rotation's
production columns can ever be filled from. So this job is the one dated
deadline in the factory: after it runs, a row with no `produced_at` is
indistinguishable from a video that was never made, and `production_gap()`
says so itself.

Everything here runs in a temp dir. FACTORY_ROOT is a fake root holding a
*copy* of rotation/ (so the real rotation/ledger/*.csv is never written to)
with patterns/ symlinked in for the import, a pipeline/ built here, and
`--volume` is a plain directory (`--skip-mount-check`) standing in for the mounted volume. The
real /Volumes/Archive is never touched and does not have to be mounted.

What each case pins:

  fills_then_archives     the point of the task - a due batch whose row is
                          still blank gets the row filled from disk *first*
                          and is only then carried away.
  recent_batch_untouched  the ledger is asked lazily: a channel with nothing
                          due costs no backfill at all.
  conflict_blocks_move    `backfill --check` exiting 1 is a veto, not a note:
                          the batch stays on the local disk, and archive.log
                          says why.
  broken_ledger / missing_rotate
                          the same veto when the ledger cannot be read or
                          rotate.py is not where the job expects it. A job
                          that cannot ask must not destroy.
  unrecorded_is_logged    videos no ledger row mentions are not recoverable by
                          anything and do not block the move - but the log
                          line naming them is the only trace that survives it.
  unmounted_is_a_no_op    no volume, no work, and no ledger writes either.
"""
import csv
import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "monthly_archive.py"
CHANNEL = "example-film"

COLUMNS = [
    "seq", "assigned_at", "channel", "batch_id", "script_id", "pattern_id",
    "rhythm_id", "assigned_by", "rejection_reason", "rejection_verdict",
    "rejected_at", "produced_at", "pattern_delivered", "rhythm_delivered",
    "video_path", "published_at", "feed_position", "video_id",
]

TMPDIRS = []


def batch_id(days_ago):
    day = _dt.date.today() - _dt.timedelta(days=days_ago)
    return f"{day.isoformat()}T1200Z"


class World:
    """A fake FACTORY_ROOT plus a fake mount point, wired to the real script."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cf0056-"))
        TMPDIRS.append(self.tmp)
        self.root = self.tmp / "root"
        self.root.mkdir()
        shutil.copytree(ROOT / "rotation", self.root / "rotation")
        for stale in (self.root / "rotation" / "ledger").glob("*.csv"):
            stale.unlink()
        (self.root / "patterns").symlink_to(ROOT / "patterns")
        # CF-0197: rotate.py reads `shared/channel_ids.py` for the names a
        # channel has had. No `channels/` here on purpose - this root has no
        # renamed channel, and the resolver must answer "one name" for it.
        (self.root / "shared").symlink_to(ROOT / "shared")
        self.pipeline = self.root / "pipeline"
        self.pipeline.mkdir()
        self.mount = self.tmp / "mount"
        self.mount.mkdir()
        self.archive = self.mount / "shorts-content-factory-pipeline"
        self.log = self.tmp / "archive.log"
        self.rows = []

    # -- building the state ------------------------------------------------

    def batch(self, bid, videos, extra_files=("01-trend-hunter.json",)):
        """A batch on disk: Video Editor's file plus some other stage output."""
        d = self.pipeline / CHANNEL / bid
        d.mkdir(parents=True)
        (d / "05-video-editor.json").write_text(json.dumps({
            "batch_id": bid,
            "generated_at": f"{bid[:10]}T12:00:00Z",
            "videos": [{"script_id": s, "output_path": f"videos/{s}.mp4"}
                       for s in videos],
        }), encoding="utf-8")
        for name in extra_files:
            (d / name).write_text("{}", encoding="utf-8")
        (d / "work").mkdir()
        (d / "work" / "scratch.txt").write_text("x", encoding="utf-8")
        return d

    def row(self, bid, script_id, **cells):
        row = {c: "" for c in COLUMNS}
        row.update(seq=str(len(self.rows) + 1),
                   assigned_at="2026-01-01T00:00:00Z",
                   channel=CHANNEL, batch_id=bid, script_id=script_id,
                   pattern_id="contrast", rhythm_id="alternate",
                   assigned_by="rotation")
        row.update(cells)
        self.rows.append(row)

    def write_ledger(self, text=None):
        path = self.root / "rotation" / "ledger" / f"{CHANNEL}.csv"
        if text is not None:
            path.write_text(text, encoding="utf-8")
            return path
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(self.rows)
        return path

    # -- running and reading it back ---------------------------------------

    def run(self, mount=True):
        runlog = self.tmp / "runlog"                    # no batch is open
        runlog.write_text("#!/bin/bash\nexit 1\n")
        runlog.chmod(0o755)
        (self.tmp / "tmpdir").mkdir(exist_ok=True)
        args = [sys.executable, str(SCRIPT), "--root", str(self.root),
                "--volume", str(self.mount if mount else self.tmp / "nope"),
                "--skip-mount-check", "--log", str(self.log),
                "--needs-you-dir", str(self.tmp / "needs-you"), "--force",
                "--runlog", str(runlog), "--rotate", str(self.root / "rotation" / "rotate.py"),
                "--tmpdir", str(self.tmp / "tmpdir")]
        env = dict(os.environ, CLEANUP_LOG=str(self.tmp / "cleanup_tmpdir.log"))
        return subprocess.run(args, env=env, timeout=240, capture_output=True, text=True)

    def log_text(self):
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def ledger_rows(self):
        path = self.root / "rotation" / "ledger" / f"{CHANNEL}.csv"
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def on_disk(self, bid, name="05-video-editor.json"):
        return (self.pipeline / CHANNEL / bid / name).exists()

    def archived(self, bid, name="05-video-editor.json"):
        z = self.archive / CHANNEL / f"{bid[:7]}.zip"
        if not z.is_file():
            return False
        with zipfile.ZipFile(z) as zf:
            return f"{bid}/{name}" in zf.namelist()


def ok(result, world, code=0):
    assert result.returncode == code, (
        f"the job exited {result.returncode}\nstdout: {result.stdout}\n"
        f"stderr: {result.stderr}\nlog:\n{world.log_text()}")


# --------------------------------------------------------------------------


def test_fills_then_archives():
    """The whole task in one case: the row is filled before the file leaves."""
    w = World()
    old = batch_id(60)
    w.batch(old, ["lf-old-001-script1", "lf-old-002-script1"])
    w.row(old, "lf-old-001-script1")
    w.row(old, "lf-old-002-script1")
    w.write_ledger()

    result = w.run()
    ok(result, w)

    rows = w.ledger_rows()
    assert all(r["produced_at"] for r in rows), (
        f"the archive job carried the batch away without filling the production "
        f"columns first - after the mv nothing can ever fill them:\n{rows}\n"
        f"{w.log_text()}")
    assert all(r["video_path"] for r in rows), f"video_path left blank: {rows}"
    assert w.archived(old), f"the batch was not archived:\n{w.log_text()}"
    assert w.archived(old, "01-trend-hunter.json"), "other stage files stayed behind"
    assert not w.on_disk(old), "the batch is still on the local disk - no second copy"
    assert w.archived(old, "work/scratch.txt"), "the batch is not archived whole"
    assert not (w.pipeline / CHANNEL / old).exists(), (
        "the batch folder stayed - after a verified zip the original goes whole")
    assert "удалён" in w.log_text()


def test_recent_batch_untouched():
    """Nothing due: no move, and the ledger is not even asked."""
    w = World()
    fresh = batch_id(2)
    w.batch(fresh, ["lf-new-001-script1"])
    w.row(fresh, "lf-new-001-script1")
    w.write_ledger()

    result = w.run()
    ok(result, w)

    assert w.on_disk(fresh), "a two-day-old batch was archived"
    assert not w.archived(fresh)
    assert "backfill" not in w.log_text(), (
        f"the ledger was asked for a channel with nothing due - the question "
        f"belongs to the deadline, not to every run:\n{w.log_text()}")
    assert not w.ledger_rows()[0]["produced_at"], (
        "the job wrote production columns on a run that had nothing to archive")


def test_conflict_blocks_move():
    """`backfill --check` exiting 1 is a veto: the batch stays on disk."""
    w = World()
    old = batch_id(60)
    w.batch(old, ["lf-old-001-script1"])
    # video_path already holds something else, so enrich() refuses the row and
    # produced_at stays blank: produced, on disk, and still not in the ledger.
    w.row(old, "lf-old-001-script1", video_path="videos/somewhere-else.mp4")
    w.write_ledger()

    result = w.run()
    ok(result, w, code=1)                       # the step is not done: NEEDS-YOU

    assert w.on_disk(old), (
        f"the batch was archived while the ledger was still behind it:\n{w.log_text()}")
    assert not w.archived(old)
    log = w.log_text()
    assert "реестр отстаёт" in log, f"the log does not say why it was skipped:\n{log}"
    assert "пропускаю" in log and old in log, f"the skipped batch is not named:\n{log}"


def test_broken_ledger_blocks_move():
    """A ledger that cannot be read is a veto too, not a shrug."""
    w = World()
    old = batch_id(60)
    w.batch(old, ["lf-old-001-script1"])
    w.write_ledger(text="seq,made,up,columns\n1,a,b,c\n")

    result = w.run()
    ok(result, w, code=1)                       # the step is not done: NEEDS-YOU

    assert w.on_disk(old), (
        f"the batch was archived although the ledger could not be read:\n{w.log_text()}")
    assert "backfill не отработал" in w.log_text()


def test_missing_rotate_blocks_move():
    """A job that cannot ask must not destroy."""
    w = World()
    old = batch_id(60)
    w.batch(old, ["lf-old-001-script1"])
    w.row(old, "lf-old-001-script1")
    w.write_ledger()
    (w.root / "rotation" / "rotate.py").unlink()

    result = w.run()
    ok(result, w, code=1)                       # the step is not done: NEEDS-YOU

    assert w.on_disk(old), f"archived with no way to ask the ledger:\n{w.log_text()}"
    assert "спросить реестр нечем" in w.log_text()


def test_unrecorded_is_logged():
    """Videos with no row at all: not recoverable, so not a veto - but named.

    Nothing assigned them and the pair they were cut to is written nowhere, so
    the rotation may not invent a row (CF-0049). The batch is carried away, and
    this log line is then the only surviving record that they existed.
    """
    w = World()
    old = batch_id(60)
    w.batch(old, ["lf-old-001-script1", "lf-ghost-042-script1"])
    w.row(old, "lf-old-001-script1")
    w.write_ledger()

    result = w.run()
    ok(result, w)

    assert w.archived(old), f"an unrecorded video blocked the move:\n{w.log_text()}"
    log = w.log_text()
    assert "вне реестра" in log and "lf-ghost-042-script1" in log, (
        f"the batch was destroyed without naming the videos that no row mentions:\n{log}")
    assert w.ledger_rows()[0]["produced_at"], "the recordable row was not filled"


def test_unmounted_is_a_no_op():
    """No volume: no move, no ledger write, exit 0."""
    w = World()
    old = batch_id(60)
    w.batch(old, ["lf-old-001-script1"])
    w.row(old, "lf-old-001-script1")
    w.write_ledger()

    result = w.run(mount=False)
    ok(result, w, code=1)                       # put off until Archive is plugged in

    assert w.on_disk(old)
    assert "не смонтирован" in w.log_text()
    assert not w.ledger_rows()[0]["produced_at"], (
        "the job wrote to the ledger on a run that archived nothing")


def test_job_still_asks_the_ledger_and_the_old_script_is_gone():
    """CF-0056 survives CF-0358: one monthly job, and it asks the ledger."""
    assert not (ROOT / "scripts" / "archive_old_batches.sh").exists(), (
        "two archive jobs again - the user's decision of 2026-10-04 is one monthly one")
    text = SCRIPT.read_text(encoding="utf-8")
    assert '"backfill", channel' in text and '"--check"' in text, (
        "the job no longer asks the ledger (CF-0056)")


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
    for d in TMPDIRS:
        shutil.rmtree(d, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
