#!/usr/bin/env python3
"""CF-0545 / CF-0575: a block that retells the event takes the event's own
footage - the classification, in one place for the Video Editor and the
Content Researcher.

CF-0545 wrote it in `agents/video-editor/scripts/event_footage.py`; CF-0575
moved it here, to the factory root, because the writer has to answer the same
question before the voice ("does the event's own footage carry the words that
retell it?") and a rule written twice is a rule that will disagree with
itself (CF-0159). Both repositories load this file by path and keep no copy:
the Editor through its `scripts/event_footage.py` (which also hands it its
own `source_gate.source_id`), the Researcher through `scripts/_event_footage.py`.

`weekend-night-live` (`pipeline/example-film/2026-10-05T0701Z`): under the
words about Taylor Sterling walking into Dana Reyes's WNL monologue stood
`d7b1ilF5290` - Dana Reyes on the guest couch of *Late Night with Seth
Meyers*, a promo interview from before the broadcast. The event itself had
one source (`KTe9OatvQas`, 8 shots, 3 clean), the interview fifty, and the
matcher picks by person and description ("a woman in a dress, talking"), so
nothing tied a block that retells the monologue to the monologue's footage.
The frame judge called it another show (CF-0539) - after the render.

The rule, in front of every rung that picks a picture (the Editor)
-----------------------------------------------------------------
When the script retells a scene of the hunter's (`scene_id`, CF-0533) and
that scene names a moment *on screen* (a monologue, an episode, a finale, a
cameo - not "X says / reveals / explains", where the interview *is* the
event, and not a box office figure or a renewal, where there is no moment
to hold to), every
block whose words retell it takes no shot from an **interview of another
production**: a source whose nature is `interview` (the hunter's
`footage_candidates[]`, a consumed supplement request's `candidates[]`, or -
for a pool source neither names - its title in `shared/footage/index.json`)
and whose channel is not the work's own (`title_ref` name, its initials,
`network`, `rights_holder`, `parent_work`). The hunter calls "Dana Reyes
Monologue - WNL" an interview too (its facet came from the search query);
the channel `Weekend Night Live` is the work's own, so it stays.

An interview is still the right picture under words that say so: a block
whose words name an interview ("in an interview", "on a podcast", "talk
show", "sat down with", "press tour") or the interview's own show / host
("Late Night with Sam Meadows", "Sam Meadows") keeps it.

The rule is off - and says why - when the script has no scene, the scene is
a statement, the pool holds no interview of another production, or the pool
holds no source of the work's own (then there is nothing to keep the block
on, and the answer is more material, CF-0345, not an empty video).

When an event block loses its interview candidates and the event's own
footage does not carry it, the block falls to the ladder (topic footage of
the event, the repeat) like any thin block - never back to the interview -
and the storyboard's `event_footage.short[]` names it: the pool wants a
supplement of the event's footage.

The writer's half (CF-0575, `scope()` below)
--------------------------------------------
The Editor only refuses the interview; whether the event's own footage is
enough is a question for before the voice, when more footage can still be
fetched (CF-0345). `scope()` answers it on the rule above, narrowed twice:

  * **the event's sources** - of the work's own sources, the ones whose title
    names the scene's moment, when the moment is a specific segment of a
    broadcast (`SPECIFIC_MOMENTS`: monologue, cold open, sketch, cameo,
    musical guest, walk-on). WNL's cold open (`JmTwSOlQz8g`, "Republican
    Midterm Ads Cold Open - WNL") and a Kart Rally sketch are the work's own
    and not the monologue: under "Reyes calls her my literal therapist"
    they are the wrong picture as surely as the Late Night couch, only
    quieter. A moment that is not a segment (an episode, a finale, a scene)
    or a pool whose own titles do not name it - every own source is the
    event;
  * **the event's anchors** - the anchors whose words retell the scene
    (`block_rule()`), less those whose words name *another* segment ("the
    same night's cold open ran", "a completely separate sketch").

The anchor's own picture (CF-0576, `interview_anchor()`)
-------------------------------------------------------
The writer can also *ask* for the interview: WNL 0701Z's payoff anchor v7 -
"Sam Meadows ... and Dana Reyes ... meet and shake hands" under "One
monologue, two different segments worth remembering". A phrase that names one
of the pool's interviews' show or host, or the words of an interview / a talk
show's set, is a picture of that interview, and it is allowed under the same
words the Editor's `block_rule()` allows an interview under ("interview",
"talk show", the show or its host) - anywhere else in a script the rule is on
for, the writer points the block at a frame the Editor will refuse there.

Pure json work - no CLIP, no ffmpeg. Stdlib only.
"""
import importlib.util
import json
import re
from pathlib import Path


def _footage_ids():
    """shared/footage_ids.py, loaded by path - this file is itself loaded by
    path from other repositories, so no neighbour is imported by name."""
    path = Path(__file__).resolve().parent / "footage_ids.py"
    spec = importlib.util.spec_from_file_location("footage_ids", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


FOOTAGE_IDS = _footage_ids()


def source_id(value):
    """The source id in `<id>:<n>` / `.../<id>.mp4` / `<id>`. The Video
    Editor's loader (`agents/video-editor/scripts/event_footage.py`) puts its
    own `source_gate.source_id` here, which also reads cut-clip names."""
    if not value:
        return None
    s = Path(str(value)).name
    s = s.split(":", 1)[0]
    for suffix in (".shots.json", ".mp4", ".json"):
        if s.endswith(suffix):
            return s[: -len(suffix)]
    return s or None

HUNTER_NAME = "01-trend-hunter.json"
REGISTRY_NAME = "index.json"          # <footage>/index.json
SUPPLEMENT_DIR = ("work", "supplement-requests")

# The hunter's own `interview` rule (trend-hunter footage_candidates.KIND_RULES)
# plus "X Talks Y" - the d7b1ilF5290 title ("... Talks Filming with Taylor
# Swift") - for a pool source the hunter of this batch never offered.
INTERVIEW_TITLE_RE = re.compile(
    r"\b(interview(s|ed)?|talks?\s+(about|to)|talks|sits?\s+down|"
    r"press\s+(junket|conference|tour)|q\s*&\s*a|q and a|red carpet|roundtable|"
    r"on playing|answers|in conversation)\b", re.I)

# The same for the work's own cuts, for a pool source the hunter never
# offered (the hunter's trailer / teaser / episode_clip / featurette rules).
OWN_TITLE_RE = re.compile(
    r"\b(trailer|teaser|clip|scenes?|full\s+episode|cold\s+open|sneak\s+peek|"
    r"first\s+look|featurette|behind[\s-]the[\s-]scenes)\b", re.I)

# A scene that is somebody *saying* something: the interview is the event.
STATEMENT_RE = re.compile(
    r"\b(says?|said|saying|reveal(s|ed|ing)?|explain(s|ed|ing)?|told|tells|"
    r"teas(e|es|ed|ing)|admit(s|ted)?|confirm(s|ed)?|recall(s|ed)?|opens?\s+up|"
    r"talk(s|ed|ing)?|interview(s|ed)?|podcast|stands?\s+by|address(es|ed)?|"
    r"insist(s|ed)?|claim(s|ed)?|prais(e|es|ed))\b", re.I)
# ...unless it names a moment on screen: then "the finale reveals" is still
# the finale.
ON_SCREEN_RE = re.compile(
    r"\b(monologue|sketch|cold\s+open|episodes?|finale|premiere\s+episode|"
    r"scenes?|cameo|walk[\s-]?on|opening\s+(monologue|scene|sequence|credits)|"
    r"on[\s-]air|broadcast|sequence|musical\s+guest|performance)\b", re.I)

# Words that put the block in the interview.
ATTRIBUTION_RE = re.compile(
    r"\b(interview(s|ed)?|podcast|talk[\s-]?show|sat\s+down\s+with|"
    r"sits?\s+down\s+with|press\s+(tour|junket|run|conference)|"
    r"in\s+conversation\s+with|late[\s-]night|tonight\s+show)\b", re.I)

GENERIC_CHANNEL_WORDS = {"studios", "studio", "pictures", "entertainment", "tv",
                         "channel", "official", "network", "networks", "inc",
                         "films", "the"}
INITIALS_SKIP = {"the", "of", "and", "a", "an", "&"}


def norm(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def _core(text):
    return " ".join(t for t in norm(text).split() if t not in GENERIC_CHANNEL_WORDS)


def _contains(hay, needle):
    return bool(needle) and f" {needle} " in f" {hay} "


def own_names(title_ref):
    """The names a channel of the work's own goes by: the work, its initials
    ("Weekend Night Live" -> "wnl"), its network, rights holder and parent
    work - each without the generic channel words."""
    tr = title_ref if isinstance(title_ref, dict) else {}
    out = []
    for key in ("name", "network", "parent_work"):
        if tr.get(key):
            out.append(tr[key])
    for part in re.split(r"[/,&]", str(tr.get("rights_holder") or "")):
        if part.strip():
            out.append(part)
    words = [w for w in norm(tr.get("name")).split() if w not in INITIALS_SKIP]
    if len(words) >= 2:
        out.append("".join(w[0] for w in words))
    names = []
    for n in out:
        c = _core(n)
        if c and c not in names:
            names.append(c)
    return names


def is_own_channel(channel, names):
    c = _core(channel)
    if not c:
        return False
    return any(_contains(c, n) or _contains(n, c) for n in names)


def show_names(channel):
    """The ways a block's words can name an interview's show: the channel
    itself and its host ("Late Night with Sam Meadows" -> "sam meadows",
    "The Evening Show Starring Jim Fenwick" -> "jim fenwick")."""
    full = norm(channel)
    out = [full] if full else []
    m = re.search(r"\b(?:with|starring)\s+(.+)$", full)
    if m and len(m.group(1).split()) >= 2:
        out.append(m.group(1))
    return out


def scene_kind(description):
    """`on_screen` (it names a moment on screen) | `statement` (somebody says
    something) | `other` (a box office figure, a renewal - no moment to hold
    a block to) | None (no description)."""
    if not description:
        return None
    if ON_SCREEN_RE.search(description):
        return "on_screen"
    return "statement" if STATEMENT_RE.search(description) else "other"


def _load(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError, TypeError):
        return None


def topic_and_scene(hunter, topic_id, scene_id):
    for t in (hunter or {}).get("topics") or []:
        if not isinstance(t, dict) or t.get("topic_id") != topic_id:
            continue
        scene = next((s for s in t.get("scenes") or []
                      if isinstance(s, dict) and s.get("scene_id") == scene_id),
                     None)
        return t, scene
    return None, None


def source_records(topic, supplement_requests, registry):
    """`{video_id: {"title", "uploader", "nature"}}` from everything that
    named the source: the hunter's candidates for the topic, the consumed
    supplement requests' candidates, the footage registry (title, uploader).
    `uploader` is the YouTube channel that published the source - never a
    factory channel id, so CF-0197's resolve_channel is not for it.

    CF-0665: an archive file (NASA / Commons) is in the pool under its file id
    `nasa-<id>` / `commons-<pageid>`, while the hunter names it `nasa:<id>` /
    `commons:<pageid>`; the indexer keeps the hunter's id beside the file as
    `candidate_id` (the registry entry, `fetched[]`). A candidate is keyed by
    the file id that `candidate_id` points at - or, for a file the registry
    does not hold yet, by the same rule the indexer names it by - so its
    `nature` and `title` reach the source the Editor actually picks."""
    out = {}
    file_of = {}                    # candidate_id -> file id (CF-0665)
    for e in ((registry or {}).get("entries") or []):
        if isinstance(e, dict) and e.get("id"):
            out[e["id"]] = {"title": e.get("title"), "uploader": e.get("uploader"),
                            "nature": None, "from": "registry"}
            if isinstance(e.get("candidate_id"), str) and e["candidate_id"]:
                file_of[e["candidate_id"]] = e["id"]
    cands = list(((topic or {}).get("evidence") or {}).get("footage_candidates") or [])
    for req in supplement_requests or []:
        cands += [c for c in (req or {}).get("candidates") or [] if isinstance(c, dict)]
    for c in cands:
        if not isinstance(c, dict) or not c.get("video_id"):
            continue
        cid = c.get("candidate_id") or c["video_id"]
        vid = file_of.get(cid) or FOOTAGE_IDS.archive_file_id(cid)
        rec = out.setdefault(vid, {})
        rec.update({"title": c.get("title") or rec.get("title"),
                    "uploader": c.get("channel_title") or rec.get("uploader"),
                    "nature": c.get("nature"), "from": "hunter"})
    return out


def classify(vid, rec, names):
    """(`own` | `interview` | `other`, why)."""
    if not rec:
        return "other", "nothing names this source - not touched"
    channel, title, nature = rec.get("uploader"), rec.get("title"), rec.get("nature")
    if is_own_channel(channel, names):
        return "own", f"the channel {channel!r} is the work's own"
    if nature == "interview":
        return "interview", (f"an interview (the hunter's nature) on {channel!r}, "
                             f"not the work's channel")
    if nature is None and title and INTERVIEW_TITLE_RE.search(title):
        return "interview", (f"an interview by its title ({title!r}) on "
                             f"{channel!r}, not the work's channel")
    if nature in ("trailer", "episode", "featurette", "promo"):
        return "own", f"a {nature} of the work"
    if nature is None and title and OWN_TITLE_RE.search(title):
        return "own", (f"a cut of the work by its title ({title!r})")
    return "other", f"nature {nature or 'unknown'} - not an interview, not touched"


def build(spec, source_ids, hunter=None, registry=None, supplement_requests=None):
    """The guard for one script: which sources are interviews of another
    production, and whether the rule is on at all. Pure."""
    spec = spec if isinstance(spec, dict) else {}
    guard = {"task": "CF-0545", "applied": False, "scene_id": spec.get("scene_id"),
             "scene_kind": None, "sources": {}, "interview": [], "own": [],
             "show_names": [], "why": None}
    topic, scene = topic_and_scene(hunter, spec.get("topic_id"), spec.get("scene_id"))
    names = own_names(spec.get("title_ref") or (topic or {}).get("title_ref"))
    recs = source_records(topic, supplement_requests, registry)
    for vid in source_ids:
        role, why = classify(vid, recs.get(vid), names)
        guard["sources"][vid] = {"role": role, "why": why,
                                 "uploader": (recs.get(vid) or {}).get("uploader"),
                                 "title": (recs.get(vid) or {}).get("title")}
        if role == "interview":
            guard["interview"].append(vid)
            for n in show_names((recs.get(vid) or {}).get("uploader")):
                if n not in guard["show_names"]:
                    guard["show_names"].append(n)
        elif role == "own":
            guard["own"].append(vid)
    if not spec.get("scene_id"):
        guard["why"] = "the script retells no scene of the hunter's - nothing to hold to"
        return guard
    if scene is None:
        guard["why"] = (f"scene {spec.get('scene_id')} is not in the hunter's "
                        f"record - the rule cannot tell what the event is")
        return guard
    guard["scene_kind"] = scene_kind(scene.get("description"))
    if guard["scene_kind"] == "statement":
        guard["why"] = ("the scene is somebody saying something - the interview "
                        "is the event's own footage")
        return guard
    if guard["scene_kind"] != "on_screen":
        guard["why"] = ("the scene names no moment on screen (a figure, a "
                        "renewal) - there is no broadcast to hold the blocks to")
        return guard
    if not guard["interview"]:
        guard["why"] = "the pool holds no interview of another production"
        return guard
    if not guard["own"]:
        guard["why"] = ("the pool holds no source of the work's own - nothing to "
                        "keep the blocks on; the event's footage wants a "
                        "supplement (CF-0345)")
        guard["needs_supplement"] = True
        return guard
    guard["applied"] = True
    guard["why"] = (f"scene {spec.get('scene_id')} is a moment on screen: its "
                    f"blocks take no shot of {', '.join(guard['interview'])}")
    return guard


def words_text(words, start_index, end_index):
    return " ".join(str(w.get("word") or w.get("text") or "")
                    for w in (words or [])[start_index:end_index]
                    if isinstance(w, dict))


def block_rule(guard, text):
    """(retells the event?, why) for one block's spoken words."""
    if not guard or not guard.get("applied"):
        return False, None
    m = ATTRIBUTION_RE.search(text or "")
    if m:
        return False, f"its words put it in an interview ({m.group(0)!r})"
    t = norm(text)
    for n in guard.get("show_names") or []:
        if _contains(t, n):
            return False, f"its words name the interview's show ({n!r})"
    return True, "its words retell the event"


def refusal(guard, event_block, source):
    """Why this candidate may not stand in this block, or None."""
    if not event_block or not guard or not guard.get("applied"):
        return None
    vid = source_id(source)
    if vid in (guard.get("interview") or []):
        rec = guard["sources"].get(vid) or {}
        return (f"{vid} is {rec.get('why') or 'an interview of another production'}"
                f" - a block that retells scene {guard.get('scene_id')} takes the "
                f"event's own footage (CF-0545)")
    return None


def screen_matches(matches, decisions, guard, min_score=None):
    """Take every interview candidate out of each event block's phrase, in
    place, before any rung sees them. `decisions[i]` is block_rule()'s
    answer for anchor i. Returns the refusals."""
    refused = []
    if not guard or not guard.get("applied"):
        return refused
    for i, m in enumerate(matches):
        event_block = bool(decisions[i][0]) if i < len(decisions) else False
        keep = []
        for c in m.get("candidates") or []:
            why = refusal(guard, event_block, c.get("source"))
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


def batch_inputs(batch_dir, footage_dir):
    """(hunter, registry, consumed supplement requests) for a batch dir and
    a footage dir; each None/[] when absent."""
    hunter = _load(Path(batch_dir) / HUNTER_NAME) if batch_dir else None
    registry = _load(Path(footage_dir) / REGISTRY_NAME) if footage_dir else None
    reqs = []
    if batch_dir:
        base = Path(batch_dir).joinpath(*SUPPLEMENT_DIR)
        for d in (base, base / "consumed"):
            for f in sorted(d.glob("*.json")) if d.is_dir() else []:
                r = _load(f)
                if isinstance(r, dict):
                    reqs.append(r)
    return hunter, registry, reqs


# --------------------------------------------------------------------------
# CF-0575: the event's own sources and the anchors that retell it
# --------------------------------------------------------------------------

# A segment of a broadcast a title can name: (moment, pattern). The scene's
# first one (by position in its description) is the event; an anchor whose
# words name only others is about another segment.
SPECIFIC_MOMENTS = (
    ("cold open", r"cold\s+opens?"),
    ("monologue", r"monologues?"),
    ("sketch", r"sketch(es)?"),
    ("cameo", r"cameos?"),
    ("musical guest", r"musical\s+(guest|performance)"),
    ("walk-on", r"walk[\s-]?ons?"),
)
_MOMENT_RES = tuple((m, re.compile(r"\b" + p + r"\b", re.I)) for m, p in SPECIFIC_MOMENTS)


def moments_in(text):
    """The specific segments `text` names, in the order it names them."""
    found = []
    for moment, rx in _MOMENT_RES:
        m = rx.search(text or "")
        if m:
            found.append((m.start(), moment))
    return [moment for _, moment in sorted(found)]


def scene_moment(description):
    """The segment the scene is about: the first one its description names,
    or None (an episode, a finale - no segment narrower than the work)."""
    found = moments_in(description)
    return found[0] if found else None


def event_sources(guard, moment):
    """(the event's own source ids, why): the work's own sources whose title
    names the scene's segment; every own source when the moment is no
    segment or no own title names it."""
    own = list((guard or {}).get("own") or [])
    if not moment:
        return own, "the scene names no segment narrower than the work - every own source is the event"
    titled = [v for v in own
              if moment in moments_in(((guard.get("sources") or {}).get(v) or {}).get("title"))]
    if not titled:
        return own, (f"no own source's title names the {moment} - every own source "
                     f"is counted as the event")
    return titled, (f"the {moment}: the own source(s) whose title names it "
                    f"({', '.join(titled)}); the work's other segments are not this event")


def event_anchor(guard, moment, text):
    """(retells this scene?, why) for one anchor's words: `block_rule()`, and
    not words that name another segment only."""
    retells, why = block_rule(guard, text)
    if not retells:
        return False, why
    named = moments_in(text)
    if moment and named and moment not in named:
        return False, f"its words name another segment ({', '.join(named)}), not the {moment}"
    return True, why


# --------------------------------------------------------------------------
# CF-0576: an anchor whose picture is the interview, under words that are not
# --------------------------------------------------------------------------

# What a frame of an interview looks like in an anchor's `phrase`: the words
# that put a block in the interview (ATTRIBUTION_RE, less the bare "late
# night", which is also an hour of the day) and the furniture of a talk show.
# The interview's own show and host (`show_names()`) are matched apart.
INTERVIEW_PICTURE_RE = re.compile(
    r"\b(interview(s|er|ed|ing)?|podcast|talk[\s-]?show|"
    r"press\s+(tour|junket|run|conference)|sat\s+down\s+with|sits?\s+down\s+with|"
    r"in\s+conversation\s+with|guest\s+(couch|chair|seat)|host'?s\s+desk|"
    r"late[\s-]night\s+(show|set|desk|couch|host|stage|studio)|tonight\s+show)\b", re.I)


def pictures_interview(guard, phrase, samples=None):
    """(the anchor pictures an interview of another production?, why).

    * its phrase names the show or host of one of the pool's interviews
      (`guard['show_names']`: "sam meadows", "late night with sam meadows");
    * or its best shot in the pool (`samples`, the preflight's distinct
      samples, best first) is one of those interviews - the writer described
      a frame of it, whatever the words;
    * or its phrase has the words of an interview / a talk show's set, and
      there is no best shot to say *which* interview (`samples` unknown or
      empty). With a best shot of another source, "an on-camera interview" is
      that source's - 1901Z's Kelli Giddish (`extratv`, the work's own
      featurette), not the pool's foreign one.

    Only meaningful where the pool holds such an interview (`guard['interview']`)."""
    if not guard or not guard.get("interview"):
        return False, None
    t = norm(phrase)
    for n in guard.get("show_names") or []:
        if _contains(t, n):
            return True, f"it names the interview's show ({n!r})"
    best = next(iter(samples or []), None)
    if best is not None and source_id(best) in guard["interview"]:
        return True, f"its best shot in the pool ({best}) is the interview's"
    m = INTERVIEW_PICTURE_RE.search(phrase or "")
    if m and best is None:
        return True, f"it pictures an interview ({m.group(0)!r})"
    return False, None


def interview_anchor(guard, phrase, text, samples=None):
    """CF-0576: (a picture of another production's interview under words that
    do not put the block in it?, why). The Editor's `block_rule()` lets an
    interview stand only under words that name it ("interview", "talk show",
    the show or its host); an anchor that *asks* for the interview anywhere
    else - WNL 0701Z v7, "Sam Meadows ... shake hands" under "One monologue,
    two different segments" - is the writer pointing the block at a picture
    the Editor will refuse there."""
    pictured, why_picture = pictures_interview(guard, phrase, samples)
    if not pictured:
        return False, None
    retells, why_words = block_rule(dict(guard, applied=True), text)
    if not retells:
        return False, f"{why_picture}, and {why_words} - allowed"
    return True, (f"{why_picture}, but the words under it do not name an interview, "
                  f"a talk show or its host")


def scope(spec, source_ids, texts, hunter=None, registry=None, supplement_requests=None,
          phrases=None, samples=None):
    """CF-0575: the writer's question - which anchors retell the scene, and
    which sources are the event. `texts[i]` is anchor i's words; `phrases[i]`,
    when given, its picture (and `samples[i]`, when given, the preflight's
    distinct samples for it, best first) - and `foreign_interview_anchors`
    (CF-0576) the anchors that picture another production's interview under
    words that do not name it.

    `active` is the Editor's `applied` (the rule is on, the pool has the work's
    own footage): only then are the event anchors held to the event's
    sources. `needs_supplement` (on-screen scene, interviews, no own source)
    is not active - there is nothing to count - and is a request on its own."""
    guard = build(spec, source_ids, hunter, registry, supplement_requests)
    topic, scene = topic_and_scene(hunter, (spec or {}).get("topic_id"),
                                   (spec or {}).get("scene_id"))
    moment = scene_moment((scene or {}).get("description"))
    out = {"task": "CF-0575", "active": bool(guard.get("applied")),
           "needs_supplement": bool(guard.get("needs_supplement")),
           "why": guard.get("why"), "scene_id": guard.get("scene_id"),
           "scene_kind": guard.get("scene_kind"), "moment": moment,
           "interview": list(guard.get("interview") or []),
           "own": list(guard.get("own") or []),
           "event_sources": [], "event_sources_why": None,
           "anchors": [], "event_anchors": [],
           "show_names": list(guard.get("show_names") or []),
           "foreign_interview_anchors": []}
    if not (out["active"] or out["needs_supplement"]):
        return out
    rule_guard = dict(guard, applied=True)
    if out["active"]:
        out["event_sources"], out["event_sources_why"] = event_sources(guard, moment)
    else:
        out["event_sources_why"] = "the pool holds no source of the work's own"
    for i, text in enumerate(texts or []):
        retells, why = event_anchor(rule_guard, moment, text)
        rec = {"anchor_index": i, "event": retells, "why": why}
        # CF-0576: the anchor's own picture - an interview of another
        # production is allowed only under words that name it.
        if phrases is not None and i < len(phrases):
            best = samples[i] if samples is not None and i < len(samples) else None
            foreign, why_f = interview_anchor(rule_guard, phrases[i], text, best)
            if why_f:
                rec["interview_picture"] = {"foreign": foreign, "why": why_f}
            if foreign:
                out["foreign_interview_anchors"].append(i)
        out["anchors"].append(rec)
        if retells:
            out["event_anchors"].append(i)
    return out
