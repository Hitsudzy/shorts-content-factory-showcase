"""Shared pieces of the Video Editor pipeline.

These constants and helpers were copied into six or eight scripts as the agent
grew, which is how the asset gate and the plan builder ended up probing clips at
different offsets and disagreeing about whether a fading shot was black. One
definition each, so they cannot drift apart again.
"""
import array
import json
import subprocess
import sys
import wave
from pathlib import Path
from _runlog import runlog  # CF-0107: ffmpeg/ffprobe/sibling scripts as child events
# CF-0125: AGENT_ROOT is the checkout this file lives in (a worktree runs its
# own code); VENV_PY is the *main* checkout's interpreter, because .venv/ is
# gitignored and a worktree therefore has none of its own.
from repo_paths import AGENT_ROOT, VENV_PY  # noqa: F401 - re-exported

# ffmpeg-full is keg-only: the plain formula lacks libass, so the `subtitles`
# filter is unavailable there.
FFMPEG = "/usr/local/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE = "/usr/local/opt/ffmpeg-full/bin/ffprobe"

SCRIPTS = AGENT_ROOT / "scripts"
RENDER = AGENT_ROOT / "render"

# Where an asset is probed for quality. Every gate uses these same offsets: a
# shot that fades in reads as usable at one instant and as a black frame at
# another, so disagreeing probes let a 98%-black clip through once already.
PROBE_OFFSET = 0.5

# Below this share of the subject surviving the crop, or below this short-side
# resolution, an asset is not usable and the caller should try another
# candidate. resolve_anchors.py used to gate at looser defaults (0.40 / 600)
# than qc_asset.py and build_render_plan.py actually enforce (0.65 / 720), so
# a candidate it accepted could still be rejected downstream with nothing left
# to substitute (CF-0003) - one definition so the early and late checks agree.
MIN_COVERAGE = 0.65

# CF-0104: MIN_SHORT_SIDE is no longer compared against the source's own
# short side. It is compared against the geometry that actually reaches the
# render, and which geometry that is depends on the delivery mode
# (delivery_fit() below):
#
#   cover   - the 9:16 window AssetLayer.jsx's object-fit:cover shows
#             (smart_crop.crop_for_aspect()'s tightened rect / delivered_
#             window()'s `ch`). object-fit:cover always frames the source's
#             full available height once it is wider than 9:16 (CF-0033), so
#             a 608px-*wide* portrait source whose whole ~1080px height
#             survives into that window is not the same shot as one actually
#             cut down to 608px of usable height - the old check, which read
#             the source's raw short side off the cut clip, could not tell
#             them apart and rejected both. The 720 floor itself does not
#             move (CF-0062 question 1, variant A): it is still the one gate
#             that catches the pipeline's own caption crop cutting a window
#             under a readable height (RUN_LOG.txt:52, 2026-09-03T2037Z run) -
#             only what it is measured against changes.
#   contain - a title/end card, fitted whole and letterboxed (CF-0047) so its
#             wordmark survives; there is no crop window to hold a floor
#             against. What limits legibility instead is how far the whole
#             frame has to be blown up to reach the 1920px delivery height -
#             MAX_CONTAIN_UPSCALE below.
MIN_SHORT_SIDE = 720

# CF-0104/CF-0062: the upscale ceiling for a `contain`-delivered card, i.e.
# 1920 / (the card's own frame height, after any caption crop - CF-0103's
# subtitle band comes off a card's bottom the same as any other clip's).
# Measured across every card CF-0062's real batch accepted: median 2.67x,
# max 3.31x (ZZ_urA56pJE); plain 1080p sources ranged 1.78x-2.39x depending
# on how much letterbox their own footage had already lost before the caption
# crop ran. 3.31 is the measured ceiling of what was actually accepted, not a
# guess - a card upscaled further than that is the failure this floor exists
# to catch.
MAX_CONTAIN_UPSCALE = 3.31

# CF-0068: the sound insert's mix and placement constants (inserts/sound.json
# `mix.constants` / `placement`). MAX_SOUND_SECONDS is inserts_lib's and is
# imported where it is needed, never repeated here. None of these is a
# measurement yet (`validated.status: unvalidated`): the level is where a
# recognisable sound reads as punctuation rather than as a second speaker,
# the fades are the shortest that stop a click, the audibility floor was set 8
# dB above the bed's (MIN_BED_RMS_DB = -38.0 in qc_render.py) because a sound
# that was placed has to be *heard*, not merely present - CF-0025 has since
# moved the bed's floor into the >200 Hz band, so the two numbers are no
# longer the same meter and the 8 dB is history, not a live relation - and the
# gap is roughly two median blocks. The first batch on a test config with the
# library filled (CF-0115) is what turns any of them into a measurement.
SOUND_LEVEL_REL_VOICE_DB = -3.0   # integrated loudness vs the whole voice track
SOUND_DUCKS_BED = True            # the bed is sidechain-ducked under the sound
SOUND_DUCKS_VOICE = False         # the voice is never ducked - it is the product
SOUND_FADE_IN_MS = 5
SOUND_FADE_OUT_MS = 40
SOUND_PEAK_CEILING_DBFS = -1.0
SOUND_MIN_GAP_SECONDS = 4.0       # anchor to anchor between two placed sounds
SOUND_MAX_PER_VIDEO = 2

# CF-0025: where the background bed is measured, and by whom. The bed is
# mixed by build_soundtrack.py and gated by qc_render.py, and the two
# disagreed with the user's ear for a whole milestone because they both
# measured it broadband: 95.2% of the generated bed's energy sat under
# 100 Hz, which a phone or laptop speaker does not radiate at all, so a bed
# reading a healthy -32 dBFS on the meter was -58 dBFS in the band anyone
# actually hears. Everything about the bed's level is therefore measured
# above BED_AUDIBLE_BAND_HZ, in both files, by the same definition.
BED_AUDIBLE_BAND_HZ = 200.0     # the low edge of what a small speaker radiates
BED_FADE_SECONDS = 1.5          # the generated bed's own fade at each end

# CF-0071: the screenshot proof (inserts/proof.json). Every number below
# mirrors a field of that contract - `placement`, `legibility`, the
# `behaviour` block of each accepted capture method - and is named here so
# proof_layer.py, render_quote.py, capture_page.py and build_render_plan.py's
# gate read one definition. The contract is what validate_inserts.py checks
# storyboards and channel configs against; these are what runs at render time.
#
# placement
PROOF_MIN_BLOCK_SECONDS = 3.0       # a block shorter than this never carries a proof
PROOF_READING_RATE_CPS = 12.0       # and never one shorter than len(verbatim_text) / this
PROOF_MAX_READING_SECONDS = 6.0     # a text that needs longer than this does not go in
PROOF_MAX_PER_VIDEO = 2
PROOF_MAX_VERBATIM_CHARS = 72       # script_contract.max_verbatim_chars -> `too_long`
# legibility - the gate build_render_plan.check_proof_gates() runs instead of
# the footage asset gate (composition.asset_gate.skipped). The floor is half
# our own caption: a line of type the viewer could not read as a caption is
# not evidence either.
PROOF_CAPTION_SIZE_PX = 78
PROOF_FRAME_HEIGHT_REF = 1920
PROOF_MIN_TEXT_HEIGHT_FRACTION_OF_CAPTION = 0.5
PROOF_MIN_TEXT_HEIGHT_FRACTION = (
    PROOF_CAPTION_SIZE_PX * PROOF_MIN_TEXT_HEIGHT_FRACTION_OF_CAPTION
) / PROOF_FRAME_HEIGHT_REF
PROOF_MIN_CAPTURE_WIDTH = 1080      # no_upscale: narrower than the frame is a blurred proof
PROOF_MAX_LINES = 6
# The floor applies to the lines that carry the proof (inserts/proof.json
# legibility.floor_applies_to = "gating_lines", refined 2026-09-06): for
# headless_browser the recognised lines matching the page's <h1> (and the
# standfirst when that region was captured), for rendered_quote every line
# drawn. Furniture - navigation, subscribe prompts, breadcrumbs, dateline,
# byline, masthead - is measured and recorded, never gating. PROOF_MAX_LINES
# counts gating lines.
PROOF_MIN_GATING_LINES = 1                 # fewer recognised -> illegible
PROOF_MATCH_MIN_TOKEN_FRACTION = 0.6       # of a line's tokens found in order in the h1
PROOF_MATCH_MIN_LINE_CHARS = 4             # shorter normalised lines never gate
PROOF_TEXT_FIELD = "proof_text"            # {h1: str, standfirst: str|null}
PROOF_TEXT_SIDECAR_SUFFIX = ".proof_text.json"   # <capture>.proof_text.json beside the PNG
# rendered_quote - our own card (render_quote.py). 1080x1350 (4:5): at least
# as wide as the frame (no upscale under `contain`) and taller than
# MIN_SHORT_SIDE on its short side, so the ordinary resolution floor the
# proof gate also applies reads the card the same way it reads a capture.
PROOF_CARD_WIDTH = 1080
PROOF_CARD_HEIGHT = 1350
# headless_browser - capture_page.py / capture_page.mjs
PROOF_USER_AGENT = "shorts-content-factory/video-editor (personal research tool)"
PROOF_NOT_FOR_HOSTS = ("x.com", "twitter.com", "t.co")
PROOF_VIEWPORT_WIDTH = 640
PROOF_VIEWPORT_HEIGHT = 1136
PROOF_DEVICE_SCALE_FACTOR = 2
PROOF_CAPTURE_WIDTH = PROOF_VIEWPORT_WIDTH * PROOF_DEVICE_SCALE_FACTOR   # 1280
PROOF_REGION_DEFAULT = "article_header"
PROOF_REGION_STANDFIRST = "article_header_with_standfirst"   # the one region whose standfirst gates
PROOF_REGIONS = ("article_header", PROOF_REGION_STANDFIRST, "viewport")
PROOF_REGION_MAX_HEIGHT_PX = 1400   # capture pixels, i.e. 700 CSS px at 2x
PROOF_TIMEOUT_SECONDS = 20
PROOF_MIN_SECONDS_BETWEEN_REQUESTS_PER_HOST = 2.0
PROOF_MAX_REQUESTS_PER_HOST_PER_BATCH = 20
PROOF_MAX_ATTEMPTS_PER_URL = 1

# CF-0077: ceilings on the external tools build_render_plan.py runs per asset.
# A hang is worse than a failure - it looks like "still computing" and eats
# the window - so every wait has a ceiling and a tool that reaches it is a
# gate failure (the asset is rejected on the ordinary ASSETS REJECTED path),
# never a hang and never a traceback.
#
# ASSET_TOOL_TIMEOUT_SECONDS - qc_asset.py / smart_crop.py on one asset.
# Measured warm (worker up): qc_asset.py 0.3-0.6 s, smart_crop.py ~1 s on a
# 1080p frame (smart_crop.py runs Vision in-process, no worker wait). The
# slowest *honest* path is qc_asset.py against a wedged worker: vision_client
# waits CONNECT_TIMEOUT + REQUEST_TIMEOUT (5 + 60 s) per request before its
# in-process fallback, and qc_asset.py makes two requests (find_roi, then
# text_regions) - ~130 s plus the local fallback's own work. 240 s sits
# above that whole chain; a tool past it is stuck, not thinking.
# PROBE_FRAME_TIMEOUT_SECONDS - one ffmpeg frame grab (-ss on a local file,
# measured 0.3 s on a 45 MB clip; no Vision in the chain). 60 s is 200x that.
ASSET_TOOL_TIMEOUT_SECONDS = 240
PROBE_FRAME_TIMEOUT_SECONDS = 60
# The keyed verdict (`failed` list, next to qc_asset.py's "resolution",
# "black", ...) a timed-out tool reports as, and the info-dict key
# build_render_plan.py marks such an asset with.
TOOL_TIMEOUT_KEY = "tool_timeout"

# CF-0128: the same ceilings for the helpers below, which every other script
# in this repo runs its subprocesses through (render_video.py,
# build_soundtrack.py, qc_render.py, resolve_anchors.py, detect_text_band.py,
# meme_layer.py, proof_layer.py). CF-0077 capped the four calls
# build_render_plan.py makes directly and left these uncapped, so the same
# hang was still reachable from every other entry point.
#
# One rule for all of them: a timeout is never a value. A helper that reaches
# its ceiling raises ToolTimeout (a SystemExit, so an uncaught one ends the
# script with the message rather than a traceback) instead of returning the
# 0.0 / None / False it returns for a file it merely could not read. A hang
# and an unreadable file are different events and must not arrive as the same
# answer - a plan built on a silent 0.0 is worse than one that stopped.
# A caller that would rather substitute a candidate catches ToolTimeout, the
# way build_render_plan.probe_frame() turns its own ffmpeg timeout into a
# gate failure.
#
# The numbers. Measured 2026-09-07 on the 12 largest clips of shared/footage
# (35 MB - 1.2 GB, 2 min - 62 min of media), machine idle:
#
#   ffprobe metadata (media_duration, image_size)  max 0.48 s, flat in file
#       size - it reads the container's header, not the media.
#   ffmpeg single frame (grab_frame)               max 1.08 s (CF-0077
#       measured the same call at 0.3 s on a 45 MB clip).
#   ffmpeg cut+encode (libx264 -preset veryfast, prepare_clip.py's own
#       command) on 4 s and 12 s of media, per source: a fixed part of
#       0.6-1.5 s and a slope of 0.32-0.52 s of wall per second of media.
#
# Every ceiling below carries at least the 1.4x that CF-0052 measured this
# machine losing to thermal throttling (CPU_Speed_Limit 37% after ~2.5 h of
# back-to-back rendering) - a factory renders back to back, so the throttled
# state is the state the ceiling has to be honest in, and one derived from an
# idle measurement would fire falsely exactly on the long batch it exists for.
# Beyond that they are deliberately loose: a false timeout breaks a run that
# would have finished, which is worse than the hang it was meant to catch.
#
# FFPROBE_TIMEOUT_SECONDS - one metadata read. 0.48 s measured, 0.67 s
# throttled; 60 s is ~90x that, and the same order as CF-0077's frame-grab
# ceiling so the two probe classes read alike.
FFPROBE_TIMEOUT_SECONDS = 60

# A whole ffmpeg pass whose length is known - a cut, a decode, a mix. Derived
# from the material, per the shape the fix was scoped in: a ceiling that does
# not scale with the video is the one that turns a long honest render into a
# false failure.
#   base  - what a pass costs before it touches a frame: process start,
#           opening a 1.2 GB source, writing the output. Measured 1.5 s
#           (2.1 s throttled). 300 s is ~140x, and it is also the whole
#           ceiling a caller that cannot say how long its material is gets,
#           so it is sized for that case rather than for the fixed cost.
#   slope - 0.52 s per media second measured on the heaviest cut in the pool,
#           0.73 s throttled. 8.0 is ~11x that. The margin is this wide
#           because ffmpeg() is a generic helper: the pass it is handed may
#           be a filter_complex mix rather than the veryfast cut that was
#           measured, and nothing in the signature says which.
FFMPEG_BASE_TIMEOUT_SECONDS = 300
FFMPEG_SECONDS_PER_MEDIA_SECOND = 8.0

# A sibling script run through run_script()/run_json(). This one is not
# measured at the call: run_script() runs whatever script it is given, and
# the slowest honest ones are not ffmpeg but the model-backed steps.
# The only honest datum in reach is the run ledger (pipeline/**/*.jsonl,
# `kind: script`): the `tts+align` step - synthesize_voiceover.py plus
# align_words.py on one video - has a median of 155 s and a maximum of
# 843 s over 165 recorded runs, and `resolve` reaches 4284 s (but that is a
# whole stage over many assets, not one child). 843 s is therefore already
# an over-estimate of any single script - it is two of them plus the step's
# own overhead, recorded at minute precision, on a machine that may well have
# been throttled at the time. 2400 s is twice that even after another 1.4x of
# throttling, i.e. the same "twice the throttled worst case" margin the probe
# ceilings above carry. It is a deliberately loose placeholder, not a
# measurement of run_script() itself -
# see the task's `## Полный прогон`: the honest per-script maxima come from
# a batch run with CF-0107 child events on, which has not happened yet.
# A caller that knows its script's class passes its own `timeout=` (as
# build_render_plan.py does with ASSET_TOOL_TIMEOUT_SECONDS).
SIBLING_SCRIPT_TIMEOUT_SECONDS = 2400


class ToolTimeout(SystemExit):
    """A helper's subprocess ran past its ceiling (CF-0128).

    SystemExit, so a caller that does not care ends with the message and no
    traceback - the way run_script() already ends a run on a script that
    failed - while a caller that would rather substitute a candidate can
    catch this exactly, without catching every SystemExit in the file.

    `tool`, `target` and `ceiling` are kept as attributes so a caller can
    build its own verdict (build_render_plan.tool_timeout_info()'s shape)
    without parsing the message back out.
    """

    def __init__(self, tool, target, ceiling):
        self.tool, self.target, self.ceiling = tool, target, ceiling
        super().__init__(tool_timeout_message(tool, target, ceiling))


def tool_timeout_message(tool, target, ceiling):
    """The one sentence a timed-out helper says, in CF-0077's words: which
    tool, on what, against which ceiling, and that this is a hang rather
    than slow work - so the reader knows raising the ceiling is the wrong
    first move."""
    return (f"{tool}: no result within the {ceiling:g} s ceiling on {target} - "
            f"hung, not slow (raise the ceiling in common.py only if the tool "
            f"is honestly this long)")


def media_timeout(media_seconds=0.0):
    """The ceiling for one ffmpeg pass over `media_seconds` of material -
    FFMPEG_BASE_TIMEOUT_SECONDS plus the measured slope. 0 (the default) is
    "the caller cannot say", which gets the base alone."""
    try:
        seconds = max(0.0, float(media_seconds))
    except (TypeError, ValueError):
        seconds = 0.0
    return FFMPEG_BASE_TIMEOUT_SECONDS + FFMPEG_SECONDS_PER_MEDIA_SECOND * seconds


def delivery_fit(is_card):
    """`cover` or `contain` - the same choice build_render_plan.py makes for
    a block's asset (CF-0047: a title/end card is fitted whole so its
    wordmark survives; anything else is cropped to fill the 9:16 frame).

    CF-0104: the resolution floor depends on this choice too, and it has to
    be asked before a render plan exists to read `fit` off of - qc_asset.py's
    gate runs on a freshly cut candidate, long before build_render_plan.py
    ever sees it. One function, so the two places that decide it cannot
    quietly drift apart.
    """
    return "contain" if is_card else "cover"


# CF-0078: the delivery aspect ratio every geometry-aware check compares
# against - qc_asset.py's own CLI default (`--aspect 1080:1920`),
# usability_probe.py's QC_ASPECT and measure_crop_floor.py's TARGET_W/
# TARGET_H all agree on this same 9:16. Named here so predict_resolution_
# floor_fail() below needs no fourth copy of it.
DELIVERY_ASPECT = 1080 / 1920
# The delivery height qc_asset.py's evaluate() defaults `target_height` to -
# what a `contain` card's own height is blown up to reach.
DELIVERY_HEIGHT = 1920


def crop_bottom_height(height, crop_bottom):
    """The height left after prepare_clip.py's own caption-crop filter:
    `crop=iw:floor(ih*(1-crop)/2)*2:0:0`. Mirrors measure_crop_floor.py's
    identical helper - duplicated rather than imported because that script
    is a standalone measurement tool, not a pipeline dependency, and this
    needs the formula on the *cached*, uncut source (CF-0078), before any
    clip exists for measure_crop_floor.py's own frame probe to run on.
    """
    if not crop_bottom:
        return height
    return int((height * (1 - crop_bottom)) // 2) * 2


def predict_resolution_floor_fail(width, height, crop_bottom, fit,
                                   min_short_side=MIN_SHORT_SIDE,
                                   max_contain_upscale=MAX_CONTAIN_UPSCALE):
    """CF-0078: whether qc_asset.py's geometry-aware resolution floor
    (CF-0104) is *guaranteed* to reject this shot once prepare_clip.py's own
    caption crop (`crop_bottom`, i.e. `crop_bottom_cached`) is applied -
    computed from the index's cached width/height alone, before paying for a
    real cut() to find out. resolve_anchors.py's probably_unusable() may
    only ever skip a candidate that is doomed either way (CF-0029/CF-0048);
    this function keeps that promise for the resolution axis specifically by
    only ever answering "yes, guaranteed doomed" or "cannot tell from here" -
    never "guaranteed fine".

    contain (a title/end card, CF-0047) - build_render_plan.py always
        renders a card at zoom=1 with no crop window (CF-0104), so its own
        post-crop height is exactly what qc_asset.py's evaluate() measures.
        The prediction here is exact, not just a bound.

    cover - smart_crop.py may tighten the delivered window further for a
        single subject (CF-0033's zoom) or centre it on an off-centre focus
        point, and neither is knowable without running Vision on the real
        cut clip. What *is* knowable from geometry alone is the loosest,
        untightened window a centred, zoom=1 crop would deliver -
        smart_crop.delivered_window()'s own cover-branch formula at zoom=1,
        reproduced below rather than imported (smart_crop.py imports this
        module, so the reverse import would be circular). Zoom tightening
        can only ever shrink that window further, never grow it, so a shot
        that fails the floor even on this most generous window is one no
        real crop can save.
    """
    post_h = crop_bottom_height(height, crop_bottom or 0.0)
    if post_h <= 0:
        return True
    if fit == "contain":
        return (DELIVERY_HEIGHT / post_h) > max_contain_upscale
    if width <= 0:
        return True
    # smart_crop.delivered_window()'s cover branch, zoom=1, centred focus:
    # the window keeps the source's full (post-crop) height whenever the
    # source is wider than the delivery aspect, otherwise it is narrowed by
    # width instead and the window's height shrinks below it.
    window_h = post_h if (width / post_h) > DELIVERY_ASPECT else width / DELIVERY_ASPECT
    return window_h < min_short_side



def run_tool(cmd, *, tool=None, target=None, check=False,
             timeout=SIBLING_SCRIPT_TIMEOUT_SECONDS):
    """One child process, given as a whole command line, under a ceiling.

    CF-0132: run_script()'s generalisation, for the callers whose command is
    not "a sibling script in scripts/" and so cannot be named by one:
      - the footage-indexer's match_anchors.py - another agent's checkout,
        run on another agent's interpreter;
      - whisper.cpp, a binary;
      - the qc_asset.py and prepare_clip.py calls resolve_anchors.py builds
        through qc_command()/cut_command(), argv builders that exist so a test
        can read what the gate is told, and which must stay the one place that
        argv is written.
    Same rule as run_script(), which is now this function with the argv filled
    in: reaching the ceiling raises ToolTimeout whatever `check` says, because
    a tool that never answered has not failed the check, it has stopped.
    """
    tool = tool or Path(str(cmd[0])).name
    try:
        # CF-0815: a tool's output is read as text; a byte that is not UTF-8
        # (a tag or a path in another encoding) is a replacement character,
        # not a UnicodeDecodeError that takes the caller down.
        result = runlog.run_child(cmd, tool=tool, capture_output=True, text=True,
                                  errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ToolTimeout(tool, target if target is not None else
                          " ".join(str(a) for a in cmd[1:]) or "(no arguments)", timeout)
    if check and result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(f"{tool} failed")
    return result


def run_script(name, *args, check=True, timeout=SIBLING_SCRIPT_TIMEOUT_SECONDS):
    """Run a sibling script in this agent's own interpreter.

    CF-0128: under SIBLING_SCRIPT_TIMEOUT_SECONDS unless the caller knows its
    script's class and says so (build_render_plan.py passes
    ASSET_TOOL_TIMEOUT_SECONDS for the gate tools). A script that reaches the
    ceiling raises ToolTimeout regardless of `check`: `check` is about what a
    script *answered*, and one that never answered has not failed the check,
    it has stopped."""
    return run_tool([VENV_PY, str(SCRIPTS / name), *[str(a) for a in args]],
                    tool=name, target=" ".join(str(a) for a in args) or "(no arguments)",
                    check=check, timeout=timeout)


def run_json(name, *args, timeout=SIBLING_SCRIPT_TIMEOUT_SECONDS):
    """Run a sibling script that prints JSON, and parse it. Inherits
    run_script()'s ceiling (CF-0128) - a script that hung raises ToolTimeout
    rather than arriving here as "produced no output"."""
    result = run_script(name, *args, check=False, timeout=timeout)
    if not result.stdout.strip():
        raise SystemExit(f"{name} produced no output:\n{result.stderr}")
    return json.loads(result.stdout)


def ffmpeg(*args, check=False, timeout=None, media_seconds=None,
           log_level="error", text=True):
    """One ffmpeg pass. CF-0128: always under a ceiling.

    `timeout` when the caller has one; otherwise media_timeout(media_seconds),
    i.e. the ceiling derived from how much material this pass has to chew -
    the only ceiling that stays honest across a 3-second cut and a
    three-minute mix. `media_seconds=None` means "cannot say", which gets
    media_timeout()'s base alone. A pass that reaches the ceiling raises
    ToolTimeout regardless of `check`, for run_script()'s reason.

    CF-0132: two knobs, and they exist only so that the passes which were
    still calling runlog.run_child() directly - and therefore still waiting
    forever - fit through this one ceiling instead of growing ceilings of
    their own next to it.
      `log_level` - a pass whose *answer* is its own stderr: silencedetect,
          astats, cropdetect and blackdetect all print at ffmpeg's `info`
          level, which the default `error` would swallow. Measuring a pass is
          not a different class of wait from writing one, so it is the same
          helper and the same ceiling, not a second code path.
      `text`     - False for a pass whose answer is raw bytes on stdout
          (`-f f32le -`, the audio decodes qc_render.py and build_soundtrack.py
          make). Only the pipe's decoding changes; the ceiling does not.
    """
    ceiling = timeout if timeout is not None else media_timeout(media_seconds or 0.0)
    try:
        result = runlog.run_child(
            [FFMPEG, "-y", "-nostdin", "-hide_banner", "-v", log_level,
             *[str(a) for a in args]],
            tool="ffmpeg", capture_output=True, text=text, timeout=ceiling)
    except subprocess.TimeoutExpired:
        raise ToolTimeout("ffmpeg", " ".join(str(a) for a in args), ceiling)
    if check and result.returncode != 0:
        print(ffmpeg_stderr(result), file=sys.stderr)
        raise SystemExit("ffmpeg failed")
    return result


def ffmpeg_stderr(result):
    """What a pass said, as text, whether it was run with `text=` or not -
    so a caller that reads the log does not have to know which."""
    err = result.stderr or ("" if isinstance(result.stdout, str) else b"")
    return err.decode(errors="replace") if isinstance(err, bytes) else err


def grab_frame(source, at, dest, extra_vf=None):
    """Single frame as PNG. PNG, not JPG: some downloaded footage is full-range
    YUV, which the mjpeg encoder refuses outright.

    CF-0128: under PROBE_FRAME_TIMEOUT_SECONDS - CF-0077's own ceiling for
    exactly this call, since build_render_plan.probe_frame() grabs the same
    frame the same way. Not media_timeout(): a single frame costs what it
    costs (measured 0.3-1.1 s) no matter how long the source is. A grab that
    reaches the ceiling raises ToolTimeout rather than returning False - the
    False here means "ffmpeg wrote no frame", and a hang is not that."""
    args = ["-ss", at, "-i", source, "-frames:v", "1"]
    if extra_vf:
        args += ["-vf", extra_vf]
    ffmpeg(*args, dest, timeout=PROBE_FRAME_TIMEOUT_SECONDS)
    return Path(dest).exists()


def grab_frames(source, first, step, count, dest_pattern):
    """`count` frames of `source`, `step` seconds apart, starting at `first`,
    in ONE ffmpeg pass (CF-0155). Returns the paths written, in time order.

    `dest_pattern` is an ffmpeg output pattern (`.../probe_%02d.png`); the
    files are numbered from 1 in the order they were decoded, so index k is
    the frame at `first + k * step`.

    One pass rather than `count` calls to grab_frame() because the gate that
    needs several frames of one short clip pays a fresh decode per seek
    otherwise: measured on the CF-0122 sample, four seeks cost about what one
    pass over the whole clip costs, and the pass keeps costing that as the
    frame count grows. Same ceiling as grab_frame() - one clip's frames, not
    a re-encode of it.
    """
    stem = Path(dest_pattern)
    glob = stem.name.replace("%02d", "*")
    # A pass that writes fewer frames than the last one (a shorter clip, a
    # source that ended early) would otherwise leave the previous run's tail
    # sitting in the glob, and the caller would judge a frame from another
    # clip's window at this clip's offset.
    for stale in stem.parent.glob(glob):
        stale.unlink(missing_ok=True)
    ffmpeg("-ss", first, "-i", source, "-vf", f"fps=1/{step}",
           "-frames:v", count, dest_pattern, timeout=PROBE_FRAME_TIMEOUT_SECONDS)
    return sorted(stem.parent.glob(glob))


def ffprobe(*args, what="ffprobe", target=None, timeout=FFPROBE_TIMEOUT_SECONDS):
    """One ffprobe read, under FFPROBE_TIMEOUT_SECONDS.

    CF-0132: the four probes in this file and the five that were scattered
    across qc_render.py, prepare_clip.py, sound_layer.py and meme_layer.py are
    all the same wait - a container header read, measured flat at 0.48 s
    whatever the file weighs - so they are one function with one ceiling
    rather than nine commands each free to forget it.

    `what` is the name the timeout message uses ("ffprobe (duration)"), and
    `target` the file it names; both exist so a caller keeps CF-0077's
    sentence pointing at its own question rather than at the argv.
    """
    try:
        return runlog.run_child(
            [FFPROBE, "-v", "error", *[str(a) for a in args]],
            tool="ffprobe", capture_output=True, text=True, errors="replace",
            timeout=timeout)  # CF-0815: a non-UTF-8 tag is not a crash
    except subprocess.TimeoutExpired:
        raise ToolTimeout(what, target if target is not None else
                          " ".join(str(a) for a in args), timeout)


def probe_json(path):
    """Everything ffprobe will say about a file - format and streams - as the
    dict its JSON printer produces (qc_render.py's whole-file read)."""
    return json.loads(ffprobe("-print_format", "json", "-show_format", "-show_streams",
                              str(path), what="ffprobe (json)", target=path).stdout)


def stream_kinds(path):
    """The codec types a file carries, as a set: {"video", "audio"} or less.

    CF-0132: sound_layer.py asked this with one ffprobe command and
    meme_layer.py asked the narrower "is there any audio" with another. One
    function, so the two cannot come to disagree about what an audio track is,
    and one ceiling instead of two missing ones.
    """
    result = ffprobe("-show_entries", "stream=codec_type", "-of", "csv=p=0",
                     str(path), what="ffprobe (streams)", target=path)
    return {line.strip().strip(",") for line in result.stdout.splitlines() if line.strip()}


def media_duration(path):
    """Seconds of media in `path`, 0.0 for a file ffprobe cannot read.
    CF-0128: under FFPROBE_TIMEOUT_SECONDS, and a probe that reaches it
    raises ToolTimeout instead of returning that same 0.0 - a caller cannot
    tell an unreadable file from a wedged machine otherwise, and a plan built
    on a silently zero duration is the failure this ceiling exists to
    prevent."""
    result = ffprobe("-show_entries", "format=duration", "-of", "default=nw=1:nk=1",
                     str(path), what="ffprobe (duration)", target=path)
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


# ---------------------------------------------------------------------------
# CF-0131: where a clip block runs out of its own footage.
#
# Two scripts need this arithmetic and they must never answer it differently.
# `qc_render.py` asks it after the render, to decide whether a motionless
# block is CF-0031's playback-ran-out fault; `build_render_plan.py` asks it
# before the render, to keep such a block from being rendered at all. If they
# used two thresholds, the planner would either wave through blocks QC then
# fails (the CF-0052 demo: 948 OffthreadVideo frames past the end of a 1.30s
# clip, ~250s of a 29-minute render drawing one frozen picture) or degrade
# blocks QC would have accepted. So the numbers and the test live here, once,
# and both scripts import them - the planner's threshold is not chosen, it is
# QC's own condition read forward.
# ---------------------------------------------------------------------------

PROBE_FRACTIONS = (0.25, 0.5, 0.75)   # where in a block motion is sampled
PROBE_GAP = 0.3                       # seconds between the two sampled frames
# Video.jsx mounts every block in a Sequence starting CROSSFADE seconds early,
# so a block's clip is already 0.35s into its own playback at block["start"].
# The two numbers have to agree or the source-side probe lands on the wrong
# frame; this is the only place outside the renderer that needs to know it.
# (tests/test_frozen_block_source_check.py checks it against Video.jsx.)
RENDER_CROSSFADE = 0.35
CLIP_TAIL_TOLERANCE = 0.05   # seconds; ignore rounding at a clip's last frame
# How far back from a clip's stated duration its last decodable frame sits.
# ffmpeg's input seek returns the first frame at or after the timestamp, so a
# seek inside the final frame's own interval returns nothing at all; this has
# to clear one frame at the slowest fps the pipeline handles (24 -> 0.042s).
LAST_FRAME_EPSILON = 0.05
# CF-0249: how long the picture may sit still *continuously* before that is a
# defect rather than a held shot. The old gate asked a different question -
# "did any probe in this block move" - and a block that is alive for its first
# 4.0s and frozen for its last 5.4s answers yes (dtf-st-louis, found by the
# user on review, block 0 = 0.0-9.4s cut from a 4.03s clip). Length of the
# motionless stretch is the question that separates the two cases; max() over
# probes stays exactly where CF-0004 put it, for exactly CF-0004's reason.
#
# The number is 6 windows of PROBE_GAP, and it is set from the material this
# pipeline actually cuts into blocks (measured with the gate's own definition
# of motion, 0.3s windows at 200px, run continuously):
#
#   * the 58 clips of batch example-film/2026-09-15T1034Z - every shot the
#     detector, the source gate and prepare_clip.py let through, i.e. the
#     population a block is made of - hold still for at most 1.2s. Of their 16
#     still runs, 8 reach 0.6s, 2 reach 1.2s and none reaches 1.5s.
#   * CF-0004's canonical held pose (H-43VeYGiPM, Wile E. Coyote held in
#     mid-air on rocket skates, the case that made the second look exist) is
#     1.2s long, and is also the longest hold anywhere in that trailer.
#   * the freeze the user saw is 5.37s, and its measured motionless stretch in
#     the delivered mp4 runs 4.0-8.5s+.
#
# So 1.8s sits 1.5x above the longest hold the cut material produces and 3x
# below the defect. 1.5s was rejected: one window of margin over the measured
# 1.2s means a single sample of compression noise dipping under the floor
# decides the verdict. It also has to stay well under the pattern band's
# shortest block (4.0s), or a freeze covering nearly half a legal block would
# still slip through. 0.3s - one window - cannot be reached by construction.
#
# Whole *trailers*, unlike the shots cut out of them, do hold for seconds at a
# time (logo slates, credits: 33 runs over 3.0s and one of 11.7s across the 20
# cached trailers measured). That is not a false-positive risk this number has
# to absorb: a flagged stretch is still checked against the clip it was cut
# from (freeze_verdict), and footage that holds there too is reported as held
# footage, never as a failure.
MAX_HELD_RUN = 1.8


def source_time(block, t):
    """Where inside its own clip the renderer is at composition time `t`.

    Video.jsx starts each block's Sequence RENDER_CROSSFADE early (clamped at
    zero for the opening block) and AssetLayer.jsx trims the clip by
    `start_seconds`, so local playback time is what is left over.
    """
    seq_start = max(0.0, block["start"] - RENDER_CROSSFADE)
    return block["asset"].get("start_seconds", 0) + (t - seq_start)


def probe_times(block):
    """The composition times qc_render.frozen_blocks() samples this block at.

    A probe needs PROBE_GAP of block left after it to measure anything, so a
    block shorter than PROBE_GAP / (1 - min(PROBE_FRACTIONS)) yields none at
    all - and a block with no probes is never judged, by QC or by the planner.
    """
    span = block["end"] - block["start"]
    return [block["start"] + span * f for f in PROBE_FRACTIONS
            if block["start"] + span * f + PROBE_GAP < block["end"]]


def probe_exhausted(ts, clip_seconds):
    """True when the source-side probe at clip time `ts` has no footage left.

    Both of freeze_verdict()'s reasons for skipping a probe, in one place:
    past the last frame (OffthreadVideo holds it, so of course the render is
    still there), or so little clip left that the pair would be two frames a
    few hundredths apart rather than a measurement.
    """
    if ts >= clip_seconds - CLIP_TAIL_TOLERANCE:
        return True
    until = min(ts + PROBE_GAP, clip_seconds - LAST_FRAME_EPSILON)
    return (until - ts) < PROBE_GAP / 2


def clip_shortfall(block, clip_seconds):
    """Seconds of footage this clip block asks for and does not have, or None.

    None means qc_render.py will *not* report this block as frozen-because-
    playback-ran-out: either it is too short to be probed at all, or at least
    one probe still lands on real footage, which is the only thing that keeps
    freeze_verdict() from returning that fault. A number means every probe is
    already on the held last frame - the block is a decided defect, and the
    number is how far past the end of the file it plays.

    Note what this is *not*: a "block longer than clip by more than X" rule.
    A clip block routinely outruns its clip a little by design - the Sequence
    is a crossfade longer than the clip - and QC accepts that, so the planner
    must too.
    """
    times = probe_times(block)
    if not times or not clip_seconds:
        return None
    if not all(probe_exhausted(source_time(block, t), clip_seconds)
               for t in times):
        return None
    return round(source_time(block, block["end"]) - clip_seconds, 3)


def held_tail(block, clip_seconds):
    """Seconds this clip block would spend holding its clip's last frame, or
    None when that stretch is short enough to be the design's own slack.

    CF-0249. clip_shortfall() above answers "is *every* probe already on the
    held frame" - a block that is frozen end to end. The block the user
    caught was frozen for its last 5.37s and perfectly alive before that:
    dtf-st-louis block 0 spans 0.00-9.40s and its clip runs 4.03s, so the
    first probe lands on real footage and clip_shortfall() says None. The
    arithmetic that does see it is the same arithmetic, read forwards instead
    of backwards - how far past the end of the file the block plays:

        source_time(block, block["end"]) - clip_seconds

    which is known at plan time, from two numbers already in hand, with no
    render and no pixel measurement at all.

    The threshold is MAX_HELD_RUN, i.e. the same number qc_render.py fails a
    frozen stretch by after the render. That is the point: the planner is not
    inventing a second rule, it is stating the gate's rule one stage earlier
    (CF-0131's principle, applied to the partial case). A clip block is still
    *allowed* to outrun its clip a little - the Sequence is mounted
    RENDER_CROSSFADE (0.35s) early and every clip block ends on a held frame
    by design - and 0.35s is comfortably under MAX_HELD_RUN, so nothing that
    was accepted before is refused now.

    Returns the held seconds (never more than the block's own span, since
    that is all the screen time there is to hold), rounded, or None.
    """
    if not clip_seconds:
        return None
    overrun = source_time(block, block["end"]) - clip_seconds
    if overrun < MAX_HELD_RUN:
        return None
    return round(min(overrun, block["end"] - block["start"]), 3)


def image_size(path):
    """Native pixel width/height of an image or video frame, straight from
    ffprobe. CF-0071: proof captures bypass inspect_asset()/qc_asset.py
    entirely (the asset gate they skip is exactly the one that would
    otherwise have reported this), so the no_upscale / MIN_SHORT_SIDE gates
    need their own, narrower way to learn the source resolution.

    CF-0128: under FFPROBE_TIMEOUT_SECONDS, ToolTimeout on reaching it - the
    None this returns means "ffprobe named no size", not "ffprobe never
    answered".
    """
    result = ffprobe("-select_streams", "v:0", "-show_entries", "stream=width,height",
                     "-of", "csv=s=x:p=0", str(path),
                     what="ffprobe (size)", target=path)
    try:
        w, h = result.stdout.strip().split("x")
        return int(w), int(h)
    except ValueError:
        return None


def audio_duration(path):
    """Seconds of a wav, read from its own header.

    No ceiling here on purpose (CF-0128 listed it with the others): this runs
    no subprocess - `wave` reads the header in this process - so there is
    nothing to hang and nothing to kill. The same goes for leading_silence()
    below. Said out loud so the next reader does not go looking for the
    `timeout=` that is missing."""
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


# CF-0050: a sample this quiet is silence. 16-bit PCM full scale is 32768, so
# this is about -60 dBFS - well under qc_render.py's -45 dB silence detector,
# because the question here is "where does the audio actually begin" rather than
# "is this stretch dead air", and TTS output has no room tone to allow for.
SILENCE_SAMPLE_LEVEL = 32


def leading_silence(path):
    """Seconds of silence before the audio starts (CF-0050).

    Measured off the samples, not taken from whoever passed --lead-silence to
    synthesize_voiceover.py: the beat a `cold_frame` opening is made of is a
    property of the wav that is about to be mixed, and the one thing that must
    not happen is a plan claiming a cold open over a file that starts talking
    immediately.

    Not measured off the word alignment either, and that is the interesting
    part: whisper reports its first token as starting at 0.00 even when the
    speech in it begins most of a second later, because the token inherits its
    segment's boundary. align_words.py uses this to correct that.

    0.0 for anything this cannot read - a compressed file, a sample width other
    than 8/16/32-bit PCM. Unknown is never treated as a declared beat.
    """
    try:
        with wave.open(str(path)) as w:
            if w.getcomptype() != "NONE":
                return 0.0
            width, rate, channels = w.getsampwidth(), w.getframerate(), w.getnchannels()
            code = {1: "b", 2: "h", 4: "i"}.get(width)
            if not code:
                return 0.0
            frames = w.readframes(min(w.getnframes(), rate * 10))
    except (OSError, wave.Error):
        return 0.0
    samples = array.array(code)
    samples.frombytes(frames[:len(frames) - len(frames) % samples.itemsize])
    # Scale the threshold to the sample width so the answer does not depend on
    # the file's bit depth.
    level = SILENCE_SAMPLE_LEVEL * (2 ** (8 * (width - 2)))
    for i, v in enumerate(samples):
        if abs(v) > level:
            return round((i // max(1, channels)) / rate, 3)
    return round(len(samples) / max(1, channels) / rate, 3)


def load_words(path):
    """Word timings from align_words.py, tolerating either shape it has used."""
    data = json.load(open(path))
    return data["words"] if isinstance(data, dict) and "words" in data else data


def luma_pixels(image):
    """Greyscale pixel list, across the Pillow API change in 12."""
    return list(image.get_flattened_data()
                if hasattr(image, "get_flattened_data") else image.getdata())
