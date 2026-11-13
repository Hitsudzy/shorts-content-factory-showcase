"""CF-0432: `from shared.score import score` (root on sys.path) or
`sys.path.insert(0, "<root>/shared/score"); import score` - the same module
either way, exactly as shared/runlog/ and shared/factrule/ are reached."""
from . import score  # noqa: F401
