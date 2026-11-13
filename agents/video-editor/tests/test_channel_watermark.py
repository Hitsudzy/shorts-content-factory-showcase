#!/usr/bin/env python3
"""CF-0212: the watermark is the channel's, read off its config - never a
name typed into the code.

`build_render_plan.py` carried the mark as `--watermark-text`'s default
("TV SHOW MOMENTS", then "EXAMPLE_FILM"), and nothing told anyone to override
it: a second channel would have gone out with the first one's name in its
corner. Locked here:

  * `channel_watermark.watermark_text()` - a config with `display_name` gives
    that name in capitals (what Watermark.jsx draws: it uppercases), so
    example-film's `ExampleFilm` is the `EXAMPLE_FILM` its plans always carried;
    a named channel without a `display_name` (or without a readable config)
    is a refusal with a line that names the key; no `--channel` is no mark;
  * the same three through the real `build_render_plan.py`: the plan's
    `watermark.text` is the config's name, a channel without one gets no
    plan, a plan without `--channel` has `watermark: null` and says why;
  * the guard: no script of this agent carries a channel's name as an
    argument or parameter default, and `--watermark-text` is gone.

Stand-in configs in a temporary directory only - no live channel file, no
network (docs/test-hygiene.md at the factory root).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME  # noqa: E402 - CF-0572: the planner refuses a channel without a theme
import ast
import json
import re
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402 - CF-0125: paths outside this repo

import channel_watermark  # noqa: E402

RENDER_SRC = AGENT_ROOT / "render" / "src"

# Every name a channel of this factory has gone by, squashed to letters and
# digits: the old one (CF-0180 renamed it) and the three of the Example brand.
CHANNEL_NAMES = ("legacyfilm", "example-film", "example-tech", "example-science")


# --------------------------------------------------------------------------
# the reading
# --------------------------------------------------------------------------

def test_the_text_is_the_display_name_in_capitals():
    text, note = channel_watermark.watermark_text(
        "example-film", {"channel_id": "example-film", "display_name": "ExampleFilm"})
    # The string every example-film plan carried before CF-0212 - the frames,
    # and the procedural background seeded off this text, stay as they were.
    assert text == "EXAMPLE_FILM" and note is None
    text, _ = channel_watermark.watermark_text("ch", {"display_name": "  Second Channel "})
    assert text == "SECOND CHANNEL"


def test_a_named_channel_without_a_display_name_is_refused():
    for cfg in ({"channel_id": "ch"}, {"display_name": ""}, {"display_name": "  "},
                {"display_name": None}, {"display_name": 7}):
        try:
            channel_watermark.watermark_text("ch", cfg)
        except channel_watermark.WatermarkError as e:
            msg = str(e)
            assert "display_name" in msg and "'ch'" in msg and "no default" in msg, msg
        else:
            raise AssertionError(f"{cfg} got a mark")


def test_a_named_channel_without_a_readable_config_is_refused():
    try:
        channel_watermark.watermark_text("ghost", None)
    except channel_watermark.WatermarkError as e:
        assert "'ghost'" in str(e) and "display_name" in str(e), e
    else:
        raise AssertionError("an unreadable channel got a mark")


def test_no_channel_is_no_mark_and_says_so():
    text, note = channel_watermark.watermark_text(None, None)
    assert text is None and "no --channel" in note and "display_name" in note


def test_the_plan_text_is_what_the_frame_draws():
    """The capitals in the plan are only honest while Watermark.jsx draws the
    mark in capitals - pin the two together."""
    src = (RENDER_SRC / "components" / "Watermark.jsx").read_text()
    assert "textTransform: 'uppercase'" in src, (
        "Watermark.jsx no longer uppercases - channel_watermark.py hands the "
        "plan capitals on the strength of it")
    assert "if (!watermark?.text) return null;" in src, (
        "a plan without --channel carries watermark: null and must draw nothing")


# --------------------------------------------------------------------------
# through build_render_plan.py
# --------------------------------------------------------------------------

def _voice_wav(path, seconds=6.0, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            frames += int(2000 if (i // 40) % 2 else -2000).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))


def _channel(tmp, **cfg):
    path = Path(tmp) / "channels" / "ch-wm.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"channel_id": "ch-wm", "theme": STAND_IN_THEME, **cfg}))
    return path


def _build_plan(tmp, channel=None):
    py = Path(repo_paths.VENV_PY3)
    py = str(py) if py.exists() else sys.executable
    tmp = Path(tmp)
    _voice_wav(tmp / "voice.wav")
    words = [{"word": f"w{i}", "start": round(0.5 + i * 0.5, 2),
              "end": round(0.9 + i * 0.5, 2)} for i in range(10)]
    (tmp / "words.json").write_text(json.dumps(words))
    story = {"script_id": "cf-0212", "style": "typographic",
             "blocks": [{"word_range": [0, 4], "intent": "hook", "asset_kind": "text",
                         "asset_query": "", "emphasis_words": []},
                        {"word_range": [5, 9], "intent": "payoff", "asset_kind": "text",
                         "asset_query": "", "emphasis_words": []}]}
    (tmp / "storyboard.json").write_text(json.dumps(story))
    out = tmp / "plan.json"
    cmd = [py, str(SCRIPTS / "build_render_plan.py"), str(tmp / "storyboard.json"),
           str(tmp / "words.json"), str(tmp / "voice.wav"), str(out),
           "--style", "typographic", "--target-duration", "1", "60"]
    if channel:
        cmd += ["--channel", str(channel)]
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp)
    return result, out


def test_build_render_plan_draws_the_channels_own_name():
    with tempfile.TemporaryDirectory() as tmp:
        result, out = _build_plan(tmp, _channel(tmp, display_name="Second Channel"))
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        assert plan["watermark"] == {"text": "SECOND CHANNEL", "position": "top-left"}, \
            plan["watermark"]


def test_build_render_plan_refuses_a_channel_that_cannot_name_its_mark():
    with tempfile.TemporaryDirectory() as tmp:
        result, out = _build_plan(tmp, _channel(tmp))
        assert result.returncode not in (0, None), result.returncode
        assert "display_name" in result.stderr and "watermark" in result.stderr, \
            result.stderr[-1500:]
        assert not out.exists(), "a plan was written with no name for its mark"


def test_build_render_plan_without_a_channel_draws_no_mark():
    with tempfile.TemporaryDirectory() as tmp:
        result, out = _build_plan(tmp)
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        assert plan["watermark"] is None, plan["watermark"]
        assert any("watermark: no --channel" in n for n in plan["notes"]), plan["notes"]


# --------------------------------------------------------------------------
# the guard
# --------------------------------------------------------------------------

def _squash(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _channel_name_defaults(path):
    """(line, what) for every string default in `path` that names a channel:
    `add_argument(..., default="...")` and a function parameter's default."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found = []

    def check(node, what):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            squashed = _squash(node.value)
            if any(name in squashed for name in CHANNEL_NAMES):
                found.append((node.lineno, f"{what} = {node.value!r}"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument":
            for kw in node.keywords:
                if kw.arg == "default":
                    check(kw.value, "add_argument default")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for d in [*node.args.defaults, *node.args.kw_defaults]:
                if d is not None:
                    check(d, f"default of {getattr(node, 'name', 'lambda')}()")
    return found


def test_the_guard_sees_what_it_guards_against():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "bad.py"
        bad.write_text('import argparse\n'
                       'p = argparse.ArgumentParser()\n'
                       'p.add_argument("--watermark-text", default="TV SHOW MOMENTS")\n'
                       'p.add_argument("--channel", default="example-film")\n'
                       'def f(channel="ExampleTech"): pass\n'
                       'def g(name="ok"): pass\n')
        assert sorted(line for line, _ in _channel_name_defaults(bad)) == [3, 4, 5]


def test_no_script_defaults_to_a_channels_name():
    hits = [f"{path.relative_to(AGENT_ROOT)}:{line}: {what}"
            for path in sorted(SCRIPTS.rglob("*.py")) if "__pycache__" not in path.parts
            for line, what in _channel_name_defaults(path)]
    assert not hits, ("a channel's name as a default - a second channel that "
                      "forgets the flag runs as the first one (CF-0212):\n  "
                      + "\n  ".join(hits))


def test_the_watermark_has_one_source():
    src = (SCRIPTS / "build_render_plan.py").read_text()
    assert '"--watermark-text"' not in src and "args.watermark_text" not in src, (
        "build_render_plan.py takes the mark's text from somewhere other than "
        "channel_watermark.py again")
    assert "channel_watermark.watermark_text(" in src
    assert '"text": watermark_text' in src


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
