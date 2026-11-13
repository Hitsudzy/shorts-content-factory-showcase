#!/usr/bin/env python3
"""The plan's on-screen theme, read off the channel it is drawn for (CF-0572).

Every colour and face the composition draws - the captions, the watermark,
the comparison-line badge, the quote card, the end card, the split ground,
the procedural background - used to be a literal in `render/src/` (and a
regex over `Video.jsx` in `render_quote.py`): ExampleFilm's palette, written
into code, and so the palette of every other channel too. The theme is
channel data now (`channels/<id>.json` -> `theme`, the root's
`docs/channel-data.md` «The theme»), read through the root's contract
`shared/channel_data.py` `theme(channel, root)` (`_channel_data.py` finds
it), and the planner writes it into `plan.theme` - the one place the render
takes colours and faces from (`Video.jsx` refuses a plan without one).

What goes into the plan is the block as the channel keeps it, minus the
bookkeeping keys `picked` and `note` (what was picked by hand and why - for
the people reading the config, not for the frame).

Two cases, the watermark's (`channel_watermark.py`):

* no `--channel` at all - nobody here knows whose video this is, so the plan
  carries `theme: null` and a note; the render then refuses with a line
  saying why. Never ExampleFilm's palette passed off as the channel's, and no
  "neutral" palette either: a video without its channel's look is not a
  video this factory posts.
* `--channel` given and the theme missing or broken - a refusal (ThemeError,
  a SystemExit with the contract's message), before any work.

`--channel` may also be a path to a `.json` (meme_layer.load_channel): then
the config already loaded is the source, checked by the same `theme_errors`.
"""
from _channel_data import channel_data

THEME_KEY = "theme"
#: keys of the channel's theme block that are about the config, not the frame
BOOKKEEPING = ("picked", "note")


class ThemeError(SystemExit):
    """The channel was named and has no usable theme. A SystemExit, so the
    planner stops on it with the message as its last line."""


def strip(theme):
    """The theme as the plan carries it: without `picked`/`note`."""
    return {k: v for k, v in theme.items() if k not in BOOKKEEPING}


def plan_theme(channel, channel_cfg, root):
    """(theme, note) for `plan.theme`.

    `channel` is what `--channel` said (an id or a path to a .json),
    `channel_cfg` the config it loaded to (None when it did not), `root` the
    factory root the planner works against. Returns (None, note) without a
    channel; raises ThemeError when the channel is named but has no theme."""
    if not channel:
        return None, ("theme: no --channel, so the plan carries no theme and the "
                      "render refuses it - the palette is the channel's (CF-0572)")
    if str(channel).endswith(".json"):
        return config_theme(channel_cfg, what=str(channel)), None
    try:
        block = channel_data.theme(channel, root)
    except channel_data.ChannelDataError as exc:
        raise ThemeError(f"theme: channel {channel!r}: {exc} (CF-0572)") from exc
    return strip(block), None


def config_theme(channel_cfg, what=None):
    """The checked theme of a channel config already loaded (a `.json`
    `--channel`, or the config a layer was handed - the proof layer's quote
    card), without `picked`/`note`. The block is the one `channels/<id>.json`
    carries, so this is `channel_data.theme` minus the file read. ThemeError
    when the config has none or a broken one."""
    cfg = channel_cfg if isinstance(channel_cfg, dict) else {}
    what = what or cfg.get("channel_id") or "the channel config"
    block = cfg.get(THEME_KEY)
    if block is None:
        raise ThemeError(f"theme: channel {what!r}: no `{THEME_KEY}` - the on-screen "
                         f"palette is the channel's, there is no factory theme to fall "
                         f"back to (CF-0572)")
    errs = channel_data.theme_errors(block)
    if errs:
        raise ThemeError(f"theme: channel {what!r}: " + "; ".join(errs) + " (CF-0572)")
    return strip(block)
