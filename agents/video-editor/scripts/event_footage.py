#!/usr/bin/env python3
"""CF-0545: a block that retells the event takes the event's own footage.

The rule itself lives at the factory root, `shared/event_footage.py`
(CF-0575 moved it there: the Content Researcher counts the event's own
footage before the voice with the same classification, and a rule written
twice is a rule that will disagree with itself - CF-0159). This file keeps
**no** copy: it loads the root's module by path and hands it this repo's
`source_gate.source_id` (the reading the two-source gate uses, which also
knows cut-clip and held-frame names), so `import event_footage` in
`resolve_anchors.py` and the tests reads exactly the root's functions.

A root without the module is an error, and loudly: an event rule with no
rule behind it could only refuse interviews on a guess or keep them on one.
"""
import importlib.util
from pathlib import Path

from repo_paths import FACTORY_ROOT

SHARED_REL = Path("shared") / "event_footage.py"

try:  # the same id reading the two-source gate uses
    from source_gate import source_id as _ve_source_id
except ImportError:  # pragma: no cover
    _ve_source_id = None


def _load():
    path = Path(FACTORY_ROOT) / SHARED_REL
    if not path.is_file():
        raise RuntimeError(
            f"{SHARED_REL} was not found at the factory root ({FACTORY_ROOT}): the "
            f"event-footage rule (CF-0545/CF-0575) is kept there only, this "
            f"repository holds no copy of it")
    spec = importlib.util.spec_from_file_location("event_footage_shared", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if _ve_source_id is not None:
        mod.source_id = _ve_source_id
    mod.ORIGIN = str(path)
    return mod


_shared = _load()
globals().update({k: v for k, v in vars(_shared).items()
                  if not (k.startswith("__") and k.endswith("__"))})
