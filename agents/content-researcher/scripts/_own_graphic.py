"""CF-0689: the one place in this repo that finds the root's own-graphic rule
(`<root>/shared/own_graphic.py`), the way `_factrule.py` finds the fact rule:
loaded by path from the factory root, no copy kept here.

    from _own_graphic import own_graphic, channel_draws, is_graphic_anchor

    og = own_graphic()                       # the root's module (KIND, TEMPLATES,
    problems = og.check_graphics(script, pieces)   # check_graphics, ...)

The module is loaded on first use, not at import: the coverage, two-source and
rewrite gates import this file for `is_graphic_anchor` / `graphics_of` on every
channel, and a script without graphics never needs the rule. A root without
the module when a script DOES order graphics is an error (`RuntimeError`), as
for the fact rule - a graphic judged against no rule is not judged.

What lives here and nowhere else in this repo:

* `is_graphic_anchor(anchor)` - a `visual_anchors[]` entry that places one of
  the script's own graphics (`graphic_id`, no pool `phrase` needed). The Video
  Editor reads the same key (`graphic_id` wins over `phrase`).
* `channel_draws(channel, root)` - the channel's switch: its
  `channels/<channel>/footage-origin.json` has a `footage_origins[]` entry
  under the `own_graphic` licence (ExampleTech since CF-0689). Without it a
  channel is judged exactly as before: a graphic anchor there is no anchor.
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import factory_root  # noqa: E402

SHARED_REL = Path("shared") / "own_graphic.py"
# The root module's own names, mirrored so a script with no graphics never
# has to load it; tests/test_graphics_check.py pins them to the module.
KIND = "own_graphic"
ANCHOR_KEY = "graphic_id"
GRAPHICS_FIELD = "graphics"
WHERE_PREFIX = "graphic:"
ORIGIN_FILE = "footage-origin.json"

_MODULE = {}


def shared_path(root=None):
    """The root's module, or None when the root cannot be found or has not got it."""
    try:
        base = Path(root) if root else factory_root()
    except RuntimeError:
        return None
    path = base / SHARED_REL
    return path if path.is_file() else None


def own_graphic(root=None):
    """The root's `shared/own_graphic.py`, loaded by path once per path."""
    path = shared_path(root)
    if path is None:
        raise RuntimeError(f"{SHARED_REL} was not found at the factory root (CF-0689): this "
                           f"repository keeps no copy of it (set FACTORY_ROOT, or see "
                           f"scripts/_own_graphic.py)")
    key = str(path)
    if key not in _MODULE:
        spec = importlib.util.spec_from_file_location("own_graphic_shared", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.ORIGIN = key
        _MODULE[key] = mod
    return _MODULE[key]


def is_graphic_anchor(anchor):
    """A `visual_anchors[]` entry that places a graphic (`graphic_id` set)."""
    return isinstance(anchor, dict) and ANCHOR_KEY in anchor and anchor.get(ANCHOR_KEY) is not None


def graphics_of(script):
    g = (script or {}).get(GRAPHICS_FIELD)
    return g if isinstance(g, list) else []


def pool_anchors(script, anchors_field="visual_anchors"):
    """The anchors the pool has to picture - every anchor but a graphic's."""
    return [a for a in (script or {}).get(anchors_field) or [] if not is_graphic_anchor(a)]


def graphic_anchors(script, anchors_field="visual_anchors"):
    return [a for a in (script or {}).get(anchors_field) or [] if is_graphic_anchor(a)]


API_DEMO_LICENCE = "api_demo"        # = api_demo.ORIGIN = footage_licence.API_DEMO (CF-0690)
API_CHAT = "api_chat"                # = own_graphic.API_CHAT
API_DEMO_CONFIG_KEY = "api_demo"     # = api_demo.CONFIG_KEY


def _origin_doc(channel, root=None):
    """The channel's footage-origin document, or None."""
    if not channel:
        return None
    try:
        base = Path(root) if root else factory_root()
    except RuntimeError:
        return None
    path = base / "channels" / str(channel) / ORIGIN_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _has_licence(doc, licence):
    origins = (doc or {}).get("footage_origins")
    return any(isinstance(o, dict) and o.get("licence") == licence for o in origins or [])


def channel_api_demo(channel, root=None):
    """CF-0690: `(has_origin, config)` - whether the channel's footage-origin
    document has an origin under the `api_demo` licence (ExampleTech), and its
    `api_demo` block (the models, the prompts, `max_answer_chars`; None when
    there is none). A channel with no document is `(False, None)`."""
    doc = _origin_doc(channel, root)
    block = (doc or {}).get(API_DEMO_CONFIG_KEY)
    return _has_licence(doc, API_DEMO_LICENCE), (block if isinstance(block, dict) else None)


def api_chats(script):
    """The script's ordered `api_chat` graphics."""
    return [g for g in graphics_of(script)
            if isinstance(g, dict) and g.get("template") == API_CHAT]


def channel_draws(channel, root=None):
    """True when the channel's footage-origin document has an origin under
    the `own_graphic` licence - the switch that lets its scripts order
    graphics. A channel with no document, or none such, is False."""
    if not channel:
        return False
    try:
        base = Path(root) if root else factory_root()
    except RuntimeError:
        return False
    path = base / "channels" / str(channel) / ORIGIN_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    origins = doc.get("footage_origins") if isinstance(doc, dict) else None
    return any(isinstance(o, dict) and (o.get("licence") == KIND)
               for o in origins or [])


# CF-0806: the topics the Footage Indexer kept on own graphics (CF-0689). The
# indexer writes them in two places of `01b-footage-index.json` and the root's
# funnel (`shared/runlog/funnel.py`) reads both, so this reads both too: a
# topic named in either one is kept.
FOOTING_KEY = "own_graphic_footing"            # = ingest_batch.OWN_GRAPHIC_KEY
FOOTING_KEPT = "kept"                          # own_graphic_footing.kept[]
FLOOR_KEY = "two_source_floor"
FLOOR_KEPT = "kept_on_own_graphics"            # two_source_floor.kept_on_own_graphics


def kept_on_own_graphics(index):
    """`{topic_id: the indexer's kept record (or {})}` out of a parsed
    `01b-footage-index.json`; `{}` for no index or no such block."""
    index = index if isinstance(index, dict) else {}
    out = {}
    block = index.get(FOOTING_KEY)
    for r in (block.get(FOOTING_KEPT) if isinstance(block, dict) else None) or []:
        if isinstance(r, dict) and isinstance(r.get("topic_id"), str) and r["topic_id"]:
            out[r["topic_id"]] = r
    floor = index.get(FLOOR_KEY)
    for t in (floor.get(FLOOR_KEPT) if isinstance(floor, dict) else None) or []:
        if isinstance(t, str) and t:
            out.setdefault(t, {})
    return out
