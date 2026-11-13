#!/usr/bin/env python3
"""CF-0501: `scripts/cleanup_tmpdir.sh` - the cleanup of old factory trees in
$TMPDIR (the user's decision 03.10: delete, no archive).

Everything runs on a synthetic root (CLEANUP_TMPDIR_ROOT) inside a temp dir of
this test: factory trees by name and by content, old and fresh, next to
neighbours that must survive (system dirs, files with factory-looking names, a
symlink, generic tmp dirs without a factory trace). The live $TMPDIR is never
touched.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cleanup_tmpdir.sh"
OLD = time.time() - 48 * 3600


def put(base, rel, data="x", old=True):
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(data)
    return p


def age(path, old=True):
    t = OLD if old else time.time()
    for dp, dn, fn in os.walk(path):
        for f in fn:
            os.utime(os.path.join(dp, f), (t, t))
        os.utime(dp, (t, t))


def run(root, *args, log=None):
    env = dict(os.environ, CLEANUP_TMPDIR_ROOT=str(root), CLEANUP_LOG=str(log or root.parent / "log"))
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)


def build(base):
    r = base / "T"
    r.mkdir()
    outside = base / "outside"
    put(outside, "keep.txt")
    gone = ["rt-abc12345", "th-runlog-xy", "th-apikey-q1", "cc-runlog-z", "cf0014-ab12cd34",
            "cf0052-runlog-zz", "run-tests-runlog_batch-k", "frame-judge-contract-p",
            "ve-text-gates-a", "remotion-webpack-bundle-Q", "react-motion-renderX"]
    for n in gone:
        put(r, f"{n}/sub dir/f.json")
    put(r, "tmpab12cd_9/channels/example-film.json")                 # mkdtemp + trace
    put(r, "tmpzz99yy88/123-content-researcher.json")
    put(r, "tmp.AbCdEf1234/RUN_EVENTS.jsonl")                       # mktemp -d + trace
    (r / "tmpemptyab1").mkdir()                                      # empty generic
    keep_old = ["tmpqq11ww22", "com.apple.trustd", "claude-501", "remotion-v4.0.1",
                "intellij-npm-info", "tmp_not_generic_name"]
    put(r, "tmpqq11ww22/ctN.png")                                    # generic, no trace
    for n in keep_old[1:]:
        put(r, f"{n}/a.txt")
    put(r, "rt-file-not-dir")                                         # a file with a factory name
    put(r, "push-failures-agent-a.log")
    os.symlink(outside, r / "rt-symlink")                             # a symlink with a factory name
    put(r, "th-runlog-fresh/f.json")                                  # fresh: a run in progress
    put(r, "tmpfresh001/plan.json")
    put(r, "cf0499-oldtop/x.json")
    for e in r.iterdir():
        if not e.is_symlink():
            age(e, old=True)
    age(r / "th-runlog-fresh", old=False)
    age(r / "tmpfresh001", old=False)
    # an old top dir with one fresh file deep inside - still in use
    put(r, "cf0499-oldtop/deep/now.json")
    os.utime(r / "cf0499-oldtop", (OLD, OLD))
    return r, outside, gone + ["tmpab12cd_9", "tmpzz99yy88", "tmp.AbCdEf1234", "tmpemptyab1"]


TMPDIRS = []
SURVIVORS = {"tmpqq11ww22", "com.apple.trustd", "claude-501", "remotion-v4.0.1", "intellij-npm-info",
             "tmp_not_generic_name", "rt-file-not-dir", "push-failures-agent-a.log", "rt-symlink",
             "th-runlog-fresh", "tmpfresh001", "cf0499-oldtop"}


def world():
    base = Path(tempfile.mkdtemp(prefix="cf0501-"))
    TMPDIRS.append(base)
    r, outside, gone = build(base)
    return base, r, outside, gone


def test_list_mode_deletes_nothing_and_prints_the_total():
    base, r, _, gone = world()
    before = sorted(os.listdir(r))
    res = run(r)
    assert res.returncode == 0, res.stderr
    assert sorted(os.listdir(r)) == before
    assert f"ИТОГО к удалению: {len(gone)} шт" in res.stdout, res.stdout
    assert all(c in res.stdout for c in ("tmp-factory", "tmp-empty", "th-runlog", "cfNNNN")), res.stdout
    assert not (base / "log").exists()


def test_verbose_prints_each_path():
    _, r, _, gone = world()
    res = run(r, "--verbose")
    assert all(f"{r.resolve()}/{n}" in res.stdout for n in gone), res.stdout


def test_delete_takes_exactly_the_old_factory_trees_and_logs_each_path():
    base, r, outside, gone = world()
    res = run(r, "--delete")
    assert res.returncode == 0, res.stdout + res.stderr
    left = set(os.listdir(r))
    assert not (set(gone) & left), sorted(set(gone) & left)
    assert SURVIVORS <= left, sorted(SURVIVORS - left)
    assert (outside / "keep.txt").exists()
    log = (base / "log").read_text()
    assert "--- до:" in log and "--- после:" in log and all(f"/{n}" in log for n in gone), log[-800:]
    assert all(f"/{n}" in res.stdout for n in gone), res.stdout


def test_threshold_zero_takes_fresh_trees_but_never_neighbours():
    _, r, _, _ = world()
    res = run(r, "--delete", "--min-age-hours", "0")
    assert res.returncode == 0, res.stdout + res.stderr
    left = set(os.listdir(r))
    assert not ({"th-runlog-fresh", "tmpfresh001", "cf0499-oldtop"} & left), sorted(left)
    assert (r / "tmpqq11ww22").exists() and (r / "rt-symlink").is_symlink()


def test_bad_roots_and_arguments_are_refused():
    base, r, _, _ = world()
    env = dict(os.environ, CLEANUP_TMPDIR_ROOT="relative/dir", CLEANUP_LOG=str(base / "log2"))
    res = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)
    assert res.returncode != 0 and "абсолютным" in res.stderr, res.stderr
    res = run(Path("/"), "--delete", log=base / "log3")
    assert res.returncode != 0 and "слишком широкий" in res.stderr, res.stderr
    assert run(r, "--min-age-hours", "abc").returncode != 0
    assert run(r, "--bogus").returncode == 2


# ---------------------------------------------------------------- CF-0720: --json, --only, --by/--via
import json  # noqa: E402


def test_cf0720_json_list_is_the_dry_run_and_deletes_nothing():
    base, r, _, gone = world()
    before = sorted(os.listdir(r))
    res = run(r, "--json", "--by", "user", "--via", "center")
    assert res.returncode == 0, res.stderr
    doc = json.loads(res.stdout)
    assert sorted(os.listdir(r)) == before and not (base / "log").exists()
    assert doc["dry_run"] is True and doc["result"] is None and doc["only"] is None
    assert doc["by"] == "user" and doc["via"] == "center" and doc["root"] == str(r.resolve())
    chosen = {e["name"] for e in doc["entries"] if e["selected"]}
    assert chosen == set(gone), sorted(chosen ^ set(gone))
    assert doc["totals"]["selected"] == len(gone)
    names = {e["name"] for e in doc["entries"]}
    assert "com.apple.trustd" not in names and "claude-501" not in names, names
    fresh = next(e for e in doc["entries"] if e["name"] == "th-runlog-fresh")
    assert fresh["action"] == "keep" and fresh["selected"] is False
    assert set(doc["entries"][0]) == {"name", "class", "action", "kb", "age_h", "selected"}


def test_cf0720_delete_only_takes_the_named_and_reports_the_same_shape():
    base, r, _, gone = world()
    pick = ["rt-abc12345", "tmpemptyab1"]
    dry = json.loads(run(r, "--json", "--only", ",".join(pick)).stdout)
    assert {e["name"] for e in dry["entries"] if e["selected"]} == set(pick), dry
    res = run(r, "--delete", "--json", "--only", pick[0], "--only", pick[1], "--by", "user",
              "--via", "center")
    assert res.returncode == 0, res.stdout + res.stderr
    doc = json.loads(res.stdout)
    left = set(os.listdir(r))
    assert not (set(pick) & left) and (set(gone) - set(pick)) <= left, sorted(left)
    assert doc["dry_run"] is False and sorted(doc["result"]["removed"]) == sorted(pick), doc
    assert doc["result"]["failed"] == [] and doc["only"] == pick
    assert set(doc) == set(dry) and [e["name"] for e in doc["entries"]] == \
        [e["name"] for e in dry["entries"]]
    log = (base / "log").read_text()
    assert "кто: by user, via center" in log and f"только: {pick[0]},{pick[1]}" in log, log
    assert "rm -rf" in res.stderr                       # the log lines go to stderr under --json


def test_cf0720_only_refuses_names_not_in_the_listing_and_deletes_nothing():
    base, r, _, gone = world()
    before = sorted(os.listdir(r))
    for bad in ("nope-not-here", "com.apple.trustd", "th-runlog-fresh", "rt-symlink",
                "../outside", "rt-abc12345,claude-501"):
        res = run(r, "--delete", "--only", bad)
        assert res.returncode == 2 and "не в списке" in res.stderr, (bad, res.stderr)
        assert sorted(os.listdir(r)) == before, bad
    for args in (["--only", " , "], ["--only"], ["--by", " "], ["--via", "x" * 41], ["--by"]):
        res = run(r, "--delete", *args)
        assert res.returncode == 2, (args, res.stdout, res.stderr)
    assert sorted(os.listdir(r)) == before and not (base / "log").exists()


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
