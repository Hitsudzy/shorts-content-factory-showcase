#!/usr/bin/env python3
"""CF-0319: the batch files no task; a triage script after it does, by itself.

What is pinned here:

* the two kinds of event - an **авария** (a crash, a stage never closed, a
  watchdog kill, a broken artifact, a broken contract between stages, a refusal
  in force without a signed price) is always a task; a **topic loss** under a
  funnel code is a number and never a task;
* a script's own refusal (`SystemExit: N`) is not a crash;
* the gate-price step of CF-0320 runs on every triage and turns a refusing,
  unpriced rule into an авария - and reads "refusing" from the user's decision,
  then the channel config, then "hard-wired in code";
* filing needs no human: one note per incident key with its INDEX row, an open
  note with the key takes the repeat, a closed one does not, `--dry-run` writes
  nothing;
* the run's own code names no `tasks/` directory: only `triage.py` does.

Synthetic batches only, in a temp tree; nothing outside it is written.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
import funnel       # noqa: E402
import gate_price   # noqa: E402
import triage       # noqa: E402
from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("triage-test-")
_n = [0]
TS = "2026-09-30T10:{:02d}:00.000Z"


def ev(i, kind, status, stage=None, **kw):
    e = {"ts": TS.format(i), "kind": kind, "status": status, "stage": stage,
         "step": kw.pop("step", None), "video": kw.pop("video", None)}
    e.update(kw)
    return e


def markers(*stages, done=True):
    out, i = [ev(0, "marker", "batch-start")], 1
    for s in stages:
        out.append(ev(i, "marker", "stage-start", s))
        out.append(ev(i + 1, "marker", "stage-done", s))
        i += 2
    if done:
        out.append(ev(59, "marker", "batch-done"))
    return out


def batch(events, artifacts=True, extra=None, channel="testchan"):
    """A batch dir: t1 goes all the way to a ready video, t2 is refused by
    compliance under the funnel's own code."""
    _n[0] += 1
    b = TMP / f"pool-{_n[0]}" / channel / "2026-09-30T1000Z"
    b.mkdir(parents=True)
    files = {
        "01-trend-hunter.json": {"batch_id": "B", "topics": [{"topic_id": "t1"},
                                                             {"topic_id": "t2"}]},
        "02-compliance-checker.json": {"batch_id": "B", "results": [
            {"topic_id": "t1", "verdict": "clear"}, {"topic_id": "t2", "verdict": "reject"}]},
        "01b-footage-index.json": {"batch": str(b), "fetched": [], "skipped_topics": [],
                                   "failed": [], "sources_by_topic": {"t1": ["a", "b"]}},
        "03-content-researcher.json": {"batch_id": "B", "skipped": [],
                                       "scripts": [{"script_id": "s1", "topic_id": "t1"}]},
        "04-compliance-checker.json": {"batch_id": "B", "results": [
            {"script_id": "s1", "verdict": "clear"}]},
        "05-video-editor.json": {"batch_id": "B", "refusals": [], "videos": [
            {"script_id": "s1", "output_path": "/x/s1.mp4", "qc": {"passed": True}}]},
    }
    files.update(extra or {})
    if artifacts:
        for name, d in files.items():
            if d is None:
                continue
            (b / name).write_text(d if isinstance(d, str) else json.dumps(d), encoding="utf-8")
    (b / "RUN_EVENTS.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events),
                                        encoding="utf-8")
    return b


ALL = ("trend-hunter", "compliance-checker", "footage-indexer", "content-researcher",
       "compliance-checker", "video-editor")


def gate(rule, verdict, price=None):
    return {"rule": rule, "verdict": verdict, "price": price, "measured_on": 1, "of": 5,
            "why": f"{rule}: {verdict}"}


def run(b, events=None, config=None, ledger=None, gates=()):
    return triage.triage(b, events=events, config=config if config is not None else {},
                         ledger=ledger or {"rules": {}}, gate_results=list(gates))


def kinds(res):
    return sorted(i["kind"] for i in res["incidents"])


def tasks_dir():
    _n[0] += 1
    d = TMP / f"tasks-{_n[0]}"
    d.mkdir()
    (d / "INDEX.md").write_text("| ID | Веха | Тип | Статус | Репо | Название |\n|---|---|---|---|---|---|\n",
                                encoding="utf-8")
    (d / "CF-0400-something.md").write_text("---\nid: CF-0400\nstatus: done\n---\n",
                                            encoding="utf-8")
    return d


# --------------------------------------------------------------------------
# the two kinds of event
# --------------------------------------------------------------------------

def test_a_clean_run_has_no_incident_and_its_topic_loss_is_a_number():
    b = batch(markers(*ALL))
    res = run(b)
    assert res["incidents"] == [], res["incidents"]
    assert res["ready"] == 1, res["ready"]
    assert res["losses"] == funnel.funnel(b)["losses"] and sum(res["losses"].values()) == 1, \
        res["losses"]
    assert all(c in funnel.FUNNEL_CODES for c in res["losses"])


SHA_RUN, SHA_OTHER = "a" * 40, "b" * 40


def _built_by(code_shas):
    evs = markers(*ALL)
    evs[0]["header"] = {"git": {"root": {"commit": SHA_RUN, "dirty": False},
                                "agents": {"video-editor": {"commit": SHA_RUN, "dirty": False}}}}
    v = {"script_id": "s1", "output_path": "/x/s1.mp4", "qc": {"passed": True}}
    if code_shas != "absent":
        v["code_shas"] = code_shas
    b = batch(evs, extra={"05-video-editor.json": {"batch_id": "B", "refusals": [],
                                                     "videos": [v]}})
    return [i for i in run(b)["incidents"] if i["kind"] == triage.BUILT_OFF_RUN]


def test_a_ready_video_built_by_the_runs_own_clean_code_is_no_incident():
    """CF-0399. And a video without code_shas (before CF-0399) or with null is
    unknown: nothing is claimed about it either way."""
    same = {"root": {"commit": SHA_RUN, "dirty": False},
            "agents/video-editor": None, "agents/analyst": None}
    assert _built_by(same) == []
    assert _built_by("absent") == [] and _built_by(None) == []


def test_a_ready_video_built_by_other_code_or_a_dirty_tree_is_an_incident():
    """CF-0399 / the CF-0376 case: a video in the batch the run's code did not build."""
    inc = _built_by({"root": {"commit": SHA_OTHER, "dirty": True}})
    assert sorted(i["key"] for i in inc) == ["built_off_run:root:commit",
                                             "built_off_run:root:dirty"], inc
    assert all("s1" in i["detail"] for i in inc), inc
    assert triage.KIND_LABEL[triage.BUILT_OFF_RUN]


def _git_root():
    """A tiny root repo: (dir, start sha, sha after a records-only commit (tasks/,
    docs/, ROADMAP.md), sha after a code commit (shared/))."""
    _n[0] += 1
    d = TMP / f"root-{_n[0]}"
    d.mkdir()

    def git(*a):
        return subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c",
                               "user.email=t@t", *a], capture_output=True, text=True,
                              check=True).stdout.strip()

    def commit(path, text):
        f = d / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", path)
        return git("rev-parse", "HEAD")

    git("init", "-q")
    start = commit("shared/x.py", "a = 1\n")
    commit("tasks/CF-1.md", "status: done\n")
    commit("docs/n.md", "n\n")
    records = commit("ROADMAP.md", "r\n")
    code = commit("shared/x.py", "a = 2\n")
    return d, start, records, code


def _built_off(root, header, shas):
    evs = markers(*ALL)
    evs[0]["header"] = {"git": header}
    v = {"script_id": "s1", "output_path": "/x/s1.mp4", "qc": {"passed": True},
         "code_shas": shas}
    b = batch(evs, extra={"05-video-editor.json": {"batch_id": "B", "refusals": [],
                                                     "videos": [v]}})
    return triage.built_off_run_incidents(runlog_events(b), b, ["s1"], root=root)


def runlog_events(b):
    return [json.loads(x) for x in (b / "RUN_EVENTS.jsonl").read_text().splitlines()]


def test_a_root_commit_of_records_only_between_start_and_build_is_the_runs_code():
    """CF-0484: the 2210Z case - only tasks/ (and other NON_CODE_PATHS) moved in
    the root between batch-start and the build: not an авария, by the same rule
    (runlog.code_moved) code_drift keeps since CF-0479."""
    d, start, records, code = _git_root()
    hdr = {"root": {"commit": start, "dirty": False}}
    assert _built_off(d, hdr, {"root": {"commit": records, "dirty": False}}) == []
    inc = _built_off(d, hdr, {"root": {"commit": code, "dirty": False}})
    assert [i["key"] for i in inc] == ["built_off_run:root:commit"], inc
    # the very rule code_drift uses
    import runlog
    assert runlog.code_moved("root", start, records, d) is False
    assert runlog.code_moved("root", start, code, d) is True


def test_an_agent_built_on_another_sha_is_an_incident():
    """CF-0484: an agent differs on any sha - its pin, not its paths."""
    d, start, _, _ = _git_root()
    hdr = {"root": {"commit": start, "dirty": False},
           "agents": {"video-editor": {"commit": SHA_RUN, "dirty": False}}}
    same = {"root": {"commit": start, "dirty": False},
            "agents/video-editor": {"commit": SHA_RUN, "dirty": False}}
    assert _built_off(d, hdr, same) == []
    moved = dict(same, **{"agents/video-editor": {"commit": SHA_OTHER, "dirty": False}})
    inc = _built_off(d, hdr, moved)
    assert [i["key"] for i in inc] == ["built_off_run:agents/video-editor:commit"], inc


def test_a_refusal_exit_is_not_a_crash_and_an_exception_is():
    evs = markers(*ALL)
    evs[3:3] = [ev(30, "script", "failed", "content-researcher", name="check_x.py",
                   error="SystemExit: 1"),
                ev(31, "script", "failed", "video-editor", name="qc_render.py",
                   error="KeyError: 'streams'"),
                ev(32, "script", "failed", "video-editor", name="qc_render.py",
                   error="KeyError: 'format'")]
    res = run(batch(evs))
    assert kinds(res) == [triage.CRASH], res["incidents"]
    inc = res["incidents"][0]
    assert inc["count"] == 2 and inc["key"] == "crash:video-editor:qc_render.py:KeyError", inc


def test_a_stage_opened_and_never_closed_is_a_crash():
    evs = markers(*ALL)
    evs.insert(-1, ev(50, "marker", "stage-start", "frame-judge"))
    res = run(batch(evs))
    assert kinds(res) == [triage.CRASH], res["incidents"]
    assert "frame-judge" in res["incidents"][0]["what"]


def test_a_stage_that_changed_tracked_code_is_an_incident_keyed_by_repo_and_stage():
    """CF-0713: the executor's `stage_code_edit` event is an авария, one per
    repo and stage; the file it changed is named."""
    evs = markers(*ALL)
    edit = ev(25, "stage_code_edit", "warn", "footage-indexer", plan_stage="footage-indexer",
              run="footage-indexer.llm", task="CF-0713",
              edits=[{"repo": "agents/footage-indexer", "files": ["scripts/source_rights.py"]}])
    evs[5:5] = [edit, dict(edit, ts=TS.format(26))]
    res = run(batch(evs))
    assert kinds(res) == [triage.STAGE_CODE_EDIT], res["incidents"]
    inc = res["incidents"][0]
    assert inc["key"] == "stage_code_edit:agents/footage-indexer:footage-indexer", inc
    assert inc["count"] == 2 and "scripts/source_rights.py" in inc["what"], inc
    assert triage.STAGE_CODE_EDIT in triage.INCIDENT_KINDS
    assert triage.KIND_LABEL[triage.STAGE_CODE_EDIT] in triage.render(res)


def test_a_sieve_flag_override_is_listed_with_its_reason_and_files_nothing():
    """CF-0713, item 2: a flag a stage changed after the describer answered it
    is not silent - TRIAGE.md lists who, what, why - and not an incident."""
    evs = markers(*ALL)
    evs[5:5] = [ev(25, "sieve_flag_override", "applied", "footage-indexer", video="esa1",
                   flag="on_topic", to=True, shots=[3, 4], was=[False, False],
                   by="footage-indexer stage", note="ESA's own control room, not another work")]
    res = run(batch(evs))
    assert res["incidents"] == [], res["incidents"]
    [o] = res["flag_overrides"]
    assert o["video"] == "esa1" and o["shots"] == [3, 4] and o["to"] is True
    text = triage.render(res)
    assert "## Ручные перезаписи флагов сита: 1 (CF-0713)" in text
    assert "| footage-indexer stage | `esa1` | `on_topic` | 3, 4 | false → true | ESA's own " \
        "control room, not another work |" in text, text
    assert "## Ручные перезаписи флагов сита: 0 (CF-0713)" in triage.render(run(batch(markers(*ALL))))


def test_a_watchdog_kill_is_an_incident_of_its_own_kind():
    evs = markers(*ALL)
    evs.insert(3, ev(20, "child", "failed", "footage-indexer", step="index", rc="index_timeout",
                     tool="ffmpeg", watchdog={"code": "index_timeout", "source": "abc",
                                              "silent_s": 1900, "ceiling_s": 1860}))
    res = run(batch(evs))
    assert kinds(res) == [triage.TIMEOUT], res["incidents"]
    assert len(res["watchdog"]) == 1


def test_a_broken_artifact_is_an_incident_and_not_also_a_missing_one():
    res = run(batch(markers(*ALL), extra={"05-video-editor.json": "{not json"}))
    assert triage.BROKEN_ARTIFACT in kinds(res), res["incidents"]
    assert not [i for i in res["incidents"] if i["key"] == "contract:missing:05-video-editor.json"]


def test_a_stage_closed_without_its_artifact_breaks_the_contract():
    res = run(batch(markers(*ALL), extra={"05-video-editor.json": None}))
    keys = [i["key"] for i in res["incidents"]]
    assert "contract:missing:05-video-editor.json" in keys, keys


def test_the_triage_reads_a_finished_run_only():
    b = batch(markers(*ALL, done=False))
    try:
        run(b)
    except triage.NotClosed:
        pass
    else:
        raise AssertionError("a run with no batch-done was triaged")


def test_stage_times_add_up_per_stage_across_its_runs():
    res = run(batch(markers(*ALL)))
    by = {r["stage"]: r for r in res["stage_times"]}
    assert by["compliance-checker"]["runs"] == 2 and by["compliance-checker"]["seconds"] == 120.0
    assert by["video-editor"]["seconds"] == 60.0


# --------------------------------------------------------------------------
# the gate price step (CF-0320)
# --------------------------------------------------------------------------

def test_an_unpriced_rule_refusing_in_code_is_an_incident():
    res = run(batch(markers(*ALL)), gates=[gate("x.hard", gate_price.WARN)])
    assert kinds(res) == [triage.UNPRICED_REFUSAL], res["incidents"]
    assert res["gates"][0]["mode"] == triage.MODE_HARDWIRED


def test_a_rule_the_config_or_the_user_keeps_at_a_warning_is_not():
    config = {"x": {"measured": "measure", "warned": {"mode": "warn"},
                    "enforced": {"mode": "enforce"}}}
    ledger = {"rules": {"x.decided": {"decision": {"mode": "warn"}}}}
    res = run(batch(markers(*ALL)), config=config, ledger=ledger,
              gates=[gate("x.measured", gate_price.WARN), gate("x.warned", gate_price.WARN),
                     gate("x.decided", gate_price.WARN), gate("x.enforced", gate_price.WARN)])
    assert [i["what"] for i in res["incidents"]] == ["x.enforced"], res["incidents"]
    modes = {g["rule"]: (g["mode"], g["mode_from"]) for g in res["gates"]}
    assert modes["x.decided"] == ("warn", "decision") and modes["x.measured"] == ("measure", "config")


def test_a_priced_rule_at_zero_refuses_freely():
    res = run(batch(markers(*ALL)), gates=[gate("x.hard", gate_price.ENFORCE, 0)])
    assert res["incidents"] == []


def test_a_penalty_rule_of_the_score_model_is_never_an_unpriced_refusal():
    # CF-0432: the config still says `enforce` and nobody signed a price, but
    # the score model holds the rule as a penalty - it costs points, it is not
    # a refusal, and triage must not file it as one.
    config = {"x": {"enforced": {"mode": "enforce"}}}
    ledger = {"rules": {"x.enforced": {"mode": "penalty", "penalty": {"price": 2}}}}
    res = run(batch(markers(*ALL)), config=config, ledger=ledger,
              gates=[gate("x.enforced", gate_price.WARN)])
    assert res["incidents"] == [], res["incidents"]
    g = res["gates"][0]
    assert (g["mode"], g["mode_from"], g["refusing"]) == ("penalty", "score model", False), g
    ledger["rules"]["x.enforced"]["mode"] = "hard"
    res = run(batch(markers(*ALL)), config=config, ledger=ledger,
              gates=[gate("x.enforced", gate_price.WARN)])
    assert [i["what"] for i in res["incidents"]] == ["x.enforced"], res["incidents"]


def test_with_no_channel_config_the_mode_is_unknown_and_nothing_is_claimed():
    assert triage.mode_of("x.hard", None, {}) == (triage.MODE_UNKNOWN, "no channel config")


def test_a_rule_whose_code_the_registry_states_as_measure_is_not_read_as_hard_wired():
    """CF-0472: `content_researcher.tail_after_last_anchor` was filed as an
    авария off example-film/2026-10-01T1313Z because nothing told the triage
    that the cadence gate stopped refusing at CF-0433/CF-0447. The registry
    says so now; a channel switch and the user's decision still come first."""
    tail = "content_researcher.tail_after_last_anchor"
    assert gate_price.rule(tail).mode == gate_price.CODE_MEASURE
    assert triage.mode_of(tail, {}, {}) == ("measure", "registry")
    assert triage.mode_of(tail, None, {}) == ("measure", "registry")
    assert triage.mode_of(tail, {"content_researcher": {"tail_after_last_anchor": "enforce"}},
                          {}) == ("enforce", "config")
    led = {"rules": {tail: {"decision": {"mode": "warn"}}}}
    assert triage.mode_of(tail, {}, led) == ("warn", "decision")
    res = run(batch(markers(*ALL)), gates=[gate(tail, gate_price.WARN, 1)])
    assert res["incidents"] == [], res["incidents"]
    g = res["gates"][0]
    assert (g["mode"], g["mode_from"], g["refusing"]) == ("measure", "registry", False), g


def test_the_registry_may_only_state_a_mode_that_refuses_nothing():
    """CF-0472: a registered mode can lift a false `hard-wired`, never write a
    refusal into the registry - that takes the user's signature."""
    for bad in ("enforce", "fail", "refuse", "hard-wired"):
        try:
            gate_price.Rule("x.bad", gate_price.WHAT_VIDEO, lambda A: None, mode=bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted as a registered mode")
    assert all(r.mode in (None,) + gate_price.CODE_MODES for r in gate_price.RULES.values())
    assert not set(gate_price.CODE_MODES) & set(triage.REFUSING_MODES)


def test_the_gate_step_prices_every_registered_rule_when_not_handed_results():
    b = batch(markers(*ALL))
    res = triage.triage(b, config={}, ledger={"rules": {}})
    assert sorted(g["rule"] for g in res["gates"]) == sorted(gate_price.RULES)


# --------------------------------------------------------------------------
# filing
# --------------------------------------------------------------------------

def _crash_batch():
    evs = markers(*ALL)
    evs.insert(3, ev(30, "script", "failed", "video-editor", name="qc_render.py",
                     error="KeyError: 'streams'"))
    return batch(evs)


def test_an_incident_is_filed_as_a_task_with_its_key_and_index_row():
    d = tasks_dir()
    res = run(_crash_batch())
    filed = triage.file_tasks(res, d, milestone="1.4.5", today="2026-09-30")
    assert [t for t, _ in filed] == ["CF-0401"], filed
    text = filed[0][1].read_text(encoding="utf-8")
    assert "status: open" in text and "milestone: 1.4.5" in text
    assert "triage-key: `crash:video-editor:qc_render.py:KeyError`" in text
    assert "CF-0319" in text
    assert "[CF-0401](" in (d / "INDEX.md").read_text(encoding="utf-8")
    assert res["incidents"][0]["task"] == "CF-0401" and res["incidents"][0]["filed"]


def test_the_same_incident_on_the_next_batch_goes_to_the_open_task():
    d = tasks_dir()
    triage.file_tasks(run(_crash_batch()), d)
    again = run(_crash_batch())
    assert triage.file_tasks(again, d) == []
    assert again["incidents"][0]["task"] == "CF-0401" and not again["incidents"][0]["filed"]
    assert len(list(d.glob("CF-04*-triage-*.md"))) == 1


def test_an_incident_whose_task_is_closed_is_filed_again_naming_the_old_one():
    d = tasks_dir()
    (_, p), = triage.file_tasks(run(_crash_batch()), d)
    p.write_text(p.read_text(encoding="utf-8").replace("status: open", "status: done"),
                 encoding="utf-8")
    filed = triage.file_tasks(run(_crash_batch()), d)
    assert [t for t, _ in filed] == ["CF-0402"]
    assert "CF-0401" in filed[0][1].read_text(encoding="utf-8")


SIG_ASSET = ('Could not extract frame from compositor Error: Can only download URLs '
             'starting with http:// or https://, got "file://<work>/clips/{clip}.mp4" '
             'frame <n> Rendered <n>/<m>')


def _stopped(reason, clip="a06_s009", slug="s1", asset=True, sig=None):
    """A batch whose only video the Editor stopped on a render stop (CF-0518 /
    CF-0305), its needs_you shaped as attempts.same_failure_stop writes it."""
    ny = {"reason": reason, "last_failure": "render_failed", "attempts": 2,
          "error": f'Error: got "file:///p/pipeline/c/B/work/{slug}/clips/{clip}.mp4"',
          "error_signature": sig if sig is not None else SIG_ASSET.format(clip=clip),
          "toolchain": "t" * 12, "build_inputs": "p" * 12, "renders": [1, 2],
          "frames_rendered": [507, 508] if reason == "render_stuck_on_asset" else [0, 0],
          "asset": f"/p/pipeline/c/B/work/{slug}/clips/{clip}.mp4" if asset else None,
          "at": "2026-10-04T10:00:00Z"}
    v = {"script_id": "s1", "output_path": f"/x/{slug}.mp4", "qc": {"passed": False},
         "needs_you": ny}
    return batch(markers(*ALL), extra={"05-video-editor.json": {
        "batch_id": "B", "refusals": [], "videos": [v]}})


def test_a_render_stuck_on_one_asset_is_an_incident_keyed_by_the_failure():
    """CF-0518: the second render_failed in a row with one signature stops the
    video; the triage sees the stop as an авария, its key the failure with the
    asset read as <asset> - the topic itself stays a needs_you loss."""
    res = run(_stopped("render_stuck_on_asset"))
    inc = [i for i in res["incidents"] if i["kind"] == triage.RENDER_TOOL_STOP]
    assert len(inc) == 1 and kinds(res) == [triage.RENDER_TOOL_STOP], res["incidents"]
    key = inc[0]["key"]
    assert key.startswith("render_tool_stop:video-editor:render_stuck_on_asset:"), key
    assert "<asset>" in key and "a06_s009" not in key and " " not in key, key
    assert triage.KEY_LINE.findall(f"triage-key: `{key}`\n") == [key]
    d = inc[0]["detail"]
    assert "a06_s009.mp4" in d and "[507, 508]" in d and "[1, 2]" in d and "Error" in d, d
    assert inc[0]["stage"] == "video-editor" and "a06_s009.mp4" in inc[0]["what"]
    assert res["losses"].get("needs_you") == 1 and res["ready"] == 0, res["losses"]
    assert "needs_you" in funnel.FUNNEL_CODES
    assert "CF-0518" in triage.KIND_RELATED[triage.RENDER_TOOL_STOP]
    assert "CF-0305" in triage.KIND_RELATED[triage.RENDER_TOOL_STOP]
    assert triage.KIND_LABEL[triage.RENDER_TOOL_STOP] in triage.render(res)


def test_a_render_broken_twice_is_an_incident_too():
    """CF-0305: two render_broken in a row stop the video as well - before
    CF-0518 that stop was seen nowhere in the root."""
    res = run(_stopped("render_broken", asset=False,
                       sig="Error: Remotion exited before the first frame pid <pid>"))
    inc = [i for i in res["incidents"] if i["kind"] == triage.RENDER_TOOL_STOP]
    assert [i["key"] for i in inc] == [
        "render_tool_stop:video-editor:render_broken:"
        "Error:_Remotion_exited_before_the_first_frame_pid_<pid>"], inc
    assert "ассет не назван" in inc[0]["what"], inc


def test_another_needs_you_is_no_render_stop():
    """The attempt cap and the qc degrade cap stay a topic loss only."""
    for reason in ("attempt cap 3 reached", "qc degrade cap 3 reached"):
        res = run(_stopped(reason))
        assert res["incidents"] == [], (reason, res["incidents"])
        assert res["losses"].get("needs_you") == 1


def test_the_same_asset_failure_in_the_next_batch_goes_to_the_open_task():
    """The key is the failure, not the clip: another clip, another batch, the
    same tool failure on an unstaged asset -> the task already open."""
    d = tasks_dir()
    filed = triage.file_tasks(run(_stopped("render_stuck_on_asset")), d)
    assert len(filed) == 1, filed
    text = filed[0][1].read_text(encoding="utf-8")
    assert "рендер упёрся в ассет" in text and "CF-0518" in text, text
    again = run(_stopped("render_stuck_on_asset", clip="b11_s002", slug="other"))
    assert triage.file_tasks(again, d) == []
    assert again["incidents"][0]["task"] == filed[0][0]


def test_a_topic_loss_is_never_filed():
    d = tasks_dir()
    res = run(batch(markers(*ALL)))
    assert sum(res["losses"].values()) == 1
    assert triage.file_tasks(res, d) == []


def test_a_topic_the_plan_check_dropped_is_a_known_loss_and_no_incident():
    """CF-0411: `plan_unassembled` (the Researcher's step 6b) is a topic loss
    under a known code - a number in the statistics, never an `unknown_code`
    contract incident and never a filed task."""
    extra = {"03-content-researcher.json": {
        "batch_id": "B",
        "skipped": [{"topic_id": "t2", "reason_code": "plan_unassembled", "stage": "scripts",
                     "script_id": "s2", "kinds": ["pattern_ceiling"],
                     "reason": "s2: the Video Editor's own gates built no plan out of this "
                               "script before the render (CF-0411)"}],
        "scripts": [{"script_id": "s1", "topic_id": "t1"}]},
        "02-compliance-checker.json": {"batch_id": "B", "results": [
            {"topic_id": "t1", "verdict": "clear"}, {"topic_id": "t2", "verdict": "clear"}]},
        "01b-footage-index.json": {"batch": "B", "fetched": [], "skipped_topics": [],
                                   "failed": [], "sources_by_topic": {"t1": ["a", "b"],
                                                                      "t2": ["c", "d"]}}}
    res = run(batch(markers(*ALL), extra=extra))
    assert res["incidents"] == [], res["incidents"]
    assert res["losses"] == {"plan_unassembled": 1}, res["losses"]
    assert triage.file_tasks(res, tasks_dir()) == []


def test_a_dry_run_writes_nothing():
    d = tasks_dir()
    before = sorted(p.name for p in d.iterdir()), (d / "INDEX.md").read_text(encoding="utf-8")
    filed = triage.file_tasks(run(_crash_batch()), d, dry_run=True)
    assert len(filed) == 1
    assert (sorted(p.name for p in d.iterdir()), (d / "INDEX.md").read_text(encoding="utf-8")) \
        == before


def test_the_cli_files_writes_its_report_and_answers_with_its_exit_code():
    d = tasks_dir()
    b = _crash_batch()
    cli = [sys.executable, str(ROOT / "scripts" / "runlog"), "triage", "--batch", str(b),
           "--tasks", str(d)]
    p = subprocess.run(cli, capture_output=True, text=True, timeout=120)
    assert p.returncode == 1, (p.returncode, p.stderr[-500:])
    assert (b / triage.REPORT_NAME).is_file()
    assert "## Аварии: 1" in (b / triage.REPORT_NAME).read_text(encoding="utf-8")
    assert len(list(d.glob("CF-0401-triage-crash-*.md"))) == 1, list(d.iterdir())
    clean = batch(markers(*ALL))
    p = subprocess.run(cli[:4] + [str(clean), "--tasks", str(d)], capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 0, (p.returncode, p.stdout[-800:], p.stderr[-500:])
    open_ = batch(markers(*ALL, done=False))
    p = subprocess.run(cli[:4] + [str(open_), "--tasks", str(d)], capture_output=True,
                       text=True, timeout=120)
    assert p.returncode == 2, p.returncode


def test_the_run_itself_names_no_tasks_directory():
    """Task item 1: from the tracked tree a run writes statistics only. Of the
    accounting layer, only the triage module knows where tasks live."""
    offenders = []
    for py in sorted((ROOT / "shared" / "runlog").glob("*.py")):
        if py.name == "triage.py":
            continue
        for n, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if '"tasks"' in line or "'tasks'" in line or '/ "tasks' in line:
                offenders.append(f"{py.name}:{n}")
    assert not offenders, offenders


# --------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
