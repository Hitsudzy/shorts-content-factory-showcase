#!/usr/bin/env python3
"""CF-0420: a rights-holder match is information, not a verdict.

The channel keeps a configurable list of rights holders (a blocklist with a
`risk_level` and a `reason` per entry). A topic whose `title_ref.rights_holder`
or `network` answers to an entry is recorded in the verdict row's
`rights_holder_check`. That record is advisory: the verdict
(`clear | caution | review`) comes from the content-sensitivity check alone -
that check is the only thing that can hold a video.

What this script does
---------------------
The verdict is written by a model reading the SKILL, and a model with a habit
of "this holder is `high`, write `review`" is exactly where an old rule
survives a new one. So the rule is enforced here, deterministically, over the
file the pass just wrote - the same division of labour as the cut
(`cut_shortlist.py`) and the holds (`publication_hold.py`):

* every `rights_holder_check` in `results[]` and `reserve[]` gets
  `affects_verdict: false` (and `task: "CF-0420"`);
* a row whose verdict is above `clear`, whose rights-holder check matched and
  whose content-sensitivity check is **not** flagged carries a verdict only the
  rights match can have earned, so it is set to `clear`, with a
  `rights_holder_decoupled` record beside it naming the verdict it had before.
  Nothing is lowered silently.
* a row whose content-sensitivity check **is** flagged keeps its verdict,
  whatever the rights match says. A raised verdict with neither a flag nor a
  match is not this script's either, and it is left exactly as written. So
  does `contribution_check` (CF-0187) - it is a separate verdict
  (`pass | block`) and is not read here at all.

It never raises a verdict on the list match. Running it twice changes nothing.

Where the match came from (CF-0600)
-----------------------------------
The batch's channel's rights-holder list (`channels/<channel>/
rights-holder-blacklist.json`, the channel's own data, read through the root's
`shared/channel_data.py`) carries entries of the form

    {"rights_holder": "Example Studios", "aliases": ["Example Pictures"],
     "risk_level": "medium", "reason": "why it is on the list"}

For every row whose `rights_holder_check.matched` is `true` (or a name) this
step finds the list entry the match stands for - the names asked are the one
the pass wrote in `matched`, the topic's `title_ref.rights_holder` and
`title_ref.network`; an entry answers by its `rights_holder` or any of its
`aliases`, compared word-run-wise ("Example Studios" is inside "Example Studios
Pictures") - and adds to the check, beside what the pass wrote:

* `evidence` - the entry's `evidence` field (`null` when it has none);
* `blacklist_entry` - the entry's `rights_holder`;
* `also_matched` - `[{"blacklist_entry", "evidence"}]`, the other entries the
  names answered to, when there were several.

`matched`, `risk_level`, `reason` and the verdict are never touched - the
fields are additive. A row the pass did not match, or whose names answer no
entry, gets none of them (and loses them on a re-run).

Whose list. The list is the batch's channel's, never a common one and never
another channel's: the channel is the `channel` of `01-trend-hunter.json`
beside the compliance file (a former id resolves), else the name of the
`pipeline/<channel>/` directory the batch sits in. There is no default
channel: a file whose channel cannot be found gets no evidence and says so. A
channel without the list, a list that does not read, an unnamed or unknown
channel - each adds nothing and is said in the summary line (`error`); nothing
depends on it.
"""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runlog import runlog  # noqa: E402
from _channel_data import ChannelDataError, channel_data  # noqa: E402
from _channel_ids import factory_root, resolve_channel  # noqa: E402
from _cli import screen  # noqa: E402

TASK = "CF-0420"
CHECK_KEY = "rights_holder_check"
SENSITIVITY_KEY = "content_sensitivity_check"
RECORD_KEY = "rights_holder_decoupled"
FREE_VERDICT = "clear"
# The verdicts above `clear`. Only these can be something the rights match
# alone raised.
RAISED_VERDICTS = ("caution", "review")

RECORD_NOTE = (
    f"{TASK}: this verdict was above `clear` on a rights-holder match with no "
    f"content-sensitivity flag, so only the rights match can have raised it. "
    f"The rights-holder list is advisory; the content-sensitivity check is the "
    f"only basis a verdict or a publication hold has. `{CHECK_KEY}` is kept as "
    f"written, for information."
)

TREND_HUNTER_FILE = "01-trend-hunter.json"
CONTENT_RESEARCHER_FILE = "03-content-researcher.json"
BLACKLIST_LIST = "rights-holders"
PIPELINE_DIR = "pipeline"
EVIDENCE_TASK = "CF-0600"
EVIDENCE_FIELDS = ("evidence", "blacklist_entry", "also_matched")
_LEGAL = {"inc", "ltd", "llc", "co", "corp", "company", "the", "and"}


def sensitivity_flagged(row):
    check = row.get(SENSITIVITY_KEY) if isinstance(row, dict) else None
    return isinstance(check, dict) and check.get("flagged") is True


def rights_matched(row):
    check = row.get(CHECK_KEY) if isinstance(row, dict) else None
    return isinstance(check, dict) and check.get("matched") is True


def rights_only(row):
    """True for a verdict above `clear` that nothing but the rights-holder
    match can have earned: the match is there, no content-sensitivity flag is.
    The same predicate `publication_hold.py` uses to refuse a hold and to
    resolve the ledger's rights-only rows."""
    return (isinstance(row, dict)
            and (row.get("verdict") or "") in RAISED_VERDICTS
            and rights_matched(row)
            and not sensitivity_flagged(row))


def _tokens(name):
    return [t for t in re.findall(r"[a-z0-9]+", str(name or "").lower()) if t not in _LEGAL]


def same_holder(a, b):
    """Two names are the same holder when one's word tokens are a whole run
    inside the other's (legal-form words ignored)."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    n = len(short)
    return any(long_[i:i + n] == short for i in range(len(long_) - n + 1))


# --------------------------------------------------------------------------
# CF-0600: the evidence behind a rights match
# --------------------------------------------------------------------------
def read_blacklist(channel, root=None):
    """The channel's rights-holder list read once for a whole file:
    `{"entries", "same", "error"}`. `channel` is the batch's - no default. No
    channel, an unknown channel, a channel without the list, a list that does
    not read or has no entries - each is `error` with no entries: the evidence
    is information, so nothing fails on it, and no other channel's list stands
    in."""
    try:
        doc = channel_data.rights_holders(channel, root or factory_root())
    except ChannelDataError as exc:
        return {"entries": [], "same": same_holder, "error": str(exc)}
    entries = doc.get("entries") if isinstance(doc, dict) else None
    if not isinstance(entries, list):
        return {"entries": [], "same": same_holder,
                "error": f"the {BLACKLIST_LIST} list of {channel!r} has no entries list"}
    return {"entries": [e for e in entries if isinstance(e, dict) and e.get("rights_holder")],
            "same": same_holder, "error": None}


def _entry_names(entry):
    names = [entry.get("rights_holder")] + list(entry.get("aliases") or [])
    return [n for n in names if isinstance(n, str) and n.strip()]


def blacklist_match(check, title_ref, blacklist):
    """`(entry, others)` - the list entry a matched rights check stands for,
    and the other entries its names answered to; `(None, [])` when the check
    did not match or no entry answers. Order: the entry the pass's own
    `matched` name answers to first, then file order."""
    if not isinstance(check, dict) or not blacklist or not blacklist.get("same"):
        return None, []
    matched = check.get("matched")
    if matched is not True and not (isinstance(matched, str) and matched.strip()):
        return None, []
    same = blacklist["same"]
    ref = title_ref if isinstance(title_ref, dict) else {}
    pass_name = matched if isinstance(matched, str) else None
    names = [n for n in (pass_name, ref.get("rights_holder"), ref.get("network"))
             if isinstance(n, str) and n.strip()]
    hits = []
    for i, entry in enumerate(blacklist.get("entries") or []):
        own = _entry_names(entry)
        if not any(same(n, e) for n in names for e in own):
            continue
        by_pass = bool(pass_name) and any(same(pass_name, e) for e in own)
        hits.append(((not by_pass, i), entry))
    if not hits:
        return None, []
    hits.sort(key=lambda h: h[0])
    return hits[0][1], [h[1] for h in hits[1:]]


def add_evidence(check, title_ref, blacklist):
    """Writes CF-0600's fields into `check` (in place) from the entry the
    match stands for, or removes them when there is none. Never touches
    `matched`, `risk_level` or `reason`."""
    if not isinstance(check, dict) or blacklist is None:
        return
    for key in EVIDENCE_FIELDS:
        check.pop(key, None)
    entry, others = blacklist_match(check, title_ref, blacklist)
    if entry is None:
        return
    check["evidence"] = entry.get("evidence")
    check["blacklist_entry"] = entry.get("rights_holder")
    if others:
        check["also_matched"] = [{"blacklist_entry": o.get("rights_holder"),
                                  "evidence": o.get("evidence")} for o in others]


def decouple_row(row, title_ref=None, blacklist=None):
    """`(row, record)` - a copy of the row with the rights match made
    informational, and the record of a lowered verdict (None if the verdict
    stood).

    `blacklist` (from `read_blacklist`) names where a matched rights check
    came from (CF-0600: `evidence`, `blacklist_entry`, `also_matched`);
    without it the check is left as it is."""
    out = copy.deepcopy(row)
    if not isinstance(out, dict):
        return out, None
    check = out.get(CHECK_KEY)
    if isinstance(check, dict):
        check["affects_verdict"] = False
        check.setdefault("task", TASK)
        if blacklist is not None:
            ref = title_ref if isinstance(title_ref, dict) else (
                out.get("title_ref") if isinstance(out.get("title_ref"), dict) else None)
            add_evidence(check, ref, blacklist)
    if not rights_only(out):
        return out, None
    record = {
        "task": TASK,
        "verdict_before": out.get("verdict"),
        "verdict_after": FREE_VERDICT,
        "note": RECORD_NOTE,
    }
    out["verdict"] = FREE_VERDICT
    out[RECORD_KEY] = record
    return out, record


def _row_id(row):
    return row.get("script_id") or row.get("topic_id")


def title_ref_of(row, topics=None, script_topics=None):
    """The topic's `title_ref` for a row: by `topic_id`, or for a `04` row by
    its script's `topic_id` in `03-content-researcher.json`; else the row's
    own `title_ref`; else None."""
    if not isinstance(row, dict):
        return None
    topics, script_topics = topics or {}, script_topics or {}
    tid = row.get("topic_id") or script_topics.get(row.get("script_id"))
    topic = topics.get(tid) if tid else None
    ref = topic.get("title_ref") if isinstance(topic, dict) else None
    if isinstance(ref, dict):
        return ref
    return row.get("title_ref") if isinstance(row.get("title_ref"), dict) else None


def decouple_document_full(doc, *, topics=None, script_topics=None, root=None,
                           blacklist=None, channel=None):
    """`(doc, lowered)` - every row decoupled; `lowered` is `{row_id: record}`
    for the verdicts CF-0420 lowered. The list (CF-0600) is read once from
    `root` - `channel`'s list (the batch's channel, `batch_channel`; without
    one no evidence is added and `blacklist["error"]` says why)."""
    out = copy.deepcopy(doc)
    lowered = {}
    if not isinstance(out, dict):
        return out, lowered
    if blacklist is None:
        blacklist = read_blacklist(channel, root)
    for key in ("results", "reserve"):
        rows = out.get(key)
        if not isinstance(rows, list):
            continue
        for i, row in enumerate(rows):
            new_row, record = decouple_row(row, title_ref_of(row, topics, script_topics),
                                           blacklist)
            rows[i] = new_row
            if record:
                lowered[_row_id(new_row)] = record
    return out, lowered


def decouple_document(doc, **kw):
    """Alias of `decouple_document_full`."""
    return decouple_document_full(doc, **kw)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def sibling_topics(path):
    """`({topic_id: topic}, {script_id: topic_id})` from `01-trend-hunter.json`
    and `03-content-researcher.json` beside the compliance file (empty when
    they are not there)."""
    path = Path(path)
    th = _read_json(path.with_name(TREND_HUNTER_FILE)) or {}
    topics = {t["topic_id"]: t for t in (th.get("topics") or [])
              if isinstance(t, dict) and t.get("topic_id")} if isinstance(th, dict) else {}
    cr = _read_json(path.with_name(CONTENT_RESEARCHER_FILE)) or {}
    scripts = {}
    if isinstance(cr, dict):
        for s in cr.get("scripts") or []:
            if isinstance(s, dict) and s.get("script_id") and s.get("topic_id"):
                scripts[s["script_id"]] = s["topic_id"]
    return topics, scripts


def batch_channel(path):
    """The channel of the batch the compliance file belongs to, its current id:
    the `channel` of `01-trend-hunter.json` beside it (a former id resolves),
    else the name of the `pipeline/<channel>/` directory the batch sits in;
    None when neither is there - no default channel."""
    path = Path(path)
    th = _read_json(path.with_name(TREND_HUNTER_FILE))
    channel = resolve_channel((th.get("channel") if isinstance(th, dict) else None) or "")
    if isinstance(channel, str) and channel.strip():
        return channel.strip()
    batch_dir = path.resolve().parent
    if batch_dir.parent.parent.name == PIPELINE_DIR and batch_dir.parent.name:
        return resolve_channel(batch_dir.parent.name)
    return None


USAGE = "usage: rights_holder_info.py <NN-compliance-checker.json> [--dry-run]"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rc = screen(argv, USAGE, flags=("--dry-run",))  # CF-0777
    if rc is not None:
        return rc
    dry_run = "--dry-run" in argv
    argv = [a for a in argv if a != "--dry-run"]
    if len(argv) != 1:
        print(USAGE)
        return 2
    path = Path(argv[0])
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        print(f"cannot read the compliance file: {exc}")
        return 2
    topics, script_topics = sibling_topics(path)
    blacklist = read_blacklist(batch_channel(path))
    new_doc, lowered = decouple_document_full(doc, topics=topics,
                                              script_topics=script_topics,
                                              blacklist=blacklist)
    for rid, record in lowered.items():
        print(f"{rid}: {record['verdict_before']} -> {FREE_VERDICT} "
              f"(no content-sensitivity flag; the rights-holder match is "
              f"information only, {TASK})")
    if blacklist.get("error"):
        print(f"list not read, no evidence added ({EVIDENCE_TASK}): {blacklist['error']}")
    if not dry_run:
        path.write_text(json.dumps(new_doc, indent=2, ensure_ascii=False) + "\n")
    rows = sum(len(new_doc.get(k) or []) for k in ("results", "reserve")
               if isinstance(new_doc.get(k), list))
    print(f"\n{rows} row(s), {len(lowered)} verdict(s) lowered to {FREE_VERDICT}"
          + (" (dry run, nothing written)" if dry_run else ""))
    return 0


@runlog.script("compliance-checker", "rights-holder-info",
               name="rights_holder_info.py")
def cli():
    """The command-line entry (CF-0107 accounting, same shape as
    `cut_shortlist.py`). Pure Python over one JSON file - no child events."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
