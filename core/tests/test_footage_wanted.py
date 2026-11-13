#!/usr/bin/env python3
"""CF-0023: the list of footage to get (`agents/analyst/footage_wanted.py`).

Every root is a synthetic factory in a temp dir - the live `pipeline/`,
`shared/footage/` and `analytics/` are never read or written.

What is pinned:

* every reason a stage records is extracted: 05 unresolved anchors (no
  picture / short), 06 `contradicts` / `foreign`, 03 warnings
  (`pool_too_thin`, `no_second_source`, `event_footage_short`,
  `visual_claim_uncovered`), 03 skipped, 05 refusals, 01 `no_source` /
  `rights_exclusion` - and nothing from an anchor that was resolved;
* the kind of a row: the topic's work, a person an anchor names, the event of
  `event_footage_short`, a scene of the work otherwise; a person topic is a
  person;
* one name from many batches is one row (case, accents, punctuation folded);
  a rebuild of the same topic is one topic, two batches;
* rows go most topics first, then the most recent;
* a packed batch is read from the month's zip in place (nothing unpacked), a
  batch both on disk and in a zip is read once, a missing archive is a note;
* "in the pool now" is a run of words in the index title / note, a candidate
  already fetched is marked; "where" is only the requests' candidates and the
  official channels of the channel's own `channels/<id>/footage-origin.json`
  - nothing for a work without them; a channel without that file is a note,
  the trend-hunter's old `config/footage_origin.json` is never read, a former
  id reads the current channel's list, and the tracked example-film list is
  not empty on this tree (CF-0631: the move of CF-0627 emptied "where"
  silently while this file kept writing its own stand on the old path);
* `--channel` keeps another channel's rebuilds out, `--since` drops older
  batches, an unknown channel exits 2; the CLI writes md + json, prints TOTAL,
  and a rerun at the same `--now` writes the same bytes;
* the archive path and the non-channel folders are the ones of
  `scripts/monthly_archive.py` / `gate_price.NOT_CHANNELS`.
"""
import io
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "analyst"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))

import footage_wanted as fw         # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("footage-wanted-test-")
_n = [0]
CH, OTHER = "reelch", "otherch"
NOW = "2026-10-06T12:00:00Z"


def _w(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _root():
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    for ch in (CH, OTHER):
        _w(r / "channels" / f"{ch}.json", {"channel": ch})
    _w(r / "shared" / "footage" / "index.json", {"entries": [
        {"id": "POOL1", "title": "Harbourlights | Official Trailer | Example Max", "note": ""},
        {"id": "POOL2", "title": "Something else", "note": "BTS of The Lantern Makers"},
        {"id": "CAND1", "title": "Teaser", "note": ""},
    ]})
    _w(r / "channels" / CH / "footage-origin.json", {"official_channels": [
        {"pattern": "example network", "owners": ["example network"], "channels": [{"id": "UC_Example_Network", "title": "Example Max"}]},
        {"pattern": "examplestream", "channels": [{"id": "UC_NF", "title": "ExampleStream"}]},
    ]})
    return r


def _topic(tid, name, kind="work", network=None):
    return {"topic_id": tid, "title_ref": {"name": name, "kind": kind, "network": network,
                                           "rights_holder": network,
                                           "person": name if kind == "person" else None}}


def _batch(r, name, channel=CH, group=None, topics=(), skipped=(), warnings=(), skipped3=(),
           videos=(), refusals=(), judged=(), step=None, requests=(), consumed=()):
    b = r / "pipeline" / (group or channel) / name
    _w(b / "01-trend-hunter.json", {"channel": channel, "topics": list(topics),
                                    "skipped_topics": list(skipped)})
    _w(b / "03-content-researcher.json", {"channel": channel, "warnings": list(warnings),
                                          "skipped": list(skipped3), "scripts": [
        {"script_id": f"{t['topic_id']}-script1", "topic_id": t["topic_id"]} for t in topics]})
    _w(b / "05-video-editor.json", {"channel": channel, "videos": list(videos),
                                    "refusals": list(refusals)})
    if judged:
        _w(b / "06-frame-judge.json", {"channel": channel, "videos": list(judged)})
    if step:
        _w(b / "work" / "supplement-step.json", {"topics": step})
    for q in requests:
        _w(b / "work" / "supplement-requests" / f"{q['topic_id']}.json", q)
    for q in consumed:
        _w(b / "work" / "supplement-requests" / "consumed" / f"{q['topic_id']}.json", q)
    return b


def _unresolved(sid, *anchors):
    return {"script_id": sid, "unresolved_anchors": [
        {"phrase": p, "reason": why} for p, why in anchors]}


NO_PIC = "every candidate failed a gate - shot 3: scores 0.19, under the 0.22 similarity floor"
SHORT = "resolved candidates cover only 4.77s of 7.36s needed - 2.59s shortfall"


def _rows(rep, kind=None):
    return {(r["kind"], r["name"]): r for r in rep["rows"] if kind in (None, r["kind"])}


def _build(r, **kw):
    kw.setdefault("archive", None)
    return fw.build(r, CH, now=NOW, **kw)


# ---------------------------------------------------------------- extraction
def _full_batch(r):
    return _batch(
        r, "2026-10-01T1000Z",
        topics=[_topic("t1", "Harbourlights", network="Example Max"), _topic("t2", "East of Eden"),
                _topic("t3", "Dana Reyes", kind="person"), _topic("t4", "WNL")],
        skipped=[{"topic_id": "t9", "reason_code": "no_source", "title": "Lost Show", "kind": "work"},
                 {"topic_id": "t8", "reason_code": "rights_exclusion", "title": "Struck Film"},
                 {"topic_id": "t7", "reason_code": "below_shortlist", "title": "Not A Need"}],
        warnings=[
            {"topic_id": "t1", "script_id": "t1-script1", "warning_code": "pool_too_thin",
             "gate": "block_capacity", "detail": "3 anchors more than the pool",
             "supplement": {"anchors": [{"anchor_id": "v2", "phrase": "Aaron Pryce in the cell",
                                         "entities": [{"name": "Aaron Pryce", "kind": "person"}]}]}},
            {"topic_id": "t1", "script_id": "t1-script1", "warning_code": "pool_too_thin",
             "gate": "anchor_coverage"},
            {"topic_id": "t2", "script_id": "t2-script1", "warning_code": "no_second_source"},
            {"topic_id": "t4", "script_id": "t4-script1", "warning_code": "event_footage_short"},
            {"topic_id": "t2", "script_id": "t2-script1", "warning_code": "visual_claim_uncovered",
             "numbers": {"claims": [{"section": "payoff", "claim": "one scene", "anchors": [
                 {"anchor_id": "v9", "status": "absent", "phrase": "a farmhouse at dusk"},
                 {"anchor_id": "v8", "status": "present", "phrase": "resolved one"}]}]}},
            {"topic_id": "t2", "script_id": "t2-script1", "warning_code": "foreign_interview_anchor"},
        ],
        skipped3=[{"topic_id": "t6", "reason_code": "pool_too_thin", "reason": "x"},
                  {"topic_id": "t5", "reason_code": "thin_scene", "reason": "writing, not footage"}],
        videos=[_unresolved("t1-script1", ("a green lantern ring glowing", NO_PIC),
                            ("Aaron Pryce in the cell", SHORT)),
                {"script_id": "t2-script1", "unresolved_anchors": []}],
        refusals=[{"script_id": "t3-script1", "reason_code": "pool_too_thin", "reason": "refused"},
                  {"script_id": "t2-script1", "reason_code": "score_below_threshold"}],
        judged=[{"script_id": "t3-script1", "verdicts": [
            {"verdict": "contradicts", "narration": "the wave-shaped building", "why": "no building"},
            {"verdict": "foreign", "narration": "Utah Temple", "why": "a selfie clip"},
            {"verdict": "neutral", "narration": "fine"}, {"verdict": "backs", "narration": "ok"}]}],
        step={"t4": {"outcome": "wall_ceiling"}, "t1": {"outcome": "sources"}},
        requests=[{"topic_id": "t4", "reason_code": "event_footage_short", "entities": [
            {"name": "WNL", "kind": "work"}, {"name": "Dana Reyes monologue", "kind": "scene"}],
            "candidates": [{"video_id": "CAND1", "entity": "WNL", "title": "WNL monologue",
                            "channel_title": "WNL", "origin": "official"}]}],
        consumed=[{"topic_id": "t1", "entities": [{"name": "Harbourlights", "kind": "work"},
                                                  {"name": "Aaron Pryce", "kind": "person"}]}])


def test_every_recorded_reason_is_extracted_and_nothing_else():
    r = _root()
    _full_batch(r)
    rep = _build(r)
    assert rep["by_reason"] == {
        "anchor_no_picture": 1, "anchor_short": 1, "event_footage_short": 1,
        "frame_contradicts": 1, "frame_foreign": 1, "no_second_source": 1, "no_source": 1,
        "pool_too_thin": 2, "rights_exclusion": 1, "visual_claim_uncovered": 1}, rep["by_reason"]
    names = {r_["name"] for r_ in rep["rows"]}
    assert "Not A Need" not in names and not any("resolved one" in str(x["examples"]) for x in rep["rows"])
    assert rep["batches"]["read"] == 1 and rep["needs"] == 11
    assert any("without a name" in n and "t6 pool_too_thin" in n for n in rep["notes"]), \
        "a refusal of a topic no record names is a note, never a guessed row"


def test_the_kind_of_a_row():
    r = _root()
    _full_batch(r)
    rows = _rows(_build(r))
    assert rows[("work", "Harbourlights")]["reasons"] == {"pool_too_thin": 1}, \
        "two warnings of one topic and one code are one need"
    assert rows[("work", "Harbourlights")]["searched"] == ["Harbourlights", "Aaron Pryce"]
    assert rows[("work", "Harbourlights")]["supplement_outcomes"] == {"sources": 1}
    assert rows[("person", "Aaron Pryce")]["reasons"] == {"anchor_short": 1}
    assert rows[("person", "Aaron Pryce")]["of_topics"] == ["Harbourlights"]
    assert rows[("scene", "Harbourlights")]["examples"] == ["a green lantern ring glowing"]
    assert rows[("scene", "East of Eden")]["reasons"] == {"visual_claim_uncovered": 1}
    assert rows[("event", "Dana Reyes monologue")]["supplement_outcomes"] == {"wall_ceiling": 1}
    assert rows[("person", "Dana Reyes")]["reasons"] == {"pool_too_thin": 1}, \
        "a person topic's refusal is the person"
    assert rows[("scene", "Dana Reyes")]["reasons"] == {"frame_contradicts": 1, "frame_foreign": 1}
    assert rows[("work", "Lost Show")]["reasons"] == {"no_source": 1}
    assert rows[("work", "Struck Film")]["reasons"] == {"rights_exclusion": 1}


# ------------------------------------------------------------- normalization
def test_one_name_from_many_batches_is_one_row():
    r = _root()
    _batch(r, "2026-09-20T1000Z", topics=[_topic("a1", "Harbourlights")],
           warnings=[{"topic_id": "a1", "script_id": "a1-script1", "warning_code": "pool_too_thin"}])
    _batch(r, "2026-09-25T1000Z", topics=[_topic("b1", "LANTÉRNS!")],
           warnings=[{"topic_id": "b1", "script_id": "b1-script1", "warning_code": "no_second_source"}])
    _batch(r, "2026-09-26T1000Z", topics=[_topic("c1", "Harbourlights")],
           warnings=[{"topic_id": "c1", "script_id": "c1-script1", "warning_code": "pool_too_thin"}])
    rows = [x for x in _build(r)["rows"] if x["kind"] == "work"]
    assert len(rows) == 1, rows
    row = rows[0]
    assert (row["topics"], row["batches"], row["misses"]) == (3, 3, 3)
    assert row["first_seen"] == "2026-09-20" and row["last_seen"] == "2026-09-26"
    assert row["name"] == "Harbourlights", "the spelling used most"
    assert fw.norm("Vanguards: Doomsday") == fw.norm("vanguards doomsday")


def test_a_rebuild_of_the_same_topic_is_one_topic_two_batches():
    r = _root()
    w = [{"topic_id": "t1", "script_id": "t1-script1", "warning_code": "pool_too_thin"}]
    _batch(r, "2026-09-27T0929Z", topics=[_topic("t1", "Day Drinker")], warnings=w)
    _batch(r, "2026-09-30T1248Z", group="rebuilds", topics=[_topic("t1", "Day Drinker")], warnings=w)
    row = _rows(_build(r))[("work", "Day Drinker")]
    assert (row["topics"], row["batches"]) == (1, 2), row


# ------------------------------------------------------------------- sorting
def test_rows_go_most_topics_first_then_the_most_recent():
    r = _root()
    def warn(t):
        return {"topic_id": t, "script_id": f"{t}-script1", "warning_code": "pool_too_thin"}
    _batch(r, "2026-09-01T1000Z", topics=[_topic("o1", "Old Twice"), _topic("o2", "Old Once")],
           warnings=[warn("o1"), warn("o2")])
    _batch(r, "2026-09-02T1000Z", topics=[_topic("o3", "Old Twice")], warnings=[warn("o3")])
    _batch(r, "2026-10-01T1000Z", topics=[_topic("n1", "New Once")], warnings=[warn("n1")])
    order = [x["name"] for x in _build(r)["rows"]]
    assert order == ["Old Twice", "New Once", "Old Once"], order
    rows = fw.sort_rows([
        {"kind": "work", "name": "B", "topics": 1, "last_seen": "2026-10-01", "misses": 1},
        {"kind": "work", "name": "A", "topics": 1, "last_seen": "2026-10-01", "misses": 5}])
    assert [x["name"] for x in rows] == ["A", "B"], "same topics and day: more misses first"


# -------------------------------------------------------------------- packed
def _pack(r, archive, group, month, batch_dir):
    z = archive / group / f"{month}.zip"
    z.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z, "a" if z.exists() else "w") as zf:
        for p in sorted(batch_dir.rglob("*")):
            if p.is_file():
                zf.write(p, f"{batch_dir.name}/{p.relative_to(batch_dir)}")
    return z


def test_a_packed_batch_is_read_in_place_and_once():
    r = _root()
    arch = TMP / f"arch{_n[0]}"
    old = _batch(r, "2026-08-20T1000Z", topics=[_topic("p1", "Packed Show")],
                 videos=[_unresolved("p1-script1", ("a lighthouse", NO_PIC))])
    _pack(r, arch, CH, "2026-08", old)
    import shutil
    shutil.rmtree(old)                                    # gone from disk, as monthly_archive does
    both = _batch(r, "2026-09-10T1000Z", topics=[_topic("p2", "Packed Show")],
                  videos=[_unresolved("p2-script1", ("a harbour", NO_PIC))])
    _pack(r, arch, CH, "2026-09", both)                   # still on disk too
    before = sorted(str(p) for p in arch.rglob("*"))
    rep = _build(r, archive=arch)
    row = _rows(rep)[("scene", "Packed Show")]
    assert rep["batches"]["read"] == 2 and rep["batches"]["packed"] == 1, rep["batches"]
    assert (row["topics"], row["batches"], row["misses"]) == (2, 2, 2), row
    assert row["packed_batches"] == ["2026-08-20T1000Z"]
    assert sorted(str(p) for p in arch.rglob("*")) == before, "nothing unpacked next to the zip"
    rep = _build(r, archive=TMP / "no-such-volume")
    assert rep["batches"]["read"] == 1 and any("is not there" in n for n in rep["notes"]), rep["notes"]


def test_a_broken_zip_is_a_note_not_a_crash():
    r = _root()
    arch = TMP / f"arch{_n[0]}"
    (arch / CH).mkdir(parents=True)
    (arch / CH / "2026-08.zip").write_bytes(b"not a zip")
    rep = _build(r, archive=arch)
    assert any("unreadable" in n for n in rep["notes"]), rep["notes"]


# ------------------------------------------------------------- pool and where
def test_in_the_pool_now_is_a_run_of_words():
    r = _root()
    _full_batch(r)
    rows = _rows(_build(r))
    assert [p["id"] for p in rows[("work", "Harbourlights")]["in_pool_now"]] == ["POOL1"], \
        "'The Lantern Makers' is not 'Harbourlights'"
    assert rows[("work", "East of Eden")]["in_pool_now"] == []
    cand = rows[("event", "Dana Reyes monologue")]["where"]["candidates"]
    assert [(c["video_id"], c["in_pool"]) for c in cand] == [("CAND1", True)], \
        "the request's candidate, filed under the work searched, and already fetched"
    assert rows[("event", "Dana Reyes monologue")]["of_topics"] == ["WNL"]


def test_where_is_only_what_the_factory_knows():
    r = _root()
    _full_batch(r)
    rows = _rows(_build(r))
    oc = rows[("work", "Harbourlights")]["where"]["official_channels"]
    assert oc == [{"title": "Example Max", "id": "UC_Example_Network", "for": "Example Max"}], oc
    assert rows[("person", "Aaron Pryce")]["where"]["official_channels"] == oc, \
        "a person found in a work's topic: the work's official channels"
    w = rows[("work", "East of Eden")]["where"]
    assert w == {"official_channels": [], "candidates": []}, \
        "no network, no request: nothing is suggested"
    md = fw.render_md(_build(r))
    assert "| — |" in md


def test_official_channels_are_the_channel_s_own_list():
    r = _root()
    # the place CF-0627 moved them away from: a decoy that must never be read
    _w(r / "agents" / "trend-hunter" / "config" / "footage_origin.json", {"official_channels": [
        {"pattern": "example network", "channels": [{"id": "UC_OLD", "title": "Old Path"}]}]})
    got, note = fw.load_official(r, CH)
    assert note is None and [e["pattern"] for e in got] == ["example network", "examplestream"], (got, note)

    got, note = fw.load_official(r, OTHER)
    assert got == [] and note and f"channels/{OTHER}/footage-origin.json" in note, note
    _batch(r, "2026-10-01T1000Z", channel=OTHER,
           topics=[_topic("t1", "Harbourlights", network="Example Max")],
           warnings=[{"topic_id": "t1", "script_id": "t1-script1",
                      "warning_code": "pool_too_thin"}])
    rep = fw.build(r, OTHER, archive=None, now=NOW)
    assert any("footage-origin" in n for n in rep["notes"]), rep["notes"]
    assert all(x["where"]["official_channels"] == [] for x in rep["rows"])
    assert "footage-origin" in fw.render_md(rep), "the note reaches the list people read"

    _w(r / "channels" / f"{CH}.json", {"channel": CH, "former_channel_ids": ["oldreel"]})
    got, note = fw.load_official(r, "oldreel")
    assert note is None and got and got[0]["pattern"] == "example network", (got, note)

    _w(r / "channels" / OTHER / "footage-origin.json", {"note": "nothing yet"})
    got, note = fw.load_official(r, OTHER)
    assert got == [] and "official_channels" in note, note
    got, note = fw.load_official(r, "")
    assert got == [] and "no channel named" in note, "no channel named is a refusal, not a list"


def test_the_tracked_example_film_list_is_not_empty():
    # channels/example-film/footage-origin.json is a tracked file of the
    # channel, not live data: if a move empties it again, this goes red.
    got, note = fw.load_official(ROOT, "example-film")
    assert note is None and len(got) >= 5, (len(got), note)
    assert all(e.get("channels") for e in got), "every entry names its YouTube channels"


# ------------------------------------------------------------------- the CLI
def test_channel_and_since_filters_and_the_cli():
    r = _root()
    w = [{"topic_id": "t1", "script_id": "t1-script1", "warning_code": "pool_too_thin"}]
    _batch(r, "2026-09-01T1000Z", topics=[_topic("t1", "Early Show")], warnings=w)
    _batch(r, "2026-10-01T1000Z", topics=[_topic("t1", "Late Show")], warnings=w)
    _batch(r, "2026-10-02T1000Z", channel=OTHER, group="rebuilds",
           topics=[_topic("t1", "Other Channel Show")], warnings=w)
    names = {x["name"] for x in _build(r)["rows"]}
    assert names == {"Early Show", "Late Show"}, names
    names = {x["name"] for x in _build(r, since="2026-09-15")["rows"]}
    assert names == {"Late Show"}, names

    out = TMP / f"out{_n[0]}"
    buf = io.StringIO()
    args = ["collect", "--root", str(r), "--out", str(out), "--now", NOW, "--no-archive"]
    assert fw.main(args, out=buf) == 0, buf.getvalue()
    text = buf.getvalue()
    assert f"TOTAL channel={CH} batches=2 packed=0 needs=2 rows=2 work=2" in text, text
    assert f"TOTAL channel={OTHER} batches=1" in text, text
    md = (out / CH / "footage-wanted.md").read_bytes()
    js = json.loads((out / CH / "footage-wanted.json").read_text())
    assert js["channel"] == CH and js["built_at"] == NOW and len(js["rows"]) == 2
    assert b"## \xd0\xa0\xd0\xb0\xd0\xb1\xd0\xbe\xd1\x82\xd1\x8b" in md     # "## Работы"
    assert fw.main(args, out=io.StringIO()) == 0
    assert (out / CH / "footage-wanted.md").read_bytes() == md, "same data, same bytes"
    assert not (r / "analytics").exists(), "--out keeps analytics/ untouched"

    buf = io.StringIO()
    assert fw.main(["collect", "--root", str(r), "--channel", "nope", "--no-write"], out=buf) == 2
    assert "nope" in buf.getvalue()
    assert fw.main(["collect", "--root", str(r), "--since", "Sept", "--no-write"],
                   out=io.StringIO()) == 2


def test_the_archive_place_is_monthly_archive_s():
    ma = (ROOT / "scripts" / "monthly_archive.py").read_text(encoding="utf-8")
    apm = (ROOT / "scripts" / "archive_publish_month.py").read_text(encoding="utf-8")
    gp = (ROOT / "shared" / "runlog" / "gate_price.py").read_text(encoding="utf-8")
    vol = re.search(r'^DEFAULT_VOLUME = "([^"]+)"', apm, re.M).group(1)
    sub = re.search(r'^BATCH_ARCHIVE_DIR = "([^"]+)"', ma, re.M).group(1)
    assert fw.DEFAULT_ARCHIVE == f"{vol}/{sub}", (fw.DEFAULT_ARCHIVE, vol, sub)
    assert re.search(r'^REBUILDS = "rebuilds"', ma, re.M)
    nc = re.search(r"^NOT_CHANNELS = (\(.*\))", gp, re.M).group(1)
    assert tuple(eval(nc)) == fw.NOT_A_CHANNEL, nc                      # noqa: S307


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
