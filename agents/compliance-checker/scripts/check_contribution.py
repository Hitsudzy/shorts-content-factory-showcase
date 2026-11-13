#!/usr/bin/env python3
"""CF-0187: judge the *substance* of a script's added fact (any kind, CF-0439).

Takes over from CF-0066, which judged a different contribution. CF-0181
cancelled the position that one rested on (an announcement held up against a
frame we watched ourselves) and put another in its place: the script retells
the story and owes it **one concrete fact the story does not carry, taken
from a source of its own and shown with it**. CF-0439 widened that fact from
"how the thing was made" to **a fact of any kind** - production, box office,
release, casting, reception, scandal, people news, an unscripted moment, or
`other` (the kinds of `shared/factrule/fact_rule.py`; a kind names the fact
for the record and is never a reason to block). The field judged here is
still `production_fact` - its name is a contract kept for compatibility, not
a restriction to the set. So the question
this module asks changed with it, and the `comparison` block CF-0066 read is
not judged here any more - `agents/content-researcher/scripts/
check_production_fact.py` is the one that answers a script still carrying it.

The definition is not hardcoded here. It is read from
`channels/<channel>/stance.json` (written by CF-0181), whose `verification.
compliance_checker` names this module's whole job in one sentence: "whether
the fact is a real one or filler - concrete, not lifted out of the story it
is added to, and backed by a link (CF-0187) ... It does not judge whether the
fact is true of the world; that rests on the source it is taken from."

**The split with the validator, which this module must not cross.** Shape is
`check_production_fact.py`'s (CF-0183, content-researcher's repo): the field
is there, its four keys are there, `beat_text` is a verbatim substring of
`commentary`, `source_url` is http(s), `on_screen` fits the screen. None of
that is re-checked here. This module reads what the fact *says* - the
`text`, which CF-0183's own docstring hands to CF-0187 by name - and answers
three questions, in this order:

  1. Is it concrete?          `fact_is_filler`, `fact_not_concrete`
  2. Is it absent from the    `fact_in_the_story`
     story being retold?
  3. Is it backed by a link   `fact_unsourced`, `source_is_the_story`
     to a source of its own?

**What question 3 can and cannot be.** Nothing here is fetched. The judge
does not open the URL, does not ask a model whether the page says the fact,
and does not know one domain from another - hardcoding an expected host (the
Wikipedia of CF-0184, say) would make the judge wrong the moment the source
changes, and CF-0184 is at this writing an open decision. What is checkable
without leaving the batch directory is the *relation*: a link is there, and
it is not one of the story's own links. The stance is explicit that the two
must differ - "The fact comes from a source of its own, never from the lead
it is added to" - so a fact footnoted to the Variety piece the script is
retelling is self-sourcing, and that is a block. Whether the page actually
confirms the fact rests on the source (CF-0184), not on this module and not
on the model reading after it.

**What question 2 compares against, and the limit that follows.** The judge
never sees the article bodies - CF-0045 refused to collect them and CF-0181
did not reverse that. What exists at this stage is:

  * `01-trend-hunter.json`, sibling of the file being judged: per topic, the
    `scenes[].description` digest and the `evidence.sources[].title`
    headlines. Note what is *not* there - `fetch_rss_news.py` collects a
    summary of up to 500 characters per entry, but the stage file does not
    carry it. The lead as this judge sees it is thinner than the lead the
    Content Researcher saw.
  * the script itself: `proofs[].verbatim_text` and `proofs[].source.title`,
    which are quoted lead text carried inside the script, and the retelling
    the script wrote from the lead - the `commentary`, with the fact's own
    beat removed (removable exactly because CF-0183 makes `beat_text` a
    verbatim substring of it). The `hook` and the `payoff` are not the
    retelling and are not read here: they are the frame every pattern builds
    on the fact, so the fact is in them by contract (CF-0273 -
    `retelling_segments` has the case that cost a video).

So "absent from the news" is decided against a digest of the news plus the
retelling written from it, not against the articles. A fact lifted out of a
paragraph no file here contains will pass this check. That is a real hole and
it is named in the result (`compared_against`) rather than hidden: every
verdict says what it was measured against, so a reader can see how thin the
comparison was. Widening it means collecting article bodies, which is a
decision CF-0045 and CF-0181 both took the other way.

The verdict is `pass` or `block`, nothing softer, and it is separate from the
rights/risk verdict (`clear|caution|review`) this agent also writes: CF-0043
rejected flagging a weak contribution for a human to look at, and the stance
still refuses it ("A vague fact is no fact, and the topic is dropped").
A `block` means the script does not proceed to Video Editor.

**What is not here.** The refusal rule - no fact found, so the topic is
dropped - is CF-0185's, behind a switch, off by default. A script with no
`production_fact` at all is therefore not judged and not blocked here: its
result carries `judged: false` and says so. Absence is the validator's to
catch and the refusal rule's to act on; this module judges a fact that was
written.

This is a heuristic net, not a full reading: it catches the blatant cases by
deterministic string work so a model does not have to look at everything.
SKILL.md tells the agent to run it first and read the rest with its own
judgment - the stance calls this check "qualitative, needs a model", and this
module is the cheap half of that, not a replacement for it.

Run directly against a batch's Content Researcher output (the trend-hunter
file beside it is picked up automatically when it is there):

    python3 agents/compliance-checker/scripts/check_contribution.py \\
        pipeline/legacy-film/2026-09-09T2031Z/03-content-researcher.json
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
from _cli import screen  # noqa: E402


def _find_repo_root(start):
    """Walk upward from `start` looking for the shorts-content-factory root
    (identified by having both `channels/` and `patterns/` as children).

    Not a fixed `.parent` count: this file's own location differs between a
    normal checkout (`agents/compliance-checker/scripts/...`) and a task
    worktree (`agents/compliance-checker/.claude/worktrees/agent-*/scripts/
    ...`, two extra directory levels deep). A marker search works from
    either without needing to know which one it's running from."""
    for p in [start, *start.parents]:
        if (p / "channels").is_dir() and (p / "patterns").is_dir():
            return p
    raise RuntimeError(
        f"could not locate the shorts-content-factory root above {start} "
        f"(looked for an ancestor with both channels/ and patterns/)")


REPO = _find_repo_root(Path(__file__).resolve())

FIELD = "production_fact"
TREND_HUNTER_FILE = "01-trend-hunter.json"

# How much of the fact's own vocabulary may already be in the story before
# the fact reads as a restatement of it. Containment, not Jaccard: the fact
# is one or two sentences and the story surface is a digest plus a dozen
# headlines, so a symmetric measure is small even for a straight copy - what
# matters is how much of the *fact* the story already had.
#
# Calibrated on the real 2026-09-09T2031Z lead (topic ...-001, the Venice
# ovation: 2 scene descriptions + 9 source titles). A fact written out of
# that lead measures 0.88; the same fact reworded around its own synonyms
# 0.50; production facts that merely share the film and the cast with it
# 0.17-0.35. 0.65 sits above the reworded case on purpose - a paraphrase
# thorough enough to drop half its vocabulary is not separable from a real
# fact by counting words, and pretending otherwise would block honest
# material. That case is the model's to catch on the read after this one.
CONTAINMENT_THRESHOLD = 0.65

# A lifted phrase is evidence a ratio can miss: a long fact that quotes one
# clause out of the lead and surrounds it with new words scores low on
# containment and is still a copy. Six content words in the same order is
# past coincidence for texts this short.
SHINGLE_N = 6

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "in", "on",
    "and", "or", "but", "that", "this", "it", "its", "as", "at", "for",
    "with", "from", "by", "be", "been", "has", "have", "had", "not", "no",
    "one", "two", "three", "her", "his", "their", "she", "he", "they",
    "there", "here", "than", "then", "so", "if", "we", "our", "into",
    "over", "after", "before", "while", "what", "which", "who", "says",
    "say", "said",
}
_WORD_RE = re.compile(r"[a-z0-9']+")


def _word_list(text):
    """Content words in order: lowercased, stopwords and words <= 2 chars
    dropped, so overlap reflects shared subject matter, not shared grammar.
    Order is kept because `shared_phrase` needs a sequence."""
    return [w for w in _WORD_RE.findall((text or "").lower())
            if w not in _STOPWORDS and len(w) > 2]


def _words(text):
    """`_word_list` as a set - the shape both overlap measures want."""
    return set(_word_list(text))


def jaccard(a, b):
    """Vocabulary overlap between two texts, 0.0 (nothing shared) to 1.0
    (same content words). Symmetric; kept because it is the right measure
    when the two texts are of comparable length."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def containment(fact_text, story_text):
    """How much of `fact_text`'s vocabulary the story already had, 0.0 to
    1.0. Asymmetric on purpose - see CONTAINMENT_THRESHOLD."""
    wa, wb = _words(fact_text), _words(story_text)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa)


def shared_phrase(fact_text, story_text, n=SHINGLE_N):
    """The first run of `n` content words appearing, in order, in both texts
    - or None. Returned as a string so the failure can quote it."""
    a, b = _word_list(fact_text), _word_list(story_text)
    if len(a) < n or len(b) < n:
        return None
    theirs = {tuple(b[i:i + n]) for i in range(len(b) - n + 1)}
    for i in range(len(a) - n + 1):
        window = tuple(a[i:i + n])
        if window in theirs:
            return " ".join(window)
    return None


def shared_phrase_in_any(fact_text, story_segments, n=SHINGLE_N):
    """`shared_phrase` against each of the story's fragments separately,
    never against their concatenation (CF-0242).

    A surface is not one text. The lead is a title, then a scene digest, then
    a dozen headlines, then the script's quoted proof and the proof's title -
    fragments that were written apart and are only ever joined here, to be
    counted as a bag of words. Run a sliding window over the joined string
    and it also reports windows that *straddle a join*: a run of words that
    appears in no headline, no digest and no article, only in the seam this
    module made. Those are not lifted phrases, and a lifted phrase is exactly
    what the shingle rule claims to be evidence of.

    Real case, `example-film/2026-09-15T1034Z` script 001: the topic is called
    'Spire-Runner: Fresh Dawn' and the scene digest opens with the same
    title, so joining them makes 'spire runner fresh dawn spider' - six
    content words, over SHINGLE_N, present in neither fragment. The fact,
    which names the film and then names Spire-Runner again, matches it. Same
    seam again between the proof's `verbatim_text` and the proof's `title`,
    which under CF-0223/CF-0241 are the same string twice over. Containment
    on that pair is 19% - inside the 0.17-0.35 band CONTAINMENT_THRESHOLD is
    calibrated to call honest, a third of the way to the 0.65 that would call
    it a retelling - so the two measures said opposite things and the
    manufactured one won.

    Checking per fragment does not weaken the rule: a phrase really lifted
    out of the lead sits inside one headline or one digest, and is still
    found. It only stops the module from quoting itself back."""
    for segment in story_segments or []:
        phrase = shared_phrase(fact_text, segment, n)
        if phrase:
            return phrase
    return None


# --- concreteness -----------------------------------------------------
#
# The stance names what a concrete fact carries: "a number, a name, a date,
# an event - not an opinion" (CF-0438/CF-0439; the kind of fact does not
# matter - a box-office figure, a casting name and a release date are as
# concrete as a take count on the set). A number, a date and a name are
# findable in a string; "an event" is not,
# so the net is built from the two that are, and the residual is stated
# rather than faked: a concrete event carrying neither a number nor a name
# ("the set flooded and was rebuilt") reads as vague to this module and is
# the model's to pass on the read after it.

_NUMBER_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "hundreds", "thousand", "thousands", "dozen", "dozens", "half", "twice",
    "first", "second", "third", "fourth", "fifth", "last",
}
_MONTHS = {
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
}
_DIGIT_RE = re.compile(r"\d")
# Double quotes only: an apostrophe is not a quotation mark, and treating it
# as one turns "the crew's rig" into a quoted phrase.
_QUOTE_RE = re.compile(r"[\"“]([^\"“”]{3,})[\"”]")
# A capitalized word that is not the first word of its sentence: the cheap
# proxy for a proper name that does not need a dictionary of them.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_CAPITALIZED_RE = re.compile(r"\b([A-Z][\w'’-]{2,})")

# Placeholders: the fact was never written. The validator catches the field
# being absent; this catches it being present and empty of content, which is
# the "filler" half the task brief splits off from absence.
_FILLER_RE = re.compile(
    r"\b(tbd|todo|to be (determined|added|written|filled)|placeholder|n/?a|"
    r"lorem ipsum|fact goes here|coming soon|fill in|insert fact|"
    r"see source|source needed|citation needed)\b", re.I)

# Hedges. Not a block on their own - a real fact may be hedged - but they
# are what a general phrase is made of, so they decide the case where the
# only concrete thing in the fact is a name the story already carried.
_VAGUE_RE = re.compile(
    r"\b(difficult|challenging|a challenge|challenges|complicated|tough|"
    r"hard work|not easy|demanding|intense|gruelling|grueling|emotional|"
    r"interesting|impressive|memorable|behind the scenes|reportedly|"
    r"apparently|allegedly|said to be|it is said|famously|notoriously|"
    r"many|much|several|some|various|numerous|a number of|a lot of|"
    r"a great deal)\b", re.I)

# CF-0439: a fact about a real person is *required* to be put as someone's
# statement ("Variety reported that...", "X said that...", CF-0438), so the
# hedge that marks a report must not read as vagueness once the report names
# who made it. Only these hedges are forgiven, and only for an attributed
# fact: an unattributed "reportedly" - no one named, no `fact.attribution` -
# is still a hedge, and "allegedly"/"said to be" stay hedges either way
# (a rumour is not made concrete by naming who repeats it).
_ATTRIBUTION_HEDGES = {"reportedly"}
# Someone named, then a reporting verb: "Variety reported", "Deadline
# confirmed", "Nolan told Empire", "according to The Hollywood Reporter",
# and the Russian forms the stance itself writes the rule in. A bare verb
# with no name right before it ("Cruz reportedly said") is not an
# attribution.
_ATTRIBUTED_RE = re.compile(
    r"(\b[A-Z][\w'’&.-]*(?:\s+[A-Z][\w'’&.-]*)*\s+"
    r"(?:told|said|says|reported|reports|confirmed|confirms|announced|"
    r"revealed|wrote|writes|stated|recalled|admitted|disclosed|noted)\b"
    r"|\b[Aa]ccording to\s+[A-Z]"
    r"|(?:сообщил[аио]?|заявил[аио]?|рассказал[аио]?|написал[аио]?|"
    r"подтвердил[аио]?)(?![а-я])|по словам|по данным)")


def is_attributed(text, fact_meta=None):
    """Whether the fact is put as a named source's statement (CF-0438):
    either the script's `fact.attribution` says who (CF-0439's `03
    scripts[].fact`), or the text itself names someone and a reporting verb.
    """
    if isinstance(fact_meta, dict):
        attribution = fact_meta.get("attribution")
        if isinstance(attribution, str) and attribution.strip():
            return True
    return bool(_ATTRIBUTED_RE.search(text or ""))


def vague_hedge(text, attributed=False):
    """The first hedge in the fact that counts as vagueness, or None. An
    attributed fact's reporting hedge ("reportedly") does not count."""
    for match in _VAGUE_RE.finditer(text or ""):
        if attributed and match.group(0).lower() in _ATTRIBUTION_HEDGES:
            continue
        return match
    return None


def anchors(text):
    """The concrete things the fact names: numbers, proper names, quoted
    phrases. Lowercased tokens, so they can be compared against the story's
    vocabulary the same way everything else here is."""
    text = text or ""
    found = set()
    for word in _WORD_RE.findall(text.lower()):
        if _DIGIT_RE.search(word) or word in _NUMBER_WORDS or word in _MONTHS:
            found.add(word)
    for sentence in _SENTENCE_SPLIT_RE.split(text.strip()):
        sentence = sentence.strip()
        capitalized = _CAPITALIZED_RE.findall(sentence)
        # A word capitalized because its sentence starts there is no
        # evidence of a name; one capitalized mid-sentence is.
        if capitalized and sentence.startswith(capitalized[0]):
            capitalized = capitalized[1:]
        found.update(w.lower() for w in capitalized)
    for quoted in _QUOTE_RE.findall(text):
        found.update(_words(quoted))
    return found


# --- the story the fact is added to -----------------------------------


def retelling_segments(script):
    """The story as the script itself tells it: the `commentary`, as the
    separately written pieces the fact's own beat leaves behind it.

    Two things are left out of it, for one reason: a surface the fact is
    measured against may not be a place the channel's own contract puts the
    fact in. Measuring the fact there asks the script to be blocked for
    obeying the rule it was written under, and what comes back is not a
    finding about the fact but a restatement of the contract.

    **The fact's beat.** The stance requires the fact to be *spoken* - "A
    block in every script where the fact is spoken" (CF-0183) - and CF-0183
    makes `beat_text` a verbatim contiguous substring of `commentary`, which
    is what makes the cut exact. Without it the fact would be found in the
    retelling every time, since the retelling is where the fact is said. On
    `list` and `moment-breakdown` that beat is the whole of the pattern's
    fact-carrying block - the last item of the list, the last pass over the
    moment, whose sentences go verbatim into `beat_text` (CF-0216) - so the
    same one cut takes those out too and no pattern needs a rule of its own
    here.

    Cut out rather than blanked over (CF-0242): replacing the beat with a
    space would leave the words before and after it adjacent, and a phrase
    that only exists because a sentence was removed from between its halves
    is not a phrase the script wrote. Same reason the pieces are kept apart
    - see `shared_phrase_in_any`.

    **The hook and the payoff (CF-0273).** They are the frame, not the news,
    and every pattern in `patterns/` builds that frame on the fact.
    `explainer`: "The hook names the specific fact, not the topic", and "The
    payoff closes the loop on the hook's actual wording so a replay from the
    top reads as a continuation". `contrast`: the axis is named in the hook
    and "is whatever the production fact is measured on", and the payoff
    "resolves the contrast ... and closes on the hook's wording".
    `moment-breakdown`: the hook promises the thing the viewer missed, which
    the fact's own last pass is what reveals, and the payoff "resolves the
    promise made in the hook ... and closes on the hook's wording". Even
    `list`, the one pattern that keeps the fact out of both ("The fact is an
    item and not a coda. It does not go in the payoff ... and it does not go
    in the hook"), still writes the payoff back onto the hook's count. So the
    fact's numbers and names are in the frame by contract, and on three of
    the four patterns they are there because the pattern said to put them
    there.

    Real case, `example-film/2026-09-17T1901Z` script 001 of the Wren Hollow
    topic (`lf-2026-09-17-006-script1`, explainer): ten animatronic owls at
    thirty-six thousand feathers each, sourced to the Wikipedia Design
    section, spoken in its beat, named in the hook as the pattern demands,
    and the payoff closing on the hook's wording - "Thirty-six thousand
    feathers a bird". Against the whole script the fact shared 47 % of its
    content words and the shingle rule found 'owls thirty six thousand
    feathers each' - in the hook, where the pattern had told the writer to
    put it. Against the lead the same fact measures 5 %, and against the
    commentary that remains here, 21 %. It was blocked as `fact_in_the_story`
    and the video was lost (that batch's funnel: `contribution_blocked` 1).

    What is left is the retelling proper, and the question keeps its teeth: a
    fact really lifted out of the news is in the news the script retells,
    which is the commentary, and it is still found there."""
    fact = script.get(FIELD)
    commentary = script.get("commentary") or ""
    beat = (fact or {}).get("beat_text") if isinstance(fact, dict) else None
    if isinstance(beat, str) and beat and beat in commentary:
        parts = commentary.split(beat)
    else:
        parts = [commentary]
    return [p for p in parts if p and p.strip()]


def retelling(script):
    """`retelling_segments` as one text - what the bag-of-words measures
    want, and what `compared_against` is described from."""
    return " ".join(retelling_segments(script))


def lead_segments(script, topic=None):
    """The news as this stage has it: the trend-hunter digest for the topic
    when that file is at hand, plus any lead text the script carries itself
    (`proofs[].verbatim_text` and the titles behind them). Never an article
    body - nothing in this pipeline fetches one.

    A list, one entry per separately written fragment, because that is what
    the phrase check has to run against (CF-0242, `shared_phrase_in_any`):
    the title, each scene digest and each headline were written apart, and a
    run of words spanning two of them exists only in this function's join."""
    parts = []
    if topic:
        name = (topic.get("title_ref") or {}).get("name")
        if name:
            parts.append(name)
        for scene in topic.get("scenes") or []:
            if scene.get("description"):
                parts.append(scene["description"])
        for source in (topic.get("evidence") or {}).get("sources") or []:
            if source.get("title"):
                parts.append(source["title"])
    for proof in script.get("proofs") or []:
        if not isinstance(proof, dict):
            continue
        if proof.get("verbatim_text"):
            parts.append(proof["verbatim_text"])
        title = (proof.get("source") or {}).get("title")
        if title:
            parts.append(title)
    return [p for p in parts if p and p.strip()]


def lead_text(script, topic=None):
    """`lead_segments` as one text - the bag of words the containment ratio
    is taken over, where the joins do no harm."""
    return " ".join(lead_segments(script, topic))


def story_surfaces(script, topic=None):
    """Everything the fact is checked for absence against, each labelled so
    the verdict can say what it was measured against. Order is deliberate:
    the lead first, since that is the story; the script's retelling of it
    second, since news the script itself already told is news, and a fact
    that repeats it is no addition either.

    Both surfaces are the story, and nothing else is (CF-0273): the beats
    written to carry the fact are not a surface, however much of the fact
    they contain - see `retelling_segments`."""
    surfaces = []
    lead = lead_segments(script, topic)
    if lead:
        where = []
        if topic:
            where.append(f"{TREND_HUNTER_FILE} topic {topic.get('topic_id')} "
                         f"(scene descriptions + source titles)")
        if script.get("proofs"):
            where.append("the script's own proofs[] (verbatim lead text + titles)")
        surfaces.append({
            "surface": "lead",
            "label": " + ".join(where) or "the lead as carried in the script",
            "text": " ".join(lead),
            "segments": lead,
        })
    told = retelling_segments(script)
    if told:
        surfaces.append({
            "surface": "retelling",
            "label": "the script's own retelling of the news (the commentary "
                     "with the fact's beat removed; the hook and the payoff "
                     "are the frame the pattern builds on the fact, not the "
                     "story - CF-0273)",
            "text": " ".join(told),
            "segments": told,
        })
    return surfaces


def _normalize_url(url):
    """Enough normalization to tell 'the same link' from 'a different one':
    case, scheme, a leading www. and a trailing slash. Not a canonicalizer -
    query strings and fragments are left alone, because two URLs that differ
    there are two URLs."""
    u = (url or "").strip().lower()
    for scheme in ("https://", "http://"):
        if u.startswith(scheme):
            u = u[len(scheme):]
            break
    if u.startswith("www."):
        u = u[4:]
    return u.rstrip("/")


def story_links(script, topic=None):
    """The links the story itself is retold from - the ones the fact's own
    source must not be. Normalized.

    **The proof link that is the fact's own source is not one of them
    (CF-0242).** A proof link used to be counted here without exception, and
    that was right while a proof was only ever quoted lead material. Since
    CF-0223 and CF-0241 it is not: the contract now *requires*
    `proofs[].source.url` to be the fact's `source_url`, so counting it would
    put the fact's own source into the set the fact's source must stay out
    of, and `source_is_the_story` would fire on every correctly written
    script. That is a tautology, not a check - it blocked 4 of 4 on
    `example-film/2026-09-15T1034Z`, where no fact's source appears among its
    topic's links at all.

    Only that one link is spared, and only because the contract forces it to
    be there. Any other proof link is still the story: a proof is quoted lead
    material, and a fact footnoted to it is footnoted to the lead. And the
    topic's own links are never spared - if the fact's source is one of
    *those*, it is the story whatever the proofs say, which is the case the
    check exists for.

    **Per article, not per outlet (CF-0439).** A fact of any kind is very
    often a trade fact - box office, casting, a release date - from Variety,
    Deadline or THR, the very outlets the feed's links point at. A different
    article of the same outlet is a source of the fact's own; only the
    story's own link (after `_normalize_url`) is the story. Hosts are never
    compared here, which is also why `test_no_host_is_privileged` holds."""
    urls = set()
    if topic:
        evidence = topic.get("evidence") or {}
        for link in evidence.get("rss_links") or []:
            urls.add(_normalize_url(link))
        for source in evidence.get("sources") or []:
            if source.get("url"):
                urls.add(_normalize_url(source["url"]))
    fact = script.get(FIELD)
    fact_url = fact.get("source_url") if isinstance(fact, dict) else None
    fact_url = _normalize_url(fact_url) if isinstance(fact_url, str) else ""
    proof_urls = set()
    for proof in script.get("proofs") or []:
        if isinstance(proof, dict):
            url = (proof.get("source") or {}).get("url")
            if url:
                proof_urls.add(_normalize_url(url))
    if fact_url:
        proof_urls.discard(fact_url)
    urls |= proof_urls
    urls.discard("")
    return urls


# --- the judgment -----------------------------------------------------


def judge_fact(fact, script, topic=None, *,
               containment_threshold=CONTAINMENT_THRESHOLD,
               shingle_n=SHINGLE_N):
    """The three questions, asked of one script's added fact (the
    `production_fact` contract field; since CF-0439 a fact of any kind, never
    judged on its kind). Returns
    a list of failure dicts (empty when the fact holds up). Shape is never
    re-checked here - that is CF-0183's validator, in the Content
    Researcher's repo - so a missing or non-string `text` is read as "no
    fact to judge" and answered by the concreteness question rather than by
    a second copy of the validator's message."""
    text = fact.get("text") if isinstance(fact, dict) else None
    text = text if isinstance(text, str) else ""
    failures = []

    # (1) concrete - a number, a name, something quoted; not a general
    # phrase, and not a placeholder standing in for a fact nobody wrote.
    filler = _FILLER_RE.search(text)
    if filler:
        failures.append({
            "reason_code": "fact_is_filler",
            "detail": (
                f"{FIELD}.text carries the placeholder {filler.group(0)!r} - "
                f"the field was filled in, not written; a stub is not a fact "
                f"(the validator catches the field being absent, this catches "
                f"it being empty of content)"),
        })
    found = anchors(text)
    story_words = set()
    for surface in story_surfaces(script, topic):
        story_words |= _words(surface["text"])
    new_anchors = {a for a in found if a not in story_words}
    fact_meta = script.get("fact") if isinstance(script, dict) else None
    vague = vague_hedge(text, attributed=is_attributed(text, fact_meta))
    if not found:
        failures.append({
            "reason_code": "fact_not_concrete",
            "detail": (
                f"{FIELD}.text names nothing specific - no number, no proper "
                f"name, nothing quoted"
                + (f" (and hedges: {vague.group(0)!r})" if vague else "")
                + f". The stance asks for a number, a name, a date or an "
                  f"event - of any kind: set, box office, release, casting, "
                  f"reception, people - not a general phrase or an opinion"),
        })
    elif not new_anchors and vague:
        failures.append({
            "reason_code": "fact_not_concrete",
            "detail": (
                f"{FIELD}.text hedges ({vague.group(0)!r}) and the only "
                f"specific things in it ({', '.join(sorted(found))}) are "
                f"already in the story - a general phrase wrapped around the "
                f"names the story already carried adds nothing"),
        })

    # (2) absent from the story being retold.
    if text:
        for surface in story_surfaces(script, topic):
            ratio = containment(text, surface["text"])
            phrase = shared_phrase_in_any(text, surface["segments"], shingle_n)
            if ratio >= containment_threshold or phrase:
                detail = (
                    f"{FIELD}.text shares {ratio:.0%} of its content words "
                    f"with {surface['label']}")
                if phrase:
                    detail += f", including the phrase {phrase!r}"
                detail += (" - this is the story retold, not a fact added to "
                           "it")
                failures.append({
                    "reason_code": "fact_in_the_story",
                    "surface": surface["surface"],
                    "overlap": round(ratio, 2),
                    "shared_phrase": phrase,
                    "detail": detail,
                })

    # (3) backed by a link to a source of the fact's own.
    url = fact.get("source_url") if isinstance(fact, dict) else None
    url = url.strip() if isinstance(url, str) else ""
    if not url or not url.lower().startswith(("http://", "https://")):
        failures.append({
            "reason_code": "fact_unsourced",
            "detail": (
                f"{FIELD}.source_url is {url or 'absent'!r} - with no link "
                f"there is nothing holding the fact up but our word, which is "
                f"what the stance refuses; the fact cannot be judged backed"),
        })
    elif _normalize_url(url) in story_links(script, topic):
        failures.append({
            "reason_code": "source_is_the_story",
            "detail": (
                f"{FIELD}.source_url is one of the story's own links ({url}) - "
                f"the fact is supposed to come from a source of its own, never "
                f"from the lead it is added to, so a fact footnoted to the "
                f"lead is the lead"),
        })

    return failures


def evaluate_script(script, topic=None, **thresholds):
    """Judge one script's added fact (any kind, CF-0439). Returns
    {"verdict": "pass"|"block", "failures": [...], "reason": str|None,
     "judged": bool, "compared_against": [...], "note": str|None}.

    `judged: false` with a `pass` is not a loophole: a script with no fact at
    all is the validator's to fail (CF-0183) and the refusal rule's to drop
    (CF-0185, behind a switch). This module does not get to invent either."""
    fact = script.get(FIELD)
    compared = [s["label"] for s in story_surfaces(script, topic)]
    if not isinstance(fact, dict) or not fact:
        return {
            "verdict": "pass",
            "failures": [],
            "reason": None,
            "judged": False,
            "compared_against": compared,
            "note": (
                f"no `{FIELD}` to judge - absence is the validator's "
                f"(check_production_fact.py, CF-0183) and the refusal rule's "
                f"(CF-0185, behind a switch); this check judges a fact that "
                f"was written"),
        }
    failures = judge_fact(fact, script, topic, **thresholds)
    reason = "; ".join(f["reason_code"] for f in failures) or None
    note = None
    if not compared:
        note = ("nothing to compare the fact against - neither "
                f"{TREND_HUNTER_FILE} nor any lead text or retelling in the "
                f"script; the 'absent from the story' question went unasked")
    return {
        "verdict": "block" if failures else "pass",
        "failures": failures,
        "reason": reason,
        "judged": True,
        "compared_against": compared,
        "note": note,
    }


def load_stance(channel, repo=REPO):
    """The channel's stance file - the single source of truth for what counts
    as a contribution here (CF-0181 wrote the one in force). Referenced, not
    hardcoded: this function's only job is to find and load it; the
    definitions it points at (`position`, `verification.compliance_checker`)
    live only in that file."""
    cfg_path = repo / "channels" / f"{channel}.json"
    cfg = json.loads(cfg_path.read_text())
    stance_rel = cfg.get("stance")
    if not stance_rel:
        raise ValueError(f"{cfg_path} has no `stance` field to point at a stance file")
    stance_path = repo / "channels" / stance_rel
    return json.loads(stance_path.read_text())


def load_topics(trend_hunter_json):
    """`01-trend-hunter.json`'s topics, keyed by topic_id. A dict, not a
    file path, so callers can hand in a batch of their own."""
    if not trend_hunter_json:
        return {}
    return {t["topic_id"]: t for t in trend_hunter_json.get("topics", [])
            if t.get("topic_id")}


def evaluate_batch(content_researcher_json, channel, *, repo=REPO,
                   trend_hunter_json=None, **thresholds):
    """Evaluate every script in a `03-content-researcher.json`-shaped dict.
    Returns a dict keyed by script_id, each value the `evaluate_script`
    result plus `checked_against` naming the stance file used, so the output
    stays traceable back to the document that defines the contribution rather
    than to a rule hidden in this agent.

    `trend_hunter_json` is the stage-01 file of the same batch, optional: it
    is where the news the fact must not repeat comes from. Without it the
    judge falls back to what the script carries itself, which is thinner -
    and says so in every result's `compared_against`."""
    stance = load_stance(channel, repo=repo)
    task = stance.get("decided_by", {}).get("task")
    checked_against = f"channels/{channel}/stance.json ({task})" if task \
        else f"channels/{channel}/stance.json"
    topics = load_topics(trend_hunter_json)
    results = {}
    for script in content_researcher_json.get("scripts", []):
        result = evaluate_script(script, topics.get(script.get("topic_id")),
                                 **thresholds)
        result["checked_against"] = checked_against
        results[script["script_id"]] = result
    return results


def read_trend_hunter(cr_path):
    """The stage-01 file beside the file being judged, or None. Optional by
    design - the judge runs without it, on less."""
    path = Path(cr_path).resolve().parent / TREND_HUNTER_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


USAGE = "usage: check_contribution.py <path-to-03-content-researcher.json> [channel]"


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # CF-0777: `--help` is a question, not a file to judge - it answers with
    # the usage and exit 0; any other option is a usage error (exit 2).
    rc = screen(argv, USAGE)
    if rc is not None:
        return rc
    if not argv:
        print(USAGE)
        return 2
    path = Path(argv[0])
    try:
        d = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        print(f"cannot read the batch: {exc}")
        return 2
    # CF-0197: a batch written before the channel was renamed carries the
    # old id frozen in its `channel` field - the file is a dated record and
    # is not rewritten - so resolve it before the config is looked up.
    channel = resolve_channel(
        argv[1] if len(argv) > 1 else d.get("channel", "example-film"))
    th = read_trend_hunter(path)
    if th is None:
        # Deliberately without the path: this line is part of the output two
        # runs of the same batch are compared on, and an absolute path makes
        # the same run read differently depending on where it ran from.
        print(f"note: no {TREND_HUNTER_FILE} beside the file being judged - "
              f"the fact is compared only against what each script carries "
              f"itself")
    results = evaluate_batch(d, channel, trend_hunter_json=th)
    blocked = 0
    unjudged = 0
    for script_id, r in results.items():
        line = f"{script_id}: {r['verdict']}"
        if r["reason"]:
            line += f" - {r['reason']}"
        if not r["judged"]:
            line += f" - not judged ({r['note']})"
            unjudged += 1
        print(line)
        for f in r["failures"]:
            print(f"    {f['reason_code']}: {f['detail']}")
        if r["verdict"] == "block":
            blocked += 1
    tail = f"\n{len(results)} script(s), {blocked} blocked"
    if unjudged:
        tail += f", {unjudged} with no {FIELD} to judge"
    print(tail)
    return 1 if blocked else 0


@runlog.script("compliance-checker", "check-contribution", name="check_contribution.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event, so a non-zero result (1 = something blocked,
    2 = usage) is recorded as `failed` (CF-0107). The check itself is pure
    Python over the batch files and stance.json - no external binary, no model
    call, nothing fetched - so there is no `child` event to write; the script
    event is the whole record."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
