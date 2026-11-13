#!/usr/bin/env python3
"""CF-0738: an accepted video with no slot always lies in its channel's
`publish/<channel>/_queue/` - and the repair that finds the ones that do not.

13.10: Science `sophie-adenot` (rebuild 0524Z) was accepted through the center
(`record_and_commit`) and lay nowhere - nothing called `acceptance.place()`
after a verdict. Pinned here, on temp git repositories only (no live record,
no live batch, no network):

* a verdict `accepted` given with no batch going copies the render into
  `publish/<channel>/_queue/` (the channel's folder made when missing) and the
  row's `publish_path` goes into the same commit as the verdict;
* under an open batch the render is copied at once (gitignored, the tree stays
  clean) and `commit_pending` writes the path when it commits the queue;
* a rejection is never queued; a verdict whose render cannot be found is kept
  and the answer says why (`render_missing`);
* an accepted version of a video whose other version already lies in publish/
  is not queued (`other_version_placed`, CF-0463) - CF-0921: quietly, into
  `stash-events.jsonl`, not on the notification bus;
* idempotent: a second call adopts or leaves, never copies twice;
* `repair_queue` / `runlog acceptance --enqueue-accepted`: a dry run by
  default, `--apply` needs by/via, refuses under an open batch and on a changed
  base sha256, commits the record once.
"""
import hashlib
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

TMP = tmp_root("accepted-queue-test-")
os.environ.setdefault("RUNLOG_STATE_DIR", str(TMP / "state"))
os.environ["RUNLOG_POOL"] = str(TMP / "no-pool")       # never the live pipeline/
os.environ["NOTIFY_BACKENDS"] = "log"                  # CF-0821: the bus never leaves the Mac
os.environ.setdefault("NOTIFY_STATE_DIR", str(TMP / "notify"))

import acceptance    # noqa: E402

CH = "scichan"
BATCH = "2026-10-13T0524Z"
NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
_n = [0]


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def factory(channels=(CH, "otherchan")):
    """A fresh root repo: the record, the repo's gitignore lines for publish/,
    two channels on file, a rebuild directory with one rendered video."""
    _n[0] += 1
    d = TMP / f"root{_n[0]}"
    (d / "publish").mkdir(parents=True)
    git(d, "init", "-q", "-b", "main")
    git(d, "config", "user.email", "t@example.invalid")
    git(d, "config", "user.name", "test")
    git(d, "config", "core.hooksPath", str(d / ".git" / "hooks"))
    ignore = [l for l in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
              if l.startswith("publish/")]
    assert "publish/**/*.mp4" in ignore
    (d / ".gitignore").write_text("\n".join(ignore + ["pipeline/"]) + "\n", encoding="utf-8")
    (d / "channels").mkdir()
    for c in channels:
        (d / "channels" / f"{c}.json").write_text("{}\n", encoding="utf-8")
    acceptance.write_log([], path=d / "publish" / "acceptance-log.json")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "init")
    return d


def render(d, slug, batch=BATCH, where="rebuilds", body=b"MP4"):
    b = d / "pipeline" / where / batch
    (b / "videos").mkdir(parents=True, exist_ok=True)
    (b / "videos" / f"{slug}.mp4").write_bytes(body)
    (b / "videos" / f"{slug}.jpg").write_bytes(b"JPG")
    return b


def log_of(d):
    return d / "publish" / "acceptance-log.json"


def rows_of(d):
    return acceptance.entries(path=log_of(d))


def clean(d):
    return git(d, "status", "--porcelain", "--untracked-files=all") == ""


def say(d, slug, verdict="accepted", open_rows=(), batch=BATCH, bdir=None, **kw):
    if verdict == "rejected":
        kw.setdefault("reason", "кадры не про тему")
        kw.setdefault("reason_code", "off_topic")
    return acceptance.record_and_commit(
        CH, batch, slug, verdict, f"{slug} - {verdict}", by="центр", root=d,
        open_rows=list(open_rows), topic_id="t-" + slug,
        batch_dir=bdir if bdir is not None else d / "pipeline" / "rebuilds" / batch, **kw)


def test_an_accepted_rebuild_goes_into_a_channel_queue_that_did_not_exist():
    d = factory()
    render(d, "sophie-adenot")
    assert not (d / "publish" / CH).exists()
    res = say(d, "sophie-adenot")
    q = res["queued"]
    assert q["code"] == "placed" and q["ok"] and q["changed"], q
    dst = d / "publish" / CH / "_queue" / "sophie-adenot.mp4"
    assert dst.read_bytes() == b"MP4"
    row = rows_of(d)[0]
    assert row["publish_path"] == f"publish/{CH}/_queue/sophie-adenot.mp4"
    # one commit: the verdict and the path together; the mp4 is gitignored
    assert git(d, "show", "--name-only", "--format=", "HEAD") == "publish/acceptance-log.json"
    assert "Копилка (CF-0738)" in git(d, "log", "-1", "--format=%B")
    assert clean(d)


def test_the_batch_is_found_from_the_row_when_the_caller_names_none():
    d = factory()
    render(d, "sophie-adenot")
    res = acceptance.record_and_commit(CH, BATCH, "sophie-adenot", "accepted",
                                       "sophie-adenot принят", by="центр", root=d,
                                       open_rows=[], topic_id="t-1")
    assert res["queued"]["code"] == "placed", res["queued"]
    assert (d / "publish" / CH / "_queue" / "sophie-adenot.mp4").is_file()


def test_a_rejection_is_not_queued_and_a_missing_render_keeps_the_verdict():
    d = factory()
    render(d, "bad-one")
    res = say(d, "bad-one", "rejected")
    assert res["queued"] is None and not (d / "publish" / CH).exists()
    res = say(d, "no-render", bdir=d / "pipeline" / "rebuilds" / BATCH)
    assert res["committed"] and res["queued"]["code"] == "render_missing"
    assert res["queued"]["refused"] and "mp4" in res["queued"]["text_ru"]
    row = [r for r in rows_of(d) if r["slug"] == "no-render"][0]
    assert row["verdict"] == "accepted" and row["publish_path"] is None
    res = say(d, "no-batch", bdir=d / "nowhere")
    assert res["queued"]["code"] == "batch_missing"


def test_under_an_open_batch_the_copy_is_made_now_and_the_path_with_the_queue():
    d = factory()
    render(d, "sophie-adenot")
    head = git(d, "rev-parse", "HEAD")
    going = [(d / "pipeline" / CH / "2026-10-13T1000Z", NOW, True)]
    res = say(d, "sophie-adenot", open_rows=going)
    assert res["pending"] and res["queued"]["code"] == "placed"
    assert (d / "publish" / CH / "_queue" / "sophie-adenot.mp4").is_file()
    assert git(d, "rev-parse", "HEAD") == head and clean(d)
    assert rows_of(d)[0].get("pending")
    out = acceptance.commit_pending(d, open_rows=[])
    assert out["committed"], out
    assert [q["code"] for q in out["queued"]] == ["adopted"], out["queued"]
    row = rows_of(d)[0]
    assert row["publish_path"] == f"publish/{CH}/_queue/sophie-adenot.mp4"
    assert "Копилка (CF-0738)" in git(d, "log", "-1", "--format=%B")


def _cli_check(d):
    cp = subprocess.run(
        [sys.executable, str(ROOT / "shared" / "runlog" / "acceptance.py"), "--root", str(d),
         "--log", str(log_of(d)), "--publish-dir", str(d / "publish"),
         "--holds", str(d / "publish" / "no-holds.json"), "--check", "--json"],
        capture_output=True, text=True, timeout=120,
        env=dict(os.environ, RUNLOG_POOL=str(TMP / "no-pool")))
    assert cp.returncode in (0, 1), cp.stderr[-400:]
    return cp.returncode, json.loads(cp.stdout)


def test_a_verdict_given_under_a_batch_backs_its_queued_video_in_the_check():
    """CF-0870: 26.10 i-play-rocky was accepted while example-film 1514Z ran - the
    render went into `_queue/` at once (CF-0738), the verdict into the queue of
    CF-0675, and the live monitor at the batch's end (`runlog acceptance
    --check`) saw a video with no verdict. The queued verdict backs it: the
    check is green during the batch and after the queue is committed."""
    d = factory()
    render(d, "i-play-rocky")
    going = [(d / "pipeline" / CH / "2026-10-13T1000Z", NOW, True)]
    res = say(d, "i-play-rocky", open_rows=going)
    assert res["pending"] and res["queued"]["code"] == "placed", res
    assert (d / "publish" / CH / "_queue" / "i-play-rocky.mp4").is_file()
    code, out = _cli_check(d)
    assert code == 0 and out["problems"] == [], out
    assert [w["entry_id"] for w in out["pending"]] == [f"{CH}/{BATCH}/i-play-rocky"], out
    lib = acceptance.check(path=log_of(d), publish_dir=d / "publish",
                           holds_path=d / "publish" / "no-holds.json")
    assert lib["problems"] == [] and len(lib["pending"]) == 1, lib
    assert acceptance.commit_pending(d, open_rows=[])["committed"]
    code, out = _cli_check(d)
    assert code == 0 and out["problems"] == [] and out["pending"] == [], out
    # a video in _queue/ with no verdict anywhere is still the problem it was
    (d / "publish" / CH / "_queue" / "stray.mp4").write_bytes(b"MP4")
    code, out = _cli_check(d)
    assert code == 1 and [p["slug"] for p in out["problems"]] == ["stray"], out


def _cli_state(d, slug, json_out=True):
    cp = subprocess.run(
        [sys.executable, str(ROOT / "shared" / "runlog" / "acceptance.py"), "--root", str(d),
         "--log", str(log_of(d)), "--holds", str(d / "publish" / "no-holds.json"),
         "--state", f"{CH}/{BATCH}/{slug}"] + (["--json"] if json_out else []),
        capture_output=True, text=True, timeout=120,
        env=dict(os.environ, RUNLOG_POOL=str(TMP / "no-pool")))
    assert cp.returncode in (0, 1), cp.stderr[-400:]
    return cp.returncode, (json.loads(cp.stdout) if json_out else cp.stdout)


def test_a_verdict_given_under_a_batch_is_in_the_state_marked_pending():
    """CF-0875: `runlog acceptance --state` read the record's own rows only - a
    video accepted while a batch ran showed `no verdict` until the queue of
    CF-0675 was committed. It reads the queue as --check does (CF-0870): the
    verdict is there at once, marked pending, and plain once committed."""
    d = factory()
    render(d, "i-play-rocky")
    code, st = _cli_state(d, "i-play-rocky")
    assert code == 1 and not st["recorded"] and st["verdict"] is None, st
    going = [(d / "pipeline" / CH / "2026-10-13T1000Z", NOW, True)]
    res = say(d, "i-play-rocky", open_rows=going)
    assert res["pending"], res
    code, st = _cli_state(d, "i-play-rocky")
    assert code == 0 and st["recorded"] and st["verdict"] == "accepted", st
    assert st["pending"] and st["queued_at"] and st["publishable"], st
    code, text = _cli_state(d, "i-play-rocky", json_out=False)
    assert code == 0 and "i-play-rocky: accepted (pending since" in text, text
    assert "-> publishable" in text, text
    assert acceptance.commit_pending(d, open_rows=[])["committed"]
    code, st = _cli_state(d, "i-play-rocky")
    assert code == 0 and st["verdict"] == "accepted" and not st["pending"], st
    assert st["queued_at"] is None, st
    code, text = _cli_state(d, "i-play-rocky", json_out=False)
    assert code == 0 and "pending" not in text and "i-play-rocky: accepted ->" in text, text


def test_idempotent_and_never_over_another_batch_file():
    d = factory()
    render(d, "sophie-adenot")
    row = {"entry_id": f"{CH}/{BATCH}/sophie-adenot", "slug": "sophie-adenot", "channel": CH,
           "batch_id": BATCH, "verdict": "accepted", "publish_path": None}
    a = acceptance.queue_accepted(row, [row], root=d)
    assert a["code"] == "placed"
    b = acceptance.queue_accepted(row, [row], root=d)
    assert b["code"] == "already_placed" and not b["changed"]
    row2 = dict(row, publish_path=None)
    c = acceptance.queue_accepted(row2, [row2], root=d)
    assert c["code"] == "adopted" and row2["publish_path"] == row["publish_path"]
    # a note of another batch under the same name in _queue/: not ours, not copied over
    q = d / "publish" / CH / "_queue"
    (q / "x-one.md").write_text("Батч `pipeline/scichan/2026-10-01T0000Z`\n", encoding="utf-8")
    render(d, "x-one")
    row3 = dict(row, entry_id=f"{CH}/{BATCH}/x-one", slug="x-one", publish_path=None)
    t = acceptance.queue_accepted(row3, [row3], root=d)
    # CF-0920: goes in beside it under its batch's name, the other file is not touched
    assert t["code"] == "placed" and t["ok"] and not t["refused"], t
    assert row3["publish_path"] == f"publish/{CH}/_queue/x-one~{BATCH}.mp4" == t["publish_path"]
    assert t["name_taken"]["batch_id"] == "2026-10-01T0000Z" and row3["slug"] == "x-one"
    assert (q / "x-one.md").read_text(encoding="utf-8").startswith("Батч `pipeline/scichan/2026-10")
    assert not (q / "x-one.mp4").exists()
    # CF-0855: another batch's pair of the name in a day folder holds its own day -
    # the copy goes to _queue/ beside it, the day folder is left as it is
    day = d / "publish" / CH / "2026-10-20"
    day.mkdir(parents=True)
    old_note = "Батч `pipeline/scichan/2026-10-01T0000Z`\n"
    (day / "z-three.md").write_text(old_note, encoding="utf-8")
    (day / "z-three.mp4").write_bytes(b"OLD")
    render(d, "z-three")
    row5 = dict(row, entry_id=f"{CH}/{BATCH}/z-three", slug="z-three", publish_path=None)
    z = acceptance.queue_accepted(row5, [row5], root=d)
    assert z["code"] == "placed" and z["ok"], z
    assert row5["publish_path"] == f"publish/{CH}/_queue/z-three.mp4"
    assert (q / "z-three.mp4").read_bytes() == b"MP4"
    assert (day / "z-three.mp4").read_bytes() == b"OLD"
    assert (day / "z-three.md").read_text(encoding="utf-8") == old_note
    # dry run changes nothing
    render(d, "y-two")
    row4 = dict(row, entry_id=f"{CH}/{BATCH}/y-two", slug="y-two", publish_path=None)
    dr = acceptance.queue_accepted(row4, [row4], root=d, apply=False)
    assert dr["code"] == "placed" and dr["dry_run"] and not dr["changed"]
    assert row4["publish_path"] is None
    assert not (d / "publish" / CH / "_queue" / "y-two.mp4").exists()


def test_a_version_whose_other_version_is_placed_is_not_queued():
    d = factory()
    render(d, "harbourlights")
    placed = {"entry_id": f"{CH}/2026-10-01T0000Z/harbourlights", "slug": "harbourlights", "channel": CH,
              "batch_id": "2026-10-01T0000Z", "verdict": "accepted", "topic_id": "t-l",
              "publish_path": f"publish/{CH}/2026-10-07/harbourlights.mp4"}
    row = dict(placed, entry_id=f"{CH}/{BATCH}/harbourlights", batch_id=BATCH, publish_path=None)
    res = acceptance.queue_accepted(row, [placed, row], root=d)
    assert res["code"] == "other_version_placed" and res["skipped"] and not res["refused"]
    # a legacy `rebuilds` row (its channel cannot be read with two channels) counts too
    legacy = dict(placed, channel="rebuilds")
    assert acceptance.queue_accepted(row, [legacy, row], root=d)["code"] == "other_version_placed"
    # another topic with no fact on the record cannot be told from a version (CF-0821)
    other_topic = dict(placed, topic_id="t-other")
    assert acceptance.queue_accepted(row, [other_topic, row], root=d)["code"] == \
        "other_version_placed"
    # a person says it is a new video under an old name: placed
    assert acceptance.queue_accepted(row, [placed, row], root=d,
                                     other_version_ok=True)["code"] == "placed"


def _seed(d, rows):
    acceptance.write_log(rows, path=log_of(d))
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "seed")


def _accepted(slug, batch=BATCH, **kw):
    r = {"entry_id": f"{CH}/{batch}/{slug}", "slug": slug, "channel": CH, "batch_id": batch,
         "verdict": "accepted", "answered_at": "2026-10-13", "answer": f"{slug} да",
         "recorded_at": "2026-10-13T05:42:44Z", "topic_id": "t-" + slug,
         "code_shas_source": f"pipeline/rebuilds/{batch}/05-video-editor.json",
         "publish_path": None, "history": []}
    r.update(kw)
    return r


def test_a_namesake_in_the_reserve_does_not_stand_in_the_way():
    """CF-0919: the reserve lies apart - accepting a new video of the same name
    is not `slug_taken`, the new one goes into `_queue/`, the reserve one stays."""
    d = factory()
    kept = d / "publish" / CH / "_reserve"
    kept.mkdir(parents=True)
    (kept / "percy.mp4").write_bytes(b"OLD")
    (kept / "percy.md").write_text(f"# percy\n\nБатч `pipeline/{CH}/2026-11-01T0832Z`\n",
                                   encoding="utf-8")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "reserve")
    render(d, "percy")
    res = say(d, "percy")
    assert res["queued"]["code"] == "placed" and res["queued"]["ok"], res["queued"]
    assert (d / "publish" / CH / "_queue" / "percy.mp4").read_bytes() == b"MP4"
    assert (kept / "percy.mp4").read_bytes() == b"OLD"
    assert rows_of(d)[0]["publish_path"] == f"publish/{CH}/_queue/percy.mp4"


def test_repair_brings_an_accepted_video_to_its_card():
    """CF-0919: `--enqueue-accepted` is how the driver brings a video accepted
    with `slug_taken` to the копилка and the card: the build starts as at a verdict."""
    d = factory()
    render(d, "percy")
    _seed(d, [_accepted("percy")])
    calls, was = [], acceptance._card_build
    acceptance._card_build = lambda row, root, pub, batch_dir=None: (
        calls.append(row["slug"]) or {"ok": True, "launched": True, "skipped": None,
                                      "run_id": "r", "log": None, "refusals": []})
    try:
        dry = acceptance.repair_queue(d)
        assert not calls and "card_build" not in dry["items"][0]
        res = acceptance.repair_queue(d, apply=True, by="driver", via="CF-0919", open_rows=[])
        assert res["ok"] and calls == ["percy"], res
        assert res["items"][0]["card_build"]["launched"]
        assert any(l.startswith(f"card {CH}/") and "build started" in l for l in res["lines"])
        again = acceptance.repair_queue(d, apply=True, by="driver", via="CF-0919", open_rows=[])
        assert calls == ["percy"] and not again["items"]
    finally:
        acceptance._card_build = was


def test_repair_dry_run_then_apply_commits_once():
    d = factory()
    render(d, "sophie-adenot")
    _seed(d, [_accepted("sophie-adenot"),
              _accepted("gone", publish_path=f"publish/{CH}/2026-10-01/gone.mp4"),
              _accepted("lost-render")])
    sha = hashlib.sha256(log_of(d).read_bytes()).hexdigest()
    dry = acceptance.repair_queue(d)
    assert dry["dry_run"] and not dry["written"] and dry["sha256"] == sha
    codes = {i["slug"]: i["code"] for i in dry["items"]}
    assert codes == {"sophie-adenot": "placed", "lost-render": "render_missing"}, codes
    assert [r["code"] for r in dry["refusals"]] == ["render_missing"] and not dry["ok"]
    assert not (d / "publish" / CH).exists()
    head = git(d, "rev-parse", "HEAD")
    bad = acceptance.repair_queue(d, apply=True, by="driver", via=None, open_rows=[])
    assert bad["refusals"][0]["code"] == "bad_who" and git(d, "rev-parse", "HEAD") == head
    changed = acceptance.repair_queue(d, apply=True, by="driver", via="CF-0738",
                                      base_sha256="0" * 64, open_rows=[])
    assert "check_changed" in [r["code"] for r in changed["refusals"]]
    going = acceptance.repair_queue(d, apply=True, by="driver", via="CF-0738",
                                    open_rows=[(d / "pipeline" / CH / "b", NOW, True)])
    assert "batch_open" in [r["code"] for r in going["refusals"]]
    assert git(d, "rev-parse", "HEAD") == head and not (d / "publish" / CH).exists()
    res = acceptance.repair_queue(d, apply=True, by="driver", via="CF-0738",
                                  base_sha256=sha, open_rows=[])
    assert res["commit"] == git(d, "rev-parse", "HEAD") and res["written"]
    assert git(d, "log", "-1", "--format=%s").startswith("Копилка: 1 принятых")
    assert (d / "publish" / CH / "_queue" / "sophie-adenot.mp4").is_file()
    by = {r["slug"]: r for r in rows_of(d)}
    assert by["sophie-adenot"]["publish_path"] == f"publish/{CH}/_queue/sophie-adenot.mp4"
    assert by["lost-render"]["publish_path"] is None
    assert clean(d)
    again = acceptance.repair_queue(d, apply=True, by="driver", via="CF-0738", open_rows=[])
    assert again["commit"] is None and [i["slug"] for i in again["items"]] == ["lost-render"]


def test_repair_only_named_rows_and_other_version_ok():
    d = factory()
    render(d, "harbourlights")
    render(d, "sophie-adenot")
    placed = _accepted("harbourlights", batch="2026-10-01T0000Z",
                       publish_path=f"publish/{CH}/2026-10-07/harbourlights.mp4")
    _seed(d, [placed, _accepted("harbourlights"), _accepted("sophie-adenot")])
    eid = f"{CH}/{BATCH}/harbourlights"
    dry = acceptance.repair_queue(d, only=[eid])
    assert [i["code"] for i in dry["items"]] == ["other_version_placed"] and dry["ok"]
    nf = acceptance.repair_queue(d, only=[f"{CH}/{BATCH}/nope"], apply=True, by="driver",
                                 via="CF-0738", open_rows=[])
    assert nf["refusals"][0]["code"] == "not_found" and nf["commit"] is None
    res = acceptance.repair_queue(d, only=[eid], other_version_ok=True, apply=True,
                                  by="driver", via="CF-0738", open_rows=[])
    assert [i["code"] for i in res["items"]] == ["placed"] and res["commit"], res
    assert not (d / "publish" / CH / "_queue" / "sophie-adenot.mp4").exists()


def test_cli_enqueue_accepted_is_a_dry_run_by_default():
    d = factory()
    render(d, "sophie-adenot")
    _seed(d, [_accepted("sophie-adenot")])
    env = dict(os.environ)
    env.pop("FACTORY_ROOT", None)
    env.pop("ACCEPTANCE_LOG", None)
    cmd = [sys.executable, str(ROOT / "shared" / "runlog" / "acceptance.py"),
           "--enqueue-accepted", "--root", str(d), "--log", str(log_of(d)), "--json"]
    cp = subprocess.run(cmd, capture_output=True, text=True, env=env)
    assert cp.returncode == 0, cp.stderr
    out = json.loads(cp.stdout)
    assert out["dry_run"] and out["items"][0]["code"] == "placed"
    assert not (d / "publish" / CH).exists()


# --------------------------------------------------------------------------
# CF-0821: a new video under an old name is not "another version"
# --------------------------------------------------------------------------

def _prof(script, url, text):
    return {"task": "CF-0440", "script_id": script, "fact_text": text,
            "fact_source": {"name": "Wikipedia", "url": url, "id": "wikipedia", "tier": 1}}


OLD_YCSE = {"entry_id": f"{CH}/2026-09-23T1722Z/you-can-see-everything",
            "slug": "you-can-see-everything", "channel": CH, "batch_id": "2026-09-23T1722Z",
            "verdict": "accepted", "topic_id": "lf-2026-09-23-004",
            "publish_path": "Archive:shorts-content-factory-publish/" + CH
                            + "/2026-09.zip#2026-09-25/you-can-see-everything.mp4",
            "batch_artifact": "pipeline/example-film/2026-09-23T1722Z",
            "profile": _prof("lf-2026-09-23-004-script1",
                             "https://en.wikipedia.org/wiki/You_Can_See_Everything#Production",
                             "The plan was for Fielder to stay behind the camera.")}


def _new_ycse(**kw):
    r = {"entry_id": f"{CH}/2026-10-18T0841Z/you-can-see-everything",
         "slug": "you-can-see-everything", "channel": CH, "batch_id": "2026-10-18T0841Z",
         "verdict": "accepted", "topic_id": "lf-2026-10-18-002", "publish_path": None,
         "batch_artifact": None,
         "profile": _prof("lf-2026-10-18-002-script1",
                          "https://en.wikipedia.org/wiki/You_Can_See_Everything#Release",
                          "Attendees were unaware of what film they would be seeing.")}
    r.update(kw)
    return r


def test_the_ycse_case_a_new_video_under_an_old_name_goes_into_the_queue_by_itself():
    d = factory()
    render(d, "you-can-see-everything", batch="2026-10-18T0841Z", where=CH)
    row = _new_ycse()
    assert acceptance.placed_version(row, [OLD_YCSE, row], root=d) is None
    res = acceptance.queue_accepted(row, [OLD_YCSE, row], root=d)
    assert res["code"] == "placed" and res["ok"], res
    assert res["namesake"]["entry_id"] == OLD_YCSE["entry_id"]
    assert "другая тема" in res["namesake"]["why"]
    assert row["publish_path"] == f"publish/{CH}/_queue/you-can-see-everything.mp4"


def test_a_version_is_a_rerun_a_rebuild_the_same_script_topic_or_fact():
    row = _new_ycse()
    sv = acceptance.same_video
    assert sv(row, dict(OLD_YCSE, batch_id=row["batch_id"]))[0]                # rerun
    assert sv(dict(row, batch_artifact="pipeline/example-film/2026-09-23T1722Z"), OLD_YCSE)[0]
    assert sv(row, dict(OLD_YCSE, topic_id=row["topic_id"]))[0]                 # same topic
    assert sv(row, dict(OLD_YCSE, profile=dict(OLD_YCSE["profile"],
                                               script_id=row["profile"]["script_id"])))[0]
    # CF-0855: one page holds many facts - the url is the fact only when a text is missing
    same_url = _prof("x-script", row["profile"]["fact_source"]["url"], "other words")
    same, why = sv(row, dict(OLD_YCSE, profile=same_url))                       # other fact
    assert not same and "тот же источник" in why, why
    same_url_no_text = _prof("x-script", row["profile"]["fact_source"]["url"], None)
    same, why = sv(row, dict(OLD_YCSE, profile=same_url_no_text))               # same fact
    assert same and "тот же факт" in why
    same_text = _prof("x-script", "https://example.org/a",
                      "  attendees were UNAWARE of what film they would be seeing ")
    assert sv(row, dict(OLD_YCSE, profile=same_text))[0]
    # nothing to tell them by: a version - the person decides
    assert sv(row, dict(OLD_YCSE, topic_id=None))[0]
    same, why = sv(row, dict(OLD_YCSE, profile=None))
    assert same and "факта нет" in why
    assert not sv(row, OLD_YCSE)[0]


def test_the_seven_rows_a_person_settled_stay_versions():
    d = factory(channels=("example-film",))
    placed = dict(OLD_YCSE, entry_id="example-film/2026-09-23T1722Z/american-dread-story",
                  slug="american-dread-story", channel="example-film",
                  topic_id="lf-2026-09-23-006")
    row = _new_ycse(entry_id="example-film/2026-09-30T2210Z/american-dread-story",
                    slug="american-dread-story", channel="example-film",
                    batch_id="2026-09-30T2210Z", topic_id="lf-2026-09-27-002")
    assert "example-film/2026-09-30T2210Z/american-dread-story" in acceptance.CF0463_SETTLED
    assert len(acceptance.CF0463_SETTLED) == 7
    res = acceptance.queue_accepted(row, [placed, row], root=d)
    assert res["code"] == "other_version_placed", res
    assert "CF-0463" in res["text_ru"] and "--other-version-ok" in res["text_ru"]
    # the same pair under an entry id nobody settled is a new video
    fresh = dict(row, entry_id="example-film/2026-10-20T0000Z/american-dread-story",
                 batch_id="2026-10-20T0000Z")
    assert acceptance.placed_version(fresh, [placed, fresh], root=d) is None


# --------------------------------------------------------------------------
# CF-0821 item 2: a video left out of the копилка is said loudly
# --------------------------------------------------------------------------

def _version_seeded(d):
    """A placed accepted row of `harbourlights` (same topic as the one `say` gives)."""
    placed = _accepted("harbourlights", batch="2026-10-01T0000Z", topic_id="t-harbourlights",
                       publish_path=f"publish/{CH}/2026-10-07/harbourlights.mp4")
    _seed(d, [placed])
    render(d, "harbourlights")


def _stash_events(d, entry_id):
    """The lines of `notify/stash-events.jsonl` (the test's NOTIFY_STATE_DIR) of one row."""
    import notify as bus
    f = bus.state_dir(d) / acceptance.STASH_EVENTS
    if not f.is_file():
        return []
    rows = [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in rows if r.get("entry_id") == entry_id]


def test_a_left_out_video_is_in_the_answer_the_commit_and_on_the_bus():
    d = factory()
    render(d, "other-one")                      # the batch's directory is there
    sent = []
    acceptance.NOTIFY = lambda *a, **kw: sent.append((a, kw)) or {"status": "sent"}
    try:
        res = say(d, "no-render", bdir=d / "pipeline" / "rebuilds" / BATCH)
    finally:
        acceptance.NOTIFY = None
    q = res["queued"]
    assert q["code"] == "render_missing" and q["left_out"], q
    assert q["text_ru"].startswith("НЕ В КОПИЛКЕ: ")
    assert "no-render" in q["alert_ru"] and "_queue/" in q["alert_ru"]
    lo = res["left_out"]
    assert lo["entry_id"] == f"{CH}/{BATCH}/no-render" and lo["code"] == "render_missing"
    assert lo["notified"] == {"status": "sent"}
    assert len(sent) == 1
    (kind, key, text), kw = sent[0]
    assert kind == "needs_human" and key == f"stash-left-out:{CH}/{BATCH}/no-render:" \
        "render_missing"
    assert "no-render" in text and "не в копилке" in text and kw["channel"] == CH
    assert "Не в копилке (CF-0821)" in git(d, "log", "-1", "--format=%B")
    # a video that went in is not loud
    render(d, "sophie-adenot")
    ok = say(d, "sophie-adenot")
    assert ok["queued"]["code"] == "placed" and ok["left_out"] is None
    assert not ok["queued"]["left_out"] and ok["queued"]["alert_ru"] is None


def test_another_version_is_left_out_quietly_into_the_stash_journal():
    """CF-0921: `other_version_placed` is about names and versions - the driver's
    (the user's order of 25.10), not the bus: said in the answer and the commit,
    one line in `stash-events.jsonl`, `notified` None."""
    d = factory()
    _version_seeded(d)
    eid = f"{CH}/{BATCH}/harbourlights"
    sent = []
    acceptance.NOTIFY = lambda *a, **kw: sent.append((a, kw)) or {"status": "sent"}
    try:
        res = say(d, "harbourlights")
    finally:
        acceptance.NOTIFY = None
    q = res["queued"]
    assert q["code"] == "other_version_placed" and q["left_out"] and q["skipped"], q
    assert "other_version_placed" in acceptance.LEFT_OUT_QUIET
    assert q["text_ru"].startswith("НЕ В КОПИЛКЕ: ") and "--other-version-ok" in q["text_ru"]
    assert sent == [] and q.get("notified") is None and res["left_out"]["notified"] is None
    assert "нужен человек" not in q["alert_ru"]
    # the same topic: a sure version, nothing left for the driver to decide
    assert q["version_unsure"] is False and q["other_entry"] == f"{CH}/2026-10-01T0000Z/harbourlights"
    assert "Не в копилке (CF-0821)" in git(d, "log", "-1", "--format=%B")
    ev = _stash_events(d, eid)
    assert len(ev) == 1 and ev[0]["action"] == "other_version_placed", ev
    assert ev[0]["channel"] == CH and ev[0]["other"] == f"{CH}/2026-10-01T0000Z/harbourlights"
    assert ev[0]["other_path"] == f"publish/{CH}/2026-10-07/harbourlights.mp4"
    assert ev[0]["unsure"] is False and "--other-version-ok" in ev[0]["repair"]
    row = [r for r in rows_of(d) if r["entry_id"] == eid][0]
    assert row["verdict"] == "accepted" and row["publish_path"] is None


def test_under_a_batch_the_bus_hears_it_once_and_commit_pending_says_it_too():
    import notify as bus
    d = factory()
    render(d, "other-one")              # the bus journal is shared: another name
    going = [(d / "pipeline" / CH / "2026-10-13T1000Z", NOW, True)]
    res = say(d, "unrendered", open_rows=going, bdir=d / "pipeline" / "rebuilds" / BATCH)
    assert res["pending"] and res["left_out"]["notified"]["status"] == "sent", res["left_out"]
    out = acceptance.commit_pending(d, open_rows=[])
    assert out["committed"] and [x["code"] for x in out["left_out"]] == ["render_missing"]
    assert out["left_out"][0]["notified"]["status"] == "duplicate"
    key = f"stash-left-out:{CH}/{BATCH}/unrendered:render_missing"
    mine = [r for r in bus.rows(d) if r.get("key") == key]
    assert len(mine) == 1 and mine[0]["kind"] == "needs_human"
    assert "publishing?channel=" + CH in (mine[0]["link"] or "")


def test_the_bus_names_the_current_channel_when_the_answer_carries_a_former_id():
    """CF-0835 (CF-0197): an answer or a row frozen before a rename carries the
    channel's old id; the bus line and its link go to the channel as it is now."""
    d = factory()
    (d / "channels" / f"{CH}.json").write_text(
        json.dumps({"former_channel_ids": ["sci-old"]}) + "\n", encoding="utf-8")
    row = {"entry_id": f"sci-old/{BATCH}/harbourlights", "slug": "harbourlights", "batch_id": BATCH,
           "channel": "sci-old"}
    sent = []
    acceptance.NOTIFY = lambda *a, **kw: sent.append((a, kw)) or {"status": "sent"}
    try:
        for q in ({"entry_id": row["entry_id"], "code": "slug_taken", "channel": "sci-old"},
                  {"entry_id": row["entry_id"], "code": "slug_taken"}):
            assert acceptance.notify_left_out(q, row, root=d) == {"status": "sent"}
    finally:
        acceptance.NOTIFY = None
    assert [kw["channel"] for _, kw in sent] == [CH, CH], sent
    assert all(a[2].startswith(f"{CH}: ") for a, _ in sent), sent


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
