#!/usr/bin/env python3
"""CF-0530: `scripts/cleanup_batch_journals.py` - deleting the test garbage
from the batch journals by the CF-0251 markup.

Everything runs on a synthetic factory root inside a temp dir of this test
(`--root`, CLEANUP_LOG): closed batches with foreign activity after
`batch-done`, a legal rework reopened by `stage-start`, accounting written after
close, a whole-foreign journal with its backfill twin, neighbours that must
survive (a rebuild without `batch-start`, a no-start journal without a twin, a
no-start journal with an accounting line, backfill itself). The live
`pipeline/` is never touched.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "cleanup_batch_journals.py"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
import cleanup_batch_journals as cbj  # noqa: E402
import summary  # noqa: E402

TMPDIRS = []
T0 = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)
_n = [0]


def ts(minutes):
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ev(kind, minute, **kw):
    _n[0] += 1
    e = {"ts": ts(minute), "machine": "m", "kind": kind, "stage": kw.pop("stage", None),
         "video": None, "step": None, "attempt": None, "status": kw.pop("status", None),
         "params": kw.pop("params", None), "duration_s": None, "pid": 1, "id": f"id{_n[0]:06d}",
         "parent": None}
    e.update(kw)
    return e


def marker(status, minute, stage=None):
    return ev("marker", minute, status=status, stage=stage)


def script(minute, stage="video-editor", name="qc_render.py", argv="/var/folders/x/T/rt-1/plan.json"):
    """A start/done pair of a script."""
    s = ev("script", minute, stage=stage, status="start", name=name, params={"args": [argv]})
    d = dict(s, ts=ts(minute + 1), status="done", duration_s=60.0)
    return [s, d]


def usage(minute, stage, inp, computed="2026-09-10T20:00:00Z"):
    return ev("usage", minute, stage=stage, model="opus", role="main", calls=3, computed=computed,
              usage={"input": inp, "cache_write": 1, "cache_read": 2, "output": 5, "thinking": 0})


def write(path, events, extra_raw=b""):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        for e in events:
            fh.write(json.dumps(e).encode() + b"\n")
        fh.write(extra_raw)
    return path


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def build():
    base = Path(tempfile.mkdtemp(prefix="cf0530-test-"))
    TMPDIRS.append(base)
    root = base / "factory"
    pipe = root / "pipeline"
    # A: closed batch, foreign activity after batch-done, accounting after close,
    #    a legal rework (stage-start .. stage-done .. batch-done), more foreign after.
    a = [marker("batch-start", 0), marker("stage-start", 1, "video-editor"), *script(2),
         ev("sample", 3, params={"cpu": 10}), marker("stage-done", 10, "video-editor"),
         marker("batch-done", 11),
         *script(100), ev("sample", 101),                                  # foreign: 3
         usage(102, "video-editor", 1000), ev("gap", 103, params={"start": ts(4), "end": ts(9), "cause": "x"}),
         ev("limits", 104, params={"five_hour": 0.5}),                     # accounting after close: kept
         marker("stage-start", 200, "video-editor"), *script(201), marker("stage-done", 205, "video-editor"),
         marker("batch-done", 206),
         *script(300, stage="content-researcher", name="check_x.py", argv="pipeline/v/A"),  # foreign: 2
         usage(301, "video-editor", 2000, computed="2026-09-11T00:00:00Z")]
    pa = write(pipe / "example-film" / "2026-09-10T1200Z" / "RUN_EVENTS.jsonl", a,
               extra_raw=b"not json at all\n")
    # B: whole-foreign journal (no batch-start, all activity) with a backfill twin.
    pb = write(pipe / "legacy-film" / "2026-08-31T2155Z" / "RUN_EVENTS.jsonl",
               [*script(5), *script(7), ev("sample", 8)])
    twin = write(pipe / "backfill" / "2026-08-31T2155Z" / "RUN_EVENTS.jsonl",
                 [marker("batch-start", 0), *script(1), marker("batch-done", 3), *script(9)])
    # neighbours that must survive
    keep = {
        "rebuild": write(pipe / "rebuilds" / "2026-09-23T1053Z" / "RUN_EVENTS.jsonl", [*script(1)]),
        "no-twin": write(pipe / "legacy-film" / "2026-09-05T0000Z" / "RUN_EVENTS.jsonl", [*script(1)]),
        "acct": write(pipe / "legacy-film" / "2026-09-03T2037Z" / "RUN_EVENTS.jsonl",
                      [*script(1), usage(2, "x", 5)]),
        "open-ok": write(pipe / "example-film" / "2026-09-11T0000Z" / "RUN_EVENTS.jsonl",
                         [*script(-1, name="parent_decisions.py"), marker("batch-start", 0), *script(2),
                          marker("batch-done", 5)]),
        "twin": twin,
    }
    write(pipe / "backfill" / "2026-09-03T2037Z" / "RUN_EVENTS.jsonl", [marker("batch-start", 0)])
    keep_sha = {k: sha(p) for k, p in keep.items()}
    return base, root, pa, pb, keep, keep_sha


def run(root, *args, log=None):
    env = dict(os.environ, CLEANUP_LOG=str(log or root.parent / "cleanup.log"))
    env.pop("CLEANUP_JOURNALS_ROOT", None)
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root), *args], env=env,
                          capture_output=True, text=True, timeout=240)


def test_classify_follows_cf0251_markup():
    lines = [json.dumps(e).encode() + b"\n" for e in [
        *script(-5), marker("batch-start", 0), *script(1), marker("batch-done", 2), *script(3),
        marker("stage-done", 4, "x"), ev("sample", 5), usage(6, "x", 1), marker("stage-start", 7, "x"),
        *script(8), marker("batch-done", 9), ev("child", 10, status="start"), marker("batch-start", 11),
        *script(12)]]
    cls, started = cbj.classify(lines)
    assert started
    kinds = [(json.loads(r)["kind"], json.loads(r).get("ts")) for r, f in cls if f]
    # after the 1st batch-done: script x2 + sample (stage-done does not reopen); usage kept;
    # after the 2nd batch-done: the child; a pre-batch-start script is not foreign.
    assert [k for k, _ in kinds] == ["script", "script", "sample", "child"], kinds


def test_list_mode_names_and_changes_nothing():
    base, root, pa, pb, keep, keep_sha = build()
    a_sha, b_sha = sha(pa), sha(pb)
    res = run(root)
    assert res.returncode == 0, res.stderr
    out = res.stdout
    assert "example-film/2026-09-10T1200Z/RUN_EVENTS.jsonl" in out and "2026-08-31T2155Z" in out, out
    assert "[журнал целиком]" in out
    assert "журналов целиком 1" in out and "строк из 1 журналов 5 " in out, out
    for name in ("rebuilds", "2026-09-05T0000Z", "2026-09-03T2037Z", "2026-09-11T0000Z", "backfill"):
        assert name not in out.split("итого")[0], (name, out)
    assert sha(pa) == a_sha and sha(pb) == b_sha
    assert all(sha(keep[k]) == v for k, v in keep_sha.items())
    assert "ничего не удалено" in (root.parent / "cleanup.log").read_text()


def test_delete_cuts_foreign_keeps_accounting():
    base, root, pa, pb, keep, keep_sha = build()
    before = pa.read_bytes()
    mode = 0o640
    os.chmod(pa, mode)
    res = run(root, "--delete")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not pb.exists() and pb.parent.is_dir()
    assert all(sha(keep[k]) == v for k, v in keep_sha.items()), "a neighbour was touched"
    after = pa.read_bytes()
    assert len(before.splitlines()) - len(after.splitlines()) == 5
    assert (pa.stat().st_mode & 0o777) == mode
    assert b"not json at all\n" in after
    # every non-activity line survives byte for byte, in order
    keep_lines = [r for r in before.splitlines() if not cbj.is_activity(r)]
    assert [r for r in after.splitlines() if not cbj.is_activity(r)] == keep_lines
    # the legal rework's script survived, the foreign ones did not
    names = [json.loads(r).get("ts") for r in after.splitlines() if cbj.is_activity(r)]
    assert ts(201) in names and ts(100) not in names and ts(300) not in names
    # CF-0530 п.2: the summary's accounting on the copy "before" and on the result "after"
    line = next(l for l in res.stdout.splitlines() if l.startswith("копия оригиналов:"))
    backup = Path(line.split(":", 1)[1].strip())
    TMPDIRS.append(backup)
    copy = backup / "pipeline" / "example-film" / "2026-09-10T1200Z" / "RUN_EVENTS.jsonl"
    assert copy.read_bytes() == before
    assert (backup / "pipeline" / "legacy-film" / "2026-08-31T2155Z" / "RUN_EVENTS.jsonl").is_file()
    db = summary.load(pa.parent, events=[json.loads(r) for r in before.splitlines() if r.startswith(b"{")])
    da = summary.load(pa.parent)
    for k in ("usage", "limits", "limit_hits", "quota", "markers", "wall", "stages"):
        assert json.dumps(db[k], default=str, sort_keys=True) == json.dumps(da[k], default=str, sort_keys=True), k
    tb, ta = summary.tokens(db), summary.tokens(da)
    assert tb["total"] == ta["total"] and tb["by_stage"] == ta["by_stage"]
    assert ta["total"]["input"] == 2000                     # the newest usage generation
    assert [g["params"] for g in (json.loads(r) for r in after.splitlines() if r.startswith(b"{"))
            if g["kind"] == "gap"] == [{"start": ts(4), "end": ts(9), "cause": "x"}]
    log = (root.parent / "cleanup.log").read_text()
    assert "УДАЛЁН журнал целиком" in log and "ВЫРЕЗАНО" in log and "учёт сводки совпал" in log
    # idempotent: a second run finds nothing
    res2 = run(root)
    assert res2.returncode == 0 and "чистить нечего" in res2.stdout, res2.stdout


def test_refuses_while_a_batch_is_open():
    base, root, pa, pb, keep, keep_sha = build()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    write(root / "pipeline" / "example-film" / "2026-10-04T0000Z" / "RUN_EVENTS.jsonl",
          [dict(marker("batch-start", 0), ts=now)])
    a_sha, b_sha = sha(pa), sha(pb)
    res = run(root, "--delete")
    assert res.returncode == 1 and "открыт батч" in res.stderr, res.stdout + res.stderr
    assert sha(pa) == a_sha and pb.exists() and sha(pb) == b_sha


def test_mismatch_restores_from_copy():
    base, root, pa, pb, keep, keep_sha = build()
    before = pa.read_bytes()
    os.environ["CLEANUP_LOG"] = str(base / "log-mm")
    cbj.LOG = base / "log-mm"
    real, calls = cbj.accounting, [0]

    def fake(data, bdir):
        calls[0] += 1
        return real(data, bdir) + ("x" if calls[0] == 2 else "")
    cbj.accounting = fake
    cbj.active_batches = lambda root: []
    saved_tmp, tempfile.tempdir = tempfile.tempdir, str(base)          # the copy "before" lands in base
    try:
        rc = cbj.main(["--root", str(root), "--delete"])
    finally:
        cbj.accounting, tempfile.tempdir = real, saved_tmp
    assert rc == 1
    assert pa.read_bytes() == before, "the journal was not restored"
    assert "восстановлен из копии" in (base / "log-mm").read_text()
    assert not list(pa.parent.glob(".RUN_EVENTS.jsonl.cf0530-*")), "temp file left behind"


def test_refuses_relative_root_and_missing_pipeline():
    base = Path(tempfile.mkdtemp(prefix="cf0530-test-"))
    TMPDIRS.append(base)
    env = dict(os.environ, CLEANUP_LOG=str(base / "log"))
    res = subprocess.run([sys.executable, str(SCRIPT), "--root", "relative/dir"], env=env,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 1 and "абсолютным" in res.stderr, res.stderr
    res = subprocess.run([sys.executable, str(SCRIPT), "--root", str(base)], env=env,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 1 and "нет каталога pipeline" in res.stderr, res.stderr


def test_default_root_is_the_main_checkout():
    """From a version worktree the default root is the main checkout (the live pipeline/)."""
    cp = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                        capture_output=True, text=True, timeout=10)
    if cp.returncode != 0:
        return
    os.environ.pop("CLEANUP_JOURNALS_ROOT", None)
    assert cbj.default_root() == Path(cp.stdout.strip()).parent


# ---------------------------------------------------------------- CF-0720: by/via, dry run
def _report(rows):
    return [{k: r[k] for k in ("rel", "mode", "lines", "bytes", "drop", "after_lines",
                               "after_bytes")} for r in rows]


def test_cf0720_dry_run_reports_what_the_real_run_does_and_touches_nothing():
    base, root, pa, pb, keep, keep_sha = build()
    log = base / "log-dry"
    saved = (cbj.LOG, cbj.active_batches, tempfile.tempdir)
    cbj.LOG, cbj.active_batches, tempfile.tempdir = log, (lambda r: []), str(base)
    try:
        a_sha, b_sha = sha(pa), sha(pb)
        dry_rows = cbj.plan(root.resolve())
        got = cbj.delete(root.resolve(), dry_rows, by="user", via="center", dry_run=True)
        assert got is None and sha(pa) == a_sha and pb.exists() and sha(pb) == b_sha
        assert not log.exists(), "a dry run wrote the cleanup log"
        assert not list(base.glob("cf0530-journals-*")), "a dry run made the copy"
        assert all(r["applied"] is False for r in dry_rows)
        real_rows = cbj.plan(root.resolve())
        backup = cbj.delete(root.resolve(), real_rows, by="user", via="center")
        assert backup is not None and backup.is_dir() and not pb.exists()
        assert all(r["applied"] is True for r in real_rows)
        assert _report(dry_rows) == _report(real_rows), (_report(dry_rows), _report(real_rows))
        a = next(r for r in real_rows if r["mode"] == "lines")
        assert a["after_lines"] == len(pa.read_bytes().splitlines()) == a["lines"] - 5
        assert a["after_bytes"] == len(pa.read_bytes())
        assert "кто: by user, via center" in log.read_text()
    finally:
        cbj.LOG, cbj.active_batches, tempfile.tempdir = saved


def test_cf0720_bad_by_via_and_an_open_batch_refuse_the_dry_run_too():
    base, root, pa, pb, keep, keep_sha = build()
    saved = (cbj.LOG, cbj.active_batches)
    cbj.LOG = base / "log-bad"
    try:
        rows = cbj.plan(root.resolve())
        cbj.active_batches = lambda r: []
        for kw in ({"by": ""}, {"via": "a\nb"}, {"by": "x" * 41}, {"via": 1}):
            for dry in (True, False):
                try:
                    cbj.delete(root.resolve(), rows, dry_run=dry, **kw)
                except cbj.Stop as e:
                    assert "by=" in str(e) or "via=" in str(e), e
                else:
                    raise AssertionError(f"{kw} dry_run={dry} was taken")
        cbj.active_batches = lambda r: ["example-film/2026-10-04T0000Z"]
        try:
            cbj.delete(root.resolve(), rows, by="user", via="center", dry_run=True)
        except cbj.Stop as e:
            assert "открыт батч" in str(e)
        else:
            raise AssertionError("a dry run under an open batch answered")
        assert pb.exists() and not (base / "log-bad").exists()
        # a journal that changed since the plan stops the dry run as it stops the real one
        cbj.active_batches = lambda r: []
        with open(pa, "ab") as fh:
            fh.write(b"{}\n")
        try:
            cbj.delete(root.resolve(), rows, dry_run=True)
        except cbj.Stop as e:
            assert "изменился" in str(e)
        else:
            raise AssertionError("a changed journal passed the dry run")
    finally:
        cbj.LOG, cbj.active_batches = saved


def test_cf0720_cli_by_via_go_into_the_log_and_a_bad_one_stops():
    base, root, pa, pb, keep, keep_sha = build()
    res = run(root, "--delete", "--by", "", "--via", "cli")
    assert res.returncode == 1 and "by=" in res.stderr, res.stderr
    assert pb.exists()
    res = run(root, "--delete", "--by", "user", "--via", "cli")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "кто: by user, via cli" in (root.parent / "cleanup.log").read_text()
    line = next(l for l in res.stdout.splitlines() if l.startswith("копия оригиналов:"))
    TMPDIRS.append(Path(line.split(":", 1)[1].strip()))


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
