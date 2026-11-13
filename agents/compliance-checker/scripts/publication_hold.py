#!/usr/bin/env python3
"""CF-0318: a `review` verdict holds the **publication**, not the production.

The decision (user, grill of 2026-09-22, Q8): *without a human's approval only
the publication of a video to the channel is forbidden - the thing Publisher
will do. The video itself must be made without a human.*

What this reverses, and what it keeps
-------------------------------------
`CF-0232` settled that nobody looks at a `review` topic, and made the loss a
**recorded refusal** instead of a silent drop. That half stands and is not
softened here: the verdict is still written in full, still carries both checks,
still reaches the funnel. What CF-0232 got wrong was *where* the refusal lands.
It took the topic off the batch at the indexer
(`agents/footage-indexer/scripts/ingest_batch.py`, `COMPLIANCE_SKIP_CODE`,
"compliance verdict is 'review' - not signed off"), so a topic nobody was
waiting on died before a frame of it existed. The instrumented funnel put a
number on that: **`compliance_review` cost 19 topics of 101 across ten runs**,
second only to `no_production_fact` (29).

The verdict does not get milder. `review` stays `review`, the rights reading
that earned it stays word for word, and the video that comes out of a `review`
topic is **not publishable**. It simply stops killing the topic at the moment
the batch could still have made something out of it. The cost of being wrong
moved from "a video that was never made" to "a video that sits unpublished
until the user says yes", and only the second one is recoverable.

Where the mark lives, and why not in the batch
----------------------------------------------
Two places, and they are not a duplicate - they answer two different readers.

* **In the batch artifact**, on the `review` row itself: a `publication_hold`
  block (`mark_document`). This makes `02-compliance-checker.json`
  self-describing - whoever opens the batch sees, on the row, that the topic
  went on and that its video may not be published.
* **In `publish/publication-holds.json` at the factory root** - the ledger,
  and the authority. `scripts/archive_old_batches.sh` **moves** a batch
  directory to Archive after 31 days (`mv`, not `cp` - the user's decision
  of 2026-09-02, see CF-0056), so a mark that lives only under `pipeline/`
  leaves the disk a month after the video was made. Publisher does not exist
  yet - it is milestone 2.0, months out - so by construction the reader of
  this mark arrives **after** the batch is gone. A mark in the batch alone
  would therefore be a mark that is never read once.

`publish/` is where a video goes when it is accepted for upload
(`publish/README.md`), which makes it the one directory whose whole subject is
publication and which the archive job never touches. `CF-0017` (Publisher
prepares metadata) and `CF-0018` (upload on an explicit yes) read the ledger
from here; `docs/publisher-metadata-rules.md` names it.

The signature
-------------
`signature` is the only field a human decides, and no automatic path in this
file ever writes one - the same rule, deliberately the same shape, as
`shared/gate-prices.json` (CF-0320): a signature written by the code that needs
it is not a signature. It is `{"user", "date", "note"}`. Until it is there the
hold stands and Publisher must not upload.

One narrow exception, CF-0687 (the user's permission in chat, 2026-10-11):
**`sign_hold` is the only code that writes a signature**, and it is called on
an explicit human action - the command center calls it after the user watched
the video in the center and pressed the button, with the user's name and a
note that may not be empty. It writes `{"user", "date", "note", "via"}`,
`via: "center"` by default, so the ledger says the signature came through the
center and not from a hand-edited file. `check_sign` is the same validation
with nothing written. The pass, `merge`, `resolve_rights_only` and every other
path still never write one; the guard test checks that `sign_hold`'s body is
the only place in this file that assigns a signature other than `None`.

What can be signed: a standing **content-sensitivity hold** - an unresolved,
unsigned row whose verdict is in `HOLD_VERDICTS` and that is not rights-only
(`holds(row)`; since CF-0420 every hold that is not rights-only is the
content-sensitivity check's, whatever its notes say). A rights-only row is
`not_signable`: it is not a hold anyone owes a look - it is resolved by
`--resolve-rights-only` with the advisory-only rule as the reason.

A hold is never deleted by this script either. When a verdict stops being
`review` - a rights-only `review` is lowered to `clear` - the row is **resolved**, with `resolved_at` and the
reason, and it stays in the ledger. A hold that vanishes is a hold nobody can
audit.

The rights-holder match holds nothing (CF-0420)
-----------------------------------------------
The channel's rights-holder list is advisory: a hold is earned by the
content-sensitivity check, never by a rights match. A `review` row that only
the rights match can have raised (`rights_only`) is not held here even if
step 4b was skipped, and `--resolve-rights-only` resolves the rows the ledger
already carries on that basis alone - in place, with the rule as the reason,
never deleted.

Which name of the channel the ledger stores
-------------------------------------------
The **current** one: the channel is resolved at the door, before a `hold_id` is
built, and never the string the batch happened to carry. A channel can be
renamed (CF-0180, CF-0197) and a batch frozen before the rename keeps the old
id in its `channel` field forever - it is a dated record and is not rewritten.
If the ledger stored that field verbatim it would hold two keys for one
channel, and `is_held` would answer `False` for a video that is held, purely
because Publisher asked under the other name. That is the one failure this
ledger may not have.

Storing the resolved name is not enough on its own, because *this* file is the
durable one: the batch is on Archive in a month, and a rename that happens
after a row was written turns that row's stored id into a former id in place.
So the comparison resolves **both sides** - the key asked for and the key
rebuilt from the stored row (`_row_key`) - and the ledger is never rewritten to
chase a rename. `is_held`, `merge` and `open_holds` all go through it, which is
what makes the lookup answer the same under every name the channel has had.

Fail closed
-----------
A ledger that cannot be parsed makes `is_held` answer `True` for everything,
with a reason saying why. A *missing* ledger is not that: no file means no hold
was ever written, which is the state of every batch before this task and is not
an error. The distinction is the one this project already draws between an
absent key and an empty one.
"""
import copy
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _channel_ids import factory_root, resolve_channel  # noqa: E402
from _runlog import runlog  # noqa: E402
from _cli import screen  # noqa: E402
from rights_holder_info import rights_only  # noqa: E402

# The ledger, relative to the factory root. Outside `pipeline/` on purpose:
# see "Where the mark lives" above.
LEDGER_REL = Path("publish") / "publication-holds.json"

# The verdicts that hold the publication. One today. Spelled as a tuple so the
# next one (if a verdict is ever added) is a data change, not a rewrite.
HOLD_VERDICTS = ("review",)

# The verdicts that need no signature to be published. The pair the funnel and
# the Content Researcher read as "passing" - here it means exactly one thing,
# publishable, and no longer doubles as "goes into production"
# (`cut_shortlist.PRODUCTION_VERDICTS` is that).
PUBLISH_VERDICTS = ("clear", "caution")

# The code the hold carries. Deliberately not `compliance_review`: that one is
# the funnel's code for a topic the gate *lost*, and this topic is not lost.
REASON_CODE = "compliance_review_hold"

# The block stamped on the row inside the batch artifact.
MARK_KEY = "publication_hold"
LEDGER_KEY = "holds"
TASK = "CF-0318"

# CF-0420: the reason written on a ledger row resolved because its only basis
# was the rights-holder match, which is advisory and holds nothing.
RIGHTS_ONLY_TASK = "CF-0420"
RIGHTS_ONLY_REASON = ("the rights-holder match is advisory only and holds "
                      "nothing (CF-0420)")

BLOCKS = "publication"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ledger_path(root=None):
    """The ledger's absolute path. `root` overrides the factory root (tests,
    and a checkout somewhere else); otherwise `_channel_ids.factory_root()`
    finds it the way every script in this repo finds it."""
    base = Path(root).expanduser() if root else factory_root()
    return base / LEDGER_REL


# Which file of the batch the verdict was written in. The Trend Hunter pass
# writes `02`, the Content Researcher pass writes `04` - the same two names
# `shared/runlog/funnel.py` reads as the two compliance stages. Recorded on the
# hold because the ledger is read after the batch directory has been archived,
# and "which pass judged it" is then unanswerable from anywhere else.
STAGE_ARTIFACTS = {"01-trend-hunter": "02-compliance-checker.json"}
DEFAULT_ARTIFACT = "04-compliance-checker.json"


def artifact_name(stage_checked):
    return STAGE_ARTIFACTS.get(stage_checked or "", DEFAULT_ARTIFACT)


def hold_id(channel, batch_id, topic_id):
    """The key of a hold: the three things that identify one video before a
    video exists. Stable across a re-run of the pass, and readable by a human
    with no other file open."""
    return f"{channel}/{batch_id}/{topic_id}"


def _row_key(row, root=None):
    """A stored row's `hold_id` as it reads *today*.

    Rows are written with the channel already resolved, so for every row this
    returns what is stored. It earns its keep on the one that is not: a rename
    that happens after a row was written (CF-0180 did one) turns that row's id
    into a former one, and this ledger is deliberately never rewritten to chase
    it - it is the durable record, read after the batch is gone. Rebuilding the
    key from the row's own fields is what lets the lookup answer the same under
    either name. A row too old or too damaged to carry the three fields falls
    back to the id it was stored under.
    """
    channel = resolve_channel(row.get("channel") or "", root=root)
    batch_id, topic_id = row.get("batch_id"), row.get("topic_id")
    if channel and batch_id and topic_id:
        return hold_id(channel, batch_id, topic_id)
    return row.get("hold_id")


# --------------------------------------------------------------------------
# the mark
# --------------------------------------------------------------------------
def hold_reason(row, channel, batch_id, stage_checked):
    """The sentence a reader of the ledger gets in a month with nothing else
    open - the batch directory included, since by then it is on Archive."""
    sensitivity = row.get("content_sensitivity_check") or {}
    # CF-0420: the rights-holder match is never a basis of a hold, so it is not
    # named as one; it is still copied onto the ledger row for information.
    earned = ("content-sensitivity flag" if sensitivity.get("flagged")
              else "the checks recorded on this row")
    return (
        f"Compliance verdict {row.get('verdict')!r} on {earned}. The video may be "
        f"MADE but must NOT be PUBLISHED until the user signs this row "
        f"(`signature`). This is not a refusal of the topic: since {TASK} "
        f"(user's decision, grill of 2026-09-22) a `review` blocks publication "
        f"only - it used to take the topic off the batch at the indexer, which "
        f"cost 19 topics of 101 across ten instrumented runs. The verdict itself "
        f"is unchanged and is not milder: read `content_sensitivity_check` on "
        f"this row, copied verbatim from pipeline/{channel}/{batch_id}/"
        f"{artifact_name(stage_checked)} - it is the whole basis. "
        f"`rights_holder_check` is copied beside it for information only: since "
        f"{RIGHTS_ONLY_TASK} a rights-holder match holds nothing. "
        f"Publisher (CF-0017/CF-0018) must treat an unsigned hold as a hard stop."
    )


def holds(row):
    """Whether this verdict row holds the publication: a `review`, and not one
    only the rights-holder match can have raised (CF-0420)."""
    return (row.get("verdict") or "") in HOLD_VERDICTS and not rights_only(row)


def mark(row, channel, batch_id, stage_checked):
    """The `publication_hold` block as it is stamped on the row and stored in
    the ledger - one shape, so that the batch and the ledger cannot drift."""
    return {
        "task": TASK,
        "hold_id": hold_id(channel, batch_id, row.get("topic_id")),
        "blocks": BLOCKS,
        "blocks_production": False,
        "reason_code": REASON_CODE,
        "ledger": str(LEDGER_REL),
        "reason": hold_reason(row, channel, batch_id, stage_checked),
    }


def _rows(doc):
    """Every judged row of the artifact, `results[]` then `reserve[]`, with the
    list it came from.

    `reserve[]` is included on purpose. A reserve topic is not made today, but
    CF-0306's substitution pulls one into the batch when a topic is lost after
    compliance, and `02` is not rewritten when that happens - so a `review`
    sitting in `reserve[]` can become a video without this script ever running
    again. A hold on a video that is never made costs nothing; a video made
    with no hold is the wrong publication this task exists to prevent.
    """
    for key in ("results", "reserve"):
        value = doc.get(key)
        if isinstance(value, list):
            for row in value:
                if isinstance(row, dict) and row.get("topic_id"):
                    yield key, row


def mark_document(doc, channel=None, batch_id=None):
    """`(doc, held_ids, resolved_ids)` - the artifact with `publication_hold`
    stamped on every held row and taken off every row that no longer holds.

    Idempotent: the block is derived from the verdict alone, so a second run
    over the same verdicts writes the same block, and a run after the blooper
    relaxation lowered a `review` to `caution` takes the stale block off (the
    ledger row is resolved rather than deleted - see `merge`).
    """
    out = copy.deepcopy(doc)
    # CF-0197: resolved here and not at the lookup. The block carries a
    # `hold_id`, `mark()` is the single shape the batch row and the ledger row
    # are both built from, and a batch frozen before the rename would otherwise
    # stamp one id on the row and another in the ledger.
    channel = resolve_channel(channel or out.get("channel") or "")
    batch_id = batch_id or out.get("batch_id") or ""
    stage = out.get("stage_checked")
    held, resolved = [], []
    for _, row in _rows(out):
        if holds(row):
            row[MARK_KEY] = mark(row, channel, batch_id, stage)
            held.append(row["topic_id"])
        elif MARK_KEY in row:
            row.pop(MARK_KEY)
            resolved.append(row["topic_id"])
    return out, held, resolved


def hold_rows(doc, channel=None, batch_id=None):
    """The ledger rows this artifact earns - one per held topic, carrying the
    whole verdict record. The record travels with the hold because the batch
    directory will not be there when the hold is read."""
    channel = resolve_channel(channel or doc.get("channel") or "")
    batch_id = batch_id or doc.get("batch_id") or ""
    stage = doc.get("stage_checked")
    rows = []
    for where, row in _rows(doc):
        if not holds(row):
            continue
        block = mark(row, channel, batch_id, stage)
        rows.append({
            "hold_id": block["hold_id"],
            "channel": channel,
            "batch_id": batch_id,
            "topic_id": row["topic_id"],
            # The Content Researcher pass writes one row per script and carries
            # `topic_id` beside it. The hold is keyed on the topic, because a
            # hold is on the video and the video is the topic; `script_id` is
            # recorded so the row still names the thing that was judged.
            "script_id": row.get("script_id"),
            "verdict": row.get("verdict"),
            "stage_checked": stage,
            "found_in": where,
            "raised_by": "compliance-checker",
            "raised_at": _now(),
            "task": TASK,
            "blocks": BLOCKS,
            "blocks_production": False,
            "reason_code": REASON_CODE,
            "reason": block["reason"],
            "rights_holder_check": row.get("rights_holder_check"),
            "content_sensitivity_check": row.get("content_sensitivity_check"),
            "batch_artifact": (f"pipeline/{channel}/{batch_id}/"
                               f"{artifact_name(stage)}"),
            "resolved_at": None,
            "resolved_reason": None,
            "signature": None,
        })
    return rows


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------
LEDGER_NOTE = (
    f"{TASK}. A `review` compliance verdict blocks the PUBLICATION of the video, "
    f"not its production (user's decision, grill of 2026-09-22). Every row here is "
    f"a video that may be made and may NOT be uploaded until a human signs it. "
    f"`signature` is the only field a human decides and no automatic path in "
    f"agents/compliance-checker/scripts/publication_hold.py ever writes one - it is "
    f'{{"user", "date", "note"}}, the same rule as shared/gate-prices.json (CF-0320). '
    f"The one writer is sign_hold (CF-0687): the command center calls it after the "
    f"user watched the video there and pressed the button, with a note, and it "
    f'records "via": "center". '
    f"A row is never deleted: when the verdict stops being `review` the row is "
    f"resolved in place, with `resolved_at` and the reason. This file lives outside "
    f"pipeline/ because scripts/archive_old_batches.sh MOVES a batch to Archive "
    f"after 31 days, and Publisher (CF-0017/CF-0018, milestone 2.0) arrives long "
    f"after that."
)


def empty_ledger():
    return {"note": LEDGER_NOTE, "task": TASK, LEDGER_KEY: []}


def read_ledger(root=None, path=None):
    """`(ledger, problem)`. A missing file is an empty ledger and no problem -
    nothing was ever held. A file that will not parse is a problem, and the
    caller fails closed on it; the ledger returned is empty so a caller that
    ignores the problem cannot silently clear a hold."""
    path = Path(path) if path else ledger_path(root)
    if not path.exists():
        return empty_ledger(), None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        return empty_ledger(), f"{path} could not be read ({exc})"
    if not isinstance(data, dict) or not isinstance(data.get(LEDGER_KEY), list):
        return empty_ledger(), f"{path} carries no `{LEDGER_KEY}` list"
    return data, None


# Fields the pass owns: a re-run rewrites them from the verdicts. Everything
# else on a stored row - `signature`, `raised_at`, `resolved_at` - belongs to
# whoever wrote it first, and the pass does not get to overwrite it.
PASS_OWNED = ("channel", "batch_id", "topic_id", "script_id", "verdict",
              "stage_checked", "found_in", "raised_by", "task", "blocks",
              "blocks_production", "reason_code", "reason",
              "rights_holder_check", "content_sensitivity_check",
              "batch_artifact")


def merge(ledger, rows, resolved_ids=(), channel=None, batch_id=None, stage=None):
    """`(ledger, added, refreshed, resolved)` - the rows folded into the ledger
    by `hold_id`.

    * A new `hold_id` is appended, unsigned.
    * A known `hold_id` has its pass-owned fields refreshed and keeps its
      `raised_at` and its `signature`. Re-running the pass must never un-sign a
      row a human signed, and must never re-date a hold that has been standing
      for a month.
    * A row whose topic no longer holds (`resolved_ids`) is marked resolved in
      place - never removed - **and only if the same pass raised it**. The two
      passes judge different things: `02` judges the topic, `04` judges the
      written script. A `clear` at `04` is not a re-reading of the high-risk
      rights match that held the topic at `02`, so it does not get to lift it.
      Only the pass that raised a hold may resolve it.

    Both sides of that `hold_id` are looked up through the current channel id
    (`_row_key`), so a pass run after a rename refreshes the row it already
    wrote instead of appending a second one beside it.
    """
    out = copy.deepcopy(ledger)
    out.setdefault("note", LEDGER_NOTE)
    out["note"] = LEDGER_NOTE
    out.setdefault("task", TASK)
    stored = {_row_key(r): r for r in out[LEDGER_KEY]
              if isinstance(r, dict) and r.get("hold_id")}
    added, refreshed = [], []
    for row in rows:
        known = stored.get(row["hold_id"])
        if known is None:
            out[LEDGER_KEY].append(row)
            stored[row["hold_id"]] = row
            added.append(row["hold_id"])
            continue
        for field in PASS_OWNED:
            known[field] = row[field]
        known["resolved_at"] = None
        known["resolved_reason"] = None
        known.setdefault("signature", None)
        known.setdefault("raised_at", row["raised_at"])
        refreshed.append(row["hold_id"])

    resolved = []
    for tid in resolved_ids:
        known = stored.get(hold_id(resolve_channel(channel or ""), batch_id, tid))
        if known is None or known.get("resolved_at"):
            continue
        if stage is not None and known.get("stage_checked") != stage:
            continue
        known["resolved_at"] = _now()
        known["resolved_reason"] = (
            f"the verdict on this topic is no longer one of {list(HOLD_VERDICTS)} "
            f"- re-read {known.get('batch_artifact')}. The row stays here because a "
            f"hold that disappears is a hold nobody can audit.")
        resolved.append(known["hold_id"])
    return out, added, refreshed, resolved


def _ledger_bytes(ledger):
    return (json.dumps(ledger, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_ledger(ledger, root=None, path=None):
    """Write the ledger atomically (CF-0687): a temp file beside it, then
    `os.replace`, so a reader - Publisher, the command center fingerprinting
    the file - never sees half of it."""
    path = Path(path) if path else ledger_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(_ledger_bytes(ledger))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def resolve_rights_only(ledger, when=None):
    """`(ledger, resolved_ids)` - every standing hold (unresolved, unsigned)
    whose only basis is the rights-holder match resolved in place, CF-0420.

    The row stays, with `resolved_at` (`when`, default now) and the user's
    decision as `resolved_reason`. A row with a content-sensitivity flag is
    left standing: that restriction is unchanged. A signed row is left alone -
    it no longer holds anything, and its signature is the human's record.
    Idempotent: a resolved row is never re-dated."""
    out = copy.deepcopy(ledger)
    resolved = []
    for row in out.get(LEDGER_KEY) or []:
        if not isinstance(row, dict) or row.get("resolved_at"):
            continue
        signature = row.get("signature")
        if isinstance(signature, dict) and signature.get("user"):
            continue
        if not rights_only(row):
            continue
        row["resolved_at"] = when or _now()
        row["resolved_reason"] = RIGHTS_ONLY_REASON
        resolved.append(row.get("hold_id"))
    return out, resolved


# --------------------------------------------------------------------------
# the reader Publisher uses
# --------------------------------------------------------------------------
def is_held(channel, batch_id, topic_id, root=None, path=None):
    """`(held, reason)` - **the function CF-0017/CF-0018 call before upload.**

    `True` means: do not publish this video without a signature. It is `True`
    for an unsigned, unresolved hold, and `True` for a ledger that exists and
    will not parse (fail closed: an unreadable ledger is not an empty one). It
    is `False` when no ledger was ever written, when the topic has no row, when
    the row was resolved, and when a human signed it.
    """
    ledger, problem = read_ledger(root=root, path=path)
    if problem:
        return True, (f"held: the publication-hold ledger cannot be read, so no "
                      f"video can be cleared from it ({problem}). {TASK}.")
    wanted = hold_id(resolve_channel(channel, root=root), batch_id, topic_id)
    for row in ledger[LEDGER_KEY]:
        if not isinstance(row, dict) or _row_key(row, root=root) != wanted:
            continue
        if row.get("resolved_at"):
            return False, (f"not held: the hold on {wanted} was resolved at "
                           f"{row['resolved_at']} - {row.get('resolved_reason')}")
        signature = row.get("signature")
        if isinstance(signature, dict) and signature.get("user"):
            via = (f" via {signature['via']}" if signature.get("via") else "")
            return False, (f"not held: signed by {signature.get('user')} on "
                           f"{signature.get('date')}{via} - {signature.get('note')}")
        return True, row.get("reason") or f"held: {wanted} carries an unsigned hold"
    return False, f"not held: no publication hold recorded for {wanted}"


def open_holds(root=None, path=None, channel=None):
    """Every hold still standing - unresolved and unsigned. The list the user
    is shown when they are asked to sign."""
    ledger, problem = read_ledger(root=root, path=path)
    if problem:
        return [], problem
    out = []
    for row in ledger[LEDGER_KEY]:
        if not isinstance(row, dict) or row.get("resolved_at"):
            continue
        signature = row.get("signature")
        if isinstance(signature, dict) and signature.get("user"):
            continue
        if channel and resolve_channel(row.get("channel") or "", root=root) != \
                resolve_channel(channel, root=root):
            continue
        out.append(row)
    return out, None


# --------------------------------------------------------------------------
# the signature, written on a human's action (CF-0687)
# --------------------------------------------------------------------------
# code -> the Russian line of a refusal; the command center shows it as is.
# The English text - str(e) - is for logs and tests. Same shape as
# `shared/operator_requests.py` `RequestError` / `REFUSALS_RU` (CF-0684).
SIGN_REFUSALS_RU = {
    "no_such_hold": "Холда {hold_id} нет в журнале холдов публикации.",
    "already_signed": "Холд {hold_id} уже подписан ({user}, {date}) - вторая "
                      "подпись не пишется.",
    "already_resolved": "Холд {hold_id} уже снят ({why}) - подписывать нечего.",
    "not_signable": "Холд {hold_id} не подписывается: он держится только на "
                    "совпадении с правообладателем, а это ограничение снято "
                    "28.09 (CF-0420). Такой холд снимается без подписи "
                    "(--resolve-rights-only).",
    "empty_user": "Не сказано, кто подписывает.",
    "empty_note": "Подпись без заметки не пишется - напишите, почему видео "
                  "можно публиковать.",
    "ledger_unreadable": "Журнал холдов не читается ({why}) - подпись в него "
                         "не пишется.",
}

SIGN_TASK = "CF-0687"
SIGN_VIA_DEFAULT = "center"


class HoldSignError(Exception):
    """A signature that may not be written.

    Carries a stable `code` and `text_ru` (SIGN_REFUSALS_RU, filled with the
    values the raise passes); a code with no row is a KeyError at the raise."""

    def __init__(self, text, *, code, **values):
        super().__init__(text)
        self.code = code
        self.values = values
        self.text_ru = SIGN_REFUSALS_RU[code].format_map(values)

    def as_dict(self):
        """{code, text_ru, text} - the refusal as the center reads it."""
        return {"code": self.code, "text_ru": self.text_ru, "text": str(self)}


def _sign_target(ledger_or_root):
    """`(ledger_file, root)` for `check_sign` / `sign_hold`.

    A path whose name ends in `.json` is the ledger file itself; anything else
    (a directory, or None for the live factory root) is a factory root and the
    ledger is `ledger_path(root)`. The root of a ledger file is recovered only
    when the file sits at its canonical place (`<root>/publish/
    publication-holds.json`) - it is what channel renames are resolved against;
    otherwise `_channel_ids` finds the factory root itself."""
    if ledger_or_root is None:
        return ledger_path(None), None
    p = Path(ledger_or_root).expanduser()
    if p.suffix == ".json":
        canonical = (p.name == LEDGER_REL.name
                     and p.parent.name == LEDGER_REL.parent.name)
        return p, (p.parent.parent if canonical else None)
    return ledger_path(p), p


def _fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def _signable(ledger_or_root, wanted_id):
    """`(ledger, row, path, fingerprint)` - the row `wanted_id` names, read from
    the bytes the fingerprint is taken of, or HoldSignError. Writes nothing.

    The order of the refusals: no row, signed, resolved, rights-only, and a row
    whose verdict no longer holds anything (resolved in all but the stamp)."""
    path, root = _sign_target(ledger_or_root)
    wanted_id = str(wanted_id or "")
    if not path.exists():
        raise HoldSignError(f"no publication-hold ledger at {path}, so no hold "
                            f"{wanted_id!r}", code="no_such_hold",
                            hold_id=wanted_id)
    try:
        raw = path.read_bytes()
        ledger = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise HoldSignError(f"{path} could not be read ({exc})",
                            code="ledger_unreadable", why=str(exc))
    if not isinstance(ledger, dict) or not isinstance(ledger.get(LEDGER_KEY), list):
        raise HoldSignError(f"{path} carries no `{LEDGER_KEY}` list",
                            code="ledger_unreadable",
                            why=f"нет списка `{LEDGER_KEY}`")
    parts = wanted_id.split("/", 2)
    wanted = (hold_id(resolve_channel(parts[0], root=root), parts[1], parts[2])
              if len(parts) == 3 and all(parts) else wanted_id)
    row = None
    for candidate in ledger[LEDGER_KEY]:
        if isinstance(candidate, dict) and (
                _row_key(candidate, root=root) == wanted
                or candidate.get("hold_id") == wanted_id):
            row = candidate
            break
    if row is None or not wanted_id:
        raise HoldSignError(f"no hold {wanted_id!r} in {path}",
                            code="no_such_hold", hold_id=wanted_id)
    signature = row.get("signature")
    if isinstance(signature, dict) and signature.get("user"):
        raise HoldSignError(
            f"{wanted_id} is already signed by {signature.get('user')} on "
            f"{signature.get('date')}", code="already_signed",
            hold_id=wanted_id, user=signature.get("user"),
            date=signature.get("date"))
    if row.get("resolved_at"):
        raise HoldSignError(
            f"{wanted_id} was resolved at {row['resolved_at']} - "
            f"{row.get('resolved_reason')}", code="already_resolved",
            hold_id=wanted_id, why=f"снят {row['resolved_at']}")
    if rights_only(row):
        raise HoldSignError(
            f"{wanted_id} rests on the rights-holder match alone, which holds "
            f"nothing since {RIGHTS_ONLY_TASK}; it is resolved by "
            f"--resolve-rights-only, not signed", code="not_signable",
            hold_id=wanted_id)
    if not holds(row):
        raise HoldSignError(
            f"{wanted_id} carries verdict {row.get('verdict')!r}, which holds "
            f"nothing", code="already_resolved", hold_id=wanted_id,
            why=f"вердикт {row.get('verdict')!r} ничего не держит")
    return ledger, row, path, _fingerprint(raw)


def check_sign(ledger_or_root, hold_id):
    """`{"row", "fingerprint"}` - whether the hold `hold_id`
    (`channel/batch_id/topic_id`) may be signed, and the ledger file's sha256
    as it was read. Raises HoldSignError (`no_such_hold`, `already_signed`,
    `already_resolved`, `not_signable`, `ledger_unreadable`). Writes nothing.

    `ledger_or_root`: a factory root, or the ledger file (`*.json`) - see
    `_sign_target`. An absent ledger is `no_such_hold`: no hold was written."""
    _, row, _, fingerprint = _signable(ledger_or_root, hold_id)
    return {"row": copy.deepcopy(row), "fingerprint": fingerprint}


def _sign_date(when):
    if when is None:
        return _now()
    if isinstance(when, datetime):
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(when)


def sign_hold(ledger_or_root, hold_id, user, note, when=None, via=SIGN_VIA_DEFAULT):
    """Sign the hold `hold_id` on a human's explicit action - **the only code
    in this file that writes a signature** (CF-0687, the user's permission of
    2026-10-11). The command center calls it after the user watched the video
    there and pressed the button, with that user's name and note.

    Validates as `check_sign`, then `empty_user` / `empty_note` (whitespace
    only is empty), sets `signature = {"user", "date", "note", "via"}` -
    `date` is `when` (a string as given, or a datetime) or now, in `_now()`'s
    format - and writes the ledger atomically. Returns `{"row", "fingerprint"}`
    with the sha256 of the file as written. It takes no expected fingerprint:
    the center compares fingerprints itself and calls this only to write."""
    ledger, row, path, _ = _signable(ledger_or_root, hold_id)
    user = str(user if user is not None else "").strip()
    note = str(note if note is not None else "").strip()
    if not user:
        raise HoldSignError("a signature needs the name of who signs",
                            code="empty_user")
    if not note:
        raise HoldSignError("a signature needs a note", code="empty_note")
    row["signature"] = {"user": user, "date": _sign_date(when), "note": note,
                        "via": str(via or SIGN_VIA_DEFAULT)}
    write_ledger(ledger, path=path)
    return {"row": copy.deepcopy(row), "fingerprint": _fingerprint(path.read_bytes())}


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------
USAGE = ("usage: publication_hold.py <02-compliance-checker.json> [channel] "
         "[--dry-run]\n"
         "       publication_hold.py --list [channel]\n"
         "       publication_hold.py --check <channel> <batch-id> <topic-id>\n"
         "       publication_hold.py --resolve-rights-only [--date YYYY-MM-DD] "
         "[--dry-run]\n"
         "       publication_hold.py --sign <channel/batch-id/topic-id> --user U "
         "--note N [--via cli] [--date D] [--dry-run]")


# Every option the command line knows (CF-0777): the bare ones, and the ones
# whose next argument is their value.
CLI_FLAGS = ("--dry-run", "--check", "--sign", "--resolve-rights-only", "--list")
CLI_VALUED = ("--root", "--date", "--user", "--note", "--via")


def _root_arg(argv):
    for i, a in enumerate(argv):
        if a == "--root" and i + 1 < len(argv):
            return argv[i + 1], argv[:i] + argv[i + 2:]
    return None, argv


def _main_sign(argv, root, dry_run):
    """`--sign`: a human at the terminal signs one hold (CF-0687). Refusal:
    the Russian text and exit 1; usage: exit 2. `via` defaults to `cli` here -
    the center calls `sign_hold` itself and records `center`."""
    opts = {}
    rest = argv[1:]
    i = 0
    positional = []
    while i < len(rest):
        if rest[i] in ("--user", "--note", "--via", "--date"):
            if i + 1 >= len(rest):
                print(USAGE)
                return 2
            opts[rest[i][2:]] = rest[i + 1]
            i += 2
            continue
        positional.append(rest[i])
        i += 1
    if len(positional) != 1:
        print(USAGE)
        return 2
    target = root if root else None
    try:
        if dry_run:
            seen = check_sign(target, positional[0])
            if not (opts.get("user") or "").strip():
                raise HoldSignError("a signature needs the name of who signs",
                                    code="empty_user")
            if not (opts.get("note") or "").strip():
                raise HoldSignError("a signature needs a note", code="empty_note")
            print(f"{seen['row'].get('hold_id')}: may be signed by "
                  f"{opts['user'].strip()} via {opts.get('via') or 'cli'} "
                  f"(dry run, nothing written; ledger sha256 {seen['fingerprint']})")
            return 0
        done = sign_hold(target, positional[0], opts.get("user"), opts.get("note"),
                         when=opts.get("date"), via=opts.get("via") or "cli")
    except HoldSignError as exc:
        print(exc.text_ru)
        return 1
    sig = done["row"]["signature"]
    print(f"{done['row'].get('hold_id')}: signed by {sig['user']} on {sig['date']} "
          f"via {sig['via']} - {sig['note']}; ledger sha256 {done['fingerprint']}")
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # CF-0777: help and unknown options are answered before anything is read.
    rc = screen(argv, USAGE, flags=CLI_FLAGS, valued=CLI_VALUED)
    if rc is not None:
        return rc
    root, argv = _root_arg(argv)
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]

    if argv and argv[0] == "--check":
        if len(argv) < 4:
            print(USAGE)
            return 2
        held, reason = is_held(argv[1], argv[2], argv[3], root=root)
        print(reason)
        return 1 if held else 0

    if argv and argv[0] == "--sign":
        return _main_sign(argv, root, dry_run)

    if argv and argv[0] == "--resolve-rights-only":
        when = None
        if "--date" in argv:
            i = argv.index("--date")
            if i + 1 >= len(argv):
                print(USAGE)
                return 2
            when = argv[i + 1]
        ledger, problem = read_ledger(root=root)
        if problem:
            print(f"refusing: {problem}. Nothing is resolved in a ledger that "
                  f"cannot be read.")
            return 2
        ledger, resolved = resolve_rights_only(ledger, when=when)
        for hid in resolved:
            print(f"{hid}: hold resolved - {RIGHTS_ONLY_REASON}")
        if not dry_run and resolved:
            path = write_ledger(ledger, root=root)
        else:
            path = ledger_path(root)
        print(f"\n{len(resolved)} rights-only hold(s) resolved; ledger {path}"
              + (" (dry run, nothing written)" if dry_run else ""))
        return 0

    if argv and argv[0] == "--list":
        rows, problem = open_holds(root=root, channel=argv[1] if len(argv) > 1 else None)
        if problem:
            print(f"cannot read the ledger: {problem}")
            return 2
        for row in rows:
            print(f"{row['hold_id']}: {row.get('verdict')!r}, unsigned - "
                  f"{row.get('reason_code')}")
        print(f"\n{len(rows)} publication hold(s) standing "
              f"({ledger_path(root)})")
        return 0

    if not argv:
        print(USAGE)
        return 2

    out_path = Path(argv[0])
    try:
        doc = json.loads(out_path.read_text())
    except (OSError, ValueError) as exc:
        print(f"cannot read the batch: {exc}")
        return 2

    # CF-0197: a batch written before the channel was renamed carries the old
    # id frozen in its `channel` field.
    channel = resolve_channel(argv[1] if len(argv) > 1 else doc.get("channel", ""))
    batch_id = doc.get("batch_id") or ""

    new_doc, held, resolved = mark_document(doc, channel=channel, batch_id=batch_id)
    rows = hold_rows(new_doc, channel=channel, batch_id=batch_id)
    ledger, problem = read_ledger(root=root)
    if problem:
        print(f"refusing: {problem}. A hold is not written over a ledger that "
              f"cannot be read - that would lose the holds already standing.")
        return 2
    ledger, added, refreshed, closed = merge(
        ledger, rows, resolved_ids=resolved, channel=channel, batch_id=batch_id,
        stage=doc.get("stage_checked"))

    for tid in held:
        print(f"{tid}: publication held - the video is made, and is not published "
              f"without a signature ({REASON_CODE})")
    for tid in closed:
        print(f"{tid.rsplit('/', 1)[-1]}: hold resolved - the verdict is no longer "
              f"{list(HOLD_VERDICTS)}, the ledger row stays with its reason")
    if not dry_run:
        out_path.write_text(json.dumps(new_doc, indent=2, ensure_ascii=False) + "\n")
        path = write_ledger(ledger, root=root)
    else:
        path = ledger_path(root)
    print(f"\n{len(held)} held, {len(added)} new in the ledger, "
          f"{len(refreshed)} refreshed, {len(closed)} resolved; ledger {path}"
          + (" (dry run, nothing written)" if dry_run else ""))
    return 0


@runlog.script("compliance-checker", "publication-hold", name="publication_hold.py")
def cli():
    """The command-line entry (CF-0107 accounting, same shape as
    `cut_shortlist.py`): main()'s return code becomes the exit code inside the
    run event. Pure Python over two JSON files - no model call, no external
    binary - so there is no `child` event."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
