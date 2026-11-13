#!/usr/bin/env python3
"""CF-0565: render a Example channel's ending clip - `channels/<channel>/ending.mp4`.

ExampleFilm's ending.mp4 was rendered by hand outside this repository (CF-0141),
so there was no generator to reuse. This one draws the clip from the brand the
user approved on 2026-10-06 (ROADMAP 2.3 «Brand») and the channel's own files:

* the emblem is `channels/<channel>/brand/avatar.png` - the ring, «EX», the red
  play button, the rule and the label - cut to its circle;
* the wordmark is «Example» + «Co» in the accent + the channel's name, Poppins
  ExtraBold, with the accent underline under «taGe»; under it the tracked
  «X · Y · FACTS» line with accent dots;
* the ground is the channel's two greens/navies with the banner's frame above
  and below - per channel (`motif`): ExampleScience's star-map tick rule and a
  faint star field; ExampleTech's circuit traces (CF-0568) - a bus with pads
  for the rule, and traces running in from both edges to pads on the emblem's
  ring, like the pins of a chip.

Light motion only: the emblem settles in (scale and fade), a small accent
satellite orbits it on a thin ring, the wordmark and the line fade up in turn;
the stars twinkle and drift, or the traces carry accent pulses inwards. The format is the composition's - 1080x1920 at
30 fps, H.264 High / yuv420p, an AAC track - because the Video Editor checks
the clip against the composition and never converts it (end_card.py,
decision 5 of 2026-09-08), and the clip carries its own sound (decision 2).

The sound is a short excerpt of a CC0 track, given on the command line; its
provenance goes into the channel's SOURCES.md like every other piece of
third-party audio (beds/SOURCES.md beside the channel's own beds; ExampleTech,
which mixes ExampleFilm's beds, keeps channels/example-tech/SOURCES.md).

Usage:
    python3 scripts/brand_ending.py example-science --fonts DIR \
        --audio SRC.mp3 --audio-start 600 [--out channels/example-science/ending.mp4]
    python3 scripts/brand_ending.py example-tech --fonts DIR \
        --audio SRC.mp3 --audio-start 120 [--audio-gain-db -2]

CF-0722: every flag but the channel may be left out - it is then read from
`channels/<channel>/brand.json` -> `ending.render` (fonts, track + its
sha256, audio_start, audio_gain_db; `ending.clip` for --out), and the track
is refused when its bytes are not the recorded sha256:
    python3 scripts/brand_ending.py example-tech [--plan]

`DIR` holds Poppins-ExtraBold.ttf and Poppins-Bold.ttf (Google Fonts, SIL Open
Font Licence). The length is fixed at 155 frames = 5.167 s, ExampleFilm's
ending length, so `narration_budget.ending_seconds` stays the number every
channel's budget was derived with; a different length is a config edit.
"""
import argparse
import json
import math
import os
import random
import signal
import subprocess
import sys
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H, FPS, FRAMES = 1080, 1920, 30, 155

# The whole render - drawing the 155 frames, piping them into ffmpeg and its
# `-preset slow` encode - under one deadline (tests/test_timeouts.py's
# POPEN_SITES). A render takes a minute or two; past this the encoder's
# process group is killed, the pipe breaks and the script fails.
RENDER_DEADLINE_SECONDS = 600

# Everything that must read stays inside the middle 860 px: the Shorts player
# lays its action buttons over the right edge and nothing of the brand may sit
# under them.
SAFE_WIDTH = 860

WHITE = (245, 241, 233)
LINE_GREY = (222, 210, 192)

# Per channel: the ROADMAP 2.3 brand table. Only what the clip draws.
BRANDS = {
    "example-science": {
        "ground_inner": "#0D3324", "ground_outer": "#040C09",
        "ring": "#C97A3D", "accent": "#34D399", "star": "#BFEAD4",
        "name": "Science", "line": ["SPACE", "SCIENCE", "NATURE", "FACTS"],
        "motif": "stars",
    },
    "example-tech": {
        "ground_inner": "#102846", "ground_outer": "#050A14",
        "ring": "#2F6FED", "accent": "#22D3EE", "star": "#9CC9FF",
        "name": "Tech", "line": ["TECH", "AI", "GADGETS", "FACTS"],
        "motif": "circuit",
    },
}


def hx(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ease_out(t):
    t = min(1.0, max(0.0, t))
    return 1 - (1 - t) ** 3


def ramp(t, t0, t1):
    return ease_out((t - t0) / (t1 - t0))


def ground(inner, outer):
    """Radial ground, the lighter green behind the emblem."""
    sw, sh = W // 4, H // 4
    img = Image.new("RGB", (sw, sh))
    px = img.load()
    cx, cy = sw / 2, sh * 0.42
    maxd = math.hypot(sw / 2, sh * 0.58)
    for y in range(sh):
        for x in range(sw):
            d = min(1.0, math.hypot(x - cx, y - cy) / maxd) ** 1.3
            px[x, y] = tuple(int(inner[i] + (outer[i] - inner[i]) * d) for i in range(3))
    return img.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))


def tick_rule(draw, y, color, accent):
    pitch = 34
    for i in range(W // pitch + 2):
        x = i * pitch + 6
        major = i % 4 == 0
        th = 22 if major else 12
        draw.line([(x, y - th // 2), (x, y + th // 2)], fill=color + (150 if major else 95,),
                  width=3 if major else 2)
    draw.line([(0, y + 22), (W, y + 22)], fill=accent + (120,), width=2)


def emblem(avatar_path, size):
    av = Image.open(avatar_path).convert("RGBA")
    s = av.size[0]
    mask = Image.new("L", (s * 2, s * 2), 0)
    r = s * 0.4856  # the outer ring's outside edge (388.5 of 800 px), nothing of the square beyond it
    ImageDraw.Draw(mask).ellipse([s - 2 * r, s - 2 * r, s + 2 * r, s + 2 * r], fill=255)
    mask = mask.resize((s, s), Image.LANCZOS)
    av.putalpha(mask)
    return av.resize((size, size), Image.LANCZOS)


def calibrated(path, cap_px):
    probe = ImageFont.truetype(path, 400)
    bb = ImageDraw.Draw(Image.new("L", (4, 4))).textbbox((0, 0), "H", font=probe)
    return ImageFont.truetype(path, max(4, int(round(400 * cap_px / (bb[3] - bb[1])))))


def wordmark_layer(fonts, brand, accent):
    """The wordmark and the line on a transparent layer, plus where they sit."""
    f_wm = calibrated(str(fonts / "Poppins-ExtraBold.ttf"), 96)
    f_ln = calibrated(str(fonts / "Poppins-Bold.ttf"), 27)
    parts = [("Example", WHITE), ("Co", accent), (brand["name"], WHITE)]
    probe = ImageDraw.Draw(Image.new("L", (4, 4)))
    full = "".join(p[0] for p in parts)
    while probe.textlength(full, font=f_wm) > SAFE_WIDTH:
        f_wm = ImageFont.truetype(f_wm.path, f_wm.size - 2)

    wm = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(wm)
    total = d.textlength(full, font=f_wm)
    x = (W - total) / 2
    cap = d.textbbox((0, 0), "H", font=f_wm)
    y = 40 - cap[1]
    x0 = x
    for text, color in parts:
        d.text((x, y), text, font=f_wm, fill=color)
        x += d.textlength(text, font=f_wm)
    baseline = y + cap[3]
    ul_x0 = x0 + d.textlength("Van", font=f_wm)
    ul_x1 = x0 + d.textlength("Example", font=f_wm)
    ul_y = baseline + 22
    d.line([(ul_x0, ul_y), (ul_x1, ul_y)], fill=accent, width=7)

    ln = Image.new("RGBA", (W, 120), (0, 0, 0, 0))
    d2 = ImageDraw.Draw(ln)
    track = 27 * 0.52
    dot_r, dot_gap = 5, 26
    cap2 = d2.textbbox((0, 0), "H", font=f_ln)

    def layout(start):
        items, xx, ink_r = [], start, start
        for wi, word in enumerate(brand["line"]):
            if wi:
                items.append(("dot", xx + dot_gap))
                xx += dot_gap + 2 * dot_r + dot_gap
            for ci, c in enumerate(word):
                items.append(("c", c, xx))
                ink_r = xx + d2.textbbox((0, 0), c, font=f_ln)[2]
                xx += d2.textlength(c, font=f_ln) + (track if ci < len(word) - 1 else 0)
        return items, ink_r

    _, width = layout(0)
    while width > SAFE_WIDTH - 60:
        # the line is held inside the same safe width as the wordmark, a
        # little narrower, by tightening the tracking and the dot gaps
        track *= 0.9
        dot_gap = max(14, int(dot_gap * 0.9))
        _, width = layout(0)
    items, _ = layout((W - width) / 2)
    ty = 30 - cap2[1]
    mid = 30 + (cap2[3] - cap2[1]) / 2
    for it in items:
        if it[0] == "c":
            d2.text((it[2], ty), it[1], font=f_ln, fill=LINE_GREY)
        else:
            d2.ellipse([it[1], mid - dot_r, it[1] + 2 * dot_r, mid + dot_r], fill=accent)
    return wm, ln


# -- ExampleTech's frame: circuit traces (CF-0568) ---------------------------

def _polyline_len(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def _point_at(pts, s):
    """The point at arc length `s` along the polyline (clamped to its ends)."""
    for a, b in zip(pts, pts[1:]):
        seg = math.hypot(b[0] - a[0], b[1] - a[1])
        if s <= seg:
            k = s / seg if seg else 0.0
            return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k
        s -= seg
    return pts[-1]


def _pad(draw, x, y, r, color, alpha, hole=None):
    draw.ellipse([x - r, y - r, x + r, y + r], fill=color + (alpha,))
    if hole is not None:
        h = max(1, r // 2)
        draw.ellipse([x - h, y - h, x + h, y + h], fill=hole + (255,))


def trace_rule(draw, y, color, accent, ground, down):
    """The banner's circuit frame as a rule: a bus of two lines across the
    width, stubs leaving it at a 45-degree bend every few pitches, each ending
    in a pad (every fourth pad lit in the accent), and the accent line 22 px
    off the bus on the inside, where ExampleScience's tick rule has it."""
    sign = 1 if down else -1
    draw.line([(0, y), (W, y)], fill=color + (150,), width=3)
    draw.line([(0, y - 9 * sign), (W, y - 9 * sign)], fill=color + (80,), width=2)
    pitch = 68
    for i in range(W // pitch + 2):
        x = i * pitch + 20
        long_ = i % 3 == 0
        rise = 26 if long_ else 14
        x2, y2 = x + rise, y - sign * (rise + 10)
        draw.line([(x, y - 9 * sign), (x, y - sign * 10 - 9 * sign)], fill=color + (110,), width=2)
        draw.line([(x, y - sign * 10 - 9 * sign), (x2, y2 - 9 * sign)], fill=color + (110,), width=2)
        lit = i % 4 == 1
        _pad(draw, x2, y2 - 9 * sign, 6 if long_ else 4, accent if lit else color,
             220 if lit else 150, hole=ground if long_ else None)
    draw.line([(0, y + 22 * sign), (W, y + 22 * sign)], fill=accent + (120,), width=2)


def chip_traces(rnd, ecx, ecy, ring_r):
    """Traces running in from both edges to pads on the emblem's ring: each
    leaves the edge level, bends 45 degrees once towards the emblem's middle
    and ends on the ring. Polylines in frame coordinates."""
    out = []
    for side in (-1, 1):
        for k in range(7):
            y0 = ecy - 330 + k * 110 + rnd.uniform(-14, 14)
            y1 = ecy + (y0 - ecy) * rnd.uniform(0.45, 0.7)
            x0 = 0 if side < 0 else W
            xb = ecx + side * rnd.uniform(470, 520)
            xd = xb - side * abs(y1 - y0)
            dy = y1 - ecy
            xe = ecx + side * math.sqrt(max(0.0, ring_r ** 2 - dy ** 2))
            if side * (xd - xe) <= 10:
                continue
            out.append([(x0, y0), (xb, y0), (xd, y1), (xe, y1)])
    return out


def circuit_layers(brand, base_ground, rnd, ecx, ecy, ring_r):
    """(the static traces layer, [(polyline, length, phase, speed)]) - the
    pulses are drawn per frame."""
    ring, accent = hx(brand["ring"]), hx(brand["accent"])
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    traces = chip_traces(rnd, ecx, ecy, ring_r)
    for pts in traces:
        d.line(pts, fill=ring + (95,), width=3, joint="curve")
        _pad(d, *pts[0], 5, ring, 120)
        _pad(d, *pts[-1], 7, accent, 200, hole=base_ground)
    pulses = [(pts, _polyline_len(pts), rnd.uniform(0, 1), rnd.uniform(0.45, 0.75))
              for pts in traces]
    return layer, pulses


def draw_pulses(draw, pulses, t, accent, k):
    """One accent pulse per trace, edge to ring, then again - data going in."""
    for pts, length, phase, speed in pulses:
        u = (phase + speed * t) % 1.0
        x, y = _point_at(pts, u * length)
        fade = min(1.0, u / 0.12, (1 - u) / 0.12)
        a = int(255 * k * fade)
        if a <= 0:
            continue
        draw.ellipse([x - 11, y - 11, x + 11, y + 11], fill=accent + (a // 5,))
        draw.ellipse([x - 5, y - 5, x + 5, y + 5], fill=accent + (a,))


def render_frames(channel, fonts):
    brand = BRANDS[channel]
    inner, outer = hx(brand["ground_inner"]), hx(brand["ground_outer"])
    ring, accent, star = hx(brand["ring"]), hx(brand["accent"]), hx(brand["star"])
    base = ground(inner, outer).convert("RGBA")
    frame_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(frame_layer)
    circuit = brand.get("motif") == "circuit"
    em_size = 600
    em = emblem(ROOT / "channels" / channel / "brand" / "avatar.png", em_size)
    ecx, ecy = W // 2, 760
    orbit_r = 362
    if circuit:
        trace_rule(fd, 150, ring, accent, outer, down=True)
        trace_rule(fd, H - 190, ring, accent, outer, down=False)
    else:
        tick_rule(fd, 150, ring, accent)
        tick_rule(fd, H - 190, ring, accent)
    base = Image.alpha_composite(base, frame_layer)

    rnd = random.Random(565)
    stars, pulses = [], []
    if circuit:
        traces, pulses = circuit_layers(brand, outer, random.Random(568), ecx, ecy, orbit_r)
        base = Image.alpha_composite(base, traces)
    else:
        stars = [(rnd.uniform(0, W), rnd.uniform(200, H - 230), rnd.uniform(1.0, 2.8),
                  rnd.uniform(0, 2 * math.pi), rnd.uniform(0.6, 1.6)) for _ in range(150)]
    wm, ln = wordmark_layer(fonts, brand, accent)
    wm_y, ln_y = 1120, 1300

    for i in range(FRAMES):
        t = i / FPS
        img = base.copy()
        sl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sl)
        drift = -14 * t
        for (x, y, r, ph, sp) in stars:
            a = int(60 + 110 * (0.5 + 0.5 * math.sin(ph + sp * t * 2 * math.pi / 2.5)))
            yy = y + drift * (r / 2.8)
            sd.ellipse([x - r, yy - r, x + r, yy + r], fill=star + (a,))
        k = ramp(t, 0.0, 0.8)
        if pulses:
            draw_pulses(sd, pulses, t, accent, k)
        img = Image.alpha_composite(img, sl)

        # orbit ring + satellite, fading in with the emblem
        ol = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(ol)
        od.ellipse([ecx - orbit_r, ecy - orbit_r, ecx + orbit_r, ecy + orbit_r],
                   outline=ring + (int(90 * k),), width=2)
        ang = -math.pi / 2 + t * 2 * math.pi / 5.0
        sx, sy = ecx + orbit_r * math.cos(ang), ecy + orbit_r * math.sin(ang)
        od.ellipse([sx - 16, sy - 16, sx + 16, sy + 16], fill=accent + (int(60 * k),))
        od.ellipse([sx - 8, sy - 8, sx + 8, sy + 8], fill=accent + (int(255 * k),))
        img = Image.alpha_composite(img, ol)

        # emblem settles in, then breathes
        scale = (0.86 + 0.14 * k) * (1 + 0.012 * math.sin(max(0.0, t - 0.8) * 2 * math.pi / 4.4))
        sz = int(em_size * scale)
        e = em.resize((sz, sz), Image.LANCZOS)
        if k < 1:
            e.putalpha(e.split()[3].point(lambda v, k=k: int(v * k)))
        img.alpha_composite(e, (ecx - sz // 2, ecy - sz // 2))

        kw = ramp(t, 0.55, 1.25)
        if kw > 0:
            layer = wm.copy()
            layer.putalpha(layer.split()[3].point(lambda v, k=kw: int(v * k)))
            img.alpha_composite(layer, (0, int(wm_y + 30 * (1 - kw))))
        kl = ramp(t, 1.0, 1.6)
        if kl > 0:
            layer = ln.copy()
            layer.putalpha(layer.split()[3].point(lambda v, k=kl: int(v * k)))
            img.alpha_composite(layer, (0, int(ln_y + 20 * (1 - kl))))
        yield img.convert("RGB").tobytes()


# -- CF-0722: the arguments as channel data -----------------------------------
#
# `channels/<channel>/brand.json` -> `ending.render` (shared/channel_data.py,
# `ending()`): the fonts directory, the track and its sha256, `audio_start`,
# `audio_gain_db`. A flag still wins over the data, one by one; a flag the
# command line leaves out is taken from the data, and only a value neither
# gives is a refusal. The track taken from the data - or given by a flag that
# names the data's own file - is checked against its sha256 before a frame is
# drawn: a swapped file is `ending_sha256_mismatch`, an absent one
# `ending_file_missing`. Same values -> the same ffmpeg command, byte for
# byte, whichever way they came (tests/test_channel_ending.py).

ARGS_MISSING = "ending_args_missing"     # neither the flag nor the data gives it
NO_GENERATOR = "ending_no_generator"     # the channel has no BRANDS row / no `render`


class EndingRefused(Exception):
    """A render that may not start; `code` names why (ARGS_MISSING,
    NO_GENERATOR, or channel_data's ENDING_* codes)."""

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


def channel_data(root=ROOT):
    """`<root>/shared/channel_data.py`, loaded by path (nothing of the root on
    sys.path is assumed)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("channel_data_for_brand_ending",
                                                  Path(root) / "shared" / "channel_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ffmpeg_command(audio, audio_start, audio_gain_db, out):
    """The encode: raw frames on stdin, the track's excerpt, the composition's
    format. Unchanged since CF-0565 - only lifted out of main()."""
    seconds = FRAMES / FPS
    af = (f"volume={audio_gain_db}dB,afade=t=in:st=0:d=0.4,"
          f"afade=t=out:st={seconds - 1.4:.3f}:d=1.4")
    return ["ffmpeg", "-v", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-ss", str(audio_start), "-t", f"{seconds:.6f}", "-i", str(audio),
            "-map", "0:v", "-map", "1:a", "-af", af,
            "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p", "-crf", "18",
            "-preset", "slow", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
            "-map_metadata", "-1", "-movflags", "+faststart", "-shortest", str(out)]


def render_plan(channel, fonts=None, audio=None, audio_start=None, audio_gain_db=None,
                out=None, root=ROOT, check_files=True):
    """What a render of `channel` would run, without running it:

        {channel, fonts, audio, audio_start, audio_gain_db, out, command,
         sources: {fonts|audio|audio_start|audio_gain_db|out: "flag"|"data"|"default"},
         clip_sha256}

    Each argument is the flag's (not None) or else brand.json's
    `ending.render` / `ending.clip`. With `check_files` the fonts directory and
    the track are checked (the track by its sha256 when it is the data's
    file). Raises EndingRefused with a code."""
    root = Path(root)
    if channel not in BRANDS:
        raise EndingRefused(f"{NO_GENERATOR}: {channel!r} has no row in "
                            f"brand_ending.BRANDS ({sorted(BRANDS)})", NO_GENERATOR)
    cd = channel_data(root)
    try:
        section = cd.ending(channel, root)
    except cd.EndingError as e:
        raise EndingRefused(str(e), e.code) from e
    render = (section or {}).get("render") or {}
    sources = {}

    def pick(name, flag, data_key, default=None, as_path=False):
        if flag is not None:
            sources[name] = "flag"
            return Path(flag) if as_path else float(flag)
        if data_key in render:
            sources[name] = "data"
            return root / render[data_key] if as_path else float(render[data_key])
        if default is not None:
            sources[name] = "default"
            return default
        flag_name = "--" + name.replace("_", "-")
        raise EndingRefused(
            f"{ARGS_MISSING}: {flag_name} is not given and channels/{channel}/brand.json "
            f"has no ending.render.{data_key} - pass the flag or record it in the "
            f"channel's data", ARGS_MISSING)

    fonts = pick("fonts", fonts, "fonts", as_path=True)
    audio = pick("audio", audio, "track", as_path=True)
    audio_start = pick("audio_start", audio_start, "audio_start")
    audio_gain_db = pick("audio_gain_db", audio_gain_db, "audio_gain_db", default=0.0)
    if out is not None:
        out, sources["out"] = Path(out), "flag"
    elif section and section.get("clip"):
        out, sources["out"] = root / section["clip"], "data"
    else:
        out, sources["out"] = root / "channels" / channel / "ending.mp4", "default"
    if check_files:
        missing = [f for f in cd.ENDING_FONT_FILES if not (Path(fonts) / f).is_file()]
        if missing:
            raise EndingRefused(
                f"{cd.ENDING_FILE_MISSING}: the fonts directory {fonts} has no "
                f"{', '.join(missing)}", cd.ENDING_FILE_MISSING)
        data_track = root / render["track"] if "track" in render else None
        if data_track is not None and (sources["audio"] == "data" or
                                       Path(audio).resolve() == data_track.resolve()):
            try:
                cd.ending_file(render["track"], render["track_sha256"], root,
                               what="ending track")
            except cd.EndingError as e:
                raise EndingRefused(str(e), e.code) from e
    return {"channel": channel, "fonts": str(fonts), "audio": str(audio),
            "audio_start": audio_start, "audio_gain_db": audio_gain_db, "out": str(out),
            "command": ffmpeg_command(audio, audio_start, audio_gain_db, out),
            "sources": sources,
            "clip_sha256": (section or {}).get("clip_sha256")}


def main(argv=None, root=ROOT):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("channel", choices=sorted(BRANDS))
    ap.add_argument("--fonts", type=Path,
                    help="default: ending.render.fonts of channels/<channel>/brand.json")
    ap.add_argument("--audio", type=Path,
                    help="default: ending.render.track (checked by its sha256)")
    ap.add_argument("--audio-start", type=float, help="default: ending.render.audio_start")
    ap.add_argument("--audio-gain-db", type=float,
                    help="default: ending.render.audio_gain_db, else 0.0")
    ap.add_argument("--out", type=Path, help="default: ending.clip, else "
                                             "channels/<channel>/ending.mp4")
    ap.add_argument("--plan", action="store_true",
                    help="print what would run as JSON and render nothing (CF-0722)")
    a = ap.parse_args(argv)
    try:
        plan = render_plan(a.channel, a.fonts, a.audio, a.audio_start, a.audio_gain_db,
                           a.out, root=root)
    except EndingRefused as e:
        if a.plan:
            print(json.dumps({"ok": False, "refusal": {"code": e.code, "message": str(e)}},
                             ensure_ascii=False))
            sys.exit(1)
        sys.exit(str(e))
    if a.plan:
        print(json.dumps({"ok": True, "plan": plan, "refusal": None}, ensure_ascii=False))
        return
    out = Path(plan["out"])
    p = subprocess.Popen(plan["command"], stdin=subprocess.PIPE, start_new_session=True)
    expired = threading.Event()

    def _kill():
        expired.set()
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    timer = threading.Timer(RENDER_DEADLINE_SECONDS, _kill)
    timer.daemon = True
    timer.start()
    try:
        try:
            for buf in render_frames(a.channel, Path(plan["fonts"])):
                p.stdin.write(buf)
            p.stdin.close()
        except BrokenPipeError:
            pass
        rc = p.wait()
    finally:
        timer.cancel()
    if expired.is_set():
        sys.exit(f"ffmpeg killed: the render passed {RENDER_DEADLINE_SECONDS} s")
    if rc != 0:
        sys.exit("ffmpeg failed")
    print(out)
    # CF-0722: the Video Editor closes a video only on the bytes brand.json
    # records, so a new render has to be recorded there to be used.
    recorded = plan.get("clip_sha256")
    if recorded:
        got = channel_data(root).file_sha256(out)
        if got != recorded:
            print(f"the new clip's sha256 is {got}; channels/{a.channel}/brand.json "
                  f"records {recorded} - record the new one (ending.clip_sha256) and "
                  f"in SOURCES.md, or the Video Editor refuses the clip "
                  f"(ending_sha256_mismatch)", file=sys.stderr)


if __name__ == "__main__":
    main()
