# Render speed

What a render costs on the factory's machine. The block between the markers is
generated from `work/cf0052-measure/measured.json` by
[`tests/test_render_speed_doc.py`](../tests/test_render_speed_doc.py)
(`python3 tests/test_render_speed_doc.py --write`); edit the measurement, not
the text. The overview is the [README](../README.md).

<!-- CF-0052:begin - generated from work/cf0052-measure/measured.json by tests/test_render_speed_doc.py -->

Rendering cost is set by what a frame is made of, not by how long the video is.
Measured 2026-10-03 on this machine - MacBookPro16,1, 6 physical / 12 logical
cores (Intel), 16 GB, macOS 26.6.2, Remotion 4.0.518 at its default concurrency
of 6 - steady state with a warm bundle, seconds of render per second of
finished video:

| block kind | cost per second of output |
|---|---|
| held picture (`AssetLayer` -> `<Img>`) | 1.4x realtime (1.4-1.5x) with `--gl=angle`, 1.7x without |
| footage (`AssetLayer` -> `<OffthreadVideo>`) | 3.4x realtime (3.3-3.4x) with `--gl=angle`, 3.3x without |
| procedural block (`ProceduralBg`) | 2.3x realtime (2.3-2.3x) with `--gl=angle`, 2.9x without |
| whole-video `typographic` style | 2.6x realtime (2.6-2.6x) with `--gl=angle`, 3.2x without |

Add about 7s per render for the bundle, the browser and the single encoding
pass, and about 21s on top of that for the first render of a session, which
bundles from scratch (2026-09-07, CF-0052: same 8s still plan: 60.5s as the
first render of the session, 37.5-40.3s on the three that followed (not re-
measured by CF-0134 - its first render reused a warm bundle)).

A 70s video of the shape this factory actually produces - about half footage,
half procedural - therefore costs about 3m26s with the knob below and 3m44s
without it, and one that is procedural throughout about 2m48s. The 72.725s
`raygun-sneak-peek` plan (34.1s of clip blocks + 35.6s of procedural blocks + a
3s end card) rendered in 3m14s with the knob and 3m43s without, against 206s
and 221s these per-kind costs predict for it.

The table was taken cold - CPU_Speed_Limit 100 throughout - and heat moves it
more than anything in it. This machine drops to CPU_Speed_Limit 37% (pmset -g
therm after ~2.5h of back-to-back rendering, 2026-09-07), and the same 8s still
plan takes 37.5-40.3s on a cool machine and 55.1s throttled - about 1.4x. A
factory that renders back to back lives in the throttled state, so the high end
of each span is the number to plan capacity with, not the low one.

`render_video.py` passes `--gl=angle` for `typographic` plans, and any other
plan whose block seconds times each kind's measured saving sum to more than
zero - against footage alone that is a procedural share of about 15%. Chrome's
ANGLE backend rasterises on the GPU, which makes procedural frames 1.23x, the
typographic style 1.25x and held pictures 1.21x faster; footage measured about
3% slower (3.4x against 3.3x per second of output), inside the software runs'
own 3.1-3.4x spread. A plan of footage alone therefore stays on the software
rasteriser. `--gl` on the command line overrides the choice either way.
Concurrency was measured and left alone: 12 workers instead of 6 bought 1.9%.

These numbers are not portable. This is one Intel Mac that is also somebody's
desktop: the desktop holds ~1.5-2 cores at rest (DisplayLink, WindowServer,
Claude, Spotlight/media analysis), and every number here was taken with that
load and nothing else running.

<!-- CF-0052:end -->

Since CF-0711 the `--gl` choice above is made only where the factory may use the GPU at
all: on an Intel Mac (`FACTORY_GPU` unset, or `off`) every plan renders on the
software rasteriser - the Intel UHD 630 here hung under the factory's Vision
work on 12.10 and took the laptop down, so the 1.2x above is left on the table.
