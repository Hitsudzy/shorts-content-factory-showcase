"""CF-0673: the one place in this repo that finds the root's
`shared/factrule/scale_support.py` - the module whose `channel_gate(sources)`
holds the channel's text-reading rule (the AI-bot rule of CF-0557/CF-0635)
for every reader of the factory. `source_gate.py` asks it; this repository
keeps no copy of the rule.

    from _scale_support import scale_support
    why = scale_support.channel_gate(sources).refusal(url)

Lookup, in order (as `_channel_data.py` finds `shared/channel_data.py`):

  1. `<factory_root()>/shared/factrule/scale_support.py` (`FACTORY_ROOT` wins);
  2. the nearest ancestor of this file that holds it - a test's
     `FACTORY_ROOT` is a temp tree with `channels/` and nothing else, and it is
     the *data* that comes from there, not the rule.

The module is loaded by path under one `sys.modules` name, so a process holds
one module object. There is no fallback: a root without it is an error at
import - a door that cannot judge an outlet must not look like one that let it
through."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

SHARED_REL = Path("shared") / "factrule" / "scale_support.py"
MODULE_NAME = "factory_scale_support"


def shared_path():
    """Where the root's module is, or None."""
    try:
        path = factory_root() / SHARED_REL
        if path.is_file():
            return path.resolve()
    except RuntimeError:
        pass
    for p in HERE.parents:
        if (p / SHARED_REL).is_file():
            return (p / SHARED_REL).resolve()
    return None


def _load():
    path = shared_path()
    if path is None:
        raise RuntimeError(f"{SHARED_REL} was not found (FACTORY_ROOT or an ancestor of "
                           f"{HERE}): the channel's text-reading rule lives in the "
                           f"factory root and this repository keeps no copy of it "
                           f"(CF-0673)")
    held = sys.modules.get(MODULE_NAME)
    if held is not None and Path(getattr(held, "__file__", "")).resolve() == path:
        return held
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    module.ORIGIN = str(path)
    return module


scale_support = _load()
