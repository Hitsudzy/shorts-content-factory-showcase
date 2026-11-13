#!/usr/bin/env python3
"""CF-0845: a topic whose pool holds fewer clean usable shots than the
channel's `content_researcher.min_usable_shots_for_script` (default 10) is
taken out of `03-content-researcher.json -> scripts[]` before the first plan
check, into `skipped[]` as `pool_too_thin` - its slot goes to the reserve by
the usual `reserve_refill`. Thin shim over shared/runlog/thin_topic.py - the
rule and the count are documented there.

    scripts/thin_topic_gate.py --batch <batch-dir> [--check] [--write] [--json]

Exit 0: no thin topic (`--check`), or the drop written (`--write`).
Exit 1: `--check` - there are thin topics. Exit 2: bad call."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared" / "runlog"))
import thin_topic  # noqa: E402

sys.exit(thin_topic.main())
