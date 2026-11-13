#!/usr/bin/env python3
"""CF-0572: the on-screen theme is the channel's, carried in the plan.

Locked here:

  * `channel_theme.plan_theme()` - a channel id gives the root's
    `channel_data.theme(channel, root)` without `picked`/`note`; a `.json`
    path gives the loaded config's theme, checked by the same rule; a named
    channel without a theme (or with a broken one) is a refusal; no channel is
    `None` and a note - never ExampleFilm's palette as a default;
  * the same through the real `build_render_plan.py`: `plan.theme` is the
    channel's, a channel without one gets no plan, a plan without `--channel`
    carries `theme: null` and says why;
  * example-film: the theme the plan carries is the root's `REEL_FROZEN`
    (the root's tests/test_channel_theme.py, read as a literal - one copy).

Stand-in roots and configs in temporary directories only - no live channel
file, no network (docs/test-hygiene.md at the factory root).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _stand_in_theme import STAND_IN_THEME, stand_in_theme  # noqa: E402
import ast
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402

import channel_theme  # noqa: E402
import test_channel_watermark as wm  # noqa: E402 - the planner run on a stand-in channel


def reel_frozen():
    """`REEL_FROZEN` of the factory root's tests/test_channel_theme.py - the
    values the Video Editor drew for example-film at 3732fb7 - read as a
    literal (the file is not imported: it is the root's test, not a module)."""
    path = Path(repo_paths.factory_root()) / "tests" / "test_channel_theme.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "REEL_FROZEN" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"no REEL_FROZEN in {path}")


REEL_FROZEN = reel_frozen()


def _root(tmp, channels):
    """A stand-in factory root with `channels/<id>.json` for each config."""
    root = Path(tmp) / "factory"
    (root / "channels").mkdir(parents=True)
    for cid, cfg in channels.items():
        (root / "channels" / f"{cid}.json").write_text(json.dumps({"channel_id": cid, **cfg}))
    return root


def _refused(fn):
    try:
        fn()
    except channel_theme.ThemeError as exc:
        return str(exc)
    raise AssertionError("no refusal")


# --------------------------------------------------------------------------
# the reading
# --------------------------------------------------------------------------

def test_a_channel_id_gives_its_theme_without_the_bookkeeping():
    with tempfile.TemporaryDirectory() as tmp:
        root = _root(tmp, {"ch-a": {"theme": {**stand_in_theme(), "picked": ["muted"],
                                               "note": "why"}}})
        theme, note = channel_theme.plan_theme("ch-a", None, root)
        assert theme == STAND_IN_THEME and note is None, theme


def test_a_channel_path_gives_the_loaded_configs_theme():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = {"channel_id": "x", "theme": {**stand_in_theme(), "note": "n"}}
        theme, _ = channel_theme.plan_theme(str(Path(tmp) / "x.json"), cfg, tmp)
        assert theme == STAND_IN_THEME


def test_a_named_channel_without_a_theme_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        root = _root(tmp, {"bare": {"display_name": "Bare"}})
        msg = _refused(lambda: channel_theme.plan_theme("bare", None, root))
        assert "theme" in msg and "bare" in msg, msg
        msg = _refused(lambda: channel_theme.plan_theme(
            str(Path(tmp) / "bare.json"), {"display_name": "Bare"}, root))
        assert "theme" in msg, msg
        _refused(lambda: channel_theme.plan_theme("nobody", None, root))


def test_a_broken_theme_is_refused_not_patched():
    with tempfile.TemporaryDirectory() as tmp:
        broken = stand_in_theme()
        del broken["badge"]
        root = _root(tmp, {"ch-b": {"theme": broken}})
        msg = _refused(lambda: channel_theme.plan_theme("ch-b", None, root))
        assert "badge" in msg, msg
        low = stand_in_theme()
        low["text"] = low["bg"]
        msg = _refused(lambda: channel_theme.plan_theme(
            str(Path(tmp) / "c.json"), {"theme": low}, root))
        assert "contrast" in msg, msg


def test_no_channel_is_no_theme_and_a_note():
    theme, note = channel_theme.plan_theme(None, None, "/nonexistent")
    assert theme is None and "no --channel" in note, (theme, note)


def test_example_films_plan_theme_is_the_frozen_one():
    """The config as the root keeps it (REEL_FROZEN plus note) gives exactly
    REEL_FROZEN in the plan: no key lost, none added."""
    with tempfile.TemporaryDirectory() as tmp:
        root = _root(tmp, {"example-film": {"theme": {**REEL_FROZEN, "note": "kept"}}})
        theme, _ = channel_theme.plan_theme("example-film", None, root)
        assert theme == REEL_FROZEN, theme


# --------------------------------------------------------------------------
# the planner
# --------------------------------------------------------------------------

def test_build_render_plan_carries_the_channels_theme():
    with tempfile.TemporaryDirectory() as tmp:
        result, out = wm._build_plan(tmp, wm._channel(tmp, display_name="Second Channel"))
        assert result.returncode == 0, result.stderr[-2000:]
        assert json.loads(out.read_text())["theme"] == STAND_IN_THEME


def test_build_render_plan_refuses_a_channel_without_a_theme():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "channels" / "bare.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"channel_id": "bare", "display_name": "Bare"}))
        result, out = wm._build_plan(tmp, path)
        assert result.returncode not in (0, None), result.returncode
        assert "theme" in result.stderr and "CF-0572" in result.stderr, result.stderr[-1500:]
        assert not out.exists(), "a plan was written without the channel's theme"


def test_build_render_plan_without_a_channel_carries_no_theme():
    with tempfile.TemporaryDirectory() as tmp:
        result, out = wm._build_plan(tmp)
        assert result.returncode == 0, result.stderr[-2000:]
        plan = json.loads(out.read_text())
        assert plan["theme"] is None, plan["theme"]
        assert any("theme: no --channel" in n for n in plan["notes"]), plan["notes"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
