#!/usr/bin/env python3
"""CF-0345: the thin-pool supplement step of a batch, after the Content
Researcher and before the second compliance pass. Thin shim over
shared/runlog/supplement.py - the order and the states are documented there.

    scripts/thin_pool_supplement.py <batch-dir> [--dry-run] [--json]

Exit 0: done, or no request (the step is skipped); when step 6b deferred
scripts for the supplement (CF-0422), it then prints the next command,
`plan_check_loop.py <batch> --write --after-supplement` - it does not run it.
Exit 10: the new sources owe shot descriptions - describe them, run again.
Exit 2: bad call."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared" / "runlog"))
import supplement  # noqa: E402

sys.exit(supplement.main())
