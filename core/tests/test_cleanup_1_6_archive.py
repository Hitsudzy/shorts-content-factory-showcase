#!/usr/bin/env python3
"""CF-0500: `scripts/cleanup_1_6_archive.sh` - the one-off move of the 1.6
cleanup candidates to Archive (one zip per group, `unzip -t`, sha256 of every file
against the originals, deletion only with `--delete-originals`).

Everything runs in a temp dir: FACTORY_ROOT is a synthetic factory holding the
candidate paths and their neighbours that must survive, ARCHIVE_DIR is a plain
directory standing in for the volume, `runlog` and `rotate.py` are stubs whose
exit code each case sets. The live tree and /Volumes/Archive are never
touched.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cleanup_1_6_archive.sh"

OLD_REBUILDS = ["2026-09-23T0330Z", "2026-09-23T0725Z", "2026-09-23T1053Z",
                "2026-09-23T1344Z", "2026-09-24T2027Z", "2026-09-25T0100Z"]
WORK = ["cf0116-sample", "cf0117-sample", "cf0130-frames", "cf0162-ambient"]
TMPDIRS = []


class World:
    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="cf0500-"))
        TMPDIRS.append(self.tmp)
        self.root = self.tmp / "factory"
        self.vol = self.tmp / "Archive"
        self.vol.mkdir()
        self.archive = self.vol / "cleanup"
        r = self.root
        for b in ("2026-08-28T2016Z", "2026-09-09T2031Z"):
            self.put(f"pipeline/legacy-film/{b}/05-video-editor.json", '{"b": "%s"}' % b)
            self.put(f"pipeline/legacy-film/{b}/videos/a.mp4", os.urandom(4096))
            self.put(f"pipeline/legacy-film/{b}/work/x y/plan.json", "{}")  # a space in a name
        self.put("pipeline/legacy-film/.DS_Store", b"\0\1")
        for b in OLD_REBUILDS + ["2026-09-27T1757Z"]:
            self.put(f"pipeline/rebuilds/{b}/RUN_EVENTS.jsonl", b + "\n")
        self.put("pipeline/rebuilds/retired-shots.json", "{}")
        self.put("pipeline/example-film/2026-10-01T2210Z/05-video-editor.json", "{}")
        for w in WORK + ["cf0052-measure", "cf-render-now"]:
            self.put(f"agents/video-editor/work/{w}/f.bin", os.urandom(1024))
        (r / "agents/video-editor/videos").mkdir(parents=True)
        (r / "agents/analyst").mkdir(parents=True)
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        self.runlog = bin_ / "runlog"
        self.runlog.write_text('#!/bin/bash\n[ "$1" = batch-active ] || exit 9\nexit "${STUB_RUNLOG_RC:-1}"\n')
        self.runlog.chmod(0o755)
        self.rotate = bin_ / "rotate.py"
        self.rotate.write_text(
            "import os, sys\nassert sys.argv[1:] == ['backfill', 'example-film', '--check'], sys.argv\n"
            "open(os.environ['STUB_ROTATE_LOG'], 'a').write('asked\\n')\n"
            "sys.exit(int(os.environ.get('STUB_ROTATE_RC', '0')))\n")
        self.rotate_log = self.tmp / "rotate.log"

    def put(self, rel, data):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            p.write_bytes(data)
        else:
            p.write_text(data)

    def run(self, *args, runlog_rc=1, rotate_rc=0, archive=None):
        env = dict(os.environ, FACTORY_ROOT=str(self.root),
                   ARCHIVE_DIR=str(archive or self.archive), RUNLOG=str(self.runlog),
                   ROTATE=str(self.rotate), PYTHON=sys.executable,
                   STUB_RUNLOG_RC=str(runlog_rc), STUB_ROTATE_RC=str(rotate_rc),
                   STUB_ROTATE_LOG=str(self.rotate_log))
        return subprocess.run(["bash", str(SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=120)

    def exists(self, rel):
        return (self.root / rel).exists()

    def candidates(self):
        return (["pipeline/legacy-film"] + [f"pipeline/rebuilds/{b}" for b in OLD_REBUILDS]
                + [f"agents/video-editor/work/{w}" for w in WORK])

    def keepers(self):
        return ["pipeline/rebuilds/2026-09-27T1757Z", "pipeline/rebuilds/retired-shots.json",
                "pipeline/example-film/2026-10-01T2210Z/05-video-editor.json",
                "agents/video-editor/work/cf0052-measure/f.bin",
                "agents/video-editor/work/cf-render-now/f.bin"]


ZIPS = ["legacy-film-batches", "rebuilds-2026-09-23-to-25", "video-editor-work-leftovers"]


def test_without_the_flag_it_archives_verifies_and_deletes_nothing():
    w = World()
    p = w.run()
    assert p.returncode == 0, p.stdout + p.stderr
    for z in ZIPS:
        assert (w.archive / f"{z}.zip").is_file(), z
        assert (w.archive / f"{z}.sha256").is_file(), z
    assert all(w.exists(c) for c in w.candidates()), "no flag - originals stay"
    assert w.exists("agents/analyst") and w.exists("agents/video-editor/videos")
    assert "удаляю" not in p.stdout
    assert not w.rotate_log.exists(), "the ledger is asked only before a deletion"
    assert not list(w.archive.glob(".verify-*")), "the verification dir is cleaned up"
    listing = subprocess.run(["unzip", "-Z1", str(w.archive / "legacy-film-batches.zip")],
                             capture_output=True, text=True).stdout.split("\n")
    assert "pipeline/legacy-film/2026-09-09T2031Z/work/x y/plan.json" in listing
    assert "pipeline/legacy-film/.DS_Store" in listing
    log = (w.archive / "cleanup.log").read_text()
    assert "sha256 всех файлов сошлись" in log and "файлов ->" in log


def test_with_the_flag_it_deletes_exactly_the_candidates_and_prints_each_path():
    w = World()
    p = w.run("--delete-originals")
    assert p.returncode == 0, p.stdout + p.stderr
    for c in w.candidates():
        assert not w.exists(c), c
        assert f"удаляю: {w.root / c}" in p.stdout, c
    for k in w.keepers():
        assert w.exists(k), f"{k} is not a candidate and must survive"
    assert not w.exists("agents/analyst") and not w.exists("agents/video-editor/videos")
    assert w.rotate_log.read_text().count("asked") == 1
    again = w.run("--delete-originals")
    assert again.returncode == 0, again.stdout + again.stderr
    assert again.stdout.count("уже сделано") == 3, again.stdout


def test_an_open_batch_stops_everything_before_any_zip():
    w = World()
    p = w.run("--delete-originals", runlog_rc=0)
    assert p.returncode != 0
    assert "открыт батч" in p.stderr
    assert not list(w.archive.glob("*.zip"))
    assert all(w.exists(c) for c in w.candidates())


def test_runlog_that_cannot_answer_is_a_stop_too():
    w = World()
    p = w.run(runlog_rc=2)
    assert p.returncode != 0 and "не проверена" in p.stderr


def test_a_zip_that_no_longer_matches_the_originals_blocks_the_deletion():
    w = World()
    assert w.run().returncode == 0
    w.put("pipeline/rebuilds/2026-09-23T0330Z/RUN_EVENTS.jsonl", "changed after the zip\n")
    p = w.run("--delete-originals")
    assert p.returncode != 0
    assert "sha256" in p.stderr, p.stderr
    assert all(w.exists(c) for c in w.candidates()), "a failed check deletes nothing"


def test_a_ledger_behind_the_disk_blocks_the_deletion():
    w = World()
    p = w.run("--delete-originals", rotate_rc=1)
    assert p.returncode != 0 and "реестр ротации" in p.stderr, p.stderr
    assert all(w.exists(c) for c in w.candidates())
    assert all((w.archive / f"{z}.zip").is_file() for z in ZIPS), "the zips are made anyway"


def test_a_non_empty_leftover_dir_is_kept():
    w = World()
    w.put("agents/analyst/note.txt", "x")
    p = w.run("--delete-originals")
    assert p.returncode == 0, p.stderr
    assert w.exists("agents/analyst/note.txt") and "не пуст" in p.stdout


def test_a_partly_missing_group_is_a_stop():
    w = World()
    shutil.rmtree(w.root / "agents/video-editor/work/cf0130-frames")
    p = w.run()
    assert p.returncode != 0 and "часть путей отсутствует" in p.stderr


def test_no_volume_no_work():
    w = World()
    p = w.run(archive=w.tmp / "not-mounted" / "cleanup")
    assert p.returncode != 0 and "не смонтирован" in p.stderr
    assert all(w.exists(c) for c in w.candidates())


def test_repack_replaces_a_stale_zip_with_a_verified_one():
    """CF-0358: a journal removed after the zip was made (CF-0530) - the old zip
    carries an extra file, the regular run stops on it, `--repack` fixes it."""
    w = World()
    assert w.run().returncode == 0
    gone = "pipeline/legacy-film/2026-08-28T2016Z/videos/a.mp4"
    (w.root / gone).unlink()
    stuck = w.run("--delete-originals")
    assert stuck.returncode != 0 and "файлов" in stuck.stderr, stuck.stderr
    assert all(w.exists(c) for c in w.candidates() if c != gone)
    p = w.run("--repack", "legacy-film-batches")
    assert p.returncode == 0, p.stdout + p.stderr
    listing = subprocess.run(["unzip", "-Z1", str(w.archive / "legacy-film-batches.zip")],
                             capture_output=True, text=True).stdout.split("\n")
    assert gone not in listing, "the repacked zip still carries the removed file"
    assert "pipeline/legacy-film/2026-09-09T2031Z/videos/a.mp4" in listing
    assert not list(w.archive.glob("*.repack*")), "the new zip was left beside the old one"
    assert "заменён сверенным новым" in p.stdout
    assert w.exists("pipeline/legacy-film"), "--repack never deletes originals"
    ok = w.run("--delete-originals")
    assert ok.returncode == 0, ok.stdout + ok.stderr


def test_repack_refuses_an_unknown_group_and_an_open_batch():
    w = World()
    assert w.run().returncode == 0
    before = (w.archive / "legacy-film-batches.zip").read_bytes()
    p = w.run("--repack", "no-such-group")
    assert p.returncode != 0 and "нет группы" in p.stderr, p.stderr
    p = w.run("--repack", "legacy-film-batches", runlog_rc=0)
    assert p.returncode != 0 and "открыт батч" in p.stderr
    assert (w.archive / "legacy-film-batches.zip").read_bytes() == before


if __name__ == "__main__":
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    try:
        for name, fn in tests:
            try:
                fn()
                print(f"ok   {name}")
            except Exception as e:                      # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    finally:
        for d in TMPDIRS:
            shutil.rmtree(d, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
