"""The score model as it stood before 2026-10-01, for the checks of mechanics.

N 60, E from 60, `score.judge_neutral` 1 per block with a cap of 8, and the
30.09 prices of frozen_block / repeated_shot / crop_cuts_subject - the
numbers the arithmetic checks (tiers, the hook multiplier, the CLI, the judge's
line, the stages, the frame-judge gate) were written against. On 2026-10-01
the user moved neutral to 0 and N to 40 (CF-0462); a check of *how* the model
counts must not move when a price moves, so it runs on this pinned copy of the
live table. Checks of the live signed table read shared/gate-prices.json
directly.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIVE = ROOT / "shared" / "gate-prices.json"

PINNED_THRESHOLD = 60
PINNED_TIERS = {"S": 92, "A": 85, "B": 78, "C": 71, "D": 65, "E": 60}
PINNED_NEUTRAL = {"price": 1, "cap": 8}
# Repriced by the user on 2026-10-01 (CF-0469, «подписываю») so that each defect
# he refused a video for takes a clean video under N 40; the mechanics checks
# were written against the 30.09 prices.
PINNED_PENALTIES = {
    "score.frozen_block": {"price": 20, "per": "block", "cap": None, "hook_mult": 2},
    "score.repeated_shot": {"price": 5, "per": "repeat", "cap": 20, "hook_mult": 2},
    "score.crop_cuts_subject": {"price": 41, "per": "case", "cap": None, "hook_mult": None},
}


def pinned_table(**score_over):
    """The live table with the pre-2026-10-01 threshold, tiers and neutral
    price; `score_over` overrides keys of its `score` block."""
    d = json.loads(LIVE.read_text(encoding="utf-8"))
    d["score"]["threshold"] = PINNED_THRESHOLD
    d["score"]["tiers"] = dict(PINNED_TIERS)
    d["rules"]["score.judge_neutral"]["penalty"].update(PINNED_NEUTRAL)
    for name, pen in PINNED_PENALTIES.items():
        d["rules"][name]["penalty"] = dict(pen)
    # Signed by the user on 2026-10-27 (CF-0877, «да, подписываю»): a person
    # mismatch is charged score.judge_wrong_person (-25, x2 in the hook) in
    # place of score.judge_contradicts. The mechanics checks were written
    # against every `contradicts` costing judge_contradicts, so the pinned
    # table keeps the row in `proposals`, unsigned - as it stood before.
    wp = d["rules"].pop("score.judge_wrong_person", None)
    if wp is not None:
        wp = {k: v for k, v in wp.items() if k != "task"}
        wp["signature"] = None
        d["proposals"]["rows"]["score.judge_wrong_person"] = wp
    for k, v in score_over.items():
        d["score"][k] = v
    return d


def pinned_ledger_file(directory):
    """The pinned table written to `directory`, for a script that takes
    `--ledger PATH`."""
    p = Path(directory) / "pinned-gate-prices.json"
    p.write_text(json.dumps(pinned_table(), ensure_ascii=False), encoding="utf-8")
    return p
