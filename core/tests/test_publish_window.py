#!/usr/bin/env python3
"""CF-0042: the no-repeat window of (pattern, rhythm) pairs over the published
feed (`agents/publisher/publish_window.py`) and the queue's reorder on a
conflict (`publish_queue.plan_slot` / `apply_moves`).

Every root is a fixture in a temp dir; the committed publish/ and pipeline/
are never read (the vocabulary in patterns/ is, as the rotation reads it).

What is pinned:

* K is the channel's (`patterns.rotation.no_repeat_window_k`); a channel with
  no block gets a warning, not a refusal; a second channel with another K
  judges the same feed by its own K;
* the pair of a video: 05 (delivered, else requested) -> 03 -> the ledger
  row; a rebuild through `rebuild_of`; nothing found is "no data", a warning;
* a pair inside K of the published tail is a conflict; outside it is not;
* a conflict swaps with a later planned video not in Studio; a video in
  Studio is never moved; else a substitute from _queue/ takes the slot and the
  candidate the next one (or stays in _queue/); nothing to swap with places
  anyway with a loud warning - the slot never moves;
* the ledger's publication columns are filled from the journal, once.
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
for _p in (AGENT, ROOT / "shared" / "runlog", ROOT / "shared", ROOT / "rotation"):
    sys.path.insert(0, str(_p))

import publish_queue as pq          # noqa: E402
import publish_window as pw         # noqa: E402
from ledger import Ledger, ledger_path   # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("publish-window-test-")
_n = [0]
CH = "testreel"
CH2 = "testsecond"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
NOW = "2026-10-06T12:00:00+03:00"          # today's 01:00 is published; next slot 10-07
A, B, C, D, E = (("explainer", "even"), ("list", "hold"), ("contrast", "alternate"),
                 ("moment-breakdown", "hold"), ("list", "staccato"))


class World:
    def __init__(self, k=4, channel=CH, rotation=True):
        _n[0] += 1
        self.r = TMP / f"w{_n[0]}"
        self.ch = channel
        (self.r / "publish").mkdir(parents=True)
        (self.r / "channels").mkdir()
        self.channel(channel, k, rotation)
        self.journal, self.acc = [], []
        self.flush()

    def channel(self, name, k, rotation=True):
        pat = {"allowed_pattern_ids": ["explainer", "moment-breakdown", "list", "contrast"]}
        if rotation:
            pat["rotation"] = {"no_repeat_window_k": k, "distribution_window": 30}
        (self.r / "channels" / f"{name}.json").write_text(json.dumps(
            {"channel_id": name, "patterns": pat, "publisher": {"slot": SLOT}}), encoding="utf-8")

    def flush(self):
        pub = self.r / "publish"
        (pub / "uploads.json").write_text(json.dumps({"uploads": self.journal}), encoding="utf-8")
        (pub / "acceptance-log.json").write_text(json.dumps({"acceptances": self.acc}),
                                                 encoding="utf-8")
        (pub / "publication-holds.json").write_text(json.dumps({"holds": []}), encoding="utf-8")

    def batch(self, slug, pair, batch=None, delivered=True, rebuild_of=None, channel=None):
        """pipeline/<ch>/<batch>/05-video-editor.json naming the video."""
        batch = batch or f"B-{slug}"
        ch = channel or self.ch
        group = "rebuilds" if rebuild_of else ch
        d = self.r / "pipeline" / group / batch
        d.mkdir(parents=True, exist_ok=True)
        v = {"script_id": f"s-{slug}", "output_path": str(d / "videos" / f"{slug}.mp4"),
             "pattern_requested": pair[0] if pair else None,
             "rhythm_requested": pair[1] if pair else None,
             "pattern_delivered": pair[0] if (pair and delivered) else None,
             "rhythm_delivered": pair[1] if (pair and delivered) else None}
        (d / "05-video-editor.json").write_text(json.dumps(
            {"batch_id": batch, "channel": ch, "videos": [v],
             "rebuild_of": {"channel": ch, "batch_id": rebuild_of} if rebuild_of else None}),
            encoding="utf-8")
        return batch

    def accept(self, slug, batch):
        self.acc.append({"entry_id": f"{self.ch}/{batch}/{slug}", "channel": self.ch,
                         "batch_id": batch, "slug": slug, "topic_id": f"t-{slug}",
                         "verdict": "accepted", "answered_at": "2026-10-01T10:00:00Z"})
        self.flush()

    def published(self, day, slug, pair, vid=None):
        """A video in Studio on `day` (journal row), its batch on disk."""
        batch = self.batch(slug, pair) if pair else f"B-{slug}"
        self.accept(slug, batch)
        self.journal.append({"channel": self.ch, "entry_id": f"{self.ch}/{batch}/{slug}",
                             "batch_id": batch, "slug": slug,
                             "video_id": vid or (slug.upper() + "X" * 11)[:11],
                             "publish_day": day, "publish_at": f"{day}T01:00:00+03:00"})
        self.flush()
        return batch

    def folder(self, bucket, slug, pair, line=None):
        """A pair mp4 + note in publish/<ch>/<bucket>/ (a day or _queue)."""
        batch = self.batch(slug, pair) if pair else f"B-{slug}"
        self.accept(slug, batch)
        d = self.r / "publish" / self.ch / bucket
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{slug}.mp4").write_bytes(b"\0")
        body = f"# {slug}\n\nБатч `pipeline/{self.ch}/{batch}/`\n\n## Публикация\n{line or '-'}\n"
        (d / f"{slug}.md").write_text(body, encoding="utf-8")
        return batch


def _day(at):
    return pq.msk_day(at)


def _tail(w):
    """Published 10-04 A, 10-05 B, 10-06 C."""
    w.published("2026-10-04", "a", A)
    w.published("2026-10-05", "b", B)
    w.published("2026-10-06", "c", C)


# ------------------------------------------------------------------ K and the pair
def test_k_is_the_channels_and_a_channel_without_it_gets_a_warning():
    w = World(k=4)
    assert pw.window_config(CH, w.r) == {"k": 4, "configured": 4, "pairs": 8}
    w.channel(CH2, 3)
    assert pw.window_config(CH2, w.r)["k"] == 3
    w.channel("bare", 4, rotation=False)
    assert pw.window_config("bare", w.r) is None
    said = pw.candidate_check("bare", "x", pq.now_utc(NOW), w.r, NOW, {"batch_id": "B-x"})
    assert said["verdict"] == "warn" and "no_repeat_window_k" in said["reason"]


def test_the_pair_comes_from_05_then_03_then_the_ledger_and_nothing_is_no_data():
    w = World()
    w.batch("d", A)
    assert pw.pair_of(CH, "B-d", "d", w.r)["pair"] == A
    w.batch("r", B, delivered=False)                       # a shortfall: the requested pair
    assert pw.pair_of(CH, "B-r", "r", w.r)["pair"] == B
    # 05 names no pattern: 03 of the same batch says what the script was written in
    w.batch("n", None)
    (w.r / "pipeline" / CH / "B-n" / "03-content-researcher.json").write_text(json.dumps(
        {"scripts": [{"script_id": "s-n", "pattern": {"pattern_id": "contrast",
                                                      "rhythm_id": "alternate"}}]}))
    got = pw.pair_of(CH, "B-n", "n", w.r)
    assert got["pair"] == C and "03" in got["source"]
    # a rebuild: the pair from its own 05, the ledger row of its source batch
    led = Ledger(ledger_path(CH, w.r / "rotation" / "ledger"))
    led.append(channel=CH, batch_id="SRC", script_id="s-rb", pattern_id="list",
               rhythm_id="staccato", assigned_by="rotation")
    w.batch("rb", E, batch="RB1", rebuild_of="SRC")
    got = pw.pair_of(CH, "RB1", "rb", w.r)
    assert got["pair"] == E and got["ledger_batch"] == "SRC" and got["seq"] == "1"
    # the batch archived away: the ledger row whose video_path is the video
    led.append(channel=CH, batch_id="OLD", script_id="s-old", pattern_id="moment-breakdown",
               rhythm_id="hold", assigned_by="rotation")
    led.enrich(2, produced_at="2026-09-01T00:00:00Z", video_path="/x/OLD/videos/old.mp4")
    got = pw.pair_of(CH, "OLD", "old", w.r)
    assert got["pair"] == D and got["source"].startswith("ledger seq 2")
    # nothing anywhere: no data, said
    got = pw.pair_of(CH, "GONE", "ghost", w.r)
    assert got["pair"] is None and "GONE/ghost" in got["source"]


# ------------------------------------------------------------------ the window
def test_a_pair_inside_k_of_the_published_tail_is_a_conflict_and_outside_is_not():
    w = World(k=4)
    _tail(w)
    w.batch("x", A)
    w.batch("y", D)
    slot = pq.next_free(CH, w.r, NOW)
    assert _day(slot) == "2026-10-07"
    said = pw.candidate_check(CH, "x", slot, w.r, NOW, {"batch_id": "B-x"})
    assert said["verdict"] == "reorder" and "explainer/even" in said["reason"] \
        and "a (2026-10-04, опубликован)" in said["reason"], said
    assert pw.candidate_check(CH, "y", slot, w.r, NOW, {"batch_id": "B-y"}) is None
    # one day later A is four back - outside K=4
    assert pw.candidate_check(CH, "x", pq.now_utc("2026-10-08T01:00:00+03:00"), w.r, NOW,
                              {"batch_id": "B-x", "moved": {"y": {
                                  "slot": slot, "batch_id": "B-y"}}}) is None


def test_a_second_channel_judges_by_its_own_k():
    w = World(k=4)
    w.channel(CH2, 3)
    w.ch = CH2
    _tail(w)
    w.batch("x", A)
    slot = pq.next_free(CH2, w.r, NOW)
    # A three back: inside 4, outside 3
    assert pw.candidate_check(CH2, "x", slot, w.r, NOW, {"batch_id": "B-x"}) is None
    w.channel(CH2, 4)
    assert pw.candidate_check(CH2, "x", slot, w.r, NOW, {"batch_id": "B-x"})["verdict"] == "reorder"


def test_no_pair_data_lets_the_slot_through_with_a_warning():
    w = World()
    _tail(w)
    w.accept("x", "B-x")                                   # accepted, no batch files anywhere
    plan = pq.plan_slot(CH, "B-x", "x", w.r, NOW)
    assert plan["day"] == "2026-10-07" and plan["moves"] == []
    assert any("нет данных о паре" in m and "x" in m for m in plan["warnings"]), plan["warnings"]


# ------------------------------------------------------------------ the reorder
def test_a_conflict_swaps_with_a_later_video_not_yet_in_studio():
    w = World()
    _tail(w)
    w.folder("2026-10-08", "y", D, "**2026-10-08 01:00 МСК** — слот")
    w.batch("x", A)
    w.accept("x", "B-x")
    plan = pq.plan_slot(CH, "B-x", "x", w.r, NOW)
    assert plan["day"] == "2026-10-08", plan                # x takes y's slot
    assert [(m["slug"], m["from"], m["day"]) for m in plan["moves"]] == [
        ("y", "2026-10-08", "2026-10-07")]
    assert "поменялись местами" in plan["note"]
    done = pq.apply_moves(CH, plan["moves"], w.r, git=False)
    assert done == ["y: 2026-10-08 -> 2026-10-07"]
    moved = w.r / "publish" / CH / "2026-10-07" / "y.md"
    assert moved.is_file() and not (w.r / "publish" / CH / "2026-10-08" / "y.mp4").exists()
    assert "**2026-10-07 01:00 МСК**" in moved.read_text(encoding="utf-8")
    # the feed after the swap holds no repeat inside K (x would go to 10-08)
    items = pw.arrange(CH, "x", plan["slot"], w.r, NOW, {"batch_id": "B-x"})
    assert not pw.repeats(pw._with_pairs(CH, items, w.r, {}), 4)


def test_a_video_already_in_studio_is_never_moved_and_nothing_to_swap_still_places_loudly():
    w = World()
    _tail(w)
    w.published("2026-10-08", "y", D)                      # scheduled in Studio
    w.batch("x", A)
    w.accept("x", "B-x")
    plan = pq.plan_slot(CH, "B-x", "x", w.r, NOW)
    assert plan["day"] == "2026-10-07" and plan["moves"] == []
    warn = [m for m in plan["warnings"] if "ПОВТОРОМ" in m]
    assert warn and "переставить не с чем" in warn[0] and "слот не сдвигается" in warn[0]


def test_a_substitute_from_the_queue_takes_the_slot_and_the_candidate_the_next():
    w = World()
    _tail(w)
    w.folder("_queue", "z", D)
    w.batch("x", A)
    w.accept("x", "B-x")
    plan = pq.plan_slot(CH, "B-x", "x", w.r, NOW)
    assert [(m["slug"], m["from"], m["day"]) for m in plan["moves"]] == [
        ("z", "_queue", "2026-10-07")]
    assert plan["day"] == "2026-10-08", plan
    pq.apply_moves(CH, plan["moves"], w.r, git=False)
    assert (w.r / "publish" / CH / "2026-10-07" / "z.mp4").is_file()
    # a candidate that repeats in the next slot too stays in _queue/ - the slot is filled anyway
    w2 = World()
    _tail(w2)
    w2.folder("_queue", "z", D)
    w2.batch("x", B)
    w2.accept("x", "B-x")
    plan = pq.plan_slot(CH, "B-x", "x", w2.r, NOW)
    assert plan["slot"] is None and plan["day"] is None
    assert plan["moves"][0]["slug"] == "z" and plan["moves"][0]["day"] == "2026-10-07"
    assert any("остаётся в publish/" in m for m in plan["warnings"])


def test_a_queue_video_that_also_repeats_is_not_a_substitute():
    w = World()
    _tail(w)
    w.folder("_queue", "z", C)                             # C published yesterday
    w.batch("x", A)
    w.accept("x", "B-x")
    plan = pq.plan_slot(CH, "B-x", "x", w.r, NOW)
    assert plan["moves"] == [] and plan["day"] == "2026-10-07"
    assert any("ПОВТОРОМ" in m for m in plan["warnings"])


# ------------------------------------------------------------------ the ledger
def test_record_published_fills_the_ledger_once_from_the_journal():
    w = World()
    led = Ledger(ledger_path(CH, w.r / "rotation" / "ledger"))
    for slug in ("a", "b", "c", "f"):
        led.append(channel=CH, batch_id=f"B-{slug}", script_id=f"s-{slug}",
                   pattern_id="explainer", rhythm_id="even", assigned_by="rotation")
    _tail(w)
    w.published("2026-10-09", "f", E)                      # in Studio, not out yet
    w.published("2026-10-03", "nobody", A)                 # no ledger row
    res = pw.record_published(CH, w.r, NOW)
    assert len(res["filled"]) == 3 and res["no_row"] == ["B-nobody/nobody"], res
    rows = {r["script_id"]: r for r in led.rows()}
    assert rows["s-a"]["feed_position"] == "2" and rows["s-c"]["feed_position"] == "4"
    assert rows["s-a"]["video_id"] == "AXXXXXXXXXX"
    assert rows["s-c"]["published_at"].startswith("2026-10-05T22:00:00")
    assert rows["s-f"]["published_at"] == ""
    again = pw.record_published(CH, w.r, NOW)
    assert again["filled"] == [] and len(again["already"]) == 3
    # a cell already holding another value is a conflict, reported, not raised
    w.journal[0]["video_id"] = "ZZZZZZZZZZZ"
    w.flush()
    res = pw.record_published(CH, w.r, NOW)
    assert res["conflicts"] and res["conflicts"][0]["seq"] == "1"


def test_an_early_video_written_into_the_journal_later_shifts_ranks_not_conflicts():
    """CF-0866: outrider-doune-castle was written into the Reel journal on 07.10
    before eight already-ranked videos; every later `feed_position` moved by one
    and `record` warned about them forever. A shifted rank is re-derived."""
    import ledger as ledger_mod
    w = World()
    led = Ledger(ledger_path(CH, w.r / "rotation" / "ledger"))
    for slug in ("a", "b", "c"):
        led.append(channel=CH, batch_id=f"B-{slug}", script_id=f"s-{slug}",
                   pattern_id="explainer", rhythm_id="even", assigned_by="rotation")
    _tail(w)
    assert len(pw.record_published(CH, w.r, NOW)["filled"]) == 3
    w.published("2026-10-02", "early", D)                  # the backfill, no ledger row
    dry = pw.record_published(CH, w.r, NOW, dry_run=True)
    assert dry["conflicts"] == [] and len(dry["shifted"]) == 3, dry
    assert {"video": "B-a/a", "seq": "1", "old": "1", "new": "2"} in dry["shifted"]
    assert {r["script_id"]: r["feed_position"] for r in led.rows()}["s-a"] == "1"
    out = io.StringIO()
    assert pw.main(["record", "--channel", CH, "--root", str(w.r), "--now", NOW, "--dry-run"],
                   out) == 0
    assert "shifted 3, conflicts 0" in out.getvalue() and "CONFLICT" not in out.getvalue()
    res = pw.record_published(CH, w.r, NOW)
    assert res["conflicts"] == [] and len(res["shifted"]) == 3
    assert [r["feed_position"] for r in led.rows()] == ["2", "3", "4"]
    log = ledger_mod.resyncs_path(led.path).read_text().splitlines()
    assert len(log) == 3 and json.loads(log[0])["task"] == "CF-0866"
    again = pw.record_published(CH, w.r, NOW)
    assert again["shifted"] == [] and len(again["already"]) == 3
    # another video id is still a conflict, even with a shifted rank beside it
    w.published("2026-10-01", "earlier", E)
    w.journal[0]["video_id"] = "ZZZZZZZZZZZ"
    w.flush()
    res = pw.record_published(CH, w.r, NOW)
    assert [c["seq"] for c in res["conflicts"]] == ["1"] and \
        set(res["conflicts"][0]["cells"]) == {"feed_position", "video_id"}, res
    assert [x["seq"] for x in res["shifted"]] == ["2", "3"]
    assert {r["script_id"]: r["feed_position"] for r in led.rows()}["s-a"] == "2"


def test_the_check_command_prints_the_feed_and_exits_1_on_a_repeat():
    w = World()
    _tail(w)
    w.published("2026-10-07", "x", A)
    out = io.StringIO()
    assert pw.main(["check", "--channel", CH, "--root", str(w.r), "--now", NOW], out) == 1
    text = out.getvalue()
    assert "K=4" in text and "REPEAT explainer/even: a (2026-10-04) and x (2026-10-07)" in text
    w2 = World()
    _tail(w2)
    out = io.StringIO()
    assert pw.main(["check", "--channel", CH, "--root", str(w2.r), "--now", NOW], out) == 0


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
