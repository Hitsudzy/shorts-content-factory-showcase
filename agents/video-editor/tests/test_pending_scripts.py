#!/usr/bin/env python3
"""CF-0802: `pending_scripts.py <batch>` lists what the `new-only` mode renders.

Pinned here:

- nothing pending prints nothing on stdout, exit 0;
- some pending: only the cleared scripts of 04 that 05 names in neither
  videos[] nor refusals[], in 03's order (not 04's);
- "cleared" is the funnel's rule: clear/caution go on, review only with a
  publication_hold, reject/no verdict/no 04 row do not, a contribution
  `block` does not whatever the verdict;
- no 05 (no first pass) is exit 2, a broken 04 is exit 2;
- the copy of the rule agrees with the root's `shared/runlog/funnel.py`.

Synthetic batches in temp directories only - no live batch is read.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))
import pending_scripts as ps  # noqa: E402


def _batch(tmp, scripts, rows, d05=None):
    b = Path(tmp) / "pipeline" / "example-film" / "b1"
    b.mkdir(parents=True)
    (b / ps.SCRIPTS_FILE).write_text(json.dumps(
        {"scripts": [{"script_id": s, "topic_id": s.rsplit("-", 1)[0]} for s in scripts]}))
    (b / ps.VERDICTS_FILE).write_text(json.dumps({"results": rows}))
    if d05 is not None:
        (b / ps.EDITOR_FILE).write_text(json.dumps(d05))
    return b


def _run(batch):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ps.main([str(batch)])
    return code, out.getvalue(), err.getvalue()


def _clear(sid, verdict="clear", **extra):
    return {"script_id": sid, "verdict": verdict, **extra}


def test_nothing_pending_prints_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp, ["a-script1", "b-script1"],
                   [_clear("a-script1"), _clear("b-script1")],
                   {"videos": [{"script_id": "a-script1"}],
                    "refusals": [{"script_id": "b-script1"}]})
        code, out, err = _run(b)
        assert code == 0, err
        assert out == "", out
        assert "0 script(s)" in err, err


def test_some_pending_in_03_order():
    with tempfile.TemporaryDirectory() as tmp:
        # 03's order differs from 04's: the listing follows 03.
        b = _batch(tmp, ["a-script1", "r2-script1", "b-script1", "r1-script1"],
                   [_clear("r1-script1"), _clear("b-script1"), _clear("a-script1"),
                    _clear("r2-script1", "caution")],
                   {"videos": [{"script_id": "a-script1"}],
                    "refusals": [{"script_id": "b-script1"}]})
        code, out, err = _run(b)
        assert code == 0, err
        assert out.splitlines() == ["r2-script1", "r1-script1"], out
        assert "2 script(s)" in err, err


def test_only_cleared_scripts():
    with tempfile.TemporaryDirectory() as tmp:
        hold = {"code": "compliance_review_hold"}
        b = _batch(tmp, ["ok-script1", "held-script1", "oldreview-script1", "rej-script1",
                         "blocked-script1", "unjudged-script1", "noverdict-script1"],
                   [_clear("ok-script1"),
                    _clear("held-script1", "review", publication_hold=hold),
                    _clear("oldreview-script1", "review"),
                    _clear("rej-script1", "reject"),
                    _clear("blocked-script1", contribution_check={"verdict": "block"}),
                    {"script_id": "noverdict-script1"}],
                   {"videos": [], "refusals": []})
        assert ps.pending(b) == ["ok-script1", "held-script1"]


def test_no_05_is_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp, ["a-script1"], [_clear("a-script1")])
        code, out, err = _run(b)
        assert code == 2 and out == "", (code, out)
        assert "no first pass" in err, err


def test_unreadable_04_is_exit_2():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp, ["a-script1"], [_clear("a-script1")], {"videos": []})
        (b / ps.VERDICTS_FILE).write_text("{not json")
        code, out, err = _run(b)
        assert code == 2 and out == "", (code, out)
        assert ps.VERDICTS_FILE in err, err
        code, _, err = _run(b.parent / "nope")
        assert code == 2, err


def test_usage():
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert ps.main([]) == 2
        assert ps.main(["--pending"]) == 2
    assert "usage" in err.getvalue()


def _root_funnel():
    for a in AGENT_ROOT.parents:
        p = a / "shared" / "runlog" / "funnel.py"
        if p.is_file():
            spec = importlib.util.spec_from_file_location("funnel_for_cf0802_test", p)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def test_rule_matches_the_root_funnel():
    """The copy agrees with the funnel's `_goes_on` + contribution step on
    every shape a 04 row takes. Skipped (said) outside a factory checkout."""
    f = _root_funnel()
    if f is None:
        print("  (no factory root above this checkout - parity not checked)")
        return
    assert ps.PUBLISH_VERDICTS == tuple(f.PUBLISH_VERDICTS)
    assert ps.PRODUCTION_VERDICTS == tuple(f.PRODUCTION_VERDICTS)
    assert ps.PUBLICATION_HOLD_KEY == f.PUBLICATION_HOLD_KEY
    assert ps.CONTRIBUTION_KEY == f.CONTRIBUTION_KEY
    assert ps.CONTRIBUTION_BLOCK == f.CONTRIBUTION_BLOCK
    for verdict in ("clear", "caution", "review", "reject", "", None):
        for hold in (None, {"code": "x"}, "yes"):
            for contribution in (None, {"verdict": "pass"}, {"verdict": "block"}, "block"):
                row = {"script_id": "s", "verdict": verdict}
                if hold is not None:
                    row[f.PUBLICATION_HOLD_KEY] = hold
                if contribution is not None:
                    row[f.CONTRIBUTION_KEY] = contribution
                c = row.get(f.CONTRIBUTION_KEY)
                c = c if isinstance(c, dict) else {}
                root = f._goes_on(row) and (c.get("verdict") or "") != f.CONTRIBUTION_BLOCK
                assert ps.cleared(row) == root, row


BLOCK_ROW = {"script_id": "b-script1", "verdict": "clear",
             "contribution_check": {"verdict": "block", "failures": [
                 {"reason_code": "claim_unsupported",
                  "detail": "claims gate (CF-0553): shot_not_under_words"}],
                 "reason": "a claim of the script has no footing (CF-0553)"}}


def test_first_pass_lists_the_cleared_scripts_without_05():
    """CF-0902: the full mode's listing - 03's order, the same rule, no 05
    needed; the blocked script is named on stderr with its reason."""
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp, ["a-script1", "b-script1", "c-script1"],
                   [_clear("c-script1", "caution"), BLOCK_ROW, _clear("a-script1")])
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ps.main([str(b), "--first-pass"])
        assert code == 0, err.getvalue()
        assert out.getvalue().split() == ["a-script1", "c-script1"], out.getvalue()
        assert "not cleared, not rendered: b-script1" in err.getvalue(), err.getvalue()
        assert "claim_unsupported" in err.getvalue() and "CF-0902" in err.getvalue()


def _work_plan(b, slug, sid, where="score"):
    w = b / "work" / slug
    w.mkdir(parents=True)
    plan = w / "plan.json"
    plan.write_text(json.dumps({"style": "motion", "blocks": [],
                                "audio": {"duration": 4.0, "src": "voice.wav"},
                                "output": {"width": 1080, "height": 1920, "fps": 30}}))
    side = w / ("plan.score.json" if where == "score" else "plan_check.json")
    side.write_text(json.dumps({"script_id": sid}))
    return plan


def test_render_refusal_reads_the_row_of_the_plans_script():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp, ["a-script1", "b-script1"], [_clear("a-script1"), BLOCK_ROW])
        blocked = _work_plan(b, "pine-park", "b-script1")
        sid, why = ps.render_refusal(blocked)
        assert sid == "b-script1" and "claim_unsupported" in why, why
        assert ps.render_refusal(_work_plan(b, "ok", "a-script1", where="check")) is None
        # the plan check's verdict names the script when there is no score log
        assert ps.render_refusal(_work_plan(b, "sp2", "b-script1", where="check"))
        # no row for the script, no script id, a plan outside a batch: renders as before
        assert ps.render_refusal(_work_plan(b, "x", "z-script1")) is None
        (b / "work" / "x" / "plan.score.json").unlink()
        assert ps.render_refusal(b / "work" / "x" / "plan.json") is None
        loose = Path(tmp) / "plan.json"
        loose.write_text("{}")
        assert ps.render_refusal(loose) is None


def test_render_video_does_not_render_a_script_04_does_not_clear():
    """CF-0902 (pine-park, example-film/2026-10-30T1033Z): exit 5 and the
    NOT CLEARED line before any attempt - no ledger entry, no file."""
    import os
    import subprocess
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp, ["b-script1"], [BLOCK_ROW])
        plan = _work_plan(b, "pine-park", "b-script1")
        from repo_paths import VENV_PY3
        py = Path(VENV_PY3)
        r = subprocess.run([str(py if py.exists() else sys.executable),
                            str(AGENT_ROOT / "scripts" / "render_video.py"), str(plan),
                            str(b / "out.mp4")], capture_output=True, text=True,
                           timeout=120, env={**os.environ, "RUNLOG_BATCH": str(b)})
        assert r.returncode == 5, (r.returncode, r.stdout[-1500:], r.stderr[-1500:])
        assert "NOT CLEARED: b-script1" in r.stdout and "claim_unsupported" in r.stdout
        assert not (b / "out.mp4").exists()
        assert not (b / "work" / "pine-park" / "attempts.json").exists()


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
