"""CF-0575: the words that retell the hunter's on-screen scene are counted on
the event's own footage, before the voice - and a pool that does not hold
enough of it asks for more (CF-0345, `event_footage_short`).

**Why.** WNL `pipeline/example-film/2026-10-05T0701Z`: the Video Editor's
CF-0545 rule took the Late Night interview (`d7b1ilF5290`) out from under the
words about Taylor Sterling walking into Dana Reyes's monologue - and the
monologue (`KTe9OatvQas`) had 8 shots. Four went to the first blocks; "my
literal therapist" and the shout-out stood on a Kart Rally trailer and the
cold open: the work's own, not the monologue. This stage's pool gates had
said `pass` (52 distinct samples, 45 over the anchors) because they counted
the interview's fifty. The answer to "the event's own footage is short" is
more of it, and only this stage can still ask: the supplement step
(`scripts/thin_pool_supplement.py`) runs after it and before the Editor.

**The rule is the root's.** Which sources are the event and which anchors
retell it is `shared/event_footage.py` (`scope()`), the same module the
Editor's `scripts/event_footage.py` loads - this file keeps no copy and a
root without it is an error, like `_factrule.py`.

**What changes here** (`check_anchor_coverage.py`, before any gate reads the
preflight):

  * `narrow()` - every anchor of the scene keeps only the samples of the
    event's own sources; an anchor left with none is `absent`
    (`cause: event_footage`). The report written with `--out` is the narrowed
    one, so `check_block_capacity.py` and `check_two_sources.py` count the
    same pool, and `anchor_coverage_pool`'s distinct samples are recounted;
  * `judge()` - gate `event_footage`: the event's distinct samples against
    `SHOTS_PER_EVENT_BLOCK` per anchor of the scene. Short (or an anchor of
    the scene with no event sample, or no own source at all) is a warning
    `event_footage_short` carrying a supplement block (`_supplement_request
    .from_event()`): the work and the event, natures `episode`/`trailer`, not
    `interview`.

`SHOTS_PER_EVENT_BLOCK = 2`: a block is not one frame stretched (CF-0480 - a
block whose one shot would stand still takes 2-3 shots of its own phrase) and
a sample is used once (CF-0121). 0701Z is the measure: six distinct samples
of the monologue carried four of its five blocks, and the fifth went to
another segment.

The rule is off - and the record says why - wherever the Editor's is off
(no scene, a statement, no interview of another production in the pool).
"""
import copy
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

SHARED_REL = Path("shared") / "event_footage.py"
TASK = "CF-0575"
RECORD_KEY = "event_footage_capacity"
WARNING_CODE = "event_footage_short"
CAUSE = "event_footage"
SHOTS_PER_EVENT_BLOCK = 2
NATURES_WANTED = ("episode", "trailer")
NATURES_REFUSED = ("interview",)
ACTION_PASS, ACTION_WARN, ACTION_OFF, ACTION_REWRITE = "pass", "warn", "off", "rewrite"

_module = None


def rule():
    """The root's `shared/event_footage.py`, loaded once by path."""
    global _module
    if _module is None:
        try:
            path = factory_root() / SHARED_REL
        except RuntimeError:
            path = None
        if path is None or not path.is_file():
            raise RuntimeError(f"{SHARED_REL} was not found at the factory root ({TASK}): "
                               f"this repository keeps no copy of the event-footage rule")
        spec = importlib.util.spec_from_file_location("event_footage_shared", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ORIGIN = str(path)
        _module = mod
    return _module


def anchor_texts(script):
    """Each anchor's spoken words (`beat_text`) - what the Editor's
    `block_rule()` reads off the voice, here before there is one."""
    return [str((a or {}).get("beat_text") or "") if isinstance(a, dict) else ""
            for a in (script or {}).get("visual_anchors") or []]


def footage_dir(pool):
    """Where the pool's shot indexes (and the registry `index.json`) live."""
    for index in (pool or {}).get("indexes") or []:
        return Path(index).parent
    return None


def anchor_phrases(script):
    """Each anchor's picture (`phrase`) - CF-0576 reads it beside its words."""
    return [str((a or {}).get("phrase") or "") if isinstance(a, dict) else ""
            for a in (script or {}).get("visual_anchors") or []]


def anchor_samples(script, report):
    """Each anchor's distinct samples in the preflight's report *before*
    `narrow()` (best first) - which shot of the pool its phrase describes
    (CF-0576). None without a report."""
    if not report:
        return None
    by_index = {a.get("anchor_index"): a.get("samples") or []
                for a in report.get("anchors") or [] if isinstance(a, dict)}
    return [list(by_index.get(i) or []) for i in range(len(anchor_texts(script)))]


def scope_for(script, batch_dir, pool, report=None):
    """`shared/event_footage.scope()` for one script against its topic's pool
    (with the anchors' pictures and, given the preflight's report, their best
    shots - CF-0576)."""
    ef = rule()
    hunter, registry, reqs = ef.batch_inputs(batch_dir, footage_dir(pool))
    return ef.scope(script, list((pool or {}).get("video_ids") or []),
                    anchor_texts(script), hunter, registry, reqs,
                    phrases=anchor_phrases(script), samples=anchor_samples(script, report))


def _source(sample):
    return rule().source_id(sample)


def narrow(report, scope):
    """A copy of the preflight's report in which every anchor of the scene
    keeps only the event's own samples. Unchanged (the same object) when the
    rule is not active."""
    if not report or not (scope or {}).get("active"):
        return report
    keep = set(scope.get("event_sources") or [])
    event = set(scope.get("event_anchors") or [])
    out = copy.deepcopy(report)
    dropped_total = 0
    for a in out.get("anchors") or []:
        if not isinstance(a, dict) or a.get("anchor_index") not in event:
            continue
        samples = list(a.get("samples") or [])
        kept = [s for s in samples if _source(s) in keep]
        dropped = [s for s in samples if _source(s) not in keep]
        a["event_footage"] = {"task": TASK, "event_sources": sorted(keep),
                              "dropped": dropped}
        dropped_total += len(dropped)
        a["samples"] = kept
        if isinstance(a.get("survivors"), int):
            a["survivors"] = len(kept)
        if not kept and a.get("verdict") != "absent":
            a["verdict"], a["covered"], a["cause"] = "absent", False, CAUSE
            a["detail"] = (f"no sample of the event's own source(s) "
                           f"({', '.join(sorted(keep)) or 'none'}) - {TASK}")
    anchors = [a for a in out.get("anchors") or [] if isinstance(a, dict)]
    out["absent"] = [a["anchor_index"] for a in anchors if a.get("verdict") == "absent"]
    out["covered_count"] = sum(1 for a in anchors if a.get("verdict") == "covered")
    because = [b for b in out.get("refused_because") or [] if b != "absent_anchors"]
    if out["absent"]:
        because.insert(0, "absent_anchors")
    out["refused_because"] = because
    out["passed"] = not because
    distinct = set()
    for a in anchors:
        distinct.update(a.get("samples") or [])
    if isinstance(out.get("contention"), dict):
        before = out["contention"].get("distinct_samples")
        out["contention"]["distinct_samples"] = len(distinct)
        out["contention"]["note"] = (f"{out['contention'].get('note') or ''} - {len(distinct)} "
                                     f"after the scene's anchors kept only the event's own "
                                     f"footage ({TASK}; {before} before)").lstrip(" -")
    out["event_footage"] = {"task": TASK, "event_sources": sorted(keep),
                            "event_anchors": sorted(event), "samples_dropped": dropped_total}
    return out


def judge(script, report, scope):
    """Gate `event_footage`: is the event's own footage enough for the
    anchors that retell it? A record, never a refusal (CF-0330)."""
    scope = scope or {}
    rec = {"task": TASK, "topic_id": (script or {}).get("topic_id"),
           "scene_id": scope.get("scene_id"), "moment": scope.get("moment"),
           "active": bool(scope.get("active")),
           "needs_supplement": bool(scope.get("needs_supplement")),
           "why_rule": scope.get("why"),
           "event_sources": list(scope.get("event_sources") or []),
           "event_sources_why": scope.get("event_sources_why"),
           "interview": list(scope.get("interview") or []),
           "event_anchors": list(scope.get("event_anchors") or []),
           "shots_per_event_block": SHOTS_PER_EVENT_BLOCK}
    if not (rec["active"] or rec["needs_supplement"]):
        rec.update(action=ACTION_OFF, reason=f"the event-footage rule is off: {scope.get('why')}")
        return rec
    event = set(rec["event_anchors"])
    samples, uncovered = set(), []
    for a in (report or {}).get("anchors") or []:
        if not isinstance(a, dict) or a.get("anchor_index") not in event:
            continue
        mine = [s for s in a.get("samples") or [] if _source(s) in set(rec["event_sources"])]
        samples.update(mine)
        if not mine:
            uncovered.append(a.get("anchor_index"))
    need = SHOTS_PER_EVENT_BLOCK * len(event)
    rec.update(distinct_event_samples=len(samples), need=need,
               short_by=max(0, need - len(samples)), uncovered=sorted(uncovered))
    if not event:
        rec.update(action=ACTION_PASS, short_by=0,
                   reason="no anchor's words retell the scene - nothing to count")
        return rec
    if rec["needs_supplement"]:
        rec.update(action=ACTION_WARN, short_by=need, uncovered=sorted(event),
                   reason=(f"scene {rec['scene_id']} is a moment on screen and the pool holds "
                           f"no source of the work's own - {len(event)} anchor(s) retell it "
                           f"on no footage of it; the event's footage wants a supplement"))
        return rec
    moment = rec["moment"] or "event"
    if rec["short_by"] or uncovered:
        rec.update(action=ACTION_WARN, reason=(
            f"the {moment} ({', '.join(rec['event_sources'])}) gives "
            f"{len(samples)} distinct usable sample(s) to the {len(event)} anchor(s) "
            f"that retell it - {need} wanted ({SHOTS_PER_EVENT_BLOCK} a block)"
            + (f", anchor(s) {', '.join(str(i) for i in uncovered)} with none" if uncovered else "")
            + "; the event's footage wants a supplement (CF-0345), not another "
              "segment or an interview under its words"))
    else:
        rec.update(action=ACTION_PASS, reason=(
            f"the {moment} ({', '.join(rec['event_sources'])}) gives {len(samples)} "
            f"distinct usable sample(s) to the {len(event)} anchor(s) that retell it "
            f"- at or over the {need} wanted"))
    return rec


def numbers(rec):
    return {k: rec.get(k) for k in ("event_anchors", "event_sources", "distinct_event_samples",
                                     "need", "short_by", "uncovered")}


def lines(rec):
    if not rec or rec.get("action") == ACTION_OFF:
        return []
    out = [f"    event footage ({TASK}): {rec.get('action')} - {rec.get('reason')}"]
    if rec.get("active"):
        out.append(f"      event sources: {rec.get('event_sources_why')}")
    return out


# --------------------------------------------------------------------------
# CF-0576: the writer does not ask for another production's interview under
# words that are not about it
# --------------------------------------------------------------------------
#
# WNL 0701Z: the payoff "One monologue, two different segments worth
# remembering" had anchor v7 "Sam Meadows in a white tuxedo jacket and Dakota
# Reyes ... meet and shake hands" (and the direction "closing on the Seth
# Meyers greeting from Reyes's press run"). The Editor's CF-0545 rule
# refuses the Late Night interview under those words, so the block was always
# going to stand on something its anchor does not name. An anchor whose
# phrase pictures an interview of another production (`shared/event_footage
# .interview_anchor()`: its show or host; its best shot in the preflight is
# that interview's; or interview / talk-show words with no best shot) is
# allowed only on a beat whose words name it - "interview", "talk show", the
# show or its host.
#
# The ladder is CF-0437's (the visual claim): the first time it is a rewrite
# - the text and the anchors can still change here, and the answer is one of
# two edits: point the anchor at a frame of the event, or put the interview on
# words that say it is one. After that one rewrite it is a warning
# (`foreign_interview_anchor`), the script goes on - the Editor's rule keeps
# the interview out of the block either way.

INTERVIEW_TASK = "CF-0576"
INTERVIEW_RECORD_KEY = "interview_anchor_check"
INTERVIEW_GATE = "interview_anchor"
INTERVIEW_WARNING_CODE = "foreign_interview_anchor"
INTERVIEW_REWRITES_ALLOWED = 1
INTERVIEW_PREDICTS = "video_editor: event_footage refuses the interview under these words"


def _failed(script):
    before = (script or {}).get(INTERVIEW_RECORD_KEY)
    n = before.get("failed_attempts") if isinstance(before, dict) else 0
    return n if isinstance(n, int) and not isinstance(n, bool) else 0


def foreign_anchors(script, scope):
    """The anchors whose phrase pictures another production's interview under
    words that do not name it: [{anchor_index, anchor_id, phrase, beat_text, why}]."""
    anchors = (script or {}).get("visual_anchors") or []
    out = []
    by_index = {a.get("anchor_index"): a for a in (scope or {}).get("anchors") or []}
    for i in (scope or {}).get("foreign_interview_anchors") or []:
        a = anchors[i] if i < len(anchors) and isinstance(anchors[i], dict) else {}
        out.append({"anchor_index": i, "anchor_id": a.get("anchor_id"),
                    "phrase": a.get("phrase"), "beat_text": a.get("beat_text"),
                    "why": ((by_index.get(i) or {}).get("interview_picture") or {}).get("why")})
    return out


def direction_names_interview(script, scope):
    """The interview's show or host named in the script's `scene_direction`
    (0701Z: "closing on the Sam Meadows greeting from Reyes's press run") -
    part of the same rewrite when an anchor is foreign."""
    sd = (script or {}).get("scene_direction")
    text = sd.get("description") if isinstance(sd, dict) else sd
    t = rule().norm(text)
    return [n for n in (scope or {}).get("show_names") or [] if rule()._contains(t, n)]


def interview_judgement(script, scope):
    """Gate `interview_anchor` (CF-0576): `off` where the event-footage rule
    is off, `pass`, `rewrite` the first time, `warn` after the one rewrite."""
    scope = scope or {}
    failed = _failed(script)
    rec = {"task": INTERVIEW_TASK, "failed_attempts": failed,
           "rewrites_allowed": INTERVIEW_REWRITES_ALLOWED,
           "interview": list(scope.get("interview") or []),
           "show_names": list(scope.get("show_names") or [])}
    if not (scope.get("active") or scope.get("needs_supplement")):
        rec.update(action=ACTION_OFF, reason=f"the event-footage rule is off: {scope.get('why')}")
        return rec
    foreign = foreign_anchors(script, scope)
    rec["anchors"] = foreign
    if not foreign:
        rec.update(action=ACTION_PASS, reason=(
            "no anchor pictures another production's interview under words that do "
            "not name it"))
        return rec
    named = direction_names_interview(script, scope)
    if named:
        rec["scene_direction_names"] = named
    ids = ", ".join(str(a.get("anchor_id") or a.get("anchor_index")) for a in foreign)
    what = (f"anchor(s) {ids} picture the interview of another production "
            f"({', '.join(rec['interview'])}) under words that retell scene "
            f"{scope.get('scene_id')} - the Editor refuses that interview there (CF-0545)")
    if failed < INTERVIEW_REWRITES_ALLOWED:
        rec.update(action=ACTION_REWRITE, failed_attempts=failed + 1, reason=(
            f"interview anchor: {what}; point each at a frame of the event, or put it on "
            f"words that name the interview (\"interview\", \"talk show\", the show or "
            f"its host)"
            + (f"; the scene_direction names it too ({', '.join(named)})" if named else "")
            + f"; one rewrite, then it is a warning and the script goes on ({INTERVIEW_TASK})"))
        return rec
    rec.update(action=ACTION_WARN, reason=(
        f"interview anchor: {what} - still after the one rewrite; a warning, the script "
        f"goes on, the Editor keeps the interview out of the block ({INTERVIEW_TASK})"))
    return rec


def interview_detail(rec):
    return " | ".join(f"{a.get('anchor_id')} «{a.get('phrase')}» under «{a.get('beat_text')}»: "
                      f"{a.get('why')}" for a in (rec or {}).get("anchors") or [])


def interview_lines(rec):
    if not rec or rec.get("action") in (ACTION_OFF, ACTION_PASS):
        return []
    return [f"    interview anchor ({INTERVIEW_TASK}): {rec.get('action')} - "
            f"{interview_detail(rec)}"]
