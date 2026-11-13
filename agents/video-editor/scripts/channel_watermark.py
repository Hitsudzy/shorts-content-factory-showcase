#!/usr/bin/env python3
"""The watermark's text, read off the channel it is drawn for (CF-0212).

`build_render_plan.py` used to carry the mark as an argparse default - "TV
SHOW MOMENTS", then "EXAMPLE_FILM" after the rename (CF-0180) - and no SKILL.md
ever told anyone to override it. A second channel would have gone out with
the first one's name in its corner, silently: channel identity written into
code, the class of CF-0213/CF-0214.

One source now: `channels/<id>.json` -> `display_name`, the name the end card
already signs with (end_card.channel_name). The plan carries it in capitals,
because capitals are what the frame shows - `render/src/components/
Watermark.jsx` draws the mark with `textTransform: 'uppercase'` - and because
`plan.watermark.text` also seeds the procedural background (Video.jsx), so
the plan has to say the same string it said before the move for example-film's
frames to stay the frames they were: `ExampleFilm` -> `EXAMPLE_FILM`.

Two cases, and only one of them is soft:

* no `--channel` at all - nothing here knows whose video this is, so the
  plan gets no mark (`None`, which Watermark.jsx draws as nothing) and a note
  saying why. Never somebody else's name.
* `--channel` given and its config missing, unreadable or without a
  `display_name` - a refusal with the line below, not a default. A channel
  that runs the factory must be able to say its own name.
"""

WATERMARK_KEY = "display_name"


class WatermarkError(SystemExit):
    """The channel was named and cannot say what its mark reads. A
    SystemExit, so the planner stops on it with the message as its last
    line - a broken channel config, not a verdict on the material."""


def watermark_text(channel, channel_cfg):
    """(text, note) for `plan.watermark.text`.

    `channel` is what `--channel` said (an id or a path to a .json), and
    `channel_cfg` the config it loaded to (None when it did not). Returns
    (None, note) without a channel; raises WatermarkError when the channel
    is named but its config gives no `display_name`."""
    if not channel:
        return None, ("watermark: no --channel, so no mark is drawn - the text "
                      "is the channel's display_name (CF-0212)")
    if not isinstance(channel_cfg, dict):
        raise WatermarkError(
            f"watermark: channel {channel!r} has no readable config, so there is "
            f"no display_name to draw as its mark - fix channels/<id>.json; the "
            f"planner has no default name (CF-0212)")
    name = channel_cfg.get(WATERMARK_KEY)
    if not isinstance(name, str) or not name.strip():
        raise WatermarkError(
            f"watermark: channel {channel!r} has no `{WATERMARK_KEY}` in its "
            f"config, so there is no text for its mark - add it to "
            f"channels/<id>.json; the planner has no default name (CF-0212)")
    return name.strip().upper(), None
