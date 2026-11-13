#!/usr/bin/env python3
"""CC-0104: the month archive (step a of `scripts/archive_publish_month.py`,
`--publish-only`) from the center, plan -> confirm (`api/maintenance.py`):

    POST /api/maintenance/archive/plan        --dry-run --json --publish-only - nothing touched
    POST /api/maintenance/archive {confirm}   the same dry run, then --by user --via center

In-process (the TestClient) against stand-in factory roots in a temp dir
(`tests/test_cc_api_batches.py` `factory_tree`: a git repo of its own, hooks
off) and a temp folder standing in for the archive volume
(`--skip-mount-check`, the script's own seam for tests), the script's log
and its questions in the test's temp dir, the day fixed (`--today`). The
real script runs - on those temp trees only: the factory root is never
named (`ARCHIVE_ARGS`, `--root` the temp root, asserted on each command).

What is pinned: the plan is the factory's document (the zip as `<volume>:`,
what leaves `publish/`, git rm / delete), nothing touched; the confirm moves
the month - the zip on the volume, the day folder gone, one commit with
`Requested-by: user via center`; the token once only, and nothing owed
afterwards; a volume gone since the plan is 409 `volume_missing` with the
factory's own line and nothing touched; no volume at all - no token; a
month that changed is `check_changed`; an open batch - no token, and the
confirm refuses `batch_open`; a real run that fails or prints no document
is `factory_broken`; no absolute path in any answer.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from api import maintenance                           # noqa: E402
import test_cc_api_batches as tb                      # noqa: E402

TMP = tb.TMP
H = tb.H
PLAN, RUN = "/api/maintenance/archive/plan", "/api/maintenance/archive"
DAY = "publish/reel/2026-09-22"
_N = [0]


def fresh(name):
    _N[0] += 1
    d = TMP / f"am-{name}-{_N[0]}"
    d.mkdir(parents=True)
    return d


def no_abs(text):
    for bad in (str(TMP), str(TMP.resolve()), str(Path.home()), str(ROOT)):
        assert bad not in text, (bad, text[:2000])


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.parts}


class World:
    """A factory root owing September (one video of reel), a temp volume, the
    script's seams pointed into the test's temp dir."""

    def __init__(self, mounted=True):
        self.root = tb.factory_tree()
        day = self.root / DAY
        day.mkdir(parents=True)
        (day / "x.mp4").write_bytes(b"mp4-bytes")
        (day / "x.md").write_text("# x\n", encoding="utf-8")
        with open(self.root / ".gitignore", "a", encoding="utf-8") as fh:
            fh.write("*.mp4\n")
        tb.git(self.root, "add", "-A")
        tb.git(self.root, "commit", "-q", "-m", "september")
        self.vol = fresh("vol") / "Archive-Stand-in"
        if mounted:
            self.vol.mkdir()
        self.side = fresh("side")

    def __enter__(self):
        self.saved = list(maintenance.ARCHIVE_ARGS), maintenance.ARCHIVE_VOLUME, \
            maintenance.run_archive, maintenance.run_archive_apply
        self.cmds = []
        maintenance.ARCHIVE_ARGS[:] = ["--volume", str(self.vol), "--skip-mount-check",
                                       "--today", "2026-10-01",
                                       "--log", str(self.side / "archive.log"),
                                       "--needs-you-dir", str(self.side / "ny"),
                                       "--min-free-gb", "0"]
        maintenance.ARCHIVE_VOLUME = str(self.vol)
        dry, real = maintenance.run_archive, maintenance.run_archive_apply

        def seen(run):
            def go(cmd):
                i = cmd.index("--root")
                assert cmd[i + 1] == str(self.root), "only the temp root, never the factory's"
                self.cmds.append(cmd)
                return run(cmd)
            return go
        maintenance.run_archive, maintenance.run_archive_apply = seen(dry), seen(real)
        self.c = tb.client(self.root)
        return self

    def __exit__(self, *exc):
        (maintenance.ARCHIVE_ARGS[:], maintenance.ARCHIVE_VOLUME, maintenance.run_archive,
         maintenance.run_archive_apply) = self.saved

    def post(self, path, body=None):
        r = self.c.post(path, headers=H, json=body)
        no_abs(r.text)
        return r.status_code, r.json()


def test_the_plan_then_the_confirm_moves_the_month_and_commits_by_user_via_center():
    with World() as w:
        h0, before = tb.git(w.root, "rev-parse", "HEAD"), tree(w.root)
        code, p = w.post(PLAN)
        assert code == 200 and p["ok"] and p["confirm"] and p["expires_in_s"] == 120, p
        assert (p["action"], p["by"], p["via"], p["mounted"]) == \
            ("publish_month_archive", "user", "center", True), p
        assert "--dry-run" in p["command"] and "--json" in p["command"] and \
            "--publish-only" in p["command"], p["command"]
        assert "--by user --via center" in p["apply_command"] and \
            "--dry-run" not in p["apply_command"], p["apply_command"]
        assert p["today"] == "2026-10-01" and p["volume"] == "Archive-Stand-in", p
        assert [(d["channel"], d["month"], d["files"]) for d in p["debt"]] == \
            [("reel", "2026-09", 2)], p["debt"]
        [job] = p["jobs"]
        assert (job["channel"], job["month"], job["action"], job["status"], job["members"]) == \
            ("reel", "2026-09", "create", "planned", 2), job
        assert job["zip"] == "Archive-Stand-in:shorts-content-factory-publish/reel/2026-09.zip", job
        assert sorted((f["path"], f["kind"], f["op"]) for f in job["from_publish"]) == \
            [(f"{DAY}/x.md", "md", "git rm"), (f"{DAY}/x.mp4", "mp4", "delete")], job
        assert job["day_dirs"] == [DAY] and p["enough_space"] is True, p
        assert tree(w.root) == before and list(w.vol.iterdir()) == [], "a plan touches nothing"
        assert list(w.side.iterdir()) == [], "the dry run writes neither the log nor a question"
        code, b = w.post(RUN, {"confirm": p["confirm"]})
        assert code == 200, b
        assert b["written"] and (b["by"], b["via"]) == ("user", "center"), b
        assert [(j["channel"], j["month"], j["status"]) for j in b["jobs"]] == \
            [("reel", "2026-09", "moved")], b["jobs"]
        assert b["committed"] is True and b["exit_code"] == 0, b
        assert (b["commit"]["by"], b["commit"]["via"]) == ("user", "center"), b["commit"]
        assert "--by" in w.cmds[-1] and "--dry-run" not in w.cmds[-1], w.cmds[-1]
        assert len([c for c in w.cmds if "--dry-run" in c]) == 2, "plan + confirm dry runs"
        zp = w.vol / "shorts-content-factory-publish" / "reel" / "2026-09.zip"
        assert zp.is_file() and zp.with_name("2026-09.manifest.json").is_file()
        assert not (w.root / DAY).exists(), "the month left publish/"
        assert tb.git(w.root, "rev-parse", "HEAD") != h0
        msg = tb.git(w.root, "log", "-1", "--format=%B")
        assert "Requested-by: user via center" in msg, msg
        assert any("кто: by user, via center" in ln for ln in b["lines"]), b["lines"]
        # the token once only; nothing owed now - no token
        code, r = w.post(RUN, {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "confirm_unknown", r
        code, again = w.post(PLAN)
        assert code == 200 and not again["ok"] and again["confirm"] is None, again
        assert "долга архива нет" in again["why"], again


def test_a_volume_gone_since_the_plan_is_volume_missing_and_nothing_is_touched():
    with World() as w:
        code, p = w.post(PLAN)
        assert p["ok"], p
        shutil.rmtree(w.vol)
        before, h0 = tree(w.root), tb.git(w.root, "rev-parse", "HEAD")
        code, r = w.post(RUN, {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "volume_missing", r
        assert set(r) == {"message", "code", "details"}, r
        assert "не смонтирован" in r["message"] and "ничего не трогаю" in r["message"], r
        assert all("--dry-run" in c for c in w.cmds), "the real run never started"
        assert tree(w.root) == before and tb.git(w.root, "rev-parse", "HEAD") == h0


def test_no_volume_at_all_is_a_plan_without_a_token():
    with World(mounted=False) as w:
        code, p = w.post(PLAN)
        assert code == 200 and not p["ok"] and p["confirm"] is None, p
        assert p["mounted"] is False and "не смонтирован" in p["why"], p
        assert p["jobs"][0]["action"] is None, p["jobs"]


def test_a_month_that_changed_is_check_changed():
    with World() as w:
        code, p = w.post(PLAN)
        assert p["ok"], p
        late = w.root / "publish" / "reel" / "2026-09-23"
        late.mkdir()
        (late / "y.md").write_text("# y\n", encoding="utf-8")
        before = tree(w.root)
        code, r = w.post(RUN, {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert tree(w.root) == before and list(w.vol.iterdir()) == []


def test_an_open_batch_holds_the_archive():
    with World() as w:
        code, p = w.post(PLAN)
        assert p["ok"], p
        tb.write_batch(w.root, "reel", "going", [tb.marker("batch-start", hours_ago=0.01),
                                                 tb.marker("stage-start", "trend-hunter",
                                                           hours_ago=0.005)])
        before = tree(w.root)
        code, r = w.post(RUN, {"confirm": p["confirm"]})
        assert code == 409 and r["code"] == "batch_open", r
        assert "reel/going" in r["message"], r
        assert tree(w.root) == before and list(w.vol.iterdir()) == []
        code, p = w.post(PLAN)
        assert not p["ok"] and p["confirm"] is None and p["open_batches"] == ["reel/going"], p
        assert "Открыт батч" in p["why"], p


class Ran:
    """A stand-in run: what `child.start` gives, with a fixed answer."""

    def __init__(self, out, err="", code=0):
        self.out, self.err, self.returncode = out, err, code

    def communicate(self, timeout=None):
        return self.out, self.err


def test_a_real_run_that_fails_or_says_nothing_is_factory_broken():
    for answer in (lambda d: Ran(json.dumps(dict(d, exit_code=1, lines=["сверка не сошлась"])),
                                 code=1),
                   lambda d: Ran("not a document", "Traceback ...", code=2)):
        with World() as w:
            code, p = w.post(PLAN)
            assert p["ok"], p

            def fake(cmd, answer=answer):
                out, _err = maintenance.child.start(
                    [c for c in cmd if c not in ("--by", "user", "--via", "center")] +
                    ["--dry-run"], timeout=60).communicate()
                return answer(json.loads(out))
            maintenance.run_archive_apply = fake        # World puts the seam back
            code, r = w.post(RUN, {"confirm": p["confirm"]})
            assert code == 500 and r["code"] == "factory_broken", r
            assert set(r) == {"message", "code", "details"}, r
            assert (w.root / DAY).is_dir(), "the stand-in run moved nothing"


if __name__ == "__main__":
    import traceback
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            traceback.print_exc()
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
