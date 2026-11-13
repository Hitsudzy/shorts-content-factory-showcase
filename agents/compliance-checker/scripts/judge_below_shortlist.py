#!/usr/bin/env python3
"""CF-0882: the compliance half of the refill from below the shortlist.

    judge_below_shortlist.py judge <batch> --topics id1,id2,... --result <path> [--round R]
    judge_below_shortlist.py admit <batch> --topics id1,id2,... --round first|late|judge
                                   --result <path>

Why. A batch substitutes a lost slot from `02-compliance-checker.json ->
reserve[]` - the shortlist (8) less the cut (5), three topics. When those are
spent the slot stayed empty while viable topics below the shortlist
(`01-trend-hunter.json -> skipped_topics[]`, `reason_code: below_shortlist`,
CF-0264: fact-probed, ranked, no slot) were never touched (the funnel of
20-27.10: 6 empty slots, Reel 21 and Tech 15 such topics). The root's round
(`shared/below_shortlist.py promote`, the plan stages
`reserve-below-shortlist{,-late,-judge}`) now takes them - and nothing reaches
the batch that compliance has not seen. This script is that seam, two steps:

**judge** - a verdict on the fly, with no model. The same rules the pass over
the shortlist applies, the deterministic part of them:

* the rights-holder match (CF-0420) is information: written with
  `affects_verdict: false` and its CF-0600 evidence, it moves nothing;
* a machine screen for the SKILL's forbidden topics (drugs, murder and the
  like, tragedy for shock, a political flashpoint, a private individual
  targeted) over `scenes[].description/tags` and the topic's news headlines
  (`evidence.sources[].title`; a topic below the shortlist usually has no
  scenes yet). The work's own name is taken out first: a show called
  "Only Murders in the Building" is not a murder.

A hard term -> `outcome: refused`: the topic is not taken
(the queue has the next one, and a `review` would make a video nobody may
upload unsigned), and the refusal is appended to `02 -> refill_refused[]` so
the root never offers it again. A soft term (scandal, lawsuit, feud ...) ->
`eligible` at `caution`; nothing -> `eligible` at `clear`. `decided_by` says
it was this script: the full reading of the content stays with the pass over
the scripts (`compliance-scripts`, 04), which judges the written text as for
any topic. `results[]` and `reserve[]` are not touched here.

**admit** - for the topics Trend Hunter gave a pool (moved into `01 ->
topics[]` with `refill`): the same verdict, re-read from the topic as it is
now, written into `02 -> reserve[]` with `reason_code: reserve_unused`, a
one-line `reason` and `"refill": {"task": "CF-0882", "round": R}` - the mark
by which the root's `stopcock._remaining_reserve` sees them after `01b
remaining[]` and the Footage Indexer's reserve round takes them. `results[]`
is not touched (reserve is not results, CF-0265); the `cut` record counts the
rows (`cut.reserve` = the rows in `reserve[]`, `cut.refill`). Then
`sensitivity_scenes.py` checks the flags name their scenes (CF-0846) and
`publication_hold.py` stamps any `review` (none can come from here today, but
the step is the pass's and costs nothing - CF-0318). A topic admitted before
is not written twice.

Both write `{"topics": [...]}` to `--result` and exit 0 when they wrote it;
the root reads only that file and `02`.
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _runlog import runlog  # noqa: E402
from _cli import screen as screen_argv  # noqa: E402
import rights_holder_info as rhi  # noqa: E402
import cut_shortlist  # noqa: E402

TASK = "CF-0882"
DECIDED_BY = "script (CF-0882, on the fly)"
TREND_FILE = "01-trend-hunter.json"
COMPLIANCE_FILE = "02-compliance-checker.json"
BELOW_CODE = "below_shortlist"           # fact_probe_topics.OVERFLOW_CODE (CF-0264)
TOPIC_KEY = "topic"                      # fact_probe_topics.RESERVE_TOPIC_KEY (CF-0313)
REFILL_MARK = "refill"                   # shared/below_shortlist.py REFILL_MARK
REFUSED_KEY = "refill_refused"
TH_LOG_KEY = "below_shortlist_refill"    # 01 -> below_shortlist_refill[] (Trend Hunter's half)
ROUNDS = ("first", "late", "judge")
RESERVE_CODE = cut_shortlist.RESERVE_CODE
SCREEN_CODE = "refill_screen"
ELIGIBLE, REFUSED = "eligible", "refused"
ADMITTED, SKIPPED = "admitted", "skipped"
WHOLE_TOPIC = "whole_topic"

# The SKILL's forbidden topics, the part a word can find. A hard term refuses
# the topic here; the pass over the shortlist would have read it and most
# likely written `review`, and a refill has the next topic in the queue.
HARD = {
    "drugs": r"\b(drugs?|cocaine|heroin|meth|methamphetamine|fentanyl|opioids?|narcotics?|"
             r"overdos(?:e|ed|es|ing)|drug[- ]dealing)\b|наркот",
    "murder and the like": r"\b(murder(?:s|ed|er|ers|ing)?|homicides?|killings?|"
                           r"killed(?!\s+off)|slain|stabb(?:ed|ing)|shot dead|"
                           r"(?:mass|fatal) shooting|massacre|manslaughter|rape[ds]?|"
                           r"sexual assault|kidnapp?(?:ed|ing)|terror(?:ism|ist|ists)?)\b"
                           r"|убий|убит|изнасил",
    "tragedy for shock": r"\b(died|dies|dead at|death of|passed away|obituary|suicide|"
                         r"tragic(?:ally)?|tragedy|funeral|fatal)\b|умер|смерт|суицид|трагед",
    "political flashpoint": r"\b(trump|biden|kamala|vance|putin|zelensky[iy]?|netanyahu|gaza|"
                            r"israel(?:i|is)?|palestin\w*|hamas|ukraine|election|maga|"
                            r"abortion|immigration|white house|congress(?:man|woman)?|"
                            r"senat(?:e|or))\b|трамп|путин|выбор(?:ы|ах|ов)|войн",
    "a private individual targeted": r"\b(private (?:citizen|individual|person)|doxx\w*)\b",
}
# A soft term: the topic may go on, kept analytical - `caution`, as the pass
# writes for a soft content-sensitivity flag. A `controversial` tag on its own
# is not one (SKILL step 2).
SOFT = {
    "scandal or dispute": r"\b(scandals?|lawsuits?|sued|sues|arrest(?:ed)?|feuds?|backlash|"
                          r"allegations?|accus(?:ed|es|ations?)|misconduct|harass\w*|"
                          r"racis[mt]\w*|boycott\w*|protests?)\b|скандал|иск\b",
    "violence": r"\b(violen(?:ce|t)|gore|gory|bloody|bloodbath|brutal(?:ly)?)\b",
}
_HARD = {k: re.compile(v, re.I) for k, v in HARD.items()}
_SOFT = {k: re.compile(v, re.I) for k, v in SOFT.items()}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _id(row):
    return (row.get("topic_id") or row.get("id")) if isinstance(row, dict) else None


def factory_root_of(batch):
    """`<root>` of a batch at `<root>/pipeline/<channel>/<id>`, else None (the
    scripts then find the root the way they always do)."""
    b = Path(batch).resolve()
    return b.parent.parent.parent if b.parent.parent.name == "pipeline" else None


# --------------------------------------------------------------------------
# where a topic is
# --------------------------------------------------------------------------
def below_rows(t01):
    """`{topic_id: row}` of the `below_shortlist` rows of 01."""
    out = {}
    for row in (t01 or {}).get("skipped_topics") or []:
        if isinstance(row, dict) and row.get("reason_code") == BELOW_CODE and _id(row):
            out.setdefault(_id(row), row)
    return out


def below_topic(row):
    """The topic record a `below_shortlist` row keeps (CF-0313), else a
    stand-in from the row's summary (an artifact older than CF-0313)."""
    topic = row.get(TOPIC_KEY)
    if isinstance(topic, dict) and _id(topic):
        return topic
    return {"topic_id": _id(row), "title_ref": {"name": row.get("title"), "kind": row.get("kind")}}


def promoted_topic(t01, tid):
    """The `01 -> topics[]` record Trend Hunter put back from below the
    shortlist (marked `refill`, or named in `below_shortlist_refill[]` with a
    pool), else None."""
    walked = {_id(r) for r in (t01 or {}).get(TH_LOG_KEY) or []
              if isinstance(r, dict) and r.get("outcome") == "candidates"}
    for topic in (t01 or {}).get("topics") or []:
        if isinstance(topic, dict) and _id(topic) == tid \
                and (topic.get(REFILL_MARK) or tid in walked):
            return topic
    return None


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------
def _texts(topic, title=None):
    """`[(where, text)]` the screen reads: each scene's description and tags
    (where = its scene_id), the topic's title and its news headlines (where =
    the whole topic). The work's own name is cut out of every text."""
    ref = topic.get("title_ref") if isinstance(topic.get("title_ref"), dict) else {}
    names = []
    if (ref.get("kind") or "") != "person":
        names = [n for n in (ref.get("name"), ref.get("parent_work"), title)
                 if isinstance(n, str) and len(n.strip()) > 2]
    out = []
    for scene in topic.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        sid = scene.get("scene_id") or WHOLE_TOPIC
        tags = " ".join(t for t in scene.get("tags") or [] if isinstance(t, str))
        out.append((sid, f"{scene.get('description') or ''} {tags}"))
    if ref.get("kind") == "person" or ref.get("person"):
        out.append((WHOLE_TOPIC, " ".join(str(x) for x in (ref.get("person"), ref.get("name"))
                                          if x)))
    evidence = topic.get("evidence") if isinstance(topic.get("evidence"), dict) else {}
    for src in evidence.get("sources") or []:
        if isinstance(src, dict) and isinstance(src.get("title"), str):
            out.append((WHOLE_TOPIC, src["title"]))
    cleaned = []
    for where, text in out:
        for n in sorted(names, key=len, reverse=True):
            text = re.sub(re.escape(n.strip()), " ", text, flags=re.I)
        cleaned.append((where, text))
    return cleaned


def screen(topic, title=None):
    """`{"hard": [hit], "soft": [hit]}`, a hit `{category, term, where}`."""
    hits = {"hard": [], "soft": []}
    for where, text in _texts(topic, title):
        for kind, table in (("hard", _HARD), ("soft", _SOFT)):
            for category, rx in table.items():
                m = rx.search(text)
                if m:
                    hits[kind].append({"category": category, "term": m.group(0),
                                       "where": where})
    return hits


def _scenes(hits):
    wheres = {h["where"] for h in hits}
    if not wheres or WHOLE_TOPIC in wheres:
        return WHOLE_TOPIC
    return sorted(wheres)


def _hit_text(hits):
    return "; ".join(f"{h['category']}: {h['term']!r} in "
                     f"{'a headline/the topic' if h['where'] == WHOLE_TOPIC else h['where']}"
                     for h in hits)


def sensitivity_check(hits):
    flagged = hits["hard"] or hits["soft"]
    if not flagged:
        return {"flagged": False, "task": TASK,
                "notes": ("Machine screen on the fly (CF-0882): none of the forbidden-topic "
                          "terms in the scenes or the headlines. The full reading of the "
                          "content is the pass over the scripts (04).")}
    use = hits["hard"] or hits["soft"]
    return {"flagged": True, "task": TASK, "scenes": _scenes(use),
            "screen": {"hard": hits["hard"], "soft": hits["soft"]},
            "notes": (f"Machine screen on the fly (CF-0882), "
                      f"{'forbidden topic' if hits['hard'] else 'soft flag'}: "
                      f"{_hit_text(use)}.")}


def rights_check(title_ref, blacklist):
    """The rights-holder check as the pass writes it - looked up in the
    channel's list, information only (CF-0420)."""
    ref = title_ref if isinstance(title_ref, dict) else {}
    entry, _others = rhi.blacklist_match({"matched": True}, ref, blacklist)
    if entry is not None:
        return {"matched": entry.get("rights_holder"), "risk_level": entry.get("risk_level"),
                "reason": entry.get("reason") or "", "affects_verdict": False}
    holder = ref.get("rights_holder")
    why = (f"no entry of the channel's list answers to {holder!r}"
           + (f" or the network {ref.get('network')!r}" if ref.get("network") else "")
           if holder or ref.get("network") else
           "title_ref.rights_holder is null and no network is named - nothing to look up")
    if blacklist.get("error"):
        why += f" (list not read: {blacklist['error']})"
    return {"matched": False, "risk_level": None, "reason": why, "affects_verdict": False}


def verdict_row(topic, title, blacklist):
    """`(row, outcome, reason)` - the full verdict record of one topic."""
    tid = _id(topic)
    ref = topic.get("title_ref") if isinstance(topic.get("title_ref"), dict) else {}
    hits = screen(topic, title)
    verdict = "review" if hits["hard"] else "caution" if hits["soft"] else "clear"
    row = {"topic_id": tid, "verdict": verdict,
           "rights_holder_check": rights_check(ref, blacklist),
           "content_sensitivity_check": sensitivity_check(hits),
           "decided_by": DECIDED_BY, "task": TASK}
    if hits["hard"]:
        return row, REFUSED, (f"forbidden topic on the machine screen - {_hit_text(hits['hard'])}; "
                              f"not taken from below the shortlist (a `review` would make a "
                              f"video nobody may upload unsigned, and the queue has the next)")
    if hits["soft"]:
        return row, ELIGIBLE, f"caution: {_hit_text(hits['soft'])} - keep the treatment analytical"
    return row, ELIGIBLE, "clear: no forbidden-topic term"


class Context:
    """One batch: its 01 and 02 and the channel's list, each read once."""

    def __init__(self, batch):
        self.batch = Path(batch)
        self.t01 = _read(self.batch / TREND_FILE) or {}
        self.c02_path = self.batch / COMPLIANCE_FILE
        self.c02 = _read(self.c02_path)
        self.channel = rhi.batch_channel(self.c02_path)
        self.blacklist = rhi.read_blacklist(self.channel)


def _refuse(doc, row, reason, rnd=None):
    """Append one refusal to `02 -> refill_refused[]` (once per topic)."""
    rows = doc.setdefault(REFUSED_KEY, [])
    if any(_id(r) == _id(row) for r in rows if isinstance(r, dict)):
        return False
    rec = {"topic_id": _id(row), "verdict": row.get("verdict"), "reason": reason,
           "reason_code": SCREEN_CODE,
           "decided_by": DECIDED_BY, "task": TASK, "at": _now(),
           "content_sensitivity_check": row.get("content_sensitivity_check")}
    if rnd:
        rec["round"] = rnd
    rows.append(rec)
    return True


def judge(batch, ids, rnd=None):
    """`[{topic_id, verdict, outcome, reason}]`; refusals into
    `02 -> refill_refused[]`."""
    ctx = Context(batch)
    below = below_rows(ctx.t01)
    out, refused = [], []
    for tid in ids:
        row = below.get(tid)
        if row is None:
            out.append({"topic_id": tid, "verdict": None, "outcome": REFUSED,
                        "reason": f"not a {BELOW_CODE} topic of {TREND_FILE} - nothing to judge"})
            continue
        vrow, outcome, reason = verdict_row(below_topic(row), row.get("title"),
                                            ctx.blacklist)
        out.append({"topic_id": tid, "verdict": vrow.get("verdict"), "outcome": outcome,
                    "reason": reason, "decided_by": DECIDED_BY})
        if outcome == REFUSED:
            refused.append((vrow, reason))
    if refused and isinstance(ctx.c02, dict):
        for vrow, reason in refused:
            _refuse(ctx.c02, vrow, reason, rnd)
        _write(ctx.c02_path, ctx.c02)
    return out


# --------------------------------------------------------------------------
# admit
# --------------------------------------------------------------------------
def admit_reason(rnd, rank, verdict):
    return (f"Admitted from below the shortlist (CF-0882, round {rnd}): rank {rank} in "
            f"{TREND_FILE}, verdict {verdict!r} on the fly by script, given a footage pool by "
            f"Trend Hunter's step 5b - reserve for a slot the batch lost when its own reserve "
            f"was spent; the pass over the scripts (04) reads it in full.")


def admit(batch, ids, rnd):
    """`([{topic_id, outcome, reason}], 02 written?, channel)`; rows into
    `02 -> reserve[]`."""
    ctx = Context(batch)
    if not isinstance(ctx.c02, dict):
        return [{"topic_id": t, "outcome": SKIPPED, "reason": f"no readable {COMPLIANCE_FILE}"}
                for t in ids], False, ctx.channel
    reserve = ctx.c02.setdefault("reserve", [])
    results = ctx.c02.get("results") or []
    out, changed = [], False
    for tid in ids:
        have = next((r for r in reserve if isinstance(r, dict) and _id(r) == tid), None)
        if have is not None and have.get(REFILL_MARK):
            out.append({"topic_id": tid, "outcome": SKIPPED,
                        "reason": f"already admitted (round {(have[REFILL_MARK] or {}).get('round')})"})
            continue
        if have is not None or any(isinstance(r, dict) and _id(r) == tid for r in results):
            out.append({"topic_id": tid, "outcome": SKIPPED,
                        "reason": "judged by the pass over the shortlist already - not a refill"})
            continue
        topic = promoted_topic(ctx.t01, tid)
        if topic is None:
            out.append({"topic_id": tid, "outcome": SKIPPED,
                        "reason": (f"not in {TREND_FILE} topics[] as a refill - Trend Hunter "
                                   f"gave it no pool")})
            continue
        vrow, outcome, reason = verdict_row(topic, None, ctx.blacklist)
        if outcome != ELIGIBLE:
            changed |= _refuse(ctx.c02, vrow, reason, rnd)
            out.append({"topic_id": tid, "outcome": SKIPPED, "reason": f"refused: {reason}"})
            continue
        rank = topic.get("rank") or next((r.get("rank") for r in (ctx.t01.get("skipped_topics") or [])
                                          if isinstance(r, dict) and _id(r) == tid), None)
        vrow["reason_code"] = RESERVE_CODE
        vrow["reason"] = admit_reason(rnd, rank if rank is not None else "?", vrow["verdict"])
        vrow[REFILL_MARK] = {"task": TASK, "round": rnd, "at": _now()}
        reserve.append(vrow)
        changed = True
        out.append({"topic_id": tid, "outcome": ADMITTED, "verdict": vrow["verdict"],
                    "reason": reason})
    if changed:
        cut = ctx.c02.get(cut_shortlist.CUT_KEY)
        if isinstance(cut, dict):
            cut["reserve"] = len(reserve)
            cut[REFILL_MARK] = {"task": TASK,
                                "admitted": sum(1 for r in reserve
                                                if isinstance(r, dict) and r.get(REFILL_MARK))}
        _write(ctx.c02_path, ctx.c02)
    return out, changed, ctx.channel


def after_admit(batch, channel):
    """Step 4a and 4d of the pass over the file just written: the flags name
    their scenes (CF-0846), the holds are stamped (CF-0318). `{step: exit}`."""
    import publication_hold  # noqa: PLC0415
    import sensitivity_scenes  # noqa: PLC0415
    path = str(Path(batch) / COMPLIANCE_FILE)
    codes = {"sensitivity_scenes": sensitivity_scenes.main([path])}
    argv = [path] + ([channel] if channel else [])
    root = factory_root_of(batch)
    if root is not None:
        argv += ["--root", str(root)]
    codes["publication_hold"] = publication_hold.main(argv)
    return codes


# --------------------------------------------------------------------------
# the command line
# --------------------------------------------------------------------------
def _ids(raw):
    out = []
    for t in (raw or "").split(","):
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out


USAGE = ("usage: judge_below_shortlist.py judge <batch> --topics id1,id2,... --result <path> "
         "[--round first|late|judge]\n"
         "       judge_below_shortlist.py admit <batch> --topics id1,id2,... "
         "--round first|late|judge --result <path>\n"
         "  CF-0882: the compliance half of the refill from below the shortlist - judge "
         "the topics on the fly (refusals into 02 -> refill_refused[]), admit the ones "
         "Trend Hunter gave a pool into 02 -> reserve[] (marked `refill`).")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    rc = screen_argv(argv, USAGE, valued=("--topics", "--result", "--round"))  # CF-0777
    if rc is not None:
        return rc
    ap = argparse.ArgumentParser(prog="judge_below_shortlist.py",
                                 description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("judge", "admit"):
        s = sub.add_parser(name)
        s.add_argument("batch")
        s.add_argument("--topics", required=True)
        s.add_argument("--result", required=True)
        s.add_argument("--round", choices=ROUNDS, required=name == "admit")
    ns = ap.parse_args(argv)
    batch = Path(ns.batch)
    if not batch.is_dir():
        print(f"no batch dir {batch}", file=sys.stderr)
        return 2
    ids = _ids(ns.topics)
    if ns.cmd == "judge":
        rows = judge(batch, ids, ns.round)
        for r in rows:
            print(f"{r['topic_id']}: {r['outcome']} ({r['verdict']}) - {r['reason']}")
        print(f"\n{len(rows)} judged on the fly, "
              f"{sum(r['outcome'] == ELIGIBLE for r in rows)} eligible, "
              f"{sum(r['outcome'] == REFUSED for r in rows)} refused ({TASK})")
    else:
        rows, changed, channel = admit(batch, ids, ns.round)
        for r in rows:
            print(f"{r['topic_id']}: {r['outcome']} - {r['reason']}")
        if changed:
            codes = after_admit(batch, channel)
            for step, code in codes.items():
                if code:
                    print(f"{step}: exit {code} - see above")
        print(f"\n{sum(r['outcome'] == ADMITTED for r in rows)} admitted into reserve[] "
              f"(round {ns.round}), {sum(r['outcome'] == SKIPPED for r in rows)} skipped ({TASK})")
    _write(ns.result, {"task": TASK, "command": ns.cmd, "batch": str(batch),
                       "at": _now(), "topics": rows})
    return 0


@runlog.script("compliance-checker", "judge-below-shortlist", name="judge_below_shortlist.py")
def cli():
    """CF-0107 accounting: main()'s return code is the exit code inside the run
    event. Pure Python over JSON files, no model, no child process."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
