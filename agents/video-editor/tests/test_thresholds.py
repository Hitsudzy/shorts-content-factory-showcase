#!/usr/bin/env python3
"""CF-0024: the constants two gates disagreeing about killed CF-0003.

Not "does the pipeline still produce good video" - just "do the values a
human tuned once still agree with each other". Seconds to run, no render.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
from repo_paths import VENV_PY  # noqa: E402 - CF-0125: resolved against the main checkout


def test_qc_asset_matches_common():
    import common
    import qc_asset
    assert qc_asset.MIN_COVERAGE == common.MIN_COVERAGE, \
        "qc_asset.py's MIN_COVERAGE drifted from common.py (this is exactly CF-0003's bug)"
    assert qc_asset.MIN_SHORT_SIDE == common.MIN_SHORT_SIDE, \
        "qc_asset.py's MIN_SHORT_SIDE drifted from common.py"
    assert qc_asset.MAX_CONTAIN_UPSCALE == common.MAX_CONTAIN_UPSCALE, \
        "qc_asset.py's MAX_CONTAIN_UPSCALE drifted from common.py (CF-0104)"


def test_build_render_plan_matches_common():
    import common
    import build_render_plan
    assert build_render_plan.MIN_COVERAGE == common.MIN_COVERAGE
    assert build_render_plan.MIN_SHORT_SIDE == common.MIN_SHORT_SIDE


def test_render_video_asks_remotion_to_say_what_it_did():
    """CF-0131: render_video.py passed `--log=error`, so a successful render
    wrote nothing at all - every attempt log under <batch>/logs/ read
    `lines=0`, and "why did that render take 29 minutes" could only be
    answered by booking a fresh measurement session.

    Measured on a 60-frame render of work/cf0052-measure/plans/clip-2s.json:
    `error` writes 1 line, `info` writes 82 (bundling percentages, the
    composition/codec/concurrency table, `Rendered n/60` with a running ETA,
    then `Encoded n/60`), `verbose` writes 729. `info` is the level that
    decomposes a render into stages without a line per frame; the log is a
    file on disk (CF-0098) and only quiet.py's tail reaches a terminal, so
    the extra lines cost no context.
    """
    import render_video
    assert render_video.REMOTION_LOG not in ("error", "warn"), (
        f"REMOTION_LOG is {render_video.REMOTION_LOG!r} - at that level Remotion "
        f"prints nothing on a successful render and the attempt log is empty "
        f"again, which is the whole of CF-0131's second half")
    src = (SCRIPTS / "render_video.py").read_text()
    assert "--log=error" not in src, \
        "a literal --log=error is back in the remotion command line"
    assert '--log={args.remotion_log}' in src, \
        "the remotion command line no longer takes its log level from the flag"


def test_resolve_anchors_cli_defaults_reference_common_not_a_literal():
    """resolve_anchors.py's --min-coverage/--min-delivery-height defaults are
    argparse defaults, not an importable module-level constant, so a normal
    equality check can't see them. CF-0003 was exactly this: a hardcoded
    0.40/600 quietly replacing the shared 0.65/720. Parse the source instead
    of importing, and assert the default= argument is a reference to the
    common.py names, not a numeric literal that could silently drift again.

    CF-0104 renamed --min-short-side to --min-delivery-height (the floor now
    checks delivered geometry, not the source's raw short side); the old
    name survives only as a deprecated alias whose default is deliberately
    `None` (a sentinel for "not passed"), not a reference to MIN_SHORT_SIDE,
    so it is checked separately below rather than through the loop above.
    """
    import ast
    tree = ast.parse((SCRIPTS / "resolve_anchors.py").read_text())
    seen = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        if not (node.args and isinstance(node.args[0], ast.Constant)):
            continue
        flag = node.args[0].value
        if flag not in ("--min-coverage", "--min-delivery-height", "--min-short-side"):
            continue
        default = next((kw.value for kw in node.keywords if kw.arg == "default"), None)
        seen[flag] = default

    for flag, expected_name in (("--min-coverage", "MIN_COVERAGE"),
                                 ("--min-delivery-height", "MIN_SHORT_SIDE")):
        assert flag in seen, f"{flag} argument not found in resolve_anchors.py"
        default = seen[flag]
        assert isinstance(default, ast.Name) and default.id == expected_name, (
            f"{flag}'s default in resolve_anchors.py is no longer a reference to "
            f"common.{expected_name} - it's {ast.dump(default)}. This is how CF-0003 "
            f"happened: a hardcoded literal here silently disagrees with common.py.")

    assert "--min-short-side" in seen, \
        "--min-short-side (CF-0104's deprecated alias) is missing from resolve_anchors.py"
    assert isinstance(seen["--min-short-side"], ast.Constant) \
        and seen["--min-short-side"].value is None, (
        "--min-short-side's default should be the None sentinel that marks 'not "
        "passed' - CF-0104's alias only overrides --min-delivery-height when a "
        "caller actually used the old flag")


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
