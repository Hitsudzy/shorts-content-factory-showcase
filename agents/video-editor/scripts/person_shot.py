#!/usr/bin/env python3
"""CF-0879: a block that names person X does not take a close face of Y.

The case. wicker 0841Z (`pipeline/example-film/2026-10-26T0841Z`): under
"Four. Peter Dinklage is the basket weaver" stood `ob-KN-uRkB0:7`, a close
face from "Wicker Co-Stars Olivia Colman and Alexander Skarsgård Watch Early
Career Clips Together" - Skarsgård, not Dinklage; under "Elizabeth Debicki
plays the tailor's" an older man dabbing his mouth (Richard E. Grant).
the-gilded-age 0836Z: under "Fellowes called writing The Gilded Age ..." an
interview of a blonde woman. CF-0877 taught the frame judge to see "the name
over another face" (`mismatch: person`), but the judge only rejects a video
already built; the defect is born here, at the choice of the shot.

Pool shots carry no identity labels - only the describer's `description` and
the framing's `roi_source`. What can be read without looking again:

* **who the script names** (`script_people()`): never "every capitalised
  run" - only the script's own list: `title_ref.person`, the cast pairs of
  `story_claims` (actor -> character, CF-0533/CF-0540), their `attribution`,
  and the people the claims quote or cast ("reported Julian Fellowes as
  saying", "Carrie Coon was cast as", "X plays", "X said");
* **their sex, when the script says it** (`gender`): the cast character's
  head noun ("the Tailor's Wife", "the Wicker Husband") and the pronouns of
  the script's sentences that name that person and nobody else of the list
  ("Julian Fellowes said he was", "the way Coon presents herself"). No cue
  -> unknown -> no sex rule for that person;
* **a shot of one person in front** (`single_person()`): the framing found
  faces (`roi_source: faces`) or the description leads with one person
  ("An older man in a vest ..."), and the description is not a crowd, a
  group, a couple or a wide scene;
* **whose source it is** (`title_owners()`): the people of the list the
  source's YouTube title names (`01b`/hunter/registry title, the same record
  CF-0545 reads).

A single-person shot is **foreign** to X when its source's title names
somebody of the list and not X, or when its description's sex contradicts
X's. A block naming several people is fine as long as the shot fits one of
them (a man under "Debicki ... and Richard E. Grant is the doctor").

What the editor does with it (`resolve_anchors.py`): before any rung, each
anchor whose words name somebody loses its foreign candidates - but only when
a non-foreign candidate over the similarity floor stays (a neutral picture -
a crowd, a wide shot, an object - or a shot of X's own source). With no such
replacement the foreign shot is kept: a block with no picture is worse. Every
block's names go on the block (`names_person`), and a block that still shows
a foreign face is a `person_shot_risk` warning in the plan - mode `measure`
(CF-0320): no price, no refusal, until the user signs one.

CF-0913 (Reel 27.10-01.11: 13 of 24 refused videos had a face under a
name it was not; 9 of 27 such blocks named a job behind the camera, and the
list above held none of them - "Taika Waititi directed Klara and the Sun",
"written by Dolly Alderton", "Casting directors Debra Zane and Dylan Jury"):
the people named for a job behind the camera (director, writer, showrunner,
creator, cinematographer, composer, producer, casting) join the list with
`role: crew` (`crew_names()`), unless the script puts them in front of the
camera too ("Sacha Baron Cohen wrote, produced, directed and stars"; a cast
pair) - those are `role: cast`. A single-person shot is foreign to a crew
name when its source's title does not name that person: the work's own
trailer shows its characters, not its director. Same screen, same
`min_score` replacement rule, same measure mode - no price, no refusal.

Pure json/regex - no CLIP, no vision, no network.
"""
import re
import unicodedata

TASK = "CF-0879"
FIELD = "names_person"            # storyboard/plan block: the people its words name
RECORD = "person_shot"            # storyboard/plan top-level record
WARNING = "person_shot_risk"      # plan.warnings[].gate / warning_code
MODE = "measure"                  # CF-0320: no price until the user signs one

FEMALE, MALE = "f", "m"

_FEMALE_WORDS = {
    "woman", "girl", "lady", "wife", "mother", "mom", "mum", "daughter", "sister",
    "aunt", "niece", "grandmother", "grandma", "queen", "princess", "actress",
    "heroine", "widow", "bride", "girlfriend", "waitress", "nun", "witch",
    "duchess", "empress", "countess", "baroness", "mistress", "maid",
    "matriarch", "stepmother", "stepdaughter", "goddess", "hostess"}
_MALE_WORDS = {
    "man", "boy", "gentleman", "husband", "father", "dad", "son", "brother",
    "uncle", "nephew", "grandfather", "grandpa", "king", "prince", "widower",
    "groom", "boyfriend", "monk", "priest", "wizard", "duke", "emperor", "baron",
    "lord", "patriarch", "stepfather", "stepson", "god", "host", "actor"}
_NOT_MAN = {"human", "shaman", "woman", "german", "talisman", "caiman", "ottoman"}
_SHE = {"she", "her", "hers", "herself"}
_HE = {"he", "him", "his", "himself"}

# The describer's words for a sex, on the picture (description of a shot).
_DESC_FEMALE = _FEMALE_WORDS | {"she", "her", "herself"}
_DESC_MALE = ({"man", "boy", "gentleman", "husband", "father", "king", "actor",
               "he", "his", "him", "himself", "beard", "bearded", "moustache",
               "mustache", "moustached", "mustached", "businessman"})

# A description of more than one person, or of no one in front.
_GROUP_RE = re.compile(
    r"\b(crowds?|group|audience|guests|extras|dancers|people|villagers|crew|"
    r"ensemble|panel|couple|family|men|women|children|kids|friends|soldiers|"
    r"two|three|four|five|several|many|both|together|everyone|team|band|"
    r"choir|students|spectators|onlookers|partygoers|congregation)\b", re.I)
# A description that leads with one person.
_ONE_LEAD_RE = re.compile(
    r"^\s*(?:(?:an?\s+)?(?:extreme\s+|medium\s+|tight\s+)?close[- ]?up(?:\s+shot)?\s+of\s+|"
    r"close\s+view\s+of\s+|portrait\s+of\s+|interview\s+(?:of|with)\s+)?"
    r"(?:a|an|the)\s+(?:[\w'’-]+\s+){0,4}?"
    r"(man|woman|boy|girl|person|actor|actress|gentleman|lady)\b", re.I)

# A description whose own words put one face in front.
_FACE_LEAD_RE = re.compile(
    r"^\s*(?:an?\s+)?(?:(?:extreme\s+|medium\s+|tight\s+)?close[- ]?up(?:\s+shot)?\s+of|"
    r"close\s+view\s+of|portrait\s+of|interview\s+(?:of|with))\s+(?:a|an|the)\s+"
    r"(?:[\w'’-]+\s+){0,4}?(man|woman|boy|girl|person|actor|actress|gentleman|lady)\b",
    re.I)
# Single people a description can mention.
_PERSON_NOUNS = {
    "man", "woman", "boy", "girl", "person", "actor", "actress", "gentleman",
    "lady", "operator", "cameraman", "director", "host", "interviewer",
    "reporter", "presenter", "figure", "child", "soldier", "guard", "coachman",
    "driver", "butler", "maid", "waiter", "waitress", "officer", "doctor",
    "nurse", "priest", "singer", "dancer", "anchor"}

# Names the claims quote or cast. NAME: 2-4 capitalised words.
_NAME = r"([A-Z][\w'’.\-]*(?:\s+[A-Z][\w'’.\-]*){1,3})"
_SPEECH = (r"said|says|told|tells|recalled|recalls|explained|explains|added|adds|"
           r"wrote|writes|called|calls|described|describes|admitted|admits|"
           r"revealed|reveals|confirmed|confirms|insisted|insists|noted|notes|"
           r"spoke|speaks|discussed|discusses")
_CLAIM_NAME_RES = [
    re.compile(r"\breported\s+" + _NAME + r"\s+as\s+saying"),
    re.compile(r"\baccording\s+to\s+" + _NAME),
    re.compile(_NAME + r"\s+(?:" + _SPEECH + r")\b"),
    re.compile(_NAME + r"\s+(?:was|is|has\s+been|had\s+been|were)\s+cast\s+as\b"),
    re.compile(_NAME + r"\s+(?:plays|played|portrays|portrayed|voices|voiced|"
                       r"stars\s+as|starred\s+as)\b"),
]
# CF-0913: a job behind the camera. Somebody the script names only for one
# of these is not on screen in the work's own footage - a trailer shows its
# characters, not its director, writer, showrunner or casting director.
_CREW_NOUN = (r"(?:co-?)?(?:directors?|filmmakers?|writers?|screenwriters?|showrunners?|"
              r"creators?|cinematographers?|directors?\s+of\s+photography|composers?|"
              r"(?:executive\s+)?producers?|casting\s+directors?|authors?|novelists?)")
# A name that never runs over a sentence's end: a word, or an initial with
# its period ("Sean S. Cunningham"), never "Alderton. Two. Linus".
_CREW_TOKEN = r"(?:[A-Z]\.|[A-Z][\w'’\-]*)"
_CREW_NAME = r"(" + _CREW_TOKEN + r"(?:\s+" + _CREW_TOKEN + r"){1,3})"
_CREW_VERB = (r"(?:co-?)?(?:directed|directs|wrote|writes|created|creates|produced|"
              r"produces|developed|develops)")
# "X directed", "X created it", "X replaced Y as director of photography",
# "Matalas serves as showrunner".
_CREW_AFTER_RES = [
    re.compile(_CREW_NAME + r"\s+" + _CREW_VERB + r"\b"),
    re.compile(_CREW_NAME + r",?\s+(?:[\w'’-]+\s+){0,4}?(?:as|is|was)\s+(?:the\s+|a\s+|an\s+|its\s+)?"
               r"(?:[\w'’-]+['’]s?\s+)?" + _CREW_NOUN + r"\b"),
]
# "directed by X", "co-written, directed, and co-produced by X",
# "director Christopher Nolan", "Casting directors Debra Zane and Dylan Jury".
_CREW_BEFORE_RES = [
    re.compile(r"\b(?:co-?)?(?:directed|written|created|produced|developed)\b"
               r"(?:[^.;]{0,40}?)\bby\s+(?=[A-Z])"),
    re.compile(r"\b" + _CREW_NOUN + r"\s+(?=[A-Z])", re.I),
]
# A list of names ends in "and" ("A, B and C"); a comma alone ends the list
# ("director Francis Lawrence, Jennifer Lawrence said" - she is no director).
_NAME_LIST_RE = re.compile(_CREW_NAME + r"(?:(?:\s*,\s*" + _CREW_NAME + r")*,?\s+and\s+" + _CREW_NAME + r")?")
# Words of a cast member next to the name ("X ... stars in the film").
_CAST_AFTER = (r"(?:[\w'’,-]+\s+){0,4}?(?:stars?|starred|starring|plays|played|"
               r"portrays|portrayed|voices|voiced|reprises|reprised|"
               r"(?:is|was|has\s+been)\s+cast)\b")
_CAST_BEFORE = r"\b(?:starring|actor|actress|co-?star|stars?)\s+"
CREW = "crew"
CAST = "cast"

# Capitalised words that start a sentence or name a trade, not a person.
_LEAD_SKIP = {
    "then", "in", "and", "but", "so", "when", "after", "before", "the", "now",
    "later", "also", "meanwhile", "while", "here", "there", "this", "that",
    "actor", "actress", "director", "star", "creator", "writer", "producer",
    "showrunner", "co-star", "costar", "executive", "series", "since", "on",
    "at", "by", "with", "as", "if", "even", "only", "still", "yet", "once",
    "ceo", "founder", "co-founder", "cofounder", "president", "chief", "head",
    "boss", "chairman", "chairwoman", "chair", "author", "host", "singer"}
# A run with one of these is an outlet or a company, not a person.
_ORG_WORDS = {
    "the", "newsroom", "news", "times", "post", "telegraph", "journal",
    "reuters", "variety", "deadline", "inc", "corp", "studios", "studio",
    "pictures", "entertainment", "network", "channel", "magazine", "media",
    "examplestream", "example network", "nbc", "abc", "cbs", "bbc", "itv", "fox", "example animation",
    "example pictures", "apple", "google", "amazon", "microsoft", "warner", "universal",
    "sony", "reporter", "hollywood", "guardian", "independent", "vulture",
    "wikipedia", "daily", "weekly", "tribune", "herald", "press", "records",
    "films", "film", "tv", "television", "radio", "company", "group",
    "university", "institute", "deepmind", "openai", "anthropic", "meta"}

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


def fold(text):
    """Accents off, case kept ("Skarsgård" -> "Skarsgard")."""
    s = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _tokens(text):
    """The words of a text, accents folded, case kept, possessive cut
    ("Stallone's" -> "Stallone", "E." -> "E")."""
    out = []
    for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’\-]*", fold(text)):
        t = re.sub(r"['’]s?$", "", t)
        if t:
            out.append(t)
    return out


def _name_tokens(name):
    return [t.lower() for t in _tokens(name)]


def named_in(text, name):
    """Does `text` name `name` - the full name in a row, or the surname alone
    as a capitalised word (`Fellowes called ...`)? Accent- and case-blind for
    the full name; the lone surname has to be capitalised, so "grant" the
    verb is not Richard E. Grant."""
    want = _name_tokens(name)
    if not want:
        return False
    toks = _tokens(text)
    low = [t.lower() for t in toks]
    n = len(want)
    for i in range(len(low) - n + 1):
        if low[i:i + n] == want:
            return True
    if len(want) >= 2 and len(want[-1]) >= 3:
        sur = want[-1]
        return any(t.lower() == sur and t[:1].isupper() for t in toks)
    return False


def names_in(text, people):
    """The people of `people` (`[{"name": ...}]` or names) that `text`
    names, in the list's order, each once."""
    out = []
    for p in people or []:
        name = p.get("name") if isinstance(p, dict) else p
        if name and name not in out and named_in(text, name):
            out.append(name)
    return out


def _clean_name(run):
    """A capitalised run cut down to a person's name, or None: sentence
    openers and trade words off the front, nothing with an outlet's word in
    it, two to four words left."""
    toks = str(run or "").split()
    while toks and toks[0].lower().strip(".,") in _LEAD_SKIP:
        toks = toks[1:]
    if not 2 <= len(toks) <= 4:
        return None
    if any(re.search(r"['’]s?$", t) for t in toks[:-1]):
        return None                          # "Stallone's daughter Scarlet"
    if any(t.lower().strip(".,") in _ORG_WORDS for t in toks):
        return None
    if not all(t[:1].isupper() for t in toks):
        return None
    return " ".join(toks).strip(" ,.;:")


def _crew_name(run, after=True):
    """A capitalised run cut to a name at a sentence's end: a name before
    its verb loses the sentence before it ("Two. Linus Sandgren replaced"),
    a name after its trigger loses the sentence after it ("written by Dolly
    Alderton. Two. Linus"); an initial ("Sean S. Cunningham") is no end.
    Then `_clean_name`."""
    toks = str(run or "").split()
    ends = [i for i, t in enumerate(toks) if t.endswith(".") and len(t.strip(".")) > 1]
    if ends and after:
        toks = toks[ends[-1] + 1:]
    elif ends:
        toks = toks[:ends[0] + 1]
        toks[-1] = toks[-1].rstrip(".")
    return _clean_name(" ".join(toks))


def crew_names(texts):
    """CF-0913: the names the texts give a job behind the camera
    (`_CREW_AFTER_RES`, `_CREW_BEFORE_RES`), in order, each once."""
    out = []

    def keep(run, after=True):
        name = _crew_name(run, after)
        if name and name not in out:
            out.append(name)

    for t in texts:
        for rx in _CREW_AFTER_RES:
            for m in rx.finditer(t):
                keep(m.group(1))
        for rx in _CREW_BEFORE_RES:
            for m in rx.finditer(t):
                lst = _NAME_LIST_RE.match(t, m.end())
                if not lst:
                    continue
                for run in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", lst.group(0)):
                    keep(run, after=False)
                    if re.search(r"\w\w\.(?:\s|$)", run):
                        break           # the sentence ended inside this name
    return out


def _cast_cue(name, texts):
    """Do the texts put `name` in front of the camera ("X ... stars in the
    film", "starring X")? Full name or capitalised surname, as `named_in`."""
    toks = _tokens(name)
    if not toks:
        return False
    forms = [r"\s+".join(map(re.escape, toks))]
    if len(toks) >= 2 and len(toks[-1]) >= 3:
        forms.append(re.escape(toks[-1]))
    for t in texts:
        f = fold(t)
        for form in forms:
            if re.search(r"\b" + form + r"\b['’]?s?,?\s+" + _CAST_AFTER, f) or \
                    re.search(_CAST_BEFORE + form + r"\b", f):
                return True
    return False


def _texts(script):
    """Every sentence source of the script a sex can be read from: the
    narration, the claims and their quotes, the cast claims."""
    s = script or {}
    out = [s.get(k) for k in ("hook", "commentary", "payoff")]
    for c in s.get("claims") or []:
        if isinstance(c, dict):
            out.append(c.get("text"))
            out += [q.get("quote") for q in c.get("support") or [] if isinstance(q, dict)]
    for c in s.get("story_claims") or []:
        if isinstance(c, dict):
            out += [c.get("text"), c.get("beat_text")]
    return [t for t in out if isinstance(t, str) and t.strip()]


def _noun_sex(word):
    w = str(word or "").lower()
    if w in _FEMALE_WORDS or (w.endswith("woman") and len(w) > 5):
        return FEMALE
    if w in _MALE_WORDS or (w.endswith("man") and w not in _NOT_MAN and len(w) > 3):
        return MALE
    return None


def _gender(name, character, texts, all_names):
    """(sex or None, the cues it was read from)."""
    votes = {FEMALE: 0, MALE: 0}
    cues = []
    if character:
        toks = _tokens(character)
        sex = _noun_sex(toks[-1]) if toks else None
        if sex:
            votes[sex] += 2
            cues.append(f"character {character!r}")
    others = [n for n in all_names if n != name]
    for t in texts:
        for sent in _SENT_SPLIT.split(t):
            if not named_in(sent, name) or any(named_in(sent, o) for o in others):
                continue
            low = [w.lower() for w in _tokens(sent)]
            f = sum(1 for w in low if w in _SHE)
            m = sum(1 for w in low if w in _HE)
            if f or m:
                votes[FEMALE] += f
                votes[MALE] += m
                cues.append(sent.strip()[:120])
    if votes[FEMALE] > votes[MALE]:
        return FEMALE, cues
    if votes[MALE] > votes[FEMALE]:
        return MALE, cues
    return None, cues


def script_people(script):
    """`[{"name", "from", "character", "gender", "gender_from"}]` - the
    people this script names, from its own lists (module docstring)."""
    s = script or {}
    found = []                      # (name, from, character)

    def add(name, source, character=None):
        name = re.sub(r"\s+", " ", str(name or "")).strip(" ,.;:")
        if not name:
            return
        key = [t.lower() for t in _tokens(name)]
        for i, (n, src, ch) in enumerate(found):
            k = [t.lower() for t in _tokens(n)]
            if k == key:
                if character and not ch:
                    found[i] = (n, src, character)
                return
            if len(key) < len(k) and k[-len(key):] == key:
                return              # "Fellowes" inside "Julian Fellowes"
            if len(k) < len(key) and key[-len(k):] == k:
                found[i] = (name, source, character or ch)
                return
        found.append((name, source, character))

    ref = s.get("title_ref") if isinstance(s.get("title_ref"), dict) else {}
    person = ref.get("person")
    if isinstance(person, dict):
        person = person.get("name")
    if isinstance(person, str) and person.strip():
        add(person, "title_ref")
    for c in s.get("story_claims") or []:
        if not isinstance(c, dict):
            continue
        if c.get("actor"):
            add(c["actor"], "cast", c.get("character"))
        att = _clean_name(c.get("attribution")) if c.get("attribution") else None
        if att:
            add(att, "attribution")
    for c in s.get("claims") or []:
        if not isinstance(c, dict):
            continue
        texts = [c.get("text")] + [q.get("quote") for q in c.get("support") or []
                                   if isinstance(q, dict)]
        for t in texts:
            if not isinstance(t, str):
                continue
            for rx in _CLAIM_NAME_RES:
                for m in rx.finditer(t):
                    name = _clean_name(m.group(1))
                    if name:
                        add(name, "claims")
    texts = _texts(s)
    # CF-0913: the people named for a job behind the camera (director,
    # writer, showrunner, cinematographer, casting) - Waititi under "Taika
    # Waititi directed Klara and the Sun" was on nobody's list.
    crew = crew_names(texts)
    for name in crew:
        add(name, CREW)
    names = [n for n, _, _ in found]
    out = []
    for name, source, character in found:
        sex, cues = _gender(name, character, texts, names)
        out.append({"name": name, "from": source, "character": character,
                    "gender": sex, "gender_from": cues[:3],
                    "role": _role(name, source, character, crew, texts)})
    return out


def _role(name, source, character, crew, texts):
    """`crew` - named for a job behind the camera and nowhere for a part in
    front of it, nor the topic's own person; `cast` - a part of the work;
    None - neither is said."""
    if character or source == "cast" or _cast_cue(name, texts):
        return CAST
    if source == "title_ref":
        return None
    want = _name_tokens(name)
    for c in crew:
        have = _name_tokens(c)
        short, long_ = sorted((want, have), key=len)
        # the same person: the same words, or the longer name ending in the
        # shorter one of 2+ words ("Baron Cohen" in "Sacha Baron Cohen") -
        # never a shared surname alone (Jennifer and Francis Lawrence)
        if have == want or (len(short) >= 2 and long_[-len(short):] == short):
            return CREW
    return None


def roi_source(shot):
    shot = shot or {}
    cached = shot.get("usable_cached") if isinstance(shot.get("usable_cached"), dict) else {}
    return cached.get("roi_source") or shot.get("roi_source")


def _people_count(description):
    """How many single people the description mentions by a person noun."""
    return sum(1 for w in _tokens(description) if w.lower() in _PERSON_NOUNS)


def single_person(shot):
    """Does this shot put one person in front? A description that leads
    with a close-up, a portrait or an interview of someone is one by its own
    words. Otherwise: the framing found faces, or the description leads with
    one person - and the description is no crowd, group, couple or wide
    scene, and mentions no second person ("a camera operator ... while an
    actress ..." is a set, not a face)."""
    desc = str((shot or {}).get("description") or "")
    if _GROUP_RE.search(desc):
        return False
    if _FACE_LEAD_RE.search(desc):
        return True
    if _people_count(desc) > 1:
        return False
    if roi_source(shot) == "faces":
        return True
    return bool(_ONE_LEAD_RE.search(desc))


def description_sex(description):
    """The sex the description gives its people, or None (none, or both)."""
    low = {w.lower() for w in _tokens(description)}
    f = bool(low & _DESC_FEMALE)
    m = bool(low & _DESC_MALE)
    if f and not m:
        return FEMALE
    if m and not f:
        return MALE
    return None


def title_owners(title, people):
    """The people of the list a source's title names."""
    return names_in(title or "", people) if title else []


def _person(people, name):
    for p in people or []:
        if isinstance(p, dict) and p.get("name") == name:
            return p
    return {"name": name, "gender": None}


def risk(shot, title, named, people):
    """Why this shot is somebody else's face under these names - `[]` when
    it is not a single-person shot, when nobody is named, or when it fits at
    least one named person."""
    if not named or not single_person(shot):
        return []
    owners = title_owners(title, people)
    dsex = description_sex((shot or {}).get("description"))
    reasons = []
    for x in named:
        why = []
        if owners and x not in owners:
            why.append(f"its source is titled {title!r} - {', '.join(owners)}'s, not {x}'s")
        xsex = _person(people, x).get("gender")
        if xsex and dsex and xsex != dsex:
            word = {FEMALE: "a woman", MALE: "a man"}
            why.append(f"the description shows {word[dsex]} and {x} is {word[xsex]}")
        if _person(people, x).get("role") == CREW and x not in owners:
            why.append(f"{x} is named for a job behind the camera and its source "
                       f"is not titled with {x} - a character or a cast member "
                       f"of the footage, not {x} (CF-0913)")
        if not why:
            return []
        reasons += [f"{x}: {w}" for w in why]
    return reasons


def reason_text(shot_key, named, reasons):
    return (f"shot {shot_key} is one person in front under words naming "
            f"{', '.join(named)}, and it is somebody else: {'; '.join(reasons)} "
            f"({TASK})")


def words_text(words, start_index, end_index):
    return " ".join(str(w.get("word", "")) for w in (words or [])[start_index:end_index])


def span_text(words, start, end):
    """The words heard over [start, end) - a word counts when it overlaps
    the span, the frame judge's reading (frame_judge_pack.narration)."""
    return " ".join(str(w.get("word", "")) for w in words or []
                    if float(w.get("end", 0)) > start and float(w.get("start", 0)) < end)


def anchor_names(anchors, words, people):
    """The people each anchor's words name, word_index to the next anchor's."""
    wi = [a["word_index"] for a in anchors]
    return [names_in(words_text(words, wi[i], wi[i + 1] if i + 1 < len(wi) else len(words)),
                     people) for i in range(len(wi))]


def screen_matches(matches, names_by_anchor, shot_of, title_of, people, min_score):
    """Take the foreign single-person shots out of each named anchor's
    candidates, in place - only when a non-foreign candidate at or over
    `min_score` stays. Returns `(refused, kept)`: one
    `{phrase, shot, score, reason}` per removed candidate, and one
    `{phrase, names_person, shots}` per anchor that had to keep its foreign
    shots for want of a replacement. `shot_of(cand)` -> shots.json entry,
    `title_of(cand)` -> its source's title."""
    refused, kept = [], []
    for i, m in enumerate(matches):
        named = names_by_anchor[i] if i < len(names_by_anchor) else []
        if not named:
            continue
        ok, bad = [], []
        for c in m.get("candidates") or []:
            why = risk(shot_of(c), title_of(c), named, people)
            (bad if why else ok).append((c, why))
        if not bad:
            continue
        if any(float(c.get("score") or 0) >= float(min_score or 0) for c, _ in ok):
            m["candidates"] = [c for c, _ in ok]
            for c, why in bad:
                refused.append({"phrase": m.get("phrase"), "shot": c.get("shot"),
                                "score": c.get("score"),
                                "reason": reason_text(c.get("shot"), named, why)})
        else:
            kept.append({"phrase": m.get("phrase"), "names_person": named,
                         "shots": [c.get("shot") for c, _ in bad]})
    return refused, kept


def block_shot_refs(block):
    """`[(key, video id, shot number)]` of every picture a block shows."""
    import entity_guard  # this repo's reading of a block's shots (CF-0665)
    return [(key, entity_guard.source_id(src), n)
            for key, src, n in entity_guard._shot_refs(block)]


def block_risks(blocks, words, people, shot_by_key, title_of_vid,
                start_key="_start", end_key="_end"):
    """Stamp `names_person` on every block (in place) and return the blocks
    that still show a foreign face: `[{block, names_person, shot, reasons}]`.
    `shot_by_key(vid, n)` -> shots.json entry, `title_of_vid(vid)` -> title."""
    out = []
    for i, b in enumerate(blocks or []):
        if not isinstance(b, dict):
            continue
        try:
            start, end = float(b[start_key]), float(b[end_key])
        except (KeyError, TypeError, ValueError):
            continue
        named = names_in(span_text(words, start, end), people)
        b[FIELD] = named
        if not named:
            continue
        for key, vid, n in block_shot_refs(b):
            why = risk(shot_by_key(vid, n), title_of_vid(vid), named, people)
            if why:
                out.append({"block": i, "names_person": named, "shot": key,
                            "reasons": why})
                break
    return out


def record(people, refused, kept, risky):
    """The storyboard's / plan's `person_shot` record."""
    return {"task": TASK, "mode": MODE,
            "people": people,
            "refused": len(refused),
            "kept_for_want_of_replacement": kept,
            "risky_blocks": risky}


def warning(script_id, r):
    """One `plan.warnings[]` record for a risky block - the shape of a
    plan_refusal warning (script_id, gate, reason, severity, decision,
    numbers), with no funnel code: a measured rule, never a refusal yet."""
    return {"script_id": script_id, "gate": WARNING, "warning_code": WARNING,
            "severity": "warn", "mode": MODE, "task": TASK,
            "block": r["block"], "shot": r["shot"],
            "names_person": list(r["names_person"]),
            "reason": (f"block {r['block']} names {', '.join(r['names_person'])} and "
                       f"shows {r['shot']}, one person in front who is somebody "
                       f"else: {'; '.join(r['reasons'])} - no replacement without "
                       f"one face in front, nor of their own source"),
            "numbers": {"block": r["block"]},
            "decision": (f"CF-0320: measure - no price and no refusal until the "
                         f"user signs one ({TASK})")}
