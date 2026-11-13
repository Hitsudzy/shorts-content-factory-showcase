#!/usr/bin/env python3
"""CF-0551: the Wikipedia client (CF-0184/CF-0237) moved to the factory root.

Its home is `<root>/shared/wikipedia/wikipedia_api.py` - the Trend Hunter reads
Wikipedia too since CF-0551 (the topic's support text), and two clients of
one source would be two etiquettes. This file keeps the import name the
researcher's scripts and tests use (`import wikipedia_api`,
`from wikipedia_api import WikipediaClient`) and hands out the root's module
itself: after the import, `sys.modules["wikipedia_api"]` *is* that module,
registered under its one name (`factory_wikipedia_api`) as well, so this
repository, `shared/factrule/story_claims.py` and the hunter share one module
object and one `WikipediaError` class in a process.

This repository keeps no copy on purpose (the `_factrule.py` precedent). Root
lookup is `_runlog.factory_root()` - `FACTORY_ROOT` wins, else the nearest
ancestor holding `shared/runlog/runlog.py`; a root without the module is an
error, never a silent fallback to an older client.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

SHARED_REL = Path("shared") / "wikipedia" / "wikipedia_api.py"
MODULE_NAME = "factory_wikipedia_api"


def _load():
    try:
        path = (factory_root() / SHARED_REL).resolve()
    except RuntimeError as exc:
        raise RuntimeError(f"the Wikipedia client was not found: {exc} "
                           f"(CF-0551: it lives in the root, {SHARED_REL})")
    if not path.is_file():
        raise RuntimeError(f"the Wikipedia client was not found at {path}: this repository "
                           f"keeps no copy of it and loads {SHARED_REL} from the factory "
                           f"root (set FACTORY_ROOT; CF-0551)")
    held = sys.modules.get(MODULE_NAME)
    if held is not None and Path(getattr(held, "__file__", "")).resolve() == path:
        return held
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    module.ORIGIN = str(path)
    return module


sys.modules[__name__] = _load()
