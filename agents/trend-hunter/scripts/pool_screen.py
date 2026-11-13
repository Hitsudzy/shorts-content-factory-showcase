#!/usr/bin/env python3
"""CF-0325: screen pool sources with the Video Editor's own pre-cut gate.

Run by `pool_coverage.py` as a child, under the Footage Indexer's interpreter
(`agents/footage-indexer/.venv`), because the gate lives behind
`footage-indexer/scripts/pool_depth.py` -> `video-editor/scripts/resolve_anchors.py`
and that import needs PIL, which this repo's venv does not carry. Nothing is
copied: the count is `pool_depth.screen_shots()` - the same number the indexer's
walk stops on (CF-0304) - over the shots of each source **minus the shots that
already went into a finished video** (`pipeline/<channel>/retired-shots.json`,
CF-0397), because a retired shot is refused by `resolve_anchors` for every
other video and so is not pool any more.

stdin:  {"cache": "<shared/footage>", "indexer_scripts": "<dir>",
         "sources": {"<video_id>": [<retired shot index>, ...], ...}}
stdout: {"floor": <pool_depth.POOL_DEPTH_FLOOR>, "error": null | "<why not>",
         "sources": {"<video_id>": {"shots", "retired", "usable", "seconds",
                                    "cards", "error"}}}

When the gate cannot be imported the answer still comes back, with `error`
set and `usable: null` on every source - the caller ranks on the source count
then, and says so.
"""
import json
import sys
from pathlib import Path


def main():
    req = json.load(sys.stdin)
    cache = Path(req["cache"])
    sys.path.insert(0, req["indexer_scripts"])
    gate_error = None
    try:
        import pool_depth  # noqa: E402
        gate_error = pool_depth.import_error()
        floor = pool_depth.POOL_DEPTH_FLOOR
    except Exception as exc:  # pragma: no cover - only when the sibling repo is gone
        pool_depth, floor = None, None
        gate_error = f"{type(exc).__name__}: {exc}"
    out = {}
    for vid, retired in (req.get("sources") or {}).items():
        retired = {int(i) for i in retired or ()}
        try:
            shots = (json.load(open(cache / f"{vid}.shots.json")) or {}).get("shots") or []
        except Exception as exc:
            out[vid] = {"shots": 0, "retired": 0, "usable": None, "seconds": None,
                        "cards": None, "error": f"{type(exc).__name__}: {exc}"}
            continue
        live = [s for s in shots if s.get("index") not in retired]
        rec = {"shots": len(live), "retired": len(shots) - len(live), "usable": None,
               "seconds": None, "cards": None, "error": None}
        if pool_depth is not None and not gate_error:
            try:
                rec["usable"], rec["seconds"], rec["cards"] = pool_depth.screen_shots(live)
            except Exception as exc:
                rec["error"] = f"{type(exc).__name__}: {exc}"
        out[vid] = rec
    json.dump({"floor": floor, "error": gate_error, "sources": out}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
