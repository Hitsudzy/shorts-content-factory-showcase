#!/usr/bin/env python3
"""CC-0105: freeing the footage pool of finished videos' sources (`runlog
pool-release --variants` / `--delete`), `api/pool.py`:

    GET  /api/maintenance/pool                  plan + variants - nothing written
    POST /api/maintenance/pool/release/plan     the same plan, what --delete removes, a token
    POST /api/maintenance/pool/release {confirm}   the same plan again, then pool_release.delete

In-process (the TestClient) against a stand-in factory root in a temp dir: a
batch with two videos whose topics share a pool source, the pool's files
(bytes of nothing) and its index, a withdrawal of one video recorded in the
temp root's journal. Nothing outside the temp dir is read for the pool or
written, the network is refused (`no_network`).

What is pinned: the read is the factory's plan (release / keep / orphan, the
variants) without the root's path and writes nothing; the plan says what
goes and gives a token; the confirm removes exactly the planned source's
files and index entry (the factory's `delete`), one `released` row; a token
once only; a world that moved since the plan is `check_changed` and nothing
is deleted; an open batch - no token, and a confirm then is `batch_open`;
a bad stale_days is `invalid`.
"""
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("FACTORY_ROOT", None)
os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

import test_cc_api_batches as tb                                             # noqa: E402
from test_cc_api_batches import _w, client, factory_tree                    # noqa: E402
from test_cc_api_publish import files                                        # noqa: E402
from test_cc_api_publish_writes import head, no_network, post                # noqa: E402

from api import factory                                                      # noqa: E402

BATCH = "2026-10-01T1000Z"
GONE, KEEP = "gone-girl", "keeper"
OWN, SHARED, OTHER, LOOSE = "AaAaAaAaAa1", "ShArEdSrC01", "KkKkKkKkKk1", "LlLlLlLlLl1"
POOL = "/api/maintenance/pool"
PLAN, CONFIRM = f"{POOL}/release/plan", f"{POOL}/release"


def world():
    root = factory_tree()
    d = root / "pipeline" / "reel" / BATCH
    _w(d / "05-video-editor.json", {"videos": [
        {"output_path": f"/x/videos/{GONE}.mp4", "script_id": "t-gone-script1", "topic_id": "t-gone"},
        {"output_path": f"/x/videos/{KEEP}.mp4", "script_id": "t-keep-script1",
         "topic_id": "t-keep"}]})
    _w(d / "01b-footage-index.json", {"sources_by_topic": {"t-gone": [OWN, SHARED],
                                                           "t-keep": [SHARED, OTHER]}})
    pool = root / "shared" / "footage"
    pool.mkdir(parents=True, exist_ok=True)
    for vid in (OWN, SHARED, OTHER, LOOSE):
        (pool / f"{vid}.mp4").write_bytes(b"\0" * 10)
        (pool / f"{vid}.shots.json").write_text("{}", encoding="utf-8")
    _w(pool / "index.json", {"entries": [{"id": v} for v in (OWN, SHARED, OTHER, LOOSE)]})
    _w(root / "publish" / "acceptance-log.json", {"acceptances": [
        {"entry_id": f"reel/{BATCH}/{GONE}", "topic_id": "t-gone", "verdict": "rejected",
         "answered_at": "2026-10-02T10:00:00Z"}]})
    factory.pool_release().record_withdrawal(root, f"reel/{BATCH}/{GONE}", f"снимаю {GONE}")
    return root


def journal(root):
    p = root / "shared" / "footage" / "release-log.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def utc_iso(s):
    """A journal stamp: an ISO timestamp in UTC (Z or +00:00) - parsed, or the test fails."""
    assert isinstance(s, str) and (s.endswith("Z") or s.endswith("+00:00")), s
    t = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    assert t.utcoffset() == timedelta(0), s
    return t


def index_ids(root):
    doc = json.loads((root / "shared" / "footage" / "index.json").read_text(encoding="utf-8"))
    return [e["id"] for e in doc["entries"]]


def test_the_read_is_the_factory_s_plan_and_variants():
    with no_network() as nn:
        root = world()
        c = client(root)
        before = files(root)
        r = c.get(POOL)
        assert r.status_code == 200, r.text
        v = r.json()
        assert v["command"] == "scripts/runlog pool-release --json --variants", v["command"]
        assert [e["video_id"] for e in v["release"]] == [OWN], v["release"]
        assert v["release"][0]["files"] == [f"{OWN}.mp4", f"{OWN}.shots.json"]
        assert v["release"][0]["topics"]["t-gone"]["status"] == "withdrawn", v["release"]
        assert sorted(e["video_id"] for e in v["keep"]) == [OTHER, SHARED], v["keep"]
        assert all(e["blocked_by"] == ["no_video"] for e in v["keep"]), v["keep"]
        assert [(e["video_id"], e["kind"]) for e in v["orphan"]] == [(LOOSE, "unmentioned")]
        assert v["totals"] == {"release": {"sources": 1, "bytes": 12},
                               "keep": {"sources": 2, "bytes": 24},
                               "orphan": {"sources": 1, "bytes": 12}}, v["totals"]
        assert v["pool"] == {"sources": 4, "bytes": 48}, v["pool"]
        assert v["variants"] and all({"rule", "sources", "bytes"} == set(x) for x in v["variants"])
        assert v["journal"] == "shared/footage/release-log.jsonl" and v["open_batches"] == []
        assert v["delete_action"] == "pool_release_delete" and "root" not in v
        assert str(root) not in r.text
        r = c.get(POOL, params={"stale_days": 14})
        assert r.status_code == 200 and r.json()["stale_days"] == 14, r.text
        assert r.json()["command"].endswith("--stale-days 14")
        for bad in (0, 400):
            r = c.get(POOL, params={"stale_days": bad})
            assert r.status_code == 422 and r.json()["code"] == "invalid", r.text
            assert set(r.json()) == {"message", "code", "details"}
        assert files(root) == before, "a read writes nothing"
    assert nn.net == [], nn.net


def test_the_plan_then_the_confirm_deletes_the_planned_source_only():
    with no_network():
        root = world()
        c = client(root)
        h0, before = head(root), files(root)
        n0 = len(journal(root))
        code, plan = post(c, PLAN)
        assert code == 200 and plan["ok"] and plan["confirm"], plan
        assert (plan["action"], plan["by"], plan["via"], plan["recorded_by"]) == \
            ("pool_release_delete", "user", "center", True), plan
        # CC-0117: the factory's dry run - the very rows the confirm writes, by/via on each
        assert [(x["event"], x["video_id"], x["bytes"], x["by"], x["via"])
                for x in plan["rows"]] == [("released", OWN, 12, "user", "center")], plan["rows"]
        assert plan["command"] == "scripts/runlog pool-release --delete", plan["command"]
        assert [e["video_id"] for e in plan["release"]] == [OWN] and \
            plan["totals"] == {"sources": 1, "bytes": 12}, plan
        assert plan["kept"] == {"sources": 2, "bytes": 24} and plan["open_batches"] == []
        assert files(root) == before, "a plan writes nothing"
        assert str(root) not in json.dumps(plan, ensure_ascii=False)
        code, done = post(c, CONFIRM, {"confirm": plan["confirm"]})
        assert code == 200 and done["written"] and done["deleted"] == [OWN], done
        pool = root / "shared" / "footage"
        assert not (pool / f"{OWN}.mp4").exists() and not (pool / f"{OWN}.shots.json").exists()
        for vid in (SHARED, OTHER, LOOSE):
            assert (pool / f"{vid}.mp4").is_file(), vid
        assert index_ids(root) == [SHARED, OTHER, LOOSE], index_ids(root)
        rows = journal(root)[n0:]
        assert [(x["event"], x["video_id"], x["bytes"], x["by"], x["via"]) for x in rows] == \
            [("released", OWN, 12, "user", "center")], rows
        # CC-0119: the plan and the write may straddle a second under load - `at` is
        # checked on its own (a UTC ISO stamp, not before the plan's), the rest as is
        assert done["recorded_by"] is True and \
            [{k: v for k, v in x.items() if k not in ("removed", "at")} for x in plan["rows"]] == \
            [{k: v for k, v in x.items() if k not in ("removed", "at")} for x in rows], \
            (plan["rows"], rows)
        assert len(plan["rows"]) == len(rows), (plan["rows"], rows)
        for p, w in zip(plan["rows"], rows):
            assert utc_iso(w["at"]) >= utc_iso(p["at"]), (p["at"], w["at"])
        assert done["rows"] == rows and done["totals"] == {"sources": 1, "bytes": 12}, done
        after = files(root)
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        assert changed == {f"shared/footage/{OWN}.mp4", f"shared/footage/{OWN}.shots.json",
                           "shared/footage/index.json", "shared/footage/release-log.jsonl"}, changed
        assert head(root) == h0
        code, r = post(c, CONFIRM, {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "confirm_unknown", r
        code, again = post(c, PLAN)
        assert code == 200 and not again["ok"] and again["confirm"] is None, again
        assert "нечего" in again["why"], again


def test_a_world_that_moved_is_check_changed_and_nothing_is_deleted():
    with no_network():
        root = world()
        c = client(root)
        code, plan = post(c, PLAN)
        assert plan["ok"], plan
        # the keeper withdrawn at the terminal meanwhile: now three sources would go
        factory.pool_release().record_withdrawal(root, f"reel/{BATCH}/{KEEP}", f"снять {KEEP}")
        before = files(root)
        code, r = post(c, CONFIRM, {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "check_changed", r
        assert set(r) == {"message", "code", "details"}, r
        assert files(root) == before
        code, plan = post(c, PLAN, {"stale_days": 14})
        assert plan["ok"] and plan["stale_days"] == 14, plan
        assert sorted(e["video_id"] for e in plan["release"]) == sorted([OTHER, OWN, SHARED]), plan
        code, r = post(c, PLAN, {"stale_days": 0})
        assert code == 422 and r["code"] == "invalid", r


def test_an_open_batch_holds_the_release():
    with no_network():
        root = world()
        c = client(root)
        code, plan = post(c, PLAN)
        assert plan["ok"], plan
        tb.write_batch(root, "reel", "going", [tb.marker("batch-start", hours_ago=0.01),
                                              tb.marker("stage-start", "trend-hunter",
                                                        hours_ago=0.005)])
        before = files(root)
        code, r = post(c, CONFIRM, {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "batch_open" and "reel/going" in r["message"], r
        assert files(root) == before
        code, plan = post(c, PLAN)
        assert not plan["ok"] and plan["confirm"] is None, plan
        assert plan["open_batches"] == ["reel/going"] and "Открыт батч" in plan["why"], plan


def test_a_batch_only_the_factory_s_plan_names_open_holds_it_too():
    """A stale open batch (no batch-done, `runlog batch-active` counts none):
    the factory's plan names it and its `delete` refuses on it - no token, and
    a token of before is `batch_open`."""
    with no_network():
        root = world()
        c = client(root)
        code, plan = post(c, PLAN)
        assert plan["ok"], plan
        tb.write_batch(root, "reel", "old", [tb.marker("batch-start", hours_ago=30)])
        assert factory.open_batches(root) == []
        before = files(root)
        code, r = post(c, CONFIRM, {"confirm": plan["confirm"]})
        assert code == 409 and r["code"] == "batch_open" and "reel/old" in r["message"], r
        assert files(root) == before
        code, plan = post(c, PLAN)
        assert not plan["ok"] and plan["confirm"] is None, plan
        assert plan["open_batches"] == ["reel/old"], plan


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                                  # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
