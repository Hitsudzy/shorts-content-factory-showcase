"""CF-0690: the one place in this repo that finds the factory's "demo via
API" pieces and hands them to the scripts:

    from _api_demo import api_demo, gemini_api

    api_demo.display_name_for("gemini-2.5-flash-001", block)   # "Gemini 2.5 Flash"
    gemini_api.GeminiClient(min_interval=5, timeout=60).ask(model, prompt)

* `api_demo`   - `<root>/shared/api_demo.py`: the rule an `api_chat` graphic
  is held to (`RECORD_FIELD`, `RECORD_ID_RE`, `protocol_problems`,
  `display_name_for`, `shown_answer` ...);
* `gemini_api` - `<root>/shared/gemini/gemini_api.py`: the factory's one
  Gemini API client (the free tier), registered under its one `sys.modules`
  name `factory_gemini_api` as `_tvmaze.py` does for TVmaze.

Lookup is the one `_own_graphic.py` uses: `<factory_root()>/shared/...`
first, then the nearest ancestor of this file that holds it (a test's
`FACTORY_ROOT` is a temp tree with `channels/` and nothing else). Loaded by
path, so nothing of the root goes onto `sys.path`. This repository keeps a
copy of neither.

No fallback. A piece that cannot be found or loaded is None and the caller
says so: `fetch_api_demo.py` then asks nothing ("the Gemini client was not
found"), `api_demo_text.py` writes no piece.
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

RULE_REL = Path("shared") / "api_demo.py"
CLIENT_REL = Path("shared") / "gemini" / "gemini_api.py"
CLIENT_MODULE_NAME = "factory_gemini_api"


def library_path(rel):
    """Where `rel` is under the factory root, or None."""
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


def _load(rel, name, register=False):
    path = library_path(rel)
    if path is None:
        return None
    path = path.resolve()
    if register:
        held = sys.modules.get(name)
        if held is not None and Path(getattr(held, "__file__", "")).resolve() == path:
            return held
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:   # a piece that cannot load is a piece not found - said by the caller
        if register:
            sys.modules.pop(name, None)
        return None
    mod.ORIGIN = str(path)
    return mod


api_demo = _load(RULE_REL, "api_demo_for_trend_hunter")
gemini_api = _load(CLIENT_REL, CLIENT_MODULE_NAME, register=True)
