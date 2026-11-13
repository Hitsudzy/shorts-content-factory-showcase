#!/usr/bin/env python3
"""CF-0846: a publication hold whose flags all rest on a scene the script did
not take lifts itself.

Why
---
`example-film/2026-10-21T0837Z`, topic `lf-2026-10-21-006` (The Daily Show).
The shortlist pass of compliance (`02`, `stage_checked: "01-trend-hunter"`)
put `review` on the whole topic because of its scene 2 (sitting politicians at
the centre); scene 1 was harmless on its own. The Content Researcher wrote the
script on scene 1. The publication hold (CF-0318, `publish/publication-holds.json`)
still waited for the user's signature - a hold earned by a scene that is not in
the video. The user, 2026-10-21: "да, заводи задачу".

What it does
------------
The agent's half (agents/compliance-checker, `sensitivity_scenes.py`) makes the
pass write which scenes a flag rests on: `content_sensitivity_check.scenes`, a
list of the topic's scene ids or `"whole_topic"`. This half, the root's, runs
once the scripts are chosen - the plan's `scene-holds` stage of the close, after
both compliance passes - and for every hold of the batch:

* **lifts** a standing (unresolved, unsigned) hold when the batch has at least
  one script of its topic and `sensitivity_scenes.hold_spared_by_scene()` says
  yes for the scene of **every** one of them: the hold was raised by the
  shortlist pass, its flag is tied to scenes, and the script's scene is a scene
  of the topic (`01-trend-hunter.json`) that is not one of them. The row is
  resolved in place - `resolved_at`, `resolved_reason` (starts with the code
  `flagged_scene_not_in_script`), `resolved_reason_code` and `scene_release`
  (the script's scenes, the scripts, the flagged scenes); never deleted, no
  signature written or needed - and one line goes to the user
  (`shared/notify.py`, kind `hold_released`);
* **puts back** a hold this rule lifted before when the scenes no longer spare
  it (a later round wrote a script on the flagged scene): the rule may only
  lift what it still can, so the row stands again and needs the signature;
* leaves everything else alone: a flag on the whole topic, on the chosen scene,
  an old row without `scenes` (fail closed - `sensitivity_scenes.flagged_scenes`
  reads every doubt as "the whole topic"), a hold of the scripts pass (`04`), a
  signed row, a row resolved by anything else, a topic with no script in this
  batch directory (nothing to judge - a rebuild's `03` carries only its videos).

Idempotent: a second run over the same files changes nothing and sends nothing
(the notification's key carries the hold and the moment it was lifted).

What it does not do (the task's item 4): it never reads the script's text. A
flag checked against the final words of the script would soften the gate, and
that needs the user's signature.

Safe when the agent is older
----------------------------
The agent's modules are loaded by path from this checkout
(`agents/compliance-checker/scripts/`). A checkout pinned before CF-0846 has no
`sensitivity_scenes.py`: then nothing is lifted, the step says so on stdout and
exits 0 - the holds stand exactly as before. A ledger that does not parse, or
a batch whose `03` / `01` cannot be read, lifts nothing and exits 1 (the plan
step takes 1 as ok: the close goes on).

    runlog scene-holds [--batch DIR] [--dry-run] [--json] [--no-notify]
"""
import argparse
import copy
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

TASK = "CF-0846"
CODE = "flagged_scene_not_in_script"          # sensitivity_scenes.RESOLVED_REASON_CODE
NOTIFY_KIND = "hold_released"
RELEASE_KEY = "scene_release"
CODE_KEY = "resolved_reason_code"
REOPENED_KEY = "scene_release_reopened"
BY = "runlog scene-holds"

CODE_ROOT = Path(__file__).resolve().parents[2]
AGENT_SCRIPTS = Path("agents") / "compliance-checker" / "scripts"
SCENES_FILE = "sensitivity_scenes.py"
HOLD_FILE = "publication_hold.py"
SCRIPTS_FILE = "03-content-researcher.json"
TOPICS_FILE = "01-trend-hunter.json"

# what a row's action is
RELEASE, REOPEN, KEEP, HOLD, TIDY = "release", "reopen", "already", "held", "tidy"


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def data_root(root=None):
    if root:
        return Path(root)
    env = os.environ.get("FACTORY_ROOT")
    return Path(env).expanduser().resolve() if env else CODE_ROOT


# --------------------------------------------------------------------------
# the agent's modules, by path
# --------------------------------------------------------------------------
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    sys.modules[name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    finally:
        sys.path[:] = saved        # the agent's module puts its own folder first
    return mod


def agent_modules(code_root=None):
    """`(sensitivity_scenes, publication_hold, problem)`; on a problem both
    modules are None and nothing may be lifted."""
    base = Path(code_root or CODE_ROOT) / AGENT_SCRIPTS
    scenes_path, hold_path = base / SCENES_FILE, base / HOLD_FILE
    if not scenes_path.is_file():
        return None, None, (f"{AGENT_SCRIPTS / SCENES_FILE} is not in this checkout (the "
                            f"compliance-checker is pinned before {TASK}): no hold is lifted "
                            f"by scene")
    try:
        ss = _load("sensitivity_scenes_for_scene_holds", scenes_path)
        ph = _load("publication_hold_for_scene_holds", hold_path)
    except Exception as e:                                       # noqa: BLE001
        return None, None, (f"the compliance-checker's modules did not load "
                            f"({e.__class__.__name__}: {e}): no hold is lifted by scene")
    for need in ("hold_spared_by_scene", "topic_scene_ids"):
        if not hasattr(ss, need):
            return None, None, f"{SCENES_FILE} has no {need}(): no hold is lifted by scene"
    return ss, ph, None


# --------------------------------------------------------------------------
# the channel a batch or a ledger row was written under (CF-0197)
# --------------------------------------------------------------------------
_CHANNEL_IDS = []


def _channel_ids():
    """The root's shared/channel_ids.py, loaded by path once (CF-0231: `shared`
    is a guarded directory; the module keeps its own cache of the mapping).
    None when it does not load - then names are taken as they are."""
    if _CHANNEL_IDS:
        return _CHANNEL_IDS[0]
    path = Path(__file__).resolve().parents[1] / "channel_ids.py"
    try:
        spec = importlib.util.spec_from_file_location("channel_ids_for_scene_holds", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:                                   # noqa: BLE001
        mod = None
    _CHANNEL_IDS.append(mod)
    return mod


def resolve_channel(name, root=None):
    """Today's id of a channel named by a former one, through the root's
    `channel_ids.resolve_channel`; the name as it is when that module is
    missing or the mapping cannot be read."""
    cid = _channel_ids()
    if not name or cid is None:
        return name
    try:
        return cid.resolve_channel(name, root=root)
    except Exception:                                   # noqa: BLE001
        return name


# --------------------------------------------------------------------------
# reading the batch
# --------------------------------------------------------------------------
def scripts_by_topic(doc03):
    """`{topic_id: [(script_id, scene_id), ...]}` from `03-content-researcher.json`."""
    out = {}
    scripts = doc03.get("scripts") if isinstance(doc03, dict) else None
    for s in scripts if isinstance(scripts, list) else []:
        if isinstance(s, dict) and s.get("topic_id"):
            out.setdefault(s["topic_id"], []).append((s.get("script_id"), s.get("scene_id")))
    return out


def short_scene(scene_id, topic_id):
    """`lf-2026-10-21-006-s2` -> `s2` (the topic's prefix taken off)."""
    s = str(scene_id or "")
    pre = f"{topic_id}-"
    return s[len(pre):] if topic_id and s.startswith(pre) and len(s) > len(pre) else s


def _signed(row):
    sig = row.get("signature")
    return isinstance(sig, dict) and bool(sig.get("user"))


def _ours(row):
    return row.get(CODE_KEY) == CODE


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------
def decide(rows, channel, batch_id, by_topic, scenes_of_topic, ss, resolve=None, root=None):
    """`[(action, row, info)]` for every ledger row of this batch.

    `info`: `{"why", "script_scenes", "scripts", "flagged"}`. Pure: nothing
    is written. A row's stored channel is mapped to today's id by `resolve`
    when one is given, else by the root's `resolve_channel` under `root`."""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_channel = (resolve(row.get("channel") or "") if resolve
                       else resolve_channel(row.get("channel") or "", root=root))
        if row_channel != channel or row.get("batch_id") != batch_id:
            continue
        topic = row.get("topic_id")
        scripts = by_topic.get(topic) or []
        info = {"scripts": [s for s, _ in scripts],
                "script_scenes": [sc for _, sc in scripts],
                "flagged": sorted(ss.flagged_scenes(row.get(ss.CHECK_KEY)) or [])}
        if _signed(row):
            continue                       # a human's signature: not this rule's row
        resolved = bool(row.get("resolved_at"))
        if resolved and not _ours(row):
            continue                       # resolved by something else: not ours to judge
        # merge() re-opens a row this rule had lifted when the pass that raised
        # it runs again: the leftovers of the old release must not read as
        # "lifted" - taken off (TIDY) unless the row is lifted again right away.
        stale = not resolved and (_ours(row) or RELEASE_KEY in row)
        if not scripts:
            if not resolved:
                out.append((TIDY if stale else HOLD, row,
                            dict(info, why=f"no script of {topic} in this batch's "
                                           f"{SCRIPTS_FILE} - nothing to judge")))
            continue
        verdicts = [ss.hold_spared_by_scene(row, scene, scenes_of_topic.get(topic, []))
                    for _, scene in scripts]
        spared = all(v[0] for v in verdicts)
        why = "; ".join(dict.fromkeys(v[1] for v in verdicts))
        if resolved:                       # lifted by this rule before
            out.append((KEEP if spared else REOPEN, row, dict(info, why=why)))
        elif spared:
            out.append((RELEASE, row, dict(info, why=why)))
        else:
            out.append((TIDY if stale else HOLD, row, dict(info, why=why)))
    return out


def reason_text(row, info):
    topic = row.get("topic_id")
    flagged = ", ".join(info["flagged"]) or "?"
    scenes = ", ".join(str(s) for s in info["script_scenes"])
    scripts = ", ".join(str(s) for s in info["scripts"])
    return (f"{CODE}: every content-sensitivity flag of the shortlist pass rests on "
            f"{flagged}; the script ({scripts}) took {scenes} - a scene the flag does not "
            f"touch. Lifted by the root, no signature needed ({TASK}); the rule never reads "
            f"the script's text. Topic {topic}.")


def notify_text(channel, row, info):
    topic = row.get("topic_id")
    fl = ", ".join(short_scene(s, topic) for s in info["flagged"]) or "?"
    sc = ", ".join(short_scene(s, topic) for s in info["script_scenes"])
    return (f"{channel}: удержание {topic} снято — флаг комплаенса на сцене {fl}, "
            f"в ролике {sc} ({TASK})")


def apply(rows_doc, decisions, batch_rel, when=None):
    """The ledger with every decision applied; `(ledger, changed)`. Only the
    rows of `decisions` are touched; the order of the ledger is kept."""
    out = copy.deepcopy(rows_doc)
    by_id = {id(r): i for i, r in enumerate(rows_doc.get("holds") or [])}
    changed = []
    when = when or _now()
    for action, row, info in decisions:
        if action not in (RELEASE, REOPEN, TIDY):
            continue
        target = out["holds"][by_id[id(row)]]
        if action == RELEASE:
            target["resolved_at"] = when
            target["resolved_reason"] = reason_text(row, info)
            target[CODE_KEY] = CODE
            target[RELEASE_KEY] = {"task": TASK, "script_scenes": info["script_scenes"],
                                   "scripts": info["scripts"], "flagged_scenes": info["flagged"],
                                   "by": BY, "batch_dir": batch_rel}
            target.pop(REOPENED_KEY, None)
        else:                              # REOPEN, TIDY: the row stands
            was = target.pop(RELEASE_KEY, None)
            target.pop(CODE_KEY, None)
            if action == REOPEN:
                target["resolved_at"] = None
                target["resolved_reason"] = None
                target[REOPENED_KEY] = {"at": when, "task": TASK, "was": was,
                                        "why": info["why"],
                                        "script_scenes": info["script_scenes"]}
        changed.append((action, target, info))
    return out, changed


# --------------------------------------------------------------------------
# the run
# --------------------------------------------------------------------------
def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rel(path, root):
    try:
        return str(Path(path).resolve().relative_to(Path(root).resolve()))
    except ValueError:
        return str(path)


def _send(channel, row, info, root):
    nf = _load("notify_for_scene_holds", CODE_ROOT / "shared" / "notify.py") \
        if "notify_for_scene_holds" not in sys.modules else sys.modules["notify_for_scene_holds"]
    key = f"{NOTIFY_KIND}:{row.get('hold_id')}:{row.get('resolved_at')}"
    return nf.send(NOTIFY_KIND, key, notify_text(channel, row, info), channel=channel,
                   link=nf.link_of(channel, "acceptance"), root=root)


def run(batch_dir, root=None, code_root=None, dry_run=False, notify=True, send=None,
        when=None):
    """Judge every hold of the batch in `batch_dir`. Returns a report dict:
    `{ok, batch, channel, batch_id, problem, lifted, reopened, held, already,
    tidied, written, notified, lines}`. Never raises on a bad file."""
    root = data_root(root)
    bdir = Path(batch_dir)
    rep = {"ok": True, "task": TASK, "batch": str(bdir), "channel": None, "batch_id": None,
           "problem": None, "lifted": [], "reopened": [], "held": [], "already": [],
           "tidied": [], "written": False, "notified": [], "lines": []}
    say = rep["lines"].append

    ss, ph, problem = agent_modules(code_root)
    if problem:
        rep["problem"] = problem
        say(f"scene-holds: {problem}")
        return rep
    try:
        doc03 = _read(bdir / SCRIPTS_FILE)
    except (OSError, ValueError) as e:
        rep.update(ok=not (bdir / SCRIPTS_FILE).exists(),
                   problem=f"{SCRIPTS_FILE} not readable ({e.__class__.__name__})")
        say(f"scene-holds: {rep['problem']} - no script, nothing lifted")
        return rep
    try:
        doc01 = _read(bdir / TOPICS_FILE)
    except (OSError, ValueError) as e:
        rep.update(ok=False, problem=f"{TOPICS_FILE} not readable ({e.__class__.__name__})")
        say(f"scene-holds: {rep['problem']} - the topic's scenes are unknown, nothing lifted")
        return rep

    channel = resolve_channel(doc03.get("channel") or bdir.parent.name, root=root)
    batch_id = doc03.get("batch_id") or bdir.name
    rep.update(channel=channel, batch_id=batch_id)
    path = ph.ledger_path(root)
    for attempt in (1, 2):
        before = path.read_bytes() if path.exists() else None
        ledger, problem = ph.read_ledger(path=path)
        if problem:
            rep.update(ok=False, problem=problem)
            say(f"scene-holds: the hold ledger cannot be read ({problem}) - nothing lifted")
            return rep
        decisions = decide(ledger.get("holds") or [], channel, batch_id,
                           scripts_by_topic(doc03), ss.topic_scene_ids(doc01), ss, root=root)
        new, changed = apply(ledger, decisions, _rel(bdir, root), when=when)
        if dry_run or not changed:
            break
        now = path.read_bytes() if path.exists() else None
        if now != before:              # someone (the center's signature) wrote meanwhile
            if attempt == 2:
                rep.update(ok=False, problem="the ledger kept changing under this step")
                say("scene-holds: the ledger changed while it was read twice - nothing written")
                return rep
            continue
        try:
            ph.write_ledger(new, path=path)
        except OSError as e:
            rep.update(ok=False, problem=f"the ledger could not be written ({e})")
            say(f"scene-holds: {rep['problem']}")
            return rep
        rep["written"] = True
        break

    for action, row, info in decisions:
        hid = row.get("hold_id")
        if action == HOLD:
            rep["held"].append(hid)
            say(f"held      {hid}: {info['why']}")
        elif action == KEEP:
            rep["already"].append(hid)
    for action, row, info in changed:
        hid = row.get("hold_id")
        if action == RELEASE:
            rep["lifted"].append(hid)
            say(f"{'would lift' if dry_run else 'lifted   '} {hid}: {notify_text(channel, row, info)}")
            if notify and not dry_run:
                res = (_send if send is None else send)(channel, row, info, root)
                rep["notified"].append({"hold_id": hid, "status": (res or {}).get("status")})
        elif action == REOPEN:
            rep["reopened"].append(hid)
            say(f"{'would put back' if dry_run else 'put back '} {hid}: {info['why']} - "
                f"the hold stands again and needs the signature")
        elif action == TIDY:
            rep["tidied"].append(hid)
            rep["held"].append(hid)
            say(f"held      {hid}: {info['why']} (the old scene release taken off the row)")
    say(f"scene-holds {channel}/{batch_id}: {len(rep['lifted'])} lifted, "
        f"{len(rep['reopened'])} put back, {len(rep['held'])} still held"
        + (" (dry run, nothing written)" if dry_run else "") + f" ({TASK})")
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="runlog scene-holds",
        description=f"lift the publication holds whose flags rest on a scene the script "
                    f"did not take ({TASK})")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--root", default=None, help="the factory root (default FACTORY_ROOT / this checkout)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-notify", action="store_true")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import runlog                                               # noqa: E402
    bdir = runlog.find_batch_dir(ns.batch)
    if bdir is None:
        sys.stderr.write("runlog: error: no batch directory (use --batch DIR)\n")
        return 2
    rep = run(bdir, root=ns.root, dry_run=ns.dry_run, notify=not ns.no_notify)
    if ns.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print("\n".join(rep["lines"]))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
