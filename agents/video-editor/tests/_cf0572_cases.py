"""CF-0572: the plans and frames the theme equivalence is checked on - every
place the composition draws a theme colour or face: captions (active and
not), the watermark, the comparison-line badge and fact strip, the end card
(phrase + name, and name alone), the typographic procedural background, and
among footage blocks a quote card, a split ground and a per-block procedural
background. Synthetic plans; no file is read (media paths are never loaded
by the markup render)."""

LINE = {"fact_id": "production_fact", "text": "They built a real diner in Piru for the show.",
        "start_s": 2.0, "end_s": 5.4, "hold_start_s": 2.38, "hold_end_s": 5.16,
        "move_in_s": 0.38, "move_out_s": 0.24, "ref": 1, "publisher": "Wikipedia",
        "panel_w": 314, "block_index": 1}


def _words(n=20, start=0.2, step=0.48):
    names = ("the diner was real and the town of piru let the crew build it on "
             "main street for one season only").split()
    return [{"word": names[i % len(names)], "start": round(start + i * step, 3),
             "end": round(start + i * step + 0.4, 3)} for i in range(n)]


def _base(style, blocks, end_card, theme):
    plan = {
        "style": style,
        "output": {"width": 1080, "height": 1920, "fps": 30},
        "safe_zones": {"top": 0.12, "bottom": 0.28, "left": 0.116, "right": 0.212},
        "layout": {"main": {"fit": "cover"}, "secondary": None},
        "watermark": {"text": "EXAMPLE_FILM", "position": "top-left"},
        "audio": {"src": None, "duration": 10.0},
        "duration": {"actual": 10.0, "composition": 13.0},
        "words": _words(),
        "punches": [3.1],
        "comparison_lines": [dict(LINE)],
        "blocks": blocks,
        "end_card": end_card,
    }
    if theme is not None:
        plan["theme"] = theme
    return plan


PHRASE_CARD = {"text": "Every set is somebody's town.", "channel_name": "ExampleFilm",
               "variant": "phrase", "start_s": 10.0, "seconds": 3.0}
NAME_CARD = {"text": None, "channel_name": "ExampleFilm", "variant": "name",
             "start_s": 10.0, "seconds": 3.0}

PALETTE_SEEDS = (0, 1, 2, 5, 6, 9)  # palettes 0, 4, 5, 1, 2, 3 at 3732fb7

FOOTAGE_BLOCKS = [
    {"start": 0.0, "end": 3.0, "intent": "hook",
     "asset": {"kind": "card", "text": "A real diner"}},
    {"start": 3.0, "end": 6.0, "intent": "contrast",
     "asset": {"kind": "split", "seam_px": 6,
               "sides": [{"side": "a", "kind": "still", "src": "/nonexistent/a.jpg"},
                         {"side": "b", "kind": "still", "src": "/nonexistent/b.jpg"}]}},
    {"start": 6.0, "end": 10.0, "intent": "payoff", "asset": {"kind": "procedural"}},
]


def cases(theme):
    """[{plan, frame, what}] - `theme` goes into every plan (None: no key)."""
    typo = _base("typographic", [{"start": 0.0, "end": 10.0, "intent": "all",
                                  "asset": {"kind": "procedural"}}], PHRASE_CARD, theme)
    typo_name = _base("typographic", [{"start": 0.0, "end": 10.0, "intent": "all",
                                       "asset": {"kind": "procedural"}}], NAME_CARD, theme)
    foot = _base("footage", FOOTAGE_BLOCKS, PHRASE_CARD, theme)
    return [
        {"what": "typographic: captions, watermark, procedural ground", "plan": typo, "frame": 15},
        {"what": "typographic: comparison line in its hold", "plan": typo, "frame": 110},
        {"what": "typographic: comparison line moving in", "plan": typo, "frame": 64},
        {"what": "typographic: procedural ground later on", "plan": typo, "frame": 250},
        {"what": "end card: phrase and name", "plan": typo, "frame": 340},
        {"what": "end card: fading in", "plan": typo, "frame": 296},
        {"what": "end card: name alone", "plan": typo_name, "frame": 340},
        {"what": "footage: quote card", "plan": foot, "frame": 45},
        {"what": "footage: split ground", "plan": foot, "frame": 135},
        {"what": "footage: per-block procedural ground", "plan": foot, "frame": 240},
    ] + [
        # The procedural ground picks its palette off a seed (watermark text
        # and voice path): these seeds between them reach palette 0 (the
        # theme's own) and every one of `procedural_palettes`.
        {"what": f"procedural palette seed {seed}",
         "plan": {**typo, "audio": {"src": f"/nonexistent/voice-{seed}.wav", "duration": 10.0}},
         "frame": 30}
        for seed in PALETTE_SEEDS
    ]


#: (verbatim_text, author_or_outlet, posted_at) for the quote card PNGs
#: (render_quote.py) - a three-line quotation with an ISO datetime, and a
#: post's one-word quote under a handle.
QUOTES = [
    ("They built a real diner in Piru, on its main street, for the show.",
     "Variety", "2026-09-01T10:00:00Z"),
    ("again", "@showrunner", "2026-09-02"),
]
