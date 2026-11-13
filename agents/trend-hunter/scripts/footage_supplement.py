#!/usr/bin/env python3
"""CF-0343: a thin pool's supplement request gets its candidates - footage of
the *entity* an uncovered anchor is about, not of the topic's work.

The user's ruling of 2026-09-23 on `widows-bay` / `everyday-sorcery-2`
(CF-0338): "if they talk about the actor's Emmy and there is no frame of the
actor in the sources - google the actor's highlights, find their work, put it
in to fill the gap". Narrowed on 2026-09-28 (CF-0426, grill "добор по актёру
и его другим работам"): four runs, about 1 h 48 m, five downloads; the sieve
refused three other films (Ad Astra, Civil War, Ebenezer), and the four shots
that reached the videos were all interviews - the person as themselves. The
user refused kaijura as "from the picture you cannot tell what the video is
about". So the order is now: **the topic's own footage -> its people as
themselves (interview, press tour / conference, red carpet, award) -> reels
of the same kind**, and **another work is never looked for** - not by search,
not as "<person> <work>", not off the official channels' feeds. Three stages
share the step (one repository each):

  * the writer's pool gates name the uncovered anchors and their entities and
    write a request skeleton `<batch>/work/supplement-requests/<topic>.json`
    (`agents/content-researcher/scripts/_supplement_request.py`, CF-0342);
  * **this module** searches for those entities with this stage's own search
    (`fetch_youtube_signal.py --facets`), its own four sieves and its own
    quota ledger, and fills `candidates[]` of the request;
  * the indexer fetches them (`ingest_batch.py --supplement`, CF-0338a),
    reading them with `read_supplement()` / `supplement_candidates()`.

Entry: `footage_candidates.py --supplement <request.json|dir> ...` (the
footage stage's CLI; this module is its supplement half).

**The queries.** One `fetch_youtube_signal.py` run per entity with the
facets of its kind (`FACETS_BY_KIND`): the topic's own work - its bare name
plus trailer, clip, interview; a person - **only** interview, press
conference, red carpet, award, and no bare-name query (`--no-bare`, CF-0426:
in 0929Z the bare name answered with other films' trailers). A place is
ambiguous on its own (the live run of 2026-09-23 answered "Worcester Park"
with a cricket club's matches), so it is searched only as "<place> <topic's
work>" for filming, and its candidates must name both. The window is
`SUPPLEMENT_DAYS`, not the scoring pass's week: a person's interviews are
years old.

**Whose entity it is - the foreign-work rule** (driver 2026-09-23, the user
2026-09-28). The entities are read out of anchor text deterministically, and
the rule errs: `everyday-sorcery-2`'s box-office anchor gave `Spire-Runner: Brand
New Day`, the film it knocked off the top, which is no part of the topic. So a
`show` / `work` entity:

  1. that *is* the topic's work (a form of its name that names **this** work
     is a form of `title_ref`'s - `distinct_forms` / `own_forms`, not the
     franchise's short form: "Vanguards: Infinity War" is not "Vanguards:
     Endgame Encore", CF-0426) is searched as the topic's work;
  2. that is another work **of the topic's franchise** (a shared colon stem,
     the name without its sequel number, a film's `parent_work`) is the
     topic's frame **only when the narrator names it** - in the script's hook
     / commentary / payoff (`03-content-researcher.json`, `narration_of`) or
     in the request's own anchors' `beat_text` (`topic_scope`, the user's
     rule 4 of 2026-09-28). Then it is searched as a work (`franchise: true`)
     and its name counts as the topic's; otherwise it is rule 3;
  3. anything else is **not searched at all** - not alone, and not as
     "<person> <work>" (CF-0343's rule 2, removed by CF-0426): it is listed
     in `search.entities_skipped[]` with `foreign_work`, and no search call
     is spent on it.

**Who is not on screen** (CF-0373). The researcher marks every person
`role: crew | on_screen` and leaves crew and `kind: event` out of the request's
`entities` (CF-0372); as a safety net, an entity that still carries
`role: crew` (a director, a cinematographer - "their highlights" are other
people's frames) or `kind: event` (a festival, an awards night) is not
searched: it goes to `search.entities_skipped[]` with `off_screen_person` /
`event`. An entity with no `role` (a request written before CF-0372) is read
as before.

**The event's own footage** (CF-0582, the hunter's half of CF-0575). An
`event_footage_short` request names the work and the event - `kind: scene`,
"<person> <moment>" ("Dana Reyes monologue"), the moment on its
`event{}` - and the natures that answer it (`natures_wanted: [episode,
trailer]`, `natures_refused: [interview]`). The scene is searched first, as
"<work> <person> <moment>" and the same under the names the work's uploads go
by - the channel of the topic's own footage that names the work, its
initials, its network (`scene_queries`, at most `SCENE_VARIANTS_MAX` bare
calls, no facet). Its upload must name the person, the moment **in the
title** and the work by a form of its own (`scene_miss`); it is the work's
own cut, so the person-as-themselves verdict does not apply. The request's
natures then hold for the scene's and the work's uploads, searched or off
the feeds (`nature_partition`, the nature read as CF-0577 reads it: title,
room, description, channel): a refused nature is `nature_refused`, a nature
outside the wanted list `nature_not_wanted`, and a work facet whose nature is
refused ("interview") is not spent. A person's search (an anchor outside the
event) keeps its own rule. The request says what was searched for the scene
(`search.scene[]`) and what the natures cost (`search.natures`).

**The sieves - entity mode.** The same four as the footage pass, in the same
order, with one change: "names the topic's work" becomes "names the entity"
(`topic_relevance.partition` / `footage_sieve.partition` over the entity's
name instead of `title_ref`); an upload that does not name the entity is
`wrong_entity`, and a work search's upload that names the work only by its
franchise's short form is `foreign_work_footage`.
`footage_origin` (fan edits, reactions, reposts) and the length ceiling
(`channels/<id>.json`, CF-0302) are unchanged. An id the topic's own footage
pass already offered is not offered again (`already_in_pool`).

One more, before the download (CF-0414, widened by CF-0426: `foreign_footage`
over `person_verdict`): an upload found for a **person** whose title names no
form of the topic's work passes only when it reads as the person as
themselves - `fc.classify` says interview, or the title or the channel names
an interview, a press conference or tour, a red carpet or premiere, an award,
a festival, a talk show (`SELF_RE`); a highlights reel only when it is a reel
of that kind. A cut of a work - trailer, teaser, promo, scene clip, a fan
edit or scene pack of a role, "Starring" - is `foreign_work_footage`;
anything that says neither is `person_not_as_self`. The indexer's source
sieve refuses the first kind once its shots are described (over half of them
neither the topic's work nor the entity, `source_foreign`): 0929Z downloaded
and described the Ebenezer trailer for Johnny Depp (87% off) and Civil War's
airport scene for Iron Man (85%) for an hour and got nothing.

**How many.** At most `max_attempts` x `CANDIDATE_SLACK` candidates (the
indexer downloads down the list until `shots_wanted` usable shots or
`max_attempts` new videos), round-robin across entities in request order and,
within an entity, across natures as `select_candidates` does.

**The feeds come first** (CF-0369, the rule CF-0361 gave the footage pass).
A search call is the scarce thing here (100 a day; on 2026-09-23T1722Z the day
was at 99 when the supplement's turn came and three topics got no supplement
at all), and the footage of a *work* - a trailer, a teaser, a clip - is an
upload of a registered official channel, which is readable without search:
`fetch_channel_feeds.topic_feed()` over the registry of the batch's channel
(`channels/<id>/footage-origin.json`, CF-0627) (RSS, 0 units; the uploads playlist, 1 unit per
50). So an entity that is a work goes to the feeds first:

  * the topic's **own** work (rule 1 above) is read from the feeds under the
    topic's whole `title_ref`, so its rights holder's and network's channels
    are read deep; if the batch already has that read on disk
    (`<batch>/work/feeds/feed-<topic_id>.json`, CF-0361), it is reused and the
    step costs nothing at all;
  * a franchise film the narrator names (rule 2) is read under its own name;
  * a **person** and a **place** are not on any work's upload feed and keep
    going to the search.

A feed read matches every `work_forms` form of the work's name - the
franchise's short form too, so Zenith's channels read for "Vanguards: Endgame
Encore" give every Vanguards trailer. So a feed upload is kept (CF-0426,
`feed_verdict`, the user's rule 5 of 2026-09-28) only when its **title** names
the topic's own work (a narrated franchise film included), or names a person
of the request and reads as that person as themselves (then it is that
person's candidate); another work's trailer, clip or podcast is
`foreign_work_footage`. The other three sieves are unchanged.

The search stays the fallback and is never a refusal: a work whose feeds gave
fewer than `FEED_ENOUGH` candidates is searched exactly as before, and a work
the feeds covered is listed in `search.searches_skipped[]` with
`covered_by_feeds` - the call it did not need is counted in
`search.search_calls_saved_by_feeds`.

**"Enough" is counted after the pool** (CF-0414). Batch 2026-09-27T0929Z:
Wolfhame's feed gave 4 uploads, "enough" (4 >= 2), the search was skipped - and
all 4 were already the topic's sources, so the request came back with 0
candidates (Kaijura Minus Zero and Day Drinker the same). The feed's
candidates are now counted once the topic's pool is out (`pool_ids`: the
footage pass's `youtube_video_ids`, the indexer's `sources_by_topic` /
`fetched` / `aliases` / earlier supplement offers, `work/footage-aliases.json`)
together with every upload of the same cut (`split_pool`); `search.feeds[]`
says `kept`, `in_pool`, `new_candidates`, and `enough` is `new_candidates >=
floor`. A work the feeds did not cover is searched, and the topic's **own**
work goes first under `SEARCH_CAP`: in 0929Z Day Drinker's search would have
sat behind four people's 16 calls.

**Quota.** Every planned search costs its `search.list` calls (1 + facets).
The plan takes searches in order while they fit both `SEARCH_CAP` and what
the batch's `search_quota` ledger has left (`search_quota.settle`, the
`--searches-spent` word included); the rest are listed with
`search_quota_exhausted`, never silently dropped. With `--search` the calls
made are written into the ledger under `supplement:<topic_id>`. The feed phase
runs **before** that budget is spent and writes nothing into the ledger: it
costs 0 `search.list` calls, and what it did cost - `videos.list` /
`playlistItems.list` units - is written on the request as
`search.feed_api_units`, a different currency the daily search cap does not
count.

**Exit code** (CF-0414). 0 - every request was filled and written, whatever
its candidate count: a request with none is an answer, its reasons are on it
(`searches_unrun`, `searches_skipped`, `candidates_dropped`) and on a
`no candidates for <topic>` stderr line. 1 - a request's searches all failed
(`search_failed`, none read) and it has no candidates: the tool failed, not
the topic. 2 - a request could not be read. Before CF-0414 any empty request
made the whole run exit 1, and the root's supplement step - one hunter run for
every request - wrote `hunter exit 1` on all five topics of 0929Z, three of
which had candidates.

Stdlib, plus the stage's own modules - one of which, `fetch_channel_feeds`
(the feed phase), reads the network with `requests`.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import fetch_channel_feeds as fcf  # noqa: E402
import footage_candidates as fc  # noqa: E402
import host_show  # noqa: E402  - CF-0817
import footage_origin  # noqa: E402
import footage_sieve  # noqa: E402
import search_quota  # noqa: E402
from _runlog import runlog  # noqa: E402
from fact_probe_topics import normalise  # noqa: E402
from topic_relevance import _acronyms, franchise_forms, names_work, work_forms  # noqa: E402

KIND = "thin_pool_supplement"
TASK = "CF-0343"
BLOCK = "search"                     # the block this module writes on a request
BATCH_FILE = "01-trend-hunter.json"
REQUEST_DIR = Path("work") / "supplement-requests"

KIND_PERSON, KIND_PLACE, KIND_SHOW, KIND_WORK = "person", "place", "show", "work"
KIND_EVENT = "event"
# CF-0582: the event itself - "<person> <moment>" of the topic's work ("Dakota
# Reyes monologue"), the entity the writer's `event_footage_short` request
# names beside the work (CF-0575). Searched as "<work> <person> <moment>".
KIND_SCENE = "scene"
ROLE_CREW = "crew"
# CF-0426 (the user, 2026-09-28): a person is searched only as themselves -
# an interview, a press tour / press conference, a red carpet, an award. No
# `trailer` (another film's) and no bare `highlights` (a cut of their roles);
# a highlights reel still comes in off these four, and passes only when it is
# a reel of the same kind (`person_verdict`).
PERSON_FACETS = ("interview", "press conference", "red carpet", "award")
FACETS_BY_KIND = {
    KIND_PERSON: PERSON_FACETS,
    KIND_WORK: ("trailer", "clip", "interview"),
    KIND_PLACE: ("filming",),
}
# CF-0582: the scene's queries - the work's name first, then the names its
# own uploads go under (the channel of the topic's own footage that names the
# work, the work's initials - "Dana Reyes Monologue - WNL" - and its
# network); each a bare query, one call, no facets (a facet word would steer
# the search off the event: "... monologue trailer").
SCENE_VARIANTS_MAX = 3
# CF-0582: the natures of a request (`natures_wanted` / `natures_refused`,
# CF-0575) hold for the searches of the event and of the work, not for a
# person's (an anchor outside the event, searched as themselves).
NATURE_KINDS = (KIND_SCENE, KIND_WORK, KIND_SHOW)
NATURE_REFUSED_CODE = "nature_refused"
NATURE_UNWANTED_CODE = "nature_not_wanted"
NATURE_CODES = (NATURE_REFUSED_CODE, NATURE_UNWANTED_CODE)
# CF-0426: the bare name of a person is not searched (`fetch_youtube_signal.py
# --no-bare`): in 0929Z it answered with other films' trailers and scene clips
# (Ebenezer for Johnny Depp, Civil War for Iron Man) and nothing of the person
# as themselves that the four facets do not find.
BARE_BY_KIND = {KIND_PERSON: False}
# The person's footage is years old; the scoring pass's week would find nothing.
SUPPLEMENT_DAYS = 3650
MAX_RESULTS = 15
# `search.list` calls one request may spend, whatever the day has left: a
# request is one topic's gap, not a licence to spend the day's quota on it.
SEARCH_CAP = 16
# Candidates per new video the indexer may spend: slack for a failed fetch
# and a same-source collapse, as FOOTAGE_CANDIDATE_MAX is for the pass.
CANDIDATE_SLACK = 2
DEFAULT_MAX_ATTEMPTS = 3

# CF-0369: the feed phase. A work's footage is read off the registered official
# channels first (`fetch_channel_feeds`), and only what the feeds did not give
# is searched for.
VIA_FEEDS = "feeds"
FEED_SOURCE = fcf.SOURCE
FEED_FACET = fcf.FEED_FACET
FEED_PAGES = fcf.DEFAULT_PAGES
# Feed candidates that count as "the feeds were enough": the same floor a topic
# is refused under (`fc.CANDIDATE_REFUSAL_FLOOR`, CF-0361's `fallback_search`),
# never more than the request's own candidate cap.
FEED_ENOUGH = fc.CANDIDATE_REFUSAL_FLOOR
# "read the key out of this repo" as a default argument, told apart from an
# explicit `api_key=None` (the RSS feeds only).
_AUTO_KEY = object()
# Where CF-0361 leaves the batch's own feed reads, one per topic.
FEED_DIR = Path("work") / "feeds"
# CF-0414: what the topic's pool already holds, read before "the feeds were
# enough" is decided - the indexer's report and its alias file.
POOL_FILE = "01b-footage-index.json"
ALIASES_FILE = Path("work") / "footage-aliases.json"

FOREIGN_WORK_CODE = "foreign_work"
# CF-0426 rule 4: where the narrator's text is - the writer's scripts.
NARRATION_FILE = "03-content-researcher.json"
NARRATION_KEYS = ("hook", "commentary", "payoff")
# A `title_ref.type` whose `parent_work` is an earlier film of the franchise
# (a sequel's), not the show an episode or a season belongs to.
FILM_TYPES = ("film", "movie")
_QUOTES = " \t'\"\u2018\u2019\u201c\u201d"
WRONG_ENTITY_CODE = "wrong_entity"
IN_POOL_CODE = "already_in_pool"
QUOTA_CODE = "search_quota_exhausted"
PLACE_CODE = "place_without_work"
OFF_SCREEN_CODE = "off_screen_person"
EVENT_CODE = "event"
# CF-0425: an entity of a kind this stage has no search for (`thing` - the
# Infinity Stones, which the writer's anchors carry since CF-0425 part 1 - or
# any kind a later writer adds). Before, it was searched as a person.
UNSEARCHED_KIND_CODE = "kind_not_searched"
FEED_COVERED_CODE = "covered_by_feeds"
# CF-0414 / CF-0426: a person search's upload that is a work's cut (or a
# work search's that names the work only by its franchise's short form).
FOREIGN_FOOTAGE_CODE = "foreign_work_footage"
WORK_CUT_KINDS = ("trailer", "teaser", "promo", "episode_clip")
HIGHLIGHTS_RE = re.compile(r"\bhighlights?\b", re.I)
WORK_CUT_WORDS_RE = re.compile(r"\b(clip|scenes?|trailer|teaser|promo|sneak peek|episode)\b",
                               re.I)
# CF-0426: a cut of someone's roles, whatever `fc.classify` calls it - a fan
# edit, a scene pack, a film's own listing ("A Christmas Miracle (2004)
# Starring Penélope Cruz"), a trailer in another language.
ROLE_CUT_RE = re.compile(
    r"\b(edit|edits|editz|scene ?pack|twixtor|fmv|amv|starring|full movie|movie clip|"
    r"tr[aá]iler|bande[\s-]annonce|every role|all roles|best scenes?|filmography)\b|#movies?\b",
    re.I)
# CF-0426: what a person "as themselves" is published under - the user's list
# (interview, press tour / conference, red carpet, award) and the rooms it
# happens in: talk shows, junkets, premieres, festivals, ceremonies.
SELF_RE = re.compile(
    r"\b(interview(s|ed)?|press (junket|conference|tour|day|event)|junket|red carpet|"
    r"premiere|photocall|award(s)?|oscars?|academy awards?|golden globes?|emmys?|baftas?|"
    r"sag awards?|cannes|venice film festival|sundance|berlinale|tiff|film festival|"
    r"comic[\s-]?con|panel|q\s*&\s*a|q and a|talks? (about|to|with)|sits? down|"
    r"in conversation|conversation with|on playing|answers|roundtable|acceptance speech|"
    r"speech|monologue|talk show|late show|late night|tonight show|jimmy kimmel|kimmel|"
    r"fallon|graham norton|colbert|sam meadows|hot ones|wired|vanity fair|actors on actors|"
    r"showbiz evening|access hollywood|good morning america|this morning|"
    r"the view|today show|cast (plays?|reads?|answers?|tests?|guess(es)?|reveals?))\b",
    re.I)
NOT_SELF_CODE = "person_not_as_self"
FEEDS_UNREAD_CODE = "feeds_not_read"
FEEDS_FAILED_CODE = "feeds_failed"
FEEDS_RULE = ("CF-0369: an entity that is a work (the topic's own, or a franchise film "
              "the narrator names) is read off the registered official channels' upload "
              "feeds first - 0 search calls - and searched only when the feeds gave fewer "
              f"than {FEED_ENOUGH} candidate(s). CF-0426: a feed upload is kept only when "
              "its title names the topic's own work, or names a person of the topic and "
              "reads as that person as themselves; another work's trailer or clip is "
              "foreign_work_footage. People and places are not on a work's feed and go "
              "straight to the search. CF-0414: the "
              "candidates are counted after the topic's pool is taken out - an upload "
              "the pool holds, is an alias of, or is the same cut of, is no new "
              "footage (`already_in_pool`), and the topic's own work, when its feeds "
              "did not cover it, is searched before the people.")
RULE = ("CF-0426 (the user, 2026-09-28): the supplement looks for the topic's own "
        "footage, then its people as themselves, and never for another work. A "
        "show/work entity that is not the topic's work is not searched "
        "(foreign_work) - not alone, not as '<person> <work>'. A person is searched "
        "for interview / press conference / red carpet / award, with no bare-name "
        "query; an upload found for a person whose title names no form of the topic's "
        "work passes only when it reads as the person as themselves (interview, press, "
        "premiere, awards, a talk show, a reel of those): a cut of a work (trailer, "
        "teaser, promo, scene clip, fan edit, a reel of roles) is foreign_work_footage, "
        "anything else person_not_as_self - both dropped before the download. "
        "Candidates must name their entity (wrong_entity). CF-0582: a scene entity "
        "(the event of an event_footage_short request) is searched as '<work> <person> "
        "<moment>' and its variants, and the request's natures_wanted/natures_refused "
        "hold for the scene's and the work's candidates (nature_refused, "
        "nature_not_wanted).")
# Keys the indexer reads as "the hunter dropped this" - never on a candidate.
INDEXER_DROP_KEYS = ("drop_reason", "dropped", "reason_code")


# --------------------------------------------------------------------------
# reading a request and its topic
# --------------------------------------------------------------------------

def load_request(path):
    doc = json.load(open(path))
    if not isinstance(doc, dict) or doc.get("kind") != KIND:
        raise ValueError(f"{path}: not a {KIND} request")
    if not isinstance(doc.get("topic_id"), str) or not doc["topic_id"]:
        raise ValueError(f"{path}: no topic_id")
    return doc


def request_paths(arg):
    p = Path(arg)
    if p.is_dir():
        return sorted(x for x in p.glob("*.json") if not x.name.endswith(".tmp"))
    return [p]


def batch_dir_of(request_path):
    """`<batch>/work/supplement-requests/<topic>.json` -> `<batch>`, or None."""
    p = Path(request_path).resolve()
    if p.parent.name == REQUEST_DIR.name and p.parent.parent.name == REQUEST_DIR.parent.name:
        return p.parent.parent.parent
    return None


def _find_topic(node, tid):
    if isinstance(node, dict):
        if node.get("topic_id") == tid and isinstance(node.get("title_ref"), (dict, str)):
            return node
        node = list(node.values())
    if isinstance(node, list):
        for x in node:
            hit = _find_topic(x, tid)
            if hit is not None:
                return hit
    return None


def topic_of(batch_dir, tid):
    """The topic record (`title_ref`, `evidence`) out of the batch's own
    artifacts: the hunter's file first, then the writer's."""
    if not batch_dir:
        return None
    for name in (BATCH_FILE, "03-content-researcher.json"):
        path = Path(batch_dir) / name
        if path.is_file():
            try:
                hit = _find_topic(json.load(open(path)), tid)
            except ValueError:
                hit = None
            if hit is not None:
                return hit
    return None


def _load(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return None


def pool_ids(batch_dir, topic_id, topic=None):
    """CF-0414: every video id this topic's pool already holds or already
    tried - an upload of one of them is no new footage, and a feed that gave
    only those is not "enough" (batch 2026-09-27T0929Z: Wolfhame's feed gave 4,
    all 4 were the topic's own sources, the search was skipped and the
    supplement came back empty).

    Read from: the topic's `evidence.youtube_video_ids` (the footage pass's
    offer), the indexer's `01b-footage-index.json` - `sources_by_topic`,
    `fetched[]`, `aliases[]` (both the alias and what it is an alias of) and
    the ids an earlier supplement round of this topic offered - and
    `work/footage-aliases.json`. Missing files are normal (a request outside a
    batch): what is there is read."""
    ids = set(((topic or {}).get("evidence") or {}).get("youtube_video_ids") or [])
    if not batch_dir or not topic_id:
        return ids
    ix = _load(Path(batch_dir) / POOL_FILE)
    if isinstance(ix, dict):
        ids.update((ix.get("sources_by_topic") or {}).get(topic_id) or [])
        for row in (ix.get("fetched") or []) + (ix.get("aliases") or []):
            if isinstance(row, dict) and row.get("topic_id") == topic_id:
                ids.update(x for x in (row.get("video_id"), row.get("alias_of")) if x)
        for row in ix.get("supplements") or []:
            if isinstance(row, dict) and row.get("topic_id") == topic_id:
                ids.update(row.get("offered") or [])
    al = _load(Path(batch_dir) / ALIASES_FILE)
    if isinstance(al, dict):
        for row in al.get(topic_id) or []:
            if isinstance(row, dict):
                ids.update(x for x in (row.get("video_id"), row.get("alias_of")) if x)
    return {i for i in ids if isinstance(i, str) and i}


def split_pool(videos, taken, name, config=None):
    """CF-0414: -> (fresh, in_pool records). A video already in the pool is
    out, and so is every upload of the same cut (`fc.group_videos`: a teaser
    re-uploaded under another title is the same footage the indexer would
    collapse as an alias)."""
    taken = set(taken or ())
    if not taken:
        return list(videos or []), []
    fresh, gone = [], []
    for g in fc.group_videos(videos or [], name, config):
        ids = [x.get("video_id") for x in g["videos"]]
        hit = next((i for i in ids if i in taken), None)
        if hit is None:
            fresh += g["videos"]
            continue
        for i in ids:
            rec = {"video_id": i, "reason_code": IN_POOL_CODE}
            if i != hit:
                rec["same_cut_as"] = hit
            gone.append(rec)
    return fresh, gone


def title_ref_of(req, topic=None, override=None):
    if override:
        return {"name": override}
    for ref in (req.get("title_ref"), (topic or {}).get("title_ref"), req.get("work")):
        if isinstance(ref, str) and ref.strip():
            return {"name": ref.strip()}
        if isinstance(ref, dict) and ref.get("name"):
            return ref
    for e in req.get("entities") or []:
        if isinstance(e, dict) and e.get("kind") == KIND_WORK and e.get("name"):
            return {"name": e["name"]}
    return None


def _entities(raw):
    out = []
    for e in raw or ():
        if isinstance(e, str):
            e = {"name": e, "kind": KIND_PERSON}
        if not isinstance(e, dict):
            continue
        name = str(e.get("name") or "").strip()
        if name and not any(x["name"].casefold() == name.casefold() for x in out):
            ent = {"name": name, "kind": e.get("kind") or KIND_PERSON}
            if e.get("role"):
                ent["role"] = e["role"]
            out.append(ent)
    return out


def off_screen_code(entity):
    """CF-0373: why an entity has no footage of its own to search for -
    `off_screen_person` for a `role: crew` person, `event` for `kind: event`;
    None otherwise (an entity without `role` included: a pre-CF-0372 request)."""
    if entity.get("kind") == KIND_EVENT:
        return EVENT_CODE
    if entity.get("role") == ROLE_CREW:
        return OFF_SCREEN_CODE
    return None


# --------------------------------------------------------------------------
# CF-0582: the event's own footage - the scene entity and the request's natures
# --------------------------------------------------------------------------

# A moment the writer could not name (`_supplement_request.event_entity`'s
# fallback): searched, but not required in a title.
GENERIC_MOMENTS = ("scene",)


def _ws(text):
    return " ".join(str(text or "").split())


def scene_parts(entity, req, title_ref):
    """CF-0582: a `kind: scene` entity -> {"person", "moment", "work"}.

    The writer names the event "<person> <moment>" ("Dana Reyes
    monologue", `_supplement_request.event_entity`) and puts the moment on the
    request's `event{}`; the person is the topic's `title_ref.person`, or the
    name with the moment taken off its end. A request without `event{}` (or
    one naming another event) gives the person and no moment: the name is
    searched whole."""
    name = _ws(entity.get("name"))
    ev = (req or {}).get("event") if isinstance((req or {}).get("event"), dict) else {}
    moment = None
    if _ws(ev.get("name")).casefold() == name.casefold() or not ev.get("name"):
        moment = _ws(ev.get("moment")) or None
    if moment and not name.casefold().endswith(moment.casefold()):
        moment = None
    person = _ws(name[:len(name) - len(moment)]) if moment else name
    ref = _ref(title_ref)
    work = _ws(ref.get("name")) or None
    if work and person and set(distinct_forms(person)) & set(distinct_forms(work)):
        person = None          # "<work> scene": the topic names no person
    if not person and not moment:
        person = name
    return {"person": person or None, "moment": moment, "work": work}


def work_channels(topic, title_ref):
    """CF-0582: the channels the topic's own footage went out on whose name
    names the topic's work ("Weekend Night Live") - the work's own channel,
    in the pool order."""
    forms = own_forms(_ref(title_ref)) if _ref(title_ref).get("name") else []
    ev = (topic or {}).get("evidence") or {}
    out = []
    for c in list((topic or {}).get("footage_candidates") or []) + list(
            ev.get("footage_candidates") or []):
        ch = _ws((c or {}).get("channel_title")) if isinstance(c, dict) else ""
        if ch and forms and names_work({"title": ch}, forms)[0] and ch not in out:
            out.append(ch)
    return out


def scene_queries(parts, title_ref, topic=None, cap=SCENE_VARIANTS_MAX):
    """CF-0582: the queries one scene is searched under - "<work> <person>
    <moment>" first, then the same with the names the work's own uploads go
    under: its channel (`work_channels`), its initials ("WNL" - "Dakota
    Reyes Monologue - WNL"), its network. One bare call each, at most `cap`;
    without a known work, "<person> <moment>" alone."""
    tail = _ws(" ".join(x for x in (parts.get("person"), parts.get("moment")) if x))
    ref = _ref(title_ref)
    work = parts.get("work")
    if not work:
        return [tail] if tail else []
    heads = [work] + work_channels(topic, ref)
    forms = own_forms(ref)
    heads += [f.upper() for f in forms if f in _acronym_forms(forms)]
    if ref.get("network"):
        heads.append(_ws(ref["network"]))
    out, seen = [], set()
    for h in heads:
        q = _ws(f"{h} {tail}")
        k = _key(q)
        if h and k not in seen:
            seen.add(k)
            out.append(q)
    return out[:max(1, cap)]


def _moment_named(title, moment):
    """Whether a title names the scene's moment - whole words, a plural
    allowed ("monologues", "sketches")."""
    words = normalise(moment).split()
    if not words:
        return True
    pat = r"(?<= )" + r" ".join(re.escape(w) for w in words) + r"(s|es)?(?= )"
    return bool(re.search(pat, normalise(title)))


def scene_miss(video, s, scope):
    """CF-0582: the drop record of an upload a scene search brought that is
    not that scene, or None. The scene is the person **and** the moment
    **and** the work: the person in the title, description or channel (as a
    person's search reads them), the moment in the **title** (CF-0575 counts
    an event source by the segment its title names), the work by any form of
    its own - its initials and its channel included ("Dana Reyes Monologue
    - WNL" on the channel Weekend Night Live). A generic moment ("scene") is
    not required."""
    missing = []
    person, moment, work = s.get("person"), s.get("moment"), s.get("work")
    if person and not names_work(video, work_forms({"name": person}))[0]:
        missing.append(repr(person))
    if (moment and moment.casefold() not in GENERIC_MOMENTS
            and not _moment_named(video.get("title"), moment)):
        missing.append(f"the moment {moment!r} in its title")
    if work:
        forms = (scope or {}).get("forms") or distinct_forms(work)
        if not names_work(video, forms)[0]:
            missing.append(repr(work))
    if not missing:
        return None
    return {"video_id": video.get("video_id"), "title": video.get("title"),
            "channel_title": video.get("channel_title"),
            "view_count": video.get("view_count"), "reason_code": WRONG_ENTITY_CODE,
            "reason": (f"does not name {' and '.join(missing)} - not the scene "
                       f"{s['entity']!r} it was searched for (CF-0582)")}


def request_natures(req):
    """CF-0582: the request's `natures_wanted` / `natures_refused` (CF-0575)
    -> (wanted, refused), each a tuple of known natures (`fc.NATURES`); both
    empty for a request that names none."""
    out = []
    for key in ("natures_wanted", "natures_refused"):
        raw = (req or {}).get(key)
        raw = raw if isinstance(raw, (list, tuple)) else ()
        out.append(tuple(dict.fromkeys(str(n) for n in raw if str(n) in fc.NATURES)))
    wanted, refused = out
    return tuple(n for n in wanted if n not in refused), refused


def facet_nature(facet):
    """The nature a search facet word asks for ("clip" -> episode), or None."""
    hit = fc._rule_of(facet)
    return hit[1] if hit else None


def nature_partition(videos, s):
    """CF-0582: -> (kept, dropped) under the search's `natures_wanted` /
    `natures_refused`. The nature is `fc.classify_with_source` - the title,
    then the room (a talk show's tag or channel), then the description, then
    the channel's words (CF-0577) - the same reading the candidate's `nature`
    is. A refused nature is `nature_refused`; with a wanted list, any other
    nature (`unknown` too) is `nature_not_wanted`."""
    wanted, refused = s.get("natures_wanted") or (), s.get("natures_refused") or ()
    if not (wanted or refused):
        return list(videos), []
    kept, dropped = [], []
    for v in videos:
        kind, nature, read = fc.classify_with_source(v)
        if nature in refused:
            code = NATURE_REFUSED_CODE
            why = f"its nature is {nature!r}, which the request refuses"
        elif wanted and nature not in wanted:
            code = NATURE_UNWANTED_CODE
            why = (f"its nature is {nature!r}, and the request wants only "
                   f"{', '.join(wanted)}")
        else:
            kept.append(v)
            continue
        dropped.append({"video_id": v.get("video_id"), "title": v.get("title"),
                        "channel_title": v.get("channel_title"),
                        "view_count": v.get("view_count"), "kind": kind, "nature": nature,
                        "nature_read": read, "reason_code": code,
                        "reason": (f"{why} (read off its {read}, CF-0577) - the event's "
                                   f"own footage is the work's cuts, not another "
                                   f"production's couch (CF-0575, CF-0582)")})
    return kept, dropped


def _clean(name):
    """An entity name as the writer's entity reader left it ("Vanguards:
    Endgame'" - a quote it did not strip) -> the name."""
    return str(name or "").strip(_QUOTES)


def _ref(title_ref):
    if isinstance(title_ref, str):
        return {"name": title_ref}
    return dict(title_ref or {})


def franchise_stems(name):
    """CF-0426: the normalised short forms a work's name shares with the rest
    of its franchise - the stem before a colon ("Vanguards" of "Vanguards:
    Endgame Encore") and the name without its sequel number ("Everyday Sorcery"
    of "Everyday Sorcery 2"). `topic_relevance.work_forms` counts both as
    naming the work, which is right for a topic's own footage pass and wrong
    for telling two works of one franchise apart. Since CF-0444 the rule lives
    in `topic_relevance.franchise_forms` - one place for the hunter's
    candidate sieve, this module and the indexer's pool check; a bare name has
    no `parent_work`, so this is exactly the two forms above."""
    return franchise_forms({"name": _clean(name)})


def distinct_forms(name):
    """The forms of a work's name that name **this** work: `work_forms`
    without the franchise's short forms (`franchise_stems`)."""
    name = _clean(name)
    forms = work_forms({"name": name})
    stems = franchise_stems(name)
    return [f for f in forms if f not in stems] or forms


def own_names(title_ref):
    """The names of the topic's own work: `title_ref.name`, and its
    `parent_work` when that is the show an episode or a season belongs to - a
    film's `parent_work` is the franchise's earlier film, which is the topic's
    only when the narrator names it (CF-0426 rule 4, `topic_scope`)."""
    ref = _ref(title_ref)
    names = [ref.get("name")]
    parent = ref.get("parent_work") or ref.get("parent")
    if parent and str(ref.get("type") or "").lower() not in FILM_TYPES:
        names.append(parent)
    return [_clean(n) for n in names if n and _clean(n)]


def own_forms(title_ref, named=()):
    """The forms that name the topic's own work - `distinct_forms` of its own
    names plus the franchise works the narrator names (`named`)."""
    forms = []
    for n in own_names(title_ref) + [_clean(x) for x in named]:
        for f in distinct_forms(n):
            if f not in forms:
                forms.append(f)
    return forms


def is_topic_work(name, title_ref):
    """Whether a show/work entity is the topic's own work: a form of it that
    names this work (not the franchise's short form) is one of the topic's.

    CF-0426: "Vanguards: Infinity War" is not "Vanguards: Endgame Encore" -
    both share the short form "Vanguards", which `work_forms` counts, and in
    0929Z that made another film of the franchise the topic's own work."""
    forms = set(own_forms(title_ref)) if title_ref else set()
    if not forms:
        return False
    mine = set(distinct_forms(name))
    # CF-0425: an acronym names the work only when one side *is* the acronym
    # ("AEE" for "Vanguards: Endgame Encore"). Two spelled-out names that only
    # share their initials ("Adventures: Elm Eagles") are two works.
    own_acr, mine_acr = _acronym_forms(forms), _acronym_forms(mine)
    if (mine - mine_acr) & (forms - own_acr):
        return True
    whole = normalise(_clean(name)).strip()
    owns = {normalise(n).strip() for n in own_names(title_ref)}
    return whole in own_acr or bool(owns & mine_acr)


def _acronym_forms(forms):
    """The forms in `forms` that are only another form's initials."""
    acr = {a for f in forms for a in _acronyms(f)}
    return {f for f in forms if f in acr}


def same_franchise(name, title_ref):
    """Whether a work that is not the topic's belongs to its franchise: the
    two share a form of their names - a colon stem, the name without a sequel
    number, or the topic's `parent_work`."""
    ref = _ref(title_ref)
    fam = set()
    for n in (ref.get("name"), ref.get("parent_work") or ref.get("parent")):
        if n:
            fam |= set(work_forms({"name": _clean(n)}))
    return bool(set(work_forms({"name": _clean(name)})) & fam)


def narration_of(batch_dir, topic_id):
    """CF-0426 rule 4: the narrator's text of the topic's script - `hook`,
    `commentary`, `payoff` of its `scripts[]` entry in the batch's
    `03-content-researcher.json`, which the writer wrote before its pool gates
    left the request (0929Z: 03 was on disk two hours before the step). ""
    when the batch or the script is not there."""
    if not batch_dir or not topic_id:
        return ""
    doc = _load(Path(batch_dir) / NARRATION_FILE)
    texts = []
    for sc in (doc or {}).get("scripts") or [] if isinstance(doc, dict) else []:
        if isinstance(sc, dict) and sc.get("topic_id") == topic_id:
            texts += [sc[k] for k in NARRATION_KEYS if isinstance(sc.get(k), str)]
    return " ".join(texts)


def _mask(text, forms):
    """`text` normalised with every form in `forms` blanked out, longest
    first - so "Everyday Sorcery 2" in the narration does not read as the
    narrator naming "Everyday Sorcery"."""
    t = normalise(text)
    for f in sorted(forms, key=len, reverse=True):
        t = re.sub(r"(?<= )" + re.escape(f) + r"(?= )", "#", t)
    return t


def topic_scope(req, title_ref, narration=None):
    """CF-0426: what counts as the topic's own footage for this request.

    -> {"forms", "franchise_named", "franchise_unnamed", "narration_source",
    "persons"}. `forms` name the topic's own work (`own_forms`) plus every
    work of its franchise the narrator names - in the script's hook /
    commentary / payoff (`narration`, `narration_of`) or in the request's own
    anchors' `beat_text` (which is the narrator's text, beat by beat). A work
    of the franchise the narrator does not name is `franchise_unnamed`:
    another work, never searched, never kept (the user, 2026-09-28 rule 4).
    The franchise works looked at are the request's show/work entities, its
    anchors' and a film's `parent_work`."""
    req = req or {}
    ref = _ref(title_ref)
    beats = [a.get("beat_text") for a in req.get("anchors") or []
             if isinstance(a, dict) and isinstance(a.get("beat_text"), str)]
    text = " ".join([narration or ""] + beats)
    base = own_forms(ref) if ref.get("name") else []
    masked = _mask(text, base)
    names = []
    parent = ref.get("parent_work") or ref.get("parent")
    if parent and str(ref.get("type") or "").lower() in FILM_TYPES:
        names.append(parent)
    ents = list(req.get("entities") or [])
    for a in req.get("anchors") or []:
        if isinstance(a, dict):
            ents += list(a.get("entities") or []) if isinstance(a.get("entities"), list) else []
    for e in _entities(ents):
        if e["kind"] in (KIND_SHOW, KIND_WORK):
            names.append(e["name"])
    named, unnamed, seen = [], [], set()
    for n in names:
        n = _clean(n)
        key = tuple(distinct_forms(n))
        if not n or key in seen or not base:
            continue
        seen.add(key)
        if is_topic_work(n, ref) or not same_franchise(n, ref):
            continue
        (named if names_work({"title": masked}, list(key))[0] else unnamed).append(n)
    persons = [e["name"] for e in _entities(req.get("entities"))
               if e["kind"] == KIND_PERSON and not off_screen_code(e)]
    return {"forms": own_forms(ref, named) if base else [],
            "franchise_named": named, "franchise_unnamed": unnamed,
            "narration": bool(text.strip()), "persons": persons}


def is_franchise_named(name, scope):
    key = set(distinct_forms(name))
    return any(key & set(distinct_forms(n)) for n in (scope or {}).get("franchise_named") or [])


def names_own(video, scope, fields=("title",)):
    """Whether the upload names the topic's own work (a franchise work the
    narrator names included) in `fields`."""
    forms = (scope or {}).get("forms") or []
    return bool(forms) and bool(names_work({f: video.get(f) for f in fields}, forms)[0])


# --------------------------------------------------------------------------
# the plan: which searches, under the foreign-work rule and the quota
# --------------------------------------------------------------------------

def calls_of(s):
    """`search.list` calls one planned search costs: the bare query (unless
    `bare` is False - a person, CF-0426) plus one per facet."""
    return (0 if s.get("bare") is False else 1) + len(s.get("facets") or ())


def wanted_searches(req, title_ref, narration=None, scope=None, topic=None):
    """-> (wanted, entities_skipped): every search this request's entities ask
    for, before any budget and before the feed phase takes the works out.

    One search = one `fetch_youtube_signal.py` run: `query`, `facets`, `bare`
    (False: the facets only, no bare-name query), `entity` (whose footage it
    is), `needs` (the names a candidate must carry), `franchise` (True: a work
    of the topic's franchise the narrator names, CF-0426 rule 4).

    CF-0582: a `kind: scene` entity (the event of an `event_footage_short`
    request, CF-0575) is searched as "<work> <person> <moment>" and its
    variants (`scene_queries`), one bare call each, ahead of everything else;
    the request's `natures_wanted` / `natures_refused` ride on the scene's and
    the work's searches (`nature_partition`), and a work facet whose nature
    the request refuses ("interview") is not spent."""
    scope = scope or topic_scope(req, title_ref, narration)
    ents = _entities(req.get("entities"))
    wanted, skipped_entities = [], []
    n_wanted, n_refused = request_natures(req)
    for e in ents:
        name, kind = e["name"], e["kind"]
        if kind == KIND_SCENE:
            parts = scene_parts(e, req, title_ref)
            for q in scene_queries(parts, title_ref, topic):
                wanted.append({"entity": name, "kind": KIND_SCENE, "query": q,
                               "facets": [], "bare": True, **parts,
                               "needs": [x for x in (parts["person"], parts["work"]) if x],
                               "sieve_name": parts["work"] or name})
            continue
        code = off_screen_code(e)
        if code:
            skipped_entities.append({
                "entity": name, "kind": kind, "reason_code": code,
                "reason": (f"{name!r} is behind the camera (role: crew) - a search for "
                           f"them brings other people's frames (CF-0373)"
                           if code == OFF_SCREEN_CODE else
                           f"{name!r} is an event, not someone or something on screen "
                           f"in the topic's work (CF-0373)")})
            continue
        if kind in (KIND_SHOW, KIND_WORK):
            if is_topic_work(name, title_ref) or (kind == KIND_WORK and not title_ref):
                wanted.append({"entity": name, "kind": KIND_WORK, "query": name,
                               "facets": work_facets(n_wanted, n_refused), "needs": [name]})
                continue
            if is_franchise_named(name, scope):
                # CF-0426 rule 4: an earlier film of the franchise the narrator
                # names himself is the topic's frame - searched as a work.
                wanted.append({"entity": _clean(name), "kind": KIND_WORK,
                               "query": _clean(name), "franchise": True,
                               "facets": work_facets(n_wanted, n_refused),
                               "needs": [_clean(name)]})
                continue
            # CF-0426: another work is never searched - not alone and not as
            # "<person> <work>" (CF-0343's rule 2, gone): a frame of another
            # film in another role leaves the viewer unsure which film the
            # video is about (the user on kaijura, 2026-09-28).
            franchise = same_franchise(name, title_ref) if title_ref else False
            skipped_entities.append({
                "entity": name, "kind": kind, "reason_code": FOREIGN_WORK_CODE,
                "reason": (f"{name!r} is another work of the topic's franchise "
                           f"({(title_ref or {}).get('name')!r}) and the narrator does not "
                           f"name it - its frames would be another film's (CF-0426 rule 4)"
                           if franchise else
                           f"{name!r} is not the topic's work "
                           f"({(title_ref or {}).get('name')!r}) - another work's frames "
                           f"are not the topic's, with or without a person of the topic "
                           f"in them (CF-0426)")})
            continue
        if kind == KIND_PLACE:
            # A place name is ambiguous ("Worcester Park" is also a cricket
            # club): searched only as "<place> <topic's work>", and its
            # candidates must name both - filming there, not the place.
            work = (title_ref or {}).get("name")
            if not work:
                skipped_entities.append({
                    "entity": name, "kind": kind, "reason_code": PLACE_CODE,
                    "reason": "a place is searched only with the topic's work, and the "
                              "topic's work is unknown (CF-0343)"})
                continue
            wanted.append({"entity": name, "kind": kind, "query": f"{name} {work}",
                           "facets": list(FACETS_BY_KIND[KIND_PLACE]), "needs": [name, work]})
            continue
        if kind not in FACETS_BY_KIND:
            skipped_entities.append({
                "entity": name, "kind": kind, "reason_code": UNSEARCHED_KIND_CODE,
                "reason": f"{name!r} is a {kind!r}, and only a person, a place or the "
                          f"topic's work is searched for - a {kind!r} searched as a "
                          f"person brings other people's frames (CF-0425)"})
            continue
        facets = FACETS_BY_KIND[kind]
        wanted.append({"entity": name, "kind": kind, "query": name,
                       "facets": list(facets), "needs": [name],
                       "bare": BARE_BY_KIND.get(kind, BARE_BY_KIND[KIND_PERSON])})
    for s in wanted:
        s["searches"] = calls_of(s)
        if s["kind"] in NATURE_KINDS and (n_wanted or n_refused):
            s["natures_wanted"], s["natures_refused"] = list(n_wanted), list(n_refused)
    # CF-0582: the event leads - in the plan and in the round-robin choice.
    wanted.sort(key=lambda s: s["kind"] != KIND_SCENE)
    return wanted, skipped_entities


def work_facets(wanted=(), refused=()):
    """The facets a work is searched with (`FACETS_BY_KIND`), less those whose
    nature the request refuses or (with a wanted list) does not want - CF-0582:
    an `event_footage_short` request spends no call on "<work> interview"."""
    out = [f for f in FACETS_BY_KIND[KIND_WORK]
           if facet_nature(f) not in refused and (not wanted or facet_nature(f) in wanted)]
    return out


def apply_budget(wanted, remaining=None, cap=SEARCH_CAP):
    """-> (searches, skipped, budget, planned): the searches that fit both
    `cap` and what the quota day has left, in request order; the rest listed
    with `search_quota_exhausted`."""
    budget = cap if remaining is None else min(cap, max(0, int(remaining)))
    searches, skipped, spent = [], [], 0
    for s in wanted:
        s["searches"] = calls_of(s)
        if spent + s["searches"] <= budget:
            spent += s["searches"]
            searches.append(s)
        else:
            skipped.append(dict(s, reason_code=QUOTA_CODE,
                                reason=f"needs {s['searches']} search call(s), "
                                       f"{budget - spent} left of {budget}"))
    return searches, skipped, budget, spent


# --------------------------------------------------------------------------
# the feed phase: a work's footage off the official channels, 0 search calls
# --------------------------------------------------------------------------

def feed_work_of(s):
    """The work whose official-channel feeds answer this planned search: the
    entity itself for the topic's own work. None for a person (interviews,
    press, awards) and a place (filming) - a work's upload feed does not hold
    those, so they keep going to the search (CF-0369). Another work is never
    planned at all (CF-0426), so it has no feed read either."""
    if s.get("kind") == KIND_WORK:
        return s["entity"]
    return None


def feed_item(s, title_ref=None):
    """The plan item of one feed read - the same shape `sieve()` and
    `entity_candidates()` take for a search, with:

      * `needs` = the work. The upload is on the work's own registered
        official channel and its title names the work, which is what makes it
        that work's footage.
      * `sieve_name` = the work: the footage sieve and the cut grouping ask
        the title about the work.
      * `entity` = whoever the candidate is for, so the request's candidates
        stay in the indexer's shape.

    -> None for a search the feeds cannot answer."""
    work = feed_work_of(s)
    if not work:
        return None
    own = is_topic_work(work, title_ref)
    ref = dict(title_ref) if own and isinstance(title_ref, dict) else {"name": work}
    item = {"entity": s["entity"], "kind": s["kind"], "work": work, "own_work": own,
            "query": work, "facets": [FEED_FACET], "needs": [work],
            "sieve_name": work, "via": VIA_FEEDS, "source": FEED_SOURCE,
            "searches": 0, "ref": ref}
    if s.get("franchise"):
        item["franchise"] = True
    for k in ("natures_wanted", "natures_refused"):
        if s.get(k):
            item[k] = list(s[k])
    return item


def feed_row(item):
    """One feed read as it is written into the plan / the request (no `ref`:
    the record is read by people, and the ref is already `title_ref`)."""
    return {k: item[k] for k in ("entity", "kind", "work", "own_work", "franchise", "needs",
                                 "source", "searches") if k in item}


def feed_command(item):
    """The `fetch_channel_feeds.py` command that reads this work's feeds, for
    the record of a read nobody made."""
    ref = item.get("ref") or {}
    argv = [str((HERE / "fetch_channel_feeds.py").name), item["work"]]
    if ref.get("rights_holder"):
        argv += ["--rights-holder", ref["rights_holder"]]
    if ref.get("network"):
        argv += ["--network", ref["network"]]
    return " ".join(repr(a) if " " in a else a for a in argv)


def feed_reader(api_key=_AUTO_KEY, http=None):
    """A `fetch_channel_feeds.Reader` - reads every channel once per process.
    The key is this repo's own unless one is passed (`api_key=None`: the RSS
    feeds only - 0 units, no `playlistItems.list` and no `videos.list`)."""
    key = fcf.youtube_api_key() if api_key is _AUTO_KEY else api_key
    return fcf.Reader(api_key=key, http=http)


def make_feeder(reader=None, pages=FEED_PAGES, limits=None, config=None):
    """-> a callable `feed item -> feed signal` for `fill()`. This is the one
    place in the supplement that reads the feeds off the network."""
    reader = reader if reader is not None else feed_reader()

    def read(item):
        return fcf.topic_feed(item["ref"], reader, pages=pages, config=config,
                              limits=limits)

    read.reader = reader
    return read


def batch_feeds(batch_dir, topic_id):
    """The feed read CF-0361 already left in the batch for this topic
    (`work/feeds/feed-<topic_id>.json`) -> `{query: signal}`, or `{}`. Reusing
    it makes the own-work half of the supplement free."""
    if not batch_dir or not topic_id:
        return {}
    path = Path(batch_dir) / FEED_DIR / f"feed-{topic_id}.json"
    if not path.is_file():
        return {}
    try:
        sig = json.load(open(path))
    except (ValueError, OSError):
        return {}
    if not isinstance(sig, dict) or not sig.get("query"):
        return {}
    # CF-0425 item 3: this read was paid for once, by the pass that wrote it
    # (its units are already in the ledger under the topic's own key); reading
    # the file again costs nothing (CF-0369) - `cached` keeps it off the
    # `supplement-feeds` article.
    sig = dict(sig, read_from=str(path), cached=True)
    return {sig["query"]: sig}


def plan(req, title_ref, remaining=None, cap=SEARCH_CAP, covered=(), narration=None,
         topic=None):
    """-> {"searches", "skipped", "feeds", "entities_skipped", "budget",
    "planned"}.

    `feeds` names the entities whose footage the official channels' feeds
    answer for (CF-0369) - the works, in request order. `covered` is the works
    a feed read has already given enough candidates for: their searches are not
    planned at all and are listed in `skipped` with `covered_by_feeds`, which
    is a call saved, not a refusal. A search with a feed read ahead of it
    carries `feeds_first`, so that its `search_quota_exhausted` is not read as
    the entity going without footage."""
    wanted, skipped_entities = wanted_searches(req, title_ref, narration, topic=topic)
    feeds = [feed_row(feed_item(s, title_ref)) for s in wanted if feed_work_of(s)]
    for s in wanted:
        if feed_work_of(s):
            # The feeds are read before this search, so its `search_quota_exhausted`
            # is not the entity going without footage - which is what the plan
            # printout of 2026-09-23T1722Z would otherwise read like.
            s["feeds_first"] = True
    covered_keys = {_key(w) for w in covered or ()}
    rest, by_feeds = [], []
    for s in wanted:
        work = feed_work_of(s)
        if work and _key(work) in covered_keys:
            by_feeds.append(dict(s, reason_code=FEED_COVERED_CODE,
                                 reason=(f"the official channels' feeds already gave "
                                         f"footage of {work!r}: the {s['searches']} search "
                                         f"call(s) this query would cost are not spent "
                                         f"(CF-0369)")))
        else:
            rest.append(s)
    # CF-0414: the topic's own work, when its feeds did not cover it, is
    # searched first - its footage is the one the source sieve always keeps,
    # and in 0929Z Day Drinker's search sat behind four people's 16 calls.
    # CF-0426: then a franchise work the narrator names, then the people.
    # CF-0582: the event's scene before all of them - it is what the request
    # is for.
    rest.sort(key=lambda s: -1 if s["kind"] == KIND_SCENE
              else 0 if (s["kind"] == KIND_WORK and is_topic_work(s["entity"], title_ref))
              else 1 if s.get("franchise") else 2)
    searches, skipped, budget, spent = apply_budget(rest, remaining, cap)
    return {"searches": searches, "skipped": by_feeds + skipped, "feeds": feeds,
            "entities_skipped": skipped_entities, "budget": budget, "planned": spent}


def command(s, days=SUPPLEMENT_DAYS, max_results=MAX_RESULTS):
    """The `fetch_youtube_signal.py` argv of one planned search (`--no-bare`
    for a person, CF-0426: the facets only)."""
    return ([sys.executable, str(HERE / "fetch_youtube_signal.py"), s["query"]]
            + (["--facets", ",".join(s["facets"])] if s.get("facets") else [])
            + ["--days", str(days),
             "--max-results", str(max_results)]
            + (["--no-bare"] if s.get("bare") is False else []))


def run_search(s, days=SUPPLEMENT_DAYS, max_results=MAX_RESULTS):
    """Run one planned search through the stage's own fetcher; -> its JSON.

    The subprocess is told whose quota it is spending (CF-0368): it is the same
    `fetch_youtube_signal.py --facets` step 5b runs, and without the word in
    its environment the run log has no way to tell the supplement's calls from
    the footage pass's."""
    env = search_quota.with_article(os.environ, search_quota.ARTICLE_SUPPLEMENT)
    out = subprocess.run(command(s, days, max_results), capture_output=True, text=True,
                         timeout=120, env=env)
    if out.returncode != 0:
        raise RuntimeError(f"fetch_youtube_signal.py {s['query']!r}: "
                           f"{(out.stderr or '').strip()[-300:]}")
    return json.loads(out.stdout)


# --------------------------------------------------------------------------
# the sieves, entity mode, and the choice
# --------------------------------------------------------------------------

def sieve_name(s):
    """The name the footage sieve and the cut grouping ask the title about:
    the entity, or the work for a feed read (CF-0369)."""
    return s.get("sieve_name") or s["entity"]


def _wrong_entity(video, needs):
    return {"video_id": video.get("video_id"), "title": video.get("title"),
            "channel_title": video.get("channel_title"),
            "view_count": video.get("view_count"), "reason_code": WRONG_ENTITY_CODE,
            "reason": (f"does not name {' and '.join(repr(n) for n in needs)} in its title, "
                       f"description or channel - not footage of the entity it was "
                       f"searched for (CF-0343)")}


def person_verdict(video):
    """CF-0426: what an upload found for a person reads as, before anyone has
    seen a frame of it -> (`self` | `cut` | `unknown`, the `fc.classify` kind).

      * `cut` - a cut of a work: `fc.classify` says trailer / teaser / promo /
        scene clip (a highlights reel with no cut word is not one), or the
        title carries a cut word (trailer, clip, scene, episode...) or a role
        reel's (a fan edit, a scene pack, "Starring", a trailer in another
        language). Checked first: "the scene that won Penélope Cruz her first
        Oscar" is a scene of another film, whatever the Oscar in it says.
      * `self` - the person as themselves: `fc.classify` says interview, or
        the title or the channel names a room the person sits in as
        themselves (`SELF_RE`: an interview, a press conference or tour, a red
        carpet or premiere, an award, a festival, a talk show). A highlights
        reel passes this way only when it is a reel of the same kind ("funny
        interview moments"); a reel of roles does not.
      * `unknown` - neither: an upload that says nothing about what it is."""
    kind, _ = fc.classify(video)
    title = str(video.get("title") or "")
    highlights_only = (kind == "episode_clip" and HIGHLIGHTS_RE.search(title)
                       and not WORK_CUT_WORDS_RE.search(title))
    if ((kind in WORK_CUT_KINDS and not highlights_only) or WORK_CUT_WORDS_RE.search(title)
            or ROLE_CUT_RE.search(title)):
        return "cut", kind
    where = " ".join(str(video.get(k) or "") for k in ("title", "channel_title"))
    if kind == "interview" or SELF_RE.search(where):
        return "self", kind
    return "unknown", kind


def foreign_footage(video, s, title_ref, scope=None):
    """CF-0414 / CF-0426: the drop record of an upload a **person** search
    brought that is not the person as themselves, or None.

    The footage indexer's source sieve (CF-0344,
    `agents/footage-indexer/scripts/source_sieve.py::judge` over
    `shot_schema.sieve_counts(entity=...)`) refuses a supplement source as
    `source_foreign` when over half its shots neither picture the topic's work
    (`on_topic`) nor show the entity it was fetched for (`shows_entity`). A
    trailer, teaser, promo or scene clip of another film is exactly that - an
    ensemble cut in which the actor is a minority of the shots: in 0929Z the
    Ebenezer trailer fetched for Johnny Depp was 87% off, the Captain America:
    Civil War airport scene fetched for Iron Man 85%, and in 1722Z the Ad Astra
    trailer fetched for James Grove 100% - each an hour of download and
    description for nothing. What did reach the videos over four runs (four
    shots) was all interviews - the person as themselves. And the user, on
    2026-09-28, refused even what the sieve would keep: a frame of another
    film, in another role, leaves the viewer unsure which film the video is
    about.

    So, before the download: the search is a person's (anything but the
    topic's work or a place); an upload whose **title** names a form of the
    topic's work (`topic_scope` forms: the work itself, not its franchise's
    short form, plus a franchise work the narrator names) is the topic's
    footage and passes (the Day Drinker teaser found for Penélope Cruz); any
    other passes only when it
    reads as the person as themselves (`person_verdict` `self`). A cut of a
    work is `foreign_work_footage`, anything else `person_not_as_self`."""
    if s.get("via") == VIA_FEEDS or s.get("kind") in (KIND_WORK, KIND_SHOW, KIND_PLACE,
                                                     KIND_SCENE):
        return None
    scope = scope if scope is not None else topic_scope({}, title_ref)
    title = str(video.get("title") or "")
    if names_own(video, scope):
        return None
    verdict, kind = person_verdict(video)
    if verdict == "self":
        return None
    rec = {"video_id": video.get("video_id"), "title": title,
           "channel_title": video.get("channel_title"),
           "view_count": video.get("view_count"), "kind": kind}
    work = (title_ref or {}).get("name")
    if verdict == "cut":
        rec.update(reason_code=FOREIGN_FOOTAGE_CODE, reason=(
            f"a {kind if kind in WORK_CUT_KINDS else 'cut'} of another work: its title "
            f"names no form of the topic's work ({work!r}), and a search for "
            f"{s['entity']!r} brought it. Another film in another role is not the "
            f"person as themselves (CF-0426), and the footage indexer's source sieve "
            f"refuses such a source as `source_foreign` once its shots are described "
            f"(0929Z: the Ebenezer trailer 87%, the Civil War airport scene 85%). "
            f"Dropped before the download."))
    else:
        rec.update(reason_code=NOT_SELF_CODE, reason=(
            f"its title names no form of the topic's work ({work!r}) and does not read "
            f"as {s['entity']} as themselves - an interview, a press conference or "
            f"tour, a red carpet, an award, a talk show, or a reel of those (CF-0426). "
            f"Dropped before the download."))
    return rec


def _need_forms(n, s, scope):
    """The forms a candidate must carry for one of `needs`: a work's are the
    topic's own forms (`topic_scope`, the franchise's short form not among
    them) when the need is the topic's work or a franchise work the narrator
    names, else that work's own `distinct_forms`; a person's or a place's are
    `work_forms` of the name, as before."""
    is_work = s.get("kind") in (KIND_WORK, KIND_SHOW) or s.get("via") == VIA_FEEDS or (
        s.get("kind") == KIND_PLACE and n != s.get("entity"))
    if not is_work:
        return work_forms({"name": n})
    if scope and scope.get("forms") and set(distinct_forms(n)) & set(scope["forms"]):
        return scope["forms"]
    return distinct_forms(n)


def _franchise_only(video, s, needs):
    """CF-0426: the drop record of a work search's upload that names the work
    only by its franchise's short form ("Vanguards: Infinity War" found for
    "Vanguards: Endgame Encore"), or None."""
    if s.get("kind") not in (KIND_WORK, KIND_SHOW) and s.get("via") != VIA_FEEDS:
        return None
    if not all(names_work(video, work_forms({"name": _clean(n)}))[0] for n in needs):
        return None
    return {"video_id": video.get("video_id"), "title": video.get("title"),
            "channel_title": video.get("channel_title"),
            "view_count": video.get("view_count"), "reason_code": FOREIGN_FOOTAGE_CODE,
            "reason": (f"names {' and '.join(repr(n) for n in needs)} only by the "
                       f"franchise's short form - another work of the franchise the "
                       f"narrator does not name, not the topic's footage (CF-0426)")}


def feed_verdict(video, s, scope):
    """CF-0426 (the user, 2026-09-28 rule 5): what an official channel's upload
    read for the topic's work may be -> (None, person) to keep it, or (drop
    record, None).

    `fetch_channel_feeds.topic_feed` matches every `work_forms` form of the
    work's name, the franchise's short form among them, so a read of
    "Vanguards: Endgame Encore" off Zenith's channels brings every Vanguards
    trailer and clip. Kept are only:

      * an upload whose **title** names the topic's own work (a franchise film
        the narrator names included, `topic_scope`) - whatever its kind: it is
        the topic's trailer, clip or featurette;
      * an upload whose title names a person of the request and reads as that
        person as themselves (`person_verdict` `self`: an interview, a press
        conference, a premiere...) - kept for that person.

    Anything else - another work's trailer, teaser, clip - is
    `foreign_work_footage`. Title only, as `fetch_channel_feeds.names_in_title`
    reads it: an official channel's description lists its other works."""
    forms = (scope or {}).get("forms") or distinct_forms(s.get("work") or s["entity"])
    title = str(video.get("title") or "")
    if names_work({"title": title}, forms)[0]:
        return None, None
    for person in (scope or {}).get("persons") or []:
        if names_work({"title": title}, work_forms({"name": person}))[0]:
            verdict, _ = person_verdict(video)
            if verdict == "self":
                return None, person
    kind, _ = fc.classify(video)
    return {"video_id": video.get("video_id"), "title": title,
            "channel_title": video.get("channel_title"),
            "view_count": video.get("view_count"), "kind": kind,
            "reason_code": FOREIGN_FOOTAGE_CODE,
            "reason": (f"an upload of an official channel read for "
                       f"{s.get('work') or s['entity']!r} whose title names no form of the "
                       f"topic's work - another work's {kind if kind != 'unknown' else 'upload'}"
                       f" (the feed matched the franchise's short form or the channel), and "
                       f"not a person of the topic as themselves (CF-0426)")}, None


def sieve(videos, s, limits=None, config=None, title_ref=None, scope=None):
    """-> (kept, dropped) for one search's videos: names the entity (every
    name in `needs`; a work by a form of its own, not by its franchise's short
    form - CF-0426), not another work's cut nor a person not as themselves
    (`foreign_footage`), then `footage_origin`,
    the length ceiling and `footage_sieve` with the entity as the 'work'. Order as in the footage
    pass (`fc.select_candidates`). `scope` is the request's `topic_scope`
    (built from `title_ref` alone when not handed in)."""
    config = footage_origin._require(config)
    if scope is None:
        scope = topic_scope({}, title_ref)
    kept, dropped, as_person = [], [], {}
    for v in videos or []:
        if not v.get("video_id"):
            continue
        if s.get("via") == VIA_FEEDS:
            rec, person = feed_verdict(v, s, scope)
            if rec:
                dropped.append(rec)
                continue
            if person:
                as_person[v["video_id"]] = person
            kept.append(v)
            continue
        if s.get("kind") == KIND_SCENE:
            # CF-0582: the scene is the person, the moment and the work - and
            # its cut is the work's own, so no person-as-themselves verdict.
            miss = scene_miss(v, s, scope)
            if miss:
                dropped.append(miss)
            else:
                kept.append(v)
            continue
        if not all(names_work(v, _need_forms(n, s, scope))[0] for n in s["needs"]):
            dropped.append(_franchise_only(v, s, s["needs"]) or _wrong_entity(v, s["needs"]))
            continue
        foreign = foreign_footage(v, s, title_ref, scope)
        if foreign:
            dropped.append(foreign)
            continue
        kept.append(v)
    kept, unofficial = footage_origin.partition(kept, config)
    kept, too_long = fc.partition_too_long(kept, limits)
    # The title must name the entity - for a feed read of a work, the work
    # (`sieve_name`, CF-0369), whose own channel the upload is on; for a feed
    # upload of a person as themselves (CF-0426), that person.
    work_kept = [v for v in kept if v["video_id"] not in as_person]
    kept_out, not_footage = footage_sieve.partition(work_kept, {"name": sieve_name(s)},
                                                    origin=config)
    for person in dict.fromkeys(as_person.values()):
        mine = [v for v in kept if as_person.get(v["video_id"]) == person]
        got, gone = footage_sieve.partition(mine, {"name": person}, origin=config)
        kept_out += [dict(v, as_person=person) for v in got]
        not_footage += gone
    order = {v["video_id"]: i for i, v in enumerate(kept)}
    kept_out.sort(key=lambda v: order[v["video_id"]])
    # CF-0582: the request's natures - over what is the entity's footage.
    kept_out, by_nature = nature_partition(kept_out, s)
    # CF-0817, last (a request that refuses `interview` keeps its own code):
    # somebody else's host is not our backdrop - a podcast, an
    # interview, a talk show... leaves here whatever its origin, unless the
    # title names the person this search is about: a `kind: person` entity
    # (the uncovered anchor is about them - Danny Vermette's own interview for
    # backrooms) or the person a feed upload was kept for; else the topic's
    # own subject person (`host_show.subject_person`). A scene is the work's
    # own cut and has no such person.
    def _person_of(v):
        if as_person.get(v["video_id"]):
            return as_person[v["video_id"]]
        return s["entity"] if s.get("kind") == KIND_PERSON else None

    kept_out, host_shows = host_show.partition(
        kept_out, lambda v: fc.classify_with_source(v, config),
        lambda v: footage_origin.is_official(v, config), title_ref=title_ref,
        person_of=_person_of)
    return kept_out, (dropped + unofficial + too_long + not_footage
                      + by_nature + host_shows)


def entity_candidates(videos, s, config=None):
    """One search's surviving videos -> candidate records, round-robin across
    natures as the footage pass orders them."""
    config = footage_origin._require(config)
    groups = fc.group_videos(videos, sieve_name(s), config)
    by_nature = {}
    for g in groups:
        by_nature.setdefault(g["nature"], []).append(g)
    for gs in by_nature.values():
        gs.sort(key=lambda g: (footage_origin.rank(g["videos"][0], config),
                               -(g["videos"][0].get("view_count") or 0)))

    def rank(n):
        return fc.NATURE_ORDER.index(n) if n in fc.NATURE_ORDER else len(fc.NATURE_ORDER)

    out = []
    for natures in (sorted((n for n in by_nature if n not in fc.TAIL_NATURES), key=rank),
                    sorted((n for n in by_nature if n in fc.TAIL_NATURES), key=rank)):
        i = 0
        while any(i < len(by_nature[n]) for n in natures):
            for n in natures:
                if i < len(by_nature[n]):
                    g = by_nature[n][i]
                    c = fc._candidate(g, i, len(by_nature[n]), config)
                    c = {"video_id": c["video_id"],
                         "entity": g["videos"][0].get("as_person") or s["entity"],
                         "nature": c["nature"], "origin": c["origin"],
                         fc.DURATION_KEY: c[fc.DURATION_KEY], "query": s["query"],
                         **({"source": s["source"]} if s.get("source") else {}),
                         "kind": c["kind"], "title": c["title"],
                         "channel_title": c["channel_title"],
                         "view_count": c["view_count"], "facets": c["facets"],
                         "why": c["why"],
                         # CF-0817: the verdict of a host show kept under the
                         # exception (the entity's own interview), else None
                         host_show.HOST_SHOW_KEY: c[host_show.HOST_SHOW_KEY]}
                    out.append(c)
            i += 1
    return out


def _one_pool_record_per_id(dropped):
    out, seen = [], set()
    for d in dropped:
        if d.get("reason_code") == IN_POOL_CODE:
            if d.get("video_id") in seen:
                continue
            seen.add(d.get("video_id"))
        out.append(d)
    return out


def choose(per_search, cap, taken=()):
    """Round-robin across searches (request order) -> at most `cap`
    candidates, each id once; an id in `taken` (the topic's own pass) is
    listed, not offered."""
    chosen, seen, in_pool = [], set(taken), []
    queues = [list(c) for c in per_search]
    while len(chosen) < cap and any(queues):
        for q in queues:
            while q:
                c = q.pop(0)
                if c["video_id"] in seen:
                    if c["video_id"] in taken and c["video_id"] not in {x["video_id"] for x in in_pool}:
                        in_pool.append({"video_id": c["video_id"], "entity": c["entity"],
                                        "reason_code": IN_POOL_CODE})
                    continue
                seen.add(c["video_id"])
                chosen.append(c)
                break
            if len(chosen) >= cap:
                break
    return chosen, in_pool


# --------------------------------------------------------------------------
# filling one request
# --------------------------------------------------------------------------

def _key(query):
    return " ".join(normalise(query).split())


def _item_key(s):
    """What makes one planned search that request's own: whose footage, under
    which query. Used to line the feed reads and the searches back up with the
    entity order the candidates are chosen in."""
    return (s["entity"], s["query"])


def feed_phase(wanted, title_ref, feeds=None, feeder=None, cap=None, limits=None,
               config=None, taken=(), scope=None):
    """The works of this request off the official channels' feeds, before a
    single search call is spent (CF-0369).

    -> `{"by_item", "runs", "unread", "covered", "dropped", "api_units",
    "saved"}`: the candidates per planned search, one accounting row per work
    read, the works nobody read, the works the feeds covered (their searches
    are not planned), the sieve drops, the units the reads cost and the search
    calls they saved.

    `feeds` - `{query: feed signal}` handed in (`fetch_channel_feeds.py`
    output, or the batch's own `work/feeds/feed-<topic>.json`); `feeder` - a
    callable `feed item -> feed signal` for the works no signal covers (None:
    the works are listed unread and go to the search, which is what this stage
    did before CF-0369). Nothing here touches the network by itself.

    CF-0414: `taken` is the topic's pool (`pool_ids`). "Enough" counts the
    candidates left **after** the pool and its same-cut uploads are taken out
    (`split_pool`) - a feed that only gives back what the pool already holds
    covers nothing, and the work's search runs."""
    config = footage_origin._require(config)
    feeds = {_key(k): v for k, v in (feeds or {}).items() if k}
    items = [it for it in (feed_item(s, title_ref) for s in wanted) if it]
    floor = FEED_ENOUGH if not cap else max(1, min(FEED_ENOUGH, cap))
    first = {}
    for it in items:
        first.setdefault(_key(it["work"]), it)
    signals, runs, unread, dropped, units, covered_keys = {}, [], [], [], 0, set()
    for key, it in first.items():
        sig = feeds.get(key)
        if sig is None and feeder is not None:
            try:
                sig = feeder(it)
            except Exception as exc:  # noqa: BLE001 - a dead feed is not a refusal
                unread.append({"work": it["work"], "entity": it["entity"],
                               "reason_code": FEEDS_FAILED_CODE, "reason": str(exc)[:300],
                               "command": feed_command(it)})
                continue          # the work keeps its search, and why is written down
        if sig is None:
            unread.append({"work": it["work"], "entity": it["entity"],
                           "reason_code": FEEDS_UNREAD_CODE,
                           "reason": "the feeds of this work were not read; its footage is "
                                     "looked for with the search instead (CF-0369)",
                           "command": feed_command(it)})
            continue
        videos = sig.get("videos") or []
        kept, gone = sieve(videos, it, limits, config, title_ref=title_ref, scope=scope)
        fresh, pooled = split_pool(kept, taken, sieve_name(it), config)
        for d in gone + pooled:
            d.setdefault("entity", it["entity"])
            d["query"] = it["work"]
            d["source"] = FEED_SOURCE
        dropped += gone + pooled
        signals[key] = fresh
        new = len(fc.group_videos(fresh, sieve_name(it), config))
        # CF-0425: a cached read (the batch's own `work/feeds/feed-<topic>.json`)
        # spends nothing now; what it once cost is kept as `api_units_cached`.
        paid = int(sig.get("api_units") or 0)
        spent = 0 if sig.get("cached") else paid
        units += spent
        runs.append({**feed_row(it), "source": sig.get("source") or FEED_SOURCE,
                     "api_units": spent,
                     **({"cached": True, "api_units_cached": paid} if sig.get("cached") else {}),
                     "read_from": sig.get("read_from"),
                     "feed_entries_seen": sig.get("feed_entries_seen"),
                     "videos_seen": len([v for v in videos if v.get("video_id")]),
                     "kept": len(kept), "in_pool": len(pooled), "new_candidates": new,
                     "enough": new >= floor, "enough_floor": floor})
        if new >= floor:
            covered_keys.add(key)
    covered = [it["work"] for key, it in first.items() if key in covered_keys]
    by_item, saved = {}, 0
    for s, it in zip([x for x in wanted if feed_work_of(x)], items):
        kept = signals.get(_key(it["work"]))
        if not kept:
            continue
        by_item[_item_key(s)] = entity_candidates(kept, it, config)
        if it["work"] in covered:
            saved += int(s.get("searches") or 0)
    return {"by_item": by_item, "runs": runs, "unread": unread, "covered": covered,
            "dropped": dropped, "api_units": units, "saved": saved}


def fill(req, title_ref, signals=None, searcher=None, remaining=None, limits=None,
         topic=None, config=None, feeds=None, feeder=None, pool=(), narration=None,
         narration_source=None):
    """Fill `req["candidates"]` and `req["search"]`; -> (req, calls_spent).

    `signals` - `{normalised query: fetch output}` handed in; `searcher` - a
    function `plan item -> fetch output` for the searches no signal covers
    (None: those stay unrun and are listed). `feeds` / `feeder` are the same
    two for the feed phase, which runs first and costs no search call
    (CF-0369). Nothing here touches the network by itself.

    `calls_spent` counts `search.list` calls only: the feed reads spend units,
    and those are in `req["search"]["feed_api_units"]`.

    `pool` (CF-0414, `pool_ids`) - the ids the topic's pool already holds,
    beside the topic's own `evidence.youtube_video_ids`: they and their
    same-cut uploads are never offered, and a feed read is "enough" only on
    what is left after them.

    `narration` (CF-0426 rule 4, `narration_of`) - the narrator's text of the
    topic's script; with the request's own anchors' `beat_text` it decides
    which works of the topic's franchise are the topic's frames
    (`topic_scope`)."""
    config = footage_origin._require(config)
    signals = signals or {}
    scope = topic_scope(req, title_ref, narration)
    attempts = req.get("max_attempts")
    if not (isinstance(attempts, int) and not isinstance(attempts, bool) and attempts > 0):
        attempts = DEFAULT_MAX_ATTEMPTS
    cap = attempts * CANDIDATE_SLACK
    taken = set(((topic or {}).get("evidence") or {}).get("youtube_video_ids") or [])
    taken |= set(pool or ())
    wanted, _ = wanted_searches(req, title_ref, scope=scope, topic=topic)
    ph = feed_phase(wanted, title_ref, feeds, feeder, cap, limits, config, taken=taken,
                    scope=scope)
    p = plan(req, title_ref, remaining, covered=ph["covered"], narration=narration,
             topic=topic)
    by_search, dropped, runs, unrun, calls = {}, list(ph["dropped"]), [], [], 0
    for s in p["searches"]:
        sig = signals.get(_key(s["query"]))
        if sig is None and searcher is not None:
            try:
                sig = searcher(s)
                calls += search_quota.searches_of(sig)
            except Exception as e:  # a failed search is a listed search
                unrun.append({"query": s["query"], "entity": s["entity"],
                              "reason_code": "search_failed", "reason": str(e)[:300]})
                continue
        if sig is None:
            unrun.append({"query": s["query"], "entity": s["entity"],
                          "reason_code": "not_searched",
                          "command": " ".join(repr(a) if " " in a else a
                                              for a in command(s)[1:])})
            continue
        videos = sig.get("videos") or []
        kept, gone = sieve(videos, s, limits, config, title_ref=title_ref, scope=scope)
        kept, pooled = split_pool(kept, taken, sieve_name(s), config)
        for d in gone + pooled:
            d.setdefault("entity", s["entity"])
            d["query"] = s["query"]
        dropped += gone + pooled
        cands = entity_candidates(kept, s, config)
        by_search[_item_key(s)] = cands
        runs.append({"entity": s["entity"], "kind": s["kind"], "query": s["query"],
                     "facets": s["facets"], "searches": search_quota.searches_of(sig),
                     # CF-0824: what the channel's search cache answered of it
                     **({"cached_searches": search_quota.cached_of(sig)}
                        if search_quota.cached_of(sig) else {}),
                     **({"bare": False} if s.get("bare") is False else {}),
                     "videos_seen": len([v for v in videos if v.get("video_id")]),
                     "kept": len(cands)})
    # Round-robin across the entities in request order, the feeds of an entity
    # before its search (CF-0369): the feed clip of a work is the cheaper and
    # the more official of the two.
    per_source = []
    for s in wanted:
        key = _item_key(s)
        for got in (ph["by_item"].get(key), by_search.get(key)):
            if got:
                per_source.append(got)
    chosen, in_pool = choose(per_source, cap, taken)
    # One in-pool record per id, however many feeds and searches brought it.
    dropped = _one_pool_record_per_id(dropped + in_pool)
    in_pool = []
    for c in chosen:
        assert not any(c.get(k) for k in INDEXER_DROP_KEYS)
    req["candidates"] = chosen
    req[BLOCK] = {
        "task": TASK, "rule": RULE,
        "title_ref": (title_ref or {}).get("name"),
        "narration": {"read_from": narration_source if narration else None,
                      "anchors_beat_text": sum(1 for a in req.get("anchors") or []
                                               if isinstance(a, dict) and a.get("beat_text")),
                      "franchise_named": scope["franchise_named"],
                      "franchise_unnamed": scope["franchise_unnamed"]},
        "days": SUPPLEMENT_DAYS, "candidate_cap": cap,
        "feeds_rule": FEEDS_RULE,
        "feeds": ph["runs"], "feeds_unread": ph["unread"],
        "feeds_covered": ph["covered"],
        "feed_api_units": ph["api_units"],
        "search_calls_saved_by_feeds": ph["saved"],
        "search_budget": p["budget"], "searches_planned": p["planned"],
        "searches": runs, "searches_unrun": unrun,
        "searches_skipped": p["skipped"],
        "entities_skipped": p["entities_skipped"],
        "candidates_dropped": dropped + in_pool,
        "scene": scene_report(wanted, p, runs, unrun, chosen),
        "natures": natures_report(req, dropped),
    }
    return req, calls


def scene_report(wanted, p, runs, unrun, chosen):
    """CF-0582: what the scene entities were searched under - one row per
    scene: its person / moment / work, every query planned, the ones read
    (`searched`), left unrun or over the quota, the videos seen and the
    candidates it gave."""
    out = {}
    for s in wanted:
        if s["kind"] != KIND_SCENE:
            continue
        row = out.setdefault(s["entity"], {
            "entity": s["entity"], "person": s.get("person"), "moment": s.get("moment"),
            "work": s.get("work"), "queries": [], "searched": [], "unrun": [],
            "over_quota": [], "videos_seen": 0, "kept": 0, "candidates": 0,
            "natures_wanted": s.get("natures_wanted") or [],
            "natures_refused": s.get("natures_refused") or []})
        row["queries"].append(s["query"])
    for r in runs:
        row = out.get(r["entity"]) if r.get("kind") == KIND_SCENE else None
        if row is not None:
            row["searched"].append(r["query"])
            row["videos_seen"] += r.get("videos_seen") or 0
            row["kept"] += r.get("kept") or 0
    for u in unrun:
        if u.get("entity") in out and u.get("query") in out[u["entity"]]["queries"]:
            out[u["entity"]]["unrun"].append(u["query"])
    for k in p.get("skipped") or []:
        if k.get("kind") == KIND_SCENE and k.get("entity") in out:
            out[k["entity"]]["over_quota"].append(k["query"])
    for c in chosen:
        if c.get("entity") in out:
            out[c["entity"]]["candidates"] += 1
    return list(out.values())


def natures_report(req, dropped):
    """CF-0582: the request's natures and how many uploads they cost - None
    for a request that names none."""
    wanted, refused = request_natures(req)
    if not (wanted or refused):
        return None
    codes, by_nature = {}, {}
    for d in dropped:
        if d.get("reason_code") in NATURE_CODES:
            codes[d["reason_code"]] = codes.get(d["reason_code"], 0) + 1
            by_nature[d.get("nature")] = by_nature.get(d.get("nature"), 0) + 1
    return {"wanted": list(wanted), "refused": list(refused),
            "applies_to": list(NATURE_KINDS) + ["feeds of the work"],
            "dropped_total": sum(codes.values()), "dropped": codes,
            "dropped_by_nature": by_nature}


# --------------------------------------------------------------------------
# CLI (called from footage_candidates.py --supplement)
# --------------------------------------------------------------------------

def _write_json(path, doc):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _quota(batch_dir, before):
    """-> (batch doc or None, its settled quota block)."""
    batch = None
    path = Path(batch_dir) / BATCH_FILE if batch_dir else None
    if path and path.is_file():
        try:
            batch = json.load(open(path))
        except ValueError:
            batch = None
    block = search_quota.quota_block(batch)
    search_quota.settle(block, batch_dir, before)
    return batch, block


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="footage_candidates.py --supplement",
                                 description="CF-0343: fill a thin pool's supplement "
                                             "request with footage of its entities")
    ap.add_argument("--supplement", required=True, action="append", metavar="REQUEST",
                    help="a request file or a supplement-requests/ directory; repeatable")
    ap.add_argument("--signal", action="append", default=[],
                    help="a fetch_youtube_signal.py output for one planned query "
                         "(bound by its `query`)")
    ap.add_argument("--plan", action="store_true",
                    help="print the searches the requests need, and stop")
    ap.add_argument("--search", action="store_true",
                    help="run the planned searches no --signal covers "
                         "(fetch_youtube_signal.py, YOUTUBE_API_KEY)")
    ap.add_argument("--feeds", action="store_true",
                    help="read the entity works off the official channels' feeds first "
                         "(fetch_channel_feeds.py; 0 search calls). On by default with "
                         "--search (CF-0369)")
    ap.add_argument("--no-feeds", action="store_true",
                    help="do not read any feed: every entity goes to the search, as "
                         "before CF-0369")
    ap.add_argument("--feed-signal", action="append", default=[], metavar="FILE",
                    help="a fetch_channel_feeds.py output for one work (bound by its "
                         "`query`); repeatable. The batch's own work/feeds/feed-<topic>.json "
                         "is read without asking")
    ap.add_argument("--feed-pages", type=int, default=FEED_PAGES, metavar="N",
                    help=f"uploads-playlist pages per deep channel of a feed read "
                         f"(default {FEED_PAGES}; 0 = RSS only, no key, no units)")
    ap.add_argument("--write", action="store_true", help="write the filled request in place")
    ap.add_argument("--title", default=None,
                    help="the topic's work, when the batch holding the request is not readable")
    ap.add_argument("--searches-spent", type=int, default=None, metavar="N",
                    help="search.list calls this quota day spent outside the batch's run log")
    args = ap.parse_args(argv)

    signals = {}
    for f in args.signal:
        sig = json.load(open(f))
        signals[_key(sig.get("query") or "")] = sig
    # CF-0369: the feeds are the first source of a work's footage. Reading them
    # is network, so it is asked for - with --search (the flag that already
    # means "you may call YouTube") or with --feeds - and one Reader serves the
    # whole run, so every channel's feed is fetched once however many requests
    # are filled.
    handed_feeds = {}
    for f in args.feed_signal:
        sig = json.load(open(f))
        if sig.get("query"):
            handed_feeds[sig["query"]] = dict(sig, read_from=str(f))
    use_feeds = (args.feeds or args.search) and not args.no_feeds and not args.plan
    reader = feed_reader() if use_feeds else None
    status = 0
    for arg in args.supplement:
        for path in request_paths(arg):
            try:
                req = load_request(path)
            except (ValueError, OSError) as e:
                print(f"{path}: refused - {e}", file=sys.stderr)
                status = 2
                continue
            bdir = batch_dir_of(path)
            topic = topic_of(bdir, req["topic_id"])
            ref = title_ref_of(req, topic, args.title)
            narration = narration_of(bdir, req["topic_id"])
            batch, block = _quota(bdir, args.searches_spent)
            remaining = block.get("remaining_searches")
            if args.plan:
                p = plan(req, ref, remaining, narration=narration, topic=topic)
                for s in p["searches"]:
                    s["command"] = command(s)[1:]
                print(json.dumps({"topic_id": req["topic_id"], **p},
                                 ensure_ascii=False, indent=2))
                continue
            limits = fc.channel_ceiling(fc._batch_channel(batch or {}))
            # CF-0627: the official channels are the batch's channel's list.
            try:
                origin = footage_origin.load_config(fc._batch_channel(batch or {}))
            except footage_origin.ConfigError as e:
                print(f"{path}: refused - {e}", file=sys.stderr)
                status = 2
                continue
            # The batch's own feed read of this topic (CF-0361) costs nothing to
            # reuse and is taken whatever the flags say.
            feeds = {**batch_feeds(bdir, req["topic_id"]), **handed_feeds}
            feeder = (make_feeder(reader, pages=args.feed_pages, limits=limits,
                                  config=origin)
                      if use_feeds else None)
            req, calls = fill(req, ref, signals, run_search if args.search else None,
                              remaining, limits, topic, config=origin, feeds=feeds,
                              feeder=feeder,
                              pool=pool_ids(bdir, req["topic_id"], topic),
                              narration=narration,
                              narration_source=(str(Path(bdir) / NARRATION_FILE)
                                                if narration else None))
            units =int((req.get(BLOCK) or {}).get("feed_api_units") or 0)
            # CF-0824: the searches the cache answered - no call, own ledger
            cached = sum(int(r.get("cached_searches") or 0)
                         for r in (req.get(BLOCK) or {}).get("searches") or [])
            if (calls or units or cached) and batch is not None:
                # CF-0368: two articles, because two currencies. The searches
                # are the supplement's own; the feed reads it made first
                # (CF-0369) are `playlistItems`/`videos`/`channels` and belong
                # to the feeds' row, which the day's 100-call cap never sees.
                tid = req["topic_id"]
                search_quota.charge(block, f"supplement:{tid}",
                                    search_quota.ARTICLE_SUPPLEMENT, searches=calls,
                                    cached=cached)
                search_quota.charge(block, f"supplement-feeds:{tid}",
                                    search_quota.ARTICLE_FEEDS, api_units=units)
                search_quota.settle(block, bdir, args.searches_spent)
                batch[search_quota.QUOTA_KEY] = block
                _write_json(Path(bdir) / BATCH_FILE, batch)
            if args.write:
                _write_json(path, req)
            else:
                print(json.dumps(req, ensure_ascii=False, indent=2))
            b = req[BLOCK]
            print(f"{path.name}: {len(req['candidates'])} candidate(s) for "
                  f"{req['topic_id']} (cap {b['candidate_cap']}), "
                  f"{len(b['feeds'])} feed read(s) of {len(b['feeds']) + len(b['feeds_unread'])} "
                  f"work(s) ({b['feed_api_units']} api unit(s), "
                  f"{b['search_calls_saved_by_feeds']} search call(s) saved), "
                  f"{len(b['searches'])} search(es) read, {calls} call(s) spent, "
                  f"{len(b['searches_unrun'])} unrun, {len(b['searches_skipped'])} over "
                  f"quota, {len(b['entities_skipped'])} entity(ies) skipped, "
                  f"{len(b['candidates_dropped'])} dropped; "
                  + search_quota.line(block), file=sys.stderr)
            # CF-0368: what the day went on, by article, and the line the
            # root's RUN_SUMMARY carries.
            if block.get("summary_line"):
                print("  " + block["summary_line"], file=sys.stderr)
                for row in search_quota.article_lines(block):
                    print(row, file=sys.stderr)
                search_quota.record_event(block, runlog=runlog, batch_dir=bdir,
                                          step="footage-supplement")
            for f in b["feeds"]:
                print(f"  feeds  {f['work']!r}: {f['kept']} upload(s) off "
                      f"{f['feed_entries_seen']} feed entry(ies), {f.get('in_pool', 0)} "
                      f"already in the pool, {f.get('new_candidates', f['kept'])} new "
                      f"candidate(s) - "
                      + ("enough - no search spent on it"
                         if f["enough"] else "thin - the search takes over"),
                      file=sys.stderr)
            for f in b["feeds_unread"]:
                print(f"  feeds  {f['work']!r}: {f['reason_code']}", file=sys.stderr)
            for e in b["entities_skipped"]:
                print(f"  skipped {e['entity']!r}: {e['reason_code']}", file=sys.stderr)
            for sc in b.get("scene") or []:
                print(f"  scene  {sc['entity']!r}: {len(sc['searched'])} of "
                      f"{len(sc['queries'])} quer(ies) read ("
                      + "; ".join(repr(q) for q in sc["queries"])
                      + f"), {sc['videos_seen']} video(s) seen, {sc['candidates']} "
                      f"candidate(s)", file=sys.stderr)
            if b.get("natures"):
                n = b["natures"]
                print(f"  natures wanted {n['wanted']} refused {n['refused']}: "
                      f"{n['dropped_total']} candidate(s) dropped by nature"
                      + (f" ({', '.join(f'{k} {v}' for k, v in sorted(n['dropped'].items()))})"
                         if n["dropped"] else ""), file=sys.stderr)
            if not req["candidates"]:
                why = empty_reason(b)
                print(f"  no candidates for {req['topic_id']}: {why}", file=sys.stderr)
                if searches_all_failed(b):
                    status = max(status, 1)
    return status


def searches_all_failed(block):
    """CF-0414: the one way a filled request is a tool failure rather than an
    answer - searches were run for it and every one of them raised
    (`search_failed`), none was read. The root's step reads the same thing off
    the request (`shared/runlog/supplement.py::_hunter_failed`)."""
    failed = [u for u in block.get("searches_unrun") or []
              if u.get("reason_code") == "search_failed"]
    return bool(failed) and not block.get("searches")


def empty_reason(block):
    """One line on why a filled request has no candidates - read off the
    request itself, which says it in full."""
    parts = []
    if block.get("searches"):
        parts.append(f"{len(block['searches'])} search(es) read")
    for code in ("search_failed", "not_searched"):
        n = sum(1 for u in block.get("searches_unrun") or [] if u.get("reason_code") == code)
        if n:
            parts.append(f"{n} {code}")
    n = len(block.get("searches_skipped") or [])
    if n:
        parts.append(f"{n} search(es) skipped")
    n = len(block.get("entities_skipped") or [])
    if n:
        parts.append(f"{n} entity(ies) skipped")
    codes = {}
    for d in block.get("candidates_dropped") or []:
        codes[d.get("reason_code")] = codes.get(d.get("reason_code"), 0) + 1
    if codes:
        parts.append("dropped " + ", ".join(f"{v} {k}" for k, v in sorted(codes.items())))
    return "; ".join(parts) or "nothing to search for"
