#!/usr/bin/env python3
"""`evidence.youtube_video_ids` as a *pool* - at least three candidate sources
per topic, of different kinds (CF-0129, DoD 1.4.4 item 2).

Why this script exists. The two-source gate asks for two *independent*
sources per video, and independence is decided after download, by the CF-0080
fingerprint - three uploads of one teaser are one source (2026-09-03:
`GyEpwGQIEZw` / `SJVmeJaS44s`, distance 1.82), which is how the batch of
2026-09-03T2037Z passed the gate on 0 of 4 videos. Discovery cannot check a
fingerprint before downloading, so the only thing it can do is hand the
indexer **three candidates that are not the same cut**: a second trailer, a
press interview, an episode clip, a making-of. The indexer (`ingest_batch.py`,
part 2 of CF-0129) then downloads down this list until two canonical sources
survive deduplication, at most four attempts, and refuses the topic with
`no_second_source` if they do not.

What this script does, mechanically, over one topic's footage search
(`fetch_youtube_signal.py --facets`, see FOOTAGE_FACETS there):

  0. drops the uploads that **do not name the topic's work** anywhere in their
     own metadata (`topic_relevance.py`, CF-0272) - the search answers a query
     through the channel and the network as readily as through the words, and
     on "Wren Hollow" that put two Example Max promos for *Harbourlights* (2.5M / 2.1M
     views) at the head of the list in two batches running. They are recorded
     in `evidence.footage_candidates_dropped` with `wrong_work`, and because
     the drop happens here - before grouping, before ranking - the next real
     candidate moves up into the slot instead of the topic losing one;
  0a. drops the uploads whose **own title names the work only by the
     franchise's stem or parent** - another installment (CF-0444,
     `topic_relevance.installment_forms`, the same forms the indexer's pool
     check asks, CF-0325). Batch 2026-09-29T0705Z gave Vanguards: Doomsday the
     candidate list of Vanguards: Endgame through the stem "Vanguards", and the
     frame judge was the first to notice. Recorded with `other_installment`;
     and two topics that still end with one set of ids are written to the
     batch's `footage_candidates_shared` and printed as a WARNING;
  0b. drops the uploads that are somebody's video **about** the work rather
     than footage of it (`footage_origin.py`, CF-0297) - a fan concept
     trailer, a game capture, an edit, a reaction, a parody, a short-form
     repost, a podcast. The batch of 2026-09-19T0116Z handed the indexer four
     of those as canonical sources and lost four topics of five at the frame
     judge, with a two-source gate formally passed. They are recorded in
     `evidence.footage_candidates_dropped` with `unofficial_source`, in the
     same place and for the same reason as the `wrong_work` drops above;
  0c. drops the uploads that are **longer than the ceiling their nature is
     held to** (CF-0302) - the batch of 2026-09-21T0358Z offered a 2 h 14 min
     news podcast with 46 views as a `trailer`, because "Trailer" was in its
     title; the indexer downloaded it, spent the topic's attempt budget and
     lost the topic. The length comes free with the search
     (`fetch_youtube_signal.py` reads `contentDetails.duration`), the ceiling
     from `channels/<id>.json` -> `sources.youtube.max_source_duration_seconds`,
     and the drop is recorded with `source_too_long` and the measured length
     beside the other two. An upload nobody measured is never dropped;
  0d. drops the uploads whose **own title says they are a talk about the work**
     rather than a cut of it (`footage_sieve.py`, CF-0309) - a news round-up
     naming three other works, a press outlet's junket interview, a title made
     of hashtags, a title that never names the work at all, a reupload
     claiming "official". The batch of 2026-09-21T1541Z offered thirteen of
     those to the indexer, which paid for every one of them - the download,
     ~6 min of indexing per minute of source, the shot describer - and lost
     four topics because their good candidates ran out before the attempts
     did. Recorded with `not_the_works_footage` beside the other three;
  0e. drops the uploads that are a **host show** - a podcast, an interview, a
     talk show, a press junket, a roundtable, a reaction, a review
     (`host_show.py`, CF-0817) - **whatever their origin**, after 0b-0d: the
     Reel vanguards-doomsday ran 16 of 16 clips out of Zenith's own official
     podcast, and a viewer called it stolen. Recorded with `host_show` and the
     verdict (`host_show` on the record); one exception - the topic is about
     the person the title names - keeps the candidate with its verdict on it;
  1. classifies every video by the **nature of the footage** from its title,
     then its room and channel, and only then the head of its description
     (CF-0577; trailer / teaser / episode clip / interview /
     featurette / promo / commentary), and by its **origin** - `official` when
     the channel is a studio's, a streamer's, a network's or a distributor's,
     else `unknown`. The origin is written on every candidate record and
     orders the uploads inside each nature, official first (CF-0297);
  2. collapses uploads that look like *the same cut* - same nature, same
     title core once the topic's own words and the upload noise ("official",
     "HD", "4K", the year) are stripped - into one group with one
     representative, the official channel's upload first and the most-viewed
     after. This is the part that stops "three candidates" from being three
     reuploads of one trailer; it is a metadata heuristic and not a
     fingerprint, so it catches reuploads that kept the title and leaves the
     rest to CF-0080 downstream;
  3. orders the groups by round-robin across natures, so that the first two
     ids the indexer tries are of different natures rather than two cuts of
     one trailer;
  4. writes `evidence.youtube_video_ids` (ordered, at most
     FOOTAGE_CANDIDATE_MAX) and the parallel `evidence.footage_candidates` -
     one record per id, saying what the upload is and why it was kept;
  5. when fewer than FOOTAGE_CANDIDATE_FLOOR survive, or they are all of one
     nature, writes `evidence.footage_candidate_shortfall` with the counts -
     how many videos were seen, how many collapsed as the same cut, how many
     natures there were. A thin topic is thin **in the artifact**; it never
     looks like a topic nobody looked for;
  6. when fewer than CANDIDATE_REFUSAL_FLOOR candidates survive all four
     sieves, the topic is refused by this stage: it leaves `topics[]` and
     becomes a `skipped_topics[]` record with `reason_code: "no_source"` - the
     vocabulary of the root funnel (`shared/runlog/funnel.py` FUNNEL_CODES,
     CF-0232), so the loss is counted rather than silent. Until CF-0309 this
     was "nothing filmable at all"; one candidate is the same refusal one step
     later and five hours more expensive, because the two-source gate cannot
     be passed by one source however good it is.

Usage (from the agent root, after the batch file has its topics):
  scripts/footage_candidates.py <batch-dir|01-trend-hunter.json> \\
      --signal /tmp/footage-<slug>.json ... --write      # fill in place
  scripts/footage_candidates.py <batch-dir|file> --check  # validate only
  scripts/footage_candidates.py --supplement <batch>/work/supplement-requests/ \\
      [--plan | --signal ... | --search] --write           # CF-0343, footage_supplement.py
      # the entity works come off the official channels' feeds first (CF-0369):
      # --feeds / --no-feeds / --feed-signal <fetch_channel_feeds.py output>
      # exit 0 = every request answered (an empty one too), 1 = a request's
      # searches all failed, 2 = an unreadable request (CF-0414)

Each `--signal` file is one `fetch_youtube_signal.py --facets` output; it is
bound to a topic by its `query` against `title_ref.name`, or explicitly with
`--signal <file>:<topic_id>`.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _runlog import runlog  # noqa: E402
import _channel_ids  # noqa: E402
import _footage_licence  # noqa: E402
import _own_graphic  # noqa: E402  - CF-0689
import _sentences  # noqa: E402  - CF-0737
import footage_origin  # noqa: E402
import footage_sieve  # noqa: E402
import host_show  # noqa: E402  - CF-0817
import own_capture_text  # noqa: E402  - CF-0567
import api_demo_text  # noqa: E402  - CF-0690
import search_quota  # noqa: E402
from footage_origin import ORIGINS, UNOFFICIAL_CODE  # noqa: E402
from footage_sieve import NOT_FOOTAGE_CODE  # noqa: E402
from host_show import HOST_SHOW_CODE, HOST_SHOW_KEY  # noqa: E402  - CF-0817
from topic_relevance import (  # noqa: E402
    OTHER_INSTALLMENT_CODE, WRONG_WORK_CODE, check_exclusions, installment_forms,
    is_story, partition, partition_other_installment, work_forms)

# The floor this task exists to make a property of the stage rather than of
# luck: three candidate ids per topic. Two is what the gate needs *after*
# deduplication (funnel.TWO_SOURCE_FLOOR), and the third is the one that pays
# for a collapse - on 2026-09-03 every topic had exactly one surviving cut.
FOOTAGE_CANDIDATE_FLOOR = 3
# Above this the list stops being a choice and starts being a dump: the
# indexer tries at most four ids per topic (CF-0129 part 2), so six is that
# plus slack for two failed fetches.
FOOTAGE_CANDIDATE_MAX = 6
# At least two natures, or the pool is one cut with extra uploads.
NATURE_FLOOR = 2
# Below this the topic is not thin, it is **refused here** (CF-0309). The
# indexer needs two canonical sources to pass the two-source gate
# (`shared/runlog/funnel.py` TWO_SOURCE_FLOOR) and one candidate cannot
# produce two; carrying it there buys nothing and costs the batch a download,
# ~6 min of indexing per minute of source and the shot describer - the stage
# of 2026-09-21T1541Z ran 5 h 37 min largely on candidates that could not have
# worked. A topic refused here is refused in a second and says why.
CANDIDATE_REFUSAL_FLOOR = 2
# CF-0567, the driver's decision: on a channel whose footage origins name
# `own_capture` (ExampleTech) one own capture meets the floor by itself - it
# is our footage with no rights risk, the editor's two-source gate never
# counts own captures and passes a video made of recordings only, and the
# «демо» pattern is built on the one recording. Vendor quotes alone never
# meet it any differently than before (they are never the base), and on
# every other channel the floor is the count above, unchanged.


# CF-0689 (the user's decision of 12.10): on a channel whose footage origins
# name `own_graphic` (ExampleTech) the base footage is the graphics the
# factory draws itself from the script's facts (root `shared/own_graphic.py`:
# spec card, comparison, price and date, benchmark, timeline, how it works).
# Such a topic needs no pool at all - the Content Researcher lets an
# all-graphic script through coverage and two sources - but every number,
# name and date on a graphic must stand verbatim in a quote of the topic's
# `support_text`. So a topic with too few footage candidates is not refused
# here when its support text holds GRAPHIC_FACT_FLOOR quotable facts: distinct
# sentences of its pieces that carry a figure or a date, read by the root
# rule's own `parse_numbers` / `parse_dates` (the parser the writer's check
# will later hold the graphic's values to).
#
# Three, and not one: an all-graphic Short is several graphics (a hook figure,
# a comparison or a benchmark, a date or a price to land on), each value its
# own verbatim quote; and, as with FOOTAGE_CANDIDATE_FLOOR's third candidate,
# one of them is allowed to fail the claim judge without taking the video
# with it. Conservative on purpose:
#   * a sentence counts once, however many pieces repeat it;
#   * the factory's own `own_capture_record` pieces are never a fact
#     (CF-0567), so they never count - nor its `api_demo_record` pieces
#     (CF-0690: a number in a model's answer is the model's), nor any piece
#     marked `not_a_fact`;
#   * a number glued to a name ("GPT-5", "Llama-3.1") or a version ("2.5.1"),
#     and any number inside the topic's own name ("Gemini 2.5 Pro"), is a
#     name, not a figure;
#   * a "sentence" longer than GRAPHIC_FACT_MAX_CHARS is a table or a list
#     the plain-text article flattened, not a quote anybody can stand on.
# A topic with neither candidates nor quotable facts is refused exactly as
# before; Reel and Science (no `own_graphic` origin) keep the count floor.
# The «демо» pattern is not this floor's: it is chosen by the writer, and its
# own recording is required downstream (the Content Researcher's
# check_demo.py reads `evidence.footage_base.base`, the Video Editor's
# demo_own_capture gate) - a topic kept on graphics has `footage_base.base`
# null and can never be a demo.
GRAPHIC_FACT_FLOOR = 3
GRAPHIC_FACT_MAX_CHARS = 400
GRAPHIC_FACT_EXAMPLES = 5
GRAPHIC_FOOTING_KEY = "own_graphic_footing"
# The factory's own records in `support_text` - never a fact, never counted:
# what was recorded (CF-0567) and what a model answered through its API
# (CF-0690: a number in the model's answer is the model's, not the story's).
NOT_A_FACT_KINDS = (own_capture_text.KIND, api_demo_text.KIND)
_NAME_NUMBER_RE = re.compile(r"(?<=[A-Za-z])[-‐‑]?\d+(?:\.\d+)*(?![\d%])|"
                             r"(?<![\d.,])\d+(?:\.\d+){2,}")


def _topic_names(topic):
    """The topic's own names (`title_ref.name` / `tool` / `model`, the
    title): a number inside them names the thing, it is no figure of it."""
    ref = topic.get("title_ref") if isinstance(topic.get("title_ref"), dict) else {}
    names = [ref.get(k) for k in ("name", "tool", "model")] + [topic.get("title")]
    return sorted({n.strip() for n in names if isinstance(n, str) and n.strip()},
                  key=len, reverse=True)


def _figures(sentence, lib, names=()):
    """The figures of one sentence: numbers the root rule reads, after the
    topic's own names and the numbers glued to a name or a version are taken
    out."""
    masked = sentence
    for name in names:
        masked = re.sub(re.escape(name), " ", masked, flags=re.I)
    masked = _NAME_NUMBER_RE.sub(" ", masked)
    return [bare for bare, _ in lib.parse_numbers(masked) if re.fullmatch(r"\d+(?:\.\d+)?", bare)]


def quotable_facts(pieces, lib=None, names=()):
    """-> [{"piece", "quote"}] of a topic's support text: every distinct
    sentence (of a piece that is not the factory's own capture record) that
    carries a figure or a date; `names` are the topic's own names, whose
    numbers are no figures. [] without the root rule."""
    lib = lib if lib is not None else _own_graphic.own_graphic
    if lib is None:
        return []
    out, seen = [], set()
    for piece in pieces or []:
        if not isinstance(piece, dict) or piece.get("kind") in NOT_A_FACT_KINDS \
                or piece.get("not_a_fact") is True:
            continue
        # CF-0737: never at an abbreviation's stop («Example Studios»)
        for sentence in _sentences.split_sentences(str(piece.get("text") or "")):
            sentence = " ".join(sentence.split())
            if not sentence or len(sentence) > GRAPHIC_FACT_MAX_CHARS:
                continue
            key = sentence.casefold()
            if key in seen:
                continue
            if lib.parse_dates(sentence) or _figures(sentence, lib, names):
                seen.add(key)
                out.append({"piece": piece.get("id"), "quote": sentence})
    return out


# CF-0809 (batch example-tech/2026-10-19T0844Z, topic 005): the news was the NEW
# Tesla Roadster, the probe resolved "Tesla Roadster (first generation)" - the
# 2008-12 car - and its 215 sentences with a figure kept the topic on own
# graphics, facts about another car (CF-0263: the article must be about the
# thing itself). So a Wikipedia piece whose title is qualified by an EDITION
# of the thing - "(first generation)", "(2nd generation)", "(gen 2)",
# "(original)", a year "(2008)" / "(1999 film)" - gives no quotable fact unless
# that edition is the news's:
#   * the topic's own text names the qualifier's marker (title_ref name / year,
#     its title, its scene descriptions, its news pieces - rss / vendor), or
#   * the edition is current: the qualifier's year, or the newest year the
#     article names at least twice (one stray "In November 2023, ..." does not
#     make an article about 2008-12 an article about today), is no older than
#     EDITION_RECENT_YEARS before the batch's year.
# A qualifier that names no edition ("(language model)", "(TV series)",
# "(smartphone)") and an unqualified title are the thing itself and count as
# before. Only the count changes: the support text and the probe's facts stay
# where they are; the pieces set aside are listed on the footing
# (`other_subject[]`) and in its note, which the refusal row quotes.
EDITION_RECENT_YEARS = 1
_ORDINAL_WORDS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh",
                  "eighth", "ninth", "tenth")
_QUALIFIED_TITLE_RE = re.compile(r"^(?P<base>.*\S)\s*\((?P<qual>[^()]+)\)\s*$")
_EDITION_MARKER_RE = re.compile(
    r"\b(?:(?:" + "|".join(_ORDINAL_WORDS) + r"|\d+(?:st|nd|rd|th))[\s\-‐‑]+generation"
    r"|generation[\s\-‐‑]*\d+|gen[\s\-‐‑]*\d+|original|(?:19|20)\d\d)\b", re.I)
_YEAR_RE = re.compile(r"(?<!\d)(?:19|20)\d\d(?!\d)")
OWN_TEXT_KINDS = ("rss_summary", "vendor_page")   # = support_text.KIND_RSS / KIND_VENDOR


def _plain(text):
    """Lower case, hyphens and punctuation as spaces - "first-generation" and
    "First generation" are one marker."""
    return " ".join(re.sub(r"[^\w]+", " ", str(text or "").casefold()).split())


def _topic_own_text(topic):
    """What the topic itself says it is about: its `title_ref`, its title,
    its scene descriptions and its news pieces - never the article."""
    ref = topic.get("title_ref") if isinstance(topic.get("title_ref"), dict) else {}
    parts = [ref.get(k) for k in ("name", "tool", "model", "year", "season", "parent_work")]
    parts.append(topic.get("title"))
    parts += [s.get("description") for s in topic.get("scenes") or [] if isinstance(s, dict)]
    parts += [p.get("text") for p in topic.get(SUPPORT_KEY) or []
              if isinstance(p, dict) and p.get("kind") in OWN_TEXT_KINDS]
    return " " + _plain(" ".join(str(p) for p in parts if p not in (None, ""))) + " "


def batch_year(topic):
    """The year the topic was asked about (its probe's `asked_at`, else its
    support pieces' revision), None when nothing says."""
    for stamp in ([(topic.get("fact_probe") or {}).get("asked_at")]
                  + [p.get("revised_at") for p in topic.get(SUPPORT_KEY) or []
                     if isinstance(p, dict)]):
        m = re.match(r"((?:19|20)\d\d)-", str(stamp or ""))
        if m:
            return int(m.group(1))
    return None


def other_subject(piece, topic, year=None):
    """-> None when `piece` may give the topic quotable facts; else a record
    of why not: a Wikipedia article about another edition of the thing than
    the topic's news (CF-0809, above)."""
    if not isinstance(piece, dict) or piece.get("source") != "wikipedia":
        return None
    title = str(piece.get("article") or piece.get("title") or "")
    m = _QUALIFIED_TITLE_RE.match(title)
    if not m:
        return None
    qual = m.group("qual").strip()
    markers = [x.group(0) for x in _EDITION_MARKER_RE.finditer(qual)]
    if not markers:
        return None
    own = _topic_own_text(topic)
    if all(f" {_plain(x)} " in own for x in markers):
        return None
    year = year if year is not None else batch_year(topic)
    counts = {}
    for y in _YEAR_RE.findall(str(piece.get("text") or "")):
        counts[int(y)] = counts.get(int(y), 0) + 1
    years = [int(y) for y in _YEAR_RE.findall(qual)] + [y for y, c in counts.items() if c >= 2]
    newest = max(years) if years else None
    if year is not None and newest is not None and newest >= year - EDITION_RECENT_YEARS:
        return None
    unnamed = ", ".join(repr(x) for x in markers if f" {_plain(x)} " not in own)
    when = (f"the newest year it names is {newest}" if newest is not None
            else "it names no year")
    return {"piece": piece.get("id"), "article": title, "qualifier": qual,
            "newest_year": newest, "batch_year": year,
            "reason": (f"article {title!r} is about another edition ({qual}) than the news: "
                       f"the topic's own text does not name {unnamed} and {when}"
                       + (f" (the batch is {year})" if year is not None else "")
                       + " - its sentences are not the news's facts (CF-0263, CF-0809)")}


def subject_facts(topic, lib=None, year=None):
    """-> `(facts, set_aside)`: the topic's quotable facts from the pieces
    about the news's own subject, and `[other_subject record + "facts"]` for
    each piece about another edition, whose sentences are not counted."""
    pieces = topic.get(SUPPORT_KEY)
    if not isinstance(pieces, list):
        return [], []
    names = _topic_names(topic)
    kept, set_aside = [], []
    for piece in pieces:
        other = other_subject(piece, topic, year)
        if other is None:
            kept.append(piece)
        else:
            set_aside.append(dict(other, facts=len(quotable_facts([piece], lib, names))))
    return quotable_facts(kept, lib, names), set_aside


def graphic_footing(topic, config=None, year=None):
    """-> `evidence.own_graphic_footing` of one topic on a channel with the
    `own_graphic` origin (None elsewhere): how many quotable facts its
    support text holds, the floor, whether it meets it, a few of them, and
    a note the funnel and the step-8 report can quote. Pieces about another
    edition of the thing than the news (CF-0809) give none; they are listed
    under `other_subject`."""
    if not footage_origin.has_own_graphic(config):
        return None
    lib = _own_graphic.own_graphic
    pieces = topic.get(SUPPORT_KEY)
    facts, set_aside = subject_facts(topic, lib, year) if lib is not None else ([], [])
    n = len(facts)
    meets = lib is not None and n >= GRAPHIC_FACT_FLOOR
    if lib is None:
        note = ("own graphics: the root rule shared/own_graphic.py was not found - no topic "
                "is kept on its quotable facts, the footage floor alone applies")
    elif not isinstance(pieces, list):
        note = ("own graphics: no support_text yet (step 5a) - nothing to quote, the footage "
                "floor alone applies")
    else:
        note = (f"own graphics: {n} quotable fact(s) (sentences with a figure or a date in "
                f"support_text), floor is {GRAPHIC_FACT_FLOOR}")
        for other in set_aside:
            note += (f"; {other['facts']} sentence(s) of {other['article']!r} not counted: "
                     f"{other['reason']}")
    footing = {"origin": footage_origin.OWN_GRAPHIC, "quotable_facts": n,
               "floor": GRAPHIC_FACT_FLOOR, "meets_floor": meets,
               "examples": facts[:GRAPHIC_FACT_EXAMPLES], "note": note}
    if set_aside:
        footing["other_subject"] = set_aside
    return footing


def meets_refusal_floor(candidates, config=None, footing=None):
    """Whether a topic's candidate list keeps it: CANDIDATE_REFUSAL_FLOOR
    candidates, or - on a channel with the `own_capture` origin only - one
    own capture (CF-0567), or - on a channel with the `own_graphic` origin
    only - a support text with GRAPHIC_FACT_FLOOR quotable facts
    (`footing`, `graphic_footing`; CF-0689)."""
    if len(candidates or []) >= CANDIDATE_REFUSAL_FLOOR:
        return True
    if footage_origin.has_own_capture(config) and any(
            footage_origin.is_own_capture(c) for c in candidates or []):
        return True
    return kept_on_graphics(candidates, config, footing)


def kept_on_graphics(candidates, config=None, footing=None):
    """CF-0689: whether the topic is kept by its quotable facts alone - the
    channel draws its own graphics, the footage floor is not met, and the
    footing meets its floor."""
    return (footage_origin.has_own_graphic(config)
            and bool((footing or {}).get("meets_floor"))
            and (footing or {}).get("quotable_facts", 0) >= GRAPHIC_FACT_FLOOR)


def _own_capture_base(records):
    """`--check`'s reading of the same rule off a written list (no channel
    config at hand): an own capture the channel's licence list judged and
    took as `own_capture`, with `role: base` - which only a channel with the
    `own_capture` origin writes."""
    for r in records or []:
        lic = (r or {}).get(LICENCE_KEY) or {}
        if (isinstance(r, dict) and footage_origin.is_own_capture(r) and r.get("role") == "base"
                and lic.get("judged") and lic.get("accepted") and lic.get("id") == "own_capture"):
            return True
    return False

# `shared/runlog/funnel.py` FUNNEL_CODES - spelled here rather than imported
# for the reason the funnel spells TWO_SOURCE_FLOOR: an agent repo does not
# reach into the root's modules. `no_source` is "no source was registered for
# it and no failure was recorded either", which is exactly a topic discovery
# could find no filmable video for.
REFUSAL_CODE = "no_source"

# CF-0317. The other way a topic can leave this stage without footage
# evidence: the day's YouTube Search quota (100 `search.list` calls, CF-0288)
# will not pay for its facet run. Until this task that was not an outcome at
# all - `fill_batch` kept the topic and recorded a *problem* telling the
# operator to run `--facets` for it, and the only way to obey was to wait for
# the reset. The run `example-film/2026-09-19T0116Z` did exactly that: the
# stage closed at 01:26 with five topics carrying no footage evidence and
# reopened at 07:06, "resumed after the YouTube search quota reset" - 5 h 40 m
# of an autonomous run spent standing in front of somebody else's clock.
# Now the topic leaves `topics[]` with this code and the batch goes on in the
# same minute. The word is the root register's
# (`shared/runlog/no_waiting.py`, `hunter_quota_resume`), spelled here for the
# reason REFUSAL_CODE is: an agent repo does not import the root's modules.
# A second spelling of it would make the record unreadable to
# `no_waiting.classify()`, so this line is the only place it is written.
EVIDENCE_QUOTA_CODE = "footage_evidence_quota"

CANDIDATE_KEYS = ("video_id", "kind", "nature", "origin", "title", "channel_title",
                  "view_count", "duration_seconds", "facets", "same_cut", "why",
                  "licence", "footage_origin",
                  "credit", "source_url", "download_url", "media_type", "bytes", "archive",
                  "channel_id", "role", "capture_file", "capture",
                  # CF-0817: null, or the host-show verdict of a candidate kept
                  # under the exception (`host_show.judge`)
                  "host_show")
# CF-0662: the two keys younger than most written batches - a record without
# them is judged as if they were there (`check_topic`), as `duration_seconds`
# is (CF-0302).
LICENCE_KEY = "licence"
FOOTAGE_ORIGIN_KEY = "footage_origin"
# CF-0665 (TH-3 of the root's docs/science-footage.md): a candidate out of an
# archive (`fetch_archive_footage.py`: the NASA Image and Video Library,
# Wikimedia Commons) is a file the indexer fetches directly (FI-1) - its
# `download_url`, `media_type` (MIME) and `bytes` - with the file's own
# `credit` line (FI-2's `rights.credit`, `credit_from: candidate`), the page it
# was read on (`source_url`) and `archive` (which archive, the item id, the
# rendition, the picture size, the caveats of CF-0564 that apply). A YouTube
# candidate carries them all as null.
ARCHIVE_KEYS = ("credit", "source_url", "download_url", "media_type", "bytes", "archive")
ARCHIVE_KEY = "archive"
ARCHIVE_ID_PREFIXES = ("nasa:", "commons:")
# CF-0567 (TH step of the root's docs/tech-footage.md): every candidate says
# which YouTube channel it is on (`channel_id`, the id the Footage Indexer
# reads `official_channels` by) and the role that channel's entry gives it
# (`role`: `proof_quote` on ExampleTech's vendors - a short quote, never the
# base; null off the list and on the channels whose entries name no role). An
# own capture (`own_capture:<id>`, `fetch_own_capture.py`) carries the
# recording (`capture_file`, the mp4's absolute path), what was recorded and
# how (`capture`: the Space, its page, its licence, the steps played, the
# sidecar) and `role: base` - the «демо» pattern's footage. Null on every
# other candidate.
CAPTURE_KEYS = ("channel_id", "role", "capture_file", "capture")
CAPTURE_FILE_KEY = "capture_file"
CAPTURE_KEY = "capture"
BASE_ROLE = "base"
PROOF_QUOTE_ROLE = footage_origin.PROOF_QUOTE
OWN_CAPTURE_HEAD = footage_origin.OWN_CAPTURE_HEAD
YOUNGER_KEYS = ("duration_seconds", LICENCE_KEY, FOOTAGE_ORIGIN_KEY) + ARCHIVE_KEYS + CAPTURE_KEYS \
    + (HOST_SHOW_KEY,)

# --------------------------------------------------------------------------
# how long a candidate is, and how long it is allowed to be (CF-0302)
# --------------------------------------------------------------------------
# The incident. On 2026-09-21 (`lf-2026-09-21-004`) this stage offered
# `Lv_GOa6HXVA` - "Lakeside Trailer, Example Pictures Leaving California, People
# vs. Gorilla Boss & More - SMALL ZERO", a 2 h 14 min news podcast with 46
# views - as a `trailer` candidate, because the word "Trailer" is in its
# title. The indexer downloaded it and was still splitting shots 41 minutes
# later; the run was killed by hand, the topic's attempt budget was gone, and
# the topic died with `no_second_source` holding a perfectly good first
# source. Nature is read off a title and titles lie; the length does not.
#
# So the length is now read here, where `videos.list` is called anyway
# (`fetch_youtube_signal.duration_seconds`), and an upload longer than the
# ceiling its own nature is held to never becomes a candidate. It leaves the
# pool the way CF-0272's `wrong_work` and CF-0297's `unofficial_source` do -
# before grouping, before ranking, with a record in
# `evidence.footage_candidates_dropped` carrying the measured length - so the
# next real candidate moves up into its slot instead of the topic losing one.
#
# An upload whose length nobody can tell (a live stream, a premiere, a batch
# whose search predates this) is **not** dropped: unknown is not long, and a
# sieve that guessed would be the CF-0272 failure over again. The indexer
# keeps its own copy of this ceiling as a second gate for exactly those
# (`ingest_batch.measure_candidate`, which reads the `duration_seconds` below
# before it asks YouTube anything).
DURATION_KEY = "duration_seconds"

# The code the drop record carries. Like `wrong_work` and `unofficial_source`
# this is one upload leaving one topic's pool, not a topic leaving the batch -
# but it is deliberately spelled the way the funnel spells the indexer's
# refusal (`shared/runlog/funnel.py` SOURCE_TOO_LONG), so that the same loss
# has one name wherever it is read. A topic the ceiling empties is still
# refused with this stage's own `no_source`.
TOO_LONG_CODE = "source_too_long"

# Where the numbers live: `channels/<id>.json`, beside the indexer's
# other source settings and read by the indexer from the same key
# (`ingest_batch.CEILING_KEY`). Either one number for every nature, or
# `{nature: seconds}` with an optional `default`. Nothing there leaves the
# measured defaults below.
CEILING_KEY_PATH = ("sources", "youtube", "max_source_duration_seconds")
CEILING_KEY = ".".join(CEILING_KEY_PATH)
CEILING_DEFAULT_NATURE = "default"

# Measured 2026-09-21 over the 93 accepted sources of the eight written
# batches, not invented (the reasoning is in the CF-0302 task file): 3600 is
# above the longest source that ever reached a finished video (3426 s) and
# below both incidents (4307 s CF-0281, 8019 s CF-0302); 900 for `trailer`
# because that label is put on by a word in a title and the longest trailer
# ever actually used is 501 s. `interview` stays on the default on purpose -
# interviews of up to 3426 s are in finished videos.
DEFAULT_MAX_SOURCE_SECONDS = {CEILING_DEFAULT_NATURE: 3600, "trailer": 900}

# --------------------------------------------------------------------------
# the licence of a candidate (CF-0662, TH-2 of the root's docs/science-footage.md)
# --------------------------------------------------------------------------
# What a candidate may be taken under is the channel's list
# (`channels/<id>/footage-origin.json` `licences`, CF-0564), judged by the
# factory's common rule (`shared/footage_licence.py` `licence_of`, found by
# `_footage_licence.py`). On the YouTube path an upload's licence is one of
# three names, never read off a title or an uploader's name:
#   * `cc by` - YouTube itself says `status.license: creativeCommon` (its CC is
#     CC BY 3.0), written by `fetch_youtube_signal.video_record` as `yt_license`;
#   * `youtube official upload` - a channel of the channel's `official_channels`
#     (by id), under YouTube's standard licence;
#   * `youtube upload` - anyone else, the sieved search candidate.
# An archive's per-file licence (TH-3, not yet written) rides on the record as
# `licence_short_name` / `licence_non_free` and is judged the same way, so a
# CC BY-NC or ND file, a non-free one or an ESA-Standard-only item is refused
# by the rule's `refused` lists.
#
# A refused candidate leaves the pool here, before grouping and ranking, with
# a `licence_refused` record in `evidence.footage_candidates_dropped` (so the
# next real candidate takes its slot and the indexer never sees it). A channel
# whose footage-origin.json has no `licences` (ExampleFilm) gets no judgement
# at all: its candidates carry the licence the YouTube path implies, marked
# `judged: false`, and nothing is refused - today's footing.
LICENCE_REFUSED_CODE = "licence_refused"
YT_CC = "creativeCommon"
LICENCE_NAMES = {          # the short names the YouTube path writes -> the accepted id they read as
    "cc by": "cc_by",
    "youtube official upload": "youtube_official_upload",
    "youtube upload": "youtube_upload",
}

# --------------------------------------------------------------------------
# what an upload is
# --------------------------------------------------------------------------
# (kind, nature, pattern), first match wins. `nature` is the coarser bucket
# the diversity of the pool is counted in: a teaser and a trailer are two
# kinds but one nature, because they are cut from the same shoot and the
# CF-0080 fingerprint has every chance of collapsing them.
#
# Order matters. `commentary` is first on purpose: "Official Trailer
# Breakdown" and "Trailer REACTION" are somebody talking over a trailer, not
# a second source, and a title that says so must not be read as a trailer.
KIND_RULES = (
    ("commentary", "commentary",
     r"\b(reaction|reacts|reacting|review|breakdown|explained|explains|recap|"
     r"theor(y|ies)|top\s*\d+|rank(ed|ing)|tier list|podcast|analysis|"
     r"everything we know|easter eggs|things you missed|spoiler(s)? talk)\b"),
    ("featurette", "featurette",
     r"\b(featurette|behind[\s-]the[\s-]scenes|bts|making[\s-]of|b[\s-]?roll|"
     r"blooper(s)?|gag reel|deleted scene(s)?|inside (the )?(episode|look)|"
     r"on set|set visit)\b"),
    ("interview", "interview",
     r"\b(interview(s|ed)?|talks? (about|to)|sits? down|press (junket|conference|tour)|"
     r"q\s*&\s*a|q and a|red carpet|roundtable|on playing|answers|in conversation|"
     # CF-0577: a director or an actor walking through their own scene is
     # them talking, not the scene ("Zach Cregger Breaks Down Scenes From ...")
     r"break(s|ing)? down|dish(es|ing)? (on|about))\b"),
    ("episode_clip", "episode",
     r"\b(clip|scene(s)?|sneak peek|first look|opening (scene|minutes|credits)|"
     r"full episode|s\d{1,2}\s*e\d{1,2}|episode \d+|cold open|highlight(s)?|"
     # CF-0577: a monologue, a sketch or a Weekend Update segment is a number
     # of the show itself - "Dana Reyes Monologue - WNL" is the event on
     # screen, not the host talking about it
     r"monologue|sketch(es)?|weekend update)\b"),
    ("teaser", "trailer", r"\bteaser\b"),
    ("trailer", "trailer", r"\btrailer\b"),
    ("promo", "promo",
     r"\b(promo|tv spot|spot|date announcement|announcement|first promo|opening titles)\b"),
)

# CF-0662 (TH-1 of the root's docs/science-footage.md): a science channel's
# uploads are not a film's. An agency publishes briefings, animations, b-roll,
# launch and landing coverage, interviews and lectures - read with the film's
# rules almost all of them were `unknown`, the tail nature, ordered last and
# never counted as a nature of the pool. These are their own natures, chosen
# by the channel (`footage_kinds` of its footage-origin.json; absent = the
# film set). Order matters as above: `commentary` first, then the words that
# say *who talks* (a launch briefing is a briefing, an astronaut interview
# after splashdown is an interview), then what is shown.
#
# The ceiling (`sources.youtube.max_source_duration_seconds`) reads these
# natures by name: `trailer` (a mission trailer or teaser) keeps its 900 s;
# everything else is held to `default` - a multi-hour launch broadcast or a
# lecture is refused on its metadata, the short cut beside it is not.
SCIENCE_KIND_RULES = (
    ("commentary", "commentary",
     r"\b(reaction|reacts|reacting|podcast|top\s*\d+|rank(ed|ing)|tier list|"
     r"conspiracy|debunk(ed|ing)?|hoax)\b"),
    ("teaser", "trailer", r"\bteaser\b"),
    ("trailer", "trailer", r"\btrailer\b"),
    ("briefing", "briefing",
     r"\b(briefing|news conference|press conference|teleconference|media (call|event)|"
     r"press event|town hall|post[\s-]?launch (news|press)|science update)\b"),
    ("lecture", "lecture",
     r"\b(lecture|colloquium|seminar|symposium|keynote|webinar|public talk|"
     r"panel discussion|talk series)\b"),
    ("interview", "interview",
     r"\b(interview(s|ed)?|q\s*&\s*a|q and a|in conversation|meet the|"
     r"ask an? (astronaut|scientist|engineer|expert)|talks? (about|with))\b"),
    ("animation", "animation",
     r"\b(animation|animated|visuali[sz]ation|simulation|artist'?s (concept|impression)|"
     r"render(ing)?|cgi|fly[\s-]?through|zoom(s)? (in|into)|3d (tour|model))\b"),
    ("b_roll", "b_roll",
     r"\b(b[\s-]?roll|raw (footage|video)|stock footage|time[\s-]?lapse|"
     r"4k (footage|video))\b"),
    ("explainer", "explainer",
     r"\b(explained|explainer|explains|how (does|do|did|is|are|we)|what (is|are)|"
     r"why (does|do|is|are)|science of|101)\b"),
    ("launch", "mission",
     r"\b(launch(es|ed)?|lift[\s-]?off|countdown|splashdown|touchdown|landing|landed|"
     r"docking|undocking|spacewalk|flyby|fly[\s-]by|rollout|roll[\s-]out|"
     r"static fire|hot fire|deploy(s|ed|ment)?|separation|arrives?|arrival|"
     r"first (image|images|light|look))\b"),
)
SCIENCE_NATURE_ORDER = ("mission", "animation", "b_roll", "trailer", "explainer",
                        "interview", "briefing", "lecture", "commentary", "unknown")

# CF-0567 (TH step of the root's docs/tech-footage.md): a tech channel's
# footage is of two kinds only - its own screen recording of the tool
# (`own_capture`, nature `demo`: the «демо» pattern's footage, assigned by the
# record's kind and never read off a title) and the vendors' own uploads,
# taken as short proof quotes (`official_channels[].role: proof_quote`;
# anyone else's upload is refused by the channel's licence list). The rules
# below read the vendors' uploads: a keynote or launch event, the company's
# own demo of the product, the launch film ("Introducing ..."), a product
# shot (the product film, the reveal, the ad), an interview, an explainer of
# the research, a trailer or teaser - and `commentary` first, as in the other
# sets, for a reaction or a review that slipped past the licence.
#
# The ceiling reads these natures by name too: `trailer` keeps its 900 s,
# everything else `default` - a two-hour keynote is refused on its metadata
# (channels/example-tech.json `max_source_duration_seconds` note: the short
# cut a company publishes beside it is the footage).
OWN_CAPTURE_KIND = footage_origin.OWN_CAPTURE
DEMO_NATURE = "demo"
TECH_KIND_RULES = (
    ("commentary", "commentary",
     r"\b(reaction|reacts|reacting|review(s|ed)?|podcast|top\s*\d+|rank(ed|ing)|tier list|"
     r"rumou?rs?|leak(s|ed)?|vs\.?|versus|compared|comparison)\b"),
    ("teaser", "trailer", r"\bteaser\b"),
    ("trailer", "trailer", r"\btrailer\b"),
    ("keynote", "keynote",
     r"\b(keynote|live\s?stream|livestream|full (event|presentation|stream)|event recap|"
     r"supercut|launch event|special event|conference|i/o|wwdc|gtc|re:?invent|dev\s?day|"
     r"connect \d{4}|build \d{4}|presentation)\b"),
    ("interview", "interview",
     r"\b(interview(s|ed)?|in conversation|fireside chat|q\s*&\s*a|q and a|sits? down|"
     r"talks? (about|with))\b"),
    ("demo", "vendor_demo",
     r"\b(demo(s|nstration)?|hands[\s-]on|in action|see (it|how)|walk[\s-]?through|tutorial|"
     r"how to (use|build|get|make)|getting started|use cases?|try it|showcase)\b"),
    ("product_shot", "product",
     r"\b(product (film|video)|b[\s-]?roll|reveal(ed)?|unboxing|design (film|story)|"
     r"first look|commercial|tv spot|ad)\b"),
    ("explainer", "explainer",
     r"\b(explained|explainer|explains|how (it|does|do|we|they) work|research|paper|"
     r"deep dive|behind the|inside|science of|101)\b"),
    ("announcement", "launch",
     r"\b(introducing|announc(e|es|ed|ing|ement)|launch(es|ed|ing)?|unveil(s|ed|ing)?|meet|"
     r"now available|available (now|today)|coming soon|release[sd]?|what'?s new|new)\b"),
)
# Our recording leads; then what shows the product working (the vendor's
# demo, the launch film, the product shot), then the people talking.
TECH_NATURE_ORDER = (DEMO_NATURE, "vendor_demo", "launch", "product", "keynote", "explainer",
                     "trailer", "interview", "commentary", "unknown")

FILM_KINDS = "film"
SCIENCE_KINDS = "science"
TECH_KINDS = "tech"
KINDS_KEY = "footage_kinds"
# The sets a channel may choose (`footage_kinds`). `room`: a talk show named
# as a title tag or as the uploader is an interview (CF-0577) - a film rule.
KIND_SETS = {
    FILM_KINDS: {"rules": KIND_RULES, "room": True},
    SCIENCE_KINDS: {"rules": SCIENCE_KIND_RULES, "room": False},
    TECH_KINDS: {"rules": TECH_KIND_RULES, "room": False},
}

# Every kind and nature any set can write - what `--check` holds a record to.
# CF-0567: `own_capture` / `demo` is written off the record's kind, not a rule.
KINDS = tuple(dict.fromkeys(k for ks in KIND_SETS.values() for k, _, _ in ks["rules"])) \
    + (OWN_CAPTURE_KIND, "unknown")
NATURES = tuple(dict.fromkeys(n for ks in KIND_SETS.values() for _, n, _ in ks["rules"])) \
    + (DEMO_NATURE, "unknown")

# Which nature goes first when the pool has several. A trailer is the most
# reliably downloadable and best-framed cut, so it leads; everything after it
# is there to be *different from it*, which is what round-robin delivers.
# `commentary` is last: it is mostly a talking head over the trailer, and it
# is a candidate only when the topic has nothing else.
NATURE_ORDER = ("trailer", "episode", "interview", "featurette", "promo",
                "commentary", "unknown")
KIND_SETS[FILM_KINDS]["order"] = NATURE_ORDER
KIND_SETS[SCIENCE_KINDS]["order"] = SCIENCE_NATURE_ORDER
KIND_SETS[TECH_KINDS]["order"] = TECH_NATURE_ORDER
# The natures that are not footage of the thing itself: a reaction video is a
# talking head over the trailer, and an upload whose title says nothing may be
# anything. They are still offered - a topic with nothing else has to offer
# something - but they go after every real cut in the order, and they do not
# count towards the natures a pool is judged to hold.
TAIL_NATURES = ("commentary", "unknown",
                # CF-0662: a lecture is a talking head and slides for most of
                # its length - offered, but not counted as footage of the story
                "lecture")


def kind_set_name(config=None):
    """-> the name of the channel's kind set: its `footage_kinds` when it
    names one; else, CF-0567, `tech` for a channel whose footage origins name
    `own_capture` (ExampleTech, until the root writes the key) and `film`
    for every other (ExampleFilm)."""
    name = (config or {}).get(KINDS_KEY)
    if name:
        return name
    return TECH_KINDS if footage_origin.has_own_capture(config) else FILM_KINDS


def kind_set(config=None):
    """-> the kind set the channel's footage is read in (`footage_kinds` of
    its footage-origin.json, carried by `footage_origin.load_config`); the
    film set when the channel names none (ExampleFilm), the tech set when it
    names none but records its own footage (CF-0567). A name nobody knows is
    a ConfigError, not a quiet fallback."""
    name = kind_set_name(config)
    if name not in KIND_SETS:
        raise footage_origin.ConfigError(
            f"{(config or {}).get('official_path') or 'footage-origin.json'}: "
            f"{KINDS_KEY} {name!r} is not one of {sorted(KIND_SETS)} (CF-0662)")
    return KIND_SETS[name]

# Publishers whose channel is the source rather than a reupload of it. The
# list itself moved to `config/footage_origin.json` on CF-0297 (and on CF-0627 to
# the channel's own `channels/<id>/footage-origin.json`) - it used to be
# the regex `OFFICIAL_CHANNEL_RE` here - because it is appended to every time a
# batch shows a distributor nobody had seen, and because it now decides three
# things instead of one: which upload represents a group of same-cut uploads,
# which upload leads its nature (`official` before `unknown`), and which
# uploads the CF-0297 stop-word sieve must never touch.

# Upload noise: words that differ between two uploads of one cut and say
# nothing about which cut it is.
NOISE_WORDS = {
    "official", "officiel", "hd", "fhd", "uhd", "4k", "1080p", "720p", "60fps",
    "new", "newest", "latest", "final", "full", "watch", "now", "online", "free",
    "exclusive", "premiere", "first", "video", "youtube", "subscribe", "sub",
    "subtitulado", "sub espanol", "espanol", "legendado", "vostfr", "dub", "dubbed",
    "reupload", "hq", "movie", "film", "series", "show", "examplestream", "example network", "max",
    "the", "a", "an", "of", "and", "or", "to", "in", "on", "for", "with", "feat",
}
YEAR_RE = re.compile(r"^(19|20)\d{2}$")
SPLIT_RE = re.compile(r"[|–—·]")


# CF-0577: a talk show or a studio-interview room, named in the title ("... |
# Late Night with Sam Meadows") or as the uploader's channel. What such a room
# uploads is the guest talking as themselves - an interview - unless its title
# says it is something else (a sketch, a monologue, a clip), which the title
# pass reads first. Kept narrow on purpose: a bare "Ellen" or "Conan" is a
# first name or a barbarian as often as it is a show.
TALK_SHOW_RE = re.compile(
    r"\b(late night with|late show|late late show|tonight show|jimmy kimmel( live)?|"
    r"sam meadows|jim fenwick|stephen colbert|graham norton|daily show|"
    r"kelly clarkson show|drew barrymore show|ellen show|ellen degeneres|james corden|"
    r"conan o'?brien|team coco|today show|good morning america|watch what happens live|"
    r"live with kelly|hot ones|talk show)\b", re.I)

# How much of the description the last pass reads: past the first couple of
# lines it is boilerplate ("subscribe", social links) that matches everything.
DESCRIPTION_HEAD = 240


def _text(video):
    """Title + channel + the head of the description - everything
    classification may read, in the order it trusts it."""
    desc = (video.get("description") or "")[:DESCRIPTION_HEAD]
    return " ".join(str(x or "") for x in (video.get("title"), video.get("channel_title"), desc)).lower()


def _rule_of(text, rules=None):
    """The first rule (default KIND_RULES) this one text matches, or None."""
    for kind, nature, pattern in rules or KIND_RULES:
        if re.search(pattern, text, re.I):
            return kind, nature
    return None


def classify(video, config=None):
    """-> (kind, nature). Reads the metadata the search gave us and nothing
    else; an upload whose title says nothing is `unknown`, not a guess.

    CF-0577: the title decides, then the room (a talk show named as a title
    tag or as the uploader's channel is an interview), then the head of the
    description, then the words of the channel's name.
    It used to be one string of title + channel + description against the
    rules in rule order, so "Dana Reyes Monologue - WNL" (channel Saturday
    Night Live) became an `interview` off a description that says the host
    "talks about" something - the description outranked a title that names the
    number. The search facet that found an upload (`facets`) is never read
    here: "Mean, Scary Girlfriend - WNL" was found by the trailer facet and is
    no trailer."""
    return classify_with_source(video, config)[:2]


def _room_tags(title):
    """The trailing `| ...` segments of a title - where an upload names the
    room it was shot in ("... | Late Night with Sam Meadows"). The head of the
    title is what happened, and a show named there is the subject ("The Late
    Show with Stephen Colbert Wins Outstanding Variety Series | 78th Emmy
    Awards | NBC" is an award, not a talk-show couch)."""
    return " | ".join(SPLIT_RE.split(title)[1:])


def classify_with_source(video, config=None):
    """-> (kind, nature, read) - `classify()` plus which reading decided it:
    `title`, `room` (a talk show named as a title tag or as the channel),
    `description` or `channel` (the channel's own words, last: a channel
    called "Scene Flix Studios" or "Red Carpet Trailers" says nothing about
    one upload), or `none`. The history replay of CF-0577 reads it, because a
    written batch keeps no descriptions."""
    ks = kind_set(config)
    # CF-0567: our own recording is the demo's footage by what it is, whatever
    # its title says.
    if footage_origin.is_own_capture(video):
        return OWN_CAPTURE_KIND, DEMO_NATURE, "kind"
    rules = ks["rules"]
    title = str(video.get("title") or "")
    channel = str(video.get("channel_title") or "")
    hit = _rule_of(title, rules)
    if hit:
        return hit + ("title",)
    # CF-0665: an archive item's own keywords (NASA's `keywords`) say what it
    # is more reliably than a file name ("KSC-20241115-...-Stacking").
    if video.get("keywords"):
        hit = _rule_of(" ; ".join(str(k) for k in video["keywords"]), rules)
        if hit:
            return hit + ("keywords",)
    if ks["room"] and (TALK_SHOW_RE.search(_room_tags(title)) or TALK_SHOW_RE.search(channel)):
        return "interview", "interview", "room"
    hit = _rule_of((video.get("description") or "")[:DESCRIPTION_HEAD], rules)
    if hit:
        return hit + ("description",)
    hit = _rule_of(channel, rules)
    if hit:
        return hit + ("channel",)
    return "unknown", "unknown", "none"


def is_official(video, config=None):
    """Whether this upload's channel is on the official list (CF-0297)."""
    return footage_origin.is_official(video, config)


def origin(video, config=None):
    """-> `official` / `unofficial` / `unknown` (CF-0297)."""
    return footage_origin.origin_of(video, config)[0]


def _signs_upload(segment, config=None):
    """Whether a title segment is the publisher signing its own upload
    ("... | Example Studios"). Read with the same list `is_official` reads, so
    the two answers cannot drift apart."""
    return footage_origin.official_channel({"channel_title": segment}, config) is not None


def _tokens(text):
    return [t for t in re.split(r"[^0-9a-z]+", (text or "").lower()) if t]


def cut_key(video, nature, topic_title=None, config=None):
    """The group two uploads of the same cut land in: the nature plus the
    title core - the title's own words with the topic's name, the upload
    noise and the release year removed, order-insensitive.

    "Everyday Sorcery 2 | Official Teaser | Example Studios" and "EVERYDAY SORCERY
    2 Teaser (2026) HD" both reduce to `("trailer", "2 teaser")`; "Official
    Trailer 2" does not join them. The bias is deliberately towards
    collapsing: over-collapsing costs a candidate and is recorded as a
    shortfall, while splitting two uploads of one cut hands the indexer three
    ids that turn into one source after CF-0080 - the failure this task is
    about.
    """
    segments = [s for s in SPLIT_RE.split(video.get("title") or "") if s.strip()]
    # "... | Example Studios" is the publisher signing its own upload, not a word
    # about which cut this is; a reupload does not carry it and would land in
    # its own group.
    kept = [s for s in segments if not _signs_upload(s, config)] or segments
    drop = {t for t in _tokens(topic_title) if not t.isdigit()}
    core = [t for t in _tokens(" ".join(kept))
            if t not in drop and t not in NOISE_WORDS and not YEAR_RE.match(t)]
    return nature, " ".join(sorted(set(core)))


def _rank_in_group(video, config=None):
    """Which upload of one cut represents it: the official channel's, then
    the most-viewed. CF-0665: an archive file before both - the same cut as a
    direct download with its licence and credit known."""
    return (0 if is_archive(video) else 1, 0 if is_official(video, config) else 1,
            -(video.get("view_count") or 0))


def group_videos(videos, topic_title=None, config=None):
    """-> [{"nature", "kind", "key", "videos": [...]}] - one entry per cut,
    its uploads sorted by `_rank_in_group`."""
    groups = {}
    for video in videos:
        if not video.get("video_id"):
            continue
        kind, nature = classify(video, config)
        key = cut_key(video, nature, topic_title, config)
        g = groups.setdefault(key, {"nature": nature, "kind": kind, "key": key[1], "videos": []})
        g["videos"].append(video)
    for g in groups.values():
        g["videos"].sort(key=lambda v: _rank_in_group(v, config))
        g["kind"] = classify(g["videos"][0], config)[0]
    return list(groups.values())


# --------------------------------------------------------------------------
# the ceiling: reading it, and taking the pool through it
# --------------------------------------------------------------------------

def ceiling_limits(node):
    """Whatever the config key holds -> `{nature: seconds}`.

    One number is a ceiling for every nature; a mapping names natures and may
    carry its own `default`, and the natures it does not name keep
    DEFAULT_MAX_SOURCE_SECONDS. Anything else - a string, a `note` written
    beside the numbers the way the rest of this factory's config writes them,
    a negative, a bool - is ignored rather than raising: a ceiling nobody can
    parse must not be the reason a batch has no footage. Read exactly the way
    `ingest_batch._ceiling_limits` reads it, so the two ends of the contract
    cannot drift.
    """
    limits = dict(DEFAULT_MAX_SOURCE_SECONDS)
    if isinstance(node, bool):
        return limits
    if isinstance(node, (int, float)) and node > 0:
        return {CEILING_DEFAULT_NATURE: node}
    if isinstance(node, dict):
        got = {k: v for k, v in node.items()
               if isinstance(k, str) and isinstance(v, (int, float))
               and not isinstance(v, bool) and v > 0}
        if got:
            limits.update(got)
    return limits


def _batch_channel(batch):
    """The batch's channel id, resolved at the door (CF-0197): a batch written
    before a rename carries the former id frozen in that field."""
    return _channel_ids.resolve_channel(batch.get("channel")) if batch.get("channel") else None


def channel_ceiling(channel=None, config_path=None, root=None):
    """`{nature: seconds}` for one channel, out of `channels/<id>.json`.

    A channel that is not named, a config that is missing or unreadable and a
    config silent on the key are all normal states and all mean the measured
    defaults: this stage must keep working in a temp tree and on a batch whose
    channel was renamed (the id is resolved through CF-0197 first).
    """
    path = Path(config_path).expanduser() if config_path else None
    if path is None and channel:
        try:
            path = Path(_channel_ids.channel_config_path(str(channel), root=root))
        except Exception:                                   # noqa: BLE001
            path = None
    node = None
    if path is not None and path.is_file():
        try:
            node = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            node = None
        for part in CEILING_KEY_PATH:
            node = node.get(part) if isinstance(node, dict) else None
            if node is None:
                break
    return ceiling_limits(node)


def ceiling_for(nature, limits=None):
    """The ceiling one nature is held to, in seconds."""
    limits = limits or dict(DEFAULT_MAX_SOURCE_SECONDS)
    if nature in limits:
        return limits[nature]
    return limits.get(CEILING_DEFAULT_NATURE,
                      DEFAULT_MAX_SOURCE_SECONDS[CEILING_DEFAULT_NATURE])


def duration_of(video):
    """The upload's length in seconds, or None when nobody measured it.

    None is the answer for an absent field (a search run before CF-0302), for
    a live stream or a premiere (`P0D`) and for anything that is not a
    positive number. It never means "short"."""
    raw = (video or {}).get(DURATION_KEY)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return raw if raw > 0 else None


def over_ceiling(video, nature=None, limits=None):
    """-> (seconds, limit) when this upload is longer than its nature's
    ceiling, else (None, None). An unmeasured upload is never over it."""
    seconds = duration_of(video)
    if seconds is None:
        return None, None
    nature = nature or classify(video)[1]
    limit = ceiling_for(nature, limits)
    return (seconds, limit) if seconds > limit else (None, None)


def too_long_record(video, nature, seconds, limit):
    """One `source_too_long` drop, in the shape `footage_candidates_dropped`
    already holds (`topic_relevance.EXCLUSION_KEYS`) plus the three numbers
    that make the drop arguable: what was measured, what it was measured
    against, and which nature that ceiling belongs to. A drop nobody can
    re-derive is the CF-0272 failure over again."""
    return {
        "video_id": (video or {}).get("video_id"),
        "title": (video or {}).get("title"),
        "channel_title": (video or {}).get("channel_title"),
        "view_count": (video or {}).get("view_count"),
        "reason_code": TOO_LONG_CODE,
        "reason": (f"{int(seconds)} s long - over the {int(limit)} s ceiling this channel "
                   f"holds nature {nature!r} to ({CEILING_KEY}, CF-0302). A two-hour upload "
                   f"with 'trailer' in its title is not a trailer; downloading it costs the "
                   f"topic an attempt and hours of indexing (Lv_GOa6HXVA, 2026-09-21)."),
        DURATION_KEY: seconds,
        "ceiling_seconds": limit,
        "nature": nature,
    }


def partition_too_long(videos, limits=None, config=None):
    """-> (kept, dropped_records), the pool order preserved - the third sieve,
    in the same place and for the same reason as CF-0272's and CF-0297's."""
    kept, dropped = [], []
    for video in videos or []:
        nature = classify(video, config)[1]
        seconds, limit = over_ceiling(video, nature, limits)
        if seconds is not None:
            dropped.append(too_long_record(video, nature, seconds, limit))
        else:
            kept.append(video)
    return kept, dropped


def licence_name(video, config=None):
    """-> (short_name, what it was read off) for one upload - the archive's
    own per-file name when the record carries one, else YouTube's
    `status.license`, else official / anyone's upload by the channel id."""
    video = video or {}
    if footage_origin.is_own_capture(video):
        # CF-0567: our recording - the channel's `own_capture` licence (its
        # `matches`: "own capture"), never a licence of the page recorded.
        return "own capture", "the factory's own recording (origin own_capture, CF-0567)"
    name = video.get("licence_short_name")
    if is_archive(video):
        # CF-0665: an archive file is judged on the archive's word alone - an
        # empty one is "no licence named", never a YouTube licence.
        return (name if isinstance(name, str) else "",
                video.get("licence_read_from") or "the archive's own licence of the file")
    if isinstance(name, str) and name.strip():
        return name, "the archive's own licence of the file"
    if video.get("yt_license") == YT_CC:
        return "cc by", "YouTube's status.license creativeCommon (CC BY 3.0)"
    if footage_origin.is_official(video, config):
        return ("youtube official upload",
                "an official channel's upload under YouTube's standard licence")
    return "youtube upload", "anyone's upload under YouTube's standard licence (sieved)"


def licence_block(video, config=None):
    """-> the candidate's `licence` record: `{id, accepted, judged, short_name,
    read_from, yt_license, origin, attribution, share_alike, license_url,
    reason}`. `judged: false` (and `accepted: null`) for a channel that lists
    no licences; a channel that lists them but whose rule cannot be found is
    judged closed - refused, with the reason."""
    config = footage_origin._require(config)
    video = video or {}
    name, read_from = licence_name(video, config)
    block = {"id": None, "accepted": None, "judged": False, "short_name": name,
             "read_from": read_from, "yt_license": video.get("yt_license"),
             "origin": footage_origin.origin_id(video, config),
             "attribution": None, "share_alike": None, "license_url": None, "reason": None}
    lists = config.get("licences")
    if not lists:
        block.update(id=LICENCE_NAMES.get(name),
                     reason=("the channel lists no licences (its footage-origin.json has no "
                             "`licences`) - no licence judgement, the YouTube path's footing"))
        return block
    rule = _footage_licence.footage_licence
    if rule is None:
        block.update(judged=True, accepted=False,
                     reason=("the channel lists licences but the factory's licence rule "
                             "(shared/footage_licence.py) was not found - nothing is taken "
                             "unjudged (CF-0662)"))
        return block
    verdict = rule.licence_of(name, lists, non_free=bool(video.get("licence_non_free")))
    # CF-0665: a file's own licence link (Commons `LicenseUrl`: CC BY-SA 4.0,
    # not the family's 3.0 IGO) is the one its credit line must carry.
    own_url = video.get("licence_url") if verdict.get("accepted") else None
    block.update(id=verdict.get("id"), accepted=bool(verdict.get("accepted")), judged=True,
                 attribution=verdict.get("attribution"), share_alike=verdict.get("share_alike"),
                 license_url=own_url or verdict.get("license_url"), reason=verdict.get("reason"))
    return block


def is_archive(video):
    """CF-0665: a record out of an archive (`fetch_archive_footage.py`), not a
    YouTube upload."""
    video = video or {}
    return bool(video.get(ARCHIVE_KEY)) or video.get("kind") == "archive" or \
        str(video.get("video_id") or "").startswith(ARCHIVE_ID_PREFIXES)


def licence_refused_record(video, block):
    """One `licence_refused` drop, in the shape `footage_candidates_dropped`
    holds, plus the licence record that refused it."""
    video = video or {}
    return {
        "video_id": video.get("video_id"),
        "title": video.get("title"),
        "channel_title": video.get("channel_title"),
        "view_count": video.get("view_count"),
        "reason_code": LICENCE_REFUSED_CODE,
        "reason": (f"licence {block.get('short_name')!r} ({block.get('read_from')}) is not one "
                   f"this channel takes - {block.get('reason')} "
                   f"(channels/<id>/footage-origin.json `licences`, CF-0564/CF-0662)"),
        LICENCE_KEY: block,
    }


def partition_licence_refused(videos, config=None):
    """-> (kept, dropped_records), the pool order preserved: the uploads whose
    licence the channel refuses leave the pool before grouping, so the next
    real candidate takes the slot (CF-0662)."""
    config = footage_origin._require(config)
    kept, dropped = [], []
    for video in videos or []:
        block = licence_block(video, config)
        if block["judged"] and not block["accepted"]:
            dropped.append(licence_refused_record(video, block))
        else:
            kept.append(video)
    return kept, dropped


def _candidate(group, nature_rank, groups_in_nature, config=None):
    video = group["videos"][0]
    same_cut = [v["video_id"] for v in group["videos"][1:]]
    where, where_why = footage_origin.origin_of(video, config)
    block = licence_block(video, config)
    why = f"{group['kind']}; {where} - {where_why}"
    if block["judged"]:
        why += f"; licence {block['id']} ({block['read_from']})"
    if is_archive(video):
        arch = video.get(ARCHIVE_KEY) or {}
        why += (f"; archive {arch.get('name')} {arch.get('id')!r} - direct download "
                f"({arch.get('rendition')}, {video.get('media_type')}, {video.get('bytes')} bytes), "
                f"credit {video.get('credit')!r}")
    own = footage_origin.is_own_capture(video)
    role = BASE_ROLE if own else footage_origin.role_of(video, config)
    if own:
        cap = video.get(CAPTURE_KEY) or {}
        why += (f"; own capture of {cap.get('space') or video.get('source_url')} "
                f"({len(cap.get('steps') or [])} steps, recording {video.get(CAPTURE_FILE_KEY)}) "
                f"- the demo's base footage")
    elif role == PROOF_QUOTE_ROLE:
        why += ("; the vendor's own upload - a proof quote only, never the base "
                "(proof_quotes caps, CF-0567)")
    if video.get(HOST_SHOW_KEY):
        why += f"; {video[HOST_SHOW_KEY]['reason']}"
    if same_cut:
        why += (f"; {len(same_cut) + 1} uploads of the same cut collapsed into one candidate "
                f"(kept {'the official channel' if is_official(video, config) else 'the most-viewed'})")
    if nature_rank:
        why += (f"; cut #{nature_rank + 1} of nature {group['nature']!r} "
                f"({groups_in_nature} in the pool)")
    record = {
        "video_id": video["video_id"],
        "kind": group["kind"],
        "nature": group["nature"],
        "origin": where,
        "title": video.get("title"),
        "channel_title": video.get("channel_title"),
        "view_count": video.get("view_count"),
        # CF-0302: what the search measured, carried into the artifact so the
        # indexer can hold the same ceiling without asking YouTube again
        # (`ingest_batch.measure_candidate` reads exactly this key). None when
        # nobody could tell.
        DURATION_KEY: duration_of(video),
        "facets": list(video.get("facets") or []),
        "same_cut": same_cut,
        "why": why,
        # CF-0662: what the upload may be taken under and whose footage it is
        # (`footage_origins[].id`; None off the official list). `origin` above
        # stays CF-0297's official/unknown, which the Analyst reads.
        LICENCE_KEY: block,
        FOOTAGE_ORIGIN_KEY: block["origin"],
        # CF-0665: the archive half - null on a YouTube candidate.
        **{k: (video.get(k) if is_archive(video) else None) for k in ARCHIVE_KEYS},
        # CF-0567: the channel and its role, and an own capture's recording.
        "channel_id": None if own else video.get("channel_id"),
        "role": role,
        CAPTURE_FILE_KEY: video.get(CAPTURE_FILE_KEY) if own else None,
        CAPTURE_KEY: video.get(CAPTURE_KEY) if own else None,
        # CF-0817: a host show kept under the exception carries its verdict;
        # every other candidate None (a refused host show is never here).
        HOST_SHOW_KEY: video.get(HOST_SHOW_KEY),
    }
    if own:
        record["source_url"] = video.get("source_url")
    return record


def select_candidates(videos, topic_title=None, want=FOOTAGE_CANDIDATE_FLOOR,
                      cap=FOOTAGE_CANDIDATE_MAX, config=None, limits=None):
    """-> (candidates, pool). `candidates` is the ordered candidate pool of one
    topic, round-robin across natures so the first two ids are of different
    natures; `pool` is what the search actually held, which is what a
    shortfall has to be read against.

    `topic_title` is the topic's whole `title_ref` (a bare name still works and
    is read as `{"name": ...}`). It is the whole ref because CF-0272 asks the
    pool a question the name alone cannot answer: a subtitle, a `parent_work`
    and a person-topic's work all count as naming the topic.

    The **first** thing done to the pool is dropping the uploads that name
    another work (`topic_relevance.partition`). It happens before grouping and
    before ranking on purpose: a Harbourlights trailer taken out at this point is
    replaced by the next real candidate the search found, so relevance costs a
    topic nothing as long as its own pool is deep enough. Taking it out later -
    after the round-robin, off the finished list - would leave the topic three
    candidates short for somebody else's promo.
    """
    config = footage_origin._require(config)
    seen = len([v for v in (videos or []) if v.get("video_id")])
    # CF-0567: the factory's own recordings are not uploads - the relevance,
    # installment, stop-word, length and talk sieves read an uploader's
    # metadata, and a recording has none (its Space was matched to the tool
    # by `fetch_own_capture.py`). They answer to the channel's licence list
    # like everything else, and lead the list below.
    own = [v for v in videos or [] if footage_origin.is_own_capture(v)]
    videos = [v for v in videos or [] if not footage_origin.is_own_capture(v)]
    own, own_licence = partition_licence_refused(own, config)
    videos, dropped = partition(videos or [], topic_title)
    named = len([v for v in (videos or []) if v.get("video_id")])
    # CF-0662: an upload whose licence the channel refuses (its footage-origin
    # `licences`) leaves here too - before grouping, so the next real
    # candidate takes its slot and the indexer never downloads it.
    videos, licence_refused = partition_licence_refused(videos, config)
    # CF-0444, the relevance rule's second half, in the same place and for the
    # same reason: an upload whose title names the topic's work only by the
    # franchise's short form ("Vanguards: Endgame | Official Trailer" for
    # Vanguards: Doomsday) leaves the pool here. Batch 2026-09-29T0705Z gave
    # Doomsday Endgame's candidate list, and the frame judge was the first to
    # notice. One rule with the indexer's pool check (CF-0325):
    # `topic_relevance.installment_forms`.
    videos, other_installment = partition_other_installment(videos, topic_title)
    # CF-0297, the second sieve, in the same place and for the same reason as
    # the first: an upload that says it is a fan trailer, a game capture, an
    # edit, a reaction, a parody, a repost or a podcast leaves the pool here,
    # before grouping and before ranking, so the next real candidate moves up
    # into its slot instead of the topic losing one.
    videos, unofficial = footage_origin.partition(videos, config)
    # CF-0302, the third sieve, in the same place and for the same reason: an
    # upload longer than the ceiling its nature is held to leaves the pool
    # here, before grouping and before ranking, so the next real candidate
    # takes its slot. An upload nobody measured stays - unknown is not long.
    videos, too_long = partition_too_long(videos, limits, config)
    # CF-0309, the fourth sieve, in the same place and for the same reason: an
    # upload whose own title says it is a talk about the work - a news
    # round-up, an opinion piece, a press junket interview, a title of
    # hashtags, a title that never names the work - leaves the pool here, so
    # the next real candidate takes its slot instead of the topic paying an
    # indexer attempt for it.
    videos, not_footage = footage_sieve.partition(videos, topic_title, origin=config)
    # CF-0817, the last sieve: somebody else's host is not our backdrop. A
    # podcast, an interview, a talk show, a junket, a reaction or a review
    # leaves the pool here - whatever its origin: the Zenith podcast is
    # Zenith's own, and every sieve above exempts an official channel -
    # unless the topic is about the person the title names
    # (`host_show.judge`). Last, so the drops above keep their own codes (a
    # fan reaction stays `unofficial_source`); before grouping, so the next
    # real candidate takes the slot.
    videos, host_shows = host_show.partition(
        videos, lambda v: classify_with_source(v, config),
        lambda v: footage_origin.is_official(v, config), title_ref=topic_title)
    licence_refused = own_licence + licence_refused
    dropped = (list(dropped) + licence_refused + other_installment
               + unofficial + too_long + not_footage + host_shows)
    videos = own + list(videos or [])
    groups = group_videos(videos or [], _topic_name(topic_title), config)
    by_nature = {}
    for g in groups:
        by_nature.setdefault(g["nature"], []).append(g)
    # CF-0665: for a story (a mission, an object, a phenomenon - CF-0662's
    # `is_story`) the archives' files lead: a direct download whose licence and
    # credit are the file's own. A film topic is never searched in an archive.
    archives_first = is_story(topic_title)
    for gs in by_nature.values():
        # Official first, then by views. CF-0297 item 3: `official` above
        # `unknown` - the studio's own cut of a nature leads that nature, and
        # a view count cannot buy a fan upload past it.
        gs.sort(key=lambda g: ((0 if archives_first and is_archive(g["videos"][0]) else 1),
                               footage_origin.rank(g["videos"][0], config),
                               -(g["videos"][0].get("view_count") or 0)))

    order = kind_set(config)["order"]

    def rank(nature):
        return order.index(nature) if nature in order else len(order)

    candidates = []
    # CF-0665: for a story the archive files are walked first - all of them,
    # real natures and tail alike - and the uploads after; otherwise one walk.
    phases = ([lambda g: is_archive(g["videos"][0]), lambda g: not is_archive(g["videos"][0])]
              if archives_first else [lambda g: True])
    # CF-0567: the factory's own recordings first, all of them - the «демо»
    # pattern's base footage - and a vendor's proof quote only after them.
    if any(footage_origin.is_own_capture(g["videos"][0]) for g in groups):
        phases = [lambda g: footage_origin.is_own_capture(g["videos"][0])] + [
            (lambda ph: (lambda g: not footage_origin.is_own_capture(g["videos"][0]) and ph(g)))(ph)
            for ph in phases]
    for in_phase in phases:
        phase = {n: [g for g in gs if in_phase(g)] for n, gs in by_nature.items()}
        phase = {n: gs for n, gs in phase.items() if gs}
        # Real footage first, round-robin across its natures - so the first two
        # ids the indexer tries are two different kinds of shoot rather than two
        # cuts of one trailer - and the tail natures after all of it.
        for natures in (sorted((n for n in phase if n not in TAIL_NATURES), key=rank),
                        sorted((n for n in phase if n in TAIL_NATURES), key=rank)):
            round_i = 0
            while len(candidates) < cap:
                took = False
                for nature in natures:
                    gs = phase[nature]
                    if round_i < len(gs) and len(candidates) < cap:
                        g = gs[round_i]
                        candidates.append(_candidate(g, by_nature[nature].index(g),
                                                     len(by_nature[nature]), config))
                        took = True
                if not took:
                    break
                round_i += 1

    pool = {
        # `videos_seen` is still everything the search returned, including the
        # uploads of another work - a shortfall has to be read against what was
        # looked at, not against what survived the relevance rule.
        "videos_seen": seen,
        "named_the_work": named,
        # The uploads the two rules took out, in full - `fill_batch` writes
        # them to `evidence.footage_candidates_dropped`, which is what makes
        # the drop readable instead of a silently shorter list. The key keeps
        # its CF-0272 name; `unofficial` beside it is the CF-0297 half of it.
        "wrong_work": dropped,
        "unofficial": unofficial,
        # CF-0302: the same list, split out so that a shortfall can say which
        # rule took which upload. `wrong_work` stays the whole of what was
        # dropped, whatever dropped it - that is what gets written to
        # `evidence.footage_candidates_dropped`.
        "too_long": too_long,
        # CF-0309, likewise split out so a shortfall can name the rule that
        # took the upload.
        "not_footage": not_footage,
        # CF-0444, likewise: the uploads of another installment of the
        # franchise, and the forms that name this one (None: the rule does
        # not apply to this name).
        "other_installment": other_installment,
        "installment_forms": installment_forms(topic_title),
        # CF-0662, likewise: the uploads under a licence the channel refuses.
        "licence_refused": licence_refused,
        # CF-0817, likewise: the host shows (podcast, interview, talk show...).
        "host_show": host_shows,
        "ceiling":dict(limits or DEFAULT_MAX_SOURCE_SECONDS),
        "origins": footage_origin.counts(videos, config),
        "distinct_cuts": len(groups),
        "collapsed_same_cut": sum(len(g["videos"]) - 1 for g in groups),
        "natures": {n: len(gs) for n, gs in sorted(by_nature.items())},
        "facets_searched": sorted({f for v in (videos or []) for f in (v.get("facets") or [])}),
        "wanted": want,
        "work_forms": work_forms(topic_title),
    }
    return candidates, pool


def _topic_name(topic_title):
    """The topic's name out of a `title_ref` or a bare string - what `cut_key`
    strips out of a title."""
    if isinstance(topic_title, dict):
        return topic_title.get("name")
    return topic_title


def pool_natures(records):
    """The natures a candidate list actually holds, counting footage only -
    TAIL_NATURES are offered but never make a pool look wide."""
    return sorted({r.get("nature") for r in records
                   if isinstance(r, dict) and r.get("nature") not in TAIL_NATURES})


def falls_short(records, want=FOOTAGE_CANDIDATE_FLOOR):
    """Whether a candidate list owes the artifact a shortfall record: fewer
    than `want` candidates, or fewer than NATURE_FLOOR natures of real
    footage among them (three cuts of one trailer, or one trailer and two
    reaction videos, is the shape CF-0080 collapses)."""
    return len(records) < want or len(pool_natures(records)) < NATURE_FLOOR


def shortfall_of(candidates, pool, want=FOOTAGE_CANDIDATE_FLOOR):
    """-> the `evidence.footage_candidate_shortfall` record, or None when the
    pool is at or above the floor in at least NATURE_FLOOR natures."""
    natures = pool_natures(candidates)
    found = len(candidates)
    unofficial = len(pool.get("unofficial") or [])
    too_long = len(pool.get("too_long") or [])
    not_footage = len(pool.get("not_footage") or [])
    other = len(pool.get("other_installment") or [])
    licence = len(pool.get("licence_refused") or [])
    hosts = len(pool.get("host_show") or [])
    dropped = (len(pool.get("wrong_work") or [])
               - unofficial - too_long - not_footage - other - licence - hosts)
    wrong = ((f"; {dropped} upload(s) named another work and were dropped "
              f"({WRONG_WORK_CODE})" if dropped else "")
             + (f"; {other} upload(s) named the work only by its franchise - another "
                f"installment ({OTHER_INSTALLMENT_CODE})" if other else "")
             + (f"; {unofficial} upload(s) were somebody's video about the work, not "
                f"footage of it ({UNOFFICIAL_CODE})" if unofficial else "")
             + (f"; {too_long} upload(s) were longer than the ceiling their nature is "
                f"held to ({TOO_LONG_CODE})" if too_long else "")
             + (f"; {not_footage} upload(s) were a talk about the work rather than a cut "
                f"of it ({NOT_FOOTAGE_CODE})" if not_footage else "")
             + (f"; {licence} upload(s) are under a licence this channel does not take "
                f"({LICENCE_REFUSED_CODE})" if licence else "")
             + (f"; {hosts} upload(s) were a host show - a podcast, an interview or a "
                f"talk show ({HOST_SHOW_CODE})" if hosts else ""))
    if not falls_short(candidates, want):
        return None
    if not found:
        reason = ("no filmable video found for this topic in the footage search - "
                  f"{pool['videos_seen']} video(s) seen" + wrong)
    elif found < want:
        reason = (f"only {found} distinct cut(s) of {pool['videos_seen']} video(s) seen"
                  + (f"; {pool['collapsed_same_cut']} upload(s) collapsed as the same cut"
                     if pool["collapsed_same_cut"] else "")
                  + wrong
                  + f"; floor is {want}")
    elif len(natures) == 1:
        reason = (f"{found} candidates but only one nature of footage ({natures[0]!r}) - the "
                  f"CF-0080 fingerprint is likely to collapse them into one source")
    else:
        reason = (f"{found} candidates but none of them is footage of the thing itself "
                  f"(natures: {', '.join(sorted(c['nature'] for c in candidates))})")
    return {"wanted": want, "found": found, "natures": natures,
            "videos_seen": pool["videos_seen"], "distinct_cuts": pool["distinct_cuts"],
            "collapsed_same_cut": pool["collapsed_same_cut"],
            "dropped_wrong_work": dropped,
            "dropped_unofficial": unofficial,
            "dropped_too_long": too_long,
            "dropped_not_footage": not_footage,
            "dropped_other_installment": other,
            "dropped_licence_refused": licence,
            "dropped_host_show": hosts,
            "facets_searched": pool["facets_searched"], "reason": reason}


# --------------------------------------------------------------------------
# filling a batch
# --------------------------------------------------------------------------

# CF-0567: the topic's footage base on a channel that records its own footage
# (ExampleTech) - how many own captures and proof quotes the list holds, and
# what that means for the «демо» pattern. Written on every topic of such a
# channel and nowhere else.
FOOTAGE_BASE_KEY = "footage_base"
QUOTES_ONLY = "proof_quotes_only"


def footage_base(candidates):
    """-> `{base, own_captures, proof_quotes, other, note}` of one topic's
    candidate list. `base` is `own_capture` when the list holds our recording;
    else null, and `note` says why that matters: vendor quotes are never the
    base of a video, so the editor's `demo_own_capture` / `proof_quote_cap`
    gates refuse a demo built on them alone."""
    own = [c for c in candidates or [] if footage_origin.is_own_capture(c)]
    quotes = [c for c in candidates or [] if c.get("role") == PROOF_QUOTE_ROLE]
    other = len(candidates or []) - len(own) - len(quotes)
    if own:
        state, note = (footage_origin.OWN_CAPTURE,
                       f"{len(own)} own capture(s) lead the list - the demo's base footage"
                       + (f"; {len(quotes)} vendor proof quote(s) beside them, capped by "
                          f"`proof_quotes`" if quotes else ""))
    elif quotes:
        state, note = (None,
                       f"{QUOTES_ONLY}: {len(quotes)} vendor proof quote(s) and no own capture - "
                       f"not a demo: a quote is never the base of a video (`proof_quotes."
                       f"never_the_base`), and the editor's demo_own_capture / proof_quote_cap "
                       f"gates refuse a demo built on quotes alone (CF-0567)")
    else:
        state, note = (None, "no own capture and no vendor proof quote - nothing for a demo")
    return {"base": state, "own_captures": len(own), "proof_quotes": len(quotes),
            "other": other, "only_proof_quotes": bool(quotes) and not own, "note": note}


SUPPORT_KEY = "support_text"   # = support_text.SUPPORT_KEY (step 5a writes it)


def refusal_reason(shortfall, footing=None):
    """The `skipped_topics[]` reason of a refusal at the floor: the
    shortfall's, and on a channel that draws its own graphics why its
    quotable facts did not keep it either (CF-0689)."""
    reason = (shortfall or {}).get("reason") or "below the footage candidate floor"
    return reason + (f"; {footing['note']}" if footing else "")


def kept_on_graphics_line(candidates, footing):
    """CF-0689: the note of a topic the footage floor alone would refuse and
    its quotable facts keep."""
    return (f"{len(candidates or [])} footage candidate(s), floor is "
            f"{CANDIDATE_REFUSAL_FLOOR}; {footing['note']} - the script stands on the "
            f"graphics the channel draws, not on footage (CF-0689)")


def write_capture_text(topic, candidates, config):
    """CF-0567: on a channel with the `own_capture` origin, put one
    `own_capture_record` piece per own capture of the list into the topic's
    `support_text` (`own_capture_text.py`) - the factory's own record of
    what was recorded, where, when and which steps completed, so a demo
    script's "running in a public Hugging Face Space, <owner>/<name>" has a
    verbatim quote to stand on. Never the fact; the state is untouched.
    -> the pieces written, or None when the topic has no support_text yet
    (step 5a has not run) or the channel records nothing."""
    if not footage_origin.has_own_capture(config):
        return None
    if not isinstance(topic.get(SUPPORT_KEY), list):
        return None
    topic[SUPPORT_KEY], new = own_capture_text.merge(topic[SUPPORT_KEY], candidates,
                                                     footage_origin.is_own_capture)
    return new


def write_api_demo_text(topic, config):
    """CF-0690: on a channel with the `api_demo` origin, put the topic's
    `api_demo_record` (`fetch_api_demo.py`) into its `support_text` as one
    `api_demo_record` piece (`api_demo_text.py`) - the factory's own record
    of the prompt sent, the model and the verbatim answer, so a script's
    sentence about the demo has a quote to stand on. Never a fact; the state
    is untouched. -> the pieces written, or None when the topic has no
    support_text yet (step 5a has not run) or the channel asks nothing."""
    if not footage_origin.has_api_demo(config):
        return None
    if not isinstance(topic.get(SUPPORT_KEY), list):
        return None
    topic[SUPPORT_KEY], new = api_demo_text.merge(topic[SUPPORT_KEY], topic,
                                                  footage_origin.api_demo_block(config))
    return new


def _match_signal(topic, signals):
    """The footage search belonging to one topic: bound explicitly by
    topic_id, else by `query` against `title_ref.name` (exact on normalised
    tokens, then the name's tokens contained in the query's)."""
    tid = topic.get("topic_id")
    if tid in signals:
        return tid, signals[tid]
    name = set(_tokens(((topic.get("title_ref") or {}).get("name")) or ""))
    if not name:
        return None, None
    best = None
    for key, sig in signals.items():
        q = set(_tokens(sig.get("query") or key))
        if q == name:
            return key, sig
        if name and name <= q:
            best = best or (key, sig)
    return best or (None, None)


def fill_batch(batch, signals, want=FOOTAGE_CANDIDATE_FLOOR, limits=None,
               batch_dir=None, searches_before=None, substitute=True):
    """Set `evidence.youtube_video_ids`, `evidence.footage_candidates` and
    `evidence.footage_candidate_shortfall` on every topic from its footage
    search. A topic with no candidate at all is taken out of `topics[]` and
    recorded in `skipped_topics[]` with `reason_code: no_source` - this stage
    refusing a topic it found no footage for, which is a loss the funnel can
    count. Since CF-0313 the slot that refusal empties is then refilled from
    the reserve, as far as the day's search quota reaches
    (`substitute_reserve`). Returns (problems, notes)."""
    problems, notes, kept, used, spent = [], [], [], set(), {}
    unsearched = []
    # CF-0302: the ceiling belongs to the channel this batch is for, and is
    # read once per batch from `channels/<id>.json`.
    limits = limits or channel_ceiling(_batch_channel(batch))
    # CF-0627: which channels are official is the batch's channel's list.
    try:
        origin_config = footage_origin.load_config(_batch_channel(batch))
    except footage_origin.ConfigError as exc:
        return [f"footage origin of the batch's channel: {exc}"], []
    for topic in batch.get("topics") or []:
        ctx = f"topic {topic.get('topic_id', '?')}"
        key, signal = _match_signal(topic, signals)
        evidence = topic.setdefault("evidence", {})
        if signal is None:
            # CF-0317: whether this is an operator who forgot the search or a
            # day that cannot pay for it is a question about the quota ledger,
            # and the ledger is only settled below. Decide after it.
            unsearched.append(topic)
            kept.append(topic)
            continue
        used.add(key)
        spent[topic.get("topic_id") or key] = key
        candidates, pool = select_candidates(signal.get("videos") or [],
                                             topic.get("title_ref") or {}, want,
                                             limits=limits, config=origin_config)
        shortfall = shortfall_of(candidates, pool, want)
        dropped = pool["wrong_work"]
        evidence["youtube_video_ids"] = [c["video_id"] for c in candidates]
        evidence["footage_candidates"] = candidates
        evidence["footage_candidates_dropped"] = dropped
        evidence["footage_candidate_shortfall"] = shortfall
        if signal.get("feed_read"):
            # CF-0661: what the official channels' feed read was - how many
            # feeds answered, how many yt-dlp read instead, how many nobody
            # read, and by which path each candidate came - so "0 candidates
            # off the feeds" can be told from "the feeds were not read".
            evidence["footage_feed_read"] = signal["feed_read"]
        if signal.get("archive_read"):
            # CF-0665: what the archives answered (queries, hits, files kept).
            evidence["footage_archive_read"] = signal["archive_read"]
        if signal.get("capture_read"):
            # CF-0567: what the own-capture pass did for this topic - the Hugging
            # Face requests, the Spaces looked at, every take and every refusal
            # of the recorder (its policy refusals are final).
            evidence["footage_capture_read"] = signal["capture_read"]
        if footage_origin.has_own_capture(origin_config):
            # CF-0567: what the demo would stand on - our recording or nothing
            # but the vendors' proof quotes.
            evidence[FOOTAGE_BASE_KEY] = footage_base(candidates)
            written = write_capture_text(topic, candidates, origin_config)
            if written is None and any(footage_origin.is_own_capture(c) for c in candidates):
                notes.append(f"{ctx}: no support_text yet (step 5a) - the own capture's record "
                             f"is not a piece, a demo cannot quote where the tool ran")
            if not evidence[FOOTAGE_BASE_KEY]["own_captures"] and candidates:
                notes.append(f"{ctx}: {evidence[FOOTAGE_BASE_KEY]['note']}")
        if footage_origin.has_api_demo(origin_config):
            # CF-0690: the topic's API demo call as the factory's own record.
            written = write_api_demo_text(topic, origin_config)
            if written is None and api_demo_text.records_of(topic):
                notes.append(f"{ctx}: no support_text yet (step 5a) - the API demo's record "
                             f"is not a piece, a script cannot quote what the model was asked")
        footing = graphic_footing(topic, origin_config)
        if footing is not None:
            # CF-0689: what the graphics the channel draws would stand on.
            evidence[GRAPHIC_FOOTING_KEY] = footing
        for code, rows, what in ((WRONG_WORK_CODE,
                                  [d for d in dropped if d.get("reason_code") == WRONG_WORK_CODE],
                                  "another work"),
                                 (OTHER_INSTALLMENT_CODE, pool["other_installment"],
                                  "another installment of the franchise"),
                                 (UNOFFICIAL_CODE, pool["unofficial"],
                                  "not footage of the work"),
                                 (TOO_LONG_CODE, pool["too_long"],
                                  "longer than its nature's ceiling"),
                                 (NOT_FOOTAGE_CODE, pool["not_footage"],
                                  "a talk about the work, not a cut of it"),
                                 (LICENCE_REFUSED_CODE, pool.get("licence_refused") or [],
                                  "under a licence this channel does not take"),
                                 (HOST_SHOW_CODE, pool.get("host_show") or [],
                                  "a host show - somebody else's host is not our backdrop")):
            if rows:
                notes.append(f"{ctx}: {len(rows)} upload(s) dropped, {what} ({code}): "
                             + ", ".join(
                                 f"{d['video_id']} {d['title']!r}"
                                 + (f" [{int(d[DURATION_KEY])} s > {int(d['ceiling_seconds'])} s "
                                    f"for {d['nature']!r}]" if code == TOO_LONG_CODE else "")
                                 + (f" [{(d.get(LICENCE_KEY) or {}).get('short_name')}]"
                                    if code == LICENCE_REFUSED_CODE else "")
                                 for d in rows[:4])
                             + (" ..." if len(rows) > 4 else ""))
        if not meets_refusal_floor(candidates, origin_config, footing):
            refuse(batch, topic.get("topic_id"), refusal_reason(shortfall, footing))
            what = ("no footage candidate" if not candidates
                    else f"{len(candidates)} footage candidate, floor is "
                         f"{CANDIDATE_REFUSAL_FLOOR} - one source cannot pass the "
                         f"two-source gate")
            notes.append(f"{ctx}: refused, {what}"
                         + (f"; {footing['note']}" if footing else "")
                         + f" ({REFUSAL_CODE})")
            continue
        if not meets_refusal_floor(candidates, origin_config):
            notes.append(f"{ctx}: kept on own graphics - {kept_on_graphics_line(candidates, footing)}")
        kept.append(topic)
        if shortfall:
            notes.append(f"{ctx}: {len(candidates)} candidate(s) - {shortfall['reason']}")
    # CF-0313. What the pass above cost the day, before anything is spent on a
    # substitution: one ledger row per topic whose search was read, so a
    # second run over the same batch (the usual way a substitution is
    # completed) counts the same facet run once.
    quota = search_quota.quota_block(batch)
    # CF-0368: the article this pass spends on is the footage pass's - unless
    # the signal handed in is a feed read (CF-0361), which says so itself and
    # is charged to the feeds' own currency.
    search_quota.count_searches(quota, {tid: signals[key] for tid, key in spent.items()},
                                article=search_quota.ARTICLE_FOOTAGE)
    search_quota.settle(quota, batch_dir=batch_dir, before=searches_before)
    batch[search_quota.QUOTA_KEY] = quota
    # CF-0317, and only now, because the answer is in the ledger above.
    if unsearched:
        dropped, more_problems, more_notes = no_search_yet(batch, unsearched, quota)
        kept = [t for t in kept if not any(t is d for d in dropped)]
        problems.extend(more_problems)
        notes.extend(more_notes)
    batch["topics"] = kept
    if substitute:
        notes.extend(substitute_reserve(batch, signals, want=want, limits=limits,
                                        batch_dir=batch_dir, used=used))
    # A search that matched nothing is an operator error - except when what it
    # matched is a topic this stage has since taken out of `topics[]`. Since
    # CF-0313 a second pass over the batch is the ordinary way a substitution
    # is completed, and a second pass hands in every search again, including
    # the one for the topic the first pass refused.
    refused_keys = {r.get("topic_id") for r in batch.get("skipped_topics") or []}
    refused_keys |= {(r.get("title") or "").strip()
                     for r in batch.get("skipped_topics") or []}
    for key in sorted(set(signals) - used):
        if key in refused_keys:
            continue
        problems.append(f"footage search {key!r} matched no topic in this batch")
    # CF-0444: two topics of one batch walking away with the same candidate
    # list is the shape the 0705Z loss had (Endgame's six ids on Doomsday).
    # The sieve above is the fix; this is the alarm for the next shape of it.
    shared = shared_candidate_lists(batch)
    batch[SHARED_KEY] = shared
    notes.extend(shared_lines(shared))
    problems.extend(check_batch(batch, want))
    return problems, notes


# --------------------------------------------------------------------------
# CF-0444 - one candidate list for two topics
# --------------------------------------------------------------------------

# The batch-level key the warning is written to: [] when every topic's list is
# its own. A warning, not a problem: two works can share an upload honestly (a
# double bill, a studio sizzle reel), and `--check` does not fail the batch for
# it - the operator names it in the step-8 report.
SHARED_KEY = "footage_candidates_shared"
SHARED_CODE = "same_candidate_list"


def shared_candidate_lists(batch):
    """-> [{"topics", "names", "video_ids", "reason_code", "reason"}], one
    entry per set of topics of `topics[]` whose `evidence.youtube_video_ids`
    are the same set of ids. Order is ignored: a list re-sorted is still the
    same footage."""
    groups = {}
    for topic in batch.get("topics") or []:
        ids = (topic.get("evidence") or {}).get("youtube_video_ids") or []
        if not isinstance(ids, list) or not ids:
            continue
        groups.setdefault(frozenset(ids), []).append(topic)
    out = []
    for key, topics in groups.items():
        if len(topics) < 2:
            continue
        tids = [t.get("topic_id") for t in topics]
        names = [(t.get("title_ref") or {}).get("name") for t in topics]
        ids = list((topics[0].get("evidence") or {}).get("youtube_video_ids") or [])
        out.append({
            "topics": tids, "names": names, "video_ids": ids,
            "reason_code": SHARED_CODE,
            "reason": (f"{len(topics)} topics ({', '.join(repr(n) for n in names)}) have the "
                       f"same {len(ids)} footage candidate(s) - at most one of them is looking "
                       f"at its own work's footage; batch 2026-09-29T0705Z built Vanguards: "
                       f"Doomsday on Endgame's list and lost it at the frame judge (CF-0444)"),
        })
    return out


def shared_lines(shared):
    """The warning lines of `shared_candidate_lists`, for the stage's output
    and so for the step-8 report."""
    return [f"WARNING {row['reason_code']}: {' / '.join(row['topics'])} - {row['reason']}"
            for row in shared or []]


def no_search_yet(batch, topics, quota):
    """CF-0317. The topics that reached step 5b with no footage search behind
    them, judged against the day's settled ledger.

    Two different things wear the same shape. A day that can still pay for the
    facet run means the search was simply not handed in - an operator error,
    and the message says which command to run. A day that cannot is not a
    question for anybody: the key resets on its own clock, the reset is hours
    away, and no batch may be paid for standing in front of it. That topic
    leaves `topics[]` here with `footage_evidence_quota`, the funnel counts
    the loss, and the batch goes to compliance in the same minute.

    The topics are taken in order, so the searches the day *can* still pay for
    go to the topics that rank first. -> (dropped topics, problems, notes)."""
    price = max(1, int(quota.get("substitution_price_searches")
                       or search_quota.FACET_RUN_SEARCHES))
    left = int(quota.get("remaining_searches") or 0)
    affordable = left // price
    dropped, problems, notes = [], [], []
    for topic in topics:
        tid = topic.get("topic_id")
        ctx = f"topic {tid or '?'}"
        name = (topic.get("title_ref") or {}).get("name")
        if affordable > 0:
            affordable -= 1
            problems.append(f"{ctx}: no footage search given for {name!r} - "
                            f"run fetch_youtube_signal.py --facets for it "
                            f"({price} `search.list` call(s), and the day has "
                            f"{left} left)")
            continue
        reason = (f"no footage search was made for {name!r} and the day's YouTube "
                  f"Search quota will not pay for one: a facet run is {price} "
                  f"`search.list` call(s) and {left} of "
                  f"{quota.get('daily_limit_searches')} are left (CF-0288). The "
                  f"topic leaves this batch without footage evidence instead of the "
                  f"batch waiting for the reset at {quota.get('resets_at')} "
                  f"(CF-0317): the quota resets on its own clock, no batch is paid "
                  f"for standing in front of it, and the next scheduled run starts "
                  f"with a full day.")
        refuse(batch, tid, reason, code=EVIDENCE_QUOTA_CODE)
        dropped.append(topic)
        notes.append(f"{ctx}: refused, no footage search and no quota left to buy one "
                     f"({EVIDENCE_QUOTA_CODE})")
    return dropped, problems, notes


def refuse(batch, topic_id, reason, code=REFUSAL_CODE):
    """Record this stage's own refusal of a topic in `skipped_topics[]` - the
    shape the funnel reads (`topic_id`, `reason_code`, `reason`)."""
    skipped = batch.setdefault("skipped_topics", [])
    for row in skipped:
        if row.get("topic_id") == topic_id:
            row.update({"reason_code": code, "reason": reason, "stage": "trend-hunter"})
            return row
    row = {"topic_id": topic_id, "reason_code": code, "reason": reason, "stage": "trend-hunter"}
    skipped.append(row)
    return row


# --------------------------------------------------------------------------
# CF-0313: the slot a refusal empties is refilled from the reserve
# --------------------------------------------------------------------------
# The gap this closes. Step 5a (`fact_probe_topics.py`, CF-0264) cuts the
# shortlist to `scope.shortlist_size` and records everything past the cut as
# `below_shortlist` - viable topics, with a fact, that the batch simply had no
# room for. Step 5b then refuses a topic with fewer than
# CANDIDATE_REFUSAL_FLOOR candidates (CF-0309), and until CF-0313 its slot
# stayed empty: the shortlist went to compliance one topic short while two
# perfectly good reserve topics sat in `skipped_topics[]`. The slack between
# the shortlist (8) and the batch target (5) hid it; CF-0309 made the
# refusals frequent enough that it stops hiding it.
#
# So the loss is answered here, in the same pass that made it, exactly the way
# the indexer answers a loss of its own (CF-0306, `ingest_batch.py` ->
# `reserve_substitution`): the next reserve topic by rank takes the slot, goes
# back into `topics[]`, and is walked through step 5b like any other topic of
# the batch - the same four sieves, the same floor, the same refusal if its
# own pool is thin. Compliance then judges it on its first pass, because it is
# in `topics[]` before compliance ever opens the file; `cut_shortlist.py`
# (CF-0265) reads `topics[]` for its order and ranks the substitute where its
# score puts it, which is last - it is the topic the cut had no room for.
#
# What makes this different from the indexer's version, and is the whole
# reason CF-0313 is its own task: **a substitution costs YouTube quota**.
# Walking a reserve topic through 5b is one facet run - 6 `search.list` calls,
# 600 units - against a hard 100 calls a day (CF-0288). A batch is already
# ~68 of those, so the day pays for about five substitutions and the number is
# read out of `search_quota.py`, not written here as a literal.
#
# And because the facet run is a network call this module does not make, a
# substitution decided here may have to wait for it: the entry is written with
# `outcome: pending_search` and the exact command to run, and the topic goes
# into `topics[]` only on the next pass, when its search is in `--signal`. A
# pending entry is idempotent - the same loss is never answered twice, and a
# reserve topic offered once is never offered again.
SUBSTITUTION_KEY = "footage_substitution"

# `fact_probe_topics.OVERFLOW_CODE` - the reserve this stage draws on. Spelled
# here rather than imported for the same reason REFUSAL_CODE is.
RESERVE_CODE = "below_shortlist"
# The funnel's own words for the two things a substitution can be (CF-0306):
# a reserve topic that is now *in* the batch, and a slot nothing could fill.
SUBSTITUTED_CODE = "reserve_substituted"
RESERVE_EXHAUSTED_CODE = "reserve_exhausted"
# New in the vocabulary with CF-0313, and the code CF-0288 item 3 asks for: a
# slot that could have been refilled and was not, because the day's search
# calls would not pay for the facet run. It is not "no footage" - it is "not
# looked for", and a funnel that called it `no_source` would read a limit as a
# fact about the topic.
QUOTA_EXHAUSTED_CODE = "search_quota_exhausted"

# What the entry's `outcome` says happened to the substitute:
OUTCOME_PENDING = "pending_search"    # decided, waiting for its facet run
OUTCOME_CANDIDATES = "candidates"     # walked through 5b, and it has a pool
OUTCOME_REFUSED = "refused"           # walked, and 5b refused it too
OUTCOME_UNUSABLE = "unusable_record"  # the reserve row holds no topic to put back

SUBSTITUTION_NOTE = (
    "CF-0313. A topic this stage refuses at step 5b (`no_source`, fewer than "
    "CANDIDATE_REFUSAL_FLOOR candidates after the CF-0272/CF-0297/CF-0302/"
    "CF-0309 sieves) empties a shortlist slot, and the next `below_shortlist` "
    "topic by rank takes it: back into `topics[]`, walked through 5b, judged "
    "by compliance on its first pass like any other topic of the batch. "
    "`substitutions[]` says who replaced whom, with what code the replaced "
    "topic died and how the substitute ended up; `unmatched[]` is a slot that "
    "stayed empty, with the reason it did (`reserve_exhausted` - nothing left "
    "in reserve; `search_quota_exhausted` - the day's `search.list` calls do "
    "not pay for another facet run, see `search_quota`); `remaining[]` is the "
    "reserve nobody touched. `outcome: pending_search` is a substitution "
    "decided and not yet walked: run the facet search named in `reason` and "
    "re-run footage_candidates.py with it, which completes this entry rather "
    "than writing a second one. `selection` is step 5a's own record of the "
    "pass that cut the shortlist and is never rewritten here - what the batch "
    "holds now is `topics[]` and `skipped_topics[]`.")


def substitution_block(batch=None):
    """The batch's `footage_substitution` block, fresh or as it stands. Always
    the same shape once this has run, empty lists included: "the reserve was
    not needed" and "nobody looked at the reserve" must not read alike."""
    block = (batch or {}).get(SUBSTITUTION_KEY)
    if not isinstance(block, dict):
        block = {"task": "CF-0313"}
    for key in ("substitutions", "unmatched", "remaining"):
        if not isinstance(block.get(key), list):
            block[key] = []
    block["note"] = SUBSTITUTION_NOTE
    return block


def reserve_rows(batch, used=()):
    """The reserve of this batch, in the shortlist's own order: the
    `below_shortlist` rows of `skipped_topics[]` that nothing has spent yet.

    `rank` is the score order step 5a cut on and is what this queue is about,
    so it is used when it is there (CF-0313). A row written before that field
    keeps its place in `skipped_topics[]`, which *is* rank order - the cut
    appends the overflow in it - so an old artifact queues correctly as long
    as nobody re-sorted the list by hand.
    """
    used = set(used or ())
    rows = [r for r in (batch.get("skipped_topics") or [])
            if isinstance(r, dict) and r.get("reason_code") == RESERVE_CODE
            and r.get("topic_id") and r.get("topic_id") not in used]
    ordered = sorted(enumerate(rows),
                     key=lambda p: (p[1].get("rank")
                                    if isinstance(p[1].get("rank"), int) else 10 ** 6,
                                    p[0]))
    return [r for _, r in ordered]


def restore_reserve_topic(row):
    """-> (the topic record to put back into `topics[]`, whether it had to be
    rebuilt), or (None, True) when the row holds nothing to rebuild from.

    Since CF-0313 the cut keeps the whole topic on the row (`topic`), and this
    is a copy of it. Before CF-0313 it kept a summary, and a summary is not
    nothing: `title`, `kind`, `popularity_score` and the probe's own record,
    whose `asked` block is `title_ref` as the probe was given it - the name,
    the type, the year, the season, the network, the parent. That is enough
    for compliance to judge the topic and for the writer to look the fact up
    in the same article, and it is missing the two things this says out loud
    on the entry: the topic's `evidence` (its news leads, gathered at the
    scoring pass) and `rights_holder`.
    """
    kept = row.get("topic")
    if isinstance(kept, dict) and kept.get("topic_id"):
        return json.loads(json.dumps(kept)), False
    probe = row.get("fact_probe") if isinstance(row.get("fact_probe"), dict) else {}
    asked = probe.get("asked") if isinstance(probe.get("asked"), dict) else {}
    name = (row.get("title") or asked.get("name") or "").strip()
    if not name:
        return None, True
    kind = row.get("kind") or ("person" if asked.get("person") else "work")
    title_ref = {"name": name, "kind": kind, "type": asked.get("type"),
                 "year": asked.get("year"), "season": asked.get("season"),
                 "network": asked.get("network"),
                 "parent_work": asked.get("parent"),
                 "person": asked.get("person") or (name if kind == "person" else None),
                 "rights_holder": None}
    score = row.get("popularity_score")
    return {"topic_id": row["topic_id"], "title_ref": title_ref,
            "signal": {"popularity_score": score} if score is not None else {},
            "fact_probe": probe or None, "scenes": [], "evidence": {}}, True


def _reserve_name(row, topic=None):
    return (((topic or {}).get("title_ref") or {}).get("name")
            or row.get("title") or row.get("topic_id"))


def facet_command(name):
    """The exact line the operator runs to pay for a substitution."""
    return (f'scripts/fetch_youtube_signal.py "{name}" --facets '
            f'> /tmp/footage-<slug>.json')


def our_losses(batch):
    """The refusals of *this* stage that empty a shortlist slot: a topic taken
    out of `topics[]` with `no_source`. Step 5a's own refusals are not here -
    a topic that never entered the shortlist vacated nothing - and neither is
    the reserve."""
    return [r for r in (batch.get("skipped_topics") or [])
            if isinstance(r, dict) and r.get("reason_code") == REFUSAL_CODE
            and r.get("topic_id")]


def _walk_substitute(batch, topic, signal, want, limits):
    """Step 5b over one substituted topic: the same four sieves and the same
    floor every other topic of the batch went through. -> (outcome, notes)."""
    notes = []
    tid = topic.get("topic_id")
    ctx = f"topic {tid}"
    evidence = topic.setdefault("evidence", {})
    origin_config = footage_origin.load_config(_batch_channel(batch))
    candidates, pool = select_candidates(signal.get("videos") or [],
                                         topic.get("title_ref") or {}, want, limits=limits,
                                         config=origin_config)
    if footage_origin.has_own_capture(origin_config):
        # CF-0567: as in fill_batch - the footage base and the capture's record.
        evidence[FOOTAGE_BASE_KEY] = footage_base(candidates)
        write_capture_text(topic, candidates, origin_config)
    footing = graphic_footing(topic, origin_config)
    if footing is not None:
        # CF-0689: as in fill_batch - what the channel's own graphics stand on.
        evidence[GRAPHIC_FOOTING_KEY] = footing
    shortfall = shortfall_of(candidates, pool, want)
    evidence["youtube_video_ids"] = [c["video_id"] for c in candidates]
    evidence["footage_candidates"] = candidates
    evidence["footage_candidates_dropped"] = pool["wrong_work"]
    evidence["footage_candidate_shortfall"] = shortfall
    # `excluded_evidence` belongs to the scoring pass (CF-0272) and a restored
    # record may not carry it; an absent list is a `--check` problem, and an
    # empty one is the truth for a topic whose scoring exclusions nobody kept.
    evidence.setdefault("excluded_evidence", [])
    if not meets_refusal_floor(candidates, origin_config, footing):
        refuse(batch, tid, refusal_reason(shortfall, footing))
        batch["topics"] = [t for t in batch.get("topics") or []
                           if t.get("topic_id") != tid]
        notes.append(f"{ctx}: the substitute is refused too, "
                     f"{len(candidates)} footage candidate(s)"
                     + (f"; {footing['note']}" if footing else "")
                     + f" ({REFUSAL_CODE})")
        return OUTCOME_REFUSED, notes
    if not meets_refusal_floor(candidates, origin_config):
        notes.append(f"{ctx}: kept on own graphics - {kept_on_graphics_line(candidates, footing)}")
    if shortfall:
        notes.append(f"{ctx}: {len(candidates)} candidate(s) - {shortfall['reason']}")
    return OUTCOME_CANDIDATES, notes


def substitute_reserve(batch, signals, want=FOOTAGE_CANDIDATE_FLOOR, limits=None,
                       batch_dir=None, used=None):
    """Refill every shortlist slot this stage emptied, from the reserve, as
    far as the day's search quota reaches. -> notes.

    Idempotent: a loss already answered - with a substitute, with an empty
    slot, or with a substitution still waiting for its facet run - is never
    answered twice, and a reserve topic already spent is never offered again.
    """
    notes = []
    block = substitution_block(batch)
    quota = search_quota.quota_block(batch)
    limits = limits if limits is not None else channel_ceiling(_batch_channel(batch))
    price = quota.get("substitution_price_searches") or search_quota.FACET_RUN_SEARCHES
    # A substitution already decided and waiting for its facet run has not
    # spent its calls yet, and the day still owes them: it is held against the
    # remainder here, or a batch would decide five substitutions it can pay
    # for once.
    reserved = price * len([s for s in block["substitutions"]
                            if s.get("outcome") == OUTCOME_PENDING])

    def signal_for(tid, topic):
        key, signal = _match_signal(topic or {"topic_id": tid}, signals)
        if key is not None and used is not None:
            # the caller's "which searches matched a topic" set: a facet run
            # handed in for a reserve topic matched one, and is not the
            # operator searching for something this batch never carried.
            used.add(key)
        return key, signal

    def affordable():
        return quota.get("remaining_searches", 0) - reserved >= price

    def spend(tid, key, signal):
        # A substitution is another facet run of step 5b, so the same article
        # pays for it (CF-0368).
        search_quota.count_searches(quota, {tid: signal},
                                    article=search_quota.ARTICLE_FOOTAGE)
        search_quota.settle(quota, batch_dir=batch_dir)

    # 1. The entries already decided and waiting for their search. A pass that
    #    now has it completes the entry in place - one loss, one entry, for
    #    however many times this runs.
    for entry in block["substitutions"]:
        if entry.get("outcome") != OUTCOME_PENDING or not entry.get("topic_id"):
            continue
        row = next((r for r in (batch.get("skipped_topics") or [])
                    if r.get("topic_id") == entry["topic_id"]
                    and r.get("reason_code") == RESERVE_CODE), None)
        topic, restored = restore_reserve_topic(row) if row else (None, True)
        key, signal = signal_for(entry["topic_id"], topic)
        if topic is None or signal is None:
            continue
        reserved = max(0, reserved - price)
        _promote(batch, row, topic, entry.get("replaced"))
        spend(entry["topic_id"], key, signal)
        outcome, walked = _walk_substitute(batch, topic, signal, want, limits)
        entry.update({"outcome": outcome, "promoted": True, "restored": restored,
                      "candidates": len((topic.get("evidence") or {})
                                        .get("youtube_video_ids") or [])})
        notes.extend(walked)
        notes.append(f"RESERVE {entry['topic_id']} takes the slot of {entry['replaced']} "
                     f"({entry['replaced_reason_code']}) - {outcome}")

    # 2. The losses nothing has answered yet, in the order they were recorded.
    handled = {s.get("replaced") for s in block["substitutions"]}
    handled |= {u.get("replaced") for u in block["unmatched"]}
    # the reserve topics this batch has already spoken for - the parameter
    # `used` is the caller's set of *searches* that matched a topic and is a
    # different thing entirely.
    spent_reserve = {s.get("topic_id") for s in block["substitutions"] if s.get("topic_id")}
    queue = [r for r in our_losses(batch) if r.get("topic_id") not in handled]
    while queue:
        loss = queue.pop(0)
        tid = loss["topic_id"]
        if tid in handled:
            continue
        handled.add(tid)
        available = reserve_rows(batch, spent_reserve)
        empty = None
        if not available:
            empty = (RESERVE_EXHAUSTED_CODE,
                     f"topic {tid} was refused at step 5b ({loss.get('reason_code')}) and its "
                     f"shortlist slot cannot be refilled: "
                     + ("every `below_shortlist` topic of this batch has already been spent "
                        "on an earlier loss of it" if block["substitutions"] else
                        "step 5a left no `below_shortlist` topic in reserve at all")
                     + " (CF-0313). The slot stays empty - the batch goes to compliance one "
                       "topic short, and the fix is a longer `scope.shortlist_size`, not "
                       "anything this stage can do.")
        elif not affordable():
            empty = (QUOTA_EXHAUSTED_CODE,
                     f"topic {tid} was refused at step 5b ({loss.get('reason_code')}) and its "
                     f"slot is not refilled: walking a reserve topic through 5b is "
                     f"{quota.get('substitution_price_searches')} `search.list` call(s) "
                     f"({quota.get('substitution_price_units')} units) and the day has "
                     f"{quota.get('remaining_searches')} of "
                     f"{quota.get('daily_limit_searches')} left (CF-0288, CF-0313). "
                     f"{len(available)} reserve topic(s) are still there and the quota resets "
                     f"at {quota.get('resets_at')}, which is the next scheduled run's day and "
                     f"not this batch's: the slot stays empty and the batch goes to compliance "
                     f"one topic short rather than waiting for it (CF-0317).")
        if empty:
            code, reason = empty
            block["unmatched"].append({
                "replaced": tid, "replaced_reason_code": loss.get("reason_code"),
                "replaced_stage": loss.get("stage") or "trend-hunter",
                "topic_id": None, "reason_code": code, "stage": "trend-hunter",
                "at": "footage_candidates", "reason": reason,
                "remaining_searches": quota.get("remaining_searches"),
            })
            notes.append(f"RESERVE {tid} ({loss.get('reason_code')}) leaves a slot nobody "
                         f"fills ({code})")
            continue

        row = available[0]
        sub = row["topic_id"]
        spent_reserve.add(sub)
        topic, restored = restore_reserve_topic(row)
        entry = {
            "replaced": tid,
            "replaced_reason_code": loss.get("reason_code"),
            "replaced_stage": loss.get("stage") or "trend-hunter",
            "replaced_reason": loss.get("reason"),
            "topic_id": sub,
            "rank": row.get("rank"),
            "title": _reserve_name(row, topic),
            "reason_code": SUBSTITUTED_CODE,
            "stage": "trend-hunter",
            "at": "footage_candidates",
            "restored": restored,
            "promoted": False,
            "outcome": None,
            "candidates": None,
            "price_searches": quota.get("substitution_price_searches"),
            "reason": (f"{sub} takes the shortlist slot of {tid}, which this stage refused at "
                       f"step 5b with '{loss.get('reason_code')}'. {sub} is viable, has a "
                       f"fact (of any kind, CF-0439) and was only past `scope.shortlist_size` "
                       f"(CF-0264/CF-0313)."),
        }
        block["substitutions"].append(entry)

        if topic is None:
            # A reserve row nothing can be rebuilt from: no name, no probe. It
            # is not a topic, so the slot is free again and goes to the next
            # reserve topic - the same way the indexer treats a reserved id
            # `01-trend-hunter.json` does not name.
            entry["outcome"] = OUTCOME_UNUSABLE
            entry["reason"] += (f" The row records no topic to put back (no `topic`, no "
                                f"title, no probe), so nothing could be carried and the slot "
                                f"goes to the next reserve topic.")
            notes.append(f"RESERVE {sub} cannot be restored from its record ({OUTCOME_UNUSABLE})")
            queue.insert(0, loss)
            handled.discard(tid)
            continue

        key, signal = signal_for(sub, topic)
        if signal is None:
            # The facet run is a network call this module does not make. The
            # decision stands, the topic waits outside `topics[]` - it has no
            # candidates yet and a topic with none is not one this stage
            # carries - and the entry names the command that completes it.
            entry["outcome"] = OUTCOME_PENDING
            reserved += price
            entry["facet_search"] = facet_command(_reserve_name(row, topic))
            entry["reason"] += (f" Its footage search has not been run yet: "
                                f"`{entry['facet_search']}`, then re-run "
                                f"footage_candidates.py with that file in --signal and this "
                                f"entry is completed (it is not written twice).")
            notes.append(f"RESERVE {sub} takes the slot of {tid} "
                         f"({loss.get('reason_code')}) - {OUTCOME_PENDING}: run "
                         f"{entry['facet_search']}")
            continue
        _promote(batch, row, topic, tid)
        spend(sub, key, signal)
        outcome, walked = _walk_substitute(batch, topic, signal, want, limits)
        entry.update({"outcome": outcome, "promoted": True,
                      "candidates": len((topic.get("evidence") or {})
                                        .get("youtube_video_ids") or [])})
        notes.extend(walked)
        notes.append(f"RESERVE {sub} takes the slot of {tid} ({loss.get('reason_code')}) "
                     f"- {outcome}")
        if outcome == OUTCOME_REFUSED:
            # A substitute this stage refuses empties the same slot again, so
            # it goes back into the queue as a loss of its own - and pays for
            # the next facet run out of the same day.
            queue.append(next(r for r in our_losses(batch) if r["topic_id"] == sub))

    block["remaining"] = [r["topic_id"] for r in reserve_rows(batch, spent_reserve)]
    quota["substitutions_made"] = len([s for s in block["substitutions"]
                                       if s.get("promoted")])
    search_quota.settle(quota, batch_dir=batch_dir)
    batch[search_quota.QUOTA_KEY] = quota
    batch[SUBSTITUTION_KEY] = block
    return notes


def _promote(batch, row, topic, replaced=None):
    """The reserve topic stops being reserve: its `below_shortlist` record
    leaves `skipped_topics[]` (a spare that was used is not a spare, and the
    funnel counts that column in its own column, not among the losses), it
    goes into `topics[]` after the topics that outscored it - which keeps the
    list in descending score order, because everything in reserve ranked below
    everything in the shortlist - and the topic it replaced gains the one fact
    that says where its slot went."""
    batch["skipped_topics"] = [r for r in (batch.get("skipped_topics") or [])
                               if not (r.get("topic_id") == topic.get("topic_id")
                                       and r.get("reason_code") == RESERVE_CODE)]
    for r in batch.get("skipped_topics") or []:
        if replaced and r.get("topic_id") == replaced:
            r["replaced_by_topic"] = topic.get("topic_id")
    batch.setdefault("topics", []).append(topic)
    return topic


# --------------------------------------------------------------------------
# checking - the floor, stated as a check so that "three candidates" is a
# property of the artifact and not of how the run went
# --------------------------------------------------------------------------

def _graphic_footing_holds(topic):
    """`--check`'s reading of CF-0689's pass off a written topic (no channel
    config at hand): its `evidence.own_graphic_footing` - which only a
    channel with the `own_graphic` origin writes - says the floor was met,
    and the topic's support text, read again, still holds that many
    quotable facts."""
    footing = (topic.get("evidence") or {}).get(GRAPHIC_FOOTING_KEY)
    if not isinstance(footing, dict) or footing.get("origin") != footage_origin.OWN_GRAPHIC:
        return False
    if not footing.get("meets_floor"):
        return False
    # CF-0809: the same count as the footing's - another edition's article
    # gives none
    return len(subject_facts(topic, _own_graphic.own_graphic)[0]) >= GRAPHIC_FACT_FLOOR


def check_topic(topic, ctx="topic", want=FOOTAGE_CANDIDATE_FLOOR, limits=None):
    evidence = topic.get("evidence") or {}
    ids = evidence.get("youtube_video_ids")
    problems = []
    if not isinstance(ids, list) or not all(isinstance(i, str) and i.strip() for i in ids):
        return [f"{ctx}: evidence.youtube_video_ids is not a list of video ids"]
    if len(set(ids)) != len(ids):
        problems.append(f"{ctx}: duplicate ids in evidence.youtube_video_ids - "
                        f"one upload is one candidate")
    shortfall = evidence.get("footage_candidate_shortfall")
    records = evidence.get("footage_candidates")

    if len(ids) < CANDIDATE_REFUSAL_FLOOR and not (
            ids and isinstance(records, list) and _own_capture_base(records)) and not (
            _graphic_footing_holds(topic)):
        what = ("no footage candidate at all" if not ids
                else f"{len(ids)} footage candidate - the two-source gate needs two canonical "
                     f"sources and one candidate cannot produce two (CF-0309)")
        problems.append(f"{ctx}: {what} - such a topic cannot be carried; take it out of "
                        f"topics[] and record it in skipped_topics[] with reason_code "
                        f"{REFUSAL_CODE!r}")
        if not ids:
            # nothing left to read; with one candidate the record itself is
            # still checked, so an artifact does not hide a second fault
            # behind the first.
            return problems

    if not isinstance(records, list):
        problems.append(f"{ctx}: evidence.footage_candidates is missing - the candidates were "
                        f"not picked by footage_candidates.py, so nothing says what they are "
                        f"or that they are different cuts")
        records = []
    else:
        if [r.get("video_id") if isinstance(r, dict) else None for r in records] != ids:
            problems.append(f"{ctx}: footage_candidates is not parallel to youtube_video_ids - "
                            f"one record per id, same order, same strings")
        for i, record in enumerate(records):
            rctx = f"{ctx} footage_candidates[{i}]"
            if not isinstance(record, dict):
                problems.append(f"{rctx}: not an object")
                continue
            # CF-0302: a record written before the duration ceiling carries
            # every other key and no `duration_seconds`. That is not a
            # problem to report - the field is younger than the artifact, and
            # the indexer measures such a candidate itself before it
            # downloads it - so the record is judged as if the field were
            # there. The same leniency `origin` got on CF-0297, for the same
            # reason: `--check` over an old batch must not go red over a
            # field nobody could have written.
            keys = set(record) | set(YOUNGER_KEYS)
            if keys == set(CANDIDATE_KEYS) - {"origin"}:
                problems.append(f"{rctx}: no `origin` - this batch was written before CF-0297, "
                                f"so nothing on its candidates says whether they are the work's "
                                f"own footage or somebody's video about it; re-run "
                                f"footage_candidates.py --write over its footage searches")
                continue
            if keys != set(CANDIDATE_KEYS):
                problems.append(f"{rctx}: keys {sorted(record)} != {sorted(CANDIDATE_KEYS)}")
                continue
            if record["kind"] not in KINDS:
                problems.append(f"{rctx}: kind {record['kind']!r} is not one of {list(KINDS)}")
            if record["nature"] not in NATURES:
                problems.append(f"{rctx}: nature {record['nature']!r} is not one of {list(NATURES)}")
            if record["origin"] not in ORIGINS:
                problems.append(f"{rctx}: origin {record['origin']!r} is not one of {list(ORIGINS)}")
            elif record["origin"] == "unofficial":
                problems.append(f"{rctx}: {record['video_id']} is an 'unofficial' candidate - an "
                                f"upload about the work is not offered as footage of it "
                                f"(CF-0297); it belongs in footage_candidates_dropped with "
                                f"reason_code {UNOFFICIAL_CODE!r}")
            # CF-0817: a host show is offered only under the exception.
            problems += [f"{rctx}: {p}" for p in host_show.check_record(record)]
            # CF-0662: a candidate whose licence the channel's rule refused is
            # not a candidate at all.
            lic = record.get(LICENCE_KEY)
            if lic is not None and not isinstance(lic, dict):
                problems.append(f"{rctx}: {LICENCE_KEY} is not an object (CF-0662)")
            elif lic and lic.get("judged") and not lic.get("accepted"):
                problems.append(f"{rctx}: {record['video_id']} is under a licence this channel "
                                f"refuses ({lic.get('short_name')!r}: {lic.get('reason')}) - it "
                                f"belongs in footage_candidates_dropped with reason_code "
                                f"{LICENCE_REFUSED_CODE!r} (CF-0662)")
            # CF-0665: an archive candidate is a direct download or nothing.
            if (str(record.get("video_id") or "").startswith(ARCHIVE_ID_PREFIXES)
                    or record.get(ARCHIVE_KEY)) and not (
                    isinstance(record.get("download_url"), str)
                    and record["download_url"].startswith("https://")):
                problems.append(f"{rctx}: {record['video_id']} is an archive candidate without an "
                                f"https download_url - the indexer has nothing to fetch (CF-0665)")
            # CF-0567: an own capture names its recording - the indexer looks
            # for it there first - and what was recorded.
            if footage_origin.is_own_capture(record):
                if not str(record.get("video_id") or "").startswith(OWN_CAPTURE_HEAD):
                    problems.append(f"{rctx}: an own capture's id is {OWN_CAPTURE_HEAD}<id>, not "
                                    f"{record.get('video_id')!r} (CF-0567)")
                if not (isinstance(record.get(CAPTURE_FILE_KEY), str)
                        and record[CAPTURE_FILE_KEY].endswith(".mp4")):
                    problems.append(f"{rctx}: {record['video_id']} is an own capture without its "
                                    f"recording (`{CAPTURE_FILE_KEY}`, an .mp4 path) - the indexer "
                                    f"ingests a recording that already exists (CF-0567)")
                if not str(record.get("source_url") or "").startswith("https://"):
                    problems.append(f"{rctx}: {record['video_id']} is an own capture without the "
                                    f"https page it recorded (`source_url`, CF-0567)")
            # CF-0302. `null` is legal and means "nobody measured it" - a
            # live stream, a premiere, a search older than the field. A
            # number has to be a positive count of seconds, and it has to be
            # under the ceiling its nature is held to: an upload over it is
            # not a candidate at all.
            raw = record.get(DURATION_KEY)
            if raw is not None and duration_of(record) is None:
                problems.append(f"{rctx}: {DURATION_KEY} {raw!r} is neither null nor a "
                                f"positive number of seconds (CF-0302)")
            else:
                seconds, limit = over_ceiling(record, record.get("nature"), limits)
                if seconds is not None:
                    problems.append(
                        f"{rctx}: {record['video_id']} is {int(seconds)} s long, over the "
                        f"{int(limit)} s ceiling for nature {record.get('nature')!r} "
                        f"({CEILING_KEY}, CF-0302) - it is not offered as a candidate; it "
                        f"belongs in footage_candidates_dropped with reason_code "
                        f"{TOO_LONG_CODE!r}")

    # CF-0272. The uploads the relevance rule took out of the pool, and the
    # exclusions the scoring pass made on the same rule. Both are lists that
    # may be empty and neither may be absent: "nothing was excluded" and "the
    # exclusions were never written down" are the two states this task exists
    # to tell apart - on 2026-09-18T1058Z the operator excluded seven uploads
    # across four topics and the artifact recorded none of it.
    if isinstance(evidence.get("footage_candidates"), list):
        dropped = evidence.get("footage_candidates_dropped")
        problems.extend(check_exclusions(
            dropped, f"{ctx}: footage_candidates_dropped",
            remedy="re-run footage_candidates.py --write, which writes it (empty or not)"))
        if isinstance(dropped, list):
            overlap = {r.get("video_id") for r in dropped if isinstance(r, dict)} & set(ids)
            if overlap:
                problems.append(f"{ctx}: {sorted(overlap)} are both candidates and dropped - "
                                f"an upload is one or the other")
        problems.extend(check_exclusions(
            evidence.get("excluded_evidence"), f"{ctx}: excluded_evidence",
            remedy="run topic_relevance.py over the scoring pass's search output "
                   "(SKILL.md step 4) and copy its `excluded_evidence` in, [] included"))

    natures = pool_natures(records)
    thin = falls_short(records, want) if records else len(ids) < want
    if thin and not isinstance(shortfall, dict):
        problems.append(
            f"{ctx}: {len(ids)} candidate(s) of {len(natures) or '?'} footage nature(s), floor is {want} "
            f"in at least {NATURE_FLOOR} natures, and evidence.footage_candidate_shortfall says "
            f"nothing - a thin topic has to be visible in the artifact (CF-0129), not look like "
            f"a topic nobody searched for")
    elif isinstance(shortfall, dict):
        missing = [k for k in ("wanted", "found", "reason") if k not in shortfall]
        if missing:
            problems.append(f"{ctx}: footage_candidate_shortfall is missing {missing}")
        elif shortfall.get("found") != len(ids):
            problems.append(f"{ctx}: footage_candidate_shortfall says found="
                            f"{shortfall.get('found')} for {len(ids)} ids")
        if not thin:
            problems.append(f"{ctx}: footage_candidate_shortfall is recorded, but the topic has "
                            f"{len(ids)} candidates in {len(natures)} natures - nothing fell short")
    return problems


def check_batch(batch, want=FOOTAGE_CANDIDATE_FLOOR, limits=None):
    problems = []
    topics = batch.get("topics") or []
    limits = limits or channel_ceiling(_batch_channel(batch))
    for topic in topics:
        problems.extend(check_topic(topic, f"topic {topic.get('topic_id', '?')}", want, limits))
    ids = {t.get("topic_id") for t in topics}
    skipped = batch.get("skipped_topics")
    if skipped is not None and not isinstance(skipped, list):
        return problems + ["skipped_topics is not a list"]
    for i, row in enumerate(skipped or []):
        ctx = f"skipped_topics[{i}]"
        if not isinstance(row, dict) or not row.get("topic_id"):
            problems.append(f"{ctx}: no topic_id")
            continue
        if not (row.get("reason") or "").strip():
            problems.append(f"{ctx} ({row['topic_id']}): no reason - a refusal without a reason "
                            f"is a silent loss")
        if not row.get("reason_code"):
            problems.append(f"{ctx} ({row['topic_id']}): no reason_code; this stage refuses with "
                            f"{REFUSAL_CODE!r} (shared/runlog/funnel.py FUNNEL_CODES)")
        if row["topic_id"] in ids:
            problems.append(f"{ctx} ({row['topic_id']}): also in topics[] - a topic is either "
                            f"carried or refused, not both")
    return problems


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _batch_path(arg):
    path = Path(arg).expanduser()
    return path / "01-trend-hunter.json" if path.is_dir() else path


def missing_signal_message(raw):
    """The refusal for a `--signal` value that names no file and binds no
    topic (no `:` left in it). When it reads like a file name glued to the
    rest of a topic id (`footage-003.jsonvsm-2026-10-25-003`) the likely
    cause is named: a shell modifier ate `<dir>/` and the colon."""
    raw = str(raw)
    msg = f"--signal {raw}: no signal file {raw}"
    head, dot, tail = raw.partition(".json")
    if dot and tail:
        msg += (f" - it reads as the file `{Path(head).name}.json` glued to `{tail}`: "
                "the `:<topic_id>` binding was lost before the call. In zsh "
                "`$f:t...` is `$f` with the `:t` (tail) modifier, which drops the "
                "directory and the colon; write the binding braced and quoted, "
                '`--signal "${f}:<topic_id>"` (CF-0862)')
    else:
        msg += (" - no `:<topic_id>` binding is left in it either; a shell loop "
                'writes it braced and quoted, `--signal "${f}:${t}"` (CF-0862)')
    return msg


def load_signals(args_signals):
    """`--signal path` / `--signal path:topic_id` -> {key: signal output}.
    The key is the topic_id when one was given, else the file's `query`."""
    signals = {}
    for raw in args_signals or []:
        path, _, topic_id = str(raw).rpartition(":")
        if not path or not Path(path).expanduser().exists():
            # CF-0198: the `:topic_id` suffix is read off the file existing;
            # when neither reading names a file, say which file is missing
            # instead of opening `<path>:<topic>` and reporting that.
            if path and not Path(str(raw)).expanduser().exists():
                raise FileNotFoundError(f"--signal {raw}: no signal file {path}")
            path, topic_id = str(raw), ""
            if not Path(path).expanduser().exists():
                # CF-0862: no colon left and no file - the binding was eaten
                # before the script saw it. The 0934Z crash: zsh read
                # `$f:lf-...` as `$f` + the `:t` (tail) modifier, so the
                # argument came in as `footage-003.jsonvsm-2026-10-25-003`.
                raise FileNotFoundError(missing_signal_message(path))
        data = json.load(open(Path(path).expanduser()))
        key = topic_id or data.get("query") or path
        signals[key] = merge_signals(signals[key], data) if key in signals else data
    return signals


def merge_signals(first, second):
    """CF-0361: two footage signals of one topic - the official channels'
    feeds (`fetch_channel_feeds.py`, 0 searches) and, where the feeds were not
    enough, the facet search - read as one pool. A video both found keeps the
    first record and the union of the labels; the search count is the sum,
    so the quota ledger charges the facet run and not the feed."""
    videos, index = [], {}
    for sig in (first, second):
        for v in (sig or {}).get("videos") or []:
            vid = v.get("video_id")
            if vid in index:
                have = index[vid]
                have["facets"] = list(dict.fromkeys((have.get("facets") or [])
                                                    + (v.get("facets") or [])))
                continue
            v = dict(v)
            if vid:
                index[vid] = v
            videos.append(v)
    sources = []
    for sig in (first, second):
        for s in (sig or {}).get("sources") or [(sig or {}).get("source")]:
            if s and s not in sources:
                sources.append(s)
    return {
        "source": sources[0] if len(sources) == 1 else "+".join(sources),
        "sources": sources,
        "query": (first or {}).get("query") or (second or {}).get("query"),
        "facets_used": list(dict.fromkeys(((first or {}).get("facets_used") or [])
                                          + ((second or {}).get("facets_used") or []))),
        "searches": (search_quota.searches_of(first) + search_quota.searches_of(second)),
        # CF-0661: the feed read's account rides along with the merged pool.
        "feed_read": (first or {}).get("feed_read") or (second or {}).get("feed_read"),
        # CF-0665: what the archives answered, likewise.
        "archive_read": (first or {}).get("archive_read") or (second or {}).get("archive_read"),
        # CF-0567: what the own-capture pass did, likewise.
        "capture_read": (first or {}).get("capture_read") or (second or {}).get("capture_read"),
        "videos": videos,
    }


def main(argv=None):
    # CF-0343: `--supplement <request.json|dir>` is the supplement half of
    # this stage - footage of an uncovered anchor's entity for a thin pool's
    # request (`footage_supplement.py`). It takes no batch positional: the
    # request knows its batch by where it lies.
    raw = list(sys.argv[1:] if argv is None else argv)
    if any(a == "--supplement" or a.startswith("--supplement=") for a in raw):
        import footage_supplement
        return footage_supplement.main(raw)
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch", help="batch directory or its 01-trend-hunter.json")
    ap.add_argument("--signal", action="append",
                    help="a fetch_youtube_signal.py --facets output; repeatable; "
                         "`path:topic_id` binds it to a topic explicitly")
    ap.add_argument("--want", type=int, default=FOOTAGE_CANDIDATE_FLOOR,
                    help=f"candidates per topic (default {FOOTAGE_CANDIDATE_FLOOR})")
    ap.add_argument("--write", action="store_true", help="write the candidates into the batch file")
    ap.add_argument("--check", action="store_true", help="validate the batch's candidates only")
    # CF-0313
    ap.add_argument("--searches-spent", type=int, default=None, metavar="N",
                    help="`search.list` calls this quota day has already spent outside this "
                         "batch's run log - the scoring pass, an earlier batch of the same "
                         "Pacific day. Added to what this batch is known to have spent, and "
                         "the remainder is what pays for a substitution (CF-0288)")
    args = ap.parse_args(argv)

    path = _batch_path(args.batch)
    if not path.exists():
        print(f"no {path}", file=sys.stderr)
        return 2
    batch = json.load(open(path))

    notes = []
    if args.check or not args.signal:
        if not args.check:
            print("no --signal given: checking the batch's existing candidates only",
                  file=sys.stderr)
        problems = check_batch(batch, args.want)
        # CF-0444: a check reads the written lists for the same alarm a fill
        # raises - a batch written before this task carries no SHARED_KEY,
        # and 0705Z is exactly such a batch. A warning, never a problem.
        notes = shared_lines(shared_candidate_lists(batch))
    else:
        # CF-0862: a signal that names no file stops the call before anything
        # is read or written, with the refusal on stderr - not a traceback.
        try:
            signals = load_signals(args.signal)
        except FileNotFoundError as exc:
            print(exc, file=sys.stderr)
            return 2
        problems, notes = fill_batch(batch, signals, args.want,
                                     batch_dir=path.parent,
                                     searches_before=args.searches_spent)
        if args.write:
            with open(path, "w") as fh:
                json.dump(batch, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
        else:
            print(json.dumps({t.get("topic_id"): t["evidence"]["footage_candidates"]
                              for t in batch.get("topics") or []
                              if (t.get("evidence") or {}).get("footage_candidates")},
                             ensure_ascii=False, indent=2))

    topics = batch.get("topics") or []
    ids = [i for t in topics for i in (t.get("evidence") or {}).get("youtube_video_ids") or []]
    thin = [t.get("topic_id") for t in topics
            if (t.get("evidence") or {}).get("footage_candidate_shortfall")]
    # CF-0272: what the relevance rule took out is part of the summary, in
    # `--check` as much as in a fill - a check that reads a written batch and
    # says nothing about its drops is how the Harbourlights uploads survived two
    # batches.
    dropped = [r for t in topics
               for r in ((t.get("evidence") or {}).get("footage_candidates_dropped") or [])]
    unofficial = [r for r in dropped if r.get("reason_code") == UNOFFICIAL_CODE]
    too_long = [r for r in dropped if r.get("reason_code") == TOO_LONG_CODE]
    not_footage = [r for r in dropped if r.get("reason_code") == NOT_FOOTAGE_CODE]
    other = [r for r in dropped if r.get("reason_code") == OTHER_INSTALLMENT_CODE]
    licence = [r for r in dropped if r.get("reason_code") == LICENCE_REFUSED_CODE]
    hosts = [r for r in dropped if r.get("reason_code") == HOST_SHOW_CODE]
    print(f"{path.name}: {len(topics)} topics, {len(ids)} candidates, "
          f"{len(dropped) - len(unofficial) - len(too_long) - len(not_footage) - len(other) - len(licence) - len(hosts)} "
          f"dropped as another work ({WRONG_WORK_CODE}), "
          f"{len(other)} dropped as another installment ({OTHER_INSTALLMENT_CODE}), "
          f"{len(unofficial)} dropped as not footage of it ({UNOFFICIAL_CODE}), "
          f"{len(too_long)} dropped as too long ({TOO_LONG_CODE}, ceiling "
          f"{channel_ceiling(_batch_channel(batch))}), "
          f"{len(not_footage)} dropped as a talk about the work ({NOT_FOOTAGE_CODE}), "
          + (f"{len(licence)} dropped under a licence the channel refuses "
             f"({LICENCE_REFUSED_CODE}), " if licence else "")
          + f"{len(hosts)} dropped as a host show ({HOST_SHOW_CODE}), "
          + f"{len(thin)} under the floor of {args.want}, "
          f"{len(batch.get('skipped_topics') or [])} refused, {len(problems)} problems",
          file=sys.stderr)
    # CF-0313: what the reserve did for the slots this stage emptied, and what
    # the day's quota has left for the next one. Printed in `--check` too - a
    # slot left empty for want of quota is the fact CF-0288 went looking for.
    block = batch.get(SUBSTITUTION_KEY)
    if isinstance(block, dict):
        subs = [s for s in block.get("substitutions") or [] if isinstance(s, dict)]
        if subs:
            print(f"  {len(subs)} slot(s) refilled from the reserve ({SUBSTITUTED_CODE}): "
                  + ", ".join(f"{s.get('topic_id')} for {s.get('replaced')} "
                              f"[{s.get('outcome')}]" for s in subs)
                  + f"; {len(block.get('remaining') or [])} reserve topic(s) left",
                  file=sys.stderr)
        for row in block.get("unmatched") or []:
            print(f"  slot of {row.get('replaced')} stays empty "
                  f"({row.get('reason_code')})", file=sys.stderr)
    if isinstance(batch.get(search_quota.QUOTA_KEY), dict):
        quota = batch[search_quota.QUOTA_KEY]
        # CF-0368: settled again here so that `--check` on a written batch says
        # what the day went on too - the run log is the whole measurement and
        # reading it costs nothing. Nothing is written by a check.
        search_quota.settle(quota, batch_dir=path.parent)
        print("  " + search_quota.line(quota), file=sys.stderr)
        print("  " + quota["summary_line"], file=sys.stderr)
        for row in search_quota.article_lines(quota):
            print(row, file=sys.stderr)
        # The line the root's RUN_SUMMARY carries, as an event, because
        # `shared/runlog/summary.py` reads the events and nothing else.
        search_quota.record_event(quota, runlog=runlog, batch_dir=path.parent,
                                  step="footage-candidates")
    if args.check:
        for topic in topics:
            for record in (topic.get("evidence") or {}).get("footage_candidates_dropped") or []:
                print(f"  {topic.get('topic_id')}: dropped {record.get('video_id')} "
                      f"{record.get('title')!r} [{record.get('channel_title')}] "
                      f"{record.get('view_count')} views", file=sys.stderr)
    for line in notes + problems:
        print(f"  {line}", file=sys.stderr)
    return 1 if problems else 0


@runlog.script("trend-hunter", "footage-candidates", name="footage_candidates.py")
def cli(argv=None):
    """The command-line entry: main()'s return code becomes the exit code
    *inside* the run event, so a non-zero result is recorded as `failed`
    (CF-0107). Tests call main() directly and leave no event."""
    sys.exit(main(argv))


if __name__ == "__main__":
    cli()
