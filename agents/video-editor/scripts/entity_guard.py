#!/usr/bin/env python3
"""CF-0348: a supplement source's shot without its entity is never placed.

A thin-pool supplement (CF-0338) is a source fetched *for an entity* - the
actor's other film, an interview - not for the topic's own work. The sieve
(footage-indexer `source_sieve.py`, CF-0344) keeps or refuses such a source
whole, and a kept one still brings shots that show neither the topic nor the
entity: a frame of Ocean's 8 without Sandra Birch in a video about Practical
Magic 2. For the viewer that is the same emptiness the rung was meant to fill,
only worse - it is somebody else's film.

So every rung that picks a picture (the regular match, CF-0337's topic
footage, CF-0137's emergency repeat, the split opening) skips such a shot, and
`qc_render.py` fails a plan that carries one anyway (DoD 4).

Which shots
-----------
A source is a supplement when the batch report (`<batch>/01b-footage-index.json`)
says so: its `source_sieve.sources[]` record reads `judged_by: entity`, or its
`fetched[]` record carries `supplement.entity`. For such a source a shot is
refused when

  * its number is in the sieve record's `off_topic_shots` (neither the
    topic's work nor the entity, as the indexer measured it), or
  * its shots.json entry carries the describer's `shows_entity: false`.

An ordinary source is never touched by that rule: no record, no rule.

CF-0351: the same chokepoint refuses somebody else's burned-in text
---------------------------------------------------------------------
A shot the describer marked `burned_text: true` (footage-indexer
`shot_schema.py`, CF-0299: a caption outside the bottom band, a title card, an
end card, a website screenshot - still there after the 9:16 crop) is refused
for *every* source, supplement or not: the user rejects foreign text in the
frame (DoD 2), and the sieve only ever counted it as a share of the whole
source, so a kept source still brought its title cards in (CF-0346: block 0
of everyday-sorcery-2 was `Ho10_4IX1jE:43`, a "Nora Kingsley" name card).
`refusal()` answers both questions, so every rung that already asked about
the entity asks about the text too.

`qc_render.py` cannot see that flag in a plan - the plan names `<id>:<n>`,
not the shot's entry - so it reads the entry from `<footage>/<id>.shots.json`
(`shot_reader()`), the describer's current answer; the same entry makes
`shows_entity: false` visible to it as well. Pure json work - no CLIP, no
ffmpeg.

CF-0354: an unanswered card counts as text
------------------------------------------
Two thirds of the pool was indexed before the describer was asked about
burned-in text (CF-0299), so the flag is simply absent there - and the rule
above refused exactly what was marked. After `Ho10_4IX1jE:43` went, block 0
of everyday-sorcery-2 took `QE0W5UW2qxE:20`: `is_card: true`, "a retro
website interface ... reading MovieLink", no `burned_text` at all. A card is
text or graphics in the frame by definition, so a shot with `is_card: true`
whose `burned_text` is missing or null is refused like a marked one, until
the describer answers `false`. A non-card without the flag is still let
through - an unasked shot is not a refused one; filling the flag in over the
old pool is the indexer's job. Priced on the two accepted videos
(outrider-doune-castle 1541Z, widows-bay 1053Z): 0 of their 34 shots.

CF-0567: our own screen recording is exempt by its kind
--------------------------------------------------------
A shot of the factory's own recording of a tool (`own_capture-<id>`, or a
shots.json entry with `source_kind: own_capture` - footage-indexer 14c4ff4)
shows the tool's interface, and its text is the footage, not somebody
else's caption (the root's frame-judge rule, the same day). The describer
still says `burned_text: true` there and FI keeps it under
`usability.exempt`; this rule exempts it by the source's kind -
`own_capture_exemption()` says so in a sentence, `screen_matches()` /
`plan_violations()` hand it back in `exempted` - and never by loosening the
flag for anybody else. The supplement rule (CF-0348) is untouched.
"""
import json
import re
from pathlib import Path

import _clip_names  # CF-0665: the source id in a clip name; CF-0567 own capture

REPORT_NAME = "01b-footage-index.json"
BURNED_TEXT = "burned_text"   # footage-indexer shot_schema.BURNED_TEXT
IS_CARD = "is_card"

try:  # the same id reading the two-source gate uses
    from source_gate import source_id
except ImportError:  # pragma: no cover - imported from another repo's path
    def source_id(value):
        return Path(str(value)).stem if value else None


def find_report(path, levels=5):
    """`<batch>/01b-footage-index.json` for a path inside the batch (a clips
    dir, a plan), found by walking up; None when there is none - a batch made
    before the file existed, or a scratch run outside any batch."""
    if not path:
        return None
    try:
        p = Path(path).resolve()
    except OSError:
        return None
    for d in [p, *p.parents][:levels + 1]:
        f = d / REPORT_NAME
        if f.is_file():
            return f
    return None


def load_report(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError, TypeError):
        return None


def supplements(report):
    """`{video_id: {"entity": name, "off": {shot numbers}}}` for every
    supplement source the report names. Empty for no report."""
    out = {}
    if not isinstance(report, dict):
        return out
    for f in report.get("fetched") or []:
        if not isinstance(f, dict):
            continue
        ent = (f.get("supplement") or {}).get("entity")
        if isinstance(ent, dict):
            ent = ent.get("name")
        if ent and f.get("video_id"):
            out.setdefault(f["video_id"], {"entity": ent, "off": set()})
    for rec in (report.get("source_sieve") or {}).get("sources") or []:
        if not isinstance(rec, dict) or rec.get("judged_by") != "entity":
            continue
        vid = rec.get("video_id")
        if not vid:
            continue
        sup = out.setdefault(vid, {"entity": rec.get("entity"), "off": set()})
        sup["entity"] = sup.get("entity") or rec.get("entity")
        for n in rec.get("off_topic_shots") or []:
            try:
                sup["off"].add(int(n))
            except (TypeError, ValueError):
                continue
    return out


def own_capture_exemption(source, shot_no, shot):
    """CF-0567: the sentence that a shot of our own recording keeps its text
    - None when the shot is not one, or carries no text flag to exempt."""
    if not isinstance(shot, dict):
        shot = {}
    flagged = shot.get(BURNED_TEXT) is True or (shot.get(IS_CARD) is True
                                                and shot.get(BURNED_TEXT) is None)
    if not flagged or not _clip_names.is_own_capture_shot(shot, source):
        return None
    vid = source_id(source) or source
    return (f"shot {vid}:{shot_no} is our own screen recording (own_capture) - "
            f"its interface text is the footage, not foreign burned-in text; "
            f"exempt from CF-0351/CF-0354 by its kind (CF-0567)")


def refusal(source, shot_no, shot, sups):
    """Why this shot may not be placed, or None. `source` is anything
    `source_id()` reads (a shots.json `source` path, a `<id>:<n>` key);
    `shot` the shots.json entry when the caller has it."""
    vid = source_id(source)
    try:
        n = int(shot_no)
    except (TypeError, ValueError):
        n = None
    own = _clip_names.is_own_capture_shot(shot, source)
    if isinstance(shot, dict) and shot.get(BURNED_TEXT) is True and not own:
        return (f"shot {vid}:{n} carries somebody else's burned-in text "
                f"(burned_text: true - a caption, a title or end card) that "
                f"the 9:16 crop does not remove (CF-0351)")
    if (isinstance(shot, dict) and shot.get(IS_CARD) is True
            and shot.get(BURNED_TEXT) is None and not own):
        return (f"shot {vid}:{n} is a card (is_card: true) nobody has "
                f"answered burned_text for - a card is text or graphics in "
                f"the frame, so it counts as burned-in text until the "
                f"describer marks it false (CF-0354, CF-0351)")
    if not sups:
        return None
    sup = sups.get(vid) if vid else None
    if sup is None:
        return None
    entity = sup.get("entity") or "its entity"
    if n is not None and n in sup["off"]:
        return (f"shot {vid}:{n} of supplement source {vid} shows neither the "
                f"topic's work nor {entity} (the sieve's off_topic_shots) - "
                f"another film's frame is not material of this topic (CF-0348)")
    if isinstance(shot, dict) and shot.get("shows_entity") is False:
        return (f"shot {vid}:{n} of supplement source {vid} does not show "
                f"{entity} (shows_entity: false) - another film's frame is "
                f"not material of this topic (CF-0348)")
    return None


def screen_matches(matches, index_data, sups, min_score=None, exempted=None):
    """Take every refused supplement shot out of each phrase's candidates, in
    place, before any rung sees them. Returns the refusals, one
    `{phrase, shot, score, reason}` per removed candidate. `found` is
    re-read over what is left, when `min_score` is given. CF-0351: runs
    with no supplement too - a burned-text shot is refused everywhere.
    CF-0567: `exempted`, when a list, receives `{phrase, shot, score,
    exempt: own_capture, reason}` for every own-capture shot kept despite its
    text flag."""
    refused = []
    lut = {}
    for idx, data in (index_data or {}).items():
        for s in data.get("shots", []) or []:
            lut[(idx, s.get("index"))] = s
    for m in matches:
        keep = []
        for c in m.get("candidates") or []:
            entry = lut.get((c.get("index"), c.get("shot")))
            why = refusal(c.get("source"), c.get("shot"), entry, sups)
            ex = None if why else own_capture_exemption(c.get("source"), c.get("shot"), entry)
            if ex and isinstance(exempted, list):
                exempted.append({"phrase": m.get("phrase"), "shot": c.get("shot"),
                                 "score": c.get("score"), "exempt": "own_capture",
                                 "reason": ex})
            if why:
                refused.append({"phrase": m.get("phrase"), "shot": c.get("shot"),
                                "score": c.get("score"), "reason": why})
            else:
                keep.append(c)
        if len(keep) != len(m.get("candidates") or []):
            m["candidates"] = keep
            if min_score is not None:
                m["found"] = bool(keep) and max(c["score"] for c in keep) >= min_score
    return refused




def _shot_refs(block):
    """`(key text, video id, shot number)` for every picture a plan block
    names: its `shot` key, the asset's, each side-by-side half's and each
    sequence cut's, and - for a piece that carries no key - the
    `<id>_s<n>` in its clip name."""
    refs = []

    def add(d):
        if not isinstance(d, dict):
            return
        key = d.get("shot")
        if key and ":" in str(key):
            src, n = str(key).rsplit(":", 1)
            refs.append((str(key), src, n))
            return
        for f in ("src", "clip", "asset"):
            v = d.get(f)
            if isinstance(v, str):
                hit = _clip_names.clip_shot(Path(v).stem)  # CF-0665
                if hit:
                    refs.append((f"{hit[0]}:{int(hit[1])}", hit[0], hit[1]))
                    return

    add(block)
    asset = block.get("asset") if isinstance(block.get("asset"), dict) else {}
    add(asset)
    for part in (asset.get("halves") or []) + (asset.get("cuts") or []):
        add(part)
    seen, out = set(), []
    for r in refs:
        if r[0] not in seen:
            seen.add(r[0])
            out.append(r)
    return out


def shot_reader(footage_dir):
    """`(video id, shot number) -> shots.json entry or None`, reading
    `<footage_dir>/<id>.shots.json` once per id. None for a missing or
    unreadable file - an unknown shot is not a refused one."""
    cache = {}

    def read(vid, n):
        if vid not in cache:
            lut = {}
            try:
                data = json.load(open(Path(footage_dir) / f"{vid}.shots.json"))
                for s in data.get("shots") or []:
                    if isinstance(s, dict) and s.get("index") is not None:
                        lut[int(s["index"])] = s
            except (OSError, ValueError, TypeError, AttributeError):
                pass
            cache[vid] = lut
        try:
            return cache[vid].get(int(n))
        except (TypeError, ValueError):
            return None
    return read


def plan_violations(plan, sups, shots_of=None, exempted=None):
    """The plan's blocks that show a refused shot:
    `[{"block": i, "shot": key, "reason": ...}]`. `shots_of` (`shot_reader()`)
    gives each shot's entry, so `burned_text` and `shows_entity` count too;
    without it only the report's `off_topic_shots` can refuse."""
    out = []
    if not sups and shots_of is None:
        return out
    for i, b in enumerate((plan or {}).get("blocks") or []):
        if not isinstance(b, dict):
            continue
        for key, src, n in _shot_refs(b):
            vid = source_id(src)
            shot = shots_of(vid, n) if shots_of and vid else None
            why = refusal(src, n, shot, sups)
            if why:
                out.append({"block": i, "shot": key, "reason": why})
            elif isinstance(exempted, list):
                ex = own_capture_exemption(src, n, shot)
                if ex:
                    exempted.append({"block": i, "shot": key, "exempt": "own_capture",
                                     "reason": ex})
    return out
