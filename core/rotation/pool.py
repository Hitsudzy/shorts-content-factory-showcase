#!/usr/bin/env python3
"""CF-0149: the observable answer to "has the pool been topped up since?".

`CF-0139` gave the rotation the first half of the question. A refusal for want
of material writes `rotation/ledger/<channel>.shortages.jsonl`, and every
record there carries `pool_fixable` and `retry_when` - *what* the topic is
waiting for, machine-readable, per anchor. This module is the second half:
*has it arrived*. Nothing else in the factory could answer that;
`01b-footage-index.json` is the list of files one batch happened to touch, not
an inventory of the pool.

--------------------------------------------------------------------------
Two stores, because the causes look at two stores
--------------------------------------------------------------------------

`shortage.POOL_FIXABLE` is three causes and they are not fixed by the same
shopping:

    no_footage         shared/footage/   more material
    footage_unusable   shared/footage/   more material, *or* a re-measurement
                                         that makes material already there
                                         takeable
    insert_below_floor shared/inserts/   more library entries

So "the pool grew" is two signals, never one, and a record is released only
when every store it names has answered - see `arrival()`.

--------------------------------------------------------------------------
Why a census and not a digest (the CF-0179 lesson, applied the other way)
--------------------------------------------------------------------------

The obvious signal is a fingerprint: hash the store, compare. CF-0179 measured
what that costs when the thing hashed is *code* - 15 of 38 commits in a month
(39 %) moved the caption fingerprint without changing a single measurement, and
each of those false moves cost a 51.7-minute re-measure of the pool.

The mistake there was not hashing; it was hashing something that moves for
reasons unrelated to the question. So this module hashes nothing. It **counts**,
and it counts the data rather than the code:

  * a count answers "is there more than there was", which is the question.
    A digest answers "is it byte-identical", which is a different and stricter
    question, and the difference between the two is exactly the false-positive
    rate CF-0179 paid for.
  * a count is unmoved by a file rewritten with the same content - `save_index`
    in `shared/inserts/inserts_lib.py` is deliberately idempotent, and
    `remeasure_captions.py` rewrites every `*.shots.json` it touches. A digest
    of bytes survives that; mtime does not, which is why no mtime, ctime or
    file size is read anywhere below.
  * a count is unmoved by `touch`, by a `git checkout` that restores the same
    content, and by an edit to the code that produced the numbers. The stored
    measurement identity (`crop_bottom_measured_by`) only changes when somebody
    actually ran a re-measurement and wrote new numbers into the pool - which
    is a fact about material, not about a source file.

--------------------------------------------------------------------------
Which side of the error is cheaper, and the mechanism that decides it
--------------------------------------------------------------------------

A census is pool-wide; the anchor is not. So a false "it grew" is possible -
a shot arrives that answers some other anchor, the topic is released, and the
video refuses again. Narrowing that would mean asking, per anchor, whether
*this* hole is now fillable, which is re-running the resolver - i.e. paying the
refusal in order to predict it.

The asymmetry is settled by a mechanism, not by taste. Since CF-0140/CF-0151
the coverage question is asked at the *front* of the pipeline
(`anchor_coverage.py` for the Editor, `check_anchor_coverage.py` for the
writer, ~5 s on a clean source), before narration is written and long before
TTS or a render. So a topic released too early does not burn a stage any more;
it fails a five-second preflight. A topic held too long, by contrast, idles for
a whole batch cycle and nothing in the factory notices.

That inverts the naive reading of the two costs, and it is why the rules below
are the *loose* ones (strictly-greater on a count, any new measurement
generation) rather than an attempt to prove the anchor is now answerable.

What is deliberately NOT claimed: that growth means the topic will build. It
means the store is no longer the same store that refused it. A necessary
condition, honestly labelled - `arrival()` returns `"arrived"`, never "will
work".

--------------------------------------------------------------------------
Counted per source, because the pool now shrinks (CF-0527)
--------------------------------------------------------------------------

Until CF-0358 the pool only ever grew, so one pool-wide total was enough:
more shots than at the refusal meant something had arrived. CF-0358 made
`runlog pool-release --delete` take the sources of published topics out of
`shared/footage/`, and a total cannot tell "three sources released, one new
one ingested" from "nothing happened" - the new material is there, the total
is lower than at the refusal, and the topic waiting for it never comes back.

So the footage census also carries `per_source`: `{source id: shots}`, the id
being the `*.shots.json` stem (the video id the whole factory keys a source
by). "It grew" is then a question about identity, not about a total: is there
a source the refusal's pool did not have, or a source that now holds more
shots than it did. A source that is gone is simply absent from both answers -
deletion is not a signal either way, which is what it is: releasing what a
published video used adds nothing a waiting topic could take.

Why per-source ids and not the release journal (`shared/footage/release-log.jsonl`):
subtracting what the journal says was released would make the gate as right
as the journal, and a source removed by hand, by a failed ingest cleanup or by
anything other than `pool-release` would again read as "nothing arrived". The
ids are read from the pool itself, so whatever removed a file, the answer
stays right. The price is roughly 25 bytes per source per refusal record
(~1.2 KB at 47 sources) - paid only on a refusal, which is rare.

Records written before CF-0527 carry no `per_source`. They are read with the
old rule (the totals), which is exactly what they were written for; the one
case it misjudges - deletions since the refusal - did not exist in the live
tree when this was written (no `*.shortages.jsonl` on 2026-10-03), so no old
record is left stranded by it.
"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FOOTAGE = "footage"
INSERTS = "inserts"
STORES = (FOOTAGE, INSERTS)

# Which store answers which cause. Keys are exactly `shortage.POOL_FIXABLE`;
# a cause outside this map is one no shopping fixes, and `arrival()` says so
# rather than inventing a store for it.
CAUSE_STORE = {
    "no_footage": FOOTAGE,
    "footage_unusable": FOOTAGE,
    "insert_below_floor": INSERTS,
}

# The causes a re-measurement can answer. An anchor that resolved to nothing
# has no frame to re-measure, so re-measuring the pool gives it nothing; an
# anchor whose frame exists and could not be taken is exactly the one a new
# measurement can free. CF-0151 measured the size of that effect on the real
# pool: of 980 cached shots a full re-measure moved 241 and 34 crossed the
# 720 px short-side line, i.e. changed the `usable()` verdict itself, with not
# one new file arriving.
REMEASURE_ANSWERS = ("footage_unusable",)

FOOTAGE_DIR = Path("shared") / "footage"
INSERTS_DIR = Path("shared") / "inserts"


# --------------------------------------------------------------------------
# the census
# --------------------------------------------------------------------------

def footage_census(root=None):
    """What `shared/footage/` holds, as numbers that only grow when material
    does.

        sources       how many `*.shots.json` are on disk
        shots         how many shot records they hold in total
        per_source    {source id: shots} - the `*.shots.json` stem and its
                      shot count (CF-0527). The growth rule reads this, so a
                      source released from the pool is not mistaken for
                      material that never arrived; the two totals above stay
                      for the human-readable verdict and for old records.
        measurements  {"<what>:<fingerprint>": count} - the measurement
                      generations actually written into the pool. New material
                      is not the only way an unusable frame becomes usable; a
                      re-measurement is the other, and it leaves its identity
                      in the shot record (`usable_cached.measured_by`,
                      `crop_bottom_measured_by`). Read from the data, so an
                      edit to the measuring code moves nothing here until
                      somebody re-measures and writes.
    """
    base = Path(root or ROOT) / FOOTAGE_DIR
    sources = 0
    shots = 0
    per_source = {}
    measurements = {}
    for path in sorted(base.glob("*.shots.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # A half-written or unreadable source is not material. Counting it
            # would be a growth event produced by a broken file.
            continue
        if not isinstance(doc, dict):
            continue
        sources += 1
        sid = path.name[:-len(".shots.json")]
        per_source[sid] = 0
        for shot in doc.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            shots += 1
            per_source[sid] += 1
            cached = shot.get("usable_cached")
            if isinstance(cached, dict) and cached.get("measured_by"):
                key = f"usability:{cached['measured_by']}"
                measurements[key] = measurements.get(key, 0) + 1
            if shot.get("crop_bottom_measured_by"):
                key = f"caption:{shot['crop_bottom_measured_by']}"
                measurements[key] = measurements.get(key, 0) + 1
    return {"sources": sources, "shots": shots, "per_source": per_source,
            "measurements": measurements}


def _inserts_lib():
    """The library schema module - always this repository's, never `root`'s.

    `root` says where the *stores* are (tests point it at a scratch pool); the
    code that knows what an entry is does not move with them.
    """
    base = str(ROOT / INSERTS_DIR)
    if base not in sys.path:
        sys.path.insert(0, base)
    import inserts_lib  # noqa: E402
    return inserts_lib


# The key of the library census that is not a kind: the channels whose
# rights-holder list is there but cannot be read (CF-0632). Every reader of the
# census that adds counts goes through `_kind_counts`, which leaves it out.
UNREAD_RIGHTS_HOLDERS = "_unread_rights_holders"


def _channel_data():
    spec = importlib.util.spec_from_file_location(
        "channel_data_pool", ROOT / "shared" / "channel_data.py")
    cd = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cd)
    return cd


def _every_channel_s_rights_holders(root):
    """(list, unread): one list in the common format holding the entries of
    every channel's rights-holder list under `root` (shared/channel_data.py),
    or None when no channel has one; and [{channel, reason}] for each channel
    whose list is there and cannot be read.

    CF-0632: "no channel has a list" and "a channel's list does not read" are
    two answers. The first is the design (CF-0561: no list, nothing refused).
    The second used to be the same silent None; now the broken channel adds no
    entries, the other channels' lists still refuse, and the census says which
    channel and why. `channels_with` names only the channels whose file exists,
    so a `ChannelDataError` from `rights_holders` here is a file that is there
    and does not parse (or vanished between the two reads).
    """
    cd = _channel_data()
    channels = cd.channels_with("rights-holders", root)
    if not channels:
        return None, []
    entries, unread = [], []
    for channel in channels:
        try:
            doc = cd.rights_holders(channel, root)
        except cd.ChannelDataError as exc:
            unread.append({"channel": channel, "reason": str(exc)})
            continue
        got = doc.get("entries") if isinstance(doc, dict) else None
        if got is None and isinstance(doc, dict):
            got = []                  # a list with no entries refuses nothing
        if not isinstance(got, list):
            unread.append({"channel": channel, "reason": (
                f"{cd.CHANNELS_SUBDIR}/{channel}/rights-holder list is not an "
                f"object with an `entries` list")})
            continue
        entries.extend(e for e in got if isinstance(e, dict))
    return ({"schema_note": "every channel's rights holders: " + ", ".join(channels),
             "last_updated": None, "entries": entries}, unread)


def _kind_counts(inserts):
    """{kind: candidates} of a library census - its counts without the
    `UNREAD_RIGHTS_HOLDERS` note (or any other non-count a later census adds)."""
    return {k: v for k, v in (inserts or {}).items()
            if not k.startswith("_") and isinstance(v, (int, float))
            and not isinstance(v, bool)}


def inserts_census(root=None):
    """What `shared/inserts/` holds, per kind, counted as *candidates*.

    A candidate is an entry the selector could actually put in front of a
    hole: it carries an embedding (`rank_by_embedding` skips entries without
    one, so an unembedded file cannot clear an M4 floor because it is never
    scored) and it survives the rights blacklist (`eligible`). Counting the
    raw `entries` instead would make "somebody added a blacklisted still" read
    as growth, which is the one false positive this store can produce cheaply.

    CF-0631: the rights holders are each channel's list (CF-0561) and the
    library is common, so "survives the blacklist" is "survives every
    channel's list" - the union of the lists `root` carries. With no channel
    list at all nothing is refused, as an absent file always meant.

    CF-0632: a channel whose list is there and does not read refuses nothing,
    and the census says so under `UNREAD_RIGHTS_HOLDERS`:
    [{"channel", "reason"}]. The key is there only when some list is unread,
    so a census of a healthy tree keeps its old shape {kind: count}.
    """
    base = Path(root or ROOT) / INSERTS_DIR
    lib = _inserts_lib()
    blacklist, unread = _every_channel_s_rights_holders(Path(root or ROOT))
    out = {}
    for index_path in sorted(base.glob("*/index.json")):
        kind = index_path.parent.name
        try:
            doc = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        entries = [e for e in (doc.get("entries") or [])
                   if isinstance(e, dict) and e.get("embedding")]
        if blacklist is not None:
            entries, _skipped = lib.eligible(entries, blacklist)
        out[kind] = len(entries)
    if unread:
        out[UNREAD_RIGHTS_HOLDERS] = unread
    return out


def census(root=None, stores=None):
    """The census of the stores asked for (default: both).

    Measured cost on the pool as it stands (47 sources, 1411 shots, 14 MB of
    JSON, 101 library entries): 0.12 s for both stores. That is the whole
    budget of this mechanism and it is paid once per `assign` call, not once
    per script.
    """
    # `stores=[]` means "count nothing", not "count everything" - a refusal no
    # shopping can fix asks for an empty census and must get one.
    want = STORES if stores is None else tuple(stores)
    out = {}
    if FOOTAGE in want:
        out[FOOTAGE] = footage_census(root)
    if INSERTS in want:
        out[INSERTS] = inserts_census(root)
    return out


# --------------------------------------------------------------------------
# has it grown
# --------------------------------------------------------------------------

def _new_by_source(then, now):
    """({new source: shots}, {source: shots gained}) when both censuses carry
    `per_source`, else None (a record written before CF-0527)."""
    a, b = then.get("per_source"), now.get("per_source")
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    new_src = {k: int(v) for k, v in b.items() if k not in a and int(v) > 0}
    more = {k: int(v) - int(a[k]) for k, v in b.items()
            if k in a and int(v) > int(a[k])}
    return new_src, more


def _footage_grew(then, now, remeasure_counts):
    """(grew, why). `remeasure_counts` says whether a new measurement
    generation is an answer for this record - it is for `footage_unusable`
    and it is not for `no_footage`."""
    then = then or {}
    now = now or {}
    by_id = _new_by_source(then, now)
    if by_id is not None:
        new_src, more = by_id
        if new_src or more:
            added = sum(new_src.values()) + sum(more.values())
            parts = []
            if new_src:
                parts.append(f"{len(new_src)} new source(s)")
            if more:
                parts.append(f"{len(more)} source(s) with more shots")
            return True, f"+{added} shot(s) in {' and '.join(parts)}"
        added = 0          # only identities count; a lower total is a release
    else:
        # A census written before CF-0527: no ids, so the old rule on totals.
        added = int(now.get("shots", 0)) - int(then.get("shots", 0))
        if added > 0:
            src = int(now.get("sources", 0)) - int(then.get("sources", 0))
            tail = f" in {src} new source(s)" if src > 0 else ""
            return True, f"+{added} shot(s){tail}"
    fresh = sorted(set(now.get("measurements") or {})
                   - set(then.get("measurements") or {}))
    if fresh and remeasure_counts:
        return True, f"re-measured ({', '.join(fresh)})"
    held = f"{now.get('shots', 0)} shot(s) in {now.get('sources', 0)} source(s)"
    if by_id is not None and int(now.get("shots", 0)) < int(then.get("shots", 0)):
        gone = len(set(then["per_source"]) - set(now["per_source"]))
        return False, (f"{held} - fewer than the {then.get('shots', 0)} at the refusal; "
                       f"{gone} source(s) released since and none new")
    if added < 0:
        return False, f"{held} - fewer than the {then.get('shots', 0)} at the refusal"
    if fresh:
        return False, (f"{held}, unchanged in number; re-measured, which answers "
                       f"an unusable frame but not a missing one")
    return False, f"{held}, unchanged since the refusal"


def _unread_note(inserts):
    """' - rights-holder list unread: <channel> (<reason>); ...' or ''."""
    unread = (inserts or {}).get(UNREAD_RIGHTS_HOLDERS) or []
    if not unread:
        return ""
    return ("; rights-holder list unread, nothing refused for it: "
            + "; ".join(f"{u.get('channel')} ({u.get('reason')})" for u in unread))


def _inserts_grew(then, now):
    note = _unread_note(now)
    then = _kind_counts(then)
    now = _kind_counts(now)
    added = {k: int(now.get(k, 0)) - int(then.get(k, 0)) for k in set(then) | set(now)}
    up = sorted(k for k, d in added.items() if d > 0)
    if up:
        return True, ", ".join(f"+{added[k]} {k}" for k in up) + note
    total = sum(int(v) for v in now.values())
    return False, (f"{total} candidate(s) across "
                   f"{', '.join(f'{k}:{now.get(k, 0)}' for k in sorted(now)) or 'no kind'}"
                   f" - unchanged since the refusal" + note)


def stores_for(causes):
    """The stores a record waits on, from its `causes` counter.

    A conjunction, and deliberately: a video refused because three blocks have
    no footage *and* one hole has no insert is not buildable when only one of
    the two stores has grown - it walks back into the other half of the same
    hole. `retry_when` already reads as an "and"; this is that sentence made
    executable.
    """
    return sorted({CAUSE_STORE[c] for c in (causes or {})
                   if c in CAUSE_STORE and (causes or {}).get(c)})


def arrival(record, now=None, root=None):
    """Has what this shortage record waits for arrived?

    Returns {state, assignable, says, stores:{store: {grew, says}}} where
    `state` is one of:

      arrived              every store the record names has grown
      waiting              at least one has not
      not-a-pool-question  no cause of this refusal is pool-fixable, so no
                           amount of shopping changes the answer; it waits on
                           a fix and a person, and `assign` says so instead of
                           quietly trying again
      no-baseline          the record carries no census of the stores as they
                           were at the refusal - it was written before this
                           mechanism existed. There is nothing to compare
                           against and never will be, so the gate opens: a
                           topic that can only ever be freed by hand is a
                           worse failure for an unattended pipeline than one
                           retry against an unchanged pool, and opening here
                           is exactly the behaviour these records already had.
    """
    causes = record.get("causes") or {}
    wanted = stores_for(causes)
    if not wanted:
        return {"state": "not-a-pool-question", "assignable": False, "stores": {},
                "says": (record.get("retry_when")
                         or "nothing about the pool would change this refusal")}
    before = record.get("pool_census")
    if not isinstance(before, dict) or not all(k in before for k in wanted):
        return {"state": "no-baseline", "assignable": True, "stores": {},
                "says": ("this refusal was recorded before the pool census existed "
                         "(CF-0149), so there is nothing to compare today's pool "
                         "against - the topic is let through once rather than held "
                         "for ever")}
    now = now if now is not None else census(root, stores=wanted)
    out = {}
    for store in wanted:
        if store == FOOTAGE:
            counts_remeasure = any(causes.get(c) for c in REMEASURE_ANSWERS)
            grew, says = _footage_grew(before.get(FOOTAGE), now.get(FOOTAGE),
                                       counts_remeasure)
        else:
            grew, says = _inserts_grew(before.get(INSERTS), now.get(INSERTS))
        out[store] = {"grew": bool(grew), "says": says}
    every = all(v["grew"] for v in out.values())
    return {
        "state": "arrived" if every else "waiting",
        "assignable": every,
        "stores": out,
        "says": "; ".join(f"{s}: {'arrived' if out[s]['grew'] else 'not yet'} "
                          f"({out[s]['says']})" for s in wanted),
    }
