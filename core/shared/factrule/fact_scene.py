#!/usr/bin/env python3
"""CF-0548: the video's fact is about the topic's own scene, not about the
segment next to it.

**Why.** `example-film/2026-10-05T0701Z`, WNL: the topic was Taylor Sterling
walking into Dana Reyes's monologue; the fact the writer took (CF-0438,
the best passing candidate of the topic) was Variety's line about the cold
open of the same broadcast - a separate sketch, other performers, another
segment. It passed every requirement of the fact rule (a tier-1 source, a
date, attributed) and was told as "here's the part the recaps skip". The user,
2026-10-05: if we talk about a topic, we talk about *it*, not about the one
next to it - otherwise the viewer is lost.

**The rule.** A fact is about the subject of the scene the video tells: the
same person or work **and** the same moment or event, or its direct
backstory - never another segment of the same broadcast, another film of the
same weekend's box-office piece, another topic of the batch. The deterministic
part, judged here for one candidate against one scene:

  * `other_segment`       - the fact names a segment of a broadcast (cold open,
                            monologue, Weekend Update, a musical performance, a
                            red carpet, an acceptance speech...) and the scene
                            names a different one;
  * `names_outside_scene` - the fact names somebody/something that is not in
                            the scene's world (see "two shapes" below);
  * `not_about_scene`     - an event topic's fact names nobody of the scene:
                            "the show premiered in 1975" is about the show, not
                            about tonight's monologue;
  * `other_topic`         - the fact names another topic of the same batch
                            that this topic's own world does not mention (the
                            Verity topic carrying Delver's opening weekend).

**Two shapes of topic.** An *event* topic - a person's appearance on a show
(`title_ref.kind == "person"`) or a scene that names a segment of a broadcast -
is one moment of something long-running; the show's own article and the
episode's recap describe every other segment too, so the scene's world is the
scene alone: its description, its one source's headline and summary, the
names of `title_ref`. A *work* topic (a film, a season, a finale) is about the
work, and the work's own history is its backstory: the world is every scene of
the topic, every news source of the topic, its support text (CF-0551), and a
Wikipedia candidate from the topic's own article is the work's own text (its
names are not checked; the segment and other-topic checks still are).

A candidate that fits no scene of its topic is not the topic's fact: the next
candidate is taken; a topic with no candidate that fits any scene leaves as
`no_fact`, exactly like a topic with no candidate at all (CF-0438).

Stdlib only. Loaded by path by the Trend Hunter (`check_scenes.py`) and the
Content Researcher (`production_facts.py`, `fact_refusal.py`,
`check_production_fact.py`); neither keeps a copy.
"""
import re
import unicodedata

TASK = "CF-0548"

SCENES_KEY = "scenes"          # on a candidate: the scene ids it fits
FIT_KEY = "scene_fit"          # on a candidate: {scene_id: [failure codes]}

FAIL_OTHER_SEGMENT = "other_segment"
FAIL_NAMES_OUTSIDE_SCENE = "names_outside_scene"
FAIL_NOT_ABOUT_SCENE = "not_about_scene"
FAIL_OTHER_TOPIC = "other_topic"
FAIL_CODES = (FAIL_OTHER_SEGMENT, FAIL_NAMES_OUTSIDE_SCENE, FAIL_NOT_ABOUT_SCENE,
              FAIL_OTHER_TOPIC)

SHAPE_EVENT = "event"
SHAPE_WORK = "work"

# Segments of a broadcast / an event. Two segments are "the same" when they
# share a key or the pair is listed in COMPATIBLE (a cold open is a sketch).
SEGMENTS = (
    ("cold_open", r"cold[\s-]+open(?:er|ing)?"),
    ("monologue", r"monologue"),
    ("weekend_update", r"weekend\s+update"),
    ("musical_performance", r"musical\s+(?:guest|performance)"),
    ("digital_short", r"digital\s+short"),
    ("sketch", r"sketch(?:es)?"),
    ("red_carpet", r"red[\s-]+carpet"),
    ("acceptance_speech", r"acceptance\s+speech"),
    ("halftime_show", r"half[\s-]?time\s+show"),
    ("opening_number", r"opening\s+number"),
    ("after_party", r"after[\s-]?party"),
    ("post_credits", r"(?:post|mid|end)[\s-]+credits?\s+scene"),
)
_SEGMENT_RES = tuple((key, re.compile(r"\b" + rx + r"\b", re.I)) for key, rx in SEGMENTS)
COMPATIBLE = frozenset({frozenset({"cold_open", "sketch"}),
                        frozenset({"digital_short", "sketch"})})

# Capitalised words that name nobody: dates, parties and nationalities,
# platforms, outlets' own furniture ("SUNDAY AM WRITETHRU"), grammar.
EXCEPTIONS = frozenset("""
january february march april may june july august september october november
december jan feb mar apr jun jul aug sep sept oct nov dec monday tuesday
wednesday thursday friday saturday sunday mon tue tues wed thu thurs fri sat sun
am pm et pt est pst edt pdt gmt bst
the a an in on at as after before during while when its his her their this that
these those but and so also with for from by of to it he she they we i you
there here then now today tonight yesterday tomorrow last next first new more
most some all both each every one two three no not yes per via
tv us u s uk usa eu american americans british english european canadian
australian republican republicans democratic democrat democrats gop
instagram tiktok youtube twitter x facebook threads podcast wikipedia
season seasons episode episodes part chapter volume vol series
north south east west eastern western central pacific mountain time
mr mrs ms dr st jr sr
update updated writethru exclusive breaking watch video photos report reports
""".split())
CONNECTORS = frozenset("of the and de da del della di du van von der den la le y for".split())
ABBREVIATIONS = frozenset("mr mrs ms dr st jr sr bros co corp inc ltd vs vol no mt ft".split())
SENTENCE_END = ".!?;:"
TOKEN_RE = re.compile(r"[^\W_][\w'’\-*.]*|[^\w\s]", re.UNICODE)
INITIALS_RE = re.compile(r"(?:[^\W\d_]\.)+", re.UNICODE)
INITIALS_SKIP = frozenset({"the", "of", "and", "a", "an"})
# Grammar that opens a capitalised run ("After Reyes", "In December") and is
# taken off its front; a day or a month is kept there ("Weekend Night Live").
LEADING_GRAMMAR = frozenset("""the a an in on at as after before during while when
its his her their this that these those but and so also with for from by of to
it he she they we i you there here then now per via""".split())


# ------------------------------------------------------------------ words
def fold(text):
    """Accents off, case off, `&` -> and, periods dropped, everything else a
    space; padded so `" x "` is a whole-word test."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.casefold().replace("&", " and ").replace(".", "")
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return f" {text.strip()} "


def words(text):
    return fold(text).split()


def segments(text):
    """The broadcast segments a text names, as keys of SEGMENTS."""
    return {key for key, rx in _SEGMENT_RES if rx.search(str(text or ""))}


def same_segment(fact_segments, scene_segments):
    """True when the fact's segments are the scene's (or the scene names none,
    or the fact names none)."""
    if not fact_segments or not scene_segments:
        return True
    for f in fact_segments:
        for s in scene_segments:
            if f == s or frozenset({f, s}) in COMPATIBLE:
                return True
    return False


# ------------------------------------------------------------------ names
def _split_word(raw):
    word, ends_sentence, ends_run = raw, False, False
    if word.endswith(".") and not INITIALS_RE.fullmatch(word) \
            and word.rstrip(".").casefold() not in ABBREVIATIONS:
        word = word.rstrip(".")
        ends_sentence = True
    for suffix in ("'s", "’s"):
        if word.endswith(suffix):
            word, ends_run = word[: -len(suffix)], True
    if word.endswith(("'", "’")):
        word, ends_run = word.rstrip("'’"), True
    return word, ends_sentence, ends_run


def _runs(text):
    """[(tokens, starts_sentence)]: the capitalised runs of a text."""
    text = str(text or "")
    runs, current, pending, starts, at_start = [], [], [], False, True

    def close():
        nonlocal current, pending
        if current:
            runs.append((current, starts))
        current, pending = [], []

    for m in TOKEN_RE.finditer(text):
        tok = m.group(0)
        if not tok[0].isalnum():
            close()
            if tok in SENTENCE_END:
                at_start = True
            continue
        word, ends_sentence, ends_run = _split_word(tok)
        if not word:
            continue
        if word[:1].isupper():
            if current:
                current.extend(pending)
                pending = []
                current.append(word)
            else:
                current, starts = [word], at_start
        elif current and word.casefold() in CONNECTORS:
            pending.append(word)
        else:
            close()
        at_start = False
        if ends_run or ends_sentence:
            close()
        if ends_sentence:
            at_start = True
    close()
    return runs


def _is_exception(token):
    return all(w in EXCEPTIONS for w in words(token)) if words(token) else True


def proper_names(text):
    """The names a text gives, in reading order, as written. A lone
    capitalised word that opens a sentence is grammar, not a name; dates,
    nationalities, platforms and the like (EXCEPTIONS) are not names."""
    out = []
    for tokens, starts in _runs(text):
        while tokens and (fold(tokens[0]).strip() in LEADING_GRAMMAR
                          or not tokens[0][:1].isupper()):
            tokens = tokens[1:]
        while tokens and (_is_exception(tokens[-1]) or not tokens[-1][:1].isupper()):
            tokens = tokens[:-1]
        capitals = [t for t in tokens if t[:1].isupper() and not _is_exception(t)]
        if not capitals:
            continue
        if starts and len(capitals) == 1 and len(tokens) == 1 and not _runs_away(text, tokens[0]):
            continue
        name = " ".join(tokens)
        if name not in out:
            out.append(name)
    return out


def _runs_away(text, token):
    """A sentence-opening single word that the same text also capitalises
    mid-sentence is a name after all ("Cruise ... said Cruise")."""
    return bool(re.search(r"[^.!?;:\s]\s+" + re.escape(token) + r"\b", str(text or "")))


def initials(name):
    ws = [w for w in words(name) if w not in INITIALS_SKIP]
    return "".join(w[0] for w in ws) if len(ws) >= 2 else ""


def name_in(name, world_folded, world_words):
    """Is a name in a world? The whole name, or its last word (a surname, the
    last word of a title), or its initials ("Weekend Night Live" ~ "WNL")."""
    folded = fold(name)
    if folded.strip() and folded in world_folded:
        return True
    ws = [w for w in folded.split() if w not in CONNECTORS]
    if ws and len(ws[-1]) >= 3 and ws[-1] in world_words:
        return True
    ini = initials(name)
    return bool(ini) and ini in world_words


# ------------------------------------------------------------------ a topic
def title_names(topic):
    tr = (topic or {}).get("title_ref") or {}
    out = []
    for key in ("name", "person", "parent_work", "network", "rights_holder"):
        if isinstance(tr.get(key), str) and tr[key].strip():
            out.append(tr[key])
    return out


def show_names(topic):
    """The show/work itself - never the anchor of an event scene."""
    tr = (topic or {}).get("title_ref") or {}
    out = [tr[k] for k in ("name", "network", "parent_work")
           if isinstance(tr.get(k), str) and tr[k].strip()]
    out += [initials(n) for n in out if initials(n)]
    return out


def sources_by_url(topic):
    ev = (topic or {}).get("evidence") or {}
    return {s.get("url"): s for s in ev.get("sources") or [] if isinstance(s, dict) and s.get("url")}


def scene_of(topic, scene_id):
    for s in (topic or {}).get("scenes") or []:
        if isinstance(s, dict) and s.get("scene_id") == scene_id:
            return s
    return None


def shape(topic, scene):
    """`event` - a person's appearance (`title_ref.kind == "person"`) or a
    scene naming a segment of a broadcast that is not a film's; else `work`."""
    tr = (topic or {}).get("title_ref") or {}
    if tr.get("kind") == "person":
        return SHAPE_EVENT
    if tr.get("type") != "film" and segments((scene or {}).get("description")):
        return SHAPE_EVENT
    return SHAPE_WORK


def _source_text(source):
    return " ".join(str(source.get(k) or "") for k in ("title", "summary"))


def world_texts(topic, scene, candidate=None):
    """The texts a fact's names are looked up in (see the module's docstring)."""
    texts = [(scene or {}).get("description") or ""]
    texts += title_names(topic)
    by_url = sources_by_url(topic)
    own = by_url.get((scene or {}).get("source_url"))
    if own:
        texts.append(_source_text(own))
    if candidate:
        texts += [str(candidate.get(k) or "") for k in ("source", "attribution")]
    if shape(topic, scene) == SHAPE_WORK:
        texts += [s.get("description") or "" for s in (topic or {}).get("scenes") or []
                  if isinstance(s, dict)]
        texts += [_source_text(s) for s in by_url.values()]
        texts += [str(p.get("text") or "") + " " + str(p.get("title") or "")
                  for p in (topic or {}).get("support_text") or [] if isinstance(p, dict)]
    return texts


def other_subjects(topic, batch_topics):
    """The works of the batch's other topics (`title_ref.name`). Their people
    are not listed: a star of two topics' works (Dana Reyes hosting WNL and
    starring in Verity) belongs to both."""
    tid = (topic or {}).get("topic_id")
    out = []
    for t in batch_topics or []:
        if not isinstance(t, dict) or t.get("topic_id") == tid:
            continue
        n = (t.get("title_ref") or {}).get("name")
        if isinstance(n, str) and n.strip() and n not in out:
            out.append(n)
    return out


def own_article_candidate(candidate):
    """A Wikipedia sentence: fact_search takes Wikipedia candidates from the
    one article the hunter resolved for the topic. Read off the source or the
    link, not off `section` - a lead sentence's record carries none (the
    accepted Primetime of 2026-09-30T2210Z)."""
    if str(candidate.get("source") or "").casefold() == "wikipedia":
        return True
    return bool(re.match(r"https?://[a-z]+\.wikipedia\.org/", str(candidate.get("url") or "")))


# ------------------------------------------------------------------ the verdict
def fits_scene(candidate, scene, topic, others=()):
    """One candidate against one scene. -> {"fits", "failures", "shape",
    "outside", "foreign", "segments": {"fact", "scene"}}."""
    candidate = candidate or {}
    text = str(candidate.get("text") or "")
    sc_text = (scene or {}).get("description") or ""
    kind = shape(topic, scene)
    fails, outside, foreign = [], [], []

    f_seg, s_seg = segments(text), segments(sc_text)
    if not same_segment(f_seg, s_seg):
        fails.append(FAIL_OTHER_SEGMENT)

    world = " ".join(world_texts(topic, scene, candidate))
    world_f, world_w = fold(world), set(words(world))
    names = proper_names(text)

    # The other topic is foreign unless this topic's own title or this very
    # scene names it ("Verity outpaced Delver" may say Delver).
    near = " ".join(title_names(topic) + [sc_text])
    near_f, near_w = fold(near), set(words(near))
    for subject in others or ():
        if name_in(subject, near_f, near_w):
            continue
        sf = fold(subject)
        if sf.strip() and any(sf in fold(n) for n in names):
            foreign.append(subject)
    if foreign:
        fails.append(FAIL_OTHER_TOPIC)

    outside = [n for n in names if not name_in(n, world_f, world_w)]
    if kind == SHAPE_EVENT and outside:
        fails.append(FAIL_NAMES_OUTSIDE_SCENE)

    if kind == SHAPE_WORK and not own_article_candidate(candidate):
        # A news sentence about a work names the work or somebody of this
        # scene - not merely another topic the scene compares it with;
        # "another Hoover adaptation is coming" under Delver does not.
        own = [n for n in title_names(topic) + proper_names(sc_text)
               if not any(fold(o) == fold(n) for o in others or ())]
        o_f = fold(" ".join(own))
        o_w = set(o_f.split())
        if not any(name_in(n, o_f, o_w) for n in names):
            fails.append(FAIL_NOT_ABOUT_SCENE)

    if kind == SHAPE_EVENT:
        shows = show_names(topic)
        anchors = [n for n in proper_names(sc_text) + [((topic or {}).get("title_ref") or {}).get("person") or ""]
                   if n and not any(fold(n) == fold(s) or (initials(s) and fold(n).strip() == initials(s))
                                    for s in shows)]
        a_f = fold(" ".join(anchors))
        a_w = set(a_f.split())
        if not any(name_in(n, a_f, a_w) for n in names):
            fails.append(FAIL_NOT_ABOUT_SCENE)

    return {"fits": not fails, "failures": fails, "shape": kind,
            "outside": outside, "foreign": foreign,
            "segments": {"fact": sorted(f_seg), "scene": sorted(s_seg)}}


def annotate(candidates, topic, batch_topics=None):
    """Each candidate (a copy) with SCENES_KEY - the ids of the topic's scenes
    it fits - and FIT_KEY - {scene_id: failures} for every scene. Order kept."""
    others = other_subjects(topic, batch_topics)
    scenes = [s for s in (topic or {}).get("scenes") or [] if isinstance(s, dict)]
    out = []
    for cand in candidates or []:
        if not isinstance(cand, dict):
            continue
        entry = dict(cand)
        fit = {s.get("scene_id"): fits_scene(cand, s, topic, others)["failures"] for s in scenes}
        entry[FIT_KEY] = fit
        entry[SCENES_KEY] = [sid for sid, f in fit.items() if not f]
        out.append(entry)
    return out


def failure_summary(candidate):
    """The codes a candidate failed on across all scenes (for a `rejected`
    line): every code seen, first-seen order."""
    seen = []
    for codes in (candidate.get(FIT_KEY) or {}).values():
        for c in codes:
            if c not in seen:
                seen.append(c)
    return seen


def fits_any(candidate):
    return bool(candidate.get(SCENES_KEY))


def best_for_scene(candidates, scene_id):
    """The first candidate (in the caller's order) that fits `scene_id`."""
    for c in candidates or []:
        if scene_id in (c.get(SCENES_KEY) or []):
            return c
    return None


def fact_fits_script(fact, script, topic, batch_topics=None):
    """The gate's question: does the script's `fact` fit the scene the script
    tells (`scene_id`)? -> the fits_scene verdict, or None when the topic or
    the scene cannot be found (an old batch: nothing to judge against)."""
    scene = scene_of(topic, (script or {}).get("scene_id"))
    if scene is None or not isinstance(fact, dict):
        return None
    return fits_scene(fact, scene, topic, other_subjects(topic, batch_topics))
