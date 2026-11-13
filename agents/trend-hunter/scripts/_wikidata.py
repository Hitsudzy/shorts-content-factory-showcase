"""CF-0637: the one place in this repo that finds the Wikidata client, the
same way `_wikipedia.py` finds the Wikipedia client:

    from _wikidata import wikidata_api
    client = wikidata_api.cached_client(cache_dir, tool_name=TOOL_NAME, gate=...)

The client's home is `<root>/shared/wikidata/wikidata_api.py` (the factory's one
Wikidata client - a topic's structured facts, dates, cast, crew, studios,
awards, as support text and fact candidates; CC0, no attribution owed). This repository keeps no copy of it. It is registered under its
one `sys.modules` name (`factory_wikidata_api`), so a process holds one module
object.

Root lookup is `_runlog.factory_root()`: `FACTORY_ROOT` wins, else the nearest
ancestor holding `shared/runlog/runlog.py`. A root without the module is an
error at import - a stage that cannot read Wikidata must not look like a stage
whose topics have no statements there."""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

SHARED_REL = Path("shared") / "wikidata" / "wikidata_api.py"
MODULE_NAME = "factory_wikidata_api"


def _load():
    try:
        path = (factory_root() / SHARED_REL).resolve()
    except RuntimeError as exc:
        raise RuntimeError(f"the Wikidata client was not found: {exc} (CF-0637)")
    if not path.is_file():
        raise RuntimeError(f"the Wikidata client was not found at {path}: this repository "
                           f"keeps no copy of it and loads {SHARED_REL} from the factory "
                           f"root (set FACTORY_ROOT; CF-0637)")
    held = sys.modules.get(MODULE_NAME)
    if held is not None and Path(getattr(held, "__file__", "")).resolve() == path:
        return held
    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    module.ORIGIN = str(path)
    return module


wikidata_api = _load()
