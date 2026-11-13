"""CF-0535: the 9:16 face window went to the band behind the host.

`weekend-night-live` of `example-film/2026-10-05T0701Z`, block 5 (23.20-30.13
s, `KTe9OatvQas:5`, 1920x736): at the probe frame (0.5 s) the host is turned
away from the camera, so Vision's only faces are two band members at x
1364-1635, framed together (focus x 0.781) and held for seven seconds. From
~2 s the host faces the camera - the largest face, frame centre - but nothing
looked past 0.5 s.

The face boxes below are that clip's real Vision output (smart_crop._find_roi
on frames at 0.5 / 2 / 4 / 6 s), pinned; the CLIP numbers are the injected
`score` stand-in for the measured ones (band window 0.210, host window 0.233,
whole frame 0.246, 4-frame means). No Vision, no CLIP, no ffmpeg here.

No pytest - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import face_window  # noqa: E402
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import smart_crop  # noqa: E402

SIZE = (1920, 736)
BAND = [(1537, 193, 98, 98), (1364, 210, 79, 79)]          # 0.5 s
BAND_2S = [(1537, 194, 95, 95), (1367, 209, 77, 77), (330, 323, 81, 81)]
HOST_4S = [(862, 156, 179, 179), (1530, 196, 95, 95), (1372, 206, 77, 77),
           (297, 254, 89, 89)]
INTENT = ("The woman in the red dress stands on stage beside another woman in a "
          "light plaid or check outfit, both facing the audience. (shot 5, "
          "score 0.269)")


def _info(parts, size=SIZE):
    """smart_crop.analyse()'s framing of a frame with these faces, without
    Vision: the same window_face / crop_for_aspect rules."""
    x0 = min(p[0] for p in parts)
    y0 = min(p[1] for p in parts)
    x1 = max(p[0] + p[2] for p in parts)
    y1 = max(p[1] + p[3] for p in parts)
    roi, single = (x0, y0, x1 - x0, y1 - y0), len(parts) == 1
    chosen = smart_crop.window_face(parts, size, 9, 16)
    if chosen is not None:
        roi, single = chosen, True
    rect, _c, zoom = smart_crop.crop_for_aspect(roi, size, 9, 16, single)
    return {"source_size": {"width": size[0], "height": size[1]},
            "roi_source": "faces", "roi": smart_crop.roi_dict(roi),
            "roi_parts": [smart_crop.roi_dict(p) for p in parts] if len(parts) > 1 else None,
            "zoom": zoom, "roi_coverage": 1.0}


WNL_FRAMES = [(0.5, "f0", _info(BAND)), (2.079, "f1", _info(BAND_2S)),
              (4.158, "f2", _info(HOST_4S)), (6.237, "f3", _info(HOST_4S))]


def _score(band, host, full):
    def score(frames, windows, text):
        assert "(shot" not in text, text
        out = []
        for w in windows:
            out.append(band if w[0] > 1000 else host)
        return out + [full]
    return score


def test_the_probe_frame_alone_frames_the_band():
    """The defect as it was: the probe frame's own framing is the band."""
    fx, _fy = smart_crop.focus_point(WNL_FRAMES[0][2])
    assert abs(fx - 0.781) < 0.002, fx


def test_span_offsets_cover_the_shown_span():
    assert face_window.span_offsets(0, 6.93, 7.43, 0.5) == [0.5, 2.079, 4.158, 6.237]
    # a short block: points closer than MIN_GAP_SECONDS collapse into one
    got = face_window.span_offsets(0, 1.0, 7.43, 0.5)
    assert got == [0.5, 0.9], got
    # a stretched clip shows no more of itself than it has
    got = face_window.span_offsets(0, 10.0, 3.0, 0.5)
    assert max(got) <= 2.95, got
    # the asset's own start shifts every point
    assert face_window.span_offsets(2.0, 6.0, 20.0, 0.5)[0] == 2.5


def test_distinct_windows_only():
    cands = face_window.candidates(WNL_FRAMES, 9, 16)
    assert [c["t"] for c in cands] == [0.5, 4.158], [c["t"] for c in cands]


def test_wnl_block5_moves_to_the_host_by_intent():
    rec = face_window.reframe(WNL_FRAMES, INTENT, 9, 16,
                              score=_score(0.2099, 0.233, 0.2461))
    assert rec["moved"] and rec["by"] == "intent", rec
    fx, _ = smart_crop.focus_point(rec["info"])
    assert 0.45 < fx < 0.55, fx
    assert rec["verdict"] == "ok" and abs(rec["gap"] - 0.0131) < 1e-4, rec


def test_without_clip_the_largest_face_over_the_span_decides():
    rec = face_window.reframe(WNL_FRAMES, INTENT, 9, 16,
                              score=lambda *a: None)
    assert rec["moved"] and rec["by"] == "face", rec
    assert rec["verdict"] == "ok" and rec["gap"] is None


def test_clip_near_tie_falls_to_the_face_rule():
    rec = face_window.reframe(WNL_FRAMES, INTENT, 9, 16,
                              score=_score(0.226, 0.229, 0.24))
    assert rec["by"] == "face" and rec["moved"], rec


def test_clip_lead_for_the_probe_keeps_it():
    """The intent says the band: the window stays where it was."""
    rec = face_window.reframe(WNL_FRAMES, INTENT, 9, 16,
                              score=_score(0.26, 0.22, 0.26))
    assert not rec["moved"] and rec["by"] == "intent", rec


def test_one_window_over_the_span_does_not_move():
    frames = [(0.5, "a", _info(HOST_4S)), (2.0, "b", _info(HOST_4S))]
    rec = face_window.reframe(frames, INTENT, 9, 16, score=_score(0.2, 0.25, 0.26))
    assert not rec["moved"] and rec["by"] == "probe" and len(rec["candidates"]) == 1


def test_near_equal_faces_stay_on_the_probe():
    """Two people of about one size in turn: no CLIP lead, faces within the
    tie ratio - the probe's framing is kept, nothing moves on noise."""
    left, right = (300, 200, 100, 100), (1500, 200, 98, 98)
    frames = [(0.5, "a", _info([right])), (3.0, "b", _info([left]))]
    rec = face_window.reframe(frames, INTENT, 9, 16, score=lambda *a: None)
    assert len(rec["candidates"]) == 2 and not rec["moved"], rec


def test_window_that_loses_the_intent_warns_without_price():
    """The check: the chosen window scores WARN_GAP or more below the whole
    frame - recorded as warn, mode warn, no price (CF-0320)."""
    frames = [(0.5, "a", _info(BAND))]
    rec = face_window.reframe(frames, INTENT, 9, 16, score=_score(0.21, 0.23, 0.2461))
    assert rec["verdict"] == "warn" and rec["mode"] == "warn", rec
    assert face_window.PROPOSED["price"] is None
    lines = face_window.describe(5, rec)
    assert any(face_window.RULE in ln for ln in lines), lines


def test_no_faces_on_the_probe_is_not_looked_at():
    sal = dict(_info(BAND), roi_source="saliency")
    assert face_window.reframe([(0.5, "a", sal), (2.0, "b", _info(HOST_4S))],
                               INTENT, 9, 16, score=lambda *a: None) is None


def test_intent_text_drops_the_resolver_tail():
    assert face_window.intent_text(INTENT).endswith("audience."), face_window.intent_text(INTENT)
    assert face_window.intent_text(None) == ""


def test_planner_reframes_the_asset_and_cleans_its_frames():
    """build_render_plan.reframe_faces(): the chosen window replaces the
    probe's focus in the asset, the record and notes are written, and the
    extra frames it lifted are gone."""
    import build_render_plan as brp
    tmp = tmp_root("cf0535-")
    probe = tmp / "_probe_5.png"
    probe.write_bytes(b"x")
    later = {2.079: _info(BAND_2S), 4.158: _info(HOST_4S), 6.237: _info(HOST_4S)}
    lifted = []

    def grab(source, offsets, dests, seconds=None):
        for t, dest in zip(offsets, dests):
            Path(dest).write_bytes(b"x")
            lifted.append((dest, t))
        return list(dests)

    def analyse(path, aspect):
        t = dict((d, tt) for d, tt in lifted)[path]
        return later[t]

    info = _info(BAND)
    asset = dict(brp.framing(info), fit="cover")
    notes = []
    rec = brp.reframe_faces(asset, info, probe, "clip.mp4", 0, 6.93, 7.43,
                            INTENT, (1080, 1920), 5, notes, grab=grab,
                            analyse=analyse, score=_score(0.2099, 0.233, 0.2461))
    assert rec["moved"] and "info" not in rec
    assert 0.45 < asset["focus"]["x"] < 0.55 and asset["fit"] == "cover", asset
    assert asset[face_window.FIELD]["by"] == "intent"
    assert any("face window moved" in n for n in notes), notes
    assert all(not Path(d).exists() for d, _t in lifted), lifted
    assert probe.exists()


def test_planner_leaves_a_saliency_clip_alone():
    import build_render_plan as brp
    info = dict(_info(BAND), roi_source="saliency")
    asset = dict(brp.framing(info), fit="cover")
    before = dict(asset)

    def boom(*a, **k):
        raise AssertionError("no frame is lifted for a saliency clip")

    assert brp.reframe_faces(asset, info, "p.png", "c.mp4", 0, 5, 6, INTENT,
                             (1080, 1920), 1, [], grab=boom, analyse=boom) is None
    assert asset == before


def test_one_window_is_checked_on_the_probe_frame_only():
    seen = []

    def score(frames, windows, text):
        seen.append(len(frames))
        return [0.25] * len(windows) + [0.26]
    frames = [(0.5, "a", _info(HOST_4S)), (2.0, "b", _info(HOST_4S))]
    face_window.reframe(frames, INTENT, 9, 16, score=score)
    assert seen == [1], seen
    face_window.reframe(WNL_FRAMES, INTENT, 9, 16, score=score)
    assert seen == [1, 4], seen


def test_grab_frames_lifts_every_offset_in_one_pass():
    import subprocess
    import build_render_plan as brp
    tmp = tmp_root("cf0535-")
    src = tmp / "c.mp4"
    subprocess.run([brp.FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=320x180:rate=10:duration=3", str(src)],
                   check=True, timeout=60)
    dests = [str(tmp / "a.png"), str(tmp / "b.png")]
    assert brp.grab_frames(str(src), [1.0, 2.5], dests, seconds=3.0) == dests
    assert brp.grab_frames(str(tmp / "missing.mp4"), [1.0], [str(tmp / "x.png")]) == []


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
