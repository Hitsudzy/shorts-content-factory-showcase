"""CC-0171 (factory 2.37), CC-0173 (factory 2.38, CF-0888): the batch's two
second chances, as the center shows them - read only, through the factory's
own reader, the funnel (`shared/runlog/funnel.py`, `api/factory.py`):

    judge_repairs           CF-0881 / CF-0888: the one repair pass of a video
                            the frame judge refused for a defect in one or two
                            blocks - per video the outcome, the reason, `at` and
                            `block_details[]` {block, entry, kind, why, start,
                            end, at}; the counts `repaired` / `repair_failed`
    below_shortlist_refill  CF-0882 / CF-0888: the refill from below the
                            shortlist - the root's rounds (`work/below-shortlist-
                            refill.json`, read by the funnel's `_read_json`)
                            joined with the Trend Hunter's walk (`01 ->
                            below_shortlist_refill[]`) and compliance's refusals
                            on the fly (`02 -> refill_refused[]`, `reason_ru`),
                            each row in its `round`; rows no round claims under
                            `unattributed`

**The repair** (`repairs`): the funnel's video gives the outcome, the reason,
`at` and the blocks with their defect (`kind`, `why`). What the contract (0.75.0)
shows beside it and the funnel does not give - the block's `target` (shot /
meme), the gate / code / score line before and after, the Editor's outcome and
the changed blocks - is the same record's (`06 -> repairs[]`, by script id and
entry). A batch without the pass: None.

**The refill** (`refill_batch`, `refill_topics`): the funnel's rounds (with
`outcome_ru`, CC-0173), plus the round's `need_why` and its queue of ids, which
the funnel counts but does not list, from the record it read. Per topic: the
funnel's judged / walked / refused rows and, from the agents' own marks, 01
`topics[]` (`refill: {task, restored}` - promoted), 01 `skipped_topics[]`
(`refill_outcome: refused`, `refill_reason` - the sieve refused) and 02
`reserve[]` (`refill: {task, round}` - admitted). A batch before 2.37: None
everywhere, no error.
"""
from pathlib import Path

from . import factory

FJ = "06-frame-judge.json"              # funnel FRAME_JUDGE_FILE
REPAIRED, REPAIR_FAILED = "repaired", "repair_failed"
SUMMARY_KEYS = ("gate", "reason_code", "score_line")
REFUSED = "refused"
RECORD_FILE = "work/below-shortlist-refill.json"   # funnel REFILL_RECORD_FILE


def _rows(doc, key):
    v = (doc or {}).get(key) if isinstance(doc, dict) else None
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _str(v):
    return v if isinstance(v, str) and v.strip() else None


def _ids(v):
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _summary(doc):
    if not isinstance(doc, dict):
        return None
    return {k: doc.get(k) for k in SUMMARY_KEYS}


# ---------------------------------------------------------------- CF-0881
def repairs(fj):
    """(counts, {script_id: repair}) of the funnel's `judge_repairs` - counts
    `{repaired, repair_failed, videos}` - or (None, {}) when the batch had no
    repair pass (no 06, a 06 before 2.37, a factory without the reader)."""
    fn = factory.funnel()
    read = getattr(fn, "judge_repairs", None)
    got = read(fj) if read and isinstance(fj, dict) else None
    if not got:
        return None, {}
    key = getattr(fn, "JUDGE_REPAIRS_KEY", "repairs")
    raw = {r.get("script_id"): r for r in _rows(fj, key) if r.get("script_id")}
    per = {}
    for v in got.get("videos") or []:
        sid = v.get("item")
        if not sid:
            continue
        r = raw.get(sid) or {}
        target = {b.get("entry"): b.get("target") for b in _rows(r, "blocks")}
        ed = r.get("editor") if isinstance(r.get("editor"), dict) else {}
        per[sid] = {
            "outcome": v.get("outcome"), "reason": v.get("reason"), "at": v.get("at"),
            "blocks": [{"block": b.get("block"), "entry": b.get("entry"),
                        "target": target.get(b.get("entry")), "kind": b.get("kind"),
                        "why": b.get("why")}
                       for b in v.get("block_details") or [] if isinstance(b, dict)],
            "before": _summary(r.get("before")), "after": _summary(r.get("after")),
            "editor_outcome": ed.get("outcome"),
            "changed_blocks": [b for b in ed.get("changed_blocks") or [] if _int(b) is not None]}
    counts = {REPAIRED: _int(got.get(REPAIRED)) or 0,
              REPAIR_FAILED: _int(got.get(REPAIR_FAILED)) or 0, "videos": len(per)}
    return counts, per


# ---------------------------------------------------------------- CF-0882
def refill(d, th, c02):
    """The funnel's refill of the batch - `{funnel, record}`: `funnel` is
    `below_shortlist_refill(record, 01, 02)` (None: no round, no walk, no
    refusal; a factory without the reader), `record` the root's record as the
    funnel read it (None when absent or unreadable). Built once per answer and
    handed to `refill_batch` / `refill_topics`."""
    fn = factory.funnel()
    read = getattr(fn, "below_shortlist_refill", None)
    if read is None:
        return {"funnel": None, "record": None}
    name = getattr(fn, "REFILL_RECORD_FILE", RECORD_FILE)
    record = fn._read_json(Path(d) / name) if d else None
    return {"funnel": read(record, th, c02), "record": record}


def _record_rounds(rf):
    return {r.get("round"): r for r in _rows((rf or {}).get("record"), "rounds")
            if r.get("round")}


def _round(x, rec):
    return {"round": x.get("round"), "at": x.get("at"), "at_code": x.get("at_code"),
            "need": _int(x.get("need")), "need_why": rec.get("need_why"),
            "outcome": x.get("outcome"), "outcome_ru": x.get("outcome_ru"),
            "why": x.get("why"),
            "queue": _ids(rec.get("queue")),
            "judged": [{k: j.get(k) for k in ("topic_id", "verdict", "outcome", "reason")}
                       for j in _rows(x, "judged")],
            "footage": [{"topic_id": f.get("topic_id"), "outcome": f.get("outcome"),
                         "searches": _int(f.get("searches")), "reason": f.get("reason")}
                        for f in _rows(x, "footage")],
            "admitted": _ids(x.get("admitted")),
            "searches": _int(x.get("searches")) or 0,
            "spent_after": _int(x.get("spent_after")),
            "budget_line": _str(x.get("budget_line"))}


def refill_batch(rf):
    """The refill's rounds of the batch (the funnel's `below_shortlist_refill`)
    with the totals - or None when the refill left no trace."""
    f = (rf or {}).get("funnel")
    if not f:
        return None
    recs = _record_rounds(rf)
    rounds = [_round(x, recs.get(x.get("round")) or {}) for x in _rows(f, "rounds")]
    return {"record": getattr(factory.funnel(), "REFILL_RECORD_FILE", RECORD_FILE),
            "rounds": rounds,
            "admitted": sum(len(r["admitted"]) for r in rounds),
            "searches": sum(r["searches"] for r in rounds)}


def refill_topics(rf, th, c02):
    """{topic_id: refill} of every topic the refill touched - see the module."""
    mark = getattr(factory.below_shortlist(), "REFILL_MARK", "refill")
    f = (rf or {}).get("funnel") or {}
    promoted = {t["topic_id"]: t[mark] for t in _rows(th, "topics")
                if t.get("topic_id") and isinstance(t.get(mark), dict)}
    sieve = {r["topic_id"]: r for r in _rows(th, "skipped_topics")
             if r.get("topic_id") and r.get("refill_outcome")}
    admitted = {r["topic_id"]: r[mark] for r in _rows(c02, "reserve")
                if r.get("topic_id") and isinstance(r.get(mark), dict)}
    judged, walked, refused, round_of = {}, {}, {}, {}

    def walk(x, rnd):
        tid = x.get("topic_id")
        if tid and (tid not in walked or (walked[tid].get("at") is None and x.get("at"))):
            walked[tid] = x
        if tid and rnd:
            round_of.setdefault(tid, rnd)

    for r in _rows(f, "rounds"):
        rnd = r.get("round")
        for x in _rows(r, "judged"):
            if x.get("topic_id"):
                judged[x["topic_id"]] = x
                round_of.setdefault(x["topic_id"], rnd)
        for x in _rows(r, "footage"):
            walk(x, rnd)
        for x in _rows(r, "refused"):
            if x.get("topic_id"):
                refused[x["topic_id"]] = dict(x, round=rnd)
    un = f.get("unattributed") if isinstance(f.get("unattributed"), dict) else {}
    for x in _rows(un, "footage"):
        walk(x, None)
    for x in _rows(un, "refused"):
        if x.get("topic_id"):
            refused.setdefault(x["topic_id"], dict(x, round=None))
    out = {}
    for tid in set(promoted) | set(sieve) | set(refused) | set(admitted) \
            | set(judged) | set(walked):
        out[tid] = _topic_refill(promoted.get(tid), sieve.get(tid), refused.get(tid),
                                 admitted.get(tid), judged.get(tid), walked.get(tid),
                                 round_of.get(tid))
    return out


def _topic_refill(promo, sieve, cc_ref, adm, judged, walked, rnd):
    if cc_ref is not None:
        comp = {"outcome": REFUSED, "verdict": cc_ref.get("verdict"),
                "reason_code": cc_ref.get("reason_code"), "reason_ru": cc_ref.get("reason_ru"),
                "reason": cc_ref.get("reason")}
    elif judged is not None:
        comp = {"outcome": judged.get("outcome"), "verdict": judged.get("verdict"),
                "reason_code": None, "reason": judged.get("reason")}
    else:
        comp = None
    foot = None if walked is None else {
        "outcome": walked.get("outcome"), "searches": _int(walked.get("searches")),
        "at": walked.get("at"), "reason": walked.get("reason")}
    if sieve is not None and sieve.get("refill_outcome") == REFUSED and \
            (foot is None or foot["outcome"] != REFUSED):
        foot = dict(foot or {"searches": None, "at": None},
                    outcome=REFUSED, reason=sieve.get("refill_reason") or (foot or {}).get("reason"))
    refused_by = reason = None
    if comp and comp["outcome"] == REFUSED:
        refused_by, reason = "compliance", comp["reason"]
    elif foot and foot["outcome"] == REFUSED:
        refused_by, reason = "trend_hunter", foot["reason"]
    if adm is not None:
        outcome = "admitted"
    elif refused_by:
        outcome = REFUSED
    elif foot and foot["outcome"] and foot["outcome"] != "candidates":
        outcome = foot["outcome"]                    # quota | error | not_walked
    elif promo is not None or (foot and foot["outcome"] == "candidates"):
        outcome = "promoted"
    else:
        outcome = (comp or {}).get("outcome") or "considered"   # eligible | not_judged
        if outcome not in ("eligible", "not_judged"):
            outcome = "considered"
    if reason is None and outcome not in ("admitted", "promoted"):
        reason = (foot or {}).get("reason") or (comp or {}).get("reason")
    return {"outcome": outcome, "round": (adm or {}).get("round") or
            (cc_ref or {}).get("round") or rnd,
            "promoted": promo is not None,
            "restored": promo.get("restored") if isinstance(promo, dict) and
            isinstance(promo.get("restored"), bool) else None,
            "admitted": adm is not None, "refused_by": refused_by, "reason": reason,
            "compliance": comp, "footage": foot}
