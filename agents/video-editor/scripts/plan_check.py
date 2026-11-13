#!/usr/bin/env python3
"""CF-0411: build a script's render plan without rendering it - the Editor's
own gates, run for the Content Researcher before the script leaves its stage.

Why
---
Batch `example-film/2026-09-27T0929Z` shipped 0 videos. Three of its five
scripts died in this stage *after* the voice and the resolve had been paid
for: `check_block_capacity` predicted Backrooms at 17.72 blocks/min "inside"
and the plan builder measured 3.8 (`pattern_ceiling`); Wolfhame passed the
coverage gate twice ("21/21 covered") and the cut-clip gate then refused all
55 free shots (framing and brightness are measured on the cut clip, the cache
on a probe frame). The rebuild `rebuilds/2026-09-27T1757Z` saved wolfhame and
backrooms the same way both times: by editing the anchors - never the
narrator's text - against the refusals of the *real* resolve and plan.

The user's decision of 2026-09-28: that loop belongs inside the writer's
stage. A script does not go on (compliance pass 2, this stage) until this
stage's real gates have built a plan out of it. The cheap pre-checks
(`check_block_capacity`, `check_anchor_coverage`) stay as a filter; the
verdict "buildable" is this file's.

What it runs
------------
`check` runs, for one script of a batch, exactly the commands of the Editor's
procedure (SKILL.md steps 3-6), each as its own process with this
interpreter, into `<batch>/work/<slug>/` - the directory the Editor works in:

  synthesize_voiceover.py -> narration_length.py -> align_words.py ->
  script_anchors.py spec -> resolve_anchors.py -> build_render_plan.py

and stops there: no `render_video.py`, no `qc_render.py`, no attempt is begun
on the ledger. Then it reads what those gates left on disk (the plan, its
refusal sidecar and deficit, the storyboard's `unresolved_anchors`) and writes
one machine-readable verdict, `work/<slug>/plan_check.json`:

  assembled        true only when a plan was written and no block of it is a
                   hole (below)
  refusals[]       one record per blocking finding - kind, gate, block,
                   anchor_id, phrase, reason. Kinds: `pattern_ceiling`,
                   `plan_refused` (any other gate of build_render_plan.py),
                   `background` (a block on the procedural rung),
                   `typographic` (a block degraded to the typographic rung),
                   `cut_gate` (an anchor whose candidates the cut-clip gate
                   refused), `absent` (an anchor that resolved to no picture),
                   `narration_ceiling`, `anchors_dropped`, `still_share`
                   (CF-0418: pictures over the channel's max_still_share -
                   share, threshold, blocks, spans, fixable_by_anchors)
  notes[]          non-blocking findings (a covered shortfall, plan warnings,
                   CF-0433 `low_similarity`: an anchor filled under the
                   similarity floor - priced, not refused; CF-0453
                   `too_tight`: a block built shorter than the 1.6s a
                   picture needs to read - priced `score.block_too_short`
                   once the root's table carries it, never refused here)
  score            CF-0433: the plan's `score` block verbatim (shared/score,
                   CF-0432: start, score, tier, threshold, passed, hard, log,
                   by_rule, findings) - `null` when no plan was written.
                   The pace under the pattern's floor, a block over the hold
                   band and a picture under the similarity floor are priced
                   here and no longer refuse; the plan is refused on them
                   only when `score` < `threshold`
  text_sha256     the narrator's text the voice was synthesized from
  anchors_sha256   the script's `visual_anchors` the storyboard was built from
  text_changed     whether the text differs from round 1's (the guard the
                   writer's loop uses: anchors may change, the text may not)
  fixable_by_anchors
                   CF-0428: whether an edit of `visual_anchors` alone can
                   clear this verdict's refusals - `false` when any refusal
                   is one no anchor edit moves (`narration_ceiling`; a
                   `pattern_ceiling` whose own `fixable_by_anchors` is false:
                   the pool cannot put the floor's blocks on screen, see its
                   `supply`), `true` when every refusal is of a kind the
                   anchors answer, `null` when assembled or not known. The
                   writer's loop drops or defers on `false` instead of
                   spending a round.

CF-0814: a script whose every anchor places one of its own graphics
(`graphic_id`, CF-0689/CF-0806) needs no pool: with no `--index` and an empty
`anchor_coverage_pool.indexes` it is built from its `graphics[]` alone (the
resolve and the plan get no `--index`), the verdict says `no_pool: true` and
carries a `no_pool` note - the pool's gates had nothing to measure. An empty
pool under any anchor that asks the pool stays the "which pool is it?" error.

A script that is not assembled also gets `work/<slug>/plan_check.refusal.json`
(a `plan_refusal` record with `before_render: true`), so
`write_batch_metadata.py` carries it into `05-video-editor.json` ->
`refusals[]` like any refusal of this stage, marked as taken before the
render.

A rerun after the anchors were edited does not pay for the voice again: the
synthesis and the alignment are keyed on the text plus the channel's voice
(`work/<slug>/voice.key.json`), and reused while the key holds. The previous
round's plan, sidecars and deficits are moved to
`work/<slug>/plan_check.rounds/round-<n>/` first, so nothing stale is left
beside the new verdict.

`reuse` is the Editor's side: given a script id it says whether a checked plan
can go straight to the render (exit 0), was refused before the render (exit 2,
the sidecar is on disk), has no verdict (exit 3 - build as before, which is
also every batch older than this file), or is stale (exit 4 - the text,
anchors, artifacts or cleared pool moved since the check).

Exit codes of `check`: 0 assembled, 2 not assembled (the script's), 1 the
environment (a step crashed, a file is missing - nothing about the script).
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import assetless_rung  # noqa: E402
import plan_refusal  # noqa: E402
import still_share  # noqa: E402 - CF-0418
from _channel_ids import resolve_channel  # noqa: E402 - CF-0197

VERDICT = "plan_check.json"
REFUSAL = "plan_check.refusal.json"
VOICE_KEY = "voice.key.json"
ROUNDS_DIR = "plan_check.rounds"
KIND = "plan_check"
VERSION = 1

EXIT_ASSEMBLED = 0
EXIT_ENVIRONMENT = 1
EXIT_REFUSED = 2
EXIT_NO_VERDICT = 3
EXIT_STALE = 4

# A generous ceiling per step: each tool already runs its own children under
# common.py's timeouts; this only keeps a wedged step from holding the stage.
STEP_TIMEOUT_SECONDS = float(os.environ.get("PLAN_CHECK_STEP_TIMEOUT", "1800"))

# CF-0428: refusal kinds an anchor edit answers (the writer's loop exists for
# them); `narration_ceiling` never is one - the voice is too long and the text
# may not change. `pattern_ceiling` says for itself (`fixable_by_anchors`),
# and `plan_refused` is any other plan gate, not known either way.
ANCHOR_FIXABLE_KINDS = ("anchors_dropped", "background", "typographic",
                        "cut_gate", "absent")
NOT_ANCHOR_FIXABLE_KINDS = ("narration_ceiling",)

BLOCKING_KINDS = ("pattern_ceiling", "plan_refused", "narration_ceiling",
                  "anchors_dropped", "background", "typographic", "cut_gate",
                  "absent", "still_share")

# The refusal sidecar's gate per blocking kind (plan_refusal.GATE_CODES owns
# the funnel code each maps to).
KIND_GATES = {
    "pattern_ceiling": plan_refusal.GATE_PATTERN_CEILING,
    "narration_ceiling": plan_refusal.GATE_NARRATION_CEILING,
    "anchors_dropped": plan_refusal.GATE_TEXT_GATES,
    "background": plan_refusal.GATE_ASSETLESS_RUNG,
    "typographic": plan_refusal.GATE_ASSETLESS_RUNG,
    "cut_gate": plan_refusal.GATE_UNRESOLVED_ANCHOR,
    "absent": plan_refusal.GATE_UNRESOLVED_ANCHOR,
    "still_share": plan_refusal.GATE_STILL_SHARE,  # CF-0418
}

# What a previous round leaves in work/<slug>/ that must not sit beside the
# next round's verdict: moved into the round's archive. The storyboard and the
# anchors are copied instead - resolve_anchors.py --exclude-candidate reads the
# storyboard it replaces.
MOVE_PER_ROUND = ("plan.json", VERDICT, REFUSAL)
MOVE_GLOB_PER_ROUND = ("plan.*.json",)
COPY_PER_ROUND = ("storyboard.json", "anchors.json")


# --------------------------------------------------------------------------
# small helpers

def NO_POOL_NOTE(n):  # noqa: N802 - a record shape, built where it is used
    """CF-0814: the note an all-graphic script's verdict carries in place of a
    pool - the pool-dependent gates (the matcher, the cut-clip gate, the topic
    rung, the source gate) had nothing to measure, and said so."""
    return {"kind": "no_pool", "block": None, "anchor_id": None, "phrase": None,
            "reason": f"every one of the {n} anchor(s) places one of the script's own "
                      f"graphics (`graphic_id`, CF-0689): no pool was given and none is "
                      f"needed - the pool's gates had nothing to measure (CF-0814)"}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def read_json(path):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def write_json(path, doc):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "w") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return s or None


def narration_text(script):
    """The narrator's text exactly as the Editor synthesizes it - the three
    spoken sections on one line (meme_layer.narration_text, CF-0261; spelled
    here so this file imports nothing heavy)."""
    s = script or {}
    return " ".join(x for x in (s.get("hook"), s.get("commentary"), s.get("payoff")) if x)


def anchors_of(script):
    return list((script or {}).get("visual_anchors") or [])


def load_script(batch, script_id):
    doc = read_json(Path(batch) / "03-content-researcher.json")
    if not isinstance(doc, dict):
        raise SystemExit(f"PLAN CHECK: ERROR: {batch}/03-content-researcher.json unreadable")
    for s in doc.get("scripts") or []:
        if s.get("script_id") == script_id:
            return doc, s
    raise SystemExit(f"PLAN CHECK: ERROR: no script {script_id!r} in "
                     f"{batch}/03-content-researcher.json")


def default_slug(script):
    return slugify(((script or {}).get("title_ref") or {}).get("name")) or \
        slugify((script or {}).get("script_id"))


def default_indexes(script):
    """The pool the writer's own coverage gate judged - the batch's sources for
    this topic before compliance pass 2 narrows them."""
    pool = (script or {}).get("anchor_coverage_pool") or {}
    return [str(p) for p in pool.get("indexes") or []]


def is_graphic_anchor(anchor):
    """CF-0689: an anchor that places one of the script's own graphics
    (`graphic_id`) asks the pool nothing - resolve_anchors.py's own test."""
    gid = (anchor or {}).get("graphic_id") if isinstance(anchor, dict) else None
    return isinstance(gid, str) and bool(gid.strip())


def all_graphic(script):
    """CF-0814: every anchor of the script is one of its own graphics - the
    legitimate Tech path of CF-0806 (an all-graphic script needs no pool)."""
    anchors = anchors_of(script)
    return bool(anchors) and all(is_graphic_anchor(a) for a in anchors)


def estimated_seconds(script):
    n = (script or {}).get("narration") or {}
    for v in (n.get("estimated_seconds"), (script or {}).get("estimated_spoken_duration_seconds")):
        if isinstance(v, (int, float)):
            return float(v)
    return None


def voice_key(text, channel, lead_silence):
    """The TTS fingerprint: the text and the voice it was read in. A channel
    whose profile cannot be read keys on the channel id alone - the synthesis
    step will fail on it loudly anyway."""
    try:
        import voice_profile
        v = voice_profile.load(channel)
        voice = {k: v.get(k) for k in ("engine", "voice", "speed", "lang")}
    except Exception as e:  # noqa: BLE001 - recorded, not fatal here
        voice = {"channel": channel, "unreadable": str(e)}
    return {"text_sha256": sha256_text(text), "voice": voice,
            "lead_silence": float(lead_silence or 0.0)}


def source_of_index(path):
    name = Path(path).name
    return name[:-len(".shots.json")] if name.endswith(".shots.json") else Path(path).stem


# --------------------------------------------------------------------------
# running a step - the one seam tests replace

def run_step(name, argv, cwd=None):
    """Run one of the Editor's tools. Returns (exit_code, seconds)."""
    started = time.monotonic()
    print(f"PLAN CHECK: {name}: {Path(str(argv[1])).name} ...", file=sys.stderr)
    try:
        proc = subprocess.run([str(a) for a in argv], cwd=cwd,
                              timeout=STEP_TIMEOUT_SECONDS)
        code = proc.returncode
    except subprocess.TimeoutExpired:
        print(f"PLAN CHECK: {name} passed the {STEP_TIMEOUT_SECONDS:.0f}s ceiling - killed",
              file=sys.stderr)
        code = 124
    return code, round(time.monotonic() - started, 2)


def tool(name):
    return str(SCRIPTS / name)


# --------------------------------------------------------------------------
# reading what the gates left on disk

def _anchor_by_phrase(script):
    return {(a.get("phrase") or "").strip(): a for a in anchors_of(script)}


def _intent_is(intent, phrase):
    """A block's `intent` is its anchor's phrase, sometimes with the resolver's
    note on a multi-shot block appended: "<phrase> (3 shots of side 'a': ...)"."""
    intent = (intent or "").strip()
    return bool(phrase) and (intent == phrase or intent.startswith(phrase + " ("))


def _block_of_phrase(storyboard, phrase):
    for i, b in enumerate((storyboard or {}).get("blocks") or []):
        if _intent_is(b.get("intent"), phrase):
            return i
    return None


def _anchor_of_block(storyboard, script, block):
    blocks = (storyboard or {}).get("blocks") or []
    if block is None or not (0 <= block < len(blocks)):
        return None, None
    intent = blocks[block].get("intent")
    for phrase, a in _anchor_by_phrase(script).items():
        if _intent_is(intent, phrase):
            return a.get("anchor_id"), phrase
    return None, (intent or "").strip() or None


def anchor_fixability(refusals):
    """CF-0428: the verdict's `fixable_by_anchors` - see the module docstring.

    One refusal no anchor edit moves makes the whole verdict unfixable by
    anchors, however many anchor-shaped refusals stand beside it: vanguards
    (1126Z) carried sixteen `cut_gate` / `absent` refusals next to a pace the
    pool could not reach, and rewriting all sixteen phrases would still have
    left it under the floor."""
    if not refusals:
        return None
    known = True
    for r in refusals:
        kind = r.get("kind")
        if kind in NOT_ANCHOR_FIXABLE_KINDS or r.get("fixable_by_anchors") is False:
            return False
        if kind in ("pattern_ceiling", "still_share"):
            known = known and r.get("fixable_by_anchors") is True
        elif kind not in ANCHOR_FIXABLE_KINDS:
            known = False
    return True if known else None


def plan_score(work, plan_exit):
    """CF-0433: `plan.json -> score` of this round, or None (no plan)."""
    if plan_exit != 0:
        return None
    return (read_json(work / "plan.json") or {}).get("score")


def classify_unresolved(reason):
    r = reason or ""
    # CF-0453: the block was built, only short - a note (and a price on the
    # plan's score, score.block_too_short), never `absent`.
    if "too tight to read" in r:
        return "too_tight"
    if "on the cut clip" in r:
        return "cut_gate"
    if "shortfall" in r and "every candidate failed" not in r:
        return "shortfall"
    return "absent"


def analyse(work, script, plan_exit):
    """(refusals, notes) out of the round's artifacts."""
    refusals, notes = [], []
    storyboard = read_json(work / "storyboard.json")
    plan = read_json(work / "plan.json") if plan_exit == 0 else None
    by_phrase = _anchor_by_phrase(script)

    def add(kind, reason, block=None, gate=None, anchor_id=None, phrase=None, **extra):
        if block is not None and anchor_id is None and phrase is None:
            anchor_id, phrase = _anchor_of_block(storyboard, script, block)
        rec = {"kind": kind, "gate": gate or KIND_GATES.get(kind), "block": block,
               "anchor_id": anchor_id, "phrase": phrase,
               "reason": " ".join(str(reason or "").split())}
        rec.update(extra)
        refusals.append(rec)

    # 1. the plan builder's own refusal (no plan written)
    plan_ref = read_json(work / "plan.refusal.json") if plan_exit != 0 else None
    degraded = []
    if plan_ref:
        gate = plan_ref.get("gate")
        if gate == plan_refusal.GATE_PATTERN_CEILING:
            deficit = read_json(plan_ref.get("deficit") or work / "plan.pattern-ceiling.json") or {}
            pc = deficit.get("pattern_ceiling") or {}
            blocks = sorted({b.get("block") for b in (pc.get("breaches") or [])
                             if isinstance(b.get("block"), int)})
            add("pattern_ceiling", plan_ref.get("reason"), gate=gate,
                parameter=pc.get("parameter"), measured=pc.get("measured"),
                band_min=pc.get("band_min"), band_max=pc.get("band_max"),
                cause=pc.get("cause"), blocks=blocks, deficit=plan_ref.get("deficit"),
                # CF-0428: whether the anchors are the lever at all, and the
                # numbers that say so (build_render_plan.cadence_supply()).
                fixable_by_anchors=pc.get("fixable_by_anchors"),
                supply=pc.get("supply"))
            degraded = list(pc.get("degraded_blocks") or [])
        elif gate == plan_refusal.GATE_STILL_SHARE:
            # CF-0418: pictures over the channel's line - the numbers and the
            # blocks off the deficit (still_share.write_deficit).
            deficit = read_json(plan_ref.get("deficit") or work / "plan.still-share.json") or {}
            ss = deficit.get("still_share") or {}
            named = list(ss.get("blocks") or [])
            add("still_share", plan_ref.get("reason"), gate=gate,
                block=named[0] if named else None, blocks=named,
                share=ss.get("share"), threshold=ss.get("threshold"),
                picture_seconds=ss.get("picture_seconds"),
                running_seconds=ss.get("running_seconds"), spans=ss.get("spans"),
                fixable_by_anchors=still_share.fixable_by_anchors(ss) if ss else None,
                reason_code=plan_ref.get("reason_code"), deficit=plan_ref.get("deficit"))
        else:
            named = sorted({int(n) for n in re.findall(r"\bblock (\d+)", plan_ref.get("reason") or "")})
            add("plan_refused", plan_ref.get("reason"), gate=gate,
                block=named[0] if named else None, blocks=named,
                reason_code=plan_ref.get("reason_code"), deficit=plan_ref.get("deficit"))

    # 2. anchors that resolved to no picture - one record per anchor: the
    # resolver can list a phrase twice (the refusal, then the topic fill that
    # stood in for it); the cut-clip gate wins the name when it spoke at all
    #
    # CF-0433: an anchor whose block took the best picture the pool had under
    # the similarity floor (`best_used_score` on its record, `below_floor` on
    # the block) has a picture - it is priced in the plan's score
    # (`score.low_similarity`), not refused here: a note, like a shortfall.
    by_unresolved = {}
    for u in (storyboard or {}).get("unresolved_anchors") or []:
        phrase = (u.get("phrase") or "").strip()
        by_unresolved.setdefault(phrase, []).append(u)
    for phrase, recs in by_unresolved.items():
        reasons = [u.get("reason") or "" for u in recs]
        kinds = ["low_similarity" if u.get("best_used_score") is not None
                 else classify_unresolved(u.get("reason")) for u in recs]
        # CF-0453: a too-tight note is neither: the block has its picture and
        # is priced on the plan's score. It refuses only through that score
        # (under N), never here - and it never lends its words to a refusal
        # of another kind for the same phrase.
        kind = ("cut_gate" if "cut_gate" in kinds else
                "absent" if "absent" in kinds else
                "low_similarity" if "low_similarity" in kinds else
                "shortfall" if "shortfall" in kinds else "too_tight")
        a = by_phrase.get(phrase) or {}
        rec = dict(block=_block_of_phrase(storyboard, phrase),
                   anchor_id=a.get("anchor_id"), phrase=phrase or None)
        tight = [r for r, k in zip(reasons, kinds) if k == "too_tight"]
        if kind != "too_tight" and tight:
            reasons = [r for r, k in zip(reasons, kinds) if k != "too_tight"]
            notes.append({"kind": "too_tight", **rec, "reason": " | ".join(
                " ".join(r.split()) for r in tight)})
        reason = " | ".join(" ".join(r.split()) for r in reasons)
        if kind in ("shortfall", "low_similarity", "too_tight"):
            notes.append({"kind": kind, "reason": reason, **rec})
        else:
            add(kind, reason, **rec)

    # 3. the plan's holes: blocks on the typographic / procedural rung
    if plan:
        degraded = list(plan.get("degraded_blocks") or [])
    style_typographic = (plan or {}).get("style") == "typographic"
    typo = set()
    if not style_typographic:
        for d in degraded:
            if d.get("to") == "typographic" and isinstance(d.get("index"), int):
                typo.add(d["index"])
                add("typographic", d.get("reason"), block=d["index"],
                    degraded_from=d.get("from"))
        rung = (plan or {}).get("assetless_rung") or {}
        background = set(b for b in rung.get("blocks") or [] if isinstance(b, int))
        for i, b in enumerate((plan or {}).get("blocks") or []):
            if (b.get("asset") or {}).get("kind") == "procedural" \
                    and not assetless_rung.filled_by_insert(b) and i not in typo:
                background.add(i)
        for i in sorted(background - typo):
            add("background", "block on the procedural background rung (no picture)", block=i)

    for w in (plan or {}).get("warnings") or []:
        notes.append({"kind": "plan_warning", "gate": w.get("gate"),
                      "reason_code": w.get("reason_code"),
                      "reason": " ".join(str(w.get("reason") or "").split())[:600]})
    return refusals, notes


# --------------------------------------------------------------------------
# rounds

def archive_round(work, previous):
    """Move the previous round's plan and sidecars out of the way. Returns the
    archive dir or None when there was nothing to move."""
    present = [work / n for n in MOVE_PER_ROUND if (work / n).exists()]
    for pattern in MOVE_GLOB_PER_ROUND:
        present += [p for p in work.glob(pattern) if p not in present]
    if not present:
        return None
    n = int((previous or {}).get("round") or 0) or 0
    dest = work / ROUNDS_DIR / f"round-{n}"
    k = 1
    while dest.exists():
        dest = work / ROUNDS_DIR / f"round-{n}-{k}"
        k += 1
    dest.mkdir(parents=True)
    for p in present:
        shutil.move(str(p), str(dest / p.name))
    for name in COPY_PER_ROUND:
        if (work / name).exists():
            shutil.copy2(work / name, dest / name)
    return dest


def refusal_reason(refusals):
    parts = []
    for r in refusals:
        where = []
        if r.get("block") is not None:
            where.append(f"block {r['block']}")
        if r.get("anchor_id"):
            where.append(f"anchor {r['anchor_id']}")
        head = f"[{r['kind']}]" + (f" {' '.join(where)}" if where else "")
        parts.append(f"{head}: {(r.get('reason') or '')[:400]}")
    return plan_refusal.reason_text(
        f"PLAN CHECK REFUSED BEFORE THE RENDER (CF-0411): {len(refusals)} finding(s) "
        f"of the Editor's own gates, the script does not go to the render", parts)


def write_refusal_sidecar(work, verdict):
    first = verdict["refusals"][0]
    gate = first.get("gate") or KIND_GATES.get(first["kind"])
    try:
        rec = plan_refusal.entry(verdict["script_id"], gate, refusal_reason(verdict["refusals"]),
                                 deficit=str(work / VERDICT))
    except plan_refusal.UnknownGate:
        rec = plan_refusal.entry(verdict["script_id"], plan_refusal.GATE_PATTERN_CEILING,
                                 refusal_reason(verdict["refusals"]), deficit=str(work / VERDICT))
        rec["gate"] = gate
        rec["reason_code"] = first.get("reason_code") or rec["reason_code"]
    rec["before_render"] = True
    rec["refused_by"] = KIND
    rec["kinds"] = sorted({r["kind"] for r in verdict["refusals"]})
    rec["round"] = verdict.get("round")
    write_json(work / REFUSAL, rec)
    return work / REFUSAL


# --------------------------------------------------------------------------
# check

def inputs_of(args, script, text, indexes, vkey):
    return {"text_sha256": sha256_text(text),
            "anchors_sha256": sha256_text(canonical(anchors_of(script))),
            "indexes": sorted(indexes), "voice_key": vkey,
            "pattern": script.get("pattern"), "style": args.style,
            "narration_file": bool(args.narration_file)}


def check(args):
    batch = Path(args.batch).resolve()
    doc, script = load_script(batch, args.script_id)
    channel = resolve_channel(args.channel or doc.get("channel"))
    if not channel:
        raise SystemExit("PLAN CHECK: ERROR: no --channel and no `channel` in 03")
    slug = args.slug or default_slug(script)
    work = batch / "work" / slug
    work.mkdir(parents=True, exist_ok=True)
    script_json = batch / "03-content-researcher.json"
    text = Path(args.narration_file).read_text().strip() if args.narration_file \
        else narration_text(script)
    if not text:
        raise SystemExit(f"PLAN CHECK: ERROR: {args.script_id} has no narration text")
    indexes = list(args.index or default_indexes(script))
    # CF-0814: an all-graphic script (CF-0806/CF-0689) is built from its own
    # `graphics[]` alone - no pool to name, nothing for the pool's gates to
    # measure. Only an anchor that asks the pool makes an empty pool an error.
    no_pool = not indexes and all_graphic(script)
    if not indexes and not no_pool:
        raise SystemExit(f"PLAN CHECK: ERROR: {args.script_id}: no --index and no "
                         f"anchor_coverage_pool.indexes in 03 - which pool is it?")
    vkey = voice_key(text, channel, args.lead_silence)
    inputs = inputs_of(args, script, text, indexes, vkey)
    previous = read_json(work / VERDICT)

    if previous and not args.force and previous.get("inputs") == inputs \
            and not previous.get("environment_error"):
        print(f"PLAN CHECK: UNCHANGED since round {previous.get('round')}: "
              f"assembled={previous.get('assembled')} ({work / VERDICT})")
        return EXIT_ASSEMBLED if previous.get("assembled") else EXIT_REFUSED

    archived = archive_round(work, previous)
    rnd = int((previous or {}).get("round") or 0) + 1
    baseline = (previous or {}).get("baseline_text_sha256") or (previous or {}).get("text_sha256") \
        or inputs["text_sha256"]
    py = args.python or sys.executable
    voice, words, anchors = work / "voice.wav", work / "words.json", work / "anchors.json"
    storyboard, plan = work / "storyboard.json", work / "plan.json"
    order = work / "order.json"
    steps = []

    def step(name, argv):
        code, secs = run_step(name, argv)
        steps.append({"step": name, "exit": code, "seconds": secs,
                      "argv": [str(a) for a in argv]})
        return code

    verdict = {
        "kind": KIND, "version": VERSION, "script_id": args.script_id, "slug": slug,
        "batch": str(batch), "channel": channel, "at": now(), "round": rnd,
        "assembled": False, "environment_error": False,
        "text_sha256": inputs["text_sha256"], "anchors_sha256": inputs["anchors_sha256"],
        "baseline_text_sha256": baseline,
        "text_changed": inputs["text_sha256"] != baseline,
        "previous_text_sha256": (previous or {}).get("text_sha256"),
        "anchors_changed": bool(previous) and
        (previous or {}).get("anchors_sha256") != inputs["anchors_sha256"],
        "indexes": inputs["indexes"], "inputs": inputs,
        "tts": {"reused": False}, "refusals": [], "score": None, "steps": steps,
        "notes": [NO_POOL_NOTE(len(anchors_of(script)))] if no_pool else [],
        "no_pool": no_pool,
        "archived_previous_round": str(archived) if archived else None,
    }
    if verdict["text_changed"]:
        print(f"PLAN CHECK: TEXT CHANGED since round 1 ({baseline[:12]} -> "
              f"{inputs['text_sha256'][:12]}): the narrator's text is not the one the "
              f"first round was built from", file=sys.stderr)

    def finish(code):
        if code == EXIT_ENVIRONMENT:
            verdict["environment_error"] = True
        verdict["fixable_by_anchors"] = (None if verdict["assembled"]
                                         else anchor_fixability(verdict["refusals"]))
        if verdict["refusals"]:
            verdict["refusal"] = str(write_refusal_sidecar(work, verdict))
        else:
            verdict["refusal"] = None
        for name, path in (("voice", voice), ("words", words), ("anchors", anchors),
                           ("storyboard", storyboard), ("plan", plan), ("order", order)):
            verdict.setdefault("artifacts", {})[name] = {
                "path": str(path), "sha256": sha256_file(path) if path.exists() else None}
        write_json(work / VERDICT, verdict)
        state = ("ASSEMBLED" if verdict["assembled"] else
                 "ENVIRONMENT ERROR" if verdict["environment_error"] else "NOT ASSEMBLED")
        print(f"PLAN CHECK {state}: {args.script_id} round {rnd} -> {work / VERDICT}")
        for r in verdict["refusals"]:
            where = " ".join(x for x in (
                f"block {r['block']}" if r.get("block") is not None else "",
                f"anchor {r['anchor_id']}" if r.get("anchor_id") else "") if x)
            print(f"  REFUSED [{r['kind']}] {where}: {(r.get('reason') or '')[:200]}")
        if verdict.get("refusal"):
            print(f"  refusal -> {verdict['refusal']} (before the render)")
        if verdict["fixable_by_anchors"] is False:
            print("  NOT FIXABLE BY ANCHORS: no edit of visual_anchors clears "
                  "this verdict (see the refusals' fixable_by_anchors / supply)")
        return code

    # --- the voice: reused while the text and the voice are the same
    key_rec = read_json(work / VOICE_KEY) or {}
    reusable = (key_rec.get("key") == vkey and voice.exists() and words.exists()
                and key_rec.get("wav_sha256") == sha256_file(voice)
                and key_rec.get("words_sha256") == sha256_file(words))
    if not reusable and args.adopt_voice and voice.exists() and words.exists():
        told = (work / "narration.txt").read_text().strip() \
            if (work / "narration.txt").exists() else None
        if told == text:
            reusable = True
            verdict["tts"]["adopted"] = True
    if reusable:
        verdict["tts"] = dict(verdict["tts"], reused=True)
        print("PLAN CHECK: voice reused - text and voice unchanged, no TTS paid",
              file=sys.stderr)
    else:
        argv = [py, tool("synthesize_voiceover.py"), text, voice, "--channel", channel]
        if args.lead_silence:
            argv += ["--lead-silence", str(args.lead_silence)]
        if step("tts", argv) != 0:
            return finish(EXIT_ENVIRONMENT)
    # the length gate is cheap and reads the wav - always asked
    stale_voice_refusal = work / "voice.refusal.json"
    if stale_voice_refusal.exists():
        stale_voice_refusal.unlink()
    code = step("narration_length", [py, tool("narration_length.py"), voice, "--channel", channel,
                                     "--script", script_json, "--script-id", args.script_id])
    if code == 2:
        rec = read_json(stale_voice_refusal) or {}
        # the gate's own sidecar is superseded by this verdict's
        if stale_voice_refusal.exists():
            stale_voice_refusal.unlink()
        verdict["refusals"].append({
            "kind": "narration_ceiling", "gate": plan_refusal.GATE_NARRATION_CEILING,
            "block": None, "anchor_id": None, "phrase": None,
            "reason": rec.get("reason") or "the voice is over the channel's ceiling"})
        return finish(EXIT_REFUSED)
    if code != 0:
        return finish(EXIT_ENVIRONMENT)
    if not reusable:
        # synthesize_voiceover.py records the same file; written here too so the
        # alignment reconciles onto exactly this text whatever wrote the wav
        (work / "narration.txt").write_text(text + "\n")
        if step("align", [py, tool("align_words.py"), voice, words,
                          "--text", work / "narration.txt"]) != 0:
            return finish(EXIT_ENVIRONMENT)
        write_json(work / VOICE_KEY, {"key": vkey, "at": now(),
                                      "wav_sha256": sha256_file(voice),
                                      "words_sha256": sha256_file(words)})
    verdict["tts"]["key"] = vkey

    # --- the anchors, verbatim from the script
    argv = [py, tool("script_anchors.py"), "spec", script_json, "--script-id", args.script_id,
            "--words", words, "--out", anchors]
    if args.style:
        argv += ["--style", args.style]
    code = step("anchors_spec", argv)
    if code == 2:
        verdict["refusals"].append({
            "kind": "anchors_dropped", "gate": plan_refusal.GATE_TEXT_GATES, "block": None,
            "anchor_id": None, "phrase": None,
            "reason": "script_anchors.py spec: no anchor of the script locates in the voice "
                      "(none given, or every beat_text dropped) - see its ANCHOR DROPPED lines"})
        return finish(EXIT_REFUSED)
    if code != 0:
        return finish(EXIT_ENVIRONMENT)

    # --- the order the rotation drew: the script entry itself (load_order unwraps it)
    write_json(order, script)

    # --- resolve
    argv = [py, tool("resolve_anchors.py"), anchors, words, voice, storyboard]
    for ix in indexes:
        argv += ["--index", ix]
    argv += ["--clips-dir", work / "clips", "--order", order, "--channel", channel]
    if step("resolve", argv) != 0:
        return finish(EXIT_ENVIRONMENT)

    # --- the plan (no render)
    argv = [py, tool("build_render_plan.py"), storyboard, words, voice, plan,
            "--channel", channel, "--script", script_json, "--script-id", args.script_id]
    est = estimated_seconds(script)
    if est is not None:
        argv += ["--estimated-seconds", str(est)]
    for ix in indexes:
        argv += ["--index", ix]
    plan_exit = step("plan", argv)
    if plan_exit != 0 and not (work / "plan.refusal.json").exists():
        return finish(EXIT_ENVIRONMENT)

    refusals, notes = analyse(work, script, plan_exit)
    verdict["refusals"] += refusals
    verdict["notes"] += notes
    # CF-0433: the plan's score log (shared/score, CF-0432) - pace, hold band,
    # similarity priced instead of refused. The writer's loop (6b) reads it
    # here; `null` when no plan was written.
    verdict["score"] = plan_score(work, plan_exit)
    verdict["assembled"] = plan_exit == 0 and not verdict["refusals"]
    if plan_exit == 0 and (work / "plan.refusal.json").exists():
        (work / "plan.refusal.json").unlink()
    return finish(EXIT_ASSEMBLED if verdict["assembled"] else EXIT_REFUSED)


# --------------------------------------------------------------------------
# reuse - the Editor's side

def find_verdict(batch, script_id, slug=None):
    work = Path(batch) / "work"
    if slug:
        v = read_json(work / slug / VERDICT)
        return (v, work / slug) if v and v.get("script_id") == script_id else (None, None)
    found = []
    for p in sorted(work.glob(f"*/{VERDICT}")):
        v = read_json(p)
        if isinstance(v, dict) and v.get("kind") == KIND and v.get("script_id") == script_id:
            found.append((v.get("at") or "", v, p.parent))
    if not found:
        return None, None
    found.sort(key=lambda t: t[0])
    return found[-1][1], found[-1][2]


def plan_sources(plan):
    srcs = set()
    for b in (plan or {}).get("blocks") or []:
        shots = [b.get("shot")] + [c.get("shot") for c in b.get("cuts") or []] \
            + list(b.get("swing_block_shots") or [])
        for s in shots:
            if isinstance(s, str) and ":" in s:
                srcs.add(s.rsplit(":", 1)[0])
    return srcs


def reuse(args):
    batch = Path(args.batch).resolve()
    verdict, work = find_verdict(batch, args.script_id, args.slug)
    if not verdict:
        print(f"NO PLAN CHECK for {args.script_id}: build it as before (procedure steps 1-6)")
        return EXIT_NO_VERDICT
    if verdict.get("environment_error"):
        print(f"NO PLAN CHECK for {args.script_id}: the check in {work} ended on an "
              f"environment error - build it as before")
        return EXIT_NO_VERDICT
    _, script = load_script(batch, args.script_id)
    stale = []
    if sha256_text(narration_text(script)) != verdict.get("text_sha256") and \
            not verdict.get("inputs", {}).get("narration_file"):
        stale.append("the narrator's text in 03 is not the one the check synthesized")
    if sha256_text(canonical(anchors_of(script))) != verdict.get("anchors_sha256"):
        stale.append("the script's visual_anchors changed since the check")
    if not verdict.get("assembled"):
        if stale:
            print(f"STALE: {args.script_id}: " + "; ".join(stale) + f" - check it again "
                  f"or build it as before ({work / VERDICT})")
            return EXIT_STALE
        sidecar = work / REFUSAL
        if not sidecar.exists() and verdict.get("refusals"):
            write_refusal_sidecar(work, verdict)
        kinds = ", ".join(sorted({r["kind"] for r in verdict.get("refusals") or []}))
        print(f"REFUSED BEFORE THE RENDER: {args.script_id} [{kinds}] - not rendered; "
              f"the refusal is {sidecar} (write_batch_metadata.py <batch> carries it)")
        return EXIT_REFUSED
    for name, art in (verdict.get("artifacts") or {}).items():
        if name == "order":
            continue
        if not art.get("sha256") or sha256_file(art.get("path")) != art.get("sha256"):
            stale.append(f"{name} ({art.get('path')}) is not the file the check built")
    if args.index:
        cleared = {source_of_index(i) for i in args.index}
        missing = sorted(plan_sources(read_json(work / "plan.json")) - cleared)
        if missing:
            stale.append(f"the plan uses source(s) {', '.join(missing)} not in the cleared "
                         f"--index list (compliance pass 2 narrowed the pool) - re-resolve; "
                         f"the voice is reusable")
    if stale:
        print(f"STALE: {args.script_id}: " + "; ".join(stale) + " - build it as before")
        return EXIT_STALE
    print(f"REUSE: {args.script_id} - plan {work / 'plan.json'} was built by the Editor's "
          f"gates before the handoff (round {verdict.get('round')}); the voice, the resolve "
          f"and the plan are not rebuilt - go to the render (step 7)")
    return EXIT_ASSEMBLED


def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="TTS -> resolve -> plan, no render; writes the verdict")
    c.add_argument("batch")
    c.add_argument("--script-id", required=True)
    c.add_argument("--channel", default=None, help="default: 03's `channel`")
    c.add_argument("--slug", default=None,
                   help="work/<slug>/; default: the title_ref name slugified")
    c.add_argument("--index", action="append", default=[],
                   help="a shots.json to resolve against, repeatable; default: the "
                        "script's anchor_coverage_pool.indexes")
    c.add_argument("--narration-file", default=None,
                   help="the text to synthesize; default: hook + commentary + payoff "
                        "on one line, as the Editor reads it")
    c.add_argument("--lead-silence", type=float, default=0.0)
    c.add_argument("--style", default=None, help="passed to script_anchors.py spec")
    c.add_argument("--adopt-voice", action="store_true",
                   help="trust an existing voice.wav + words.json whose narration.txt is "
                        "exactly this text (a batch voiced before this file existed)")
    c.add_argument("--force", action="store_true",
                   help="run even when nothing changed since the last round")
    c.add_argument("--python", default=None, help="interpreter for the tools (default: this one)")
    r = sub.add_parser("reuse", help="the Editor: may this script's checked plan be rendered?")
    r.add_argument("batch")
    r.add_argument("--script-id", required=True)
    r.add_argument("--slug", default=None)
    r.add_argument("--index", action="append", default=[],
                   help="the cleared pool the Editor would resolve against; a plan using "
                        "a source outside it is stale")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return check(args) if args.cmd == "check" else reuse(args)


if __name__ == "__main__":
    sys.exit(main())
