#!/usr/bin/env python3
"""CF-0108: the `StopFailure` / `rate_limit` hook - a `kind: limit-hit` event without the agent.

Install (scripts/install_accounting_hooks.py does it):

    "hooks": {"StopFailure": [{"matcher": "rate_limit",
                               "hooks": [{"type": "command",
                                          "command": "python3 <root>/shared/runlog/limit_hook.py"}]}]}

Claude Code runs the command with a JSON on stdin. The documented fields are
session_id, transcript_path, cwd, hook_event_name; the matcher/error fields
have been named differently across versions, so this reads liberally:
`error`, `error_type`, `reason`, `matcher`, `stop_reason`, `failure_reason`,
`message` - whichever is present - and stores the first of them as `reason`
(default "rate_limit").

Event: kind=limit-hit, stage=null, params:

    session_id       the Claude Code session that was stopped
    transcript_path  its transcript (.jsonl) - gaps.py reads the resume marker there
    reason           "rate_limit" | whatever the hook payload said
    hook_event_name  "StopFailure" (or whatever the payload said)
    cwd              the session's cwd when given

Resumption is not an event of its own: the next event of any kind, or the
"I hit my usage limit ... Please continue" line in the transcript, marks it.
The hook exits 0 always and writes nothing when no run is active (a limit hit
outside a run is not the factory's business).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import limits  # noqa: E402
import runlog  # noqa: E402

KIND_LIMIT_HIT = "limit-hit"
REASON_KEYS = ("error", "error_type", "reason", "matcher", "stop_reason", "failure_reason", "message")


def parse(payload):
    """The limit-hit params from a hook payload (dict), liberal about field names."""
    d = payload if isinstance(payload, dict) else {}
    reason = None
    for k in REASON_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            reason = v.strip()
            break
        if isinstance(v, dict):
            inner = v.get("type") or v.get("reason") or v.get("message")
            if isinstance(inner, str) and inner.strip():
                reason = inner.strip()
                break
    return {
        "session_id": d.get("session_id") or d.get("sessionId"),
        "transcript_path": d.get("transcript_path") or d.get("transcriptPath"),
        "reason": reason or "rate_limit",
        "hook_event_name": d.get("hook_event_name") or "StopFailure",
        "cwd": d.get("cwd"),
    }


def record(batch_dir, payload):
    """Append the limit-hit event to the batch. Returns the event or None."""
    try:
        return runlog.emit(batch_dir, KIND_LIMIT_HIT, None, params=parse(payload))
    except Exception as e:
        runlog._warn(f"limit-hit not recorded ({e.__class__.__name__}: {e})")
        return None


def main(argv=None):
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        payload = {}
    try:
        batch = limits.active_batch()
        if batch is not None:
            record(batch, payload)
    except Exception as e:
        runlog._warn(f"limit hook failed ({e.__class__.__name__}: {e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
