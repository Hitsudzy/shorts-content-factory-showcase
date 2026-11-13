#!/usr/bin/env python3
"""CF-0843: a Vision worker per index slot is the default, with a rollback and
a memory guard, and the pass says which mode it ran in.

Offline - no Vision, no vm_stat result is trusted (memory is handed in), no
batch, no pool:

  - nothing set: per-worker at N > 1 (the user's decision of 2026-10-21);
  - the rollback: `--no-vision-per-worker` and env FOOTAGE_VISION_PER_WORKER=0
    put every slot on the shared worker; the flag wins over the env;
  - less available memory than N x 0.85 GB + 2 GB: the shared worker, with a
    `low_memory` reason, not a swapping per-worker run;
  - the mode lands in 01b as additive fields (`vision_mode`,
    `vision_mode_reason`, `index_workers`), stamped by main() before the
    report is written.
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0843-")

import ingest_batch as ib  # noqa: E402

PLENTY = lambda: 64.0  # noqa: E731
SHORT = lambda: 3.0    # noqa: E731


def test_default_is_per_worker():
    assert ib.VISION_PER_WORKER is True
    plan = ib.vision_plan(4, environ={}, free_gb=PLENTY)
    assert plan["vision_mode"] == "per_worker", plan
    assert len(set(plan["sockets"])) == 4, plan
    assert plan["vision_mode_reason"].startswith("on (default)"), plan


def test_one_slot_stays_shared():
    plan = ib.vision_plan(1, environ={}, free_gb=PLENTY)
    assert plan["vision_mode"] == "shared" and plan["sockets"] is None, plan
    assert plan["vision_mode_reason"].startswith("one_worker"), plan


def test_rollback_by_flag():
    p = ib.add_vision_flags(argparse.ArgumentParser())
    assert p.parse_args([]).vision_per_worker is None
    assert p.parse_args(["--vision-per-worker"]).vision_per_worker is True
    off = p.parse_args(["--no-vision-per-worker"]).vision_per_worker
    assert off is False
    plan = ib.vision_plan(4, flag=off, environ={}, free_gb=PLENTY)
    assert plan["vision_mode"] == "shared" and plan["sockets"] is None, plan
    assert plan["vision_mode_reason"] == "off: --no-vision-per-worker", plan


def test_rollback_by_env_and_flag_wins():
    for raw in ("0", "false", "OFF", "no"):
        plan = ib.vision_plan(4, environ={ib.VISION_PER_WORKER_ENV: raw},
                              free_gb=PLENTY)
        assert plan["vision_mode"] == "shared", (raw, plan)
        assert plan["vision_mode_reason"].startswith(
            f"off: {ib.VISION_PER_WORKER_ENV}="), plan
    # the flag wins over the env
    plan = ib.vision_plan(4, flag=True, environ={ib.VISION_PER_WORKER_ENV: "0"},
                          free_gb=PLENTY)
    assert plan["vision_mode"] == "per_worker", plan
    # an unreadable env value is ignored, not a rollback
    plan = ib.vision_plan(4, environ={ib.VISION_PER_WORKER_ENV: "maybe"},
                          free_gb=PLENTY)
    assert plan["vision_mode"] == "per_worker", plan


def test_env_can_turn_it_on_when_the_constant_is_off():
    real = ib.VISION_PER_WORKER
    try:
        ib.VISION_PER_WORKER = False
        assert ib.vision_plan(4, environ={}, free_gb=PLENTY)["vision_mode"] == "shared"
        plan = ib.vision_plan(4, environ={ib.VISION_PER_WORKER_ENV: "1"},
                              free_gb=PLENTY)
        assert plan["vision_mode"] == "per_worker", plan
    finally:
        ib.VISION_PER_WORKER = real


def test_low_memory_falls_back_to_shared():
    need = 4 * ib.VISION_WORKER_GB + ib.VISION_MEMORY_HEADROOM_GB
    plan = ib.vision_plan(4, environ={}, free_gb=SHORT)
    assert plan["vision_mode"] == "shared" and plan["sockets"] is None, plan
    assert plan["vision_mode_reason"].startswith("low_memory: 3.0 GB free"), plan
    assert f"{need:.1f} GB needed" in plan["vision_mode_reason"], plan
    # just enough is enough
    plan = ib.vision_plan(4, environ={}, free_gb=lambda: need)
    assert plan["vision_mode"] == "per_worker", plan


def test_unreadable_memory_does_not_stop_per_worker():
    plan = ib.vision_plan(2, environ={}, free_gb=lambda: None)
    assert plan["vision_mode"] == "per_worker", plan
    assert "not checked" in plan["vision_mode_reason"], plan


def test_vm_stat_is_read_as_free_inactive_speculative():
    out = ("Mach Virtual Memory Statistics: (page size of 4096 bytes)\n"
           "Pages free:                                    262144.\n"
           "Pages active:                                 999999.\n"
           "Pages inactive:                               262144.\n"
           "Pages speculative:                                 0.\n")
    real = ib.subprocess.run

    class Done:
        stdout = out
    try:
        ib.subprocess.run = lambda *a, **k: Done()
        assert abs(ib.available_memory_gb() - 2.0) < 1e-9
    finally:
        ib.subprocess.run = real


def test_mode_is_written_into_01b():
    report = {"batch": "b", "fetched": []}
    plan = ib.vision_plan(4, environ={}, free_gb=SHORT)
    ib.stamp_vision_mode(report, plan, 4)
    batch = TMP / "batch"
    batch.mkdir(parents=True, exist_ok=True)
    dest = ib.write_report(batch, report)
    doc = json.load(open(dest))
    assert doc["vision_mode"] == "shared", doc
    assert doc["vision_mode_reason"].startswith("low_memory"), doc
    assert doc["index_workers"] == 4, doc
    assert "sockets" not in doc, doc          # additive: only the three fields
    assert doc["batch"] == "b" and doc["fetched"] == [], doc


def test_main_stamps_the_mode_before_writing_01b():
    src = (SCRIPTS / "ingest_batch.py").read_text()
    body = src[src.index("def main():"):]
    plan_at = body.index("vision = vision_plan(workers, args.vision_per_worker)")
    stamp_at = body.index("stamp_vision_mode(report, vision, workers)")
    write_at = body.index("dest = write_report(batch, report)")
    assert plan_at < stamp_at < write_at
    assert "add_vision_flags(p)" in body


if __name__ == "__main__":
    failures = ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
