#!/usr/bin/env python3
"""CF-0722: the ending clip is checked against the bytes the channel records
(`channels/<id>/brand.json` -> `ending.clip_sha256`, read through
`scripts/_channel_data.py` from the root's `shared/channel_data.py`).

Pinned:

  * a clip that is not the recorded bytes is refused by name
    (`ending_sha256_mismatch`) before it is probed, and a broken section is
    `ending_invalid`;
  * a channel without brand.json or without the section is not checked - the
    old behaviour;
  * compatibility: for the three channels of the factory (example-film,
    example-science, example-tech) the end-card record `plan_end_card` writes
    into the plan is the same, byte for byte, with the section read (the new
    path) and with it hidden (the old path). That case reads the root's own
    tracked channel files (configs, brand.json, ending.mp4 - ffprobe only, no
    render); every other case runs on a temp tree with the probe stubbed.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import end_card  # noqa: E402
import meme_layer  # noqa: E402
from _channel_data import channel_data  # noqa: E402

REAL_ROOT = next((c for c in [AGENT_ROOT, *AGENT_ROOT.parents]
                  if (c / "channels").is_dir() and (c / "tests").is_dir()), None)
CHANNELS = ("example-film", "example-science", "example-tech")
PROBE = {"seconds": 5.0, "width": 1080, "height": 1920, "fps": 30.0, "has_audio": True}


def plan_for(narration=49.83):
    return {"style": "stills",
            "output": {"width": 1080, "height": 1920, "fps": 30},
            "audio": {"src": "/tmp/voice.wav", "duration": narration},
            "words": [{"word": "w", "start": 0.0, "end": round(narration - 0.4, 3)}],
            "blocks": [{"start": 0.0, "end": narration,
                        "asset": {"kind": "still", "src": "f0.png"}}],
            "duration": {"target": [35, 60], "actual": narration, "deviation": 0},
            "rhythm": {}, "degraded_blocks": [], "notes": []}


def tree(tmp, clip=b"the channel's clip", brand=None):
    """<tmp>/channels/ch-test(.json) with an ending.mp4 of `clip` bytes and,
    when given, a brand.json."""
    root = Path(tmp)
    ch = root / "channels" / "ch-test"
    ch.mkdir(parents=True)
    cfg = {"channel_id": "ch-test", "display_name": "Test Channel",
           "narration_budget": {"target_total_seconds": 55, "end_card_seconds": 3.0,
                                "ending_seconds": 5.0, "words_per_second": 2.75}}
    (root / "channels" / "ch-test.json").write_text(json.dumps(cfg))
    (ch / "ending.mp4").write_bytes(clip)
    if brand is not None:
        (ch / "brand.json").write_text(json.dumps(brand))
    return root, cfg


def section(sha):
    return {"channel_id": "ch-test",
            "ending": {"clip": "channels/ch-test/ending.mp4", "clip_sha256": sha,
                       "render": None}}


class stub_probe:
    def __enter__(self):
        self.saved = end_card.probe_ending
        self.calls = []
        end_card.probe_ending = lambda path: self.calls.append(path) or dict(PROBE)
        return self

    def __exit__(self, *exc):
        end_card.probe_ending = self.saved


class hidden_section:
    """The old path: the root answers as if the channel had no section."""

    def __enter__(self):
        channel_data.ending = lambda channel, root=None: None
        return self

    def __exit__(self, *exc):
        vars(channel_data).pop("ending", None)


def card(root, cfg, plan=None):
    return end_card.plan_end_card(plan or plan_for(), cfg, {}, root=root,
                                  channel=cfg["channel_id"])


def refused(root, cfg):
    try:
        card(root, cfg)
    except end_card.EndCardError as e:
        return e
    raise AssertionError("expected EndCardError")


def test_the_recorded_clip_closes_the_video_as_before():
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = tree(tmp)
        sha = channel_data.file_sha256(root / "channels" / "ch-test" / "ending.mp4")
        (root / "channels" / "ch-test" / "brand.json").write_text(json.dumps(section(sha)))
        with stub_probe():
            new = card(root, cfg)
            with hidden_section():
                old = card(root, cfg)
        assert new["variant"] == end_card.VARIANT_CLIP, new
        assert json.dumps(new, sort_keys=False) == json.dumps(old, sort_keys=False)


def test_a_swapped_clip_is_refused_by_name_before_the_probe():
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = tree(tmp, brand=section("0" * 64))
        with stub_probe() as p:
            e = refused(root, cfg)
        assert e.code == end_card.ENDING_SHA256_MISMATCH == "ending_sha256_mismatch"
        assert str(e).startswith("ending_sha256_mismatch: the ending clip"), str(e)
        assert "0" * 64 in str(e) and "brand.json" in str(e)
        assert p.calls == [], "the swapped clip was probed"


def test_a_broken_section_is_refused_and_no_section_is_not_checked():
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = tree(tmp, brand=section("not-a-sha"))
        with stub_probe():
            e = refused(root, cfg)
        assert e.code == end_card.ENDING_INVALID, str(e)
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = tree(tmp, brand={"channel_id": "ch-test"})
        with stub_probe():
            assert card(root, cfg)["variant"] == end_card.VARIANT_CLIP
    with tempfile.TemporaryDirectory() as tmp:
        root, cfg = tree(tmp)
        with stub_probe():
            assert card(root, cfg)["variant"] == end_card.VARIANT_CLIP
        assert end_card.check_ending_bytes(root / "channels" / "ch-test" / "ending.mp4",
                                           cfg, root) is None


def test_the_three_channels_plan_the_same_ending_with_and_without_the_section():
    """Old path against new path on the factory's own channels: the record
    the plan carries is byte-identical, and the section is really read (the
    recorded sha256 is the clip's)."""
    assert REAL_ROOT is not None
    for channel in CHANNELS:
        cfg = meme_layer.load_channel(channel, REAL_ROOT)
        data = channel_data.ending(channel, REAL_ROOT)
        assert data is not None, channel
        clip, _ = end_card.ending_path(cfg, REAL_ROOT, channel)
        assert end_card.check_ending_bytes(clip, cfg, REAL_ROOT) == data["clip_sha256"]
        plan = plan_for()
        new = card(REAL_ROOT, cfg, plan)
        with hidden_section():
            old = card(REAL_ROOT, cfg, plan)
        assert new["variant"] == end_card.VARIANT_CLIP, (channel, new)
        assert json.dumps(new) == json.dumps(old), (channel, new, old)


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)
