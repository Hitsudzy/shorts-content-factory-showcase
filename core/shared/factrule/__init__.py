"""CF-0323: `from shared.factrule import fact_rule` (root on sys.path) or
`sys.path.insert(0, "<root>/shared/factrule"); import fact_rule` - the same
module either way, exactly as shared/runlog/ is reached. The agents take the
second road, through a shim by path (`agents/trend-hunter/scripts/
_factrule.py`); see fact_rule.py for the predicate itself, and for why a copy
of it still sits in that repository.

`ORIGIN` is set here for the same reason the shim sets it: the file is the
hunter's copy byte for byte, so its own default names the hunter's path, and
root code that prints which copy answered should not print a path it did not
load."""
from pathlib import Path

from . import fact_rule  # noqa: F401

fact_rule.ORIGIN = str(Path(fact_rule.__file__).resolve())
