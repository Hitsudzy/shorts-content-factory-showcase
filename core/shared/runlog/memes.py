#!/usr/bin/env python3
"""CF-0811 (part c): the meme line of RUN_SUMMARY - how many memes the batch
asked for, how many reached the screen, and why the rest did not.

The user, 18.10: «нету ни одной вставки мемов». With the line nobody has to
open two artifacts to see that: since 08.10 the writer asked for none, and
before that about half the requests were lost at `no_block`. Part (a) made the
writer place one or two (content-researcher `reactions[]`, or a recorded
`meme_none_reason`); part (b) made the editor give each one its block
(video-editor `meme_delivered[]`, `no_block` with a `reason`). This module only
counts what those two stages wrote - it decides nothing about a meme.

Read from the batch's artifacts, like the funnel:

    03-content-researcher.json  scripts[].reactions[]         -> written
                                scripts[].meme_none_reason    -> why zero
    05-video-editor.json        videos[].meme_requested[]     -> requested
                                videos[].meme_delivered[]     -> placed / not
                                videos[].meme_hole_fill.filled[] -> hole fill

* «поставлено» counts the `meme_delivered` answers with `outcome: placed`, not
  the blocks with a meme insert: a span meme (CF-0811 b) sits on several blocks
  and is still one meme.
* hole fills are counted apart - nobody asked for them (CF-0138).
* a batch older than the fields reads «нет данных», never as a zero.

Two warnings, bold like the funnel's SILENT:

* ZERO_WRITTEN - nothing requested in a batch that has scripts, and either a
  script with no reactions carries no `meme_none_reason` (the writer's gate
  stamps the closed gates, so a script with neither had an open gate and wrote
  nothing), or the channel's meme layer is on and every script is zero;
* ZERO_PLACED - memes were requested and none was placed.

`collect()` is the machine half (summary.compute -> "memes", `runlog summary
--json`); `line()` the Markdown one. Neither raises.
"""
import json
from pathlib import Path

__all__ = ["SCRIPTS_FILE", "VIDEOS_FILE", "PLACED", "NO_BLOCK", "REACTIONS_KEY",
           "NONE_REASON_KEY", "WARN_ZERO_WRITTEN", "WARN_ZERO_PLACED", "NO_REASON",
           "collect", "line", "layer_on"]

SCRIPTS_FILE = "03-content-researcher.json"
VIDEOS_FILE = "05-video-editor.json"
# agents/video-editor/scripts/meme_layer.py OUTCOME_PLACED / OUTCOME_NO_BLOCK
PLACED, NO_BLOCK = "placed", "no_block"
# agents/content-researcher/scripts/check_reactions.py (spec field, NONE_REASON_KEY)
REACTIONS_KEY, NONE_REASON_KEY = "reactions", "meme_none_reason"
WARN_ZERO_WRITTEN, WARN_ZERO_PLACED = "zero_written", "zero_placed"
NO_REASON = "без причины"
NO_DATA = "нет данных"


def _read(bd, name):
    p = Path(bd) / name
    if not p.is_file():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def _list(d, key):
    v = (d or {}).get(key)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def layer_on(batch_dir, docs=(), root=None):
    """`(channel, enabled)` of `insert_layers.meme` in the batch's channel
    config, `(channel|None, None)` when it cannot be read. The channel is the
    one the artifacts froze, resolved through former ids like the funnel's
    `target_of`, then the directory the batch sits under."""
    try:
        import runlog
        cid = runlog.sibling("funnel")._channel_ids()
        root = Path(root) if root is not None else runlog.factory_root()
        if cid is None or not (root / "channels").is_dir():
            return None, None
        channel = None
        for d in docs:
            channel = cid.resolve_channel((d or {}).get("channel"), root=root)
            if channel:
                break
        if not channel and batch_dir:
            channel = cid.resolve_channel(Path(batch_dir).parent.name, root=root)
        if not channel:
            return None, None
        cfg = json.loads(Path(cid.channel_config_path(channel, root=root)).read_text(
            encoding="utf-8"))
        meme = ((cfg or {}).get("insert_layers") or {}).get("meme")
        if not isinstance(meme, dict):
            return channel, None
        return channel, meme.get("enabled") is True
    except Exception:                                       # noqa: BLE001
        return None, None


def _bump(d, k):
    d[k] = d.get(k, 0) + 1


def _sorted(d):
    return dict(sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))


def collect(batch_dir=None, root=None, layer=None):
    """The counts as data, or None when the batch has neither artifact (or no
    directory at all) - the line is then silent, like the quota's.

    `layer`: `(channel, enabled)` to skip the config lookup (tests)."""
    if not batch_dir:
        return None
    try:
        return _collect(batch_dir, root, layer)
    except Exception as e:                                  # noqa: BLE001
        return {"available": False, "error": f"{e.__class__.__name__}: {e}", "warnings": []}


def _collect(batch_dir, root, layer):
    d03, d05 = _read(batch_dir, SCRIPTS_FILE), _read(batch_dir, VIDEOS_FILE)
    if d03 is None and d05 is None:
        return None
    scripts, videos = _list(d03, "scripts"), _list(d05, "videos")
    # Which halves carry the fields at all. A batch before CF-0067 has
    # neither; one before CF-0811 has reactions/meme_requested but never a
    # meme_none_reason - its zeros were never explained, not unexplained.
    writer_known = any(REACTIONS_KEY in s or NONE_REASON_KEY in s for s in scripts)
    reasons_known = any(NONE_REASON_KEY in s for s in scripts)
    editor_known = any("meme_requested" in v or "meme_delivered" in v for v in videos)
    out = {"available": writer_known or editor_known,
           "scripts": len(scripts), "videos": len(videos),
           "writer_known": writer_known, "reasons_known": reasons_known,
           "editor_known": editor_known}

    written, with_memes, none_reasons = 0, 0, {}
    for s in scripts:
        r = s.get(REACTIONS_KEY)
        n = len([x for x in r if isinstance(x, dict)]) if isinstance(r, list) else 0
        written += n
        if n:
            with_memes += 1
        else:
            _bump(none_reasons, s.get(NONE_REASON_KEY) or NO_REASON)
    out.update(written=written, scripts_with_memes=with_memes,
               none_reasons=_sorted(none_reasons),
               zero_unexplained=none_reasons.get(NO_REASON, 0) if reasons_known else None)

    requested, placed, not_placed, hole = 0, 0, {}, 0
    for v in videos:
        req = v.get("meme_requested") if isinstance(v.get("meme_requested"), list) else []
        ans = v.get("meme_delivered") if isinstance(v.get("meme_delivered"), list) else []
        requested += len(req)
        for i in range(len(req)):
            a = ans[i] if i < len(ans) and isinstance(ans[i], dict) else {}
            oc = a.get("outcome") or "unanswered"
            if oc == PLACED:
                placed += 1
                continue
            _bump(not_placed, f"{oc}/{a['reason']}" if oc == NO_BLOCK and a.get("reason")
                  else oc)
        hf = v.get("meme_hole_fill")
        if isinstance(hf, dict) and isinstance(hf.get("filled"), list):
            hole += len(hf["filled"])
    out.update(requested=requested if editor_known else None,
               placed=placed if editor_known else None,
               not_placed=_sorted(not_placed), hole_fill=hole)

    channel, on = layer if layer is not None else layer_on(batch_dir, (d05, d03), root=root)
    out.update(channel=channel, layer_on=on)

    warnings = []
    asked = requested if editor_known else written
    if out["available"] and scripts and asked == 0 and written == 0:
        if reasons_known and none_reasons.get(NO_REASON):
            warnings.append(WARN_ZERO_WRITTEN)
        elif on is True:
            warnings.append(WARN_ZERO_WRITTEN)
    if editor_known and requested > 0 and placed == 0:
        warnings.append(WARN_ZERO_PLACED)
    out["warnings"] = warnings
    return out


def _breakdown(d):
    return ", ".join(f"{k}×{n}" for k, n in d.items())


def line(m):
    """The RUN_SUMMARY line, or None (silent) when `collect` returned None."""
    if m is None:
        return None
    if m.get("error"):
        return f"MEMES: {NO_DATA} - не прочитано ({m['error']})"
    if not m.get("available"):
        return (f"MEMES: {NO_DATA} - в {SCRIPTS_FILE} нет reactions/{NONE_REASON_KEY}, "
                f"в {VIDEOS_FILE} нет meme_requested (батч старше этих полей)")
    if m["editor_known"]:
        bits = [f"запрошено {m['requested']}"]
        if m["writer_known"] and m["written"] != m["requested"]:
            bits[0] += f" (сценарист отметил {m['written']})"
        placed = f"поставлено {m['placed']}"
        if m["hole_fill"]:
            placed += f" (+{m['hole_fill']} hole fill)"
        bits.append(placed)
        if m["not_placed"]:
            bits.append("не поставлено: " + _breakdown(m["not_placed"]))
    else:
        bits = [f"запрошено {m['written']} (сценарист; {VIDEOS_FILE} без meme_requested)",
                f"поставлено {NO_DATA}"]
    zero = sum(m["none_reasons"].values())
    if zero:
        if m["reasons_known"]:
            bits.append("без мема: " + _breakdown(m["none_reasons"]))
        else:
            bits.append(f"без мема: {zero} сценари{'й' if zero == 1 else 'ев'}, причина не "
                        f"записывалась (до CF-0811)")
    text = "MEMES: " + " · ".join(bits)
    warn = []
    if WARN_ZERO_WRITTEN in m["warnings"]:
        why = []
        if m.get("zero_unexplained"):
            why.append(f"у {m['zero_unexplained']} без {NONE_REASON_KEY}")
        if m.get("layer_on") is True:
            why.append(f"слой мемов включён (channels/{m.get('channel')}.json)")
        warn.append(f"**НОЛЬ МЕМОВ: сценарист не отметил ни одного в {m['scripts']} "
                    f"сценари{'и' if m['scripts'] == 1 else 'ях'} - " + "; ".join(why) + "**")
    if WARN_ZERO_PLACED in m["warnings"]:
        warn.append(f"**НОЛЬ ПОСТАВЛЕНО: ни один из {m['requested']} запрошенных мемов "
                    f"не дошёл до экрана**")
    return " - ".join([text] + warn)
