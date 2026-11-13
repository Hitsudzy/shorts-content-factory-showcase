#!/usr/bin/env python3
"""Every scene of `01-trend-hunter.json` stands on one source (CF-0533), and
the topic's fact is about one of its scenes (CF-0548).

CF-0533, what is left of it. Every scene carries `source_url` - exactly one,
one of the topic's `evidence.sources[].url`. A scene without one, or citing a
URL the topic does not carry, is not written: it leaves `scenes[]` for
`scenes_dropped[]` with its reason (`no_source_url` / `source_not_in_evidence`),
and a topic left without scenes gets step 6's `general` scene, built here
from the cited source's own headline, verbatim.

Retired by CF-0556 (the claims exam of 2026-10-06, the grill's Q11): the
check that every proper name of a scene's description is printed in its
source's headline or summary (CF-0533, Coach Hale 1313Z's glued Mae / Anthony
Head scene) and the check that a scene naming a doer has a clause of its
source linking them (CF-0543, Harbourlights 0701Z's Zorvath, through the root's
`plot_claims.py`). Both judged the story by headlines; since 1.8 what a video
says is quoted from the topic's support text (CF-0551) and judged by the
root's `claim_judge.py` - the exam struck the Anthony Hart line and the
Zorvath line there, on the Wikipedia text of the batch's day.

CF-0736 - a figure the shell ate. A scene whose description reads as an
amount of its source with the `$<digits>` gone («with .5 million» for the
source's «$27.5 Million») fails as `figure_lost` (`lost_figures`): the dry run
and `--check` name it, `--write` drops it like any other failing scene.

CF-0548 - the fact is about the topic itself. WNL 0701Z: the scenes were
Taylor Sterling walking into Dana Reyes's monologue, and the best candidate
the topic carried was the cold open of the same broadcast. Once the scenes
are final, `--write` judges every `fact_candidates[]` entry against them (the
root's `fact_scene.py`, loaded by path) and writes on each candidate `scenes`
(the scene ids it is about) and `scene_fit` ({scene_id: failure codes}). A
topic whose passing candidates fit none of its scenes leaves `topics[]` for
`skipped_topics[]` as `no_fact` - here, before its footage is indexed - and
its `fact_probe.fact_rule` is rewritten `not_found`. The dry run and
`--check` name such a topic as a problem.

Usage (from the agent root):
  scripts/check_scenes.py <batch-dir|01-trend-hunter.json>          # dry run: report, exit 1 on a violation
  scripts/check_scenes.py <batch-dir|01-trend-hunter.json> --write  # drop violating scenes, `general` fallback, write
  scripts/check_scenes.py <batch-dir|01-trend-hunter.json> --check  # validate a finished batch, change nothing
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _runlog import factory_root, runlog  # noqa: E402
import skipped_codes  # noqa: E402  (CF-0708)

TASK = "CF-0533"

# CF-0548: the fact is about the topic's own scene. The rule lives at the root
# and is loaded by path - no copy here.
FACT_TASK = "CF-0548"
FACT_SCENE_REL = Path("shared") / "factrule" / "fact_scene.py"
CANDIDATES_KEY = "fact_candidates"
FACT_REFUSAL_CODE = "no_fact"   # fact_rule.REFUSAL_CODE (CF-0438)


def _fact_scene():
    import importlib.util
    path = factory_root() / FACT_SCENE_REL
    if not path.is_file():
        raise RuntimeError(f"{path} not found - the scene-fit rule lives in the factory root "
                           f"({FACT_TASK})")
    spec = importlib.util.spec_from_file_location("fact_scene_th", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fact_scene = _fact_scene()


def sources_by_url(topic):
    return {s.get("url"): s for s in ((topic.get("evidence") or {}).get("sources") or [])
            if isinstance(s, dict) and s.get("url")}


# CF-0736: a figure the shell ate. `example-film/2026-10-13T1411Z`, Other
# Mommy: the scenes were written through an unquoted heredoc (`python3 - <<E`),
# the shell read «$27.5» and «$5.5» as its positional parameters, and the
# scene said «tops the box office with .5 million ... a .5 million debut».
# zsh eats every digit after the `$` («$27.5» -> «.5», «$5 million» -> «
# million»), bash one («$27.5» -> «7.5»). The source still prints the amount,
# so the scene is read against it.
FIGURE_TASK = "CF-0736"
FIGURE_LOST_CODE = "figure_lost"
_AMOUNT_RE = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)(\s*(?:million|billion|bn|[MBK])\b)?", re.I)
_NUMBER_RE = re.compile(r"(?<![\d.,])\d[\d,]*(?:\.\d+)?")
_BARE_DECIMAL_RE = re.compile(r"(?<![\w.,$£€])\.\d+")
_SCALED_BARE_RE = re.compile(r"(?<![\w.,$£€])\.\d+\s*(?:million|billion|thousand|bn|[MBK]\b|%)", re.I)
_SCALE_RE = re.compile(r"\b(million|billion)\b", re.I)
_NUMBER_BEFORE_SCALE_RE = re.compile(r"\d[\d,]*(?:\.\d+)?\s*$")


def lost_figures(description, source):
    """-> what of the description reads as a figure that lost its `$<digits>`
    to the shell ([] when nothing does): a number with no digit before its
    point, an amount of the source with its first digit gone, or a «million»
    with no number when the source prints one."""
    desc = description or ""
    text = " ".join(str((source or {}).get(k) or "") for k in ("title", "summary"))
    amounts = _AMOUNT_RE.findall(text)
    out = []
    bare = _SCALED_BARE_RE.search(desc) or (_BARE_DECIMAL_RE.search(desc) if amounts else None)
    if bare:
        out.append(f"{bare.group(0).strip()!r} has no digit before its point")
    numbers = set(_NUMBER_RE.findall(desc))
    figures = {a for a, _ in amounts}
    for amount, scale in amounts:
        if amount in desc:
            continue
        head = re.match(r"\d+", amount).group()
        eaten = amount[1:]
        if len(head) >= 2 and eaten in numbers and eaten not in figures:
            out.append(f"{eaten!r} where the source prints ${amount}")
    scaled = next((f"${a}{sc}" for a, sc in amounts
                   if sc.strip().lower() in ("million", "billion")), None)
    if scaled:
        for m in _SCALE_RE.finditer(desc):
            if not _NUMBER_BEFORE_SCALE_RE.search(desc[:m.start()]):
                out.append(f"{m.group(0)!r} with no number where the source prints {scaled}")
                break
    return out


def judge_scene(scene, topic):
    """-> None when the scene names one source of its topic, else a dict with
    `reason_code` and `reason`."""
    sid = scene.get("scene_id", "?")
    url = scene.get("source_url")
    if not (isinstance(url, str) and url.strip()):
        return {"reason_code": "no_source_url",
                "reason": f"{sid}: no source_url - a scene names exactly one of the topic's "
                          f"evidence.sources[].url ({TASK})"}
    source = sources_by_url(topic).get(url)
    if source is None:
        return {"reason_code": "source_not_in_evidence",
                "reason": f"{sid}: source_url {url!r} is not one of the topic's "
                          f"evidence.sources[].url ({TASK})"}
    lost = lost_figures(scene.get("description"), source)
    if lost:
        return {"reason_code": FIGURE_LOST_CODE,
                "reason": f"{sid}: the description lost a figure - {'; '.join(lost)}. A `$` "
                          f"followed by digits was read by the shell (an unquoted heredoc or a "
                          f"double-quoted string); write scenes through a quoted heredoc "
                          f"(`<<'EOF'`) and copy the amount from the source ({FIGURE_TASK})"}
    return None


# --------------------------------------------------------------------------
# a topic / a batch
# --------------------------------------------------------------------------

def _scene_number(scene_id):
    m = re.search(r"-s(\d+)$", str(scene_id or ""))
    return int(m.group(1)) if m else 0


def general_scene(topic, dropped):
    """Step 6's `general` scene, built from a source's own headline - the
    first cited source of a dropped scene that is in the evidence, else the
    topic's first source with a title. None when there is no such source."""
    by_url = sources_by_url(topic)
    pick = None
    for d in dropped:
        s = by_url.get(d.get("source_url"))
        if s and s.get("title"):
            pick = s
            break
    if pick is None:
        pick = next((s for s in by_url.values() if s.get("title")), None)
    if pick is None:
        return None
    tid = topic.get("topic_id", "topic")
    used = [_scene_number(s.get("scene_id")) for s in (topic.get("scenes") or []) + list(
        topic.get("scenes_dropped") or []) + list(dropped)]
    return {"scene_id": f"{tid}-s{max(used + [0]) + 1}",
            "description": pick["title"], "tags": ["general"], "source_url": pick["url"]}


def apply_topic(topic):
    """Drop the violating scenes of one topic into `scenes_dropped[]`, add the
    `general` fallback when none is left. -> (lines, problems)."""
    tid = topic.get("topic_id", "?")
    kept, dropped, lines, problems = [], [], [], []
    for scene in topic.get("scenes") or []:
        verdict = judge_scene(scene, topic)
        if verdict is None:
            kept.append(scene)
            continue
        record = {k: scene.get(k) for k in ("scene_id", "description", "tags", "source_url")}
        record.update(verdict)
        record["stage"] = "trend-hunter"
        dropped.append(record)
        lines.append(f"topic {tid} DROP {verdict['reason']}")
    if dropped:
        if not kept:
            fallback = general_scene(topic, dropped)
            if fallback is None:
                problems.append(f"topic {tid}: every scene dropped and the topic has no source with a "
                                f"title - no `general` scene can be anchored ({TASK})")
            else:
                kept.append(fallback)
                lines.append(f"topic {tid} GENERAL {fallback['scene_id']} from "
                             f"{fallback['source_url']} ({fallback['description']!r})")
        topic["scenes"] = kept
        topic["scenes_dropped"] = list(topic.get("scenes_dropped") or []) + dropped
    elif not kept:
        problems.append(f"topic {tid}: no scenes")
    return lines, problems


def check_topic(topic):
    """-> [problem, ...] for a finished topic: every scene stands on its
    source, the topic has at least one, every drop is recorded with a code."""
    tid = topic.get("topic_id", "?")
    scenes = topic.get("scenes") or []
    problems = [f"topic {tid} {v['reason']}" for v in (judge_scene(s, topic) for s in scenes) if v]
    if not scenes:
        problems.append(f"topic {tid}: no scenes - a topic carries at least the `general` one")
    for i, d in enumerate(topic.get("scenes_dropped") or []):
        if not (isinstance(d, dict) and d.get("reason_code") and d.get("reason")):
            problems.append(f"topic {tid} scenes_dropped[{i}]: a drop without reason_code/reason")
    return problems


# --------------------------------------------------------------------------
# CF-0548: the topic's fact candidates against its scenes
# --------------------------------------------------------------------------

def _passing(candidates):
    return [c for c in candidates or [] if isinstance(c, dict)
            and (c.get("check") or {}).get("passes")]


def fact_fit(topic, batch_topics):
    """-> (annotated candidates, off_scene_only). `off_scene_only` is True when
    the topic carries passing candidates and not one of them fits any of its
    scenes - the cold open under the monologue (WNL 0701Z)."""
    cands = topic.get(CANDIDATES_KEY)
    if not isinstance(cands, list) or not (topic.get("scenes") or []):
        return None, False
    annotated = fact_scene.annotate(cands, topic, batch_topics)
    passing = _passing(annotated)
    return annotated, bool(passing) and not any(c.get(fact_scene.SCENES_KEY) for c in passing)


def off_scene_reason(topic, annotated):
    passing = _passing(annotated)
    codes = []
    for c in passing:
        for code in fact_scene.failure_summary(c):
            if code not in codes:
                codes.append(code)
    return (f"No fact about the topic itself: {len(passing)} candidate(s) passed the fact "
            f"rule and every one is about something other than the topic's "
            f"{len(topic.get('scenes') or [])} scene(s) ({', '.join(codes)}) - another segment "
            f"of the same broadcast, another topic's work, nobody of the scene. A fact about "
            f"the neighbouring story is no fact for this one ({FACT_TASK}).")


def apply_facts(batch):
    """--write: annotate every topic's candidates with the scenes they fit;
    a topic none of whose passing candidates fits any scene leaves `topics[]`
    for `skipped_topics[]` as no_fact, before a second of its footage is
    indexed. -> lines."""
    topics = [t for t in batch.get("topics") or [] if isinstance(t, dict)]
    kept, lines = [], []
    for topic in topics:
        annotated, off_only = fact_fit(topic, topics)
        if annotated is None:
            kept.append(topic)
            continue
        topic[CANDIDATES_KEY] = annotated
        if not off_only:
            kept.append(topic)
            continue
        reason = off_scene_reason(topic, annotated)
        probe = topic.get("fact_probe") if isinstance(topic.get("fact_probe"), dict) else None
        if probe is not None and isinstance(probe.get("fact_rule"), dict):
            probe["fact_rule"] = dict(probe["fact_rule"], state="not_found", drops=True,
                                      status="no_candidates", detail=FACT_TASK)
        ref = topic.get("title_ref") or {}
        batch.setdefault("skipped_topics", []).append({
            "topic_id": topic.get("topic_id"), "reason_code": FACT_REFUSAL_CODE,
            "reason": reason, "stage": "trend-hunter", "title": ref.get("name"),
            "fact_probe": probe, CANDIDATES_KEY: annotated, "rule": FACT_TASK})
        lines.append(f"topic {topic.get('topic_id')} NO_FACT {reason}")
    if len(kept) != len(topics):
        batch["topics"] = kept
    return lines


def check_facts(batch):
    """--check / dry run: a topic still carrying only off-scene candidates."""
    topics = [t for t in batch.get("topics") or [] if isinstance(t, dict)]
    out = []
    for topic in topics:
        annotated, off_only = fact_fit(topic, topics)
        if off_only:
            out.append(f"topic {topic.get('topic_id')} {off_scene_reason(topic, annotated)}")
    return out


def run_batch(batch, write=False):
    """-> (lines, problems). Dry run when not `write`: every violation is a
    problem and nothing changes. With `write`: violations are applied (drop +
    fallback) and only what cannot be applied is a problem."""
    lines, problems = [], []
    for topic in batch.get("topics") or []:
        if write:
            got, bad = apply_topic(topic)
            lines.extend(got)
            problems.extend(bad)
        else:
            for scene in topic.get("scenes") or []:
                verdict = judge_scene(scene, topic)
                if verdict:
                    problems.append(f"topic {topic.get('topic_id', '?')} {verdict['reason']}")
    # CF-0548, after the scenes are final: the fact is judged against the
    # scenes that stay, never against a dropped one.
    if write:
        lines.extend(apply_facts(batch))
    else:
        problems.extend(check_facts(batch))
    return lines, problems


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _batch_path(arg):
    path = Path(arg).expanduser()
    return path / "01-trend-hunter.json" if path.is_dir() else path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch", help="batch directory or its 01-trend-hunter.json")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true",
                      help="drop violating scenes into scenes_dropped[], add the general fallback, write in place")
    mode.add_argument("--check", action="store_true", help="validate a finished batch, change nothing")
    args = ap.parse_args(argv)

    path = _batch_path(args.batch)
    if not path.exists():
        print(f"no {path}", file=sys.stderr)
        return 2
    batch = json.load(open(path))
    if args.check:
        lines = []
        problems = [p for t in batch.get("topics") or [] for p in check_topic(t)]
        problems += check_facts(batch)
        # CF-0708: the finished batch's refusals carry the funnel's words only.
        problems += skipped_codes.check_batch(batch)
    else:
        lines, problems = run_batch(batch, write=args.write)
        if args.write:
            with open(path, "w") as fh:
                json.dump(batch, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
    topics = batch.get("topics") or []
    scenes = sum(len(t.get("scenes") or []) for t in topics)
    dropped = sum(len(t.get("scenes_dropped") or []) for t in topics)
    print(f"{path.name}: {len(topics)} topics, {scenes} scenes, {dropped} dropped, "
          f"{len(problems)} problems", file=sys.stderr)
    for line in lines + problems:
        print(f"  {line}", file=sys.stderr)
    return 1 if problems else 0


@runlog.script("trend-hunter", "check-scenes", name="check_scenes.py")
def cli(argv=None):
    """main()'s return code becomes the exit code inside the run event."""
    sys.exit(main(argv))


if __name__ == "__main__":
    cli()
