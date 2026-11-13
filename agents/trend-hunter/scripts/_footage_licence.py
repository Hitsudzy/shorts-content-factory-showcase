"""CF-0662: the one place in this repo that finds the factory's common
licence rule (`<root>/shared/footage_licence.py`, CF-0564) and hands it to
the scripts:

    from _footage_licence import footage_licence

    verdict = footage_licence.licence_of("cc by", doc["licences"])
    entry = footage_licence.origin(doc, "esa")

The rule reads a piece of footage's licence against a channel's `licences`
lists (`channels/<id>/footage-origin.json`); the lists are the channel's, the
rule is the factory's, and this repo keeps a copy of neither. Lookup is the
one `_channel_data.py` uses: `<factory_root()>/shared/footage_licence.py`
first, then the nearest ancestor of this file that holds it (a test's
`FACTORY_ROOT` is a temp tree with `channels/` and nothing else). Loaded by
path, so nothing of the root goes onto `sys.path`.

No fallback rule. When no rule can be found, `footage_licence` is None and the
caller says so: a channel that lists licences is judged by the rule or its
candidates are refused with the reason (`footage_candidates.licence_block`);
a channel that lists none (ExampleFilm) needs no rule at all.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

LIB_REL = Path("shared") / "footage_licence.py"


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
    spec = importlib.util.spec_from_file_location("footage_licence_for_trend_hunter", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


footage_licence = _load()
