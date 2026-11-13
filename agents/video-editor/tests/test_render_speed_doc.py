#!/usr/bin/env python3
"""CF-0052: the documented render-speed figure cannot drift from the measurement.

The number in the README was `~2x realtime` from 2026-08-30 and was never
true: every instrumented render since has come in five to twelve times worse,
and it is the only public capacity figure the project has (CF-0051 plans
throughput on it). The fix is not a better sentence - it is that the sentence
is *generated*. `work/cf0052-measure/measured.json` holds what was measured;
this file renders the block from it and asserts `docs/render-speed.md` says
exactly that, so editing one without the other fails the suite. (CF-0491: the
block lived in the README until the README became an overview; the README
links to the doc, and the old claim is kept out of both.)

    python3 tests/test_render_speed_doc.py --write   # regenerate the block

The harness that produced measured.json lives beside it in
`work/cf0052-measure/` (mkassets.sh, mkplan.py, measure.py, results.jsonl).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
README = REPO / "README.md"
DOC = REPO / "docs" / "render-speed.md"
MEASURED = REPO / "work" / "cf0052-measure" / "measured.json"
sys.path.insert(0, str(SCRIPTS))

BEGIN = "<!-- CF-0052:begin - generated from work/cf0052-measure/measured.json by tests/test_render_speed_doc.py -->"
END = "<!-- CF-0052:end -->"


def measured():
    return json.load(open(MEASURED))


def mmss(seconds):
    return "%dm%02ds" % (int(seconds) // 60, int(seconds) % 60)


def block(data):
    """The render-speed block of docs/render-speed.md, as the measurement dictates it."""
    m = data["machine"]
    kinds = data["per_block_kind"]
    angle = data["per_block_kind_angle"]
    knob = data["gl_knob"]
    ref = data["reference_render"]
    th = data["thermal"]

    def span(row):
        lo, hi = row["x_span"]
        return f"{row['x_realtime']}x realtime ({lo}-{hi}x)"

    def line(label, key, with_angle):
        if not with_angle:
            return f"| {label} | {span(kinds[key])} |"
        return (f"| {label} | {span(angle[key])} with `{knob['flag']}`, "
                f"{kinds[key]['x_realtime']}x without |")

    rows = "\n".join([
        line("held picture (`AssetLayer` -> `<Img>`)", "still", True),
        line("footage (`AssetLayer` -> `<OffthreadVideo>`)", "clip", True),
        line("procedural block (`ProceduralBg`)", "procedural", True),
        line("whole-video `typographic` style", "typographic", True),
    ])
    fixed = data["fixed_overhead_s"]

    paragraphs = [
        "Rendering cost is set by what a frame is made of, not by how long the "
        f"video is. Measured {data['measured_on']} on this machine - "
        f"{m['model']}, {m['cpu']}, {m['ram_gb']} GB, {m['os']}, Remotion "
        f"{m['remotion']} at its default concurrency of {m['concurrency']} - "
        "steady state with a warm bundle, seconds of render per second of "
        "finished video:",

        "| block kind | cost per second of output |\n|---|---|\n" + rows,

        f"Add about {fixed}s per render for the bundle, the browser and the "
        "single encoding pass, and about "
        f"{data['cold_start_extra_s']}s on top of that for the first render of "
        "a session, which bundles from scratch "
        f"({data['cold_start_evidence']}).",

        "A 70s video of the shape this factory actually produces - about half "
        "footage, half procedural - therefore costs about "
        f"{mmss(35 * angle['clip']['x_realtime'] + 35 * angle['procedural']['x_realtime'] + fixed)} "
        "with the knob below and "
        f"{mmss(35 * kinds['clip']['x_realtime'] + 35 * kinds['procedural']['x_realtime'] + fixed)} "
        "without it, and one that is procedural throughout about "
        f"{mmss(70 * angle['procedural']['x_realtime'] + fixed)}. "
        f"The {ref['composition_seconds']}s `{ref['video']}` plan "
        f"({ref['shape']}) rendered in {mmss(ref['wall_s'])} with the knob and "
        f"{mmss(ref['wall_s_software'])} without, against "
        f"{ref['model_says_s']}s and {ref['model_says_s_software']}s these "
        "per-kind costs predict for it.",

        "The table was taken cold - CPU_Speed_Limit 100 throughout - and "
        "heat moves it more than anything in it. This machine drops to "
        f"CPU_Speed_Limit {th['cpu_speed_limit_pct']}% "
        f"({th['observed']}, {th['observed_on']}), and {th['effect']}. "
        f"{th['meaning'].capitalize()}.",

        f"`render_video.py` passes `{knob['flag']}` for {knob['applied_to']}. "
        "Chrome's ANGLE backend rasterises on the GPU, which makes procedural "
        f"frames {knob['gain_procedural']}x, the typographic style "
        f"{knob['gain_typographic']}x and held pictures {knob['gain_still']}x "
        f"faster; footage measured {knob['cost_clip']}. A plan of footage "
        "alone therefore stays on the software rasteriser. `--gl` on the "
        "command line overrides the choice either way. Concurrency was "
        f"measured and left alone: 12 workers instead of {m['concurrency']} "
        "bought 1.9%.",

        "These numbers are not portable. This is one Intel Mac that is also "
        "somebody's desktop: "
        f"{m['idle_note'].split(' - ', 1)[1]}.",
    ]
    filled = [par if par.startswith("|") else textwrap.fill(par, 79)
              for par in paragraphs]
    return "\n\n".join([BEGIN] + filled + [END])


def doc_block():
    text = DOC.read_text()
    assert BEGIN in text, f"docs/render-speed.md has lost the CF-0052 marker {BEGIN}"
    assert END in text, f"docs/render-speed.md has lost the CF-0052 marker {END}"
    start = text.index(BEGIN)
    end = text.index(END) + len(END)
    return text[start:end]


def test_doc_matches_measured_json():
    want = block(measured())
    got = doc_block()
    assert got == want, (
        "docs/render-speed.md's render-speed block no longer matches "
        "work/cf0052-measure/measured.json.\n"
        "Regenerate it with `python3 tests/test_render_speed_doc.py --write`, "
        "or - if the doc is right and the JSON is stale - re-measure with "
        "work/cf0052-measure/measure.py.\n--- docs/render-speed.md has ---\n" + got +
        "\n--- measured.json says ---\n" + want)


def test_the_old_2x_claim_is_gone():
    """The exact sentence CF-0052 was filed against, in either spelling."""
    for path in (README, DOC):
        text = path.read_text()
        for stale in ("2x realtime", "2× realtime", "90s for a 45s video"):
            assert stale not in text, (
                f"{path.name} still carries the unmeasured claim {stale!r} - that is "
                "the defect CF-0052 closed")


def test_measured_json_is_self_consistent():
    """x_realtime is the per-frame cost at 30 fps, not a separate opinion."""
    data = measured()
    for table in ("per_block_kind", "per_block_kind_angle"):
        for kind, row in data[table].items():
            want = round(row["s_per_frame"] * 30, 1)
            assert abs(row["x_realtime"] - want) <= 0.15, (
                f"{table}.{kind}: x_realtime {row['x_realtime']} does not follow "
                f"from s_per_frame {row['s_per_frame']} at 30 fps ({want})")


def test_render_video_pins_the_measured_gl_knob():
    """The knob the doc documents is the knob the renderer applies, with
    the per-kind savings that were measured (CF-0134)."""
    import render_video
    knob = measured()["gl_knob"]
    assert knob["flag"] == f"--gl={render_video.GL_FOR_PROCEDURAL}", (
        "measured.json's gl_knob.flag drifted from render_video's constant")
    for kind, saving in render_video.GL_SAVING_S_PER_S.items():
        assert knob["saving_s_per_s"].get(kind) == saving, (
            f"render_video.GL_SAVING_S_PER_S[{kind!r}] = {saving} but "
            f"measured.json says {knob['saving_s_per_s'].get(kind)} - change "
            "both in the same commit or the knob runs on a stale measurement")


def _block(kind, seconds, start=0.0):
    return {"start": start, "end": start + seconds, "asset": {"kind": kind}}


def test_gl_choice_follows_the_plan_shape():
    """CF-0134: angle when the plan's seconds of each kind, times that kind's
    measured saving, come out positive. On footage the flag measured ~3%
    slower, on procedural and held frames ~17-18% faster, so footage alone
    stays on software and a mix tips over at roughly 15% procedural."""
    import render_video
    clip, proc, still = "clip", "procedural", "still"
    typographic = {"style": "typographic", "blocks": [_block(clip, 10)]}
    raygun = {"style": "motion", "blocks": [_block(clip, 34.1), _block(proc, 35.6)]}
    footage = {"style": "motion", "blocks": [_block(clip, 60)]}
    one_tenth = {"style": "motion", "blocks": [_block(clip, 90), _block(proc, 10)]}
    one_fifth = {"style": "motion", "blocks": [_block(clip, 80), _block(proc, 20)]}
    held = {"style": "motion", "blocks": [_block(clip, 30), _block(still, 30)]}
    assert render_video.gl_for(typographic) == "angle"
    assert render_video.gl_for(raygun) == "angle"
    assert render_video.gl_for(footage) is None
    assert render_video.gl_for(one_tenth) is None
    assert render_video.gl_for(one_fifth) == "angle"
    assert render_video.gl_for(held) == "angle"
    assert render_video.gl_for({"blocks": []}) is None


def test_gl_choice_tolerates_unmeasured_and_malformed_blocks():
    """A kind nobody measured counts zero, a block without times counts zero -
    neither may tip a footage plan or crash the render."""
    import render_video
    unmeasured = {"blocks": [_block("meme", 30), _block("card", 30)]}
    untimed = {"blocks": [{"asset": {"kind": "procedural"}},
                          _block("clip", 5)]}
    assert render_video.gl_for(unmeasured) is None
    assert render_video.gl_for(untimed) is None
    assert render_video.gl_saving({"blocks": [{"start": "x", "end": 3,
                                               "asset": None}]}) == 0.0


if __name__ == "__main__":
    if "--write" in sys.argv:
        text = DOC.read_text()
        start, end = text.index(BEGIN), text.index(END) + len(END)
        DOC.write_text(text[:start] + block(measured()) + text[end:])
        print(f"rewrote the CF-0052 block in {DOC}")
        sys.exit(0)

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
