#!/usr/bin/env python3
"""CC-0032: maintenance and spend (`api/maintenance.py`, `/api/maintenance/...`).

In-process (starlette's TestClient) against stand-in factory roots under a temp
dir (`test_cc_api_batches.factory_tree` - a git repo on main, the working
factory): no live factory, no network, no real archive or cleanup of the
factory. The scripts run for real only against those temp trees:
`archive_publish_month.py --dry-run` (a temp volume, `--skip-mount-check`,
a temp log and journal of questions), `cleanup_batch_journals.plan` /
`delete` (its log and its copy of the originals in this test's temp dir; its
`runlog batch-active` asks the temp root).

What is pinned:

* the contract: the routes and their methods, version 0.48.0, the two writes
  guarded (`require_writes`, `GUARDED` and the Spy of tests/test_cc_api_writes.py);
* the overview: every script of the task, read / plan_confirm / none, and why;
* usage: the newest generation of the batch's `usage` events and the totals of
  `usage.totals`; none yet - `ok: false` and the factory's hint; an unknown
  batch - 404 without the root's path;
* compare: the same stages - `same`, exit 0; a stage one side ran - a defect;
  a reference that is not `<channel>/<batch>` - 422;
* the archive: the real dry run on a temp tree - its plan's lines, the volume
  as `<name>:`, nothing changed; `?monthly=true` drops `--publish-only`; a CLI
  that does not start is `error`; no confirm;
* the journals: the plan (the script's rows, totals, a token); the confirm
  cuts the foreign lines through `delete(by, via)`, which says who (its `кто: by
  user, via center`); a changed journal is `check_changed` and nothing is
  touched; an open batch - the plan has no token, the confirm refuses
  `batch_open`; a token once only; nothing to clean - no token;
* no absolute path anywhere in an answer.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.routing import APIRoute                  # noqa: E402

import api                                            # noqa: E402
from api import maintenance                           # noqa: E402
from api.app import create_app                        # noqa: E402
from api.settings import Settings                     # noqa: E402
import test_cc_api_batches as tb                      # noqa: E402
import test_cc_api_writes as tw                       # noqa: E402

TMP = tb.TMP
H = tb.H
_N = [0]


def fresh(name):
    _N[0] += 1
    d = TMP / f"mt-{name}-{_N[0]}"
    d.mkdir(parents=True)
    return d


def no_abs(text):
    for bad in (str(TMP), str(TMP.resolve()), str(Path.home()), str(ROOT)):
        assert bad not in text, (bad, text[:2000])


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.parts}


def ev(kind, minute, **kw):
    e = {"ts": f"2026-09-10T12:{minute:02d}:00.000Z", "machine": "m", "kind": kind,
         "stage": kw.pop("stage", None), "status": kw.pop("status", None), "pid": 1,
         "id": f"id{kind}{minute}"}
    e.update(kw)
    return e


def write_events(d, events):
    d.mkdir(parents=True, exist_ok=True)
    (d / "RUN_EVENTS.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events),
                                        encoding="utf-8")
    return d


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_maintenance_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    want = {"/api/maintenance": ["get"], "/api/maintenance/usage/{channel}/{batch_id}": ["get"],
            "/api/maintenance/compare": ["get"], "/api/maintenance/archive": ["get", "post"],
            "/api/maintenance/archive/plan": ["post"],
            "/api/maintenance/journals/plan": ["post"], "/api/maintenance/journals": ["post"]}
    for path, methods in want.items():
        assert sorted(spec["paths"][path]) == methods, (path, spec["paths"][path])
    for m in ("Maintenance", "UsageReport", "CompareRuns", "ArchiveDryRun", "JournalsPlan",
              "JournalsResult", "MaintenanceProblem", "ArchivePlan", "ArchiveResult"):
        assert m in spec["components"]["schemas"], m
    codes = spec["components"]["schemas"]["MaintenanceProblem"]["properties"]["code"]["enum"]
    assert {"batch_open", "check_changed", "confirm_unknown", "bad_call",
            "volume_missing"} <= set(codes)


def test_the_writes_are_guarded():
    app = create_app(Settings(factory_root=TMP), token="tok")
    writes = {("POST", "/api/maintenance/journals/plan"), ("POST", "/api/maintenance/journals"),
              # CC-0105 (api/pool.py, tests/test_cc_api_pool.py)
              ("POST", "/api/maintenance/pool/release/plan"),
              ("POST", "/api/maintenance/pool/release"),
              # CC-0104 (tests/test_cc_api_archive_month.py)
              ("POST", "/api/maintenance/archive/plan"), ("POST", "/api/maintenance/archive")}
    seen = set()
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path.startswith("/api/maintenance"):
            for m in r.methods - {"HEAD"}:
                seen.add((m, r.path))
                guarded = app.state.require_writes in [d.call for d in r.dependant.dependencies]
                assert guarded == ((m, r.path) in writes), (m, r.path)
    assert writes <= seen
    assert writes <= tw.GUARDED
    assert set(tw.Spy.NAMES[maintenance]) == {"journals_plan", "journals_clean",
                                              "archive_plan", "archive_run"}


def test_the_overview_says_every_script():
    c = tb.client(tb.factory_tree())
    r = c.get("/api/maintenance")
    assert r.status_code == 200, r.text
    got = {s["script"]: s["exposed"] for s in r.json()["scripts"]}
    assert got == {"scripts/usage_report.py": "read", "scripts/compare_runs.py": "read",
                   "scripts/archive_publish_month.py": "plan_confirm",
                   "scripts/cleanup_batch_journals.py": "plan_confirm",
                   "scripts/runlog pool-release": "plan_confirm",
                   "scripts/cleanup_tmpdir.sh": "none", "scripts/cleanup_1_6_archive.sh": "none"}
    for s in r.json()["scripts"]:
        assert s["why"], s


# --------------------------------------------------------------------- usage
def usage_ev(minute, stage, inp, computed):
    return ev("usage", minute, stage=stage, model="opus", role="main", agent=None,
              session="s1", calls=2, minutes=1.5, first=1.0, last=91.0, computed=computed,
              usage={"input": inp, "cache_write": 10, "cache_read": 100, "output": 5,
                     "thinking": 0})


def test_usage_is_the_newest_generation_and_its_totals():
    root = tb.factory_tree()
    write_events(root / "pipeline" / "reel" / "b1", [
        ev("marker", 0, status="batch-start"),
        usage_ev(1, "trend-hunter", 999, "2026-09-10T12:01:00Z"),
        usage_ev(2, "trend-hunter", 40, "2026-09-10T12:30:00Z"),
        usage_ev(3, "video-editor", 60, "2026-09-10T12:30:00Z")])
    write_events(root / "pipeline" / "reel" / "b2", [ev("marker", 0, status="batch-start")])
    c = tb.client(root)
    r = c.get("/api/maintenance/usage/reel/b1")
    assert r.status_code == 200, r.text
    b = r.json()
    no_abs(r.text)
    assert b["ok"] and b["batch"] == "reel/b1" and b["computed"] == "2026-09-10T12:30:00Z"
    assert b["events"] == "pipeline/reel/b1/RUN_EVENTS.jsonl", b["events"]
    assert [x["stage"] for x in b["rows"]] == ["trend-hunter", "video-editor"]
    assert b["totals"]["input"] == 100 and b["totals"]["calls"] == 4
    assert b["totals"]["total"] == 100 + 20 + 200 + 10
    r = c.get("/api/maintenance/usage/reel/b2")
    assert r.status_code == 200 and not r.json()["ok"] and r.json()["rows"] == []
    assert "usage_from_transcripts.py reel/b2 --write" in r.json()["why"]
    r = c.get("/api/maintenance/usage/reel/nope")
    assert r.status_code == 404 and r.json()["code"] == "unknown_batch", r.text
    assert set(r.json()) == {"message", "code", "details"}
    no_abs(r.text)


# --------------------------------------------------------------------- compare
def run_batch(d, stages):
    evs = [ev("marker", 0, status="batch-start")]
    for i, s in enumerate(stages, 1):
        evs += [ev("marker", 2 * i, status="stage-start", stage=s),
                ev("marker", 2 * i + 1, status="stage-done", stage=s)]
    evs.append(ev("marker", 59, status="batch-done"))
    write_events(d, evs)
    (d / "01-trend-hunter.json").write_text("{}", encoding="utf-8")
    return d


def test_compare_holds_two_batches():
    root = tb.factory_tree()
    run_batch(root / "pipeline" / "reel" / "manual", ["trend-hunter", "video-editor"])
    run_batch(root / "pipeline" / "reel" / "exec", ["trend-hunter", "video-editor"])
    run_batch(root / "pipeline" / "reel" / "short", ["trend-hunter"])
    c = tb.client(root)
    r = c.get("/api/maintenance/compare", params={"manual": "reel/manual", "executor": "reel/exec"})
    assert r.status_code == 200, r.text
    no_abs(r.text)
    b = r.json()
    assert b["same"] and b["exit_code"] == 0 and b["defects"] == []
    assert (b["manual"], b["executor"]) == ("reel/manual", "reel/exec")
    assert b["stages"]["manual"] == ["trend-hunter", "video-editor"]
    r = c.get("/api/maintenance/compare", params={"manual": "reel/manual", "executor": "reel/short"})
    assert r.status_code == 200 and not r.json()["same"] and r.json()["exit_code"] == 1
    assert any("video-editor" in d for d in r.json()["defects"]), r.json()["defects"]
    r = c.get("/api/maintenance/compare", params={"manual": "manual", "executor": "reel/exec"})
    assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
    r = c.get("/api/maintenance/compare", params={"manual": "reel/x", "executor": "reel/exec"})
    assert r.status_code == 404 and r.json()["code"] == "unknown_batch", r.text
    no_abs(r.text)


# --------------------------------------------------------------------- the archive (read only)
def test_the_archive_dry_run_on_a_temp_tree():
    root = tb.factory_tree()
    day = root / "publish" / "reel" / "2026-09-22"
    day.mkdir(parents=True)
    (day / "x.mp4").write_bytes(b"mp4")
    (day / "x.md").write_text("# x\n", encoding="utf-8")
    vol = fresh("vol") / "Archive-Stand-in"
    vol.mkdir()
    side = fresh("side")
    before = tree(root)
    saved = list(maintenance.ARCHIVE_ARGS), maintenance.ARCHIVE_VOLUME
    maintenance.ARCHIVE_ARGS[:] = ["--volume", str(vol), "--skip-mount-check", "--today",
                                   "2026-10-01", "--log", str(side / "archive.log"),
                                   "--needs-you-dir", str(side / "ny"), "--min-free-gb", "0"]
    maintenance.ARCHIVE_VOLUME = str(vol)
    try:
        r = tb.client(root).get("/api/maintenance/archive")
    finally:
        maintenance.ARCHIVE_ARGS[:], maintenance.ARCHIVE_VOLUME = saved
    assert r.status_code == 200, r.text
    no_abs(r.text)
    b = r.json()
    assert b["ok"] and b["exit_code"] == 0 and b["dry_run"] and not b["monthly"], b
    assert b["confirm_available"] is True and b["volume"] == "Archive-Stand-in"
    assert b["plan_action"] == "publish_month_archive", b
    assert "--publish-only" in b["command"] and "--dry-run" in b["command"]
    text = "\n".join(b["lines"])
    assert "план reel 2026-09: соберу Archive-Stand-in:shorts-content-factory-publish/reel/2026-09.zip" \
        in text, text
    assert "сухой прогон" in text
    assert tree(root) == before
    assert list(side.iterdir()) == [] and list(vol.iterdir()) == []


def test_the_archive_monthly_flag_and_a_cli_that_does_not_start():
    root = tb.factory_tree()
    seen = []
    orig = maintenance.run_archive

    def stand_in(cmd):
        seen.append(cmd)
        raise OSError("no python")
    maintenance.run_archive = stand_in
    try:
        r = tb.client(root).get("/api/maintenance/archive", params={"monthly": "true"})
    finally:
        maintenance.run_archive = orig
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["monthly"] and not b["ok"] and b["exit_code"] is None and "did not start" in b["error"]
    assert "--dry-run" in seen[0] and "--publish-only" not in seen[0]
    assert "--apply" not in seen[0] and "--delete" not in " ".join(seen[0])
    no_abs(r.text)


# --------------------------------------------------------------------- the journals (a write)
class Journals:
    """The script's log and its copy of the originals in this test's temp dir."""

    def __enter__(self):
        self.cbj = maintenance._journals()
        self.side = fresh("journals-side")
        self.saved = self.cbj.LOG, tempfile.tempdir
        self.cbj.LOG = self.side / "cleanup_batch_journals.log"
        tempfile.tempdir = str(self.side)
        return self

    def __exit__(self, *exc):
        self.cbj.LOG, tempfile.tempdir = self.saved


def closed_batch_with_garbage(root, name="b1"):
    d = root / "pipeline" / "reel" / name
    write_events(d, [ev("marker", 0, status="batch-start"),
                     ev("marker", 1, status="stage-start", stage="trend-hunter"),
                     ev("script", 2, stage="trend-hunter", name="x.py"),
                     ev("marker", 3, status="stage-done", stage="trend-hunter"),
                     ev("marker", 4, status="batch-done"),
                     ev("script", 5, stage="video-editor", name="qc.py"),
                     ev("sample", 6, stage="video-editor")])
    return d / "RUN_EVENTS.jsonl"


def test_the_journals_plan_and_confirm_cut_the_foreign_lines():
    root = tb.factory_tree()
    j = closed_batch_with_garbage(root)
    with Journals() as w:
        c = tb.client(root)
        r = c.post("/api/maintenance/journals/plan", headers=H)
        assert r.status_code == 200, r.text
        no_abs(r.text)
        p = r.json()
        assert p["ok"] and p["confirm"] and p["expires_in_s"] == 120, p
        assert p["by"] == "user" and p["via"] == "center" and p["open_batches"] == []
        assert [(x["rel"], x["mode"], x["lines"], x["drop"], x["after"]) for x in p["journals"]] \
            == [("pipeline/reel/b1/RUN_EVENTS.jsonl", "lines", 7, 2, 5)]
        assert p["totals"]["cut_lines"] == 2 and p["totals"]["journals"] == 1
        assert len(j.read_text().splitlines()) == 7, "the plan touched the journal"
        r = c.post("/api/maintenance/journals", headers=H, json={"confirm": p["confirm"]})
        assert r.status_code == 200, r.text
        no_abs(r.text)
        b = r.json()
        assert b["written"] and b["by"] == "user" and b["via"] == "center"
        kinds = [json.loads(x)["kind"] for x in j.read_text().splitlines()]
        assert kinds == ["marker", "marker", "script", "marker", "marker"], kinds
        text = "\n".join(b["lines"])
        assert "кто: by user, via center" in text, text
        assert "центр:" not in text, "the factory's delete(by, via) logs who, not the API"
        assert [(x["rel"], x["after_lines"], x["applied"]) for x in b["done"]] == \
            [("pipeline/reel/b1/RUN_EVENTS.jsonl", 5, True)], b["done"]
        assert "ВЫРЕЗАНО: pipeline/reel/b1/RUN_EVENTS.jsonl" in text, text
        assert b["backup"] and b["backup"].startswith(".../cf0530-journals-"), b["backup"]
        assert "by user, via center" in w.cbj.LOG.read_text(encoding="utf-8")
        # the token once only
        r = c.post("/api/maintenance/journals", headers=H, json={"confirm": p["confirm"]})
        assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
        # nothing left: no token
        r = c.post("/api/maintenance/journals/plan", headers=H)
        assert r.status_code == 200 and not r.json()["ok"] and r.json()["confirm"] is None


def test_a_changed_journal_is_check_changed_and_nothing_is_touched():
    root = tb.factory_tree()
    j = closed_batch_with_garbage(root)
    with Journals():
        c = tb.client(root)
        p = c.post("/api/maintenance/journals/plan", headers=H).json()
        with open(j, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev("child", 7, stage="video-editor")) + "\n")
        before = j.read_bytes()
        r = c.post("/api/maintenance/journals", headers=H, json={"confirm": p["confirm"]})
        assert r.status_code == 409 and r.json()["code"] == "check_changed", r.text
        assert set(r.json()) == {"message", "code", "details"}
        assert j.read_bytes() == before


def test_an_open_batch_holds_the_cleanup():
    root = tb.factory_tree()
    j = closed_batch_with_garbage(root)
    with Journals():
        c = tb.client(root)
        p = c.post("/api/maintenance/journals/plan", headers=H).json()
        assert p["ok"], p
        tb.write_batch(root, "reel", "going", [tb.marker("batch-start", hours_ago=0.01),
                                              tb.marker("stage-start", "trend-hunter",
                                                        hours_ago=0.005)])
        before = j.read_bytes()
        r = c.post("/api/maintenance/journals", headers=H, json={"confirm": p["confirm"]})
        assert r.status_code == 409 and r.json()["code"] == "batch_open", r.text
        assert "reel/going" in r.json()["message"]
        assert j.read_bytes() == before
        p = c.post("/api/maintenance/journals/plan", headers=H).json()
        assert not p["ok"] and p["confirm"] is None and p["open_batches"] == ["reel/going"], p
        assert "Открыт батч" in p["why"]


if __name__ == "__main__":
    fails = 0
    tests = [(k, f) for k, f in sorted(globals().items()) if k.startswith("test_") and callable(f)]
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                                   # noqa: BLE001
            fails += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - fails}/{len(tests)} passed")
    sys.exit(1 if fails else 0)
