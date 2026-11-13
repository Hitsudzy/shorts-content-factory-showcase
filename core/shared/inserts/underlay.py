#!/usr/bin/env python3
"""CF-0014: the brainrot underlay - a muted loop from shared/inserts/loops/
in the second plane of the frame, under the main content.

Importable from any agent repo the same way inserts_lib is:
`sys.path.insert(0, "<FACTORY_ROOT>/shared/inserts")`; stdlib only.

What this module owns and what it does not
------------------------------------------
It owns the *decision*: is the layer on for this channel, which file goes
under this video, what is written about it. Video Editor owns the
*placement*: the composition already has an empty second-plane slot, and the
child task of CF-0014 wires `plan_underlay()`'s answer into it. The split is
the same one CF-0013 made for every insert layer - the factory owns the
mechanism, the channel switches it on, the agent renders it.

The decision, in order (`plan_underlay`):

1. the channel switch `insert_layers.underlay.enabled` (validate_inserts.py
   knows the key; absent or false means off - a channel written before the
   layer existed keeps working unchanged);
2. `inserts_lib.choose_loop(video_id)`: load loops/index.json, drop the
   entries whose rights holder is on the blacklist at risk_level high,
   pick one by sha256(video_id) mod n over what is left. Deterministic in
   the video id, stateless, and the mapping simply moves when a file is
   deleted after a claim - that rotation is the whole of the catalogue-risk
   answer the 2026-09-05 decision settled on, so nothing here may add a
   ledger or a preference on top of it;
3. the file has to exist on disk. The index is tracked and the media is not
   (same as shared/footage/), so a fresh checkout has entries and no files.

Every outcome is written down. The chosen entry and every entry the
blacklist refused become `inserts_lib.provenance_record()`s under
`videos[].inserts[]` of 05-video-editor.json (PROVENANCE_FIELD) - the same
list the proof and meme layers write to, tagged `layer: "underlay"` so the
Analyst can tell them apart - and `videos[].underlay` says whether a loop
was applied and, when not, why (`reason`: one of REASONS). A video with no
underlay is a video with an empty second plane, never a failed video: the
layer is decoration, and inserts/POLICY.md's degradation promise applies.

CLI
---
`underlay.py VIDEO_ID --channel channels/<id>.json` prints the plan for that
channel; `--force-layer` instead of `--channel` is the debugging run with the
layer on outside any channel. Neither is a refusal (CF-0214): a forgotten
flag must not switch on a layer the channel switched off.

FACTORY_ROOT
------------
The library lives at `<factory root>/shared/inserts/`. The root is found the
way inserts_lib finds it - two levels up from this file - unless the
environment variable FACTORY_ROOT names another directory. That override
exists for tests and for agent worktrees, which are not checked out inside
the factory: point it at a temp directory that has `shared/inserts/` and the
channel's `channels/<id>/rights-holder-blacklist.json`, and the layer reads
from there.

CF-0561: the rights holders are the channel's (docs/channel-data.md). The
plan reads the list of the channel its config names (`channel_id`), through
`shared/channel_data.py`; a channel with no list of its own checks nothing and
says so, as an absent file always did. A config that names no channel -
`--force-layer`, the debugging run outside any channel - reads no list at
all (CF-0631): the plan gets an explicit empty list whose note says "outside
any channel, the rights-holder check was not applied", and every record it
writes says the same (`blacklist_check.applied: false`). There is no common
list to fall back to - the old `shared/rights-holder-blacklist.json` is gone.
"""
import importlib.util
import os
import sys
from pathlib import Path

# CF-0231: the same rule as rotation/shortage.py. Both callers of this module
# (meme_layer._lib(), underlay_layer._module()) put this directory on sys.path
# before importing it, so `import inserts_lib` has always resolved - but that
# is the caller's contract, not this file's, and the one root module a
# neighbouring repository loads is exactly the one that must not depend on it.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import inserts_lib as lib  # noqa: E402 - after the sys.path line above

LAYER = "underlay"
LIBRARY_KIND = "loop"
STAGE_FIELD = "underlay"                   # videos[].underlay in 05-video-editor.json
PROVENANCE_FIELD = lib.PROVENANCE_FIELD    # videos[].inserts[]
FACTORY_ROOT_ENV = "FACTORY_ROOT"

# Why there is, or is not, a loop under this video. Closed on purpose: the
# Analyst joins on these, and a free-text reason is a reason nobody counts.
REASON_APPLIED = "applied"
REASON_DISABLED = "layer_disabled"         # the channel did not switch it on
REASON_EMPTY = "library_empty"             # loops/index.json has no entries
REASON_ALL_SKIPPED = "all_skipped"         # every entry failed the blacklist check
REASON_FILE_MISSING = "file_missing"       # indexed, chosen, not on this disk
REASONS = (REASON_APPLIED, REASON_DISABLED, REASON_EMPTY, REASON_ALL_SKIPPED,
           REASON_FILE_MISSING)

# How the file is placed once chosen. Fixed by the 2026-09-05 decision, not
# by the channel: the underlay is silent (the main content has the only
# audio track) and it fills the video's span - a video loop is repeated or
# cut to length, an image stands for the whole span.
AUDIO_TREATMENT = "muted"
FIT_LOOP_OR_TRIM = "loop_or_trim"
FIT_STILL = "still"


# --------------------------------------------------------------------------
# where the library is
# --------------------------------------------------------------------------

def factory_root():
    """The factory checkout: FACTORY_ROOT when set, else inserts_lib's REPO."""
    override = os.environ.get(FACTORY_ROOT_ENV)
    return Path(override).expanduser().resolve() if override else lib.REPO


def inserts_root(root=None):
    return Path(root) / "shared" / "inserts" if root else factory_root() / "shared" / "inserts"


# CF-0631: what a plan made outside any channel (`--force-layer`, a config
# with no `channel_id`) says about the rights-holder check - it was not run,
# since the list is a channel's and there is no common one.
NO_CHANNEL_NOTE = ("outside any channel, the rights-holder check was not applied: "
                   "the list is a channel's (channels/<id>/rights-holder-blacklist.json) "
                   "and there is no common one (CF-0631)")


def _channel_data():
    spec = importlib.util.spec_from_file_location(
        "channel_data_underlay", Path(__file__).resolve().parents[1] / "channel_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def blacklist_path(root=None, channel=None):
    """The channel's rights-holder list (CF-0561); None with no channel named
    - there is no common list (CF-0631)."""
    if not channel:
        return None
    root = Path(root) if root else factory_root()
    return _channel_data().channel_list_path(channel, "rights-holders", root)


def no_channel_blacklist():
    """The explicit empty list of a plan made outside any channel."""
    return {"schema_note": NO_CHANNEL_NOTE, "last_updated": None, "entries": [],
            "outside_channel": True}


def load_blacklist(root=None, channel=None):
    """The channel's blacklist, or an empty one when the file is absent - a
    library with no blacklist beside it checks nothing and says so
    (`blacklist_updated: null` in every record). A channel this root does
    not know has no list either - the same answer, with the reason; never
    another channel's list. With no channel named: `no_channel_blacklist()`."""
    if not channel:
        return no_channel_blacklist()
    try:
        path = blacklist_path(root, channel)
    except Exception as e:                                  # noqa: BLE001 - ChannelDataError
        return {"schema_note": f"no blacklist for channel {channel!r}: {e}",
                "last_updated": None, "entries": []}
    if not path.exists():
        return {"schema_note": "no blacklist file at " + str(path),
                "last_updated": None, "entries": []}
    return lib.load_blacklist(path)


# --------------------------------------------------------------------------
# the channel switch
# --------------------------------------------------------------------------

def layer_switch(channel_cfg):
    """(enabled, reason) from a channel config's insert_layers.underlay.

    Off unless the switch is present and `enabled` is exactly true. The
    validator in inserts/validate_inserts.py is what checks the switch is
    well-formed and that the channel may flip it; this only reads it.
    """
    layers = (channel_cfg or {}).get("insert_layers") or {}
    switch = layers.get(LAYER) if isinstance(layers, dict) else None
    if not isinstance(switch, dict):
        return False, "no insert_layers.underlay switch in the channel config"
    return switch.get("enabled") is True, str(switch.get("reason") or "")


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------

def _tagged(record, applied):
    record = dict(record)
    record["layer"] = LAYER
    record["applied"] = applied
    return record


def _media_kind(path):
    suffix = Path(path).suffix.lower()
    if suffix in lib.IMAGE_SUFFIXES:
        return "image"
    if suffix in lib.VIDEO_SUFFIXES:
        return "video"
    return "unknown"


def plan_underlay(video_id, channel_cfg, root=None, blacklist=None, video_seconds=None):
    """Decide the underlay for one video. Never raises on an empty or
    absent library; the answer says what happened.

    video_id       the id the rotation hashes (the script_id in 05-*.json)
    channel_cfg    the channel config dict (its insert_layers.underlay is read)
    root           factory root override; default factory_root() (FACTORY_ROOT
                   env, else the checkout this file is in)
    blacklist      a loaded blacklist dict; default: the list of the channel
                   `channel_cfg["channel_id"]` names (CF-0561)
    video_seconds  the video's length, when known - lets the plan say how
                   many repeats a video loop needs

    Returns a dict:
      layer      "underlay"
      video_id   as given
      enabled    the channel switch
      applied    True when a file is to be placed
      reason     one of REASONS
      entry      the chosen index entry, or None
      path       absolute path of the file to place, or None
      media      "image" | "video" | None
      treatment  {"audio": "muted", "fit": ..., "loops_needed": int | None}
      inserts    provenance records (chosen + every skipped), for
                 videos[].inserts[]
      library    {"root": ..., "entries": n, "eligible": n, "skipped": n}
    """
    root = Path(root) if root else factory_root()
    lib_root = inserts_root(root)
    channel = (channel_cfg or {}).get("channel_id") if isinstance(channel_cfg, dict) else None
    bl = blacklist if blacklist is not None else load_blacklist(root, channel)
    enabled, switch_reason = layer_switch(channel_cfg)

    plan = {
        "layer": LAYER, "video_id": video_id, "enabled": enabled,
        "applied": False, "reason": None, "entry": None, "path": None,
        "media": None,
        "treatment": {"audio": AUDIO_TREATMENT, "fit": None, "loops_needed": None},
        "inserts": [],
        "library": {"root": str(lib_root), "entries": 0, "eligible": 0, "skipped": 0},
        "note": "",
    }

    if not enabled:
        plan["reason"] = REASON_DISABLED
        plan["note"] = switch_reason or "layer off: no insert_layers.underlay switch"
        return plan

    entries = lib.load_index(LIBRARY_KIND, lib_root).get("entries", [])
    plan["library"]["entries"] = len(entries)
    if not entries:
        plan["reason"] = REASON_EMPTY
        plan["note"] = f"no loops in {lib_root / lib.KIND_FOLDERS[LIBRARY_KIND]}"
        return plan

    entry, skipped = lib.choose_loop(video_id, lib_root, bl)
    plan["inserts"] = [_tagged(r, False) for r in skipped]
    plan["library"]["skipped"] = len(skipped)
    plan["library"]["eligible"] = len(entries) - len(skipped)
    if entry is None:
        plan["reason"] = REASON_ALL_SKIPPED
        plan["note"] = (f"all {len(entries)} loop(s) refused by the blacklist check "
                        f"(blacklist updated {bl.get('last_updated')})")
        return plan

    record = _tagged(lib.provenance_record(entry, block=None, blacklist=bl), True)
    path = lib.entry_path(entry, LIBRARY_KIND, lib_root)
    plan["entry"] = entry
    if not path.exists():
        record["applied"] = False
        plan["inserts"].append(record)
        plan["reason"] = REASON_FILE_MISSING
        plan["note"] = f"{entry['id']} is indexed but {path} is not on this disk"
        return _outside_channel(plan, bl)

    plan["inserts"].append(record)
    plan["applied"] = True
    plan["reason"] = REASON_APPLIED
    plan["path"] = str(path)
    plan["media"] = _media_kind(path)
    fit = FIT_STILL if plan["media"] == "image" else FIT_LOOP_OR_TRIM
    loops_needed = None
    duration = entry.get("duration_s")
    if fit == FIT_LOOP_OR_TRIM and video_seconds and duration:
        loops_needed = max(1, -(-float(video_seconds) // float(duration)))
        loops_needed = int(loops_needed)
    plan["treatment"].update(fit=fit, loops_needed=loops_needed)
    plan["note"] = f"{entry['id']} by rotation over {plan['library']['eligible']} eligible loop(s)"
    return _outside_channel(plan, bl)


def _outside_channel(plan, bl):
    """CF-0631: a plan checked against the empty list of no channel says, in
    its note and in every record, that the rights-holder check was not run -
    "checked and passed" is a different fact."""
    if isinstance(bl, dict) and bl.get("outside_channel"):
        for rec in plan["inserts"]:
            check = rec.get("blacklist_check")
            if isinstance(check, dict) and check.get("applied", True):
                check.update(applied=False, not_applied=NO_CHANNEL_NOTE)
        plan["note"] = f"{plan['note']}; {NO_CHANNEL_NOTE}"
    return plan


# --------------------------------------------------------------------------
# what lands in 05-video-editor.json
# --------------------------------------------------------------------------

def stage_record(plan):
    """videos[].underlay: the applied/why summary, without the entry body
    (the entry's facts are in the provenance record beside it)."""
    return {
        "applied": plan["applied"],
        "reason": plan["reason"],
        "id": plan["entry"]["id"] if plan["entry"] else None,
        "file": plan["entry"]["file"] if plan["entry"] else None,
        "treatment": dict(plan["treatment"]),
        "library": dict(plan["library"]),
        "note": plan["note"],
    }


def write_stage_record(video_record, plan):
    """Merge one plan into a videos[] record of 05-video-editor.json in
    place: provenance records are appended to videos[].inserts[] beside
    whatever the proof/meme layers already wrote there (never replacing
    them), and videos[].underlay carries the summary. Returns the record."""
    existing = video_record.get(PROVENANCE_FIELD)
    if not isinstance(existing, list):
        existing = []
    video_record[PROVENANCE_FIELD] = [r for r in existing if r.get("layer") != LAYER] \
        + list(plan["inserts"])
    video_record[STAGE_FIELD] = stage_record(plan)
    return video_record


def underlay_records(video_record):
    """This layer's provenance records out of a videos[] record."""
    return [r for r in video_record.get(PROVENANCE_FIELD, []) or []
            if isinstance(r, dict) and r.get("layer") == LAYER]


# --------------------------------------------------------------------------
# CLI: what would go under a given video id
# --------------------------------------------------------------------------

FORCE_LAYER_REASON = "--force-layer: the layer run on outside any channel (debugging)"


def main(argv=None):
    """`underlay.py VIDEO_ID --channel channels/<id>.json` - what the channel's
    switch makes of the layer for this video. `--force-layer` instead of
    `--channel` runs the layer on outside any channel, to see what the
    library would put under a video; it is a debugging flag and says so in
    the plan's `channel` field.

    CF-0214: a run that names neither is a refusal (exit 2). It used to be
    the forced-on run - so a forgotten flag switched back on a layer the
    channel had switched off (example-film, CF-0014/CF-0189, by tone), the
    one channel-ownership defect that cancels a ban rather than substituting
    a value, visible only on the finished video. The Python entry point has
    the opposite, safe default: `plan_underlay(video_id, None)` is off.
    """
    import argparse
    import json
    ap = argparse.ArgumentParser(description="plan the underlay for one video id")
    ap.add_argument("video_id")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--channel", metavar="CONFIG_JSON",
                       help="the channel config (channels/<id>.json) whose "
                            "insert_layers.underlay switch decides the layer - required "
                            "unless --force-layer")
    which.add_argument("--force-layer", action="store_true",
                       help="debugging: run the layer on outside any channel (no channel's "
                            "switch is read)")
    ap.add_argument("--root", help=f"factory root (default ${FACTORY_ROOT_ENV} or checkout)")
    ap.add_argument("--seconds", type=float, help="video length, for loops_needed")
    a = ap.parse_args(argv)
    if a.force_layer:
        cfg = {"insert_layers": {LAYER: {"enabled": True, "reason": FORCE_LAYER_REASON}}}
        channel = None
    elif a.channel:
        try:
            cfg = json.loads(Path(a.channel).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            ap.error(f"--channel {a.channel}: not a readable channel config JSON ({e}) - "
                     f"the layer is not decided for a channel that cannot be read (CF-0214)")
        if not isinstance(cfg, dict):
            ap.error(f"--channel {a.channel}: a channel config is a JSON object (CF-0214)")
        channel = cfg.get("channel_id") or Path(a.channel).stem
    else:
        ap.error("no channel: pass --channel channels/<id>.json - the underlay is the "
                 "channel's switch (insert_layers.underlay), and without a channel there is "
                 "nothing to decide it; --force-layer runs the layer on outside any channel, "
                 "for debugging (CF-0214)")
    if channel and not cfg.get("channel_id"):
        cfg = dict(cfg, channel_id=channel)
    plan = plan_underlay(a.video_id, cfg, root=a.root, video_seconds=a.seconds)
    plan["channel"] = channel
    if a.force_layer:
        plan["forced"] = True
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
