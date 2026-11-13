#!/usr/bin/env python3
"""CF-0358: a published video releases its sources - and nothing else does.

Everything runs on a synthetic factory root under a temp dir: batches with
their `01b-footage-index.json` / `05-video-editor.json`, a pool of fake media
and sidecars, `publish/` with its journals. The live pool is never read.

The cases the user's conditions name:
* a source of a published topic goes - media, the three sidecars and its
  `index.json` entry - and the journal says what went and on what evidence;
* a source two topics share stays while the second one is alive (rejected and
  waiting for a rebuild, accepted and waiting for its slot, or never shown);
* a topic the user took off for good releases its sources, but only on a
  withdrawal that names the video;
* a topic in an open batch protects its sources, and `--delete` refuses to run
  at all while a batch is open;
* the default is the plan: without `--delete` not a byte moves;
* a slot not reached yet (README day, `publish_at`) is not a publication.
"""
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "shared" / "runlog"))
from _tmproot import tmp_root                                   # noqa: E402
import pool_release as pr                                       # noqa: E402

TMP = tmp_root("pool-release-test-")
MODULE = HERE.parent / "shared" / "runlog" / "pool_release.py"
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=timezone.utc)
CHAN = "chan"

IDS = {k: (k * 11)[:11] for k in "ABCDEFGHJK"}       # 11-char fake video ids
_n = [0]


def batch(root, name, topics, videos=(), chan=CHAN, open_=False, scripts=None):
    """topics: {topic_id: [video ids]}; videos: [(slug, topic_id)]."""
    b = root / "pipeline" / chan / name
    b.mkdir(parents=True)
    (b / "01b-footage-index.json").write_text(json.dumps({
        "sources_by_topic": topics,
        "fetched": [{"video_id": v, "topic_id": t} for t, vs in topics.items() for v in vs]}))
    if videos:
        (b / "05-video-editor.json").write_text(json.dumps({"videos": [
            {"output_path": f"/x/{s}.mp4", "script_id": f"{t}-script1"} for s, t in videos]}))
    if scripts is not None:
        (b / "03-content-researcher.json").write_text(json.dumps(
            {"scripts": [{"script_id": f"{t}-script1", "topic_id": t} for t in scripts]}))
    if open_:
        (b / "RUN_EVENTS.jsonl").write_text(json.dumps({"kind": "marker", "marker": "batch-start"}) + "\n")
    return b


def pool(root, *vids):
    p = root / "shared" / "footage"
    p.mkdir(parents=True, exist_ok=True)
    for v in vids:
        for suf in pr.SIDECAR_SUFFIXES:
            (p / f"{v}{suf}").write_bytes(b"x" * 100)
    idx = p / "index.json"
    entries = json.loads(idx.read_text())["entries"] if idx.exists() else []
    entries += [{"id": v, "path": str(p / f"{v}.mp4")} for v in vids]
    idx.write_text(json.dumps({"entries": entries}))


def acceptance(root, rows):
    (root / "publish").mkdir(parents=True, exist_ok=True)
    (root / "publish" / "acceptance-log.json").write_text(json.dumps({"acceptances": [
        {"entry_id": e, "verdict": v, "topic_id": None, "answered_at": "2026-10-01"} for e, v in rows]}))


def readme(root, rows):
    (root / "publish").mkdir(parents=True, exist_ok=True)
    lines = ["# x", "", "| ролик | батч | вердикт |", "|---|---|---|"]
    for day, slug, b, link in rows:
        lines.append(f"| `{CHAN}/{day}/{slug}.mp4` | `{CHAN}/{b}` | принят; "
                     + (f"**загружен**, `youtube.com/shorts/{link}`" if link else "") + " |")
    (root / "publish" / "README.md").write_text("\n".join(lines) + "\n")


def world():
    """Topic t1 published (README), t2 rejected, t3 never shown, t4 accepted
    and waiting; A only t1, B t1+t2, C t1+t3, D t1+t4, E orphan."""
    _n[0] += 1
    root = TMP / f"w{_n[0]}"
    batch(root, "2026-09-20T1000Z", {"t1": [IDS["A"], IDS["B"], IDS["C"], IDS["D"]], "t3": [IDS["C"]]},
          videos=[("one", "t1")])
    batch(root, "2026-09-25T1000Z", {"t2": [IDS["B"]], "t4": [IDS["D"]]},
          videos=[("two", "t2"), ("four", "t4")])
    pool(root, *(IDS[k] for k in "ABCDE"))
    readme(root, [("2026-09-22", "one", "2026-09-20T1000Z", "abcDEF")])
    acceptance(root, [(f"{CHAN}/2026-09-20T1000Z/one", "accepted"),
                      (f"{CHAN}/2026-09-25T1000Z/two", "rejected"),
                      (f"{CHAN}/2026-09-25T1000Z/four", "accepted")])
    return root


def run(root, *args):
    env = dict(os.environ, FACTORY_ROOT=str(root))
    return subprocess.run([sys.executable, str(MODULE), "--root", str(root), *args],
                          capture_output=True, text=True, timeout=120, env=env)


def ids(rows):
    return sorted(e["video_id"] for e in rows)


def test_published_topic_releases_only_its_own_source():
    root = world()
    p = pr.plan(root, now=NOW, open_keys=())
    assert ids(p["release"]) == [IDS["A"]], p["release"]
    assert ids(p["orphan"]) == [IDS["E"]]
    blocked = {e["video_id"]: e["blocked_by"] for e in p["keep"]}
    assert blocked == {IDS["B"]: [pr.STATUS_REJECTED], IDS["C"]: [pr.STATUS_NO_VIDEO],
                       IDS["D"]: [pr.STATUS_ACCEPTED]}, blocked
    ev = p["release"][0]["topics"]["t1"]["evidence"]
    assert any(x.startswith(pr.EVIDENCE_README) for x in ev), ev


def test_archive_files_are_pool_sources_and_are_released():
    """CF-0665: an archive file the indexer fetched directly is kept under its
    file id (`nasa-<id>` / `commons-<pageid>`), not an 11-character YouTube id
    - it is listed in the pool, read from the batches and released with its
    topic like any source."""
    nasa, commons = "nasa-PIA_25_x", "commons-123456"
    _n[0] += 1
    root = TMP / f"w{_n[0]}"
    batch(root, "2026-09-20T1000Z", {"t1": [IDS["A"], nasa], "t2": [commons]},
          videos=[("one", "t1")])
    pool(root, IDS["A"], nasa, commons)
    readme(root, [("2026-09-22", "one", "2026-09-20T1000Z", "abcDEF")])
    acceptance(root, [(f"{CHAN}/2026-09-20T1000Z/one", "accepted")])
    assert set(pr.pool_sources(root)) == {IDS["A"], nasa, commons}
    p = pr.plan(root, now=NOW, open_keys=())
    assert ids(p["release"]) == sorted([IDS["A"], nasa]), p["release"]
    blocked = {e["video_id"]: e["blocked_by"] for e in p["keep"]}
    assert blocked == {commons: [pr.STATUS_NO_VIDEO]}, blocked
    assert not p["orphan"], p["orphan"]
    # a candidate id (with its colon) is the hunter's name, never a pool file
    assert not pr.VIDEO_ID_RE.match("nasa:PIA25") and not pr.VIDEO_ID_RE.match("abc")


def test_dry_run_is_the_default_and_moves_nothing():
    root = world()
    before = sorted(f.name for f in (root / "shared" / "footage").iterdir())
    res = run(root, "--variants")
    assert res.returncode == 0, res.stderr
    assert "release (every topic published or withdrawn): 1 sources" in res.stdout, res.stdout
    assert sorted(f.name for f in (root / "shared" / "footage").iterdir()) == before
    assert not pr.journal_path(root).exists()


def test_delete_removes_media_sidecars_and_index_entry_and_journals_it():
    root = world()
    res = run(root, "--delete")
    assert res.returncode == 0, res.stderr + res.stdout
    pool_dir = root / "shared" / "footage"
    assert not any(f.name.startswith(IDS["A"]) for f in pool_dir.iterdir())
    for k in "BCDE":
        assert all((pool_dir / f"{IDS[k]}{s}").exists() for s in pr.SIDECAR_SUFFIXES), k
    idx = json.loads((pool_dir / "index.json").read_text())["entries"]
    assert IDS["A"] not in {e["id"] for e in idx} and len(idx) == 4
    rows = pr.read_journal(root)
    assert [r["event"] for r in rows] == ["released"] and rows[0]["video_id"] == IDS["A"]
    assert len(rows[0]["removed"]) == 4 and rows[0]["bytes"] == 400


def test_source_shared_by_two_topics_goes_when_both_are_finished():
    root = world()
    # t2 (rejected) is later rebuilt and published: B is free now.
    readme(root, [("2026-09-22", "one", "2026-09-20T1000Z", "abcDEF"),
                  ("2026-09-28", "two", "2026-09-25T1000Z", "ghiJKL")])
    p = pr.plan(root, now=NOW, open_keys=())
    assert ids(p["release"]) == [IDS["A"], IDS["B"]], p["release"]


def test_withdrawn_topic_releases_only_on_a_named_withdrawal():
    root = world()
    try:
        pr.record_withdrawal(root, f"{CHAN}/2026-09-25T1000Z/two", "снимаю")
    except ValueError as e:
        assert "two" in str(e)
    else:
        raise AssertionError("a withdrawal that does not name the video was filed")
    res = run(root, "--record-withdrawal", f"{CHAN}/2026-09-25T1000Z/two", "--answer", "two - снимаю")
    assert res.returncode == 0, res.stderr
    p = pr.plan(root, now=NOW, open_keys=())
    assert ids(p["release"]) == [IDS["A"], IDS["B"]]
    t2 = [e for e in p["release"] if e["video_id"] == IDS["B"]][0]["topics"]["t2"]
    assert t2["status"] == pr.STATUS_WITHDRAWN


def test_rejection_alone_is_not_a_withdrawal():
    root = world()
    p = pr.plan(root, now=NOW, open_keys=())
    assert IDS["B"] in ids(p["keep"])


def test_topic_in_an_open_batch_protects_and_delete_is_refused():
    root = world()
    batch(root, "2026-10-03T0900Z", {"t9": [IDS["A"]]}, open_=True)
    p = pr.plan(root, now=NOW)
    assert p["open_batches"] == [f"{CHAN}/2026-10-03T0900Z"]
    a = [e for e in p["keep"] if e["video_id"] == IDS["A"]][0]
    assert a["blocked_by"][0] == "open_batch"
    res = run(root, "--delete")
    assert res.returncode == 3 and "open batch" in res.stderr, res.stderr
    assert all((root / "shared" / "footage" / f"{v}.mp4").exists() for v in IDS.values()
               if (root / "shared" / "footage" / f"{v}.shots.json").exists())


def test_a_slot_not_reached_yet_is_not_a_publication():
    root = world()
    readme(root, [("2026-10-07", "one", "2026-09-20T1000Z", "abcDEF")])
    assert pr.plan(root, now=NOW, open_keys=())["release"] == []
    readme(root, [])
    (root / "publish" / "uploads.json").write_text(json.dumps({"uploads": [
        {"entry_id": f"{CHAN}/2026-09-20T1000Z/one", "topic_id": None,
         "publish_at": "2026-10-05T15:00:00Z", "uploaded_at": "2026-10-02T10:00:00Z"}]}))
    assert pr.plan(root, now=NOW, open_keys=())["release"] == []
    (root / "publish" / "uploads.json").write_text(json.dumps({"uploads": [
        {"entry_id": f"{CHAN}/2026-09-20T1000Z/one", "topic_id": None,
         "publish_at": "2026-10-01T15:00:00Z", "uploaded_at": "2026-09-30T10:00:00Z"}]}))
    p = pr.plan(root, now=NOW, open_keys=())
    assert ids(p["release"]) == [IDS["A"]]
    assert p["release"][0]["topics"]["t1"]["evidence"][0].startswith(pr.EVIDENCE_JOURNAL)


def test_rebuild_without_render_record_resolves_through_its_scripts():
    root = world()
    # A rebuild of t2 that kept no 05-video-editor.json, then published.
    batch(root, "2026-09-26T1000Z", {"t2": [IDS["B"]]}, chan="rebuilds", scripts=["t2"])
    readme(root, [("2026-09-22", "one", "2026-09-20T1000Z", "abcDEF")])
    with open(root / "publish" / "README.md", "a") as fh:
        fh.write(f"| `{CHAN}/2026-09-27/two.mp4` | `rebuilds/2026-09-26T1000Z` | `youtube.com/shorts/zz` |\n")
    p = pr.plan(root, now=NOW, open_keys=())
    assert ids(p["release"]) == [IDS["A"], IDS["B"]], (p["release"], p["unresolved"])


def test_variants_count_but_do_not_release():
    root = world()
    p = pr.plan(root, now=NOW, open_keys=())
    v = {x["rule"]: x["sources"] for x in pr.variants(p)}
    assert v["no_video older than 7 d"] == 1          # C: t3 lives in a batch of 20.09
    assert v["no_video+rejected older than 7 d"] == 2  # + B (t2, 25.09)
    assert v["no_video+rejected older than 14 d"] == 0
    assert ids(p["release"]) == [IDS["A"]]


def test_refused_candidate_of_a_published_topic_is_an_orphan_and_stays():
    root = world()
    b = root / "pipeline" / CHAN / "2026-09-20T1000Z" / "01b-footage-index.json"
    doc = json.loads(b.read_text())
    doc["failed"] = [{"video_id": IDS["F"], "topic_id": "t1", "refused_at": "sieve"}]
    doc["fetched"].append({"video_id": IDS["G"]})              # no topic: the old layout
    b.write_text(json.dumps(doc))
    pool(root, IDS["F"], IDS["G"])
    p = pr.plan(root, now=NOW, open_keys=())
    kinds = {e["video_id"]: e["kind"] for e in p["orphan"]}
    assert kinds == {IDS["E"]: "unmentioned", IDS["F"]: "refused_candidate", IDS["G"]: "untopiced"}, kinds
    assert ids(p["release"]) == [IDS["A"]]
    v = {x["rule"]: x["sources"] for x in pr.variants(p)}
    assert v["orphan: refused candidate of finished topics only"] == 1
    assert v["orphan: all"] == 3


def test_stale_rule_releases_undelivered_topics_after_14_days_only():
    """The user's rule of 2026-10-04: no_video or rejected-not-withdrawn, every
    batch older than 14 days -> finished. Accepted-and-waiting never is."""
    root = world()
    p = pr.plan(root, now=NOW, open_keys=(), stale_days=14)     # 09-20 is 13 days old
    assert ids(p["release"]) == [IDS["A"]], p["release"]
    later = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)   # 09-20 > 14 d, 09-25 not
    p = pr.plan(root, now=later, open_keys=(), stale_days=14)
    assert ids(p["release"]) == [IDS["A"], IDS["C"]], p["release"]
    c = next(e for e in p["release"] if e["video_id"] == IDS["C"])
    assert c["topics"]["t3"]["stale"] and any(x.startswith("stale") for x in c["topics"]["t3"]["evidence"])
    much_later = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    p = pr.plan(root, now=much_later, open_keys=(), stale_days=14)
    assert ids(p["release"]) == [IDS["A"], IDS["B"], IDS["C"]], p["release"]
    assert {e["video_id"]: e["blocked_by"] for e in p["keep"]} == {IDS["D"]: [pr.STATUS_ACCEPTED]}
    # without the rule nothing of that changes
    assert ids(pr.plan(root, now=much_later, open_keys=())["release"]) == [IDS["A"]]


def test_stale_rule_waits_for_the_topics_newest_batch_and_for_open_batches():
    root = world()
    batch(root, "2026-10-05T1000Z", {"t3": [IDS["C"]]})        # t3 tried again later
    later = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    p = pr.plan(root, now=later, open_keys=(), stale_days=14)
    assert IDS["C"] not in ids(p["release"]), p["release"]
    p = pr.plan(root, now=datetime(2026, 11, 1, tzinfo=timezone.utc),
                open_keys={f"{CHAN}/2026-10-05T1000Z"}, stale_days=14)
    keep = {e["video_id"]: e["blocked_by"] for e in p["keep"]}
    assert keep.get(IDS["C"]) == ["open_batch"], keep


def test_stale_days_on_the_cli_and_in_the_journal():
    root = world()
    res = run(root, "--stale-days", "1", "--delete")
    assert res.returncode == 0, res.stderr + res.stdout
    assert "stale rule" in res.stdout
    rows = [json.loads(x) for x in pr.journal_path(root).read_text().splitlines()]
    assert {r["video_id"] for r in rows} == {IDS["A"], IDS["B"], IDS["C"]}, rows
    assert any(t.get("stale") for r in rows for t in r["topics"].values())


# ---------------------------------------------------------------- CF-0720: by/via, dry runs, check_answer
def _pool_files(root):
    return sorted(f.name for f in (root / "shared" / "footage").iterdir())


def test_cf0720_delete_dry_run_returns_the_same_ids_and_rows_and_touches_nothing():
    root = world()
    before = _pool_files(root)
    p = pr.plan(root, now=NOW, open_keys=())
    dry_rows = []
    dry = pr.delete(p, root, now=NOW, by="user", via="center", dry_run=True, rows=dry_rows)
    assert _pool_files(root) == before and not pr.journal_path(root).exists()
    real_rows = []
    real = pr.delete(p, root, now=NOW, by="user", via="center", rows=real_rows)
    assert dry == real == [IDS["A"]], (dry, real)
    assert dry_rows == real_rows == pr.read_journal(root), (dry_rows, real_rows)
    assert real_rows[0]["by"] == "user" and real_rows[0]["via"] == "center"
    assert len(real_rows[0]["removed"]) == 4 and real_rows[0]["bytes"] == 400


def test_cf0720_delete_without_who_keeps_the_old_row_shape_and_bad_who_writes_nothing():
    root = world()
    p = pr.plan(root, now=NOW, open_keys=())
    before = _pool_files(root)
    for bad in ("", "  ", "a\nb", "x" * 41, 5):
        try:
            pr.delete(p, root, now=NOW, by=bad)
        except ValueError as e:
            assert "by=" in str(e), e
        else:
            raise AssertionError(f"by={bad!r} was taken")
    assert _pool_files(root) == before and not pr.journal_path(root).exists()
    pr.delete(p, root, now=NOW)
    row = pr.read_journal(root)[0]
    assert list(row) == ["event", "video_id", "removed", "bytes", "topics", "at", "task"], row


def test_cf0720_delete_dry_run_is_refused_while_a_batch_is_open_like_the_real_one():
    root = world()
    p = pr.plan(root, now=NOW, open_keys={f"{CHAN}/2026-09-25T1000Z"})
    for dry in (True, False):
        try:
            pr.delete(p, root, now=NOW, dry_run=dry)
        except RuntimeError as e:
            assert "open batch" in str(e)
        else:
            raise AssertionError(f"dry_run={dry}: not refused")
    assert not pr.journal_path(root).exists()


def test_cf0720_check_answer_is_the_rule_without_a_root():
    ok = pr.check_answer(f"{CHAN}/2026-09-25T1000Z/two", "Снимаю TWO окончательно")
    assert ok == {"ok": True, "entry_id": f"{CHAN}/2026-09-25T1000Z/two", "slug": "two",
                  "why": None}, ok
    no = pr.check_answer(f"{CHAN}/2026-09-25T1000Z/two", "снимаю")
    assert not no["ok"] and no["slug"] == "two" and "does not name 'two'" in no["why"], no
    for bad in ("two", "a/b", "a//c", None, 7):
        got = pr.check_answer(bad, "two")
        assert not got["ok"] and "CHANNEL/BATCH/SLUG" in got["why"], got
    assert not pr.check_answer(f"{CHAN}/b/two", None)["ok"]


def test_cf0720_record_withdrawal_dry_run_and_by_via():
    root = world()
    entry = f"{CHAN}/2026-09-25T1000Z/two"
    dry = pr.record_withdrawal(root, entry, "two - снимаю", now=NOW, by="user", via="center",
                               dry_run=True)
    assert not pr.journal_path(root).exists()
    real = pr.record_withdrawal(root, entry, "two - снимаю", now=NOW, by="user", via="center")
    assert dry == real == pr.read_journal(root)[0], (dry, real)
    assert real["by"] == "user" and real["via"] == "center" and real["topic_id"] == "t2"
    try:
        pr.record_withdrawal(root, entry, "two - снимаю", via="a\tb")
    except ValueError as e:
        assert "via=" in str(e)
    else:
        raise AssertionError("a bad via was taken")
    try:
        pr.record_withdrawal(root, entry, "снимаю", dry_run=True)
    except ValueError as e:
        assert "two" in str(e)
    else:
        raise AssertionError("a dry run took an answer without the name")
    assert len(pr.read_journal(root)) == 1
    old = pr.record_withdrawal(root, entry, "two - снимаю", now=NOW)
    assert "by" not in old and "via" not in old, old


def test_cf0720_cli_by_via_and_dry_run():
    root = world()
    entry = f"{CHAN}/2026-09-25T1000Z/two"
    res = run(root, "--record-withdrawal", entry, "--answer", "two - снимаю", "--by", "user",
              "--via", "cli", "--dry-run")
    assert res.returncode == 0, res.stderr
    assert json.loads(res.stdout)["via"] == "cli" and not pr.journal_path(root).exists()
    before = _pool_files(root)
    res = run(root, "--delete", "--dry-run", "--by", "user", "--via", "cli")
    assert res.returncode == 0 and "would delete 1 sources" in res.stdout, res.stdout + res.stderr
    assert _pool_files(root) == before and not pr.journal_path(root).exists()
    res = run(root, "--delete", "--by", "", "--via", "cli")
    assert res.returncode == 2 and "by=" in res.stderr, res.stderr
    assert _pool_files(root) == before
    res = run(root, "--delete", "--by", "user", "--via", "cli")
    assert res.returncode == 0, res.stderr
    assert pr.read_journal(root)[0]["by"] == "user" and pr.read_journal(root)[0]["via"] == "cli"


if __name__ == "__main__":
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                      # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
