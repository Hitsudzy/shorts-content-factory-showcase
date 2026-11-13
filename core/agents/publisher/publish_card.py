#!/usr/bin/env python3
"""CF-0017: the publication card of an accepted video - title, description and
tags built from the video's script, checked before the user sees them.

The grill of 2026-10-06 (2.0 "Publisher"): the machine does everything from
the acceptance to the Studio schedule, and the user says one "yes" per video -
the acceptance, given with the video *and its card* in front of them. So the
card is built when the video is shown for acceptance, and the acceptance is
the "yes" to publish exactly what the card says (CF-0018 fills Studio from its
fields later).

**The card is the note.** `publish/<channel>/<bucket>/<slug>.md` is what
`publish_note.py` reads, what `note_claims.py` checks and what `upload.py`
uploads, and `shared/runlog/publish_layout.py` already calls it the card
(`publish_layout.card()`). This module writes that file - it adds no second
format beside it:

    # <slug> — карточка публикации
    Ролик / Батч `pipeline/<channel>/<batch>` · сценарий `<id>` · тема `<id>`
    ## Название        title + the channel's suffix (`publisher.title_suffix`)
    ## Описание        exactly three blocks (docs/publisher-metadata-rules.md):
                         1. what the video is about - drafted from the script;
                         2. the source line with the real source of
                            `production_fact.source_url`, and the fact-check
                            line of every `comparison_line_delivered[]` of
                            05-video-editor.json (CF-0116/CF-0157: the plate in
                            the video says the fact check is in the
                            description - without it the plate lies); the
                            credit lines (CF-0636 texts, CF-0664 footage);
                            CF-0593: last, the affiliate link and its
                            disclosure - only on a channel whose slot is on
                            and only for a video about that very product
                            (`shared/affiliate.py`, docs/channel-data.md
                            «Affiliate links»);
                         3. the hashtags.
    ## Утверждения     note_claims.py (CF-0555) - written only when it passed
    ## Теги
    ## Публикация      no slot yet: the operator writes the time, then
                       `runlog publish assign`
    ## Настройки       the channel's lines
    ## Карточка        status (ready / not ready), source, fact checks, the
                       claim check's verdict, a machine marker
                       `<!-- publish_card {...} -->` for CF-0018

**Where the words come from.** Block 2, block 3's first hashtag and the
channel's constant hashtags (never cut by `max`, they stand last - CF-0678),
the tags' names and every channel-facing string (suffix, the source-line template, the
fact-check template, settings, hashtag count) are put together by code from
the script and `channels/<channel>.json` -> `publisher`; nothing about any one
channel is written here. The title, block 1 and the rest of the hashtags and
tags are *drafted*: by the model (`claim_judge.Asker`, the same answer command
and cache as the claim judge, kind `publish_card_draft`), or by the operator in
a JSON file (`--draft`, `{"title", "about", "hashtags", "tags"}`). Either way
the draft is only a proposal: what may stand in a card is decided by the
checks below and by `note_claims.py`, never by who wrote the draft. A model
draft the card's checks refuse is redrafted once, told what was refused; a
model draft whose title or description the claim check refuses (the video's
own claims passed) is redrafted once more, told the judge's reason and what
was missing, and checked again from the start (CF-0728). The draft prompt
ties every statement to a claim the script declares or the source's own
sentence (CF-0728, `DRAFT_RULES`).

**Refused, not built** (`CardError`, exit 2 - no file is written):

* no `production_fact.source_url`, or one that is not a full http(s) URL -
  block 2 needs the real source, and a card without it is the placeholder
  defect in another form;
* a `comparison_line_delivered[]` entry without its wording or its full
  `source_url` - the plate promises a fact check the card cannot give;
* the channel has no `publisher` block, or one missing a template;
* CF-0664: the video shows footage whose licence asks for credit
  (`05` `videos[].footage_credits[]`, `attribution: required`) and the row
  has no concrete credit line (`credit: null` - only the origin's rule is
  known), or the channel has no words for what the licence asks
  (`publisher.footage_attribution_line`, `footage_changes_note`,
  `footage_share_alike_line`).

**Built, not ready** (exit 1 - the file is written, status `not_ready`, the
problems named in `## Карточка`): the title over the limit or stronger than
the source (a word of the language's strength list - "confirmed",
"officially", "first", ... - that the source's own sentence does not use: rule
1, the title is no stronger than `sourcing_caveat` allows); the placeholder
`[SOURCE NAME`; not exactly three blocks; a URL or a hashtag inside block 1;
the fact check missing from block 2; the YouTube limits of `publish_note`;
CF-0671: a phrase an outlet's terms forbid in an AI product (NASA's «according
to NASA», «NASA confirms», «NASA-approved», ... - the channel's fact-sources
`ai_output_terms`, matched by `shared/channel_data.py` `attribution_hits`) in
the title or the description - a neutral «Source: NASA», the footage credit
«Footage: NASA · <url>» and NASA as the story's subject pass; and
the claim check of CF-0555 not passed (or not asked - `NOT_LOGGED_IN`, exit 3).

**Ready** (exit 0): all of the above clean, the claim check passed and its
block `## Утверждения` written for exactly this title and description.
`card_state()` answers "is this card ready" for whoever reads it next (the
fingerprint of the claim block must still match - a hand edit of the title or
the description after the build makes the card not ready until it is checked
again).

**Accepted by the user's ruling** (CF-0747, the user's word 13.10 on
the-social-reckoning: «ролик мы берем, описание и название подогнать под
правду»): a card built not ready ONLY because claims of the video's own
narration or on-screen text failed the claim check (`VIDEO_FIELDS`: hook,
commentary, payoff, on_screen/plate - the video is rendered, its words cannot
be changed by a card) may be taken by the user's ruling: a `## Решение
пользователя` section (`RULING_SECTION`) with his words, by, via, the time and
the failing claims, and its marker (`RULING_MARKER`). Never when a claim of
the title, the description or the tags failed, nor for any other problem of
the card (`ruling_check`). `card_state()` stays "machine-ready only";
`card_status()` says `ready` / `ruled` / `not_ready` and `placeable()` is what
the placing paths (`place`, `publish_stash.py`, `studio_fields.py`,
`upload.py`) read: ready or ruled. A ruled card whose title or description
changed after the ruling is not placeable (the ruling's fingerprint); a
rebuild writes a new card without the section. The ruling itself is
`card_center.py ruling-plan / ruling-confirm`.

Command line:

    python3 agents/publisher/publish_card.py build <batch_dir> <slug|script_id>
        [--draft FILE] [--out FILE] [--root DIR] [--answer-cmd CMD] [--model M]
        [--timeout S] [--jobs N] [--no-claims] [--json]
            # default out: <batch>/work/publish-card/<slug>.md; prints the
            # short view to show the user with the video
    python3 agents/publisher/publish_card.py show <card.md>
    python3 agents/publisher/publish_card.py place <batch_dir> <slug>
        [--channel C] [--day YYYY-MM-DD|_queue] [--replace] [--root DIR] [--no-slot]
            # after the acceptance: the ready card goes next to the video
            # acceptance.place() put into publish/<channel>/<bucket>/; from
            # _queue/ it goes on into the channel's nearest free slot
            # (CF-0587, publish_queue.py): `## Публикация` + the day folder
"""
import argparse
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

AGENT = Path(__file__).resolve().parent
ROOT = AGENT.parent.parent
for _p in (AGENT, ROOT / "shared" / "runlog"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import note_claims                                              # noqa: E402
import publish_layout                                           # noqa: E402
import publish_note                                             # noqa: E402
import publish_queue                                            # noqa: E402

RULE = "CF-0017"
SECTION = "Карточка"
MARKER = "publish_card"
MARK_RE = re.compile(r"<!--\s*" + MARKER + r"\s+(\{.*?\})\s*-->", re.S)
CARD_DIR = Path("work") / "publish-card"
DRAFT_KIND = "publish_card_draft"
DRAFT_RULES = "CF-0728/2"     # the draft prompt's rules; a change asks cached drafts again
READY, NOT_READY = "ready", "not_ready"
RULED = "ruled"                       # CF-0747: taken by the user's ruling
RULING_TASK = "CF-0747"
RULING_SECTION = "Решение пользователя"
RULING_MARKER = "publish_card_ruling"
RULING_RE = re.compile(r"<!--\s*" + RULING_MARKER + r"\s+(\{.*?\})\s*-->", re.S)
# the video's own words: the narration (hook, commentary, payoff) and the
# on-screen text (05's plate - `on_screen` in the claim check)
VIDEO_FIELDS = ("hook", "commentary", "payoff", "on_screen", "plate")
PROBLEM_LINE_RE = re.compile(r"^- `([^`]+)` \[([^\]]*)\]\s?(.*?)(?: → .*)?$")
EXIT_READY, EXIT_NOT_READY, EXIT_REFUSED, EXIT_NOT_ASKED = 0, 1, 2, 3

# Words a title may carry only when the source's own sentence carries them:
# each one makes a claim stronger than "a source reports X". Per language, not
# per channel; a channel adds to its language's list with
# `publisher.strength_words_extra`.
STRENGTH_WORDS = {
    "en": ("confirmed", "confirms", "confirm", "official", "officially", "proof", "proves",
           "proven", "secret", "secretly", "leaked", "exclusive", "guaranteed", "definitely",
           "always", "never", "every", "entire", "entirely", "only", "first", "ever",
           "biggest", "largest", "record", "all-time", "banned", "truth"),
}
# What a model draft gets one more try for - problems of the drafted words, not
# of the script or the channel.
REDRAFTABLE = {"title_too_long", "title_carries_tag_or_url", "about_too_long",
               "about_carries_tag_or_url", "description_not_three_blocks", "source_placeholder",
               "too_few_hashtags", "angle_brackets", "title_stronger_than_source",
               "attribution_forbidden"}
URL_RE = re.compile(r"https?://\S+", re.I)
HASHTAG_IN_TEXT_RE = re.compile(r"(?<!\S)#[^\s#]+")
REQUIRED_TEMPLATES = (("source_line", ("{source}", "{url}")),
                      ("fact_check_line", ("{wording}", "{url}")))
# CF-0636: a text read under a licence that wants its source credited - TVmaze's
# episode descriptions, CC BY-SA 4.0 - puts one line into block 2 when the
# video's claims quote it. The words are the channel's (`publisher.
# attribution_line`, with {source}, {license}, {url}); the source, its licence
# and the link are the piece's own (`shared/tvmaze/tvmaze_api.episode_piece`).
ATTRIBUTION_KEY = "attribution_line"
ATTRIBUTION_FIELDS = ("{source}", "{url}")
CREDITED_KINDS = ("tvmaze_episode",)       # = shared/tvmaze/tvmaze_api.KIND_EPISODE
CREDITED_HOSTS = ("tvmaze.com",)
# CF-0664 (PUB-1, docs/science-footage.md): the footage a video shows under a
# licence or from an origin that asks for credit - `05-video-editor.json`
# `videos[].footage_credits[]` (VE-1: one row per judged source on screen, in
# order of first use) - puts one line into block 2 per source whose
# `attribution` is `required` or `requested`. The words are the channel's:
#   `publisher.footage_attribution_line` - {credit}, {url}; optional
#       {license}, {license_url}, {changes}. A field with nothing to say
#       (public domain has no licence to name) leaves its `·`-segment out;
#   `publisher.footage_changes_note` - what was done to the footage, filled
#       into {changes} for a licence that asks that changes be indicated;
#   `publisher.footage_share_alike_line` - {license}, {license_url}: the
#       video, an adaptation of share-alike footage, is under that licence.
# A `required` credit refuses the card when the channel cannot say it, or
# when the row has no concrete credit line (`credit: null` - only the
# origin's rule is known): nothing is made up in its place. A `requested`
# credit with no line names the origin (`origin_name`), else is left out.
FOOTAGE_KEY = "footage_attribution_line"
FOOTAGE_FIELDS = ("{credit}", "{url}")
CHANGES_KEY = "footage_changes_note"
SHARE_ALIKE_KEY = "footage_share_alike_line"
SHARE_ALIKE_FIELDS = ("{license}",)
FOOTAGE_CREDITED = ("required", "requested")
# The licences whose terms ask that changes be indicated (footage-origin.json
# `licences.accepted[].what`: "say that it was changed") - per licence, not
# per channel.
CHANGES_LICENCES = ("cc_by", "cc_by_sa")
SEGMENT_RE = re.compile(r"\s*·\s*")


class CardError(Exception):
    """The card cannot be built at all - nothing is written."""


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CH = None
_CD = None
_AF = None


def _channel_data():
    global _CD
    if _CD is None:
        _CD = _load("channel_data_publish_card", ROOT / "shared" / "channel_data.py")
    return _CD


def _channel_ids():
    global _CH
    if _CH is None:
        _CH = _load("channel_ids_publish_card", ROOT / "shared" / "channel_ids.py")
    return _CH


def _affiliate():
    global _AF
    if _AF is None:
        _AF = _load("affiliate_publish_card", ROOT / "shared" / "affiliate.py")
    return _AF


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CardError(f"{path}: cannot read ({exc.__class__.__name__}: {exc})") from exc


def data_root(path):
    """The data root above a batch (the directory with pipeline/ and publish/),
    walked on the absolute path - a worktree's pipeline/<channel> may be a
    symlink into the main checkout, and the worktree's own root is meant."""
    for p in Path(path).absolute().parents:
        if (p / "pipeline").is_dir() and (p / "publish").is_dir():
            return p
    return ROOT


# ------------------------------------------------------------ the channel
def channel_config(channel, root=None):
    """`(channel_id, whole config, publisher block)` of `channels/<channel>.json`
    (a former id resolves). CardError when the channel has no usable block."""
    root = Path(root or ROOT)
    path = _channel_ids().channel_config_path(channel, root)
    if not path.is_file():
        raise CardError(f"channel {channel!r}: no {path} - the card's templates live there")
    cfg = _read_json(path)
    pub = cfg.get("publisher")
    if not isinstance(pub, dict) or not pub:
        raise CardError(f"{path}: no `publisher` block - the channel's title suffix, source "
                        f"line, fact-check line, hashtags and settings live there (CF-0017)")
    problems = []
    for key, fields in REQUIRED_TEMPLATES:
        value = pub.get(key)
        if not isinstance(value, str) or not all(f in value for f in fields):
            problems.append(f"`publisher.{key}` must be a string with {', '.join(fields)}")
    line = pub.get(ATTRIBUTION_KEY)
    if line is not None and not (isinstance(line, str)
                                 and all(f in line for f in ATTRIBUTION_FIELDS)):
        problems.append(f"`publisher.{ATTRIBUTION_KEY}` must be a string with "
                        f"{', '.join(ATTRIBUTION_FIELDS)}")
    for key, fields in ((FOOTAGE_KEY, FOOTAGE_FIELDS), (SHARE_ALIKE_KEY, SHARE_ALIKE_FIELDS),
                        (CHANGES_KEY, ())):
        value = pub.get(key)
        if value is not None and not (isinstance(value, str) and value.strip()
                                      and all(f in value for f in fields)):
            problems.append(f"`publisher.{key}` must be a non-empty string"
                            + (f" with {', '.join(fields)}" if fields else ""))
    tags = pub.get("hashtags")
    if not (isinstance(tags, dict) and isinstance(tags.get("min"), int)
            and isinstance(tags.get("max"), int) and 1 <= tags["min"] <= tags["max"]):
        problems.append("`publisher.hashtags` must carry integer `min` <= `max`")
    else:
        constant = tags.get("constant")
        if constant is not None and not (isinstance(constant, list) and all(
                isinstance(c, str) and _hashtag(c) for c in constant)):
            problems.append("`publisher.hashtags.constant` must be a list of hashtag words")
        elif len(constant_hashtags(pub)) > tags["max"]:
            problems.append(f"`publisher.hashtags.constant` holds {len(constant_hashtags(pub))} "
                            f"hashtags, more than `max` {tags['max']} - the channel's constants "
                            f"are never cut, so `max` must make room for them (CF-0678)")
    if not isinstance(pub.get("settings"), list):
        problems.append("`publisher.settings` must be a list of lines")
    if problems:
        raise CardError(f"{path}: " + "; ".join(problems))
    return cfg.get("channel_id") or path.stem, cfg, pub


# -------------------------------------------------------------- the batch
REFUSED_TASK = "CF-0891"
# the files of `work/<slug>/` that name the script the render was made for
WORK_SCRIPT_FILES = ("plan.score.refusal.json", "plan.score.json", "anchors.json", "order.json")


def _work_script_id(work_dir):
    for name in WORK_SCRIPT_FILES:
        try:
            d = json.loads((Path(work_dir) / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("script_id"):
            return d["script_id"]
    return None


def _refused_slug(batch_dir, script_id, script):
    """The name a script refused after its render was rendered under: the one
    `work/<slug>/` (with its plan.json) that names the script, else the slug
    of the script's `title_ref.name` (`publish_profile.find_script`'s rule)."""
    work = Path(batch_dir) / "work"
    hits = sorted(p.name for p in work.iterdir()
                  if p.is_dir() and (p / "plan.json").is_file()
                  and _work_script_id(p) == script_id) if work.is_dir() else []
    if len(hits) == 1:
        return hits[0]
    name = ((script or {}).get("title_ref") or {}).get("name")
    if not name:
        return None
    import publish_profile                                     # noqa: PLC0415
    return publish_profile.slugify(name) or None


def refused_video(batch_dir, key, d03, d05, channel, root=None, accepted=None):
    """CF-0891: `(video, slug, why)` of a video refused AFTER its render (its
    record in `05 -> refusals[]`, not in `videos[]`) that the user accepted
    all the same - `video` is None and `why` the reason when it does not
    qualify, `(None, None, None)` when no refusal answers to `key` at all.

    It qualifies only with its render on disk (`videos/<slug>.mp4`), the
    verdict `accepted` on `<channel>/<batch_id>/<slug>` in the acceptance
    record (or `accepted=True`: the caller is recording that verdict right
    now - `card_center.on_accepted`, before the record is written) and its
    `work/<slug>/plan.json`: the on-screen fact lines and the footage credits
    the render carries are read from there (what `videos[]` would have copied
    as `comparison_line_delivered` / `footage_credits`) - nothing is guessed."""
    batch_dir = Path(batch_dir)
    by_id = {s.get("script_id"): s for s in d03.get("scripts") or []
             if isinstance(s, dict) and s.get("script_id")}
    cands = []
    for r in d05.get("refusals") or []:
        if not isinstance(r, dict) or not r.get("script_id"):
            continue
        sid = r["script_id"]
        slug = _refused_slug(batch_dir, sid, by_id.get(sid))
        if key in (sid, slug):
            cands.append((r, slug))
    if not cands:
        return None, None, None
    if len({r["script_id"] for r, _ in cands}) != 1:
        return None, None, (f"{key!r} answers to refusals of several scripts in "
                            f"05-video-editor.json")
    ref, slug = max(cands, key=lambda c: str(c[0].get("at") or ""))
    code = ref.get("reason_code") or ref.get("gate") or "refused"
    head = f"{slug or key} was refused after its render ({code})"
    if not slug:
        return None, None, f"{head} and its rendered name is not known (no work/<slug>/)"
    mp4 = batch_dir / "videos" / f"{slug}.mp4"
    if not mp4.is_file():
        return None, slug, f"{head} and has no render videos/{slug}.mp4"
    verdict = acceptance_error = None
    if accepted:
        verdict = "accepted"
    else:
        try:
            verdict = verdict_of(channel, batch_dir.name, slug,
                                 root or data_root(batch_dir))
        except Exception as e:                                  # noqa: BLE001
            acceptance_error = f"{e.__class__.__name__}: {e}"
    if verdict != "accepted":
        return None, slug, (f"{head} and the acceptance record has "
                            + (f"no readable verdict ({acceptance_error})" if acceptance_error
                               else f"{verdict or 'no verdict'}")
                            + f" for {channel}/{batch_dir.name}/{slug} - only a video the user "
                              f"accepted despite the refusal gets a card ({REFUSED_TASK})")
    plan_path = batch_dir / "work" / slug / "plan.json"
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, slug, (f"{head}, accepted, but its {plan_path.relative_to(batch_dir)} "
                            f"does not read ({e.__class__.__name__}) - the on-screen fact lines "
                            f"and footage credits of the render are not known")
    if not isinstance(plan, dict):
        return None, slug, f"{head}, accepted, but its work/{slug}/plan.json is not an object"
    video = {"script_id": ref["script_id"], "output_path": str(mp4),
             "duration": plan.get("duration"),
             "comparison_line_delivered": plan.get("comparison_lines") or [],
             "footage_credits": plan.get("footage_credits"),
             "refused_after_render": {k: ref.get(k) for k in ("reason_code", "gate", "at",
                                                               "score_line")},
             "record_from": f"05 refusals[] + work/{slug}/plan.json ({REFUSED_TASK})"}
    return video, slug, None


def batch_video(batch_dir, key, root=None, accepted=None):
    """`(channel, script, video, slug)` of one video of a batch (or a rebuild):
    `key` is the video's slug (the stem of its `output_path`) or its script id.

    CF-0891: a video refused after its render (`05 -> refusals[]`) is taken
    when the user accepted it all the same (`refused_video`); otherwise the
    refusal is the one it always was, with the reason added."""
    batch_dir = Path(batch_dir)
    d03 = _read_json(batch_dir / "03-content-researcher.json")
    d05 = _read_json(batch_dir / "05-video-editor.json")
    channel = d03.get("channel") or d05.get("channel")
    videos = [v for v in d05.get("videos") or [] if isinstance(v, dict)]
    hit = [v for v in videos if v.get("script_id") == key
           or Path(str(v.get("output_path") or "")).stem == key]
    why = None
    if not hit and channel:
        video, _slug, why = refused_video(batch_dir, key, d03, d05, channel, root, accepted)
        if video is not None:
            hit = [video]
    if len(hit) != 1:
        raise CardError(f"{batch_dir}: no single video {key!r} in 05-video-editor.json "
                        f"(slugs: {', '.join(Path(str(v.get('output_path'))).stem for v in videos)})"
                        + (f" - {why}" if why else ""))
    video = hit[0]
    scripts = [s for s in d03.get("scripts") or []
               if isinstance(s, dict) and s.get("script_id") == video.get("script_id")]
    if len(scripts) != 1:
        raise CardError(f"{batch_dir}: no single script {video.get('script_id')!r} in "
                        f"03-content-researcher.json")
    if not channel:
        raise CardError(f"{batch_dir}: the batch names no channel")
    slug = Path(str(video.get("output_path") or "")).stem or key
    return channel, scripts[0], video, slug


def _full_url(url):
    if not isinstance(url, str):
        return False
    parts = urlsplit(url.strip())
    return parts.scheme in ("http", "https") and bool(parts.netloc) and " " not in url.strip()


def _host(url):
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _detailed(name, url, section=None):
    """`Wikipedia, Harbourlights (TV series) — Background` - the page and its section
    named the way the hand-written notes named them (2026-09-22 onwards);
    `Wikidata, Q110556821 — cast member` - the item and its property (CF-0637)."""
    parts = urlsplit(url)
    if _host(url).endswith("wikipedia.org") and parts.path.startswith("/wiki/"):
        page = unquote(parts.path[len("/wiki/"):]).replace("_", " ").strip()
        if page:
            name = f"{name}, {page}"
        section = section or unquote(parts.fragment).replace("_", " ").strip() or None
        if section:
            name = f"{name} — {section}"
    elif _host(url).endswith("wikidata.org") and re.fullmatch(r"/wiki/Q\d+", parts.path):
        # CF-0637: a fact on a Wikidata statement - the item and its property
        # (`wikidata_api.candidate_of`: the URL is the item's page at the
        # property, `section` the property's label)
        name = f"{name}, {parts.path[len('/wiki/'):]}"
        section = section or None
        if section:
            name = f"{name} — {section}"
    return name


def source_of(script, video, cfg):
    """`{name, url}` of the video's fact: the URL is `production_fact.source_url`
    (rules, block 2), the name the publication's own - the on-screen line's
    publisher for that URL, the script's `fact.source` for it, the channel's
    publisher table, the host as the last resort."""
    pf = script.get("production_fact") or {}
    url = (pf.get("source_url") or "").strip()
    if not _full_url(url):
        raise CardError(f"script {script.get('script_id')}: production_fact.source_url "
                        f"{url or '(none)'!r} is not a full URL - block 2 carries the real "
                        f"source, a card without it is not built (docs/publisher-metadata-rules.md)")
    for c in video.get("comparison_line_delivered") or []:
        if isinstance(c, dict) and (c.get("source_url") or "").strip() == url and c.get("publisher"):
            return {"name": _detailed(c["publisher"], url), "url": url}
    fact = script.get("fact") or {}
    if fact.get("source") and (fact.get("url") or "").strip() == url:
        return {"name": _detailed(fact["source"], url, fact.get("section")), "url": url}
    table = ((cfg.get("video_editor") or {}).get("comparison_line") or {}).get("publishers") or {}
    host = _host(url)
    for h, name in table.items():
        if host == h or host.endswith("." + h):
            return {"name": name, "url": url}
    if fact.get("source") and _host(fact.get("url") or "") == host:
        return {"name": fact["source"], "url": url}
    return {"name": host, "url": url}


def fact_checks(video):
    """The on-screen lines of 05 (`comparison_line_delivered[]`) as
    `[{wording, url, source}]`. A line without its wording or its full source
    URL refuses the card: the plate says the fact check is in the description,
    and the description could not give it."""
    out = []
    for i, c in enumerate(video.get("comparison_line_delivered") or []):
        if not isinstance(c, dict):
            continue
        wording = re.sub(r"\s+", " ", str(c.get("text") or "")).strip()
        url = (c.get("source_url") or "").strip()
        if not wording or not _full_url(url):
            raise CardError(f"{video.get('script_id')}: comparison_line_delivered[{i}] has "
                            f"{'no wording' if not wording else 'no full source_url'} - the "
                            f"plate promises a fact check in the description, the card cannot "
                            f"carry it (CF-0017, obligation of 2026-09-08)")
        out.append({"wording": wording, "url": url,
                    "source": c.get("publisher") or _host(url)})
    return out


# -------------------------------------------------------------- the draft
def _spoken(script):
    return " ".join(str(script.get(k) or "").strip() for k in ("hook", "commentary", "payoff")
                    if script.get(k)).strip()


# CF-0912: words that mark a claim as one that names the hero's forerunner
# too (the "was" of a "was -> is") - a claim without them is the "is"
PREDECESSOR_RE = re.compile(
    r"\b(original|first[\s_-]+gen(?:eration)?|previous|predecessor|prior|older|last[\s_-]+year'?s?|"
    r"earlier|replac(?:es|ed|ing))\b", re.I)
# the label of a whole fact as the forerunner's - in its section, its on-screen
# line or its URL's anchor ("First generation (2020)", "Original HomePod Mini")
FORERUNNER_LABEL_RE = re.compile(
    r"\b(original|first[\s_-]+gen(?:eration)?|(?:previous|prior)[\s_-]+(?:gen(?:eration)?|model|"
    r"version)s?|predecessor|older[\s_-]+models?|last[\s_-]+year'?s?)\b", re.I)
# a version mark in a name: a number ("2", "11", "2099", "4o") or a roman numeral
_VERSION_RE = re.compile(r"^(?:\d+[a-z]{0,2}|[IVX]{2,4})$", re.I)


def _name_re(name, version=None):
    """A pattern of `name` on word bounds. `version`: what a version token of
    the name may be instead (the name with another number, or none)."""
    parts = []
    for tok in re.findall(r"[^\W_]+", name, re.UNICODE):
        if version is not None and _VERSION_RE.match(tok):
            parts.append(version)
        else:
            parts.append(re.escape(tok))
    if not parts:
        return None
    body = r"[\s\W_]*".join(p for p in parts if p)
    return re.compile(r"(?<![^\W_])" + body + r"(?![^\W_])", re.I | re.UNICODE)


def _names_hero(text, name):
    rx = _name_re(name)
    return bool(rx and rx.search(str(text or "")))


def about_predecessor(script):
    """CF-0912: the reason the video's fact (`production_fact`) is about the
    hero's forerunner rather than the hero, or None. Only a hero with a version
    in its name has one (HomePod Mini 2, Pixel 11 Pro Fold, Blade Runner 2099),
    and only a fact that does not name the hero itself: one that names the same
    line with another version ("Pixel 10 Pro Fold"), or one labelled as the
    forerunner's in its section, on-screen line or URL anchor ("First
    generation (2020)", "Original HomePod Mini"). A fact that merely compares
    ("...from prior generations") or names the line or franchise without a
    version ("a Blade Runner television spin-off") stays the hero's."""
    name = str((script.get("title_ref") or {}).get("name") or "").strip()
    toks = re.findall(r"[^\W_]+", name, re.UNICODE)
    versions = {t.casefold() for t in toks if _VERSION_RE.match(t)}
    if not name or not versions:
        return None
    pf = script.get("production_fact") or {}
    fact = script.get("fact") or {}
    texts = [pf.get("text"), pf.get("beat_text")]
    if any(_names_hero(t, name) for t in texts):
        return None
    sibling = _name_re(name, version=r"(?:\d+[a-z]{0,2}|[IVX]{2,4})")
    for t in texts:
        m = sibling.search(str(t or ""))
        if m and not versions & {x.casefold() for x in re.findall(r"[^\W_]+", m.group(0))}:
            return f"the fact names {m.group(0)!r}, not {name!r}"
    for where, text in (("section", fact.get("section")), ("on_screen", pf.get("on_screen")),
                        ("anchor", (pf.get("source_url") or "").partition("#")[2])):
        m = FORERUNNER_LABEL_RE.search(str(text or ""))
        if m:
            return f"the fact's {where} says {m.group(0)!r} and the fact does not name {name!r}"
    return None


_WHERE_RANK = {"hook": 0, "commentary": 1, "payoff": 2}


def headline_fact(script):
    """CF-0912: the fact the title and block 1 carry - `{text, quote, source,
    claim_id, why}`. The video's own fact (`production_fact`, quoted by
    `fact.text`) unless it is about the hero's forerunner (`about_predecessor`):
    then the first claim the script declares that names the hero, in its own
    words and in its quote - the hook's before the commentary's before the
    payoff's, and a claim that names no forerunner ("was -> is": the "is")
    before one that does. No such claim: the video's fact stays."""
    pf = script.get("production_fact") or {}
    fact = script.get("fact") or {}
    own = {"text": pf.get("text"), "quote": fact.get("text"), "source": fact.get("source"),
           "claim_id": None, "why": None}
    why = about_predecessor(script)
    if not why:
        return own
    name = str((script.get("title_ref") or {}).get("name") or "").strip()
    best = None
    for i, c in enumerate(script.get("claims") or []):
        if not isinstance(c, dict) or c.get("where") not in _WHERE_RANK:
            continue
        if not _names_hero(c.get("text"), name):
            continue
        quote = next((s for s in c.get("support") or []
                      if isinstance(s, dict) and _names_hero(s.get("quote"), name)), None)
        if quote is None:
            continue
        rank = (bool(PREDECESSOR_RE.search(str(c.get("text") or ""))), _WHERE_RANK[c["where"]], i)
        if best is None or rank < best[0]:
            best = (rank, c, quote)
    if best is None:
        return dict(own, why=f"{why}; no declared claim names the hero with a quote - the "
                             f"video's fact stays")
    _, c, quote = best
    return {"text": c.get("text"), "quote": quote.get("quote"),
            "source": _source_named(quote.get("source"), fact.get("source")),
            "claim_id": c.get("claim_id"), "why": why}


def _source_named(piece, named):
    """The source's name for a claim's quote: the script's `fact.source` when the
    quote's piece is on that source ("wikipedia:HomePod_Mini" -> "Wikipedia")."""
    piece, named = str(piece or ""), str(named or "")
    return named if named and piece.casefold().startswith(named.casefold()) else piece or None


def draft_request(script, pub, language):
    """`(payload, prompt)` of the model's draft of the title, block 1, the
    hashtags and the tags. The fact they carry is `headline_fact` (CF-0912):
    the video's fact, or a claim about the hero when that fact is about its
    forerunner."""
    tr = script.get("title_ref") or {}
    head = headline_fact(script)
    title_max = int(pub.get("title_max_chars", publish_note.TITLE_MAX)) - len(pub.get("title_suffix") or "")
    about_max = int(pub.get("about_max_chars", 450))
    hmin, hmax = pub["hashtags"]["min"], pub["hashtags"]["max"]
    claims = [c.get("text") for c in script.get("claims") or [] if isinstance(c, dict) and c.get("text")]
    payload = {
        "work": {k: tr.get(k) for k in ("name", "kind", "type", "year", "season", "network",
                                        "parent_work", "person") if tr.get(k)},
        "narration": _spoken(script),
        "fact": head["text"], "fact_quote": head["quote"], "fact_source": head["source"],
        "sourcing_caveat": script.get("sourcing_caveat") or "",
        "script_claims": claims,
        "language": language, "title_max": title_max, "about_max": about_max,
        "hashtags": [hmin, hmax],
        # CF-0728: the rule that ties every statement to a declared claim -
        # part of the cache key, so a draft written without it is asked again
        "rules": DRAFT_RULES,
    }
    forerunner = ""
    if head["claim_id"]:
        # CF-0912: only a script whose fact is about the forerunner gets the
        # key and the rule - every other draft keeps its cache key
        payload["headline"] = {"claim_id": head["claim_id"], "why": head["why"],
                               "rule": "CF-0912"}
        forerunner = (
            f"- The title and the about are about {tr.get('name') or 'the work'} itself. The "
            "narration also names an earlier model, version or edition to compare it with; "
            "never put the earlier one's facts in the title or the about. In a 'was -> is' "
            "comparison carry the 'is'.\n")
    prompt = (
        "You write the YouTube Shorts metadata of one finished video, from its script only.\n\n"
        f"WORK: {json.dumps(payload['work'], ensure_ascii=False)}\n"
        f"NARRATION (what the video says): {payload['narration']}\n"
        f"THE VIDEO'S FACT: {payload['fact']}\n"
        f"THE SOURCE'S OWN SENTENCE ({payload['fact_source'] or 'source'}): {payload['fact_quote']}\n"
        f"SOURCING CAVEAT: {payload['sourcing_caveat'] or '(none)'}\n"
        + (f"CLAIMS THE SCRIPT DECLARES: {json.dumps(claims, ensure_ascii=False)}\n" if claims else "")
        + "\nRules:\n"
        f"- Write in {language}.\n"
        f"- title: a hook plus the words people search for (the work's name), at most "
        f"{title_max} characters, no hashtags, no URL, no '<' or '>'. It must not claim more than "
        "the source's own sentence and the sourcing caveat allow: no 'confirmed', 'officially', "
        "'first', 'only', 'never', 'every', 'secret' unless the source's sentence itself says so.\n"
        f"- about: one or two sentences, at most {about_max} characters, that carry the video's "
        "fact in plain words. Say only what the narration and the source's sentence say - no "
        "background, motive, comparison or framing of your own; no URL, no hashtags, no source "
        "line (that is added separately).\n"
        + forerunner
        + "- Every statement of the title and the about is one that a claim the script declares "
        "(or, with none listed, the narration) or the source's own sentence makes - reuse their "
        "words where you can; each is checked against the quotes those claims stand on. Never "
        "put two facts in an order, a cause or a comparison ('before', 'after', 'because', "
        "'led to', 'more than') unless one of those claims says it. Write numbers and years in "
        "digits (2021, not 'twenty twenty one' - the narration spells them for the voice).\n"
        f"- hashtags: {hmin} to {hmax} single CamelCase words without '#', the work's name first, "
        "then the network/franchise/topic.\n"
        "- tags: 5 to 12 short search phrases (names of the work, people, network, topic).\n\n"
        'Answer with one JSON object only: {"title": "...", "about": "...", '
        '"hashtags": ["..."], "tags": ["..."]}')
    return payload, prompt


def validate_draft(answer):
    """Schema problems of a draft (empty = usable)."""
    if not isinstance(answer, dict):
        return ["the draft is not a JSON object"]
    problems = []
    for key in ("title", "about"):
        if not isinstance(answer.get(key), str) or not answer[key].strip():
            problems.append(f"`{key}` must be a non-empty string")
    for key in ("hashtags", "tags"):
        v = answer.get(key)
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            problems.append(f"`{key}` must be a list of strings")
    return problems


def ask_draft(asker, script, pub, language, previous=None, problems=None):
    """The model's draft; with `previous` and `problems`, the one redraft that
    names what the checks refused in the first one."""
    payload, prompt = draft_request(script, pub, language)
    if previous is not None:
        payload = dict(payload, previous=previous, problems=problems)
        prompt += ("\n\nYour previous draft was refused by the checks:\n"
                   + "\n".join(f"- {p}" for p in problems)
                   + f"\nPrevious draft: {json.dumps(previous, ensure_ascii=False)}\n"
                   "Write it again so that none of these problems remains.")
    answer, _key = asker.ask(DRAFT_KIND, payload, prompt, validate_draft)
    return answer


def _claim_problem(p):
    """One refusal of the claim check as the redraft is told it: the code,
    where, the words, the judge's reason (with what was missing)."""
    words = f" {p['text']!r}" if p.get("text") else ""
    return f"{p.get('code')} [{p.get('where')}]{words}: {p.get('detail') or ''}".rstrip(": ")


def load_draft(path):
    answer = _read_json(path)
    problems = validate_draft(answer)
    if problems:
        raise CardError(f"{path}: " + "; ".join(problems))
    return answer


# ------------------------------------------------------------ composition
def _hashtag(text):
    words = re.findall(r"[^\W_]+", str(text or "").lstrip("#"), re.UNICODE)
    if not words:
        return ""
    if len(words) == 1:
        return words[0]
    return "".join(w if w[:1].isupper() or w.isdigit() else w[:1].upper() + w[1:] for w in words)


def constant_hashtags(pub):
    """The channel's own hashtags (`publisher.hashtags.constant`), as they
    stand in the card, duplicates dropped."""
    seen, out = set(), []
    for raw in (pub.get("hashtags") or {}).get("constant") or []:
        tag = _hashtag(raw)
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out


def hashtags_of(script, draft, pub):
    """Block 3 (CF-0678). The channel's constants are never cut: they take
    their places first, and the work's name and the draft's hashtags fill what
    `max` leaves. In the line the constants stand last - the work's name stays
    the first hashtag (YouTube picks the up-to-three hashtags it shows by the
    title by engagement, not by place, and a reader of the description meets
    the specific ones first; the generic channel tag adds nothing up front).
    `channel_config` refuses a channel whose constants alone exceed `max`."""
    tr = script.get("title_ref") or {}
    constant = constant_hashtags(pub)
    room = max(pub["hashtags"]["max"] - len(constant), 0)
    seen, own = {t.casefold() for t in constant}, []
    for raw in [tr.get("name")] + list(draft.get("hashtags") or []):
        tag = _hashtag(raw)
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            own.append(tag)
    return own[:room] + constant


def tags_of(script, draft, pub):
    tr = script.get("title_ref") or {}
    seen, out = set(), []
    for raw in [tr.get("name"), tr.get("network"), tr.get("parent_work"), tr.get("person")] + \
            list(draft.get("tags") or []) + list(pub.get("tags_constant") or []):
        tag = re.sub(r"\s+", " ", str(raw or "").replace(",", " ")).strip().lstrip("#")
        if not tag or "<" in tag or ">" in tag or tag.casefold() in seen:
            continue
        if publish_note.tags_length(out + [tag]) > publish_note.TAGS_MAX:
            break
        seen.add(tag.casefold())
        out.append(tag)
    return out


def _credited(piece):
    p = piece or {}
    return p.get("kind") in CREDITED_KINDS or str(p.get("id") or "").startswith("tvmaze:")


def attributions_of(script, topic):
    """`[{source, license, url}]` - one per credited piece the script's
    claims quote (CF-0636: a TVmaze episode description, CC BY-SA 4.0), in
    the order of the claims, one per link. The video's fact standing on a
    TVmaze page (`production_fact.source_url`) is credited too."""
    pieces = {p.get("id"): p for p in (topic or {}).get("support_text") or []
              if isinstance(p, dict) and p.get("id")}
    out, seen = [], set()

    def add(source, license_, url):
        if url and url not in seen:
            seen.add(url)
            out.append({"source": source, "license": license_, "url": url})

    for c in script.get("claims") or []:
        for s in (c.get("support") or []) if isinstance(c, dict) else []:
            piece = pieces.get(s.get("source")) if isinstance(s, dict) else None
            if piece and _credited(piece):
                add(piece.get("publication") or "TVmaze",
                    (piece.get("license") or {}).get("title") or "CC BY-SA 4.0",
                    piece.get("url"))
    url = ((script.get("production_fact") or {}).get("source_url") or "").strip()
    if _full_url(url) and any(_host(url) == h or _host(url).endswith("." + h)
                              for h in CREDITED_HOSTS):
        add("TVmaze", "CC BY-SA 4.0", url)
    return out


def _s(value):
    return value.strip() if isinstance(value, str) and value.strip() else None


def footage_attributions_of(video):
    """`[{video_id, origin, credit, credit_from, license, license_url, url,
    attribution, share_alike, changes}]` - one per source of the video's
    `footage_credits[]` (VE-1) whose credit is `required` or `requested`, in
    the order of first use, one per link. `[]` for a video without the field
    (`null`: built before CF-0664) or with nothing judged (`[]`: a channel
    that judges no licences). CardError for a `required` credit with no
    concrete line: the licence asks for the credit and only the origin's
    rule is known."""
    out, seen = [], set()
    for row in (video or {}).get("footage_credits") or []:
        if not isinstance(row, dict) or row.get("attribution") not in FOOTAGE_CREDITED:
            continue
        required = row.get("attribution") == "required"
        credit = _s(row.get("credit"))
        credit_from = "candidate" if credit else None
        if credit is None and required:
            who = row.get("origin_name") or row.get("footage_origin") or "?"
            raise CardError(
                f"the video shows {row.get('video_id')} ({who}, "
                f"{row.get('licence_label') or row.get('licence')}), whose licence asks for the "
                f"credit, and there is no concrete credit line for the file: "
                f"{row.get('credit_missing') or 'credit: null'}"
                + (f" (the origin's rule: {row['credit_rule']})" if _s(row.get("credit_rule")) else "")
                + " - nothing is made up in its place; the file's own credit comes with its "
                  "candidate (CF-0664)")
        if credit is None:
            credit = _s(row.get("origin_name"))
            credit_from = "origin_name" if credit else None
        if credit is None:
            continue                        # requested, and nobody to name: left out
        url = _s(row.get("source_url")) or ""
        key = url or credit
        if key in seen:
            continue
        seen.add(key)
        license_ = _s(row.get("licence_label")) or (
            _s(row.get("licence_name")) if required else None) or ""
        out.append({"video_id": row.get("video_id"), "origin": row.get("footage_origin"),
                    "credit": credit, "credit_from": credit_from, "license": license_,
                    "license_url": (_s(row.get("license_url")) or "") if license_ else "",
                    "url": url, "attribution": row.get("attribution"),
                    "share_alike": row.get("share_alike") is True,
                    "changes": row.get("licence") in CHANGES_LICENCES})
    return out


def _segments(line):
    """A filled template with the empty `·`-segments left out (public
    domain names no licence: `<credit> · <url>`)."""
    parts = [re.sub(r"\s+", " ", x).strip() for x in SEGMENT_RE.split(line)]
    return " · ".join(x for x in parts if x)


def footage_lines(footage, pub):
    """The credit lines of the video's footage (CF-0664), then one
    share-alike line per share-alike licence among them. CardError when the
    channel has no words for what a licence asks."""
    if not footage:
        return []
    names = ", ".join(f"{f['credit']} ({f['license'] or f['attribution']})" for f in footage)
    if not pub.get(FOOTAGE_KEY):
        raise CardError(f"the video shows footage of {names}, whose licence or origin asks for "
                        f"credit, and the channel has no `publisher.{FOOTAGE_KEY}` to credit it "
                        f"with (CF-0664)")
    lines = []
    for f in footage:
        changes = ""
        if f["changes"]:
            changes = _s(pub.get(CHANGES_KEY)) or ""
            if not changes or "{changes}" not in pub[FOOTAGE_KEY]:
                raise CardError(f"the video shows {f['credit']} under {f['license']}, which asks "
                                f"that changes be indicated, and the channel has no "
                                f"`publisher.{CHANGES_KEY}` filled into {{changes}} of "
                                f"`publisher.{FOOTAGE_KEY}` (CF-0664)")
        lines.append(_segments(pub[FOOTAGE_KEY].format(
            credit=f["credit"], license=f["license"], license_url=f["license_url"],
            changes=changes, url=f["url"])))
    shared = []
    for f in footage:
        if f["share_alike"] and (f["license"], f["license_url"]) not in shared:
            shared.append((f["license"], f["license_url"]))
    if shared and not pub.get(SHARE_ALIKE_KEY):
        raise CardError(f"the video adapts share-alike footage ({', '.join(s[0] for s in shared)}) "
                        f"and the channel has no `publisher.{SHARE_ALIKE_KEY}` to say the video "
                        f"is shared under that licence (CF-0664)")
    for license_, url in shared:
        lines.append(_segments(pub[SHARE_ALIKE_KEY].format(license=license_, license_url=url)))
    return lines


def block2(source, checks, pub, attributions=(), footage=(), affiliate=()):
    """The source line, then one fact-check line per on-screen line, then one
    credit line per licensed text the video quotes (CF-0636), then the
    footage credits (CF-0664), then - when the channel's slot placed one -
    the affiliate link and its disclosure (CF-0593, `affiliate_of`). A
    credit the channel has no line for refuses the card: the licence asks
    for it."""
    lines = [pub["source_line"].format(source=source["name"], url=source["url"])]
    for c in checks:
        same = c["url"] == source["url"] and pub.get("fact_check_line_same_source")
        tpl = pub["fact_check_line_same_source"] if same else pub["fact_check_line"]
        lines.append(tpl.format(wording=c["wording"], source=c["source"], url=c["url"]))
    if attributions and not pub.get(ATTRIBUTION_KEY):
        raise CardError(f"the video quotes {', '.join(a['source'] for a in attributions)} "
                        f"({attributions[0]['license']}), whose licence asks for the source to "
                        f"be credited with a link, and the channel has no "
                        f"`publisher.{ATTRIBUTION_KEY}` to credit it with (CF-0636)")
    for a in attributions:
        lines.append(pub[ATTRIBUTION_KEY].format(source=a["source"], license=a["license"],
                                                 url=a["url"]))
    lines.extend(footage_lines(footage, pub))
    lines.extend(affiliate)
    return "\n".join(lines)


def affiliate_of(cfg, cfg_path, script, topic=None):
    """CF-0593: the affiliate decision for one video - `shared/affiliate.py`
    `decide` on the channel's switch and table, the topic's `title_ref` (the
    script's when the topic has none) and the script's fact. None for a
    channel with no `affiliate` block: it has no slot, and its card stays as
    it was."""
    af = _affiliate()
    if not isinstance(cfg, dict) or af.KEY not in cfg:
        return None
    ref = (topic or {}).get("title_ref") if isinstance(topic, dict) else None
    if not isinstance(ref, dict) or not ref:
        ref = script.get("title_ref")
    return af.decide_for(cfg, cfg_path, ref, script)


def compose(script, video, draft, pub, cfg, topic=None, affiliate=None):
    """The card's fields - no checking beyond what refuses the card. `topic`
    is the script's topic of 01 (its support text names the pieces the
    claims quote - CF-0636's credit line); `affiliate` the decision of
    `affiliate_of` (None: the channel has no slot)."""
    source = source_of(script, video, cfg)
    checks = fact_checks(video)
    attributions = attributions_of(script, topic)
    footage = footage_attributions_of(video)
    title = re.sub(r"\s+", " ", draft["title"]).strip()
    about = re.sub(r"[ \t]+", " ", draft["about"]).strip()
    hashtags = hashtags_of(script, draft, pub)
    aff_lines = _affiliate().lines_of(affiliate)
    description = "\n\n".join([about, block2(source, checks, pub, attributions, footage,
                                              aff_lines),
                               " ".join("#" + h for h in hashtags)])
    return {"title": title + (pub.get("title_suffix") or ""), "title_bare": title,
            "about": about, "description": description, "hashtags": hashtags,
            "tags": tags_of(script, draft, pub), "source": source, "fact_checks": checks,
            "attributions": attributions, "footage_credits": footage, "affiliate": affiliate,
            "settings": [str(s) for s in pub.get("settings") or []]}


def _words(text):
    return set(re.findall(r"[^\W_]+(?:-[^\W_]+)*", str(text or "").casefold()))


def strength_problems(title, script, language, pub):
    """Rule 1: words of the strength list in the title that the source's own
    sentence (and the video's fact as the script words it) does not use."""
    strong = set(STRENGTH_WORDS.get(language, ())) | {
        w.casefold() for w in pub.get("strength_words_extra") or []}
    pf = script.get("production_fact") or {}
    allowed = _words((script.get("fact") or {}).get("text")) | _words(pf.get("text"))
    for c in script.get("claims") or []:                    # CF-0552: quotes the video stands on
        for s in (c.get("support") or []) if isinstance(c, dict) else []:
            if isinstance(s, dict):
                allowed |= _words(s.get("quote"))
    over = sorted(w for w in _words(title) & strong if w not in allowed)
    if not over:
        return []
    caveat = (script.get("sourcing_caveat") or "").strip()
    return [{"code": "title_stronger_than_source", "where": "title",
             "text": ", ".join(over),
             "detail": f"the title says {', '.join(repr(w) for w in over)}, the source's own "
                       f"sentence does not" + (f"; sourcing caveat: {caveat}" if caveat else ""),
             "fix": "write the title so it claims no more than the source's sentence "
                    "(docs/publisher-metadata-rules.md, rule 1)"}]


def attribution_terms_of(channel, root):
    """CF-0671: the channel's outlets' bans on phrasing its AI output
    (`channel_data.attribution_terms`). A channel without a fact-sources list
    has none; a ban that cannot be matched refuses the card - dropping it
    would let the phrase through."""
    cd = _channel_data()
    try:
        return cd.attribution_terms(channel, root)
    except cd.ChannelDataError as exc:
        raise CardError(f"the outlets' terms for AI output cannot be read (CF-0671): "
                        f"{exc}") from exc


def attribution_problems(card, terms):
    """CF-0671: a phrase an outlet's terms forbid in an AI product - the
    information attributed to the outlet or its endorsement implied - in the
    title or the description (the source and credit lines included: they are
    the channel's words too). Links are not read: a page's address is the
    outlet's."""
    problems = []
    for field in ("title", "description"):
        for h in _channel_data().attribution_hits(card[field], terms):
            problems.append({
                "code": "attribution_forbidden", "where": field, "text": h["match"],
                "detail": f"the {field} says {h['match']!r} - {h['outlet']}'s terms forbid "
                          f"«{h['phrase']}» in an AI product ({h['terms_url']})",
                "fix": "say the fact in the video's own words and name the source "
                       "neutrally (a source line with its link), never as the outlet's "
                       "word or approval (docs/channel-data.md, CF-0671)"})
    return problems


def card_problems(card, script, language, pub, terms=()):
    """Everything that keeps a composed card from being ready, before the
    claim check (which runs on the written note). `terms`: the channel's
    outlets' bans on phrasing (`attribution_terms_of`)."""
    problems = []

    def p(code, where, detail, fix=None, text=None):
        problems.append({"code": code, "where": where, "text": text, "detail": detail, "fix": fix})

    limit = int(pub.get("title_max_chars", publish_note.TITLE_MAX))
    if len(card["title"]) > min(limit, publish_note.TITLE_MAX):
        p("title_too_long", "title", f"{len(card['title'])} characters, the limit is "
          f"{min(limit, publish_note.TITLE_MAX)} (the suffix included)", "shorten the title")
    if HASHTAG_IN_TEXT_RE.search(card["title_bare"]) or URL_RE.search(card["title_bare"]):
        p("title_carries_tag_or_url", "title", "the drafted title carries a hashtag or a URL")
    about_max = int(pub.get("about_max_chars", 450))
    if len(card["about"]) > about_max:
        p("about_too_long", "description", f"block 1 is {len(card['about'])} characters, the "
          f"channel allows {about_max}", "one or two sentences")
    if URL_RE.search(card["about"]) or HASHTAG_IN_TEXT_RE.search(card["about"]):
        p("about_carries_tag_or_url", "description",
          "block 1 carries a URL or a hashtag - the source and the hashtags are blocks 2 and 3")
    blocks = [b for b in re.split(r"\n\s*\n", card["description"].strip()) if b.strip()]
    if len(blocks) != 3:
        p("description_not_three_blocks", "description",
          f"the description has {len(blocks)} blocks, the rules say exactly three")
    if publish_note.PLACEHOLDER.search(card["description"]):
        p("source_placeholder", "description", "the template placeholder [SOURCE NAME ...] is "
          "in the description - the real source goes there")
    b2 = blocks[1] if len(blocks) == 3 else ""
    if card["source"]["url"] not in b2:
        p("source_missing", "description", "block 2 does not carry production_fact.source_url")
    for c in card["fact_checks"]:
        if c["wording"] not in b2 or c["url"] not in b2:
            p("fact_check_missing", "description",
              f"the on-screen line {c['wording']!r} has no fact check (its wording and "
              f"{c['url']}) in block 2 - the plate in the video would lie")
    if len(card["hashtags"]) < pub["hashtags"]["min"]:
        p("too_few_hashtags", "description", f"{len(card['hashtags'])} hashtag(s), the channel "
          f"wants {pub['hashtags']['min']}-{pub['hashtags']['max']}")
    for field in ("title", "description"):
        if "<" in card[field] or ">" in card[field]:
            p("angle_brackets", field, f"the {field} contains '<' or '>', which YouTube rejects")
    if len(card["description"].encode("utf-8")) > publish_note.DESCRIPTION_MAX_BYTES:
        p("description_too_long", "description", "over YouTube's 5000 bytes")
    problems.extend(strength_problems(card["title_bare"], script, language, pub))
    problems.extend(attribution_problems(card, terms))
    return problems


# ---------------------------------------------------------------- the file
def _rel(path, root):
    for a, b in ((Path(path).absolute(), Path(root).absolute()),
                 (Path(path).resolve(), Path(root).resolve())):
        try:
            return str(a.relative_to(b))
        except ValueError:
            continue
    return str(path)


def render_note(card, meta, publish_line=None):
    """The note text without `## Утверждения` (note_claims writes it) and with
    a provisional `## Карточка`."""
    slug = meta["slug"]
    head = (f"# {slug} — карточка публикации\n\n"
            f"Ролик: `{meta['video']}` · Батч `{meta['batch']}` · сценарий `{meta['script_id']}`"
            f" · тема `{meta['topic_id']}`.\n"
            f"Карточку собрал `agents/publisher/publish_card.py` ({RULE}) из сценария; правила — "
            f"`docs/publisher-metadata-rules.md`.\n")
    settings = "\n".join(f"- {s}" for s in card["settings"]) or "-"
    publish = publish_line or (f"Слот не назначен. После «принят» `publish_card.py place` ставит "
                               f"ролик в ближайший свободный слот канала (CF-0587, "
                               f"`publish_queue.py`) и пишет его сюда.")
    return (head + "\n## Название\n" + card["title"] + "\n\n## Описание\n" + card["description"]
            + "\n\n## Теги\n" + ", ".join(card["tags"]) + "\n\n## Публикация\n" + publish
            + "\n\n## Настройки\n" + settings + "\n\n## " + SECTION + "\n(собирается)\n")


_replace_section = publish_queue.replace_section     # one copy, shared with the queue (CF-0042)


def card_section(mark, problems):
    ready = mark["status"] == READY
    lines = [f"Статус: **{'готова' if ready else 'НЕ готова'}**"
             + (" — проверки пройдены, утверждения проверены (`## Утверждения`)." if ready
                else " — показывать пользователю как готовую нельзя.")]
    src = mark.get("source") or {}
    lines.append(f"Источник факта: {src.get('name')} · {src.get('url')}")
    for c in mark.get("fact_checks") or []:
        lines.append(f"Фактчек плашки «{c['wording']}» — {c['source']} · {c['url']}")
    aff = mark.get("affiliate")
    if aff:
        lines.append(f"Партнёрская ссылка (CF-0593): " + (
            f"поставлена — {aff.get('product')} · {aff.get('url')}" if aff.get("placed")
            else f"не поставлена — {aff.get('reason')}: {aff.get('detail')}"))
    claims = mark.get("claims") or {}
    lines.append(f"Проверка утверждений (CF-0555): {claims.get('verdict')}"
                 + (f", вычеркнуто из описания: {len(claims.get('struck') or [])}"
                    if claims.get("struck") else ""))
    for p in problems:
        lines.append(f"- `{p.get('code')}` [{p.get('where')}] {p.get('detail') or p.get('text') or ''}"
                     + (f" → {p['fix']}" if p.get("fix") else ""))
    lines.append(f"<!-- {MARKER} {json.dumps(mark, ensure_ascii=False, sort_keys=True)} -->")
    return "\n".join(lines)


def mark_of(text):
    """The card's machine marker (dict), or None when the note has none."""
    body = publish_note.sections(text).get(SECTION)
    if body is None:
        return None
    m = MARK_RE.search(body)
    if not m:
        return None
    try:
        mark = json.loads(m.group(1))
    except ValueError:
        return None
    return mark if isinstance(mark, dict) else None


def card_state(text):
    """`(ready, why)` of a card's text: ready only when its marker says ready,
    the claim block is fresh for the current title and description, and the
    note still reads (`publish_note`'s checks)."""
    mark = mark_of(text)
    if mark is None:
        return False, f"no `## {SECTION}` marker - the note was not built by publish_card.py"
    if mark.get("status") != READY:
        return False, f"the card was built not ready: {', '.join(mark.get('problems') or []) or '?'}"
    why = note_claims.check_block(text)
    if why:
        return False, why
    if mark.get("fingerprint") != note_claims.fingerprint(text):
        return False, "the title or the description changed after the card was built"
    return True, None


def failing_of(text):
    """CF-0747: `[{code, where, video, text}]` - what kept the card from being
    ready: the marker's `failing` (cards built since CF-0747), else read back
    from the problem lines of `## Карточка` (older cards); [] when none."""
    mark = mark_of(text) or {}
    if isinstance(mark.get("failing"), list):
        return [dict(f) for f in mark["failing"] if isinstance(f, dict)]
    out = []
    for ln in (publish_note.sections(text).get(SECTION) or "").splitlines():
        m = PROBLEM_LINE_RE.match(ln.strip())
        if m:
            out.append({"code": m.group(1), "where": m.group(2), "video": None,
                        "text": m.group(3).strip() or None})
    return out


def _field_of(where):
    w = str(where or "")
    return w[len("claims/"):] if w.startswith("claims/") else None


def ruling_check(text):
    """CF-0747: may the user's ruling take this card? `{ok, failing, refusals
    [{code, line}]}` - ok only for a card built not ready whose claim check
    failed and whose every problem is a failed claim of the video's own words
    (`VIDEO_FIELDS`). Codes: `no_card` (not built by publish_card.py),
    `card_ready` (nothing to rule), `claims_not_failed` (the claim check did
    not run or did not fail), `failing_unknown` (what failed cannot be read),
    `note_claim_failed` (a claim of the title, the description or the tags
    failed - the card is fixed, not ruled), `card_problem` (a problem that is
    not a claim - fixed, not ruled)."""
    out = {"ok": False, "failing": [], "refusals": []}

    def refuse(code, line):
        out["refusals"].append({"code": code, "line": line})
    mark = mark_of(text)
    if mark is None:
        refuse("no_card", f"no `## {SECTION}` marker - the card was not built by publish_card.py")
        return out
    if mark.get("status") == READY:
        refuse("card_ready", "the card is ready - there is nothing to rule")
        return out
    verdict = (mark.get("claims") or {}).get("verdict")
    failing = failing_of(text)
    out["failing"] = failing
    if verdict != "failed":
        refuse("claims_not_failed", f"the claim check (CF-0555) is {verdict!r}, not failed - "
                                    f"a ruling covers only the video's own failed claims; "
                                    f"fix the card's problems and build it again")
    if not failing:
        refuse("failing_unknown", "what kept the card from being ready cannot be read from it")
    for f in failing:
        field = _field_of(f.get("where"))
        if field is None:
            refuse("card_problem", f"`{f.get('code')}` [{f.get('where')}]: not a claim - the "
                                   f"card is fixed and built again, not ruled")
        elif field in VIDEO_FIELDS or f.get("video"):
            continue
        else:
            refuse("note_claim_failed", f"`{f.get('code')}` [{f.get('where')}]: a claim of the "
                                        f"card's own text failed - the title, the description "
                                        f"and the tags are rewritten (a new draft), not ruled")
    out["ok"] = not out["refusals"]
    return out


def ruling_of(text):
    """The ruling's marker (dict) of `## Решение пользователя`, or None."""
    body = publish_note.sections(text).get(RULING_SECTION)
    if body is None:
        return None
    m = RULING_RE.search(body)
    if not m:
        return None
    try:
        doc = json.loads(m.group(1))
    except ValueError:
        return None
    return doc if isinstance(doc, dict) else None


def ruling_section(ruling):
    """The body of `## Решение пользователя` for a ruling dict {words, by, via,
    at, failing, ...}."""
    lines = [f"Карточка собрана «не готова» только из-за утверждений самого ролика "
             f"(озвучка или надпись на экране) - ролик уже собран, его слова карточка "
             f"не меняет. Пользователь принял карточку своим решением ({RULING_TASK}).",
             f"Слово пользователя: «{ruling['words']}»",
             f"Кто: {ruling['by']} · через: {ruling['via']} · когда: {ruling['at']}",
             "Не прошли проверку (CF-0555):"]
    for f in ruling.get("failing") or []:
        lines.append(f"- `{f.get('code')}` [{f.get('where')}] {f.get('text') or ''}".rstrip())
    lines.append("Название, описание и теги проверку прошли; правка названия или описания "
                 "после решения снимает его (карточка снова не готова).")
    lines.append(f"<!-- {RULING_MARKER} {json.dumps(ruling, ensure_ascii=False, sort_keys=True)} -->")
    return "\n".join(lines)


def card_status(text):
    """CF-0747: `{state, placeable, why, reasons, ruling}` of a card's text -
    `state` is `ready` (`card_state`), `ruled` (built not ready only for the
    video's own failed claims and taken by the user's ruling, the title and the
    description unchanged since) or `not_ready`; `reasons` are the codes of
    what kept it from being ready."""
    ready, why = card_state(text)
    mark = mark_of(text) or {}
    reasons = list(mark.get("problems") or [])
    if ready:
        return {"state": READY, "placeable": True, "why": None, "reasons": [], "ruling": None}
    ruling = ruling_of(text)
    if ruling is not None:
        problem = None
        if ruling.get("built_at") != mark.get("built_at"):
            problem = "the card was built again after the ruling"
        elif ruling.get("fingerprint") != note_claims.fingerprint(text):
            problem = "the title or the description changed after the ruling"
        elif not ruling_check(text)["ok"]:
            problem = "the card no longer fails only on the video's own claims"
        if problem is None:
            return {"state": RULED, "placeable": True, "why": None, "reasons": reasons,
                    "ruling": ruling}
        why = f"{why}; the user's ruling does not hold: {problem}"
    return {"state": NOT_READY, "placeable": False, "why": why, "reasons": reasons,
            "ruling": ruling}


def placeable(text):
    """`(ok, why)`: may this card go to publish/ and on to Studio - ready, or
    taken by the user's ruling (CF-0747)."""
    st = card_status(text)
    return st["placeable"], st["why"]


# ------------------------------------------------------------------ build
def build(batch_dir, key, draft=None, draft_file=None, out=None, root=None, asker=None,
          claims=True, jobs=None, now=None, accepted=None):
    """Build, check and write one card. Returns `{status, path, card, problems,
    claims, mark, text}`; raises CardError when the card cannot be built and
    claim_judge.CannotAsk when the model cannot be asked. `accepted=True`: the
    caller is recording the verdict `accepted` on this video right now (CF-0891,
    see `refused_video`)."""
    batch_dir = Path(batch_dir).absolute()   # not resolve(): a worktree's pipeline/ may be a symlink
    root = Path(root).absolute() if root else data_root(batch_dir)
    channel, script, video, slug = batch_video(batch_dir, key, root=root, accepted=accepted)
    data = root if (root / "channels").is_dir() else ROOT
    ch, cfg, pub = channel_config(channel, data)
    terms = attribution_terms_of(ch, data)
    language = cfg.get("language") or "en"
    given = draft
    if draft is None:
        if draft_file:
            draft = load_draft(draft_file)
        elif asker is not None:
            draft = ask_draft(asker, script, pub, pub.get("draft_language") or language)
        else:
            raise CardError("no draft: pass --draft FILE or let the model draft it")
    elif validate_draft(draft):
        raise CardError("the draft: " + "; ".join(validate_draft(draft)))
    topic = note_claims.judge_module().claims.topics_of(batch_dir).get(script.get("topic_id"))
    affiliate = affiliate_of(cfg, _channel_ids().channel_config_path(ch, data), script, topic)
    card = compose(script, video, draft, pub, cfg, topic, affiliate)
    problems = card_problems(card, script, language, pub, terms)
    redrafted = False
    if asker is not None and draft_file is None and given is None and \
            any(p["code"] in REDRAFTABLE for p in problems):
        # one redraft: the model is told what the checks refused (a title over
        # the limit or stronger than its source, a URL in block 1, ...)
        draft = ask_draft(asker, script, pub, pub.get("draft_language") or language,
                          previous=draft, problems=[f"{p['code']}: {p['detail']}"
                                                    for p in problems])
        card = compose(script, video, draft, pub, cfg, topic, affiliate)
        problems = card_problems(card, script, language, pub, terms)
        redrafted = True
    out = Path(out) if out else batch_dir / CARD_DIR / f"{slug}.md"
    meta = {"slug": slug, "channel": ch, "batch": _rel(batch_dir, root),
            "script_id": script.get("script_id"), "topic_id": script.get("topic_id"),
            "video": _rel(video.get("output_path") or "", root)}

    def write(card):
        text = render_note(card, meta)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        return text

    def check():
        return note_claims.check_note(out, asker, batch=batch_dir,
                                      script_id=script.get("script_id"), root=root, jobs=jobs,
                                      now=now, affiliate=_affiliate().labels_of(affiliate))

    text = write(card)
    verdict = {"verdict": "not run", "struck": []}
    claim_redrafted = False
    if claims and not problems:
        if asker is None:
            raise CardError("the claim check needs the model (or --no-claims for a draft view)")
        result = check()
        passed = result["action"] == note_claims.judge_module().ACTION_PASS
        if not passed and given is None and draft_file is None and \
                result["problems"] and not any(p.get("video") for p in result["problems"]):
            # CF-0728: the writer of the note rewrites what the claim check
            # refused in the note's own words (CF-0555 Q3: a title is not cut)
            # - once, told the judge's reason and what was missing; the
            # redraft goes through every check again. The video's own claims
            # failing are the video's problem: no redraft fixes them.
            claim_redrafted = True
            draft = ask_draft(asker, script, pub, pub.get("draft_language") or language,
                              previous=draft, problems=[_claim_problem(p)
                                                        for p in result["problems"]])
            card = compose(script, video, draft, pub, cfg, topic, affiliate)
            problems = card_problems(card, script, language, pub, terms)
            text = write(card)
            if not problems:
                result = check()
                passed = result["action"] == note_claims.judge_module().ACTION_PASS
        if problems:
            verdict["verdict"] = "not run (the redraft has problems first)"
        else:
            verdict = {"verdict": "passed" if passed else "failed",
                       "claims": len(result.get("lines") or []),
                       "struck": [s.get("text") for s in result.get("struck") or []]}
            if passed:
                text = note_claims.write_note(out, result, model=getattr(asker, "model", None),
                                              now=now)
                card["description"] = publish_note.title_and_description(
                    publish_note.sections(text))[1]
            else:
                problems.extend(dict(p, where=f"claims/{p.get('where')}")
                                for p in result["problems"])
    elif claims and problems:
        verdict["verdict"] = "not run (the card has problems first)"
    elif not claims:
        problems.append({"code": "claims_not_checked", "where": "claims",
                         "detail": "built with --no-claims: the claim check of CF-0555 was "
                                   "not run", "fix": "build again without --no-claims"})
    status = READY if not problems else NOT_READY
    mark = {"rule": RULE, "status": status, "channel": ch, "slug": slug,
            "batch": meta["batch"], "script_id": meta["script_id"], "topic_id": meta["topic_id"],
            "source": card["source"], "fact_checks": card["fact_checks"],
            "attributions": card["attributions"],
            # CF-0664: only when the video credits footage - a card of a video
            # without credits keeps its marker as it was
            **({"footage_credits": card["footage_credits"]} if card["footage_credits"] else {}),
            # CF-0593: only on a channel with the slot - placed or not, and why
            **({"affiliate": card["affiliate"]} if card["affiliate"] is not None else {}),
            # CF-0891: a video accepted despite its refusal after the render
            **({"refused_after_render": video["refused_after_render"]}
               if video.get("refused_after_render") else {}),
            "claims": verdict, "problems": [p.get("code") for p in problems],
            # CF-0747: what failed and where - the user's ruling reads it
            **({"failing": [{"code": p.get("code"), "where": p.get("where"),
                             "video": bool(p.get("video")), "text": p.get("text")}
                            for p in problems]} if problems else {}),
            "built_at": now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "draft": ("file:" + str(draft_file)) if draft_file else (
                "given" if given is not None else "model:" + str(getattr(asker, "model", ""))
                + (" (redrafted once)" if redrafted else "")
                + (" (redrafted after the claim check)" if claim_redrafted else "")),
            "fingerprint": note_claims.fingerprint(text)}
    text = _replace_section(text, SECTION, card_section(mark, problems))
    out.write_text(text, encoding="utf-8")
    return {"status": status, "path": str(out), "card": card, "problems": problems,
            "claims": verdict, "mark": mark, "text": text}


def view(text, path=None):
    """The short text shown to the user with the video at the acceptance."""
    sec = publish_note.sections(text)
    title, description = publish_note.title_and_description(sec)
    mark = mark_of(text) or {}
    st = card_status(text)
    out = [f"Карточка `{mark.get('slug') or (Path(path).stem if path else '?')}` — "
           + ("готова" if st["state"] == READY else
              "принята решением пользователя (CF-0747)" if st["state"] == RULED
              else f"НЕ готова ({st['why']})"),
           f"Название: {title}", "Описание:"]
    out += ["  " + ln if ln else "" for ln in description.splitlines()]
    out.append(f"Теги: {sec.get('Теги', '')}")
    claims = mark.get("claims") or {}
    out.append(f"Утверждения (CF-0555): {claims.get('verdict', '?')}"
               + (f", вычеркнуто: {'; '.join(claims['struck'])}" if claims.get("struck") else ""))
    if path:
        out.append(f"Файл: {path}")
    return "\n".join(out)


# ------------------------------------------------------------------ place
def place(batch_dir, key, channel=None, day=None, replace=False, root=None, schedule=True,
          now=None, report=None):
    """After the acceptance: the ready card goes next to the video in
    `publish/<channel>/<bucket>/` (where `acceptance.place()` put it).

    CF-0587: a video waiting in `_queue/` with no `day` given is put into the
    channel's nearest free slot (`publish_queue.plan_slot`: accepted, no hold,
    channel not paused - CF-0569, see below -, the candidate checks agree) - the slot is written into
    the card's `## Публикация` and the pair moves into the day folder
    (`publish_layout.assign`: README row and `publish_path` follow). A channel
    with no `publisher.slot`, or `schedule=False`, leaves the card in `_queue/`.

    CF-0569: a paused channel (`channel_pause.py`) leaves the card in `_queue/`
    too, and `report` gets a `PAUSED` line saying why - the place succeeds, the
    slot waits for the pause to be cleared.

    CF-0042: the slot passes the pattern window first - a reorder moves the
    other videos of the plan (`publish_queue.apply_moves`) before this one; the
    video may stay in `_queue/` when another took its slot. Every warning of
    the plan and what was moved go into `report` (a list) for the caller to
    print; afterwards the ledger's publication columns are brought up to date
    from the upload journal (`publish_window.record_published`).
    Returns the card's path."""
    report = report if report is not None else []
    batch_dir = Path(batch_dir).absolute()   # not resolve(): a worktree's pipeline/ may be a symlink
    root = Path(root).absolute() if root else data_root(batch_dir)
    ch, _script, _video, slug = batch_video(batch_dir, key, root=root)
    src = batch_dir / CARD_DIR / f"{slug}.md"
    if not src.is_file():
        raise CardError(f"{src}: no card - build it first")
    text = src.read_text(encoding="utf-8")
    ready, why = placeable(text)
    if not ready:
        raise CardError(f"{src}: the card is not ready ({why}) - it does not go to publish/")
    channel = _channel_ids().resolve_channel(channel or ch, root)
    # CF-0857: the video of THIS batch (its acceptance row's `publish_path`), not
    # the latest place of the name - a channel reuses names (23.10 Tech `anthropic`)
    import acceptance                                          # noqa: PLC0415
    try:
        entry, where = publish_layout.of_batch(slug, batch_dir.name, root / "publish", channel,
                                               day, log_path=acceptance_log_of(root))
    except acceptance.AcceptanceError as exc:
        raise CardError(f"{slug}: {exc}") from exc
    if not entry or not entry.get("mp4") or not Path(entry["mp4"]).is_file():
        raise CardError(f"{slug}: no video of batch {batch_dir.name} in publish/{channel}/ - "
                        f"the card follows an accepted video placed by acceptance.place(), it "
                        f"does not precede it" + (f" ({where})" if where else ""))
    dst = Path(entry["mp4"]).with_suffix(".md")
    if dst.is_file() and not replace:
        raise CardError(f"{dst}: a note is already there - pass --replace to put the card over it")
    plan = None
    if schedule and day is None and entry["bucket"] == publish_layout.QUEUE:
        try:
            if publish_queue.slot_config(channel, root) is not None:
                plan = publish_queue.plan_slot(channel, batch_dir.name, slug, root, now)
        except publish_queue.Paused as exc:
            report.append(f"PAUSED {exc} - the card waits in _queue/ until the pause is cleared "
                          f"(channel_pause.py show --channel {channel})")
        except publish_queue.QueueError as exc:
            raise CardError(f"{slug}: no slot - {exc}") from exc
    if plan is not None:
        if plan.get("note"):
            report.append(plan["note"])
        report.extend(f"WARNING {w}" for w in plan.get("warnings") or [])
        if plan.get("moves"):
            report.extend(f"moved {m}" for m in publish_queue.apply_moves(channel, plan["moves"], root))
        _record_published(channel, root, now, report)
    if plan is None or plan["slot"] is None:
        dst.write_text(text, encoding="utf-8")
        return dst
    text = _replace_section(text, "Публикация", plan["line"])
    dst.write_text(text, encoding="utf-8")
    try:
        publish_layout.assign(slug, channel, plan["day"], publish=root / "publish", apply=True,
                              stem=entry.get("stem"))
    except publish_layout.LayoutError as exc:
        raise CardError(f"{slug}: the card names {plan['day']} but the pair was not moved out of "
                        f"_queue/ ({exc}) - fix and run `runlog publish assign {slug} --channel "
                        f"{channel} --apply`") from exc
    # CF-0920: a day folder carries the plain name, whatever the file was in _queue/
    return publish_layout.bucket_dir(root / "publish", channel, plan["day"]) / f"{slug}.md"


def _record_published(channel, root, now, report):
    import publish_window                                       # noqa: PLC0415
    try:
        res = publish_window.record_published(channel, root, now)
    except (publish_window.WindowError, publish_queue.QueueError) as exc:
        report.append(f"WARNING ledger publication columns not updated ({publish_window.TASK}): {exc}")
        return
    if res["filled"]:
        report.append(f"ledger: publication columns filled for {', '.join(res['filled'])}")
    if res.get("shifted"):
        report.append(f"ledger: {publish_window.shifted_line(res['shifted'])}")
    for c in res["conflicts"]:
        report.append(f"WARNING ledger conflict ({publish_window.TASK}): "
                      f"{json.dumps(c, ensure_ascii=False)}")


# ---------------------------------------------------------------- the command
def _notify_bus():
    """CF-0591: the notification bus `shared/notify.py` - None when it cannot be
    loaded: a notification is never on the critical path."""
    try:
        shared = str(ROOT / "shared")
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus
        return bus
    except Exception:                                            # noqa: BLE001
        return None


def acceptance_log_of(root=None):
    """The acceptance record a card's root reads: `<root>/publish/acceptance-log.json`,
    or the record's own default (`$ACCEPTANCE_LOG`, `$FACTORY_ROOT`, this checkout)."""
    import acceptance                                          # noqa: PLC0415
    return Path(root) / acceptance.ACCEPTANCE_LOG_REL if root else acceptance.default_log()


def verdict_of(channel, batch_id, slug, root=None):
    """CF-0748: the user's verdict on one video in the acceptance record
    (`accepted` / `rejected`, a verdict still pending in the queue of CF-0675
    counts), or None when he was never asked. Raises
    `acceptance.AcceptanceError` when the record does not read."""
    import acceptance                                          # noqa: PLC0415
    row = acceptance.find(channel, batch_id, slug, path=acceptance_log_of(root))
    return (row or {}).get("verdict") or None


def notify_accept(result, root=None, batch=None):
    """CF-0591: a ready card is a video waiting for the user's "yes" - one
    notification per video (channel, batch, slug), linked to the console's
    acceptance section. A card built again is not sent again; a card that is
    not ready is not sent (it is fixed first). Never raises.

    CF-0748: only a video with NO verdict in the acceptance record waits for
    the "yes" - a card rebuilt after the video was accepted (or rejected) sends
    nothing (13.10, blade-runner-2099's card rebuilt after the acceptance said
    «ждёт приёмки»). A record that does not read sends nothing either."""
    try:
        if result.get("status") != READY:
            return None
        if root is None and batch is not None:
            root = data_root(Path(batch).absolute())
        m = result.get("mark") or {}
        ch, slug = m.get("channel"), m.get("slug")
        batch = Path(str(m.get("batch") or "")).name
        verdict = verdict_of(ch, batch, slug, root)
        if verdict is not None:
            return None
        bus = _notify_bus()
        if bus is None:
            return None
        title = (result.get("card") or {}).get("title") or slug
        return bus.send("accept", f"accept:{ch}:{batch}:{slug}",
                        f"{ch}: ролик «{title}» ждёт приёмки - карточка готова",
                        channel=ch, link=bus.link_of(ch, "acceptance"),
                        root=Path(root) if root else None)
    except Exception as e:                                       # noqa: BLE001
        print(f"NOTIFY accept: {e.__class__.__name__}: {e}", file=sys.stderr)
        return None


def _asker(args, batch_dir):
    """The card's asker: its own cache (`work/publish-card/cache/` - the
    drafts, the note's claims) written, the writer's claim cache read first
    (CF-0872). Three accepted videos of 2026-10-20 / 26 (i-play-rocky,
    coyote-vs-acme, android-tv): the stage's judge had answered `follows`
    once, the card put the very same request (the same key) into its own
    empty cache, drew `not_enough` twice and struck a rendered video's claim.
    The stage's answers now stand at the card; how sure a `follows` has to be
    is decided once, by the stage, before the voice and the render
    (`claim_judge.ask_entailment`: a `follows` is confirmed)."""
    cj = note_claims.judge_module()
    return cj.Asker(args.cache_dir or (Path(batch_dir) / CARD_DIR / "cache"), args.answer_cmd,
                    args.model or cj.DEFAULT_MODEL, args.timeout or cj.DEFAULT_TIMEOUT,
                    read_first=[Path(batch_dir) / cj.CACHE_REL])


def main(argv=None, accepted=None):
    """The CLI. `accepted` is not a flag: only `card_center.run` passes it - the
    detached build of a video whose verdict was being recorded (CF-0891)."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build and check one card")
    b.add_argument("batch")
    b.add_argument("key", help="the video's slug or script id")
    b.add_argument("--draft", help="a JSON draft {title, about, hashtags, tags} instead of the model")
    b.add_argument("--out")
    b.add_argument("--root")
    b.add_argument("--no-claims", action="store_true", help="skip CF-0555 (the card stays not ready)")
    b.add_argument("--answer-cmd")
    b.add_argument("--model")
    b.add_argument("--timeout", type=int)
    b.add_argument("--jobs", type=int)
    b.add_argument("--cache-dir")
    b.add_argument("--now")
    b.add_argument("--json", action="store_true")
    s = sub.add_parser("show", help="the short view of a card")
    s.add_argument("card")
    pl = sub.add_parser("place", help="put the ready card next to the accepted video")
    pl.add_argument("batch")
    pl.add_argument("key")
    pl.add_argument("--channel")
    pl.add_argument("--day")
    pl.add_argument("--replace", action="store_true")
    pl.add_argument("--root")
    pl.add_argument("--no-slot", action="store_true",
                    help="leave the card in _queue/ - no slot from the channel's queue (CF-0587)")
    pl.add_argument("--now", help="the clock for the slot (ISO with a zone; tests)")
    args = ap.parse_args(argv)

    if args.cmd == "show":
        try:
            text = Path(args.card).read_text(encoding="utf-8")
        except OSError as exc:
            print(f"PUBLISH CARD: cannot read {args.card} ({exc})", file=sys.stderr)
            return EXIT_REFUSED
        print(view(text, args.card))
        return EXIT_READY if placeable(text)[0] else EXIT_NOT_READY
    if args.cmd == "place":
        report = []
        try:
            dst = place(args.batch, args.key, args.channel, args.day, args.replace, args.root,
                        schedule=not args.no_slot, now=args.now, report=report)
        except CardError as exc:
            print(f"PUBLISH CARD: {exc}", file=sys.stderr)
            return EXIT_REFUSED
        print(f"ok   the card is at {dst}")
        for line in report:
            print(f"     {line}")
        if dst.parent.name == publish_layout.QUEUE:
            print("     no slot: it waits in _queue/ (the channel is paused, has no publisher.slot, "
                  "--no-slot, or the pattern window gave its slot to another video - see above)")
        else:
            body = publish_note.sections(dst.read_text(encoding="utf-8")).get("Публикация", "")
            print(f"     slot: {body.strip().splitlines()[0] if body.strip() else dst.parent.name}")
        return EXIT_READY

    cj = note_claims.judge_module()
    try:
        asker = None if (args.draft and args.no_claims) else _asker(args, args.batch)
        result = build(args.batch, args.key, draft_file=args.draft, out=args.out, root=args.root,
                       asker=asker, claims=not args.no_claims, jobs=args.jobs, now=args.now,
                       accepted=accepted)
    except (CardError, note_claims.NoteClaimsError) as exc:
        print(f"PUBLISH CARD: refused - {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except cj.CannotAsk as exc:
        print(f"PUBLISH CARD: cannot ask the model - {exc}", file=sys.stderr)
        return EXIT_NOT_ASKED
    notify_accept(result, args.root, batch=args.batch)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "text"},
                         ensure_ascii=False, indent=2, default=str))
    else:
        print(view(result["text"], result["path"]))
        for p in result["problems"]:
            print(f"  {p.get('code')} [{p.get('where')}] {p.get('detail') or p.get('text') or ''}")
    return EXIT_READY if result["status"] == READY else EXIT_NOT_READY


if __name__ == "__main__":
    sys.exit(main())
