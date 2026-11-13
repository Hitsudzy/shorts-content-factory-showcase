#!/usr/bin/env python3
"""CF-0424: hold every hook of a written batch to the channel's opener formulas.

**The decision** (the user, 2026-09-28). A video that opens on a formula -
"the most talked-about ...", "nobody noticed ..." - holds the viewer better.
The channel keeps the formulas (`channels/<channel>.json` ->
`content_researcher.hook_openers`), the writer picks one per script and fills
its slots with the topic's specifics, and records its id beside the hook
(`scripts[].hook_opener_id`, `null` for an opener of the writer's own). One
formula is used at most once per `hook_opener_min_gap_videos` videos (0 = the
rotation is off), and never twice in one batch. The library, the match and the
rotation's history are `hook_openers.py`, beside this file; this is the gate.

**What it holds each script to**, in file order:

    ok       the id is in the library, the hook opens on its template, and the
             formula is neither in the rotation's window nor already used
             earlier in this batch.
    free     `hook_opener_id` is null (or absent - a batch written before
             CF-0424) and the hook opens on none of the templates: an opener of
             the writer's own, which the rotation does not count.
    REWRITE  one of: the id is not in the library; the hook does not open on
             the id's template (compared on the template's own words, case and
             punctuation aside, each slot filled); the formula is barred by the
             last N openers of the channel's past batches; the formula is used
             by an earlier script of this batch; or the id is null while the
             hook opens on a template - a formula used without its id is one the
             rotation never counts.

A `REWRITE` is a rewrite of the **hook**, never a drop of the topic: this is not
a gate on whether the video gets made, only on how its first words are worded.
Pick an allowed formula (`hook_openers.py <batch-dir> --topic <topic_id>`
prints them), or open on words of your own with `hook_opener_id: null`, and
run step 6 again from the budget - the hook is narration.

On a channel with no library the gate has nothing to hold: every script is
`free` whatever it carries, exactly as before CF-0424.

Usage:

    python3 scripts/check_hook_opener.py <03-content-researcher.json>

Exit 0 when no script is `REWRITE`, 1 otherwise, 2 on bad usage, 3 when the
channel file is missing (`no-waiting: missing_channel_config_skip`). Read-only:
nothing is written back.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0853)

import _no_waiting as nw  # noqa: E402
import hook_openers as ho  # noqa: E402

POINT_NO_CONFIG = "researcher_missing_channel_config"
OK, FREE, REWRITE = "ok", "free", "REWRITE"


def judge_script(script, library, barred, used_in_batch):
    """`(verdict, detail)` for one script. `used_in_batch` maps an id to the
    script that took it earlier in this batch."""
    oid = script.get(ho.FIELD)
    hook = script.get("hook") or ""
    by_id = {o["id"]: o for o in library}
    if not oid:
        found = ho.matching_ids(hook, library)
        if found:
            return REWRITE, (f"the hook opens on the formula `{found[0]}` but `{ho.FIELD}` is "
                             f"null - a formula used without its id is one the rotation never "
                             f"counts; write the id (if the rotation allows it) or open on "
                             f"words of your own")
        return FREE, "an opener of the writer's own"
    if oid not in by_id:
        return REWRITE, (f"`{ho.FIELD}` {oid!r} is not in the channel's library "
                         f"({len(library)} formula(s)) - pick one of them or write null")
    template = by_id[oid]["template"]
    if not ho.opens_with(hook, template):
        return REWRITE, (f"the hook does not open on `{oid}` ({template!r}) - its words, in "
                         f"order, each slot filled, have to start the hook")
    if oid in barred:
        b, sid = barred[oid]
        return REWRITE, (f"`{oid}` is barred by the rotation: used by {sid} in batch {b}, "
                         f"within the channel's last openers")
    if oid in used_in_batch:
        return REWRITE, f"`{oid}` is already the opener of {used_in_batch[oid]} in this batch"
    return OK, template


def check_batch_data(data, library, gap, barred, out=print):
    """The whole batch; returns the problems, each prefixed with the script id."""
    problems = []
    used = {}
    for s in data.get("scripts") or []:
        if not isinstance(s, dict):
            continue
        sid = s.get("script_id")
        if not library:
            out(f"  free {sid}: no opener library in the channel - the opener is free")
            continue
        verdict, detail = judge_script(s, library, barred, used if gap > 0 else {})
        if verdict == OK:
            used.setdefault(s[ho.FIELD], sid)
            out(f"  ok   {sid}: {s[ho.FIELD]}")
        elif verdict == FREE:
            out(f"  free {sid}: {detail}")
        else:
            out(f"  REWRITE {sid}: {detail}")
            problems.append(f"{sid}: {detail}")
    return problems


def check_batch(path, root=None, out=print):
    """Load the batch, its channel's library and the rotation's window, and
    judge. Raises `ho.ConfigError` when the channel file is missing."""
    path = Path(path)
    data = json.loads(path.read_text())
    channel, pipeline_dir, batch_id, _ = ho.batch_context(
        path, ho.resolve_channel(data.get("channel"), root), root)
    library, gap = ho.library_of(ho.load_config(channel, root))
    barred = {}
    if library:
        barred = ho.barred_by_history(ho.history(channel, pipeline_dir, before_batch=batch_id), gap)
    n = len(data.get("scripts") or [])
    if library:
        rot = (f"one formula at most once in {gap} videos, barred now: "
               f"{', '.join(sorted(barred)) or 'none'}") if gap > 0 else "rotation off"
        out(f"{path}: {n} script(s); {len(library)} opener formula(s), {rot}")
    else:
        out(f"{path}: {n} script(s); no opener library in the channel")
    return check_batch_data(data, library, gap, barred, out=out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", type=_batch_arg.batch_file,  # CF-0853: usage, not a crash
                    help=_batch_arg.HELP)
    args = ap.parse_args(argv)
    try:
        problems = check_batch(args.batch_file)
    except ho.ConfigError as exc:
        channel = None
        try:
            channel = ho.resolve_channel(
                json.loads(Path(args.batch_file).read_text()).get("channel"))
        except (OSError, ValueError):
            pass
        print(nw.refuse(POINT_NO_CONFIG, why=str(exc), what="channel config",
                        channel=channel or "?"))
        return nw.EXIT_CANNOT_ANSWER
    if problems:
        print(f"\n{len(problems)} hook(s) to rewrite (the hook, not the topic):")
        for p in problems:
            print(f"  - {p}")
        return 1
    return 0


@runlog.script("content-researcher", "check-hook-opener", name="check_hook_opener.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event, so a non-zero result (1 = a hook to rewrite, 2 =
    usage, 3 = no channel file) is recorded as `failed` (CF-0107). Pure Python
    over the batch file and the channel's past `03`: no external binary, no
    model call, so no `child` events."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
