#!/usr/bin/env python3
"""Where does this footage candidate come from? (CF-0297)

Why this module exists. The batch `example-film/2026-09-19T0116Z` passed the
two-source gate (CF-0129) on all five of its topics and produced one script.
What the five topics were actually given became visible only when the indexer
described the shots:

    WQEC_tH0UP8  Luucy Ai                 "... Official-Style Fanmade Concept Trailer ..."
    PEiDNOQ_0ms  Manuel Over Ride (M.O.R.) "World War Lay-Z ... #VRGaming"
    QJ1WSiMUVFA  Draco Owns Me <3          "Hp is not just a movie ... #fyp #viral"
    Cym8eElO6c0  The Real Radio Show 247   "Kimberly Brooks on The Simpsons, Pine Park ..."
    wS6wtevVlmc  JoBlo Action 4K           "The Villain Gets ... | Rennick Season 3 | CLIP"

Four of the five carried no frame of the work at all - a fan concept trailer,
a blogger's game capture, a captioned nostalgia compilation, a podcast
recording that yielded one static frame in 31.8 seconds - and the topics died
downstream as `thin_scene` / `no_second_source`. Nothing upstream could see
it: `topic_relevance.py` (CF-0272) asks whether an upload *names* the work,
and every one of these does; `footage_candidates.py` asks what *nature* of
shoot the title claims, and "Fanmade Concept Trailer" claims to be a trailer.
Neither asks who shot it.

That is the question here, and it is answered from the one thing discovery
knows before it downloads anything - the metadata the search returned:

  * **official** - the channel is a studio's, a streamer's, a network's or a
    distributor's. Its upload of the work *is* the work's footage.
  * **unofficial** - a word in the title, the description or the channel name
    says the upload is somebody's video *about* the work: fan made, concept,
    gameplay, edit, reaction, parody, a short-form repost, a podcast. It
    leaves the pool with `reason_code: unofficial_source`, the way CF-0272's
    `wrong_work` does, and for the same reason: a drop that is recorded is a
    drop that can be argued with.
  * **unknown** - neither. Still offered, because most honest footage on
    YouTube comes from channels no list will ever hold, but after every
    official upload of its own nature.

Two rules that are decisions, not mechanics, and are written down where the
decision was made (the user, 2026-09-20, on this task):

  1. **An official channel is never sieved.** A word in a Example Studios title is
     not evidence about a Example Studios upload, and the official trailer is the
     most honest source the pipeline has; losing it to a stop word would be the
     sieve eating exactly what it exists to protect.
  2. **A studio's small corner logo is not a DoD item 2 violation.** Burnt-in
     subtitles, titles and captions are. That decision belongs to the frame
     judge, not here, but it is why `official` is a preference and not a
     requirement: requiring it would leave the channel with trailers only.

The lists themselves - which channels are official, which words are stop words
- are data, not constants in this file. They are appended to every time a
batch shows a channel or a genre nobody had seen, and that is config work.
CF-0627 (CF-0561) split them by whose they are: the **official channels** are
the channel's own list (`<root>/channels/<id>/footage-origin.json`, read
through the root's `shared/channel_data.py` - a science channel's official
sources are not film studios), so `load_config(channel)` takes the batch's
channel and there is no default one; the **stop words** - what makes an
upload somebody's video *about* the work - are the rule, common to every
channel, and stay in `config/footage_origin.json`. Every stop word in that file carries `seen_in`:
the real upload, out of a real pool, that the word was read off. The whole list
was replayed over the 46 videos that have ever been fetched as a canonical
source in this project and hits five of them - the four fan uploads above plus
`eTvRCugVK1Q` ("Rennick didn't die #rennick #reacherseason4 #foryou") - and
nothing else.

Used from `footage_candidates.py`, in two places:
  * `partition()` takes the unofficial uploads out of the pool *before*
    grouping and ranking, beside CF-0272's relevance drop, so a dropped upload
    is replaced by the next real candidate instead of costing the topic a slot;
  * `rank()` orders what is left inside each nature, official first.

CLI (no network, reads a written batch or a saved search; the channel is the
batch's, or `--channel` for a saved search):
  scripts/footage_origin.py <batch-dir|01-trend-hunter.json>
  scripts/footage_origin.py /tmp/footage-rennick.json --channel example-film
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _channel_data import channel_data  # noqa: E402  - CF-0627
from _channel_ids import resolve_channel  # noqa: E402

# The rule half: `stop_words`, common to every channel. The official channels
# are the channel's (`channel_data.footage_origin(channel)`), not in here.
CONFIG_PATH = HERE.parent / "config" / "footage_origin.json"
OFFICIAL_KEY = "official_channels"

# The three answers. The order is the ranking order: `official` before
# `unknown`, and `unofficial` never reaches a pool at all - it is here so that
# a record written by the CLI or by a test can still name it.
ORIGINS = ("official", "unknown", "unofficial")
OFFICIAL, UNKNOWN, UNOFFICIAL = ORIGINS

# The code an upload leaves a pool with. Like CF-0272's `wrong_work` this is
# *not* a `shared/runlog/funnel.py` FUNNEL_CODE: the funnel counts topics
# leaving a batch, and this is one upload leaving a topic's pool. A topic the
# sieve empties is refused by footage_candidates.py with the funnel's own
# `no_source`, and a topic left under the floor carries a shortfall saying how
# many uploads were unofficial.
UNOFFICIAL_CODE = "unofficial_source"

# Where a stop word may be read. The channel name is in the list because that
# is where half of them live ("Hypersphere Edits", "The Real Radio Show 247"),
# and the description is trimmed for the reason `footage_candidates._text`
# trims it: past the first lines it is boilerplate that matches everything.
STOP_FIELDS = ("title", "description", "channel_title")
DESCRIPTION_HEAD = 240

# The keys of one drop record - the same shape as
# `topic_relevance.EXCLUSION_KEYS`, so `footage_candidates_dropped` stays one
# list of one kind of record whatever took the upload out of the pool.
EXCLUSION_KEYS = ("video_id", "title", "channel_title", "view_count",
                  "reason_code", "reason")

_CACHE = {}

# CF-0361: a YouTube channel id, and the whole-token wrapper every name
# pattern is compiled inside (CF-0347: 'dc' inside 'Podcast').
CHANNEL_ID_RE = re.compile(r"^UC[0-9A-Za-z_-]{22}$")
TOKEN_EDGE = r"(?<![0-9a-z])(?:{})(?![0-9a-z])"

# CF-0567 (TH step of the root's docs/tech-footage.md): the factory's own
# screen recording of a tool (`fetch_own_capture.py`, VE's capture_tool.py).
# Its candidate id is `own_capture:<id>` - the Footage Indexer's ingest key -
# and its origin is the channel's `footage_origins[].id` `own_capture`.
OWN_CAPTURE = "own_capture"
OWN_CAPTURE_HEAD = "own_capture:"
# CF-0689: the graphics the factory draws itself from the script's facts
# (root `shared/own_graphic.py`, rendered by the Video Editor) - the
# channel's `footage_origins[].id` `own_graphic`, whose presence is the
# channel's switch for them (ExampleTech). Never a candidate: drawn, never
# fetched, never in the pool.
OWN_GRAPHIC = "own_graphic"
# CF-0690: the factory's own call of a model's official API ("a demo via
# API", root `shared/api_demo.py`) - the channel's `footage_origins[].id`
# `api_demo`, whose presence is the switch for `fetch_api_demo.py`; the
# calls' models, prompts and caps are the document's top-level `api_demo`
# block (`config["api_demo"]`).
API_DEMO = "api_demo"
# `official_channels[].role` of a vendor channel whose uploads are short
# proof quotes and never the base of a video (ExampleTech, grill Q18).
PROOF_QUOTE = "proof_quote"


def is_own_capture(video):
    """CF-0567: a record of the factory's own recording - `kind: own_capture`
    or an `own_capture:<id>` id - not an upload of anybody's."""
    video = video or {}
    return video.get("kind") == OWN_CAPTURE or \
        str(video.get("video_id") or "").startswith(OWN_CAPTURE_HEAD)


def has_own_capture(config):
    """CF-0567: whether the channel's footage-origin.json names the
    `own_capture` origin (ExampleTech) - the channels whose topics are
    recorded and whose footage is read in the tech kind set when they name
    no `footage_kinds`."""
    return any((o or {}).get("id") == OWN_CAPTURE
               for o in (config or {}).get("footage_origins") or [])


def has_own_graphic(config):
    """CF-0689: whether the channel's footage-origin.json names the
    `own_graphic` origin (ExampleTech) - the channels a topic may stand on
    the graphics drawn from its quotable facts instead of footage."""
    return any((o or {}).get("id") == OWN_GRAPHIC
               for o in (config or {}).get("footage_origins") or [])


def has_api_demo(config):
    """CF-0690: whether the channel's footage-origin.json names the
    `api_demo` origin (ExampleTech) - the channels a topic about a model the
    channel's list names may get that model's real answer to one of the
    channel's prompts (`fetch_api_demo.py`)."""
    return any((o or {}).get("id") == API_DEMO
               for o in (config or {}).get("footage_origins") or [])


def api_demo_block(config):
    """CF-0690: the channel's `api_demo` block (models, prompts, caps), or
    None when it has none."""
    block = (config or {}).get(API_DEMO)
    return block if isinstance(block, dict) else None


def role_of(video, config=None):
    """CF-0567: the role of the official channel this upload is on
    (`official_channels[].role`: `proof_quote` on ExampleTech's vendors), or
    None - off the list, or an entry that names no role (ExampleFilm's
    studios, ExampleScience's agencies)."""
    if is_own_capture(video):
        return None
    return (official_channel(video, config) or {}).get("role") or None


class ConfigError(Exception):
    """The config is unusable. Raised rather than defaulted: a sieve that
    silently falls back to an empty list is a sieve that passes everything,
    and nothing downstream would say so."""


def load_config(channel, root=None, path=None):
    """-> the channel's config, compiled and cached by channel, root and path:
    `official_channels` of the channel's own list (`channel_data.
    footage_origin(channel)`, CF-0627), `stop_words` of the common rule file
    (`path`, default CONFIG_PATH).

    The channel is required - there is no default one (CF-0213): a caller
    hands in the batch's `channel` (a former id resolves) or the CLI's
    `--channel`. A channel without its list is a ConfigError naming the file,
    never another channel's list or an empty one.

    Every pattern is compiled here, at load, so a typo in the config is a
    failure of the run that loaded it and not of the batch that happens to
    contain the title it would have matched.
    """
    if not isinstance(channel, str) or not channel.strip():
        raise ConfigError("no channel named - the official footage channels are the "
                          "channel's list (channels/<id>/footage-origin.json, CF-0627) "
                          "and there is no default channel (CF-0213)")
    path = Path(path or CONFIG_PATH)
    channel = resolve_channel(channel.strip(), root=root)
    key = (channel, str(root or ""), str(path.resolve()) if path.exists() else str(path))
    if key in _CACHE:
        return _CACHE[key]
    if not path.exists():
        raise ConfigError(f"no footage-origin rule file (stop_words) at {path}")
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    try:
        own = channel_data.footage_origin(channel, root=root)
    except channel_data.ChannelDataError as exc:
        raise ConfigError(str(exc)) from exc
    where = f"channels/{channel}/footage-origin.json"

    official, stop, by_id = [], [], {}
    for i, entry in enumerate((own or {}).get(OFFICIAL_KEY) or []):
        pattern = (entry or {}).get("pattern")
        if not pattern:
            raise ConfigError(f"{where}: official_channels[{i}] has no pattern")
        channels = (entry or {}).get("channels") or []
        for j, ch in enumerate(channels):
            cid = (ch or {}).get("id")
            if not (isinstance(cid, str) and CHANNEL_ID_RE.match(cid)):
                raise ConfigError(f"{where}: official_channels[{i}].channels[{j}] has no "
                                  f"usable YouTube channel id ({cid!r})")
            if cid in by_id:
                raise ConfigError(f"{where}: channel id {cid} is listed twice "
                                  f"({by_id[cid]['pattern']!r} and {pattern!r})")
            if not (ch.get("resolved_by")):
                raise ConfigError(f"{where}: official_channels[{i}].channels[{j}] ({cid}) "
                                  f"says nothing about how it was resolved (CF-0361)")
        compiled = dict(entry, _re=_compile(TOKEN_EDGE.format(pattern),
                                            f"{where} official_channels[{i}]"))
        for ch in channels:
            by_id[ch["id"]] = compiled
        official.append(compiled)
    for i, entry in enumerate(raw.get("stop_words") or []):
        pattern = (entry or {}).get("pattern")
        code = (entry or {}).get("code")
        if not pattern or not code:
            raise ConfigError(f"{path}: stop_words[{i}] needs both `code` and `pattern`")
        if not ((entry.get("seen_in") or {}).get("video_id")):
            raise ConfigError(
                f"{path}: stop_words[{i}] ({code}) has no seen_in.video_id - a stop word "
                f"nobody can point at in a real pool is a threshold by eye (CF-0297)")
        stop.append(dict(entry, _re=_compile(pattern, f"{path} stop_words[{i}]")))
    if not official:
        raise ConfigError(f"{where}: official_channels must be non-empty")
    if not stop:
        raise ConfigError(f"{path}: stop_words must be non-empty")
    # CF-0662 (TH-2): the channel's licence lists and its footage origins, as
    # the channel wrote them - read by `footage_candidates.licence_block`. A
    # channel without a `licences` block (ExampleFilm) gets None: no licence
    # judgement, today's footing (docs/science-footage.md of the root).
    licences = (own or {}).get("licences")
    config = {"path": path, "channel": channel, "official_path": where,
              "official_channels": official, "stop_words": stop, "by_channel_id": by_id,
              "licences": licences if isinstance(licences, dict) else None,
              "footage_origins": [o for o in (own or {}).get("footage_origins") or []
                                  if isinstance(o, dict)],
              # CF-0662 (TH-1): which set of upload natures this channel's
              # footage is read in (`footage_candidates.KIND_SETS`); absent =
              # the film set, ExampleFilm's - or, CF-0567, the tech set for a
              # channel whose origins name `own_capture` (`kind_set`).
              "footage_kinds": (own or {}).get("footage_kinds"),
              # CF-0690: the calls of the `api_demo` origin - models, prompts,
              # caps (`fetch_api_demo.py`); None on a channel without the block.
              API_DEMO: ((own or {}).get(API_DEMO)
                         if isinstance((own or {}).get(API_DEMO), dict) else None)}
    _CACHE[key] = config
    return config


def _require(config):
    """The config a caller handed in. There is none to load here: which
    channels are official is the channel's list, and only the caller knows
    the channel (`load_config(channel)`, CF-0627)."""
    if config is None:
        raise ConfigError("no footage-origin config handed in - load it with "
                          "load_config(<the batch's channel>) and pass it on (CF-0627)")
    return config


def _compile(pattern, ctx):
    try:
        return re.compile(pattern, re.I)
    except re.error as exc:
        raise ConfigError(f"{ctx}: {pattern!r} is not a regular expression: {exc}") from exc


def official_channel(video, config=None):
    """-> the config entry this upload's channel is, or None.

    CF-0361: by the channel's **id** when the record carries one
    (`channel_id`, written by both fetchers since CF-0361) - an upload whose id
    is not on the registry is not official, whatever its channel calls itself
    ("Dc Comics & Zenith", "TopMovieClips"). A record without an id (every
    batch before CF-0361, the test fixtures) falls back to the name pattern,
    matched on whole tokens of `channel_title` (CF-0347).

    Never the description, and never the title: "| Example Studios" at the end of
    a title is what a re-upload copies first, and CF-0272 exists because a
    network's name in the metadata is not evidence about the video.
    """
    config = _require(config)
    # CF-0665: an archive file is on no YouTube channel - its officiality is
    # the archive's (`archive_official`), never a name match on "NASA".
    if (video or {}).get("archive_origin") or is_own_capture(video):
        return None
    cid = (video or {}).get("channel_id")
    if cid:
        return config["by_channel_id"].get(cid)
    return name_pattern(video, config)


def name_pattern(video, config=None):
    """-> the entry whose name pattern matches `channel_title` on whole
    tokens, or None - regardless of the channel id. `origin_of` uses it to say
    that a channel *looks* official but its id is not registered."""
    config = _require(config)
    channel = (video or {}).get("channel_title") or ""
    for entry in config["official_channels"]:
        if entry["_re"].search(channel):
            return entry
    return None


def channel_ids(config=None):
    """-> {channel_id: entry} over the whole registry (CF-0361)."""
    config = _require(config)
    return dict(config["by_channel_id"])


def _owner_tokens(text):
    return re.findall(r"[a-z0-9+]+", str(text or "").lower())


def owner_parts(*names):
    """'Example Studios/Legendary', 'Hulu' -> [['warner', 'bros'], ['legendary'],
    ['hulu']]: a `rights_holder` or `network` string split into the companies
    it names."""
    parts = []
    for name in names:
        for part in re.split(r"[/,&;]|\band\b", str(name or ""), flags=re.I):
            toks = _owner_tokens(part)
            if toks and toks not in parts:
                parts.append(toks)
    return parts


def owned_by(entry, parts):
    """True when one of the entry's owners (default: its pattern) is a run of
    whole tokens inside one of `parts` ('sony' in 'Example Pictures')."""
    owners = entry.get("owners")
    if owners is None:
        owners = [re.sub(r"[\^$]", "", entry.get("pattern") or "")]
    for owner in owners:
        o = _owner_tokens(owner)
        if not o:
            continue
        for p in parts:
            if any(p[k:k + len(o)] == o for k in range(len(p) - len(o) + 1)):
                return True
    return False


def feed_channels(rights_holder=None, network=None, config=None, houses=()):
    """-> (owned, general): the registry channels of this topic's rights holder
    and network, and the licensed distributors read for every topic. Each item
    is {"id", "title", "pattern"}. CF-0361.

    CF-0662 (TH-1): `houses` - the publishing houses whose feeds carried the
    topic (`sources.rss.feeds[].house`: `nasa`, `esa`) - name owners too. A
    science story has no rights holder; the agency that published it is whose
    official channels are read deep. A house no entry owns (`sciencedaily`,
    ExampleFilm's `pmc`) reads nothing."""
    config = _require(config)
    parts = owner_parts(rights_holder, network, *(houses or ()))
    owned, general = [], []
    for entry in config["official_channels"]:
        rows = [{"id": ch["id"], "title": ch.get("title"), "pattern": entry["pattern"]}
                for ch in entry.get("channels") or []]
        if entry.get("general"):
            general.extend(rows)
        elif parts and owned_by(entry, parts):
            owned.extend(rows)
    return owned, general


def stop_word(video, config=None):
    """-> (entry, field, matched_text) for the first stop word this upload
    hits, or (None, None, None). An official channel hits nothing: see rule 1
    in the module docstring."""
    config = _require(config)
    if official_channel(video, config) or archive_official(video) or is_own_capture(video):
        return None, None, None
    for field in STOP_FIELDS:
        value = (video or {}).get(field) or ""
        if field == "description":
            value = str(value)[:DESCRIPTION_HEAD]
        for entry in config["stop_words"]:
            found = entry["_re"].search(str(value))
            if found:
                return entry, field, found.group(0)
    return None, None, None


def origin_of(video, config=None):
    """-> (origin, why). `why` is one sentence naming what decided it, so that
    a record in the artifact can be read back without this module."""
    config = _require(config)
    if is_own_capture(video):
        cap = (video or {}).get("capture") or {}
        return OFFICIAL, (f"the factory's own recording of {cap.get('space') or (video or {}).get('source_url')!r} "
                          f"(origin {OWN_CAPTURE!r}, CF-0567) - our footage, no licence needed")
    if archive_official(video):
        return OFFICIAL, (f"the agency's own archive ({((video or {}).get('archive') or {}).get('name')}, "
                          f"origin {(video or {}).get('archive_origin')!r}) - a file it publishes "
                          f"itself (CF-0665)")
    entry = official_channel(video, config)
    if entry:
        return OFFICIAL, (f"the channel {(video or {}).get('channel_title')!r} is an official "
                          f"{entry.get('what') or 'channel'} ({entry['pattern']!r})")
    hit, field, text = stop_word(video, config)
    if hit:
        return UNOFFICIAL, (f"{field} says {text!r} ({hit['code']}): {hit['why']}")
    looks = name_pattern(video, config) if (video or {}).get("channel_id") else None
    if looks:
        return UNKNOWN, (f"the channel {(video or {}).get('channel_title')!r} is named like "
                         f"{looks['pattern']!r}, but its id {video.get('channel_id')} is not "
                         f"on the registry (CF-0361) - if it is theirs, add it to "
                         f"config/footage_origin.json with the upload it was read off")
    return UNKNOWN, ("no official channel and no stop word - offered, but after the official "
                     "uploads of its own nature")


def rank(video, config=None):
    """Sort key for two uploads of one nature: official first, then unknown."""
    origin, _ = origin_of(video, config)
    return ORIGINS.index(origin) if origin in ORIGINS else len(ORIGINS)


def is_official(video, config=None):
    return (official_channel(video, config) is not None or archive_official(video)
            or is_own_capture(video))


def archive_official(video):
    """CF-0665: a file out of an agency's own archive (the NASA Image and Video
    Library - `fetch_archive_footage.py` marks it `archive_official`) is that
    agency's footage, as an upload of its registered channel is. A Commons file
    is not: anyone uploads there, so it is sieved like a search upload."""
    return (video or {}).get("archive_official") is True


def origin_id(video, config=None):
    """CF-0662: the footage origin (`footage_origins[].id` of the channel's
    footage-origin.json) of the official channel this upload is on - its
    registry entry's `origin` - or None (not official, or an entry that
    names no origin: ExampleFilm's studios)."""
    if is_own_capture(video):
        return OWN_CAPTURE
    entry = official_channel(video, config)
    # CF-0665: an archive file names its origin itself (`archive_origin`:
    # nasa, nasa_jpl, wikimedia_commons).
    return (entry or {}).get("origin") or (video or {}).get("archive_origin") or None


def exclusion_record(video, hit, field, text):
    """One `unofficial_source` record, in the shape `footage_candidates_dropped`
    already holds."""
    return {
        "video_id": (video or {}).get("video_id"),
        "title": (video or {}).get("title"),
        "channel_title": (video or {}).get("channel_title"),
        "view_count": (video or {}).get("view_count"),
        "reason_code": UNOFFICIAL_CODE,
        "reason": (f"its {field} says {text!r} - {hit['why']} ({hit['code']}, CF-0297). "
                   f"An upload about the work is not footage of the work; it passes the "
                   f"two-source gate and dies at the frame judge."),
    }


def partition(videos, config=None):
    """-> (kept, dropped_records), the pool order preserved.

    Nothing is dropped when the pool would be emptied? No - it is. A pool that
    is entirely fan uploads *is* a topic with no source, and CF-0129's refusal
    path (`no_source`, with the counts in the shortfall) is the honest end of
    it. Keeping one fan trailer so that the topic survives to the indexer is
    what this task exists to stop.
    """
    config = _require(config)
    kept, dropped = [], []
    for video in videos or []:
        hit, field, text = stop_word(video, config)
        if hit:
            dropped.append(exclusion_record(video, hit, field, text))
        else:
            kept.append(video)
    return kept, dropped


def counts(videos, config=None):
    """{origin: n} over a list of uploads - what the pool record carries."""
    config = _require(config)
    out = {o: 0 for o in ORIGINS}
    for video in videos or []:
        out[origin_of(video, config)[0]] += 1
    return out


# --------------------------------------------------------------------------
# CLI - what the sieve would say about a written batch or a saved search,
# with no call to YouTube at all
# --------------------------------------------------------------------------

def _videos(path):
    """A saved `fetch_youtube_signal.py` output, or a written
    `01-trend-hunter.json` read back through its `footage_candidates` records
    (which is all a replay has: the batch file keeps no descriptions)."""
    path = Path(path).expanduser()
    if path.is_dir():
        path = path / "01-trend-hunter.json"
    data = json.loads(path.read_text())
    if "videos" in data:
        return [(data.get("query") or path.name, v) for v in data["videos"]]
    out = []
    for topic in (data.get("topics") or []) + (data.get("skipped_topics") or []):
        tid = topic.get("topic_id")
        for record in ((topic.get("evidence") or {}).get("footage_candidates") or []):
            out.append((tid, record))
    return out


def _batch_channel(source):
    """The `channel` of a batch file, resolved (CF-0197); None for a saved
    search or a batch without one."""
    path = Path(source).expanduser()
    if path.is_dir():
        path = path / "01-trend-hunter.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "videos" in data:
        return None
    return (resolve_channel(data.get("channel")) if str(data.get("channel") or "").strip()
            else None)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="a batch dir / 01-trend-hunter.json, or a saved search")
    ap.add_argument("--channel", help="the channel whose official footage channels are read "
                                      "(default: the batch's `channel`; required for a saved search)")
    ap.add_argument("--config", help=f"the stop-word rule file, default {CONFIG_PATH}")
    args = ap.parse_args(argv)

    channel = args.channel or _batch_channel(args.source)
    if not channel:
        print("no channel: a saved search names none - pass --channel (CF-0213, CF-0627)",
              file=sys.stderr)
        return 2
    try:
        config = load_config(channel, path=args.config)
    except ConfigError as exc:
        print(f"footage-origin: {exc}", file=sys.stderr)
        return 2
    rows = []
    for owner, video in _videos(args.source):
        origin, why = origin_of(video, config)
        rows.append({"topic": owner, "video_id": video.get("video_id"),
                     "channel_title": video.get("channel_title"),
                     "title": video.get("title"), "origin": origin, "why": why})
    tally = {o: len([r for r in rows if r["origin"] == o]) for o in ORIGINS}
    print(json.dumps({"config": str(config["path"]), "channel": config["channel"],
                      "official": config["official_path"], "counted": len(rows),
                      "by_origin": tally, "links": rows}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
