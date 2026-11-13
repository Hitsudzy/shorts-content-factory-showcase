"""CF-0327: the inset panel a shot carries, and whether the frame keeps it whole.

**The defect this exists for.** `mormon-wives-comeback`
(`example-film/2026-09-17T1901Z`), 29.0-30.5 s: a narrow strip of pink hugging
the left edge of the frame, a shoulder and a rim at the very border, and
nothing else of the picture it belongs to. The user called it "an insert cut
off"; the batch's own artefacts say the proof layer delivered nothing at all
here (`proof p1: no_block`, all three attempts), so the thing on screen is not
our insert layer. It is the *source shot's own* inset: block 11's frame is a
split screen, a bright panel spanning x=127..871 of 1920, and the 9:16 cover
window this factory pointed at the face - `focus.x = 0.5305`, window
714.8..1322.3 - kept 156 px of that panel's 744. Twenty-one percent of a panel,
flush against the left edge, for a second and a half.

Block 10, the insert the user saw whole one second earlier, is the same kind of
shot framed differently: its bright region is a soft gradient with no border at
all, and the window sits inside it. So "why does the second one land differently
from the first" has a numeric answer, and it is not animation and not the size
of a capture: **nothing in the planner ever asked where the shot's own panel
was.** `smart_crop` frames on faces; a face is not a panel, and a window centred
on a face lands wherever it lands with respect to one.

**What a panel is, here.** A region bounded left and right by a vertical edge
that runs through nearly the whole height of the frame. That is what a
picture-in-picture, a split screen, an on-screen document or a phone-screen
mock-up looks like, and it is what a photograph of a room never looks like: a
real scene has edges, but they stop - a door frame ends at a wall, a person ends
at their shoulders. Measured on the two frames above, the separation is not
close: block 11's two borders run through 96 % of the rows, block 10's strongest
candidate through 57 %. `MIN_EDGE_ROWS = 0.85` sits in the gap.

**The rule the factory now holds itself to.** A panel is either on screen whole
or not on screen at all. A sliver is the one outcome forbidden - it shows the
viewer that there was something to see and then does not show it, which is the
same failure mode whether the panel was our proof capture or the footage's own
inset. `verdict()` says which of the three a window delivers; the planner moves
the window to one of the two allowed answers (build_render_plan.py) and
`qc_render.py` refuses a render that reached the screen with the third.

Deliberately not a gate of its own on the *plan* side: a panel the planner
cannot resolve is recorded and rendered, and the refusal happens once, at
`qc_render`, where every other "the delivered picture is wrong" verdict is
made. Two refusals for one defect would cost two rebuilds for one fix.
"""
import os

# A border column counts when this fraction of the frame's rows step across it.
# Measured, not chosen: see the module docstring. A panel needs two of them.
MIN_EDGE_ROWS = 0.85

# How big a luma step, 0-255, counts as an edge for one row. Low enough to
# catch a pale panel on a pale background, high enough that film grain and
# JPEG noise do not vote.
EDGE_STEP = 25

# The half-width, in analysis pixels, the step is measured across. A border is
# never one pixel wide after the source has been scaled and encoded.
EDGE_SPAN = 3

# The analysis is done on a downscale: the borders this looks for are global
# structure, and 320 px of width is plenty to find them for a fraction of the
# pixels. Wider than a thumbnail so that a genuinely thin panel border survives.
ANALYSIS_WIDTH = 320

# A panel narrower than this fraction of the source is not a panel - it is a
# sign, a lower third, a phone in someone's hand. Nothing this module says
# about those would be worth acting on.
MIN_PANEL_WIDTH = 0.12

# The two answers a window is allowed to give. A window that keeps at least
# WHOLE of the panel's area shows it; one that keeps at most ABSENT does not.
# Anything between the two is the sliver this task is named after.
PANEL_WHOLE = 0.9
PANEL_ABSENT = 0.05

WHOLE, ABSENT, CUT = "whole", "absent", "cut"

# CF-0320: a new refusal states its mode in configuration rather than in code,
# because the price of the refusal is measured after the code is written and
# the answer may be "warning". `fail` is what DoD 4 of 1.4.5 asks for and so is
# the default; `runlog gate-price` decides whether the channel keeps it.
MODE_FAIL, MODE_WARN, MODE_OFF = "fail", "warn", "off"
MODES = (MODE_FAIL, MODE_WARN, MODE_OFF)
DEFAULT_MODE = MODE_FAIL

# The key on the plan (`qc_thresholds`) and, upstream of it, in the channel's
# `video_editor` block. One name, spelled once.
MODE_KEY = "panel_in_frame_mode"
FLOOR_KEY = "panel_in_frame_floor"

# The environment escape hatch, for a replay of the gate over frozen artefacts
# that must not be steered by the plan the batch happened to carry.
MODE_ENV = "CF_PANEL_IN_FRAME_MODE"


def mode_of(plan, default=DEFAULT_MODE):
    """`fail` / `warn` / `off` for this plan, from configuration only.

    Order: the environment (a replay asking for one specific mode), then the
    plan's `qc_thresholds`, then the default. An unrecognised value is not
    silently taken as "off" - that would turn a typo into a disabled gate -
    it falls back to the default and the caller's note says the value was
    not understood.
    """
    raw = os.environ.get(MODE_ENV)
    if raw is None:
        raw = ((plan or {}).get("qc_thresholds") or {}).get(MODE_KEY)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    return value if value in MODES else default


# CF-0894: the cuts of a `sequence` block are measured by the gate like any
# other cropped picture (qc_render.panel_blocks, one row per cut, `cut` on
# it), but a cut-off panel on a cut is a *new* refusal and a new price
# (score_log reads `panel_cut_blocks`): until its count over the batches has
# been measured, a cut's fault is recorded apart (`panel_cut_sequence_blocks`)
# and neither refuses nor costs anything. `video_editor.panel_in_frame.
# sequence_cuts: true` in the channel config (carried onto the plan as this
# key) puts them on the ordinary path - the mode and the price of a plain
# block's fault.
SEQUENCE_KEY = "panel_in_frame_sequence_cuts"
DEFAULT_SEQUENCE_CUTS = False


def sequence_cuts_judged(plan, default=DEFAULT_SEQUENCE_CUTS):
    """CF-0894: does a cut-off panel on a sequence cut count like one on a
    plain block (True), or is it only measured (False, the default)? Only a
    real boolean on the plan's `qc_thresholds` changes the answer."""
    raw = ((plan or {}).get("qc_thresholds") or {}).get(SEQUENCE_KEY)
    return raw if isinstance(raw, bool) else default


def floor_of(plan, default=PANEL_WHOLE):
    """The fraction of a panel's area the delivered window has to keep."""
    raw = ((plan or {}).get("qc_thresholds") or {}).get(FLOOR_KEY)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if 0.0 < value <= 1.0 else default


# --------------------------------------------------------------------------
# the detector
# --------------------------------------------------------------------------

def _luma(path):
    """The image at `path` as a float array of luma, downscaled to
    ANALYSIS_WIDTH, plus the source's own (width, height). None when it cannot
    be read - a caller with no picture has nothing to judge, which is not the
    same as a picture with no panel."""
    try:
        from PIL import Image
        import numpy as np
    except Exception:                                   # noqa: BLE001
        return None, None
    try:
        with Image.open(path) as im:
            size = im.size
            if not all(size):
                return None, None
            height = max(1, round(size[1] * ANALYSIS_WIDTH / size[0]))
            small = im.convert("L").resize((ANALYSIS_WIDTH, height))
            return np.asarray(small).astype("float32"), size
    except Exception:                                   # noqa: BLE001
        return None, None


def border_columns(path):
    """Columns of the analysis image that a vertical border runs down, as
    `[(x_fraction, rows)]` sorted left to right.

    `rows` is the fraction of the image's rows that step across the column by
    at least EDGE_STEP - the number the module docstring separates a panel
    border from a scene's own edges with. Neighbouring columns of one border
    are collapsed to the strongest of them, so a 6 px border votes once.
    """
    a, _size = _luma(path)
    if a is None:
        return []
    import numpy as np
    k = EDGE_SPAN
    if a.shape[1] <= 2 * k:
        return []
    step = np.abs(a[:, 2 * k:] - a[:, :-2 * k])
    rows = (step > EDGE_STEP).mean(axis=0)
    strong = [i for i, v in enumerate(rows) if v >= MIN_EDGE_ROWS]
    out, group = [], []
    for i in strong:
        if group and i - group[-1] > 2 * k:
            out.append(group)
            group = []
        group.append(i)
    if group:
        out.append(group)
    width = a.shape[1]
    peaks = []
    for g in out:
        best = max(g, key=lambda i: rows[i])
        peaks.append(((best + k) / width, round(float(rows[best]), 3)))
    return sorted(peaks)


def find_panel(path):
    """The dominant inset panel of the image at `path`, or None.

    `{"x0", "x1", "width", "rows"}` in fractions of the source's width: the
    widest band between two border columns that is at least MIN_PANEL_WIDTH
    wide. The widest rather than the first, because a split screen's two halves
    and the graphics inside one of them all produce borders and the band that
    matters is the one carrying a picture.

    A frame's own left and right edges are not borders and are never candidates:
    a shot is not a panel inside itself.
    """
    cols = border_columns(path)
    if len(cols) < 2:
        return None
    best = None
    for i in range(len(cols) - 1):
        for j in range(i + 1, len(cols)):
            x0, rows0 = cols[i]
            x1, rows1 = cols[j]
            if x1 - x0 < MIN_PANEL_WIDTH:
                continue
            if best is None or (x1 - x0) > (best["x1"] - best["x0"]):
                best = {"x0": round(x0, 4), "x1": round(x1, 4),
                        "width": round(x1 - x0, 4),
                        "rows": round(min(rows0, rows1), 3)}
    return best


# --------------------------------------------------------------------------
# the geometry
# --------------------------------------------------------------------------

def visible_fraction(panel, window, size):
    """How much of `panel` the delivered `window` keeps, 0.0-1.0.

    `panel` is in fractions of the source's width (find_panel's answer),
    `window` is `smart_crop.delivered_window()`'s `(x, y, w, h)` in source
    pixels and `size` is the source's `(width, height)`. Only the horizontal
    axis is measured: a panel is found by its vertical borders and this module
    makes no claim about where it starts and stops vertically, so pretending to
    an area would be pretending to a number it does not have.
    """
    if not panel or not window or not size or not size[0]:
        return None
    w = float(size[0])
    px0, px1 = panel["x0"] * w, panel["x1"] * w
    if px1 <= px0:
        return None
    wx0 = max(0.0, float(window[0]))
    wx1 = wx0 + float(window[2])
    keep = max(0.0, min(px1, wx1) - max(px0, wx0))
    return round(keep / (px1 - px0), 4)


def verdict(fraction, floor=PANEL_WHOLE, absent=PANEL_ABSENT):
    """`whole` / `absent` / `cut` for a visible fraction. None stays None."""
    if fraction is None:
        return None
    if fraction >= floor:
        return WHOLE
    if fraction <= absent:
        return ABSENT
    return CUT


def window_for(size, focus_x, focus_y, zoom, fit, aspect=(9, 16)):
    """`smart_crop.delivered_window()` for a focus stated as two numbers.

    Here so that the planner, the gate and the tests all ask the same question
    the same way - the lesson CF-0033 and CF-0155 both left behind.
    """
    import smart_crop
    return smart_crop.delivered_window(size, (focus_x, focus_y), zoom or 1.0,
                                       aspect[0], aspect[1], fit or "cover")


def candidates(panel, size, focus_x, zoom=1.0, fit="cover", aspect=(9, 16)):
    """Every focus that answers the panel legally, best first.

    `[(focus_x, outcome)]`, outcome `whole` or `absent`, ordered by what the
    channel would rather have: **showing the panel beats hiding it**, and among
    equals the one that moves the framing least wins. A panel is content - an
    article, the other half of a split screen, a phone screen being read out -
    so a window that can hold it whole should, and stepping off it is the
    answer for a panel too wide to hold.

    Empty when neither is reachable: a panel wider than the window that runs
    off both sides of the source, which is a frame the caller has to answer
    some other way (`fit: contain`, or not this shot at all).

    A list rather than one answer, because the caller has a second constraint
    this module knows nothing about - the subject has to survive the move
    (CF-0294) - and picking the first candidate that also keeps the face is
    the planner's job.
    """
    if not panel or not size or not size[0]:
        return []
    w, h = float(size[0]), float(size[1])
    window = window_for((w, h), focus_x, 0.5, zoom, fit, aspect)
    cw = float(window[2])
    span = w - cw
    if span <= 0:
        return []       # the window is the whole width; nothing is ever cut
    px0, px1 = panel["x0"] * w, panel["x1"] * w
    found = []
    if (px1 - px0) <= cw:
        # The panel fits: put the window's left edge at or left of the panel
        # and its right edge at or right of it, as little moved as possible.
        lo = max(0.0, px1 - cw)
        hi = min(span, px0)
        if lo <= hi:
            x = min(max(focus_x * span, lo), hi)
            found.append((round(x / span, 4), WHOLE))
    for x in (px1, px0 - cw):       # window entirely right of / left of it
        if 0.0 <= x <= span:
            found.append((round(x / span, 4), ABSENT))
    rank = {WHOLE: 0, ABSENT: 1}
    return sorted(found, key=lambda c: (rank[c[1]], abs(c[0] - focus_x)))


def resolve_focus(panel, size, focus_x, zoom=1.0, fit="cover", aspect=(9, 16)):
    """The best candidate of `candidates()`, or `(focus_x, None)` for none."""
    found = candidates(panel, size, focus_x, zoom, fit, aspect)
    return found[0] if found else (focus_x, None)
