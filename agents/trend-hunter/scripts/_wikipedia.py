"""CF-0551: the one place in this repo that finds the Wikipedia client, the
same way `_factrule.py` finds the fact rule:

    from _wikipedia import wikipedia_api
    client = wikipedia_api.cached_client(cache_dir, tool_name=TOOL_NAME)

The client's home is `<root>/shared/wikipedia/wikipedia_api.py` (CF-0237's
client, moved out of the Content Researcher's tree by CF-0551 so this stage can
read the topic's support text through it rather than through a second client of
its own). This repository keeps no copy of it. It is registered under its one
`sys.modules` name (`factory_wikipedia_api`), as the researcher's loader and
`story_claims.py` register it, so a process holds one module object.

Root lookup is `_runlog.factory_root()`: `FACTORY_ROOT` wins, else the nearest
ancestor holding `shared/runlog/runlog.py`. A root without the module is an
error at import - a stage that cannot read the support text must not look like
a stage whose topics have none."""
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
        raise RuntimeError(f"the Wikipedia client was not found: {exc} (CF-0551)")
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


wikipedia_api = _load()
