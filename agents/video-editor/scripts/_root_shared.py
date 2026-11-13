"""CF-0567: the one place in this repo that finds a module of the factory
root's `shared/` that is not the channel-data contract (that one is
`_channel_data.py`) and loads it by path:

    from _root_shared import root_module

    fl = root_module("footage_licence")   # shared/footage_licence.py
    sp = root_module("source_policy")     # shared/source_policy.py

Why. The rule that decides where the factory may record a page
(`footage_licence.capture_allowed`) and the robots.txt reading of the 08.10
rule (`source_policy.check_url`: Anthropic's agents or `*`) are the root's,
one copy each; the recorder (`capture_tool.py`) and the quote cap
(`proof_quote_cap.py`) ask them, never a copy kept here.

Lookup, as `_channel_data.library_path()`: `<factory_root()>/shared/<name>.py`
first (`FACTORY_ROOT` when it is a real root), else the nearest ancestor of
this file that holds it. The module is loaded under a name of this repo's
own (`<name>_for_video_editor`), so nothing of the root goes onto `sys.path`.
None when no copy can be found - the caller refuses rather than guessing.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

_CACHE = {}


def module_path(name):
    rel = Path("shared") / f"{name}.py"
    try:
        path = factory_root() / rel
        if path.is_file():
            return path
    except RuntimeError:
        pass
    for p in HERE.parents:
        if (p / rel).is_file():
            return p / rel
    return None


def root_module(name):
    """The root's `shared/<name>.py`, loaded once, or None."""
    if name in _CACHE:
        return _CACHE[name]
    path = module_path(name)
    mod = None
    if path is not None:
        spec = importlib.util.spec_from_file_location(f"{name}_for_video_editor", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    _CACHE[name] = mod
    return mod
