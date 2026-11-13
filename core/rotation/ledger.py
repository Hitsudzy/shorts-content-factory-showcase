#!/usr/bin/env python3
"""CF-0040: the assignment ledger - one file per channel, one row per assignment.

This file *is* the format, the same way patterns/validate_patterns.py is the
schema of the vocabulary (CF-0039): there is no prose copy of the column list
anywhere else, because two descriptions of one file is how they drift.

Why a ledger at all, rather than scanning pipeline/ for what was assigned
(CF-0015 Q16): a rejected assignment appears in no batch file. The pair was
drawn, offered, and turned down; nothing downstream ever mentions it. Those
events are exactly what tells us a month from now that one pattern is being
refused half the time - which is a design defect visible long before the
Analyst exists. A scan of produced batches cannot see them by construction.

Why CSV and not JSON, against the rest of the repo (CF-0015 Q17):

  * the thing is a table - one row per assignment, fixed columns, thousands of
    rows over a year. JSON would nest a table for no gain.
  * append-only has to be *visible* as an append. Adding an element to a JSON
    array rewrites the previous line (the comma) and the closing bracket, so a
    one-row addition shows up in git as a three-line change; a CSV append is
    one added line and nothing else. The invariant this file is built around
    should be legible in the diff, not just enforced in code.
  * Publisher (CF-0042) and the Analyst (2.1.2) both want to read it as rows.

--------------------------------------------------------------------------
The columns
--------------------------------------------------------------------------

Written when the rotation assigns:

  seq                 int, 1-based, strictly increasing. The axis the K window
                      and the distribution window are counted on.
  assigned_at         ISO-8601 UTC
  channel, batch_id, script_id
  pattern_id, rhythm_id
  assigned_by         "rotation" | "rotation-after-rejection"

Written if the agent rejects the assignment (never by the agent itself - the
guard in rotate.py decides which of the two happens):

  rejection_reason    the agent's written reason. Required; a rejection
                      without one is not a rejection.

                      CF-0286 puts one more thing in this cell and, again, no
                      new column: an upheld rejection that was about the
                      *rhythm* rather than about the pair is stored with the
                      guard's prefix `[excluded rhythm: <rhythm_id>] ` in front
                      of the agent's own words. The replacement draw skips
                      every pair carrying that rhythm, and so does the next
                      assignment of the same script. Written by the guard and
                      only on an upheld rejection - see RHYTHM_EXCLUSION below
                      for why it is a prefix in the prose and not a column.
  rejection_verdict   "upheld" | "denied" - the guard's decision.
  rejected_at         ISO-8601 UTC, and non-empty *only* on an upheld
                      rejection. A row with this set is an event without a
                      continuation: no video was ever produced from it, and it
                      is excluded from every distribution count. A denied
                      rejection leaves this empty - the assignment stands, and
                      the reason is recorded on the standing row rather than
                      as a row of its own, so a denied rejection cannot inflate
                      the ledger or double-count the script.

                      CF-0139 adds a second writer of exactly these three
                      cells and no new ones: the planner's refusal. A video
                      whose pool could not supply the pictures (CF-0137 rung
                      4) is neither produced nor rejected on its pair - the
                      assignment was fine and the material was not - but it
                      is the same kind of row: an event without a
                      continuation. So it is written as an upheld rejection,
                      and the difference lives in the reason text and in the
                      machine-readable record beside it
                      (`rotation/shortage.py`, `<channel>.shortages.jsonl`),
                      not in a column of its own. A `production_failed_at`
                      column was rejected outright: it would be a schema
                      migration and a new branch in every counter, to
                      separate two things that already read apart. The
                      difference from an agent's rejection is that no
                      replacement pair is assigned - the topic goes back to
                      the queue and waits for material, and its next row says
                      `rotation-after-rejection`.

Written when the video is produced (Video Editor's file, via rotate.py):

  produced_at, video_path
  pattern_delivered, rhythm_delivered
                      CF-0041 writes these into 05-video-editor.json. Batches
                      cut before it landed carry no pattern at all, and those
                      cells stay empty rather than guessing: nothing checked
                      whether those cuts were the rhythm they were ordered as,
                      because nothing ordered them one.

  Nobody enters these by hand and Video Editor does not know this file exists.
  They are a pure function of 05-video-editor.json, so `rotate.py` derives
  them - inside `assign`, on every assignment, because assignment is the step
  of the pipeline that cannot be skipped and the enrichment had no pressure of
  its own (CF-0049). The deadline is the archive job: 30 days, and it moves the
  batch rather than copying it.

Written when the video is published - CF-0042:

  published_at, feed_position, video_id
                      Derived, like the production columns: the record of an
                      upload is `publish/uploads.json` (CF-0586, one writer:
                      agents/publisher/upload_records.py), and
                      `agents/publisher/publish_window.py record_published`
                      copies a video's slot (once it is in the past), its
                      1-based position in the channel's feed and its YouTube
                      id onto the script's row - matched by the strict key
                      (batch, script id; a rebuild through its `rebuild_of`).
                      It runs after every placement (`publish_card.py place`)
                      and on `publish_window.py record`. A video with no row
                      (a batch assigned before the ledger, a repeat batch that
                      reuses another batch's scripts) is listed, not guessed.
                      `feed_position` is a rank in the journal, not an
                      observation: a video written into the journal before it
                      shifts it. The one exception to "filled once" below
                      (CF-0866): `Ledger.resync` re-derives it on a row whose
                      `published_at` and `video_id` match the journal, logged
                      to `<channel>.resyncs.jsonl` beside the CSV.

--------------------------------------------------------------------------
The invariant
--------------------------------------------------------------------------

Append-only, enforced at two granularities:

  * rows are only ever appended, never deleted, never reordered, and `seq`
    is checked to be exactly last + 1;
  * a cell only ever goes from empty to filled. Enrichment fills the blanks
    left by earlier stages; it may not change what an earlier stage wrote.
    An assignment that has been recorded is a fact about what the rotation
    did, and rewriting it would make the distribution history unfalsifiable -
    which is the whole reason the guard has something to count.

One standing row per (batch_id, script_id) - CF-0383. A script id is unique
inside its batch and not across batches (two batches of one day, a repeat
batch and its parent carry the same ids), so the pair is the key, and a second
standing row for the same pair is refused out loud rather than merged.

A rejected row additionally refuses production and publication columns: it
has no continuation by definition, and a produced_at on it would mean the
ledger is describing a video that was never ordered.

--------------------------------------------------------------------------
Closures - CF-0776
--------------------------------------------------------------------------

A batch re-run from the Researcher (`batch_control rerun-from`) writes its
scripts again, and `assign` is idempotent per (batch, script): it hands back
the standing row of the run before. 16.10, 0839Z: two rows `demo` stood with a
writer's rejection *denied* under the rule before CF-0775, and the re-run got
`demo` again for topics with no base for it - the new rule never reached them,
and a filled `rejection_verdict` cannot be ruled again (empty -> filled only).

So a re-run closes the batch's standing rows that made no video, and the
closure is a record of its own, not a cell: `<channel>.closures.jsonl` beside
the ledger, one line per closed `seq` (`seq`, `closed_at`, `batch_id`,
`script_id`, `pattern_id`, `rhythm_id`, `by`, `task`, `why`, and whatever the
closer adds). Appended only, a `seq` closed once - the shortages record's form
(`shortage.py`) for the same reason: the CSV keeps what the rotation did, the
row is not rewritten. A closed row does not stand (`standing_rows`): it is not
counted in the distribution, `assign` draws the script again, and it takes no
production or publication cells. Only a standing row with no video produced or
published can be closed - the closure is about a script that is being written
again, not about a video that exists.
"""
import contextlib
import csv
import json
import datetime as _dt
import fcntl
import os
import re
import tempfile
from pathlib import Path

COLUMNS = (
    "seq",
    "assigned_at",
    "channel",
    "batch_id",
    "script_id",
    "pattern_id",
    "rhythm_id",
    "assigned_by",
    "rejection_reason",
    "rejection_verdict",
    "rejected_at",
    "produced_at",
    "pattern_delivered",
    "rhythm_delivered",
    "video_path",
    "published_at",
    "feed_position",
    "video_id",
)

ASSIGNMENT_COLUMNS = COLUMNS[:8]
REJECTION_COLUMNS = ("rejection_reason", "rejection_verdict", "rejected_at")
PRODUCTION_COLUMNS = ("produced_at", "pattern_delivered", "rhythm_delivered", "video_path")
PUBLICATION_COLUMNS = ("published_at", "feed_position", "video_id")

ASSIGNED_BY = ("rotation", "rotation-after-rejection")
VERDICTS = ("upheld", "denied")

# CF-0286: a rejection that is about the *rhythm* and not only about the pair.
#
# `contrast`/`alternate` was refused because the fact has no second side a
# viewer can tell apart; the rejection was upheld and the rotation handed back
# `explainer`/`alternate` - a different pattern carrying the same rhythm, which
# wants the same two sides. The script died at the Video Editor twice. So an
# upheld rejection may name the rhythm as what does not fit, and the
# replacement draw skips every pair carrying it.
#
# The exclusion is written into `rejection_reason` rather than into a column of
# its own, which is the decision CF-0139 already took for the planner's refusal
# (see the column list above): a column would be a schema migration plus a new
# branch in every counter, to separate two things that read apart in the text.
# It is a *prefix*, so it is the first thing a human reading the cell sees, and
# it is written by the guard - never by the agent, whose own words follow it
# unchanged and are what R2 measures. A denied rejection never carries it: a
# rejection that was not upheld excludes nothing.
RHYTHM_EXCLUSION = "[excluded rhythm: {rhythm}] "
_RHYTHM_EXCLUSION_RE = re.compile(r"^\[excluded rhythm: ([A-Za-z0-9][A-Za-z0-9_-]*)\] ")


def mark_rhythm_excluded(reason, rhythm):
    """The reason as it is stored for an upheld rhythm-class rejection."""
    if not rhythm:
        return reason
    if excluded_rhythm(reason):
        raise LedgerError(
            f"the reason already names an excluded rhythm ({excluded_rhythm(reason)!r}) - "
            f"the marker is the guard's to write, once")
    return RHYTHM_EXCLUSION.format(rhythm=rhythm) + reason


def excluded_rhythm(reason):
    """The rhythm an upheld rejection excluded, or None. Takes a row or a str."""
    if isinstance(reason, dict):
        # Only an upheld rejection excludes anything. A marker on a row that
        # was not upheld is read as no exclusion rather than trusted, because
        # the thing that makes the exclusion legitimate is the ruling.
        if reason.get("rejection_verdict") != "upheld" or not reason.get("rejected_at"):
            return None
        reason = reason.get("rejection_reason") or ""
    m = _RHYTHM_EXCLUSION_RE.match(reason or "")
    return m.group(1) if m else None


# CF-0775: the second marker the guard writes, after the rhythm one when both
# are there. An upheld rejection of a pattern the topic has no base footage for
# (`rotation/material.py`: `demo` with no own capture and no api_demo_record)
# is a missing-material ruling, not a statement about the pattern's design -
# so R4 (one refusal of a pair per window) does not count it against the next
# topic that is drawn the same pair with its base in hand. The marker is how a
# later ruling tells the two apart without re-reading another batch's files.
PATTERN_UNDELIVERABLE = "[undeliverable pattern: {pattern}] "
_PATTERN_UNDELIVERABLE_RE = re.compile(
    r"^\[undeliverable pattern: ([A-Za-z0-9][A-Za-z0-9_-]*)\] ")


def mark_pattern_undeliverable(reason, pattern):
    """The reason as stored for an upheld missing-material rejection (CF-0775).
    Goes after the rhythm marker when the reason carries one."""
    if not pattern:
        return reason
    head = _RHYTHM_EXCLUSION_RE.match(reason or "")
    head = head.group(0) if head else ""
    rest = (reason or "")[len(head):]
    if _PATTERN_UNDELIVERABLE_RE.match(rest):
        raise LedgerError("the reason already names an undeliverable pattern - the marker "
                          "is the guard's to write, once")
    return head + PATTERN_UNDELIVERABLE.format(pattern=pattern) + rest


def undeliverable_pattern(reason):
    """The pattern an upheld missing-material rejection named, or None.
    Takes a row (only an upheld one counts) or a str."""
    if isinstance(reason, dict):
        if reason.get("rejection_verdict") != "upheld" or not reason.get("rejected_at"):
            return None
        reason = reason.get("rejection_reason") or ""
    rest = _RHYTHM_EXCLUSION_RE.sub("", reason or "", count=1)
    m = _PATTERN_UNDELIVERABLE_RE.match(rest)
    return m.group(1) if m else None


def rejection_prose(reason):
    """The agent's own words, with the guard's markers taken off the front."""
    if isinstance(reason, dict):
        reason = reason.get("rejection_reason") or ""
    rest = _RHYTHM_EXCLUSION_RE.sub("", reason or "", count=1)
    return _PATTERN_UNDELIVERABLE_RE.sub("", rest, count=1)


def history_of_script(script_id, rows, batch_id=None):
    """The rows that are this script's own history, in file order (CF-0383).

    `script_id` is unique inside a batch and not across them: it is derived
    from the date and the topic's number in its batch, so two batches of one
    day, and a repeat batch that copies its parent's topics, carry the same
    ids for videos that are not the same video. So the key of an assignment is
    the pair (batch_id, script_id), and a script's history is its own batch's
    rows - plus the rows of every other batch the script *left*: one where it
    no longer stands at all. A topic refused for want of material leaves its
    batch with no standing row and comes back in a later one under the same
    id (CF-0139/CF-0149), and its refusal, its upheld rejections and their
    excluded rhythms travel with it. A batch where the id still stands is
    somebody else's video - rejected and replaced there or not - and is no
    part of this one's history. `batch_id=None` is the batch-blind reading
    every caller used before CF-0383, kept for callers that name no batch.
    """
    mine = [r for r in rows if r.get("script_id") == script_id]
    if batch_id is None:
        return mine
    still_there = {r.get("batch_id") for r in mine if not r.get("rejected_at")}
    return [r for r in mine
            if r.get("batch_id") == batch_id or r.get("batch_id") not in still_there]


def rhythms_excluded_for(script_id, rows, batch_id=None, skip_seqs=()):
    """Every rhythm an upheld rejection has excluded for this script, in order.

    Read back out of the ledger rather than held in memory, because the
    exclusion outlives the call that made it: a topic that comes back to
    `assign` after a refusal for want of material must not be handed the
    rhythm its own upheld rejection already took off the table. With a
    `batch_id`, only the script's own history counts (`history_of_script`).

    CF-0784: `skip_seqs` are rows that are not this script's history any more
    - `Ledger.closed_run_seqs()`, the rows a re-run left behind: the re-run
    writes the script again, so the closed run's exclusions are not its own.
    """
    skip = {str(s) for s in skip_seqs or ()}
    out = []
    for row in history_of_script(script_id, rows, batch_id):
        if str(row.get("seq")) in skip:
            continue
        rid = excluded_rhythm(row)
        if rid and rid not in out:
            out.append(rid)
    return out

DEFAULT_LEDGER_DIR = Path(__file__).resolve().parent / "ledger"


class LedgerError(Exception):
    """A write that would break the append-only invariant."""


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ledger_path(channel, directory=None):
    return Path(directory or DEFAULT_LEDGER_DIR) / f"{channel}.csv"


CLOSURES_SUFFIX = ".closures.jsonl"
CLOSURE_FIELDS = ("seq", "closed_at", "batch_id", "script_id", "pattern_id", "rhythm_id",
                  "by", "task", "why")


def closures_path(path):
    """`<channel>.closures.jsonl` beside the ledger `<channel>.csv` (CF-0776)."""
    path = Path(path)
    return path.with_name(path.stem + CLOSURES_SUFFIX)


RESYNCS_SUFFIX = ".resyncs.jsonl"


def resyncs_path(path):
    """`<channel>.resyncs.jsonl` beside the ledger `<channel>.csv` (CF-0866):
    every re-derived `feed_position`, old and new."""
    path = Path(path)
    return path.with_name(path.stem + RESYNCS_SUFFIX)


# CF-0416: one writer at a time. The ledger is shared by every run of a channel
# - a batch and a rebuild of an older batch reject, assign and fill production
# cells in the same file - and every write here is read-modify-write (`append`
# counts the rows for `seq`, `enrich` rewrites the whole file). Two operators
# writing at once could hand one `seq` to two rows or drop a row, and on
# 2026-09-27 the permission system refused a rebuild's `rotate.py reject` for
# exactly that reason ("a shared-resource write while another operator was
# active on the same ledger"); the operator then bent the plan instead. The
# answer is to make the write safe, not to route around it: an exclusive
# `flock` on `<ledger>.lock` beside the file, held for the whole ruling
# (rotate.py takes it around read-rule-write) and re-entered, not re-taken,
# by the append/enrich inside it. The lock file is never tracked
# (.gitignore) and carries nothing - the lock is the kernel's, released when
# the process ends however it ends.
LOCK_SUFFIX = ".lock"
_held = {}


def lock_path(path):
    return Path(str(path) + LOCK_SUFFIX)


@contextlib.contextmanager
def locked(path):
    """Hold the ledger at `path` for one writer. Re-entrant within a process."""
    key = str(Path(path).resolve())
    if _held.get(key):
        _held[key] += 1
        try:
            yield
        finally:
            _held[key] -= 1
        return
    lp = lock_path(path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    with lp.open("a") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        _held[key] = 1
        try:
            yield
        finally:
            _held.pop(key, None)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


class Ledger:
    """The assignment ledger of one channel."""

    def __init__(self, path):
        self.path = Path(path)

    # -- reading ----------------------------------------------------------

    def rows(self):
        """Every row, in file order, as dicts of strings."""
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is not None and tuple(reader.fieldnames) != COLUMNS:
                raise LedgerError(
                    f"{self.path}: header is {reader.fieldnames}, expected {list(COLUMNS)} - "
                    f"a ledger with different columns is a different ledger, not this one "
                    f"with a field added; migrate it deliberately")
            out = []
            for i, row in enumerate(reader, start=1):
                row = {c: (row.get(c) or "") for c in COLUMNS}
                if row["seq"] != str(i):
                    raise LedgerError(
                        f"{self.path}: row {i} carries seq {row['seq']!r} - seq is the axis "
                        f"the no-repeat window is counted on, so a gap or a reorder means "
                        f"the history is no longer the history")
                out.append(row)
            return out

    def closures(self):
        """The closure records (CF-0776), in file order; [] without the file."""
        path = closures_path(self.path)
        if not path.exists():
            return []
        out = []
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError as exc:
                raise LedgerError(f"{path}: line {i} is not JSON ({exc})") from exc
            if not isinstance(rec, dict) or not str(rec.get("seq", "")).isdigit():
                raise LedgerError(f"{path}: line {i} names no seq")
            out.append(rec)
        return out

    def closed_seqs(self):
        return {str(int(r["seq"])) for r in self.closures()}

    def closed_run_seqs(self, rows=None):
        """The seqs of the rows a re-run left behind (CF-0781): for each closed
        row, every row of its (batch, script) up to and including it - the
        closed run's assignment and the rejections that led to it. A re-run
        writes the script again from a new row, so the closed run's taste
        rulings are not this script's ruling (R3); the rows themselves stay in
        the CSV, and their refusals still count where the rotation is about
        pairs, not about this script (R4, the distribution)."""
        rows = self.rows() if rows is None else rows
        by_seq = {r["seq"]: r for r in rows}
        last = {}
        for rec in self.closures():
            seq = int(rec["seq"])
            row = by_seq.get(str(seq)) or {}
            key = (rec.get("batch_id") or row.get("batch_id"),
                   rec.get("script_id") or row.get("script_id"))
            last[key] = max(last.get(key, 0), seq)
        return {r["seq"] for r in rows
                if int(r["seq"]) <= last.get((r["batch_id"], r["script_id"]), 0)}

    def standing_rows(self, rows=None):
        """Assignments that still stand: everything that was not rejected and
        not closed (CF-0776).

        These are the rows the guard counts. A rejected assignment produced no
        video, so counting it would let a written rejection move the
        distribution - which is the loophole the guard exists to close. A
        closed one produced none either: its batch is writing the script again.
        """
        closed = self.closed_seqs()
        return [r for r in (self.rows() if rows is None else rows)
                if not r["rejected_at"] and r["seq"] not in closed]

    def standing_row_for(self, script_id, rows=None, batch_id=None):
        """The standing row of (batch_id, script_id), or None (CF-0383).

        The key is the pair: one script id may stand once in each batch that
        carries it (two batches of one day, a repeat batch and its parent).
        Without a `batch_id` the id alone has to be unambiguous - one that
        stands in two batches raises and names them, rather than handing back
        whichever row came first, which is how the ledger used to credit one
        batch's video to another without a word.
        """
        matches = [r for r in self.standing_rows(rows) if r["script_id"] == script_id
                   and (batch_id is None or r["batch_id"] == batch_id)]
        batches = sorted({r["batch_id"] for r in matches})
        if batch_id is None and len(batches) > 1:
            raise LedgerError(
                f"{self.path}: {script_id} stands in {len(batches)} batches "
                f"({', '.join(batches)}) - a script id is unique inside a batch, not across "
                f"them, so name the batch (CF-0383)")
        if len(matches) > 1:
            raise LedgerError(
                f"{self.path}: {script_id} has {len(matches)} standing assignments in batch "
                f"{batches[0]} - a script is written once per batch, so this means an "
                f"assignment was made without checking")
        return matches[0] if matches else None

    def row_by_seq(self, seq, rows=None):
        rows = self.rows() if rows is None else rows
        return rows[int(seq) - 1] if 0 < int(seq) <= len(rows) else None

    # -- writing ----------------------------------------------------------

    def append(self, **cells):
        """Append one assignment row. Returns the row as written."""
        unknown = set(cells) - set(COLUMNS)
        if unknown:
            raise LedgerError(f"unknown column(s) {sorted(unknown)}")
        for key in ("channel", "batch_id", "script_id", "pattern_id", "rhythm_id", "assigned_by"):
            if not cells.get(key):
                raise LedgerError(f"append: {key} is required")
        if cells["assigned_by"] not in ASSIGNED_BY:
            raise LedgerError(f"append: assigned_by must be one of {ASSIGNED_BY}")

        with locked(self.path):
            return self._append(cells)

    def _append(self, cells):
        rows = self.rows()
        existing = self.standing_row_for(cells["script_id"], rows, cells["batch_id"])
        if existing:
            raise LedgerError(
                f"{cells['batch_id']}/{cells['script_id']} already has a standing assignment "
                f"({existing['pattern_id']}/{existing['rhythm_id']}, seq {existing['seq']}) - "
                f"assigning again would count one script twice in the distribution; the "
                f"ledger refuses rather than merging the two (CF-0383)")

        row = {c: "" for c in COLUMNS}
        row.update({k: str(v) for k, v in cells.items()})
        row["seq"] = str(len(rows) + 1)
        row["assigned_at"] = row["assigned_at"] or utc_now()

        new_file = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            if new_file:
                writer.writeheader()
            writer.writerow(row)
        return row

    def enrich(self, at_seq, **cells):
        """Fill blank cells of an existing row. Returns the updated row.

        Only blank -> value. An attempt to change a cell that already carries
        a value is the error, not a silent overwrite: the ledger's job is to
        be the history, and a history that can be edited is an opinion.
        """
        unknown = set(cells) - set(COLUMNS)
        if unknown:
            raise LedgerError(f"unknown column(s) {sorted(unknown)}")
        if set(cells) & set(ASSIGNMENT_COLUMNS):
            raise LedgerError(
                f"columns {sorted(set(cells) & set(ASSIGNMENT_COLUMNS))} are written by the "
                f"rotation at assignment time and are not enrichable - what was assigned is "
                f"the fact the guard counts")

        with locked(self.path):
            return self._enrich(at_seq, cells)

    def close(self, at_seq, by, task, why, at=None, **extra):
        """Close a standing row with no video (CF-0776): one line in
        `<channel>.closures.jsonl`, the CSV untouched. Returns the record."""
        for key, value in (("by", by), ("task", task), ("why", why)):
            if not value or not str(value).strip():
                raise LedgerError(f"close: {key} is required")
        with locked(self.path):
            return self._close(at_seq, by, task, why, at, extra)

    def _close(self, at_seq, by, task, why, at, extra):
        rows = self.rows()
        row = self.row_by_seq(at_seq, rows)
        if row is None:
            raise LedgerError(f"{self.path}: no row with seq {at_seq}")
        if row["seq"] in self.closed_seqs():
            raise LedgerError(f"seq {at_seq} is already closed - a closure is written once")
        if row["rejected_at"]:
            raise LedgerError(f"seq {at_seq} is a rejected assignment - it already stands for "
                              f"nothing, there is nothing to close")
        made = [c for c in PRODUCTION_COLUMNS + PUBLICATION_COLUMNS if row[c]]
        if made:
            raise LedgerError(f"seq {at_seq} carries {made} - a video was made from it, and a "
                              f"closure is for a script written again, not a video")
        rec = {"seq": int(row["seq"]), "closed_at": at or utc_now(),
               "batch_id": row["batch_id"], "script_id": row["script_id"],
               "pattern_id": row["pattern_id"], "rhythm_id": row["rhythm_id"],
               "by": str(by), "task": str(task), "why": str(why)}
        rec.update({k: v for k, v in extra.items() if k not in rec})
        path = closures_path(self.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec

    def _enrich(self, at_seq, cells):
        rows = self.rows()
        row = self.row_by_seq(at_seq, rows)
        if row is None:
            raise LedgerError(f"{self.path}: no row with seq {at_seq}")
        if row["seq"] in self.closed_seqs() and \
                set(cells) & (set(PRODUCTION_COLUMNS) | set(PUBLICATION_COLUMNS)):
            raise LedgerError(
                f"seq {at_seq} was closed (CF-0776) - its script is written again under "
                f"another row, so this one cannot be produced or published")

        if row["rejected_at"] and set(cells) & (set(PRODUCTION_COLUMNS) | set(PUBLICATION_COLUMNS)):
            raise LedgerError(
                f"seq {at_seq} is a rejected assignment and has no continuation - it never "
                f"became a video, so it cannot be produced or published")

        for key, value in cells.items():
            value = "" if value is None else str(value)
            if not value:
                continue
            if row[key] and row[key] != value:
                raise LedgerError(
                    f"seq {at_seq}: {key} is already {row[key]!r}; refusing to change it to "
                    f"{value!r} - the ledger is append-only at cell granularity too")
            row[key] = value

        self._write(rows)
        return row

    def resync(self, at_seq, feed_position, by, task, why, at=None):
        """Re-derive the `feed_position` of a published row (CF-0866). Returns
        the journal record.

        `feed_position` is not an observation but a rank in the channel's
        upload journal: a video written into the journal before it (a backfill,
        a late id, a move between days) shifts every later rank by one. The
        cell is the one ledger cell that may change after it is filled - only
        this one, only on a row whose `published_at` and `video_id` already
        stand, and every change is a line in `<channel>.resyncs.jsonl` beside
        the CSV (`seq`, `at`, `column`, `old`, `new`, `by`, `task`, `why`).
        """
        for key, value in (("by", by), ("task", task), ("why", why)):
            if not value or not str(value).strip():
                raise LedgerError(f"resync: {key} is required")
        value = str(feed_position).strip()
        if not value.isdigit() or int(value) < 1:
            raise LedgerError(f"resync: feed_position must be a positive integer, got {value!r}")
        with locked(self.path):
            rows = self.rows()
            row = self.row_by_seq(at_seq, rows)
            if row is None:
                raise LedgerError(f"{self.path}: no row with seq {at_seq}")
            if not (row["published_at"] and row["video_id"] and row["feed_position"]):
                raise LedgerError(f"resync: seq {at_seq} is not a published row - an empty "
                                  f"cell is filled by enrich, not re-derived")
            old = row["feed_position"]
            if old == value:
                return None
            row["feed_position"] = value
            rec = {"seq": int(row["seq"]), "at": at or utc_now(), "column": "feed_position",
                   "old": old, "new": value, "batch_id": row["batch_id"],
                   "script_id": row["script_id"], "video_id": row["video_id"],
                   "by": str(by), "task": str(task), "why": str(why)}
            self._write(rows)
            path = resyncs_path(self.path)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return rec

    def _write(self, rows):
        # Written beside and moved into place: a reader never sees half a file.
        fd, tmp = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            os.chmod(tmp, 0o644)
            os.replace(tmp, self.path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


def validate(path):
    """Structural check of a ledger on disk. Returns a list of errors."""
    errs = []
    ledger = Ledger(path)
    try:
        rows = ledger.rows()
        closures = ledger.closures()
    except LedgerError as exc:
        return [str(exc)]

    closed = set()
    for rec in closures:                                        # CF-0776
        seq = str(int(rec["seq"]))
        ctx = f"closure of seq {seq}"
        row = ledger.row_by_seq(seq, rows)
        if seq in closed:
            errs.append(f"{ctx}: closed twice")
        closed.add(seq)
        if row is None:
            errs.append(f"{ctx}: no such row in the ledger")
            continue
        for key in ("batch_id", "script_id"):
            if rec.get(key) != row[key]:
                errs.append(f"{ctx}: record names {key} {rec.get(key)!r}, the row {row[key]!r}")
        for key in ("closed_at", "by", "task", "why"):
            if not rec.get(key):
                errs.append(f"{ctx}: {key} is empty")
        if row["rejected_at"]:
            errs.append(f"{ctx}: the row is a rejected assignment - nothing stood to close")
        made = [c for c in PRODUCTION_COLUMNS + PUBLICATION_COLUMNS if row[c]]
        if made:
            errs.append(f"{ctx}: the closed row carries {made} - a closed row has no video")

    seen_standing = {}
    for row in rows:
        ctx = f"seq {row['seq']}"
        for key in ("channel", "batch_id", "script_id", "pattern_id", "rhythm_id", "assigned_by"):
            if not row[key]:
                errs.append(f"{ctx}: {key} is empty")
        if row["assigned_by"] and row["assigned_by"] not in ASSIGNED_BY:
            errs.append(f"{ctx}: assigned_by {row['assigned_by']!r} not in {ASSIGNED_BY}")
        if row["rejection_verdict"] and row["rejection_verdict"] not in VERDICTS:
            errs.append(f"{ctx}: rejection_verdict {row['rejection_verdict']!r} not in {VERDICTS}")
        if row["rejection_verdict"] and not row["rejection_reason"]:
            errs.append(f"{ctx}: a rejection was ruled on but carries no written reason")
        if _RHYTHM_EXCLUSION_RE.match(row["rejection_reason"] or "") and not excluded_rhythm(row):
            errs.append(f"{ctx}: the reason carries a rhythm exclusion but the rejection is "
                        f"{row['rejection_verdict'] or 'unruled'!r} - only an upheld rejection "
                        f"excludes a rhythm (CF-0286)")
        if excluded_rhythm(row) and not rejection_prose(row).strip():
            errs.append(f"{ctx}: the reason is the exclusion marker and nothing else - the "
                        f"marker is the guard's, the reason is the agent's")
        if row["rejected_at"] and row["rejection_verdict"] != "upheld":
            errs.append(f"{ctx}: rejected_at is set but the verdict is "
                        f"{row['rejection_verdict']!r} - only an upheld rejection ends a row")
        if row["rejection_verdict"] == "upheld" and not row["rejected_at"]:
            errs.append(f"{ctx}: rejection upheld but rejected_at is empty")
        if row["rejected_at"]:
            filled = [c for c in PRODUCTION_COLUMNS + PUBLICATION_COLUMNS if row[c]]
            if filled:
                errs.append(f"{ctx}: rejected assignment carries {filled} - a rejected "
                            f"assignment has no continuation")
        elif row["seq"] not in closed:
            key = (row["channel"], row["batch_id"], row["script_id"])
            if key in seen_standing:
                errs.append(f"{ctx}: {row['batch_id']}/{row['script_id']} already stands at "
                            f"seq {seen_standing[key]} - one script of a batch, one standing "
                            f"assignment")
            seen_standing[key] = row["seq"]
        if row["published_at"] and not row["produced_at"]:
            errs.append(f"{ctx}: published before it was produced")
    return errs
