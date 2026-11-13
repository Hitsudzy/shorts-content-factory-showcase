"""CF-0467: the score model as it stood before 2026-10-01, for the checks of
mechanics - the editor's copy of the root's `tests/_pinned_prices.py`.

N 60, E from 60, `score.judge_neutral` 1 per block with a cap of 8 - the
numbers the score-log and early-stop checks (the line, the tiers, the stop
under N, 05's record) were written against. On 2026-10-01 the user moved
neutral to 0 and N to 40 (CF-0462); a check of *how* the log counts must not
move when a price moves, so it runs on this pinned copy of the live table
(every other price and rule as the root has it). Checks of the live signed
table read the root's shared/gate-prices.json directly.

Two ways in, matching how the score model is reached:

- in this process: `with pinned():` points the loaded root module's
  `LEDGER` at the pinned file, so every `load_model(None)` - `score_log.build`,
  `summary_line`, write_batch_metadata's `record_fields` - reads it;
- in a child script: the `root` that `pinned()` yields is a synthetic factory
  root (the real score module, the pinned table, the real patterns/inserts/
  channels) for `FACTORY_ROOT`, the same mechanism `_strict_root` uses.
"""
import contextlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import _score  # noqa: E402

PINNED_THRESHOLD = 60
PINNED_TIERS = {"S": 92, "A": 85, "B": 78, "C": 71, "D": 65, "E": 60}
PINNED_NEUTRAL = {"price": 1, "cap": 8}
# CF-0469 (the user, 2026-10-01): repriced in the root table; mechanics run on 30.09.
PINNED_PENALTIES = {
    "score.frozen_block": {"price": 20, "per": "block", "cap": None, "hook_mult": 2},
    "score.repeated_shot": {"price": 5, "per": "repeat", "cap": 20, "hook_mult": 2},
    "score.crop_cuts_subject": {"price": 41, "per": "case", "cap": None, "hook_mult": None},
}


def live_path():
    """The root's live price table, or None when the root is not reachable."""
    root = _score.factory_root()
    return root / "shared" / "gate-prices.json" if root else None


def live_table():
    return json.loads(live_path().read_text(encoding="utf-8"))


def pinned_table(**score_over):
    """The live table with the pre-2026-10-01 threshold, tiers and neutral
    price; `score_over` overrides keys of its `score` block."""
    d = live_table()
    d["score"]["threshold"] = PINNED_THRESHOLD
    d["score"]["tiers"] = dict(PINNED_TIERS)
    d["rules"]["score.judge_neutral"]["penalty"].update(PINNED_NEUTRAL)
    for name, pen in PINNED_PENALTIES.items():
        d["rules"][name]["penalty"] = dict(pen)
    for k, v in score_over.items():
        d["score"][k] = v
    return d


def synthetic_root(directory, table):
    """A factory root under `directory` holding the real score module and
    `table` as its price table; everything else the stages read off the root
    (patterns, inserts, channels) is the real one, symlinked."""
    real = _score.factory_root()
    root = Path(directory) / "root"
    (root / "shared" / "score").mkdir(parents=True)
    for name in ("score.py", "__init__.py"):
        shutil.copy(real / "shared" / "score" / name, root / "shared" / "score" / name)
    (root / "shared" / "gate-prices.json").write_text(
        json.dumps(table, ensure_ascii=False), encoding="utf-8")
    for name in ("patterns", "inserts", "channels"):
        if (real / name).exists():
            (root / name).symlink_to(real / name)
    return root


@contextlib.contextmanager
def pinned(**score_over):
    """Run the block on the pinned table: in process (the root module's
    `LEDGER`) and, through the yielded root, in child scripts
    (`env={"FACTORY_ROOT": str(root)}`)."""
    mod = _score.module()
    with tempfile.TemporaryDirectory(prefix="cf0467-pinned-") as tmp:
        root = synthetic_root(tmp, pinned_table(**score_over))
        real = mod.LEDGER
        mod.LEDGER = root / "shared" / "gate-prices.json"
        try:
            yield root
        finally:
            mod.LEDGER = real
