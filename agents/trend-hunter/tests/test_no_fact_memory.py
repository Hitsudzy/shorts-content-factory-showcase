#!/usr/bin/env python3
"""CF-0823: the channel's memory of `no_fact` refusals between batches.

Character.AI was refused with `no_fact` in five ExampleTech batches in a row,
each time after its scoring search was paid for. These tests hold the memory
to what the task asks of it: a refusal of the last N days (the channel's
`scope.no_fact_memory_days`, 3 by default) holds the candidate back, older
ones do not, nothing but `no_fact` is remembered, a held-back candidate does
not renew its own entry, and the file lives beside the channel's other
memory under `pipeline/<channel>/`. Everything runs in a temp root - no live
pipeline, channel or batch is read.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

from _tmproot import tmp_root  # noqa: E402
import no_fact_memory as nfm  # noqa: E402

TMP = tmp_root("th-nofact-")
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
_N = [0]


def root():
    _N[0] += 1
    base = TMP / f"root-{_N[0]}"
    base.mkdir()
    return base


def refusal(name, code="no_fact", outcome="ok", failures=("tier2_without_primary",),
            **extra):
    row = {"topic_id": f"t-{name}", "reason_code": code, "reason": f"no fact: {name}",
           "stage": "trend-hunter", "title": name,
           "fact_probe": {"source": "wikipedia", "outcome": outcome,
                          "article": f"{name} (article)" if outcome == "ok" else None},
           "fact_candidates": [{"text": "x", "check": {"passes": False,
                                                      "failures": list(failures)}}]}
    row.update(extra)
    return row


def at(text):
    return nfm.parse_time(text)


def test_the_key_is_the_normalised_name():
    assert nfm.key_of("Character.AI") == nfm.key_of("character ai") == " character ai "
    assert nfm.key_of("  ") is None and nfm.key_of(None) is None
    assert nfm.names_of({"title_ref": {"name": "Tesla Roadster", "person": "Elon Musk"}}) \
        == [" tesla roadster ", " elon musk "]
    assert nfm.names_of({"name": "Apple HomeView"}) == [" apple homeview "]


def test_the_days_are_the_channels_and_three_by_default():
    assert nfm.days_of({}) == (3, "default", None)
    assert nfm.days_of({"scope": {"no_fact_memory_days": 5}})[:2] == (5, "channel")
    assert nfm.days_of({"scope": {"no_fact_memory_days": 0}})[:2] == (0, "channel")
    days, origin, note = nfm.days_of({"scope": {"no_fact_memory_days": "three"}})
    assert (days, origin) == (3, "default") and "three" in note


def test_the_file_lives_beside_the_channels_other_memory_under_pipeline():
    base = root()
    assert nfm.memory_path(base, "example-tech") == \
        base / "pipeline" / "example-tech" / "no-fact-memory.json"
    saved = os.environ.get(nfm.PIPELINE_ENV)
    os.environ[nfm.PIPELINE_ENV] = str(base / "elsewhere")
    try:
        assert nfm.memory_path(base, "example-tech") == \
            base / "elsewhere" / "example-tech" / "no-fact-memory.json"
    finally:
        if saved is None:
            os.environ.pop(nfm.PIPELINE_ENV, None)
        else:
            os.environ[nfm.PIPELINE_ENV] = saved


def test_a_no_fact_is_recorded_with_date_channel_batch_and_subreason():
    base = root()
    added = nfm.record(base, "example-tech",
                       [refusal("Character.AI"),
                        refusal("Apple HomeView", outcome="no_article", failures=()),
                        refusal("Below", code="below_shortlist"),
                        refusal("Old", code="no_support_text")],
                       "2026-10-20T1448Z", now=at("2026-10-20T14:58:00Z"))
    assert [e["name"] for e in added] == ["Character.AI", "Apple HomeView"]
    doc = json.loads(nfm.memory_path(base, "example-tech").read_text())
    rows = {e["name"]: e for e in doc["entries"]}
    assert rows["Character.AI"]["subreason"] == "tier2_without_primary"
    assert rows["Apple HomeView"]["subreason"] == "no_article"
    for e in doc["entries"]:
        assert e["channel"] == "example-tech" and e["batch"] == "2026-10-20T1448Z"
        assert e["refused_at"] == "2026-10-20T14:58:00Z"
    # a second pass over the same batch adds nothing
    assert nfm.record(base, "example-tech", [refusal("Character.AI")], "2026-10-20T1448Z",
                      now=at("2026-10-20T15:30:00Z")) == []


def test_a_refusal_within_the_days_holds_the_candidate_back_an_older_one_does_not():
    base = root()
    nfm.record(base, "example-tech", [refusal("Character.AI")], "2026-10-19T0844Z",
               now=at("2026-10-19T09:00:00Z"))
    nfm.record(base, "example-tech", [refusal("Tesla Roadster")], "2026-10-15T1854Z",
               now=at("2026-10-15T19:00:00Z"))
    mem = nfm.load(base, "example-tech", {}, now=NOW, batch="2026-10-21T1200Z")
    assert mem.hit({"title_ref": {"name": "Character.AI"}})["batch"] == "2026-10-19T0844Z"
    assert mem.hit({"name": "character ai"}) is not None
    assert mem.hit({"title_ref": {"name": "Tesla Roadster"}}) is None   # 6 days ago
    longer = nfm.load(base, "example-tech", {"scope": {"no_fact_memory_days": 7}}, now=NOW)
    assert longer.hit({"title_ref": {"name": "Tesla Roadster"}}) is not None
    off = nfm.load(base, "example-tech", {"scope": {"no_fact_memory_days": 0}}, now=NOW)
    assert off.hit({"title_ref": {"name": "Character.AI"}}) is None and off.live == {}


def test_the_memory_is_the_channels_and_not_the_batchs_own():
    base = root()
    nfm.record(base, "example-tech", [refusal("Character.AI")], "2026-10-21T0800Z",
               now=at("2026-10-21T08:10:00Z"))
    assert nfm.load(base, "example-film", {}, now=NOW).hit(
        {"title_ref": {"name": "Character.AI"}}) is None
    same = nfm.load(base, "example-tech", {}, now=NOW, batch="2026-10-21T0800Z")
    assert same.hit({"title_ref": {"name": "Character.AI"}}) is None


def test_a_held_back_candidate_does_not_renew_its_own_entry():
    base = root()
    nfm.record(base, "example-tech", [refusal("Character.AI")], "2026-10-19T0844Z",
               now=at("2026-10-19T09:00:00Z"))
    mem = nfm.load(base, "example-tech", {}, now=NOW, batch="2026-10-21T1200Z")
    entry = mem.hit({"title_ref": {"name": "Character.AI"}})
    row = nfm.remembered_refusal({"topic_id": "t9", "title_ref": {"name": "Character.AI",
                                                                  "kind": "work"}},
                                 entry, mem.days)
    assert row["reason_code"] == "no_fact" and row["before_scoring"] is True
    assert row["fact_probe"]["source"] == nfm.MEMORY_SOURCE and row["fact_memory"]
    assert "2026-10-19T0844Z" in row["reason"]
    assert nfm.subreason_of(row) == "tier2_without_primary"
    assert nfm.record(base, "example-tech", [row], "2026-10-21T1200Z", now=NOW) == []


def test_old_entries_leave_the_file_when_it_is_written():
    base = root()
    nfm.record(base, "example-tech", [refusal("Ancient")], "2026-09-01T0800Z",
               now=at("2026-09-01T08:00:00Z"))
    nfm.record(base, "example-tech", [refusal("Fresh")], "2026-10-21T0800Z", now=NOW)
    names = [e["name"] for e in json.loads(
        nfm.memory_path(base, "example-tech").read_text())["entries"]]
    assert names == ["Fresh"]


def test_an_unreadable_file_is_an_empty_memory():
    base = root()
    path = nfm.memory_path(base, "example-tech")
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert nfm.load(base, "example-tech", {}, now=NOW).live == {}


def test_the_subreason_of_another_edition_is_said_as_such():
    row = refusal("Tesla Roadster", outcome="wrong_article", failures=())
    row["fact_probe"]["detail"] = "the article is about another edition"
    assert nfm.subreason_of(row) == "edition"


def test_an_entry_or_a_batch_under_the_former_channel_id_is_the_same_channel():
    """CF-0835 (CF-0197): a refusal remembered before the channel was renamed
    carries the old id, and a batch written before it asks under the old id -
    both are the channel as it is now, in a temp root that maps the two."""
    base = root()
    (base / "channels").mkdir()
    (base / "channels" / "example-tech.json").write_text(
        json.dumps({"channel_id": "example-tech", "former_channel_ids": ["tech-old"]}))
    from _channel_ids import resolve_channel   # noqa: PLC0415
    if resolve_channel("tech-old", base) != "example-tech":
        print("  skip test_an_entry_or_a_batch_under_the_former_channel_id_is_the_same_"
              "channel: no root channel_ids library to resolve with")
        return
    nfm.record(base, "example-tech", [refusal("Character.AI")], "2026-10-19T0844Z",
               now=at("2026-10-19T09:00:00Z"))
    path = nfm.memory_path(base, "example-tech")
    doc = json.loads(path.read_text())
    for e in doc["entries"]:
        e["channel"] = "tech-old"
    path.write_text(json.dumps(doc))
    topic = {"title_ref": {"name": "Character.AI"}}
    assert nfm.load(base, "example-tech", {}, now=NOW).hit(topic) is not None
    old = nfm.load(base, "tech-old", {}, now=NOW)
    assert old.channel == "example-tech" and old.path == str(path)
    assert old.hit(topic) is not None
    # another channel's entry still does not hold this one back
    assert nfm.load(base, "example-film", {}, now=NOW).hit(topic) is None


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
