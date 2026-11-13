#!/usr/bin/env python3
"""CF-0302: a candidate too long to index is refused before it is downloaded,
and the refusal does not cost the topic an attempt.

The incident: a candidate filed as `nature: trailer` because the word was in
its title was an 8019 s news talk show with a handful of views. The indexer
downloaded it and was still splitting its shots 41 minutes later, when the
stage operator killed it by hand. The attempt was spent, the four-attempt cap
of CF-0129 was reached, and a topic holding a good first source and two
untried candidates left the batch with `no_second_source`.

What is pinned here, all of it offline - the measurement is a seam and no test
in this file makes a request:

  - the length is read before the download, from the batch artifact, then the
    cache, then one metadata request, and the first answer wins;
  - the talk show is refused before the fetch, with `source_too_long`,
    `refused_at: metadata` and the measured length in the record;
  - the topic's attempt is NOT spent;
  - the ordinary sources of a batch pass;
  - a length nobody could measure is not a refusal;
  - the ceiling is on with no configuration at all, and the channel config
    can name it per nature;
  - the report's `duration_ceiling` block and the skill's paragraph.

No pytest dependency - plain asserts, run directly.
"""
import io
import json
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fetch_footage as ff          # noqa: E402
import ingest_batch as ib           # noqa: E402

# CF-0505: the pool every default reads is a temp one - `fetch_footage.INDEX`
# holds only the entry for FIRST_SOURCE (304 s), and the depth record
# (`pool_depth.CACHE`) reads an empty directory.
import pool_depth                   # noqa: E402
from _tmproot import tmp_root       # noqa: E402
POOL = tmp_root("cf0505-ceiling-")
ff.CACHE = ib.CACHE = pool_depth.CACHE = POOL
ff.INDEX = POOL / "index.json"
(POOL / "firstsrc001.mp4").write_bytes(b"\0")
ff.INDEX.write_text(json.dumps({"entries": [{
    "id": "firstsrc001", "url": "https://www.youtube.com/watch?v=firstsrc001",
    "path": str(POOL / "firstsrc001.mp4"), "duration": 304}]}))

SKIPPED = []

# The incident, reduced to its numbers.
TALK_SHOW = "talkshow0001"
TALK_SHOW_SECONDS = 8019
TOPIC = "topic-004"
FIRST_SOURCE = "firstsrc001"        # a normal source, 304 s

# ---------------------------------------------------------------------------
# Fakes

class Fetcher:
    """A fake `fetch_source`. `gone` raises a plain failure, everything else
    comes down."""

    def __init__(self, gone=()):
        self.gone = set(gone)
        self.calls = []

    def __call__(self, vid, note):
        self.calls.append(vid)
        if vid in self.gone:
            raise RuntimeError(f"ERROR: [youtube] {vid}: Video unavailable")
        return ib.FetchResult(f"/tmp/{vid}.mp4", False)


def measurer(table, unknown_error="nothing answered"):
    """A `measure` seam over `{video_id: seconds}`; an id the table does not
    name has no measurable length, which is the case the ceiling may not act
    on. Counts what it was asked, so a test can pin that the cache and the
    artifact are read before YouTube is."""
    asked = []

    def measure(vid, record=None):
        asked.append(vid)
        rec = record if isinstance(record, dict) else {}
        raw = rec.get(ib.CANDIDATE_DURATION_KEY)
        if isinstance(raw, (int, float)):
            return ib.Measured(float(raw), "candidate", None)
        if vid in table:
            return ib.Measured(float(table[vid]), "cache", None)
        return ib.Measured(None, "metadata", unknown_error)

    measure.asked = asked
    return measure


def run(topics, fetch, measure, **kw):
    """`ingest()` with the waiting and the network injected away."""
    out, err = io.StringIO(), io.StringIO()
    kw.setdefault("measurements", [])
    index = kw.pop("index", None)
    with redirect_stdout(out), redirect_stderr(err):
        result = ib.ingest(topics, {}, "batch-x", kw.pop("max_per_topic", 4),
                           index is None, fetch=fetch,
                           index=index or (lambda p: None),
                           fingerprint=lambda p: None, sleep=lambda s: None,
                           pause=0, is_cached=lambda vid: False,
                           measure=measure, **kw)
    return result, out.getvalue(), kw["measurements"]


def refusal(skipped, tid):
    return next(s for s in skipped if s["topic_id"] == tid)


# ---------------------------------------------------------------------------
# The metadata request itself

def test_the_length_is_asked_for_without_downloading_anything():
    seen = {}

    def runner(cmd, **kw):
        seen["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": "8019.0\n", "stderr": ""})()

    meta = ff.probe_duration("https://www.youtube.com/watch?v=" + TALK_SHOW,
                             runner=runner)
    assert meta == ff.Metadata(8019.0, False, None)
    cmd = seen["cmd"]
    assert "--skip-download" in cmd and "%(duration)s" in cmd
    # Nothing about media: no format selection, no output template, no merge.
    for never in ("-f", "-o", "--merge-output-format", "-P"):
        assert never not in cmd, never


def test_an_unanswered_probe_is_a_record_and_never_an_exception():
    def failing(rc=1, stdout="", stderr=""):
        return lambda cmd, **kw: type(
            "R", (), {"returncode": rc, "stdout": stdout, "stderr": stderr})()

    # A live stream, and a video with no duration in its metadata.
    assert ff.probe_duration("u", runner=failing(0, "NA\n")).seconds is None
    # yt-dlp lost the video.
    m = ff.probe_duration("u", runner=failing(1, "", "ERROR: Video unavailable"))
    assert m.seconds is None and "unavailable" in m.error
    # yt-dlp not on this machine at all, or any other explosion.
    def boom(cmd, **kw):
        raise OSError("no such file")
    assert ff.probe_duration("u", runner=boom).seconds is None


def test_the_artifact_is_read_before_the_cache_and_the_cache_before_youtube():
    probes = []

    def probe(url):
        probes.append(url)
        return ff.Metadata(42.0, False, None)

    # 1. what Trend Hunter measured (the CF-0302 half in the hunter)
    m = ib.measure_candidate(TALK_SHOW, record={ib.CANDIDATE_DURATION_KEY: 8019},
                             probe=probe)
    assert (m.seconds, m.source) == (8019.0, "candidate") and not probes
    # 2. the factory's own cache, for an id it already holds
    m = ib.measure_candidate(FIRST_SOURCE, record={}, probe=probe)
    assert (m.source, m.seconds) == ("cache", 304.0) and not probes, m
    # 3. only then YouTube
    probes.clear()
    m = ib.measure_candidate("not-in-anything-xyz", record={}, probe=probe)
    assert (m.seconds, m.source) == (42.0, "metadata") and len(probes) == 1


# ---------------------------------------------------------------------------
# The refusal

def test_the_talk_show_is_refused_before_it_is_fetched():
    f = Fetcher()
    topics = [{"topic_id": TOPIC, "evidence": {
        "youtube_video_ids": [TALK_SHOW],
        "footage_candidates": [{"video_id": TALK_SHOW, "nature": "trailer",
                                "title": "Weekly news talk show - episode 212",
                                ib.CANDIDATE_DURATION_KEY: TALK_SHOW_SECONDS}]}}]
    (fetched, _, skipped, failed, by_topic), log, measured = run(
        topics, f, measurer({}))

    assert f.calls == []                       # nothing was downloaded
    assert fetched == [] and by_topic == {TOPIC: []}
    rec = failed[0]
    assert rec["video_id"] == TALK_SHOW
    assert rec["reason_code"] == ib.TOO_LONG_CODE == "source_too_long"
    assert rec["refused_at"] == ib.RUNG_METADATA == "metadata"
    assert rec["duration_seconds"] == float(TALK_SHOW_SECONDS)
    assert rec["ceiling_seconds"] == 900 and rec["nature"] == "trailer"
    assert rec["measured_from"] == "candidate"
    assert rec["attempt_spent"] is False and rec["attempts"] == []
    # the sentence reads on its own - the funnel copies it into `detail`
    assert "8019 s is over the 900 s ceiling" in rec["error"]
    assert "attempt was not spent" in rec["error"]
    assert "CEILING talkshow0001 refused before the download" in log
    # the topic's own refusal names it apart from a failed fetch
    r = refusal(skipped, TOPIC)
    assert r["reason_code"] == ib.TOO_LONG_CODE
    assert r["failed"] == [] and r["too_long"][0]["video_id"] == TALK_SHOW
    assert "refused before the download as too long" in r["reason"]
    assert TALK_SHOW not in r["tried"] and TALK_SHOW not in r["unused"]


def test_the_ceiling_is_on_with_no_configuration_at_all():
    """A caller that says nothing about the ceiling still gets one - it is a
    safety net, never something a caller has to remember to switch on."""
    f = Fetcher()
    topics = [{"topic_id": "t", "evidence": {"youtube_video_ids": [TALK_SHOW]}}]
    (_, _, _, failed, _), _, _ = run(topics, f, measurer({TALK_SHOW: 8019}))
    assert f.calls == [] and failed[0]["reason_code"] == ib.TOO_LONG_CODE
    # ... and with no `nature` to read it is the default, not the trailer one
    assert failed[0]["ceiling_seconds"] == 3600


def test_an_ordinary_source_of_the_batch_passes():
    """The lengths of the sources 2026-09-21T0358Z really used, against the
    natures Trend Hunter gave them."""
    real = {"9a7i4LHHZNs": 144, "wIM1PDRvKSE": 147, "lYXtL5TreOE": 144,
            FIRST_SOURCE: 304, "JzA-WopbYnc": 211, "ZLXL1L0TfsI": 629,
            "mtZjyyslZ_s": 24, "bYKJxZYd66o": 99}
    nature = {"9a7i4LHHZNs": "trailer", "wIM1PDRvKSE": "trailer",
              "lYXtL5TreOE": "trailer", FIRST_SOURCE: "episode",
              "JzA-WopbYnc": "episode", "ZLXL1L0TfsI": "interview",
              "mtZjyyslZ_s": "trailer", "bYKJxZYd66o": "episode"}
    f = Fetcher()
    topics = [{"topic_id": "t", "evidence": {
        "youtube_video_ids": list(real),
        "footage_candidates": [{"video_id": v, "nature": nature[v]}
                               for v in real]}}]
    (fetched, _, _, failed, _), _, _ = run(
        topics, f, measurer(real), max_per_topic=len(real), wanted=len(real))
    assert [x["video_id"] for x in fetched] == list(real)
    assert failed == []


def test_a_length_nobody_could_measure_is_not_a_refusal():
    f = Fetcher()
    topics = [{"topic_id": "t", "evidence": {"youtube_video_ids": ["mystery"]}}]
    (fetched, _, _, failed, _), log, measured = run(
        topics, f, measurer({}, unknown_error="yt-dlp printed 'NA'"))
    assert f.calls == ["mystery"]                      # fetched as usual
    assert [x["video_id"] for x in fetched] == ["mystery"] and failed == []
    assert "CEILING mystery: length unknown" in log
    # and the fact is on paper, not only in the log
    assert measured == [{"video_id": "mystery", "topic_id": "t", "nature": None,
                         "duration_seconds": None, "measured_from": "metadata",
                         "ceiling_seconds": 3600, "error": "yt-dlp printed 'NA'"}]
    block = ib.ceiling_report(None, failed, measured)
    assert block["refused"] == [] and block["unmeasured"] == measured


def test_a_measurement_that_explodes_does_not_take_the_batch_with_it():
    """The ceiling is a safety net and may never become a new way to lose a
    topic: whatever goes wrong reading one number, the candidate keeps its
    ordinary path and the failure is on paper."""
    def measure(vid, record=None):
        raise RuntimeError("yt-dlp is not on this machine")

    f = Fetcher()
    topics = [{"topic_id": "t", "evidence": {"youtube_video_ids": ["a"]}}]
    (fetched, _, _, failed, _), log, measured = run(topics, f, measure)
    assert [x["video_id"] for x in fetched] == ["a"] and failed == []
    assert measured[0]["error"] == "RuntimeError: yt-dlp is not on this machine"


# ---------------------------------------------------------------------------
# Where the number lives

from _tmproot import tmp_root  # noqa: E402
_TMP = tmp_root("cf0302-")   # CF-0489: removed at exit


def test_the_channel_config_names_the_ceiling_and_a_broken_one_is_ignored():
    tmp = Path(tempfile.mkdtemp(dir=_TMP))
    (tmp / "channels").mkdir()
    (tmp / "shared").mkdir()

    def ceiling(node):
        cfg = tmp / "channels" / "c.json"
        doc = {"channel_id": "c"}
        if node is not None:
            doc["sources"] = {"youtube": {"max_source_duration_seconds": node}}
        cfg.write_text(json.dumps(doc))
        return ib.duration_ceiling("c", config_path=cfg, root=tmp)

        assert ib.CEILING_KEY == "sources.youtube.max_source_duration_seconds"

    # nothing said: this stage's own measured numbers, and the report says so
    c = ceiling(None)
    assert c.configured is False
    assert c.limits == {"default": 3600, "trailer": 900}
    assert (c.seconds("trailer"), c.seconds("interview"), c.seconds(None)) \
        == (900, 3600, 3600)

    # one number for every nature
    c = ceiling(1200)
    assert c.configured and c.seconds("trailer") == c.seconds("episode") == 1200

    # per nature, with the natures it does not name keeping the defaults
    c = ceiling({"trailer": 600, "interview": 5400})
    assert c.configured
    assert (c.seconds("trailer"), c.seconds("interview"), c.seconds("episode")) \
        == (600, 5400, 3600)

    # a `_note` beside the numbers, the way the rest of this factory's config
    # is written, is not a ceiling
    c = ceiling({"trailer": 600, "trailer_note": "measured 2026-09-21"})
    assert c.seconds("trailer") == 600

    # garbage never becomes the reason a batch has no footage
    for bad in ("soon", -5, 0, True, [], {}, {"trailer": "long"}):
        c = ceiling(bad)
        assert c.configured is False and c.limits == ib.DEFAULT_MAX_SOURCE_SECONDS
    # ... and neither does a config that is not there or is not JSON
    c = ib.duration_ceiling("c", config_path=tmp / "channels" / "nope.json", root=tmp)
    assert c.configured is False and c.seconds("trailer") == 900


def test_the_numbers_are_the_measured_ones():
    """The defaults are a measurement of this factory's own pool, not a
    preference: 3600 is above the longest source that ever reached a finished
    video (3426 s) and below both incidents (4307 s, 8019 s); 900 is above the
    longest `trailer` that was ever used (501 s) and far below them."""
    assert ib.DEFAULT_MAX_SOURCE_SECONDS == {"default": 3600, "trailer": 900}
    src = (SCRIPTS / "ingest_batch.py").read_text()
    for evidence in ("3426", "501", "8019", "4307"):
        assert evidence in src, evidence


# ---------------------------------------------------------------------------
# What the operator sees

def test_the_report_block_is_written_even_when_nothing_was_too_long():
    c = ib.Ceiling(limits={"default": 3600}, configured=True,
                   config_path=Path("/x/channels/c.json"), key=ib.CEILING_KEY)
    block = ib.ceiling_report(c, [], [])
    assert block["limits"] == {"default": 3600} and block["configured"] is True
    assert block["refused"] == [] and block["unmeasured"] == []
    assert block["key"] == ib.CEILING_KEY
    assert ib.CANDIDATE_DURATION_KEY in block["note"]

    failed = [{"video_id": TALK_SHOW, "topic_id": TOPIC,
               "reason_code": ib.TOO_LONG_CODE, "error": "too long",
               "nature": "trailer", "duration_seconds": 8019.0,
               "ceiling_seconds": 900, "measured_from": "candidate"},
              {"video_id": "x", "topic_id": TOPIC, "reason_code": "fetch_failed"}]
    block = ib.ceiling_report(c, failed, [])
    assert [r["video_id"] for r in block["refused"]] == [TALK_SHOW]
    assert block["refused"][0]["stage"] == ib.STAGE_NAME


def test_the_skill_carries_the_ceiling():
    skill = (HERE.parent / ".claude" / "skills" / "footage-indexer"
             / "SKILL.md").read_text()
    assert "CF-0302" in skill and "2026-09-21" in skill
    for phrase in ("max_source_duration_seconds", "source_too_long",
                   "duration_seconds", "3600", "900",
                   "the topic's attempt is not spent",
                   "duration_ceiling"):
        assert phrase in skill, phrase


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    for note in dict.fromkeys(SKIPPED):
        print(f"  note: {note}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
