"""Where the graphic layer may be drawn — and why that is not the frame.

Until 2026-09-23 the four numbers below meant one thing: **what the platform
draws on top of the video**. `render/src/lib/layout.js` says so in its own
words — "safe zones are the platforms' own UI overlays". They never accounted
for the other thing a player does, which is **cut the video off**.

`CF-0329` found the difference on the channel's first published Short. The
master is 1080×1920, exactly 9:16 (0.5625 w/h). A phone screen is narrower
than that — 19.5:9 on an iPhone, 20:9 on most Android — and Shorts scales the
video to fill the screen's height, so the sides go outside the screen. At
19.5:9 that is 193.7 px of 1080, about 9 % per side. The left safe zone was
0.04. It sat inside the cut, and on the published video "filmed" read as
"ilmed", "Scotland's" as "cotland's", and the EXAMPLE_FILM watermark lost its
first letters. Every plan this factory ever wrote carried the same 0.04, back
to 2026-08-28.

So a safe zone is the sum of two unrelated things, and this module keeps them
apart:

1. **The cut.** Geometry, not taste. A frame of aspect `FRAME_ASPECT` shown
   full-height on a screen of aspect `NARROWEST_SCREEN_ASPECT` keeps
   `VISIBLE_WIDTH` of its width, and loses `CROP_PER_SIDE` off each side.
2. **The overlay.** What the player paints over what survived — the Shorts
   header, the right-hand rail of Like/Comment/Save/Share/Remix, the handle,
   title and comment bar along the bottom. Measured in fractions of the
   *screen*, so it is converted into frame fractions by `VISIBLE_WIDTH` on the
   horizontal axis and left alone on the vertical, where nothing is cut.

**Where the overlay numbers come from.** One screenshot: the user's phone,
2026-09-23, the published Short `jLolLMW5AbI` in the real YouTube app, 590×1278
(≈19.5:9). That is one device and one app version, and it is one more than this
repository had before. Re-measure on a second phone before trusting the third
decimal; the numbers are here, named, so that re-measuring means editing four
lines rather than hunting through a planner.

**Second measurement, 2026-10-01** (`CF-0329`): an iPhone 15 Pro Max, the
YouTube app opened from the channel page, eight screenshots of five published
Shorts, 590×1280. The player does *not* fill the screen's height there: the
app's tab bar sits below the video, which runs from y 0 to ≈1166. So the frame
is ≈656 px wide on a 590 px screen and loses ≈5 % per side, half of the 10 %
`CROP_PER_SIDE` assumes — the 20:9 bound below is the conservative one, and the
watermark's left edge landing at x 44-46, exactly where 0.116 of a 656 px frame
puts it, confirms the geometry. Overlay in frame terms: header icons end at
y 126 (0.108 ≤ top 0.12); the rail's labels start at x 510 (0.136 of the screen,
same as 0.14 here; 0.172 of the frame against the 0.212 zone); the handle row
starts at y 930 (0.202 ≤ bottom 0.28, ~90 px spare). Nothing of the graphic
layer was cut or covered in any of the eight. Numbers left as they are; the
bottom is the one with room to give back if layout ever needs it. Both phones
measured so far are 19.5:9 iPhones — a 20:9 Android is still unmeasured.

**The cost, stated rather than hidden.** The usable band goes from 864 px of
1080 (the old 0.04/0.16) to about 726. Captions wrap sooner and the layout has
less room. That is not a regression introduced here — it is how much room there
actually was all along, on the screen where the video is actually watched.
"""

FRAME_ASPECT = 9 / 16

# The narrowest screen we promise to look right on, as width/height. 20:9
# covers the iPhone's 19.5:9 and nearly every current Android; 21:9 exists
# (Sony Xperia) and is deliberately not covered, because the extra ~2 % per
# side costs usable width on every phone to protect a rare one. Changing this
# number is a product decision, not a tuning knob.
NARROWEST_SCREEN_ASPECT = 9 / 20

# Fraction of the frame's width that survives the player's fill-crop, and what
# is lost off each side. Pure geometry; do not hand-edit.
VISIBLE_WIDTH = NARROWEST_SCREEN_ASPECT / FRAME_ASPECT
CROP_PER_SIDE = (1 - VISIBLE_WIDTH) / 2

# What the player paints on top, as fractions of the screen the viewer sees.
# Measured off the 2026-09-23 screenshot described above.
OVERLAY = {
    # Status bar plus the Shorts header (back arrow, sound, search, ⋮).
    "top": 0.12,
    # Handle + Subscribe row, title, the "New" chip and the comment bar.
    "bottom": 0.28,
    # Nothing of the player's lives on the left; a hair of margin so that text
    # does not start flush against the cut.
    "left": 0.02,
    # The rail: Like, Comment, Save, Share, Remix.
    "right": 0.14,
}


def safe_zones():
    """The four fractions of the **frame** that the graphic layer must stay inside."""
    return {
        "top": round(OVERLAY["top"], 4),
        "bottom": round(OVERLAY["bottom"], 4),
        "left": round(CROP_PER_SIDE + OVERLAY["left"] * VISIBLE_WIDTH, 4),
        "right": round(CROP_PER_SIDE + OVERLAY["right"] * VISIBLE_WIDTH, 4),
    }


def survives_the_cut(zones):
    """Is a plan's own safe area at least as wide as the cut it has to survive?

    A plan written before CF-0329 answers no — it carries 0.04 on the left —
    and `qc_render` refuses it rather than rendering a video whose left edge is
    known in advance to be gone. Returns the sides that fail, empty when the
    plan is fine.

    **A side the plan does not name is not a failure.** It falls through to the
    renderer's own default, which is this module's own number; refusing it
    would fail every minimal plan for carrying no opinion, which is not the
    defect. What is refused is a plan that states a zone and states it too
    narrow — and every plan the planner writes states all four.

    Its price (CF-0320) is replayed by machine from the root:
    `shared/runlog/gate_price.py` loads this very function by path as the
    gate-price rule "safe_area" of shared/gate-prices.json (a rule name, not a
    config key) and runs it over every frozen
    `work/<slug>/plan.json`. Measured 2026-09-26: 1 of 4 ready videos over the
    window (`outrider-doune-castle`, the video that carries the defect), 17 of
    20 over every batch on disk — every pre-fix plan, none after. So keep this
    a pure function of the zones: the ledger's number is only honest while the
    rule it replays is the one `qc_render` calls.
    """
    zones = zones or {}
    bad = []
    for side in ("left", "right"):
        have = zones.get(side)
        if have is not None and have + 1e-9 < CROP_PER_SIDE:
            bad.append((side, have, round(CROP_PER_SIDE, 4)))
    return bad
