#!/usr/bin/env python3
"""CF-0109: tokens per stage x video x model x role of one run, read from the
Claude Code transcripts by the batch's time window.

    scripts/usage_from_transcripts.py <batch-dir> [--transcripts DIR] [--session ID]...
                                      [--slack MIN] [--write] [--json]

Prints the one-screen table; --write appends `kind: usage` events to the
batch's RUN_EVENTS.jsonl (a new generation each time - readers use the newest)
and re-renders RUN_LOG.txt. Thin shim over shared/runlog/usage.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared" / "runlog"))
import usage  # noqa: E402

sys.exit(usage.main())
