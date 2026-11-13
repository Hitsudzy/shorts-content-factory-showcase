#!/usr/bin/env python3
"""CF-0533: claims about real people in the retelling, under CF-0438's rule.

The defect. The published `coach-hale` (example-film/2026-10-01T1313Z) said
"Anthony Hart, the actor who played her [Mae], died this year". Anthony Hart
played Rupert; Mae is Annette Bramwell. The fact rule (`fact_rule.py`,
CF-0184/0438) and compliance (CF-0187) judged only the script's `fact` field;
the retelling around it - a model's synthesis of two Deadline headlines - went
through as a given. Every sentence in `commentary` about a real person was
outside the strict rule that exists precisely for claims about real people.

The user's decision of 2026-10-05, rule 2: the scriptwriter declares every
claim `commentary` makes about a real person in `script.story_claims[]`, and
this module checks them deterministically:

    {"kind": "cast" | "person_event", "text", "beat_text",
     "source_url", "attribution", ["actor", "character"]}

* `cast` - "actor X plays Y". The pair must stand on one line of the cast
  section of the work's Wikipedia article (`Cast and characters` / `Cast` /
  `Starring`, with its `Main` / `Recurring` / `Guests` subsections). No such
  line -> `cast_mismatch`. The character is matched against the line's
  *character slot* (the words after "as", up to the description), not the
  whole line: Rupert's line says "Rebecca's vindictive ex-husband", and
  "Anthony Hart played Rebecca" must not pass on it. `actor` / `character`
  are optional structured fields; without them both are read out of `text`
  against the names the cast section holds.
* `person_event` - a death, an illness, an arrest, a departure, a scandal -
  is no longer a kind of this list (CF-0556, the grill's Q11: "through the
  quote"). Until then it went through `fact_rule.check_candidate` (a major
  outlet and an attribution); now it is a `script.claims[]` entry (CF-0552)
  with a verbatim quote of the topic's support text - the news item that
  reports it, or Wikipedia - and the root's claim judge (CF-0553) decides
  whether the quote says it. A `person_event` entry here is
  `claim_malformed`, its detail says where it goes.
* Completeness - every actor of the cast section whose full name occurs in
  `commentary` is covered by some claim - a `cast` claim here (its `text` or
  `actor`) or a `claims[]` entry naming them - otherwise
  `person_claim_undeclared`. Without it the rule is dodged by silence, which
  is exactly what the published script did.
* `beat_text` is a verbatim substring of `commentary`, as for every other
  field of a script that points into it (`beat_text_not_in_commentary`).

The cast comes from Wikipedia through the CF-0237 client
(`shared/wikipedia/wikipedia_api.py` since CF-0551, before that the Content
Researcher's `scripts/wikipedia_api.py`: `WikipediaClient`, `resolve_article`) - the same host, endpoints, User-Agent, interval floor and
retry etiquette, nothing of its own on the network. What this module adds is
a disk cache *at the transport seam* (`cached_transport`, which moved
into the client module with CF-0551 and is re-exported here): a recorded answer
is served instead of a request, so one article is read once per cache
lifetime however many scripts and re-runs ask about it, and the tests run on
a cache directory of recorded answers with a transport that refuses to go
out. When Wikipedia cannot be asked, or has no article / no cast section, the
cast state says so and every `cast` claim is `cast_unverifiable`: a pair
nobody could check is not a pair that passed.

CF-0543's plot half (`script.plot_claims[]`, `plot_claims.py`: who killed /
betrayed whom, held to one clause of a headline) was retired by CF-0556 after
the claims exam: a plot claim is a `claims[]` entry with a verbatim quote of
the topic's support text, judged by `claim_judge.py` - the exam struck
Harbourlights' "Zorvath is behind the kill" there on the finale's own summary.
`topic=` is still accepted and ignored, so an old caller does not break.

Stdlib only; the Wikipedia client is loaded by path (or handed in by the
caller, which is what the Content Researcher does with its own module).
"""
import importlib.util
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
# CF-0231: a neighbour loads this file by path; register the directory before
# naming the sibling, as every module of shared/runlog/ does.
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import fact_rule  # noqa: E402

RULE = "CF-0533"
CLAIMS_FIELD = "story_claims"
# What the Content Researcher writes onto the script: this module's answer.
CHECK_FIELD = "story_claims_check"

KIND_CAST = "cast"
KIND_PERSON_EVENT = "person_event"
CLAIM_KINDS = (KIND_CAST,)                 # person_event: a claims[] entry since CF-0556
QUOTED_CLAIMS_FIELD = "claims"             # = claims.CLAIMS_FIELD (CF-0552)
CLAIM_KEYS = ("kind", "text", "beat_text")
CLAIM_OPTIONAL_KEYS = ("source_url", "attribution", "actor", "character",
                       "primary_url", "source_type", "quote")

FAIL_CAST_MISMATCH = "cast_mismatch"
FAIL_CAST_UNVERIFIABLE = "cast_unverifiable"
FAIL_UNDECLARED = "person_claim_undeclared"
FAIL_BEAT_NOT_IN_COMMENTARY = "beat_text_not_in_commentary"
FAIL_CLAIM_MALFORMED = "claim_malformed"
PEOPLE_FAIL_CODES = (FAIL_CAST_MISMATCH, FAIL_CAST_UNVERIFIABLE,
                     FAIL_UNDECLARED, FAIL_BEAT_NOT_IN_COMMENTARY, FAIL_CLAIM_MALFORMED)
FAIL_CODES = PEOPLE_FAIL_CODES
# The topic's refusal after the one rewrite. (`plot_claim_failed`, CF-0543's
# plot half, was retired by CF-0556; funnel.py still reads it in old batches.)
SKIP_PEOPLE = "story_claim_failed"
PERSON_EVENT_MOVED = ("a death / illness / arrest / departure / scandal of a real person is a "
                      "`claims[]` entry with a verbatim quote of the topic's support text (the "
                      "news item that reports it), judged by the claim judge - not a "
                      "story_claims kind since CF-0556")

ACTION_PASS = "pass"
ACTION_FAIL = "fail"

CAST_FOUND = "found"
CAST_NO_ARTICLE = "no_article"
CAST_NO_SECTION = "no_cast_section"
CAST_UNREACHABLE = fact_rule.STATE_UNREACHABLE
CAST_NOT_ASKED = "not_asked"        # the title_ref names no work

# A cached answer older than this is asked again (a cast list changes on the
# scale of a season, not of a day). None in a call = never expires. The cache
# itself lives in the client module since CF-0551; these are its numbers.
CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600
CACHED_STATUSES = (200, 404)
# CF-0551: the client moved to the shared layer, next to this package.
WIKIPEDIA_API_REL = "shared/wikipedia/wikipedia_api.py"

HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)
CAST_HEADING_RE = re.compile(r"\b(cast|characters|starring)\b", re.I)
_REF_RE = re.compile(r"<ref[^>]*/>|<ref[^>]*>.*?</ref\s*>", re.S | re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]")
_LINK_TARGET_RE = re.compile(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]")
# CF-0540: "Tom Carver as:" with the characters on the nested lines below.
_AS_RE = re.compile(r"\s+as\s*:\s*|\s+as\s+|\s+as$")
_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}")
_TEMPLATE_ARG_SPLIT_RE = re.compile(r"\|(?![^\[]*\]\])")
# Templates that stand for a person's name in a cast line (CF-0540): an
# interlanguage link and `sortname` are the name as a link; the wrappers keep
# their text. Every other template is dropped, as before.
LINK_NAME_TEMPLATES = {"ill", "ill2", "illm", "interlanguage link",
                       "interlanguage link multi", "link-interwiki", "ill-wd"}
TEXT_TEMPLATES = {"nowrap", "nobr", "nobold", "small", "abbr", "plainlist"}
_SLOT_END_RE = re.compile(r"\(|<|:|\s[–—-]\s|;")
_SPLIT_NAMES_RE = re.compile(r"\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
SELF_WORDS = {"himself", "herself", "themselves", "themself", "itself"}
TITLE_WORDS = {"dr", "mr", "mrs", "ms", "miss", "coach", "sir", "lady", "lord",
               "captain", "the", "young", "old", "officer", "detective", "agent"}


# ------------------------------------------------------------------- names
def norm(text):
    """Lower case, accents off, quotes straightened - what two spellings of
    one name have in common (Cristo Fernández / Cristo Fernandez)."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("‘", "'")
    return text.lower()


def tokens(text):
    """Name tokens: possessive dropped (Rebecca's -> rebecca)."""
    return [t for t in _TOKEN_RE.findall(re.sub(r"'s\b", "", norm(text))) if t]


def name_in(name, text):
    """A whole name, as words, in the text."""
    words = tokens(name)
    if not words:
        return False
    pattern = r"\b" + r"\W+".join(re.escape(w) for w in words) + r"\b"
    return re.search(pattern, re.sub(r"'s\b", "", norm(text))) is not None


def _key_tokens(name):
    return [t for t in tokens(name) if t not in TITLE_WORDS]


# --------------------------------------------------------- the cast section
def _name_template(m):
    parts = [p.strip() for p in _TEMPLATE_ARG_SPLIT_RE.split(m.group(1))]
    name = parts[0].lower().replace("_", " ").strip()
    args = [p for p in parts[1:] if p and not re.match(r"^[\w -]+=", p)]
    if name in LINK_NAME_TEMPLATES and args:
        return f"[[{args[0]}]]"
    if name == "sortname" and len(args) >= 2:
        return f"[[{args[0]} {args[1]}]]"
    if name == "lang" and len(args) >= 2:
        return args[1]
    if name in TEXT_TEMPLATES and args:
        return args[0]
    return m.group(0)


def name_templates(line):
    """Name-bearing templates turned into what they show (CF-0540):
    `{{ill|Mercedes Hernández|es}}` -> `[[Mercedes Hernández]]`,
    `{{sortname|Tom|Cruise}}` -> `[[Tom Carver]]`, `{{nowrap|...}}` -> its
    text. The rest stays for `_clean` to drop. References go first: a
    citation is never a name."""
    line = _COMMENT_RE.sub("", line)
    line = _REF_RE.sub("", line)
    for _ in range(4):
        new = _TEMPLATE_RE.sub(_name_template, line)
        if new == line:
            break
        line = new
    return line


def _clean(line):
    line = _COMMENT_RE.sub("", line)
    line = _REF_RE.sub("", line)
    line = re.sub(r"<ref[^>]*>.*$", "", line, flags=re.S | re.I)   # an unclosed ref
    # templates: innermost first, a few rounds are enough for a list line
    for _ in range(4):
        line = re.sub(r"\{\{[^{}]*\}\}", "", line)
    line = _LINK_RE.sub(lambda m: m.group(1), line)
    line = _TAG_RE.sub("", line)
    line = line.replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", line).strip()


def cast_text(wikitext):
    """[(heading, text)] of every top cast section of an article: a heading
    naming the cast, with everything under it down to the next heading of its
    own level or higher. A matching subsection inside one already taken is
    part of it, not a second section."""
    heads = list(HEADING_RE.finditer(wikitext or ""))
    out = []
    i = 0
    while i < len(heads):
        m = heads[i]
        level = len(m.group(1))
        if not CAST_HEADING_RE.search(m.group(2)):
            i += 1
            continue
        end = len(wikitext)
        j = i + 1
        while j < len(heads):
            if len(heads[j].group(1)) <= level:
                end = heads[j].start()
                break
            j += 1
        out.append((m.group(2).strip(), wikitext[m.end():end]))
        i = j
    return out


def _actors_of(part):
    part = re.sub(r"\([^)]*\)", "", part)
    names = [n.strip(" ,.;:\"'") for n in _SPLIT_NAMES_RE.split(part)]
    return [n for n in names if n and any(ch.isupper() for ch in n[:1])]


def character_slot(rest):
    """The character's name(s) after "as": up to the first parenthesis,
    colon, dash or `<`, then comma by comma while the next piece is a short
    capitalised name that is not a possessive ("Rebecca's ex-husband" opens
    the description, "Jeremy Blumenthal" continues a list of three)."""
    m = _SLOT_END_RE.search(rest)
    rest = rest[:m.start()] if m else rest
    pieces = [p.strip() for p in rest.split(",")]
    slot = [pieces[0]] if pieces else []
    for piece in pieces[1:]:
        piece = re.sub(r"^and\s+", "", piece)
        words = piece.split()
        if (not words or not words[0][:1].isupper() or len(words) > 4
                or re.search(r"'s$|’s$", words[0])):
            break
        slot.append(piece)
    return ", ".join(p for p in slot if p).strip(" .\"")


def _before_parenthesis(body):
    """The line up to its first parenthesis outside a link: the actor of
    `[[Corey Reyes (actor)|Corey Reyes]] (season 2)` is still linked."""
    masked = re.sub(r"\[\[[^\]]*\]\]", lambda m: "x" * len(m.group(0)), body)
    cut = masked.find("(")
    return body if cut < 0 else body[:cut]


def _line_entry(line, body, section):
    """One cast line read on its own: `{actors, slot, characters, line,
    section, unparsed}`, or None when it names no actor. `unparsed` is a line
    that holds more than its actors but no character could be read out of it
    ("Tom Carver as:" before its nested lines are seen, "Actor - Character"):
    a claim about such an actor cannot be checked, which is not the same as
    being contradicted (CF-0540)."""
    split = _AS_RE.split(line, maxsplit=1)
    unparsed = False
    if len(split) == 2:
        actors = _actors_of(split[0])
        slot = character_slot(split[1])
        if slot and norm(slot).split()[0] in SELF_WORDS:
            slot = ""
        elif not slot:
            unparsed = True
    else:
        linked = [m.group(2) or m.group(1)
                  for m in _LINK_TARGET_RE.finditer(_before_parenthesis(body))]
        actors = [_clean(n) for n in linked if n]
        slot = ""
        rest = re.sub(r"\([^)]*\)", "", line)
        for actor in actors:
            rest = rest.replace(actor, " ")
        # "Actor - Character" / "Actor: Character": a character slot in a
        # form this parser does not read. A comma and a lower-case clause
        # ("..., who are members of ...") is a description, not a slot.
        unparsed = bool(re.search(r"(?:[–—:]|\s-\s)\s*[A-Z]", rest))
    if not actors:
        return None
    characters = [c.strip(" \"") for c in _SPLIT_NAMES_RE.split(slot) if c.strip(" \"")]
    return {"actors": actors, "slot": slot, "characters": characters,
            "line": line, "section": section, "unparsed": unparsed}


def cast_entries(wikitext):
    """Every line of the cast section(s) as `{actors, slot, characters,
    line, section, unparsed}`. `slot` is "" for a line without "as" (a cameo
    as a group) and for "as himself".

    Nesting (CF-0540, Delver 0701Z): an actor whose line ends in "as" / "as:"
    plays the characters of the nested (`**`) lines under it - one entry per
    nested character, the actor's own. A nested line under an actor whose
    character is already read is a description and names no actor of its own
    (its links are an oil tycoon and Greenland, not cast), unless it is
    itself an "Actor as Character" line."""
    entries = []
    for heading, text in cast_text(wikitext):
        parent = None          # the last top-level actor line
        for raw in text.splitlines():
            stripped = raw.lstrip()
            if not stripped.startswith(("*", "#")):
                continue
            depth = len(stripped) - len(stripped.lstrip("*#"))
            body = name_templates(stripped.lstrip("*#: ").strip())
            line = _clean(body)
            if not line:
                continue
            nested = depth > 1 and parent is not None
            own_line = (len(_AS_RE.split(line, maxsplit=1)) == 2
                        and body.startswith("[["))     # "** [[Actor]] as Character"
            if nested and parent["awaiting"] and not own_line:
                piece = re.sub(r"^as\s+", "", line, flags=re.I)
                slot = character_slot(piece)
                if slot and norm(slot).split()[0] not in SELF_WORDS:
                    parent["entry"]["drop"] = True
                    entries.append({
                        "actors": list(parent["entry"]["actors"]), "slot": slot,
                        "characters": [c.strip(" \"") for c in _SPLIT_NAMES_RE.split(slot)
                                       if c.strip(" \"")],
                        "line": f"{parent['entry']['line']} {line}", "section": heading,
                        "unparsed": False})
                continue
            if nested and len(_AS_RE.split(line, maxsplit=1)) < 2:
                continue        # a description of the actor above
            entry = _line_entry(line, body, heading)
            if entry is None:
                if not nested:
                    parent = None
                continue
            entries.append(entry)
            if not nested:
                parent = {"entry": entry,
                          "awaiting": entry["unparsed"] and bool(_AS_RE.search(line))
                          and not _AS_RE.split(line, maxsplit=1)[1].strip()}
    return [e for e in entries if not e.pop("drop", False)]


def cast_from_article(article, state=CAST_FOUND, error=None):
    """The cast record this module reads, out of a `wikipedia_api.article_of`
    article (or None)."""
    if article is None:
        return {"state": state if state != CAST_FOUND else CAST_NO_ARTICLE,
                "article": None, "entries": [], "error": error}
    entries = cast_entries(article.get("wikitext") or "")
    return {"state": CAST_FOUND if entries else CAST_NO_SECTION,
            "article": {"title": article.get("title"), "url": article.get("url"),
                        "revised_at": article.get("revised_at")},
            "entries": entries, "error": error}


# ------------------------------------------------- the transport and cache
def wikipedia_api(root=None):
    """The CF-0237 client module, `shared/wikipedia/wikipedia_api.py` of the
    factory root (CF-0551), registered under its one `sys.modules` name so
    every loader in a process gets the same module object (and the same
    `WikipediaError` to catch)."""
    root = Path(root) if root else HERE.parents[1]
    path = (root / WIKIPEDIA_API_REL).resolve()
    name = "factory_wikipedia_api"
    held = sys.modules.get(name)
    if held is not None and Path(getattr(held, "__file__", "")).resolve() == path:
        return held
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def cache_name(url):
    """The file one answer is kept in - the client module's (CF-0551)."""
    return wikipedia_api().cache_name(url)


def cached_transport(cache_dir, wp, transport=None,
                     max_age_seconds=CACHE_MAX_AGE_SECONDS, clock=time.time):
    """`wp.cached_transport` (CF-0551 moved it into the client module); the
    signature with `wp` is kept for the callers written before."""
    wp = wp or wikipedia_api()
    return wp.cached_transport(cache_dir, transport=transport,
                               max_age_seconds=max_age_seconds, clock=clock)


def wikipedia_client(cache_dir=None, wp=None, root=None, transport=None, **kw):
    """A CF-0237 client whose network goes through the cache (when given)."""
    wp = wp or wikipedia_api(root)
    if cache_dir:
        transport = cached_transport(cache_dir, wp, transport)
    return wp.WikipediaClient(transport=transport, **kw)


def cast_of(title_ref, client=None, wp=None, cache_dir=None, root=None):
    """The cast record of the work a script is about. The parent work when
    the title_ref names one (a spin-off season's cast is in its parent's
    article), the season deliberately not: the series article lists every
    season's main and recurring cast, a season article only its own."""
    title_ref = title_ref or {}
    name = (title_ref.get("parent_work") or title_ref.get("name") or "").strip()
    if not name or title_ref.get("kind") not in (None, "work"):
        return {"state": CAST_NOT_ASKED, "article": None, "entries": [], "error": None}
    wp = wp or wikipedia_api(root)
    client = client or wikipedia_client(cache_dir=cache_dir, wp=wp)
    try:
        article = wp.resolve_article(
            client, name, year=title_ref.get("year"),
            accept=lambda a: bool(cast_entries(a.get("wikitext") or "")),
            work_type=title_ref.get("type"))
    except wp.WikipediaError as error:
        return {"state": CAST_UNREACHABLE, "article": None, "entries": [],
                "error": str(error)}
    return cast_from_article(article)


# --------------------------------------------------------------- the check
def _violation(code, index, claim, detail):
    claim = claim if isinstance(claim, dict) else {}
    return {"code": code, "claim_index": index, "kind": claim.get("kind"),
            "text": claim.get("text"), "detail": detail}


def actors_named(text, entries):
    """The cast's actors whose full name is in the text, in cast order."""
    seen = []
    for entry in entries:
        for actor in entry["actors"]:
            if actor not in seen and name_in(actor, text):
                seen.append(actor)
    return seen


def _without(text, names):
    low = re.sub(r"'s\b", "", norm(text))
    for name in names:
        low = re.sub(r"\b" + r"\W+".join(re.escape(w) for w in tokens(name)) + r"\b", " ", low)
    return low


def characters_named(text, entries, skip=(), actors=None):
    """The cast's characters the text names: the full name, or its first or
    last key token as a word (a script says "Mae", the list "Mae Green").

    CF-0540: when the text names a character of two or more key words in
    full, those full names are the answer and a shared surname does not drag
    in the rest of the family ("Kenny Rockwell" is not "Delver Rockwell").
    The full names are looked for with only the `actors` taken out - the
    work's own title may be a character's first name (Delver / Delver
    Rockwell)."""
    full_text = _without(text, skip if actors is None else actors)
    full = []
    for entry in entries:
        for character in entry["characters"]:
            if (len(_key_tokens(character)) >= 2 and name_in(character, full_text)
                    and character not in full):
                full.append(character)
    if full:
        return full
    low = re.sub(r"'s\b", "", norm(text))
    for name in skip:
        low = re.sub(r"\b" + r"\W+".join(re.escape(w) for w in tokens(name)) + r"\b", " ", low)
    # a lone first or last name counts only capitalised: "will" is not Will Kitman
    plain = unicodedata.normalize("NFKD", text or "")
    words = {w.lower() for w in re.findall(r"[A-Za-z0-9]+", plain) if w[:1].isupper()}
    for name in skip:
        words -= set(tokens(name))
    found = []
    for entry in entries:
        for character in entry["characters"]:
            keys = _key_tokens(character)
            if not keys:
                continue
            hit = name_in(character, low) or any(
                k in words for k in {keys[0], keys[-1]} if len(k) >= 3)
            if hit and character not in found:
                found.append(character)
    return found


def plays(entry, character):
    """Does this cast line's slot hold that character? Every key token of the
    name has to be in the slot (`Coach Hale` is not `Coach Willis Beard`)."""
    keys = _key_tokens(character)
    return bool(keys) and set(keys) <= set(tokens(entry["slot"]))


def check_cast_claim(claim, cast, skip_names=()):
    """None, or (code, detail) for one `cast` claim."""
    if cast.get("state") != CAST_FOUND:
        return FAIL_CAST_UNVERIFIABLE, (
            f"the cast could not be read ({cast.get('state')}"
            + (f": {cast['error']}" if cast.get("error") else "") + ")")
    entries = cast["entries"]
    text = claim.get("text") or ""
    actors = [claim["actor"]] if (claim.get("actor") or "").strip() else actors_named(text, entries)
    if not actors:
        return FAIL_CAST_MISMATCH, "the claim names no actor of the article's cast list"
    if (claim.get("character") or "").strip():
        characters = [claim["character"].strip()]
    else:
        characters = characters_named(text, entries, skip=list(actors) + list(skip_names),
                                      actors=list(actors))
    if not characters:
        return FAIL_CAST_MISMATCH, "the claim names no character of the article's cast list"
    problems = []
    unreadable = []
    for actor in actors:
        lines = [e for e in entries if any(norm(a) == norm(actor) for a in e["actors"])]
        if not lines:
            problems.append(f"{actor} is not in the cast list")
        elif not any(plays(e, c) for e in lines for c in characters):
            # CF-0540: a line the parser could not read a character out of
            # neither confirms nor contradicts the pair - unverifiable.
            unread = [e for e in lines if e.get("unparsed")]
            if unread:
                unreadable.append(f"{actor}'s cast line could not be read for its character: "
                                  f"{unread[0]['line'][:160]}")
                continue
            listed = "; ".join(e["slot"] or "(no character)" for e in lines)
            problems.append(f"{actor} is listed as {listed}, not as {' / '.join(characters)}")
    if problems:
        return FAIL_CAST_MISMATCH, "; ".join(problems + unreadable)
    if unreadable:
        return FAIL_CAST_UNVERIFIABLE, "; ".join(unreadable)
    return None


def check_story_claims(script, sources=None, cast=None, client=None, wp=None,
                       cache_dir=None, root=None, topic=None):
    """The script's `story_claims[]` against the rule. Returns the record the
    Content Researcher writes as `story_claims_check`:

        {"rule", "action": "pass"|"fail", "claims", "violations": [
            {"code", "claim_index", "kind", "text", "detail"}],
         "cast_source": {"state", "title", "url", "revised_at", "entries", "error"}}

    `sources` is accepted and unused (the person_event half went to claims[],
    CF-0556). `topic` is accepted and ignored (CF-0543's plot half,
    retired by CF-0556). `cast` is a record from `cast_of` / `cast_from_article`
    when the caller already has one; otherwise it is resolved from
    `script.title_ref` through `client` / `wp` / `cache_dir`."""
    script = script or {}
    commentary = script.get("commentary") or ""
    claims = script.get(CLAIMS_FIELD)
    claims = claims if isinstance(claims, list) else []
    if cast is None:
        cast = cast_of(script.get("title_ref"), client=client, wp=wp,
                       cache_dir=cache_dir, root=root)
    work = ((script.get("title_ref") or {}).get("name") or "").strip()
    skip = [work] if work else []
    violations = []

    for i, claim in enumerate(claims):
        if isinstance(claim, dict) and claim.get("kind") == KIND_PERSON_EVENT:
            violations.append(_violation(FAIL_CLAIM_MALFORMED, i, claim, PERSON_EVENT_MOVED))
            continue
        if not isinstance(claim, dict) or claim.get("kind") not in CLAIM_KINDS \
                or not (claim.get("text") or "").strip():
            violations.append(_violation(FAIL_CLAIM_MALFORMED, i, claim,
                                         f"a claim is an object with `kind` in {CLAIM_KINDS} "
                                         f"and a non-empty `text`"))
            continue
        beat = claim.get("beat_text") or ""
        if not beat.strip() or beat not in commentary:
            violations.append(_violation(FAIL_BEAT_NOT_IN_COMMENTARY, i, claim,
                                         "`beat_text` is not a verbatim substring of `commentary`"))
        found = check_cast_claim(claim, cast, skip_names=skip)
        if found:
            violations.append(_violation(found[0], i, claim, found[1]))

    if cast.get("state") == CAST_FOUND:
        quoted = script.get(QUOTED_CLAIMS_FIELD)
        covered = " \n ".join(
            " ".join(str(c.get(k) or "") for k in ("text", "actor"))
            for c in claims + (quoted if isinstance(quoted, list) else [])
            if isinstance(c, dict))
        for actor in actors_named(commentary, cast["entries"]):
            if not name_in(actor, covered):
                line = next(e["line"] for e in cast["entries"] if actor in e["actors"])
                violations.append(_violation(FAIL_UNDECLARED, None, None, {
                    "name": actor, "cast_line": line[:200]}))

    article = cast.get("article") or {}
    record = {"rule": RULE,
              "action": ACTION_FAIL if violations else ACTION_PASS,
              "claims": len(claims),
              "violations": violations,
              "cast_source": {"state": cast.get("state"), "title": article.get("title"),
                              "url": article.get("url"),
                              "revised_at": article.get("revised_at"),
                              "entries": len(cast.get("entries") or []),
                              "error": cast.get("error")}}
    return record


def skip_code(record):
    """The refusal a failed record stands for: `story_claim_failed`."""
    return SKIP_PEOPLE


def codes(record):
    """The violation codes of a check record, in order, once each."""
    out = []
    for v in (record or {}).get("violations") or []:
        if v["code"] not in out:
            out.append(v["code"])
    return out
