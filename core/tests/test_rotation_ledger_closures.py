#!/usr/bin/env python3
"""CF-0776: a standing ledger row is closed by a record beside the ledger.

16.10, the re-run of ExampleTech 2026-10-16T0839Z from the Researcher: -005
and -013 stood on `demo` rows whose writer's rejection had been *denied* under
the rule before CF-0775 (seq 9, 10). `assign` is idempotent per (batch,
script), so the re-run got `demo` back and both topics left again as
pattern_undeliverable; a filled `rejection_verdict` cannot be ruled again.
The answer: `<channel>.closures.jsonl` - the CSV is not rewritten, the closed
row stops standing, and the next `assign` draws the script under today's rule.

Offline: the channel config is the repository's, the batch files and the
ledger are stand-ins in a tmp directory shaped like 0839Z's (the stand-ins of
`tests/test_rotation_material.py`).

Run: python3 tests/test_rotation_ledger_closures.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "rotation"))
import test_rotation_material as trm  # noqa: E402
from ledger import (Ledger, LedgerError, closures_path, ledger_path,  # noqa: E402
                    validate)

BATCH, CHANNEL, sid = trm.BATCH, trm.CHANNEL, trm.sid
DENIED = ("no own capture: proof_quotes_only (4 vendor proof quotes, no recording, no "
          "api_demo_record) - demo/even has no base footage")


class Closures(trm.Scratch):
    def standing_demo(self, n, rhythm="even"):
        row = self.append(n, "demo", rhythm)
        return self.ledger().enrich(row["seq"], rejection_reason=DENIED,
                                    rejection_verdict="denied")

    def test_a_closure_is_a_record_beside_the_ledger_and_the_row_stops_standing(self):
        led = self.ledger()
        row = self.standing_demo(5)
        csv_before = led.path.read_bytes()
        rec = led.close(row["seq"], "user", "CF-0776", "rerun-from content-researcher",
                        at="2026-10-16T17:00:00Z", via="telegram")
        self.assertEqual(led.path.read_bytes(), csv_before)          # the CSV is not touched
        lines = closures_path(led.path).read_text().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0]), rec)
        self.assertEqual(closures_path(led.path).name, f"{CHANNEL}.closures.jsonl")
        self.assertEqual((rec["seq"], rec["batch_id"], rec["script_id"], rec["pattern_id"],
                          rec["via"]), (int(row["seq"]), BATCH, sid(5), "demo", "telegram"))
        self.assertIsNone(led.standing_row_for(sid(5), batch_id=BATCH))
        self.assertEqual(led.standing_rows(), [])
        self.assertEqual(validate(led.path), [])
        # the script may be assigned again in its batch: one standing row again
        led.append(channel=CHANNEL, batch_id=BATCH, script_id=sid(5), pattern_id="list",
                   rhythm_id="hold", assigned_by="rotation")
        self.assertEqual(led.standing_row_for(sid(5), batch_id=BATCH)["pattern_id"], "list")
        self.assertEqual(validate(led.path), [])

    def test_what_cannot_be_closed(self):
        led = self.ledger()
        row = self.standing_demo(5)
        for args in ((row["seq"], "", "CF-0776", "why"), (row["seq"], "user", "CF-0776", " ")):
            with self.assertRaises(LedgerError):
                led.close(*args)
        with self.assertRaises(LedgerError):
            led.close(99, "user", "CF-0776", "no such row")
        led.close(row["seq"], "user", "CF-0776", "first")
        with self.assertRaisesRegex(LedgerError, "already closed"):
            led.close(row["seq"], "user", "CF-0776", "second")
        made = self.append(8, "explainer", "alternate")
        led.enrich(made["seq"], produced_at="2026-10-16T17:26:51Z", video_path="v.mp4")
        with self.assertRaisesRegex(LedgerError, "video was made"):
            led.close(made["seq"], "user", "CF-0776", "a produced row")
        gone = self.append(4, "demo", "even")
        led.enrich(gone["seq"], rejection_reason=DENIED, rejection_verdict="upheld",
                   rejected_at="2026-10-16T10:22:16Z")
        with self.assertRaisesRegex(LedgerError, "rejected"):
            led.close(gone["seq"], "user", "CF-0776", "a rejected row")
        self.assertEqual(len(closures_path(led.path).read_text().splitlines()), 1)

    def test_a_closed_row_takes_no_production(self):
        led = self.ledger()
        row = self.standing_demo(13, "hold")
        led.close(row["seq"], "user", "CF-0776", "rerun")
        with self.assertRaisesRegex(LedgerError, "closed"):
            led.enrich(row["seq"], produced_at="2026-10-16T17:26:51Z")
        led.enrich(row["seq"], rejection_reason=DENIED)              # same value: no change

    def test_validate_reads_the_closures(self):
        led = self.ledger()
        row = self.standing_demo(5)
        path = closures_path(led.path)
        good = {"seq": int(row["seq"]), "closed_at": "t", "batch_id": BATCH,
                "script_id": sid(5), "by": "user", "task": "CF-0776", "why": "rerun"}
        path.write_text("\n".join(json.dumps(r) for r in (
            good, good, dict(good, seq=42), dict(good, seq=int(row["seq"]),
                                                  batch_id="other"))) + "\n")
        errs = "\n".join(validate(led.path))
        self.assertIn("closed twice", errs)
        self.assertIn("no such row", errs)
        self.assertIn("record names batch_id", errs)
        path.write_text("not json\n")
        self.assertIn("not JSON", "\n".join(validate(led.path)))

    def test_0839z_the_closed_demo_row_is_drawn_again_without_demo(self):
        """seq 9, 10 of 0839Z: standing `demo` rows with a denied rejection.
        Before the closure the re-run's `assign` hands `demo` back; after it,
        the draw runs under CF-0775 and leaves `demo` out."""
        self.standing_demo(5, "even")
        self.standing_demo(13, "hold")
        again = {a["script_id"]: a for a in self.assign(5, 13)}
        self.assertEqual({a["pattern_id"] for a in again.values()}, {"demo"})
        self.assertFalse(any(a["reassigned"] for a in again.values()))
        led = self.ledger()
        for a in again.values():
            led.close(a["seq"], "user", "CF-0776", "rerun-from content-researcher")
        drawn = {a["script_id"]: a for a in self.assign(5, 13)}
        for n in (5, 13):
            a = drawn[sid(n)]
            self.assertTrue(a["reassigned"], a)
            self.assertNotEqual(a["pattern_id"], "demo", a)
            self.assertIn("demo", a["material_excluded"], a)
        self.assertEqual(validate(led.path), [])
        # and the assignment is idempotent again from here
        self.assertEqual({a["seq"] for a in self.assign(5, 13)},
                         {a["seq"] for a in drawn.values()})


def test_closures():
    trm._run(Closures)


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
