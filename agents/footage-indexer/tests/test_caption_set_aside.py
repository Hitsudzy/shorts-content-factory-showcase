#!/usr/bin/env python3
"""CF-0819: a stale caption crop is set aside, never re-measured in bulk.

Tech 2026-10-20T0831Z made 0 videos: an unpaired neutral edit moved the
caption key, every crop in the pool read stale, pool-maintenance re-measured
the whole pool for 2 h and was stopped at its ceiling (exit 5). The pool is
transient and is never re-measured in bulk (the user's rule), so a stale crop
is moved aside (`caption_cache.set_aside`) and the shot is cut with a fresh
`--auto-crop`; `remeasure_captions.py --budget-seconds` re-measures only what
fits in minutes and sets the rest aside with `--set-aside-rest`, exit 0.

Synthetic indexes in a temp directory and a stand-in probe - no pool, no
Vision, no network. Plain asserts, run directly.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import caption_cache  # noqa: E402
import remeasure_captions  # noqa: E402

FOREIGN = "0123456789ab"
V, S, A = caption_cache.VALUE_KEY, caption_cache.STAMP_KEY, caption_cache.SET_ASIDE_KEY


def shot(index, value=None, stamp=None):
    s = {"index": index, "start": 1.0, "end": 2.0}
    if value is not None:
        s[V] = value
    if stamp is not None:
        s[S] = stamp
    return s


def _index(tmp, name, shots):
    p = Path(tmp) / f"{name}.shots.json"
    p.write_text(json.dumps({"source": str(Path(tmp) / f"{name}.mp4"), "shots": shots}))
    (Path(tmp) / f"{name}.mp4").write_bytes(b"")
    return p


def test_set_aside_moves_only_stale_crops_and_keeps_them():
    current = caption_cache.captions_fingerprint()
    with tempfile.TemporaryDirectory() as tmp:
        p = _index(tmp, "x", [shot(1, 0.3, FOREIGN), shot(2, 0.2, current),
                              shot(3), shot(4, 0.0)])
        assert caption_cache.set_aside(p, dry_run=True) == 2
        assert json.loads(p.read_text())["shots"][0][V] == 0.3
        assert caption_cache.set_aside(p) == 2
        after = json.loads(p.read_text())["shots"]
        assert V not in after[0] and S not in after[0]
        assert after[0][A]["value"] == 0.3 and after[0][A]["measured_by"] == FOREIGN
        assert after[3][A]["value"] == 0.0 and after[3][A]["measured_by"] is None
        assert after[1][V] == 0.2 and A not in after[1]          # fresh: untouched
        assert A not in after[2]                                  # nothing cached
        assert caption_cache.survey([p]) == {}                    # the gate passes
        assert caption_cache.set_aside(p) == 0                    # idempotent


def test_a_pair_proven_later_brings_a_set_aside_crop_back():
    current = caption_cache.captions_fingerprint()
    saved = dict(caption_cache.LEGACY_STAMPS)
    with tempfile.TemporaryDirectory() as tmp:
        p = _index(tmp, "x", [shot(1, 0.3, FOREIGN), shot(2, 0.1, "fedcba987654")])
        assert caption_cache.set_aside(p) == 2
        try:
            caption_cache.LEGACY_STAMPS[FOREIGN] = current
            assert caption_cache.restore_set_aside(p, dry_run=True) == 1
            assert caption_cache.restore_set_aside(p) == 1
        finally:
            caption_cache.LEGACY_STAMPS.clear()
            caption_cache.LEGACY_STAMPS.update(saved)
        after = json.loads(p.read_text())["shots"]
        assert after[0][V] == 0.3 and after[0][S] == FOREIGN and A not in after[0]
        assert V not in after[1] and after[1][A]["measured_by"] == "fedcba987654"


def test_a_fresh_measurement_retires_the_set_aside_record():
    s = {"index": 1, A: {"value": 0.3, "measured_by": FOREIGN, "at": "x"}}
    caption_cache.store(s, 0.25)
    assert s[V] == 0.25 and A not in s


def test_the_refusal_names_the_set_aside_way_out():
    with tempfile.TemporaryDirectory() as tmp:
        p = _index(tmp, "x", [shot(1, 0.3, FOREIGN)])
        text = caption_cache.complaint(caption_cache.survey([p]))
        assert "--set-aside-stale" in text and "remeasure_captions.py" in text


class _Args:
    dry_run = False
    include_uncached = False
    stale_only = True
    set_aside_rest = True


def _stand_in_probe(calls, clock, per_shot):
    def measure(shot, video):
        calls.append(shot["index"])
        clock[0] += per_shot
        return caption_cache.store(shot, 0.11)
    return measure


def test_the_budget_stops_measuring_and_sets_the_rest_aside():
    """Budget 25 s, a stand-in shot costs 10 s: three shots are measured
    (the third starts at 20 s, inside the budget), the other stale ones are
    set aside, a fresh one is neither."""
    current = caption_cache.captions_fingerprint()
    calls, clock = [], [0.0]
    saved = (caption_cache.measure, remeasure_captions.source_height,
             remeasure_captions._now)
    caption_cache.measure = _stand_in_probe(calls, clock, 10.0)
    remeasure_captions.source_height = lambda video: 1080
    remeasure_captions._now = lambda: clock[0]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            a = _index(tmp, "a", [shot(1, 0.3, FOREIGN), shot(2, 0.2, current),
                                  shot(3, 0.3, FOREIGN)])
            b = _index(tmp, "b", [shot(1, 0.3, FOREIGN), shot(2, 0.3, FOREIGN),
                                  shot(3, 0.3, FOREIGN)])
            args = _Args()
            args.deadline = 25.0
            ra = remeasure_captions.remeasure(Path(tmp) / "a.mp4", a, args)
            rb = remeasure_captions.remeasure(Path(tmp) / "b.mp4", b, args)
            assert calls == [1, 3, 1], calls          # stale only, the fresh one skipped
            assert ra["measured"] == 2 and ra["set_aside"] == 0
            assert rb["measured"] == 1 and rb["set_aside"] == 2 and rb["over_budget"] == 2
            shots_b = json.loads(b.read_text())["shots"]
            assert shots_b[0][V] == 0.11
            assert V not in shots_b[1] and shots_b[1][A]["measured_by"] == FOREIGN
            assert caption_cache.survey([a, b]) == {}
            # The fresh shot of `a` was left exactly as it was.
            assert json.loads(a.read_text())["shots"][1][V] == 0.2
    finally:
        (caption_cache.measure, remeasure_captions.source_height,
         remeasure_captions._now) = saved


def test_over_budget_without_set_aside_leaves_the_rest_stale_and_says_so():
    calls, clock = [], [0.0]
    saved = (caption_cache.measure, remeasure_captions.source_height,
             remeasure_captions._now)
    caption_cache.measure = _stand_in_probe(calls, clock, 10.0)
    remeasure_captions.source_height = lambda video: 1080
    remeasure_captions._now = lambda: clock[0]
    try:
        with tempfile.TemporaryDirectory() as tmp:
            b = _index(tmp, "b", [shot(1, 0.3, FOREIGN), shot(2, 0.3, FOREIGN)])
            args = _Args()
            args.set_aside_rest = False
            args.deadline = 5.0
            r = remeasure_captions.remeasure(Path(tmp) / "b.mp4", b, args)
            assert calls == [1] and r["over_budget"] == 1 and r["set_aside"] == 0
            assert list(caption_cache.survey([b]).values()) == [[(2, FOREIGN)]]
    finally:
        (caption_cache.measure, remeasure_captions.source_height,
         remeasure_captions._now) = saved


def test_a_spent_budget_is_exit_0_with_the_warning():
    """The command as pool-maintenance runs it: a budget of 0 measures
    nothing, sets every stale crop aside, exits 0 and says so loudly - the
    batch goes on (CF-0819)."""
    with tempfile.TemporaryDirectory() as tmp:
        a = _index(tmp, "a", [shot(1, 0.3, FOREIGN), shot(2, 0.3, FOREIGN)])
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "remeasure_captions.py"), str(a),
             "--stale-only", "--budget-seconds", "0", "--set-aside-rest"],
            capture_output=True, text=True, timeout=120,
            env={k: v for k, v in __import__("os").environ.items()
                 if k not in ("RUNLOG_BATCH",)})
        assert r.returncode == 0, r.stdout + r.stderr
        assert "WARNING caption-band cache" in r.stderr, r.stderr
        assert "2 stale crop(s)" in r.stderr, r.stderr
        assert caption_cache.survey([a]) == {}


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
