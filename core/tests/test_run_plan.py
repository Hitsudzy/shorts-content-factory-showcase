#!/usr/bin/env python3
"""CF-0202: the run plan of a channel and its validator (`shared/run_plan.py`).

Three things are held here.

1. The committed ExampleFilm plan (`channels/example-film.json` -> `run_plan`)
   is valid, and it is the *only* record of the order (CF-0204): the
   documents point at `run_plan.py show` and do not list the stages again -
   no arrow chain of stages, no fenced block of stage markers or close
   commands in sequence, the close table alphabetical. The README's diagram
   is the factory's common picture (docs/readme-template.md, shared by six
   READMEs) and is held to the plan, not the plan to it. The CF-0306 /
   CF-0345 rules of `docs/pipeline.md` still say why a stage sits where it
   does, and the plan is held to them. The whole order is also pinned as an
   explicit list, so a change to it is a change to this file.
2. Every refusal of the validator, on a synthetic plan: unknown agent, missing
   script / SKILL.md, duplicate id, cycle, unreachable stage, a handler nobody
   calls, a consumed file nobody produces (or nobody upstream does), two
   producers, unknown marker / placeholder, a decision with no automatic default.
3. A different graph is a valid plan: a synthetic channel with stages
   ExampleFilm does not have and without the ones it has.
"""
import copy
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

import run_plan as rp  # noqa: E402



def _real():
    return rp.load("example-film", ROOT)


def _skip_missing():
    """A root tree without the agents' checkouts (CF-0191) still checks the
    structure; on a full checkout every path is checked."""
    return any(not (ROOT / p).is_dir() for p in rp.lock_agents(ROOT).values())


def _pos(order):
    return {s: i for i, s in enumerate(order)}


# --------------------------------------------------------------------------
# 1. the committed plan
# --------------------------------------------------------------------------

def test_the_example_film_plan_is_valid():
    errs = rp.validate(_real(), ROOT, skip_missing_checkouts=_skip_missing())
    assert errs == [], "\n".join(errs)




# The README's "Place in the pipeline" diagram, node -> stage of the plan.
# PLAN (step 6b) runs inside the Researcher's stage (its SKILL step 6b); ACC
# and PUB are after the run (the user's acceptance, publish/), not stages.
README_NODES = {"PM": "pool-maintenance", "TH": "trend-hunter",
                "CC1": "compliance-shortlist", "FI": "footage-indexer",
                "CR": "content-researcher", "PLAN": None,
                "SUP": "thin-pool-supplement", "CC2": "compliance-scripts",
                "VE": "video-editor", "FJ": "frame-judge", "ACC": None, "PUB": None}




















# The whole order as the operator runs a batch today - docs/running-a-batch.md
# (Studio read, batch-start, the close), docs/run-accounting.md
# (pool-maintenance before the first agent), docs/pipeline.md (CF-0306,
# CF-0345, CF-0422, the stop-cock), README (the diagram), frame-judge after the
# Editor (.claude/skills/frame-judge/SKILL.md). rotation-backfill is the
# operator's practice that test_rotation_ledger.py enforces; no doc names it.
EXPECTED_ORDER = [
    "studio-read-due", "rights-check", "batch-start", "pool-maintenance",
    "trend-hunter", "compliance-shortlist", "footage-indexer", "content-researcher",
    "content-researcher-empty", "reserve-below-shortlist", "footage-indexer-reserve",
    "content-researcher-reserve",
    "thin-pool-supplement", "plan-check-after-supplement",
    "reserve-below-shortlist-late", "footage-indexer-reserve-late", "content-researcher-reserve-late",
    "thin-pool-supplement-late", "plan-check-after-supplement-late",
    "compliance-scripts", "video-editor", "frame-judge-empty", "frame-judge",
    "judge-repair-request", "judge-repair-editor", "judge-repair-judge",
    "reserve-below-shortlist-judge",
    "footage-indexer-reserve-judge", "content-researcher-reserve-judge",
    "thin-pool-supplement-judge", "plan-check-after-supplement-judge",
    "compliance-scripts-judge", "video-editor-judge", "frame-judge-judge",
    "batch-done", "monitors", "triage", "rotation-backfill", "footage-wanted",
    "scene-holds", "commit-records",
]
# CF-0881: the repair pass goes first after the judge, the reserve round after it;
# CF-0882: the refill from below the shortlist right before the round's indexer
REPAIR_AFTER_JUDGE = ["judge-repair-request", "judge-repair-editor", "judge-repair-judge"]
REFILL_JUDGE = ["reserve-below-shortlist-judge"]
REFILL_STAGES = {"reserve-below-shortlist": ("first", "below_shortlist_refill",
                                             "footage-indexer-reserve"),
                 "reserve-below-shortlist-late": ("late", "below_shortlist_refill_late",
                                                  "footage-indexer-reserve-late"),
                 "reserve-below-shortlist-judge": ("judge", "below_shortlist_refill_judge",
                                                   "footage-indexer-reserve-judge")}
ROUND_AFTER_JUDGE = EXPECTED_ORDER[EXPECTED_ORDER.index("footage-indexer-reserve-judge"):
                                   EXPECTED_ORDER.index("batch-done")]


# --- CF-0204: the plan is the one record of the order -----------------------

ARROW = re.compile(r"-->|──►|→|->|=>")
CLOSE_CMDS = ("batch-done", "monitors", "triage")




def _stage_names():
    names = {"Trend Hunter", "Compliance", "Compliance Checker", "Footage Indexer",
             "Content Researcher", "Video Editor", "Frame Judge", "frame judge"}
    for st in _real()["stages"]:
        names.add(st["id"])
        if st.get("marker"):
            names.add(st["marker"])
    return names


def _names_in(line, names):
    return {n for n in names if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", line)}


def _fences(text):
    """(lang, body) of every fenced block."""
    return re.findall(r"^```([a-z]*)\n(.*?)^```", text, re.S | re.M)


def order_listings(text, names, allow_mermaid=False):
    """Where a document lists stages in sequence: an arrow chain over three
    stages or more on one line, a mermaid flowchart, a fenced block opening two
    stages or holding two close commands. [] for a document that only points."""
    found = []
    for i, line in enumerate(text.splitlines(), 1):
        if len(ARROW.findall(line)) >= 2 and len(_names_in(line, names)) >= 3:
            found.append(f"line {i}: an arrow chain of stages: {line.strip()[:120]}")
    for lang, body in _fences(text):
        if lang == "mermaid" and not allow_mermaid:
            found.append("a mermaid diagram")
        starts = set(re.findall(r"stage-start\s+([a-z0-9-]+)", body))
        if len(starts) >= 2:
            found.append(f"a fenced block opening stages {sorted(starts)}")
        lines = body.splitlines()
        for a, b in zip(lines, lines[1:]):          # a usage reference is not a sequence
            ca = [c for c in CLOSE_CMDS if re.search(r"runlog\S*\s+" + c + r"\b", a)]
            cb = [c for c in CLOSE_CMDS if re.search(r"runlog\S*\s+" + c + r"\b", b)]
            if ca and cb and ca != cb:
                found.append(f"a fenced block of close commands in sequence {ca + cb}")
                break
    return found






def test_the_guard_catches_the_listings_it_replaced():
    """What the documents held before CF-0204 is refused by the guard."""
    names = _stage_names()
    old_ascii = "Trend Hunter ──► Compliance ──► Footage Indexer ──► Content Researcher"
    assert order_listings(old_ascii, names)
    assert order_listings("(`batch-done` → `monitors` → `triage`, then this)", names)
    old_close = ("```\nscripts/runlog batch-done\nscripts/runlog monitors --batch b\n"
                 "scripts/runlog triage --batch b\n```\n")
    assert order_listings(old_close, names)
    old_run = ("```sh\nscripts/runlog stage-start trend-hunter\n"
               "scripts/runlog stage-start compliance-checker\n```\n")
    assert order_listings(old_run, names)
    assert order_listings("```mermaid\nflowchart TD\n A --> B\n```\n", names)
    one_stage = ('```bash\n"$RUNLOG" stage-start frame-judge --batch "$B"\n'
                 '"$RUNLOG" stage-done frame-judge --batch "$B"\n```\n')
    assert order_listings(one_stage, names) == []       # a stage's own markers are its own


def test_the_whole_order_is_pinned():
    assert rp.order(_real()) == EXPECTED_ORDER


def test_every_agent_stage_runs_its_own_skill_and_writes_its_own_markers():
    """Today every agent stage is a sonnet subagent on the agent's SKILL.md,
    and the SKILL writes stage-start/stage-done itself - the executor must not
    write them a second time (CF-0203)."""
    for st in _real()["stages"]:
        if st["kind"] == "llm" and st.get("marker") in rp.known_markers():
            assert st["marker_by"] == "skill", st["id"]
            assert st["model"] == "sonnet", st["id"]
            if st["owner"] != "root":
                assert st["skill"].startswith(f"agents/{st['owner']}/"), st["id"]


def test_the_stages_after_the_researcher_respect_the_stopcock():
    by_id = {s["id"]: s for s in _real()["stages"]}
    for sid in ("compliance-scripts", "video-editor", "frame-judge", "thin-pool-supplement",
                "footage-indexer-reserve-late", "thin-pool-supplement-late",
                "plan-check-after-supplement-late",
                *[s for s in ROUND_AFTER_JUDGE if s != "content-researcher-reserve-judge"]):
        conds = by_id[sid]["when"] if isinstance(by_id[sid]["when"], list) else [by_id[sid]["when"]]
        assert any(c.get("cmd", [None, None])[1] == "stopcock" for c in conds), sid


def test_cli_validate_and_show():
    cmd = [sys.executable, str(ROOT / "shared" / "run_plan.py")]
    extra = ["--skip-missing-checkouts"] if _skip_missing() else []
    p = subprocess.run(cmd + ["validate", "example-film"] + extra, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "valid" in p.stdout
    p = subprocess.run(cmd + ["show", "example-film", "--json"] + extra, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert json.loads(p.stdout)["order"] == EXPECTED_ORDER
    p = subprocess.run(cmd + ["show", "example-film"] + extra, capture_output=True, text=True)
    listed = re.findall(r"^\s*\d+\. (\S+)", p.stdout, re.M)
    assert listed == EXPECTED_ORDER, listed


def test_cli_refuses_a_channel_without_a_plan():
    d = tempfile.mkdtemp(prefix="run-plan-test-")
    try:
        (Path(d) / "channels").mkdir()
        (Path(d) / "channels" / "bare.json").write_text("{}")
        p = subprocess.run([sys.executable, str(ROOT / "shared" / "run_plan.py"),
                            "validate", "bare", "--root", d], capture_output=True, text=True)
        assert p.returncode == 2 and "no `run_plan` key" in p.stderr, p.stderr
        p = subprocess.run([sys.executable, str(ROOT / "shared" / "run_plan.py"),
                            "validate", "nosuch", "--root", d], capture_output=True, text=True)
        assert p.returncode == 2 and "no channel config" in p.stderr, p.stderr
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --------------------------------------------------------------------------
# 2. the refusals, on a synthetic plan
# --------------------------------------------------------------------------
# Root-owned stages only, on files every root checkout holds, so these run on
# a tree without the agents too.

def _stage(sid, after=None, **kw):
    st = {"id": sid, "title": sid, "kind": "machine", "owner": "root", "marker": None,
          "steps": [{"argv": ["{runlog}", "tail", "--batch", "{batch}"]}]}
    if after is not None:
        st["after"] = after
    st.update(kw)
    return st


def _base():
    return {"version": 1, "batch_dir": "pipeline/{channel}/{batch_id}", "stages": [
        _stage("open"),
        _stage("make", ["open"], produces=["01-x.json"],
               steps=[{"argv": ["python3", "{root}/rotation/rotate.py", "--help"],
                       "on_exit": {"7": {"run": "fix", "then": "rerun"}}}]),
        _stage("fix", trigger="on_exit", kind="decision", question="what now?",
               decided_by="llm", outcomes=["retry", "give_up"], default="give_up", steps=None),
        _stage("use", ["make"], consumes=["01-x.json"], produces=["02-y.json"]),
        _stage("judge", ["use"], kind="llm", skill=".claude/skills/frame-judge/SKILL.md",
               model="sonnet", consumes=["02-y.json"], marker="frame-judge",
               marker_by="skill", steps=None),
        _stage("close", ["judge"], always=True),
    ]}


def _clean(plan):
    for st in plan["stages"]:
        if st.get("steps") is None:
            st.pop("steps", None)
    return plan


def _errs(plan):
    return rp.validate(_clean(plan), ROOT, skip_missing_checkouts=True)


def _refused(mutate, needle):
    plan = copy.deepcopy(_clean(_base()))
    mutate(plan)
    errs = _errs(plan)
    assert errs, f"accepted a plan that should fail on {needle!r}"
    assert any(needle in e for e in errs), f"no error says {needle!r}: {errs}"


def _st(plan, sid):
    return next(s for s in plan["stages"] if s["id"] == sid)


def test_the_synthetic_base_is_valid():
    errs = _errs(_base())
    assert errs == [], errs
    assert rp.order(_clean(_base())) == ["open", "make", "use", "judge", "close"]


def test_refuses_an_unknown_agent():
    _refused(lambda p: _st(p, "use").update(owner="banner-maker"),
             "neither 'root' nor an agent of agents.lock.json")


def test_refuses_a_missing_script():
    _refused(lambda p: _st(p, "use").update(
        steps=[{"argv": ["python3", "{root}/scripts/no_such_step.py"]}]), "does not exist")


def test_refuses_a_missing_skill():
    _refused(lambda p: _st(p, "judge").update(skill=".claude/skills/nope/SKILL.md"),
             "skill .claude/skills/nope/SKILL.md does not exist")


def test_refuses_an_entry_point_that_is_not_a_path_template():
    _refused(lambda p: _st(p, "use").update(steps=[{"argv": ["/usr/bin/env", "true"]}]),
             "is not a path under")


def test_refuses_a_duplicate_id():
    _refused(lambda p: p["stages"].append(_stage("use", ["make"])), "duplicate id")


def test_refuses_a_cycle():
    _refused(lambda p: _st(p, "make").update(after=["open", "judge"]), "cycle in `after`")


def test_refuses_an_unreachable_stage():
    _refused(lambda p: p["stages"].append(_stage("orphan")), "exactly one entry stage")


def test_refuses_an_after_that_names_no_stage():
    _refused(lambda p: _st(p, "use").update(after=["make", "ghost"]), "unknown stage 'ghost'")


def test_refuses_a_handler_nobody_calls():
    def m(p):
        p["stages"].append(_stage("lonely", trigger="on_exit"))
    _refused(m, "a handler no step's on_exit runs")


def test_refuses_on_exit_to_a_stage_that_is_not_a_handler():
    _refused(lambda p: _st(p, "make")["steps"][0]["on_exit"].update(
        {"8": {"run": "use", "then": "continue"}}), "has no `trigger: on_exit`")


def test_refuses_consuming_what_nobody_produces():
    _refused(lambda p: _st(p, "judge").update(consumes=["02-y.json", "03-z.json"]),
             "consumes 03-z.json, which no stage produces")


def test_refuses_consuming_what_only_a_later_stage_produces():
    def m(p):
        _st(p, "use").update(consumes=["01-x.json", "02-late.json"])
        _st(p, "close").update(produces=["02-late.json"])
    _refused(m, "is not upstream of it")


def test_refuses_two_producers_of_one_file():
    _refused(lambda p: _st(p, "close").update(produces=["01-x.json"]), "produced by both")


def test_refuses_an_unknown_marker():
    _refused(lambda p: _st(p, "use").update(marker="banner", marker_by="executor"),
             "is not a runlog stage")


def test_refuses_an_unknown_placeholder():
    _refused(lambda p: _st(p, "use").update(
        steps=[{"argv": ["{runlog}", "tail", "--batch", "{batchdir}"]}]),
        "unknown placeholder {batchdir}")


def test_refuses_a_decision_with_no_automatic_outcome():
    _refused(lambda p: _st(p, "fix").update(default="ask_the_user"),
             "takes it when nobody answers")


def test_refuses_an_unknown_condition():
    _refused(lambda p: _st(p, "use").update(when={"check": "moon_is_full"}),
             "is not a known condition")


def test_refuses_an_unknown_kind_and_key():
    _refused(lambda p: _st(p, "use").update(kind="magic"), "kind must be one of")
    _refused(lambda p: _st(p, "use").update(model="sonnet"), "unknown key(s) for kind machine")


# --------------------------------------------------------------------------
# 3. a different graph
# --------------------------------------------------------------------------

def test_a_channel_with_other_stages_is_a_valid_plan():
    """The RU channel of the 2026-09-12 grill (CF-0205), as a shape: full
    episodes fetched, a moment chosen inside an episode, a banner layer - and
    no script, no voice, no pattern rotation. Other stages, other edges, the
    same reader."""
    fi = "agents/footage-indexer/.claude/skills/footage-indexer/SKILL.md"
    plan = {"version": 1, "batch_dir": "pipeline/{channel}/{batch_id}", "stages": [
        _stage("batch-start", steps=[{"argv": ["{runlog}", "batch-start", "--batch", "{batch}"]}]),
        {"id": "fetch-episodes", "title": "full episodes", "kind": "machine",
         "owner": "footage-indexer", "marker": "footage-indexer", "marker_by": "executor",
         "after": ["batch-start"],
         "steps": [{"argv": ["{python}", "{agent_dir}/scripts/ingest_batch.py", "{batch}"]}],
         "produces": ["01-episodes.json"]},
        {"id": "pick-moment", "title": "the moment inside the episode", "kind": "llm",
         "owner": "footage-indexer", "marker": None, "after": ["fetch-episodes"],
         "skill": fi, "model": "sonnet", "args": {"batch": "{batch}"},
         "consumes": ["01-episodes.json"], "produces": ["02-moments.json"]},
        {"id": "is-it-funny", "title": "keep the moment?", "kind": "decision",
         "owner": "root", "marker": None, "after": ["pick-moment"],
         "question": "Does the moment stand without context?", "decided_by": "llm",
         "outcomes": ["keep", "drop"], "default": "drop", "consumes": ["02-moments.json"]},
        _stage("banner", ["pick-moment"], consumes=["02-moments.json"], produces=["03-banner.json"],
               steps=[{"argv": ["python3", "{root}/scripts/runlog", "render"]}]),
        _stage("batch-done", ["banner", "is-it-funny"], always=True, consumes=["03-banner.json"],
               steps=[{"argv": ["{runlog}", "batch-done", "--batch", "{batch}"]}]),
    ]}
    errs = rp.validate(plan, ROOT, skip_missing_checkouts=True)
    assert errs == [], errs
    order = rp.order(plan)
    assert order == ["batch-start", "fetch-episodes", "pick-moment", "is-it-funny",
                     "banner", "batch-done"], order
    assert not {"content-researcher", "video-editor", "trend-hunter"} & set(order)


def test_a_ceiling_and_a_note_on_exit_are_accepted():
    """CF-0204: `timeout_min` on an llm stage, `note_on_exit` on a code the
    stage goes on with."""
    plan = _clean(_base())
    _st(plan, "judge")["timeout_min"] = 45
    _st(plan, "make")["steps"][0]["note_on_exit"] = {"7": "fixed and rerun", "0": "fine"}
    assert _errs(plan) == []



def test_a_rerun_env_and_an_exhausted_last_run_are_accepted():
    """CF-0793: the plan check's rerun is told an anchor-edit pass ran
    (`rerun_env`), and past the rerun limit it runs once more with `--final`
    (`exhausted`) instead of failing the batch."""
    plan = _clean(_base())
    step = _st(plan, "make")["steps"][0]
    step["on_exit"]["7"]["rerun_env"] = {"PLAN_CHECK_EDIT_PASS": "1"}
    step["exhausted"] = {"argv_add": ["--final"], "note": "closed"}
    assert _errs(plan) == []


def test_refuses_a_bad_rerun_env_or_exhausted():
    _refused(lambda p: _st(p, "make")["steps"][0]["on_exit"]["7"].update(rerun_env={"X": 1}),
             "rerun_env must be a non-empty {name: text}")
    _refused(lambda p: _st(p, "make")["steps"][0]["on_exit"]["7"].update(rerun_env={}),
             "rerun_env must be a non-empty {name: text}")
    _refused(lambda p: _st(p, "make")["steps"][0].update(exhausted={"argv_add": []}),
             "exhausted must be")
    _refused(lambda p: _st(p, "make")["steps"][0].update(exhausted={"argv_add": ["--x"],
                                                                    "then": "go"}),
             "exhausted must be")
    _refused(lambda p: _st(p, "use")["steps"][0].update(exhausted={"argv_add": ["--x"]}),
             "exhausted without an on_exit `then: rerun`")



def test_refuses_a_ceiling_that_is_not_a_positive_number():
    for bad in (0, -5, "60", True):
        _refused(lambda p, b=bad: _st(p, "judge").update(timeout_min=b),
                 "timeout_min must be a positive number")


def test_refuses_a_ceiling_on_a_machine_stage():
    _refused(lambda p: _st(p, "use").update(timeout_min=10), "unknown key(s) for kind machine")


def test_refuses_a_note_on_a_code_that_fails_the_stage():
    _refused(lambda p: _st(p, "make")["steps"][0].update(note_on_exit={"3": "x"}),
             "note_on_exit 3 is neither ok_exit nor on_exit")
    _refused(lambda p: _st(p, "make")["steps"][0].update(note_on_exit={"0": " "}),
             "must be a non-empty text")
    _refused(lambda p: _st(p, "make")["steps"][0].update(note_on_exit=["0"]),
             "note_on_exit must be an object")


def test_structure_only_without_a_root():
    """root=None checks the structure alone - no file is looked for."""
    plan = _clean(_base())
    _st(plan, "use")["steps"] = [{"argv": ["python3", "{root}/scripts/not_here.py"]}]
    assert rp.validate(plan, None) == []


# --------------------------------------------------------------------------
# 3. CF-0668: the rebuild modes
# --------------------------------------------------------------------------

def _with_rebuild(plan, **mode):
    spec = {"title": "t", "from": "use", "copy": ["01-x.json"], "skip": ["close"],
            "args": {"judge": {"rebuild": "of {source}: {videos} ({scripts}) {exclusions}"}}}
    spec.update(mode)
    plan["rebuild"] = {"modes": {"again": spec}}
    return plan


def test_the_example_film_rebuild_modes_lay_out_as_the_task_says():
    plan = _real()
    assert set(rp.rebuild_modes(plan)) == {"reedit", "rewrite"}
    re_ = rp.rebuild_layout(plan, "reedit")
    # CF-0846: scene-holds runs in a rebuild too - a rewrite may take another scene of
    # the topic, and only the scene the video has may lift or put back a hold
    assert re_["run"] == ["video-editor", "frame-judge-empty", "frame-judge", "scene-holds"], re_
    close = {"batch-done", "monitors", "triage", "rotation-backfill", "footage-wanted",
             "commit-records"}
    # a rebuild has no close (CF-0339) and no reserve round after the judge (CF-0802)
    assert set(re_["skipped"]) == close | set(ROUND_AFTER_JUDGE) | set(REPAIR_AFTER_JUDGE) \
        | set(REFILL_JUDGE), re_
    assert "batch-done" in re_["skipped"] and "batch-start" in re_["copied"]
    assert "content-researcher" in re_["copied"] and "trend-hunter" in re_["copied"]
    rw = rp.rebuild_layout(plan, "rewrite")
    assert rw["run"][0] == "content-researcher" and "compliance-scripts" in rw["run"]
    assert rw["run"][-4:] == ["video-editor", "frame-judge-empty", "frame-judge", "scene-holds"]
    assert set(rw["skipped"]) == close | set(ROUND_AFTER_JUDGE) | set(REPAIR_AFTER_JUDGE) \
        | set(REFILL_JUDGE), rw
    assert "footage-indexer" in rw["copied"]
    spec = rp.rebuild_modes(plan)["reedit"]
    assert spec["only_videos"] == ["03-content-researcher.json", "04-compliance-checker.json"]
    assert rp.rebuild_modes(plan)["rewrite"]["copy"] == [
        "01-trend-hunter.json", "01b-footage-index.json", "02-compliance-checker.json"]
    assert "--no-parent" in rp.rebuild_modes(plan)["rewrite"]["args"]["content-researcher"]["rebuild"]


def test_a_rebuild_block_is_valid_and_lays_out():
    plan = _with_rebuild(_clean(_base()))
    assert _errs(plan) == []
    assert rp.rebuild_layout(plan, "again") == {"copied": ["open", "make"],
                                                "skipped": ["close"], "run": ["use", "judge"]}


def test_the_rebuild_block_is_not_in_the_fingerprint():
    sys.path.insert(0, str(ROOT / "shared"))
    import run_executor as rx
    plain = _clean(_base())
    assert rx.fingerprint(plain) == rx.fingerprint(_with_rebuild(copy.deepcopy(plain)))
    moved = copy.deepcopy(plain)
    moved["stages"][-1]["always"] = False
    assert rx.fingerprint(moved) != rx.fingerprint(plain)


def test_refuses_a_bad_rebuild_mode():
    cases = [
        (dict(**{"from": "nowhere"}), "is not a stage of the run order"),
        (dict(**{"from": "fix"}), "is not a stage of the run order"),       # a handler
        (dict(copy=[]), "copy names no file"),
        (dict(copy=["../01-x.json"]), "is not a file of the batch directory"),
        (dict(only_videos=["03.json"]), "only_videos '03.json' is not copied"),
        (dict(skip=["open"]), "is not after `from`"),
        (dict(skip=["use", "close"]), "`from` 'use' is skipped"),
        (dict(args={"close": {"a": "b"}}), "which does not run in this mode"),
        (dict(args={"use": {"a": "b"}}), "which is not an llm stage"),
        (dict(args={"judge": {"a": "{nope}"}}), "unknown placeholder {nope}"),
        (dict(copy=["02-y.json"]), "consumes 01-x.json, which the rebuild neither copies"),
        (dict(work=["/abs"]), "must be a path under work/"),
        (dict(colour="red"), "unknown key(s) ['colour']"),
    ]
    for mode, needle in cases:
        plan = _with_rebuild(_clean(_base()), **mode)
        errs = _errs(plan)
        assert any(needle in e for e in errs), (mode, needle, errs)
    plan = _clean(_base())
    plan["rebuild"] = {"modes": {}}
    assert any("modes must be a non-empty object" in e for e in _errs(plan))



def test_a_human_decision_may_be_quiet_and_say_its_russian_line():
    """CF-0735: `notify` ("bus"|"quiet") and `say` belong to a human decision."""
    def human(p, **kw):
        _st(p, "fix").update(decided_by="human", **kw)
    plan = copy.deepcopy(_clean(_base()))
    human(plan, notify="quiet", say="Studio не прочитан перед батчем {channel}")
    assert _errs(plan) == [], _errs(plan)
    _refused(lambda p: human(p, notify="loud"), "notify must be one of")
    _refused(lambda p: human(p, say="  "), "say must be a non-empty line")
    _refused(lambda p: _st(p, "fix").update(notify="quiet"), "for decided_by human only")



if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
