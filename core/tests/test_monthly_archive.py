#!/usr/bin/env python3
"""CF-0358: the monthly archive after `publish/` - pool, old batches, $TMPDIR.

Everything runs in a temp dir: a synthetic factory root (pipeline/, the pool
shared/footage/, publish/), a plain folder standing in for Archive
(`--skip-mount-check`), a fake `runlog` (exit 0 = a batch is open, 1 = none),
a fake `rotate.py` whose `backfill --check` exit code a file sets, and a fake
$TMPDIR. The real pool, pipeline/, ledger, $TMPDIR and Archive are never touched.

What each case pins (the user's decision of 2026-10-04):
  order          pool before batches: the footage of a topic in a batch about
                 to leave is released by that batch's own `01b` (14-day rule),
                 then the batch goes into the month's zip, then $TMPDIR.
  open batch     nothing at all is deleted while a batch is open; the steps are
                 put off and NEEDS-YOU says so.
  verification   a zip that does not verify deletes no batch.
  14 days        a never-delivered topic younger than 14 days keeps its source.
  ledger         `backfill --check` != 0 -> that channel's batches stay.
  monthly        a step done this month is not repeated on the next mount.
  dry run        the plan writes nothing: no deletion, no Archive, no state.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))
from _tmproot import tmp_root                                   # noqa: E402
import monthly_archive as ma                                    # noqa: E402

TMP = tmp_root("monthly-archive-test-")
SCRIPT = ROOT / "scripts" / "monthly_archive.py"
CHAN = "chan"
IDS = {k: (k * 11)[:11] for k in "ABCDEFG"}
TODAY = date.today().isoformat()
_n = [0]


def bid(days_ago):
    return f"{(date.today() - timedelta(days=days_ago)).isoformat()}T1200Z"


class World:
    def __init__(self):
        _n[0] += 1
        self.tmp = TMP / f"w{_n[0]}"
        self.root = self.tmp / "root"
        self.vol = self.tmp / "vol"
        self.tmpdir = self.tmp / "tmpdir"
        for d in (self.root / "pipeline", self.vol, self.tmpdir, self.root / "publish"):
            d.mkdir(parents=True)
        self.log = self.tmp / "archive.log"
        self.needs = self.tmp / "needs-you"          # CF-0652: the journal of questions
        # fake runlog: open when the file `open` exists
        self.runlog = self.tmp / "runlog"
        self.runlog.write_text(f"#!/bin/bash\n[ -f '{self.tmp}/open' ] && exit 0\nexit 1\n")
        self.runlog.chmod(0o755)
        # fake rotate.py: backfill prints a report; --check exits with the code in `check`
        self.rotate = self.tmp / "rotate.py"
        self.rotate.write_text(
            "import json, sys, pathlib\n"
            f"t = pathlib.Path({str(self.tmp)!r})\n"
            "with open(t / 'rotate-calls', 'a') as f: f.write(' '.join(sys.argv[1:]) + '\\n')\n"
            "if '--check' in sys.argv:\n"
            "    code = int((t / 'check').read_text()) if (t / 'check').exists() else 0\n"
            "    print(json.dumps({'recoverable': {}})); sys.exit(code)\n"
            "print(json.dumps({'filled': [], 'batches': []}))\n")

    def batch(self, name, topics, group=CHAN):
        b = self.root / "pipeline" / group / name
        b.mkdir(parents=True)
        (b / "01b-footage-index.json").write_text(json.dumps({
            "sources_by_topic": topics,
            "fetched": [{"video_id": v, "topic_id": t} for t, vs in topics.items() for v in vs]}))
        (b / "05-video-editor.json").write_text(json.dumps({"channel": CHAN, "videos": []}))
        (b / "work").mkdir()
        (b / "work" / "frame.bin").write_bytes(os.urandom(4096))
        (b / "videos").mkdir()
        (b / "videos" / "x.mp4").write_bytes(os.urandom(8192))
        return b

    def pool(self, *vids):
        p = self.root / "shared" / "footage"
        p.mkdir(parents=True, exist_ok=True)
        for v in vids:
            for suf in (".mp4", ".shots.json", ".contact.jpg", ".fingerprint.json"):
                (p / f"{v}{suf}").write_bytes(b"x" * 100)
        (p / "index.json").write_text(json.dumps({"entries": [{"id": v} for v in vids]}))

    def in_pool(self, v):
        return (self.root / "shared" / "footage" / f"{v}.mp4").exists()

    def old_tmp_run(self, name="rt-old"):
        d = self.tmpdir / name
        d.mkdir()
        f = d / "x.txt"
        f.write_text("x")
        old = time.time() - 3 * 86400
        os.utime(f, (old, old))
        os.utime(d, (old, old))
        return d

    def questions(self):
        """The live questions of the journal, their keys and texts in one string."""
        sys.path.insert(0, str(ROOT / "shared"))
        import needs_you                                    # noqa: PLC0415
        return " ".join(f"{q['key']} {q['text']}" for q in needs_you.live(directory=self.needs))

    def run(self, *extra, today=TODAY):
        args = [sys.executable, str(SCRIPT), "--root", str(self.root), "--volume", str(self.vol),
                "--skip-mount-check", "--log", str(self.log), "--needs-you-dir", str(self.needs),
                "--today", today, "--runlog", str(self.runlog), "--rotate", str(self.rotate),
                "--tmpdir", str(self.tmpdir), *extra]
        env = dict(os.environ, CLEANUP_LOG=str(self.tmp / "cleanup_tmpdir.log"))
        self.res = subprocess.run(args, capture_output=True, text=True, timeout=240, env=env)
        return self.res

    def text(self):
        return self.log.read_text(encoding="utf-8") if self.log.exists() else ""

    def zip(self, month, group=CHAN):
        return self.vol / ma.BATCH_ARCHIVE_DIR / group / f"{month}.zip"

    def why(self):
        return f"\nstdout:{self.res.stdout}\nstderr:{self.res.stderr}\nlog:\n{self.text()}"


def test_order_pool_then_batches_then_tmpdir():
    w = World()
    old = w.batch(bid(40), {"t-old": [IDS["A"]]})              # never a video, 40 days
    w.pool(IDS["A"])
    tmp_run = w.old_tmp_run()
    res = w.run()
    assert res.returncode == 0, w.why()
    assert not w.in_pool(IDS["A"]), "the stale topic's source stayed - pool ran after the batch left?" + w.why()
    assert not old.exists(), "the 40-day batch is still on disk" + w.why()
    z = w.zip(old.name[:7])
    with zipfile.ZipFile(z) as zf:
        names = set(zf.namelist())
    assert {f"{old.name}/01b-footage-index.json", f"{old.name}/work/frame.bin",
            f"{old.name}/videos/x.mp4"} <= names, names
    assert subprocess.run(["unzip", "-tq", str(z)], capture_output=True).returncode == 0
    assert not tmp_run.exists(), "an old factory run in $TMPDIR stayed" + w.why()
    log = w.text()
    i_pool, i_batch, i_other = log.index("пул:"), log.index("батчи"), log.index("прочее:")
    assert i_pool < i_batch < i_other, log
    rel = (w.root / "shared" / "footage" / "release-log.jsonl").read_text()
    assert IDS["A"] in rel and '"stale": true' in rel


def test_open_batch_puts_everything_off():
    w = World()
    old = w.batch(bid(40), {"t-old": [IDS["A"]]})
    w.pool(IDS["A"])
    tmp_run = w.old_tmp_run()
    (w.tmp / "open").write_text("")
    res = w.run()
    assert res.returncode == 1, w.why()
    assert w.in_pool(IDS["A"]) and old.exists() and tmp_run.exists(), w.why()
    assert not (w.vol / ma.BATCH_ARCHIVE_DIR).exists()
    assert "открыт батч" in w.text()
    assert ma.MARKER in w.questions()
    assert not Path(str(w.log) + ma.STATE_SUFFIX).exists(), "a put-off step was marked done"
    # closed again: the next run pays it and clears the reminder
    (w.tmp / "open").unlink()
    assert w.run().returncode == 0, w.why()
    assert not old.exists() and not w.in_pool(IDS["A"])
    assert ma.MARKER not in w.questions()


def test_failed_verification_deletes_no_batch():
    w = World()
    old = w.batch(bid(40), {})
    log = ma.Log(w.log)
    ctx = ma.Ctx(w.root, w.vol, log, TODAY, runlog=str(w.runlog), rotate=w.rotate,
                 skip_mount_check=True)
    done = ma.step_batches(ctx, verify=lambda z, m: (["a member does not match"], None, None))
    assert done is False
    assert old.exists() and (old / "videos" / "x.mp4").exists()
    assert not w.zip(old.name[:7]).exists()
    assert not list((w.vol / ma.BATCH_ARCHIVE_DIR).rglob("*.partial"))
    assert "сверка не сошлась" in w.text()


def test_fourteen_day_rule_keeps_a_younger_topic():
    w = World()
    w.batch(bid(10), {"t-young": [IDS["B"]]})
    w.batch(bid(20), {"t-mid": [IDS["C"]]})
    w.pool(IDS["B"], IDS["C"])
    assert w.run().returncode == 0, w.why()
    assert w.in_pool(IDS["B"]), "a 10-day-old undelivered topic lost its source" + w.why()
    assert not w.in_pool(IDS["C"]), "a 20-day-old undelivered topic kept its source" + w.why()
    assert (w.root / "pipeline" / CHAN / bid(10)).exists()
    assert (w.root / "pipeline" / CHAN / bid(20)).exists(), "a 20-day batch left (< 30 days)"


def test_ledger_behind_keeps_the_channels_batches():
    w = World()
    old = w.batch(bid(45), {})
    (w.tmp / "check").write_text("1")
    res = w.run()
    assert res.returncode == 1, w.why()
    assert old.exists(), "batches left while backfill --check was not 0" + w.why()
    assert not w.zip(old.name[:7]).exists()
    calls = (w.tmp / "rotate-calls").read_text().splitlines()
    assert calls == [f"backfill {CHAN}", f"backfill {CHAN} --check"], calls
    assert "реестр отстаёт" in w.text() and old.name in w.text()


def test_late_batch_joins_the_months_zip():
    w = World()
    a = w.batch(bid(70), {})
    assert w.run().returncode == 0, w.why()
    b = w.batch(bid(69), {})
    if a.name[:7] != b.name[:7]:
        return                                                  # month boundary today
    assert w.run("--force").returncode == 0, w.why()
    with zipfile.ZipFile(w.zip(a.name[:7])) as zf:
        tops = {n.split("/", 1)[0] for n in zf.namelist()}
    assert tops == {a.name, b.name}, tops
    man = json.loads((w.vol / ma.BATCH_ARCHIVE_DIR / CHAN / f"{a.name[:7]}.manifest.json").read_text())
    assert man["batches"] == sorted([a.name, b.name])


def test_monthly_not_daily():
    w = World()
    w.batch(bid(10), {})
    assert w.run().returncode == 0, w.why()
    old = w.batch(bid(50), {})
    assert w.run().returncode == 0, w.why()
    assert old.exists(), "a second run in the same month archived again" + w.why()
    nxt = (date.fromisoformat(TODAY).replace(day=1) + timedelta(days=32)).replace(day=1)
    assert w.run(today=nxt.isoformat()).returncode == 0, w.why()
    assert not old.exists(), "the next month's run did not archive" + w.why()


def test_dry_run_writes_nothing():
    w = World()
    old = w.batch(bid(40), {"t-old": [IDS["A"]]})
    w.pool(IDS["A"])
    tmp_run = w.old_tmp_run()
    res = w.run("--dry-run")
    assert res.returncode == 0, w.why()
    assert w.in_pool(IDS["A"]) and old.exists() and tmp_run.exists()
    assert not (w.vol / ma.BATCH_ARCHIVE_DIR).exists()
    assert not w.log.exists() and not Path(str(w.log) + ma.STATE_SUFFIX).exists()
    calls = (w.tmp / "rotate-calls").read_text().splitlines()
    assert calls == [f"backfill {CHAN} --check"], calls
    assert "освободить 1" in res.stdout and old.name in res.stdout, res.stdout


def test_synthetic_backfill_group_is_never_touched():
    w = World()
    syn = w.batch(bid(60), {}, group="backfill")
    assert w.run().returncode == 0, w.why()
    assert syn.exists()


def test_a_rebuild_answers_to_the_channel_its_records_name():
    w = World()
    rb = w.batch(bid(40), {}, group="rebuilds")
    (rb / "05-video-editor.json").write_text(json.dumps(
        {"channel": "rebuilds", "rebuild_of": {"channel": CHAN, "batch_id": bid(50)}}))
    assert w.run().returncode == 0, w.why()
    calls = (w.tmp / "rotate-calls").read_text().splitlines()
    assert calls == [f"backfill {CHAN}", f"backfill {CHAN} --check"], calls
    assert not rb.exists() and w.zip(rb.name[:7], group="rebuilds").is_file(), w.why()


def test_cf0720_archive_json_dry_run_carries_the_monthly_lines_and_stdout_is_json_alone():
    """`archive_publish_month.py --dry-run --json` without --publish-only: the
    monthly steps' lines (and the children's output) go to stderr and into
    `monthly.lines`; stdout is one JSON document."""
    w = World()
    old = w.batch(bid(40), {"t-old": [IDS["A"]]})
    w.pool(IDS["A"])
    tmp_run = w.old_tmp_run()
    cmd = [sys.executable, str(ROOT / "scripts" / "archive_publish_month.py"), "--root",
           str(w.root), "--volume", str(w.vol), "--skip-mount-check", "--log", str(w.log),
           "--needs-you-dir", str(w.needs), "--today", TODAY, "--runlog", str(w.runlog),
           "--rotate", str(w.rotate), "--tmpdir", str(w.tmpdir), "--dry-run", "--json",
           "--by", "user", "--via", "center"]
    env = dict(os.environ, CLEANUP_LOG=str(w.tmp / "cleanup_tmpdir.log"))
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=240, env=env)
    assert res.returncode == 0, res.stdout + res.stderr
    doc = json.loads(res.stdout)
    assert doc["dry_run"] is True and doc["by"] == "user" and doc["exit_code"] == 0, doc
    lines = doc["monthly"]["lines"]
    assert any("освободить 1" in ln for ln in lines) and any(old.name in ln for ln in lines), lines
    assert "освободить 1" in res.stderr
    assert w.in_pool(IDS["A"]) and old.exists() and tmp_run.exists() and not w.log.exists()


if __name__ == "__main__":
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                      # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
