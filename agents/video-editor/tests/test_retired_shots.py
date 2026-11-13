"""CF-0397: a shot that reached a ready video is retired for the channel.

The registry (`scripts/retired_shots.py`) is written when a video becomes
ready - `write_batch_metadata.py` putting it into videos[] of
05-video-editor.json - and read by `resolve_anchors.py` through
`rhythm.ShotLedger` before any shot is chosen. The source is never retired:
its other shots stay on offer.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import retired_shots as rs  # noqa: E402

# CF-0519: the production default is <root>/publish/acceptance-log.json - the
# user's live verdicts. A test that does not hand its own log reads none
# (DoD 1.6.1 #2); the tests about the log write theirs (acceptance_log()).
rs.default_acceptance_log = lambda: None
import rhythm  # noqa: E402
from test_shot_reuse_once import SRC, _run, anchor, shots_of  # noqa: E402


def registry(tmp_path, videos):
    path = tmp_path / "retired-shots.json"
    doc = rs.empty("example-film")
    doc["videos"] = {eid: {"shots": shots, "retired_at": "t"}
                     for eid, shots in videos.items()}
    path.write_text(json.dumps(doc))
    return path


# --------------------------------------------------------------------------
# the ledger asks the channel's memory
# --------------------------------------------------------------------------

def test_a_retired_shot_is_blocked_and_its_source_is_not():
    retired = rs.Retired({"videos": {"example-film/b1/other": {"shots": ["pool:1"]}}})
    ledger = rhythm.ShotLedger(retired=retired)
    assert ledger.blocked((SRC, 1))
    assert "example-film/b1/other" in ledger.retired((SRC, 1))
    assert "(CF-0397)" in ledger.retired((SRC, 1))
    assert not ledger.blocked((SRC, 2)), "the source must stay on offer"
    assert ledger.retired((SRC, 2)) is None
    assert ledger.fork().blocked((SRC, 1)), "a fork forgot the channel's memory"


def test_no_registry_is_the_old_behaviour():
    ledger = rhythm.ShotLedger()
    assert ledger.retired((SRC, 1)) is None and not ledger.blocked((SRC, 1))


def test_a_video_never_refuses_its_own_shots(tmp_path):
    """A re-render of the same video in its own batch (another attempt,
    --exclude-candidate): its own entry refuses nothing."""
    reg = registry(tmp_path, {"example-film/2026-09-15T1034Z/widows-bay": ["pool:1"],
                              "example-film/2026-09-18T2232Z/other": ["pool:2"]})
    out = tmp_path / "pipeline" / "example-film" / "2026-09-15T1034Z" / "work" / \
        "widows-bay" / "storyboard.json"
    out.parent.mkdir(parents=True)
    r = rs.Retired.for_output(out, registry=reg, channel="example-film")
    assert r.exempt == "example-film/2026-09-15T1034Z/widows-bay"
    assert r.also_exempt == []
    assert r.reason("pool:1") is None
    assert r.reason("pool:2") is not None


def test_a_rebuild_keeps_the_shots_of_the_video_it_rebuilds(tmp_path):
    """CF-0532: a rebuild (`pipeline/rebuilds/<ts>`) is the source video
    replaced - before its 05 exists the source is the batch its copied 03
    names, and with no --channel the channel comes off that record too, not
    the directory name `rebuilds`. Another batch's widows-bay stays refused."""
    pipe = tmp_path / "pipeline"
    (pipe / "example-film").mkdir(parents=True)
    reg = registry(pipe / "example-film", {
        "example-film/2026-09-15T1034Z/widows-bay": ["pool:1"],
        "example-film/2026-09-10T0000Z/widows-bay": ["pool:3"],
        "example-film/2026-09-18T2232Z/other": ["pool:2"]})
    rb = pipe / "rebuilds" / "2026-09-23T0725Z"
    out = rb / "work" / "widows-bay" / "storyboard.json"
    out.parent.mkdir(parents=True)
    (rb / "03-content-researcher.json").write_text(json.dumps(
        {"channel": "example-film", "batch_id": "2026-09-15T1034Z"}))
    r = rs.Retired.for_output(out)
    assert Path(r.path).resolve() == reg.resolve()
    assert r.exempt == "example-film/rebuilds/2026-09-23T0725Z/widows-bay"
    assert r.also_exempt == ["example-film/2026-09-15T1034Z/widows-bay"]
    assert r.reason("pool:1") is None, "a rebuild refused its own source video"
    assert "2026-09-10T0000Z/widows-bay" in r.reason("pool:3"), \
        "another batch's video of the same slug is a second video"
    assert r.reason("pool:2") is not None
    # once the Editor wrote the rebuild's 05, its rebuild_of names the source
    (rb / "03-content-researcher.json").unlink()
    (rb / "05-video-editor.json").write_text(json.dumps(
        {"channel": "example-film", "rebuild_of": {
            "channel": "example-film", "batch_id": "2026-09-15T1034Z",
            "path": "pipeline/example-film/2026-09-15T1034Z", "read_from": "03"}}))
    r = rs.Retired.for_output(out, channel="example-film")
    assert r.also_exempt == ["example-film/2026-09-15T1034Z/widows-bay"]
    assert r.reason("pool:1") is None and r.reason("pool:3") is not None


def test_the_same_slug_in_another_batch_is_refused(tmp_path):
    """CF-0532, the 1825Z regression: delver of 1313Z was ready, delver of
    1825Z (another fact on the same film) is a second video - it may not take
    1313Z's footage. Before the fix every entry of the slug was exempt."""
    reg = registry(tmp_path, {"example-film/2026-10-01T1313Z/delver": ["pool:1", "pool:2"],
                              "example-film/2026-10-04T1825Z/rennick": ["pool:4"]})
    out = tmp_path / "pipeline" / "example-film" / "2026-10-04T1825Z" / "work" / \
        "delver" / "storyboard.json"
    out.parent.mkdir(parents=True)
    r = rs.Retired.for_output(out, registry=reg, channel="example-film")
    assert r.exempt == "example-film/2026-10-04T1825Z/delver" and r.also_exempt == []
    assert "example-film/2026-10-01T1313Z/delver" in r.reason("pool:1")
    assert r.reason("pool:2") is not None and r.reason("pool:4") is not None
    ledger = rhythm.ShotLedger(retired=r)
    assert ledger.blocked((SRC, 1)) and ledger.blocked((SRC, 2))


def test_outside_pipeline_there_is_no_channel_memory(tmp_path):
    r = rs.Retired.for_output(tmp_path / "storyboard.json")
    assert len(r) == 0 and r.path is None


# --------------------------------------------------------------------------
# main(): the real fill loop
# --------------------------------------------------------------------------

def test_a_shot_of_a_ready_video_is_not_offered_a_second_time(tmp_path):
    reg = registry(tmp_path, {"example-film/b1/earlier-video": ["pool:1"]})
    story, _ = _run([anchor(1, "the cottage"), anchor(7, "the lake")],
                    [(1, 0.31), (2, 0.25), (3, 0.24)],
                    extra_args=("--retired-shots", str(reg)))
    shown = shots_of(story)
    assert "pool:1" not in shown, story["blocks"]
    assert "pool:2" in shown, "the retired shot's source must still be offered"
    refused = [r for r in story["rejected_candidates"] if "(CF-0397)" in r["reason"]]
    assert refused and all(r["shot"] == 1 for r in refused)
    assert story["retired_shots"]["refused"] == len(refused)
    assert story["retired_shots"]["registry"] == str(reg)


def test_a_block_left_without_a_shot_falls_down_the_existing_ladder(tmp_path):
    """The only candidate is retired: the storyboard is still written and the
    anchor is unresolved with the retirement as its reason - the same path a
    block the CF-0121 cap empties takes (unresolved, its time carried into
    the next anchor, the rung ladder of build_render_plan after it), never a
    dropped video and never the retired picture."""
    reg = registry(tmp_path, {"example-film/b1/earlier-video": ["pool:1"]})
    story, err = _run([anchor(1, "the cottage"), anchor(7, "the lake")],
                      [(1, 0.31)], extra_args=("--retired-shots", str(reg)))
    assert "pool:1" not in shots_of(story)
    reasons = [u["reason"] for u in story["unresolved_anchors"]]
    assert any("(CF-0397)" in r for r in reasons), reasons
    assert any("carried into the next anchor" in r for r in reasons), reasons
    assert "UNRESOLVED: the cottage" in err


def test_without_a_registry_the_same_run_takes_the_best_shot():
    story, _ = _run([anchor(1, "the cottage"), anchor(7, "the lake")],
                    [(1, 0.31), (2, 0.25), (3, 0.24)])
    assert shots_of(story)[0] == "pool:1"
    assert story["retired_shots"]["retired"] == 0


# --------------------------------------------------------------------------
# writing: a ready video retires its shots, a dropped one gives them back
# --------------------------------------------------------------------------

def plan(*shots):
    return {"blocks": [{"shot": s} for s in shots]}


def batch(root, channel, batch_id, videos, write_plans=True, group=None):
    """A batch under <root>/pipeline/<group or channel>/<batch_id>."""
    bdir = root / "pipeline" / (group or channel) / batch_id
    records = []
    for slug, shots in videos.items():
        records.append({"script_id": f"{slug}-id", "qc": {"passed": True},
                        "output_path": str(bdir / "videos" / f"{slug}.mp4"),
                        "assets": [{"src": f"work/{slug}/clips/a00_{s.split(':')[0]}"
                                           f"_s{int(s.split(':')[1]):03d}.mp4"}
                                   for s in shots]})
        if write_plans:
            (bdir / "work" / slug).mkdir(parents=True, exist_ok=True)
            (bdir / "work" / slug / "plan.json").write_text(json.dumps(plan(*shots)))
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "05-video-editor.json").write_text(json.dumps(
        {"channel": channel, "videos": records,
         "merge_log": [{"videos": [r["script_id"] for r in records]}]}))
    return bdir, records


def test_sync_retires_a_ready_video_and_is_idempotent(tmp_path):
    bdir, recs = batch(tmp_path, "example-film", "2026-09-20T0000Z",
                       {"a": ["AAAAAAAAAAA:1", "AAAAAAAAAAA:2"]})
    reg, added, removed = rs.sync_from_batch(bdir, recs, channel="example-film")
    assert reg.resolve() == \
        (tmp_path / "pipeline" / "example-film" / "retired-shots.json").resolve()
    assert added == ["example-film/2026-09-20T0000Z/a"] and removed == []
    first = reg.read_text()
    assert rs.sync_from_batch(bdir, recs, channel="example-film")[1:] == ([], [])
    assert reg.read_text() == first, "a second sync rewrote the registry"
    doc = rs.load(reg)
    assert doc["videos"]["example-film/2026-09-20T0000Z/a"]["shots"] == \
        ["AAAAAAAAAAA:1", "AAAAAAAAAAA:2"]


def test_a_video_the_batch_drops_gives_its_shots_back(tmp_path):
    bdir, recs = batch(tmp_path, "example-film", "2026-09-20T0000Z",
                       {"a": ["AAAAAAAAAAA:1"], "b": ["BBBBBBBBBBB:4"]})
    reg, _, _ = rs.sync_from_batch(bdir, recs, channel="example-film")
    _, added, removed = rs.sync_from_batch(bdir, recs[:1], channel="example-film")
    assert removed == ["example-film/2026-09-20T0000Z/b"]
    assert rs.Retired(rs.load(reg)).reason("BBBBBBBBBBB:4") is None
    assert rs.Retired(rs.load(reg)).reason("AAAAAAAAAAA:1") is not None


def test_other_batches_are_untouched_and_a_missing_plan_keeps_its_entry(tmp_path):
    b1, r1 = batch(tmp_path, "example-film", "2026-09-19T0000Z", {"x": ["XXXXXXXXXXX:3"]})
    b2, r2 = batch(tmp_path, "example-film", "2026-09-20T0000Z", {"a": ["AAAAAAAAAAA:1"]})
    rs.sync_from_batch(b1, r1, channel="example-film")
    reg, _, _ = rs.sync_from_batch(b2, r2, channel="example-film")
    assert set(rs.load(reg)["videos"]) == {"example-film/2026-09-19T0000Z/x",
                                           "example-film/2026-09-20T0000Z/a"}


def test_a_rebuild_retires_into_its_channel(tmp_path):
    bdir, recs = batch(tmp_path, "example-film", "2026-09-23T0725Z",
                       {"widows-bay": ["hG2tH_gTvRI:12"]}, group="rebuilds")
    # the real acceptance log rejected this very rebuild (CF-0443): read none
    reg, added, _ = rs.sync_from_batch(bdir, recs, channel="example-film",
                                       acceptance_log=tmp_path / "no-log.json")
    assert reg.resolve() == \
        (tmp_path / "pipeline" / "example-film" / "retired-shots.json").resolve()
    assert added == ["example-film/rebuilds/2026-09-23T0725Z/widows-bay"]


def test_a_pre_rename_batch_retires_into_the_current_channel(tmp_path):
    """CF-0197: `legacy-film` is example-film's former id. A batch written
    under it - its directory and its 05 record's `channel` - reads and writes
    the example-film registry; no registry for a name that is gone appears."""
    bdir, recs = batch(tmp_path, "legacy-film", "2026-08-30T1759Z",
                       {"old": ["OOOOOOOOOOO:2"]})
    reg, added, _ = rs.sync_from_batch(bdir, recs, channel="legacy-film")
    assert reg.resolve() == \
        (tmp_path / "pipeline" / "example-film" / "retired-shots.json").resolve()
    assert added == ["example-film/legacy-film/2026-08-30T1759Z/old"]
    assert rs.load(reg)["channel"] == "example-film"
    assert not (tmp_path / "pipeline" / "legacy-film" / rs.REGISTRY_NAME).exists()
    story = tmp_path / "pipeline" / "legacy-film" / "2026-08-30T1759Z" / \
        "work" / "new" / "storyboard.json"
    story.parent.mkdir(parents=True)
    r = rs.Retired.for_output(story, channel="legacy-film")
    assert Path(r.path).resolve() == reg.resolve()
    assert r.reason("OOOOOOOOOOO:2") is not None
    # backfill of the current channel reads the former directory too, and
    # backfill started from the former directory writes the same registry
    chan = tmp_path / "pipeline" / "example-film"
    rs.backfill(chan)
    first = reg.read_text()
    rs.backfill(tmp_path / "pipeline" / "legacy-film")
    assert reg.read_text() == first
    assert not (tmp_path / "pipeline" / "legacy-film" / rs.REGISTRY_NAME).exists()


def test_a_batch_outside_pipeline_writes_nothing(tmp_path):
    bdir = tmp_path / "somewhere" / "batch"
    bdir.mkdir(parents=True)
    assert rs.sync_from_batch(bdir, [{"output_path": "x/a.mp4"}]) is None
    assert not list(tmp_path.rglob(rs.REGISTRY_NAME))


def test_backfill_reads_the_ready_videos_on_disk_idempotently(tmp_path):
    batch(tmp_path, "example-film", "2026-09-19T0000Z", {"x": ["XXXXXXXXXXX:3"]})
    # work/ already cleaned: the shots are read off the record's asset names
    batch(tmp_path, "example-film", "2026-09-15T0000Z", {"old": ["-05WmSAmLK4:7"]},
          write_plans=False)
    batch(tmp_path, "example-film", "2026-09-23T0725Z", {"x": ["XXXXXXXXXXX:9"]},
          group="rebuilds")
    chan = tmp_path / "pipeline" / "example-film"
    also = [tmp_path / "pipeline" / "rebuilds"]
    rs.backfill(chan, also=also)
    reg = rs.registry_path(chan)
    first = reg.read_text()
    assert all(a == [] and r == [] for a, r in rs.backfill(chan, also=also).values())
    assert reg.read_text() == first
    videos = rs.load(reg)["videos"]
    assert videos["example-film/2026-09-15T0000Z/old"]["shots"] == ["-05WmSAmLK4:7"]
    assert "example-film/rebuilds/2026-09-23T0725Z/x" in videos


def test_cost_counts_a_shot_an_earlier_ready_video_showed(tmp_path):
    batch(tmp_path, "example-film", "2026-09-19T0000Z", {"x": ["XXXXXXXXXXX:3"]})
    batch(tmp_path, "example-film", "2026-09-20T0000Z",
          {"x": ["XXXXXXXXXXX:3"], "y": ["XXXXXXXXXXX:3", "XXXXXXXXXXX:4"]})
    rep = rs.cost(tmp_path / "pipeline" / "example-film", last=1)
    assert rep["ready_videos"] == 2
    # CF-0532: x of 0920Z is a second video on the same slug, not x of 0919Z
    assert [a["video"] for a in rep["affected_videos"]] == \
        ["example-film/2026-09-20T0000Z/x", "example-film/2026-09-20T0000Z/y"]
    assert rep["blocks_lost"] == 2


def test_cost_lets_a_rebuild_keep_the_video_it_rebuilds(tmp_path):
    batch(tmp_path, "example-film", "2026-09-19T0000Z", {"x": ["XXXXXXXXXXX:3"]})
    rb, _ = batch(tmp_path, "example-film", "2026-09-20T0000Z",
                  {"x": ["XXXXXXXXXXX:3"]}, group="rebuilds")
    (rb / "03-content-researcher.json").write_text(json.dumps(
        {"channel": "example-film", "batch_id": "2026-09-19T0000Z"}))
    rep = rs.cost(tmp_path / "pipeline" / "example-film", last=1,
                  also=[tmp_path / "pipeline" / "rebuilds"])
    assert rep["ready_videos"] == 1
    assert rep["affected_videos"] == [], "a rebuild of x is not a second video"


# --------------------------------------------------------------------------
# CF-0443: only a video that goes to the user retires its shots; what the
# user sends back returns them
# --------------------------------------------------------------------------

def acceptance_log(tmp_path, *rows):
    """A publish/acceptance-log.json with rows (entry_id, verdict)."""
    path = tmp_path / "acceptance-log.json"
    out = []
    for eid, verdict in rows:
        bits = eid.split("/")
        out.append({"entry_id": eid, "slug": bits[-1], "channel": bits[0],
                    "batch_id": bits[-2], "verdict": verdict,
                    "reason_code": "frozen_frame" if verdict == "rejected" else None,
                    "answered_at": "2026-09-30"})
    path.write_text(json.dumps({"task": "CF-0328", "acceptances": out}))
    return path


def set_record(bdir, slug, **fields):
    """Change one videos[] record of the batch's 05 and return the list."""
    rec = bdir / "05-video-editor.json"
    doc = json.loads(rec.read_text())
    for v in doc["videos"]:
        if v["script_id"] == f"{slug}-id":
            v.update(fields)
    rec.write_text(json.dumps(doc))
    return doc["videos"]


def test_a_harbourlights_like_video_does_not_retire_its_shots(tmp_path):
    """0705Z: `harbourlights` was in videos[] with qc.passed false and a NEEDS-YOU
    line; its shots were taken from every later video."""
    bdir, _ = batch(tmp_path, "example-film", "2026-09-29T0705Z",
                    {"vanguards-endgame": ["EEEEEEEEEEE:1"],
                     "harbourlights": ["LLLLLLLLLLL:3", "LLLLLLLLLLL:7"]})
    recs = set_record(bdir, "harbourlights", qc={"passed": False},
                      needs_you="NEEDS-YOU harbourlights: attempt cap 3 reached")
    none = tmp_path / "no-log.json"
    synced = rs.sync_from_batch(bdir, recs, channel="example-film", acceptance_log=none)
    reg, added, _ = synced
    assert added == ["example-film/2026-09-29T0705Z/vanguards-endgame"]
    assert set(synced.held) == {"harbourlights"} and "needs_you" in synced.held["harbourlights"]
    r = rs.Retired(rs.load(reg))
    assert r.reason("LLLLLLLLLLL:3") is None and r.reason("LLLLLLLLLLL:7") is None
    assert r.reason("EEEEEEEEEEE:1") is not None
    # QC failed with no NEEDS-YOU: held too, with its own reason
    recs = set_record(bdir, "harbourlights", needs_you=None)
    synced = rs.sync_from_batch(bdir, recs, channel="example-film", acceptance_log=none)
    assert synced.held["harbourlights"].startswith("qc failed")
    # an older registry that retired it is corrected by the next write
    doc = rs.load(reg)
    doc["videos"]["example-film/2026-09-29T0705Z/harbourlights"] = \
        {"shots": ["LLLLLLLLLLL:3"], "retired_at": "t"}
    rs.write_atomic(reg, doc)
    _, _, removed = rs.sync_from_batch(bdir, recs, channel="example-film",
                                       acceptance_log=none)
    assert removed == ["example-film/2026-09-29T0705Z/harbourlights"]


def test_admitted_to_the_judge_retires_and_tier_f_or_judge_reject_does_not(tmp_path):
    bdir, _ = batch(tmp_path, "example-film", "2026-09-29T0705Z",
                    {"cosmetic": ["CCCCCCCCCCC:1"], "tier-f": ["FFFFFFFFFFF:2"],
                     "judged-out": ["JJJJJJJJJJJ:4"]})
    set_record(bdir, "cosmetic", qc={"passed": False},
               judge_admitted_despite=["meme_caption_blank_blocks"])
    recs = set_record(bdir, "tier-f", score={"passed": False, "score": 41,
                                             "threshold": 60, "tier": "F"})
    (bdir / rs.JUDGE_RECORD).write_text(json.dumps({"videos": [
        {"slug": "cosmetic", "gate": "pass", "reason_code": None},
        {"slug": "judged-out", "gate": "reject", "reason_code": "frame_judge_failed"}]}))
    synced = rs.sync_from_batch(bdir, recs, channel="example-film",
                                acceptance_log=tmp_path / "no-log.json")
    assert synced[1] == ["example-film/2026-09-29T0705Z/cosmetic"]
    assert "under N 60" in synced.held["tier-f"]
    assert "frame_judge_failed" in synced.held["judged-out"]


def test_a_video_the_user_rejected_gives_its_shots_back(tmp_path):
    bdir, recs = batch(tmp_path, "example-film", "2026-09-29T0705Z",
                       {"vanguards-doomsday": ["DDDDDDDDDDD:1", "DDDDDDDDDDD:2"],
                        "vanguards-endgame": ["EEEEEEEEEEE:1"]})
    log = acceptance_log(tmp_path)
    reg, _, _ = rs.sync_from_batch(bdir, recs, channel="example-film", acceptance_log=log)
    assert rs.Retired(rs.load(reg)).reason("DDDDDDDDDDD:1") is not None
    # days later the user answers; the next write of the registry - any
    # batch's - returns the rejected video's shots and keeps the accepted one's
    acceptance_log(tmp_path, ("example-film/2026-09-29T0705Z/vanguards-doomsday", "rejected"),
                   ("example-film/2026-09-29T0705Z/vanguards-endgame", "accepted"))
    b2, r2 = batch(tmp_path, "example-film", "2026-09-30T0900Z", {"next": ["NNNNNNNNNNN:1"]})
    synced = rs.sync_from_batch(b2, r2, channel="example-film", acceptance_log=log)
    assert synced.returned == ["example-film/2026-09-29T0705Z/vanguards-doomsday"]
    doc = rs.load(reg)
    back = doc["returned"]["example-film/2026-09-29T0705Z/vanguards-doomsday"]
    assert back["shots"] == ["DDDDDDDDDDD:1", "DDDDDDDDDDD:2"]
    assert back["returned_by"] == "acceptance" and "frozen_frame" in back["reason"]
    assert "example-film/2026-09-29T0705Z/vanguards-doomsday" not in doc["videos"]
    r = rs.Retired(doc)
    assert r.reason("DDDDDDDDDDD:1") is None and r.reason("DDDDDDDDDDD:2") is None
    assert r.reason("EEEEEEEEEEE:1") is not None, "an accepted video stays retired"
    # idempotent, and a re-write of the rejected video's own batch keeps it returned
    first = reg.read_text()
    assert rs.sync_from_batch(b2, r2, channel="example-film",
                              acceptance_log=log).returned == []
    rs.sync_from_batch(bdir, recs, channel="example-film", acceptance_log=log)
    assert reg.read_text() == first
    # the user changes his mind: accepted - the shots retire again
    acceptance_log(tmp_path, ("example-film/2026-09-29T0705Z/vanguards-doomsday", "accepted"))
    rs.sync_from_batch(b2, r2, channel="example-film", acceptance_log=log)
    doc = rs.load(reg)
    assert doc["returned"] == {}
    assert rs.Retired(doc).reason("DDDDDDDDDDD:1") is not None


def test_a_held_video_the_user_accepted_retires(tmp_path):
    """The user saw it and took it (harbourlights, accepted on 30.09): it will be on
    the channel, so its shots retire whatever QC said."""
    bdir, _ = batch(tmp_path, "example-film", "2026-09-29T0705Z",
                    {"harbourlights": ["LLLLLLLLLLL:3"]})
    recs = set_record(bdir, "harbourlights", qc={"passed": False}, needs_you="NEEDS-YOU x")
    log = acceptance_log(tmp_path, ("example-film/2026-09-29T0705Z/harbourlights", "accepted"))
    reg, added, _ = rs.sync_from_batch(bdir, recs, channel="example-film", acceptance_log=log)
    assert added == ["example-film/2026-09-29T0705Z/harbourlights"]
    assert rs.Retired(rs.load(reg)).reason("LLLLLLLLLLL:3") is not None


def test_a_rejected_rebuild_gives_its_shots_back(tmp_path):
    """A rebuild is `example-film/rebuilds/<ts>/<slug>` in the registry and
    `rebuilds/<ts>/<slug>` in the acceptance log (CF-0416)."""
    bdir, recs = batch(tmp_path, "example-film", "2026-09-27T1757Z",
                       {"kaijura-minus-zero": ["GGGGGGGGGGG:5"],
                        "wolfhame": ["WWWWWWWWWWW:1"]}, group="rebuilds")
    log = tmp_path / "acceptance-log.json"
    log.write_text(json.dumps({"acceptances": [
        {"entry_id": "rebuilds/2026-09-27T1757Z/kaijura-minus-zero", "slug":
         "kaijura-minus-zero", "channel": "example-film", "batch_id": "2026-09-27T1757Z",
         "verdict": "rejected", "reason_code": "slideshow"},
        {"entry_id": "rebuilds/2026-09-27T1757Z/wolfhame", "slug": "wolfhame",
         "channel": "example-film", "batch_id": "2026-09-27T1757Z", "verdict": "accepted"}]}))
    synced = rs.sync_from_batch(bdir, recs, channel="example-film", acceptance_log=log)
    doc = rs.load(synced[0])
    assert list(doc["returned"]) == ["example-film/rebuilds/2026-09-27T1757Z/kaijura-minus-zero"]
    assert list(doc["videos"]) == ["example-film/rebuilds/2026-09-27T1757Z/wolfhame"]


def test_a_judge_reject_of_an_earlier_batch_returns_at_the_next_write(tmp_path):
    """The judge runs after the Editor wrote the registry: its reject is read
    off the batch's 06 at the next write."""
    b1, r1 = batch(tmp_path, "example-film", "2026-09-29T0705Z", {"a": ["AAAAAAAAAAA:1"]})
    reg, _, _ = rs.sync_from_batch(b1, r1, channel="example-film",
                                   acceptance_log=tmp_path / "no-log.json")
    assert rs.Retired(rs.load(reg)).reason("AAAAAAAAAAA:1") is not None
    (b1 / rs.JUDGE_RECORD).write_text(json.dumps({"videos": [
        {"slug": "a", "gate": "reject", "reason_code": "score_below_threshold"}]}))
    b2, r2 = batch(tmp_path, "example-film", "2026-09-30T0900Z", {"b": ["BBBBBBBBBBB:1"]})
    synced = rs.sync_from_batch(b2, r2, channel="example-film",
                                acceptance_log=tmp_path / "no-log.json")
    assert synced.returned == ["example-film/2026-09-29T0705Z/a"]
    doc = rs.load(reg)
    assert doc["returned"]["example-film/2026-09-29T0705Z/a"]["returned_by"] == "frame_judge"
    assert rs.Retired(doc).reason("AAAAAAAAAAA:1") is None
    # the user's verdict wins over the judge: accepted keeps it retired
    log = acceptance_log(tmp_path, ("example-film/2026-09-29T0705Z/a", "accepted"))
    rs.sync_from_batch(b2, r2, channel="example-film", acceptance_log=log)
    assert rs.Retired(rs.load(reg)).reason("AAAAAAAAAAA:1") is not None


def test_backfill_applies_the_rule_and_the_returns(tmp_path):
    bdir, _ = batch(tmp_path, "example-film", "2026-09-29T0705Z",
                    {"good": ["GGGGGGGGGGG:1"], "bad": ["BBBBBBBBBBB:1"],
                     "gone": ["XXXXXXXXXXX:1"]})
    set_record(bdir, "bad", qc={"passed": False})
    log = acceptance_log(tmp_path, ("example-film/2026-09-29T0705Z/gone", "rejected"))
    chan = tmp_path / "pipeline" / "example-film"
    rs.backfill(chan, acceptance_log=log)
    doc = rs.load(rs.registry_path(chan))
    assert list(doc["videos"]) == ["example-film/2026-09-29T0705Z/good"]
    assert list(doc["returned"]) == ["example-film/2026-09-29T0705Z/gone"]
    first = rs.registry_path(chan).read_text()
    rs.backfill(chan, acceptance_log=log)
    assert rs.registry_path(chan).read_text() == first


def test_an_unreadable_acceptance_log_is_an_error_not_no_verdicts(tmp_path):
    bdir, recs = batch(tmp_path, "example-film", "2026-09-29T0705Z", {"a": ["AAAAAAAAAAA:1"]})
    log = tmp_path / "acceptance-log.json"
    log.write_text("{not json")
    try:
        rs.sync_from_batch(bdir, recs, channel="example-film", acceptance_log=log)
    except rs.RegistryError:
        pass
    else:
        raise AssertionError("a log nobody can read was read as no verdicts")


def test_local_judge_candidate_matches_the_root():
    """The local copy is the fallback for a checkout without the root; the
    root's funnel.judge_candidate is the rule (one rule for the judge, the
    funnel and this registry)."""
    root = rs.root_judge_candidate()
    assert root is not None, "the root's funnel.judge_candidate is not reachable"
    cases = [{}, {"qc": {"passed": True}}, {"qc": {"passed": False}},
             {"qc": {"passed": True}, "needs_you": "NEEDS-YOU x"},
             {"qc": {"passed": False}, "judge_admitted_despite": ["meme_caption_blank_blocks"]},
             {"qc": {"passed": False}, "judge_admitted_despite": [" "]},
             {"qc": {"passed": False}, "judge_admitted_despite": "x"},
             {"qc": {"passed": True}, "needs_you": "y",
              "judge_admitted_despite": ["meme_caption_blank_blocks"]},
             {"qc": None}, {"qc": {"passed": "true"}}]
    for c in cases:
        assert bool(root(c)) == rs._local_judge_candidate(c), c


# --------------------------------------------------------------------------
# what a video shows
# --------------------------------------------------------------------------

def test_block_shots_reads_every_picture_and_no_offer():
    storyboard_split = {"asset_kind": "split", "shot": None,
                        "split": [{"shot": "AAAAAAAAAAA:1",
                                   "cuts": [{"shot": "AAAAAAAAAAA:1"},
                                            {"shot": "AAAAAAAAAAA:5"}]},
                                  {"shot": "BBBBBBBBBBB:2", "cuts": []}]}
    plan_split = {"asset": {"kind": "split", "sides": [
        {"cuts": [{"shot": "CCCCCCCCCCC:1"}]}, {"cuts": [{"shot": "DDDDDDDDDDD:2"}]}]}}
    ordinary = {"shot": "EEEEEEEEEEE:3",
                "candidate_supply": {"nearest": {"shot": "FFFFFFFFFFF:9"}},
                "topic_fill": {"shot": "EEEEEEEEEEE:3"}}
    assert rs.block_shots(storyboard_split) == ["AAAAAAAAAAA:1", "AAAAAAAAAAA:5",
                                                "BBBBBBBBBBB:2"]
    assert rs.block_shots(plan_split) == ["CCCCCCCCCCC:1", "DDDDDDDDDDD:2"]
    assert rs.block_shots(ordinary) == ["EEEEEEEEEEE:3"]
    before_shot_names = {"asset": {"kind": "clip", "src":
                                   "/p/work/x/clips/a00_H-43VeYGiPM_s012.mp4"}}
    assert rs.block_shots(before_shot_names) == ["H-43VeYGiPM:12"]
    assert rs.record_shots({"assets": [
        {"src": "work/p/clips/s01_held_a01_MLwTyQOhBkw_s053.png"},
        {"src": "work/p/clips/a00_dPmklyud1P8_s001.mp4"}, {"src": None}]}) == \
        ["MLwTyQOhBkw:53", "dPmklyud1P8:1"]


if __name__ == "__main__":
    import inspect
    import tempfile
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            if inspect.signature(t).parameters:
                with tempfile.TemporaryDirectory() as tmp:
                    t(Path(tmp))
            else:
                t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
