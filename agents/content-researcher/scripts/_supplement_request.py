"""CF-0342: a `pool_too_thin` warning names what the pool is missing, and asks
for it.

The user's ruling of 2026-09-23 on `widows-bay` / `everyday-sorcery-2` (CF-0338):
an anchor the topic's own sources cannot picture is answered by *more footage
of the anchor's entity* - highlights, trailers, interviews, the actor's other
work - fetched before the Video Editor, not by an empty block. Three stages
share that work; this module is the writer's third: the pool gates of step 6
already warn (CF-0330), and now each warning carries

  * the uncovered anchors, each with the named entities it is about, and
  * `shots_wanted` - how many usable shots the pool is short, in the gate's
    own count (uncovered anchors, empty blocks, a thin side's unfilled slots,
    distinct samples under the margin),

and, with `--write`, the topic gets a request skeleton at
`<batch>/work/supplement-requests/<topic_id>.json` in the `thin_pool_supplement`
contract that `agents/footage-indexer/scripts/ingest_batch.py --supplement`
reads (CF-0338a, `af2428e`): `kind`, `topic_id`, `reason_code`,
`entities[{name, kind}]`, `shots_wanted`, `max_attempts` - and no
`candidates`, which are Trend Hunter's to fill (CF-0343).

**Where the entities come from.** `visual_anchors[]` has no entity field: an
anchor is a frame (`phrase`) and the words it lands on (`beat_text`). The
names are in that text - `everyday-sorcery-2`'s first anchor is "two women
standing in a wood-paneled room, name captions reading Nora Kingsley and
Sandra Birch". So they are read out of it, deterministically, by one rule
(`anchor_entities()`):

  1. the topic's own work (`title_ref.name`) is cut out of the text first - it
     is what the pool was already searched for, not a new entity;
  2. what is left is split into runs of capitalised words (a possessive `'s`
     dropped, `Spire-Runner: Fresh Dawn` kept whole across its colon);
  3. a run is cut at a word that is capitalised for another reason - a
     sentence opener or function word (`STOP`), a month or weekday, an awards
     word (`NOT_NAMES`), a hyphenated common word like `Co-star` - and its
     leading and trailing such words are dropped;
  4. a run of two or more words is kept and classified: a digit or a colon ->
     `show`; a last word naming a kind of place (`PLACE_WORDS`: Park,
     Studios, Street...) or a first word that opens one (`PLACE_PREFIX`: St.,
     Fort, Lake...) -> `place`; two or three name-shaped words ->
     `person`; anything longer -> `show`;
     (CF-0425: before the `person` fallback, a last word naming a thing
     (`THING_WORDS`: Stones, Gauntlet, Shield...) -> `thing`, and a name
     standing after a preposition of place - "inside Durham Cathedral",
     "a location in Santa Cruz" (`PLACE_BEFORE`) -> `place`);
  5. a single word is kept only as the surname of a person the script names
     in full somewhere in its anchors (`Bullock` -> Sandra Birch); any other
     single word (`London`, `Hamptons`, `Owens`) is too ambiguous to search.

The same text gives the same entities every run: no model call, no lookup.

**Not everyone two capitalised words long is a person** (CF-0425, after batch
`2026-09-27T0929Z` asked the hunter for the "person" `Durham Cathedral` and
`Infinity Stones` (12 search calls on topic 004 with Iron Man's) and `Santa
Cruz` (4 on topic 005), and read the title card "from Robert Eggers'" as the
show `Robert Eggers'`): a quote closing round a name, or the plural
possessive, is stripped off the word (`Eggers'` -> `Eggers`, `Endgame'` ->
`Endgame`); a cathedral, an auditorium, a museum end a place (`PLACE_WORDS`);
Santa / San / Los open one (`PLACE_PREFIX`); a name right after inside / near
/ a location in is a place; and a thing (`kind: thing`) is, like an event,
kept in the anchor's entities and never put in the request's `entities` -
a prop has no footage of its own, and a search for it as a "person" brings
other films' frames. A release card's "Only in Theaters Christmas" is not a
person either: holidays and theaters are `NOT_NAMES`, like the months.

**Who is in front of the camera** (CF-0372, after Paper Dragon's request in
batch `2026-09-23T1722Z` named its director James Grove, its cinematographer
Joaquin Baca-Asay and "Cannes Film Festival" as a `person`, and the search for
Gray brought 60 shots of Ad Astra). A person's footage pictures the topic only
if the person is *on screen* in it; a director's name finds that director's
other films. So every `person` carries `role`, read out of the whole script's
text (anchors' `phrase` / `beat_text` and `production_fact`, `script_roles()`):

  * `crew` - a behind-the-camera word stands right before the name or its
    surname (`CREW_WORDS`: director, writer-director, cinematographer, DP,
    producer, composer, editor, showrunner, creator...), a "by" form names it
    (`shot by`, `directed by`, `written by`...), or the name is the maker of
    a picture: "a James Grove crime picture" (`a <Name> [up to two words]
    film / picture / movie`);
  * `on_screen` - otherwise, and also whenever an on-screen word stands before
    it too (actor, actress, star, co-star, starring, host, `played by`...):
    an actor-director is searched.

A run with a festival or ceremony word (`EVENT_WORDS`: Festival, Gala,
Premiere...) is `kind: event`. Neither `crew` nor `event` goes into the
request's `entities` (their footage is not the topic's); both stay in
`anchors[].entities`, with the role, for whoever reads why.

**What the request asks for** (CF-0349, after `everyday-sorcery-2` asked only
for `Spire-Runner: Fresh Dawn` and got 0 searches): the uncovered anchors'
entities first, then always the topic's own work (kind `work`), then the
people and places of the whole script. A work that is not the topic's is put
in only beside a person named in the same anchor - the hunter's foreign-work
rule (CF-0343), so the request never names what the hunter will not search.

Stdlib only.
"""
import json
import os
import re
from pathlib import Path

KIND = "thin_pool_supplement"
REASON_CODE = "pool_too_thin"
# CF-0575: the words that retell the hunter's on-screen scene have too little
# of the event's own footage (`_event_footage.py`). The same request, the same
# step; it names the work and the event and wants the work's own cuts.
EVENT_REASON_CODE = "event_footage_short"
REASON_CODES = (REASON_CODE, EVENT_REASON_CODE)
KIND_SCENE = "scene"       # CF-0575: the event itself - "<person> <moment>" of the work
MAX_ATTEMPTS = 3           # new videos a request may spend (the indexer's default)
REQUEST_DIR = Path("work") / "supplement-requests"
FIELD = "supplement"       # the block each pool warning carries
DECISION = ("CF-0338/CF-0342: an uncovered anchor is answered by more footage of "
            "its entity, fetched before the Video Editor")

KIND_PERSON, KIND_PLACE, KIND_SHOW, KIND_WORK = "person", "place", "show", "work"
KIND_EVENT = "event"
NATURES_WANTED = ("episode", "trailer")   # CF-0575: the work's own cuts of the event
NATURES_REFUSED = ("interview",)          # CF-0575: not another production's couch
KIND_THING = "thing"       # CF-0425: a prop or an object - nothing to search for
ROLE_CREW, ROLE_ON_SCREEN = "crew", "on_screen"

# Capitalised for a reason other than being a name: sentence openers,
# pronouns, function words. Compared lower-cased with a trailing 's removed.
STOP = frozenset("""
a an and as at back but by each even every for from he her here his how i if in
it its just not now of on one only or our she so still that the their then there
these they this those three to trade two six we what when where which while who
why with yet you after before during into over under also meanwhile later
""".split())
# Capitalised words that are never part of a searchable name here.
NOT_NAMES = frozenset("""
january february march april may june july august september october november
december monday tuesday wednesday thursday friday saturday sunday
emmy emmys oscar oscars golden globe globes grammy grammys tony tonys award awards
best actor actress supporting lead series season episode part chapter comedy drama
limited outstanding tv
director directors writer writers screenwriter cinematographer producer producers
composer editor showrunner creator filmmaker
christmas easter halloween thanksgiving theaters theatres cinemas
""".split())
# A run with one of these words is an event, not a person (CF-0372: "Cannes
# Film Festival" was a `person`). Awards words are cut out of runs already
# (`NOT_NAMES`), so what is left of an awards night never reaches `_classify`.
EVENT_WORDS = frozenset("""
festival fest gala premiere ceremony ceremonies expo convention biennale telethon
""".split())

# CF-0372: the roles of a person, as words standing right before the name.
CREW_WORDS = (r"(?:co-?)?(?:director|writer|screenwriter|cinematographer|showrunner|creator|"
              r"producer|composer|editor|filmmaker|auteur)s?|dp|dop|"
              r"director\s+of\s+photography|executive\s+producer")
CREW_BY = (r"(?:shot|directed|written|co-written|produced|scored|lensed|photographed|"
           r"created|edited|helmed|filmed)\s+by")
ON_SCREEN_WORDS = (r"actor|actress|actors|star|co-?star|starring|stars|host|comedian|"
                   r"singer|rapper|athlete|(?:played|portrayed|voiced|hosted)\s+by")
WORK_WORDS = r"films?|pictures?|movies?|joint|production"
PLACE_WORDS = frozenset("""
park studios studio street square island islands city county beach hall theatre
theater stadium center centre lake river valley mountains heights hills village
castle palace manor estate airport station bridge road avenue lot arena gardens
cathedral church abbey chapel basilica temple monastery mosque synagogue shrine
tower museum gallery opera auditorium auditorio library university college
hospital harbor harbour bay coast desert forest canyon falls peak cove pier
plaza boulevard hotel market quarter district province island
""".split())
# CF-0425: a last word naming an object makes the run a thing ("Infinity
# Stones" was a `person`). Compared lower-cased. Mostly plurals: a singular
# that is also a surname (Emma Stone, Armie Hammer, Russell Crowe's Crown)
# stays out - a person read as a thing loses a search, the other way round
# only spends one.
THING_WORDS = frozenset("""
stones gems jewels gauntlet gauntlets rings swords shields suits helmets masks
relic relics amulet amulets necklace wand wands spears blades guns rifles
ships cars trucks armor armour throne thrones
""".split())

WORD = r"[A-Z][A-Za-z'’.-]*"
RUN_RE = re.compile(rf"{WORD}(?:(?::\s+|\s+)(?:{WORD}|\d+\b))*")
# Abbreviations whose full stop is part of the name ("St. Louis").
ABBREV = frozenset({"St.", "Mt.", "Ft.", "Dr.", "Jr.", "Sr."})
# A first word that makes the run a place whatever follows ("St. Louis").
PLACE_PREFIX = frozenset({"st.", "saint", "mt.", "mount", "fort", "port", "lake", "cape",
                          "santa", "san", "são", "sao", "los", "las", "isle"})
# CF-0425: words that put the name after them in a place ("inside Durham
# Cathedral", "standing in as a location in Santa Cruz", "filmed in ...").
# Plain "in" / "at" is not enough ("starring in", "at Johnny Depp's side").
PLACE_BEFORE = (r"inside|outside|near|(?:location|locations|filmed|shot|set|"
                r"located|based|town|city|village)\s+(?:in|at)")
NAME_SHAPED = re.compile(r"^[A-Z][A-Za-z'’-]*[a-z]$")
HYPHEN_COMMON = re.compile(r"^[A-Z][a-z]+-[a-z]+$")    # Co-star, Well-known
POSSESSIVE = re.compile(r"['’]s$")
QUOTES = "'’‘\""


def _bare(token):
    """A word without its trailing punctuation, possessive `'s`, and (CF-0425)
    the quote closing round it or the plural possessive's apostrophe:
    `Eggers'` -> `Eggers`, `Endgame'` -> `Endgame`."""
    if token in ABBREV:
        return token
    return POSSESSIVE.sub("", token.rstrip(".,;")).rstrip(QUOTES)


def _noise(token):
    low = _bare(token).casefold()
    return (low in STOP or low in NOT_NAMES or bool(HYPHEN_COMMON.match(token))
            or low.endswith("'s") or low.endswith("’s"))


def _runs(text):
    """Capitalised runs of `text`, each split at its noise words and trimmed."""
    out = []
    for m in RUN_RE.finditer(text or ""):
        # keep "Title: Subtitle" as one piece, split the rest on whitespace
        parts = re.split(r"\s+", m.group(0))
        current = []
        for tok in parts:
            if _noise(tok.rstrip(":")):
                if current:
                    out.append(current)
                current = []
                continue
            current.append(tok)
        if current:
            out.append(current)
    cleaned = []
    for run in out:
        run = [_bare(t) if not t.endswith(":") else t for t in run]
        while run and run[-1].endswith(":"):
            run[-1] = run[-1].rstrip(":")
            if not run[-1]:
                run.pop()
        if run:
            cleaned.append(run)
    return cleaned


def _placed(name, text):
    """CF-0425: `name` stands right after a preposition of place in `text`."""
    return bool(text) and bool(re.search(
        rf"(?i:\b(?:{PLACE_BEFORE}))\s+(?:the\s+)?{re.escape(name)}\b(?!['’]s)", text))


def _classify(run, text=None):
    """The kind of one run; `text` (the anchor's words) lets a name standing
    after a preposition of place be a place (CF-0425)."""
    name = " ".join(run)
    if any(t.casefold() in EVENT_WORDS for t in run):
        return KIND_EVENT
    if any(ch.isdigit() for ch in name) or ":" in name:
        return KIND_SHOW
    if run[-1].casefold() in PLACE_WORDS or run[0].casefold() in PLACE_PREFIX:
        return KIND_PLACE
    if run[-1].casefold() in THING_WORDS:
        return KIND_THING
    if len(run) <= 3 and all(NAME_SHAPED.match(t) for t in run):
        return KIND_PLACE if _placed(name, text) else KIND_PERSON
    return KIND_SHOW


def title_of(script):
    ref = (script or {}).get("title_ref")
    if isinstance(ref, dict):
        ref = ref.get("name")
    return ref.strip() if isinstance(ref, str) and ref.strip() else None


def _cut_title(text, title):
    if not title:
        return text or ""
    return re.sub(re.escape(title) + r"(?:['’]s)?", " . ", text or "", flags=re.I)


def _anchor_text(anchor, title):
    if not isinstance(anchor, dict):
        return ""
    # A sentence break between the two fields, so a run cannot span them.
    return " . ".join(_cut_title(anchor.get(k), title) for k in ("phrase", "beat_text"))


def script_people(script):
    """Every person the script's anchors name in full - what a lone surname
    elsewhere in the script is resolved against."""
    title = title_of(script)
    people = []
    for a in (script or {}).get("visual_anchors") or []:
        atext = _anchor_text(a, title)
        for run in _runs(atext):
            if len(run) >= 2 and _classify(run, atext) == KIND_PERSON:
                name = " ".join(run)
                if name not in people:
                    people.append(name)
    return people


def _script_text(script):
    """All the script's words a role can be read from: every anchor's frame
    and narration, and the production fact (its source sentence names the
    crew by trade - "cinematographer Joaquin Baca-Asay")."""
    parts = []
    for a in (script or {}).get("visual_anchors") or []:
        if isinstance(a, dict):
            parts += [a.get("phrase"), a.get("beat_text")]
    fact = (script or {}).get("production_fact")
    if isinstance(fact, dict):
        parts += [fact.get(k) for k in ("text", "beat_text", "on_screen")]
    return " . ".join(p for p in parts if isinstance(p, str))


def _before(words, name):
    """`words` (a role pattern, any case) right before `name` (exact case),
    chained ("writer director", "writer-director", "director and co-writer")."""
    return re.compile(rf"(?i:\b(?:{words})(?:\s*(?:[-/,&]|and)\s*(?:{words}))*)"
                      rf"[\s,:-]+{name}\b")


def person_role(name, text):
    """CF-0372: `crew` or `on_screen` for one person, by the rule of the
    module docstring."""
    forms = [re.escape(name)]
    if len(name.split()) > 1:
        forms.append(re.escape(name.split()[-1]))
    who = "(?:" + "|".join(forms) + ")"
    if _before(ON_SCREEN_WORDS, who).search(text):
        return ROLE_ON_SCREEN
    crew = (_before(CREW_WORDS, who).search(text)
            or re.search(rf"(?i:\b{CREW_BY})\s+{who}\b", text)
            or re.search(rf"(?i:\ban?)\s+{who}(?:['’]s)?\s+(?:[a-z-]+\s+){{0,2}}"
                         rf"(?i:{WORK_WORDS})\b", text))
    return ROLE_CREW if crew else ROLE_ON_SCREEN


def script_roles(script, people=None):
    """`{name: role}` for every person the script names in full."""
    people = script_people(script) if people is None else people
    text = _script_text(script)
    return {p: person_role(p, text) for p in people}


def _add(out, name, kind, role=None):
    if not any(e["name"].casefold() == name.casefold() for e in out):
        e = {"name": name, "kind": kind}
        if kind == KIND_PERSON:
            e["role"] = role or ROLE_ON_SCREEN
        out.append(e)


def _searchable(entity):
    """CF-0372: what the request may name - not a person behind the camera,
    not an event; CF-0425: not a thing."""
    return (entity["kind"] not in (KIND_EVENT, KIND_THING)
            and entity.get("role") != ROLE_CREW)


def anchor_entities(anchor, script, people=None, roles=None):
    """The named entities one anchor is about, `[{name, kind[, role]}]`, in
    the order they first appear - the rule of the module docstring."""
    title = title_of(script)
    people = script_people(script) if people is None else people
    if roles is None:
        roles = script_roles(script, people)
    text = None
    out = []
    atext = _anchor_text(anchor, title)
    for run in _runs(atext):
        if len(run) >= 2:
            name, kind = " ".join(run), _classify(run, atext)
            role = None
            if kind == KIND_PERSON:
                role = roles.get(name)
                if role is None:
                    text = _script_text(script) if text is None else text
                    role = person_role(name, text)
            _add(out, name, kind, role)
            continue
        word = run[0]
        full = [p for p in people if p.split()[-1] == word]
        if len(full) == 1:
            _add(out, full[0], KIND_PERSON, roles.get(full[0]))
    return out


# --------------------------------------------------------------------------
# what each gate says is missing
# --------------------------------------------------------------------------

def _anchor_rows(script, indices):
    anchors = (script or {}).get("visual_anchors") or []
    people = script_people(script)
    roles = script_roles(script, people)
    rows = []
    for i in indices:
        if not isinstance(i, int) or not 0 <= i < len(anchors):
            continue
        a = anchors[i] if isinstance(anchors[i], dict) else {}
        rows.append({"anchor_index": i, "anchor_id": a.get("anchor_id"),
                     "phrase": a.get("phrase"), "beat_text": a.get("beat_text"),
                     "entities": anchor_entities(a, script, people, roles)})
    return rows


def _is_topic_work(name, title):
    return bool(title) and name.casefold() == title.casefold()


def _keep(entity, anchor_entities_):
    """CF-0349, the hunter's foreign-work rule (CF-0343) applied at the
    source: a work that is not the topic's goes into the request only beside a
    person named in the same anchor - alone it would bring that work's frames,
    not the topic's, and the hunter would skip it anyway."""
    if entity["kind"] not in (KIND_SHOW, KIND_WORK):
        return True
    return any(e["kind"] == KIND_PERSON and _searchable(e) for e in anchor_entities_)


def topic_entities(script):
    """CF-0349: the people and places the whole script names, in anchor
    order - what a gap is also answered by when its own anchor names nobody
    (`everyday-sorcery-2`'s house) or only another work (its box-office beat)."""
    people = script_people(script)
    roles = script_roles(script, people)
    out = []
    for a in (script or {}).get("visual_anchors") or []:
        for e in anchor_entities(a, script, people, roles):
            if e["kind"] in (KIND_PERSON, KIND_PLACE) and _searchable(e):
                _add(out, e["name"], e["kind"], e.get("role"))
    return out


def block(script, indices, shots_wanted):
    """The `supplement` block of one warning: the uncovered anchors with
    their entities, the entities together (a foreign work only beside a
    person of its anchor), the people and places of the whole script, the
    shots the pool is short."""
    rows = _anchor_rows(script, sorted({i for i in indices if isinstance(i, int)}))
    title = title_of(script)
    entities = []
    for r in rows:
        for e in r["entities"]:
            if not _searchable(e):
                continue
            if _is_topic_work(e["name"], title) or _keep(e, r["entities"]):
                _add(entities, e["name"], e["kind"], e.get("role"))
    return {"anchors": rows, "entities": entities,
            "topic_entities": topic_entities(script),
            "shots_wanted": max(1, int(shots_wanted or 0)),
            "work": title}


def from_coverage(script, report):
    """The preflight's verdict: every anchor it did not cover, one shot each."""
    idx = [a.get("anchor_index") for a in (report or {}).get("anchors") or []
           if isinstance(a, dict) and a.get("verdict") != "covered"]
    return block(script, idx, len(idx))


def from_pool(script, record):
    """The pool's margin (CF-0274): no single anchor is to blame, so every
    anchor's entities are asked for; the shots are the distinct samples the
    pool lacks to hold the anchors plus the margin."""
    anchors = record.get("anchors") or 0
    short = anchors + (record.get("margin_required") or 0) - (record.get("distinct_samples") or 0)
    return block(script, range(len((script or {}).get("visual_anchors") or [])), short)


def from_blocks(script, record):
    """Block capacity (CF-0284): the driver anchors of the empty blocks, one
    shot per empty block."""
    empty = [b for b in record.get("blocks") or [] if isinstance(b, dict) and b.get("empty")]
    return block(script, [b.get("anchor") for b in empty],
                 len(record.get("blocks_empty") or empty))


def event_entity(script, record):
    """CF-0575: the event as a searchable name - the scene's person (the
    hunter's `title_ref.person`) and its moment ("Dana Reyes monologue"),
    or the work and the moment when the topic names no person."""
    tr = (script or {}).get("title_ref") or {}
    moment = (record or {}).get("moment") or "scene"
    who = tr.get("person") or title_of(script)
    return {"name": f"{who} {moment}".strip(), "kind": KIND_SCENE,
            "scene_id": (record or {}).get("scene_id"), "moment": moment}


def from_event(script, record):
    """CF-0575: the event's own footage is short. The anchors that retell the
    scene, and only two entities: the work (its own cuts) and the event - not
    the people of the script, whose search brings the interviews the Editor
    refuses under these words (`d7b1ilF5290`, 0701Z)."""
    rows = _anchor_rows(script, sorted(i for i in (record or {}).get("event_anchors") or []
                                       if isinstance(i, int)))
    title = title_of(script)
    entities = []
    if title:
        _add(entities, title, KIND_WORK)
    ev = event_entity(script, record)
    entities.append(ev)
    return {"anchors": rows, "entities": entities, "topic_entities": [],
            "shots_wanted": max(1, int((record or {}).get("short_by") or 0)),
            "work": title, "event": ev,
            "natures_wanted": list(NATURES_WANTED),
            "natures_refused": list(NATURES_REFUSED)}


def from_sides(script, record):
    """Alternate sides (CF-0285): the anchors written on a side that cannot
    carry its slots, one shot per slot that side leaves unfilled."""
    thin, short = [], 0
    for side, r in (record.get("per_side") or {}).items():
        missing = (r.get("slots") or 0) - (r.get("filled") or 0)
        if missing > 0:
            thin.append(side)
            short += missing
    # The driver anchors of that side's blocks (the Editor's plan); a record
    # without them falls back to the anchors written on that side.
    idx = [b.get("anchor") for b in record.get("blocks") or []
           if isinstance(b, dict) and b.get("side") in thin]
    if not idx:
        anchors = (script or {}).get("visual_anchors") or []
        idx = [i for i, a in enumerate(anchors) if isinstance(a, dict) and a.get("side") in thin]
    return block(script, idx, short)


# --------------------------------------------------------------------------
# the request skeleton
# --------------------------------------------------------------------------

def request_path(batch_dir, topic_id):
    safe = re.sub(r"[^\w.-]", "_", str(topic_id))
    return Path(batch_dir) / REQUEST_DIR / f"{safe}.json"


# CF-0422: is the topic's request still open? The thin-pool supplement step
# (the factory root's `shared/runlog/supplement.py`, CF-0345) keeps its record
# at `work/supplement-step.json` -> `topics[<topic_id>].phase`; these are its
# words. A request is *closed* once the step has finished the topic - `done`
# (answered) or `skipped` (it gave up after its tool attempts, CF-0350). Any
# other state is open: the skeleton lies in `supplement-requests/` and the step
# has not taken it (no record, or `failed` - a tool failed and the attempt is
# retried), or the hunter answered and the request was moved to `consumed/`
# while its sources still owe descriptions and the sieve (`fetched`). A fresh
# skeleton the step's recheck lays for a topic it already finished is not
# open: the step gives a topic one round per batch.
STEP_RECORD = Path("work") / "supplement-step.json"
CONSUMED_DIR = "consumed"
PHASES_CLOSED = ("done", "skipped")


def open_request(batch_dir, topic_id):
    """`{"path", "phase"}` of the topic's open supplement request, else None."""
    if not topic_id:
        return None
    path = request_path(batch_dir, topic_id)
    found = None
    for p in (path, path.parent / CONSUMED_DIR / path.name):
        try:
            req = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(req, dict) and req.get("kind") == KIND:
            found = p
            break
    if found is None:
        return None
    try:
        record = json.loads((Path(batch_dir) / STEP_RECORD).read_text())
    except (OSError, ValueError):
        record = {}
    topics = record.get("topics") if isinstance(record, dict) else None
    entry = topics.get(str(topic_id)) if isinstance(topics, dict) else None
    phase = entry.get("phase") if isinstance(entry, dict) else None
    if phase in PHASES_CLOSED:
        return None
    return {"path": str(found), "phase": phase or "not taken"}


def skeleton(topic_id, warnings):
    """One topic's `thin_pool_supplement` request out of its pool warnings.

    Entities, in the order the hunter takes them round-robin (CF-0349):
    first the uncovered anchors' own entities, then the topic's work (`kind:
    work`, always - ahead of the rest so the hunter's search cap never drops
    it), then the people and places of the whole script. `shots_wanted` is
    the largest shortfall any gate measured - the gates count the same
    missing pictures from different sides, so they are not added up.

    CF-0575: with an `event_footage_short` warning the request is the event's
    (`reason_code`, `event`, `natures_wanted`/`natures_refused`): the work and
    the event first, other gates' entities only for anchors outside the
    event, no whole-script people."""
    entities, rest, anchors, gates, wanted, work = [], [], [], [], 0, None
    codes = [c for c in REASON_CODES if any(w.get("warning_code") == c for w in warnings)]
    event = None
    # CF-0575: the event's request names the event first - ahead of every other
    # gate's entities, so the hunter's search cap never drops it.
    warnings = sorted(warnings, key=lambda w: w.get("warning_code") != EVENT_REASON_CODE)
    event_anchors = set()
    for w in warnings:
        sup = w.get(FIELD) or {}
        if w.get("warning_code") == EVENT_REASON_CODE:
            event = event or sup.get("event")
            event_anchors.update(a.get("anchor_index") for a in sup.get("anchors") or [])
            ents = sup.get("entities") or []
        elif event:
            # CF-0575: beside the event's request another gate's entities count
            # only for the anchors that do not retell the event - a search for
            # the people under the event's words brings the interviews the
            # Editor refuses there - and the whole script's people not at all.
            ents = [e for a in sup.get("anchors") or []
                    if a.get("anchor_index") not in event_anchors
                    for e in a.get("entities") or []
                    if e.get("kind") not in (KIND_SHOW, KIND_WORK)
                    or _is_topic_work(e.get("name") or "", sup.get("work"))]
        else:
            ents = sup.get("entities") or []
        for e in ents:
            if _searchable(e):
                _add(entities, e["name"], e["kind"], e.get("role"))
        for e in ([] if event else sup.get("topic_entities") or []):
            if _searchable(e):
                _add(rest, e["name"], e["kind"], e.get("role"))
        for a in sup.get("anchors") or []:
            if a.get("anchor_index") not in {x.get("anchor_index") for x in anchors}:
                anchors.append(a)
        wanted = max(wanted, sup.get("shots_wanted") or 0)
        work = work or sup.get("work")
        if w.get("gate") not in gates:
            gates.append(w.get("gate"))
    if work:
        _add(entities, work, KIND_WORK)
    for e in rest:
        _add(entities, e["name"], e["kind"], e.get("role"))
    out = {"kind": KIND, "topic_id": topic_id,
           "reason_code": EVENT_REASON_CODE if event else REASON_CODE,
           "entities": entities, "shots_wanted": max(1, wanted),
           "max_attempts": MAX_ATTEMPTS,
           "gates": gates,
           "anchors": sorted(anchors, key=lambda a: a.get("anchor_index", 0)),
           "decision": DECISION}
    if event:
        # CF-0575: what kind of footage answers it - the work's own cuts of the
        # event, never another production's interview.
        out.update(reason_codes=codes or [EVENT_REASON_CODE], event=event,
                   natures_wanted=list(NATURES_WANTED),
                   natures_refused=list(NATURES_REFUSED),
                   decision=DECISION + "; CF-0575: the event's own footage under its words")
    return out


def sync(batch_dir, data, topic_ids):
    """Bring `work/supplement-requests/` in line with `data["warnings"]` for
    the topics just judged: a topic with a pool warning that carries a
    `supplement` block gets its skeleton (re)written whole - a re-run
    replaces it, never appends - and a topic with none loses the skeleton an
    earlier run wrote. Returns `(written, removed)` as paths."""
    written, removed = [], []
    for tid in dict.fromkeys(t for t in topic_ids if t):
        mine = [w for w in data.get("warnings") or []
                if isinstance(w, dict) and w.get("topic_id") == tid
                and w.get("warning_code") in REASON_CODES and isinstance(w.get(FIELD), dict)]
        path = request_path(batch_dir, tid)
        if not mine:
            if path.exists():
                path.unlink()
                removed.append(path)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(skeleton(tid, mine), indent=2, ensure_ascii=False) + "\n")
        os.replace(tmp, path)
        written.append(path)
    return written, removed


def lines(written, removed):
    out = [f"  supplement request: {p} (no candidates yet - Trend Hunter fills them, "
           f"CF-0338)" for p in written]
    out += [f"  supplement request removed (the pool covers it now): {p}" for p in removed]
    return out
