"""CF-0815: the (video, plan) pair a gate is handed, read in the order it means.

qc_render.py and frame_judge_pack.py take two positionals, `video plan`. On
the Tech batch 2026-10-19T0844Z the operator called qc_render.py with them the
other way round - `plan.json videos/<slug>.mp4` - and both videos died in
0.05 s on

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xdf in position 34

which is `json.load(open(<the mp4>))`: an mp4 opens with a 32-byte `ftyp` box
and the bytes after it are not text. Nothing was wrong with the video or with
QC; the operator read the traceback, looked at `--help` and re-ran.

Two rules, one per half of that:

- `ordered()` - a pair whose "video" is a JSON document and whose "plan" is
  not is the same pair handed over the other way round, and is read as such.
  The answer is the one the right-order call gives: the same files go to the
  same checks, only the names on them are put back, and the caller says on
  stderr that it did so. Anything less clear-cut (both JSON, neither JSON, a
  file missing) is left exactly as given for the caller's own refusals.
- `load_plan()` - a plan that is not there, not text or not a JSON object is a
  sentence naming the file (PlanUnreadable), never a traceback out of the
  codec or the JSON parser.
"""
import json
from pathlib import Path

# Enough to get past a UTF-8 BOM and leading whitespace to the first byte.
_HEAD_BYTES = 64


class PlanUnreadable(Exception):
    """The plan argument is not a plan: missing, not text, or not JSON."""


def _head(path):
    try:
        with open(path, "rb") as fh:
            return fh.read(_HEAD_BYTES)
    except OSError:
        return b""


def looks_like_json(path):
    """True when the file's first meaningful byte opens a JSON document. Reads
    64 bytes, never the file - a render is hundreds of megabytes."""
    head = _head(path)
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return head.lstrip()[:1] in (b"{", b"[")


def ordered(video, plan):
    """(video, plan, swapped): the pair in `video plan` order.

    Swapped only when it is unambiguous - both files exist, the one given as
    the video is JSON and the one given as the plan is not. Paths come back
    as the same type they were given in."""
    if (Path(video).is_file() and Path(plan).is_file()
            and looks_like_json(video) and not looks_like_json(plan)):
        return plan, video, True
    return video, plan, False


def swap_note(video, plan):
    """The stderr line a caller prints after ordered() swapped the pair."""
    return (f"arguments given as `plan video` - read as video={video}, "
            f"plan={plan} (the usage is `video plan`; CF-0815)")


def load_plan(path):
    """The plan's JSON object, or PlanUnreadable with a sentence naming the file."""
    p = Path(path)
    if not p.is_file():
        raise PlanUnreadable(f"no plan at {p} - nothing to check against "
                             f"(the usage is `video plan`)")
    try:
        with open(p, encoding="utf-8-sig") as fh:
            plan = json.load(fh)
    except UnicodeDecodeError:
        raise PlanUnreadable(f"{p} is not a plan: it is not text (a video or "
                             f"other binary file?) - the usage is `video plan`")
    except json.JSONDecodeError as e:
        raise PlanUnreadable(f"{p} is not a plan: not valid JSON ({e})")
    if not isinstance(plan, dict):
        raise PlanUnreadable(f"{p} is not a plan: JSON {type(plan).__name__}, "
                             f"not an object")
    return plan
