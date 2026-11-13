#!/usr/bin/env python3
"""CF-0435: a weak shot is ranked and priced, not refused.

Up to this task the usability bundle was a gate at three places of this repo:
the resolver's pre-cut filter (`resolve_anchors.precut_cache_refusal`, on the
pool's cached measurements), the resolver's `usable()` on the cut clip and
`build_render_plan.py`'s asset gate (both on qc_asset.py's verdict of the real
frame). Framing under 0.65, mean luma under 28 or a delivery height under 720
took the shot out, and batch `example-film/2026-09-29T0929Z` reached the writer
with 42 % of its raw footage. The grill of 2026-09-29 (Q16, Q19 step 4) moved
the bundle onto the score model of CF-0432: the Editor takes the best shot it
has, and the video pays for every weak one that reaches the screen.

What this module decides, once for the three places:

  * **the rank** of a candidate among the ones that picture its phrase -
    `rank()`: clean shots first, weak ones after them by their usability score,
    the matcher's order kept among equals. The score is the Footage Indexer's
    (`footage-indexer/scripts/shot_usability.py`, `of()`), derived on the fly
    from what the shot stores - the pool's old indexes carry no `usability`
    field and are never re-measured for one (the pool is transient). A cache
    the running code did not measure (`cache_fingerprint`, CF-0048) is judged
    on the describer's flags alone (`measurements=False`).
  * **hard or soft** for one qc_asset.py verdict - `split_verdict()`. Soft:
    `coverage` (score.low_framing), `luma` (score.low_brightness),
    `resolution` (score.low_resolution). Everything else stays hard and still
    refuses: `subject` (an empty frame - nothing to look at), `black` (a dead
    frame over the clip ceiling), `crop_framing` (our own caption crop runs
    through the faces, CF-0092), a tool that hung (CF-0077). A verdict with
    any hard key is refused whole, with all its lines, exactly as before.
  * **what the video pays** - `plan_findings()`: one finding per soft rule per
    distinct shot on screen (a block's own shot, every cut of a sequence, every
    cut of a side-by-side half), priced `score.<rule>` in
    `shared/gate-prices.json` with the table's caps. The measured rules come
    from the real clip (the resolver's probes and the plan's own frame), never
    from the cache: the cache ranks, the clip is what the viewer sees.
    `score.off_topic_shot` comes from the describer's `on_topic: false` (a
    shot that shows a supplement's entity is not off the topic, CF-0344).

The hard list of the pool stays where it was: `burned_text` is
`entity_guard.refusal()`'s (CF-0351), a supplement shot without its entity is
too (CF-0348, somebody else's film), and `text_cut_by_crop` (CF-0275) is the
resolver's - cut words on screen are foreign text, not a weak shot.

Stdlib only; the indexer's module is loaded by path, like `code_reach`
(cache_fingerprint.py), because a worktree has no sibling one `..` away.
"""
import ast
import importlib.util
import sys
from pathlib import Path

from repo_paths import INDEXER_SCRIPTS  # CF-0125: beside the main checkout
import wide_place  # CF-0352: a wide shot of a place is not low framing

TASK = "CF-0435"
FIELD = "usability"   # the storyboard's per-picture record (block, cut)

SHOT_USABILITY = INDEXER_SCRIPTS / "shot_usability.py"

LOW_FRAMING = "low_framing"
LOW_BRIGHTNESS = "low_brightness"
LOW_RESOLUTION = "low_resolution"
OFF_TOPIC_SHOT = "off_topic_shot"
SOFT_RULES = (LOW_FRAMING, LOW_BRIGHTNESS, LOW_RESOLUTION, OFF_TOPIC_SHOT)

# qc_asset.evaluate()'s `failed` keys that cost points instead of the shot.
SOFT_QC = {"coverage": LOW_FRAMING, "luma": LOW_BRIGHTNESS,
           "resolution": LOW_RESOLUTION}

_MEMO = {}

# CF-0452: sharpness (the indexer's `sharpness.py`, part 1 of the task).
SHARPNESS = INDEXER_SCRIPTS / "sharpness.py"
SHARPNESS_TASK = "CF-0452"
LOW_SHARPNESS = "low_sharpness"
SHARPNESS_FIELD = "sharpness_cached"   # on a shots.json entry
# On-the-fly measures (a shot of the old pool carries no record): the top
# candidates of one rank() only, and a ceiling per run - one measure is
# ~1-2 s (`sharpness.measure(..., n=5)`), so a video pays at most
# SHARPNESS_PROBES_PER_RUN of them; a shot measured once is not again.
SHARPNESS_PROBES_PER_RANK = 3
SHARPNESS_PROBES_PER_RUN = 60
SHARPNESS_SAMPLES = 5


def price_key(rule):
    return f"score.{rule}"


def _indexer_siblings(path):
    """The top-level imports of the indexer file `path` that are themselves
    files of INDEXER_SCRIPTS - the modules a by-path load must supply,
    because INDEXER_SCRIPTS is not on this process's sys.path."""
    try:
        tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return []
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            found = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found = [node.module.split(".")[0]]
        else:
            continue
        for name in found:
            if name not in names and (INDEXER_SCRIPTS / f"{name}.py").exists():
                names.append(name)
    return names


def _load_indexer_module(name, loading=()):
    """footage-indexer's `<name>.py` loaded by path, with the indexer modules
    it imports (`_indexer_siblings`) loaded the same way first and handed to
    it through sys.modules for the duration of its import only.

    CF-0451's regression: `shot_usability.py` grew `import screen_recording`
    and `import sharpness` (CF-0451, CF-0452). A plain by-path load of it then
    raised ModuleNotFoundError - INDEXER_SCRIPTS is deliberately not on
    sys.path (cache_fingerprint.code_reach() says why: it would shadow this
    repo's own `_runlog.py` & co.) - `indexer()` swallowed it as "no indexer",
    and every fresh cache stopped refusing a black or an empty frame with no
    word said. The siblings are put in sys.modules only while the importing
    module executes and the previous entries are restored afterwards, so
    nothing of the indexer leaks into this process's later imports; the
    loaded module keeps its references as its own globals."""
    if name in loading:
        raise ImportError(f"import cycle in footage-indexer: "
                          f"{' -> '.join(loading + (name,))}")
    path = INDEXER_SCRIPTS / f"{name}.py"
    deps = {dep: _load_indexer_module(dep, loading + (name,))
            for dep in _indexer_siblings(path) if dep != name}
    saved = {dep: sys.modules.get(dep, _ABSENT) for dep in deps}
    try:
        sys.modules.update(deps)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        for dep, prev in saved.items():
            if prev is _ABSENT:
                sys.modules.pop(dep, None)
            else:
                sys.modules[dep] = prev
    return mod


_ABSENT = object()


def indexer():
    """footage-indexer's `shot_usability` module, or None when it is not
    beside the main checkout (then nothing is ranked or priced from the
    cache - an unknown shot is neither clean nor doomed).

    The file being there and still not loading is not "no indexer": it is
    said once on stderr, because the effect is otherwise invisible - every
    cached black/empty frame stops being refused and nothing is ranked
    (the CF-0451 regression, see `_load_indexer_module`)."""
    if "mod" not in _MEMO:
        mod = None
        try:
            mod = _load_indexer_module("shot_usability")
        except (OSError, ImportError, AttributeError, SyntaxError) as exc:
            mod = None
            if SHOT_USABILITY.exists():
                print(f"  shot_score: {SHOT_USABILITY} is there but does not "
                      f"load ({type(exc).__name__}: {exc}) - the pool's "
                      f"usability record is not read: nothing ranked, no "
                      f"cached black/empty frame refused", file=sys.stderr)
        _MEMO["mod"] = mod
    return _MEMO["mod"]


def usability(shot, fresh=True):
    """`shot_usability.of(shot)` - the pool's verdict on one shot from what it
    stores now. `fresh=False` (a cache the running code did not measure)
    judges the flags alone. None without the indexer or without a shot."""
    mod = indexer()
    if mod is None or not isinstance(shot, dict):
        return None
    return mod.of(shot, measurements=bool(fresh))


def cached_hard(shot, fresh=True):
    """The hard rules the pool's own record finds on this shot (black, empty,
    burned-in text) as a list of rule dicts; [] when there are none or the
    indexer is not there."""
    u = usability(shot, fresh)
    return list((u or {}).get("hard") or [])


def rank_key(shot, fresh=True, video=None, wide=False):
    """Sort key of one candidate: hard ones last, then by usability score,
    best first, then (CF-0452) a blurry shot behind a sharp one of the same
    score. A shot nobody can judge ranks as clean (1.0). CF-0436: the score is
    the one the viewer gets (`viewer_rank_key`). CF-0352: `wide` - the
    candidate pictures a place anchor - drops `low_framing` from a shot whose
    subject box is not a face (`wide_place`)."""
    # CF-0436: priced as the viewer will see it - a framing or brightness
    # fault a presentation fixes costs the presentation, not the rule.
    u = usability(shot, fresh)
    if wide and wide_place.wide_ok(wide_place.shot_roi_source(shot)):
        u = wide_place.waive_record(u)
    return viewer_rank_key(u, blur=blur_rank(u, shot, video))


def rank(pool, shot_of, fresh_of=None, video_of=None,
         probes=SHARPNESS_PROBES_PER_RANK, wide_of=None, lead=None,
         lead_floor=None, mild_from=None, pinned=None):
    """`pool` re-ordered by usability, stable - so among equally usable shots
    the matcher's order (similarity) holds. `shot_of(cand)` returns the
    shots.json entry, `fresh_of(shot)` whether its cache may be believed.

    CF-0452: `video_of(cand)` is the candidate's source file. A shot of the
    top `probes` that carries no fresh `sharpness_cached` (the old pool) is
    measured on the fly (`probe_sharpness`) - only those, never the whole
    pool - and the order is taken again; a blurry one drops behind the sharp
    ones of its score. Without the indexer's `sharpness.py` nothing is
    measured and the order is CF-0436's.

    CF-0352: `wide_of(cand)` says the candidate pictures a place anchor - its
    shot is ranked without `low_framing` when it has no face (`rank_key`).

    CF-0517: `lead(cand)` is a key ranked *before* the usability score and
    after the hard tier - `(hard, lead, -score, blur)`. A one-shot block
    passes "too short for the block" here, so a long-enough shot goes ahead
    of a shorter, cleaner one (length first, then usability), and a hard
    shot stays behind every other however long it is. The sharpness probes
    then measure the top of *that* order.

    `lead_floor` - the usability score (the viewer's, `viewer_rank_key`) a
    shot needs for its `lead` to count: below it the shot is ranked as if
    `lead` were True (behind every shot that leads, by its score among the
    rest). A long shot priced near zero does not jump a clean short one.

    CF-0537 (delver 0701Z, "6 секунда выглядит будто экранка"): nor does a
    blurry one - a shot `blur_rank()` finds `low_sharpness` (warned while
    the price is unsigned, so its usability score is untouched) ranks with
    the short ones too: behind a sharp shot of its usability score, ahead of
    a short blurry one of the same score and sharpness. An order of this
    stage, not a price: nothing is charged for it.

    CF-0648 (delver 1824Z, block 7: a 1.17 s shot held still on a 2.91 s
    block while four long-enough shots, all `low_sharpness`, sat behind it):
    two tiers between "leads" and "ranks with the short ones", asked for by
    a one-shot block that cannot be split into several shots (its short shot
    is a frame held for the whole block, not a split, CF-0480) -

    * `pinned(cand)` - a short shot that is the anchor's own picture (its
      description is the phrase) goes ahead of a mildly blurry long one
      (and so of the short ones); not ahead of a sharp long one (CF-0517
      stands). Only while it clears `lead_floor`, is not found blurry
      itself, and a mildly blurry long shot is in the pool - without one
      the short ones keep their old order (an accepted video's held frame
      does not change picture for it: east-of-eden 0701Z block 11);
    * `mild_from` - a long shot found blurry at or above this sharpness
      keeps its lead over the short ones (behind every sharp long one and
      the pinned anchor): a moving clip just under the floor instead of a
      frame held still for the whole block. Under it, CF-0537 stands.

    Without either the key is CF-0537's: `(hard, 0|3, -score, blur, ...)`
    with 0 for a shot that leads and 3 for one that does not."""
    def key(cand):
        shot = shot_of(cand)
        fresh = fresh_of(shot) if (fresh_of and shot) else True
        k = rank_key(shot, fresh, video_of(cand) if video_of else None,
                     wide=bool(wide_of and wide_of(cand)))
        if lead is None:
            return k
        short = bool(lead(cand))
        led = short
        under = lead_floor is not None and -k[1] < lead_floor
        if under:
            led = True
        tier = 3 if led else 0
        if k[2] > 0:
            # CF-0537: a blurry shot (low_sharpness, warned or priced) does
            # not lead on length either - it ranks with the short ones, so a
            # sharp shot of its score goes first (blur is the next key), and
            # among blurry ones of one score and sharpness the long one.
            # CF-0648: unless the caller holds a short shot still for the
            # whole block and this one is only mildly blurry.
            tier = 2 if (not led and mild_from is not None
                         and 2.0 - k[2] >= mild_from) else 3
        elif short and not under and pinned is not None and pinned(cand):
            tier = 1   # CF-0648: the anchor's own picture, short
        return (k[0], tier) + tuple(k[1:]) + (short and k[2] > 0,)
    ordered = _sorted(pool, key)
    if video_of is None or not probes or sharpness_module() is None:
        return ordered
    spent = 0
    while spent < probes:
        todo = next((c for c in ordered[:probes]
                     if _wants_probe(c, shot_of(c), video_of(c))), None)
        if todo is None:
            break
        probe_sharpness(shot_of(todo), video_of(todo))
        spent += 1
        ordered = _sorted(pool, key)
    return ordered


def _sorted(pool, key):
    """CF-0648: `pool` by `key`; a pinned tier (1) counts only while the
    pool has a mildly blurry long shot (tier 2) for it to go ahead of."""
    keys = [(key(c), i) for i, c in enumerate(pool)]
    if not any(k[1] == 2 for k, _ in keys):
        keys = [((k[0], 3) + k[2:] if k[1] == 1 else k, i) for k, i in keys]
    return [pool[i] for _, i in sorted(keys)]


def split_verdict(qc):
    """`(hard_failures, soft_rules)` of one qc_asset.py verdict (or
    build_render_plan's info["qc"]). Usable -> `([], [])`. Only soft keys
    failed -> `([], [rule, ...])`: the picture is shown and priced. Anything
    else -> `(failures, [])`, refused with every line, as before CF-0435."""
    qc = qc or {}
    if qc.get("usable"):
        return [], []
    failed = list(qc.get("failed") or [])
    if failed and all(k in SOFT_QC for k in failed):
        rules = []
        for k in failed:
            if SOFT_QC[k] not in rules:
                rules.append(SOFT_QC[k])
        return [], rules
    return list(qc.get("failures") or ["unusable (no failure recorded)"]), []


def flag_rules(shot):
    """The soft rules a shot carries on its flags, whatever was measured:
    `off_topic_shot` for `on_topic: false` on a shot that does not show a
    supplement's entity (the indexer's rule, CF-0435 item 2)."""
    u = usability(shot, fresh=False)
    if u is not None:
        return [v["rule"] for v in u.get("soft") or [] if v.get("rule") in SOFT_RULES]
    if (isinstance(shot, dict) and shot.get("on_topic") is False
            and shot.get("shows_entity") is not True):
        return [OFF_TOPIC_SHOT]
    return []


def record(shot, measured=(), video=None, held=False):
    """The storyboard's `usability` record of one picture put on screen:
    `measured` are the soft rules the real clip failed (`split_verdict`), the
    shot's flags add `off_topic_shot`. CF-0452: the shot's fresh sharpness
    record (or this run's on-the-fly measure of `video`) adds
    `low_sharpness` - `warn` until the price is signed (`with_sharpness`).
    None for a clean picture, so a clean storyboard reads as it always did."""
    rules = []
    for r in list(measured or ()) + flag_rules(shot):
        if r in SOFT_RULES and r not in rules:
            rules.append(r)
    base = None
    if rules:
        mod = indexer()
        table = mod.prices() if mod is not None else {}
        penalty = sum(table.get(r, 0) for r in rules)
        base = {"task": TASK, "soft": rules, "penalty": penalty,
                "score": max(0.0, round(1.0 - penalty / 100.0, 4))}
    verdict = sharpness_verdict(shot, video, held=held)
    if verdict is None:
        return base
    return with_sharpness(base, verdict)


def _pictures(block):
    """`(shot key, usability record)` for every picture a storyboard/plan
    block shows: the block itself, its sequence `cuts`, the cuts of each
    side-by-side half (`split`)."""
    out = [(block.get("shot"), block.get(FIELD))]
    for c in block.get("cuts") or []:
        if isinstance(c, dict):
            out.append((c.get("shot"), c.get(FIELD)))
    for h in block.get("split") or []:
        if not isinstance(h, dict):
            continue
        for c in h.get("cuts") or []:
            if isinstance(c, dict):
                out.append((c.get("shot"), c.get(FIELD)))
    return out


def plan_findings(blocks, extra=None, finding=None, in_hook=None,
                  presented=None):
    """CF-0435: the plan stage's price of the weak shots on screen. One
    finding per soft rule per distinct shot (a shot held or shown twice is
    one weak shot - its repeat is `score.repeated_shot`'s), at the first block
    that shows it. `extra` is `{(block index, shot key): {rule, ...}}` - what
    build_render_plan's own frame found beyond the resolver's record.
    `finding` / `in_hook` are `_score.finding` / `_score.in_hook` (passed in
    so this module stays free of the score model). CF-0436: `presented` is
    `{(block index, shot key): {mode, ...}}` - the presentations the plan
    showed that picture with; the soft rule a presentation removes is not
    charged there (`presentation_findings` prices the presentation). Pure."""
    if finding is None or in_hook is None:
        import _score
        finding = finding or _score.finding
        in_hook = in_hook or _score.in_hook
    extra = extra or {}
    presented = presented or {}
    seen, out = set(), []
    for i, b in enumerate(blocks or []):
        if not isinstance(b, dict):
            continue
        t0 = b.get("_start", b.get("start"))
        pics = _pictures(b)
        for (bi, key), rules in extra.items():
            if bi == i:
                pics.append((key, {"soft": sorted(rules)}))
        for key, rec in pics:
            if not key or not isinstance(rec, dict):
                continue
            for rule in rec.get("soft") or []:
                if rule == LOW_SHARPNESS:
                    # CF-0452: in `soft` only once signed; charged only while
                    # the root's table carries the row (never written here).
                    if (key, rule) in seen or not _priced(price_key(rule)):
                        continue
                elif rule not in SOFT_RULES or (key, rule) in seen:
                    continue
                if rule not in viewer_rules([rule], presented.get((i, key))):
                    continue   # CF-0436: shown so the viewer does not see it
                seen.add((key, rule))
                where = {"block": i, "shot": key}
                if isinstance(t0, (int, float)):
                    where["t"] = round(t0, 3)
                out.append(finding(price_key(rule), where, hook=in_hook(t0),
                                   note=f"shot {key}: {rule.replace('_', ' ')} "
                                        f"- the best the pool had (CF-0435)"))
    return out


# --------------------------------------------------------------------------
# CF-0436: presentation instead of a price - the penalty is what the viewer
# sees. Grill 2026-09-29, Q26: part of a weak shot is fixed by how it is shown.
#
#   * `blur_fill` - a wide shot the 9:16 crop cuts (`low_framing`, or a crop
#     that would run through the hero - QC's `crop_cuts_subject`) is shown
#     WHOLE across the width, over a blurred, enlarged copy of the same frame.
#     Nothing is cropped away, so the framing rule has nothing to charge.
#     The asset goes out `fit: contain` (every "is the subject cut?" gate of
#     qc_render already stands down for a contained picture) and carries the
#     picture's rectangle (`rect`, output px) for the renderer and for QC.
#   * `luma_lift` - a dark shot (`low_brightness`, mean luma under the
#     qc_asset floor of 28) is multiplied up in brightness (CSS
#     `brightness(gain)`, the same arithmetic as PIL's ImageEnhance
#     Brightness the plan measures the lifted probe with) to LUMA_LIFT_TARGET,
#     never past LUMA_LIFT_MAX_GAIN. A frame the capped gain cannot bring over
#     the floor is not "fixed" and is shown as it is, priced.
#
# A presentation is not free: `score.presentation_<mode>` in
# shared/gate-prices.json (DEFAULT_PRESENTATION_PRICE while the table has no
# such row). The Editor takes it only when it costs less than the soft rule it
# removes - one comparison per picture, on the table's per-shot prices.
# --------------------------------------------------------------------------

BLUR_FILL = "blur_fill"
LUMA_LIFT = "luma_lift"
PRESENTATIONS = (BLUR_FILL, LUMA_LIFT)
PRESENTATION_FIELD = "presentation"     # on a plan asset / sequence cut
PRESENTATION_TASK = "CF-0436"
# The soft rule each presentation removes from what the viewer sees.
FIXES = {BLUR_FILL: LOW_FRAMING, LUMA_LIFT: LOW_BRIGHTNESS}
DEFAULT_PRESENTATION_PRICE = 1
# Draft soft prices when neither the indexer nor the table can be read
# (shot_usability.DEFAULT_PRICES).
DEFAULT_SOFT_PRICES = {LOW_FRAMING: 3, LOW_BRIGHTNESS: 3, LOW_RESOLUTION: 2,
                       OFF_TOPIC_SHOT: 4}

LUMA_FLOOR = 28           # qc_asset.MIN_MEAN_LUMA (a test pins them equal)
LUMA_LIFT_TARGET = 40     # clear of the floor, still a dark scene
LUMA_LIFT_MAX_GAIN = 3.0  # past it a compressed dark frame is mostly noise

# The blurred ground: how much the background copy is blurred (output px),
# how far it is scaled past `cover` so the blur never shows its edge, and
# how much it is dimmed so the whole picture in the middle is what the eye
# takes. The renderer reads these off the plan (`blur_fill` detail).
BLUR_FILL_BLUR_PX = 48
BLUR_FILL_BG_SCALE = 1.15
BLUR_FILL_BG_DIM = 0.55


def presentation_key(mode):
    return f"score.presentation_{mode}"


def _table_rules():
    if "rules" not in _MEMO:
        rules = {}
        try:
            import json
            import _score
            root = _score.factory_root()
            if root is not None:
                rules = (json.loads((root / "shared" / "gate-prices.json")
                                    .read_text()) or {}).get("rules") or {}
        except Exception:  # an unreadable table prices from the defaults
            rules = {}
        _MEMO["rules"] = rules
    return _MEMO["rules"]


def _price(key, default):
    price = ((_table_rules().get(key) or {}).get("penalty") or {}).get("price")
    if isinstance(price, (int, float)) and not isinstance(price, bool):
        return price
    return default


def presentation_price(mode):
    """Points one picture shown with `mode` costs: the table's
    `score.presentation_<mode>`, else DEFAULT_PRESENTATION_PRICE."""
    return _price(presentation_key(mode), DEFAULT_PRESENTATION_PRICE)


def soft_price(rule):
    """Points one weak picture costs for `rule` as it is."""
    mod = indexer()
    if mod is not None:
        try:
            return mod.prices().get(rule, DEFAULT_SOFT_PRICES.get(rule, 0))
        except Exception:
            pass
    return _price(price_key(rule), DEFAULT_SOFT_PRICES.get(rule, 0))


def luma_gain(luma, floor=LUMA_FLOOR, target=LUMA_LIFT_TARGET,
              max_gain=LUMA_LIFT_MAX_GAIN):
    """The brightness gain that lifts a frame of mean luma `luma` to
    `target`, capped at `max_gain`; None when even the capped gain leaves it
    under `floor` (or the luma is unknown) - such a frame is not fixed by
    lifting and goes on screen as it is, priced."""
    if not isinstance(luma, (int, float)) or isinstance(luma, bool) or luma <= 0:
        return None
    gain = min(float(max_gain), max(1.0, float(target) / float(luma)))
    if luma * gain < floor:
        return None
    return round(gain, 3)


def worth(mode):
    """True when showing a picture with `mode` costs less than the soft rule
    it removes - the Editor's comparison, on the table's per-shot prices."""
    return presentation_price(mode) < soft_price(FIXES[mode])


def choose(rules, luma=None):
    """`{mode: detail}` of the presentations one picture is shown with, from
    the soft rules it fails (`rules`) and its measured mean luma. `{}` for a
    picture shown as it is. `luma_lift`'s detail carries its `gain`. Pure
    apart from the price table."""
    rules = set(rules or ())
    out = {}
    if LOW_FRAMING in rules and worth(BLUR_FILL):
        out[BLUR_FILL] = {}
    if LOW_BRIGHTNESS in rules and worth(LUMA_LIFT):
        gain = luma_gain(luma)
        if gain is not None and gain > 1.0:
            out[LUMA_LIFT] = {"gain": gain}
    return out


def viewer_rules(rules, presentation):
    """The soft rules the viewer still sees once `presentation` (a mode list
    or the plan's `{mode: detail}`) is applied."""
    fixed = {FIXES[m] for m in (presentation or ()) if m in FIXES}
    return [r for r in (rules or ()) if r not in fixed]


def blur_fill_rect(source_size, box):
    """The rectangle (output px, ints) the whole picture occupies in a
    `blur_fill` block: `source_size` contained in `box` = `(x, y, w, h)`,
    centred - meme_captions.contained_picture() over the insert box, so the
    picture ends above the caption band exactly as an insert does. None when
    the size is unknown."""
    try:
        sw, sh = float(source_size["width"]), float(source_size["height"])
    except (KeyError, TypeError, ValueError):
        return None
    x, y, bw, bh = box
    if sw <= 0 or sh <= 0 or bw <= 0 or bh <= 0:
        return None
    scale = min(bw / sw, bh / sh)
    w, h = int(round(sw * scale)), int(round(sh * scale))
    return {"x": int(round(x + (bw - w) / 2)), "y": int(round(y + (bh - h) / 2)),
            "width": w, "height": h}


def blur_fill_detail(source_size, box):
    """The plan's `blur_fill` record: the picture's `rect` and the ground's
    look. None when the rect cannot be computed (the picture is then shown
    as it is)."""
    rect = blur_fill_rect(source_size, box)
    if rect is None:
        return None
    return {"rect": rect, "blur_px": BLUR_FILL_BLUR_PX,
            "bg_scale": BLUR_FILL_BG_SCALE, "bg_dim": BLUR_FILL_BG_DIM}


# --------------------------------------------------------------------------
# CF-0903: a blur_fill picture is a strip, and the strip has a price of its own.
#
# A 16:9 picture shown whole is 0.317 of the screen's height, a 2.39:1 one
# 0.235 - under the root's `strip_on_blur.STRIP_SHARE` (0.33), so every
# blur_fill of a trailer frame is the strip the user refuses
# (`narrow_strip_on_blur`, 13 refusals by 30.10 - more than any other code).
# `worth(BLUR_FILL)` compares one picture's presentation (1) with its
# `low_framing` (3), and never with `score.narrow_strip_on_blur` (signed
# 2026-10-27: -2 per second of strip over 5 s), which the video pays for the
# sum of its strips.
#
# The replay of the 12 refusals' plans (18.10-30.10): 186 of 274 strip
# seconds were pictures whose OWN probe (the cut clip at the plan's framing)
# keeps the subject in the 9:16 crop - the `low_framing` came from the
# picture's record alone. CF-0904 checked whose record: not the pool's cache
# (`usable_cached.roi_coverage` agrees with the plan's probe on 889 of 917
# pictures of 18.10-30.10, and on 184 of these 186 strip seconds), but the
# resolver's - usable() judges PROBE_FRAMES frames of the cut clip and one
# later frame under the floor puts `low_framing` on the record, while the
# plan frames the clip from the first. `pool_record` below names that record.
# After the take-back 10 of the 12 plans are under a third (9 under 25 %);
# wildwood 0840Z, the-long-voyage 1624Z and sandfall-part-three 0841Z keep 27-36 % of
# strips the probe itself asked for (2.2-2.39:1 trailers, the subject wider
# than the crop) - a choice of other shots, not of presentation.
# So a blur_fill decided on the record alone is marked
# (`framed_by: pool_record`), and once the plan's strip seconds run past
# STRIP_ALLOW_SECONDS such pictures go back to the crop the probe found
# keeping the subject - longest first, until the strip is within the
# allowance or none is left. Their `low_framing` is charged again at its own
# price (nothing new is priced or refused). A blur_fill the probe itself
# asked for (the crop would cut the subject) is never taken back.
# --------------------------------------------------------------------------

STRIP_TASK = "CF-0903"
STRIP_SHARE = 0.33           # root shared/strip_on_blur.STRIP_SHARE
STRIP_ALLOW_SECONDS = 5.0    # root shared/strip_on_blur.ALLOW_SECONDS (signed 2026-10-27)
FRAMED_BY = "framed_by"      # on a blur_fill detail: who found the framing low
FRAMED_BY_PROBE = "probe"
FRAMED_BY_RECORD = "pool_record"
_CUTOUT_PLACEMENTS = ("cutout_on_subject", "cutout_in_corner")


def strip_share(target, screen_height=1920):
    """The picture's height over the screen's: a blur_fill rect's height, a
    `contain` picture fitted whole into 1080 wide, else 1.0 (a cover crop) -
    strip_on_blur.picture_share() for one plan target."""
    target = target or {}
    rect = ((target.get(PRESENTATION_FIELD) or {}).get(BLUR_FILL) or {}).get("rect")
    if isinstance(rect, dict) and isinstance(rect.get("height"), (int, float)):
        return round(min(1.0, rect["height"] / float(screen_height)), 3)
    if target.get("fit") == "contain":
        ss = target.get("source_size") or {}
        try:
            w, h = float(ss["width"]), float(ss["height"])
        except (KeyError, TypeError, ValueError):
            return 1.0
        if w > 0 and h > 0:
            width = screen_height * 9.0 / 16.0
            s = min(width / w, screen_height / h)
            return round(min(1.0, h * s / screen_height), 3)
    return 1.0


def _strip_pieces(blocks):
    """`(block index, cut index | None, target, seconds, shot)` of every
    picture on screen: a block's asset, or each cut of a sequence. A block
    whose picture an opaque insert covers is left out (strip_on_blur.hidden)."""
    for i, b in enumerate(blocks or []):
        if not isinstance(b, dict):
            continue
        ins = b.get("insert")
        if isinstance(ins, dict) and ins and ins.get("placement") not in _CUTOUT_PLACEMENTS:
            continue
        try:
            s, e = float(b.get("start")), float(b.get("end"))
        except (TypeError, ValueError):
            continue
        if e <= s:
            continue
        a = b.get("asset") or {}
        cuts = a.get("cuts") if a.get("kind") == "sequence" else None
        if cuts:
            t = s
            for ci, c in enumerate(cuts):
                try:
                    sec = float(c.get("seconds") or 0.0)
                except (TypeError, ValueError):
                    sec = 0.0
                end = min(e, t + sec)
                if end > t:
                    yield i, ci, c, end - t, c.get("shot") or b.get("shot")
                t = end
        else:
            yield i, None, a, e - s, a.get("shot") or b.get("shot")


def take_back_strips(blocks, allow=STRIP_ALLOW_SECONDS, screen_height=1920,
                     share_below=STRIP_SHARE):
    """CF-0903: past `allow` seconds of strip, the blur_fills decided on the
    pool's record alone go back to the crop (in place: `presentation` loses
    `blur_fill`, `fit` is `cover`), longest first, until the strip is within
    `allow` or none is left. Returns the record the plan carries:
    `{"task", "share_below", "allow_seconds", "seconds_before",
    "seconds_after", "taken_back": [{"block", "cut", "shot", "seconds",
    "share"}], "kept_by_probe_seconds"}`."""
    strips = [(i, ci, t, sec, shot) for i, ci, t, sec, shot in _strip_pieces(blocks)
              if strip_share(t, screen_height) < share_below]
    total = sum(sec for *_, sec, _ in strips)
    rec = {"task": STRIP_TASK, "share_below": share_below, "allow_seconds": allow,
           "seconds_before": round(total, 3), "taken_back": []}
    movable = [x for x in strips
               if ((x[2].get(PRESENTATION_FIELD) or {}).get(BLUR_FILL) or {})
               .get(FRAMED_BY) == FRAMED_BY_RECORD]
    for i, ci, t, sec, shot in sorted(movable, key=lambda x: -x[3]):
        if total <= allow:
            break
        share = strip_share(t, screen_height)
        pres = t[PRESENTATION_FIELD]
        pres.pop(BLUR_FILL, None)
        if not pres:
            t.pop(PRESENTATION_FIELD, None)
        t["fit"] = "cover"
        total -= sec
        rec["taken_back"].append({"block": i, "cut": ci, "shot": shot,
                                  "seconds": round(sec, 3), "share": share})
    rec["seconds_after"] = round(max(0.0, total), 3)
    rec["kept_by_probe_seconds"] = round(sum(
        sec for i, ci, t, sec, shot in strips
        if ((t.get(PRESENTATION_FIELD) or {}).get(BLUR_FILL) or {}).get(FRAMED_BY)
        == FRAMED_BY_PROBE), 3)
    return rec


def viewer_rank_key(u, blur=0.0):
    """rank_key's triple for a pool usability record, priced as the viewer
    will see the shot: a fixable soft rule costs its presentation instead
    (framing always, brightness when luma_gain() can lift the cached luma).
    The third element is CF-0452's `blur_rank()`: 0 for a shot not found
    blurry, above 1 for a `low_sharpness` one (the sharper, the lower) - a
    rank, not a price: it only orders shots of one score."""
    if u is None:
        return (0, -1.0, blur)
    if u.get("hard"):
        return (1, -float(u.get("score") or 0.0), blur)
    penalty = 0.0
    for v in u.get("soft") or []:
        rule, price = v.get("rule"), v.get("price")
        if not isinstance(price, (int, float)):
            price = soft_price(rule)
        if rule == LOW_FRAMING and worth(BLUR_FILL):
            price = presentation_price(BLUR_FILL)
        elif (rule == LOW_BRIGHTNESS and worth(LUMA_LIFT)
              and luma_gain(v.get("value")) is not None):
            price = presentation_price(LUMA_LIFT)
        penalty += price
    return (0, -max(0.0, round(1.0 - penalty / 100.0, 4)), blur)


def presentation_findings(blocks, finding=None, in_hook=None, priced=None):
    """CF-0436: the plan stage's price of the presentations on screen - one
    `score.presentation_<mode>` per mode per distinct shot, at the first
    block that shows it. `blocks` are plan blocks (a single asset, or the
    `cuts` of a sequence). `priced(key)` says whether the root's table
    carries the rule (`_score.has_rule`): a key it does not price yet is left
    out of the log rather than stopping it (the root adds it, CF-0436 part
    B). Pure."""
    if finding is None or in_hook is None or priced is None:
        import _score
        finding = finding or _score.finding
        in_hook = in_hook or _score.in_hook
        priced = priced or _score.has_rule
    seen, out = set(), []
    for i, b in enumerate(blocks or []):
        asset = b.get("asset") if isinstance(b, dict) else None
        if not isinstance(asset, dict):
            continue
        t0 = b.get("start")
        pics = [asset] + [c for c in asset.get("cuts") or [] if isinstance(c, dict)]
        for pic in pics:
            pres = pic.get(PRESENTATION_FIELD) or {}
            key = pic.get("shot") or pic.get("src")
            for mode in PRESENTATIONS:
                if mode not in pres or (key, mode) in seen:
                    continue
                seen.add((key, mode))
                rule = presentation_key(mode)
                if not priced(rule):
                    continue
                where = {"block": i, "shot": key}
                if isinstance(t0, (int, float)):
                    where["t"] = round(t0, 3)
                out.append(finding(rule, where, hook=in_hook(t0),
                                   note=f"shot {key}: shown {mode.replace('_', ' ')} "
                                        f"instead of {FIXES[mode].replace('_', ' ')} "
                                        f"(CF-0436)"))
    return out


# --------------------------------------------------------------------------
# CF-0452: a blurry shot is ranked behind a sharp one, and a held frame is
# the shot's sharpest moment. From the kaijura-minus-zero refusal
# (2026-09-30T1248Z, `blurry_footage`: "a lot of smeared material").
#
# The measure is the indexer's (`footage-indexer/scripts/sharpness.py`,
# `shot["sharpness_cached"]`, `measured_by` CF-0452/...); a record another
# measure wrote is not read (`sharpness.is_fresh`). The old pool carries no
# record: rank() measures its top candidates on the fly and keeps the record
# in this process only (the pool is transient, CF-0358 - nothing is written
# back). Without the module nothing is measured and nothing changes.
#
# Until the root signs `score.low_sharpness` (sharpness.mode()["signed"]) the
# rule only ranks and warns: the storyboard's usability record carries it in
# `warn`, unpriced. Signed, it goes into `soft` at the table's price and
# plan_findings() charges it like any other weak picture. This repo never
# writes the row (CF-0320: the table is the root's).
# --------------------------------------------------------------------------

_SHARP = {}          # (video, shot index, start, end) -> record or None
_SHARP_RUN = {"probes": 0}


def sharpness_module():
    """footage-indexer's `sharpness` module, or None when it is not beside
    the main checkout (then no shot is found blurry and nothing is measured)."""
    if "sharp" not in _MEMO:
        mod = None
        try:
            if SHARPNESS.exists():
                spec = importlib.util.spec_from_file_location("sharpness", SHARPNESS)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if not all(hasattr(mod, f) for f in ("verdict", "is_fresh")):
                    mod = None
        except Exception:  # a broken module measures nothing
            mod = None
        _MEMO["sharp"] = mod
    return _MEMO["sharp"]


def _priced(key):
    """True when the root's price table carries `key` (`_score.has_rule`)."""
    try:
        import _score
        return bool(_score.has_rule(key))
    except Exception:
        return False


def _sharp_key(shot, video):
    return (str(video or ""), shot.get("index"), shot.get("start"), shot.get("end"))


def _fresh(mod, rec):
    try:
        return isinstance(rec, dict) and bool(mod.is_fresh(rec))
    except Exception:
        return False


def sharpness_record(shot, video=None):
    """The fresh sharpness record of one shot: its own `sharpness_cached`
    when the running measure wrote it, else the one rank() measured on the
    fly in this run. None when there is neither (or no module)."""
    mod = sharpness_module()
    if mod is None or not isinstance(shot, dict):
        return None
    rec = shot.get(SHARPNESS_FIELD)
    if _fresh(mod, rec):
        return rec
    rec = _SHARP.get(_sharp_key(shot, video))
    return rec if _fresh(mod, rec) else None


def _wants_probe(cand, shot, video):
    """True for a candidate rank() should measure: a live shot (a card is
    lettering, shown whole) of a source file on disk, with no fresh record
    and not measured in this run yet, while the run's ceiling lasts."""
    if not isinstance(shot, dict) or not video:
        return False
    if (cand or {}).get("card") or shot.get("is_card"):
        return False
    if _SHARP_RUN["probes"] >= SHARPNESS_PROBES_PER_RUN:
        return False
    if _sharp_key(shot, video) in _SHARP or sharpness_record(shot, video):
        return False
    try:
        from pathlib import Path
        return Path(video).exists()
    except (TypeError, ValueError, OSError):
        return False


def probe_unmeasured(pool, shot_of, video_of, n=SHARPNESS_PROBES_PER_RANK):
    """CF-0537: measure the first `n` candidates of `pool` (in its order)
    that carry no fresh sharpness record - the same probe and the same
    per-run ceiling rank() uses, but over the caller's order rather than the
    usability one, so a pool asked "which of these is sharp" is answered for
    its best-scoring members, not only for its cleanest. Returns how many
    were measured."""
    if sharpness_module() is None:
        return 0
    spent = 0
    for cand in pool:
        if spent >= n:
            break
        shot, video = shot_of(cand), video_of(cand)
        if _wants_probe(cand, shot, video):
            probe_sharpness(shot, video)
            spent += 1
    return spent


def probe_sharpness(shot, video):
    """Measure one shot of the old pool on the fly (`sharpness.of_shot`, else
    `sharpness.measure(video, start, end, n=5)`) and keep the record for this
    run. A failed measure is kept as None, so it is not tried again. Returns
    the record or None."""
    mod = sharpness_module()
    if mod is None or not isinstance(shot, dict):
        return None
    key = _sharp_key(shot, video)
    if key in _SHARP:
        return _SHARP[key]
    _SHARP_RUN["probes"] += 1
    rec = None
    try:
        if hasattr(mod, "of_shot"):
            rec = mod.of_shot(shot, video)
        else:
            rec = mod.measure(video, float(shot["start"]), float(shot["end"]),
                              n=SHARPNESS_SAMPLES)
    except Exception:  # an unreadable source is not found blurry
        rec = None
    if not isinstance(rec, dict):
        rec = shot.get(SHARPNESS_FIELD)   # a measure that stamped the shot
    _SHARP[key] = rec if isinstance(rec, dict) else None
    return _SHARP[key]


def sharpness_verdict(shot, video=None, held=False, rec=None):
    """`sharpness.verdict(record, held=...)` of the shot's fresh record (or
    of `rec` when given): None (sharp enough, or unknown) or `{"rule":
    "low_sharpness", "value", "floor", "held"}`."""
    mod = sharpness_module()
    if rec is None:
        rec = sharpness_record(shot, video)
    if mod is None or not _fresh(mod, rec):
        return None
    try:
        v = mod.verdict(rec, held=held)
    except Exception:
        return None
    return v if isinstance(v, dict) else None


def sharpness_mode():
    """`sharpness.mode()` - `{"mode": "warn"|"penalty", "price", "price_key",
    "signed"}`; unsigned warn when the module is not there."""
    mod = sharpness_module()
    try:
        m = mod.mode() if mod is not None and hasattr(mod, "mode") else None
    except Exception:
        m = None
    m = dict(m) if isinstance(m, dict) else {"mode": "warn", "price": None,
                                             "signed": False}
    m.setdefault("price_key", price_key(LOW_SHARPNESS))
    return m


def blur_rank(u, shot=None, video=None):
    """The rank's third element (viewer_rank_key): 0.0 for a shot not found
    blurry; `2 - sharpness` (above 1, the sharper the lower) for a
    `low_sharpness` one - in the pool record's `warn` (unsigned) or `soft`
    (signed), or in the verdict of the shot's own fresh record / this run's
    on-the-fly measure. Sharpness is the tie-break among blurry shots only:
    among sharp ones the matcher's order stands."""
    flagged, value = False, None
    for v in list((u or {}).get("warn") or []) + list((u or {}).get("soft") or []):
        if isinstance(v, dict) and v.get("rule") == LOW_SHARPNESS:
            flagged, value = True, v.get("value")
    if flagged and isinstance((u or {}).get("sharpness"), (int, float)):
        value = u["sharpness"]
    if not flagged:
        v = sharpness_verdict(shot, video)
        if v is not None:
            flagged, value = True, v.get("value")
    if not flagged:
        return 0.0
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 2.0
    return round(2.0 - max(0.0, min(1.0, float(value))), 4)


def with_sharpness(rec, verdict):
    """The storyboard's usability record `rec` (record()'s, or None) with its
    `low_sharpness` set from `verdict` (sharpness_verdict(), or None):
    signed -> in `soft` at the table's price; unsigned -> in `warn`, no price.
    A previous `low_sharpness` is replaced, price and all (a held frame is the
    shot's sharpest moment and is judged again, held=True). The detail is in
    `sharpness`. None for a clean picture, as before."""
    rec = dict(rec) if isinstance(rec, dict) else {}
    old = rec.pop("sharpness", None) or {}
    soft = [r for r in rec.pop("soft", None) or [] if r != LOW_SHARPNESS]
    warn = [r for r in rec.pop("warn", None) or [] if r != LOW_SHARPNESS]
    penalty = float(rec.pop("penalty", 0) or 0) - float(old.get("price") or 0)
    rec.pop("score", None)
    info = None
    if verdict is not None:
        mode = sharpness_mode()
        price = mode.get("price")
        signed = bool(mode.get("signed")) and isinstance(price, (int, float))
        info = {"task": SHARPNESS_TASK, "value": verdict.get("value"),
                "floor": verdict.get("floor"), "held": bool(verdict.get("held")),
                "signed": signed}
        if signed:
            soft.append(LOW_SHARPNESS)
            penalty += price
            info["price"] = price
        else:
            warn.append(LOW_SHARPNESS)
    if not soft and not warn:
        return None
    penalty = max(0.0, penalty)
    out = {"task": rec.pop("task", TASK), **rec, "soft": soft}
    if warn:
        out["warn"] = warn
    if info:
        out["sharpness"] = info
    out["penalty"] = int(penalty) if penalty.is_integer() else round(penalty, 4)
    out["score"] = max(0.0, round(1.0 - penalty / 100.0, 4))
    return out


# CF-0536: a held frame is the calmest of the shot's sampled moments that read
# at least this sharp - `held_sharpness.FLOOR` (score.held_soft_frame, signed),
# the floor the plan prices a held picture against (a test pins them equal).
HELD_SHARP_FLOOR = 0.53


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def held_moment(used):
    """CF-0452: where a held frame of the resolver's cut `used` is taken -
    `(at, sharpness)` in source seconds from `used["sharpness"]` (the shot's
    fresh record as the cut found it), or None when there is no fresh record
    with a `best_at` (then the frame is the one it always was).

    CF-0536 (delver 0701Z, "неудачный стоп кадр"): not simply the sharpest
    sample - the sharpest moment of a moving shot is a frame of the motion,
    and held it reads as a person stopped mid-gesture. Among the record's
    sampled moments (`frames`: `[t, sharpness, motion]`) that read at least
    `HELD_SHARP_FLOOR`, the calmest (least `motion`; the sharper on a tie);
    a sample with no motion reading ranks behind every measured one. No
    sample over the floor, or none with a time: `best_at`, as before."""
    rec = (used or {}).get("sharpness")
    mod = sharpness_module()
    if mod is None or not _fresh(mod, rec):
        return None
    at = rec.get("best_at")
    if not _num(at):
        return None
    calm = [(float(f[0]), float(f[1]), f[2]) for f in rec.get("frames") or []
            if isinstance(f, (list, tuple)) and len(f) >= 3 and _num(f[0])
            and _num(f[1]) and f[1] >= HELD_SHARP_FLOOR]
    if calm:
        t, s, _m = min(calm, key=lambda f: (f[2] if _num(f[2]) else float("inf"), -f[1]))
        return t, s
    return float(at), rec.get("best")
