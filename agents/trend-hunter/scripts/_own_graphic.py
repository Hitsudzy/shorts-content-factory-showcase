"""CF-0689: the one place in this repo that finds the factory's own-graphic
rule (`<root>/shared/own_graphic.py`) and hands it to the scripts:

    from _own_graphic import own_graphic

    own_graphic.parse_numbers("63.8% on SWE-bench Verified")   # [("63.8", None)]
    own_graphic.parse_dates("released on March 25, 2025")      # [(2025, 3, 25)]

The rule decides what a graphic's number and date are when the Content
Researcher holds a graphic's value to its quote; the refusal floor
(`footage_candidates.graphic_footing`) reads a topic's support text with the
same parser, so "a quotable figure" here is the same thing the writer's
check will later look for. Lookup is the one `_footage_licence.py` uses:
`<factory_root()>/shared/own_graphic.py` first, then the nearest ancestor of
this file that holds it (a test's `FACTORY_ROOT` is a temp tree with
`channels/` and nothing else). Loaded by path, so nothing of the root goes
onto `sys.path` (the rule loads `shared/factrule/claims.py` beside itself by
path, too).

No fallback parser. When no rule can be found, `own_graphic` is None and the
caller says so: a topic on an `own_graphic` channel then gets no pass on its
quotable facts and is held to the footage floor alone.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

LIB_REL = Path("shared") / "own_graphic.py"


def library_path():
    """Where the rule is, or None."""
    try:
        path = factory_root() / LIB_REL
        if path.is_file():
            return path
    except RuntimeError:
        pass
    for p in HERE.parents:
        if (p / LIB_REL).is_file():
            return p / LIB_REL
    return None


def _load():
    path = library_path()
    if path is None:
        return None
    spec = importlib.util.spec_from_file_location("own_graphic_for_trend_hunter", path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:   # a rule that cannot load is a rule not found - said by the caller
        return None
    return mod


own_graphic = _load()
