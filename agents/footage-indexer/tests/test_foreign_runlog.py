"""CF-0267 (regression 2026-10-03): this repo's scripts import cleanly in a
process whose `_runlog` is another agent's.

Every agent repo has a `scripts/_runlog.py`. video-editor's tests put their
own `scripts/` first on sys.path and then import `caption_cache` /
`usability_probe` from here, so `from _runlog import X` resolves to the Video
Editor's `_runlog`. Only `runlog` (and `factory_root`) is common to all of
them; `sibling_scripts` was not, and `test_card_band_threshold.py` died with
`ImportError: cannot import name 'sibling_scripts' from '_runlog'`. The
resolver now lives in `_fi_paths.py`, a name no other repo uses.

Two checks:
  * static - no script here takes anything but `runlog` from `_runlog`, and no
    script reads an attribute off `_runlog` that a foreign one lacks;
  * live - in a subprocess, the Video Editor's `_runlog` is imported first,
    then the modules other repos import from here are imported.
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import _fi_paths  # noqa: E402

# What every agent's `_runlog` defines (checked 2026-10-03 across
# video-editor, trend-hunter, content-researcher).
COMMON = {"runlog", "factory_root"}
# Attributes usability_probe adds to a foreign `_runlog` itself (CF-0406 shim).
SHIMMED = {"video_script", "video_attempt"}

# The modules other repos import from this scripts/ directory (grep of
# agents/*/ on 2026-10-03): video-editor tests (caption_cache,
# usability_probe, code_reach), video-editor shot_score (shot_usability,
# sharpness), trend-hunter pool_screen (pool_depth), trend-hunter tests
# (pool_work_check, ingest_batch), content-researcher (ingest_batch,
# pool_layout's scripts). Plus index_footage, which most of them pull in.
CROSS_IMPORTED = ("caption_cache", "caption_probe", "usability_probe", "code_reach",
                  "shot_usability", "sharpness", "pool_depth", "pool_work_check",
                  "ingest_batch", "source_sieve", "index_footage")


def test_no_script_takes_a_private_name_from_runlog():
    bad = []
    for f in sorted(SCRIPTS.glob("*.py")):
        if f.name == "_runlog.py":
            continue
        tree = ast.parse(f.read_text(), str(f))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "_runlog":
                for a in node.names:
                    if a.name != "runlog":
                        bad.append(f"{f.name}:{node.lineno} from _runlog import {a.name}")
            elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                  and node.value.id == "_runlog"
                  and node.attr not in COMMON | SHIMMED):
                bad.append(f"{f.name}:{node.lineno} _runlog.{node.attr}")
    assert not bad, ("another repo's `_runlog` may be the one in sys.modules; "
                     "take these from `_fi_paths` instead: " + "; ".join(bad))


def test_scripts_import_under_the_video_editors_runlog():
    editor = _fi_paths.sibling_scripts("video-editor")
    assert (editor / "_runlog.py").is_file(), editor
    py = _fi_paths.venv_bin("python3")
    py = str(py) if py.exists() else sys.executable
    present = [m for m in CROSS_IMPORTED if (SCRIPTS / f"{m}.py").is_file()]
    prog = "\n".join([
        "import sys",
        f"sys.path.insert(0, {str(editor)!r})",
        "import _runlog",
        f"assert _runlog.__file__.startswith({str(editor)!r}), _runlog.__file__",
        f"sys.path.insert(0, {str(SCRIPTS)!r})",
        *[f"import {m}" for m in present],
        f"assert sys.modules['_runlog'].__file__.startswith({str(editor)!r})",
        "print('ok')",
    ])
    env = {k: v for k, v in os.environ.items() if k not in ("RUNLOG_BATCH", "RUNLOG_PARENT")}
    out = subprocess.run([py, "-c", prog], capture_output=True, text=True,
                         env=env, timeout=240, cwd=str(HERE.parent))
    assert out.returncode == 0 and out.stdout.strip().endswith("ok"), out.stderr[-1500:]


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:  # a crash is a failure, not a skip
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
