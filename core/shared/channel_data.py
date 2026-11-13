#!/usr/bin/env python3
"""CF-0561: the channel's own lists - where they live and the one way to read them.

Grill «Каналы ИИ и Наука» 2026-10-05/06, Q13. The factory grew up as one film
channel, and five lists it judges by were written as if they were the
factory's: the outlets a fact may be taken from, the kinds of fact, the
rights holders to be careful with, the official YouTube channels of footage,
the ceiling of publishing houses in the trend score. They are a *channel's*
data - a science channel takes its facts from Nature, not from Variety - and
they move under `channels/<id>/`. What stays common is the *rule* that reads
them: what a fact source is and how its tiers work (`shared/factrule/
fact_rule.py`), the independence of two sources and the claim checks (1.8,
CF-0551...0556), the shape of a rights-holder entry (`inserts_lib.
blacklist_check`). `docs/channel-data.md` is the table of what is whose.

The contract, for every reader in every repository:

    channel_list(channel, name, root=None)       the parsed file
    channel_list_path(channel, name, root=None)  where it is (it may not exist)
    channels_with(name, root=None)               the channels that have it
    fact_sources(channel, root=None)             channel_list(.., "fact-sources")
    fact_kinds(channel, root=None)               its `kinds`, as a tuple
    rights_holders(channel, root=None)           channel_list(.., "rights-holders")
    footage_origin(channel, root=None)           channel_list(.., "footage-origin")
    rss_house_ceil(channel, root=None)           `sources.rss.house_ceil` of
                                                 channels/<id>.json
    theme(channel, root=None)                    `theme` of channels/<id>.json -
                                                 the on-screen graphics' palette
                                                 and faces (CF-0572), checked
    theme_errors(theme)                          why a theme block is not valid
                                                 ([] when it is) - the one rule
                                                 the root validator and the
                                                 reader share
    feeds(channel, root=None)                    `sources.rss.feeds` of
                                                 channels/<id>.json (CF-0557)
    feed_urls(channel, root=None)                the feed URLs a collector may
                                                 read - every feed whose `use`
                                                 and `ai_policy` let it be read
    source_policy_errors(channel, root=None)     why the channel's outlets and
                                                 feeds break the AI-bot rule
                                                 ([] when they do not, CF-0557)
    attribution_terms(channel, root=None)        the outlets' bans on phrasing
                                                 the channel's AI output
                                                 (`ai_output_terms` of a
                                                 fact-sources entry, CF-0671)
    attribution_hits(text, terms)                the banned phrases a text
                                                 carries ([] when none)
    brand(channel, root=None)                    channels/<id>/brand.json, or
                                                 None when the channel has none
    ending(channel, root=None)                   its `ending` section, checked,
                                                 or None (CF-0722: the ending
                                                 clip and how it is rendered)
    ending_errors(section)                       why an `ending` section is not
                                                 valid ([] when it is)
    ending_file(rel, sha256, root=None, what=..) the file the section names,
                                                 refused (`EndingError.code`)
                                                 when it is missing or its
                                                 bytes are not the sha256's

Three promises, each with its reason:

  * the channel is always named. There is no default channel and no
    "first channel" (CF-0213/CF-0214, `tests/test_no_default_channel.py`):
    a reader that does not know the channel has to find it out where it is
    called, not have one picked for it here. An empty name is a refusal.
  * a former id is a name of the same channel (CF-0197): it resolves through
    `channel_ids.resolve_channel` before any path is built, so a batch frozen
    as `legacy-film` reads example-film's lists.
  * a channel without the file gets a refusal that names the file, never a
    silent fall back to somebody else's list. A science channel judged by the
    film channel's outlets is the defect this module exists to end, and an
    empty list is not a safe default either - "no outlet is listed" refuses
    every fact. The caller decides what a missing list means for its stage.

Stdlib only, and it imports no neighbour by name: `channel_ids.py` is loaded
by path from beside this file, so an agent that loads this module with
`spec_from_file_location` from a process with nothing of the checkout on
`sys.path` gets the same answer (`tests/test_module_path_loading.py`).
"""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

# name -> (file under channels/<id>/, what it is, who reads it). The names are
# the contract; the files are where the names live today. A list that is not
# here is not a channel list - add it here and to docs/channel-data.md, in one
# change, or keep it common.
LISTS = {
    "fact-sources": (
        "fact-sources.json",
        "the outlets a fact may be taken from (tiers 1/2, any_host, do_not_take) "
        "and the channel's `kinds` of fact - read by the fact rule "
        "(shared/factrule/fact_rule.py) through its caller",
        ("agents/trend-hunter", "agents/content-researcher",
         "shared/runlog/publish_profile.py")),
    "rights-holders": (
        "rights-holder-blacklist.json",
        "the rights holders the channel is careful with, in the common entry "
        "format of inserts_lib.blacklist_check; advisory only",
        ("agents/analyst", "agents/compliance-checker", "agents/video-editor",
         "shared/inserts")),
    "footage-origin": (
        "footage-origin.json",
        "the official YouTube channels a piece of footage may come from "
        "(studios, distributors) - read by the Trend Hunter's scoring and the "
        "Analyst's footage-to-get list (agents/analyst/footage_wanted.py)",
        ("agents/trend-hunter", "agents/analyst")),
    "affiliate": (
        "affiliate.json",
        "the affiliate programmes the user registered and the product links the "
        "user wrote (CF-0593) - read through the channel's `affiliate` switch by "
        "shared/affiliate.py for the publication card's description; the machine "
        "never adds a programme or a link",
        ("agents/publisher", "inserts/validate_inserts.py")),
}

FACT_KINDS_KEY = "kinds"
RSS_HOUSE_CEIL_PATH = ("sources", "rss", "house_ceil")

CHANNELS_SUBDIR = "channels"


class ChannelDataError(Exception):
    """A channel list that cannot be had: no channel named, an unknown list,
    an unknown channel, a missing or unreadable file."""


def _channel_ids():
    spec = importlib.util.spec_from_file_location("_channel_ids_for_channel_data",
                                                  HERE / "channel_ids.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_IDS = _channel_ids()


def find_root(start=None):
    """The factory checkout - `channel_ids.find_root`, the same answer."""
    return _IDS.find_root(start)


def _root(root):
    return Path(root) if root else find_root()


def channel_id(channel, root=None):
    """The current id of `channel` (a former id resolves), or a refusal when
    no channel is named or this checkout has no such channel."""
    if not isinstance(channel, str) or not channel.strip():
        raise ChannelDataError(
            "no channel named - a channel's list is read for a channel, and there "
            "is no default one (CF-0213/CF-0561); pass the batch's or the "
            "config's channel id")
    root = _root(root)
    current = _IDS.resolve_channel(channel.strip(), root)
    base = root / CHANNELS_SUBDIR
    if not (base / f"{current}.json").is_file() and not (base / current).is_dir():
        raise ChannelDataError(
            f"unknown channel {channel!r}: neither {CHANNELS_SUBDIR}/{current}.json "
            f"nor {CHANNELS_SUBDIR}/{current}/ under {root}")
    return current


def channel_dir(channel, root=None):
    """`channels/<id>/` of the channel (it is not created)."""
    root = _root(root)
    return root / CHANNELS_SUBDIR / channel_id(channel, root)


def _entry(name):
    if name not in LISTS:
        raise ChannelDataError(
            f"{name!r} is not a channel list; the channel lists are "
            f"{sorted(LISTS)} (shared/channel_data.py LISTS, docs/channel-data.md)")
    return LISTS[name]


def channel_list_path(channel, name, root=None):
    """Where `name` of `channel` lives. The file may not exist - the writer
    (the Analyst for rights-holders) creates it there; a reader calls
    `channel_list`, which refuses."""
    return channel_dir(channel, root) / _entry(name)[0]


def channel_list(channel, name, root=None):
    """The parsed list `name` of `channel`. Refuses - never falls back to
    another channel's or a "common" list - when the file is missing or does
    not parse."""
    path = channel_list_path(channel, name, root)
    if not path.is_file():
        raise ChannelDataError(
            f"channel {path.parent.name!r} has no {name} list: "
            f"{CHANNELS_SUBDIR}/{path.parent.name}/{path.name} is missing. "
            f"It is the channel's own data (docs/channel-data.md); there is no "
            f"common list to fall back to")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChannelDataError(f"{path} does not parse: {exc}") from exc


def channels_with(name, root=None):
    """The channel ids under `channels/` that carry the list `name`, sorted."""
    filename = _entry(name)[0]
    base = _root(root) / CHANNELS_SUBDIR
    if not base.is_dir():
        return []
    return sorted(p.parent.name for p in base.glob(f"*/{filename}") if p.is_file())


# ---------------------------------------------------------------- the lists
def fact_sources(channel, root=None):
    """The channel's fact outlets, in the shape `fact_rule.source_of` and
    `fact_rule.check_candidate(s)` take as `sources`."""
    return channel_list(channel, "fact-sources", root)


def fact_kinds(channel, root=None):
    """The channel's kinds of fact - `kinds` of its fact-sources list. The
    fact rule keeps one rule for them: anything outside the list reads as
    `other`, so `other` is always one of them."""
    cfg = fact_sources(channel, root)
    kinds = cfg.get(FACT_KINDS_KEY) if isinstance(cfg, dict) else None
    if not isinstance(kinds, list) or not kinds or not all(
            isinstance(k, str) and k for k in kinds):
        raise ChannelDataError(
            f"the fact-sources list of {channel_id(channel, root)!r} has no "
            f"`{FACT_KINDS_KEY}` list of strings")
    return tuple(kinds)


def rights_holders(channel, root=None):
    """The channel's rights-holder entries document (`entries[]` in the common
    format)."""
    return channel_list(channel, "rights-holders", root)


def footage_origin(channel, root=None):
    """The channel's official footage channels."""
    return channel_list(channel, "footage-origin", root)


def rss_house_ceil(channel, root=None):
    """How many distinct publishing houses saturate the RSS signal of the
    trend score for this channel (`sources.rss.house_ceil` in
    `channels/<id>.json`, next to the feeds whose `house` it counts)."""
    root = _root(root)
    current = channel_id(channel, root)
    path = root / CHANNELS_SUBDIR / f"{current}.json"
    try:
        node = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChannelDataError(f"{path} cannot be read: {exc}") from exc
    for key in RSS_HOUSE_CEIL_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    if isinstance(node, bool) or not isinstance(node, int) or node < 1:
        raise ChannelDataError(
            f"{CHANNELS_SUBDIR}/{current}.json has no `{'.'.join(RSS_HOUSE_CEIL_PATH)}` "
            f"(a positive integer) - the house ceiling is the channel's, there is "
            f"no factory default")
    return node


# ---------------------------------------------------------------- the theme
# CF-0572 (grill «Каналы ИИ и Наука» 2026-10-05/06; the user, 06.10: «плашка,
# которая выезжает про "факт в описании", тоже стилизуется под канал»). The
# video's own graphics - captions, watermark, the source badge and its fact
# strip, the quote and proof cards, the card layer, the end card - are drawn
# in the *channel's* palette, as the ROADMAP 2.3 «Brand» table says. The
# palette is data of `channels/<id>.json` → `theme`; the shapes, the motion
# and the sizes stay the Video Editor's. docs/channel-data.md («The theme»)
# is the description of every key.
THEME_KEY = "theme"
#: plain colours, `#RRGGBB`
THEME_COLORS = ("bg", "accent", "accent2", "text", "muted")
#: gradient stops, `#RRGGBB` each, centre first: name -> how many
THEME_GROUNDS = {"card_ground": 3, "end_card_ground": 3}
#: the source badge and its fact strip («факт / адрес в описании»)
THEME_BADGE_KEY = "badge"
THEME_BADGE = ("paper", "ink", "ink_muted", "rule", "accent", "accent_ink")
#: CSS font-family stacks, as Remotion takes them; the last entry is a
#: generic family so a missing face never leaves a glyph without one
THEME_FONT_KEY = "font"
THEME_FONTS = ("display", "text", "card", "badge")
THEME_GENERIC_FAMILIES = ("sans-serif", "serif", "monospace")
#: optional: the keys whose values were picked to fit the brand table rather
#: than taken from it - they wait for the user's look («подобрано, ждёт
#: взгляда пользователя»); and a free-text note
THEME_PICKED_KEY = "picked"
THEME_NOTE_KEY = "note"
#: optional: the extra palettes of the Video Editor's procedural background
#: (render/src/components/ProceduralBg.jsx `palettesFor`), in its own shape -
#: `{bg, a, b, c}`, `#RRGGBB` each: `bg` the ground, `a`/`b`/`c` the three
#: blob colours (`a` also the light sweep). Palette 0 is always built from
#: the theme itself (`bg`, `accent`, `accent2`, `accent`); these come after
#: it, in order. A channel without the key gets palette 0 only.
THEME_PROCEDURAL_KEY = "procedural_palettes"
THEME_PROCEDURAL_PALETTE = ("bg", "a", "b", "c")
#: optional (CF-0699): the captions' own colours, `#RRGGBB` each - the base
#: words, the spoken word, and a pill drawn behind the spoken word. Without
#: them the captions draw `text` and `accent` with no pill, as before; only
#: the Video Editor's caption row reads them, never the graphics.
THEME_CAPTION_COLORS = ("caption_text", "caption_active", "caption_active_box")
THEME_KEYS = (THEME_COLORS + tuple(THEME_GROUNDS)
              + (THEME_BADGE_KEY, THEME_FONT_KEY, THEME_PROCEDURAL_KEY)
              + THEME_CAPTION_COLORS
              + (THEME_PICKED_KEY, THEME_NOTE_KEY))
#: (foreground, background, minimum WCAG 2 contrast, why). Paths are
#: `key` or `badge.key`. 4.5 is WCAG AA for body text, 3 for large text and
#: for what is read as a secondary line. The badge's anchor digit is large
#: type (its numeral is set far above 24px), so its pair is held at 3 -
#: ExampleFilm's red anchor with cream ink is 4.30 and stays as it is.
THEME_CONTRAST = (
    ("text", "bg", 4.5, "the text colour on the ground"),
    ("muted", "bg", 3.0, "the secondary line (attribution, date) on the ground"),
    ("accent", "bg", 3.0, "the accent is drawn as type (the card's quote mark)"),
    ("badge.ink", "badge.paper", 4.5, "the badge's name and the fact strip"),
    ("badge.ink_muted", "badge.paper", 3.0, "the badge's SOURCE label"),
    ("badge.accent_ink", "badge.accent", 3.0, "the badge's anchor digit (large type)"),
)
#: CF-0699: the caption colours, when a channel sets them. A caption is body
#: text, so 4.5: the base words on the ground; the spoken word on its pill
#: when there is one (the pill carries the word's contrast, it has no
#: stroke), else on the ground. With a pill and no `caption_active` the
#: spoken word is `accent`, and that is what must read on the pill.
THEME_CAPTION_FLOOR = 4.5
_HEX6 = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _relative_luminance(hex6):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex6[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast_ratio(fg, bg):
    """WCAG 2 contrast ratio of two `#RRGGBB` colours (1.0 ... 21.0)."""
    hi, lo = sorted((_relative_luminance(fg), _relative_luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _font_stack_error(stack):
    if not isinstance(stack, str) or not stack.strip():
        return "is not a CSS font-family stack (a non-empty string)"
    parts = [p.strip() for p in stack.split(",")]
    if not all(parts):
        return f"{stack!r} has an empty entry"
    if parts[-1] not in THEME_GENERIC_FAMILIES:
        return (f"{stack!r} does not end in a generic family "
                f"({', '.join(THEME_GENERIC_FAMILIES)})")
    return None


def theme_errors(theme):
    """Why `theme` is not a valid channel theme block ([] when it is): every
    key present and of its shape, no unknown key (a misspelt key would render
    as nobody's choice), colours `#RRGGBB`, the contrast pairs of
    THEME_CONTRAST held."""
    if not isinstance(theme, dict):
        return [f"`{THEME_KEY}` is not an object"]
    errs = []
    unknown = sorted(set(theme) - set(THEME_KEYS))
    if unknown:
        errs.append(f"unknown `{THEME_KEY}` key(s) {unknown} (known: {', '.join(THEME_KEYS)})")
    colours = {}

    def colour(path, value):
        if not isinstance(value, str) or not _HEX6.match(value):
            errs.append(f"`{THEME_KEY}.{path}` is {value!r}, not a colour #RRGGBB")
            return
        colours[path] = value

    for key in THEME_COLORS:
        if key not in theme:
            errs.append(f"no `{THEME_KEY}.{key}`")
        else:
            colour(key, theme[key])
    for key, n in THEME_GROUNDS.items():
        stops = theme.get(key)
        if not isinstance(stops, list) or len(stops) != n:
            errs.append(f"`{THEME_KEY}.{key}` is not a list of {n} colours #RRGGBB")
            continue
        for i, value in enumerate(stops):
            colour(f"{key}[{i}]", value)
    badge = theme.get(THEME_BADGE_KEY)
    if not isinstance(badge, dict):
        errs.append(f"no `{THEME_KEY}.{THEME_BADGE_KEY}` object ({', '.join(THEME_BADGE)})")
    else:
        extra = sorted(set(badge) - set(THEME_BADGE))
        if extra:
            errs.append(f"unknown `{THEME_KEY}.{THEME_BADGE_KEY}` key(s) {extra}")
        for key in THEME_BADGE:
            if key not in badge:
                errs.append(f"no `{THEME_KEY}.{THEME_BADGE_KEY}.{key}`")
            else:
                colour(f"{THEME_BADGE_KEY}.{key}", badge[key])
    fonts = theme.get(THEME_FONT_KEY)
    if not isinstance(fonts, dict):
        errs.append(f"no `{THEME_KEY}.{THEME_FONT_KEY}` object ({', '.join(THEME_FONTS)})")
    else:
        extra = sorted(set(fonts) - set(THEME_FONTS))
        if extra:
            errs.append(f"unknown `{THEME_KEY}.{THEME_FONT_KEY}` key(s) {extra}")
        for key in THEME_FONTS:
            if key not in fonts:
                errs.append(f"no `{THEME_KEY}.{THEME_FONT_KEY}.{key}`")
                continue
            why = _font_stack_error(fonts[key])
            if why:
                errs.append(f"`{THEME_KEY}.{THEME_FONT_KEY}.{key}` {why}")
    for key in THEME_CAPTION_COLORS:
        if key in theme:
            colour(key, theme[key])
    if THEME_PROCEDURAL_KEY in theme:
        palettes = theme[THEME_PROCEDURAL_KEY]
        shape = "{" + ", ".join(THEME_PROCEDURAL_PALETTE) + "}"
        if not isinstance(palettes, list) or not palettes:
            errs.append(f"`{THEME_KEY}.{THEME_PROCEDURAL_KEY}` is not a non-empty list of "
                        f"palettes {shape} (leave the key out for palette 0 only)")
        else:
            for i, pal in enumerate(palettes):
                path = f"{THEME_PROCEDURAL_KEY}[{i}]"
                if not isinstance(pal, dict):
                    errs.append(f"`{THEME_KEY}.{path}` is not a palette {shape}")
                    continue
                extra = sorted(set(pal) - set(THEME_PROCEDURAL_PALETTE))
                if extra:
                    errs.append(f"unknown `{THEME_KEY}.{path}` key(s) {extra}")
                for key in THEME_PROCEDURAL_PALETTE:
                    if key not in pal:
                        errs.append(f"no `{THEME_KEY}.{path}.{key}`")
                    else:
                        colour(f"{path}.{key}", pal[key])
    picked = theme.get(THEME_PICKED_KEY, [])
    if not isinstance(picked, list) or not all(isinstance(k, str) for k in picked):
        errs.append(f"`{THEME_KEY}.{THEME_PICKED_KEY}` is not a list of theme keys")
    else:
        bad = sorted(set(picked) - (set(THEME_KEYS) - {THEME_PICKED_KEY, THEME_NOTE_KEY}))
        if bad:
            errs.append(f"`{THEME_KEY}.{THEME_PICKED_KEY}` names {bad}, which are not theme keys")
    if THEME_NOTE_KEY in theme and not isinstance(theme[THEME_NOTE_KEY], str):
        errs.append(f"`{THEME_KEY}.{THEME_NOTE_KEY}` is not a string")
    for fg, bg, floor, why in THEME_CONTRAST:
        if fg in colours and bg in colours:
            ratio = contrast_ratio(colours[fg], colours[bg])
            if ratio < floor:
                errs.append(f"`{THEME_KEY}.{fg}` {colours[fg]} on `{THEME_KEY}.{bg}` "
                            f"{colours[bg]} has contrast {ratio:.2f}, below {floor} "
                            f"({why})")
    if "bg" in colours:
        pairs = []
        if "caption_text" in colours:
            pairs.append(("caption_text", colours["caption_text"], "bg", colours["bg"],
                          "the caption's base words on the ground"))
        if "caption_active_box" in theme:
            fg = "caption_active" if "caption_active" in theme else "accent"
            if fg in colours and "caption_active_box" in colours:
                pairs.append((fg, colours[fg], "caption_active_box",
                              colours["caption_active_box"],
                              "the spoken caption word on its pill"))
        elif "caption_active" in colours:
            pairs.append(("caption_active", colours["caption_active"], "bg", colours["bg"],
                          "the spoken caption word on the ground"))
        for fg, fgc, bg, bgc, why in pairs:
            ratio = contrast_ratio(fgc, bgc)
            if ratio < THEME_CAPTION_FLOOR:
                errs.append(f"`{THEME_KEY}.{fg}` {fgc} on `{THEME_KEY}.{bg}` {bgc} has "
                            f"contrast {ratio:.2f}, below {THEME_CAPTION_FLOOR} ({why})")
    return errs


def theme(channel, root=None):
    """The channel's on-screen theme (`theme` of `channels/<id>.json`), checked
    by `theme_errors`. A channel without one, or with a broken one, is a
    refusal - never ExampleFilm's palette passed off as the channel's."""
    root = _root(root)
    current = channel_id(channel, root)
    path = root / CHANNELS_SUBDIR / f"{current}.json"
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChannelDataError(f"{path} cannot be read: {exc}") from exc
    block = cfg.get(THEME_KEY) if isinstance(cfg, dict) else None
    if block is None:
        raise ChannelDataError(
            f"{CHANNELS_SUBDIR}/{current}.json has no `{THEME_KEY}` - the on-screen "
            f"palette is the channel's (CF-0572, docs/channel-data.md), there is no "
            f"factory theme to fall back to")
    errs = theme_errors(block)
    if errs:
        raise ChannelDataError(f"{CHANNELS_SUBDIR}/{current}.json: " + "; ".join(errs))
    return block


# ------------------------------------------------- the outlets' AI-bot policy
# CF-0557 (grill CF-0546 Q9 of 05.10, grill 07.10 Q8; the factory's rule: an
# outlet whose robots.txt forbids Anthropic's bots - anthropic-ai, ClaudeBot,
# Claude-Web, Claude-User, Claude-SearchBot - or every agent is not scraped;
# narrowed to those by the user's decision of 08.10, CF-0635). The feeds of an
# outlet that is closed, or whose terms forbid grounding AI (PMC), serve topic
# selection only - `headline_only` (CF-0635). Every outlet of a channel's
# fact-sources tiers and every feed of its `sources.rss.feeds` says two
# things: how the factory *uses* it (`use`) and what its robots.txt says to
# AI bots (`ai_policy`, written by `shared/source_policy.py check <channel>
# --write`, the agent set is `source_policy.AI_AGENTS`). The rule that ties
# them is here, so the reader and the root validator
# (`inserts/validate_inserts.py`) answer the same.
SOURCE_USE_KEY = "use"
AI_POLICY_KEY = "ai_policy"
#: how the factory touches an outlet. Only `read_text` lets the outlet's own
#: words reach the writer as support text.
SOURCE_USES = {
    "read_text": "its text is read and may reach the writer as support text - "
                 "an outlet of the tiers: the article is downloaded (Wikipedia: "
                 "the support text and the fact candidates); a feed: the excerpt "
                 "it publishes goes into the topic's support text (`rss_summary`), "
                 "article bodies are never requested. Needs verdict `allowed`",
    "headline_only": "a feed read for topic selection only - headline, link and "
                     "date (fetch_rss_news.py, the CF-0045 stance; the house count, "
                     "the headline as a signal); its excerpt never goes into the "
                     "topic's support text, so no writer is grounded on it (the "
                     "user's decision of 08.10, CF-0635: PMC's terms forbid "
                     "grounding AI). Allowed for a `forbidden` outlet (grill "
                     "CF-0546 Q9) as long as robots.txt leaves the feed open to "
                     "every agent (`*`)",
    "cite_only": "never downloaded: the outlet is a name a fact may stand on - "
                 "Wikipedia's citation (`primary_url`) or an RSS post that is "
                 "itself on its host",
}
#: the uses that let an outlet's text reach the writer
TEXT_USES = ("read_text",)
#: the uses a feed may have (a feed is read, so `cite_only` is not one).
#: `rss_annotation_only` (CF-0557: the excerpt of a forbidden outlet's feed went
#: to the writer) is gone - CF-0635 split it into `headline_only` (nothing to
#: the writer) and `read_text` (an `allowed` outlet's excerpt to the writer).
FEED_USES = ("headline_only", "read_text")
#: the uses an outlet of the fact-sources tiers may have (a tier outlet is no
#: feed, so `headline_only` is not one)
TIER_USES = ("read_text", "cite_only")
AI_VERDICTS = ("allowed", "forbidden", "unknown")
#: CF-0810: were the outlet's terms of use read? robots.txt is not the whole
#: answer - terms that ban AI use, model training, grounding or scraping close
#: an outlet too (TMDB, character.ai, ExampleStream) - so a tier-1 row records it
#: in `ai_policy.terms_read`:
#:   true          read: `terms_note` says what they say about AI and scraping
#:                 (`terms_url` where they are, null when the site links none);
#:   false         not read, or no reading on record (a bot challenge, a 403,
#:                 never tried) - the row is named only: its verdict is never
#:                 `allowed`, and a re-check
#:                 (`source_policy.py check --write`) that reads robots.txt
#:                 open keeps it `unknown` and says why (`held`);
#:   "unrecorded"  a row made `allowed` by its robots.txt before CF-0810 (the
#:                 record of 08.10-18.10 kept no terms reading): it keeps its
#:                 robots verdict until a person reads the terms and writes
#:                 true or false.
#: The shared rule refuses only what is written (an `allowed` row marked
#: false, a value outside these); that every tier-1 row of a real channel
#: says it is the root validator's (`terms_marker_errors`).
TERMS_READ_KEY = "terms_read"
TERMS_UNRECORDED = "unrecorded"
TERMS_READ_VALUES = (True, False, TERMS_UNRECORDED)
#: CF-0816: an `allowed` tier-1 row still "unrecorded" is one whose terms a
#: person tried and could not read (a 403, a page drawn by script): its
#: `terms_note` starts with this and says why - the row keeps its robots
#: verdict until the user decides, and no row is left without a word on it.
TERMS_NOT_READ_PREFIX = "not read"
#: CF-0816: terms that ban AI use, robots, scraping or automated collection
#: close the outlet whatever robots.txt says (the rule of 08.10, the TMDB
#: precedent): the row writes `terms_verdict: "forbidden"` (with
#: `terms_read` true and the clause in `terms_note`), its verdict is
#: `forbidden`, and a re-check (`source_policy.py check --write`) keeps it so.
TERMS_VERDICT_KEY = "terms_verdict"
TERMS_VERDICTS = ("forbidden",)
#: the tier whose rows must record `terms_read` (the vendor pages the Trend
#: Hunter's `vendor_page` reads are tier 1)
TERMS_MARKER_TIER = "1"
FEEDS_PATH = ("sources", "rss", "feeds")
_ISO_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _channel_config(channel, root=None):
    root = _root(root)
    current = channel_id(channel, root)
    path = root / CHANNELS_SUBDIR / f"{current}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChannelDataError(f"{path} cannot be read: {exc}") from exc


def feeds(channel, root=None):
    """The channel's RSS feeds - `sources.rss.feeds` of channels/<id>.json, as
    written (`url`, `site`, `house`, `use`, `ai_policy`). A channel without
    feeds gets [] (a stub collects nothing yet); a `feeds` that is not a list
    is a refusal."""
    node = _channel_config(channel, root)
    for key in FEEDS_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    if node is None:
        return []
    if not isinstance(node, list):
        raise ChannelDataError(f"`{'.'.join(FEEDS_PATH)}` of {channel!r} is not a list")
    return node


def support_feed_urls(channel, root=None):
    """The feed URLs whose excerpt may go into a topic's support text (the
    `rss_summary` pieces Trend Hunter hands the writer): the feeds whose `use`
    is a text use. A `headline_only` feed is not here - its entries choose
    topics and nothing of them reaches the writer (CF-0635). Refuses a channel
    that breaks the rule, as `feed_urls` does."""
    errs = source_policy_errors(channel, root)
    if errs:
        raise ChannelDataError("; ".join(errs))
    return [f["url"] for f in feeds(channel, root) if f.get(SOURCE_USE_KEY) in TEXT_USES]


def feed_urls(channel, root=None):
    """The feed URLs the collector reads for the channel: every feed whose
    `use` is a feed use and whose policy passes `source_policy_errors`. A
    channel whose feeds break the rule is a refusal, not a shorter list - a
    feed dropped silently is a signal lost without anybody deciding it."""
    errs = source_policy_errors(channel, root)
    if errs:
        raise ChannelDataError("; ".join(errs))
    return [f["url"] for f in feeds(channel, root)]


def ai_policy_errors(policy, ctx):
    """The shape of one `ai_policy` block."""
    if not isinstance(policy, dict):
        return [f"{ctx}: no `{AI_POLICY_KEY}` - run `python3 shared/source_policy.py "
                f"check <channel> --write` (CF-0557)"]
    errs = []
    if policy.get("verdict") not in AI_VERDICTS:
        errs.append(f"{ctx}: `{AI_POLICY_KEY}.verdict` is {policy.get('verdict')!r}, "
                    f"not one of {', '.join(AI_VERDICTS)}")
    if not isinstance(policy.get("checked_on"), str) or not _ISO_DAY.match(policy["checked_on"]):
        errs.append(f"{ctx}: `{AI_POLICY_KEY}.checked_on` is not a date YYYY-MM-DD")
    checks = policy.get("checks")
    if not isinstance(checks, list) or not checks:
        errs.append(f"{ctx}: `{AI_POLICY_KEY}.checks` is not a non-empty list of the "
                    f"robots.txt reads the verdict stands on")
    else:
        for i, c in enumerate(checks):
            if not isinstance(c, dict) or not isinstance(c.get("robots_url"), str):
                errs.append(f"{ctx}: `{AI_POLICY_KEY}.checks[{i}]` has no `robots_url`")
    if "terms_url" in policy and policy["terms_url"] is not None and \
            not isinstance(policy["terms_url"], str):
        errs.append(f"{ctx}: `{AI_POLICY_KEY}.terms_url` is not a URL or null")
    if TERMS_READ_KEY in policy:
        marker = policy[TERMS_READ_KEY]
        if not any(marker is v if isinstance(v, bool) else marker == v
                   for v in TERMS_READ_VALUES):
            errs.append(f"{ctx}: `{AI_POLICY_KEY}.{TERMS_READ_KEY}` is {marker!r}, not "
                        f"true, false or {TERMS_UNRECORDED!r} (CF-0810)")
        elif marker is True and not (isinstance(policy.get("terms_note"), str)
                                     and policy["terms_note"].strip()):
            errs.append(f"{ctx}: `{AI_POLICY_KEY}.{TERMS_READ_KEY}` true but no "
                        f"`terms_note` - what the terms say about AI and scraping (CF-0810)")
    if TERMS_VERDICT_KEY in policy:
        tv = policy[TERMS_VERDICT_KEY]
        if tv not in TERMS_VERDICTS:
            errs.append(f"{ctx}: `{AI_POLICY_KEY}.{TERMS_VERDICT_KEY}` is {tv!r}, not "
                        f"one of {', '.join(TERMS_VERDICTS)} (CF-0816)")
        elif policy.get(TERMS_READ_KEY) is not True:
            errs.append(f"{ctx}: `{AI_POLICY_KEY}.{TERMS_VERDICT_KEY}` {tv} but "
                        f"`{TERMS_READ_KEY}` is not true - a ban in the terms is one "
                        f"read, quoted in `terms_note` (CF-0816)")
        elif policy.get("verdict") != tv:
            errs.append(f"{ctx}: the terms forbid it (`{AI_POLICY_KEY}.{TERMS_VERDICT_KEY}` "
                        f"{tv}) but the verdict is {policy.get('verdict')!r} - terms that "
                        f"ban AI use, robots or scraping close the outlet whatever "
                        f"robots.txt says (the rule of 08.10, CF-0816)")
    return errs


def _star_closed(policy):
    """Did a robots.txt read close the path to every agent (`*`)?"""
    return any(isinstance(c, dict) and c.get("any_agent") is False
               for c in (policy or {}).get("checks") or [])


def entry_policy_errors(entry, ctx, uses):
    """One outlet or feed against the rule: its `use` is one of `uses`, its
    `ai_policy` is well formed, an outlet whose text is read is `allowed`
    (`forbidden` and `unknown` alike - unknown is not permission), and a feed
    is not read where robots.txt closes it to every agent."""
    if not isinstance(entry, dict):
        return [f"{ctx}: not an object"]
    use = entry.get(SOURCE_USE_KEY)
    if use not in uses:
        return [f"{ctx}: `{SOURCE_USE_KEY}` is {use!r}, not one of {', '.join(uses)} "
                f"(docs/channel-data.md «Sources and the AI-bot rule»)"]
    policy = entry.get(AI_POLICY_KEY)
    errs = ai_policy_errors(policy, ctx)
    if errs:
        return errs
    verdict = policy["verdict"]
    if use in TEXT_USES and verdict != "allowed":
        errs.append(f"{ctx}: `{SOURCE_USE_KEY}` {use} but its robots.txt verdict for AI "
                    f"bots is {verdict} - an outlet whose text is read must be "
                    f"`allowed`; a forbidden one stands only as headline_only "
                    f"or cite_only (the factory's rule, CF-0557/CF-0635)")
    if verdict == "allowed" and policy.get(TERMS_READ_KEY) is False:
        errs.append(f"{ctx}: verdict allowed but `{AI_POLICY_KEY}.{TERMS_READ_KEY}` is false - "
                    f"an outlet whose terms were not read is named only, never read: "
                    f"its verdict stays unknown until a person reads the terms "
                    f"(`terms_url`, `terms_note`) and writes {TERMS_READ_KEY} true (CF-0810)")
    if use != "cite_only" and _star_closed(policy):
        errs.append(f"{ctx}: robots.txt closes it to every agent (`*`) - it is not read "
                    f"at all, whatever the use (the CF-0045 stance)")
    return errs


def policy_errors_of(name, sources, feed_list):
    """The rule over data in hand: `sources` a fact-sources document (or None
    when the channel has none), `feed_list` its `sources.rss.feeds` (or
    None). `name` only labels the messages. The one rule
    `source_policy_errors` and the root validator share."""
    errs = []
    for tier, rows in sorted(((sources or {}).get("tiers") or {}).items()):
        for i, row in enumerate(rows or []):
            rid = row.get("id") if isinstance(row, dict) else None
            errs += entry_policy_errors(
                row, f"{name} fact-sources tiers.{tier}[{rid or i}]", TIER_USES)
    for i, feed in enumerate(feed_list or []):
        site = feed.get("site") if isinstance(feed, dict) else None
        errs += entry_policy_errors(feed, f"{name} sources.rss.feeds[{site or i}]", FEED_USES)
    return errs


def terms_marker_errors(name, sources):
    """CF-0810: every tier-1 row of a channel's fact-sources list says whether
    its terms were read (`ai_policy.terms_read`, `TERMS_READ_VALUES`), so a
    row added without one cannot be taken for read. The root validator's
    over the real channels; the shared rule (`policy_errors_of`) judges only
    what a row writes, so a stand-in list without the marker still reads.
    CF-0816: an `allowed` row still "unrecorded" says in `terms_note` that
    its terms could not be read and why (`TERMS_NOT_READ_PREFIX`, after an
    optional "CF-xxxx, date: " lead)."""
    errs = []
    for i, row in enumerate(((sources or {}).get("tiers") or {}).get(TERMS_MARKER_TIER) or []):
        if not isinstance(row, dict):
            continue
        policy = row.get(AI_POLICY_KEY)
        if isinstance(policy, dict) and TERMS_READ_KEY not in policy:
            errs.append(f"{name} fact-sources tiers.{TERMS_MARKER_TIER}[{row.get('id') or i}]: "
                        f"no `{AI_POLICY_KEY}.{TERMS_READ_KEY}` - say whether the terms "
                        f"were read: true (with `terms_note`), false (named only, "
                        f"never `allowed`) or {TERMS_UNRECORDED!r} (CF-0810)")
        elif isinstance(policy, dict) and policy.get(TERMS_READ_KEY) == TERMS_UNRECORDED \
                and policy.get("verdict") == "allowed" \
                and not str(policy.get("terms_note") or "").split(": ", 1)[-1] \
                .startswith(TERMS_NOT_READ_PREFIX):
            errs.append(f"{name} fact-sources tiers.{TERMS_MARKER_TIER}[{row.get('id') or i}]: "
                        f"`allowed` with `{AI_POLICY_KEY}.{TERMS_READ_KEY}` "
                        f"{TERMS_UNRECORDED!r} and no word on the terms - read them and "
                        f"write true (with `terms_note`, or `{TERMS_VERDICT_KEY}` "
                        f"forbidden on a ban), or say in `terms_note` "
                        f"\"{TERMS_NOT_READ_PREFIX} - <why>\" (CF-0816)")
    return errs


def feeds_of(config):
    """`sources.rss.feeds` of a parsed channel config, None when absent."""
    node = config
    for key in FEEDS_PATH:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def source_policy_errors(channel, root=None):
    """Why the channel's outlets and feeds break the AI-bot rule ([] when they
    do not). A channel without a fact-sources list or without feeds has
    nothing of that kind to break."""
    root = _root(root)
    current = channel_id(channel, root)
    sources = fact_sources(current, root) if current in channels_with("fact-sources", root) else None
    return policy_errors_of(current, sources, feeds(current, root))


# ------------------------------------------------- the outlets' terms for AI output
# CF-0671: an outlet whose terms allow its material in an AI product may still
# bind what that product says - NASA's «References like „according to NASA“ or
# similar are prohibited in AI products». The phrases are the outlet's terms,
# so they are channel data: `ai_output_terms` on the outlet's entry of the
# channel's fact-sources list (`forbidden[]`: `id`, `phrase`, `pattern`, `why`;
# `allowed[]`: what the terms leave free, for the reader). The rule that reads
# them is here, one for every gate: the publication card (title, description)
# and the Content Researcher's script gate (narration, plates).
AI_OUTPUT_TERMS_KEY = "ai_output_terms"
_APOSTROPHES = re.compile(r"[\u2018\u2019\u02bc\u2032`]")
_DASHES = re.compile(r"[\u2010\u2011\u2012\u2013\u2014\u2212]")
_URLS = re.compile(r"https?://\S+", re.I)


def attribution_terms_errors(sources):
    """Why the `ai_output_terms` of a parsed fact-sources list cannot be
    matched ([] when they can): a `forbidden` entry needs `id`, `phrase`, a
    `pattern` that compiles, and a `why`; the block needs its `terms_url`."""
    errs = []
    for tier, rows in sorted(((sources or {}).get("tiers") or {}).items()):
        for row in rows or []:
            if not isinstance(row, dict) or AI_OUTPUT_TERMS_KEY not in row:
                continue
            ctx = f"tiers.{tier}[{row.get('id')}].{AI_OUTPUT_TERMS_KEY}"
            terms = row[AI_OUTPUT_TERMS_KEY]
            if not isinstance(terms, dict):
                errs.append(f"{ctx} is not an object")
                continue
            if not str(terms.get("terms_url") or "").startswith("https://"):
                errs.append(f"{ctx}: no `terms_url` - the terms the phrases come from")
            forbidden = terms.get("forbidden")
            if not isinstance(forbidden, list) or not forbidden:
                errs.append(f"{ctx}: `forbidden` must be a non-empty list")
                continue
            ids = set()
            for i, f in enumerate(forbidden):
                where = f"{ctx}.forbidden[{i}]"
                if not isinstance(f, dict):
                    errs.append(f"{where} is not an object")
                    continue
                for key in ("id", "phrase", "pattern", "why"):
                    if not isinstance(f.get(key), str) or not f[key].strip():
                        errs.append(f"{where}: no `{key}`")
                if f.get("id") in ids:
                    errs.append(f"{where}: `id` {f.get('id')!r} twice")
                ids.add(f.get("id"))
                try:
                    re.compile(str(f.get("pattern") or ""))
                except re.error as exc:
                    errs.append(f"{where}: `pattern` does not compile ({exc})")
    return errs


def attribution_terms(channel, root=None):
    """The channel's outlets' bans on phrasing its AI output, one row per
    outlet that has them: `{outlet, terms_url, forbidden: [{id, phrase,
    pattern, why}]}`. A channel without a fact-sources list has none ([]),
    as for `source_policy_errors`; a block that cannot be matched is a
    refusal, not a shorter list - a ban dropped silently lets the phrase
    through."""
    root = _root(root)
    current = channel_id(channel, root)
    if current not in channels_with("fact-sources", root):
        return []
    sources = fact_sources(current, root)
    errs = attribution_terms_errors(sources)
    if errs:
        raise ChannelDataError(f"the fact-sources list of {current!r}: " + "; ".join(errs))
    out = []
    for _tier, rows in sorted((sources.get("tiers") or {}).items()):
        for row in rows or []:
            terms = row.get(AI_OUTPUT_TERMS_KEY) if isinstance(row, dict) else None
            if terms:
                out.append({"outlet": row.get("id"), "terms_url": terms["terms_url"],
                            "forbidden": [dict(f) for f in terms["forbidden"]]})
    return out


def attribution_text(text):
    """The text the `pattern`s are searched in: links out (a page's address
    is the outlet's words, not ours - `.../nasa-confirms-water/`), casefolded,
    curly apostrophes straight, every dash `-`, whitespace collapsed."""
    t = _URLS.sub(" ", str(text or ""))
    t = _APOSTROPHES.sub("'", t)
    t = _DASHES.sub("-", t)
    return re.sub(r"\s+", " ", t).casefold()


def attribution_hits(text, terms):
    """The forbidden phrases `text` carries under `terms` (`attribution_terms`):
    `[{outlet, id, phrase, match, terms_url}]` in the order they stand, []
    when it carries none."""
    norm = attribution_text(text)
    hits = []
    for t in terms or []:
        for f in t.get("forbidden") or []:
            for m in re.finditer(f["pattern"], norm):
                hits.append({"outlet": t.get("outlet"), "id": f["id"], "phrase": f["phrase"],
                             "match": m.group(0), "terms_url": t.get("terms_url"),
                             "at": m.start()})
    hits.sort(key=lambda h: h.pop("at"))
    return hits


# ---------------------------------------------------------------- the ending
# CF-0722 (request 12 of the command center, 13.10): the channel's ending as
# data. The clip itself has always been the channel's (`channels/<id>/
# ending.mp4`, CF-0141), but how it was made lived in flags of
# `scripts/brand_ending.py` and in prose of the channel's SOURCES.md - the
# fonts directory, the downloaded track, the second it starts from, the gain.
# `channels/<id>/brand.json` -> `ending` holds them:
#
#     {"ending": {
#        "clip": "channels/<id>/ending.mp4",       the clip the Editor closes on
#        "clip_sha256": "<64 hex>",                its bytes
#        "render": {                               null: made by hand (ExampleFilm)
#          "fonts": "shared/brand/fonts",          Poppins-ExtraBold.ttf + -Bold.ttf
#          "track": "channels/<id>/brand/ending-track.mp3",
#          "track_sha256": "<64 hex>",             the download, as SOURCES.md records it
#          "audio_start": 300.0,                   seconds into the track
#          "audio_gain_db": 0.0},                  optional, 0.0 when absent
#        "note": "..."}}
#
# Paths are relative to the factory root. A file named here is checked by its
# sha256 wherever it is used (`ending_file`): a swapped track or clip is a
# refusal that names itself (`ending_sha256_mismatch`), never a render or a
# video made out of somebody else's bytes. A channel without brand.json, or
# without the section, is not an error: the readers keep their old defaults
# (the flags of brand_ending.py, the Editor's convention and no sha check).
BRAND_FILE = "brand.json"
ENDING_KEY = "ending"
ENDING_KEYS = ("clip", "clip_sha256", "render", "note")
ENDING_REQUIRED = ("clip", "clip_sha256")
ENDING_RENDER_KEYS = ("fonts", "track", "track_sha256", "audio_start", "audio_gain_db",
                      "note")
ENDING_RENDER_REQUIRED = ("fonts", "track", "track_sha256", "audio_start")
ENDING_FONT_FILES = ("Poppins-ExtraBold.ttf", "Poppins-Bold.ttf")

#: Why an ending file or section was refused - `EndingError.code`.
ENDING_INVALID = "ending_invalid"                  # the section breaks ending_errors()
ENDING_FILE_MISSING = "ending_file_missing"        # the named file is not there
ENDING_SHA256_MISMATCH = "ending_sha256_mismatch"  # the file is not the recorded bytes

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EndingError(ChannelDataError):
    """An ending section or file that cannot be used; `code` says why
    (ENDING_INVALID / ENDING_FILE_MISSING / ENDING_SHA256_MISMATCH), `path`
    is the file when there is one."""

    def __init__(self, message, code, path=None):
        super().__init__(message)
        self.code = code
        self.path = path


def _rel_path_error(value, key):
    if not isinstance(value, str) or not value.strip():
        return f"`{key}` is not a path"
    p = Path(value)
    if p.is_absolute() or ".." in p.parts or value != value.strip():
        return (f"`{key}` {value!r} is not a path relative to the factory root "
                f"(no absolute path, no `..`): a machine's own path is not channel data")
    return None


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and value == value and abs(value) != float("inf")


def ending_errors(section):
    """Why `section` is not a valid `ending` section ([] when it is) - the one
    rule the reader and the tests share."""
    if not isinstance(section, dict):
        return ["`ending` is not an object"]
    errs = [f"`ending` has an unknown key `{k}`" for k in section
            if k not in ENDING_KEYS and not str(k).endswith("_note")]
    errs += [f"`ending` has no `{k}`" for k in ENDING_REQUIRED if k not in section]
    if "clip" in section:
        e = _rel_path_error(section["clip"], "ending.clip")
        if e:
            errs.append(e)
    if "clip_sha256" in section and not (isinstance(section["clip_sha256"], str)
                                         and _SHA256.match(section["clip_sha256"])):
        errs.append("`ending.clip_sha256` is not 64 lowercase hex digits")
    if "note" in section and not isinstance(section["note"], str):
        errs.append("`ending.note` is not a string")
    render = section.get("render")
    if render is None:
        return errs
    if not isinstance(render, dict):
        return errs + ["`ending.render` is neither an object nor null"]
    errs += [f"`ending.render` has an unknown key `{k}`" for k in render
             if k not in ENDING_RENDER_KEYS and not str(k).endswith("_note")]
    errs += [f"`ending.render` has no `{k}`" for k in ENDING_RENDER_REQUIRED
             if k not in render]
    for key in ("fonts", "track"):
        if key in render:
            e = _rel_path_error(render[key], f"ending.render.{key}")
            if e:
                errs.append(e)
    if "track_sha256" in render and not (isinstance(render["track_sha256"], str)
                                         and _SHA256.match(render["track_sha256"])):
        errs.append("`ending.render.track_sha256` is not 64 lowercase hex digits")
    if "audio_start" in render and not (_number(render["audio_start"])
                                        and render["audio_start"] >= 0):
        errs.append("`ending.render.audio_start` is not a number of seconds >= 0")
    if "audio_gain_db" in render and not _number(render["audio_gain_db"]):
        errs.append("`ending.render.audio_gain_db` is not a number of dB")
    if "note" in render and not isinstance(render["note"], str):
        errs.append("`ending.render.note` is not a string")
    return errs


def brand_path(channel, root=None):
    """`channels/<id>/brand.json` of the channel (it may not exist)."""
    return channel_dir(channel, root) / BRAND_FILE


def brand(channel, root=None):
    """The channel's brand.json, parsed, or None when it has none. A file
    that is there and does not parse is a refusal, not None."""
    path = brand_path(channel, root)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EndingError(f"{path} does not parse: {exc}", ENDING_INVALID, path) from exc
    if not isinstance(doc, dict):
        raise EndingError(f"{path} is not a JSON object", ENDING_INVALID, path)
    return doc


def ending(channel, root=None):
    """The channel's `ending` section, checked - a copy, with
    `render.audio_gain_db` filled in (0.0) and the numbers as floats - or
    None when the channel has no brand.json or no section (the readers then
    keep their old defaults). A section that breaks `ending_errors` is a
    refusal (`EndingError`, code ENDING_INVALID)."""
    doc = brand(channel, root)
    if doc is None or ENDING_KEY not in doc:
        return None
    section = doc[ENDING_KEY]
    errs = ending_errors(section)
    if errs:
        raise EndingError(f"the ending of {channel_id(channel, root)!r} "
                          f"({CHANNELS_SUBDIR}/<id>/{BRAND_FILE}): " + "; ".join(errs),
                          ENDING_INVALID, brand_path(channel, root))
    out = json.loads(json.dumps(section))
    render = out.get("render")
    if isinstance(render, dict):
        render["audio_start"] = float(render["audio_start"])
        render["audio_gain_db"] = float(render.get("audio_gain_db", 0.0))
    else:
        out["render"] = None
    return out


def file_sha256(path):
    """sha256 of the file's bytes, lowercase hex."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ending_file(rel, sha256, root=None, what="ending file"):
    """The absolute path of `rel` (relative to the root) once its bytes are
    `sha256`. Refuses with `EndingError`: ENDING_FILE_MISSING when there is no
    file, ENDING_SHA256_MISMATCH when there is a different one - a swapped
    track or clip is named, never used."""
    root = _root(root)
    path = Path(rel) if Path(rel).is_absolute() else root / rel
    if not path.is_file():
        raise EndingError(f"{ENDING_FILE_MISSING}: the {what} {rel} is not there "
                          f"({path}); the channel's brand.json names it with its sha256 "
                          f"{sha256}", ENDING_FILE_MISSING, path)
    got = file_sha256(path)
    if got != sha256:
        raise EndingError(f"{ENDING_SHA256_MISMATCH}: the {what} {rel} is not the file "
                          f"the channel recorded - sha256 {got}, brand.json says {sha256}. "
                          f"A swapped file is refused; if the change is meant, record "
                          f"the new sha256 in the channel's brand.json (and its "
                          f"SOURCES.md)", ENDING_SHA256_MISMATCH, path)
    return path
