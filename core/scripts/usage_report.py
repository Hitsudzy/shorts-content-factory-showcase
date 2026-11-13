#!/usr/bin/env python3
"""CF-0101 item 3 (closed via CF-0109): "stage x model x tokens x minutes" on
one screen, from the batch's `usage` events only - never from transcripts.

    scripts/usage_report.py <batch-dir> [--json]

Exit 1 with a hint when the batch has no usage events yet (run
scripts/usage_from_transcripts.py <batch-dir> --write first)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared" / "runlog"))
import usage  # noqa: E402

sys.exit(usage.report_main())
