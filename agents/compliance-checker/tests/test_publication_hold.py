#!/usr/bin/env python3
"""CF-0318: a `review` blocks the publication, not the production.

The acceptance criterion of the task, in tests: **replay a batch that had a
`review` and you get a video slot and a mark** - and the mark is somewhere it
will still be a month later, when Publisher (milestone 2.0) finally arrives to
read it.

The three things these tests really guard:

* **The mark outlives the batch.** `scripts/archive_old_batches.sh` *moves* a
  batch directory to Archive after 31 days (`mv`, not `cp` - CF-0056). A
  mark that lives only under `pipeline/` is a mark whose only reader arrives
  after it is gone. `test_the_ledger_survives_the_archive_job` is that,
  mechanically: the batch directory is deleted and `is_held` still answers.
* **A signature is never written by the code that needs it.** The same rule as
  `shared/gate-prices.json` (CF-0320). Re-running the pass over the same batch
  must not un-sign a row a human signed, and must not re-date a hold that has
  been standing for weeks. The one writer is `sign_hold` (CF-0687), called on
  the user's explicit action in the command center with a note; the guard
  asserts nothing outside its body assigns a signature other than `None`.
* **Fail closed.** A ledger that will not parse holds everything, and the
  writer refuses rather than starting a fresh one over it. A *missing* ledger
  is not that - nothing was ever held.

No pytest dependency - plain asserts, dual-mode, same style as
tests/test_cut_shortlist.py.
"""
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from _tmproot import tmp_root  # noqa: E402  CF-0489: removed at exit
_TMP = tmp_root("publication-hold-")

import _channel_ids  # noqa: E402
import cut_shortlist as cut  # noqa: E402
import publication_hold as ph  # noqa: E402

CHANNEL = "example-film"
BATCH = "2026-09-22T1001Z"
TARGET = 5
TARGET_FROM = f"channels/{CHANNEL}.json scope.max_titles_per_batch"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------
def a_result(tid, verdict):
    """A verdict record of the shape the Trend Hunter pass writes - both checks
    included, because the hold copies them into the ledger verbatim and they
    are the whole basis a reader has a month later.

    Since CF-0420 a `review` is earned by the content-sensitivity check alone -
    a rights-holder match holds nothing - so every non-`clear` fixture carries
    a sensitivity flag. The rights match stays on it, for information: the
    hold must copy it without resting on it."""
    return {"topic_id": tid, "verdict": verdict,
            "rights_holder_check": {"matched": verdict != "clear",
                                    "risk_level": "high" if verdict == "review" else "medium",
                                    "reason": f"blacklist reading for {tid}",
                                    "affects_verdict": False},
            "content_sensitivity_check": {"flagged": verdict != "clear",
                                          "notes": f"notes for {tid}"}}


def a_batch(verdicts):
    """`(compliance_doc, stage_doc)` for a shortlist of `len(verdicts)` topics
    in the order given - the same fixture shape as test_cut_shortlist.py."""
    ids = [f"t{i}" for i in range(1, len(verdicts) + 1)]
    stage = {"batch_id": BATCH, "channel": CHANNEL,
             "selection": {"stage": "trend-hunter", "shortlist_size": len(ids),
                           "carried": len(ids)},
             "topics": [{"topic_id": t} for t in ids]}
    doc = {"batch_id": BATCH, "channel": CHANNEL, "stage_checked": "01-trend-hunter",
           "checked_at": "2026-09-22T10:19:00Z",
           "results": [a_result(t, v) for t, v in zip(ids, verdicts)]}
    return doc, stage


def a_root():
    """A miniature factory root: channel config, the two shared libraries the
    scripts import, and no `publish/` directory at all - the state of every
    checkout before the first hold is written."""
    tmp = Path(tempfile.mkdtemp(prefix="publication-hold-", dir=_TMP))
    (tmp / "channels").mkdir()
    (tmp / "shared").mkdir()
    (tmp / "shared" / "runlog").symlink_to(_channel_ids.ROOT / "shared" / "runlog")
    (tmp / "shared" / "channel_ids.py").symlink_to(
        _channel_ids.ROOT / "shared" / "channel_ids.py")
    (tmp / "channels" / f"{CHANNEL}.json").write_text(json.dumps(
        {"channel": CHANNEL, "scope": {"max_titles_per_batch": TARGET}}))
    return tmp


def write_batch(root, doc, stage):
    batch = root / "pipeline" / CHANNEL / BATCH
    batch.mkdir(parents=True, exist_ok=True)
    out_path = batch / "02-compliance-checker.json"
    stage_path = batch / "01-trend-hunter.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False))
    stage_path.write_text(json.dumps(stage, ensure_ascii=False))
    return out_path, stage_path


def run_cli(root, args):
    env = dict(os.environ, FACTORY_ROOT=str(root))
    env.pop("RUNLOG_BATCH", None)
    return subprocess.run([sys.executable, str(SCRIPTS / "publication_hold.py"),
                           *args, "--root", str(root)],
                          capture_output=True, text=True, env=env, timeout=60)


def ledger(root):
    return json.loads((root / "publish" / "publication-holds.json").read_text())


def holds_by_id(root):
    return {r["hold_id"]: r for r in ledger(root)["holds"]}


# --------------------------------------------------------------------------
# the acceptance criterion: replay a batch that had a `review`
# --------------------------------------------------------------------------
def test_replay_of_a_review_batch_gives_a_slot_and_a_mark():
    """The whole task in one test. Eight judged, four of them `review`. Before
    CF-0318 a `review` died at the indexer; now it is made and held. Since
    CF-0335 the four publishable topics take their slots first, so the fifth
    goes to the best-ranked `review` (t1) and the rest wait in reserve."""
    root = a_root()
    doc, stage = a_batch(["review", "clear", "caution", "clear", "caution",
                          "review", "review", "review"])
    out, carried, _ = cut.cut_document(doc, stage, TARGET, TARGET_FROM)

    # ... the slot.
    assert carried[0] == "t1", (
        "the `review` topic at rank 1 takes a batch slot - the video is made")
    assert out["cut"]["held"] == 1

    # ... and the mark, in both places it has to be.
    out_path, _ = write_batch(root, out, stage)
    proc = run_cli(root, [str(out_path), CHANNEL])
    assert proc.returncode == 0, proc.stderr
    assert "t1: publication held" in proc.stdout, proc.stdout

    row = [r for r in json.loads(out_path.read_text())["results"]
           if r["topic_id"] == "t1"][0]
    assert row["publication_hold"]["blocks"] == "publication"
    assert row["publication_hold"]["blocks_production"] is False
    assert row["verdict"] == "review", "the verdict itself is not softened"

    held = holds_by_id(root)
    assert f"{CHANNEL}/{BATCH}/t1" in held, held.keys()
    stored = held[f"{CHANNEL}/{BATCH}/t1"]
    assert stored["signature"] is None
    assert stored["rights_holder_check"] == row["rights_holder_check"], (
        "the ledger carries the reading verbatim: the batch directory it came "
        "from is archived after 31 days, so this copy is all a reader has")
    assert ph.is_held(CHANNEL, BATCH, "t1", root=root)[0] is True


def test_a_reserve_review_is_held_too():
    """CF-0306 refills a lost slot from `reserve[]` without rewriting `02`, so
    a `review` sitting in the reserve can become a video with nothing running
    over it again. A hold on a video that is never made costs nothing; a video
    made with no hold is the wrong upload this task exists to prevent."""
    root = a_root()
    doc, stage = a_batch(["clear"] * 5 + ["review", "clear", "clear"])
    out, _, reserved = cut.cut_document(doc, stage, TARGET, TARGET_FROM)
    assert "t6" in reserved
    out_path, _ = write_batch(root, out, stage)
    assert run_cli(root, [str(out_path), CHANNEL]).returncode == 0
    row = holds_by_id(root)[f"{CHANNEL}/{BATCH}/t6"]
    assert row["found_in"] == "reserve"
    assert ph.is_held(CHANNEL, BATCH, "t6", root=root)[0] is True


def test_a_clear_topic_is_never_held():
    root = a_root()
    doc, stage = a_batch(["clear", "caution", "clear", "caution", "clear"])
    out_path, _ = write_batch(root, doc, stage)
    assert run_cli(root, [str(out_path), CHANNEL]).returncode == 0
    assert ledger(root)["holds"] == []
    for tid in ("t1", "t2"):
        held, reason = ph.is_held(CHANNEL, BATCH, tid, root=root)
        assert held is False, reason


# --------------------------------------------------------------------------
# the mark outlives the batch
# --------------------------------------------------------------------------
def test_the_ledger_lives_outside_pipeline():
    """Said as a path, because this is the whole reason the ledger exists
    rather than a field in the batch file."""
    assert ph.LEDGER_REL == Path("publish") / "publication-holds.json", ph.LEDGER_REL
    assert "pipeline" not in ph.LEDGER_REL.parts


def test_the_ledger_survives_the_archive_job():
    """`scripts/archive_old_batches.sh` MOVES the batch directory to
    Archive after 31 days. Publisher arrives months later. So: delete the
    batch and ask again."""
    root = a_root()
    doc, stage = a_batch(["review", "clear", "clear", "clear", "clear", "clear"])
    out, _, _ = cut.cut_document(doc, stage, TARGET, TARGET_FROM)
    out_path, _ = write_batch(root, out, stage)
    assert run_cli(root, [str(out_path), CHANNEL]).returncode == 0

    shutil.rmtree(root / "pipeline")            # the archive job, 31 days later
    held, reason = ph.is_held(CHANNEL, BATCH, "t1", root=root)
    assert held is True, reason
    assert "must NOT be PUBLISHED" in reason, reason
    row = holds_by_id(root)[f"{CHANNEL}/{BATCH}/t1"]
    for field in ("verdict", "rights_holder_check", "content_sensitivity_check",
                  "reason", "batch_artifact"):
        assert row.get(field) is not None, (
            f"{field} is missing from the ledger row, and the batch it could "
            f"have been read from is gone")


def test_the_reason_stands_on_its_own():
    """A month later the reader has this sentence and nothing else."""
    root = a_root()
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    run_cli(root, [str(out_path), CHANNEL])
    reason = holds_by_id(root)[f"{CHANNEL}/{BATCH}/t1"]["reason"]
    for phrase in ("may be", "MADE", "must NOT be PUBLISHED", "signature",
                   "CF-0318", "CF-0017/CF-0018"):
        assert phrase in reason, (phrase, reason)
    note = ledger(root)["note"]
    assert "archive_old_batches.sh" in note and "gate-prices.json" in note


# --------------------------------------------------------------------------
# the signature, and what a re-run may not do to it
# --------------------------------------------------------------------------
def test_a_signature_clears_the_hold_and_nothing_in_the_code_writes_one():
    root = a_root()
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    run_cli(root, [str(out_path), CHANNEL])
    assert ph.is_held(CHANNEL, BATCH, "t1", root=root)[0] is True

    path = root / "publish" / "publication-holds.json"
    data = json.loads(path.read_text())
    data["holds"][0]["signature"] = {"user": "Константин", "date": "2026-09-23",
                                     "note": "смотрел, беру на себя"}
    path.write_text(json.dumps(data, ensure_ascii=False))

    held, reason = ph.is_held(CHANNEL, BATCH, "t1", root=root)
    assert held is False and "signed by" in reason, reason
    assert ph.open_holds(root=root)[0] == [], "a signed hold is not standing"

    # and the pass, run again over the same verdicts, must not take it back.
    run_cli(root, [str(out_path), CHANNEL])
    assert ph.is_held(CHANNEL, BATCH, "t1", root=root)[0] is False, (
        "re-running the pass un-signed a row a human signed")
    assert_only_sign_hold_writes_a_signature()


SIGNATURE_WRITES = (
    # a dict literal carrying the key, and what it is set to
    re.compile(r'"signature"\s*:\s*([^,}\n]+)'),
    # a subscript assignment, `x["signature"] = ...`
    re.compile(r'\[\s*"signature"\s*\]\s*=(?!=)\s*([^\n]+)'),
    # `x.setdefault("signature", ...)`, `x.update(signature=...)` and the like
    re.compile(r'setdefault\(\s*"signature"\s*,\s*([^)\n]+)'),
    re.compile(r'[(,]\s*signature\s*=(?!=)\s*([^,)\n]+)'),
)


def test_the_signature_guard_bites():
    # the guard is only as good as its patterns: each write shape is caught
    for line in ('known["signature"] = {"user": "x"}',
                 'row.setdefault("signature", {"user": "x"})',
                 'row.update(signature={"user": "x"})',
                 '{"hold_id": h, "signature": {"user": "x"}}'):
        assert any(m.group(1).strip() != "None"
                   for rx in SIGNATURE_WRITES for m in rx.finditer(line)), line
    for line in ('signature = row.get("signature")', '"signature": None,',
                 'known.setdefault("signature", None)'):
        assert all(m.group(1).strip() == "None"
                   for rx in SIGNATURE_WRITES for m in rx.finditer(line)), line


def assert_only_sign_hold_writes_a_signature():
    """CF-0320 with the CF-0687 exception, as one assertion: outside the body
    of `sign_hold` the module assigns a signature only as `None`."""
    src = (SCRIPTS / "publication_hold.py").read_text()
    body = inspect.getsource(ph.sign_hold)
    assert src.count(body) == 1, "sign_hold's source is not found once in the module"
    assert re.search(r'row\["signature"\]\s*=\s*\{', body), (
        "sign_hold no longer writes the signature it exists to write")
    outside = src.replace(body, "")
    assert '"signature": None' in outside
    bad = [m.group(0) for rx in SIGNATURE_WRITES for m in rx.finditer(outside)
           if m.group(1).strip() != "None"]
    assert not bad, (
        "something in publication_hold.py other than sign_hold writes a "
        "signature - a signature written by the code that needs it is not a "
        "signature (CF-0320). The one exception is sign_hold, called on the "
        "user's explicit action in the command center with a note (CF-0687, "
        f"the user's permission of 2026-10-11): {bad}")


def test_a_rerun_refreshes_the_reading_and_keeps_the_date():
    root = a_root()
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    run_cli(root, [str(out_path), CHANNEL])
    first = holds_by_id(root)[f"{CHANNEL}/{BATCH}/t1"]
    raised_at = first["raised_at"]

    doc["results"][0]["rights_holder_check"]["reason"] = "a fuller reading"
    write_batch(root, doc, stage)
    proc = run_cli(root, [str(out_path), CHANNEL])
    assert "1 new" not in proc.stdout and "1 refreshed" in proc.stdout, proc.stdout
    again = holds_by_id(root)[f"{CHANNEL}/{BATCH}/t1"]
    assert again["rights_holder_check"]["reason"] == "a fuller reading"
    assert again["raised_at"] == raised_at, (
        "a re-run must not re-date a hold that has been standing for weeks")
    assert len(ledger(root)["holds"]) == 1, "a re-run duplicated the row"


def test_a_relaxed_review_resolves_the_hold_and_the_row_stays():
    """A `review` lowered to `caution` on a re-run of the pass. The video
    becomes publishable; the record of why it was held does not disappear."""
    root = a_root()
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    run_cli(root, [str(out_path), CHANNEL])

    relaxed = json.loads(out_path.read_text())
    relaxed["results"][0]["verdict"] = "caution"
    out_path.write_text(json.dumps(relaxed, ensure_ascii=False))
    proc = run_cli(root, [str(out_path), CHANNEL])
    assert "t1: hold resolved" in proc.stdout, proc.stdout

    row = holds_by_id(root)[f"{CHANNEL}/{BATCH}/t1"]
    assert row["resolved_at"] and "no longer" in row["resolved_reason"]
    assert ph.is_held(CHANNEL, BATCH, "t1", root=root)[0] is False
    assert "publication_hold" not in json.loads(out_path.read_text())["results"][0], (
        "the stale block must come off the batch row too")


# --------------------------------------------------------------------------
# the two passes
# --------------------------------------------------------------------------
def a_script_pass(verdicts):
    """`04-compliance-checker.json` - one row per script, `topic_id` beside it.
    The hold is keyed on the topic, because a hold is on the video."""
    ids = [f"t{i}" for i in range(1, len(verdicts) + 1)]
    rows = []
    for tid, verdict in zip(ids, verdicts):
        row = a_result(tid, verdict)
        row["script_id"] = f"{tid}-script1"
        rows.append(row)
    return {"batch_id": BATCH, "channel": CHANNEL,
            "stage_checked": "03-content-researcher",
            "checked_at": "2026-09-22T12:00:00Z", "results": rows}


def test_a_review_at_the_researcher_pass_is_held_on_the_topic():
    root = a_root()
    doc = a_script_pass(["clear", "review", "clear"])
    path = root / "pipeline" / CHANNEL / BATCH / "04-compliance-checker.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False))
    assert run_cli(root, [str(path), CHANNEL]).returncode == 0
    row = holds_by_id(root)[f"{CHANNEL}/{BATCH}/t2"]
    assert row["script_id"] == "t2-script1"
    assert row["stage_checked"] == "03-content-researcher"
    assert row["batch_artifact"].endswith("04-compliance-checker.json"), row


def test_the_researcher_pass_cannot_lift_a_hold_the_topic_pass_raised():
    """The two passes judge different things: `02` judges the topic against the
    blacklist, `04` judges the written script. A `clear` at `04` is not a
    re-reading of the high-risk rights match that held the topic at `02`, so it
    must not silently clear the video for upload. Only the pass that raised a
    hold may resolve it."""
    root = a_root()
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    run_cli(root, [str(out_path), CHANNEL])
    assert ph.is_held(CHANNEL, BATCH, "t1", root=root)[0] is True

    later = a_script_pass(["clear"] * 6)
    path = root / "pipeline" / CHANNEL / BATCH / "04-compliance-checker.json"
    path.write_text(json.dumps(later, ensure_ascii=False))
    assert run_cli(root, [str(path), CHANNEL]).returncode == 0
    held, reason = ph.is_held(CHANNEL, BATCH, "t1", root=root)
    assert held is True, reason
    assert holds_by_id(root)[f"{CHANNEL}/{BATCH}/t1"]["resolved_at"] is None


# --------------------------------------------------------------------------
# fail closed
# --------------------------------------------------------------------------
def test_a_missing_ledger_holds_nothing():
    root = a_root()
    assert not (root / "publish").exists()
    held, reason = ph.is_held(CHANNEL, BATCH, "t1", root=root)
    assert held is False, reason


def test_an_unreadable_ledger_holds_everything():
    root = a_root()
    (root / "publish").mkdir()
    (root / "publish" / "publication-holds.json").write_text("{not json")
    held, reason = ph.is_held(CHANNEL, BATCH, "whatever", root=root)
    assert held is True and "cannot be read" in reason, reason


def test_the_writer_refuses_an_unreadable_ledger_rather_than_replacing_it():
    """Starting a fresh ledger over a broken one loses every hold standing in
    it - the one failure mode where a crash is better than a recovery."""
    root = a_root()
    (root / "publish").mkdir()
    broken = root / "publish" / "publication-holds.json"
    broken.write_text("{not json")
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    proc = run_cli(root, [str(out_path), CHANNEL])
    assert proc.returncode == 2, proc.stdout
    assert broken.read_text() == "{not json", "the broken ledger was overwritten"


def test_dry_run_writes_nothing():
    root = a_root()
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    before = out_path.read_text()
    proc = run_cli(root, [str(out_path), CHANNEL, "--dry-run"])
    assert proc.returncode == 0 and "dry run" in proc.stdout
    assert out_path.read_text() == before
    assert not (root / "publish" / "publication-holds.json").exists()


# --------------------------------------------------------------------------
# the command line the user and Publisher use
# --------------------------------------------------------------------------
def test_check_exits_1_on_a_held_video_and_0_on_a_free_one():
    """The shape CF-0018 can call from a shell before it uploads anything."""
    root = a_root()
    doc, stage = a_batch(["review", "clear", "clear", "clear", "clear", "clear"])
    out_path, _ = write_batch(root, doc, stage)
    run_cli(root, [str(out_path), CHANNEL])
    assert run_cli(root, ["--check", CHANNEL, BATCH, "t1"]).returncode == 1
    assert run_cli(root, ["--check", CHANNEL, BATCH, "t2"]).returncode == 0


def test_list_names_every_standing_hold():
    root = a_root()
    doc, stage = a_batch(["review", "clear", "review", "clear", "clear", "clear"])
    out_path, _ = write_batch(root, doc, stage)
    run_cli(root, [str(out_path), CHANNEL])
    proc = run_cli(root, ["--list"])
    assert proc.returncode == 0
    assert f"{CHANNEL}/{BATCH}/t1" in proc.stdout and f"{CHANNEL}/{BATCH}/t3" in proc.stdout
    assert "2 publication hold(s) standing" in proc.stdout, proc.stdout


def test_usage_error_is_exit_2():
    root = a_root()
    assert run_cli(root, []).returncode == 2
    assert run_cli(root, ["--check", CHANNEL]).returncode == 2


# --------------------------------------------------------------------------
# the ledger answers under every name the channel has had (CF-0197)
# --------------------------------------------------------------------------
FORMER = "the-channels-old-name"


def a_renamed_root():
    """The same miniature root, for a channel that has been renamed once - the
    state CF-0180 left the real tree in."""
    tmp = a_root()
    (tmp / "channels" / f"{CHANNEL}.json").write_text(json.dumps(
        {"channel_id": CHANNEL, "channel": CHANNEL,
         "former_channel_ids": [FORMER],
         "scope": {"max_titles_per_batch": TARGET}}))
    return tmp


def a_frozen_batch(root, verdicts):
    """A batch written *before* the rename: the old id frozen in the `channel`
    field and in the directory name, and neither is ever rewritten - the file
    is a dated record. This is the only input this ledger will ever get for a
    video made before CF-0180."""
    doc, stage = a_batch(verdicts)
    doc["channel"] = FORMER
    stage["channel"] = FORMER
    batch = root / "pipeline" / FORMER / BATCH
    batch.mkdir(parents=True, exist_ok=True)
    out_path = batch / "02-compliance-checker.json"
    out_path.write_text(json.dumps(doc, ensure_ascii=False))
    (batch / "01-trend-hunter.json").write_text(json.dumps(stage, ensure_ascii=False))
    return out_path


def test_a_batch_frozen_before_the_rename_is_filed_under_the_current_id():
    """What the durable ledger stores is the decision, not the string the batch
    happened to carry: this file outlives the batch directory by months and is
    read by a Publisher that knows only the channel's current name."""
    root = a_renamed_root()
    out_path = a_frozen_batch(root, ["review", "clear"])
    proc = run_cli(root, [str(out_path)])
    assert proc.returncode == 0, proc.stderr

    rows = ledger(root)["holds"]
    assert len(rows) == 1, rows
    assert rows[0]["channel"] == CHANNEL, (
        f"the ledger filed the hold under {rows[0]['channel']!r} - the frozen "
        f"field, which names a config that no longer exists")
    assert rows[0]["hold_id"] == f"{CHANNEL}/{BATCH}/t1"


# Both halves of the mark, built from the artifact alone - the call a caller
# that is not the CLI makes. The CLI resolves the channel in `main` before it
# hands it down, which hides a `mark_document` that does not resolve; there is
# nothing between these two functions and the frozen `channel` field.
PROBE = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
import publication_hold as ph
doc = json.loads(open(sys.argv[2]).read())
marked, _, _ = ph.mark_document(doc)
row = marked["results"][0]["publication_hold"]
print(row["hold_id"])
print(ph.hold_rows(doc)[0]["hold_id"])
"""


def test_the_batch_mark_and_the_ledger_row_carry_the_same_hold_id():
    """`mark()` is the one shape both are built from. Resolving the channel in
    one of the two and not the other is how they drift apart, and a mark whose
    id matches nothing in the ledger is a mark that reads as `not held`."""
    root = a_renamed_root()
    out_path = a_frozen_batch(root, ["review"])
    proc = subprocess.run([sys.executable, "-c", PROBE, str(SCRIPTS), str(out_path)],
                          capture_output=True, text=True, timeout=60,
                          env=dict(os.environ, FACTORY_ROOT=str(root)))
    assert proc.returncode == 0, proc.stderr
    stamped, stored = proc.stdout.split()
    assert stamped == stored == f"{CHANNEL}/{BATCH}/t1", (
        f"the batch row was stamped {stamped!r} and the ledger row keyed "
        f"{stored!r} - one of the two read the frozen `channel` field at face "
        f"value, and a mark whose id matches no ledger row reads as `not held`")


def test_the_hold_answers_the_same_asked_by_either_name():
    """The lookup CF-0017/CF-0018 call. Publisher knows the channel by its
    current id; the batch knew it by the old one. Both must be the one video."""
    root = a_renamed_root()
    out_path = a_frozen_batch(root, ["review"])
    assert run_cli(root, [str(out_path)]).returncode == 0
    for name in (CHANNEL, FORMER):
        held, reason = ph.is_held(name, BATCH, "t1", root=root)
        assert held, f"asked by {name!r} the ledger said not held: {reason}"
        assert ph.open_holds(root=root, channel=name)[0], name
    assert not ph.is_held(CHANNEL, BATCH, "t2", root=root)[0]


def test_a_rename_after_the_row_was_written_does_not_lose_the_hold():
    """The row above is filed under the current id - but *this* file is the
    durable one, and the next rename lands while it sits on disk. The ledger is
    deliberately not rewritten to chase a rename, so the lookup rebuilds the
    key from the row's own fields instead."""
    root = a_root()
    out_path, _ = write_batch(root, *a_batch(["review"]))
    assert run_cli(root, [str(out_path)]).returncode == 0
    assert ledger(root)["holds"][0]["channel"] == CHANNEL

    # the channel is renamed now, a month later: what the row stores is a
    # former id, and nothing goes back to edit it.
    new_id = "the-channels-next-name"
    (root / "channels" / f"{CHANNEL}.json").unlink()
    (root / "channels" / f"{new_id}.json").write_text(json.dumps(
        {"channel_id": new_id, "channel": new_id, "former_channel_ids": [CHANNEL],
         "scope": {"max_titles_per_batch": TARGET}}))
    held, reason = ph.is_held(new_id, BATCH, "t1", root=root)
    assert held, f"the hold was lost by the rename: {reason}"


def test_a_second_pass_after_the_rename_refreshes_the_row_it_wrote():
    """A duplicate row would be a hold that can be signed once and still stand,
    which is the ledger answering two ways about one video."""
    root = a_renamed_root()
    out_path = a_frozen_batch(root, ["review"])
    assert run_cli(root, [str(out_path)]).returncode == 0
    assert run_cli(root, [str(out_path), CHANNEL]).returncode == 0
    rows = ledger(root)["holds"]
    assert len(rows) == 1, f"{len(rows)} rows for one video: {rows}"


# --------------------------------------------------------------------------
# CF-0420: the rights-holder match holds nothing, and the ledger's rights-only
# rows are resolved in place
# --------------------------------------------------------------------------
def a_rights_only_ledger_row(tid, flagged=False, signature=None):
    return {"hold_id": f"{CHANNEL}/{BATCH}/{tid}", "channel": CHANNEL,
            "batch_id": BATCH, "topic_id": tid, "verdict": "review",
            "stage_checked": "01-trend-hunter",
            "rights_holder_check": {"matched": True, "risk_level": "high",
                                    "reason": "Zenith Studios / Example Animation"},
            "content_sensitivity_check": {"flagged": flagged, "notes": None},
            "reason": "held", "raised_at": "2026-09-27T10:00:00Z",
            "resolved_at": None, "resolved_reason": None, "signature": signature}


def test_the_reason_does_not_name_the_rights_match_as_a_basis():
    root = a_root()
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    run_cli(root, [str(out_path), CHANNEL])
    row = holds_by_id(root)[f"{CHANNEL}/{BATCH}/t1"]
    assert "content-sensitivity flag" in row["reason"], row["reason"]
    assert "rights-holder match at risk" not in row["reason"]
    assert row["rights_holder_check"]["matched"] is True, (
        "the match is still copied onto the ledger row, for a takedown")


def test_resolve_rights_only_resolves_in_place_and_leaves_the_rest():
    root = a_root()
    (root / "publish").mkdir()
    signed = {"user": "user", "date": "2026-09-27", "note": "ok"}
    rows = [a_rights_only_ledger_row("zenith"),
            a_rights_only_ledger_row("drugs", flagged=True),
            a_rights_only_ledger_row("signed", signature=signed)]
    (root / "publish" / "publication-holds.json").write_text(json.dumps(
        {"note": "n", "task": "CF-0318", "holds": rows}, ensure_ascii=False))

    dry = run_cli(root, ["--resolve-rights-only", "--date", "2026-09-28", "--dry-run"])
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert holds_by_id(root)[f"{CHANNEL}/{BATCH}/zenith"]["resolved_at"] is None

    proc = run_cli(root, ["--resolve-rights-only", "--date", "2026-09-28"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 rights-only hold(s) resolved" in proc.stdout, proc.stdout
    by_id = holds_by_id(root)
    assert len(by_id) == 3, "no row is ever deleted"
    zenith = by_id[f"{CHANNEL}/{BATCH}/zenith"]
    assert zenith["resolved_at"] == "2026-09-28"
    assert zenith["resolved_reason"] == ph.RIGHTS_ONLY_REASON
    assert "CF-0420" in zenith["resolved_reason"]
    assert by_id[f"{CHANNEL}/{BATCH}/drugs"]["resolved_at"] is None
    assert by_id[f"{CHANNEL}/{BATCH}/signed"]["resolved_at"] is None
    assert ph.is_held(CHANNEL, BATCH, "zenith", root=root)[0] is False
    assert ph.is_held(CHANNEL, BATCH, "drugs", root=root)[0] is True

    again = run_cli(root, ["--resolve-rights-only", "--date", "2026-10-01"])
    assert "0 rights-only hold(s) resolved" in again.stdout
    assert holds_by_id(root)[f"{CHANNEL}/{BATCH}/zenith"]["resolved_at"] == "2026-09-28"


def test_resolve_rights_only_refuses_an_unreadable_ledger():
    root = a_root()
    (root / "publish").mkdir()
    (root / "publish" / "publication-holds.json").write_text("{not json")
    proc = run_cli(root, ["--resolve-rights-only"])
    assert proc.returncode == 2 and "refusing" in proc.stdout


# --------------------------------------------------------------------------
# the two scripts agree on what `review` means
# --------------------------------------------------------------------------
def test_the_two_scripts_do_not_drift_on_the_verdicts():
    assert ph.HOLD_VERDICTS == ("review",)
    assert ph.PUBLISH_VERDICTS == cut.PUBLISH_VERDICTS
    assert set(cut.PRODUCTION_VERDICTS) == set(ph.PUBLISH_VERDICTS) | set(ph.HOLD_VERDICTS), (
        "everything the cut lets into production is either publishable without a "
        "signature or held - a third state would be a video nobody can account for")
    assert ph.REASON_CODE != "compliance_review", (
        "the funnel's `compliance_review` means a topic the gate LOST; a held "
        "topic is not lost, and sharing the code would make the funnel unreadable")


# --------------------------------------------------------------------------
# CF-0687: the center signs a hold on the user's explicit action
# --------------------------------------------------------------------------
LEDGER_REL = Path("publish") / "publication-holds.json"


def a_signable_root():
    """A root whose ledger carries one content-sensitivity hold (t1), written
    by the pass itself, plus a rights-only row, a resolved row and a row whose
    verdict holds nothing - every state a sign request can meet."""
    root = a_root()
    doc, stage = a_batch(["review"] + ["clear"] * 5)
    out_path, _ = write_batch(root, doc, stage)
    proc = run_cli(root, [str(out_path), CHANNEL])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    path = root / LEDGER_REL
    data = json.loads(path.read_text())
    resolved = a_rights_only_ledger_row("old", flagged=True)
    resolved.update(resolved_at="2026-09-28", resolved_reason="lowered")
    lowered = a_rights_only_ledger_row("lowered", flagged=True)
    lowered["verdict"] = "caution"
    data["holds"] += [a_rights_only_ledger_row("zenith"), resolved, lowered]
    path.write_text(json.dumps(data, ensure_ascii=False))
    return root, out_path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def refusal(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except ph.HoldSignError as exc:
        assert exc.text_ru and exc.text_ru == ph.SIGN_REFUSALS_RU[exc.code].format_map(
            exc.values), exc.text_ru
        assert re.search("[а-яА-Я]", exc.text_ru), exc.text_ru
        assert exc.as_dict() == {"code": exc.code, "text_ru": exc.text_ru,
                                 "text": str(exc)}
        return exc
    raise AssertionError(f"{fn.__name__}{args} was not refused")


def test_check_sign_reads_and_writes_nothing():
    root, _ = a_signable_root()
    path = root / LEDGER_REL
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    seen = ph.check_sign(root, f"{CHANNEL}/{BATCH}/t1")
    assert seen["row"]["hold_id"] == f"{CHANNEL}/{BATCH}/t1"
    assert seen["row"]["signature"] is None
    assert seen["fingerprint"] == sha(path)
    for hid in ("nope/x/y", f"{CHANNEL}/{BATCH}/zenith", f"{CHANNEL}/{BATCH}/old"):
        refusal(ph.check_sign, root, hid)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before, (
        "check_sign wrote to the ledger")
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name], (
        "check_sign left a file beside the ledger")
    # the ledger file itself works as well as the root
    assert ph.check_sign(path, f"{CHANNEL}/{BATCH}/t1")["fingerprint"] == sha(path)


def test_every_refusal_code():
    root, _ = a_signable_root()
    hid = f"{CHANNEL}/{BATCH}/t1"
    codes = {
        "no_such_hold": refusal(ph.check_sign, root, f"{CHANNEL}/{BATCH}/t9").code,
        "not_signable": refusal(ph.sign_hold, root, f"{CHANNEL}/{BATCH}/zenith",
                                "Константин", "смотрел").code,
        "already_resolved": refusal(ph.check_sign, root, f"{CHANNEL}/{BATCH}/old").code,
        "empty_user": refusal(ph.sign_hold, root, hid, "  ", "смотрел").code,
        "empty_note": refusal(ph.sign_hold, root, hid, "Константин", " \n\t").code,
    }
    assert refusal(ph.check_sign, root,
                   f"{CHANNEL}/{BATCH}/lowered").code == "already_resolved", (
        "a row whose verdict no longer holds anything is not signed")
    assert refusal(ph.check_sign, a_root(), hid).code == "no_such_hold", (
        "no ledger is no hold")
    ph.sign_hold(root, hid, "Константин", "смотрел в центре")
    codes["already_signed"] = refusal(ph.sign_hold, root, hid, "Другой", "ещё").code
    assert codes == {c: c for c in codes}, codes
    broken = a_root()
    (broken / "publish").mkdir()
    (broken / LEDGER_REL).write_text("{not json")
    assert refusal(ph.check_sign, broken, hid).code == "ledger_unreadable"
    assert (broken / LEDGER_REL).read_text() == "{not json"
    assert set(ph.SIGN_REFUSALS_RU) == {
        "no_such_hold", "already_signed", "already_resolved", "not_signable",
        "empty_user", "empty_note", "ledger_unreadable"}


def test_sign_hold_records_via_and_changes_the_fingerprint():
    root, _ = a_signable_root()
    path = root / LEDGER_REL
    hid = f"{CHANNEL}/{BATCH}/t1"
    before = ph.check_sign(root, hid)["fingerprint"]
    done = ph.sign_hold(root, hid, " Константин ", " смотрел в центре ",
                        when="2026-10-11T12:00:00Z")
    assert done["fingerprint"] == sha(path) != before
    sig = holds_by_id(root)[hid]["signature"]
    assert sig == {"user": "Константин", "date": "2026-10-11T12:00:00Z",
                   "note": "смотрел в центре", "via": "center"}, sig
    assert done["row"]["signature"] == sig
    assert sorted(p.name for p in path.parent.iterdir()) == [path.name], (
        "the atomic write left its temp file")
    # the default date is the module's own format
    root2, _ = a_signable_root()
    sig2 = ph.sign_hold(root2 / LEDGER_REL, hid, "U", "n", via="cli")["row"]["signature"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", sig2["date"]), sig2
    assert sig2["via"] == "cli"
    # nothing else in the ledger moved
    others = {k: v for k, v in holds_by_id(root).items() if k != hid}
    assert all(r["signature"] is None for r in others.values())


def test_a_signed_row_is_free_and_stays_signed_after_a_rerun():
    root, out_path = a_signable_root()
    hid = f"{CHANNEL}/{BATCH}/t1"
    ph.sign_hold(root, hid, "Константин", "смотрел в центре", when="2026-10-11")
    held, reason = ph.is_held(CHANNEL, BATCH, "t1", root=root)
    assert held is False and "signed by Константин" in reason and "via center" in reason, reason
    assert hid not in [r["hold_id"] for r in ph.open_holds(root=root)[0]]
    signed = holds_by_id(root)[hid]["signature"]

    proc = run_cli(root, [str(out_path), CHANNEL])
    assert proc.returncode == 0 and "1 refreshed" in proc.stdout, proc.stdout
    assert holds_by_id(root)[hid]["signature"] == signed, (
        "re-running the pass altered a signature the user wrote through the center")
    assert run_cli(root, ["--resolve-rights-only"]).returncode == 0
    assert holds_by_id(root)[hid]["signature"] == signed
    check = run_cli(root, ["--check", CHANNEL, BATCH, "t1"])
    assert check.returncode == 0 and "via center" in check.stdout, check.stdout


def test_the_cli_signs_and_refuses_in_russian():
    root, _ = a_signable_root()
    hid = f"{CHANNEL}/{BATCH}/t1"
    path = root / LEDGER_REL
    before = path.read_bytes()
    dry = run_cli(root, ["--sign", hid, "--user", "Константин", "--note", "ок",
                         "--dry-run"])
    assert dry.returncode == 0 and "dry run" in dry.stdout, dry.stdout + dry.stderr
    assert path.read_bytes() == before
    no_note = run_cli(root, ["--sign", hid, "--user", "Константин", "--note", " "])
    assert no_note.returncode == 1, no_note.stdout
    assert ph.SIGN_REFUSALS_RU["empty_note"] in no_note.stdout
    rights = run_cli(root, ["--sign", f"{CHANNEL}/{BATCH}/zenith", "--user", "U",
                            "--note", "n"])
    assert rights.returncode == 1 and "CF-0420" in rights.stdout, rights.stdout
    assert path.read_bytes() == before
    ok = run_cli(root, ["--sign", hid, "--user", "Константин", "--note",
                        "смотрел", "--date", "2026-10-11"])
    assert ok.returncode == 0 and "via cli" in ok.stdout, ok.stdout + ok.stderr
    assert holds_by_id(root)[hid]["signature"]["via"] == "cli"
    assert run_cli(root, ["--sign", hid]).returncode == 1, "already signed"
    assert run_cli(root, ["--sign"]).returncode == 2


def test_a_hold_is_signed_by_either_name_of_a_renamed_channel():
    root = a_renamed_root()
    proc = run_cli(root, [str(a_frozen_batch(root, ["review"] + ["clear"] * 5))])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    seen = ph.check_sign(root, f"{FORMER}/{BATCH}/t1")
    assert seen["row"]["hold_id"] == f"{CHANNEL}/{BATCH}/t1"


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
