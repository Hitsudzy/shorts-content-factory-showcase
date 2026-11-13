#!/usr/bin/env python3
"""CF-0379: our captions stay on under a meme - and, since CF-0394, stay put.

The defect, found by the user on 2026-09-24: while a reaction meme was up the
word-by-word captions were gone for its whole length. The renderer hid them for
the span of *any* block carrying an insert - CF-0071's rule, written for the
proof layer, where a screenshot carries its own text. A meme carries no such
text, so the viewer lost the line and watched a mute picture.

CF-0379 answered it by raising the caption band clear of the meme for its
span; the user saw that as the captions jumping, and CF-0394 (variant D,
2026-09-25) fixed the band for the whole video just above the player's bottom
dead zone and fits the insert above it instead.

What is checked here:

  - the real Remotion composition, rendered: a plan with a meme insert gives a
    frame carrying both the meme, fitted above the band, and a caption in the
    band; a plan whose proof still says `hidden` gives a frame with the proof
    and no captions of ours anywhere. Rendered, not reasoned about - the whole
    bug was a rule in the renderer that every layer below it agreed with;
  - the geometry itself, `render/src/lib/captionBand.js`, run under plain node
    the way CF-0336 runs comparisonGeometry.js, and qc_render's Python mirror
    of it agreeing with it pixel for pixel;
  - the gate: a rendered frame with a meme and no line of ours is `blank` and a
    fault, the same frame with the line is `ink`, and the mode comes from
    configuration (CF-0320) rather than from code.

Run: python3 tests/test_meme_captions.py
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
from test_channel_theme import REEL_FROZEN  # noqa: E402 - CF-0572: the stills' theme
_TMP = tmp_root("cf0379-")
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
RENDER = AGENT_ROOT / "render"
RENDER_SRC = RENDER / "src"
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import meme_captions as mc  # noqa: E402
import qc_render  # noqa: E402
import render_video  # noqa: E402 - CF-0340: the stills get a job dir of their own

NODE = shutil.which("node")
NPX = shutil.which("npx")

WIDTH, HEIGHT = 1080, 1920
SAFE = {"top": 0.12, "bottom": 0.28, "left": 0.116, "right": 0.212}
WORDS = [{"word": "HELLO", "start": 0.2, "end": 1.0},
         {"word": "WORLD", "start": 1.0, "end": 1.8},
         {"word": "AGAIN", "start": 1.8, "end": 2.6},
         {"word": "NOW", "start": 2.6, "end": 3.4}]


def png(path, size, colour):
    from PIL import Image
    Image.new("RGB", size, colour).save(path)


def plan_with(insert, asset_src):
    return {
        "style": "cinematic",
        "output": {"width": WIDTH, "height": HEIGHT, "fps": 30},
        "safe_zones": dict(SAFE),
        "layout": {"main": {"fit": "cover"}, "secondary": None},
        "watermark": {"text": "TEST", "position": "top-left"},
        # CF-0572: the render refuses a plan without its channel's theme;
        # these stills were measured in ExampleFilm's (white captions).
        "theme": REEL_FROZEN,
        "audio": {"src": None, "duration": 4.0},
        "words": [dict(w) for w in WORDS],
        "punches": [],
        "blocks": [{"start": 0, "end": 4.0, "intent": "t",
                    "asset": {"kind": "still", "src": asset_src, "fit": "cover"},
                    "insert": insert}],
    }


# CF-0880: bbox_px is [x, y, w, h]; the cutout PNG is that w x h crop
CUTOUT_CA = {"file": "meme.cutout.png", "source_size_px": [600, 500],
             "bbox_px": [100, 50, 400, 400]}
# where the describer put the face in the shot (`roi_source: faces`)
CUTOUT_FACE = {"x": 0.5, "y": 0.3}
GREEN = (30, 200, 60)
BLUE = (30, 90, 180)


def cutout_png(path):
    """A CF-0403-shaped cutout: the source cropped to its bbox (w x h), an
    opaque ellipse filling it - the ellipse's corners are see-through."""
    from PIL import Image, ImageDraw
    w, h = CUTOUT_CA["bbox_px"][2:]
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([0, 0, w - 1, h - 1], fill=GREEN + (255,))
    im.save(path)


def cutout_overlay(render_src):
    import meme_layer as ml
    block = {"start": 0, "end": 4.0, "asset": {"kind": "still", "fit": "cover",
                                               "focus": dict(CUTOUT_FACE), "roi_source": "faces"}}
    plan = plan_with(None, "x.png")
    got = ml.cutout_placement(CUTOUT_CA, "/nowhere.png", block, ml.placement_geometry(plan),
                              {"asset_floor": {"max_upscale_factor": 2.25}})
    assert got["placement"] == ml.PLACEMENT_ON_SUBJECT, got
    cutout = {**got["cutout"], "render_src": render_src}
    return {"placement": got["placement"], "placement_why": None, "cutout": cutout,
            "motion": {"mode": "static", "why": ml.MOTION_WHY_CUTOUT}}


def band_ink(image_path, box, white=mc.WHITE_LUMA):
    from PIL import Image
    from common import luma_pixels
    x, y, w, h = box
    with Image.open(image_path) as im:
        crop = im.convert("L").crop((x, y, x + w, y + h))
        return mc.ink_fraction(luma_pixels(crop), white=white)


# --------------------------------------------------------------------------
# the rendered frames
# --------------------------------------------------------------------------

def render_stills():
    """One still per insert kind, out of the real composition.

    Assets are staged into a job directory of their own exactly as
    render_video.py stages them - the bundle is served over http and Chrome
    refuses `file://` from that origin - and the directory is removed again
    whatever happens. CF-0340: not into the shared `render/public/`, which a
    render (or this test) running alongside would copy half-filled into its
    bundle; Remotion is handed the job's public dir as --public-dir.
    """
    job = render_video.new_job("cf0379-test")
    public = render_video.job_public(job)
    staging = public / "cf0379-test"
    staging.mkdir(parents=True, exist_ok=True)
    out = {}
    try:
        png(staging / "shot.png", (1400, 900), (30, 90, 180))
        png(staging / "meme.png", (1600, 900), (200, 30, 30))
        png(staging / "proof.png", (1200, 1600), (240, 240, 240))
        meme = {"kind": "meme", "captions": "shown", "fit": "contain",
                "background": "black", "render_src": "cf0379-test/meme.png",
                "animated": False, "loop_seconds": None,
                "source_size": {"width": 1600, "height": 900}}
        proof = {"kind": "proof", "captions": "hidden", "fit": "contain",
                 "background": "black", "capture_path": "cf0379-test/proof.png"}
        # CF-0390: a card that leaves our captions on, with its text across
        # the band's own place - so the band has to climb above it.
        proof_shown = {**proof, "captions": "shown",
                       "source_size": {"width": 1200, "height": 1600},
                       "text_box": dict(PROOF_TEXT_BOX)}
        # CF-0405: a meme that fills the insert box's height, pushed in 6% -
        # drawn unclipped, its bottom would cross the gap into the band.
        png(staging / "meme-push.png", (1000, 1130), (200, 30, 30))
        meme_push = {**meme, "render_src": "cf0379-test/meme-push.png",
                     "source_size": {"width": 1000, "height": 1130},
                     "motion": {"mode": "push_in", "zoom_from": 1.0, "zoom_to": 1.06}}
        # CF-0404: a cutout laid on the face of the shot - an ellipse figure on
        # a transparent PNG, placed by meme_layer's own cutout_placement().
        cutout_png(staging / "meme.cutout.png")
        meme_cutout = {**meme, **cutout_overlay("cf0379-test/meme.cutout.png")}
        tmp = Path(tempfile.mkdtemp(prefix="m-", dir=_TMP))
        for tag, insert in (("meme", meme), ("proof", proof), ("proof-shown", proof_shown),
                            ("meme-push", meme_push), ("meme-cutout", meme_cutout),
                            ("meme-offwhite", meme)):
            plan = plan_with(insert, "cf0379-test/shot.png")
            if tag == "meme-offwhite":
                # CF-0572: a channel whose caption fill is an off-white
                plan["theme"] = {**plan["theme"], "text": OFF_WHITE}
            props = tmp / f"props-{tag}.json"
            # --props is the composition's ENTIRE props object, so the plan is
            # wrapped under the prop name; the bare plan renders the
            # placeholder instead (render_video.py says so at its own call).
            props.write_text(json.dumps({"plan": plan}))
            frame = tmp / f"{tag}.png"
            proc = subprocess.run(
                [NPX, "remotion", "still", "src/index.js", "Video", str(frame),
                 f"--props={props}", f"--public-dir={public}",
                 # the push well on, before the closing fade and while the phrase is white
                 "--frame=70" if tag == "meme-push" else "--frame=30", "--log=error"],
                cwd=RENDER, capture_output=True, text=True, timeout=300)
            assert frame.exists(), (
                f"remotion still failed for the {tag} plan: "
                f"{proc.stdout[-800:]} {proc.stderr[-800:]}")
            out[tag] = (plan, frame)
        return out
    finally:
        shutil.rmtree(job, ignore_errors=True)


STILLS = None
#: CF-0572: ExampleTech/Science's caption fill (luma ~241, under WHITE_LUMA).
OFF_WHITE = "#F5F1E9"


def stills():
    global STILLS
    if STILLS is None:
        STILLS = render_stills()
    return STILLS


def test_a_meme_frame_carries_the_meme_above_the_band_and_a_caption_in_it():
    """DoD item 1 on the frame itself, under CF-0394: the picture is there and
    so are the words - the words in their one fixed band, the meme fitted
    above it with a gap, the two never sharing a pixel."""
    plan, frame = stills()["meme"]
    insert = plan["blocks"][0]["insert"]
    picture = mc.contained_picture(insert["source_size"], mc.insert_box(plan))
    band = mc.band_box(plan)
    from PIL import Image
    with Image.open(frame) as im:
        rgb = im.convert("RGB")
        assert im.size == (WIDTH, HEIGHT)
        mid = int(picture["y"] + picture["height"] / 2)
        # the meme itself, contained on black
        assert rgb.getpixel((WIDTH // 2, mid)) == (200, 30, 30)
        # and nothing of it is left in the band: black ground and our type only
        x, y, w, h = band
        reds = sum(1 for yy in range(y, y + h, 4) for xx in range(x, x + w, 4)
                   if rgb.getpixel((xx, yy)) == (200, 30, 30))
        assert reds == 0, reds
    assert picture["y"] + picture["height"] <= band[1] - round(HEIGHT * mc.INSERT_GAP)
    assert band_ink(frame, band) > mc.MIN_INK, "no caption in the band"
    # the band is where it is on a frame with no insert at all
    assert band == mc.band_box(plan_with(None, "x.png"))


def test_the_caption_white_follows_the_channels_caption_fill():
    """CF-0572: the captions are drawn in `theme.text`. ExampleFilm's white is
    measured at WHITE_LUMA as before; an off-white fill (luma ~241) would read
    as an empty band at 250, so the floor follows the fill - and the band of a
    frame drawn in it carries ink at that floor."""
    assert mc.ink_luma(plan_with(None, "x.png")) == mc.WHITE_LUMA == 250
    assert mc.ink_luma({}) == mc.WHITE_LUMA
    assert mc.ink_luma({"theme": {"text": OFF_WHITE}}) == 236
    plan, frame = stills()["meme-offwhite"]
    band = mc.band_box(plan)
    assert band_ink(frame, band) < mc.MIN_INK, "the white floor would miss this fill"
    assert band_ink(frame, band, white=mc.ink_luma(plan)) > mc.MIN_INK, \
        "no caption found at the fill's own floor"


def test_a_pushed_in_meme_stays_in_its_box_and_the_caption_stays_in_the_band():
    """CF-0405: the push grows the picture inside the insert box, which clips
    it - so the gap and the band under the box keep no pixel of the meme, and
    our caption is still there, on a frame near the end of the push."""
    plan, frame = stills()["meme-push"]
    box = mc.insert_box(plan)
    band = mc.band_box(plan)
    from PIL import Image
    def red(p):
        return p[0] > p[1] + 60 and p[0] > p[2] + 60

    with Image.open(frame) as im:
        rgb = im.convert("RGB")
        # the meme is up, and it reaches the box's own bottom row
        assert red(rgb.getpixel((WIDTH // 2, box[1] + box[3] - 2))), \
            rgb.getpixel((WIDTH // 2, box[1] + box[3] - 2))
        # unclipped, the push at this frame would reach ~20 px into the 29 px
        # gap over the band; clipped, the gap and the band keep none of it
        below = box[1] + box[3]
        reds = sum(1 for yy in range(below, band[1] + band[3], 2) for xx in range(0, WIDTH, 4)
                   if red(rgb.getpixel((xx, yy))))
        assert reds == 0, reds
    assert band_ink(frame, band) > mc.MIN_INK, "no caption in the band under a moving meme"


def test_a_cutout_sits_on_the_face_over_the_playing_shot_and_the_caption_stays():
    """CF-0404: the figure is drawn on the face the describer found, the
    shot keeps showing around it and through its transparent corners (no black
    ground), nothing of it reaches the band, and our caption is there."""
    plan, frame = stills()["meme-cutout"]
    insert = plan["blocks"][0]["insert"]
    r = insert["cutout"]["rect"]
    band = mc.band_box(plan)
    from PIL import Image

    def near(p, c):
        return all(abs(a - b) <= 12 for a, b in zip(p, c))

    with Image.open(frame) as im:
        rgb = im.convert("RGB")
        face = (int(CUTOUT_FACE["x"] * WIDTH), int(CUTOUT_FACE["y"] * HEIGHT))
        assert near(rgb.getpixel(face), GREEN), rgb.getpixel(face)
        # the ellipse's own corner inside its rect is transparent - the shot
        assert near(rgb.getpixel((int(r["x"]) + 6, int(r["y"]) + 6)), BLUE), \
            rgb.getpixel((int(r["x"]) + 6, int(r["y"]) + 6))
        # beside the figure, in the insert box, the shot - not a black ground
        assert near(rgb.getpixel((int(r["x"] + r["width"]) + 40, face[1])), BLUE)
        x, y, w, h = band
        greens = sum(1 for yy in range(y, y + h, 3) for xx in range(x, x + w, 3)
                     if near(rgb.getpixel((xx, yy)), GREEN))
        assert greens == 0, greens
    assert r["y"] + r["height"] <= band[1] - round(HEIGHT * mc.INSERT_GAP)
    assert band_ink(frame, band) > mc.MIN_INK, "no caption in the band under a cutout"


def test_a_plan_whose_proof_says_hidden_is_still_obeyed():
    """CF-0390 turned the proof's captions on in the spec and in
    proof_layer.py; a plan written before that still says `hidden`, and the
    renderer obeys the field rather than the kind."""
    plan, frame = stills()["proof"]
    fit = mc.insert_box(plan)
    from PIL import Image
    with Image.open(frame) as im:
        assert im.convert("RGB").getpixel((WIDTH // 2, fit[3] // 2)) == (240, 240, 240)
    assert band_ink(frame, mc.band_box(plan)) == 0.0


PROOF_TEXT_BOX = {"top": 0.55, "bottom": 0.70, "left": 0.1, "right": 0.9}


def node_eval(body, payload):
    """Run `body` (a JS expression over `P`, the payload) with captionBand.js
    (as `cb`) and captions.js (as `cw`) imported, under plain node; its JSON
    back."""
    if not NODE:
        raise AssertionError("node is required to run the renderer's own geometry")
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("captionBand", "captions"):
            shutil.copy(RENDER_SRC / "lib" / f"{name}.js", Path(tmp) / f"{name}.mjs")
        runner = Path(tmp) / "run.mjs"
        runner.write_text(
            "import * as cb from './captionBand.mjs';\n"
            "import * as cw from './captions.mjs';\n"
            "const P = JSON.parse(process.argv[2]);\n"
            f"console.log(JSON.stringify({body}));\n")
        out = subprocess.run([NODE, str(runner), json.dumps(payload)],
                             capture_output=True, text=True, timeout=60)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)


def test_a_proof_frame_carries_the_card_above_the_band_and_a_caption_in_it():
    """CF-0390 on the frame, under CF-0394: the card is there and our words
    are there, the card fitted above the fixed band - so what CF-0390 had to
    solve (the band over the card's text) cannot arise."""
    plan, frame = stills()["proof-shown"]
    insert = plan["blocks"][0]["insert"]
    picture = mc.contained_picture(insert["source_size"], mc.insert_box(plan))
    band = mc.band_box(plan)
    from PIL import Image
    with Image.open(frame) as im:
        rgb = im.convert("RGB")
        assert rgb.getpixel((WIDTH // 2, 400)) == (240, 240, 240)
        # black between the card's foot and the band
        below = int(picture["y"] + picture["height"]) + 4
        assert below < band[1]
        assert rgb.getpixel((WIDTH // 2, below)) == (0, 0, 0)
    assert band_ink(frame, band) > mc.MIN_INK, "no caption in the band"
    text_bottom = picture["y"] + PROOF_TEXT_BOX["bottom"] * picture["height"]
    assert text_bottom < band[1], (text_bottom, band)


# paper-dragon (example-film 2026-09-23T1722Z), the frame the user sent on
# 2026-09-24: a 1080x1350 rendered_quote card filling the width of the frame,
# its four lines of text between 35% and 63% of it. Under CF-0390 there was no
# free zone and the band sat over the card; under CF-0394 the card is fitted
# above the band.
PAPER_DRAGON = {
    "insert": {"kind": "proof", "captions": "shown",
               "source_size": {"width": 1080, "height": 1350},
               "text_box": {"top": 0.3541, "bottom": 0.6311, "left": 0.1389, "right": 0.7574},
               "start_s": 14.11, "end_s": 20.33},
    "zone": {"x": 0, "y": 0, "width": 1080, "height": 1920},
    "safe": {"top": 230, "bottom": 538, "left": 125, "right": 229, "innerWidth": 726},
    "height": 1920, "width": 1080,
}


def test_a_full_frame_card_is_fitted_above_the_band_not_under_it():
    """The user's screenshot: the card that left the band no free zone. Now
    the card gives way - the whole card, its text included, ends a gap above
    the band's top, and the band is where it is on every other frame."""
    P = PAPER_DRAGON
    top, box, pic = node_eval(
        "[cb.bandTop(P.safe, P.height), cb.insertBox(P.zone, P.safe, P.height),"
        " cb.containedPictureBox(P.insert.source_size,"
        "   cb.insertBox(P.zone, P.safe, P.height))]", P)
    assert top == P["height"] - P["safe"]["bottom"] - round(P["height"] * mc.BAND_HEIGHT)
    assert box["y"] + box["height"] == top - round(P["height"] * mc.INSERT_GAP), (box, top)
    assert pic["y"] + pic["height"] <= box["y"] + box["height"] + 1e-6
    assert pic["height"] > 0.5 * P["height"], "still a large card, just not under the band"


def test_the_band_is_one_place_for_the_whole_video():
    """CF-0394: nothing in the renderer moves the band. The props that did
    (`liftRanges`, `captionLiftRanges`) are gone, the band's foot is the top of
    the dead zone, and the scrim under it is gone too."""
    video = (RENDER_SRC / "Video.jsx").read_text()
    captions = (RENDER_SRC / "components" / "Captions.jsx").read_text()
    for gone in ("captionLiftRanges", "liftRanges", "stripFeet"):
        assert gone not in video, gone
    assert "liftRanges" not in captions
    assert "const bottom = bandBottom(safeArea);" in captions
    # no fixed-height box clipping a second line (the scratch fork's bug)
    assert "overflow: 'hidden'" not in captions and "height: boxHeight" not in captions
    assert "linear-gradient" not in video, "the scrim is back"
    got = node_eval("[cb.bandBottom(P.safe), cb.bandTop(P.safe, P.height)]", PAPER_DRAGON)
    assert got == [538, 1920 - 538 - round(1920 * mc.BAND_HEIGHT)], got
    # and the insert makes room instead: AssetLayer fits it into insertBox
    asset = (RENDER_SRC / "components" / "AssetLayer.jsx").read_text()
    layer = asset.split("const InsertLayer = ")[1].split("\n};")[0]
    assert "insertBox(zone, safeArea, height)" in layer, layer


def test_a_phrase_never_wraps_past_two_lines():
    """CF-0394: at most three words, and closed early when the estimated wrap
    would need a third line."""
    width_em = 726 / 50
    got = node_eval(
        "[cw.linesFor(P.short, P.em), cw.linesFor(P.long, P.em),"
        " cw.groupWords(P.long, 3, 1.8, (ph) => cw.linesFor(ph, P.em) <= 2)"
        "   .map((g) => g.words.map((w) => w.word)),"
        " cw.groupWords(P.short, 3, 1.8, (ph) => cw.linesFor(ph, P.em) <= 2)"
        "   .map((g) => g.words.length)]",
        {"em": width_em,
         "short": [{"word": "THE", "start": 0, "end": .2}, {"word": "PAPER", "start": .2, "end": .5},
                   {"word": "TIGER", "start": .5, "end": .8}],
         "long": [{"word": "INTERNATIONALLY", "start": 0, "end": .4},
                  {"word": "CONSTRUCTION", "start": .4, "end": .8},
                  {"word": "INTELLIGENCE", "start": .8, "end": 1.2}]})
    one, three, long_groups, short_groups = got
    assert one == 1 and three == 3, got
    assert [len(g) for g in long_groups] == [2, 1], long_groups
    assert short_groups == [3], short_groups


def test_the_legibility_guard_reads_the_type_as_drawn():
    """caption_design_guard scales the theme's numbers by CAPTION_SCALE and no
    longer asks for a scrim (the user took it out, CF-0394)."""
    assert qc_render.caption_design_guard() == []
    assert qc_render.MIN_CAPTION_FONT_PX <= round(78 * 0.64)
    assert not hasattr(qc_render, "MIN_SCRIM_OPACITY")


def test_the_gate_fails_a_meme_with_no_line_under_it_and_passes_one_with():
    """qc_render's own gate, on video made of the rendered frames.

    The `blank` case is the defect as it shipped: a frame with a picture and no
    caption, under a plan whose insert promises captions. The `ink` case is the
    same gate over the frame the fixed renderer produces.
    """
    meme_plan, meme_frame = stills()["meme"]
    _proof_plan, proof_frame = stills()["proof"]
    tmp = Path(tempfile.mkdtemp(prefix="g-", dir=_TMP))

    def video_of(frame):
        out = tmp / f"{frame.stem}.mp4"
        if out.exists():
            return out
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1",
                        "-i", str(frame), "-t", "4", "-r", "15",
                        "-pix_fmt", "yuv420p", str(out)],
                       check=True, timeout=120)
        return out

    good = qc_render.meme_caption_blocks(str(video_of(meme_frame)), meme_plan)
    assert len(good) == 1 and good[0]["verdict"] == mc.INK, good
    assert good[0]["fault"] is False and good[0]["at"] is not None

    # The same plan over a frame that lost its captions - which is exactly what
    # the renderer produced before CF-0379.
    blank = qc_render.meme_caption_blocks(str(video_of(proof_frame)), meme_plan)
    assert len(blank) == 1 and blank[0]["verdict"] == mc.BLANK, blank
    assert blank[0]["fault"] is True and "no line" in blank[0]["reason"]


# --------------------------------------------------------------------------
# the geometry, and the mirror of it the gate measures with
# --------------------------------------------------------------------------

CASES = [
    {"w": 1600, "h": 900},      # a landscape meme
    {"w": 1920, "h": 400},      # a very wide one
    {"w": 1200, "h": 1200},     # square
    {"w": 600, "h": 1200},      # portrait, filling the box's height
    {"w": 800, "h": 1000},
]


def test_the_gate_measures_the_band_and_the_insert_the_renderer_draws():
    """The Python mirror in meme_captions.py against captionBand.js itself.

    A mirror checked against a copy of itself proves the copy; this runs the
    real module (CF-0336's rule) and demands the same pixel - for the band,
    for the box an insert is fitted into (with and without a second plane
    taking the foot of the frame), and for the picture inside it.
    """
    for secondary in (None, {"kind": "blur", "height": 0.28}, {"kind": "blur", "height": 0.1}):
        plan = plan_with(None, "x.png")
        plan["layout"]["secondary"] = secondary
        safe = mc.safe_px(plan)
        x, y, w, h = mc.main_zone(plan)
        zone = {"x": x, "y": y, "width": w, "height": h}
        top, box, pictures = node_eval(
            "[cb.bandTop(P.safe, P.height), cb.insertBox(P.zone, P.safe, P.height),"
            " P.cases.map((c) => cb.containedPictureBox({width: c.w, height: c.h},"
            "   cb.insertBox(P.zone, P.safe, P.height)))]",
            {"safe": safe, "zone": zone, "height": HEIGHT, "cases": CASES})
        bx, by, bw, bh = mc.band_box(plan)
        assert by == top and (bx, bw) == (safe["left"], safe["innerWidth"])
        assert bh == round(HEIGHT * mc.BAND_HEIGHT)
        assert mc.insert_box(plan) == (box["x"], box["y"], box["width"], box["height"]), secondary
        for case, pic in zip(CASES, pictures):
            mine = mc.contained_picture({"width": case["w"], "height": case["h"]},
                                        mc.insert_box(plan))
            assert all(abs(mine[k] - pic[k]) < 1e-6 for k in pic), (case, mine, pic)
            # and no picture reaches the band
            assert pic["y"] + pic["height"] <= top, (case, pic, top)


def test_the_suppression_is_the_insert_kind_and_not_the_presence_of_an_insert():
    """The renderer's half of item 1: `insert.captions`, never `insert`."""
    video = (RENDER_SRC / "Video.jsx").read_text()
    hidden = video.split("hiddenCaptionRanges = ")[1].split(";")[0]
    assert "block.insert.captions !== 'shown'" in hidden, hidden
    # and the gate is not judging a proof - not one that hides our captions,
    # and (CF-0390) not one that shows them either: the gate was priced on
    # memes alone
    assert mc.captioned_insert({"insert": {"kind": "proof", "captions": "hidden"}}) is False
    assert mc.captioned_insert({"insert": {"kind": "proof", "captions": "shown"}}) is False
    assert mc.captioned_insert({"insert": {"kind": "meme", "captions": "shown"}}) is True
    assert mc.captioned_insert({}) is False


def test_the_plan_carries_the_memes_own_pixel_size():
    """The band cannot be placed against a picture whose ratio nobody wrote
    down, so meme_layer.py writes it beside the file it chose."""
    import meme_layer
    src = (AGENT_ROOT / "scripts" / "meme_layer.py").read_text()
    # CF-0405: read once in place(), for the overlay and for meme_motion()
    assert "source_size = _render_size(path, animated)" in src
    assert '"source_size": source_size' in src
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / "m.png"
        png(p, (640, 481), (10, 10, 10))
        assert meme_layer._render_size(p, False) == {"width": 640, "height": 481}
        # a GIF is drawn from the even-sized mp4 prepare_render_src() cut
        assert meme_layer._render_size(p, True) == {"width": 640, "height": 480}
        assert meme_layer._render_size(Path(tmp) / "nope.png", False) is None


# --------------------------------------------------------------------------
# the gate's mode, and what it is priced by
# --------------------------------------------------------------------------

def test_the_mode_is_configuration_and_not_code():
    plan = {"qc_thresholds": {}}
    assert mc.mode_of(plan) == mc.MODE_FAIL           # DoD item 4 asks for fail
    assert mc.mode_of({"qc_thresholds": {mc.MODE_KEY: "warn"}}) == mc.MODE_WARN
    assert mc.mode_of({"qc_thresholds": {mc.MODE_KEY: "off"}}) == mc.MODE_OFF
    # a typo is not a silently disabled gate
    assert mc.mode_of({"qc_thresholds": {mc.MODE_KEY: "wrn"}}) == mc.MODE_FAIL
    # the replay's escape hatch wins over whatever the batch's plan carried
    os.environ[mc.MODE_ENV] = "warn"
    try:
        assert mc.mode_of({"qc_thresholds": {mc.MODE_KEY: "fail"}}) == mc.MODE_WARN
    finally:
        del os.environ[mc.MODE_ENV]
    assert mc.floor_of({"qc_thresholds": {mc.INK_KEY: 0.01}}) == 0.01
    assert mc.floor_of({"qc_thresholds": {mc.INK_KEY: "nonsense"}}) == mc.MIN_INK
    assert mc.RULE == "video_editor.meme_captions"


def test_silence_under_an_insert_is_not_a_defect():
    """No word spoken, no line due - the gate says nothing rather than
    accusing the gap between two phrases of having lost one."""
    assert mc.spoken_moment(WORDS, 0.0, 4.0) is not None
    assert mc.spoken_moment(WORDS, 3.5, 4.0) is None
    assert mc.spoken_moment([], 0.0, 4.0) is None
    # the longest word inside the window is the one looked at
    assert 0.2 < mc.spoken_moment(WORDS, 0.0, 1.2) < 1.0


def test_the_verdict_is_one_number_and_two_answers():
    assert mc.ink_fraction([255] * 10 + [0] * 90) == 0.1
    assert mc.ink_fraction([]) == 0.0
    assert mc.verdict(0.05) == mc.INK
    assert mc.verdict(0.0) == mc.BLANK
    assert mc.verdict(0.05, floor=0.5) == mc.BLANK


def test_the_gate_is_recorded_for_the_price_replay():
    """CF-0320: the rows are written on every render in every mode, and the
    failed gate has a name of its own so an attempt can say which rule it
    tripped."""
    src = (AGENT_ROOT / "scripts" / "qc_render.py").read_text()
    assert '"meme_caption_blocks": meme_caps,' in src
    assert '"meme_caption_gate_mode": meme_caption_mode,' in src
    assert ('("none of our captions", "meme_caption")' in src)
    # recorded outside the `if`, so `off` still measures
    measured = src.split("meme_caps = ")[1].split("\n")[0]
    assert "args.audio_only" in measured and "mode" not in measured
    assert qc_render.failed_gates(
        ["blocks showing an insert with none of our captions under it: x"]
    ) == ["meme_caption"]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
