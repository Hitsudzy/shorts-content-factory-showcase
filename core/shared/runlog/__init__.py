"""CF-0107: `from shared.runlog import runlog` (root on sys.path) or
`sys.path.insert(0, "<root>/shared/runlog"); import runlog` - the same module
either way. See runlog.py for the event format and the import snippet."""
from . import runlog  # noqa: F401
